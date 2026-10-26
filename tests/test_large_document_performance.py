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
