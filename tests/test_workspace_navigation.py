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
