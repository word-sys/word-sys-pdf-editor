try:
    import pymupdf as fitz
except ImportError:
    import fitz
import numpy as np
import cairo
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
from typing import Optional, List, Dict, Any, Tuple, Union
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
from gi.repository import GdkPixbuf, Gdk, Pango, PangoCairo
from .models import (
    EditableText, FLAG_BOLD, FLAG_ITALIC, EditableImage, EditableShape, EditableStroke,
    AcroFormField, decompose_font_name, extract_font_properties, get_base14_font_variant
)
from .utils import find_specific_font_variant, get_default_unicode_font_path, normalize_color
from .i18n import _

_cairo_page_cache = {}

def invalidate_page_cache(doc=None, page_index=None):
    """Invalidate cached Cairo page surfaces."""
    global _cairo_page_cache
    if doc is None:
        _cairo_page_cache.clear()
        return
    doc_id = id(doc)
    if page_index is None:
        keys_to_del = [k for k in _cairo_page_cache if k[0] == doc_id]
    else:
        keys_to_del = [k for k in _cairo_page_cache if k[0] == doc_id and k[1] == page_index]
    for k in keys_to_del:
        _cairo_page_cache.pop(k, None)

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

def get_page_cairo_surface(doc, page_index, zoom_level):
    """Get or render cached Cairo ImageSurface for the given page and zoom level."""
    global _cairo_page_cache
    if not doc or not (0 <= page_index < doc.page_count):
        return None

    cache_key = (id(doc), page_index, round(float(zoom_level), 4))
    if cache_key in _cairo_page_cache:
        return _cairo_page_cache[cache_key]

    try:
        page = doc.load_page(page_index)
        zoom_matrix = fitz.Matrix(zoom_level, zoom_level)
        pix = page.get_pixmap(matrix=zoom_matrix, alpha=False)
        samples_bytes = bytes(pix.samples)

        pixbuf = GdkPixbuf.Pixbuf.new_from_data(
            samples_bytes, GdkPixbuf.Colorspace.RGB, False, 8,
            pix.width, pix.height, pix.stride
        )

        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, pix.width, pix.height)
        cr_surf = cairo.Context(surf)
        cr_surf.set_source_rgb(1.0, 1.0, 1.0)
        cr_surf.paint()
        if pixbuf:
            Gdk.cairo_set_source_pixbuf(cr_surf, pixbuf, 0, 0)
            cr_surf.paint()

        # Limit cache size to 6 surfaces to conserve memory
        if len(_cairo_page_cache) >= 6:
            oldest_key = next(iter(_cairo_page_cache))
            _cairo_page_cache.pop(oldest_key, None)

        _cairo_page_cache[cache_key] = surf
        return surf
    except Exception as e:
        print(f"Error creating cached page surface for page {page_index}: {e}")
        return None

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

def load_pdf_document(filepath):
    """Load PDF document."""
    try:
        doc = fitz.open(filepath)
        if doc.needs_pass:
            doc.close()
            return None, "Password protected PDFs are not supported yet."
        return doc, None
    except Exception as e:
        return None, f"Error opening PDF: {e}\nPath: {filepath}"

def close_pdf_document(doc):
    """Close PDF document."""
    if doc:
        try:
            invalidate_page_cache(doc)
            doc.close()
        except Exception as e:
            print(f"Error closing PDF document: {e}")

def get_page_count(doc):
    """Get the page count."""
    return doc.page_count if doc else 0

def generate_thumbnail(doc, page_index, target_width=150):
    """Generate thumbnail."""
    if not doc or not (0 <= page_index < doc.page_count):
        return None
    try:
        page = doc.load_page(page_index)
        
        page_w = page.rect.width
        if page_w == 0: 
            page_w = 1 
            
        zoom_factor = target_width / page_w
        matrix = fitz.Matrix(zoom_factor, zoom_factor)

        pix = page.get_pixmap(matrix=matrix, alpha=False)
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

def pixmap_to_cairo_surface(pix):
    """Pixmap to cairo surface."""
    data = None
    fmt = None
    stride = 0
    data_ref = None

    try:
        if pix.alpha:
            if pix.n != 4: return None, None
            fmt = cairo.FORMAT_ARGB32
            samples_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 4))
            bgra_data = np.zeros_like(samples_np)
            bgra_data[..., 0] = samples_np[..., 2] # B
            bgra_data[..., 1] = samples_np[..., 1] # G
            bgra_data[..., 2] = samples_np[..., 0] # R
            bgra_data[..., 3] = samples_np[..., 3] # A
            data = bytearray(bgra_data.tobytes())
            stride = pix.stride
            data_ref = data

        else:
            if pix.n != 3: return None, None
            bgra_data = np.zeros((pix.height, pix.width, 4), dtype=np.uint8)
            try:
                 rgb_view = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 3))
            except ValueError:
                 rgb_view = np.frombuffer(pix.samples, dtype=np.uint8).copy().reshape((pix.height, pix.width, 3))

            bgra_data[:, :, 0] = rgb_view[:, :, 2]  # Blue
            bgra_data[:, :, 1] = rgb_view[:, :, 1]  # Green
            bgra_data[:, :, 2] = rgb_view[:, :, 0]  # Red
            bgra_data[:, :, 3] = 255                # Alpha
            data = bgra_data.data 
            fmt = cairo.FORMAT_ARGB32
            stride = pix.width * 4 
            data_ref = bgra_data 

        if data is None: return None, None

        surface = cairo.ImageSurface.create_for_data(data, fmt, pix.width, pix.height, stride)
        return surface, data_ref

    except Exception as e:
        print(f"Error creating Cairo surface from pixmap: {e}")
        return None, None


