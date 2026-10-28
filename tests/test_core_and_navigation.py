"""Consolidated Core Document Models, Session Management, Navigation, and UI Popovers Test Suite for word-sys-pdf-editor.

This suite validates core document models, actions and shortcuts, multi-tab workspace sessions,
workspace navigation, low-level pdf_handler utilities, smart context popovers, and the hyperlink engine.
"""

# ============================================================================
# SECTION: test_actions.py
# ============================================================================
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("."))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gio
from word_sys_pdf_editor.main import PdfEditorApplication
from word_sys_pdf_editor.window import PdfEditorWindow


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestActions(unittest.TestCase):
    def test_actions_and_shortcuts(self):
        app = PdfEditorApplication(
            application_id=f"org.word_sys.test_actions_{os.getpid()}",
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )

        def on_startup(a):
            win = PdfEditorWindow(application=a)
            a.window = win

            self.assertIsNotNone(win.lookup_action("new"))
            self.assertIsNotNone(win.lookup_action("open"))
            self.assertIsNotNone(win.lookup_action("quick_guide"))
            self.assertIsNotNone(win.lookup_action("save"))

            accels_new = a.get_accels_for_action("win.new")
            accels_open = a.get_accels_for_action("win.open")
            accels_guide = a.get_accels_for_action("win.quick_guide")

            self.assertIn("<Control>n", accels_new)
            self.assertIn("<Control>o", accels_open)
            self.assertIn("F1", accels_guide)

            win.do_close_request()
            GLib.idle_add(a.quit)

        app.connect("startup", on_startup)
        app.run([])


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_models.py
# ============================================================================
import unittest
from word_sys_pdf_editor.models import (
    EditableText, EditableImage, EditableShape, EditableStroke,
    DocumentSession, FLAG_BOLD, FLAG_ITALIC
)


class TestModels(unittest.TestCase):
    def test_editable_text_creation_and_bounds(self):
        text = EditableText(
            100.0,
            150.0,
            "Hello World",
            font_size=16.0,
            color=(0.1, 0.2, 0.3)
        )
        self.assertEqual(text.text, "Hello World")
        self.assertEqual(text.x, 100.0)
        self.assertEqual(text.y, 150.0)
        self.assertFalse(text.is_bold)
        self.assertFalse(text.is_italic)

        text.is_bold = True
        self.assertTrue(text.is_bold)

    def test_editable_shape_properties(self):
        shape = EditableShape(
            shape_type="rectangle",
            bbox=(10.0, 20.0, 110.0, 120.0),
            stroke_color=(0, 0, 0),
            fill_color=(1, 1, 1),
            stroke_width=2.0
        )
        self.assertEqual(shape.shape_type, "rectangle")
        self.assertEqual(shape.stroke_width, 2.0)
        self.assertEqual(shape.bbox, (10.0, 20.0, 110.0, 120.0))

    def test_document_session_lifecycle(self):
        session = DocumentSession(session_id="test-session-1")
        self.assertEqual(session.session_id, "test-session-1")
        self.assertIsNone(session.doc)
        self.assertIsNone(session.pdf_path)
        self.assertFalse(session.is_modified)
        self.assertEqual(session.current_page_index, 0)
        self.assertEqual(session.display_title, "Untitled Document")

        session.is_modified = True
        self.assertTrue(session.is_modified)
        session.is_modified = False
        self.assertFalse(session.is_modified)


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_session.py
# ============================================================================
import unittest
import os
import sys

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
from word_sys_pdf_editor.undo_manager import UndoManager


