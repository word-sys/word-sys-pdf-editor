try:
    import pymupdf as fitz
except ImportError:
    import fitz
import numpy as np
import cairo
import copy
import io
import os
from pathlib import Path
import math
import subprocess
import shutil
import tempfile
import traceback
import re
import uuid
import json
import hashlib
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:
    AESGCM = None
    HAS_CRYPTOGRAPHY = False

WSPDF_MAGIC = b"WSPDF01"
WSPDF_SALT_LEN = 16
WSPDF_NONCE_LEN = 12
WSPDF_TAG_LEN = 16
WSPDF_PBKDF2_ROUNDS = 100_000
import collections
import zlib
import gc
import queue
import itertools
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any, Tuple, Union, Set, Callable
try:
    import anyconvert
    from anyconvert import ConversionMode
    HAS_ANYCONVERT = True
except ImportError:
    anyconvert = None
    ConversionMode = None
    HAS_ANYCONVERT = False
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, Gdk, Pango, PangoCairo, GLib
from .models import (
    EditableText, FLAG_BOLD, FLAG_ITALIC, EditableImage, EditableShape, EditableStroke,
    AcroFormField, decompose_font_name, extract_font_properties, get_base14_font_variant,
    MeasurementObject, StickyNoteObject
)
from .utils import find_specific_font_variant, get_default_unicode_font_path, normalize_color
from .i18n import _

class BoundedLRUCache(dict):
    """LRU Cache bounded by maximum item count and maximum total memory byte ceiling."""
    def __init__(self, max_items: int = 6, max_bytes: int = 120 * 1024 * 1024):
        super().__init__()
        self._lock = threading.RLock()
        self.max_items = int(max_items)
        self.max_bytes = int(max_bytes)
        self.current_bytes = 0
        self._item_sizes = {}

    def _estimate_size(self, value) -> int:
        if value is None:
            return 0
        if hasattr(value, "get_stride") and hasattr(value, "get_height"):
            return int(value.get_stride() * value.get_height())
        if hasattr(value, "size"):
            return int(getattr(value, "size", 0))
        if hasattr(value, "samples"):
            return len(value.samples)
        if isinstance(value, (bytes, bytearray, memoryview)):
            return len(value)
        return 1024

    def __getitem__(self, key):
        with self._lock:
            val = super().__getitem__(key)
            super().__delitem__(key)
            super().__setitem__(key, val)
            return val

    def get(self, key, default=None):
        with self._lock:
            if key in self:
                return self[key]
            return default

    def __setitem__(self, key, value):
        with self._lock:
            new_size = self._estimate_size(value)
            if key in self:
                old_size = self._item_sizes.get(key, 0)
                self.current_bytes -= old_size
                super().__delitem__(key)
            super().__setitem__(key, value)
            self._item_sizes[key] = new_size
            self.current_bytes += new_size
            self._evict_as_needed()

    def _evict_as_needed(self):
        with self._lock:
            while len(self) > 1 and (len(self) > self.max_items or self.current_bytes > self.max_bytes):
                oldest_key = next(iter(self))
                self.pop(oldest_key, None)

    def set_limits(self, max_items: int, max_bytes: int):
        """Update cache item count and memory byte limits dynamically, evicting excess items."""
        with self._lock:
            self.max_items = max(1, int(max_items))
            self.max_bytes = max(1024 * 1024, int(max_bytes))
            self._evict_as_needed()

    def pop(self, key, *args):
        with self._lock:
            if key in self:
                size = self._item_sizes.pop(key, 0)
                self.current_bytes = max(0, self.current_bytes - size)
                val = super().__getitem__(key)
                super().__delitem__(key)
                return val
            if args:
                return args[0]
            raise KeyError(key)

    def __delitem__(self, key):
        with self._lock:
            self.pop(key)

    def clear(self):
        with self._lock:
            self._item_sizes.clear()
            self.current_bytes = 0
            super().clear()

    def set_budget(self, max_items: Optional[int] = None, max_bytes: Optional[int] = None):
        """Update cache boundaries dynamically."""
        with self._lock:
            if max_items is not None:
                self.max_items = max(1, int(max_items))
            if max_bytes is not None:
                self.max_bytes = max(1024 * 1024, int(max_bytes))
            self._evict_as_needed()

    def __contains__(self, key):
        with self._lock:
            return super().__contains__(key)


class CompressedSnapshotStore(dict):
    """In-memory zlib-compressed snapshot storage for PDF page content streams."""
    _MAGIC = b"ZL\x01"

    def __setitem__(self, key, value):
        if isinstance(value, (bytes, bytearray, memoryview)):
            val_bytes = bytes(value)
            if not val_bytes.startswith(self._MAGIC):
                compressed = self._MAGIC + zlib.compress(val_bytes, level=6)
                super().__setitem__(key, compressed)
                return
        super().__setitem__(key, value)

    def __getitem__(self, key):
        val = super().__getitem__(key)
        if isinstance(val, bytes) and val.startswith(self._MAGIC):
            return zlib.decompress(val[len(self._MAGIC):])
        return val

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default

    def pop(self, key, *args):
        if key in self:
            val = super().pop(key)
            if isinstance(val, bytes) and val.startswith(self._MAGIC):
                return zlib.decompress(val[len(self._MAGIC):])
            return val
        if args:
            return args[0]
        raise KeyError(key)

    def raw_items(self):
        return super().items()

    def items(self):
        for k in list(self.keys()):
            yield k, self[k]

    def values(self):
        for k in list(self.keys()):
            yield self[k]

    def raw_byte_size(self) -> int:
        return sum(len(v) for v in super().values() if isinstance(v, (bytes, bytearray)))


_cairo_page_cache = BoundedLRUCache(max_items=6, max_bytes=120 * 1024 * 1024)
_stale_page_cache: Dict[Tuple[int, int], Tuple[cairo.ImageSurface, float]] = {}
_stale_page_cache_lock = threading.Lock()
_page_rasterizer_pool = None
_tiled_page_renderer = None

def configure_memory_limits(is_eco_mode: bool):
    """Dynamically adjust internal page cache budget based on Eco / Low-Spec mode."""
    global _cairo_page_cache, _page_rasterizer_pool, _tiled_page_renderer
    if is_eco_mode:
        _cairo_page_cache.set_limits(max_items=3, max_bytes=40 * 1024 * 1024)
        if _tiled_page_renderer is not None:
            _tiled_page_renderer._tile_cache.set_limits(max_items=32, max_bytes=40 * 1024 * 1024)
    else:
        _cairo_page_cache.set_limits(max_items=6, max_bytes=120 * 1024 * 1024)
        if _tiled_page_renderer is not None:
            _tiled_page_renderer._tile_cache.set_limits(max_items=64, max_bytes=80 * 1024 * 1024)
    if _page_rasterizer_pool is not None:
        _page_rasterizer_pool.set_eco_mode(is_eco_mode)

def invalidate_page_cache(doc=None, page_index=None):
    """Invalidate cached Cairo page surfaces and internal document page cache."""
    global _cairo_page_cache, _stale_page_cache, _page_rasterizer_pool, _tiled_page_renderer
    if _page_rasterizer_pool is not None:
        if doc is None:
            _page_rasterizer_pool.bump_generation()
            _page_rasterizer_pool.cancel_all()
        else:
            _page_rasterizer_pool.bump_generation(id(doc))
            _page_rasterizer_pool.cancel_all(doc)
    if _tiled_page_renderer is not None:
        _tiled_page_renderer.invalidate_doc_tiles(doc, page_index)
    if doc is None:
        _cairo_page_cache.clear()
        with _stale_page_cache_lock:
            _stale_page_cache.clear()
        return
    if hasattr(doc, '_page_cache') and isinstance(doc._page_cache, dict):
        if page_index is None:
            doc._page_cache.clear()
        else:
            doc._page_cache.pop(page_index, None)
    doc_id = id(doc)
    with getattr(_cairo_page_cache, '_lock', threading.Lock()):
        if page_index is None:
            keys_to_del = [k for k in list(_cairo_page_cache.keys()) if k[0] == doc_id]
        else:
            keys_to_del = [k for k in list(_cairo_page_cache.keys()) if k[0] == doc_id and k[1] == page_index]
        for k in keys_to_del:
            surf = _cairo_page_cache.pop(k, None)
            if surf is not None and getattr(surf, 'get_width', lambda: 0)() > 0:
                with _stale_page_cache_lock:
                    _stale_page_cache[(k[0], k[1])] = (surf, float(k[2]))

def rotate_point(x, y, cx, cy, angle_degrees):
    """Rotate point (x, y) around pivot (cx, cy) by angle_degrees clockwise."""
    if angle_degrees == 0:
        return x, y
    rad = math.radians(angle_degrees)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    nx = cx + (x - cx) * cos_a - (y - cy) * sin_a
    ny = cy + (x - cx) * sin_a + (y - cy) * cos_a
    return nx, ny

def get_rotation_matrix(cx, cy, angle_degrees):
    """Return fitz.Matrix rotating around (cx, cy) by angle_degrees."""
    t1 = fitz.Matrix(1, 0, 0, 1, -cx, -cy)
    rot = fitz.Matrix(angle_degrees)
    t2 = fitz.Matrix(1, 0, 0, 1, cx, cy)
    return t1 * rot * t2

def transform_point_page_rot(x: float, y: float, w: float, h: float, angle_delta: int):
    """Transform a point (x, y) on a page of dimensions (w, h) when rotated by angle_delta degrees."""
    delta = angle_delta % 360
    if delta == 90:
        return h - y, x
    elif delta == 180:
        return w - x, h - y
    elif delta == 270:
        return y, w - x
    return x, y

def transform_bbox_page_rot(bbox, w: float, h: float, angle_delta: int):
    """Transform bounding box (x1, y1, x2, y2) on a page of dimensions (w, h) when rotated by angle_delta degrees."""
    if not bbox:
        return bbox
    x1, y1, x2, y2 = bbox
    delta = angle_delta % 360
    if delta == 90:
        return (h - y2, x1, h - y1, x2)
    elif delta == 180:
        return (w - x2, h - y2, w - x1, h - y1)
    elif delta == 270:
        return (y1, w - x2, y2, w - x1)
    return (x1, y1, x2, y2)

def pixmap_to_cairo_surface(pix):
    """Convert PyMuPDF Pixmap directly to Cairo ImageSurface via direct memory transfer into Cairo-allocated buffer."""
    if pix is None or pix.width <= 0 or pix.height <= 0:
        return None, None

    try:
        samples_buf = pix.samples_mv if hasattr(pix, 'samples_mv') else pix.samples
        w, h, n, stride = pix.width, pix.height, pix.n, pix.stride
        raw_arr = np.frombuffer(samples_buf, dtype=np.uint8)

        if stride != w * n:
            raw_arr = raw_arr.reshape((h, stride))[:, :w * n].reshape((h, w, n))
        elif n > 1:
            raw_arr = raw_arr.reshape((h, w, n))
        else:
            raw_arr = raw_arr.reshape((h, w))

        fmt = cairo.FORMAT_ARGB32 if pix.alpha else cairo.FORMAT_RGB24
        surface = cairo.ImageSurface(fmt, w, h)
        buf = surface.get_data()
        cairo_stride = surface.get_stride()
        dest_arr = np.frombuffer(buf, dtype=np.uint8)
        if cairo_stride == w * 4:
            dest_bgra = dest_arr.reshape((h, w, 4))
        else:
            dest_bgra = dest_arr.reshape((h, cairo_stride))[:, :w * 4].reshape((h, w, 4))

        if pix.alpha:
            if n == 4:
                # RGBA -> BGRA (PyMuPDF already premultiplies alpha)
                dest_bgra[..., 0] = raw_arr[..., 2] # Blue
                dest_bgra[..., 1] = raw_arr[..., 1] # Green
                dest_bgra[..., 2] = raw_arr[..., 0] # Red
                dest_bgra[..., 3] = raw_arr[..., 3] # Alpha
            elif n == 2:
                # Gray + Alpha -> BGRA
                gray = raw_arr[..., 0]
                dest_bgra[..., 0] = gray
                dest_bgra[..., 1] = gray
                dest_bgra[..., 2] = gray
                dest_bgra[..., 3] = raw_arr[..., 1] # Alpha
            else:
                return None, None
        else:
            if n == 3:
                # RGB -> BGRX
                dest_bgra[..., 0] = raw_arr[..., 2] # Blue
                dest_bgra[..., 1] = raw_arr[..., 1] # Green
                dest_bgra[..., 2] = raw_arr[..., 0] # Red
                dest_bgra[..., 3] = 255            # X/Padding
            elif n == 1:
                # Gray -> BGRX
                gray = raw_arr if raw_arr.ndim == 2 else raw_arr[..., 0]
                dest_bgra[..., 0] = gray
                dest_bgra[..., 1] = gray
                dest_bgra[..., 2] = gray
                dest_bgra[..., 3] = 255            # X/Padding
            else:
                return None, None

        surface.mark_dirty()
        return surface, buf

    except Exception as e:
        print(f"Error creating Cairo surface from pixmap: {e}")
        return None, None

def get_page_cairo_surface(doc, page_index, zoom_level, clip_rect=None):
    """Get or render cached Cairo ImageSurface for the given page and zoom level via direct pixel transfer."""
    global _cairo_page_cache
    if not doc or getattr(doc, 'is_closed', False) or not (0 <= page_index < doc.page_count):
        return None

    # Sub-rectangle clip renders are not cached in _cairo_page_cache
    if clip_rect is not None:
        try:
            lock = get_doc_lock(doc)
            if lock:
                with lock:
                    page = doc.load_page(page_index)
                    zoom_matrix = fitz.Matrix(zoom_level, zoom_level)
                    pix = page.get_pixmap(matrix=zoom_matrix, clip=clip_rect, alpha=False)
            else:
                page = doc.load_page(page_index)
                zoom_matrix = fitz.Matrix(zoom_level, zoom_level)
                pix = page.get_pixmap(matrix=zoom_matrix, clip=clip_rect, alpha=False)
            surf, _ = pixmap_to_cairo_surface(pix)
            return surf
        except Exception as e:
            print(f"Error creating clipped surface for page {page_index}: {e}")
            return None

    cache_key = (id(doc), page_index, round(float(zoom_level), 4))
    if cache_key in _cairo_page_cache:
        return _cairo_page_cache[cache_key]

    try:
        lock = get_doc_lock(doc)
        if lock:
            with lock:
                page = doc.load_page(page_index)
                zoom_matrix = fitz.Matrix(zoom_level, zoom_level)
                pix = page.get_pixmap(matrix=zoom_matrix, alpha=False)
        else:
            page = doc.load_page(page_index)
            zoom_matrix = fitz.Matrix(zoom_level, zoom_level)
            pix = page.get_pixmap(matrix=zoom_matrix, alpha=False)

        surf, _ = pixmap_to_cairo_surface(pix)
        if surf is None:
            return None

        _cairo_page_cache[cache_key] = surf
        with _stale_page_cache_lock:
            _stale_page_cache.pop((id(doc), page_index), None)
        return surf
    except Exception as e:
        print(f"Error creating cached page surface for page {page_index}: {e}")
        return None

def update_page_cairo_surface_rect(doc, page_index, zoom_level, rect):
    """Update a sub-rectangle region of the cached Cairo ImageSurface in-place.
    rect is (x0, y0, x1, y1) in unscaled PDF points.
    """
    global _cairo_page_cache
    if not doc or getattr(doc, 'is_closed', False) or not (0 <= page_index < doc.page_count):
        return False

    cache_key = (id(doc), page_index, round(float(zoom_level), 4))
    if cache_key not in _cairo_page_cache:
        return False

    cached_surf = _cairo_page_cache[cache_key]
    try:
        x0, y0, x1, y1 = rect
        clip_rect = fitz.Rect(max(0.0, x0 - 1.0), max(0.0, y0 - 1.0), x1 + 1.0, y1 + 1.0)
        lock = get_doc_lock(doc)
        if lock:
            with lock:
                page = doc.load_page(page_index)
                zoom_matrix = fitz.Matrix(zoom_level, zoom_level)
                clip_pix = page.get_pixmap(matrix=zoom_matrix, clip=clip_rect, alpha=False)
        else:
            page = doc.load_page(page_index)
            zoom_matrix = fitz.Matrix(zoom_level, zoom_level)
            clip_pix = page.get_pixmap(matrix=zoom_matrix, clip=clip_rect, alpha=False)

        clip_surf, _ = pixmap_to_cairo_surface(clip_pix)
        if clip_surf is None:
            return False

        cr = cairo.Context(cached_surf)
        dest_x = clip_rect.x0 * zoom_level
        dest_y = clip_rect.y0 * zoom_level
        cr.set_source_surface(clip_surf, dest_x, dest_y)
        cr.paint()
        return True
    except Exception as e:
        print(f"Error updating cached sub-rectangle for page {page_index}: {e}")
        return False

class PageRasterizerPool:
    """Dedicated worker pool for asynchronous background Cairo page surface rendering."""

    def __init__(self, max_workers: int = 2):
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="page-rasterizer")
        try:
            barrier = threading.Barrier(max_workers + 1)
            for _ in range(max_workers):
                self._executor.submit(barrier.wait)
            barrier.wait(timeout=1.0)
        except Exception:
            pass
        self._lock = threading.RLock()
        self._pending_callbacks: Dict[Tuple[int, int, float], List[Any]] = {}
        self._doc_generations: Dict[int, int] = {}
        self._active_futures: Dict[Tuple[int, int, float], Any] = {}
        self._latest_requested_zoom: Dict[Tuple[int, int], float] = {}
        self._is_eco_mode: bool = False

    def set_eco_mode(self, is_eco: bool):
        with self._lock:
            self._is_eco_mode = bool(is_eco)

    def get_generation(self, doc_id: int) -> int:
        with self._lock:
            return self._doc_generations.get(doc_id, 0)

    def bump_generation(self, doc_id: Optional[int] = None):
        with self._lock:
            if doc_id is None:
                for k in list(self._doc_generations.keys()):
                    self._doc_generations[k] += 1
                self._pending_callbacks.clear()
            else:
                self._doc_generations[doc_id] = self._doc_generations.get(doc_id, 0) + 1
                keys_to_del = [k for k in self._pending_callbacks if k[0] == doc_id]
                for k in keys_to_del:
                    self._pending_callbacks.pop(k, None)

    def peek_surface(self, doc, page_index: int, zoom_level: float) -> Optional[cairo.ImageSurface]:
        """Return cached surface if immediately available in LRU cache, otherwise None."""
        if not doc or getattr(doc, 'is_closed', False) or not hasattr(doc, 'page_count') or not (0 <= page_index < doc.page_count):
            return None
        cache_key = (id(doc), page_index, round(float(zoom_level), 4))
        global _cairo_page_cache
        if cache_key in _cairo_page_cache:
            surf = _cairo_page_cache.get(cache_key)
            if (
                surf is not None
                and getattr(surf, 'get_width', lambda: 0)() > 0
                and getattr(surf, 'get_height', lambda: 0)() > 0
            ):
                return surf
        return None

    def find_best_cached_surface(self, doc, page_index: int, target_zoom: float = 1.0) -> Optional[Tuple[cairo.ImageSurface, float]]:
        """Find an already-rendered Cairo surface for the given page at any zoom level, prioritizing closest zoom."""
        if not doc or getattr(doc, 'is_closed', False) or not hasattr(doc, 'page_count') or not (0 <= page_index < doc.page_count):
            return None
        doc_id = id(doc)
        global _cairo_page_cache
        candidates = []
        with getattr(_cairo_page_cache, '_lock', threading.Lock()):
            for k in list(_cairo_page_cache.keys()):
                if k[0] == doc_id and k[1] == page_index:
                    surf = _cairo_page_cache.get(k)
                    if (
                        surf is not None
                        and getattr(surf, 'get_width', lambda: 0)() > 0
                        and getattr(surf, 'get_height', lambda: 0)() > 0
                    ):
                        candidates.append((surf, float(k[2])))

        if not candidates:
            with _stale_page_cache_lock:
                stale = _stale_page_cache.get((doc_id, page_index))
                if (
                    stale is not None
                    and stale[0] is not None
                    and getattr(stale[0], 'get_width', lambda: 0)() > 0
                    and getattr(stale[0], 'get_height', lambda: 0)() > 0
                ):
                    return stale
            return None

        best_surf, best_zoom = min(candidates, key=lambda item: abs(item[1] - target_zoom))
        return best_surf, best_zoom

    def request_surface(self, doc, page_index: int, zoom_level: float, callback: Optional[Any] = None, defer: bool = True, progressive: bool = False):
        """Submit background rasterization request.
        
        If progressive=True and no cached surface exists for this page at any zoom level,
        dispatches a fast low-res preview (50 DPI) first, then refines to target zoom_level.
        Dispatches callback(page_index, zoom_level, surf) via GLib.idle_add upon completion.
        """
        if not doc or getattr(doc, 'is_closed', False) or not hasattr(doc, 'page_count') or not (0 <= page_index < doc.page_count):
            return

        doc_id = id(doc)
        zoom_rounded = round(float(zoom_level), 4)
        task_key = (doc_id, page_index, zoom_rounded)

        # Check if already in cache
        cached = self.peek_surface(doc, page_index, zoom_level)
        if cached is not None:
            if callback:
                def _dispatch_cached():
                    try:
                        callback(page_index, zoom_rounded, cached)
                    except Exception:
                        pass
                    return False
                GLib.idle_add(_dispatch_cached)
            return

        # Progressive LOD: if no surface at any zoom exists in cache and target is higher than 50 DPI,
        # request 50 DPI preview first for instant visual feedback (<5ms)
        preview_zoom = round(50.0 / 72.0, 4)
        if progressive and zoom_rounded > preview_zoom * 1.25:
            best_cached = self.find_best_cached_surface(doc, page_index, zoom_level)
            if best_cached is None:
                self.request_surface(doc, page_index, preview_zoom, callback=callback, defer=defer, progressive=False)

        with self._lock:
            self._latest_requested_zoom[(doc_id, page_index)] = zoom_rounded
            gen = self._doc_generations.get(doc_id, 0)
            if task_key in self._pending_callbacks:
                if callback:
                    self._pending_callbacks[task_key].append(callback)
                return

            self._pending_callbacks[task_key] = [callback] if callback else []

        def _render_worker(d, p_idx, z_val, t_key, expected_gen):
            try:
                if getattr(d, 'is_closed', False):
                    return
                surf = get_page_cairo_surface(d, p_idx, z_val)
            except Exception:
                surf = None

            with self._lock:
                callbacks = self._pending_callbacks.pop(t_key, [])
                self._active_futures.pop(t_key, None)
                cur_gen = self._doc_generations.get(doc_id, 0)
                if cur_gen != expected_gen or getattr(d, 'is_closed', False):
                    return

            if callbacks and surf is not None:
                def _dispatch_all():
                    for cb in callbacks:
                        try:
                            cb(p_idx, z_val, surf)
                        except Exception:
                            pass
                    return False
                GLib.idle_add(_dispatch_all)

        def _do_submit():
            with self._lock:
                if task_key not in self._pending_callbacks:
                    return False
                future = self._executor.submit(_render_worker, doc, page_index, zoom_rounded, task_key, gen)
                self._active_futures[task_key] = future
            return False

        if defer:
            GLib.idle_add(_do_submit)
        else:
            _do_submit()

    def wait_for_surface(self, doc, page_index: int, zoom_level: float, timeout: float = 5.0) -> Optional[cairo.ImageSurface]:
        """Wait synchronously for a requested surface (useful for tests and headless verification)."""
        cached = self.peek_surface(doc, page_index, zoom_level)
        if cached is not None:
            return cached
        event = threading.Event()
        result = [None]
        def _on_ready(p, z, surf):
            result[0] = surf
            event.set()
        self.request_surface(doc, page_index, zoom_level, callback=_on_ready, defer=False, progressive=False)
        event.wait(timeout=timeout)
        return result[0] or self.peek_surface(doc, page_index, zoom_level)

    def cancel_all(self, doc=None):
        """Cancel pending callbacks for document or all documents."""
        with self._lock:
            if doc is None:
                self._pending_callbacks.clear()
                self._active_futures.clear()
            else:
                doc_id = id(doc)
                keys_to_del = [k for k in self._pending_callbacks if k[0] == doc_id]
                for k in keys_to_del:
                    self._pending_callbacks.pop(k, None)
                    fut = self._active_futures.pop(k, None)
                    if fut and not fut.running():
                        fut.cancel()

    def shutdown(self, wait: bool = False):
        self.cancel_all()
        self._executor.shutdown(wait=wait)


def get_page_rasterizer_pool() -> PageRasterizerPool:
    global _page_rasterizer_pool
    if _page_rasterizer_pool is None:
        _page_rasterizer_pool = PageRasterizerPool(max_workers=2)
    return _page_rasterizer_pool

def peek_page_cairo_surface(doc, page_index, zoom_level):
    return get_page_rasterizer_pool().peek_surface(doc, page_index, zoom_level)

def request_page_cairo_surface(doc, page_index, zoom_level, callback=None, defer: bool = True, progressive: bool = False):
    return get_page_rasterizer_pool().request_surface(doc, page_index, zoom_level, callback=callback, defer=defer, progressive=progressive)