def draw_page_to_cairo(cr, doc, page_index, zoom_level):
    """Draw page to cairo using the cached surface."""
    surf = get_page_cairo_surface(doc, page_index, zoom_level)
    if surf:
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.paint()
        cr.set_source_surface(surf, 0, 0)
        cr.paint()
        return True, None
    else:
        cr.set_source_rgb(0.7, 0.7, 0.7)
        cr.paint()
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

                        editable = EditableText(
                            x=bbox[0], y=bbox[1], text=combined_text,
                            font_size=first_span.get("size", 11) if first_span else 11,
                            font_family=first_span.get("font", "Liberation Sans") if first_span else "Liberation Sans",
                            color=first_span.get("color", 0) if first_span else 0,
                            span_data=span_data,
                            baseline=orig_origin[1],
                            rotation=line_rot
                        )
                        editable.bbox = tuple(bbox)
                        editable.original_bbox = editable.bbox
                        editable.original_baseline = editable.baseline
                        editable.original_rotation = editable.rotation
                        editable.page_number = page_index
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
                        print(f"DEBUG: Extracted text segment: '{combined_text}' font='{editable.font_family_base}' color={editable.color} bbox={editable.bbox}")
        
        print(f"DEBUG: Total text objects extracted from page {page_index}: {len(editable_texts)}")
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
    """Burn edited text modifications into the underlying PDF page stream."""
    if not doc or text_obj.page_number is None:
        return False, "Invalid document or page number."

    font_arg, error_msg = _get_font_args_for_pymupdf(text_obj)
    if error_msg:
        return False, error_msg

    try:
        page = doc.load_page(text_obj.page_number)
        
        print(f"DEBUG apply_text_edit: is_new={text_obj.is_new}, new_text='{new_text}'")
        print(f"DEBUG: text_obj bbox: {text_obj.bbox}")
        
        if new_text.strip():
            text_color = (0, 0, 0)
            if text_obj.color:
                if isinstance(text_obj.color, (tuple, list)) and len(text_obj.color) >= 3:
                    text_color = tuple(float(c) for c in text_obj.color[:3])
                elif isinstance(text_obj.color, int):
                    blue = (text_obj.color & 255) / 255.0
                    green = ((text_obj.color >> 8) & 255) / 255.0
                    red = ((text_obj.color >> 16) & 255) / 255.0
                    text_color = (red, green, blue)
            
            print(f"DEBUG: Inserting updated text '{new_text}' at point ({text_obj.x}, {text_obj.baseline})")
            
            line_point = fitz.Point(text_obj.x, text_obj.baseline)
            rc = page.insert_text(
                line_point,
                new_text,
                fontsize=text_obj.font_size,
                color=text_color,
                overlay=True,
                **font_arg
            )
            print(f"DEBUG: insert_text returned: {rc}")
            if rc < 0:
                print(f"ERROR: insert_text failed with rc={rc}")
                return False, f"PyMuPDF insert_text error: {rc}"

        return True, None
    except Exception as e:
        print(f"ERROR applying text edit: {e}")
        traceback.print_exc()
        return False, f"Error during text application: {e}"