class TestDocumentSession(unittest.TestCase):
    """Test suite for DocumentSession architecture and window session management."""

    @classmethod
    def setUpClass(cls):
        """Initialize GTK and Adw application once for window tests."""
        cls.app = Adw.Application(application_id="org.test.session")

    def test_document_session_defaults(self):
        """Verify DocumentSession default attributes and properties."""
        session = DocumentSession()
        self.assertIsNotNone(session.session_id)
        self.assertIsNone(session.doc)
        self.assertIsNone(session.pdf_path)
        self.assertIsNone(session.original_file_path)
        self.assertEqual(session.current_page_index, 0)
        self.assertEqual(session.zoom_level, 1.0)
        self.assertTrue(session.view_mode)
        self.assertFalse(session.is_modified)
        self.assertTrue(session.allow_incremental_save)
        self.assertFalse(session.is_repaired_file)
        self.assertEqual(session.title, "Untitled Document")
        self.assertEqual(session.display_title, "Untitled Document")
        self.assertEqual(session.page_count, 0)

    def test_document_session_title_and_modified(self):
        """Verify document session title and display_title with modifications."""
        session = DocumentSession(pdf_path="/path/to/my_report.pdf")
        self.assertEqual(session.title, "my_report.pdf")
        self.assertEqual(session.display_title, "my_report.pdf")

        session.is_modified = True
        self.assertEqual(session.display_title, "*my_report.pdf")

    def test_document_session_page_count(self):
        """Verify page_count reports number of pages accurately."""
        doc = fitz.open()
        doc.new_page(width=300, height=400)
        doc.new_page(width=300, height=400)
        session = DocumentSession(doc=doc)
        self.assertEqual(session.page_count, 2)
        session.close()
        self.assertEqual(session.page_count, 0)

    def test_document_session_close_cleanup(self):
        """Verify session.close() releases doc and clears object collections."""
        doc = fitz.open()
        doc.new_page()
        session = DocumentSession(
            doc=doc,
            editable_texts=[EditableText(10, 10, "Hello")],
            editable_shapes=[EditableShape("rectangle", (0, 0, 50, 50))],
            editable_strokes=[EditableStroke([(0, 0), (10, 10)])],
            editable_images=[EditableImage((0, 0, 50, 50), 0, 0, b"")],
        )
        self.assertEqual(len(session.editable_texts), 1)
        self.assertEqual(len(session.editable_shapes), 1)
        self.assertEqual(len(session.editable_strokes), 1)
        self.assertEqual(len(session.editable_images), 1)

        session.close()
        self.assertIsNone(session.doc)
        self.assertEqual(len(session.editable_texts), 0)
        self.assertEqual(len(session.editable_shapes), 0)
        self.assertEqual(len(session.editable_strokes), 0)
        self.assertEqual(len(session.editable_images), 0)


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestWindowIntegration(unittest.TestCase):
    """Window-level session integration tests."""

    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.test.session_win")

    def test_window_session_pool_initialization(self):
        """Verify PdfEditorWindow initializes sessions pool and active_session."""
        win = PdfEditorWindow(application=self.app)
        self.assertIsNotNone(win.sessions)
        self.assertGreaterEqual(len(win.sessions), 1)
        self.assertIsNotNone(win.active_session)
        self.assertEqual(win.active_session, win.sessions[0])

    def test_window_property_delegation(self):
        """Verify properties on PdfEditorWindow transparently read and write active session."""
        win = PdfEditorWindow(application=self.app)

        # File path
        win.current_file_path = "/tmp/test.pdf"
        self.assertEqual(win.active_session.pdf_path, "/tmp/test.pdf")
        self.assertEqual(win.current_file_path, "/tmp/test.pdf")

        # Page index
        win.current_page_index = 3
        self.assertEqual(win.active_session.current_page_index, 3)
        self.assertEqual(win.current_page_index, 3)

        # Zoom level
        win.zoom_level = 1.75
        self.assertEqual(win.active_session.zoom_level, 1.75)
        self.assertEqual(win.zoom_level, 1.75)

        # View mode
        win.view_mode = False
        self.assertEqual(win.active_session.view_mode, False)
        self.assertEqual(win.view_mode, False)
        self.assertTrue(win.edit_mode)

        # Modified status
        win.document_modified = True
        self.assertTrue(win.active_session.is_modified)
        self.assertTrue(win.document_modified)

        # Collections
        text_obj = EditableText(20, 20, "Delegated")
        win.editable_texts = [text_obj]
        self.assertEqual(len(win.active_session.editable_texts), 1)
        self.assertEqual(win.editable_texts[0].text, "Delegated")

    def test_window_multi_session_switching_and_isolation(self):
        """Verify switching sessions updates window properties and isolates undo stacks."""
        win = PdfEditorWindow(application=self.app)

        # Create session 1
        doc1 = fitz.open()
        p1 = doc1.new_page(width=200, height=200)
        p1.insert_text((50, 50), "Doc 1 Text")
        s1 = win.create_session(doc=doc1, filepath="/tmp/doc1.pdf")
        s1.current_page_index = 0

        # Create session 2
        doc2 = fitz.open()
        doc2.new_page(width=300, height=300)
        p2 = doc2.new_page(width=300, height=300)
        p2.insert_text((50, 50), "Doc 2 Text")
        s2 = win.create_session(doc=doc2, filepath="/tmp/doc2.pdf")
        s2.current_page_index = 1

        # Add and switch to s1
        win.add_session(s1, switch_to=True)
        self.assertEqual(win.active_session, s1)
        self.assertEqual(win.doc, doc1)
        self.assertEqual(win.current_file_path, "/tmp/doc1.pdf")
        self.assertIn("Doc 1 Text", [t.text for t in win.editable_texts])

        # Add and switch to s2
        win.add_session(s2, switch_to=True)
        self.assertEqual(win.active_session, s2)
        self.assertEqual(win.doc, doc2)
        self.assertEqual(win.current_file_path, "/tmp/doc2.pdf")
        self.assertEqual(win.current_page_index, 1)
        self.assertIn("Doc 2 Text", [t.text for t in win.editable_texts])

        # Lookup helpers
        self.assertEqual(win.get_session_by_id(s1.session_id), s1)
        self.assertEqual(win.get_session_by_id(s2.session_id), s2)
        self.assertEqual(win.get_session_by_path("/tmp/doc1.pdf"), s1)
        self.assertEqual(win.get_session_by_path("/tmp/doc2.pdf"), s2)

        # Remove s2
        win.remove_session(s2)
        self.assertNotIn(s2, win.sessions)
        self.assertIsNone(s2.doc)
        self.assertEqual(win.active_session, s1)

        # Cleanup
        win.remove_session(s1)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_tabs.py
