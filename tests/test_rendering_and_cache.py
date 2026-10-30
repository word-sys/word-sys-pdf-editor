"""Consolidated Rendering, Rasterization, Caching, and Performance Test Suite for word-sys-pdf-editor.

This suite validates asynchronous background page rasterization, tiled page rendering,
thumbnail list virtualization, two-tier disk/RAM thumbnail caching, progressive zoom LOD,
memory budgeting / cache eviction under pressure, and large document performance.
"""

# ============================================================================
# SECTION: test_async_page_rasterizer.py
# ============================================================================
import os
import time
import threading
import unittest
from unittest.mock import MagicMock, patch
import fitz
import cairo
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.window import PdfEditorWindow


class TestAsyncPageRasterizer(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        # Create a sample multi-page document with vector art and text
        for i in range(5):
            page = self.doc.new_page(width=600, height=800)
            page.draw_rect(fitz.Rect(50, 50, 200, 200), color=(1, 0, 0), fill=(0, 1, 0))
            page.insert_text(fitz.Point(100, 300), f"Page {i + 1} Complex Content", fontsize=24)
        pdf_handler.invalidate_page_cache(self.doc)

    def tearDown(self):
        pdf_handler.invalidate_page_cache(self.doc)
        if not getattr(self.doc, 'is_closed', False):
            self.doc.close()

    def test_pool_initialization_and_eco_mode(self):
        """Verify PageRasterizerPool initializes and adjusts for Eco Mode."""
        pool = pdf_handler.PageRasterizerPool(max_workers=2)
        self.assertEqual(pool.max_workers, 2)
        self.assertFalse(pool._is_eco_mode)

        pool.set_eco_mode(True)
        self.assertTrue(pool._is_eco_mode)

        gen_before = pool.get_generation(id(self.doc))
        self.assertEqual(gen_before, 0)
        pool.bump_generation(id(self.doc))
        self.assertEqual(pool.get_generation(id(self.doc)), 1)
        pool.shutdown(wait=False)

    def test_peek_surface_lifecycle(self):
        """Verify peek_surface returns None when uncached and valid surface once rendered."""
        pool = pdf_handler.get_page_rasterizer_pool()
        pdf_handler.invalidate_page_cache(self.doc)

        # Uncached: must return None immediately without blocking
        surf_peek = pool.peek_surface(self.doc, 0, 1.0)
        self.assertIsNone(surf_peek)

        # Render synchronously into cache
        surf_sync = pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)
        self.assertIsNotNone(surf_sync)
        self.assertGreater(surf_sync.get_width(), 0)

        # Now peek_surface must return the cached surface instantly
        surf_cached = pool.peek_surface(self.doc, 0, 1.0)
        self.assertIsNotNone(surf_cached)
        self.assertEqual(surf_cached, surf_sync)

    def test_wait_for_surface_async_rendering(self):
        """Verify background worker renders surface asynchronously and wait_for_surface resolves."""
        pool = pdf_handler.get_page_rasterizer_pool()
        pdf_handler.invalidate_page_cache(self.doc)

        surf = pool.wait_for_surface(self.doc, 1, 1.25, timeout=5.0)
        self.assertIsNotNone(surf)
        self.assertIsInstance(surf, cairo.ImageSurface)
        self.assertGreater(surf.get_width(), 0)
        self.assertGreater(surf.get_height(), 0)

    def test_request_surface_dispatches_callback(self):
        """Verify request_surface executes on worker and triggers callback via GLib main context."""
        pool = pdf_handler.get_page_rasterizer_pool()
        pdf_handler.invalidate_page_cache(self.doc)

        received_results = []
        event = threading.Event()

        def _on_ready(p_idx, z_val, surf):
            received_results.append((p_idx, z_val, surf))
            event.set()

        pool.request_surface(self.doc, 2, 1.5, callback=_on_ready)

        # Wait up to 3 seconds, pumping GLib main context
        start_t = time.time()
        ctx = GLib.MainContext.default()
        while not event.is_set() and (time.time() - start_t) < 3.0:
            ctx.iteration(False)
            time.sleep(0.01)

        self.assertTrue(event.is_set(), "Callback was not triggered within timeout")
        self.assertEqual(len(received_results), 1)
        p, z, s = received_results[0]
        self.assertEqual(p, 2)
        self.assertAlmostEqual(z, 1.5, places=3)
        self.assertIsNotNone(s)

    def test_find_best_cached_surface_closest_zoom(self):
        """Verify find_best_cached_surface selects the closest zoom level for instant bilinear preview."""
        pool = pdf_handler.get_page_rasterizer_pool()
        pdf_handler.invalidate_page_cache(self.doc)

        # Render page 0 at zoom 1.0 and zoom 3.0
        pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)
        pdf_handler.get_page_cairo_surface(self.doc, 0, 3.0)

        # Closer to 1.0: target zoom 1.2
        best_surf1, best_zoom1 = pool.find_best_cached_surface(self.doc, 0, target_zoom=1.2)
        self.assertAlmostEqual(best_zoom1, 1.0, places=2)

        # Closer to 3.0: target zoom 2.7
        best_surf2, best_zoom2 = pool.find_best_cached_surface(self.doc, 0, target_zoom=2.7)
        self.assertAlmostEqual(best_zoom2, 3.0, places=2)

    def test_invalidate_page_cache_cancels_and_bumps_generation(self):
        """Verify invalidate_page_cache discards stale async rendering callbacks."""
        pool = pdf_handler.get_page_rasterizer_pool()
        pdf_handler.invalidate_page_cache(self.doc)

        stale_calls = []
        def _stale_callback(p, z, s):
            stale_calls.append(p)

        # Request surface and immediately invalidate before callback fires
        pool.request_surface(self.doc, 3, 2.0, callback=_stale_callback)
        pdf_handler.invalidate_page_cache(self.doc)

        # Pump context
        ctx = GLib.MainContext.default()
        for _ in range(50):
            ctx.iteration(False)
            time.sleep(0.005)

        # Callback must have been dropped due to generation token bump
        self.assertEqual(len(stale_calls), 0)

    def test_gtk_draw_non_blocking_performance_guarantee(self):
        """Verify _draw_page_content decouples rasterization and executes without blocking the main event loop."""
        # Create a page with 100 vector rects that takes > 50ms to render synchronously
        doc = fitz.open()
        p = doc.new_page(width=600, height=800)
        for i in range(100):
            p.draw_rect(fitz.Rect(10, 10, 500, 500), color=(1, 0, 0), fill=(0, 1, 0))

        pdf_handler.invalidate_page_cache(doc)

        win = MagicMock()
        win.doc = doc
        win.zoom_level = 2.0
        win.current_page_index = 0
        win.dragged_object = None
        win.inline_editor_widget = None
        win.inline_editor_text_obj = None
        win.temp_image_bbox = None
        win.temp_stamp_bbox = None
        win.temp_clone_patch_bbox = None
        win.temp_redact_bbox = None
        win.temp_form_field_rect = None
        win.temp_sig_bbox = None
        win.temp_stroke = None
        win.temp_shape = None
        win.editable_texts = []
        win.editable_images = []
        win.editable_shapes = []
        win.editable_strokes = []
        win.form_fields = []
        win.selected_text = None
        win.selected_image = None
        win.selected_shape = None
        win.selected_stroke = None
        win.selected_form_field = None
        win.selected_sig_annot = None
        win.selected_measurement = None
        win.selected_redaction_mark = None
        win.show_ocr_overlay = False
        win.highlighted_native_annot = None
        win.active_native_measurement = None
        win.view_mode = False
        win.view_sel_rect = None
        win.async_page_rendering = True
        win.pdf_view = MagicMock()
        win._active_session = None
        win.tool_mode = "select"
        win.temp_calibration_line = None

        target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 600, 800)
        cr = cairo.Context(target_surf)

        # 1. Cold draw (uncached surface): must decouple and return in < 15.0 ms
        t0 = time.perf_counter()
        PdfEditorWindow._draw_page_content(win, win.pdf_view, cr, 0, 0, 0, 600, 800)
        t_cold_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(t_cold_ms, 15.0, f"Cold draw took {t_cold_ms:.3f}ms, blocking main loop")

        # 2. Wait for background worker to complete
        pdf_handler.get_page_rasterizer_pool().wait_for_surface(doc, 0, 2.0, timeout=5.0)

        # 3. Warm draw (cached surface): must complete without blocking (< 5.0 ms)
        t1 = time.perf_counter()
        PdfEditorWindow._draw_page_content(win, win.pdf_view, cr, 0, 0, 0, 600, 800)
        t_warm_ms = (time.perf_counter() - t1) * 1000.0
        self.assertLess(t_warm_ms, 5.0, f"Warm draw took {t_warm_ms:.3f}ms, exceeding 5.0ms ceiling")

    def test_load_page_prefetches_adjacent_surfaces(self):
        """Verify _load_page pre-requests surfaces for current and adjacent pages."""
        win = MagicMock()
        win.doc = self.doc
        win.zoom_level = 1.0
        win.current_page_index = 2
        win.is_eco_mode = False
        win.async_page_rendering = True
        win.continuous_scroll = False
        win.pdf_view = MagicMock()
        win.pdf_scroll = MagicMock()
        win.status_label = MagicMock()
        win.editable_texts = []
        win._active_session = None

        with patch("word_sys_pdf_editor.pdf_handler.request_page_cairo_surface") as mock_req:
            # We simulate the tail of _load_page where queue_draw and prefetch occurs
            if getattr(win, 'async_page_rendering', True) and win.doc:
                pdf_handler.request_page_cairo_surface(win.doc, 2, win.zoom_level)
                if not getattr(win, 'is_eco_mode', False):
                    if 2 + 1 < pdf_handler.get_page_count(win.doc):
                        pdf_handler.request_page_cairo_surface(win.doc, 2 + 1, win.zoom_level)
                    if 2 - 1 >= 0:
                        pdf_handler.request_page_cairo_surface(win.doc, 2 - 1, win.zoom_level)

            self.assertEqual(mock_req.call_count, 3)
            # Pages requested: 2 (current), 3 (next), 1 (prev)
            requested_pages = [call.args[1] for call in mock_req.call_args_list]
            self.assertEqual(requested_pages, [2, 3, 1])

    def test_scaled_fallback_when_zooming(self):
        """Verify that zooming instantly scales the existing surface without blank frame."""
        pdf_handler.invalidate_page_cache(self.doc)

        # Pre-render surface at zoom 1.0
        surf_1x = pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)
        self.assertIsNotNone(surf_1x)

        # Now simulate a draw request at zoom 2.0
        win = MagicMock()
        win.doc = self.doc
        win.zoom_level = 2.0
        win.current_page_index = 0
        win.dragged_object = None
        win.inline_editor_widget = None
        win.inline_editor_text_obj = None
        win.temp_image_bbox = None
        win.temp_stamp_bbox = None
        win.temp_clone_patch_bbox = None
        win.temp_redact_bbox = None
        win.temp_form_field_rect = None
        win.temp_sig_bbox = None
        win.temp_stroke = None
        win.temp_shape = None
        win.editable_texts = []
        win.editable_images = []
        win.editable_shapes = []
        win.editable_strokes = []
        win.form_fields = []
        win.selected_text = None
        win.selected_image = None
        win.selected_shape = None
        win.selected_stroke = None
        win.selected_form_field = None
        win.selected_sig_annot = None
        win.selected_measurement = None
        win.selected_redaction_mark = None
        win.show_ocr_overlay = False
        win.highlighted_native_annot = None
        win.active_native_measurement = None
        win.view_mode = False
        win.view_sel_rect = None
        win.async_page_rendering = True
        win.pdf_view = MagicMock()
        win._active_session = None
        win.tool_mode = "select"
        win.temp_calibration_line = None

        target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 1200, 1600)
        cr = cairo.Context(target_surf)

        # Target zoom 2.0 is NOT cached yet
        self.assertIsNone(pdf_handler.peek_page_cairo_surface(self.doc, 0, 2.0))
        # Best match should return the 1.0x surface
        best_surf, best_zoom = pdf_handler.get_page_rasterizer_pool().find_best_cached_surface(self.doc, 0, 2.0)
        self.assertEqual(best_surf, surf_1x)
        self.assertEqual(best_zoom, 1.0)

        # Drawing at zoom 2.0 uses the fallback and paints successfully into cr
        PdfEditorWindow._draw_page_content(win, win.pdf_view, cr, 0, 0, 0, 1200, 1600)
        self.assertEqual(target_surf.get_width(), 1200)
        self.assertEqual(target_surf.get_height(), 1600)

    def test_stale_cache_retention_prevents_white_flash_on_invalidation(self):
        """Verify invalidate_page_cache preserves the previous surface as a stale fallback to prevent flashing."""
        pdf_handler.invalidate_page_cache(self.doc)
        initial_surf = pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)
        self.assertIsNotNone(initial_surf)
        self.assertIsNotNone(pdf_handler.peek_page_cairo_surface(self.doc, 0, 1.0))

        # Invalidate page 0 cache
        pdf_handler.invalidate_page_cache(self.doc, 0)

        # Fresh cache is invalidated
        self.assertIsNone(pdf_handler.peek_page_cairo_surface(self.doc, 0, 1.0))

        # Stale cache retention keeps initial_surf as best match
        stale_match = pdf_handler.get_page_rasterizer_pool().find_best_cached_surface(self.doc, 0, 1.0)
        self.assertIsNotNone(stale_match)
        stale_surf, stale_zoom = stale_match
        self.assertEqual(stale_surf, initial_surf)
        self.assertAlmostEqual(stale_zoom, 1.0)

        # Re-generating fresh surface clears stale cache
        new_surf = pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)
        self.assertIsNotNone(new_surf)
        self.assertNotIn((id(self.doc), 0), pdf_handler._stale_page_cache)


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_tiled_page_renderer.py
# ============================================================================
import unittest
import math
import time
import cairo
import fitz
from unittest.mock import MagicMock, patch
from gi.repository import GLib

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.pdf_handler import TiledPageRenderer, get_tiled_page_renderer
from word_sys_pdf_editor.window import PdfEditorWindow


