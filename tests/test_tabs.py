import unittest
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath("."))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, Gio, Adw

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor.models import (
    DocumentSession,
    PdfPage,
    EditableText,
    EditableShape,
    EditableStroke,
    EditableImage,
)
from word_sys_pdf_editor.window import PdfEditorWindow


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestTabBarAndTabView(unittest.TestCase):
    """Test suite for TabBar & TabView integration and multi-document tabs."""

    @classmethod
    def setUpClass(cls):
        """Initialize GTK and Adw application once for window tests."""
        cls.app = Adw.Application(application_id="org.test.tabs")

    def setUp(self):
        """Create a fresh PdfEditorWindow instance for each test."""
        self.win = PdfEditorWindow(application=self.app)

    def tearDown(self):
        """Ensure clean teardown of window resources."""
        if hasattr(self, "win") and self.win:
            try:
                for s in list(self.win.sessions):
                    s.is_modified = False
                    self.win.remove_session(s)
                self.win.destroy()
            except Exception:
                pass

    def test_tab_view_and_tab_bar_initialized(self):
        """Verify that Adw.TabView and Adw.TabBar are properly constructed and wired."""
        self.assertIsNotNone(self.win.tab_view)
        self.assertIsInstance(self.win.tab_view, Adw.TabView)
        self.assertIsNotNone(self.win.tab_bar)
        self.assertIsInstance(self.win.tab_bar, Adw.TabBar)
        self.assertEqual(self.win.tab_bar.get_view(), self.win.tab_view)
        self.assertTrue(self.win.tab_bar.get_autohide())

        # Check initial session tab page
        self.assertGreaterEqual(self.win.tab_view.get_n_pages(), 1)
        initial_page = self.win.tab_view.get_nth_page(0)
        self.assertIsNotNone(initial_page)
        self.assertEqual(self.win._active_session.tab_page, initial_page)

    def test_multi_tab_creation_and_switching(self):
        """Verify opening multiple documents creates separate tabs and switches active session."""
        doc1 = fitz.open()
        p1 = doc1.new_page(width=200, height=200)
        p1.insert_text((50, 50), "Document 1 Content")
        s1 = self.win.create_session(doc=doc1, filepath="/tmp/doc1.pdf")
        self.win.add_session(s1, switch_to=True)

        doc2 = fitz.open()
        p2 = doc2.new_page(width=300, height=300)
        p2.insert_text((60, 60), "Document 2 Content")
        s2 = self.win.create_session(doc=doc2, filepath="/tmp/doc2.pdf")
        self.win.add_session(s2, switch_to=True)

        self.assertGreaterEqual(self.win.tab_view.get_n_pages(), 2)
        self.assertEqual(self.win.active_session, s2)
        self.assertEqual(self.win.current_file_path, "/tmp/doc2.pdf")
        self.assertEqual(self.win.tab_view.get_selected_page(), s2.tab_page)

        # Switch tab via TabView selected page
        self.win.tab_view.set_selected_page(s1.tab_page)
        self.assertEqual(self.win.active_session, s1)
        self.assertEqual(self.win.current_file_path, "/tmp/doc1.pdf")
        self.assertEqual(self.win.doc, doc1)

        # Navigate with next_tab / prev_tab
        self.win.on_next_tab()
        self.assertEqual(self.win.active_session, s2)
        self.win.on_prev_tab()
        self.assertEqual(self.win.active_session, s1)

    def test_tab_title_and_dirty_sync(self):
        """Verify tab title and dirty notification are updated when document is modified."""
        doc = fitz.open()
        doc.new_page()
        s = self.win.create_session(doc=doc, filepath="/tmp/test_report.pdf")
        self.win.add_session(s, switch_to=True)

        self.assertEqual(s.tab_page.get_title(), "test_report.pdf")
        self.assertFalse(s.tab_page.get_needs_attention())

        # Modify document
        self.win.document_modified = True
        self.assertEqual(s.tab_page.get_title(), "*test_report.pdf")
        self.assertTrue(s.tab_page.get_needs_attention())

        # Reset modified
        self.win.document_modified = False
        self.assertEqual(s.tab_page.get_title(), "test_report.pdf")
        self.assertFalse(s.tab_page.get_needs_attention())

    def test_close_tab_unmodified(self):
        """Verify closing an unmodified tab closes page without prompting and switches active session."""
        doc1 = fitz.open()
        doc1.new_page()
        s1 = self.win.create_session(doc=doc1, filepath="/tmp/tab1.pdf")
        self.win.add_session(s1, switch_to=True)

        doc2 = fitz.open()
        doc2.new_page()
        s2 = self.win.create_session(doc=doc2, filepath="/tmp/tab2.pdf")
        self.win.add_session(s2, switch_to=True)

        initial_count = self.win.tab_view.get_n_pages()
        self.assertEqual(self.win.active_session, s2)

        # Close active tab
        self.win.on_close_tab()

        self.assertEqual(self.win.tab_view.get_n_pages(), initial_count - 1)
        self.assertNotIn(s2, self.win.sessions)
        self.assertEqual(self.win.active_session, s1)

    @patch("word_sys_pdf_editor.window.show_save_changes_dialog")
    def test_close_tab_modified_cancel(self, mock_dialog):
        """Verify canceling close on a modified tab keeps the tab and modifications intact."""
        mock_dialog.return_value = Gtk.ResponseType.CANCEL

        doc = fitz.open()
        doc.new_page()
        s = self.win.create_session(doc=doc, filepath="/tmp/modified.pdf")
        self.win.add_session(s, switch_to=True)
        self.win.document_modified = True

        initial_count = self.win.tab_view.get_n_pages()
        self.win.on_close_tab()

        # Tab should still be open
        self.assertEqual(self.win.tab_view.get_n_pages(), initial_count)
        self.assertIn(s, self.win.sessions)
        self.assertTrue(s.is_modified)

    @patch("word_sys_pdf_editor.window.show_save_changes_dialog")
    def test_close_tab_modified_discard(self, mock_dialog):
        """Verify choosing Discard on a modified tab closes the tab cleanly."""
        mock_dialog.return_value = Gtk.ResponseType.REJECT

        doc1 = fitz.open()
        doc1.new_page()
        s1 = self.win.create_session(doc=doc1, filepath="/tmp/keep.pdf")
        self.win.add_session(s1, switch_to=True)

        doc2 = fitz.open()
        doc2.new_page()
        s2 = self.win.create_session(doc=doc2, filepath="/tmp/discard_me.pdf")
        self.win.add_session(s2, switch_to=True)
        self.win.document_modified = True

        initial_count = self.win.tab_view.get_n_pages()
        self.win.on_close_tab()

        self.assertEqual(self.win.tab_view.get_n_pages(), initial_count - 1)
        self.assertNotIn(s2, self.win.sessions)
        self.assertEqual(self.win.active_session, s1)

    def test_all_tabs_closed_returns_to_welcome(self):
        """Verify closing the last document session returns window to welcome view."""
        doc = fitz.open()
        doc.new_page()
        s = self.win.create_session(doc=doc, filepath="/tmp/solo.pdf")
        self.win.add_session(s, switch_to=True)
        self.assertEqual(self.win.stack.get_visible_child_name(), "editor")

        # Close all sessions
        for sess in list(self.win.sessions):
            sess.is_modified = False
            self.win.remove_session(sess)

        self.assertEqual(self.win.stack.get_visible_child_name(), "welcome")
        self.assertFalse(self.win.tab_bar.get_visible())

    def test_open_same_document_switches_tab(self):
        """Verify that loading an already open file path switches to its tab rather than duplicating."""
        doc = fitz.open()
        doc.new_page()
        s1 = self.win.create_session(doc=doc, filepath="/tmp/unique.pdf")
        self.win.add_session(s1, switch_to=True)

        doc2 = fitz.open()
        doc2.new_page()
        s2 = self.win.create_session(doc=doc2, filepath="/tmp/other.pdf")
        self.win.add_session(s2, switch_to=True)

        self.assertEqual(self.win.active_session, s2)

        # Attempt to load /tmp/unique.pdf again
        self.win.load_document("/tmp/unique.pdf")
        self.assertEqual(self.win.active_session, s1)

    def test_tab_zoom_label_sync(self):
        """Verify that zoom_label updates correctly when switching between tabs with different zoom levels."""
        doc1 = fitz.open()
        doc1.new_page(width=200, height=200)
        s1 = self.win.create_session(doc=doc1, filepath="/tmp/zoom1.pdf")
        self.win.add_session(s1, switch_to=True)

        doc2 = fitz.open()
        doc2.new_page(width=300, height=300)
        s2 = self.win.create_session(doc=doc2, filepath="/tmp/zoom2.pdf")
        self.win.add_session(s2, switch_to=True)

        # Set s1 zoom to 144%
        s1.zoom_level = 1.44
        # Set s2 zoom to 75%
        s2.zoom_level = 0.75

        # Switch to tab 1
        self.win.set_active_session(s1)
        self.assertEqual(self.win.zoom_level, 1.44)
        self.assertEqual(self.win.zoom_label.get_text(), "144%")

        # Switch to tab 2
        self.win.set_active_session(s2)
        self.assertEqual(self.win.zoom_level, 0.75)
        self.assertEqual(self.win.zoom_label.get_text(), "75%")

        # Switch back to tab 1
        self.win.set_active_session(s1)
        self.assertEqual(self.win.zoom_level, 1.44)
        self.assertEqual(self.win.zoom_label.get_text(), "144%")

    def test_tab_scroll_position_saved_on_switch(self):
        """Verify that scroll coordinates are captured on DocumentSession when switching tabs."""
        doc1 = fitz.open()
        doc1.new_page(width=200, height=200)
        s1 = self.win.create_session(doc=doc1, filepath="/tmp/scroll1.pdf")
        self.win.add_session(s1, switch_to=True)

        doc2 = fitz.open()
        doc2.new_page(width=300, height=300)
        s2 = self.win.create_session(doc=doc2, filepath="/tmp/scroll2.pdf")
        self.win.add_session(s2, switch_to=True)

        # Set fake scroll values on s2's scroll adjustments
        h = self.win.pdf_scroll.get_hadjustment()
        v = self.win.pdf_scroll.get_vadjustment()
        h.set_upper(1000.0)
        v.set_upper(1000.0)
        h.set_value(42.0)
        v.set_value(99.0)

        # Switching to s1 should save s2's scroll values
        self.win.set_active_session(s1)
        self.assertEqual(s2.scroll_x, 42.0)
        self.assertEqual(s2.scroll_y, 99.0)


if __name__ == "__main__":
    unittest.main()