# ============================================================================
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

    def test_open_same_document_force_reload(self):
        """Verify that loading an already open file path with force_reload=True reloads the session."""
        doc = fitz.open()
        doc.new_page()
        s1 = self.win.create_session(doc=doc, filepath="/tmp/unique.pdf")
        self.win.add_session(s1, switch_to=True)
        s1.is_modified = True

        with patch.object(self.win, "_finish_loading"):
            with patch("word_sys_pdf_editor.pdf_handler.load_pdf_document", return_value=(doc, None)):
                self.win.load_document("/tmp/unique.pdf", force_reload=True)
                self.assertFalse(s1.is_modified)
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


# ============================================================================
# SECTION: test_workspace_navigation.py
# ============================================================================
import unittest
import tempfile
import os
import sys

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from word_sys_pdf_editor.models import DocumentSession
from word_sys_pdf_editor.window import PdfEditorWindow


def has_screen_display():
    return Gdk.Display.get_default() is not None


class TestWorkspaceNavigation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.doc_path = os.path.join(self.temp_dir.name, "doc.pdf")
        doc = fitz.open()
        p = doc.new_page(width=595, height=842)
        p.insert_text((50, 50), "Navigation Test")
        doc.save(self.doc_path)
        doc.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    @unittest.skipUnless(has_screen_display(), "Screen display not available (headless build environment)")
    def test_welcome_home_preserves_tab_bar_for_open_workspaces(self):
        app = Adw.Application(application_id="org.wordsys.test.nav")
        app.register(None)

        win = PdfEditorWindow(application=app)
        doc = fitz.open(self.doc_path)
        win._active_session.doc = doc
        win._active_session.pdf_path = self.doc_path
        win.tab_bar.set_visible(True)
        win.stack.set_visible_child_name("editor")

        # Active workspace has an open document
        self.assertGreater(len(win.sessions), 0)
        self.assertIsNotNone(win.sessions[0].doc)
        self.assertTrue(win.tab_bar.get_visible())

        # Go to home / welcome view
        win.go_to_welcome()
        self.assertEqual(win.stack.get_visible_child_name(), "welcome")
        # Tab bar must REMAIN visible and fully active (not autohidden) so the user does NOT lose access to open workspaces!
        self.assertTrue(win.tab_bar.get_visible())
        self.assertFalse(win.tab_bar.get_autohide())

        # Clicking tab bar switches back to editor workspace
        win._on_tab_bar_pressed(None, 1, 10, 10)
        self.assertEqual(win.stack.get_visible_child_name(), "editor")
        self.assertTrue(win.tab_bar.get_visible())

        # Go to home again
        win.go_to_welcome()
        self.assertEqual(win.stack.get_visible_child_name(), "welcome")

        # Clicking home again toggles back to editor
        win.go_to_welcome()
        self.assertEqual(win.stack.get_visible_child_name(), "editor")
        self.assertTrue(win.tab_bar.get_visible())

        win.do_close_request()

    @unittest.skipUnless(has_screen_display(), "Screen display not available (headless build environment)")
    def test_welcome_view_return_to_workspace_button(self):
        from word_sys_pdf_editor.welcome_view import WelcomeView
        from word_sys_pdf_editor.i18n import _
        app = Adw.Application(application_id="org.wordsys.test.btn")
        app.register(None)

        win = PdfEditorWindow(application=app)
        doc = fitz.open(self.doc_path)
        win._active_session.doc = doc
        win._active_session.pdf_path = self.doc_path

        welcome = WelcomeView(parent_window=win)

        def find_buttons(widget):
            buttons = []
            curr = widget.get_first_child()
            while curr:
                if isinstance(curr, Gtk.Button):
                    buttons.append(curr)
                buttons.extend(find_buttons(curr))
                curr = curr.get_next_sibling()
            return buttons

        buttons = find_buttons(welcome)
        btn_labels = [b.get_label() for b in buttons if b.get_label() is not None]
        self.assertIn(_("btn_return_to_workspace"), btn_labels)
        for label in btn_labels:
            self.assertNotIn("doc.pdf", label)
            self.assertNotIn("(", label)
        win.do_close_request()

    @unittest.skipUnless(has_screen_display(), "Screen display not available (headless build environment)")
    def test_merge_dialog_compact_dimensions(self):
        from word_sys_pdf_editor.merge_dialog import MergeDialog
        dialog = MergeDialog(parent_window=None)
        width, height = dialog.get_default_size()
        self.assertEqual(width, 700)
        self.assertEqual(height, 520)
        dialog.cleanup()
        dialog.close()


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_pdf_handler.py
# ============================================================================
import unittest
import tempfile
import os
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor import pdf_handler