class TiledPageRenderer:
    """Sub-viewport tile-based virtualized renderer for huge PDF pages and extreme zoom levels.

    Prevents GPU texture limit overruns and out-of-memory aborts on large pages (A0/A1 blueprints)
    and high zoom levels (400%-1000%) by decomposing pages into 512x512 pixel tiles and only
    rasterizing and retaining in memory the tiles that intersect the visible viewport (+1 tile margin).
    """
    DEFAULT_TILE_SIZE = 512
    TILE_DIMENSION_THRESHOLD = 2500
    TILE_PIXEL_AREA_THRESHOLD = 6_250_000

    def __init__(self, tile_size: int = DEFAULT_TILE_SIZE, max_cached_tiles: int = 64, max_cache_bytes: int = 80 * 1024 * 1024):
        self.tile_size = int(tile_size)
        self._tile_cache = BoundedLRUCache(max_items=max_cached_tiles, max_bytes=max_cache_bytes)
        self._lock = threading.RLock()
        self._pending_callbacks: Dict[Tuple[int, int, float, int, int], List[Callable]] = {}
        self._active_futures: Dict[Tuple[int, int, float, int, int], Any] = {}
        self._doc_generations: Dict[int, int] = {}
        self._executor = None

    def _get_executor(self):
        if self._executor is None:
            pool = get_page_rasterizer_pool()
            if pool and hasattr(pool, '_executor'):
                self._executor = pool._executor
            else:
                self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="TileWorker")
        return self._executor

    def is_tiling_required(self, page_width_pt: float, page_height_pt: float, zoom_level: float) -> bool:
        """Return True if rasterized dimensions exceed safe single-surface texture and memory ceilings."""
        pw_px = float(page_width_pt) * float(zoom_level)
        ph_px = float(page_height_pt) * float(zoom_level)
        return (pw_px > self.TILE_DIMENSION_THRESHOLD or 
                ph_px > self.TILE_DIMENSION_THRESHOLD or 
                (pw_px * ph_px) > self.TILE_PIXEL_AREA_THRESHOLD)

    def get_tile_counts(self, page_width_pt: float, page_height_pt: float, zoom_level: float) -> Tuple[int, int]:
        """Return (num_cols, num_rows) grid dimension for the given page geometry and zoom."""
        pw_px = max(1, int(math.ceil(float(page_width_pt) * float(zoom_level))))
        ph_px = max(1, int(math.ceil(float(page_height_pt) * float(zoom_level))))
        num_cols = max(1, int(math.ceil(pw_px / self.tile_size)))
        num_rows = max(1, int(math.ceil(ph_px / self.tile_size)))
        return num_cols, num_rows

    def get_tile_pixel_rect(self, col: int, row: int, page_width_pt: float, page_height_pt: float, zoom_level: float) -> Tuple[float, float, float, float]:
        """Return (x0, y0, width, height) in page pixel space for tile (col, row)."""
        pw_px = float(page_width_pt) * float(zoom_level)
        ph_px = float(page_height_pt) * float(zoom_level)
        tx0 = float(col * self.tile_size)
        ty0 = float(row * self.tile_size)
        tx1 = min(pw_px, float((col + 1) * self.tile_size))
        ty1 = min(ph_px, float((row + 1) * self.tile_size))
        return (tx0, ty0, max(1.0, tx1 - tx0), max(1.0, ty1 - ty0))

    def get_visible_tile_coords(self, page_canvas_x: float, page_canvas_y: float,
                                page_width_pt: float, page_height_pt: float,
                                zoom_level: float, viewport_rect: Tuple[float, float, float, float],
                                margin_tiles: int = 1) -> List[Tuple[int, int]]:
        """Return list of (col, row) coordinates intersecting visible viewport with buffer margin."""
        scroll_x, scroll_y, vp_w, vp_h = viewport_rect
        pw_px = float(page_width_pt) * float(zoom_level)
        ph_px = float(page_height_pt) * float(zoom_level)
        num_cols, num_rows = self.get_tile_counts(page_width_pt, page_height_pt, zoom_level)

        vis_x0 = max(0.0, scroll_x - page_canvas_x)
        vis_y0 = max(0.0, scroll_y - page_canvas_y)
        vis_x1 = min(pw_px, (scroll_x + vp_w) - page_canvas_x)
        vis_y1 = min(ph_px, (scroll_y + vp_h) - page_canvas_y)

        if vis_x1 <= vis_x0 or vis_y1 <= vis_y0:
            return []

        min_col = max(0, int(math.floor(vis_x0 / self.tile_size)) - margin_tiles)
        max_col = min(num_cols - 1, int(math.floor(vis_x1 / self.tile_size)) + margin_tiles)
        min_row = max(0, int(math.floor(vis_y0 / self.tile_size)) - margin_tiles)
        max_row = min(num_rows - 1, int(math.floor(vis_y1 / self.tile_size)) + margin_tiles)

        tiles = []
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                tiles.append((c, r))
        return tiles

    def peek_tile(self, doc, page_index: int, zoom_level: float, col: int, row: int) -> Optional[cairo.ImageSurface]:
        """Return cached tile Cairo surface if immediately available in LRU cache, otherwise None."""
        if not doc or getattr(doc, 'is_closed', False) or not hasattr(doc, 'page_count') or not (0 <= page_index < doc.page_count):
            return None
        doc_id = id(doc)
        zoom_rounded = round(float(zoom_level), 4)
        tile_key = (doc_id, page_index, zoom_rounded, col, row)
        with self._lock:
            return self._tile_cache.get(tile_key)

    def render_tile(self, doc, page_index: int, zoom_level: float, col: int, row: int) -> Optional[cairo.ImageSurface]:
        """Synchronously render and cache single tile at (col, row)."""
        if not doc or getattr(doc, 'is_closed', False) or not hasattr(doc, 'page_count') or not (0 <= page_index < doc.page_count):
            return None
        doc_id = id(doc)
        zoom_rounded = round(float(zoom_level), 4)
        tile_key = (doc_id, page_index, zoom_rounded, col, row)

        with self._lock:
            cached = self._tile_cache.get(tile_key)
            if cached is not None:
                return cached

        try:
            lock = get_doc_lock(doc)
            if lock:
                with lock:
                    page = doc.load_page(page_index)
                    tx0 = float(col * self.tile_size)
                    ty0 = float(row * self.tile_size)
                    tx1 = min(page.rect.width * zoom_level, float((col + 1) * self.tile_size))
                    ty1 = min(page.rect.height * zoom_level, float((row + 1) * self.tile_size))
                    clip_rect = fitz.Rect(tx0 / zoom_level, ty0 / zoom_level, tx1 / zoom_level, ty1 / zoom_level)
                    zoom_mat = fitz.Matrix(zoom_level, zoom_level)
                    pix = page.get_pixmap(matrix=zoom_mat, clip=clip_rect, alpha=False)
            else:
                page = doc.load_page(page_index)
                tx0 = float(col * self.tile_size)
                ty0 = float(row * self.tile_size)
                tx1 = min(page.rect.width * zoom_level, float((col + 1) * self.tile_size))
                ty1 = min(page.rect.height * zoom_level, float((row + 1) * self.tile_size))
                clip_rect = fitz.Rect(tx0 / zoom_level, ty0 / zoom_level, tx1 / zoom_level, ty1 / zoom_level)
                zoom_mat = fitz.Matrix(zoom_level, zoom_level)
                pix = page.get_pixmap(matrix=zoom_mat, clip=clip_rect, alpha=False)

            surf, _ = pixmap_to_cairo_surface(pix)
            if surf is not None:
                with self._lock:
                    self._tile_cache[tile_key] = surf
                return surf
        except Exception as e:
            print(f"Error rendering tile ({col}, {row}) for page {page_index}: {e}")
            return None

    def request_tile(self, doc, page_index: int, zoom_level: float, col: int, row: int, callback: Optional[Callable] = None, defer: bool = True):
        """Submit background tile rasterization request."""
        if not doc or getattr(doc, 'is_closed', False) or not hasattr(doc, 'page_count') or not (0 <= page_index < doc.page_count):
            return

        doc_id = id(doc)
        zoom_rounded = round(float(zoom_level), 4)
        task_key = (doc_id, page_index, zoom_rounded, col, row)

        cached = self.peek_tile(doc, page_index, zoom_level, col, row)
        if cached is not None:
            if callback:
                def _dispatch_cached():
                    try:
                        callback(col, row, cached)
                    except Exception:
                        pass
                    return False
                GLib.idle_add(_dispatch_cached)
            return

        with self._lock:
            gen = self._doc_generations.get(doc_id, 0)
            if task_key in self._pending_callbacks:
                if callback:
                    self._pending_callbacks[task_key].append(callback)
                return
            self._pending_callbacks[task_key] = [callback] if callback else []

        def _worker(d, p_idx, z_val, c, r, t_key, expected_gen):
            try:
                if getattr(d, 'is_closed', False):
                    return
                surf = self.render_tile(d, p_idx, z_val, c, r)
            except Exception:
                surf = None

            with self._lock:
                cbs = self._pending_callbacks.pop(t_key, [])
                self._active_futures.pop(t_key, None)
                cur_gen = self._doc_generations.get(doc_id, 0)
                if cur_gen != expected_gen or getattr(d, 'is_closed', False):
                    return

            if cbs and surf is not None:
                def _dispatch_all():
                    for cb in cbs:
                        try:
                            cb(c, r, surf)
                        except Exception:
                            pass
                    return False
                GLib.idle_add(_dispatch_all)

        def _do_submit():
            with self._lock:
                if task_key not in self._pending_callbacks:
                    return False
                executor = self._get_executor()
                future = executor.submit(_worker, doc, page_index, zoom_rounded, col, row, task_key, gen)
                self._active_futures[task_key] = future
            return False

        if defer:
            GLib.idle_add(_do_submit)
        else:
            _do_submit()

    def prune_distant_tiles(self, doc, page_index: int, zoom_level: float, active_tiles: Set[Tuple[int, int]]):
        """Evict off-screen tiles exceeding cache retention limits."""
        if not doc:
            return
        doc_id = id(doc)
        zoom_rounded = round(float(zoom_level), 4)
        with self._lock:
            keys_to_remove = []
            for k in list(self._tile_cache.keys()):
                if k[0] == doc_id and k[1] == page_index and abs(k[2] - zoom_rounded) < 0.001:
                    if (k[3], k[4]) not in active_tiles:
                        keys_to_remove.append(k)
            if len(keys_to_remove) > 32:
                for k in keys_to_remove[:-32]:
                    self._tile_cache.pop(k, None)

    def invalidate_doc_tiles(self, doc=None, page_index=None):
        """Invalidate cached tiles and cancel pending background tile rasterizations."""
        with self._lock:
            if doc is None:
                self._tile_cache.clear()
                self._pending_callbacks.clear()
                self._active_futures.clear()
                self._doc_generations.clear()
                return
            doc_id = id(doc)
            self._doc_generations[doc_id] = self._doc_generations.get(doc_id, 0) + 1
            for k in list(self._pending_callbacks.keys()):
                if k[0] == doc_id and (page_index is None or k[1] == page_index):
                    self._pending_callbacks.pop(k, None)
            for k in list(self._active_futures.keys()):
                if k[0] == doc_id and (page_index is None or k[1] == page_index):
                    fut = self._active_futures.pop(k, None)
                    if fut and not fut.running():
                        fut.cancel()
            for k in list(self._tile_cache.keys()):
                if k[0] == doc_id and (page_index is None or k[1] == page_index):
                    self._tile_cache.pop(k, None)


def get_tiled_page_renderer() -> TiledPageRenderer:
    global _tiled_page_renderer
    if _tiled_page_renderer is None:
        _tiled_page_renderer = TiledPageRenderer()
    return _tiled_page_renderer

def _get_font_args_for_pymupdf(text_obj):
    """Get the font args for pymupdf."""
    font_arg = {}
    font_to_embed_path = find_specific_font_variant(
        text_obj.font_family_base,
        text_obj.is_bold,
        text_obj.is_italic
    )

    if font_to_embed_path:
        try:
            test_f = fitz.Font(fontfile=font_to_embed_path)
            non_ascii_chars = [c for c in text_obj.text if ord(c) > 127]
            missing = [c for c in non_ascii_chars if not test_f.has_glyph(ord(c))]
            if missing:
                fb_path = find_specific_font_variant("DejaVu Sans", text_obj.is_bold, text_obj.is_italic)
                if fb_path and fb_path != font_to_embed_path:
                    fb_f = fitz.Font(fontfile=fb_path)
                    if all(fb_f.has_glyph(ord(c)) for c in missing if ord(c) < 0x10000):
                        font_to_embed_path = fb_path
                        print(f"DEBUG (FontHelper): Fallback to DejaVu Sans for symbols: {missing}")
        except Exception as e:
            print(f"DEBUG (FontHelper): Glyph check warning: {e}")

        style_suffix = ""
        if text_obj.is_bold: style_suffix += "Bold"
        if text_obj.is_italic: style_suffix += "Italic"
        if not style_suffix: style_suffix = "Regular"

        safe_family_name = re.sub(r'\W+', '', text_obj.font_family_base or "UnknownFont")
        internal_font_name = f"word-sys_{safe_family_name}_{style_suffix}"
        
        font_arg = {"fontfile": font_to_embed_path, "fontname": internal_font_name}
        print(f"DEBUG (FontHelper): Using TTF: {font_to_embed_path} as '{internal_font_name}'")
        return font_arg, None
    else:
        generic_unicode_font = get_default_unicode_font_path()
        if generic_unicode_font:
            internal_font_name = "word-sysEditFont_GenericUnicode"
            font_arg = {"fontfile": generic_unicode_font, "fontname": internal_font_name}
            print(f"DEBUG (FontHelper): WARNING: Could not find specific TTF. Using generic fallback: {generic_unicode_font}")
            return font_arg, None
        else:
            base14_name = text_obj.pdf_fontname_base14
            if text_obj.is_bold and text_obj.is_italic: base14_name += "bo"
            elif text_obj.is_bold: base14_name += "b"
            elif text_obj.is_italic: base14_name += "i"
            font_arg = {"fontname": base14_name}
            print(f"DEBUG (FontHelper): CRITICAL WARNING: No TTF found. Falling back to Base 14 font: '{base14_name}'.")
            if any(ord(c) > 127 for c in text_obj.text):
                 return None, "Cannot save non-ASCII text: No suitable Unicode font found."
            return font_arg, None

def is_wspdf_file(filepath_or_bytes: Union[str, bytes, Path]) -> bool:
    """Check if given file path or byte buffer is a word-sys Exclusive Vault container."""
    if isinstance(filepath_or_bytes, (str, Path)):
        if not os.path.exists(filepath_or_bytes):
            return False
        try:
            with open(filepath_or_bytes, "rb") as f:
                header = f.read(len(WSPDF_MAGIC))
                return header == WSPDF_MAGIC
        except Exception:
            return False
    elif isinstance(filepath_or_bytes, (bytes, bytearray)):
        return filepath_or_bytes.startswith(WSPDF_MAGIC)
    return False

def encrypt_to_wspdf(pdf_bytes: bytes, password: str) -> bytes:
    """Encrypt raw PDF bytes into a word-sys Exclusive Vault container (.wspdf)."""
    if not HAS_CRYPTOGRAPHY or AESGCM is None:
        raise RuntimeError("Cryptography library is required for word-sys Vault encryption.")
    if not password:
        raise ValueError("Password cannot be empty.")
    
    salt = os.urandom(WSPDF_SALT_LEN)
    nonce = os.urandom(WSPDF_NONCE_LEN)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, WSPDF_PBKDF2_ROUNDS, dklen=32)
    aesgcm = AESGCM(key)
    ciphertext_and_tag = aesgcm.encrypt(nonce, pdf_bytes, associated_data=WSPDF_MAGIC)
    return WSPDF_MAGIC + salt + nonce + ciphertext_and_tag

