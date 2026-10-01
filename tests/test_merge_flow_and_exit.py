import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw, GLib, Gio

sys.path.insert(0, '/home/word-sys/word-sys-pdf-editor')
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.merge_dialog import MergeDialog


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestMergeFlowAndExit(unittest.TestCase):
    def test_e2e_merge_and_clean_exit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_a = os.path.join(tmp_dir, "doc_a.pdf")
            doc_a = fitz.open()
            p1 = doc_a.new_page(width=595, height=842)
            p1.draw_rect(fitz.Rect(50, 50, 200, 200), color=(1, 0, 0))
            p2 = doc_a.new_page(width=595, height=842)
            p2.draw_rect(fitz.Rect(50, 50, 200, 200), color=(0, 1, 0))
            doc_a.save(pdf_a)
            doc_a.close()

            pdf_b = os.path.join(tmp_dir, "doc_b.pdf")
            doc_b = fitz.open()
            p3 = doc_b.new_page(width=400, height=600)
            p3.draw_rect(fitz.Rect(30, 30, 150, 150), color=(0, 0, 1))
            doc_b.save(pdf_b)
            doc_b.close()

            pdf_c = os.path.join(tmp_dir, "doc_c.pdf")
            doc_c = fitz.open()
            p4 = doc_c.new_page(width=500, height=500)
            p4.draw_rect(fitz.Rect(10, 10, 80, 80), color=(1, 1, 0))
            doc_c.save(pdf_c)
            doc_c.close()

            app = Adw.Application(application_id="org.wordsys.test.e2e_merge")

            def on_activate(application):
                win = PdfEditorWindow(application=application)
                win.load_document(pdf_a)
                win.present()

                win.on_merge_documents()
                dialog = win._merge_dialog
                self.assertIsNotNone(dialog)
                self.assertEqual(dialog.panel_a.page_count, 2)
                self.assertFalse(dialog.panel_a.empty_box.get_visible())
                self.assertTrue(dialog.panel_a.scroll.get_visible())

                ok = dialog.panel_b.load_file(pdf_b)
                self.assertTrue(ok)
                self.assertEqual(dialog.panel_b.page_count, 1)
                self.assertFalse(dialog.panel_b.empty_box.get_visible())
                self.assertTrue(dialog.panel_b.scroll.get_visible())

                dialog.panel_a.page_cards[0]._add_to_target()
                dialog.panel_b.page_cards[0]._add_to_target()
                self.assertEqual(len(dialog.target_panel.pages), 2)

                dialog.panel_b.clear()
                self.assertEqual(dialog.panel_b.page_count, 0)
                self.assertTrue(dialog.panel_b.empty_box.get_visible())
                self.assertFalse(dialog.panel_b.scroll.get_visible())
                self.assertEqual(len(dialog.target_panel.pages), 2)
                self.assertFalse(dialog.target_panel.pages[1]["source_doc"].is_closed)

                ok_c = dialog.panel_b.load_file(pdf_c)
                self.assertTrue(ok_c)
                self.assertEqual(dialog.panel_b.page_count, 1)
                self.assertFalse(dialog.panel_b.empty_box.get_visible())
                self.assertTrue(dialog.panel_b.scroll.get_visible())
                self.assertEqual(len(dialog.panel_b.page_cards), 1)

                win.close()

            app.connect("activate", on_activate)
            start_time = time.time()
            GLib.timeout_add(5000, lambda: app.quit())
            app.run([])
            elapsed = time.time() - start_time
            self.assertLess(elapsed, 4.5)


if __name__ == "__main__":
    unittest.main()