class TestPdfHandler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sample_pdf = os.path.join(self.temp_dir.name, "sample.pdf")
        doc = fitz.open()
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((50, 100), "Hello PDF Test", fontsize=14)
        p1.draw_rect(fitz.Rect(50, 150, 200, 250), color=(1, 0, 0), fill=(0.9, 0.9, 0.9))
        p2 = doc.new_page(width=612, height=792)
        p2.insert_text((50, 100), "Second Page Content", fontsize=14)
        doc.save(self.sample_pdf)
        doc.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_page_count(self):
        doc = fitz.open(self.sample_pdf)
        self.assertEqual(pdf_handler.get_page_count(doc), 2)
        doc.close()
        self.assertEqual(pdf_handler.get_page_count(None), 0)

    def test_rotate_point(self):
        # 90 degrees around origin
        nx, ny = pdf_handler.rotate_point(10, 0, 0, 0, 90)
        self.assertAlmostEqual(nx, 0.0, places=4)
        self.assertAlmostEqual(ny, 10.0, places=4)

        # 0 degrees
        nx, ny = pdf_handler.rotate_point(15, 25, 0, 0, 0)
        self.assertEqual(nx, 15)
        self.assertEqual(ny, 25)

    def test_generate_thumbnail_headless(self):
        doc = fitz.open(self.sample_pdf)
        pixbuf = pdf_handler.generate_thumbnail(doc, 0, target_width=120)
        self.assertIsNotNone(pixbuf)
        self.assertEqual(pixbuf.get_width(), 120)
        self.assertGreater(pixbuf.get_height(), 100)
        doc.close()

    def test_extract_text_and_shapes(self):
        doc = fitz.open(self.sample_pdf)
        texts, _ = pdf_handler.extract_editable_text(doc, 0)
        shapes, _ = pdf_handler.extract_editable_shapes(doc, 0)
        self.assertGreaterEqual(len(texts), 1)
        self.assertTrue(any("Hello" in t.text for t in texts))
        self.assertGreaterEqual(len(shapes), 1)
        doc.close()


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_smart_context_popover.py
# ============================================================================
import unittest
from unittest.mock import MagicMock, patch
import os
import fitz

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

from word_sys_pdf_editor.models import (
    EditableText, EditableShape, EditableImage, MeasurementObject, StickyNoteObject
)
from word_sys_pdf_editor.window import PdfEditorWindow