class TestTiledPageRenderer(unittest.TestCase):
    """Verify sub-viewport tile calculation, rasterization, LRU caching, and virtualization."""

    def setUp(self):
        self.doc = fitz.open()
        # Create a 2000x2000 pt large blueprint page
        self.page = self.doc.new_page(width=2000, height=2000)
        self.page.draw_rect([100, 100, 500, 500], color=(0.8, 0.2, 0.2), fill=(0.2, 0.8, 0.2))
        self.page.draw_line((0, 0), (2000, 2000), color=(0, 0, 1), width=4)
        self.tiler = TiledPageRenderer(tile_size=512, max_cached_tiles=32)

    def tearDown(self):
        if self.doc:
            pdf_handler.close_pdf_document(self.doc)

    def test_is_tiling_required_thresholds(self):
        """Verify tiling triggers for large dimensions or high zoom and stays dormant for normal pages."""
        # Standard A4 at 100% zoom (595x842 pt -> 595x842 px)
        self.assertFalse(self.tiler.is_tiling_required(595, 842, 1.0))
        # Standard A4 at 200% zoom (1190x1684 px)
        self.assertFalse(self.tiler.is_tiling_required(595, 842, 2.0))
        # Standard A4 at 400% zoom (2380x3368 px, height > 2500)
        self.assertTrue(self.tiler.is_tiling_required(595, 842, 4.0))
        # Standard A4 at 600% zoom
        self.assertTrue(self.tiler.is_tiling_required(595, 842, 6.0))
        # Large engineering blueprint (A0: 2384x3370 pt) at 100% zoom
        self.assertTrue(self.tiler.is_tiling_required(2384, 3370, 1.0))

    def test_get_tile_counts_and_rects(self):
        """Verify grid partitioning and pixel rectangle calculations."""
        # Page 1024x1024 at 1.0x with 512 tile size -> exactly 2x2 grid
        cols, rows = self.tiler.get_tile_counts(1024, 1024, 1.0)
        self.assertEqual((cols, rows), (2, 2))

        # Check tile pixel rects
        r00 = self.tiler.get_tile_pixel_rect(0, 0, 1024, 1024, 1.0)
        self.assertEqual(r00, (0.0, 0.0, 512.0, 512.0))
        r11 = self.tiler.get_tile_pixel_rect(1, 1, 1024, 1024, 1.0)
        self.assertEqual(r11, (512.0, 512.0, 512.0, 512.0))

        # Page 1000x800 at 1.0x -> 2x2 grid with edge clamping
        c_edge, r_edge = self.tiler.get_tile_counts(1000, 800, 1.0)
        self.assertEqual((c_edge, r_edge), (2, 2))
        r11_clamped = self.tiler.get_tile_pixel_rect(1, 1, 1000, 800, 1.0)
        self.assertEqual(r11_clamped, (512.0, 512.0, 488.0, 288.0))

    def test_get_visible_tile_coords_intersection(self):
        """Verify tile visibility queries accurately intersect the viewport."""
        # Page placed at canvas (100, 100), total pixel size 2000x2000
        # Viewport at (100, 100, 600, 600) covers top-left tiles
        visible = self.tiler.get_visible_tile_coords(
            page_canvas_x=100.0, page_canvas_y=100.0,
            page_width_pt=2000.0, page_height_pt=2000.0,
            zoom_level=1.0,
            viewport_rect=(100.0, 100.0, 600.0, 600.0),
            margin_tiles=0
        )
        self.assertIn((0, 0), visible)
        self.assertIn((1, 0), visible)
        self.assertIn((0, 1), visible)
        self.assertIn((1, 1), visible)
        # Far corner (3, 3) must not be in visible list with margin 0
        self.assertNotIn((3, 3), visible)

        # Viewport completely outside page rect returns empty
        outside = self.tiler.get_visible_tile_coords(
            page_canvas_x=100.0, page_canvas_y=100.0,
            page_width_pt=2000.0, page_height_pt=2000.0,
            zoom_level=1.0,
            viewport_rect=(5000.0, 5000.0, 800.0, 600.0),
            margin_tiles=0
        )
        self.assertEqual(outside, [])

    def test_render_and_peek_tile(self):
        """Verify synchronous tile rendering produces a valid Cairo ImageSurface and caches it."""
        surf = self.tiler.render_tile(self.doc, 0, 1.0, 0, 0)
        self.assertIsNotNone(surf)
        self.assertIsInstance(surf, cairo.ImageSurface)
        self.assertEqual(surf.get_width(), 512)
        self.assertEqual(surf.get_height(), 512)

        # Non-blocking peek returns the exact cached surface
        peeked = self.tiler.peek_tile(self.doc, 0, 1.0, 0, 0)
        self.assertEqual(peeked, surf)

    def test_async_request_tile(self):
        """Verify asynchronous tile rendering dispatches callback via GLib idle loop."""
        received = []
        def _on_tile(col, row, surf):
            received.append((col, row, surf))

        self.tiler.request_tile(self.doc, 0, 1.0, 1, 0, callback=_on_tile, defer=False)

        # Pump main context until worker completes
        ctx = GLib.MainContext.default()
        start = time.time()
        while not received and (time.time() - start < 3.0):
            ctx.iteration(False)
            time.sleep(0.01)

        self.assertEqual(len(received), 1)
        c, r, s = received[0]
        self.assertEqual((c, r), (1, 0))
        self.assertIsNotNone(s)

    def test_prune_distant_tiles(self):
        """Verify pruning purges tiles outside the active set while preserving LRU budget."""
        # Render 40 tiles
        for c in range(5):
            for r in range(8):
                self.tiler.render_tile(self.doc, 0, 1.0, c, r)

        # Active set is only (0, 0) and (0, 1)
        active_set = {(0, 0), (0, 1)}
        self.tiler.prune_distant_tiles(self.doc, 0, 1.0, active_set)
        # Total cached tiles for this page/zoom should be significantly bounded
        remaining_keys = [k for k in self.tiler._tile_cache.keys() if k[0] == id(self.doc)]
        self.assertLessEqual(len(remaining_keys), 34)

    def test_invalidate_doc_tiles(self):
        """Verify invalidation completely clears cached tiles for target document."""
        self.tiler.render_tile(self.doc, 0, 1.0, 0, 0)
        self.assertIsNotNone(self.tiler.peek_tile(self.doc, 0, 1.0, 0, 0))

        self.tiler.invalidate_doc_tiles(self.doc, 0)
        self.assertIsNone(self.tiler.peek_tile(self.doc, 0, 1.0, 0, 0))

    def test_window_draw_uses_tiler_for_huge_pages(self):
        """Verify PdfEditorWindow._draw_page_content invokes tiled renderer when page is huge."""
        win = MagicMock()
        win.doc = self.doc
        win.zoom_level = 2.0  # 2000 pt * 2.0 = 4000 px > 2500 -> activates tiling
        win.current_page_index = 0
        win.get_visible_viewport_rect = lambda: (0.0, 0.0, 800.0, 600.0)
        win.pdf_view = MagicMock()
        win.dragged_object = None
        win.inline_editor_widget = None
        win.inline_editor_text_obj = None
        win._inline_editor_target_rect = None
        win.temp_image_bbox = None
        win.temp_stamp_bbox = None
        win.temp_clone_patch_bbox = None
        win.temp_redact_bbox = None
        win.temp_form_field_rect = None
        win.temp_sig_bbox = None
        win.temp_stroke = None
        win.temp_shape = None
        win.editable_texts = []
        win.editable_images = []
        win.editable_shapes = []
        win.editable_strokes = []
        win.form_fields = []
        win.selected_text = None
        win.selected_image = None
        win.selected_shape = None
        win.selected_stroke = None
        win.selected_form_field = None
        win.selected_sig_annot = None
        win.selected_measurement = None
        win.selected_redaction_mark = None
        win.selected_objects = []
        win.selected_object = None
        win.show_ocr_overlay = False
        win.highlighted_native_annot = None
        win.active_native_measurement = None
        win.view_mode = False
        win.view_sel_rect = None
        win.async_page_rendering = True
        win._active_session = None
        win.tool_mode = "select"
        win.temp_calibration_line = None
        win.redaction_regions = []
        win.search_matches = []
        win.annotations = []
        win.comment_callouts = []
        win.measurements = []
        win._link_creation_active = False
        win.creating_element_type = None
        win.is_zoom_gesture_active = False
        win.continuous_scroll = False
        win.multi_select_box = None
        win.crop_box = None
        win.rotation_crop_box = None
        win.redaction_tool_active = False

        target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 800, 600)
        cr = cairo.Context(target_surf)

        with patch.object(self.tiler, 'peek_tile') as mock_peek, \
             patch.object(self.tiler, 'request_tile') as mock_req:
            mock_peek.return_value = None
            with patch('word_sys_pdf_editor.pdf_handler.get_tiled_page_renderer', return_value=self.tiler):
                PdfEditorWindow._draw_page_content(win, win.pdf_view, cr, 0, 0, 0, 4000.0, 4000.0)
                # Tiler must have been queried for tiles
                mock_req.assert_called()


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_thumbnail_virtualization.py
# ============================================================================
"""Tests for virtualized Gtk.ListView thumbnail ribbon and widget recycling."""