def decrypt_wspdf(vault_bytes: bytes, password: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Decrypt a word-sys Exclusive Vault container (.wspdf) into raw PDF bytes."""
    if not HAS_CRYPTOGRAPHY or AESGCM is None:
        return None, "Cryptography library is required for word-sys Vault decryption."
    if not vault_bytes.startswith(WSPDF_MAGIC):
        return None, "Invalid file format: missing word-sys Vault header."
    
    min_len = len(WSPDF_MAGIC) + WSPDF_SALT_LEN + WSPDF_NONCE_LEN + WSPDF_TAG_LEN
    if len(vault_bytes) < min_len:
        return None, "Corrupted vault container: file size is too small."
    
    offset = len(WSPDF_MAGIC)
    salt = vault_bytes[offset:offset + WSPDF_SALT_LEN]
    offset += WSPDF_SALT_LEN
    nonce = vault_bytes[offset:offset + WSPDF_NONCE_LEN]
    offset += WSPDF_NONCE_LEN
    ciphertext_and_tag = vault_bytes[offset:]
    
    try:
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, WSPDF_PBKDF2_ROUNDS, dklen=32)
        aesgcm = AESGCM(key)
        pdf_bytes = aesgcm.decrypt(nonce, ciphertext_and_tag, associated_data=WSPDF_MAGIC)
        return pdf_bytes, None
    except Exception:
        return None, "INVALID_PASSWORD"

def save_wspdf_vault(doc, save_path: str, password: str) -> Tuple[bool, Optional[str]]:
    """Save PyMuPDF document as a word-sys Exclusive Vault container."""
    if not doc:
        return False, "No document to save."
    if not password:
        return False, "Password cannot be empty."
    
    temp_path = f"{save_path}.tmp_save"
    try:
        pdf_bytes = doc.tobytes(garbage=4, deflate=True)
        vault_bytes = encrypt_to_wspdf(pdf_bytes, password)
        with open(temp_path, "wb") as f:
            f.write(vault_bytes)
        os.replace(temp_path, save_path)
        return True, None
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False, str(e)


def permissions_to_bitmask(perms: Union[int, Dict[str, Any], None]) -> int:
    """Convert permission dict, int, or None to PyMuPDF integer bitmask."""
    if isinstance(perms, int):
        return perms
    bitmask = 0
    if not isinstance(perms, dict):
        return (
            getattr(fitz, "PDF_PERM_PRINT", 4) |
            getattr(fitz, "PDF_PERM_COPY", 16) |
            getattr(fitz, "PDF_PERM_ANNOTATE", 32) |
            getattr(fitz, "PDF_PERM_MODIFY", 8) |
            getattr(fitz, "PDF_PERM_FORM", 256) |
            getattr(fitz, "PDF_PERM_ACCESSIBILITY", 512) |
            getattr(fitz, "PDF_PERM_PRINT_HQ", 2048)
        )
    if perms.get("print", True):
        bitmask |= getattr(fitz, "PDF_PERM_PRINT", 4)
        bitmask |= getattr(fitz, "PDF_PERM_PRINT_HQ", 2048)
    if perms.get("copy", True):
        bitmask |= getattr(fitz, "PDF_PERM_COPY", 16)
        bitmask |= getattr(fitz, "PDF_PERM_ACCESSIBILITY", 512)
    if perms.get("annotate", True):
        bitmask |= getattr(fitz, "PDF_PERM_ANNOTATE", 32)
    if perms.get("modify", False):
        bitmask |= getattr(fitz, "PDF_PERM_MODIFY", 8)
        bitmask |= getattr(fitz, "PDF_PERM_ASSEMBLE", 1024)
    if perms.get("form", True):
        bitmask |= getattr(fitz, "PDF_PERM_FORM", 256)
    return bitmask


def save_encrypted_standard_pdf(
    doc,
    save_path: str,
    user_password: str,
    owner_password: Optional[str] = None,
    allow_print: bool = True,
    allow_copy: bool = True,
    allow_annotate: bool = True,
    allow_modify: bool = False,
    allow_form_fill: bool = True
) -> Tuple[bool, Optional[str]]:
    """Save PyMuPDF document with AES-256 standard encryption and configurable permissions."""
    if not doc:
        return False, "No document to save."
    if not user_password:
        return False, "User password cannot be empty."
    
    permissions = permissions_to_bitmask({
        "print": allow_print,
        "copy": allow_copy,
        "annotate": allow_annotate,
        "modify": allow_modify,
        "form": allow_form_fill,
    })
        
    temp_path = f"{save_path}.tmp_save"
    try:
        doc.save(
            temp_path,
            garbage=4,
            deflate=True,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=user_password,
            owner_pw=owner_password or user_password,
            permissions=permissions
        )
        os.replace(temp_path, save_path)
        return True, None
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False, str(e)

def load_pdf_document(filepath, password=None):
    """Load PDF document or word-sys Exclusive Vault container (.wspdf).
    
    Returns (doc, None) on success.
    Returns (None, error_code_or_message) on failure or when password is required:
      - 'PASSWORD_REQUIRED_WSPDF': when a .wspdf vault is loaded without password
      - 'PASSWORD_REQUIRED_STANDARD': when an encrypted PDF is loaded without password
      - 'INVALID_PASSWORD': when password provided was rejected
      - 'Error opening PDF: ...': for general file errors
    """
    try:
        if is_wspdf_file(filepath):
            if password is None:
                return None, "PASSWORD_REQUIRED_WSPDF"
            with open(filepath, "rb") as f:
                vault_data = f.read()
            pdf_bytes, err = decrypt_wspdf(vault_data, password)
            if err:
                return None, err
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            doc._is_vault = True
            doc._vault_password = password
            doc._vault_path = filepath
            doc._file_path = os.path.abspath(filepath)
            return doc, None

        doc = fitz.open(filepath)
        doc._file_path = os.path.abspath(filepath)
        if doc.needs_pass:
            if password is None:
                doc.close()
                return None, "PASSWORD_REQUIRED_STANDARD"
            auth_res = doc.authenticate(password)
            if auth_res > 0:
                doc._pdf_password = password
                doc._pdf_permissions = getattr(doc, 'permissions', None)
                return doc, None
            else:
                doc.close()
                return None, "INVALID_PASSWORD"
        return doc, None
    except Exception as e:
        return None, f"Error opening PDF: {e}\nPath: {filepath}"

def close_pdf_document(doc):
    """Close PDF document and run generational garbage collection."""
    if doc is not None:
        release_doc_lock(doc)
        try:
            doc_id = id(doc)
            invalidate_page_cache(doc)
            with _stale_page_cache_lock:
                keys_to_del = [k for k in _stale_page_cache if k[0] == doc_id]
                for k in keys_to_del:
                    _stale_page_cache.pop(k, None)
            doc.close()
            gc.collect(1)
        except Exception as e:
            print(f"Error closing PDF document: {e}")

def get_page_count(doc):
    """Get the page count."""
    return doc.page_count if doc else 0

PRIORITY_VISIBLE = 0
PRIORITY_PREFETCH = 1
PRIORITY_BACKGROUND = 2

_DOC_LOCKS = {}
_DOC_LOCKS_LOCK = threading.Lock()

def get_doc_lock(doc):
    """Retrieve or create a reentrant threading lock for a document."""
    if doc is None:
        return None
    doc_id = id(doc)
    with _DOC_LOCKS_LOCK:
        lock = _DOC_LOCKS.get(doc_id)
        if lock is None:
            lock = threading.RLock()
            _DOC_LOCKS[doc_id] = lock
        return lock

def release_doc_lock(doc):
    """Release and remove lock entry when document is closed."""
    if doc is None:
        return
    doc_id = id(doc)
    with _DOC_LOCKS_LOCK:
        _DOC_LOCKS.pop(doc_id, None)

class DiskThumbnailCache:
    """Persistent multi-level disk cache for rendered page thumbnails with LRU quota management."""

    def __init__(self, cache_dir: Optional[str] = None, max_disk_bytes: int = 100 * 1024 * 1024):
        if cache_dir is None:
            xdg_cache = os.environ.get("XDG_CACHE_HOME")
            base = Path(xdg_cache) if xdg_cache else (Path.home() / ".cache")
            self.cache_dir = Path(base) / "word-sys-pdf-editor" / "thumbnails"
        else:
            self.cache_dir = Path(cache_dir)
        self.max_disk_bytes = int(max_disk_bytes)
        self._lock = threading.Lock()
        self._ensure_dir()

    def _ensure_dir(self):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def get_document_fingerprint(self, doc, filepath: Optional[str] = None) -> Optional[str]:
        """Compute stable document hash from realpath, modification time, and file size."""
        target_path = filepath or getattr(doc, '_file_path', None) or getattr(doc, 'name', None)
        if not target_path or not os.path.isfile(target_path):
            return None
        try:
            stat = os.stat(target_path)
            real_path = os.path.realpath(target_path)
            key_str = f"{real_path}:{stat.st_mtime_ns}:{stat.st_size}"
            return hashlib.sha256(key_str.encode('utf-8')).hexdigest()[:24]
        except Exception:
            return None

    def get_thumbnail(self, doc, page_index: int, target_width: int = 150, filepath: Optional[str] = None) -> Optional[GdkPixbuf.Pixbuf]:
        """Load pre-rendered thumbnail pixbuf directly from disk cache if valid."""
        fp = self.get_document_fingerprint(doc, filepath)
        if not fp:
            return None
        thumb_path = self.cache_dir / fp / f"{page_index}_{int(target_width)}.png"
        if not thumb_path.is_file():
            return None
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file(str(thumb_path))
            try:
                os.utime(str(self.cache_dir / fp), None)
            except Exception:
                pass
            return pb
        except Exception:
            return None

    def store_thumbnail(self, doc, page_index: int, target_width: int, pix_or_pixbuf: Any, filepath: Optional[str] = None, force: bool = False) -> bool:
        """Store rendered thumbnail directly to disk cache.
        
        Refuses to store dirty/unsaved document modifications to disk cache unless force=True.
        """
        if not force:
            if getattr(doc, '_is_modified', False):
                return False
        fp = self.get_document_fingerprint(doc, filepath)
        if not fp:
            return False
        doc_dir = self.cache_dir / fp
        temp_file = None
        try:
            doc_dir.mkdir(parents=True, exist_ok=True)
            meta_path = doc_dir / "meta.json"
            if not meta_path.is_file():
                target_path = filepath or getattr(doc, '_file_path', None) or getattr(doc, 'name', None)
                if target_path:
                    try:
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump({"path": os.path.realpath(str(target_path))}, f)
                    except Exception:
                        pass

            thumb_file = doc_dir / f"{page_index}_{int(target_width)}.png"
            temp_file = doc_dir / f"{page_index}_{int(target_width)}_{os.getpid()}.tmp.png"

            if hasattr(pix_or_pixbuf, 'save'):
                pix_or_pixbuf.save(str(temp_file))
                os.replace(str(temp_file), str(thumb_file))
                return True
            elif hasattr(pix_or_pixbuf, 'savev'):
                pix_or_pixbuf.savev(str(temp_file), 'png', [], [])
                os.replace(str(temp_file), str(thumb_file))
                return True
            return False
        except Exception:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            return False

    def invalidate_page(self, doc, page_index: int, filepath: Optional[str] = None):
        """Invalidate cached thumbnail files for a specific page."""
        fp = self.get_document_fingerprint(doc, filepath)
        if not fp:
            return
        doc_dir = self.cache_dir / fp
        if not doc_dir.is_dir():
            return
        try:
            for p in doc_dir.glob(f"{page_index}_*.png"):
                p.unlink(missing_ok=True)
        except Exception:
            pass

    def invalidate_doc(self, doc=None, filepath: Optional[str] = None):
        """Purge all cached thumbnails for a document."""
        fp = self.get_document_fingerprint(doc, filepath) if (doc or filepath) else None
        if fp:
            doc_dir = self.cache_dir / fp
            if doc_dir.is_dir():
                shutil.rmtree(str(doc_dir), ignore_errors=True)
                return

        # If file was already deleted from disk, fp is None; scan meta.json to locate and purge by path
        target_path = filepath or getattr(doc, '_file_path', None) or getattr(doc, 'name', None)
        if target_path and self.cache_dir.is_dir():
            target_real = os.path.realpath(str(target_path))
            target_str = str(target_path)
            for child in self.cache_dir.iterdir():
                if child.is_dir():
                    meta_path = child / "meta.json"
                    if meta_path.is_file():
                        try:
                            with open(meta_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            p = data.get("path")
                            if p in (target_real, target_str):
                                shutil.rmtree(str(child), ignore_errors=True)
                        except Exception:
                            pass

    def prune_orphaned_thumbnails(self):
        """Remove cached thumbnail directories whose source PDF no longer exists on disk."""
        if not self.cache_dir.is_dir():
            return
        try:
            for child in self.cache_dir.iterdir():
                if child.is_dir():
                    meta_path = child / "meta.json"
                    if meta_path.is_file():
                        try:
                            with open(meta_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            src_path = data.get("path")
                            if src_path and not os.path.isfile(src_path):
                                shutil.rmtree(str(child), ignore_errors=True)
                        except Exception:
                            pass
        except Exception:
            pass

    def prune(self, max_bytes: Optional[int] = None):
        """Evict oldest document cache directories when total disk cache exceeds quota."""
        self.prune_orphaned_thumbnails()
        limit = int(max_bytes or self.max_disk_bytes)
        if not self.cache_dir.is_dir():
            return
        try:
            entries = []
            total_bytes = 0
            for child in self.cache_dir.iterdir():
                if child.is_dir():
                    dir_size = sum(f.stat().st_size for f in child.glob('*') if f.is_file())
                    mtime = child.stat().st_mtime
                    entries.append((mtime, dir_size, child))
                    total_bytes += dir_size

            if total_bytes <= limit:
                return

            entries.sort(key=lambda x: x[0])
            for mtime, dir_size, child in entries:
                if total_bytes <= limit:
                    break
                shutil.rmtree(str(child), ignore_errors=True)
                total_bytes -= dir_size
        except Exception:
            pass

    def clear(self):
        """Purge all cached thumbnails on disk."""
        if self.cache_dir.is_dir():
            shutil.rmtree(str(self.cache_dir), ignore_errors=True)
            self._ensure_dir()


_DISK_THUMBNAIL_CACHE = None
_DISK_THUMBNAIL_CACHE_LOCK = threading.Lock()

def get_disk_thumbnail_cache() -> DiskThumbnailCache:
    """Retrieve global DiskThumbnailCache singleton."""
    global _DISK_THUMBNAIL_CACHE
    with _DISK_THUMBNAIL_CACHE_LOCK:
        if _DISK_THUMBNAIL_CACHE is None:
            _DISK_THUMBNAIL_CACHE = DiskThumbnailCache()
        return _DISK_THUMBNAIL_CACHE


class ThumbnailTask:
    """Encapsulates a pending thumbnail generation job."""
    __slots__ = ('generation_id', 'doc', 'page_index', 'target_width', 'priority', 'callback', 'cancelled', 'filepath', 'save_to_disk')
    def __init__(self, generation_id, doc, page_index, target_width, priority, callback, filepath=None, save_to_disk=None):
        self.generation_id = generation_id
        self.doc = doc
        self.page_index = page_index
        self.target_width = target_width
        self.priority = priority
        self.callback = callback
        self.cancelled = False
        self.filepath = filepath or getattr(doc, '_file_path', None) or getattr(doc, 'name', None)
        self.save_to_disk = save_to_disk

    def cancel(self):
        self.cancelled = True

class ThumbnailPipeline:
    """Priority-scheduled asynchronous thumbnail rendering pipeline backed by ThreadPoolExecutor(max_workers=2)."""
    def __init__(self, max_workers=2):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="thumb-worker")
        self._queue = queue.PriorityQueue()
        self._counter = itertools.count()
        self._lock = threading.Lock()
        self._tasks = {}
        self._active_workers = 0
        self._shutdown = False

    def request(self, generation_id, doc, page_index, target_width=150, priority=PRIORITY_VISIBLE, callback=None, filepath=None, save_to_disk=None):
        """Enqueue a thumbnail render request with priority scheduling."""
        if self._shutdown or doc is None or getattr(doc, 'is_closed', False):
            return None
        key = (generation_id, page_index)
        with self._lock:
            existing = self._tasks.get(key)
            if existing is not None and not existing.cancelled:
                if existing.priority <= priority:
                    return existing
                existing.cancel()

            task = ThumbnailTask(generation_id, doc, page_index, target_width, priority, callback, filepath=filepath, save_to_disk=save_to_disk)
            self._tasks[key] = task
            count = next(self._counter)
            self._queue.put((priority, count, task))
            self._check_dispatch_locked()
            return task

    def cancel_page(self, generation_id, page_index):
        """Cancel pending render job for a specific page."""
        key = (generation_id, page_index)
        with self._lock:
            task = self._tasks.pop(key, None)
            if task:
                task.cancel()

    def cancel_generation(self, generation_id):
        """Cancel all pending render jobs for a specific document generation."""
        with self._lock:
            keys_to_remove = [k for k in self._tasks if k[0] == generation_id]
            for k in keys_to_remove:
                task = self._tasks.pop(k, None)
                if task:
                    task.cancel()

    def cancel_all(self):
        """Cancel all pending thumbnail jobs."""
        with self._lock:
            for task in self._tasks.values():
                task.cancel()
            self._tasks.clear()

    def shutdown(self, wait=False):
        """Shut down the thread pool and cancel pending jobs."""
        self._shutdown = True
        self.cancel_all()
        try:
            self.executor.shutdown(wait=wait, cancel_futures=True)
        except Exception:
            pass

    def _check_dispatch_locked(self):
        """Dispatch queued items to executor if workers are available."""
        while not self._shutdown and self._active_workers < self.max_workers and not self._queue.empty():
            item = self._queue.get()
            self._active_workers += 1
            self.executor.submit(self._run_job, item)

    def _run_job(self, item):
        """Execute thumbnail rendering job in thread pool worker."""
        prio, count, task = item
        try:
            if task.cancelled or self._shutdown:
                return

            doc = task.doc
            if doc is None or getattr(doc, 'is_closed', False):
                return

            thumb = None
            try:
                is_modified = getattr(doc, '_is_modified', False)
                allow_disk = task.save_to_disk if task.save_to_disk is not None else (not is_modified)

                # 1. Tier 2 Disk Cache Lookup (Non-blocking, zero doc lock contention)
                if allow_disk and not is_modified:
                    disk_cache = get_disk_thumbnail_cache()
                    thumb = disk_cache.get_thumbnail(doc, task.page_index, target_width=task.target_width, filepath=task.filepath)

                # 2. If not cached on disk, render via PyMuPDF with doc lock
                if thumb is None:
                    lock = get_doc_lock(doc)
                    if lock:
                        with lock:
                            if not task.cancelled and not getattr(doc, 'is_closed', False):
                                thumb = generate_thumbnail(
                                    doc, task.page_index, target_width=task.target_width,
                                    filepath=task.filepath, save_to_disk=allow_disk
                                )
                    else:
                        if not task.cancelled and not getattr(doc, 'is_closed', False):
                            thumb = generate_thumbnail(
                                doc, task.page_index, target_width=task.target_width,
                                filepath=task.filepath, save_to_disk=allow_disk
                            )
            except Exception:
                thumb = None

            if not task.cancelled and not self._shutdown and thumb is not None and task.callback:
                cb = task.callback
                gen_id = task.generation_id
                p_idx = task.page_index
                GLib.idle_add(cb, p_idx, thumb, gen_id)
        except Exception:
            pass
        finally:
            with self._lock:
                self._active_workers -= 1
                key = (task.generation_id, task.page_index)
                if self._tasks.get(key) is task:
                    self._tasks.pop(key, None)
                self._check_dispatch_locked()


_THUMBNAIL_PIPELINE = None
_THUMBNAIL_PIPELINE_LOCK = threading.Lock()

def get_thumbnail_pipeline():
    """Retrieve or initialize the global thumbnail rendering pipeline."""
    global _THUMBNAIL_PIPELINE
    with _THUMBNAIL_PIPELINE_LOCK:
        if _THUMBNAIL_PIPELINE is None or _THUMBNAIL_PIPELINE._shutdown:
            _THUMBNAIL_PIPELINE = ThumbnailPipeline(max_workers=2)
        return _THUMBNAIL_PIPELINE

def request_thumbnail_async(generation_id, doc, page_index, target_width=150, priority=PRIORITY_VISIBLE, callback=None, filepath=None, save_to_disk=None):
    """Submit asynchronous thumbnail generation request to pipeline."""
    pipeline = get_thumbnail_pipeline()
    return pipeline.request(generation_id, doc, page_index, target_width, priority, callback, filepath=filepath, save_to_disk=save_to_disk)

def cancel_thumbnail_async(generation_id, page_index):
    """Cancel pending asynchronous thumbnail generation for page."""
    pipeline = get_thumbnail_pipeline()
    pipeline.cancel_page(generation_id, page_index)

def cancel_generation_thumbnails(generation_id):
    """Cancel all pending asynchronous thumbnail jobs for generation."""
    pipeline = get_thumbnail_pipeline()
    pipeline.cancel_generation(generation_id)

def shutdown_thumbnail_pipeline(wait=False):
    """Shut down global thumbnail rendering pipeline."""
    global _THUMBNAIL_PIPELINE
    with _THUMBNAIL_PIPELINE_LOCK:
        if _THUMBNAIL_PIPELINE is not None:
            _THUMBNAIL_PIPELINE.shutdown(wait=wait)
            _THUMBNAIL_PIPELINE = None


def generate_thumbnail(doc, page_index, target_width=150, filepath=None, save_to_disk=None):
    """Generate thumbnail, consulting persistent disk cache first.
    
    Thumbnails are only stored to disk cache when the document is clean (newly opened
    or explicitly saved). Unsaved in-memory changes are never written to disk cache.
    """
    if not doc or not (0 <= page_index < doc.page_count):
        return None

    is_modified = getattr(doc, '_is_modified', False)
    explicit_save = (save_to_disk is True)
    if save_to_disk is None:
        save_to_disk = not is_modified

    # Tier 2 Persistent Disk Cache Check
    if save_to_disk and not is_modified:
        disk_cache = get_disk_thumbnail_cache()
        cached_pb = disk_cache.get_thumbnail(doc, page_index, target_width, filepath=filepath)
        if cached_pb is not None:
            return cached_pb

    try:
        lock = get_doc_lock(doc)
        if lock:
            with lock:
                page = doc.load_page(page_index)
                page_w = page.rect.width
                if page_w == 0:
                    page_w = 1
                zoom_factor = target_width / page_w
                matrix = fitz.Matrix(zoom_factor, zoom_factor)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
        else:
            page = doc.load_page(page_index)
            page_w = page.rect.width
            if page_w == 0:
                page_w = 1
            zoom_factor = target_width / page_w
            matrix = fitz.Matrix(zoom_factor, zoom_factor)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

        # Store to disk cache
        if save_to_disk and (not is_modified or explicit_save):
            disk_cache = get_disk_thumbnail_cache()
            disk_cache.store_thumbnail(doc, page_index, target_width, pix, filepath=filepath, force=explicit_save)

        gdk_pixbuf = GdkPixbuf.Pixbuf.new_from_data(
            pix.samples, GdkPixbuf.Colorspace.RGB, False, 8,
            pix.width, pix.height, pix.stride
        )
        return gdk_pixbuf
    except Exception as thumb_error:
        print(f"Warning: Could not generate thumbnail for page {page_index+1}: {thumb_error}")
        placeholder_pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, target_width, int(target_width * 1.414))
        placeholder_pixbuf.fill(0xaaaaaaFF)
        return placeholder_pixbuf

def draw_page_to_cairo(cr, doc, page_index, zoom_level, dirty_rect=None):
    """Draw page to cairo using the cached surface."""
    surf = get_page_cairo_surface(doc, page_index, zoom_level)
    if (
        surf is not None
        and getattr(surf, 'get_width', lambda: 0)() > 0
        and getattr(surf, 'get_height', lambda: 0)() > 0
    ):
        if dirty_rect is not None:
            cr.save()
            cr.rectangle(*dirty_rect)
            cr.clip()
            cr.set_source_surface(surf, 0, 0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_surface(surf, 0, 0)
            cr.paint()
        return True, None
    else:
        cr.save()
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.paint()
        cr.restore()
        return False, "Failed to render page."


def _get_page_text_baselines(page):
    """Get list of (x0, x1, baseline) for all text lines on page."""
    baselines = []
    try:
        text_dict = page.get_text("dict", flags=0)
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if spans:
                        tx0 = min(s["bbox"][0] for s in spans)
                        tx1 = max(s["bbox"][2] for s in spans)
                        baseline = spans[0].get("origin", (0, line.get("bbox", [0, 0, 0, 0])[3]))[1]
                        baselines.append((tx0, tx1, baseline))
    except Exception:
        pass
    return baselines


def _get_page_text_strikelines(page):
    """Get list of (x0, x1, baseline, font_size) for all text lines on page."""
    strikelines = []
    try:
        text_dict = page.get_text("dict", flags=0)
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if spans:
                        tx0 = min(s["bbox"][0] for s in spans)
                        tx1 = max(s["bbox"][2] for s in spans)
                        baseline = spans[0].get("origin", (0, line.get("bbox", [0, 0, 0, 0])[3]))[1]
                        font_size = spans[0].get("size", 11.0)
                        strikelines.append((tx0, tx1, baseline, font_size))
    except Exception:
        pass
    return strikelines


def _is_underline_drawing(drawing, baselines):
    """Check if a drawing is an underline coincident with a text baseline."""
    if not baselines:
        return False
    try:
        items = drawing.get('items', [])
        rect = drawing.get('rect')
        line_y = None
        line_x0 = None
        line_x1 = None
        if len(items) == 1 and items[0][0] == 'l':
            p1, p2 = items[0][1], items[0][2]
            if abs(p1.y - p2.y) <= 1.0 and abs(p1.x - p2.x) >= 4.0:
                line_y = (p1.y + p2.y) / 2.0
                line_x0, line_x1 = min(p1.x, p2.x), max(p1.x, p2.x)
        elif rect and rect.height <= 3.5 and rect.width >= 4.0:
            line_y = (rect.y0 + rect.y1) / 2.0
            line_x0, line_x1 = rect.x0, rect.x1

        if line_y is None or line_x0 is None or line_x1 is None:
            return False

        for tx0, tx1, baseline in baselines:
            if abs(line_y - (baseline + 1.5)) <= 2.5:
                overlap = min(line_x1, tx1) - max(line_x0, tx0)
                text_width = max(0.1, tx1 - tx0)
                if overlap >= min(4.0, text_width * 0.4):
                    return True
    except Exception:
        pass
    return False


def _is_strikethrough_drawing(drawing, strikelines):
    """Check if a drawing is a strikethrough line across text midpoint."""
    if not strikelines:
        return False
    try:
        items = drawing.get('items', [])
        rect = drawing.get('rect')
        line_y = None
        line_x0 = None
        line_x1 = None
        if len(items) == 1 and items[0][0] == 'l':
            p1, p2 = items[0][1], items[0][2]
            if abs(p1.y - p2.y) <= 1.0 and abs(p1.x - p2.x) >= 4.0:
                line_y = (p1.y + p2.y) / 2.0
                line_x0, line_x1 = min(p1.x, p2.x), max(p1.x, p2.x)
        elif rect and rect.height <= 3.5 and rect.width >= 4.0:
            line_y = (rect.y0 + rect.y1) / 2.0
            line_x0, line_x1 = rect.x0, rect.x1

        if line_y is None or line_x0 is None or line_x1 is None:
            return False

        for tx0, tx1, baseline, font_sz in strikelines:
            target_strike_y = baseline - (font_sz * 0.3)
            tolerance = max(2.5, font_sz * 0.2)
            if abs(line_y - target_strike_y) <= tolerance:
                overlap = min(line_x1, tx1) - max(line_x0, tx0)
                text_width = max(0.1, tx1 - tx0)
                if overlap >= min(4.0, text_width * 0.4):
                    return True
    except Exception:
        pass
    return False


def _get_span_style_signature(span):
    """Compute a normalized tuple signature for style comparison."""
    color = span.get("color", 0)
    if isinstance(color, (list, tuple)):
        norm_color = tuple(round(float(c), 3) for c in color[:3])
    else:
        norm_color = int(color)
    font = span.get("font", "")
    flags = span.get("flags", 0)
    size = round(float(span.get("size", 11.0)), 1)
    return (norm_color, font, flags, size)


def extract_editable_text(doc, page_index):
    """Extract editable text spans from a PDF page into EditableText models."""
    editable_texts = []
    if not doc or not (0 <= page_index < doc.page_count):
        return [], "Invalid document or page index for text extraction."
    try:
        page = doc.load_page(page_index)
        try:
            raw_json = page.get_text("rawjson", flags=0)
            text_dict = json.loads(raw_json)
        except Exception:
            text_dict = page.get_text("rawdict", flags=0)

        page_drawings = None
        try:
            page_drawings = page.get_drawings()
        except Exception:
            page_drawings = []

        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    
                    # Group adjacent spans in line sharing identical style signature
                    runs = []
                    current_run = []
                    current_sig = None
                    
                    for span in spans:
                        text = "".join(c["c"] for c in span.get("chars", [])) if span.get("chars") else span.get("text", "")
                        if not text:
                            continue
                        
                        sig = _get_span_style_signature(span)
                        
                        # If span is purely whitespace, attach to current active run
                        if not text.strip() and current_run:
                            current_run.append(span)
                            continue
                            
                        if current_sig is None:
                            current_sig = sig
                            current_run = [span]
                        elif sig == current_sig:
                            current_run.append(span)
                        else:
                            if current_run:
                                runs.append(current_run)
                            current_sig = sig
                            current_run = [span]
                            
                    if current_run:
                        runs.append(current_run)
                        
                    for run in runs:
                        all_chars = []
                        for s in run:
                            if s.get("chars"):
                                all_chars.extend(s["chars"])
                        if all_chars:
                            non_space = [c for c in all_chars if not c["c"].isspace()]
                            if not non_space:
                                continue
                            combined_text = "".join(c["c"] for c in all_chars).strip()
                            min_x = min(c["bbox"][0] for c in non_space)
                            min_y = min(c["bbox"][1] for c in non_space)
                            max_x = max(c["bbox"][2] for c in non_space)
                            max_y = max(c["bbox"][3] for c in non_space)
                        else:
                            combined_text = "".join(s.get("text", "") for s in run).strip()
                            if not combined_text:
                                continue
                            min_x = min(s.get("bbox", (0, 0, 0, 0))[0] for s in run)
                            min_y = min(s.get("bbox", (0, 0, 0, 0))[1] for s in run)
                            max_x = max(s.get("bbox", (0, 0, 0, 0))[2] for s in run)
                            max_y = max(s.get("bbox", (0, 0, 0, 0))[3] for s in run)
                            
                        bbox = [min_x, min_y, max_x, max_y]
                        
                        first_span = run[0]
                        span_data = first_span.copy()
                        span_data["bbox"] = tuple(bbox)
                        span_data["text"] = combined_text

                        orig_origin = first_span.get("origin", (0, bbox[3]))
                        
                        line_dir = line.get("dir", (1.0, 0.0))
                        line_rot = 0.0
                        if line_dir and (abs(line_dir[0] - 1.0) > 1e-3 or abs(line_dir[1]) > 1e-3):
                            line_rot = round(math.degrees(math.atan2(line_dir[1], line_dir[0])), 1) % 360.0

                        if line_rot != 0.0:
                            cx = (min_x + max_x) / 2.0
                            cy = (min_y + max_y) / 2.0
                            rad = math.radians(-line_rot)
                            cos_a = math.cos(rad)
                            sin_a = math.sin(rad)
                            def _unrot_pt(px, py):
                                dx = px - cx
                                dy = py - cy
                                return (dx * cos_a - dy * sin_a + cx, dx * sin_a + dy * cos_a + cy)

                            unrot_pts = []
                            for c in (non_space if non_space else all_chars):
                                cb = c.get("bbox", [0, 0, 0, 0])
                                for px, py in [(cb[0], cb[1]), (cb[2], cb[1]), (cb[2], cb[3]), (cb[0], cb[3])]:
                                    unrot_pts.append(_unrot_pt(px, py))
                            if unrot_pts:
                                u_min_x = min(p[0] for p in unrot_pts)
                                u_min_y = min(p[1] for p in unrot_pts)
                                u_max_x = max(p[0] for p in unrot_pts)
                                u_max_y = max(p[1] for p in unrot_pts)
                                bbox = [u_min_x, u_min_y, u_max_x, u_max_y]

                            unrot_orig = _unrot_pt(orig_origin[0], orig_origin[1])
                            baseline_val = unrot_orig[1]
                        else:
                            baseline_val = orig_origin[1]

                        editable = EditableText(
                            x=bbox[0], y=bbox[1], text=combined_text,
                            font_size=first_span.get("size", 11) if first_span else 11,
                            font_family=first_span.get("font", "Liberation Sans") if first_span else "Liberation Sans",
                            color=first_span.get("color", 0) if first_span else 0,
                            span_data=span_data,
                            baseline=baseline_val,
                            rotation=line_rot
                        )
                        editable.bbox = tuple(bbox)
                        editable.original_bbox = editable.bbox
                        editable.original_baseline = editable.baseline
                        editable.original_rotation = editable.rotation
                        editable.page_number = page_index
                        if line_rot != 0.0:
                            editable.char_boxes = [
                                {
                                    "char": c.get("c", ""),
                                    "bbox": (
                                        min(_unrot_pt(c["bbox"][0], c["bbox"][1])[0], _unrot_pt(c["bbox"][2], c["bbox"][1])[0], _unrot_pt(c["bbox"][2], c["bbox"][3])[0], _unrot_pt(c["bbox"][0], c["bbox"][3])[0]),
                                        min(_unrot_pt(c["bbox"][0], c["bbox"][1])[1], _unrot_pt(c["bbox"][2], c["bbox"][1])[1], _unrot_pt(c["bbox"][2], c["bbox"][3])[1], _unrot_pt(c["bbox"][0], c["bbox"][3])[1]),
                                        max(_unrot_pt(c["bbox"][0], c["bbox"][1])[0], _unrot_pt(c["bbox"][2], c["bbox"][1])[0], _unrot_pt(c["bbox"][2], c["bbox"][3])[0], _unrot_pt(c["bbox"][0], c["bbox"][3])[0]),
                                        max(_unrot_pt(c["bbox"][0], c["bbox"][1])[1], _unrot_pt(c["bbox"][2], c["bbox"][1])[1], _unrot_pt(c["bbox"][2], c["bbox"][3])[1], _unrot_pt(c["bbox"][0], c["bbox"][3])[1])
                                    ) if c.get("bbox") else (0, 0, 0, 0),
                                    "origin": _unrot_pt(c.get("origin", (c.get("bbox", [0, 0])[0], orig_origin[1]))[0], c.get("origin", (c.get("bbox", [0, 0])[0], orig_origin[1]))[1]),
                                    "synthetic": bool(c.get("synthetic", False)),
                                }
                                for c in all_chars
                            ]
                        else:
                            editable.char_boxes = [
                                {
                                    "char": c.get("c", ""),
                                    "bbox": tuple(c.get("bbox", [0, 0, 0, 0])),
                                    "origin": tuple(c.get("origin", (c.get("bbox", [0, 0])[0], orig_origin[1]))),
                                    "synthetic": bool(c.get("synthetic", False)),
                                }
                                for c in all_chars
                            ]
                        editable.font_properties = decompose_font_name(
                            editable.font_family_original,
                            flags=first_span.get("flags", 0) if first_span else 0
                        )
                        if page_drawings:
                            for d in page_drawings:
                                if _is_underline_drawing(d, [(bbox[0], bbox[2], orig_origin[1])]):
                                    editable.is_underline = True
                                    break
                            for d in page_drawings:
                                if _is_strikethrough_drawing(d, [(bbox[0], bbox[2], orig_origin[1], editable.font_size)]):
                                    editable.is_strikethrough = True
                                    break
                        editable_texts.append(editable)
        
        # Attach existing PDF link annotations to corresponding text objects
        page_links = page.get_links() if hasattr(page, 'get_links') else []
        for editable in editable_texts:
            if not getattr(editable, 'bbox', None):
                continue
            e_rect = fitz.Rect(editable.bbox)
            for link in page_links:
                if link.get('kind') == fitz.LINK_URI and link.get('uri'):
                    l_rect = link.get('from')
                    if l_rect and (e_rect.intersects(l_rect) or l_rect.contains(e_rect) or e_rect.contains(l_rect)):
                        editable.link_url = link.get('uri')
                        editable.original_link_url = editable.link_url
                        break

        return editable_texts, None
    except Exception as e:
        error_msg = f"Error extracting text from page {page_index}: {e}"
        print(error_msg)
        traceback.print_exc()
        return [], error_msg

def _get_base14_font_variant(base_name, is_bold, is_italic):
    """Get the base14 font variant name."""
    return get_base14_font_variant(base_name, is_bold, is_italic)


def _resolve_page(target, page_index=None):
    """Resolve a fitz.Page instance from either a Page or a Document with page_index."""
    if target is None:
        return None
    if hasattr(target, "get_text"):
        return target
    if hasattr(target, "load_page") or hasattr(target, "__getitem__"):
        idx = 0 if page_index is None else page_index
        try:
            doc_len = len(target)
            if not (0 <= idx < doc_len):
                return None
            return target.load_page(idx) if hasattr(target, "load_page") else target[idx]
        except Exception:
            return None
    return None


def extract_page_text_raw(target, page_index=None, use_rawjson=True) -> Dict[str, Any]:
    """Extract raw text layout data (blocks, lines, spans, chars) from a page.
    
    Args:
        target: fitz.Page, or fitz.Document.
        page_index: 0-based page index if target is a fitz.Document.
        use_rawjson: If True, uses PyMuPDF's page.get_text("rawjson") parsed via json.loads.
                     If False, uses page.get_text("rawdict").
                     
    Returns:
        Dict with keys 'width', 'height', and 'blocks'.
    """
    page = _resolve_page(target, page_index)
    if page is None:
        return {"width": 0.0, "height": 0.0, "blocks": []}
        
    try:
        if use_rawjson:
            raw_str = page.get_text("rawjson", flags=0)
            return json.loads(raw_str)
        else:
            return page.get_text("rawdict", flags=0)
    except Exception:
        try:
            return page.get_text("rawdict", flags=0)
        except Exception:
            return {"width": 0.0, "height": 0.0, "blocks": []}


def extract_text_spans_with_char_boxes(target, page_index=None, use_rawjson=True) -> List[Dict[str, Any]]:
    """Extract text spans from a PDF page including exact character bounding boxes, origins,
    font properties, line direction/rotation, and baseline coordinates.
    
    Args:
        target: fitz.Page, or fitz.Document.
        page_index: 0-based page index if target is a fitz.Document.
        use_rawjson: If True, uses page.get_text("rawjson"); otherwise page.get_text("rawdict").
        
    Returns:
        List of span dictionaries.
    """
    page = _resolve_page(target, page_index)
    if page is None:
        return []
        
    raw_data = extract_page_text_raw(page, use_rawjson=use_rawjson)
    spans_out = []
    
    page_rot = page.rotation % 360
    rot_mat = page.rotation_matrix if page_rot != 0 else None
    
    for block_idx, block in enumerate(raw_data.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_idx, line in enumerate(block.get("lines", [])):
            line_bbox = tuple(line.get("bbox", [0, 0, 0, 0]))
            vis_line_bbox = tuple((fitz.Rect(line_bbox) * rot_mat).normalize()) if rot_mat else line_bbox
            line_dir = tuple(line.get("dir", [1.0, 0.0]))
            line_rot = 0.0
            if line_dir and (abs(line_dir[0] - 1.0) > 1e-3 or abs(line_dir[1]) > 1e-3):
                line_rot = round(math.degrees(math.atan2(line_dir[1], line_dir[0])), 1) % 360.0
                
            for span_idx, span in enumerate(line.get("spans", [])):
                font_name = span.get("font", "Helvetica")
                flags = span.get("flags", 0)
                font_props = decompose_font_name(font_name, flags)
                norm_color = normalize_color(span.get("color", 0))
                
                span_origin = tuple(span.get("origin", [0, 0]))
                span_baseline = span_origin[1]
                span_bbox = tuple(span.get("bbox", [0, 0, 0, 0]))
                vis_span_bbox = tuple((fitz.Rect(span_bbox) * rot_mat).normalize()) if rot_mat else span_bbox
                
                raw_chars = span.get("chars", [])
                char_boxes = []
                for c_idx, c in enumerate(raw_chars):
                    c_bbox = tuple(c.get("bbox", [0, 0, 0, 0]))
                    c_vis_bbox = tuple((fitz.Rect(c_bbox) * rot_mat).normalize()) if rot_mat else c_bbox
                    c_origin = tuple(c.get("origin", [c_bbox[0], span_baseline]))
                    char_boxes.append({
                        "char": c.get("c", ""),
                        "bbox": c_bbox,
                        "visual_bbox": c_vis_bbox,
                        "origin": c_origin,
                        "baseline": c_origin[1],
                        "synthetic": bool(c.get("synthetic", False)),
                        "index": c_idx,
                    })
                    
                span_text = "".join(cb["char"] for cb in char_boxes) if char_boxes else span.get("text", "")
                
                spans_out.append({
                    "text": span_text,
                    "bbox": span_bbox,
                    "visual_bbox": vis_span_bbox,
                    "origin": span_origin,
                    "baseline": span_baseline,
                    "font": font_name,
                    "font_properties": font_props,
                    "size": float(span.get("size", 11.0)),
                    "color": norm_color,
                    "flags": flags,
                    "alpha": float(span.get("alpha", 1.0)),
                    "ascender": float(span.get("ascender", 0.0)),
                    "descender": float(span.get("descender", 0.0)),
                    "block_index": block_idx,
                    "line_index": line_idx,
                    "span_index": span_idx,
                    "line_bbox": line_bbox,
                    "visual_line_bbox": vis_line_bbox,
                    "line_dir": line_dir,
                    "line_rotation": line_rot,
                    "char_boxes": char_boxes,
                })
                
    return spans_out


def get_text_hit_info_at_pos(target, pos: Tuple[float, float], page_index=None,
                             tolerance: float = 2.0, visual_coords: bool = False,
                             use_rawjson: bool = True) -> Optional[Dict[str, Any]]:
    """Perform comprehensive hit-testing at pos (x, y) on a PDF page, returning structured
    character, word, span, and line layout details with exact font metrics and bounding boxes.
    
    Args:
        target: fitz.Page, or fitz.Document.
        pos: (x, y) coordinates.
        page_index: 0-based page index if target is a fitz.Document.
        tolerance: Maximum distance in points to consider a hit. Default is 2.0.
        visual_coords: If True, pos is interpreted in visual coordinates on rotated pages.
        use_rawjson: If True, uses page.get_text("rawjson") for extraction.
        
    Returns:
        Dict with keys: 'char', 'word', 'span', 'line', 'page_index', 'block_index', or None if no hit.
    """
    if isinstance(pos, (int, float)) and isinstance(page_index, (tuple, list)):
        pos, page_index = page_index, int(pos)

    page = _resolve_page(target, page_index)
    if page is None:
        return None
        
    page_idx = getattr(page, 'number', page_index if page_index is not None else 0)
    page_rot = page.rotation % 360
    rot_mat = page.rotation_matrix if page_rot != 0 else None
    inv_rot_mat = (~page.rotation_matrix) if page_rot != 0 else None
    
    if visual_coords and inv_rot_mat:
        p_unrot = fitz.Point(pos[0], pos[1]) * inv_rot_mat
        px, py = p_unrot.x, p_unrot.y
    else:
        px, py = pos[0], pos[1]
        
    spans = extract_text_spans_with_char_boxes(page, use_rawjson=use_rawjson)
    if not spans:
        return None
        
    # Phase 1: Search character bounding boxes within tolerance
    char_candidates = []
    for span in spans:
        for cb in span["char_boxes"]:
            cx0, cy0, cx1, cy1 = cb["bbox"]
            if (cx0 - tolerance) <= px <= (cx1 + tolerance) and (cy0 - tolerance) <= py <= (cy1 + tolerance):
                mid_x = (cx0 + cx1) / 2.0
                mid_y = (cy0 + cy1) / 2.0
                dist_sq = (px - mid_x) ** 2 + (py - mid_y) ** 2
                char_candidates.append((dist_sq, span, cb))
                
    best_span = None
    best_char = None
    
    if char_candidates:
        char_candidates.sort(key=lambda item: item[0])
        best_span = char_candidates[0][1]
        best_char = char_candidates[0][2]
    else:
        # Phase 2: If no individual character matched, check span bounding boxes
        span_candidates = []
        for span in spans:
            sx0, sy0, sx1, sy1 = span["bbox"]
            if (sx0 - tolerance) <= px <= (sx1 + tolerance) and (sy0 - tolerance) <= py <= (sy1 + tolerance):
                mid_x = (sx0 + sx1) / 2.0
                mid_y = (sy0 + sy1) / 2.0
                dist_sq = (px - mid_x) ** 2 + (py - mid_y) ** 2
                span_candidates.append((dist_sq, span))
                
        if span_candidates:
            span_candidates.sort(key=lambda item: item[0])
            best_span = span_candidates[0][1]
            if best_span["char_boxes"]:
                # Pick the closest character inside this span to (px, py)
                c_dists = []
                for cb in best_span["char_boxes"]:
                    cx0, cy0, cx1, cy1 = cb["bbox"]
                    mid_x = (cx0 + cx1) / 2.0
                    mid_y = (cy0 + cy1) / 2.0
                    dist_sq = (px - mid_x) ** 2 + (py - mid_y) ** 2
                    c_dists.append((dist_sq, cb))
                c_dists.sort(key=lambda item: item[0])
                best_char = c_dists[0][1]
                
    if not best_span or not best_char:
        return None
        
    # Reconstruct word containing best_char
    hit_idx = best_char["index"]
    span_chars = best_span["char_boxes"]
    
    if best_char["char"].strip() != "":
        start_idx = hit_idx
        while start_idx > 0 and span_chars[start_idx - 1]["char"].strip() != "":
            start_idx -= 1
        end_idx = hit_idx
        while end_idx < len(span_chars) - 1 and span_chars[end_idx + 1]["char"].strip() != "":
            end_idx += 1
    else:
        # Hit on whitespace: check adjacent tokens
        if hit_idx + 1 < len(span_chars) and span_chars[hit_idx + 1]["char"].strip() != "":
            start_idx = hit_idx + 1
            end_idx = start_idx
            while end_idx < len(span_chars) - 1 and span_chars[end_idx + 1]["char"].strip() != "":
                end_idx += 1
        elif hit_idx > 0 and span_chars[hit_idx - 1]["char"].strip() != "":
            end_idx = hit_idx - 1
            start_idx = end_idx
            while start_idx > 0 and span_chars[start_idx - 1]["char"].strip() != "":
                start_idx -= 1
        else:
            start_idx = hit_idx
            end_idx = hit_idx
            
    word_char_boxes = span_chars[start_idx:end_idx + 1]
    word_text = "".join(cb["char"] for cb in word_char_boxes)
    word_x0 = min(cb["bbox"][0] for cb in word_char_boxes)
    word_y0 = min(cb["bbox"][1] for cb in word_char_boxes)
    word_x1 = max(cb["bbox"][2] for cb in word_char_boxes)
    word_y1 = max(cb["bbox"][3] for cb in word_char_boxes)
    word_bbox = (word_x0, word_y0, word_x1, word_y1)
    vis_word_bbox = tuple((fitz.Rect(word_bbox) * rot_mat).normalize()) if rot_mat else word_bbox
    
    # Reconstruct line text and spans
    line_spans = [s for s in spans if s["block_index"] == best_span["block_index"] and s["line_index"] == best_span["line_index"]]
    line_text = "".join(s["text"] for s in line_spans)
    line_char_boxes = []
    for s in line_spans:
        line_char_boxes.extend(s["char_boxes"])
        
    return {
        "char": {
            "char": best_char["char"],
            "index": best_char["index"],
            "bbox": best_char["bbox"],
            "visual_bbox": best_char["visual_bbox"],
            "origin": best_char["origin"],
            "baseline": best_char["baseline"],
            "synthetic": best_char["synthetic"],
        },
        "word": {
            "text": word_text,
            "bbox": word_bbox,
            "visual_bbox": vis_word_bbox,
            "start_char_index": start_idx,
            "end_char_index": end_idx,
            "char_boxes": word_char_boxes,
        },
        "span": {
            "text": best_span["text"],
            "index": best_span["span_index"],
            "bbox": best_span["bbox"],
            "visual_bbox": best_span["visual_bbox"],
            "origin": best_span["origin"],
            "baseline": best_span["baseline"],
            "font": best_span["font"],
            "font_size": best_span["size"],
            "font_properties": best_span["font_properties"],
            "color": best_span["color"],
            "flags": best_span["flags"],
            "alpha": best_span["alpha"],
            "ascender": best_span["ascender"],
            "descender": best_span["descender"],
            "char_boxes": best_span["char_boxes"],
        },
        "line": {
            "text": line_text,
            "index": best_span["line_index"],
            "bbox": best_span["line_bbox"],
            "visual_bbox": best_span["visual_line_bbox"],
            "baseline": best_span["baseline"],
            "dir": best_span["line_dir"],
            "rotation": best_span["line_rotation"],
            "spans": line_spans,
            "char_boxes": line_char_boxes,
            "primary_font": best_span["font"],
            "primary_font_size": best_span["size"],
            "primary_font_properties": best_span["font_properties"],
        },
        "block_index": best_span["block_index"],
        "page_index": page_idx,
    }


def hit_test_text_char_at_pos(target, pos: Tuple[float, float], page_index=None,
                              tolerance: float = 2.0, visual_coords: bool = False,
                              use_rawjson: bool = True) -> Optional[Dict[str, Any]]:
    """Hit-test a single character at pos (x, y). Returns char details or None."""
    hit = get_text_hit_info_at_pos(target, pos, page_index, tolerance, visual_coords, use_rawjson)
    if not hit:
        return None
    res = dict(hit["char"])
    res["font"] = hit["span"]["font"]
    res["font_size"] = hit["span"]["font_size"]
    res["font_properties"] = hit["span"]["font_properties"]
    res["color"] = hit["span"]["color"]
    res["span_text"] = hit["span"]["text"]
    res["span_bbox"] = hit["span"]["bbox"]
    res["visual_span_bbox"] = hit["span"]["visual_bbox"]
    res["line_text"] = hit["line"]["text"]
    res["line_bbox"] = hit["line"]["bbox"]
    res["visual_line_bbox"] = hit["line"]["visual_bbox"]
    res["line_dir"] = hit["line"]["dir"]
    res["line_rotation"] = hit["line"]["rotation"]
    res["block_index"] = hit["block_index"]
    res["page_index"] = hit["page_index"]
    return res


def hit_test_text_word_at_pos(target, pos: Tuple[float, float], page_index=None,
                              tolerance: float = 2.0, visual_coords: bool = False,
                              use_rawjson: bool = True) -> Optional[Dict[str, Any]]:
    """Hit-test a contiguous word at pos (x, y). Returns word details or None."""
    hit = get_text_hit_info_at_pos(target, pos, page_index, tolerance, visual_coords, use_rawjson)
    if not hit:
        return None
    res = dict(hit["word"])
    res["word"] = hit["word"]["text"]
    res["font"] = hit["span"]["font"]
    res["font_size"] = hit["span"]["font_size"]
    res["font_properties"] = hit["span"]["font_properties"]
    res["baseline"] = hit["span"]["baseline"]
    res["color"] = hit["span"]["color"]
    res["span_text"] = hit["span"]["text"]
    res["span_bbox"] = hit["span"]["bbox"]
    res["visual_span_bbox"] = hit["span"]["visual_bbox"]
    res["line_text"] = hit["line"]["text"]
    res["line_bbox"] = hit["line"]["bbox"]
    res["visual_line_bbox"] = hit["line"]["visual_bbox"]
    res["block_index"] = hit["block_index"]
    res["page_index"] = hit["page_index"]
    return res


def hit_test_text_line_at_pos(target, pos: Tuple[float, float], page_index=None,
                              tolerance: float = 2.0, visual_coords: bool = False,
                              use_rawjson: bool = True) -> Optional[Dict[str, Any]]:
    """Hit-test an entire text line at pos (x, y). Returns line details or None."""
    hit = get_text_hit_info_at_pos(target, pos, page_index, tolerance, visual_coords, use_rawjson)
    if not hit:
        return None
    res = dict(hit["line"])
    res["block_index"] = hit["block_index"]
    res["page_index"] = hit["page_index"]
    return res


def hit_test_text_span_at_pos(target, pos: Tuple[float, float], page_index=None,
                              tolerance: float = 2.0, visual_coords: bool = False,
                              use_rawjson: bool = True) -> Optional[Dict[str, Any]]:
    """Hit-test a text span at pos (x, y). Returns span details or None."""
    hit = get_text_hit_info_at_pos(target, pos, page_index, tolerance, visual_coords, use_rawjson)
    if not hit:
        return None
    res = dict(hit["span"])
    res["line_text"] = hit["line"]["text"]
    res["line_bbox"] = hit["line"]["bbox"]
    res["visual_line_bbox"] = hit["line"]["visual_bbox"]
    res["line_dir"] = hit["line"]["dir"]
    res["line_rotation"] = hit["line"]["rotation"]
    res["block_index"] = hit["block_index"]
    res["page_index"] = hit["page_index"]
    return res

def apply_text_edit(doc, text_obj: EditableText, new_text: str):
    """Replace original text span in the underlying PDF content stream using redaction and text insertion."""
    if not doc or text_obj.page_number is None:
        return False, "Invalid document or page number."

    try:
        page = doc.load_page(text_obj.page_number)
        
        # 1. Redact original text if this was an existing text span from the PDF
        if not getattr(text_obj, 'is_new', False):
            orig_box = getattr(text_obj, 'original_bbox', None) or getattr(text_obj, 'bbox', None)
            if orig_box:
                rot = getattr(text_obj, 'rotation', 0.0) % 360.0
                cx = (orig_box[0] + orig_box[2]) / 2.0
                cy = (orig_box[1] + orig_box[3]) / 2.0
                mat = get_rotation_matrix(cx, cy, rot) if rot != 0.0 else None
                redact_rect = fitz.Rect(orig_box)
                if mat:
                    page.add_redact_annot(redact_rect.quad * mat)
                else:
                    page.add_redact_annot(redact_rect)
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0, text=0)

        # 2. Insert replacement text if non-empty
        if new_text.strip():
            temp_obj = copy.deepcopy(text_obj)
            temp_obj.text = new_text
            res, err = _apply_single_object_to_page(doc, page, temp_obj)
            if not res:
                return False, err

        text_obj.text = new_text
        text_obj.is_baked = True
        text_obj._ghost_redacted = True
        invalidate_page_cache(doc, text_obj.page_number)
        return True, None
    except Exception as e:
        print(f"ERROR applying text edit: {e}")
        traceback.print_exc()
        return False, f"Error during text application: {e}"

def save_document(doc, save_path, incremental=False):
    """Save PyMuPDF document to disk with optional incremental saving and cleanup."""
    if not doc:
        return False, "Kaydedilecek belge yok."

    # If saving to .wspdf or the doc was opened as a vault container
    if save_path.lower().endswith(".wspdf") or getattr(doc, '_is_vault', False):
        vault_pw = getattr(doc, '_vault_password', None)
        if vault_pw:
            return save_wspdf_vault(doc, save_path, vault_pw)

    temp_path = f"{save_path}.tmp_save"

    try:
        pdf_pw = getattr(doc, '_pdf_password', None)
        owner_pw = getattr(doc, '_pdf_owner_password', None) or pdf_pw
        perms = getattr(doc, '_pdf_permissions', None)
        if pdf_pw or owner_pw or perms is not None:
            save_kwargs = {
                "garbage": 4,
                "deflate": True,
                "clean": True,
                "incremental": False,
                "encryption": fitz.PDF_ENCRYPT_AES_256,
                "user_pw": pdf_pw or "",
                "owner_pw": owner_pw or pdf_pw or "",
            }
            if perms is not None:
                save_kwargs["permissions"] = permissions_to_bitmask(perms)
            doc.save(temp_path, **save_kwargs)
        else:
            doc.save(
                temp_path,
                garbage=4,
                deflate=True,
                clean=True,
                incremental=False,  
                encryption=fitz.PDF_ENCRYPT_NONE
            )

        os.replace(temp_path, save_path)
        return True, None

    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        
        return False, _("err_pdf_save", e)
    
def export_document(
    doc=None,
    source_pdf_path=None,
    output_path=None,
    target_format="docx",
    mode="canvas",
    password="",
):
    """Export a PDF document into a target format (DOCX, PPTX, ODT, ODP, TXT) using anyconvert.

    Args:
        doc: The fitz.Document instance or None.
        source_pdf_path: File path of the source PDF if available on disk.
        output_path: Destination file path for the converted document.
        target_format: Target format ('docx', 'pptx', 'odt', 'odp', 'txt').
        mode: Layout conversion mode ('canvas' for pixel-accurate coordinate positioning or 'flow' for semantic reflow).
        password: Optional decryption password for protected PDF documents.

    Returns:
        tuple[bool, Optional[str]]: (success, error_message).
    """
    if not output_path:
        return False, "Destination output path must be specified for export."

    fmt = str(target_format).lower().strip().lstrip(".")
    if fmt not in ("docx", "pptx", "odt", "odp", "txt"):
        return False, f"Unsupported export format: '{target_format}'. Supported formats are DOCX, PPTX, ODT, ODP, TXT."

    output_path = str(output_path)
    if not output_path.lower().endswith(f".{fmt}"):
        output_path = f"{output_path}.{fmt}"

    if not HAS_ANYCONVERT:
        return False, "anyconvert engine is not installed. Please install 'anyconvert' to enable document export."

    conv_mode = "canvas"
    if isinstance(mode, str):
        normalized_mode = mode.lower().strip()
        if normalized_mode in ("canvas", "flow"):
            conv_mode = normalized_mode
    elif ConversionMode is not None and isinstance(mode, ConversionMode):
        conv_mode = "canvas" if mode == ConversionMode.CANVAS else "flow"

    pdf_input = None
    if doc is not None:
        if isinstance(doc, (bytes, bytearray)):
            pdf_input = bytes(doc)
        else:
            try:
                pdf_input = doc.tobytes(garbage=4, clean=True, deflate=True)
            except Exception:
                try:
                    pdf_input = doc.tobytes()
                except Exception:
                    if source_pdf_path and os.path.exists(source_pdf_path):
                        pdf_input = source_pdf_path
                    else:
                        return False, "Failed to serialize in-memory PDF document for export."
    elif source_pdf_path and os.path.exists(source_pdf_path):
        try:
            temp_doc = fitz.open(source_pdf_path)
            if temp_doc.is_encrypted:
                if password:
                    auth_res = temp_doc.authenticate(password)
                    if auth_res > 0:
                        pdf_input = temp_doc.tobytes()
                    else:
                        return False, "The decryption password provided is incorrect."
                else:
                    return False, "The PDF document is password-protected. Please provide the decryption password."
            else:
                pdf_input = source_pdf_path
        except Exception:
            pdf_input = source_pdf_path
    else:
        return False, "No valid document or file path provided for export."

    try:
        final_output_path = Path(output_path)
        final_output_path.parent.mkdir(parents=True, exist_ok=True)
        if final_output_path.exists():
            final_output_path.unlink()

        anyconvert.convert(
            input_path=pdf_input,
            output_format=fmt,
            output_path=output_path,
            mode=conv_mode,
            password=password,
        )

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True, None
        return False, f"Export completed but output file '{output_path}' was not created or is empty."

    except anyconvert.exceptions.PDFPasswordRequiredError:
        return False, "The PDF document is password-protected. Please provide the decryption password."
    except anyconvert.exceptions.UnsupportedFormatError as e:
        return False, f"Unsupported export format: {e}"
    except anyconvert.exceptions.AnyConvertError as e:
        return False, f"anyconvert conversion failed: {e}"
    except Exception as e:
        return False, f"Error during {fmt.upper()} export: {e}"


def export_pdf_as_docx(doc, source_pdf_path, output_docx_path, mode="canvas", password=""):
    """Export PDF as DOCX using anyconvert."""
    return export_document(doc, source_pdf_path, output_docx_path, "docx", mode=mode, password=password)


def export_pdf_as_odt(doc, source_pdf_path, output_odt_path, mode="canvas", password=""):
    """Export PDF as ODT using anyconvert."""
    return export_document(doc, source_pdf_path, output_odt_path, "odt", mode=mode, password=password)


def export_pdf_as_pptx(doc, source_pdf_path, output_pptx_path, mode="canvas", password=""):
    """Export PDF as PPTX using anyconvert."""
    return export_document(doc, source_pdf_path, output_pptx_path, "pptx", mode=mode, password=password)


def export_pdf_as_odp(doc, source_pdf_path, output_odp_path, mode="canvas", password=""):
    """Export PDF as ODP using anyconvert."""
    return export_document(doc, source_pdf_path, output_odp_path, "odp", mode=mode, password=password)


def export_pdf_as_text(doc, output_txt_path, source_pdf_path=None, mode="canvas", password=""):
    """Export PDF as Plain Text (TXT) using anyconvert."""
    return export_document(
        doc=doc,
        source_pdf_path=source_pdf_path,
        output_path=output_txt_path,
        target_format="txt",
        mode=mode,
        password=password,
    )

def get_image_rgba_bytes(doc, xref):
    """Extract image as RGBA PNG bytes, compositing alpha/smask if present."""
    try:
        image_data = doc.extract_image(xref)
        if not image_data or 'image' not in image_data:
            return None

        smask_xref = image_data.get('smask', 0)
        if not smask_xref:
            try:
                smask_val = doc.xref_get_key(xref, "SMask")
                if smask_val and smask_val[0] == "xref":
                    smask_xref = int(smask_val[1].split()[0])
            except Exception:
                pass

        base_pix = fitz.Pixmap(doc, xref)

        # If soft mask (alpha transparency) is present
        if smask_xref and smask_xref > 0:
            try:
                mask_pix = fitz.Pixmap(doc, smask_xref)
                if base_pix.n != 3:
                    base_pix = fitz.Pixmap(fitz.csRGB, base_pix)
                if mask_pix.n != 1:
                    mask_pix = fitz.Pixmap(fitz.csGRAY, mask_pix)
                if base_pix.width == mask_pix.width and base_pix.height == mask_pix.height:
                    rgba_pix = fitz.Pixmap(base_pix, mask_pix)
                    return rgba_pix.tobytes("png")
                else:
                    from PIL import Image
                    import io
                    base_img = Image.open(io.BytesIO(base_pix.tobytes("png"))).convert("RGB")
                    mask_img = Image.open(io.BytesIO(mask_pix.tobytes("png"))).convert("L")
                    mask_img = mask_img.resize(base_img.size, Image.Resampling.LANCZOS)
                    base_img.putalpha(mask_img)
                    out_buf = io.BytesIO()
                    base_img.save(out_buf, format="PNG")
                    return out_buf.getvalue()
            except Exception as mask_err:
                print(f"Warning: smask compositing failed for xref {xref}: {mask_err}")

        # If base pixmap itself has alpha channel
        if base_pix.alpha:
            if base_pix.n != 4:
                base_pix = fitz.Pixmap(fitz.csRGB, base_pix)
            return base_pix.tobytes("png")

        # If CMYK without alpha, convert to standard RGB PNG
        if base_pix.n >= 4:
            rgb_pix = fitz.Pixmap(fitz.csRGB, base_pix)
            return rgb_pix.tobytes("png")

        # Standard image (JPEG, non-transparent PNG, etc.)
        return image_data["image"]
    except Exception as e:
        print(f"Warning: get_image_rgba_bytes failed for xref {xref}: {e}")
        try:
            return doc.extract_image(xref).get("image")
        except Exception:
            return None

def extract_editable_images(doc, page_index):
    """Extract raster image objects and bounding boxes from a PDF page."""
    editable_images = []
    if not doc or not (0 <= page_index < doc.page_count):
        return [], _("err_invalid_doc_page_extract")
    
    try:
        page = doc.load_page(page_index)
        image_info_list = page.get_image_info(xrefs=True)
        
        if not image_info_list:
            image_info_list = []
        
        for img_info in image_info_list:
            try:
                bbox = img_info.get('bbox')
                xref = img_info.get('xref')
                
                if not bbox or not xref:
                    continue
 
                rect = fitz.Rect(bbox)
                if rect.is_empty or not rect.is_valid:
                    continue

                # Full-page background image (e.g. from flattening or scanned page) is static and not editable
                if (abs(rect.x0) <= 2 and abs(rect.y0) <= 2 and
                        abs(rect.width - page.rect.width) <= 2 and
                        abs(rect.height - page.rect.height) <= 2):
                    continue
 
                try:
                    image_bytes = get_image_rgba_bytes(doc, xref)
                    if not image_bytes:
                        continue
                    
                    img_rot = 0.0
                    transform = img_info.get('transform')
                    if transform and len(transform) >= 4:
                        try:
                            a, b = float(transform[0]), float(transform[1])
                            if abs(b) > 1e-3 or abs(a - round(a)) > 1e-3 or a < 0:
                                calc_ang = round(math.degrees(math.atan2(-b, a)), 1) % 360.0
                                if 0.5 < calc_ang < 359.5:
                                    img_rot = calc_ang
                        except Exception:
                            img_rot = 0.0

                    if img_rot != 0.0:
                        cx = (rect.x0 + rect.x1) / 2.0
                        cy = (rect.y0 + rect.y1) / 2.0
                        rad = math.radians(-img_rot)
                        cos_a = math.cos(rad)
                        sin_a = math.sin(rad)
                        corners = [(rect.x0, rect.y0), (rect.x1, rect.y0), (rect.x1, rect.y1), (rect.x0, rect.y1)]
                        unrot_corners = []
                        for px, py in corners:
                            dx = px - cx
                            dy = py - cy
                            unrot_corners.append((dx * cos_a - dy * sin_a + cx, dx * sin_a + dy * cos_a + cy))
                        img_bbox = (
                            min(p[0] for p in unrot_corners),
                            min(p[1] for p in unrot_corners),
                            max(p[0] for p in unrot_corners),
                            max(p[1] for p in unrot_corners),
                        )
                    else:
                        img_bbox = (rect.x0, rect.y0, rect.x1, rect.y1)

                    image_obj = EditableImage(
                        bbox=img_bbox,
                        page_number=page_index,
                        xref=xref,
                        image_bytes=image_bytes,
                        rotation=img_rot
                    )
                    editable_images.append(image_obj)
                except Exception:
                    continue
                    
            except (ValueError, TypeError) as e:
                print(_("warn_image_skipped", page_index+1, img_info.get('xref'), e))
                continue
        
        return editable_images, None
    except Exception as e:
        error_msg = _("err_image_extract_page", page_index+1, e)
        print(error_msg)
        traceback.print_exc()
        return [], error_msg

def add_image_to_page(doc, page_number, image_path, rect):
    """Insert image bytes onto a PDF page at the specified bounding box."""
    if not doc or page_number is None:
        return False, _("err_invalid_doc_page_add_image")
    try:
        page = doc.load_page(page_number)
        page.insert_image(rect, filename=image_path)
        return True, None
    except FileNotFoundError:
        return False, _("err_image_file_not_found", image_path)
    except Exception as e:
        print(_("err_placing_image", e))
        traceback.print_exc()
        return False, _("err_placing_image", e)

def get_image_pixel_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    """Extract intrinsic pixel width and height from image bytes."""
    if not image_bytes:
        return 200, 200
    try:
        pix = fitz.Pixmap(image_bytes)
        w, h = int(pix.width), int(pix.height)
        pix = None
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    try:
        from gi.repository import GdkPixbuf
        loader = GdkPixbuf.PixbufLoader()
        loader.write(image_bytes)
        loader.close()
        pb = loader.get_pixbuf()
        if pb:
            return int(pb.get_width()), int(pb.get_height())
    except Exception:
        pass
    try:
        from PIL import Image
        with Image.open(io.BytesIO(image_bytes)) as img:
            return int(img.width), int(img.height)
    except Exception:
        pass
    return 200, 200

def delete_image_from_page(doc, image_obj: EditableImage):
    """Remove image drawing from page snapshot via targeted redaction."""
    if not doc or image_obj.page_number is None:
        return False, _("err_invalid_doc_page_delete_image")
    try:
        page = doc.load_page(image_obj.page_number)

        redact_rect = fitz.Rect(image_obj.bbox)
        if not redact_rect.is_empty and redact_rect.is_valid:
            page.add_redact_annot(redact_rect)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=0, text=1)
            except TypeError:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
            doc.load_page(image_obj.page_number)
            invalidate_page_cache(doc, image_obj.page_number)
            return True, None
        else:
            return False, _("err_invalid_image_bbox")
    except Exception as e:
        print(_("err_deleting_image", e))
        traceback.print_exc()
        return False, _("err_deleting_image", e)

def _detect_image_extension(data: bytes) -> str:
    """Detect image file extension based on magic header bytes."""
    if not data or len(data) < 2:
        return "png"
    if data.startswith(b"BM"):
        return "bmp"
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "webp"
    return "png"

def extract_image_data(doc, image_obj: EditableImage) -> Tuple[Optional[bytes], str]:
    """Extract raw image bytes and file extension from an EditableImage or PDF xref."""
    if not image_obj:
        return None, "png"

    if getattr(image_obj, 'raw_image_bytes', None):
        raw_b = image_obj.raw_image_bytes
        ext = _detect_image_extension(raw_b)
        return raw_b, ext

    if doc and getattr(image_obj, 'xref', None):
        try:
            img_dict = doc.extract_image(image_obj.xref)
            if img_dict and img_dict.get("image"):
                ext = img_dict.get("ext", "png")
                return img_dict["image"], ext
        except Exception as e:
            print(f"Warning: doc.extract_image failed for xref {image_obj.xref}: {e}")

    if getattr(image_obj, 'image_bytes', None):
        raw_b = image_obj.image_bytes
        ext = _detect_image_extension(raw_b)
        return raw_b, ext

    return None, "png"

def fit_image_to_aspect_ratio(image_bytes: bytes, target_bbox: Tuple[float, float, float, float]) -> bytes:
    """Fit image bytes into target bounding box aspect ratio using transparent padding.
    
    Ensures that when placed inside target_bbox via PyMuPDF page.replace_image(),
    the image maintains its original aspect ratio centered without stretching.
    """
    try:
        from PIL import Image, PngImagePlugin

        im = Image.open(io.BytesIO(image_bytes))
        img_w, img_h = im.size
        if img_w <= 0 or img_h <= 0:
            return image_bytes

        box_w = abs(target_bbox[2] - target_bbox[0])
        box_h = abs(target_bbox[3] - target_bbox[1])
        if box_w <= 0 or box_h <= 0:
            return image_bytes

        img_aspect = img_w / img_h
        box_aspect = box_w / box_h

        png_meta = PngImagePlugin.PngInfo()
        png_meta.add_text("stream_id", str(uuid.uuid4()))

        if abs(img_aspect - box_aspect) / box_aspect < 0.005:
            out_buf = io.BytesIO()
            im.save(out_buf, format="PNG", pnginfo=png_meta)
            return out_buf.getvalue()

        if img_aspect > box_aspect:
            canvas_w = img_w
            canvas_h = max(1, int(round(img_w / box_aspect)))
            x_offset = 0
            y_offset = (canvas_h - img_h) // 2
        else:
            canvas_h = img_h
            canvas_w = max(1, int(round(img_h * box_aspect)))
            x_offset = (canvas_w - img_w) // 2
            y_offset = 0

        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        im_rgba = im.convert("RGBA") if im.mode != "RGBA" else im
        canvas.paste(im_rgba, (x_offset, y_offset))

        out_buf = io.BytesIO()
        canvas.save(out_buf, format="PNG", pnginfo=png_meta)
        return out_buf.getvalue()
    except Exception as e:
        print(f"Warning: could not fit image to aspect ratio: {e}")
        return image_bytes

def replace_image_on_page(doc, image_obj: EditableImage, new_image_bytes: bytes) -> Tuple[bool, Optional[str], Optional[int]]:
    """Replace an existing embedded PDF image using PyMuPDF page.replace_image().
    
    Maintains the aspect ratio and bounding box of the image on the page.
    Returns (success, error_message, new_xref).
    """
    if not doc or image_obj.page_number is None:
        return False, _("err_invalid_doc_page_replace_image"), None

    try:
        page_num = image_obj.page_number
        page = doc.load_page(page_num)

        fitted_bytes = fit_image_to_aspect_ratio(new_image_bytes, image_obj.bbox)

        new_xref = None
        if getattr(image_obj, 'xref', None):
            page_images = page.get_images()
            xref_exists = any(img[0] == image_obj.xref for img in page_images)
            if xref_exists:
                page.replace_image(image_obj.xref, stream=fitted_bytes)
                new_xref = image_obj.xref
            else:
                rect = fitz.Rect(image_obj.bbox)
                page.add_redact_annot(rect)
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=0, text=0)
                page.insert_image(rect, stream=fitted_bytes, keep_proportion=False)
                if page.get_images():
                    new_xref = page.get_images()[-1][0]
        else:
            rect = fitz.Rect(image_obj.bbox)
            page.add_redact_annot(rect)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=0, text=0)
            page.insert_image(rect, stream=fitted_bytes, keep_proportion=False)
            if page.get_images():
                new_xref = page.get_images()[-1][0]

        image_obj.image_bytes = fitted_bytes
        if not getattr(image_obj, 'xref', None) and new_xref:
            image_obj.xref = new_xref
        image_obj.modified = True

        save_page_snapshot(doc, page_num, force=True)
        invalidate_page_cache(doc, page_num)
        return True, None, new_xref
    except Exception as e:
        error_msg = str(e)
        print(f"Error replacing image on page {image_obj.page_number}: {error_msg}")
        traceback.print_exc()
        return False, error_msg, None

def delete_shape_from_page(doc, shape_obj: EditableShape):
    """Remove vector shape from page snapshot via targeted redaction."""
    if not doc or shape_obj.page_number is None:
        return False, _("err_invalid_doc_page_delete_shape")
    try:
        page = doc.load_page(shape_obj.page_number)

        x0, y0, x1, y1 = shape_obj.bbox
        pad = max(getattr(shape_obj, 'stroke_width', 2.0) / 2.0 + 1.5, 2.0)
        redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        if not redact_rect.is_empty and redact_rect.is_valid:
            page.add_redact_annot(redact_rect)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
            except TypeError:
                try:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=True)
                except Exception:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            doc.load_page(shape_obj.page_number)
            invalidate_page_cache(doc, shape_obj.page_number)
            return True, None
        else:
            return False, _("err_invalid_shape_bbox")
    except Exception as e:
        print(_("err_deleting_shape", e))
        traceback.print_exc()
        return False, _("err_deleting_shape", e)

def delete_stroke_from_page(doc, stroke_obj: EditableStroke):
    """Remove freehand stroke from page snapshot via targeted redaction."""
    if not doc or stroke_obj.page_number is None:
        return False, "Invalid document or page number."
    try:
        page = doc.load_page(stroke_obj.page_number)
        x0, y0, x1, y1 = stroke_obj.bbox
        pad = max(getattr(stroke_obj, 'stroke_width', 2.0) / 2.0 + 1.5, 2.0)
        redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        if not redact_rect.is_empty and redact_rect.is_valid:
            page.add_redact_annot(redact_rect)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
            except TypeError:
                try:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=True)
                except Exception:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            doc.load_page(stroke_obj.page_number)
            invalidate_page_cache(doc, stroke_obj.page_number)
            return True, None
        return False, "Invalid stroke bounding box."
    except Exception as e:
        print(f"Error deleting stroke: {e}")
        traceback.print_exc()
        return False, str(e)



def extract_editable_shapes(doc, page_index):
    """Extract editable geometric shapes (rectangles, ellipses)."""
    editable_shapes = []
    if not doc or not (0 <= page_index < doc.page_count):
        return [], "Invalid document or page index for shape extraction."
    try:
        page = doc.load_page(page_index)
        drawings = page.get_drawings()
        baselines = _get_page_text_baselines(page)
        strikelines = _get_page_text_strikelines(page)
        for drawing in drawings:
            try:
                if _is_underline_drawing(drawing, baselines) or _is_strikethrough_drawing(drawing, strikelines):
                    continue
                items = drawing.get('items', [])
                if not items:
                    continue

                raw_fill = drawing.get('fill')
                raw_stroke = drawing.get('color')
                raw_width = drawing.get('width', 1.0)
                is_transparent = (raw_fill is None)
                fill_color = raw_fill if raw_fill else (1.0, 1.0, 1.0)
                stroke_color = raw_stroke if raw_stroke else (0.0, 0.0, 0.0)
                stroke_width = float(raw_width) if raw_width else 1.0

                # Check if rectangle:
                if len(items) == 1 and items[0][0] == 're':
                    r = fitz.Rect(items[0][1])
                    if r.width >= 2 and r.height >= 2:
                        shape_obj = EditableShape(
                            shape_type=EditableShape.SHAPE_RECTANGLE,
                            bbox=(r.x0, r.y0, r.x1, r.y1),
                            fill_color=fill_color,
                            stroke_color=stroke_color,
                            stroke_width=stroke_width,
                            page_number=page_index,
                            is_new=False,
                            is_transparent=is_transparent,
                            rotation=0.0
                        )
                        shape_obj.is_baked = True
                        editable_shapes.append(shape_obj)
                    continue

                # Check if ellipse:
                if len(items) == 4 and all(it[0] == 'c' for it in items):
                    rect = drawing.get('rect')
                    if rect:
                        r = fitz.Rect(rect)
                        if r.width >= 2 and r.height >= 2:
                            shape_obj = EditableShape(
                                shape_type=EditableShape.SHAPE_ELLIPSE,
                                bbox=(r.x0, r.y0, r.x1, r.y1),
                                fill_color=fill_color,
                                stroke_color=stroke_color,
                                stroke_width=stroke_width,
                                page_number=page_index,
                                is_new=False,
                                is_transparent=is_transparent,
                                rotation=0.0
                            )
                            shape_obj.is_baked = True
                            editable_shapes.append(shape_obj)
                    continue

                # If drawing is filled, treat as rectangle shape by bounding box
                if raw_fill is not None:
                    rect = drawing.get('rect')
                    if rect:
                        r = fitz.Rect(rect)
                        if r.width >= 2 and r.height >= 2:
                            shape_obj = EditableShape(
                                shape_type=EditableShape.SHAPE_RECTANGLE,
                                bbox=(r.x0, r.y0, r.x1, r.y1),
                                fill_color=fill_color,
                                stroke_color=stroke_color,
                                stroke_width=stroke_width,
                                page_number=page_index,
                                is_new=False,
                                is_transparent=False,
                                rotation=0.0
                            )
                            shape_obj.is_baked = True
                            editable_shapes.append(shape_obj)
            except Exception as item_err:
                print(f"Warning: skipping shape drawing item: {item_err}")
                continue

        return editable_shapes, None
    except Exception as e:
        error_msg = f"Error extracting shapes from page {page_index}: {e}"
        print(error_msg)
        return [], error_msg


def extract_editable_strokes(doc, page_index):
    """Extract editable freehand and highlighter strokes."""
    editable_strokes = []
    if not doc or not (0 <= page_index < doc.page_count):
        return [], "Invalid document or page index for stroke extraction."
    try:
        page = doc.load_page(page_index)
        drawings = page.get_drawings()
        baselines = _get_page_text_baselines(page)
        strikelines = _get_page_text_strikelines(page)
        for drawing in drawings:
            try:
                if _is_underline_drawing(drawing, baselines) or _is_strikethrough_drawing(drawing, strikelines):
                    continue
                items = drawing.get('items', [])
                if not items:
                    continue

                # Skip pure shapes (handled by extract_editable_shapes)
                if len(items) == 1 and items[0][0] == 're':
                    continue
                if len(items) == 4 and all(it[0] == 'c' for it in items):
                    continue
                if drawing.get('fill') is not None:
                    continue

                raw_stroke = drawing.get('color')
                raw_width = drawing.get('width', 1.0)
                raw_opacity = drawing.get('opacity')

                subpaths = []
                current_subpath = []
                for it in items:
                    if it[0] == 'l':
                        p1, p2 = (it[1].x, it[1].y), (it[2].x, it[2].y)
                        if current_subpath and current_subpath[-1] != p1:
                            subpaths.append(current_subpath)
                            current_subpath = [p1, p2]
                        else:
                            if not current_subpath:
                                current_subpath.append(p1)
                            current_subpath.append(p2)
                    elif it[0] == 'c':
                        p1, p4 = (it[1].x, it[1].y), (it[4].x, it[4].y)
                        if current_subpath and current_subpath[-1] != p1:
                            subpaths.append(current_subpath)
                            current_subpath = [p1, p4]
                        else:
                            if not current_subpath:
                                current_subpath.append(p1)
                            current_subpath.append(p4)
                if current_subpath:
                    subpaths.append(current_subpath)

                stroke_width = float(raw_width) if raw_width else 2.0
                is_hl = (stroke_width >= 8.0) or (raw_opacity is not None and raw_opacity < 0.9)
                tool_type = EditableStroke.TOOL_HIGHLIGHTER if is_hl else EditableStroke.TOOL_PEN
                opacity = float(raw_opacity) if raw_opacity is not None else (0.35 if is_hl else 1.0)
                stroke_color = raw_stroke if raw_stroke else (0.0, 0.0, 0.0)

                for sp in subpaths:
                    if sp and len(sp) >= 1:
                        stroke_obj = EditableStroke(
                            points=sp,
                            stroke_color=stroke_color,
                            stroke_width=stroke_width,
                            opacity=opacity,
                            tool_type=tool_type,
                            page_number=page_index,
                            is_new=False,
                            rotation=0.0
                        )
                        stroke_obj.is_baked = True
                        editable_strokes.append(stroke_obj)
            except Exception as item_err:
                print(f"Warning: skipping stroke drawing item: {item_err}")
                continue

        return editable_strokes, None
    except Exception as e:
        error_msg = f"Error extracting strokes from page {page_index}: {e}"
        print(error_msg)
        return [], error_msg


_WIDGET_TYPE_MAP = {
    getattr(fitz, "PDF_WIDGET_TYPE_TEXT", 7): "text",
    getattr(fitz, "PDF_WIDGET_TYPE_CHECKBOX", 2): "checkbox",
    getattr(fitz, "PDF_WIDGET_TYPE_COMBOBOX", 3): "combobox",
    getattr(fitz, "PDF_WIDGET_TYPE_LISTBOX", 4): "listbox",
    getattr(fitz, "PDF_WIDGET_TYPE_RADIOBUTTON", 5): "radio",
    getattr(fitz, "PDF_WIDGET_TYPE_BUTTON", 1): "button",
    getattr(fitz, "PDF_WIDGET_TYPE_SIGNATURE", 6): "signature",
    getattr(fitz, "PDF_WIDGET_TYPE_UNKNOWN", 0): "unknown",
}

def _normalize_widget_type(w) -> str:
    ftype_id = getattr(w, "field_type", None)
    flags = int(getattr(w, "field_flags", 0) or 0)
    btn_radio_flag = getattr(fitz, "PDF_BTN_FIELD_IS_RADIO", 98304)
    if ftype_id == getattr(fitz, "PDF_WIDGET_TYPE_BUTTON", 1) and (flags & btn_radio_flag):
        return "radio"
    if ftype_id in _WIDGET_TYPE_MAP:
        return _WIDGET_TYPE_MAP[ftype_id]
    type_str = str(getattr(w, "field_type_string", "")).lower()
    if "text" in type_str:
        return "text"
    if "check" in type_str:
        return "checkbox"
    if "combo" in type_str:
        return "combobox"
    if "list" in type_str:
        return "listbox"
    if "radio" in type_str:
        return "radio"
    if "button" in type_str:
        return "button"
    if "sign" in type_str:
        return "signature"
    return "unknown"

def _normalize_widget_color(col):
    if col is None:
        return None
    try:
        if isinstance(col, (int, float)):
            g = float(col)
            return (g, g, g)
        if isinstance(col, (list, tuple)):
            if len(col) == 1:
                g = float(col[0])
                return (g, g, g)
            elif len(col) == 3:
                return (float(col[0]), float(col[1]), float(col[2]))
            elif len(col) == 4:
                c, m, y, k = [float(v) for v in col]
                r = (1.0 - c) * (1.0 - k)
                g = (1.0 - m) * (1.0 - k)
                b = (1.0 - y) * (1.0 - k)
                return (max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)))
    except Exception:
        pass
    return None

def has_acroforms(doc) -> bool:
    """Check if the document contains any interactive AcroForm widgets."""
    if not doc or getattr(doc, "is_closed", False):
        return False
    try:
        if bool(getattr(doc, "is_form_pdf", False)):
            return True
        for p_idx in range(len(doc)):
            page = doc.load_page(p_idx)
            for _ in page.widgets():
                return True
    except Exception:
        pass
    return False

def extract_acroform_fields(doc, page_index=None):
    """Detect and extract interactive AcroForm fields from a PDF page or entire document."""
    if doc is None or getattr(doc, "is_closed", False):
        return [], "No document loaded."

    fields = []
    try:
        if page_index is not None:
            if not (0 <= page_index < len(doc)):
                return [], f"Invalid page index {page_index}."
            pages_to_scan = [(page_index, doc.load_page(page_index))]
        else:
            pages_to_scan = [(idx, doc.load_page(idx)) for idx in range(len(doc))]

        for p_idx, page in pages_to_scan:
            for w in page.widgets():
                try:
                    rect = (float(w.rect.x0), float(w.rect.y0), float(w.rect.x1), float(w.rect.y1))
                    field_name = str(w.field_name or "")
                    field_label = str(getattr(w, "field_label", "") or "")
                    ftype_id = getattr(w, "field_type", getattr(fitz, "PDF_WIDGET_TYPE_UNKNOWN", 0))
                    flags = int(getattr(w, "field_flags", 0) or 0)
                    ftype = _normalize_widget_type(w)

                    val = w.field_value
                    choices = list(w.choice_values) if getattr(w, "choice_values", None) else []
                    btn_states = None
                    if callable(getattr(w, "button_states", None)):
                        try:
                            btn_states = w.button_states()
                        except Exception:
                            btn_states = None

                    is_ro = bool(flags & getattr(fitz, "PDF_FIELD_IS_READ_ONLY", 1))
                    is_req = bool(flags & getattr(fitz, "PDF_FIELD_IS_REQUIRED", 2))
                    is_no_export = bool(flags & getattr(fitz, "PDF_FIELD_IS_NO_EXPORT", 4))
                    is_multi = bool(flags & getattr(fitz, "PDF_TX_FIELD_IS_MULTILINE", 4096))
                    is_pwd = bool(flags & getattr(fitz, "PDF_TX_FIELD_IS_PASSWORD", 8192))
                    is_comb = bool(flags & getattr(fitz, "PDF_TX_FIELD_IS_COMB", 16777216))

                    fontsize = float(getattr(w, "text_fontsize", 0.0) or 0.0)
                    t_col = _normalize_widget_color(getattr(w, "text_color", None))
                    f_col = _normalize_widget_color(getattr(w, "fill_color", None))
                    b_col = _normalize_widget_color(getattr(w, "border_color", None))
                    b_width = float(getattr(w, "border_width", 1.0) or 1.0)
                    max_len = int(getattr(w, "text_maxlen", 0) or 0)
                    xref = int(getattr(w, "xref", 0) or 0)

                    field_id = f"acro_{p_idx}_{xref}_{field_name}" if xref else str(uuid.uuid4())

                    field_obj = AcroFormField(
                        field_id=field_id,
                        xref=xref,
                        page_number=p_idx,
                        rect=rect,
                        field_name=field_name,
                        field_label=field_label,
                        field_type=ftype,
                        field_type_id=ftype_id,
                        value=val,
                        default_value=val,
                        choice_values=choices,
                        button_states=btn_states,
                        field_flags=flags,
                        is_read_only=is_ro,
                        is_required=is_req,
                        is_no_export=is_no_export,
                        is_multiline=is_multi,
                        is_password=is_pwd,
                        is_comb=is_comb,
                        max_length=max_len,
                        text_fontsize=fontsize,
                        text_color=t_col,
                        fill_color=f_col,
                        border_color=b_col,
                        border_width=b_width,
                        is_modified=False,
                    )
                    fields.append(field_obj)
                except Exception as w_err:
                    print(f"Warning: Failed to extract widget on page {p_idx}: {w_err}")
                    continue

        return fields, None
    except Exception as e:
        return [], f"Failed to extract AcroForm fields: {e}"

def update_acroform_field_value(doc, page_index: int, field_identifier: Any, new_value: Any) -> bool:
    """Update value of an AcroForm field in the document and refresh cache."""
    if not doc or getattr(doc, "is_closed", False) or not (0 <= page_index < len(doc)):
        return False
    try:
        page = doc.load_page(page_index)
        target_xref = getattr(field_identifier, "xref", None) if hasattr(field_identifier, "xref") else (field_identifier if isinstance(field_identifier, int) else None)
        target_name = getattr(field_identifier, "field_name", None) if hasattr(field_identifier, "field_name") else (field_identifier if isinstance(field_identifier, str) else None)

        updated = False
        for w in page.widgets():
            match = False
            if target_xref is not None and getattr(w, "xref", None) == target_xref:
                match = True
            elif target_name is not None and getattr(w, "field_name", None) == target_name:
                match = True

            if match:
                w.field_value = new_value
                if not getattr(w, 'border_color', None):
                    w.border_color = (0.35, 0.35, 0.35)
                    w.border_width = 1.0
                    w.border_style = "S"
                    if not getattr(w, 'fill_color', None):
                        w.fill_color = (1.0, 1.0, 1.0)
                w.update()
                updated = True
                break

        if updated:
            invalidate_page_cache(doc, page_index)
            return True
        return False
    except Exception as e:
        print(f"Error updating AcroForm field {field_identifier} on page {page_index}: {e}")
        return False

def get_acroform_field(doc, page_index: int, field_identifier: Any) -> Optional[AcroFormField]:
    """Retrieve an extracted AcroFormField matching the identifier on page_index."""
    fields, _ = extract_acroform_fields(doc, page_index=page_index)
    target_xref = getattr(field_identifier, "xref", None) if hasattr(field_identifier, "xref") else (field_identifier if isinstance(field_identifier, int) else None)
    target_name = getattr(field_identifier, "field_name", None) if hasattr(field_identifier, "field_name") else (field_identifier if isinstance(field_identifier, str) else None)
    target_id = getattr(field_identifier, "field_id", None) if hasattr(field_identifier, "field_id") else (field_identifier if isinstance(field_identifier, str) else None)

    for f in fields:
        if target_xref is not None and f.xref == target_xref:
            return f
        if target_id is not None and f.field_id == target_id:
            return f
        if target_name is not None and f.field_name == target_name:
            return f
    return None

def export_form_data(doc) -> Dict[str, Any]:
    """Export all AcroForm field values as a dictionary."""
    if not doc or getattr(doc, "is_closed", False):
        return {}
    data = {}
    fields, _ = extract_acroform_fields(doc, page_index=None)
    for f in fields:
        if f.field_name:
            data[f.field_name] = f.value
    return data

def import_form_data(doc, data: Dict[str, Any]) -> int:
    """Import values from dictionary into document AcroForm fields."""
    if not doc or not data or getattr(doc, "is_closed", False):
        return 0
    count = 0
    pages_to_invalidate = set()
    try:
        for p_idx in range(len(doc)):
            page = doc.load_page(p_idx)
            for w in page.widgets():
                fname = getattr(w, "field_name", None)
                if fname and fname in data:
                    w.field_value = data[fname]
                    w.update()
                    count += 1
                    pages_to_invalidate.add(p_idx)
        for p_idx in pages_to_invalidate:
            invalidate_page_cache(doc, p_idx)
    except Exception as e:
        print(f"Error importing form data: {e}")
    return count

def draw_acroform_overlay(cr, fields, zoom_level=1.0, active_field=None, is_design_mode=False):
    """Render interactive AcroForm field overlays with visual cues onto Cairo context."""
    if not fields:
        return

    zoom = float(zoom_level) if zoom_level > 0 else 1.0
    for f in fields:
        rect = getattr(f, "rect", None)
        if not rect or len(rect) != 4:
            continue
        x1, y1, x2, y2 = rect
        w = x2 - x1
        h = y2 - y1
        if w <= 0 or h <= 0:
            continue

        cr.save()
        is_active = (active_field is not None and (
            f is active_field or
            getattr(f, "xref", None) == getattr(active_field, "xref", -1) or
            getattr(f, "field_id", "") == getattr(active_field, "field_id", "")
        ))

        is_req = getattr(f, "is_required", False)
        is_ro = getattr(f, "is_read_only", False)

        if is_active:
            cr.set_source_rgba(0.2, 0.45, 0.9, 0.12)
            cr.rectangle(x1, y1, w, h)
            cr.fill()
            cr.set_source_rgba(0.15, 0.45, 0.9, 0.85)
            cr.set_line_width(1.5 / zoom)
            cr.rectangle(x1, y1, w, h)
            cr.stroke()
        elif is_design_mode:
            cr.set_source_rgba(0.3, 0.5, 0.8, 0.4)
            cr.set_line_width(1.0 / zoom)
            cr.set_dash([3.0 / zoom, 3.0 / zoom])
            cr.rectangle(x1, y1, w, h)
            cr.stroke()
        elif is_ro:
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.3)
            cr.set_line_width(1.0 / zoom)
            cr.set_dash([2.0 / zoom, 2.0 / zoom])
            cr.rectangle(x1, y1, w, h)
            cr.stroke()

        if is_req:
            marker_size = min(6.0 / zoom, w * 0.25, h * 0.25)
            cr.set_source_rgba(0.9, 0.2, 0.2, 0.85)
            cr.move_to(x1 + w, y1)
            cr.line_to(x1 + w - marker_size, y1)
            cr.line_to(x1 + w, y1 + marker_size)
            cr.close_path()
            cr.fill()

        cr.restore()



def ensure_form_widgets_have_appearance(doc) -> int:
    """Ensure all form widgets in the document have visible border and fill colors defined."""
    if not doc or getattr(doc, "is_closed", False):
        return 0
    updated_count = 0
    try:
        for p_idx in range(len(doc)):
            page = doc.load_page(p_idx)
            page_changed = False
            for w in list(page.widgets()):
                if getattr(w, 'field_type', None) == getattr(fitz, 'PDF_WIDGET_TYPE_SIGNATURE', 6):
                    continue
                needs_update = False
                if not getattr(w, 'border_color', None):
                    w.border_color = (0.35, 0.35, 0.35)
                    w.border_width = 1.0
                    w.border_style = "S"
                    needs_update = True
                if not getattr(w, 'fill_color', None):
                    w.fill_color = (1.0, 1.0, 1.0)
                    needs_update = True
                if needs_update:
                    try:
                        w.update()
                        page_changed = True
                        updated_count += 1
                    except Exception:
                        pass
            if page_changed:
                invalidate_page_cache(doc, p_idx)
    except Exception as e:
        print(f"Error ensuring form widgets appearance: {e}")
    return updated_count


def draw_measurement_to_cairo(cr, measurement, scale_calib=None, zoom_level=1.0):
    """Draw a MeasurementObject (distance line or area polygon) to Cairo context."""
    if not measurement or not hasattr(measurement, 'measurement_type'):
        return
    cr.save()
    if measurement.measurement_type == MeasurementObject.TYPE_DISTANCE and len(measurement.points) >= 2:
        p0, p1 = measurement.points[0], measurement.points[1]
        sx, sy = p0
        ex, ey = p1
        pt_len = math.hypot(ex - sx, ey - sy)
        if pt_len > 0.0:
            cr.set_source_rgba(measurement.color[0], measurement.color[1], measurement.color[2], 0.95)
            cr.set_line_width(measurement.stroke_width / zoom_level)

            # Main dimension line
            cr.move_to(sx, sy)
            cr.line_to(ex, ey)
            cr.stroke()

            # Perpendicular ticks
            theta = math.atan2(ey - sy, ex - sx)
            perp = theta + math.pi / 2.0
            tick_h = 7.0 / zoom_level
            dx_p = tick_h * math.cos(perp)
            dy_p = tick_h * math.sin(perp)

            cr.move_to(sx - dx_p, sy - dy_p)
            cr.line_to(sx + dx_p, sy + dy_p)
            cr.stroke()

            cr.move_to(ex - dx_p, ey - dy_p)
            cr.line_to(ex + dx_p, ey + dy_p)
            cr.stroke()

            # Vertex circles
            rad = 3.0 / zoom_level
            cr.arc(sx, sy, rad, 0, 2 * math.pi)
            cr.stroke()
            cr.arc(ex, ey, rad, 0, 2 * math.pi)
            cr.stroke()

            # Midpoint readout badge
            mx = (sx + ex) / 2.0
            my = (sy + ey) / 2.0
            badge_str = getattr(measurement, 'label', None) or measurement.format_measurement(scale_calib)

            cr.set_font_size(max(10.0 / zoom_level, 9.0))
            ext = cr.text_extents(badge_str)
            pad_x = 6.0 / zoom_level
            pad_y = 3.0 / zoom_level
            bw = ext.width + pad_x * 2.0
            bh = ext.height + pad_y * 2.0
            bx = mx - bw / 2.0
            by = my - bh / 2.0 - (12.0 / zoom_level)

            cr.set_source_rgba(0.12, 0.15, 0.20, 0.88)
            cr.rectangle(bx, by, bw, bh)
            cr.fill()

            cr.set_source_rgba(measurement.color[0], measurement.color[1], measurement.color[2], 0.95)
            cr.set_line_width(1.0 / zoom_level)
            cr.rectangle(bx, by, bw, bh)
            cr.stroke()

            cr.set_source_rgb(1.0, 1.0, 1.0)
            cr.move_to(bx + pad_x - ext.x_bearing, by + pad_y - ext.y_bearing)
            cr.show_text(badge_str)

    elif measurement.measurement_type == MeasurementObject.TYPE_AREA and len(measurement.points) >= 3:
        cr.move_to(measurement.points[0][0], measurement.points[0][1])
        for p in measurement.points[1:]:
            cr.line_to(p[0], p[1])
        cr.close_path()

        # Fill
        cr.set_source_rgba(measurement.fill_color[0], measurement.fill_color[1], measurement.fill_color[2], measurement.fill_color[3])
        cr.fill_preserve()

        # Border
        cr.set_source_rgba(measurement.color[0], measurement.color[1], measurement.color[2], 0.95)
        cr.set_line_width(measurement.stroke_width / zoom_level)
        cr.stroke()

        # Vertex markers
        rad = 3.0 / zoom_level
        for p in measurement.points:
            cr.arc(p[0], p[1], rad, 0, 2 * math.pi)
            cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            cr.fill_preserve()
            cr.set_source_rgba(measurement.color[0], measurement.color[1], measurement.color[2], 1.0)
            cr.stroke()

        # Centroid readout badge
        cx, cy = measurement.get_centroid()
        badge_str = getattr(measurement, 'label', None) or measurement.format_measurement(scale_calib)

        cr.set_font_size(max(10.0 / zoom_level, 9.0))
        ext = cr.text_extents(badge_str)
        pad_x = 6.0 / zoom_level
        pad_y = 3.0 / zoom_level
        bw = ext.width + pad_x * 2.0
        bh = ext.height + pad_y * 2.0
        bx = cx - bw / 2.0
        by = cy - bh / 2.0

        cr.set_source_rgba(0.12, 0.15, 0.20, 0.88)
        cr.rectangle(bx, by, bw, bh)
        cr.fill()

        cr.set_source_rgba(measurement.color[0], measurement.color[1], measurement.color[2], 0.95)
        cr.set_line_width(1.0 / zoom_level)
        cr.rectangle(bx, by, bw, bh)
        cr.stroke()

        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.move_to(bx + pad_x - ext.x_bearing, by + pad_y - ext.y_bearing)
        cr.show_text(badge_str)

    cr.restore()


def add_form_widget(
    target: Any,
    *args,
    **kwargs
) -> Optional[fitz.Widget]:
    """Create and insert an interactive PDF form widget annotation on a page.
    
    Supports both signatures:
    - add_form_widget(page, field_type, rect, field_name, default_value=None, choice_values=None, ...)
    - add_form_widget(doc, page_index, field_type, rect, field_name, default_value=None, choice_values=None, ...)
    """
    if target is None:
        return None
    try:
        if hasattr(target, "load_page"):
            doc = target
            if args and isinstance(args[0], int):
                p_idx = args[0]
                page = doc.load_page(p_idx)
                remaining = args[1:]
            elif "page_index" in kwargs:
                p_idx = kwargs.pop("page_index")
                page = doc.load_page(p_idx)
                remaining = args
            else:
                p_idx = 0
                page = doc.load_page(0)
                remaining = args
        else:
            page = target
            doc = getattr(page, "parent", None)
            p_idx = getattr(page, "number", 0)
            remaining = args

        field_type = remaining[0] if len(remaining) > 0 else kwargs.get("field_type", "text")
        rect = remaining[1] if len(remaining) > 1 else kwargs.get("rect", (100, 100, 250, 130))
        field_name = remaining[2] if len(remaining) > 2 else kwargs.get("field_name", "")
        default_value = remaining[3] if len(remaining) > 3 else kwargs.get("default_value", None)
        choice_values = remaining[4] if len(remaining) > 4 else kwargs.get("choice_values", None)
        is_multiline = kwargs.get("is_multiline", False)
        is_required = kwargs.get("is_required", False)
        is_read_only = kwargs.get("is_read_only", False)
        text_fontsize = kwargs.get("text_fontsize", 0.0)

        w = fitz.Widget()
        x0, y0, x1, y1 = rect
        w.rect = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        w.border_color = (0.35, 0.35, 0.35)
        w.border_width = 1.0
        w.border_style = "S"
        w.fill_color = (1.0, 1.0, 1.0)
        
        ftype = str(field_type).lower()
        if ftype in ("text", "tx"):
            w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            if is_multiline:
                w.field_flags |= fitz.PDF_TX_FIELD_IS_MULTILINE
            if default_value is not None:
                w.field_value = str(default_value)
        elif ftype in ("checkbox", "check", "cb"):
            w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
            w.field_value = bool(default_value)
        elif ftype in ("combobox", "choice", "dropdown", "ch"):
            w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
            choices = list(choice_values) if choice_values else ["Option 1", "Option 2", "Option 3"]
            w.choice_values = choices
            w.field_value = str(default_value) if default_value is not None else choices[0]
        elif ftype in ("listbox", "list"):
            w.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
            choices = list(choice_values) if choice_values else ["Option 1", "Option 2", "Option 3"]
            w.choice_values = choices
            w.field_value = str(default_value) if default_value is not None else choices[0]
        elif ftype in ("signature", "sig"):
            w.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE

        if is_required:
            w.field_flags |= fitz.PDF_FIELD_IS_REQUIRED
        if is_read_only:
            w.field_flags |= fitz.PDF_FIELD_IS_READ_ONLY
        if text_fontsize:
            w.text_fontsize = float(text_fontsize)

        if field_name:
            w.field_name = str(field_name)
        else:
            w.field_name = f"field_{p_idx}_{len(list(page.widgets())) + 1}"

        added = page.add_widget(w)
        target_w = added if added is not None else w
        try:
            target_w.update()
        except Exception:
            pass
        if doc is not None:
            invalidate_page_cache(doc, p_idx)
        return added or w
    except Exception as e:
        print(f"Error adding form widget: {e}")
        return None


def delete_form_widget(target: Any, field_identifier: Any, page_index: Optional[int] = None) -> bool:
    """Delete an interactive AcroForm widget annotation from a page or document."""
    if target is None:
        return False
    try:
        if hasattr(target, "load_page"):
            doc = target
            if page_index is not None:
                pages_to_check = [page_index]
            else:
                pages_to_check = list(range(len(doc)))
        else:
            page = target
            doc = getattr(page, "parent", None)
            pages_to_check = [getattr(page, "number", 0)]

        target_xref = getattr(field_identifier, "xref", None) if hasattr(field_identifier, "xref") else (field_identifier if isinstance(field_identifier, int) else None)
        target_name = getattr(field_identifier, "field_name", None) if hasattr(field_identifier, "field_name") else (field_identifier if isinstance(field_identifier, str) else None)

        deleted = False
        for p_idx in pages_to_check:
            page = doc.load_page(p_idx) if hasattr(target, "load_page") else target
            for w in list(page.widgets()):
                match = False
                if target_xref is not None and getattr(w, "xref", None) == target_xref:
                    match = True
                elif target_name is not None and getattr(w, "field_name", None) == target_name:
                    match = True
                if match:
                    page.delete_widget(w)
                    deleted = True
                    if doc is not None:
                        invalidate_page_cache(doc, p_idx)
                    break
            if deleted:
                break
        return deleted
    except Exception as e:
        print(f"Error deleting form widget: {e}")
        return False


def update_form_widget_geometry(
    target: Any,
    field_identifier: Any,
    new_rect: Tuple[float, float, float, float],
    page_index: Optional[int] = None
) -> bool:
    """Update the bounding rectangle of an existing form widget in a PDF page."""
    if target is None or not new_rect or len(new_rect) != 4:
        return False
    try:
        if hasattr(target, "load_page"):
            doc = target
            if page_index is not None:
                pages_to_check = [page_index]
            else:
                pages_to_check = list(range(len(doc)))
        else:
            page = target
            doc = getattr(page, "parent", None)
            pages_to_check = [getattr(page, "number", 0)]

        target_xref = getattr(field_identifier, "xref", None) if hasattr(field_identifier, "xref") else (field_identifier if isinstance(field_identifier, int) else None)
        target_name = getattr(field_identifier, "field_name", None) if hasattr(field_identifier, "field_name") else (field_identifier if isinstance(field_identifier, str) else None)

        x0, y0, x1, y1 = new_rect
        target_fitz_rect = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

        updated = False
        for p_idx in pages_to_check:
            page = doc.load_page(p_idx) if hasattr(target, "load_page") else target
            for w in list(page.widgets()):
                match = False
                if target_xref is not None and getattr(w, "xref", None) == target_xref:
                    match = True
                elif target_name is not None and getattr(w, "field_name", None) == target_name:
                    match = True
                if match:
                    w.rect = target_fitz_rect
                    if not getattr(w, 'border_color', None):
                        w.border_color = (0.35, 0.35, 0.35)
                        w.border_width = 1.0
                        w.border_style = "S"
                        if not getattr(w, 'fill_color', None):
                            w.fill_color = (1.0, 1.0, 1.0)
                    w.update()
                    updated = True
                    if doc is not None:
                        invalidate_page_cache(doc, p_idx)
                    break
            if updated:
                break
        return updated
    except Exception as e:
        print(f"Error updating form widget geometry: {e}")
        return False


def update_form_widget_choices(
    target: Any,
    field_identifier: Any,
    new_choices: List[str],
    page_index: Optional[int] = None
) -> bool:
    """Update choice values (options) of a combobox/listbox form widget."""
    if target is None:
        return False
    try:
        if hasattr(target, "load_page"):
            doc = target
            if page_index is not None:
                pages_to_check = [page_index]
            else:
                pages_to_check = list(range(len(doc)))
        else:
            page = target
            doc = getattr(page, "parent", None)
            pages_to_check = [getattr(page, "number", 0)]

        target_xref = getattr(field_identifier, "xref", None) if hasattr(field_identifier, "xref") else (field_identifier if isinstance(field_identifier, int) else None)
        target_name = getattr(field_identifier, "field_name", None) if hasattr(field_identifier, "field_name") else (field_identifier if isinstance(field_identifier, str) else None)

        updated = False
        for p_idx in pages_to_check:
            page = doc.load_page(p_idx) if hasattr(target, "load_page") else target
            for w in list(page.widgets()):
                match = False
                if target_xref is not None and getattr(w, "xref", None) == target_xref:
                    match = True
                elif target_name is not None and getattr(w, "field_name", None) == target_name:
                    match = True
                if match:
                    w.choice_values = list(new_choices)
                    if new_choices and w.field_value not in new_choices:
                        w.field_value = new_choices[0]
                    if not getattr(w, 'border_color', None):
                        w.border_color = (0.35, 0.35, 0.35)
                        w.border_width = 1.0
                        w.border_style = "S"
                        if not getattr(w, 'fill_color', None):
                            w.fill_color = (1.0, 1.0, 1.0)
                    w.update()
                    updated = True
                    if doc is not None:
                        invalidate_page_cache(doc, p_idx)
                    break
            if updated:
                break
        return updated
    except Exception as e:
        print(f"Error updating form widget choices: {e}")
        return False




_page_snapshots: dict = CompressedSnapshotStore()
_page_original_links: dict = {}
_page_pre_ocr_snapshots: dict = CompressedSnapshotStore()
# Maps md5(snapshot content) -> {xobject resource name: xref}. Keyed by content digest
# so it survives page re-keying of _page_snapshots.
_snapshot_xobject_names: dict = {}

def _content_digest(content: bytes) -> str:
    import hashlib
    return hashlib.md5(content).hexdigest()

def save_page_snapshot(doc, page_num: int, force: bool = False):
    """Cache an unedited copy of a PDF page to allow cleanly erasing original objects."""
    key = (id(doc), page_num)
    if key in _page_snapshots and not force:
        return  
    try:
        page = doc.load_page(page_num)
        page.clean_contents()
        xrefs = page.get_contents()
        content = b""
        for xref in xrefs:
            raw = doc.xref_stream(xref)
            if raw:
                content += raw
        _page_snapshots[key] = content
        _page_original_links[key] = page.get_links()
        try:
            names = {}
            for img in doc.get_page_images(page_num):
                names[img[7]] = img[0]
            for xo in doc.get_page_xobjects(page_num):
                names.setdefault(xo[1], xo[0])
            _snapshot_xobject_names[_content_digest(content)] = names
        except Exception:
            pass
    except Exception as e:
        print(f"Warning: could not save snapshot for page {page_num}: {e}")


def restore_page_from_snapshot(doc, page_num: int) -> bool:
    """Restore a page from its cached snapshot state."""
    key = (id(doc), page_num)
    if key not in _page_snapshots:
        return False
    try:
        content = _page_snapshots[key]
        page = doc.load_page(page_num)
        page.clean_contents()
        xrefs = page.get_contents()
        if xrefs:
            doc.update_stream(xrefs[0], content)
            for extra_xref in xrefs[1:]:
                try:
                    doc.xref_set_key(extra_xref, "Length", "0")
                    doc.update_stream(extra_xref, b"")
                except Exception:
                    pass
        else:
            xref = doc._newXref()
            doc.update_stream(xref, content)

        bindings = _snapshot_xobject_names.get(_content_digest(content), {})
        if bindings:
            current = {}
            for img in doc.get_page_images(page_num):
                current[img[7]] = img[0]
            for xo in doc.get_page_xobjects(page_num):
                current.setdefault(xo[1], xo[0])
            for name, xobj_xref in bindings.items():
                if current.get(name) == xobj_xref:
                    continue
                try:
                    doc.xref_set_key(page.xref, f"Resources/XObject/{name}", f"{xobj_xref} 0 R")
                except Exception:
                    try:
                        res = doc.xref_get_key(page.xref, "Resources")
                        if res[0] == "xref":
                            res_xref = int(res[1].split()[0])
                            doc.xref_set_key(res_xref, f"XObject/{name}", f"{xobj_xref} 0 R")
                    except Exception as bind_err:
                        print(f"Warning: could not rebind xobject {name}: {bind_err}")

        original_links = _page_original_links.get(key, [])
        original_signatures = set()
        for link in original_links:
            rect = link.get("from")
            rect_tuple = (rect.x0, rect.y0, rect.x1, rect.y1) if rect else (0, 0, 0, 0)
            sig = (link.get("kind"), rect_tuple, link.get("uri"))
            original_signatures.add(sig)
            
        current_links = page.get_links()
        for link in current_links:
            rect = link.get("from")
            rect_tuple = (rect.x0, rect.y0, rect.x1, rect.y1) if rect else (0, 0, 0, 0)
            sig = (link.get("kind"), rect_tuple, link.get("uri"))
            if sig not in original_signatures:
                page.delete_link(link)
                
        invalidate_page_cache(doc, page_num)
        return True
    except Exception as e:
        print(f"Warning: could not restore snapshot for page {page_num}: {e}")
        return False

def release_page_snapshots(doc):
    """Release and clear all cached page snapshots for a document."""
    doc_id = id(doc)
    keys_to_remove = [k for k in _page_snapshots if k[0] == doc_id]
    for k in keys_to_remove:
        _page_snapshots.pop(k, None)
        if k in _page_original_links:
            del _page_original_links[k]
    ocr_keys = [k for k in _page_pre_ocr_snapshots if k[0] == doc_id]
    for k in ocr_keys:
        _page_pre_ocr_snapshots.pop(k, None)
    gc.collect(1)

def _apply_single_object_to_page(doc, page, obj):
    """Render a single object (text, image, shape, stroke) onto a PDF page with transforms."""
    rot = getattr(obj, "rotation", 0.0) % 360.0

    if isinstance(obj, EditableText):
        if obj.text:
            font_arg, error_msg = _get_font_args_for_pymupdf(obj)
            if error_msg:
                return False, error_msg
            lines = obj.text.split('\n')
            line_height = obj.font_size * 1.2
            
            base_name = getattr(obj, "pdf_fontname_base14", "helv")
            is_bold = getattr(obj, "is_bold", False)
            is_italic = getattr(obj, "is_italic", False)
            calc_font = _get_base14_font_variant(base_name, is_bold, is_italic)
            
            fontname = font_arg.get("fontname", "helv")
            fontfile = font_arg.get("fontfile", None)
            font_obj = None
            try:
                font_obj = fitz.Font(fontname=fontname, fontfile=fontfile)
            except Exception:
                pass

            cx = (obj.bbox[0] + obj.bbox[2]) / 2.0 if obj.bbox else obj.x
            cy = (obj.bbox[1] + obj.bbox[3]) / 2.0 if obj.bbox else obj.y
            morph = (fitz.Point(cx, cy), fitz.Matrix(-rot)) if rot != 0.0 else None
            mat = get_rotation_matrix(cx, cy, rot) if rot != 0.0 else None

            align = getattr(obj, 'alignment', 'left')
            box_w = (obj.bbox[2] - obj.bbox[0]) if obj.bbox and (obj.bbox[2] > obj.bbox[0]) else None

            for i, line in enumerate(lines):
                links = list(re.finditer(r'(https?://[^\s]+|www\.[^\s]+)', line))
                
                if font_obj:
                    try:
                        text_len = font_obj.text_length(line, fontsize=obj.font_size)
                    except Exception:
                        text_len = fitz.get_text_length(line, fontname=calc_font, fontsize=obj.font_size)
                else:
                    text_len = fitz.get_text_length(line, fontname=calc_font, fontsize=obj.font_size)

                w_avail = box_w if box_w and box_w > text_len else text_len
                if align == 'center':
                    line_start_x = obj.x + max(0.0, (w_avail - text_len) / 2.0)
                elif align == 'right':
                    line_start_x = obj.x + max(0.0, w_avail - text_len)
                else:
                    line_start_x = obj.x

                has_obj_link = bool(getattr(obj, 'link_url', None))
                if not links and not has_obj_link:
                    is_justified = (align == 'justify' and box_w and box_w > text_len and i < len(lines) - 1)
                    words = line.split(' ') if is_justified else None
                    if is_justified and words and len(words) > 1:
                        word_lens = []
                        for w in words:
                            if font_obj:
                                try:
                                    wl = font_obj.text_length(w, fontsize=obj.font_size)
                                except Exception:
                                    wl = fitz.get_text_length(w, fontname=calc_font, fontsize=obj.font_size)
                            else:
                                wl = fitz.get_text_length(w, fontname=calc_font, fontsize=obj.font_size)
                            word_lens.append(wl)
                        total_w = sum(word_lens)
                        space_w = (box_w - total_w) / (len(words) - 1)
                        curr_wx = obj.x
                        for w, wl in zip(words, word_lens):
                            if w:
                                pos = fitz.Point(curr_wx, obj.baseline + (i * line_height))
                                page.insert_text(pos, w, fontsize=obj.font_size,
                                                 color=obj.color, overlay=True, morph=morph, **font_arg)
                            curr_wx += wl + space_w
                        line_draw_x = obj.x
                        draw_len = box_w
                    else:
                        pos = fitz.Point(line_start_x, obj.baseline + (i * line_height))
                        page.insert_text(pos, line, fontsize=obj.font_size,
                                         color=obj.color, overlay=True, morph=morph, **font_arg)
                        line_draw_x = line_start_x
                        draw_len = text_len
                    
                    if getattr(obj, 'is_underline', False):
                        p1 = fitz.Point(line_draw_x, obj.baseline + (i * line_height) + 1.5)
                        p2 = fitz.Point(line_draw_x + draw_len, obj.baseline + (i * line_height) + 1.5)
                        if mat:
                            p1 = p1 * mat
                            p2 = p2 * mat
                        page.draw_line(p1, p2, color=obj.color, width=0.8)

                    if getattr(obj, 'is_strikethrough', False):
                        sp1 = fitz.Point(line_draw_x, obj.baseline + (i * line_height) - (obj.font_size * 0.3))
                        sp2 = fitz.Point(line_draw_x + draw_len, obj.baseline + (i * line_height) - (obj.font_size * 0.3))
                        if mat:
                            sp1 = sp1 * mat
                            sp2 = sp2 * mat
                        page.draw_line(sp1, sp2, color=obj.color, width=0.8)
                else:
                    if not links and has_obj_link:
                        segments = [(line, True, obj.link_url)]
                    else:
                        segments = []
                        last_idx = 0
                        for match in links:
                            start, end = match.start(), match.end()
                            if start > last_idx:
                                segments.append((line[last_idx:start], False, None))
                            segments.append((line[start:end], True, match.group(0)))
                            last_idx = end
                        if last_idx < len(line):
                            segments.append((line[last_idx:], False, None))
                        
                    current_x = line_start_x
                    for seg_item in segments:
                        seg_text = seg_item[0]
                        is_seg_link = seg_item[1]
                        seg_uri = seg_item[2] if len(seg_item) > 2 else (seg_text if is_seg_link else None)
                        if not seg_text:
                            continue
                        
                        seg_color = obj.color if getattr(obj, 'link_url', None) else ((0.0, 0.33, 0.8) if is_seg_link else obj.color)
                        pos = fitz.Point(current_x, obj.baseline + (i * line_height))
                        page.insert_text(pos, seg_text, fontsize=obj.font_size,
                                         color=seg_color, overlay=True, morph=morph, **font_arg)
                        
                        if font_obj:
                            try:
                                seg_len = font_obj.text_length(seg_text, fontsize=obj.font_size)
                            except Exception:
                                seg_len = fitz.get_text_length(seg_text, fontname=calc_font, fontsize=obj.font_size)
                        else:
                            seg_len = fitz.get_text_length(seg_text, fontname=calc_font, fontsize=obj.font_size)
                        
                        if is_seg_link or getattr(obj, 'is_underline', False):
                            p1 = fitz.Point(current_x, obj.baseline + (i * line_height) + 1.5)
                            p2 = fitz.Point(current_x + seg_len, obj.baseline + (i * line_height) + 1.5)
                            if mat:
                                p1 = p1 * mat
                                p2 = p2 * mat
                            page.draw_line(p1, p2, color=seg_color, width=0.8)

                        if getattr(obj, 'is_strikethrough', False):
                            sp1 = fitz.Point(current_x, obj.baseline + (i * line_height) - (obj.font_size * 0.3))
                            sp2 = fitz.Point(current_x + seg_len, obj.baseline + (i * line_height) - (obj.font_size * 0.3))
                            if mat:
                                sp1 = sp1 * mat
                                sp2 = sp2 * mat
                            page.draw_line(sp1, sp2, color=seg_color, width=0.8)
                            
                        if is_seg_link:
                            y0 = obj.baseline + (i * line_height) - obj.font_size
                            y1 = obj.baseline + (i * line_height) + (obj.font_size * 0.2)
                            link_rect = fitz.Rect(current_x, y0, current_x + seg_len, y1)
                            
                            uri = seg_uri or seg_text
                            if not uri.startswith(("http://", "https://", "mailto:")):
                                uri = "https://" + uri
                                
                            link_from = link_rect.quad * mat if mat else link_rect.quad
                            rect = link_from.rect if hasattr(link_from, 'rect') else fitz.Rect(link_from)
                            link_data = {"kind": fitz.LINK_URI, "from": rect, "uri": uri}
                            page.insert_link(link_data)
                            
                        current_x += seg_len
                        
    elif isinstance(obj, EditableImage):
        rect = fitz.Rect(obj.bbox)
        cx = (rect.x0 + rect.x1) / 2.0
        cy = (rect.y0 + rect.y1) / 2.0
        w = rect.x1 - rect.x0
        h = rect.y1 - rect.y0

        img_bytes = getattr(obj, 'image_bytes', None)
        if not img_bytes and getattr(obj, 'xref', None):
            try:
                img_bytes = get_image_rgba_bytes(doc, obj.xref)
                obj.image_bytes = img_bytes
            except Exception:
                pass

        if not img_bytes:
            return False, "Image bytes missing"

        opacity = getattr(obj, 'opacity', 1.0)
        if opacity < 1.0:
            try:
                from PIL import Image
                im_op = Image.open(io.BytesIO(img_bytes))
                if im_op.mode != "RGBA":
                    im_op = im_op.convert("RGBA")
                r_ch, g_ch, b_ch, a_ch = im_op.split()
                a_ch = a_ch.point(lambda p: int(p * opacity))
                im_op = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))
                buf_op = io.BytesIO()
                im_op.save(buf_op, format="PNG")
                img_bytes = buf_op.getvalue()
            except Exception as e:
                print(f"Warning: image opacity adjustment failed: {e}")

        if getattr(obj, 'is_patch', False) and getattr(obj, 'purge_underlying_text', True):
            try:
                page.add_redact_annot(rect)
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0, text=0)
            except Exception as e:
                print(f"Warning: could not purge underlying text under patch: {e}")

        if rot == 0.0:
            page.insert_image(rect, stream=img_bytes, keep_proportion=False)
        elif rot % 90 == 0:
            if int(rot) % 180 == 90:
                target_rect = fitz.Rect(cx - h / 2.0, cy - w / 2.0, cx + h / 2.0, cy + w / 2.0)
            else:
                target_rect = rect
            pdf_rot = (360 - int(rot)) % 360
            page.insert_image(target_rect, stream=img_bytes, rotate=pdf_rot, keep_proportion=False)
        else:
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(img_bytes))
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                rotated_im = im.rotate(-rot, expand=True, resample=Image.BICUBIC)
                buf = io.BytesIO()
                rotated_im.save(buf, format="PNG")
                stream = buf.getvalue()
                rad = math.radians(rot)
                nw = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
                nh = abs(w * math.sin(rad)) + abs(h * math.cos(rad))
                rot_rect = fitz.Rect(cx - nw / 2.0, cy - nh / 2.0, cx + nw / 2.0, cy + nh / 2.0)
                page.insert_image(rot_rect, stream=stream, keep_proportion=False)
            except Exception as e:
                print(f"Warning: PIL image rotation failed: {e}")
                page.insert_image(rect, stream=img_bytes, keep_proportion=False)
    elif isinstance(obj, EditableShape):
        rect = fitz.Rect(obj.bbox)
        shape = page.new_shape()
        stroke = tuple(float(c) for c in obj.stroke_color)
        fill = tuple(float(c) for c in obj.fill_color) if not obj.is_transparent else None
        cx = (rect.x0 + rect.x1) / 2.0
        cy = (rect.y0 + rect.y1) / 2.0
        mat = get_rotation_matrix(cx, cy, rot) if rot != 0.0 else None

        if obj.shape_type == EditableShape.SHAPE_RECTANGLE:
            if mat:
                shape.draw_quad(rect.quad * mat)
            else:
                shape.draw_rect(rect)
            shape.finish(color=stroke, fill=fill, width=obj.stroke_width)
        elif obj.shape_type == EditableShape.SHAPE_ELLIPSE:
            if mat:
                k = 0.5522847498307935
                rx = (rect.x1 - rect.x0) / 2.0
                ry = (rect.y1 - rect.y0) / 2.0
                beziers = [
                    (fitz.Point(cx + rx, cy), fitz.Point(cx + rx, cy - k * ry), fitz.Point(cx + k * rx, cy - ry), fitz.Point(cx, cy - ry)),
                    (fitz.Point(cx, cy - ry), fitz.Point(cx - k * rx, cy - ry), fitz.Point(cx - rx, cy - k * ry), fitz.Point(cx - rx, cy)),
                    (fitz.Point(cx - rx, cy), fitz.Point(cx - rx, cy + k * ry), fitz.Point(cx - k * rx, cy + ry), fitz.Point(cx, cy + ry)),
                    (fitz.Point(cx, cy + ry), fitz.Point(cx + k * rx, cy + ry), fitz.Point(cx + rx, cy + k * ry), fitz.Point(cx + rx, cy))
                ]
                for p0, c1, c2, p1 in beziers:
                    shape.draw_bezier(p0 * mat, c1 * mat, c2 * mat, p1 * mat)
            else:
                shape.draw_oval(rect)
            shape.finish(color=stroke, fill=fill, width=obj.stroke_width)
        elif obj.shape_type == EditableShape.SHAPE_CHECKMARK:
            pts = obj.get_checkmark_points()
            fitz_pts = [fitz.Point(p[0], p[1]) * mat if mat else fitz.Point(p[0], p[1]) for p in pts]
            shape.draw_polyline(fitz_pts)
            shape.finish(color=stroke, fill=None, width=obj.stroke_width, lineCap=1, lineJoin=1, closePath=False)
        elif obj.shape_type == EditableShape.SHAPE_CROSS:
            lines = obj.get_cross_lines()
            for (p1, p2) in lines:
                pt1 = fitz.Point(p1[0], p1[1]) * mat if mat else fitz.Point(p1[0], p1[1])
                pt2 = fitz.Point(p2[0], p2[1]) * mat if mat else fitz.Point(p2[0], p2[1])
                shape.draw_line(pt1, pt2)
            shape.finish(color=stroke, fill=None, width=obj.stroke_width, lineCap=1, lineJoin=1, closePath=False)
        else:
            if mat:
                shape.draw_quad(rect.quad * mat)
            else:
                shape.draw_rect(rect)
            shape.finish(color=stroke, fill=fill, width=obj.stroke_width)
        shape.commit()
    elif isinstance(obj, EditableStroke):
        if obj.points and len(obj.points) >= 2:
            shape = page.new_shape()
            pts = [fitz.Point(p[0], p[1]) for p in obj.points]
            if rot != 0.0 and obj.bbox:
                cx = (obj.bbox[0] + obj.bbox[2]) / 2.0
                cy = (obj.bbox[1] + obj.bbox[3]) / 2.0
                mat = get_rotation_matrix(cx, cy, rot)
                pts = [p * mat for p in pts]
            shape.draw_polyline(pts)
            stroke = tuple(float(c) for c in obj.stroke_color)
            is_hl = getattr(obj, 'tool_type', None) in (EditableStroke.TOOL_HIGHLIGHTER, "highlighter") or obj.stroke_width >= 8.0
            cap = 2 if is_hl else 1
            join = 2 if is_hl else 1
            shape.finish(
                color=stroke,
                width=obj.stroke_width,
                stroke_opacity=getattr(obj, 'opacity', 1.0),
                lineCap=cap,
                lineJoin=join,
                closePath=False
            )
            shape.commit()
        elif obj.points and len(obj.points) == 1:
            p = fitz.Point(obj.points[0][0], obj.points[0][1])
            if rot != 0.0 and obj.bbox:
                cx = (obj.bbox[0] + obj.bbox[2]) / 2.0
                cy = (obj.bbox[1] + obj.bbox[3]) / 2.0
                nx, ny = rotate_point(p.x, p.y, cx, cy, rot)
                p = fitz.Point(nx, ny)
            r = max(obj.stroke_width / 2.0, 1.0)
            rect = fitz.Rect(p.x - r, p.y - r, p.x + r, p.y + r)
            shape = page.new_shape()
            is_hl = getattr(obj, 'tool_type', None) in (EditableStroke.TOOL_HIGHLIGHTER, "highlighter") or obj.stroke_width >= 8.0
            if is_hl:
                shape.draw_rect(rect)
            else:
                shape.draw_oval(rect)
            stroke = tuple(float(c) for c in obj.stroke_color)
            shape.finish(
                color=stroke,
                fill=stroke,
                fill_opacity=getattr(obj, 'opacity', 1.0),
                stroke_opacity=getattr(obj, 'opacity', 1.0)
            )
            shape.commit()
    elif isinstance(obj, MeasurementObject):
        shape = page.new_shape()
        color = tuple(float(c) for c in obj.color[:3])
        if obj.measurement_type == MeasurementObject.TYPE_DISTANCE and len(obj.points) >= 2:
            p0 = fitz.Point(obj.points[0][0], obj.points[0][1])
            p1 = fitz.Point(obj.points[1][0], obj.points[1][1])
            shape.draw_line(p0, p1)
            theta = math.atan2(p1.y - p0.y, p1.x - p0.x)
            perp = theta + math.pi / 2.0
            dx_p = 7.0 * math.cos(perp)
            dy_p = 7.0 * math.sin(perp)
            shape.draw_line(fitz.Point(p0.x - dx_p, p0.y - dy_p), fitz.Point(p0.x + dx_p, p0.y + dy_p))
            shape.draw_line(fitz.Point(p1.x - dx_p, p1.y - dy_p), fitz.Point(p1.x + dx_p, p1.y + dy_p))
            shape.finish(color=color, width=obj.stroke_width)
            shape.commit()

            label_text = getattr(obj, 'label', None) or f"{math.hypot(p1.x - p0.x, p1.y - p0.y):.1f} pt"
            mx = (p0.x + p1.x) / 2.0
            my = (p0.y + p1.y) / 2.0
            try:
                page.insert_text(fitz.Point(mx, my - 6.0), label_text, fontsize=9.0, color=(0, 0, 0))
            except Exception:
                pass
        elif obj.measurement_type == MeasurementObject.TYPE_AREA and len(obj.points) >= 3:
            pts = [fitz.Point(p[0], p[1]) for p in obj.points]
            shape.draw_polyline(pts + [pts[0]])
            fill_c = tuple(float(c) for c in obj.fill_color[:3])
            fill_op = float(obj.fill_color[3]) if len(obj.fill_color) > 3 else 0.2
            shape.finish(color=color, fill=fill_c, fill_opacity=fill_op, width=obj.stroke_width)
            shape.commit()

            label_text = getattr(obj, 'label', None) or f"{obj.compute_raw_value():.1f} pt²"
            cx, cy = obj.get_centroid()
            try:
                page.insert_text(fitz.Point(cx, cy), label_text, fontsize=9.0, color=(0, 0, 0))
            except Exception:
                pass
    elif isinstance(obj, StickyNoteObject):
        annot = page.add_text_annot((obj.x, obj.y), obj.content, icon=obj.icon_type)
        annot.set_info(
            title=obj.author,
            content=obj.content,
            creationDate=obj.created_at,
            modDate=obj.modified_at,
        )
        annot.set_colors(stroke=obj.color)
        annot.update()
        obj.native_annot = annot
    return True, None

def _default_layer_rank(obj):
    if isinstance(obj, EditableImage):
        return 0
    if isinstance(obj, EditableShape):
        return 1
    if isinstance(obj, EditableStroke):
        return 2
    if isinstance(obj, EditableText):
        return 3
    return 4

def sort_by_layer(objs):
    """Return objects in bottom-to-top order.

    Objects with an explicit z_index come first, ordered by it; objects without one
    (never reordered, or newly added) follow in default type order, keeping list order.
    """
    def key(item):
        idx, obj = item
        z = getattr(obj, 'z_index', None)
        if z is not None:
            return (0, z, 0, idx)
        return (1, 0, _default_layer_rank(obj), idx)
    return [o for _, o in sorted(enumerate(objs), key=key)]

def rebuild_page(doc, page_num: int, all_texts, all_shapes, all_images,
                 exclude_obj=None, all_strokes=None, all_measurements=None,
                 all_sticky_notes=None):
    """Re-render page from snapshot applying all active editable objects."""
    if not restore_page_from_snapshot(doc, page_num):
        print(f"Warning: no snapshot for page {page_num}, skipping restore")
    try:
        page = doc.load_page(page_num)
        seen_objs = set()
        to_bake = []
        groups = (
            (all_images, True), (all_shapes, True), (all_strokes, True),
            (all_texts, True), (all_measurements, False), (all_sticky_notes, False),
        )
        for coll, needs_flag in groups:
            for obj in (coll or []):
                if id(obj) in seen_objs or getattr(obj, 'page_number', None) != page_num or obj is exclude_obj:
                    continue
                seen_objs.add(id(obj))
                if needs_flag and not (getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False)):
                    continue
                to_bake.append(obj)
        for obj in sort_by_layer(to_bake):
            _apply_single_object_to_page(doc, page, obj)
            obj.is_baked = True
        invalidate_page_cache(doc, page_num)
        return True, None
    except Exception as e:
        print(f"ERROR: rebuild_page failed for page {page_num}: {e}")
        traceback.print_exc()
        return False, str(e)

def apply_object_edit(doc, obj):
    """Burn a modified canvas object into its target PDF page stream."""
    if not doc or not hasattr(obj, 'page_number') or obj.page_number is None:
        return False, "Invalid object or page number."
    try:
        page = doc.load_page(obj.page_number)
        res, err = _apply_single_object_to_page(doc, page, obj)
        invalidate_page_cache(doc, obj.page_number)
        return res, err
    except Exception as e:
        print(f"ERROR: An error occurred while applying object edit: {e}")
        traceback.print_exc()
        return False, f"Error while applying object edit: {e}"
    
def create_new_pdf(width=595, height=842, num_pages=1):
    """Create new PDF with customizable dimensions and page count."""
    try:
        doc = fitz.open()
        w = float(width) if width else 595.0
        h = float(height) if height else 842.0
        pages = max(1, int(num_pages)) if num_pages else 1
        for _ in range(pages):
            doc.new_page(width=w, height=h)
        return doc, None
    except Exception as e:
        return None, _("err_creating_new_pdf", e)

def insert_blank_page(doc, page_index=None, width=None, height=None):
    """Insert a new empty PDF page with specified width and height at target index."""
    try:
        if width is None or height is None:
            if doc.page_count > 0:
                first_page = doc[0]
                default_width = first_page.rect.width
                default_height = first_page.rect.height
            else:
                default_width = 595
                default_height = 842
            
            if width is None:
                width = default_width
            if height is None:
                height = default_height
        
        doc_id = id(doc)
        global _page_snapshots, _page_original_links
        if page_index is not None and 0 <= page_index <= doc.page_count:
            target_pno = int(page_index)
            new_snapshots = {}
            for (did, pno), content in _page_snapshots.raw_items():
                if did == doc_id and pno >= target_pno:
                    new_snapshots[(did, pno + 1)] = content
                else:
                    new_snapshots[(did, pno)] = content
            _page_snapshots.clear()
            _page_snapshots.update(new_snapshots)

            new_links = {}
            for (did, pno), links in _page_original_links.items():
                if did == doc_id and pno >= target_pno:
                    new_links[(did, pno + 1)] = links
                else:
                    new_links[(did, pno)] = links
            _page_original_links = new_links

            doc.new_page(pno=target_pno, width=width, height=height)
        else:
            doc.new_page(width=width, height=height)

        invalidate_page_cache(doc)
        return True, _("success_blank_page_added", doc.page_count)
    
    except Exception as e:
        return False, _("err_adding_page", e)

def merge_pdf_pages(target_doc, source_pdf_path, insert_position=None):
    """Merge PDF pages."""
    try:
        source_doc = fitz.open(source_pdf_path)
        source_page_count = source_doc.page_count
        
        if source_page_count == 0:
            return False, _("err_source_pdf_empty"), 0
        
        target_doc.insert_pdf(source_doc, from_page=0, to_page=source_page_count - 1)
        
        source_doc.close()
        invalidate_page_cache(target_doc)
        
        return True, _("success_merged_pages", source_page_count), source_page_count
    
    except Exception as e:
        return False, _("err_merging_pdf", e), 0

def move_page(doc, from_index, to_index):
    """Reorder a page from from_index to to_index in document."""
    try:
        if from_index < 0 or from_index >= doc.page_count:
            return False, _("err_invalid_page_index")
        
        if to_index < 0 or to_index >= doc.page_count:
            return False, _("err_invalid_target_index")
        
        if from_index == to_index:
            return True, _("success_page_already_there")
        
        if from_index < to_index:
            fitz_target = -1 if to_index >= doc.page_count - 1 else to_index + 1
        else:
            fitz_target = to_index
        doc.move_page(from_index, fitz_target)
        
        doc_id = id(doc)
        global _page_snapshots, _page_original_links
        def _remap_index(p):
            if from_index < to_index:
                if p == from_index: return to_index
                if from_index < p <= to_index: return p - 1
            else:
                if p == from_index: return to_index
                if to_index <= p < from_index: return p + 1
            return p

        new_snapshots = {}
        for (did, pno), content in _page_snapshots.raw_items():
            if did == doc_id:
                new_snapshots[(did, _remap_index(pno))] = content
            else:
                new_snapshots[(did, pno)] = content
        _page_snapshots.clear()
        _page_snapshots.update(new_snapshots)

        new_links = {}
        for (did, pno), links in _page_original_links.items():
            if did == doc_id:
                new_links[(did, _remap_index(pno))] = links
            else:
                new_links[(did, pno)] = links
        _page_original_links = new_links

        invalidate_page_cache(doc)
        
        return True, _("success_page_moved", from_index + 1, to_index + 1)
    
    except Exception as e:
        return False, _("err_moving_page", e)

def delete_page(doc, page_index):
    """Remove the page at index from document."""
    try:
        if not doc:
            return False, _("err_no_doc_msg_alt")
        
        if doc.page_count <= 1:
            return False, _("err_cannot_delete_last_page")
        
        if page_index < 0 or page_index >= doc.page_count:
            return False, _("err_invalid_page_index_val", page_index + 1)
        
        doc.delete_page(page_index)
        
        doc_id = id(doc)
        global _page_snapshots, _page_original_links
        new_snapshots = {}
        for (did, pno), content in _page_snapshots.raw_items():
            if did == doc_id:
                if pno == page_index:
                    continue
                elif pno > page_index:
                    new_snapshots[(did, pno - 1)] = content
                else:
                    new_snapshots[(did, pno)] = content
            else:
                new_snapshots[(did, pno)] = content
        _page_snapshots.clear()
        _page_snapshots.update(new_snapshots)

        new_links = {}
        for (did, pno), links in _page_original_links.items():
            if did == doc_id:
                if pno == page_index:
                    continue
                elif pno > page_index:
                    new_links[(did, pno - 1)] = links
                else:
                    new_links[(did, pno)] = links
            else:
                new_links[(did, pno)] = links
        _page_original_links = new_links

        invalidate_page_cache(doc)
        return True, _("success_page_deleted", page_index + 1)
    
    except Exception as e:
        return False, _("err_deleting_page", e)

def rotate_page(doc, page_index: int, angle_delta: int):
    """Rotate the specified page by angle_delta degrees (e.g. 90 or -90)."""
    if not doc or not (0 <= page_index < doc.page_count):
        return False, _("err_invalid_page_index")
    try:
        page = doc.load_page(page_index)
        cur_rot = getattr(page, 'rotation', 0) or 0
        new_rot = (cur_rot + angle_delta) % 360
        page.set_rotation(new_rot)
        invalidate_page_cache(doc, page_index)
        return True, new_rot
    except Exception as e:
        return False, str(e)

def get_page_rotation(doc, page_index: int) -> int:
    """Get the current rotation of the specified page in degrees."""
    if not doc or not (0 <= page_index < doc.page_count):
        return 0
    try:
        page = doc.load_page(page_index)
        return getattr(page, 'rotation', 0) or 0
    except Exception:
        return 0

def add_highlight_annotation(doc, page_index, rect_unzoomed, color=(1, 0.93, 0), is_visual=False, rotation=0.0):
    """Add highlight annotation."""
    if not doc or not (0 <= page_index < doc.page_count):
        return False, "Invalid document or page index."
    try:
        page = doc.load_page(page_index)
        r = fitz.Rect(*rect_unzoomed)
        if is_visual and page.rotation % 360 != 0:
            r = (r * (~page.rotation_matrix)).normalize()
        if r.is_empty or not r.is_valid:
            return False, "Empty or invalid rect."
        rot = float(rotation) % 360.0
        if rot != 0.0:
            cx = (r.x0 + r.x1) / 2.0
            cy = (r.y0 + r.y1) / 2.0
            mat = get_rotation_matrix(cx, cy, rot)
            annot = page.add_highlight_annot(quads=r.quad * mat)
        else:
            annot = page.add_highlight_annot(r)
        annot.set_colors(stroke=color)
        annot.update()
        invalidate_page_cache(doc, page_index)
        return True, None
    except Exception as e:
        traceback.print_exc()
        return False, f"Highlight annotation error: {e}"

def remove_highlight_annotations(doc, page_index, rect_unzoomed=None, is_visual=False):
    """Remove highlight annotations."""
    if not doc or not (0 <= page_index < doc.page_count):
        return False, "Invalid document or page index."
    try:
        page = doc.load_page(page_index)
        annots = page.annots()
        removed_count = 0
        
        if annots:
            target_rect = None
            if rect_unzoomed:
                target_rect = fitz.Rect(*rect_unzoomed)
                if is_visual and page.rotation % 360 != 0:
                    target_rect = (target_rect * (~page.rotation_matrix)).normalize()
            
            for annot in annots:
                annot_type = annot.type[0]
                if annot_type == 8:
                    if target_rect is None or target_rect.intersects(annot.rect):
                        page.delete_annot(annot)
                        removed_count += 1
        
        if removed_count > 0:
            invalidate_page_cache(doc, page_index)
        return True, removed_count
    except Exception as e:
        traceback.print_exc()
        return False, f"Error removing highlights: {e}"

def get_text_in_rect(doc, page_index, rect_unzoomed):
    """Get the text in rect."""
    if not doc or not (0 <= page_index < doc.page_count):
        return ""
    try:
        page = doc.load_page(page_index)
        r = fitz.Rect(*rect_unzoomed)
        if page.rotation % 360 != 0:
            r = (r * (~page.rotation_matrix)).normalize()
        words = page.get_text("words", clip=r, sort=True)
        return " ".join(w[4] for w in words)
    except Exception as e:
        print(f"get_text_in_rect error: {e}")
        return ""

def get_word_at_pos(doc, page_index, pos_unzoomed):
    """Get the word at pos."""
    if not doc or not (0 <= page_index < doc.page_count):
        return None
    try:
        page = doc.load_page(page_index)
        x, y = pos_unzoomed
        p = fitz.Point(x, y)
        rot_mat = page.rotation_matrix if page.rotation % 360 != 0 else None
        if rot_mat:
            p = p * (~rot_mat)
        words = page.get_text("words")
        for w in words:
            r = fitz.Rect(w[0], w[1], w[2], w[3])
            if r.contains(p):
                vis_r = (r * rot_mat).normalize() if rot_mat else r
                return {'bbox': (vis_r.x0, vis_r.y0, vis_r.x1, vis_r.y1), 'text': w[4]}
        # Fallback to tolerance-based hit-testing
        hit = hit_test_text_word_at_pos(page, pos_unzoomed, tolerance=2.5, visual_coords=True)
        if hit:
            return {
                'bbox': hit['visual_bbox'],
                'text': hit['word'],
                'font': hit.get('font'),
                'size': hit.get('font_size'),
                'baseline': hit.get('baseline'),
                'font_properties': hit.get('font_properties'),
            }
        return None
    except Exception as e:
        print(f"get_word_at_pos error: {e}")
        return None

def get_block_at_pos(doc, page_index, pos_unzoomed):
    """Get the block at pos."""
    if not doc or not (0 <= page_index < doc.page_count):
        return None
    try:
        page = doc.load_page(page_index)
        x, y = pos_unzoomed
        p = fitz.Point(x, y)
        rot_mat = page.rotation_matrix if page.rotation % 360 != 0 else None
        if rot_mat:
            p = p * (~rot_mat)
        
        text_dict = page.get_text("dict")
        for block in text_dict["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    r = fitz.Rect(line["bbox"])
                    if r.contains(p):
                        line_text = "".join(span["text"] for span in line["spans"])
                        vis_r = (r * rot_mat).normalize() if rot_mat else r
                        return {'bbox': (vis_r.x0, vis_r.y0, vis_r.x1, vis_r.y1), 'text': line_text}
        return None
    except Exception as e:
        print(f"get_block_at_pos error: {e}")
        return None

def export_merged_pdf(pages: list, output_path: str, primary_metadata_doc=None) -> bool:
    if not pages:
        return False
    merged_doc = fitz.open()
    temp_path = output_path + ".tmp_merged"
    try:
        page_map = {}
        for target_idx, entry in enumerate(pages):
            src_doc = entry.get("source_doc")
            p_idx = entry.get("page_index", 0)
            if src_doc and not src_doc.is_closed:
                merged_doc.insert_pdf(src_doc, from_page=p_idx, to_page=p_idx)
                key = (id(src_doc), p_idx + 1)
                page_map.setdefault(key, []).append(target_idx + 1)

        if merged_doc.page_count == 0:
            return False

        source_docs = []
        for entry in pages:
            doc = entry.get("source_doc")
            if doc and not doc.is_closed and doc not in source_docs:
                source_docs.append(doc)

        meta_doc = primary_metadata_doc if (primary_metadata_doc and not primary_metadata_doc.is_closed) else (source_docs[0] if source_docs else None)
        if meta_doc and meta_doc.metadata:
            meta = meta_doc.metadata.copy()
            merged_doc.set_metadata(meta)

        merged_toc = []
        seen_items = set()
        for doc in source_docs:
            try:
                toc = doc.get_toc()
                for item in toc:
                    lvl, title, pno = item[0], item[1], item[2]
                    key = (id(doc), pno)
                    target_pages = page_map.get(key, [])
                    for tgt_pno in target_pages:
                        dedup_key = (lvl, title, tgt_pno)
                        if dedup_key not in seen_items:
                            seen_items.add(dedup_key)
                            merged_toc.append([lvl, title, tgt_pno])
            except Exception:
                pass

        if merged_toc:
            merged_toc.sort(key=lambda x: x[2])
            norm_toc = []
            prev_lvl = 0
            for item in merged_toc:
                lvl = item[0]
                if prev_lvl == 0:
                    lvl = 1
                elif lvl > prev_lvl + 1:
                    lvl = prev_lvl + 1
                elif lvl < 1:
                    lvl = 1
                prev_lvl = lvl
                new_item = list(item)
                new_item[0] = lvl
                norm_toc.append(new_item)
            try:
                merged_doc.set_toc(norm_toc)
            except Exception:
                pass

        merged_doc.save(temp_path, garbage=3, deflate=True)
        merged_doc.close()
        import os
        os.replace(temp_path, output_path)
        return True
    finally:
        try:
            if not merged_doc.is_closed:
                merged_doc.close()
        except Exception:
            pass
        import os
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def embed_scale_calibration(doc, calibration_dict: dict) -> bool:
    """Store scale calibration metadata in the PDF catalog dictionary."""
    if not doc:
        return False
    try:
        import json
        cat = doc.pdf_catalog()
        serialized = json.dumps(calibration_dict)
        doc.xref_set_key(cat, "WordSysScaleCalibration", f"({serialized})")
        return True
    except Exception as e:
        print(f"Warning: failed to embed scale calibration in PDF catalog: {e}")
        return False


def extract_scale_calibration(doc) -> Optional[dict]:
    """Retrieve embedded scale calibration metadata from the PDF catalog dictionary."""
    if not doc:
        return None
    try:
        import json
        cat = doc.pdf_catalog()
        kind, val = doc.xref_get_key(cat, "WordSysScaleCalibration")
        if val:
            raw = val.strip()
            if raw.startswith("(") and raw.endswith(")"):
                raw = raw[1:-1]
            return json.loads(raw)
    except Exception as e:
        pass
    return None


def embed_measurements(doc, measurements_data: list) -> bool:
    """Store distance and area measurement objects metadata in the PDF catalog dictionary."""
    if not doc:
        return False
    try:
        import json
        cat = doc.pdf_catalog()
        serialized = json.dumps(measurements_data)
        doc.xref_set_key(cat, "WordSysMeasurements", f"({serialized})")
        return True
    except Exception as e:
        print(f"Warning: failed to embed measurements in PDF catalog: {e}")
        return False


def extract_measurements(doc) -> Optional[list]:
    """Retrieve embedded distance and area measurements from the PDF catalog dictionary."""
    if not doc:
        return None
    try:
        import json
        cat = doc.pdf_catalog()
        kind, val = doc.xref_get_key(cat, "WordSysMeasurements")
        if val:
            raw = val.strip()
            if raw.startswith("(") and raw.endswith(")"):
                raw = raw[1:-1]
            return json.loads(raw)
    except Exception:
        pass
    return None


def extract_sticky_notes(doc) -> Dict[int, List[StickyNoteObject]]:
    """Extract all text/sticky note annotations from document pages using fast metadata check."""
    notes_by_page = {}
    if not doc:
        return notes_by_page
    for p in range(doc.page_count):
        try:
            try:
                type_str, val_str = doc.xref_get_key(doc.page_xref(p), "Annots")
                if type_str == "null" or val_str == "null":
                    continue
            except Exception:
                pass

            page = doc.load_page(p)
            page_notes = []
            annots = page.annots()
            if annots:
                for a in annots:
                    if a.type[0] in (0, 1):  # Text / Note
                        info = a.info or {}
                        colors = a.colors or {}
                        stroke = colors.get("stroke") or (1.0, 0.86, 0.24)
                        note = StickyNoteObject(
                            page_number=p,
                            x=a.rect.x0,
                            y=a.rect.y0,
                            content=info.get("content", ""),
                            author=info.get("title", ""),
                            color=tuple(float(c) for c in stroke[:3]),
                            icon_type=info.get("name", "Comment"),
                            created_at=info.get("creationDate") or None,
                            modified_at=info.get("modDate") or None,
                            width=a.rect.width if a.rect.width > 0 else 24.0,
                            height=a.rect.height if a.rect.height > 0 else 24.0,
                            is_new=False,
                            native_annot=a,
                        )
                        page_notes.append(note)
            if page_notes:
                notes_by_page[p] = page_notes
        except Exception as e:
            print(f"Warning: error extracting sticky notes on page {p}: {e}")
    return notes_by_page


def sync_sticky_notes(doc, sticky_notes_by_page: dict) -> bool:
    """Synchronize session sticky notes as fitz.PDF_ANNOT_TEXT on document pages."""
    if not doc:
        return False
    try:
        for p in range(doc.page_count):
            page = doc.load_page(p)
            # 1. Remove all existing text/note annotations on this page
            for a in list(page.annots()):
                if a.type[0] in (0, 1):
                    page.delete_annot(a)
            # 2. Add current session sticky notes for this page
            session_notes = sticky_notes_by_page.get(p, []) if sticky_notes_by_page else []
            for note in session_notes:
                annot = page.add_text_annot((note.x, note.y), note.content, icon=note.icon_type)
                annot.set_info(
                    title=note.author,
                    content=note.content,
                    creationDate=note.created_at,
                    modDate=note.modified_at,
                )
                annot.set_colors(stroke=note.color)
                annot.update()
                note.native_annot = annot
                note.is_new = False
                note.modified = False
        invalidate_page_cache(doc)
        return True
    except Exception as e:
        print(f"Error synchronizing sticky notes to PDF: {e}")
        return False


def add_sticky_note_to_pdf(page, note: StickyNoteObject):
    """Add a StickyNoteObject as a native text annotation to a page."""
    annot = page.add_text_annot((note.x, note.y), note.content, icon=note.icon_type)
    annot.set_info(
        title=note.author,
        content=note.content,
        creationDate=note.created_at,
        modDate=note.modified_at,
    )
    annot.set_colors(stroke=note.color)
    annot.update()
    note.native_annot = annot
    note.is_new = False
    note.modified = False
    return annot


def get_sticky_notes_from_pdf(page, page_number: int = 0) -> List[StickyNoteObject]:
    """Extract sticky notes from a single page."""
    notes = []
    annots = page.annots()
    if annots:
        for a in annots:
            if a.type[0] in (0, 1):
                info = a.info or {}
                colors = a.colors or {}
                stroke = colors.get("stroke") or (1.0, 0.86, 0.24)
                note = StickyNoteObject(
                    page_number=page_number,
                    x=a.rect.x0,
                    y=a.rect.y0,
                    content=info.get("content", ""),
                    author=info.get("title", ""),
                    color=tuple(float(c) for c in stroke[:3]),
                    icon_type=info.get("name", "Comment"),
                    created_at=info.get("creationDate") or None,
                    modified_at=info.get("modDate") or None,
                    width=a.rect.width if a.rect.width > 0 else 24.0,
                    height=a.rect.height if a.rect.height > 0 else 24.0,
                    is_new=False,
                    native_annot=a,
                )
                notes.append(note)
    return notes


def apply_sticky_notes_to_pdf(doc, session) -> bool:
    """Synchronize sticky notes from session to doc."""
    sticky_dict = getattr(session, 'sticky_notes', {})
    return sync_sticky_notes(doc, sticky_dict)


def flatten_page_annotations(doc, page_num: int, include_forms: bool = False, session_objects: Optional[List[Any]] = None) -> tuple[bool, Optional[str]]:
    """Burn all annotations, highlights, marks, drawings, text, and optionally form fields on page_num
    directly into a high-resolution raster background stream (true OLED burn-in).

    All text, shapes, markings, and form entries are permanently flattened into pixels so they
    cannot be selected, extracted, or edited. Sticky notes are preserved as live interactive comments.
    """
    if not doc or page_num < 0 or page_num >= doc.page_count:
        return False, "Invalid document or page index"
    try:
        # 1. Create a 1-page temp document for page_num to compose all elements
        temp_doc = fitz.open()
        temp_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        tp = temp_doc[0]
        rect = tp.rect

        # 2. Apply any in-memory session objects onto the temp page so they are included in the burn-in
        if session_objects:
            for obj in session_objects:
                try:
                    if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                        _apply_single_object_to_page(temp_doc, tp, obj)
                except Exception as ex:
                    print(f"Warning applying object before burn-in: {ex}")

        # 3. Preserve sticky notes (PDF_ANNOT_TEXT): extract details and remove before rasterizing
        saved_notes = []
        annot = tp.first_annot
        while annot:
            if annot.type and annot.type[0] in (0, 1):
                info = annot.info or {}
                colors = annot.colors or {}
                stroke = colors.get("stroke") or (1.0, 0.86, 0.24)
                saved_notes.append({
                    'point': (annot.rect.x0, annot.rect.y0),
                    'content': info.get('content', ''),
                    'author': info.get('title', ''),
                    'icon': info.get('name', 'Comment'),
                    'color': tuple(float(c) for c in stroke[:3]) if stroke else (1.0, 0.86, 0.24),
                    'created_at': info.get('creationDate'),
                    'modified_at': info.get('modDate'),
                })
            annot = annot.next

        # Delete sticky notes from temp page so their icons are not rasterized into background
        while True:
            found = None
            annot = tp.first_annot
            while annot:
                if annot.type and annot.type[0] in (0, 1):
                    found = annot
                    break
                annot = annot.next
            if found:
                tp.delete_annot(found)
            else:
                break

        # 4. If form fields should NOT be burned in, preserve them as interactive widgets
        saved_widgets = []
        if not include_forms:
            for w in list(tp.widgets()):
                try:
                    saved_widgets.append({
                        'rect': fitz.Rect(w.rect),
                        'field_name': w.field_name,
                        'field_type': w.field_type,
                        'field_value': w.field_value,
                    })
                    tp.delete_widget(w)
                except Exception as ex:
                    print(f"Warning preserving widget: {ex}")

        # 5. Render high-resolution (300 DPI) lossless raster image (true OLED burn-in)
        zoom = 300.0 / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = tp.get_pixmap(matrix=mat, annots=True)
        img_bytes = pix.tobytes("png")

        # 6. Create clean replacement page with exact same dimensions and burn image into content stream
        burn_doc = fitz.open()
        bp = burn_doc.new_page(width=rect.width, height=rect.height)
        bp.insert_image(rect, stream=img_bytes)

        # 7. Restore preserved sticky notes as live interactive comments
        for sn in saved_notes:
            try:
                na = bp.add_text_annot(sn['point'], sn['content'], icon=sn['icon'])
                na.set_info(
                    title=sn['author'],
                    content=sn['content'],
                    creationDate=sn.get('created_at'),
                    modDate=sn.get('modified_at'),
                )
                if sn.get('color'):
                    na.set_colors(stroke=sn['color'])
                na.update()
            except Exception as e:
                print(f"Warning restoring sticky note after burn-in: {e}")

        # 8. Restore preserved form widgets if include_forms was False
        if not include_forms and saved_widgets:
            for sw in saved_widgets:
                try:
                    nw = fitz.Widget()
                    nw.rect = sw['rect']
                    nw.field_name = sw['field_name']
                    nw.field_type = sw['field_type']
                    nw.field_value = sw['field_value']
                    bp.add_widget(nw)
                except Exception as e:
                    print(f"Warning restoring widget: {e}")

        # 9. Replace page in original document
        doc.delete_page(page_num)
        doc.insert_pdf(burn_doc, from_page=0, to_page=0, start_at=page_num)
        burn_doc.close()
        temp_doc.close()

        if hasattr(doc, '_page_cache') and isinstance(doc._page_cache, dict):
            doc._page_cache.clear()

        invalidate_page_cache(doc, page_num)
        return True, None
    except Exception as e:
        print(f"Error flattening annotations on page {page_num}: {e}")
        traceback.print_exc()
        return False, str(e)


def flatten_document_annotations(doc, page_indices: Optional[List[int]] = None, include_forms: bool = False, session_objects_by_page: Optional[dict] = None) -> tuple[bool, Optional[str]]:
    """Flatten annotations across specified page indices (or all pages if None)."""
    if not doc:
        return False, "No document loaded"
    if page_indices is None:
        page_indices = list(range(doc.page_count))
    try:
        # Sort in reverse order to ensure page replacement does not affect lower indices
        for p in sorted(page_indices, reverse=True):
            objs = session_objects_by_page.get(p, []) if session_objects_by_page else None
            ok, err = flatten_page_annotations(doc, p, include_forms=include_forms, session_objects=objs)
            if not ok:
                return False, err
        invalidate_page_cache(doc)
        return True, None
    except Exception as e:
        print(f"Error flattening document annotations: {e}")
        traceback.print_exc()
        return False, str(e)


def is_digital_signature_supported() -> bool:
    """Return True if digital signature backend (pyHanko) is available."""
    try:
        from .digital_signature import is_pyhanko_available
        return is_pyhanko_available()
    except Exception:
        return False


def sign_pdf_document(
    pdf_bytes: bytes,
    pfx_data_or_path: Optional[bytes | str] = None,
    passphrase: str | bytes | None = None,
    field_name: Optional[str] = None,
    reason: Optional[str] = None,
    location: Optional[str] = None,
    contact_info: Optional[str] = None,
    signer_name: Optional[str] = None,
    page_index: int = 0,
    box: Optional[Tuple[float, float, float, float]] = None,
    page_height: Optional[float] = None,
    page_width: Optional[float] = None,
    visual_stamp: bool = True,
    signature_image_bytes: Optional[bytes] = None,
    custom_stamp_text: Optional[str] = None,
    certify: bool = False,
    docmdp_permissions: Optional[int] = None,
    validation_context: Optional[Any] = None,
    pades_profile: str = "B-B",
    tsa_config: Optional[Any] = None,
    timestamper: Optional[Any] = None,
    signer: Optional[Any] = None,
    pkcs11_driver: Optional[str] = None,
    pkcs11_slot_id: Optional[int] = None,
    pkcs11_token_label: Optional[str] = None,
    pkcs11_pin: Optional[str] = None,
    pkcs11_cert_label: Optional[str] = None,
    pkcs11_cert_id: Optional[bytes] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Sign PDF bytes using cryptographic digital signature engine."""
    from .digital_signature import sign_pdf_bytes
    return sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pfx_data_or_path=pfx_data_or_path,
        passphrase=passphrase,
        field_name=field_name,
        reason=reason,
        location=location,
        contact_info=contact_info,
        signer_name=signer_name,
        page_index=page_index,
        box=box,
        page_height=page_height,
        page_width=page_width,
        visual_stamp=visual_stamp,
        signature_image_bytes=signature_image_bytes,
        custom_stamp_text=custom_stamp_text,
        certify=certify,
        docmdp_permissions=docmdp_permissions,
        validation_context=validation_context,
        pades_profile=pades_profile,
        tsa_config=tsa_config,
        timestamper=timestamper,
        signer=signer,
        pkcs11_driver=pkcs11_driver,
        pkcs11_slot_id=pkcs11_slot_id,
        pkcs11_token_label=pkcs11_token_label,
        pkcs11_pin=pkcs11_pin,
        pkcs11_cert_label=pkcs11_cert_label,
        pkcs11_cert_id=pkcs11_cert_id,
    )



