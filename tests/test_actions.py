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