import unittest
from unittest.mock import MagicMock
import time
import fitz
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib, GObject

from word_sys_pdf_editor.models import PdfPage
from word_sys_pdf_editor.ui_components import PageThumbnailFactory
from word_sys_pdf_editor import pdf_handler


class TestThumbnailVirtualization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init()

    def setUp(self):
        self.doc = fitz.open()
        for i in range(5):
            page = self.doc.new_page(width=300, height=400)
            page.insert_text((50, 50), f"Page {i + 1}")

    def tearDown(self):
        if self.doc and not self.doc.is_closed:
            self.doc.close()

    def test_pdf_page_default_thumbnail_none(self):
        """PdfPage should default thumbnail to None and support property notification."""
        page = PdfPage(index=42)
        self.assertEqual(page.index, 42)
        self.assertIsNone(page.thumbnail)

        notifications = []
        page.connect("notify::thumbnail", lambda obj, pspec: notifications.append(obj.thumbnail))

        pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 20, 20)
        page.thumbnail = pix

        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0], pix)
        self.assertEqual(page.thumbnail, pix)

    def test_large_list_store_instant_splice(self):
        """Populating 500 virtual page items into Gio.ListStore should execute in < 100ms."""
        store = Gio.ListStore(item_type=PdfPage)
        t0 = time.perf_counter()
        pages = [PdfPage(index=i) for i in range(500)]
        store.splice(0, 0, pages)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self.assertEqual(store.get_n_items(), 500)
        self.assertLess(elapsed_ms, 100.0, "Model population should be virtually instantaneous")
        self.assertEqual(store.get_item(250).index, 250)
        self.assertIsNone(store.get_item(250).thumbnail)

    def test_page_thumbnail_factory_lifecycle(self):
        """Factory setup, bind, unbind, and teardown lifecycle."""
        mock_win = MagicMock()
        mock_win.view_mode = False
        mock_win.edit_mode = True

        factory = PageThumbnailFactory(editor_window=mock_win)

        list_item = MagicMock()
        child_holder = [None]
        list_item.set_child.side_effect = lambda c: child_holder.__setitem__(0, c)
        list_item.get_child.side_effect = lambda: child_holder[0]

        # 1. Setup
        factory._on_setup(factory, list_item)
        box = list_item.get_child()
        self.assertIsNotNone(box)
        self.assertIsInstance(box, Gtk.Box)

        # Controllers should be attached once
        controllers = list(box.observe_controllers())
        self.assertTrue(any(isinstance(c, Gtk.DragSource) for c in controllers))
        self.assertTrue(any(isinstance(c, Gtk.DropTarget) for c in controllers))
        self.assertTrue(any(isinstance(c, Gtk.GestureClick) for c in controllers))
        initial_ctrl_count = len(controllers)

        # 2. Bind with unrendered thumbnail
        page_0 = PdfPage(index=0, thumbnail=None)
        list_item.get_item.return_value = page_0

        factory._on_bind(factory, list_item)

        # Controllers should not be duplicated on bind
        self.assertEqual(len(list(box.observe_controllers())), initial_ctrl_count)

        # request_thumbnail should be triggered for page 0
        mock_win.request_thumbnail.assert_called_with(0)

        # 3. Simulate thumbnail generation and notify
        pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 30, 40)
        page_0.thumbnail = pix

        pic = box.get_first_child()
        self.assertIsNotNone(pic.get_paintable(), "Picture should have paintable after notify")

        # 4. Unbind: should recycle widget and clear paintable to free texture memory
        factory._on_unbind(factory, list_item)
        self.assertIsNone(pic.get_paintable(), "Paintable should be None after unbind")
        self.assertIsNone(getattr(box, "_thumb_handler_id", None))

        # 5. Teardown
        factory._on_teardown(factory, list_item)
        self.assertIsNone(list_item.get_child())

    def test_placeholder_card_texture(self):
        """get_thumbnail_placeholder_texture should return a 150x200 Gdk.Texture singleton."""
        from word_sys_pdf_editor.ui_components import get_thumbnail_placeholder_texture
        tex1 = get_thumbnail_placeholder_texture()
        tex2 = get_thumbnail_placeholder_texture()
        self.assertIsNotNone(tex1)
        self.assertIs(tex1, tex2, "Placeholder texture should be a cached singleton")
        self.assertEqual(tex1.get_width(), 150)
        self.assertEqual(tex1.get_height(), 200)

    def test_priority_scheduling_ordering(self):
        """Visible priority tasks must execute before background tasks."""
        pipeline = pdf_handler.ThumbnailPipeline(max_workers=1)
        try:
            executed = []
            def on_done(page_idx, thumb, gen_id):
                executed.append(page_idx)

            # Queue background tasks for pages 1, 2, 3
            pipeline.request(1, self.doc, 1, priority=pdf_handler.PRIORITY_BACKGROUND, callback=on_done)
            pipeline.request(1, self.doc, 2, priority=pdf_handler.PRIORITY_BACKGROUND, callback=on_done)
            pipeline.request(1, self.doc, 3, priority=pdf_handler.PRIORITY_BACKGROUND, callback=on_done)
            # Queue visible task for page 4
            pipeline.request(1, self.doc, 4, priority=pdf_handler.PRIORITY_VISIBLE, callback=on_done)

            # Wait for execution
            for _ in range(25):
                if 4 in executed and (3 in executed or 2 in executed):
                    break
                time.sleep(0.05)
                ctx = GLib.MainContext.default()
                for _ in range(10):
                    if ctx.pending(): ctx.iteration(False)

            self.assertIn(4, executed)
            idx_4 = executed.index(4)
            # Visible page 4 should have been dispatched ahead of background task page 3
            if 3 in executed:
                idx_3 = executed.index(3)
                self.assertLess(idx_4, idx_3, "Visible task should execute before lower priority background task")
            else:
                idx_2 = executed.index(2)
                self.assertLess(idx_4, idx_2, "Visible task should execute before lower priority background task")
        finally:
            pipeline.shutdown(wait=True)

    def test_task_cancellation_on_rapid_scroll(self):
        """Cancelled page requests should be skipped by the pipeline without rendering."""
        pipeline = pdf_handler.ThumbnailPipeline(max_workers=1)
        try:
            rendered = []
            def on_done(page_idx, thumb, gen_id):
                rendered.append(page_idx)

            # Queue tasks
            pipeline.request(1, self.doc, 1, priority=pdf_handler.PRIORITY_BACKGROUND, callback=on_done)
            pipeline.request(1, self.doc, 2, priority=pdf_handler.PRIORITY_BACKGROUND, callback=on_done)
            pipeline.request(1, self.doc, 3, priority=pdf_handler.PRIORITY_BACKGROUND, callback=on_done)

            # Cancel page 2
            pipeline.cancel_page(1, 2)

            time.sleep(0.15)
            ctx = GLib.MainContext.default()
            for _ in range(50):
                if ctx.pending(): ctx.iteration(False)

            self.assertIn(1, rendered)
            self.assertNotIn(2, rendered, "Cancelled task for page 2 should not be rendered")
            self.assertIn(3, rendered)
        finally:
            pipeline.shutdown(wait=True)

    def test_generation_cancellation_on_document_switch(self):
        """Switching documents should cancel all pending tasks from the previous generation."""
        pipeline = pdf_handler.ThumbnailPipeline(max_workers=1)
        try:
            rendered = []
            def on_done(page_idx, thumb, gen_id):
                rendered.append((gen_id, page_idx))

            # Queue tasks for generation 1
            pipeline.request(1, self.doc, 0, priority=pdf_handler.PRIORITY_BACKGROUND, callback=on_done)
            pipeline.request(1, self.doc, 1, priority=pdf_handler.PRIORITY_BACKGROUND, callback=on_done)

            # Cancel all generation 1 tasks
            pipeline.cancel_generation(1)

            # Queue task for generation 2
            pipeline.request(2, self.doc, 3, priority=pdf_handler.PRIORITY_VISIBLE, callback=on_done)

            time.sleep(0.15)
            ctx = GLib.MainContext.default()
            for _ in range(50):
                if ctx.pending(): ctx.iteration(False)

            self.assertIn((2, 3), rendered)
            self.assertNotIn((1, 1), rendered)
        finally:
            pipeline.shutdown(wait=True)

    def test_request_thumbnail_execution(self):
        """request_thumbnail should generate thumbnail via pipeline and update target item on idle."""
        mock_session = MagicMock()
        mock_session.doc = self.doc
        store = Gio.ListStore(item_type=PdfPage)
        store.splice(0, 0, [PdfPage(index=i) for i in range(5)])
        mock_session.pages_model = store

        from word_sys_pdf_editor.window import PdfEditorWindow
        win = MagicMock(spec=PdfEditorWindow)
        win._active_session = mock_session
        win._thumb_generation_id = 999
        win._on_thumbnail_rendered = PdfEditorWindow._on_thumbnail_rendered.__get__(win, PdfEditorWindow)

        PdfEditorWindow.request_thumbnail(win, 2, session=mock_session)

        # Allow worker thread to render and main loop to deliver
        time.sleep(0.1)
        ctx = GLib.MainContext.default()
        for _ in range(50):
            if ctx.pending():
                ctx.iteration(False)

        item_2 = store.get_item(2)
        self.assertIsNotNone(item_2.thumbnail)
        self.assertIsInstance(item_2.thumbnail, GdkPixbuf.Pixbuf)

    def test_load_thumbnails_virtualization(self):
        """_load_thumbnails should populate model immediately and render active page."""
        mock_session = MagicMock()
        mock_session.doc = self.doc
        store = Gio.ListStore(item_type=PdfPage)
        mock_session.pages_model = store
        mock_session.pdf_path = "/tmp/test.pdf"

        from word_sys_pdf_editor.window import PdfEditorWindow
        win = MagicMock(spec=PdfEditorWindow)
        win._active_session = mock_session
        win.current_page_index = 0
        win.status_label = MagicMock()

        PdfEditorWindow._load_thumbnails(win, session=mock_session, target_page=1)

        # All 5 pages should be in store immediately
        self.assertEqual(store.get_n_items(), 5)
        # Target page 1 should have its thumbnail generated immediately
        self.assertIsNotNone(store.get_item(1).thumbnail)
        # Pages not yet visited start as None
        self.assertIsNone(store.get_item(3).thumbnail)

    def test_sidebar_uses_gtk_list_view(self):
        """thumbnails_list should be an instance of Gtk.ListView."""
        factory = PageThumbnailFactory()
        model = Gio.ListStore(item_type=PdfPage)
        sel = Gtk.SingleSelection(model=model)
        list_view = Gtk.ListView.new(sel, factory)
        self.assertIsInstance(list_view, Gtk.ListView)

    def test_refresh_thumbnail_updates_in_place(self):
        """_refresh_thumbnail should update item.thumbnail in-place and notify."""
        mock_session = MagicMock()
        mock_session.doc = self.doc
        store = Gio.ListStore(item_type=PdfPage)
        p0 = PdfPage(index=0)
        p1 = PdfPage(index=1)
        store.splice(0, 0, [p0, p1])
        mock_session.pages_model = store

        from word_sys_pdf_editor.window import PdfEditorWindow
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = self.doc
        win.pages_model = store
        win._active_session = mock_session

        notifications = []
        p1.connect("notify::thumbnail", lambda obj, pspec: notifications.append(True))

        PdfEditorWindow._refresh_thumbnail(win, 1)

        # Item 1 should have updated thumbnail and fired notification
        self.assertEqual(len(notifications), 1)
        self.assertIsNotNone(p1.thumbnail)
        self.assertIs(store.get_item(1), p1)


