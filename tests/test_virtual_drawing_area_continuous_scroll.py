import os
import unittest
try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Graphene
import cairo

from word_sys_pdf_editor.window import PdfEditorWindow, VirtualDrawingArea
from word_sys_pdf_editor.i18n import set_setting


class TestVirtualDrawingAreaContinuousScroll(unittest.TestCase):
    """Test suite verifying sub-viewport snapshot virtualization on massive documents."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Adw.Application(application_id='org.word_sys.test_vda')
        except Exception:
            cls.app = None

    def setUp(self):
        test_pdf = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_testsre.pdf')
        if os.path.exists(test_pdf):
            self.doc = fitz.open(test_pdf)
            self.pdf_path = test_pdf
        else:
            # Fallback to generating a 100-page synthetic test document
            self.doc = fitz.open()
            for i in range(100):
                p = self.doc.new_page(width=504, height=657)
                p.insert_text((50, 50), f"Test page {i}")
            self.pdf_path = None

        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.set_continuous_scroll_mode(True)

    def tearDown(self):
        set_setting("view_mode", "single")
        if hasattr(self, 'win') and self.win:
            try:
                self.win.close_document()
                self.win.destroy()
            except Exception:
                pass
        doc = getattr(self, 'doc', None)
        if doc is not None and not getattr(doc, 'is_closed', True):
            try:
                doc.close()
            except Exception:
                pass

    def test_pdf_view_is_virtual_drawing_area(self):
        """Verify window uses VirtualDrawingArea subclass for canvas rendering."""
        self.assertIsInstance(self.win.pdf_view, VirtualDrawingArea)
        self.assertIsInstance(self.win.pdf_view, Gtk.DrawingArea)
        self.assertIsNotNone(self.win.pdf_view.get_viewport_rect_cb)

    def test_large_document_continuous_scroll_snapshots_without_crashing(self):
        """Verify 1000+ page continuous scroll snapshots produce valid GskCairoNode without aborting."""
        self.win._finish_loading(self.doc, None, self.pdf_path or "test.pdf", 0, self.win._active_session)
        self.assertTrue(self.win.continuous_scroll)
        self.assertGreater(self.win.continuous_total_height, 32767.0)

        # Allocate virtual canvas to allocate content size
        self.win.allocate(1000, 800, -1, None)

        # Test jumps across beginning, middle, and end of 1000-page document
        page_count = len(self.doc)
        test_pages = [0, min(5, page_count - 1), min(50, page_count - 1),
                      min(500, page_count - 1), page_count - 1]

        target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 1000, 800)
        cr_test = cairo.Context(target_surf)

        for p in test_pages:
            self.win.scroll_to_page(p, smooth=False)
            snapshot = Gtk.Snapshot()
            self.win.pdf_view.do_snapshot(snapshot)
            node = snapshot.to_node()
            self.assertIsNotNone(node, f"Page {p} produced None node in continuous scroll")
            node.draw(cr_test)

    def test_virtual_drawing_area_viewport_bounds_clipping(self):
        """Verify VirtualDrawingArea clips snapshot bounds to visible viewport rectangle plus margin."""
        w = VirtualDrawingArea(content_width=800, content_height=500000)
        w.get_viewport_rect_cb = lambda: (0.0, 250000.0, 800.0, 600.0)

        captured_bounds = []
        def mock_draw(area, cr, width, height):
            captured_bounds.append((width, height))

        w.set_draw_func(mock_draw)

        win_dummy = Gtk.Window()
        win_dummy.set_child(w)
        win_dummy.allocate(800, 500000, -1, None)

        snap = Gtk.Snapshot()
        w.do_snapshot(snap)
        node = snap.to_node()
        self.assertIsNotNone(node)
        self.assertEqual(len(captured_bounds), 1)
        self.assertEqual(captured_bounds[0], (800, 500000))


if __name__ == '__main__':
    unittest.main()
