import unittest
import time
import os
from unittest.mock import MagicMock, patch

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from word_sys_pdf_editor.window import PdfEditorWindow, ScrollVelocityTracker
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.i18n import set_setting


class TestDirectionalScrollPrefetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Adw.Application(application_id='org.word_sys.test_prefetch')
        except Exception:
            cls.app = None

    def setUp(self):
        self.tracker = ScrollVelocityTracker(sample_window_sec=0.25)
        test_pdf = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_testsre.pdf')
        if os.path.exists(test_pdf):
            self.doc = fitz.open(test_pdf)
            self.pdf_path = test_pdf
        else:
            self.doc = fitz.open()
            for i in range(100):
                p = self.doc.new_page(width=504, height=657)
                p.insert_text((50, 50), f"Page {i}")
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

    def test_scroll_velocity_tracker_downward_rapid(self):
        """Verify rapid downward scroll calculates positive velocity and prefetch lookahead [+1, +2, +3]."""
        self.tracker.record_scroll(100.0, now=1.0)
        v, d = self.tracker.record_scroll(500.0, now=1.2)  # delta=400px over 0.2s -> 2000 px/s

        self.assertGreater(v, 400.0)
        self.assertEqual(d, ScrollVelocityTracker.DIRECTION_DOWN)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [22, 23, 24])

    def test_scroll_velocity_tracker_upward_rapid(self):
        """Verify rapid upward scroll calculates negative velocity and prefetch lookahead [-1, -2, -3]."""
        self.tracker.record_scroll(500.0, now=1.0)
        v, d = self.tracker.record_scroll(100.0, now=1.2)  # delta=-400px over 0.2s -> -2000 px/s

        self.assertLess(v, -400.0)
        self.assertEqual(d, ScrollVelocityTracker.DIRECTION_UP)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [19, 18, 17])

    def test_scroll_velocity_tracker_moderate_downward(self):
        """Verify moderate downward scroll biases ahead [+1, +2] with single page behind."""
        self.tracker.record_scroll(100.0, now=1.0)
        v, d = self.tracker.record_scroll(150.0, now=1.25)  # 200 px/s

        self.assertGreater(v, 60.0)
        self.assertLessEqual(v, 400.0)
        self.assertEqual(d, ScrollVelocityTracker.DIRECTION_DOWN)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [22, 23, 19])

    def test_scroll_velocity_tracker_moderate_upward(self):
        """Verify moderate upward scroll biases ahead [-1, -2] with single page behind."""
        self.tracker.record_scroll(150.0, now=1.0)
        v, d = self.tracker.record_scroll(100.0, now=1.25)  # -200 px/s

        self.assertLess(v, -60.0)
        self.assertGreaterEqual(v, -400.0)
        self.assertEqual(d, ScrollVelocityTracker.DIRECTION_UP)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [19, 18, 22])

    def test_scroll_velocity_tracker_settled_balanced(self):
        """Verify stillness/settle restores balanced lookahead [-1, +1]."""
        self.tracker.reset()
        self.assertEqual(self.tracker.velocity, 0.0)
        self.assertEqual(self.tracker.direction, ScrollVelocityTracker.DIRECTION_NONE)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [19, 22])

    def test_scroll_velocity_tracker_boundary_clipping(self):
        """Verify prefetch candidates are strictly bounded by [0, total_pages - 1]."""
        # At start of document, scrolling up
        self.tracker.record_scroll(100.0, now=1.0)
        self.tracker.record_scroll(0.0, now=1.1)
        pages = self.tracker.get_prefetch_page_indices([0], total_pages=50)
        self.assertEqual(pages, [])

        # At end of document, scrolling down
        self.tracker.reset()
        self.tracker.record_scroll(100.0, now=1.0)
        self.tracker.record_scroll(300.0, now=1.1)
        pages = self.tracker.get_prefetch_page_indices([49], total_pages=50)
        self.assertEqual(pages, [])

    def test_scroll_velocity_tracker_eco_mode_limits(self):
        """Verify eco mode limits prefetch to at most 1 page ahead in motion direction."""
        self.tracker.record_scroll(100.0, now=1.0)
        self.tracker.record_scroll(600.0, now=1.2)

        pages_normal = self.tracker.get_prefetch_page_indices([10], total_pages=50, is_eco_mode=False)
        self.assertEqual(pages_normal, [11, 12, 13])

        pages_eco = self.tracker.get_prefetch_page_indices([10], total_pages=50, is_eco_mode=True)
        self.assertEqual(pages_eco, [11])

    def test_window_on_canvas_scrolled_triggers_predictive_prefetch(self):
        """Verify window scroll event triggers directional prefetching on document."""
        self.win._finish_loading(self.doc, None, self.pdf_path or "test.pdf", 0, self.win._active_session)
        self.win._is_programmatic_scrolling = False
        self.win.allocate(1000, 800, -1, None)

        mock_adj = MagicMock()
        mock_adj.get_value.return_value = 2500.0

        with patch.object(self.win, '_trigger_directional_prefetch') as mock_prefetch:
            self.win._on_canvas_scrolled(mock_adj)
            mock_prefetch.assert_called()

    def test_window_scroll_to_page_updates_tracker_direction(self):
        """Verify scroll_to_page sets directional lookahead for upcoming destination pages."""
        self.win._finish_loading(self.doc, None, self.pdf_path or "test.pdf", 0, self.win._active_session)
        self.win.allocate(1000, 800, -1, None)

        total_pages = len(self.doc)
        target = min(50, total_pages - 1)
        self.win.scroll_to_page(target, smooth=False)

        # After navigation to page 50, tracker is reset and settled on target page
        self.assertEqual(self.win._scroll_tracker.direction, ScrollVelocityTracker.DIRECTION_NONE)
        visible = self.win.get_visible_page_indices()
        self.assertIn(target, visible)


if __name__ == '__main__':
    unittest.main()