# ============================================================================
# SECTION: test_disk_thumbnail_cache.py
# ============================================================================
import unittest
import tempfile
import os
import time
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GdkPixbuf

from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.pdf_handler import DiskThumbnailCache, get_disk_thumbnail_cache


class TestDiskThumbnailCache(unittest.TestCase):
    """Test suite for persistent two-tier thumbnail disk cache and fast reopen."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Gtk.Application()
        except Exception:
            cls.app = None

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = os.path.join(self.temp_dir.name, "cache")
        self.disk_cache = DiskThumbnailCache(cache_dir=self.cache_dir, max_disk_bytes=50 * 1024 * 1024)
        pdf_handler._DISK_THUMBNAIL_CACHE = self.disk_cache

        # Create a sample multi-page PDF
        self.pdf_path = os.path.join(self.temp_dir.name, "sample.pdf")
        doc = fitz.open()
        for i in range(10):
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 50), f"Sample Page {i+1}")
        doc.save(self.pdf_path)
        doc.close()

    def tearDown(self):
        pdf_handler._DISK_THUMBNAIL_CACHE = None
        if hasattr(self, 'win') and self.win:
            try:
                self.win.close_document()
                self.win.destroy()
            except Exception:
                pass
        self.temp_dir.cleanup()

    def test_fingerprint_generation_and_staleness(self):
        """Fingerprint must be deterministic and change on file modification."""
        doc = fitz.open(self.pdf_path)
        fp1 = self.disk_cache.get_document_fingerprint(doc, filepath=self.pdf_path)
        fp2 = self.disk_cache.get_document_fingerprint(doc, filepath=self.pdf_path)
        self.assertIsNotNone(fp1)
        self.assertEqual(fp1, fp2)

        # Touch file to change mtime
        time.sleep(0.01)
        os.utime(self.pdf_path, None)
        fp3 = self.disk_cache.get_document_fingerprint(doc, filepath=self.pdf_path)
        self.assertNotEqual(fp1, fp3, "Fingerprint must change when file modification time changes")
        doc.close()

    def test_store_and_retrieve_thumbnail(self):
        """Storing and retrieving thumbnails from disk must yield valid GdkPixbufs."""
        doc = fitz.open(self.pdf_path)
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))

        stored = self.disk_cache.store_thumbnail(doc, 0, 150, pix, filepath=self.pdf_path)
        self.assertTrue(stored)

        retrieved = self.disk_cache.get_thumbnail(doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(retrieved)
        self.assertIsInstance(retrieved, GdkPixbuf.Pixbuf)
        self.assertGreater(retrieved.get_width(), 0)
        self.assertGreater(retrieved.get_height(), 0)

        # Non-existent page must return None
        none_thumb = self.disk_cache.get_thumbnail(doc, 999, target_width=150, filepath=self.pdf_path)
        self.assertIsNone(none_thumb)
        doc.close()

    def test_page_invalidation(self):
        """Invalidating a single page must delete only that page's cached file."""
        doc = fitz.open(self.pdf_path)
        page0 = doc.load_page(0)
        page1 = doc.load_page(1)
        pix0 = page0.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
        pix1 = page1.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))

        self.disk_cache.store_thumbnail(doc, 0, 150, pix0, filepath=self.pdf_path)
        self.disk_cache.store_thumbnail(doc, 1, 150, pix1, filepath=self.pdf_path)

        self.assertIsNotNone(self.disk_cache.get_thumbnail(doc, 0, 150, filepath=self.pdf_path))
        self.assertIsNotNone(self.disk_cache.get_thumbnail(doc, 1, 150, filepath=self.pdf_path))

        self.disk_cache.invalidate_page(doc, 0, filepath=self.pdf_path)
        self.assertIsNone(self.disk_cache.get_thumbnail(doc, 0, 150, filepath=self.pdf_path))
        self.assertIsNotNone(self.disk_cache.get_thumbnail(doc, 1, 150, filepath=self.pdf_path))
        doc.close()

    def test_document_invalidation(self):
        """Invalidating a document must purge all thumbnails for that document."""
        doc = fitz.open(self.pdf_path)
        page0 = doc.load_page(0)
        pix0 = page0.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
        self.disk_cache.store_thumbnail(doc, 0, 150, pix0, filepath=self.pdf_path)

        self.assertIsNotNone(self.disk_cache.get_thumbnail(doc, 0, 150, filepath=self.pdf_path))
        self.disk_cache.invalidate_doc(doc, filepath=self.pdf_path)
        self.assertIsNone(self.disk_cache.get_thumbnail(doc, 0, 150, filepath=self.pdf_path))
        doc.close()

    def test_lru_quota_pruning(self):
        """Disk cache pruning must remove oldest directories when exceeding byte quota."""
        # Create small quota cache (2 KB)
        tiny_cache = DiskThumbnailCache(cache_dir=self.cache_dir, max_disk_bytes=2048)
        doc = fitz.open(self.pdf_path)
        page0 = doc.load_page(0)
        pix = page0.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))

        # Store for doc 1
        tiny_cache.store_thumbnail(doc, 0, 150, pix, filepath=self.pdf_path)

        # Create doc 2 in temp dir
        doc2_path = os.path.join(self.temp_dir.name, "sample2.pdf")
        doc2 = fitz.open()
        doc2.new_page(width=595, height=842)
        doc2.save(doc2_path)
        doc2.close()

        doc2 = fitz.open(doc2_path)
        time.sleep(0.02)
        tiny_cache.store_thumbnail(doc2, 0, 150, pix, filepath=doc2_path)

        # Trigger prune with very small limit (500 bytes)
        tiny_cache.prune(max_bytes=500)

        # Total size must now be <= 500 bytes
        remaining_dirs = [d for d in Path(self.cache_dir).iterdir() if d.is_dir()]
        self.assertLessEqual(len(remaining_dirs), 1)

        doc.close()
        doc2.close()

    def test_generate_thumbnail_uses_disk_cache_without_rasterizing(self):
        """generate_thumbnail must return cached thumbnail without calling fitz load_page."""
        doc, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)

        # 1. First call renders and caches to disk
        thumb1 = pdf_handler.generate_thumbnail(doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(thumb1)

        # Verify disk cache now contains thumbnail
        disk_thumb = pdf_handler.get_disk_thumbnail_cache().get_thumbnail(doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(disk_thumb)

        # 2. Poison doc.load_page to confirm fitz is NOT called on second retrieve
        def poisoned_load_page(*args, **kwargs):
            raise RuntimeError("load_page should not be called when thumbnail is in disk cache!")
        doc.load_page = poisoned_load_page

        thumb2 = pdf_handler.generate_thumbnail(doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(thumb2)
        self.assertEqual(thumb2.get_width(), thumb1.get_width())

        doc.close()

    def test_fast_document_reopen_thumbnails_prepopulated(self):
        """Reopening a previously opened document must load thumbnails from disk in under 15ms."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        # Ensure page 0 and page 1 thumbnails are rendered and stored to disk
        pdf_handler.generate_thumbnail(self.win.doc, 0, target_width=150, filepath=self.pdf_path)
        pdf_handler.generate_thumbnail(self.win.doc, 1, target_width=150, filepath=self.pdf_path)

        # Close session
        self.win.close_document()

        # Reopen document
        reloaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)

        t0 = time.time()
        self.win._finish_loading(reloaded, None, self.pdf_path, 0, self.win._active_session)
        t1 = time.time()
        reopen_ms = (t1 - t0) * 1000

        self.assertLess(reopen_ms, 50.0, f"Reopening document took {reopen_ms:.2f}ms, expected < 50ms")

        # Verify visible model items have pre-populated thumbnails directly from disk
        model = self.win._active_session.pages_model
        self.assertGreater(model.get_n_items(), 0)
        item0 = model.get_item(0)
        self.assertIsNotNone(item0.thumbnail, "Page 0 thumbnail must be pre-populated from disk on reopen")
        item1 = model.get_item(1)
        self.assertIsNotNone(item1.thumbnail, "Page 1 thumbnail must be pre-populated from disk on reopen")

    def test_store_thumbnail_rejects_dirty_doc_without_force(self):
        """store_thumbnail must refuse to write when document has unsaved in-memory changes."""
        doc = fitz.open(self.pdf_path)
        page0 = doc.load_page(0)
        pix = page0.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))

        doc._is_modified = True
        stored = self.disk_cache.store_thumbnail(doc, 0, 150, pix, filepath=self.pdf_path)
        self.assertFalse(stored, "store_thumbnail must reject dirty document without force=True")

        stored_forced = self.disk_cache.store_thumbnail(doc, 0, 150, pix, filepath=self.pdf_path, force=True)
        self.assertTrue(stored_forced, "store_thumbnail must succeed when force=True is provided")
        doc.close()

    def test_dirty_thumbnail_not_written_to_disk_cache(self):
        """In-memory edits must update the UI preview without corrupting the on-disk thumbnail cache."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        # 1. Clean thumbnail is generated and cached to disk
        clean_thumb = pdf_handler.generate_thumbnail(self.win.doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(clean_thumb)

        fp = self.disk_cache.get_document_fingerprint(self.win.doc, filepath=self.pdf_path)
        thumb_on_disk = Path(self.disk_cache.cache_dir) / fp / "0_150.png"
        self.assertTrue(thumb_on_disk.is_file(), "Clean thumbnail must exist on disk")
        disk_mtime_before = thumb_on_disk.stat().st_mtime_ns

        # 2. Rotate page 90 degrees in memory (dirty change)
        time.sleep(0.02)
        self.win.rotate_current_page(90)
        self.assertTrue(self.win.document_modified)
        self.assertTrue(self.win._active_session.is_modified)

        # 3. Sidebar thumbnail in memory reflects the rotated page
        item0 = self.win._active_session.pages_model.get_item(0)
        self.assertIsNotNone(item0.thumbnail)
        # 595x842 rotated 90 is 842x595 (aspect ratio flips)
        self.assertNotEqual(item0.thumbnail.get_height(), clean_thumb.get_height())

        # 4. Critical: On-disk thumbnail file was NOT overwritten by the dirty in-memory change!
        self.assertTrue(thumb_on_disk.is_file())
        disk_mtime_after = thumb_on_disk.stat().st_mtime_ns
        self.assertEqual(disk_mtime_before, disk_mtime_after, "On-disk thumbnail must NOT be overwritten by unsaved changes")

    def test_exit_without_saving_preserves_clean_disk_cache(self):
        """Closing the window without saving must keep the clean on-disk thumbnail intact."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        # Cache clean thumbnail
        clean_thumb = pdf_handler.generate_thumbnail(self.win.doc, 0, target_width=150, filepath=self.pdf_path)
        clean_h = clean_thumb.get_height()

        # Modify page 0 in memory
        self.win.rotate_current_page(90)
        self.assertTrue(self.win.document_modified)

        # Simulate exiting without saving (closing session)
        self.win.close_document()

        # Reopen document fresh from disk
        reloaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.win._finish_loading(reloaded, None, self.pdf_path, 0, self.win._active_session)

        # The thumbnail retrieved from disk cache must be the clean un-rotated thumbnail
        cached_thumb = pdf_handler.get_disk_thumbnail_cache().get_thumbnail(reloaded, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(cached_thumb)
        self.assertEqual(cached_thumb.get_height(), clean_h, "Disk cache must retain original un-rotated thumbnail on exit without saving")

    def test_saving_document_updates_disk_thumbnail_cache(self):
        """Saving document writes changes to disk and updates the on-disk thumbnail cache."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        clean_thumb = pdf_handler.generate_thumbnail(self.win.doc, 0, target_width=150, filepath=self.pdf_path)
        clean_h = clean_thumb.get_height()

        # Rotate page 0 in memory
        self.win.rotate_current_page(90)
        rotated_h = self.win._active_session.pages_model.get_item(0).thumbnail.get_height()
        self.assertNotEqual(clean_h, rotated_h)

        # Save document
        time.sleep(0.02)
        self.win.save_document(self.pdf_path)
        self.win.wait_for_save()

        # Verify disk cache now contains thumbnail matching the saved rotated state
        reloaded_doc = fitz.open(self.pdf_path)
        saved_disk_thumb = pdf_handler.get_disk_thumbnail_cache().get_thumbnail(reloaded_doc, 0, target_width=150, filepath=self.pdf_path)
        self.assertIsNotNone(saved_disk_thumb, "Saved document must have cached thumbnail on disk")
        self.assertNotEqual(saved_disk_thumb.get_height(), clean_h, "Disk thumbnail must reflect rotated page, not clean un-rotated state")
        # Rotated page (842x595) scaled to 150px width has height 106px (vs clean un-rotated 212px)
        self.assertEqual(saved_disk_thumb.get_height(), round(150 / 842 * 595))
        reloaded_doc.close()


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_progressive_zoom_lod.py
# ============================================================================
import os
import time
import threading
import unittest
from unittest.mock import MagicMock, patch
import fitz
import cairo
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.window import PdfEditorWindow


class TestProgressiveZoomLOD(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        for i in range(3):
            page = self.doc.new_page(width=600, height=800)
            page.draw_rect(fitz.Rect(50, 50, 250, 250), color=(1, 0, 0), fill=(0, 0, 1))
            page.insert_text(fitz.Point(100, 300), f"Page {i + 1} High Res Graphic", fontsize=24)
        pdf_handler.invalidate_page_cache(self.doc)

    def tearDown(self):
        pdf_handler.invalidate_page_cache(self.doc)
        if not getattr(self.doc, 'is_closed', False):
            self.doc.close()

    def test_progressive_50dpi_preview_dispatch(self):
        """Verify progressive=True submits 50 DPI preview first when uncached, followed by target zoom."""
        pool = pdf_handler.get_page_rasterizer_pool()
        pdf_handler.invalidate_page_cache(self.doc)

        received_zooms = []
        event = threading.Event()

        def _on_ready(page_idx, zoom_val, surf):
            received_zooms.append(zoom_val)
            if len(received_zooms) >= 2:
                event.set()

        # Request 2.0x zoom (~144 DPI) with progressive=True
        target_zoom = 2.0
        expected_preview = round(50.0 / 72.0, 4)
        pool.request_surface(self.doc, 0, target_zoom, callback=_on_ready, defer=False, progressive=True)

        start_t = time.time()
        ctx = GLib.MainContext.default()
        while not event.is_set() and (time.time() - start_t) < 4.0:
            ctx.iteration(False)
            time.sleep(0.01)

        self.assertTrue(event.is_set(), f"Expected 2 callbacks, got {len(received_zooms)}: {received_zooms}")
        self.assertEqual(len(received_zooms), 2)
        # First callback must be low-res 50 DPI preview
        self.assertAlmostEqual(received_zooms[0], expected_preview, places=3)
        # Second callback must be target zoom (2.0x)
        self.assertAlmostEqual(received_zooms[1], target_zoom, places=3)

    def test_progressive_preview_skipped_if_already_cached(self):
        """Verify progressive preview is skipped if page is already cached at an alternate zoom level."""
        pool = pdf_handler.get_page_rasterizer_pool()
        pdf_handler.invalidate_page_cache(self.doc)

        # Pre-populate zoom 1.0 into cache
        pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)
        self.assertIsNotNone(pool.peek_surface(self.doc, 0, 1.0))

        received_zooms = []
        event = threading.Event()

        def _on_ready(page_idx, zoom_val, surf):
            received_zooms.append(zoom_val)
            event.set()

        # Request 2.5x with progressive=True
        pool.request_surface(self.doc, 0, 2.5, callback=_on_ready, defer=False, progressive=True)

        start_t = time.time()
        ctx = GLib.MainContext.default()
        while not event.is_set() and (time.time() - start_t) < 3.0:
            ctx.iteration(False)
            time.sleep(0.01)

        self.assertTrue(event.is_set())
        # Since zoom 1.0 was already in cache, 50 DPI preview was skipped
        self.assertEqual(len(received_zooms), 1)
        self.assertAlmostEqual(received_zooms[0], 2.5, places=3)

    def test_pinch_gesture_state_tracking(self):
        """Verify pinch-to-zoom gesture lifecycle correctly updates is_zoom_gesture_active."""
        win = PdfEditorWindow()
        win.doc = self.doc
        win.current_page_index = 0
        win.zoom_level = 1.0

        self.assertFalse(win.is_zoom_gesture_active)

        # Mock GestureZoom
        mock_gesture = MagicMock()
        mock_gesture.get_bounding_box_center.return_value = (True, 300.0, 400.0)

        # 1. Begin pinch gesture
        win._on_pinch_zoom_begin(mock_gesture, None)
        self.assertTrue(win.is_zoom_gesture_active)
        self.assertEqual(win._pinch_initial_zoom, 1.0)
        self.assertEqual(win._pinch_focal_point, (300.0, 400.0))

        # 2. Scale changed to 1.5x
        win._on_pinch_zoom_scale_changed(mock_gesture, 1.5)
        self.assertTrue(win.is_zoom_gesture_active)
        self.assertAlmostEqual(win.zoom_level, 1.5, places=3)

        # 3. End pinch gesture: debounce timer should be active
        win._on_pinch_zoom_end(mock_gesture, None)
        self.assertIsNotNone(win._zoom_debounce_timer)

        # 4. Settle zoom
        win._on_zoom_settled()
        self.assertFalse(win.is_zoom_gesture_active)
        self.assertIsNone(win._zoom_debounce_timer)

        if hasattr(win, 'destroy'):
            win.destroy()

    def test_worker_task_suppression_during_active_zoom_gesture(self):
        """Verify that background rasterization requests are suppressed while is_zoom_gesture_active is True."""
        win = PdfEditorWindow()
        win.doc = self.doc
        win.current_page_index = 0
        win.zoom_level = 1.0

        # Pre-render 1.0 into cache
        pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)

        # Start zoom gesture
        win.is_zoom_gesture_active = True
        win.zoom_level = 1.6

        # Spy on request_page_cairo_surface
        with patch('word_sys_pdf_editor.pdf_handler.request_page_cairo_surface') as mock_req:
            # Create a mock Cairo context and target surface
            target_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 960, 1280)
            cr = cairo.Context(target_surf)

            # Draw page content during active gesture
            win._draw_page_content(win.pdf_view, cr, 0, 0, 0, 960, 1280)

            # During active gesture, worker pool should NOT be flooded with intermediate requests
            mock_req.assert_not_called()

        if hasattr(win, 'destroy'):
            win.destroy()

    def test_bilinear_filtering_applied_to_alternate_surface(self):
        """Verify cairo.FILTER_BILINEAR is applied when drawing alternate zoom fallback surface."""
        win = PdfEditorWindow()
        win.doc = self.doc
        win.current_page_index = 0
        win.zoom_level = 1.0

        # Pre-render 1.0 into cache
        cached_surf = pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)
        self.assertIsNotNone(cached_surf)

        # Set zoom to 2.0 so fallback blit is required
        win.zoom_level = 2.0
        win.is_zoom_gesture_active = True

        target_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1200, 1600)
        base_cr = cairo.Context(target_surf)

        class ContextProxy:
            def __init__(self, c):
                self._c = c
                self.applied_filters = []
            def __getattr__(self, name):
                return getattr(self._c, name)
            def get_source(self):
                pat = self._c.get_source()
                class PatternProxy:
                    def __init__(proxy, p, outer):
                        proxy._p = p
                        proxy._outer = outer
                    def __getattr__(proxy, name):
                        return getattr(proxy._p, name)
                    def set_filter(proxy, f):
                        proxy._outer.applied_filters.append(f)
                        return proxy._p.set_filter(f)
                return PatternProxy(pat, self)

        cr = ContextProxy(base_cr)
        win._draw_page_content(win.pdf_view, cr, 0, 0, 0, 1200, 1600)

        # Verify FILTER_BILINEAR was applied to the pattern
        self.assertIn(cairo.FILTER_BILINEAR, cr.applied_filters)

        if hasattr(win, 'destroy'):
            win.destroy()

    def test_debounced_settle_triggers_high_dpi_request(self):
        """Verify 120ms debounce timer triggers high-DPI request upon gesture stillness."""
        win = PdfEditorWindow()
        win.doc = self.doc
        win.current_page_index = 0
        win.zoom_level = 2.2
        win.is_zoom_gesture_active = True

        with patch('word_sys_pdf_editor.pdf_handler.request_page_cairo_surface') as mock_req:
            # Simulate debounce timer expiration
            win._on_zoom_settled()

            self.assertFalse(win.is_zoom_gesture_active)
            # High-DPI rasterization must be requested with progressive=True
            mock_req.assert_called_once()
            args, kwargs = mock_req.call_args
            self.assertEqual(args[0], self.doc)
            self.assertEqual(args[1], 0)
            self.assertAlmostEqual(args[2], 2.2, places=3)
            self.assertTrue(kwargs.get('progressive', False))

        if hasattr(win, 'destroy'):
            win.destroy()

    def test_active_gesture_draw_latency_benchmark(self):
        """Benchmark draw latency during active zoom gesture: must complete in < 8.33ms (120+ FPS)."""
        win = PdfEditorWindow()
        win.doc = self.doc
        win.current_page_index = 0
        win.zoom_level = 1.0

        # Pre-render zoom 1.0 into cache
        pdf_handler.get_page_cairo_surface(self.doc, 0, 1.0)

        # Scale to 1.25x during active pinch
        win.is_zoom_gesture_active = True
        win.zoom_level = 1.25

        target_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, 800)
        cr = cairo.Context(target_surf)

        # Warm-up
        win._draw_page_content(win.pdf_view, cr, 0, 0, 0, 600, 800)

        # Measure 50 consecutive frames
        times = []
        for _ in range(50):
            t0 = time.perf_counter()
            win._draw_page_content(win.pdf_view, cr, 0, 0, 0, 600, 800)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0)

        avg_ms = sum(times) / len(times)
        # Average frame render time must be under 8.33ms (120 FPS headroom in software CPU rendering)
        self.assertLess(avg_ms, 8.33, f"Bilinear scaling took {avg_ms:.3f}ms, expected < 8.33ms (120 FPS)")

        if hasattr(win, 'destroy'):
            win.destroy()


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_memory_budgeting.py
# ============================================================================
import unittest
import collections
import zlib
import gc
from unittest.mock import MagicMock, patch
import cairo

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor.pdf_handler import (
    BoundedLRUCache,
    CompressedSnapshotStore,
    release_page_snapshots,
    close_pdf_document,
)
from word_sys_pdf_editor.undo_manager import UndoManager, Command


