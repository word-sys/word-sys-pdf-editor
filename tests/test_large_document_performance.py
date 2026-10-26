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

from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor import pdf_handler


class TestLargeDocumentPerformance(unittest.TestCase):
    """Stress testing suite for 131+ page complex documents and continuous scroll."""

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
                page.draw_line((50, 200 + stroke*15), (500, 200 + stroke*15), color=(0.2, 0.2, 0.2))
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


if __name__ == "__main__":
    unittest.main()
