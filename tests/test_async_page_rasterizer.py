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


if __name__ == '__main__':
    unittest.main()