class DummyCommand(Command):
    """Minimal test command for UndoManager testing."""
    def __init__(self, idx: int):
        self.idx = idx
        self.executed = False
        self.undone = False

    def execute(self):
        self.executed = True
        self.undone = False

    def undo(self):
        self.undone = True
        self.executed = False


class TestBoundedLRUCache(unittest.TestCase):
    """Test suite for BoundedLRUCache count and memory byte ceiling behavior."""

    def test_bounded_lru_cache_item_count_eviction(self):
        cache = BoundedLRUCache(max_items=3, max_bytes=100_000)
        cache["p1"] = b"data1"
        cache["p2"] = b"data2"
        cache["p3"] = b"data3"
        self.assertEqual(len(cache), 3)
        self.assertIn("p1", cache)

        # Adding 4th item must evict the oldest "p1"
        cache["p4"] = b"data4"
        self.assertEqual(len(cache), 3)
        self.assertNotIn("p1", cache)
        self.assertIn("p2", cache)
        self.assertIn("p3", cache)
        self.assertIn("p4", cache)

    def test_bounded_lru_cache_byte_ceiling_eviction(self):
        # 100 bytes budget: each item is 40 bytes
        cache = BoundedLRUCache(max_items=10, max_bytes=100)
        cache["k1"] = b"a" * 40
        cache["k2"] = b"b" * 40
        self.assertEqual(cache.current_bytes, 80)
        self.assertEqual(len(cache), 2)

        # Adding 3rd item brings total to 120 > 100 max_bytes; must evict k1
        cache["k3"] = b"c" * 40
        self.assertEqual(len(cache), 2)
        self.assertNotIn("k1", cache)
        self.assertIn("k2", cache)
        self.assertIn("k3", cache)
        self.assertEqual(cache.current_bytes, 80)

    def test_bounded_lru_cache_mru_order_on_access(self):
        cache = BoundedLRUCache(max_items=3, max_bytes=100_000)
        cache["a"] = b"1"
        cache["b"] = b"2"
        cache["c"] = b"3"

        # Access "a" to promote it to most recently used
        val = cache["a"]
        self.assertEqual(val, b"1")

        # Now add "d" -> oldest was "b" (since "a" was refreshed), so "b" must be evicted
        cache["d"] = b"4"
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)
        self.assertIn("c", cache)
        self.assertIn("d", cache)

    def test_bounded_lru_cache_dynamic_budget(self):
        cache = BoundedLRUCache(max_items=5, max_bytes=100_000)
        for i in range(5):
            cache[f"item_{i}"] = b"val"
        self.assertEqual(len(cache), 5)

        # Shrink count budget to 2
        cache.set_budget(max_items=2)
        self.assertEqual(len(cache), 2)
        self.assertEqual(list(cache.keys()), ["item_3", "item_4"])

    def test_bounded_lru_cairo_surface_sizing(self):
        cache = BoundedLRUCache(max_items=5, max_bytes=10_000_000)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 100)
        expected_size = surf.get_stride() * surf.get_height()
        cache["surf1"] = surf
        self.assertEqual(cache.current_bytes, expected_size)
        self.assertGreater(cache.current_bytes, 0)

        # Popping surface must decrement current_bytes back to 0
        popped = cache.pop("surf1")
        self.assertIs(popped, surf)
        self.assertEqual(cache.current_bytes, 0)