def inspect_document_signatures(doc_or_bytes_or_path) -> List[Dict[str, Any]]:
    """
    Inspect all digital signatures in a document and determine cryptographic integrity.
    Accepts a PyMuPDF Document instance, file path string, or raw bytes.
    """
    from .digital_signature import inspect_pdf_signatures
    if hasattr(doc_or_bytes_or_path, "name") and doc_or_bytes_or_path.name and os.path.exists(doc_or_bytes_or_path.name):
        try:
            with open(doc_or_bytes_or_path.name, "rb") as f:
                data = f.read()
            return inspect_pdf_signatures(data)
        except Exception:
            pass

    if hasattr(doc_or_bytes_or_path, "tobytes"):
        try:
            return inspect_pdf_signatures(doc_or_bytes_or_path.tobytes())
        except Exception:
            return []

    return inspect_pdf_signatures(doc_or_bytes_or_path)


inspect_digital_signatures = inspect_document_signatures

def extract_page_region_patch(
    doc: fitz.Document,
    page_number: int,
    bbox: Tuple[float, float, float, float],
    dpi: int = 300
) -> Optional[bytes]:
    """Extract a pixel-perfect PNG bitmap crop from a page region at specified DPI."""
    if not doc or not (0 <= page_number < len(doc)):
        return None
    try:
        x1, y1, x2, y2 = bbox
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)
        if (max_x - min_x) < 2.0 or (max_y - min_y) < 2.0:
            return None

        page = doc.load_page(page_number)
        unrot_box = fitz.Rect(min_x, min_y, max_x, max_y)
        if (page.rotation % 360) != 0:
            vis_box = (unrot_box * page.rotation_matrix).normalize()
        else:
            vis_box = unrot_box

        clip_rect = vis_box.intersect(page.rect)
        if clip_rect.is_empty or not clip_rect.is_valid:
            return None

        effective_dpi = max(72, dpi)
        pix = page.get_pixmap(clip=clip_rect, dpi=effective_dpi, annots=True)
        if not pix or pix.width <= 0 or pix.height <= 0:
            return None

        patch_bytes = pix.tobytes("png")
        pix = None
        return patch_bytes
    except Exception as e:
        print(f"Error extracting page patch: {e}")
        return None

