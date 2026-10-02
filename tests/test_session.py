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