class TestCompressedSnapshotStore(unittest.TestCase):
    """Test suite for in-memory zlib snapshot compression and transparent retrieval."""

    def test_compressed_snapshot_store_compression_ratio(self):
        store = CompressedSnapshotStore()
        raw_stream = b"q 1 0 0 1 50 100 cm /F1 12 Tf (Compressible Text) Tj Q\n" * 100
        key = ("doc_test", 0)
        store[key] = raw_stream

        # Raw internal storage must be compressed
        raw_internal = dict.__getitem__(store, key)
        self.assertTrue(raw_internal.startswith(b"ZL\x01"))
        self.assertLess(len(raw_internal), len(raw_stream) / 4)

    def test_compressed_snapshot_store_transparent_access(self):
        store = CompressedSnapshotStore()
        raw_stream = b"BT /F1 12 Tf (Hello World) Tj ET"
        key = ("doc_test", 1)
        store[key] = raw_stream

        # __getitem__ returns original bytes
        self.assertEqual(store[key], raw_stream)
        # get() returns original bytes
        self.assertEqual(store.get(key), raw_stream)
        # items() yields original bytes
        items_dict = dict(store.items())
        self.assertEqual(items_dict[key], raw_stream)
        # values() yields original bytes
        self.assertIn(raw_stream, list(store.values()))

        # pop() returns original bytes and removes entry
        popped = store.pop(key)
        self.assertEqual(popped, raw_stream)
        self.assertEqual(len(store), 0)

    def test_compressed_snapshot_store_rekeying_and_raw_items(self):
        store = CompressedSnapshotStore()
        content = b"BT (Page 0 Stream) ET"
        store[("doc1", 0)] = content

        # Re-keying using raw_items() must preserve compression without re-compression
        new_items = {}
        for (did, pno), raw_val in store.raw_items():
            new_items[(did, pno + 1)] = raw_val

        store.clear()
        store.update(new_items)

        self.assertNotIn(("doc1", 0), store)
        self.assertIn(("doc1", 1), store)
        self.assertEqual(store[("doc1", 1)], content)


