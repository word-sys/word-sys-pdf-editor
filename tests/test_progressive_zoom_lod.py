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