def save_document(doc, save_path, incremental=False):
    """Save PyMuPDF document to disk with optional incremental saving and cleanup."""
    if not doc:
        return False, "Kaydedilecek belge yok."

    temp_path = f"{save_path}.tmp_save"

    try:
        doc.save(
            temp_path,
            garbage=4,
            deflate=True,
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
            print(f"DEBUG: No images found via get_image_info on page {page_index}. Trying alternative method...")
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
 
                try:
                    image_bytes = get_image_rgba_bytes(doc, xref)
                    if not image_bytes:
                        print(f"DEBUG: Could not extract image data for xref {xref}")
                        continue
                    
                    image_obj = EditableImage(
                        bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                        page_number=page_index,
                        xref=xref,
                        image_bytes=image_bytes,
                        rotation=0.0
                    )
                    editable_images.append(image_obj)
                except Exception as extract_error:
                    print(f"DEBUG: Error extracting image bytes for xref {xref}: {extract_error}")
                    continue
                    
            except (ValueError, TypeError) as e:
                print(_("warn_image_skipped", page_index+1, img_info.get('xref'), e))
                continue
        
        print(f"DEBUG: Extracted {len(editable_images)} images from page {page_index}")
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

        print(f"DEBUG: Extracted {len(editable_shapes)} shapes from page {page_index}")
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

        print(f"DEBUG: Extracted {len(editable_strokes)} strokes from page {page_index}")
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




_page_snapshots: dict = {}
_page_original_links: dict = {}

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
        del _page_snapshots[k]
        if k in _page_original_links:
            del _page_original_links[k]

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

                if not links:
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
                    segments = []
                    last_idx = 0
                    for match in links:
                        start, end = match.start(), match.end()
                        if start > last_idx:
                            segments.append((line[last_idx:start], False))
                        segments.append((line[start:end], True))
                        last_idx = end
                    if last_idx < len(line):
                        segments.append((line[last_idx:], False))
                        
                    current_x = line_start_x
                    for seg_text, is_seg_link in segments:
                        if not seg_text:
                            continue
                        
                        seg_color = (0.0, 0.33, 0.8) if is_seg_link else obj.color
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
                            
                            uri = seg_text
                            if not uri.startswith(("http://", "https://")):
                                uri = "https://" + uri
                                
                            link_from = link_rect.quad * mat if mat else link_rect.quad
                            rect = link_from.rect if hasattr(link_from, 'rect') else fitz.Rect(link_from)
                            link_data = {"kind": fitz.LINK_URI, "from": rect, "uri": uri}
                            page.insert_link(link_data)
                            
                        current_x += seg_len
                        
    elif isinstance(obj, EditableImage):
        rect = fitz.Rect(obj.bbox)
        if rot == 0.0:
            page.insert_image(rect, stream=obj.image_bytes, keep_proportion=False)
        elif rot % 90 == 0:
            page.insert_image(rect, stream=obj.image_bytes, rotate=int(rot), keep_proportion=False)
        else:
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(obj.image_bytes))
                rotated_im = im.rotate(-rot, expand=True, resample=Image.BICUBIC)
                buf = io.BytesIO()
                rotated_im.save(buf, format="PNG")
                stream = buf.getvalue()
                cx = (rect.x0 + rect.x1) / 2.0
                cy = (rect.y0 + rect.y1) / 2.0
                w = rect.x1 - rect.x0
                h = rect.y1 - rect.y0
                rad = math.radians(rot)
                nw = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
                nh = abs(w * math.sin(rad)) + abs(h * math.cos(rad))
                rot_rect = fitz.Rect(cx - nw / 2.0, cy - nh / 2.0, cx + nw / 2.0, cy + nh / 2.0)
                page.insert_image(rot_rect, stream=stream, keep_proportion=False)
            except Exception:
                page.insert_image(rect, stream=obj.image_bytes, keep_proportion=False)
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
    return True, None

def rebuild_page(doc, page_num: int, all_texts, all_shapes, all_images,
                 exclude_obj=None, all_strokes=None):
    """Re-render page from snapshot applying all active editable objects."""
    if not restore_page_from_snapshot(doc, page_num):
        print(f"Warning: no snapshot for page {page_num}, skipping restore")
    try:
        page = doc.load_page(page_num)
        for obj in all_texts:
            if getattr(obj, 'page_number', None) == page_num and obj is not exclude_obj:
                if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                    _apply_single_object_to_page(doc, page, obj)
        for obj in all_images:
            if getattr(obj, 'page_number', None) == page_num and obj is not exclude_obj:
                if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                    _apply_single_object_to_page(doc, page, obj)
        for obj in all_shapes:
            if getattr(obj, 'page_number', None) == page_num and obj is not exclude_obj:
                if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                    _apply_single_object_to_page(doc, page, obj)
        if all_strokes:
            for obj in all_strokes:
                if getattr(obj, 'page_number', None) == page_num and obj is not exclude_obj:
                    if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                        _apply_single_object_to_page(doc, page, obj)
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
            for (did, pno), content in _page_snapshots.items():
                if did == doc_id and pno >= target_pno:
                    new_snapshots[(did, pno + 1)] = content
                else:
                    new_snapshots[(did, pno)] = content
            _page_snapshots = new_snapshots

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
        for (did, pno), content in _page_snapshots.items():
            if did == doc_id:
                new_snapshots[(did, _remap_index(pno))] = content
            else:
                new_snapshots[(did, pno)] = content
        _page_snapshots = new_snapshots

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
        for (did, pno), content in _page_snapshots.items():
            if did == doc_id:
                if pno == page_index:
                    continue
                elif pno > page_index:
                    new_snapshots[(did, pno - 1)] = content
                else:
                    new_snapshots[(did, pno)] = content
            else:
                new_snapshots[(did, pno)] = content
        _page_snapshots = new_snapshots

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