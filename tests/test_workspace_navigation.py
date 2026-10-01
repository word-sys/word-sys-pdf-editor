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
        # Tab bar must REMAIN visible so the user does NOT lose access to open workspaces!
        self.assertTrue(win.tab_bar.get_visible())

        # Clicking home again toggles back to editor
        win.go_to_welcome()
        self.assertEqual(win.stack.get_visible_child_name(), "editor")
        self.assertTrue(win.tab_bar.get_visible())

        win.do_close_request()

    @unittest.skipUnless(has_screen_display(), "Screen display not available (headless build environment)")
    def test_merge_dialog_compact_dimensions(self):
        from word_sys_pdf_editor.merge_dialog import MergeDialog
        dialog = MergeDialog(parent_window=None)
        width, height = dialog.get_default_size()
        # Ensure default size is compact and not bloated to 1080x720
        self.assertLessEqual(width, 860)
        self.assertLessEqual(height, 580)
        dialog.cleanup()
        dialog.close()


if __name__ == '__main__':
    unittest.main()