class TestSmartContextPopover(unittest.TestCase):
    """Test suite for smart non-obstructive context menu and popover positioning."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        self.window = MagicMock(spec=PdfEditorWindow)
        self.window.doc = self.doc
        self.window.current_page_index = 0
        self.window.zoom_level = 1.0
        self.window.current_pdf_page_width = 600
        self.window.current_pdf_page_height = 800
        self.window.continuous_scroll = False

        # Bind methods under test from PdfEditorWindow
        self.window.get_page_canvas_rect = PdfEditorWindow.get_page_canvas_rect.__get__(self.window, PdfEditorWindow)
        self.window.get_visible_viewport_rect = PdfEditorWindow.get_visible_viewport_rect.__get__(self.window, PdfEditorWindow)
        self.window.get_object_canvas_rect = PdfEditorWindow.get_object_canvas_rect.__get__(self.window, PdfEditorWindow)
        self.window.calculate_smart_popover_placement = PdfEditorWindow.calculate_smart_popover_placement.__get__(self.window, PdfEditorWindow)

        # Mock drawing area and scroll
        mock_pdf_view = MagicMock()
        mock_pdf_view.get_allocated_width.return_value = 1000
        mock_pdf_view.get_allocated_height.return_value = 1000
        self.window.pdf_view = mock_pdf_view

        mock_pdf_scroll = MagicMock()
        mock_pdf_scroll.get_allocated_width.return_value = 1000
        mock_pdf_scroll.get_allocated_height.return_value = 1000
        mock_h_adj = MagicMock()
        mock_h_adj.get_value.return_value = 0.0
        mock_h_adj.get_page_size.return_value = 1000.0
        mock_v_adj = MagicMock()
        mock_v_adj.get_value.return_value = 0.0
        mock_v_adj.get_page_size.return_value = 1000.0
        mock_pdf_scroll.get_hadjustment.return_value = mock_h_adj
        mock_pdf_scroll.get_vadjustment.return_value = mock_v_adj
        self.window.pdf_scroll = mock_pdf_scroll

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_get_object_canvas_rect_editable_text(self):
        """Verify canvas rect calculation for EditableText centered in viewport."""
        text_obj = EditableText(
            50.0, 100.0,
            text="Hello World",
            page_number=0,
            span_data={"bbox": (50.0, 100.0, 250.0, 130.0)}
        )
        canvas_rect = self.window.get_object_canvas_rect(text_obj)
        self.assertIsNotNone(canvas_rect)
        cx, cy, cw, ch = canvas_rect

        # In 1000x1000 view with 600x800 page, page offsets are (200, 100)
        self.assertEqual(cx, 200 + 50)
        self.assertEqual(cy, 100 + 100)
        self.assertEqual(cw, 200)
        self.assertEqual(ch, 30)

    def test_get_object_canvas_rect_with_zoom(self):
        """Verify canvas rect calculation scales accurately with zoom level."""
        self.window.zoom_level = 1.5
        self.window.current_pdf_page_width = 900
        self.window.current_pdf_page_height = 1200
        # In 1000x1000 view with 900x1200 page: px = (1000-900)/2 = 50, py = max(0, -100) = 0
        text_obj = EditableText(
            40.0, 80.0,
            text="Zoomed Text",
            page_number=0,
            span_data={"bbox": (40.0, 80.0, 140.0, 100.0)}
        )
        cx, cy, cw, ch = self.window.get_object_canvas_rect(text_obj)
        self.assertEqual(cx, int(50 + 40 * 1.5))
        self.assertEqual(cy, int(0 + 80 * 1.5))
        self.assertEqual(cw, int(100 * 1.5))
        self.assertEqual(ch, int(20 * 1.5))

    def test_get_object_canvas_rect_rotated_page(self):
        """Verify canvas rect computation on a 90-degree rotated PDF page."""
        self.page.set_rotation(90)
        text_obj = EditableText(
            50.0, 100.0,
            text="Rotated Page Text",
            page_number=0,
            span_data={"bbox": (50.0, 100.0, 250.0, 130.0)}
        )
        canvas_rect = self.window.get_object_canvas_rect(text_obj)
        self.assertIsNotNone(canvas_rect)
        cx, cy, cw, ch = canvas_rect
        self.assertGreater(cw, 0)
        self.assertGreater(ch, 0)

    def test_get_object_canvas_rect_sticky_note(self):
        """Verify canvas rect calculation for StickyNoteObject."""
        note = StickyNoteObject(
            x=60.0,
            y=120.0,
            width=24.0,
            height=24.0,
            page_number=0
        )
        canvas_rect = self.window.get_object_canvas_rect(note)
        self.assertIsNotNone(canvas_rect)
        cx, cy, cw, ch = canvas_rect
        self.assertEqual(cx, 200 + 60)
        self.assertEqual(cy, 100 + 120)
        self.assertEqual(cw, 24)
        self.assertEqual(ch, 24)

    def test_get_object_canvas_rect_none(self):
        """Verify None is returned when object is None or has invalid bbox."""
        self.assertIsNone(self.window.get_object_canvas_rect(None))
        invalid_obj = object()
        self.assertIsNone(self.window.get_object_canvas_rect(invalid_obj))

    def test_smart_placement_prefers_right(self):
        """Verify popover prefers RIGHT position when ample clearance is available."""
        # Object at (100, 100) with size (150, 40) in a 1000x1000 viewport
        # Space right = 1000 - 250 = 750 (>= 240 + 8) -> PositionType.RIGHT
        anchor = (100, 100, 150, 40)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, estimated_size=(240, 300), margin=8)

        self.assertEqual(pos, Gtk.PositionType.RIGHT)
        # Pointing rect right edge must be anchor_x + anchor_w + margin
        self.assertEqual(rect.x + rect.width, 100 + 150 + 8)
        self.assertEqual(rect.x, 100 - 8)

    def test_smart_placement_flips_left_when_right_blocked(self):
        """Verify popover flips to LEFT when right window edge obstructs."""
        # Object at (800, 100) with size (150, 40) in a 1000x1000 viewport
        # Space right = 1000 - 950 = 50 (< 248)
        # Space left = 800 - 0 = 800 (>= 248) -> PositionType.LEFT
        anchor = (800, 100, 150, 40)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, estimated_size=(240, 300), margin=8)

        self.assertEqual(pos, Gtk.PositionType.LEFT)
        # Pointing rect left edge must be anchor_x - margin
        self.assertEqual(rect.x, 800 - 8)

    def test_smart_placement_flips_bottom_when_sides_blocked(self):
        """Verify popover places BOTTOM when wide element spans horizontal viewport."""
        # Wide title bar spanning from x=40 to x=960 (width 920) in 1000x1000 viewport
        # Space right = 1000 - 960 = 40 (< 248)
        # Space left = 40 - 0 = 40 (< 248)
        # Space bottom = 1000 - 140 = 860 (>= 308) -> PositionType.BOTTOM
        anchor = (40, 100, 920, 40)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, estimated_size=(240, 300), margin=8)

        self.assertEqual(pos, Gtk.PositionType.BOTTOM)
        # Pointing rect bottom edge must be anchor_y + anchor_h + margin
        self.assertEqual(rect.y + rect.height, 100 + 40 + 8)

    def test_smart_placement_flips_top_when_bottom_blocked(self):
        """Verify popover places TOP when wide element is near bottom of viewport."""
        # Wide title bar at y=850 in 1000x1000 viewport
        # Space right = 40, Space left = 40, Space bottom = 1000 - 890 = 110 (< 308)
        # Space top = 850 - 0 = 850 (>= 308) -> PositionType.TOP
        anchor = (40, 850, 920, 40)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, estimated_size=(240, 300), margin=8)

        self.assertEqual(pos, Gtk.PositionType.TOP)
        self.assertEqual(rect.y, 850 - 8)

    def test_smart_placement_tall_object_slice_around_click(self):
        """Verify tall object pointing rect is vertically restricted near click position."""
        # Tall multi-line text box: height 400px (100 to 500)
        # Clicked near line at y = 250
        anchor = (100, 100, 200, 400)
        click_pos = (180.0, 250.0)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, click_pos=click_pos)

        self.assertEqual(pos, Gtk.PositionType.RIGHT)
        # Vertical range must be centered around 250 (+/- 20)
        self.assertEqual(rect.y, 230)
        self.assertEqual(rect.height, 40)
        # Horizontal span must encompass full width + margin
        self.assertEqual(rect.x, 100 - 8)
        self.assertEqual(rect.x + rect.width, 100 + 200 + 8)

    def test_smart_placement_empty_space_click(self):
        """Verify empty space click produces 1x1 pointing rect at cursor coordinates."""
        rect, pos = self.window.calculate_smart_popover_placement(None, click_pos=(350.0, 450.0))
        self.assertEqual(rect.x, 350)
        self.assertEqual(rect.y, 450)
        self.assertEqual(rect.width, 1)
        self.assertEqual(rect.height, 1)

    def test_continuous_scroll_offset_integration(self):
        """Verify smart placement on subsequent pages in continuous scroll layout."""
        self.doc.new_page(width=600, height=800)
        self.window.continuous_scroll = True
        self.window.continuous_page_offsets = [
            (0.0, 0.0, 600.0, 800.0),
            (0.0, 824.0, 600.0, 800.0),
        ]
        # Scrolled down to page 1
        h_adj = self.window.pdf_scroll.get_hadjustment()
        v_adj = self.window.pdf_scroll.get_vadjustment()
        v_adj.get_value.return_value = 800.0
        v_adj.get_page_size.return_value = 600.0

        text_page_1 = EditableText(
            50.0, 50.0,
            text="Page 1 Text",
            page_number=1,
            span_data={"bbox": (50.0, 50.0, 200.0, 80.0)}
        )
        canvas_rect = self.window.get_object_canvas_rect(text_page_1)
        self.assertIsNotNone(canvas_rect)
        cx, cy, cw, ch = canvas_rect
        # py = 824.0, cy = 824 + 50 = 874
        self.assertEqual(cy, 874)

        rect, pos = self.window.calculate_smart_popover_placement(canvas_rect)
        self.assertEqual(pos, Gtk.PositionType.RIGHT)
        self.assertEqual(rect.x + rect.width, cx + cw + 8)

    def test_get_object_canvas_rect_shape_and_image(self):
        """Verify canvas rect calculation for EditableShape and EditableImage."""
        shape = EditableShape(
            shape_type="rectangle",
            bbox=(30.0, 40.0, 180.0, 120.0),
            page_number=0
        )
        shape_rect = self.window.get_object_canvas_rect(shape)
        self.assertIsNotNone(shape_rect)
        self.assertEqual(shape_rect[2], 150)
        self.assertEqual(shape_rect[3], 80)

        image = EditableImage(
            bbox=(100.0, 150.0, 300.0, 350.0),
            page_number=0,
            xref=1,
            image_bytes=b""
        )
        img_rect = self.window.get_object_canvas_rect(image)
        self.assertIsNotNone(img_rect)
        self.assertEqual(img_rect[2], 200)
        self.assertEqual(img_rect[3], 200)

    def test_get_object_canvas_rect_measurement(self):
        """Verify canvas rect calculation for MeasurementObject."""
        meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_DISTANCE,
            points=[(20.0, 30.0), (120.0, 80.0)],
            page_number=0
        )
        meas_rect = self.window.get_object_canvas_rect(meas)
        self.assertIsNotNone(meas_rect)
        self.assertGreater(meas_rect[2], 0)
        self.assertGreater(meas_rect[3], 0)

    def test_zero_collision_popover_body_with_text(self):
        """Mathematically verify that popover body never intersects text object bounding box."""
        # Text object box: [cx, cy, cw, ch] = [200, 300, 300, 40]
        anchor = (200, 300, 300, 40)
        est_w, est_h = 240, 280
        margin = 10

        # 1. Right placement
        rect_r, pos_r = self.window.calculate_smart_popover_placement(anchor, estimated_size=(est_w, est_h), margin=margin)
        self.assertEqual(pos_r, Gtk.PositionType.RIGHT)
        # Popover body starts at rect_r.x + rect_r.width:
        popover_body_left = rect_r.x + rect_r.width
        text_right = anchor[0] + anchor[2]
        self.assertGreater(popover_body_left, text_right)
        self.assertGreaterEqual(popover_body_left - text_right, margin)

        # 2. Left placement (near right edge)
        anchor_left = (750, 300, 200, 40)
        rect_l, pos_l = self.window.calculate_smart_popover_placement(anchor_left, estimated_size=(est_w, est_h), margin=margin)
        self.assertEqual(pos_l, Gtk.PositionType.LEFT)
        popover_body_right = rect_l.x
        text_left = anchor_left[0]
        self.assertLess(popover_body_right, text_left)
        self.assertGreaterEqual(text_left - popover_body_right, margin)

        # 3. Bottom placement (wide bar)
        anchor_wide = (50, 200, 900, 40)
        rect_b, pos_b = self.window.calculate_smart_popover_placement(anchor_wide, estimated_size=(est_w, est_h), margin=margin)
        self.assertEqual(pos_b, Gtk.PositionType.BOTTOM)
        popover_body_top = rect_b.y + rect_b.height
        text_bottom = anchor_wide[1] + anchor_wide[3]
        self.assertGreater(popover_body_top, text_bottom)
        self.assertGreaterEqual(popover_body_top - text_bottom, margin)

        # 4. Top placement (wide bar near bottom)
        anchor_bot = (50, 850, 900, 40)
        rect_t, pos_t = self.window.calculate_smart_popover_placement(anchor_bot, estimated_size=(est_w, est_h), margin=margin)
        self.assertEqual(pos_t, Gtk.PositionType.TOP)
        popover_body_bottom = rect_t.y
        text_top = anchor_bot[1]
        self.assertLess(popover_body_bottom, text_top)
        self.assertGreaterEqual(text_top - popover_body_bottom, margin)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_hyperlink_engine.py
# ============================================================================
import os
import io
import unittest
from unittest.mock import MagicMock

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor.models import EditableText
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.undo_manager import EditObjectCommand, UndoManager


class MockWindow:
    def __init__(self, doc, editable_texts=None):
        self.doc = doc
        self.current_page_index = 0
        self.editable_texts = editable_texts if editable_texts is not None else []
        self.editable_shapes = []
        self.editable_images = []
        self.editable_strokes = []
        self.document_modified = False
        self.selected_text = self.editable_texts[0] if self.editable_texts else None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.status_label = MagicMock()
        self.pdf_view = self
        self.undo_manager = UndoManager(self)

    def _update_undo_redo_buttons(self): pass
    def _update_text_format_controls(self, obj): pass
    def _update_ui_state(self): pass
    def _refresh_thumbnail(self, p): pass
    def queue_draw(self): pass


class TestHyperlinkEngine(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=500, height=500)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_editable_text_link_properties(self):
        """Test EditableText link_url, is_link, and get_link_url properties."""
        # Unlinked plain text
        t1 = EditableText(50, 50, "Plain Text")
        self.assertFalse(t1.is_link)
        self.assertIsNone(t1.get_link_url())

        # Explicit link_url on arbitrary text
        t2 = EditableText(50, 70, "Click Here", link_url="https://example.com")
        self.assertTrue(t2.is_link)
        self.assertEqual(t2.get_link_url(), "https://example.com")

        # Text containing explicit URL
        t3 = EditableText(50, 90, "Visit https://google.com for search")
        self.assertTrue(t3.is_link)
        self.assertEqual(t3.get_link_url(), "https://google.com")

        # Explicit link_url takes precedence over regex in text
        t4 = EditableText(50, 110, "Visit https://google.com", link_url="https://bing.com")
        self.assertTrue(t4.is_link)
        self.assertEqual(t4.get_link_url(), "https://bing.com")

    def test_extract_editable_texts_attaches_pdf_link_annotations(self):
        """extract_editable_texts must attach existing LINK_URI annotations from page to EditableText."""
        # Insert text and matching LINK_URI annotation
        text_rect = fitz.Rect(100, 100, 250, 120)
        self.page.insert_text(fitz.Point(100, 115), "Open Portal")
        link_dict = {"kind": fitz.LINK_URI, "from": text_rect, "uri": "https://portal.example.org"}
        self.page.insert_link(link_dict)

        # Save and reload document so PyMuPDF builds link xrefs
        doc_bytes = self.doc.tobytes()
        reloaded_doc = fitz.open(stream=doc_bytes, filetype="pdf")
        
        texts, err = pdf_handler.extract_editable_text(reloaded_doc, 0)
        self.assertIsNone(err)
        self.assertTrue(len(texts) >= 1)
        
        portal_text = None
        for t in texts:
            if "Open Portal" in t.text:
                portal_text = t
                break
                
        self.assertIsNotNone(portal_text, "Failed to find 'Open Portal' in extracted texts")
        self.assertTrue(portal_text.is_link)
        self.assertEqual(portal_text.link_url, "https://portal.example.org")
        reloaded_doc.close()

    def test_apply_single_object_embeds_link_annotation_for_link_url(self):
        """_apply_single_object_to_page must embed LINK_URI over bounding box when link_url is set."""
        text_obj = EditableText(
            x=100, y=200,
            text="Documentation Link",
            font_size=12,
            is_new=True,
            link_url="https://docs.python.org",
            page_number=0
        )
        text_obj.bbox = (100.0, 190.0, 220.0, 210.0)

        success, err = pdf_handler._apply_single_object_to_page(self.doc, self.page, text_obj)
        self.assertTrue(success)
        self.assertIsNone(err)

        # Save and verify link annotation exists on page
        b = self.doc.tobytes()
        check_doc = fitz.open(stream=b, filetype="pdf")
        p = check_doc[0]
        links = p.get_links()
        
        matching_links = [l for l in links if l.get("uri") == "https://docs.python.org"]
        self.assertEqual(len(matching_links), 1)
        self.assertEqual(matching_links[0]["kind"], fitz.LINK_URI)
        check_doc.close()

    def test_apply_and_remove_text_link_with_undo(self):
        """Applying link sets blue color and underline; undo restores original properties."""
        text_obj = EditableText(
            x=50, y=100,
            text="Sample Link Target",
            font_size=11,
            color=(0.0, 0.0, 0.0),
            is_new=False,
            page_number=0
        )
        text_obj.bbox = (50.0, 90.0, 160.0, 105.0)
        self.page.insert_text(fitz.Point(50, 102), "Sample Link Target")
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)

        win = MockWindow(self.doc, [text_obj])

        # 1. Apply Link
        old_props = {
            'link_url': None,
            'color': (0.0, 0.0, 0.0),
            'is_underline': False,
            'bbox': text_obj.bbox
        }
        new_props = {
            'link_url': "https://custom-target.com",
            'color': (0.0, 0.0, 238.0 / 255.0),
            'is_underline': True,
            'bbox': text_obj.bbox
        }
        cmd = EditObjectCommand(win, text_obj, old_props, new_props)
        cmd.execute()
        win.undo_manager.add_command(cmd)

        self.assertEqual(text_obj.link_url, "https://custom-target.com")
        self.assertTrue(text_obj.is_link)
        self.assertTrue(text_obj.is_underline)
        self.assertAlmostEqual(text_obj.color[2], 238.0 / 255.0, places=2)

        # 2. Undo
        win.undo_manager.undo()
        self.assertIsNone(text_obj.link_url)
        self.assertFalse(text_obj.is_link)
        self.assertFalse(text_obj.is_underline)
        self.assertEqual(text_obj.color, (0.0, 0.0, 0.0))

        # 3. Redo
        win.undo_manager.redo()
        self.assertEqual(text_obj.link_url, "https://custom-target.com")
        self.assertTrue(text_obj.is_link)
        self.assertTrue(text_obj.is_underline)

    def test_ghost_erasure_cleans_up_old_link_annotations(self):
        """_perform_ghost_erasure must delete old link annotations when redacting text."""
        # Insert a link on the page
        rect = fitz.Rect(50, 50, 150, 70)
        self.page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": "https://old-link.com"})
        
        b = self.doc.tobytes()
        test_doc = fitz.open(stream=b, filetype="pdf")
        p = test_doc[0]
        self.assertEqual(len(p.get_links()), 1)

        t_obj = EditableText(50, 65, "Link Text", page_number=0)
        t_obj.bbox = (50.0, 50.0, 150.0, 70.0)

        # Execute EditObjectCommand to update text and link
        win = MockWindow(test_doc, [t_obj])
        old_props = {'link_url': "https://old-link.com", 'bbox': t_obj.bbox}
        new_props = {'link_url': "https://new-link.com", 'bbox': t_obj.bbox}
        cmd = EditObjectCommand(win, t_obj, old_props, new_props)
        cmd.execute()

        # Check links on page
        b2 = test_doc.tobytes()
        doc_check = fitz.open(stream=b2, filetype="pdf")
        active_links = doc_check[0].get_links()
        uris = [l.get("uri") for l in active_links]
        self.assertIn("https://new-link.com", uris)
        self.assertNotIn("https://old-link.com", uris)
        test_doc.close()
        doc_check.close()

    def test_window_get_link_url_at_pos(self):
        """_get_link_url_at_pos must detect URLs from both EditableText and raw PDF annotations."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        
        t_linked = EditableText(100, 100, "Visit site", page_number=0, link_url="https://site.org")
        t_linked.bbox = (100.0, 90.0, 180.0, 110.0)
        
        win = MockWindow(self.doc, [t_linked])
        # Bind the actual method from PdfEditorWindow
        win._get_link_url_at_pos = PdfEditorWindow._get_link_url_at_pos.__get__(win)
        
        # 1. Point inside EditableText
        self.assertEqual(win._get_link_url_at_pos(120.0, 100.0), "https://site.org")
        
        # 2. Point outside
        self.assertIsNone(win._get_link_url_at_pos(300.0, 300.0))
        
        # 3. Raw PDF link annotation on page (reloaded)
        self.page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(300, 300, 400, 320), "uri": "https://raw-pdf-link.com"})
        reloaded = fitz.open(stream=self.doc.tobytes(), filetype="pdf")
        win.doc = reloaded
        self.assertEqual(win._get_link_url_at_pos(350.0, 310.0), "https://raw-pdf-link.com")
        reloaded.close()

    def test_window_apply_and_remove_text_link_methods(self):
        """PdfEditorWindow._apply_text_link and _remove_text_link methods update properties correctly."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        
        t_obj = EditableText(50, 50, "Custom Text", page_number=0, color=(0.1, 0.1, 0.1))
        t_obj.bbox = (50.0, 40.0, 150.0, 60.0)
        self.page.insert_text(fitz.Point(50, 55), "Custom Text")
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)
        
        win = MockWindow(self.doc, [t_obj])
        win._apply_text_link = PdfEditorWindow._apply_text_link.__get__(win)
        win._remove_text_link = PdfEditorWindow._remove_text_link.__get__(win)
        
        # Apply link without scheme prefix -> should auto-prepend https://
        win._apply_text_link(t_obj, "example.org/docs")
        self.assertEqual(t_obj.link_url, "https://example.org/docs")
        self.assertTrue(t_obj.is_link)
        self.assertTrue(t_obj.is_underline)
        self.assertAlmostEqual(t_obj.color[2], 238.0 / 255.0, places=2)
        
        # Remove link
        win._remove_text_link(t_obj)
        self.assertIsNone(t_obj.link_url)
        self.assertFalse(t_obj.is_link)
        self.assertFalse(t_obj.is_underline)
        self.assertEqual(t_obj.color, (0.1, 0.1, 0.1))