def apply_redaction_marks(doc, redaction_marks_dict, images=None, graphics=None, text=None):
    """Permanently burn staged redaction marks into the PyMuPDF document with true stream purging."""
    if not doc or not redaction_marks_dict:
        return False
    applied = False
    img_flag = fitz.PDF_REDACT_IMAGE_PIXELS if images is None else images
    gfx_flag = fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED if graphics is None else graphics
    txt_flag = fitz.PDF_REDACT_TEXT_REMOVE if text is None else text

    try:
        for page_num, marks in list(redaction_marks_dict.items()):
            if page_num < 0 or page_num >= len(doc) or not marks:
                continue
            page = doc[page_num]
            for mark in marks:
                rect = fitz.Rect(mark.bbox)
                page.add_redact_annot(
                    rect,
                    text=getattr(mark, 'overlay_text', None) or "",
                    fill=getattr(mark, 'fill_color', (0.0, 0.0, 0.0)),
                    text_color=getattr(mark, 'text_color', (1.0, 1.0, 1.0)),
                    fontsize=getattr(mark, 'font_size', 11.0),
                    align=fitz.TEXT_ALIGN_CENTER,
                )
            page.apply_redactions(images=img_flag, graphics=gfx_flag, text=txt_flag)
            invalidate_page_cache(doc, page_num)
            applied = True
        return applied
    except Exception as e:
        print(f"Error applying redaction marks: {e}")
        return False


