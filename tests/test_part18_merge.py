import unittest
import os
import sys
import tempfile
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
from word_sys_pdf_editor.merge_dialog import (
    MergeDialog, SourceDocumentPanel, TargetDocumentPanel,
    SourcePageCard, TargetPageCard
)
from word_sys_pdf_editor.i18n import _STRINGS
from word_sys_pdf_editor.window import PdfEditorWindow


def drain_events(cycles=10):
    ctx = GLib.MainContext.default()
    for _ in range(cycles):
        while ctx.pending():
            ctx.iteration(False)


class TestPart18MergeLocalization(unittest.TestCase):
    def test_merge_localization_keys_across_all_7_languages(self):
        keys = [
            "menu_merge_documents", "merge_workspace_title", "merge_workspace_subtitle",
            "merge_source_a", "merge_source_b", "merge_target_doc",
            "merge_empty_source_title", "merge_empty_source_desc",
            "merge_empty_target_title", "merge_empty_target_desc",
            "merge_btn_choose_pdf", "merge_btn_save", "merge_add_all_tip",
            "merge_clear_tip", "merge_clear_target_tip", "merge_add_page",
            "merge_move_up_tip", "merge_move_down_tip", "merge_remove_page_tip",
            "merge_page_count"
        ]
        for lang_code in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            self.assertIn(lang_code, _STRINGS)
            lang_dict = _STRINGS[lang_code]
            for k in keys:
                self.assertIn(k, lang_dict)
                self.assertTrue(lang_dict[k], f"Key '{k}' empty in {lang_code}")


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestPart18MergeWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.wordsys.test.part18")
        cls.app.register(None)

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.pdf_a_path = os.path.join(cls.temp_dir.name, "doc_a.pdf")
        cls.pdf_b_path = os.path.join(cls.temp_dir.name, "doc_b.pdf")

        doc_a = fitz.open()
        for i in range(3):
            p = doc_a.new_page(width=595, height=842)
            p.draw_rect(fitz.Rect(50, 50, 200, 200), color=(1, 0, 0), fill=(1, 0.9, 0.9))
        doc_a.save(cls.pdf_a_path)
        doc_a.close()

        doc_b = fitz.open()
        for i in range(2):
            p = doc_b.new_page(width=400, height=600)
            p.draw_rect(fitz.Rect(20, 20, 100, 100), color=(0, 0, 1), fill=(0.9, 0.9, 1))
        doc_b.save(cls.pdf_b_path)
        doc_b.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_merge_dialog_initial_structure(self):
        dialog = MergeDialog(parent_window=None)
        self.assertIsNotNone(dialog.panel_a)
        self.assertIsNotNone(dialog.panel_b)
        self.assertIsNotNone(dialog.target_panel)
        self.assertIsNotNone(dialog.save_btn)
        self.assertFalse(dialog.save_btn.get_sensitive())
        self.assertTrue(dialog.panel_a.empty_box.get_visible())
        self.assertFalse(dialog.panel_a.scroll.get_visible())
        self.assertTrue(dialog.panel_b.empty_box.get_visible())
        self.assertFalse(dialog.panel_b.scroll.get_visible())
        self.assertTrue(dialog.target_panel.empty_box.get_visible())
        self.assertFalse(dialog.target_panel.scroll.get_visible())
        dialog.cleanup()
        dialog.close()
        drain_events()

    def test_source_panel_loading_and_clearing(self):
        dialog = MergeDialog(parent_window=None)
        panel_a = dialog.panel_a

        loaded = panel_a.load_file(self.pdf_a_path)
        self.assertTrue(loaded)
        self.assertEqual(panel_a.page_count, 3)
        self.assertIsNotNone(panel_a.doc)
        self.assertFalse(panel_a.empty_box.get_visible())
        self.assertTrue(panel_a.scroll.get_visible())
        self.assertEqual(len(panel_a.page_cards), 3)
        self.assertTrue(panel_a.add_all_btn.get_sensitive())
        self.assertTrue(panel_a.clear_btn.get_sensitive())
        self.assertIn("doc_a.pdf", panel_a.file_lbl.get_text())

        drain_events(30)

        panel_a.clear()
        self.assertIsNone(panel_a.doc)
        self.assertIsNone(panel_a.file_path)
        self.assertEqual(panel_a.page_count, 0)
        self.assertEqual(len(panel_a.page_cards), 0)
        self.assertTrue(panel_a.empty_box.get_visible())
        self.assertFalse(panel_a.scroll.get_visible())
        self.assertFalse(panel_a.add_all_btn.get_sensitive())
        self.assertFalse(panel_a.clear_btn.get_sensitive())
        dialog.cleanup()
        dialog.close()
        drain_events()

    def test_source_panel_drop_file(self):
        dialog = MergeDialog(parent_window=None)
        gfile = Gio.File.new_for_path(self.pdf_b_path)
        handled = dialog.panel_b._on_file_dropped(None, gfile, 0, 0)
        self.assertTrue(handled)
        self.assertEqual(dialog.panel_b.page_count, 2)
        self.assertFalse(dialog.panel_b.empty_box.get_visible())
        self.assertTrue(dialog.panel_b.scroll.get_visible())
        dialog.cleanup()
        dialog.close()
        drain_events()

    def test_target_panel_add_page_and_save_button_sensitivity(self):
        dialog = MergeDialog(parent_window=None)
        dialog.panel_a.load_file(self.pdf_a_path)
        drain_events(20)

        self.assertFalse(dialog.save_btn.get_sensitive())
        dialog.panel_a.page_cards[0]._add_to_target()

        self.assertEqual(len(dialog.target_panel.pages), 1)
        self.assertEqual(len(dialog.target_panel.page_cards), 1)
        self.assertFalse(dialog.target_panel.empty_box.get_visible())
        self.assertTrue(dialog.target_panel.scroll.get_visible())
        self.assertTrue(dialog.target_panel.clear_btn.get_sensitive())
        self.assertTrue(dialog.save_btn.get_sensitive())

        dialog.panel_a.page_cards[1]._add_to_target()
        self.assertEqual(len(dialog.target_panel.pages), 2)

        dialog.panel_b.load_file(self.pdf_b_path)
        drain_events(20)

        dialog.panel_b.page_cards[0]._add_to_target()
        self.assertEqual(len(dialog.target_panel.pages), 3)

        self.assertEqual(dialog.target_panel.pages[0]["source_role"], "source_a")
        self.assertEqual(dialog.target_panel.pages[2]["source_role"], "source_b")

        dialog.cleanup()
        dialog.close()
        drain_events()

    def test_target_panel_reorder_and_remove(self):
        dialog = MergeDialog(parent_window=None)
        dialog.panel_a.load_file(self.pdf_a_path)
        dialog.panel_a.on_add_all_clicked(None)

        self.assertEqual(len(dialog.target_panel.pages), 3)

        dialog.target_panel.move_page(0, 1)
        self.assertEqual(len(dialog.target_panel.pages), 3)
        self.assertEqual(dialog.target_panel.pages[1]["page_index"], 0)

        dialog.target_panel.remove_page(0)
        self.assertEqual(len(dialog.target_panel.pages), 2)

        dialog.target_panel.clear()
        self.assertEqual(len(dialog.target_panel.pages), 0)
        self.assertTrue(dialog.target_panel.empty_box.get_visible())
        self.assertFalse(dialog.target_panel.scroll.get_visible())
        self.assertFalse(dialog.target_panel.clear_btn.get_sensitive())
        self.assertFalse(dialog.save_btn.get_sensitive())

        dialog.cleanup()
        dialog.close()
        drain_events()

    def test_panel_b_clear_and_reopen_cleanly(self):
        dialog = MergeDialog(parent_window=None)
        dialog.panel_a.load_file(self.pdf_a_path)
        dialog.panel_b.load_file(self.pdf_b_path)
        drain_events(20)

        dialog.panel_b.page_cards[0]._add_to_target()
        self.assertEqual(len(dialog.target_panel.pages), 1)

        # Clear panel B
        dialog.panel_b.clear()
        self.assertEqual(dialog.panel_b.page_count, 0)
        self.assertTrue(dialog.panel_b.empty_box.get_visible())
        self.assertFalse(dialog.panel_b.scroll.get_visible())

        # Target doc page must still be intact and valid
        target_page = dialog.target_panel.pages[0]
        self.assertEqual(target_page["page_index"], 0)
        self.assertFalse(target_page["source_doc"].is_closed)

        # Reopen another PDF in panel B
        dialog.panel_b.load_file(self.pdf_a_path)
        drain_events(20)
        self.assertEqual(dialog.panel_b.page_count, 3)
        self.assertFalse(dialog.panel_b.empty_box.get_visible())
        self.assertTrue(dialog.panel_b.scroll.get_visible())
        self.assertEqual(len(dialog.panel_b.page_cards), 3)

        dialog.cleanup()
        dialog.close()
        drain_events()

    def test_prepopulation_from_parent_window(self):
        win = PdfEditorWindow(application=self.app)
        win.current_file_path = self.pdf_a_path

        dialog = MergeDialog(parent_window=win)
        self.assertEqual(dialog.panel_a.page_count, 3)
        self.assertFalse(dialog.panel_a.empty_box.get_visible())
        self.assertTrue(dialog.panel_a.scroll.get_visible())
        self.assertEqual(dialog.panel_a.file_path, self.pdf_a_path)

        dialog.cleanup()
        dialog.close()
        win.do_close_request()
        drain_events()

    def test_merge_dialog_shutdown_with_main_window(self):
        win = PdfEditorWindow(application=self.app)
        win.on_merge_documents()
        self.assertIsNotNone(win._merge_dialog)

        # Closing main window must cleanly close and clean up merge dialog
        close_cancelled = win.do_close_request()
        self.assertFalse(close_cancelled)
        self.assertIsNone(win._merge_dialog)
        drain_events()


if __name__ == '__main__':
    unittest.main()