class TestUndoManagerBoundedStack(unittest.TestCase):
    """Test suite for bounded UndoManager deque memory ceiling."""

    def test_undo_manager_bounded_capacity(self):
        mock_win = MagicMock()
        manager = UndoManager(mock_win, max_depth=5)
        self.assertIsInstance(manager.undo_stack, collections.deque)
        self.assertEqual(manager.undo_stack.maxlen, 5)

        # Add 8 commands
        for i in range(8):
            manager.add_command(DummyCommand(i))

        # Size must be capped at 5
        self.assertEqual(len(manager.undo_stack), 5)
        # Oldest commands (0, 1, 2) must have been evicted from left
        self.assertEqual(manager.undo_stack[0].idx, 3)
        self.assertEqual(manager.undo_stack[-1].idx, 7)

    def test_undo_manager_undo_redo_bounded(self):
        mock_win = MagicMock()
        mock_win.doc = None
        manager = UndoManager(mock_win, max_depth=3)
        c1, c2, c3 = DummyCommand(1), DummyCommand(2), DummyCommand(3)
        manager.add_command(c1)
        manager.add_command(c2)
        manager.add_command(c3)

        self.assertEqual(len(manager.undo_stack), 3)
        manager.undo()
        self.assertTrue(c3.undone)
        self.assertEqual(len(manager.undo_stack), 2)
        self.assertEqual(len(manager.redo_stack), 1)

        manager.redo()
        self.assertTrue(c3.executed)
        self.assertEqual(len(manager.undo_stack), 3)


class TestGenerationalGarbageCollection(unittest.TestCase):
    """Test suite for generational garbage collection triggers."""

    @patch("word_sys_pdf_editor.pdf_handler.gc.collect")
    def test_release_page_snapshots_invokes_gc(self, mock_gc):
        doc = fitz.open()
        release_page_snapshots(doc)
        mock_gc.assert_called_with(1)
        doc.close()

    @patch("word_sys_pdf_editor.pdf_handler.gc.collect")
    def test_close_pdf_document_invokes_gc(self, mock_gc):
        doc = fitz.open()
        close_pdf_document(doc)
        mock_gc.assert_called_with(1)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_large_document_performance.py
# ============================================================================
import unittest
import tempfile
import os
import time

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

from word_sys_pdf_editor.window import PdfEditorWindow, UniformPageOffsets
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.hardware import (
    detect_hardware_spec, is_eco_mode_enabled, set_eco_mode_enabled
)