def sanitize_document(
    doc,
    strip_metadata: bool = True,
    purge_xmp: bool = True,
    purge_attachments: bool = True,
    purge_comments: bool = True,
    purge_hidden_layers: bool = True,
    purge_orphaned_toc: bool = True,
    redacted_pages: Optional[Set[int]] = None,
    strip_bookmarks: bool = False,
    preserve_links: bool = True,
    preserve_forms: bool = True,
    purge_thumbnails: bool = True,
    purge_javascript: bool = True,
    scrub_document_id: bool = True,
) -> dict:
    """Document-wide sanitization routine to purge sensitive metadata, XMP packets,
    attachments, hidden layers, comments, and orphaned/redacted bookmark references.
    Also strips embedded page thumbnails, JavaScript/interactive actions, and randomizes trailer ID.
    """
    if not doc:
        return {"success": False, "error": "No document provided"}

    results = {
        "success": True,
        "metadata_stripped": False,
        "xmp_purged": False,
        "attachments_purged": 0,
        "comments_purged": 0,
        "hidden_layers_purged": 0,
        "toc_items_purged": 0,
        "thumbnails_purged": 0,
        "javascript_actions_purged": 0,
        "document_id_scrubbed": False,
    }

    try:
        # 1. Strip sensitive metadata
        if strip_metadata:
            doc.set_metadata({})
            try:
                trailer_info = doc.xref_get_key(-1, "Info")
                if trailer_info[0] == "xref":
                    doc.xref_set_key(-1, "Info", "null")
            except Exception:
                pass
            results["metadata_stripped"] = True

        # 2. Purge XML Metadata (XMP)
        if purge_xmp:
            try:
                doc.del_xml_metadata()
            except Exception:
                pass
            try:
                cat = doc.pdf_catalog()
                if "Metadata" in doc.xref_get_keys(cat):
                    doc.xref_set_key(cat, "Metadata", "null")
            except Exception:
                pass
            results["xmp_purged"] = True

        # 3. Purge embedded files and attachments
        if purge_attachments:
            # Document-level attachments
            try:
                for name in list(doc.embfile_names()):
                    doc.embfile_del(name)
                    results["attachments_purged"] += 1
            except Exception as e:
                print(f"Warning: error deleting embfiles: {e}")

            # Page-level FileAttachment annotations
            try:
                for p_idx in range(len(doc)):
                    p = doc[p_idx]
                    for annot in list(p.annots()):
                        if getattr(annot, 'type', [None, None])[1] == "FileAttachment":
                            p.delete_annot(annot)
                            results["attachments_purged"] += 1
            except Exception as e:
                print(f"Warning: error deleting file attachment annots: {e}")

            # Catalog Names / EmbeddedFiles cleanup
            try:
                cat = doc.pdf_catalog()
                names_key = doc.xref_get_key(cat, "Names")
                if names_key[0] == "xref":
                    names_xref = int(names_key[1].split()[0])
                    if "EmbeddedFiles" in doc.xref_get_keys(names_xref):
                        doc.xref_set_key(names_xref, "EmbeddedFiles", "null")
            except Exception:
                pass

        # 4. Purge comments, notes, and markup annotations
        if purge_comments:
            comment_types = {
                "Text", "Highlight", "Underline", "StrikeOut", "Squiggly",
                "FreeText", "Stamp", "Ink", "Popup", "Line", "Square",
                "Circle", "Polygon", "PolyLine", "Caret", "FileAttachment"
            }
            try:
                for p_idx in range(len(doc)):
                    p = doc[p_idx]
                    for annot in list(p.annots()):
                        atype = getattr(annot, 'type', [None, None])[1]
                        if atype in comment_types:
                            p.delete_annot(annot)
                            results["comments_purged"] += 1
                    if not preserve_forms:
                        try:
                            for w in list(p.widgets()):
                                p.delete_widget(w)
                                results["comments_purged"] += 1
                        except Exception:
                            pass
                    if not preserve_links:
                        try:
                            for l in list(p.get_links()):
                                p.delete_link(l)
                        except Exception:
                            pass
            except Exception as e:
                print(f"Warning: error purging comments: {e}")

        # 5. Purge hidden layers (Optional Content Groups)
        if purge_hidden_layers:
            try:
                ocgs = doc.get_ocgs()
                if ocgs:
                    results["hidden_layers_purged"] = len(ocgs)
                    cat = doc.pdf_catalog()
                    if "OCProperties" in doc.xref_get_keys(cat):
                        doc.xref_set_key(cat, "OCProperties", "null")
            except Exception as e:
                print(f"Warning: error purging hidden layers: {e}")

        # 6. Purge TOC / Bookmarks
        if strip_bookmarks:
            try:
                results["toc_items_purged"] = len(doc.get_toc())
                doc.set_toc([])
            except Exception as e:
                print(f"Warning: error stripping bookmarks: {e}")
        elif purge_orphaned_toc:
            try:
                toc = doc.get_toc()
                cleaned_toc = []
                purged_count = 0
                for item in toc:
                    pno = item[2]
                    is_orphaned = pno < 1 or pno > len(doc)
                    is_redacted = bool(redacted_pages and (pno - 1) in redacted_pages)
                    if is_orphaned or is_redacted:
                        purged_count += 1
                    else:
                        cleaned_toc.append(item)
                if purged_count > 0:
                    doc.set_toc(cleaned_toc)
                    results["toc_items_purged"] = purged_count
            except Exception as e:
                print(f"Warning: error cleaning TOC: {e}")

        # 7. Purge embedded page thumbnails (/Thumb)
        if purge_thumbnails:
            try:
                for p_idx in range(len(doc)):
                    p = doc[p_idx]
                    pxref = p.xref
                    thumb_key = doc.xref_get_key(pxref, "Thumb")
                    if thumb_key[0] not in ("null", ""):
                        doc.xref_set_key(pxref, "Thumb", "null")
                        results["thumbnails_purged"] += 1
            except Exception as e:
                print(f"Warning: error purging page thumbnails: {e}")

        # 8. Purge JavaScript and interactive action payloads
        if purge_javascript:
            try:
                cat = doc.pdf_catalog()
                # Document-level /Names /JavaScript
                names_key = doc.xref_get_key(cat, "Names")
                if names_key[0] == "xref":
                    names_xref = int(names_key[1].split()[0])
                    if doc.xref_get_key(names_xref, "JavaScript")[0] not in ("null", ""):
                        doc.xref_set_key(names_xref, "JavaScript", "null")
                        results["javascript_actions_purged"] += 1

                # Catalog /JavaScript
                if doc.xref_get_key(cat, "JavaScript")[0] not in ("null", ""):
                    doc.xref_set_key(cat, "JavaScript", "null")
                    results["javascript_actions_purged"] += 1

                # Catalog /OpenAction
                if doc.xref_get_key(cat, "OpenAction")[0] not in ("null", ""):
                    doc.xref_set_key(cat, "OpenAction", "null")
                    results["javascript_actions_purged"] += 1

                # Catalog /AA (Additional Actions)
                if doc.xref_get_key(cat, "AA")[0] not in ("null", ""):
                    doc.xref_set_key(cat, "AA", "null")
                    results["javascript_actions_purged"] += 1

                # Page-level actions, annotations, and form widgets
                for p_idx in range(len(doc)):
                    p = doc[p_idx]
                    pxref = p.xref
                    if doc.xref_get_key(pxref, "AA")[0] not in ("null", ""):
                        doc.xref_set_key(pxref, "AA", "null")
                        results["javascript_actions_purged"] += 1

                    for annot in list(p.annots()):
                        axref = annot.xref
                        a_key = doc.xref_get_key(axref, "A")
                        if a_key[0] not in ("null", ""):
                            a_val = doc.xref_object(axref)
                            if any(k in a_val for k in ("/JavaScript", "/Launch", "/SubmitForm", "/ImportData")):
                                doc.xref_set_key(axref, "A", "null")
                                results["javascript_actions_purged"] += 1
                        aa_key = doc.xref_get_key(axref, "AA")
                        if aa_key[0] not in ("null", ""):
                            doc.xref_set_key(axref, "AA", "null")
                            results["javascript_actions_purged"] += 1

                    try:
                        for w in list(p.widgets()):
                            wxref = w.xref
                            if wxref > 0:
                                if doc.xref_get_key(wxref, "AA")[0] not in ("null", ""):
                                    doc.xref_set_key(wxref, "AA", "null")
                                    results["javascript_actions_purged"] += 1
                                a_key = doc.xref_get_key(wxref, "A")
                                if a_key[0] not in ("null", ""):
                                    w_val = doc.xref_object(wxref)
                                    if any(k in w_val for k in ("/JavaScript", "/Launch", "/SubmitForm", "/ImportData")):
                                        doc.xref_set_key(wxref, "A", "null")
                                        results["javascript_actions_purged"] += 1
                    except Exception:
                        pass
            except Exception as e:
                print(f"Warning: error purging JavaScript actions: {e}")

        # 9. Scrub and randomize Document ID (/ID trailer)
        if scrub_document_id:
            try:
                new_id1 = hashlib.md5(uuid.uuid4().bytes).hexdigest()
                new_id2 = hashlib.md5(uuid.uuid4().bytes).hexdigest()
                doc.xref_set_key(-1, "ID", f"[<{new_id1}> <{new_id2}>]")
                results["document_id_scrubbed"] = True
            except Exception as e:
                print(f"Warning: error scrubbing document ID: {e}")

        # Invalidate Cairo and document cache
        invalidate_page_cache(doc)

    except Exception as e:
        print(f"Error during document sanitization: {e}")
        results["success"] = False
        results["error"] = str(e)

    return results


def verify_document_sanitization(doc) -> dict:
    """Verify document hygiene by checking for presence of sensitive metadata,
    XMP packets, attachments, hidden layers, and comments.
    """
    if not doc:
        return {"is_clean": False, "details": "No document"}

    details = {}
    is_clean = True

    # Check metadata
    meta = doc.metadata or {}
    sensitive_fields = ["author", "title", "subject", "keywords", "creator", "producer"]
    dirty_fields = {k: v for k, v in meta.items() if k in sensitive_fields and v}
    if dirty_fields:
        is_clean = False
        details["sensitive_metadata"] = dirty_fields

    # Check XMP
    xmp = doc.get_xml_metadata()
    if xmp and xmp.strip():
        is_clean = False
        details["has_xmp"] = True

    # Check attachments
    if doc.embfile_count() > 0:
        is_clean = False
        details["attachments_count"] = doc.embfile_count()

    # Check hidden layers / OCGs
    ocgs = doc.get_ocgs()
    if ocgs:
        is_clean = False
        details["ocgs_count"] = len(ocgs)

    # Check comments / non-form annots
    comment_count = 0
    for p in doc:
        for a in p.annots():
            atype = getattr(a, 'type', [None, None])[1]
            if atype not in ("Widget", "Link"):
                comment_count += 1
    if comment_count > 0:
        is_clean = False
        details["comments_count"] = comment_count

    # Check Thumbnails
    thumb_count = 0
    try:
        for p in doc:
            if doc.xref_get_key(p.xref, "Thumb")[0] not in ("null", ""):
                thumb_count += 1
    except Exception:
        pass
    if thumb_count > 0:
        is_clean = False
        details["thumbnails_count"] = thumb_count

    # Check JavaScript / Actions
    try:
        cat = doc.pdf_catalog()
        has_js = False
        if doc.xref_get_key(cat, "OpenAction")[0] not in ("null", ""):
            has_js = True
        if doc.xref_get_key(cat, "AA")[0] not in ("null", ""):
            has_js = True
        if doc.xref_get_key(cat, "JavaScript")[0] not in ("null", ""):
            has_js = True
        names_key = doc.xref_get_key(cat, "Names")
        if names_key[0] == "xref":
            names_xref = int(names_key[1].split()[0])
            if doc.xref_get_key(names_xref, "JavaScript")[0] not in ("null", ""):
                has_js = True
        for p in doc:
            if doc.xref_get_key(p.xref, "AA")[0] not in ("null", ""):
                has_js = True
        if has_js:
            is_clean = False
            details["has_javascript_or_actions"] = True
    except Exception:
        pass

    return {"is_clean": is_clean, "details": details}