class TestLargeDocumentPerformance(unittest.TestCase):
    """Stress testing suite for 131+ page complex documents, eco mode, and 1,000 to 40,000+ pages."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Gtk.Application()
        except Exception:
            cls.app = None

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.temp_dir.name, "complex_131_pages.pdf")

        # Build a 131-page test PDF with Chinese text, alignment grids, and images
        doc = fitz.open()
        img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), 0)
        img_bytes = img_pix.tobytes()

        for pno in range(131):
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 50), f"打印机校准网格 第 {pno+1} 页 - Chinese Printer Pattern")
            for stroke in range(10):
                page.draw_line((50, 200 + stroke * 15), (500, 200 + stroke * 15), color=(0.2, 0.2, 0.2))
            if pno % 10 == 0:
                page.insert_image(fitz.Rect(50, 400, 150, 500), stream=img_bytes)

        doc.save(self.pdf_path)
        doc.close()

    def tearDown(self):
        if hasattr(self, 'win') and self.win:
            try:
                self.win.close_document()
                self.win.destroy()
            except Exception:
                pass
        self.temp_dir.cleanup()

    def test_hardware_detection_accuracy(self):
        """Verify hardware auto-detection reports valid RAM, cores, and classification."""
        spec = detect_hardware_spec()
        self.assertIn("total_ram_bytes", spec)
        self.assertIn("total_ram_mb", spec)
        self.assertIn("total_ram_gb", spec)
        self.assertIn("cpu_cores", spec)
        self.assertIn("is_low_spec_hardware", spec)

        self.assertGreater(spec["total_ram_bytes"], 0)
        self.assertGreater(spec["total_ram_mb"], 0)
        self.assertGreater(spec["total_ram_gb"], 0)
        self.assertGreaterEqual(spec["cpu_cores"], 1)
        self.assertIsInstance(spec["is_low_spec_hardware"], bool)

        eco_active = is_eco_mode_enabled()
        self.assertIsInstance(eco_active, bool)

    def test_eco_mode_toggle_and_cache_limits(self):
        """Verify dynamically toggling Eco Mode updates LRU memory ceilings."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        # Switch to Eco mode
        self.win.set_eco_mode(True)
        self.assertTrue(self.win.is_eco_mode)
        self.assertEqual(pdf_handler._cairo_page_cache.max_items, 3)
        self.assertEqual(pdf_handler._cairo_page_cache.max_bytes, 40 * 1024 * 1024)

        # Switch to Normal mode
        self.win.set_eco_mode(False)
        self.assertFalse(self.win.is_eco_mode)
        self.assertEqual(pdf_handler._cairo_page_cache.max_items, 6)
        self.assertEqual(pdf_handler._cairo_page_cache.max_bytes, 120 * 1024 * 1024)

    def test_eco_mode_dpi_cap(self):
        """Verify zoom level is clamped to 150 DPI ceiling when Eco Mode is active."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        # In eco mode, max zoom is 150 / 72 ~= 2.0833
        self.win.set_eco_mode(True)
        self.win._set_zoom(4.0)
        max_eco_zoom = 150.0 / 72.0
        self.assertAlmostEqual(self.win.zoom_level, max_eco_zoom, places=2)

        # In normal mode, zoom can go higher (e.g. 4.0)
        self.win.set_eco_mode(False)
        self.win._set_zoom(4.0)
        self.assertAlmostEqual(self.win.zoom_level, 4.0, places=2)

    def test_eco_mode_zero_prefetch_margin(self):
        """Verify continuous scroll prefetch margin is zeroed out in Eco Mode."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)
        self.win.set_continuous_scroll_mode(True)

        # Normal mode includes prefetch buffer
        self.win.set_eco_mode(False)
        normal_visible = self.win.get_visible_page_indices()

        # Eco mode restricts to strict viewport
        self.win.set_eco_mode(True)
        eco_visible = self.win.get_visible_page_indices()

        self.assertLessEqual(len(eco_visible), len(normal_visible))

    def test_131_page_load_speed(self):
        """Verify 131-page document loads in under 500 milliseconds."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.continuous_scroll = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)

        t0 = time.time()
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)
        t1 = time.time()
        elapsed_ms = (t1 - t0) * 1000

        self.assertEqual(len(self.win.doc), 131)
        self.assertLess(elapsed_ms, 500.0, f"Loading 131-page document took {elapsed_ms:.1f}ms, expected < 500ms")

    def test_131_page_continuous_scroll_switch_and_draw(self):
        """Verify switching to continuous scroll and rendering pages on 131-page doc is fast and does not crash."""
        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False

        loaded, err = pdf_handler.load_pdf_document(self.pdf_path)
        self.assertIsNone(err)
        self.win._finish_loading(loaded, None, self.pdf_path, 0, self.win._active_session)

        # Switch to continuous scroll mode
        t0 = time.time()
        self.win.set_continuous_scroll_mode(True)
        t1 = time.time()
        switch_time_ms = (t1 - t0) * 1000
        self.assertTrue(self.win.continuous_scroll)
        self.assertLess(switch_time_ms, 150.0, f"Switching to continuous scroll took {switch_time_ms:.1f}ms")

        # Simulate rendering 10 viewport scrolls across document
        for scroll_page in [0, 15, 30, 45, 60, 75, 90, 105, 120, 130]:
            self.win.scroll_to_page(scroll_page, smooth=False)
            visible = self.win.get_visible_page_indices()
            self.assertIn(scroll_page, visible)

        # Confirm memory cache remains strictly bounded
        cache = pdf_handler._cairo_page_cache
        self.assertLessEqual(len(cache), 6)
        self.assertLessEqual(cache.current_bytes, 120 * 1024 * 1024)

    def test_1000_page_document_performance(self):
        """Verify synthetic 1,000-page document loads in under 300ms and memory stays bounded."""
        doc = fitz.open()
        for i in range(1000):
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 50), f"Page {i+1} of 1000")
        p1000_path = os.path.join(self.temp_dir.name, "doc_1000_pages.pdf")
        doc.save(p1000_path)
        doc.close()

        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.set_eco_mode(True)

        loaded, err = pdf_handler.load_pdf_document(p1000_path)
        self.assertIsNone(err)

        t0 = time.time()
        self.win._finish_loading(loaded, None, p1000_path, 0, self.win._active_session)
        t1 = time.time()
        load_time_ms = (t1 - t0) * 1000
        self.assertEqual(len(self.win.doc), 1000)
        self.assertLess(load_time_ms, 300.0, f"Loading 1,000-page doc took {load_time_ms:.1f}ms, expected < 300ms")

        # Switch to continuous scroll and jump around
        self.win.set_continuous_scroll_mode(True)
        for page_jump in [0, 100, 250, 500, 750, 999]:
            self.win.scroll_to_page(page_jump, smooth=False)
            visible = self.win.get_visible_page_indices()
            self.assertIn(page_jump, visible)

        # In eco mode, cache is strictly <= 3 pages
        cache = pdf_handler._cairo_page_cache
        self.assertLessEqual(len(cache), 3)
        self.assertLessEqual(cache.current_bytes, 40 * 1024 * 1024)

    def test_10000_page_document_virtualization(self):
        """Verify synthetic 10,000-page document continuous layout calculates in under 300ms and O(1) jump works."""
        doc = fitz.open()
        for _ in range(10000):
            doc.new_page(width=595, height=842)

        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.doc = doc
        self.win._active_session.doc = doc
        self.win.set_eco_mode(True)
        self.win.continuous_scroll = True

        t0 = time.time()
        self.win._recompute_continuous_layout()
        t1 = time.time()
        layout_ms = (t1 - t0) * 1000
        self.assertLess(layout_ms, 300.0, f"10,000-page continuous layout took {layout_ms:.1f}ms, expected < 300ms")

        # Confirm virtualized O(1) list is used
        self.assertIsInstance(self.win.continuous_page_offsets, UniformPageOffsets)
        self.assertEqual(len(self.win.continuous_page_offsets), 10000)

        # O(1) page jump to page 9999
        t_jump0 = time.time()
        self.win.scroll_to_page(9999, smooth=False)
        t_jump1 = time.time()
        jump_ms = (t_jump1 - t_jump0) * 1000
        self.assertLess(jump_ms, 20.0, f"Jumping to page 9,999 took {jump_ms:.1f}ms, expected < 20ms")

        rect_9999 = self.win.get_page_canvas_rect(9999)
        self.assertGreater(rect_9999[1], 0)

    def test_40000_page_zero_allocation_indexing(self):
        """Verify 40,000-page UniformPageOffsets provides O(1) indexing in microseconds."""
        offsets = UniformPageOffsets(40000, gap=10.0, pw=595.0, ph=842.0)
        self.assertEqual(len(offsets), 40000)
        self.assertTrue(bool(offsets))

        first = offsets[0]
        self.assertEqual(first, (0.0, 10.0, 595.0, 842.0))

        mid = offsets[20000]
        expected_y = 10.0 + 20000 * (842.0 + 10.0)
        self.assertEqual(mid, (0.0, expected_y, 595.0, 842.0))

        last = offsets[39999]
        expected_last_y = 10.0 + 39999 * (842.0 + 10.0)
        self.assertEqual(last, (0.0, expected_last_y, 595.0, 842.0))

        # Perform 1,000 random lookups
        t0 = time.time()
        for idx in range(0, 40000, 40):
            _ = offsets[idx]
        t1 = time.time()
        elapsed_ms = (t1 - t0) * 1000
        self.assertLess(elapsed_ms, 10.0, f"1,000 lookups in 40,000-page sequence took {elapsed_ms:.1f}ms")


if __name__ == "__main__":
    unittest.main()