def verify_redaction_purge(doc, page_num, bbox, search_term=None, allowed_overlay=None):
    """Verify that underlying sensitive text within bbox on page_num has been completely eradicated."""
    if not doc or page_num < 0 or page_num >= len(doc):
        return False
    try:
        page = doc[page_num]
        rect = fitz.Rect(bbox)
        if search_term:
            hits = page.search_for(search_term, clip=rect)
            if hits:
                return False
            words = page.get_text("words", clip=rect)
            for w in words:
                if search_term.lower() in w[4].lower():
                    return False
        elif allowed_overlay is not None:
            words = page.get_text("words", clip=rect)
            for w in words:
                if w[4] != allowed_overlay and w[4] not in allowed_overlay:
                    return False
        else:
            words = page.get_text("words", clip=rect)
            if words:
                return False
        return True
    except Exception:
        return False


def extract_ocr_words_for_page(target_page, ocr_doc) -> List[Dict[str, Any]]:
    """Extract recognized words from a 1-page OCR document and scale their bounding boxes to target_page."""
    if target_page is None or ocr_doc is None:
        return []
    try:
        from .ocr_engine import estimate_word_confidence
        ocr_page = ocr_doc[0] if hasattr(ocr_doc, "__getitem__") else ocr_doc
        ocr_rect = ocr_page.rect
        target_rect = target_page.rect
        scale_x = target_rect.width / max(ocr_rect.width, 1.0)
        scale_y = target_rect.height / max(ocr_rect.height, 1.0)

        raw_words = ocr_page.get_text("words")
        extracted: List[Dict[str, Any]] = []
        for item in raw_words:
            if len(item) < 5:
                continue
            text = str(item[4]).strip()
            if not text:
                continue
            wx0 = float(item[0]) * scale_x
            wy0 = float(item[1]) * scale_y
            wx1 = float(item[2]) * scale_x
            wy1 = float(item[3]) * scale_y
            x0, x1 = min(wx0, wx1), max(wx0, wx1)
            y0, y1 = min(wy0, wy1), max(wy0, wy1)
            if (x1 - x0) <= 0.1 or (y1 - y0) <= 0.1:
                continue
            extracted.append({
                "bbox": (x0, y0, x1, y1),
                "text": text,
                "confidence": estimate_word_confidence(text),
                "block_no": int(item[5]) if len(item) > 5 else 0,
                "line_no": int(item[6]) if len(item) > 6 else 0,
                "word_no": int(item[7]) if len(item) > 7 else 0,
            })
        return extracted
    except Exception as e:
        print(f"Error extracting OCR words for page: {e}")
        return []


def _word_already_exists_on_page(existing_words, bbox: Tuple[float, float, float, float], text: str) -> bool:
    norm_target = text.strip().lower()
    if not norm_target or not existing_words:
        return False
    target_rect = fitz.Rect(bbox)
    target_area = max(target_rect.width * target_rect.height, 0.1)
    for ew in existing_words:
        if len(ew) < 5:
            continue
        if str(ew[4]).strip().lower() != norm_target:
            continue
        erect = fitz.Rect(ew[0], ew[1], ew[2], ew[3])
        inter = target_rect & erect
        if not inter.is_empty:
            min_area = max(min(target_area, erect.width * erect.height), 0.1)
            if (inter.width * inter.height) / min_area >= 0.25:
                return True
    return False


def restore_pre_ocr_page(doc, page_num: int) -> bool:
    """Restore a page to its state prior to OCR text layer embedding."""
    if not doc or not (0 <= page_num < len(doc)):
        return False
    key = (id(doc), page_num)
    if key not in _page_pre_ocr_snapshots:
        return False
    _page_snapshots[key] = _page_pre_ocr_snapshots.pop(key)
    return restore_page_from_snapshot(doc, page_num)


def embed_ocr_text_layer_on_page(
    doc,
    page_num: int,
    ocr_doc=None,
    ocr_words: Optional[List[Dict[str, Any]]] = None,
    language: str = "eng",
    dpi: int = 200,
    tessdata_dir: Optional[str] = None,
    replace_existing: bool = True,
    auto_deskew: bool = True,
    auto_rotate: bool = True,
    auto_invert: bool = True,
    enhance_contrast: bool = True,
) -> Dict[str, Any]:
    """Embed a transparent searchable text layer (PDF render_mode=3) onto a single page."""
    if not doc or page_num < 0 or page_num >= len(doc):
        return {"success": False, "page_num": page_num, "words_embedded": 0, "error": "Invalid document or page index"}

    own_ocr_doc = False
    try:
        save_page_snapshot(doc, page_num)
        key = (id(doc), page_num)
        if key not in _page_pre_ocr_snapshots and key in _page_snapshots:
            _page_pre_ocr_snapshots[key] = _page_snapshots[key]
        elif key in _page_pre_ocr_snapshots and replace_existing:
            _page_snapshots[key] = _page_pre_ocr_snapshots[key]
            restore_page_from_snapshot(doc, page_num)

        page = doc.load_page(page_num)

        if ocr_words is None and ocr_doc is None:
            # Auto-rotate coarse orientation if needed (90, 180, 270)
            if auto_rotate:
                try:
                    from .ocr_engine import detect_page_orientation
                    orient_rot = detect_page_orientation(page, dpi=100, language=language, tessdata_dir=tessdata_dir)
                    if orient_rot in (90, 180, 270):
                        page.set_rotation((page.rotation + orient_rot) % 360)
                except Exception as e:
                    print(f"Warning: orientation detection failed on page {page_num}: {e}")

            # Auto-deskew crooked scans
            if auto_deskew:
                try:
                    from .ocr_engine import is_scanned_page, detect_page_skew_angle, deskew_scanned_page
                    if is_scanned_page(page).is_scanned:
                        skew_angle = detect_page_skew_angle(page, dpi=100)
                        if abs(skew_angle) >= 0.35:
                            deskew_scanned_page(doc, page_num, skew_angle, dpi=dpi)
                            page = doc.load_page(page_num)
                except Exception as e:
                    print(f"Warning: deskew failed on page {page_num}: {e}")

        if ocr_words is None:
            if ocr_doc is None:
                from .ocr_engine import extract_ocr_words_with_confidence, perform_ocr_on_page
                pix = page.get_pixmap(dpi=dpi)
                ocr_words = extract_ocr_words_with_confidence(
                    pix,
                    page_rect=page.rect,
                    language=language,
                    tessdata_dir=tessdata_dir,
                    auto_invert=auto_invert,
                    enhance_contrast=enhance_contrast,
                )
                if not ocr_words:
                    ocr_doc = perform_ocr_on_page(
                        doc,
                        page_num=page_num,
                        language=language,
                        dpi=dpi,
                        tessdata_dir=tessdata_dir,
                        auto_invert=auto_invert,
                        enhance_contrast=enhance_contrast,
                    )
                    own_ocr_doc = True
                    ocr_words = extract_ocr_words_for_page(page, ocr_doc)
            else:
                ocr_words = extract_ocr_words_for_page(page, ocr_doc)

        if not hasattr(doc, "_ocr_words_cache"):
            doc._ocr_words_cache = {}
        doc._ocr_words_cache[page_num] = ocr_words

        existing_words = []
        try:
            existing_words = page.get_text("words")
        except Exception:
            pass

        unicode_font_path = None
        unicode_font_obj = None
        rot = int(page.rotation) % 360
        derot_mat = ~page.rotation_matrix if rot != 0 else None

        words_embedded = 0
        embedded_texts: List[str] = []

        for w_info in ocr_words:
            text = str(w_info.get("text", "")).strip()
            bbox = w_info.get("bbox")
            if not text or not bbox or len(bbox) < 4:
                continue

            x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            if _word_already_exists_on_page(existing_words, (x0, y0, x1, y1), text):
                continue

            box_w = max(1.0, x1 - x0)
            box_h = max(2.0, y1 - y0)
            fontsize = max(4.0, box_h * 0.85)
            baseline_y = y1 - box_h * 0.15

            needs_unicode = any(ord(c) >= 128 for c in text)
            font_kwargs: Dict[str, Any] = {}
            unit_w = 0.0

            if needs_unicode:
                if unicode_font_path is None:
                    unicode_font_path = get_default_unicode_font_path() or ""
                    if unicode_font_path:
                        try:
                            unicode_font_obj = fitz.Font(fontfile=unicode_font_path)
                        except Exception:
                            unicode_font_obj = None
                if unicode_font_path:
                    font_kwargs = {
                        "fontfile": unicode_font_path,
                        "fontname": "word_sys_ocr_u",
                    }
                    if unicode_font_obj is not None:
                        try:
                            unit_w = unicode_font_obj.text_length(text, fontsize=1.0)
                        except Exception:
                            unit_w = 0.0
                else:
                    font_kwargs = {"fontname": "helv"}
            else:
                font_kwargs = {"fontname": "helv"}
                try:
                    unit_w = fitz.get_text_length(text, fontname="helv", fontsize=1.0)
                except Exception:
                    unit_w = 0.0

            if unit_w > 0.0 and (unit_w * fontsize) > (box_w * 1.05):
                fontsize = max(3.0, box_w / unit_w)

            vis_pt = fitz.Point(x0, baseline_y)
            insert_pt = (vis_pt * derot_mat) if derot_mat is not None else vis_pt

            page.insert_text(
                insert_pt,
                text,
                fontsize=fontsize,
                render_mode=3,
                rotate=rot,
                overlay=True,
                **font_kwargs,
            )
            existing_words.append((x0, y0, x1, y1, text, 0, 0, words_embedded))
            words_embedded += 1
            embedded_texts.append(text)

        save_page_snapshot(doc, page_num, force=True)
        invalidate_page_cache(doc, page_num)

        return {
            "success": True,
            "page_num": page_num,
            "words_embedded": words_embedded,
            "text": " ".join(embedded_texts),
        }
    except Exception as e:
        print(f"Error embedding OCR text layer on page {page_num}: {e}")
        return {
            "success": False,
            "page_num": page_num,
            "words_embedded": 0,
            "error": str(e),
        }
    finally:
        if own_ocr_doc and ocr_doc is not None:
            try:
                ocr_doc.close()
            except Exception:
                pass


def embed_ocr_text_layer(
    doc,
    page_numbers: Optional[List[int]] = None,
    ocr_results: Optional[Dict[int, Any]] = None,
    ocr_words_by_page: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    language: str = "eng",
    dpi: int = 200,
    tessdata_dir: Optional[str] = None,
    replace_existing: bool = True,
    auto_deskew: bool = True,
    auto_rotate: bool = True,
    auto_invert: bool = True,
    enhance_contrast: bool = True,
) -> Dict[str, Any]:
    """Embed transparent searchable OCR text layers across one or more pages of a document."""
    if not doc:
        return {"success": False, "pages_processed": 0, "total_words_embedded": 0, "per_page": {}}

    if page_numbers is None:
        if ocr_words_by_page is not None:
            page_numbers = sorted(ocr_words_by_page.keys())
        elif ocr_results is not None:
            page_numbers = sorted(ocr_results.keys())
        else:
            page_numbers = list(range(len(doc)))

    per_page: Dict[int, Dict[str, Any]] = {}
    total_words = 0
    pages_processed = 0

    for p_num in page_numbers:
        if p_num < 0 or p_num >= len(doc):
            continue
        p_ocr_doc = ocr_results.get(p_num) if ocr_results else None
        p_ocr_words = ocr_words_by_page.get(p_num) if ocr_words_by_page else None
        res = embed_ocr_text_layer_on_page(
            doc,
            page_num=p_num,
            ocr_doc=p_ocr_doc,
            ocr_words=p_ocr_words,
            language=language,
            dpi=dpi,
            tessdata_dir=tessdata_dir,
            replace_existing=replace_existing,
            auto_deskew=auto_deskew,
            auto_rotate=auto_rotate,
            auto_invert=auto_invert,
            enhance_contrast=enhance_contrast,
        )
        per_page[p_num] = res
        if res.get("success"):
            pages_processed += 1
            total_words += int(res.get("words_embedded", 0))

    return {
        "success": pages_processed > 0 or len(page_numbers) == 0,
        "pages_processed": pages_processed,
        "total_words_embedded": total_words,
        "per_page": per_page,
    }
