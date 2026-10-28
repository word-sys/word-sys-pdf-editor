"""Consolidated Merge, Export, and Format Conversion Test Suite for word-sys-pdf-editor.

This suite merges PDF merging logic, merge preview rendering, transfer commands,
multi-format AnyConvert exports (DOCX, PPTX, XLSX, HTML, TXT, EPUB), and
export workflow tests.
"""

# ============================================================================
# SECTION: test_merge.py
# ============================================================================
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
        count = 0
        while ctx.pending() and count < 100:
            ctx.iteration(False)
            count += 1


class TestMergeLocalization(unittest.TestCase):
    def test_merge_localization_keys_across_all_7_languages(self):
        keys = [
            "menu_merge_documents", "merge_workspace_title", "merge_workspace_subtitle",
            "merge_source_a", "merge_source_b", "merge_target_doc",
            "merge_empty_source_title", "merge_empty_source_desc",
            "merge_empty_target_title", "merge_empty_target_desc",
            "merge_btn_choose_pdf", "merge_btn_save", "merge_add_all_tip",
            "merge_move_up_tip", "merge_move_down_tip", "merge_remove_page_tip",
            "merge_page_count", "merge_zoom_in", "merge_zoom_out", "merge_zoom_fit",
            "merge_insert_at_end", "merge_insert_after", "merge_insert_marker",
            "merge_inspector_title", "merge_inspector_no_selection",
            "merge_inspector_source", "merge_inspector_page", "merge_inspector_size",
            "merge_inspector_portrait", "merge_inspector_landscape"
        ]
        for lang_code in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            self.assertIn(lang_code, _STRINGS)
            lang_dict = _STRINGS[lang_code]
            for k in keys:
                self.assertIn(k, lang_dict)
                self.assertTrue(lang_dict[k], f"Key '{k}' empty in {lang_code}")


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestMergeWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.wordsys.test.merge")
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


# ============================================================================
# SECTION: test_merge_logic.py
# ============================================================================
import unittest
import tempfile
import os
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz


class TestMergeLogic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.doc_a_path = os.path.join(self.temp_dir.name, "doc_a.pdf")
        self.doc_b_path = os.path.join(self.temp_dir.name, "doc_b.pdf")
        self.merged_path = os.path.join(self.temp_dir.name, "merged.pdf")

        # Create doc A with 3 pages
        doc_a = fitz.open()
        for i in range(3):
            p = doc_a.new_page(width=595, height=842)
            p.insert_text((50, 100), f"Doc A Page {i + 1}", fontsize=16)
        doc_a.save(self.doc_a_path)
        doc_a.close()

        # Create doc B with 2 pages
        doc_b = fitz.open()
        for i in range(2):
            p = doc_b.new_page(width=612, height=792)
            p.insert_text((50, 100), f"Doc B Page {i + 1}", fontsize=16)
        doc_b.save(self.doc_b_path)
        doc_b.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cross_document_merge_and_order(self):
        doc_a = fitz.open(self.doc_a_path)
        doc_b = fitz.open(self.doc_b_path)

        # Plan merge order: Doc A page 2, Doc B page 1, Doc A page 0
        merge_plan = [
            (doc_a, 2),
            (doc_b, 1),
            (doc_a, 0),
        ]

        out_doc = fitz.open()
        for src_doc, page_idx in merge_plan:
            out_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)

        self.assertEqual(out_doc.page_count, 3)
        p0_text = out_doc.load_page(0).get_text()
        self.assertIn("Doc A Page 3", p0_text)

        p1_text = out_doc.load_page(1).get_text()
        self.assertIn("Doc B Page 2", p1_text)

        p2_text = out_doc.load_page(2).get_text()
        self.assertIn("Doc A Page 1", p2_text)

        out_doc.save(self.merged_path)
        out_doc.close()
        doc_a.close()
        doc_b.close()

        # Verify saved document on disk
        saved = fitz.open(self.merged_path)
        self.assertEqual(saved.page_count, 3)
        saved.close()

    def test_source_independence_on_source_closure(self):
        doc_a = fitz.open(self.doc_a_path)
        doc_b = fitz.open(self.doc_b_path)

        # Add page from Doc B
        out_doc = fitz.open()
        out_doc.insert_pdf(doc_b, from_page=0, to_page=0)

        # Close Doc B immediately
        doc_b.close()
        self.assertTrue(doc_b.is_closed)

        # out_doc must remain fully valid and allow subsequent operations
        out_doc.insert_pdf(doc_a, from_page=1, to_page=1)
        self.assertEqual(out_doc.page_count, 2)

        out_doc.save(self.merged_path)
        out_doc.close()
        doc_a.close()

        saved = fitz.open(self.merged_path)
        self.assertEqual(saved.page_count, 2)
        saved.close()


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_merge_flow_and_exit.py
# ============================================================================
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

                if getattr(win, '_merge_dialog', None):
                    win._merge_dialog.cleanup()
                    win._merge_dialog.close()
                    win._merge_dialog = None
                win.close()
                application.quit()

            app.connect("activate", on_activate)
            start_time = time.time()
            GLib.timeout_add(3000, lambda: app.quit())
            app.run([])
            elapsed = time.time() - start_time
            self.assertLess(elapsed, 2.5)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_merge_preview.py
# ============================================================================
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
    SourcePageCard, TargetPageCard, InsertionMarker, ZOOM_LEVELS,
    PagePreviewDialog, MergedPreviewDialog
)
from word_sys_pdf_editor.i18n import _STRINGS, _


def drain_events(cycles=10):
    ctx = GLib.MainContext.default()
    for _ in range(cycles):
        count = 0
        while ctx.pending() and count < 100:
            ctx.iteration(False)
            count += 1


class TestMergePreviewLocalization(unittest.TestCase):
    def test_keys_exist_in_all_languages(self):
        keys = [
            "merge_zoom_in", "merge_zoom_out", "merge_zoom_fit",
            "merge_insert_at_end", "merge_insert_after", "merge_insert_marker",
            "merge_inspector_title", "merge_inspector_no_selection",
            "merge_inspector_source", "merge_inspector_page", "merge_inspector_size",
            "merge_inspector_portrait", "merge_inspector_landscape",
            "merge_btn_preview", "merge_preview_page", "merge_full_preview_title", "merge_preview_page_info"
        ]
        for lang_code in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            self.assertIn(lang_code, _STRINGS)
            lang_dict = _STRINGS[lang_code]
            for k in keys:
                self.assertIn(k, lang_dict)
                val = lang_dict[k]
                self.assertTrue(val and len(val) > 0, f"Key '{k}' empty in {lang_code}")


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestMergePreview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.wordsys.test.merge_preview")
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

    def setUp(self):
        self.dialog = MergeDialog(parent_window=None)
        drain_events()

    def tearDown(self):
        self.dialog.cleanup()
        self.dialog.close()
        drain_events()

    def test_zoom_controls_and_level_progression(self):
        target = self.dialog.target_panel
        self.dialog.panel_a.load_file(self.pdf_a_path)
        drain_events(20)

        # Initially 100% (zoom_index 2)
        self.assertEqual(target.zoom_index, 2)
        self.assertEqual(target.zoom_level, 1.0)
        self.assertEqual(target.zoom_lbl.get_text(), "100%")

        # Add a page
        self.dialog.panel_a.page_cards[0]._add_to_target()
        self.assertEqual(len(target.page_cards), 1)
        card = target.page_cards[0]
        self.assertEqual(card.zoom_level, 1.0)

        # Zoom in to 120%
        target.zoom_in()
        self.assertEqual(target.zoom_index, 3)
        self.assertEqual(target.zoom_level, 1.2)
        self.assertEqual(target.zoom_lbl.get_text(), "120%")
        self.assertEqual(card.zoom_level, 1.2)
        self.assertTrue(target.zoom_in_btn.get_sensitive())
        self.assertTrue(target.zoom_out_btn.get_sensitive())

        # Zoom in to max 140%
        target.zoom_in()
        self.assertEqual(target.zoom_index, 4)
        self.assertEqual(target.zoom_level, 1.4)
        self.assertEqual(target.zoom_lbl.get_text(), "140%")
        self.assertFalse(target.zoom_in_btn.get_sensitive())
        self.assertTrue(target.zoom_out_btn.get_sensitive())

        # Zoom out back to 120%
        target.zoom_out()
        self.assertEqual(target.zoom_index, 3)
        self.assertEqual(target.zoom_level, 1.2)

        # Reset zoom with zoom_fit
        target.zoom_fit()
        self.assertEqual(target.zoom_index, 2)
        self.assertEqual(target.zoom_level, 1.0)
        self.assertEqual(target.zoom_lbl.get_text(), "100%")

        # Zoom out to minimum (0.7)
        target.zoom_out()
        target.zoom_out()
        self.assertEqual(target.zoom_index, 0)
        self.assertEqual(target.zoom_level, 0.7)
        self.assertEqual(target.zoom_lbl.get_text(), "70%")
        self.assertFalse(target.zoom_out_btn.get_sensitive())
        self.assertTrue(target.zoom_in_btn.get_sensitive())

    def test_insertion_markers_and_custom_position_insertion(self):
        target = self.dialog.target_panel
        self.dialog.panel_a.load_file(self.pdf_a_path)
        self.dialog.panel_b.load_file(self.pdf_b_path)
        drain_events(20)

        # Add 2 pages from doc A: A0, A1
        self.dialog.panel_a.page_cards[0]._add_to_target()
        self.dialog.panel_a.page_cards[1]._add_to_target()

        self.assertEqual(len(target.pages), 2)
        # Markers: before 0, after 0 (before 1), after 1
        self.assertEqual(len(target.markers), 3)
        self.assertEqual([m.index for m in target.markers], [0, 1, 2])

        # Set insertion point to 1 (between A0 and A1)
        target.set_insertion_index(1)
        self.assertEqual(target.insertion_index, 1)
        self.assertFalse(target.markers[0].is_active)
        self.assertTrue(target.markers[1].is_active)
        self.assertFalse(target.markers[2].is_active)

        # Add page from Doc B (B0): should be inserted at index 1
        self.dialog.panel_b.page_cards[0]._add_to_target()
        self.assertEqual(len(target.pages), 3)
        self.assertEqual(target.pages[0]["source_role"], "source_a")
        self.assertEqual(target.pages[0]["page_index"], 0)
        self.assertEqual(target.pages[1]["source_role"], "source_b")
        self.assertEqual(target.pages[1]["page_index"], 0)
        self.assertEqual(target.pages[2]["source_role"], "source_a")
        self.assertEqual(target.pages[2]["page_index"], 1)

        # Auto-advanced insertion index to 2 (after B0)
        self.assertEqual(target.insertion_index, 2)
        self.assertTrue(target.markers[2].is_active)

        # Add another page from Doc B (B1): should be inserted at index 2
        self.dialog.panel_b.page_cards[1]._add_to_target()
        self.assertEqual(len(target.pages), 4)
        self.assertEqual(target.pages[2]["source_role"], "source_b")
        self.assertEqual(target.pages[2]["page_index"], 1)
        self.assertEqual(target.pages[3]["source_role"], "source_a")
        self.assertEqual(target.pages[3]["page_index"], 1)

        # Reset insertion index to None (append to end) via toolbar button
        target.on_insertion_btn_clicked(target.insertion_btn)
        self.assertIsNone(target.insertion_index)
        for m in target.markers:
            self.assertFalse(m.is_active)

        # Add A2: should append to end
        self.dialog.panel_a.page_cards[2]._add_to_target()
        self.assertEqual(len(target.pages), 5)
        self.assertEqual(target.pages[4]["source_role"], "source_a")
        self.assertEqual(target.pages[4]["page_index"], 2)

    def test_card_selection_and_merge_inspector_metadata(self):
        target = self.dialog.target_panel
        self.dialog.panel_a.load_file(self.pdf_a_path)
        self.dialog.panel_b.load_file(self.pdf_b_path)
        drain_events(20)

        # Add A0 and B0
        self.dialog.panel_a.page_cards[0]._add_to_target()
        self.dialog.panel_b.page_cards[0]._add_to_target()

        # Target card 1 was just added, so it's currently selected
        self.assertEqual(target.selected_idx, 1)
        self.assertTrue(target.inspector_card.get_visible())
        self.assertIn("doc_b.pdf", target.insp_source_lbl.get_text())
        self.assertIn("1", target.insp_page_lbl.get_text())
        self.assertIn("400 × 600", target.insp_size_lbl.get_text())
        self.assertEqual(target.insp_orient_lbl.get_text(), _("merge_inspector_portrait"))
        self.assertEqual(target.insp_pos_lbl.get_text(), "#2 / 2")

        # Select card 0 (Doc A, 595 × 842 pt)
        target.select_page(0)
        self.assertEqual(target.selected_idx, 0)
        self.assertTrue(target.page_cards[0].is_selected)
        self.assertFalse(target.page_cards[1].is_selected)
        self.assertIn("doc_a.pdf", target.insp_source_lbl.get_text())
        self.assertIn("1", target.insp_page_lbl.get_text())
        self.assertIn("595 × 842", target.insp_size_lbl.get_text())
        self.assertEqual(target.insp_orient_lbl.get_text(), _("merge_inspector_portrait"))
        self.assertEqual(target.insp_pos_lbl.get_text(), "#1 / 2")

        # Selecting card 0 automatically sets insertion index after it (index 1)
        self.assertEqual(target.insertion_index, 1)
        self.assertTrue(target.markers[1].is_active)

        # Dismiss inspector via close button
        target.inspector_close_btn.emit("clicked")
        self.assertIsNone(target.selected_idx)
        self.assertFalse(target.inspector_card.get_visible())
        self.assertFalse(target.page_cards[0].is_selected)
        self.assertFalse(target.page_cards[1].is_selected)

    def test_marker_direct_click_activation(self):
        target = self.dialog.target_panel
        self.dialog.panel_a.load_file(self.pdf_a_path)
        drain_events(20)

        self.dialog.panel_a.page_cards[0]._add_to_target()
        self.dialog.panel_a.page_cards[1]._add_to_target()

        # Click marker at index 0 (very beginning)
        target.markers[0]._on_clicked(None, 1, 0, 0)
        self.assertEqual(target.insertion_index, 0)
        self.assertTrue(target.markers[0].is_active)
        self.assertEqual(target.insertion_btn.get_label(), _("merge_insert_marker"))

    def test_remove_and_clear_preserves_consistent_state(self):
        target = self.dialog.target_panel
        self.dialog.panel_a.load_file(self.pdf_a_path)
        drain_events(20)

        self.dialog.panel_a.page_cards[0]._add_to_target()
        self.dialog.panel_a.page_cards[1]._add_to_target()
        self.dialog.panel_a.page_cards[2]._add_to_target()

        # Select middle card (index 1)
        target.select_page(1)
        self.assertEqual(target.selected_idx, 1)
        self.assertTrue(target.inspector_card.get_visible())

        # Remove card 0 -> selected index shifts from 1 to 0
        target.remove_page(0)
        self.assertEqual(len(target.pages), 2)
        self.assertEqual(target.selected_idx, 0)
        self.assertTrue(target.inspector_card.get_visible())

        # Remove currently selected card -> selection becomes None, inspector hides
        target.remove_page(0)
        self.assertEqual(len(target.pages), 1)
        self.assertIsNone(target.selected_idx)
        self.assertFalse(target.inspector_card.get_visible())

        # Clear target
        target.clear()
        self.assertEqual(len(target.pages), 0)
        self.assertEqual(len(target.page_cards), 0)
        self.assertEqual(len(target.markers), 0)
        self.assertIsNone(target.selected_idx)
        self.assertIsNone(target.insertion_index)
        self.assertFalse(target.inspector_card.get_visible())
        self.assertFalse(target.insertion_btn.get_sensitive())
        self.assertFalse(target.clear_btn.get_sensitive())
        self.assertFalse(target.zoom_out_btn.get_sensitive())
        self.assertFalse(target.zoom_in_btn.get_sensitive())
        self.assertFalse(target.zoom_fit_btn.get_sensitive())

    def test_page_preview_dialog_features(self):
        self.dialog.panel_a.load_file(self.pdf_a_path)
        drain_events(20)

        added_pages = []
        def on_add(page_idx):
            added_pages.append(page_idx)

        preview = PagePreviewDialog(
            parent_window=self.dialog,
            doc=self.dialog.panel_a.doc,
            page_index=0,
            source_role="source_a",
            file_path=self.pdf_a_path,
            on_add_callback=on_add
        )
        drain_events(10)

        self.assertEqual(preview.current_page_idx, 0)
        self.assertFalse(preview.prev_btn.get_sensitive())
        self.assertTrue(preview.next_btn.get_sensitive())
        info_text = preview.page_info_lbl.get_text()
        self.assertTrue("1" in info_text and "3" in info_text)
        self.assertEqual(preview.zoom_level, 1.0)
        self.assertEqual(preview.zoom_lbl.get_text(), "100%")

        preview._go_page(1)
        self.assertEqual(preview.current_page_idx, 1)
        self.assertTrue(preview.prev_btn.get_sensitive())
        self.assertTrue(preview.next_btn.get_sensitive())
        self.assertIn("2", preview.page_info_lbl.get_text())

        preview._go_page(2)
        self.assertEqual(preview.current_page_idx, 2)
        self.assertTrue(preview.prev_btn.get_sensitive())
        self.assertFalse(preview.next_btn.get_sensitive())

        w, h = preview.picture.get_size_request()
        self.assertEqual(w, 595)
        self.assertEqual(h, 842)

        preview._set_zoom(1.5)
        self.assertEqual(preview.zoom_level, 1.5)
        self.assertEqual(preview.zoom_lbl.get_text(), "150%")
        w15, h15 = preview.picture.get_size_request()
        self.assertEqual(w15, int(595 * 1.5))
        self.assertEqual(h15, int(842 * 1.5))

        preview._set_zoom(5.0)
        self.assertEqual(preview.zoom_level, 3.0)
        preview._set_zoom(0.1)
        self.assertEqual(preview.zoom_level, 0.5)

        preview._zoom_fit()
        self.assertGreater(preview.zoom_level, 0)

        preview._go_page(0)
        preview._on_key_pressed(None, Gdk.KEY_Right, 0, 0)
        self.assertEqual(preview.current_page_idx, 1)
        preview._on_key_pressed(None, Gdk.KEY_Left, 0, 0)
        self.assertEqual(preview.current_page_idx, 0)

        preview._on_add_clicked()
        self.assertEqual(added_pages, [0])

        preview.close()
        drain_events()

    def test_merged_preview_dialog_features(self):
        merged_doc = fitz.open()
        p1 = merged_doc.new_page(width=595, height=842)
        p1.draw_rect(fitz.Rect(10, 10, 50, 50), color=(1, 0, 0))
        p2 = merged_doc.new_page(width=400, height=600)
        p2.draw_rect(fitz.Rect(20, 20, 60, 60), color=(0, 1, 0))

        preview = MergedPreviewDialog(parent_window=self.dialog, merged_doc=merged_doc)
        drain_events(10)

        self.assertEqual(preview.current_page_idx, 0)
        self.assertEqual(preview.doc.page_count, 2)
        merged_info = preview.page_info_lbl.get_text()
        self.assertTrue("1" in merged_info and "2" in merged_info)
        self.assertFalse(preview.prev_btn.get_sensitive())
        self.assertTrue(preview.next_btn.get_sensitive())

        preview._go_page(1)
        self.assertEqual(preview.current_page_idx, 1)
        self.assertTrue(preview.prev_btn.get_sensitive())
        self.assertFalse(preview.next_btn.get_sensitive())

        preview._set_zoom(1.25)
        self.assertEqual(preview.zoom_level, 1.25)

        preview._on_close_request(preview)
        self.assertTrue(merged_doc.is_closed)
        preview.close()
        drain_events()

    def test_preview_buttons_and_triggers(self):
        self.dialog.panel_a.load_file(self.pdf_a_path)
        drain_events(20)

        self.assertFalse(self.dialog.preview_merged_btn.get_sensitive())
        self.assertFalse(self.dialog.target_panel.preview_btn.get_sensitive())

        self.dialog.panel_a.page_cards[0]._add_to_target()
        self.assertTrue(self.dialog.preview_merged_btn.get_sensitive())
        self.assertTrue(self.dialog.target_panel.preview_btn.get_sensitive())

        self.dialog._on_preview_merged_clicked(self.dialog.preview_merged_btn)
        drain_events(10)

        card = self.dialog.panel_a.page_cards[0]
        self.assertIsNotNone(card.preview_btn)
        card._preview_page()
        drain_events(10)

        target_card = self.dialog.target_panel.page_cards[0]
        self.assertIsNotNone(target_card.preview_btn)
        target_card._preview_page()
        drain_events(10)

        self.dialog.target_panel.select_page(0)
        self.assertTrue(self.dialog.target_panel.insp_preview_btn.get_visible())
        self.dialog.target_panel._preview_selected_page()
        drain_events(10)

        self.dialog.target_panel.clear()
        self.assertFalse(self.dialog.preview_merged_btn.get_sensitive())
        self.assertFalse(self.dialog.target_panel.preview_btn.get_sensitive())


if __name__ == "__main__":
    unittest.main()



# ============================================================================
# SECTION: test_merge_transfer_export.py
# ============================================================================
import unittest
import os
import sys
import json
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
    SourcePageCard, TargetPageCard, InsertionMarker
)
from word_sys_pdf_editor import pdf_handler


def drain_events(cycles=10):
    ctx = GLib.MainContext.default()
    for _ in range(cycles):
        count = 0
        while ctx.pending() and count < 100:
            ctx.iteration(False)
            count += 1


class TestExportMergedPdf(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.doc_a_path = os.path.join(self.temp_dir.name, "doc_a.pdf")
        self.doc_b_path = os.path.join(self.temp_dir.name, "doc_b.pdf")
        self.out_path = os.path.join(self.temp_dir.name, "merged_out.pdf")

        doc_a = fitz.open()
        p1 = doc_a.new_page(width=300, height=400)
        p1.insert_text((50, 100), "Doc A Page 1")
        p2 = doc_a.new_page(width=300, height=400)
        p2.insert_text((50, 100), "Doc A Page 2")
        p3 = doc_a.new_page(width=300, height=400)
        p3.insert_text((50, 100), "Doc A Page 3")
        doc_a.set_metadata({
            "title": "Title Doc A",
            "author": "Author A",
            "subject": "Subject A"
        })
        doc_a.set_toc([
            [1, "Chapter 1", 1],
            [2, "Section 1.1", 2],
            [1, "Chapter 2", 3]
        ])
        doc_a.save(self.doc_a_path)
        doc_a.close()

        doc_b = fitz.open()
        bp1 = doc_b.new_page(width=400, height=500)
        bp1.insert_text((60, 120), "Doc B Page 1")
        bp2 = doc_b.new_page(width=400, height=500)
        bp2.insert_text((60, 120), "Doc B Page 2")
        doc_b.set_metadata({
            "title": "Title Doc B",
            "author": "Author B"
        })
        doc_b.set_toc([
            [1, "Appendix B", 1],
            [2, "Notes B", 2]
        ])
        doc_b.save(self.doc_b_path)
        doc_b.close()

        self.doc_a = fitz.open(self.doc_a_path)
        self.doc_b = fitz.open(self.doc_b_path)

    def tearDown(self):
        try:
            if not self.doc_a.is_closed:
                self.doc_a.close()
        except Exception:
            pass
        try:
            if not self.doc_b.is_closed:
                self.doc_b.close()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def test_export_empty_pages(self):
        res = pdf_handler.export_merged_pdf([], self.out_path)
        self.assertFalse(res)
        self.assertFalse(os.path.exists(self.out_path))

    def test_export_merged_pdf_basic(self):
        pages = [
            {"source_doc": self.doc_a, "page_index": 0},
            {"source_doc": self.doc_b, "page_index": 1}
        ]
        res = pdf_handler.export_merged_pdf(pages, self.out_path)
        self.assertTrue(res)
        self.assertTrue(os.path.exists(self.out_path))

        res_doc = fitz.open(self.out_path)
        self.assertEqual(res_doc.page_count, 2)
        self.assertIn("Doc A Page 1", res_doc[0].get_text())
        self.assertIn("Doc B Page 2", res_doc[1].get_text())
        res_doc.close()

    def test_export_merged_pdf_metadata_preservation(self):
        pages = [
            {"source_doc": self.doc_a, "page_index": 0},
            {"source_doc": self.doc_b, "page_index": 0}
        ]
        res = pdf_handler.export_merged_pdf(pages, self.out_path, primary_metadata_doc=self.doc_a)
        self.assertTrue(res)

        res_doc = fitz.open(self.out_path)
        meta = res_doc.metadata
        self.assertEqual(meta.get("title"), "Title Doc A")
        self.assertEqual(meta.get("author"), "Author A")
        self.assertEqual(meta.get("subject"), "Subject A")
        res_doc.close()

    def test_export_merged_pdf_metadata_fallback_first_doc(self):
        pages = [
            {"source_doc": self.doc_b, "page_index": 0},
            {"source_doc": self.doc_a, "page_index": 0}
        ]
        res = pdf_handler.export_merged_pdf(pages, self.out_path, primary_metadata_doc=None)
        self.assertTrue(res)

        res_doc = fitz.open(self.out_path)
        meta = res_doc.metadata
        self.assertEqual(meta.get("title"), "Title Doc B")
        self.assertEqual(meta.get("author"), "Author B")
        res_doc.close()

    def test_export_merged_pdf_toc_remapping(self):
        pages = [
            {"source_doc": self.doc_a, "page_index": 1},
            {"source_doc": self.doc_b, "page_index": 0},
            {"source_doc": self.doc_a, "page_index": 2}
        ]
        res = pdf_handler.export_merged_pdf(pages, self.out_path)
        self.assertTrue(res)

        res_doc = fitz.open(self.out_path)
        self.assertEqual(res_doc.page_count, 3)
        toc = res_doc.get_toc()
        self.assertTrue(len(toc) >= 3)

        titles_and_pages = [(item[1], item[2]) for item in toc]
        self.assertIn(("Section 1.1", 1), titles_and_pages)
        self.assertIn(("Appendix B", 2), titles_and_pages)
        self.assertIn(("Chapter 2", 3), titles_and_pages)

        titles = [item[1] for item in toc]
        self.assertNotIn("Chapter 1", titles)
        self.assertNotIn("Notes B", titles)

        page_numbers = [item[2] for item in toc]
        self.assertEqual(page_numbers, sorted(page_numbers))
        res_doc.close()

    def test_export_merged_pdf_duplicate_page_toc(self):
        pages = [
            {"source_doc": self.doc_a, "page_index": 0},
            {"source_doc": self.doc_b, "page_index": 0},
            {"source_doc": self.doc_a, "page_index": 0}
        ]
        res = pdf_handler.export_merged_pdf(pages, self.out_path)
        self.assertTrue(res)

        res_doc = fitz.open(self.out_path)
        self.assertEqual(res_doc.page_count, 3)
        self.assertIn("Doc A Page 1", res_doc[0].get_text())
        self.assertIn("Doc B Page 1", res_doc[1].get_text())
        self.assertIn("Doc A Page 1", res_doc[2].get_text())
        res_doc.close()

    def test_export_merged_pdf_atomic_clean_up(self):
        pages = [{"source_doc": self.doc_a, "page_index": 0}]
        res = pdf_handler.export_merged_pdf(pages, self.out_path)
        self.assertTrue(res)
        temp_file = self.out_path + ".tmp_merged"
        self.assertFalse(os.path.exists(temp_file))


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestMergeDragAndDrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.wordsys.test.merge_transfer_export")
        cls.app.register(None)

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.pdf_a_path = os.path.join(cls.temp_dir.name, "doc_a.pdf")
        cls.pdf_b_path = os.path.join(cls.temp_dir.name, "doc_b.pdf")

        doc_a = fitz.open()
        p1 = doc_a.new_page(width=300, height=400)
        p1.insert_text((50, 100), "A1")
        p2 = doc_a.new_page(width=300, height=400)
        p2.insert_text((50, 100), "A2")
        doc_a.save(cls.pdf_a_path)
        doc_a.close()

        doc_b = fitz.open()
        bp1 = doc_b.new_page(width=400, height=500)
        bp1.insert_text((60, 120), "B1")
        bp2 = doc_b.new_page(width=400, height=500)
        bp2.insert_text((60, 120), "B2")
        doc_b.save(cls.pdf_b_path)
        doc_b.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        self.dialog = MergeDialog(parent_window=None)
        self.dialog.panel_a.load_file(self.pdf_a_path)
        self.dialog.panel_b.load_file(self.pdf_b_path)
        drain_events(20)

    def tearDown(self):
        self.dialog.cleanup()
        self.dialog.destroy()
        drain_events(10)

    def test_handle_drop_source_to_target(self):
        payload = json.dumps({
            "type": "merge_page_transfer",
            "role": "source_a",
            "page_index": 0
        })
        res = self.dialog.target_panel.handle_drop(payload)
        self.assertTrue(res)
        self.assertEqual(len(self.dialog.target_panel.pages), 1)
        self.assertEqual(self.dialog.target_panel.pages[0]["source_role"], "source_a")
        self.assertEqual(self.dialog.target_panel.pages[0]["page_index"], 0)

    def test_handle_drop_source_to_target_with_index(self):
        payload_a0 = json.dumps({"type": "merge_page_transfer", "role": "source_a", "page_index": 0})
        payload_a1 = json.dumps({"type": "merge_page_transfer", "role": "source_a", "page_index": 1})
        payload_b0 = json.dumps({"type": "merge_page_transfer", "role": "source_b", "page_index": 0})

        self.dialog.target_panel.handle_drop(payload_a0)
        self.dialog.target_panel.handle_drop(payload_a1)
        self.assertEqual(len(self.dialog.target_panel.pages), 2)

        res = self.dialog.target_panel.handle_drop(payload_b0, target_index=1)
        self.assertTrue(res)
        self.assertEqual(len(self.dialog.target_panel.pages), 3)
        self.assertEqual(self.dialog.target_panel.pages[1]["source_role"], "source_b")
        self.assertEqual(self.dialog.target_panel.pages[1]["page_index"], 0)

    def test_handle_drop_target_reorder(self):
        tp = self.dialog.target_panel
        tp.handle_drop(json.dumps({"type": "merge_page_transfer", "role": "source_a", "page_index": 0}))
        tp.handle_drop(json.dumps({"type": "merge_page_transfer", "role": "source_a", "page_index": 1}))
        tp.handle_drop(json.dumps({"type": "merge_page_transfer", "role": "source_b", "page_index": 0}))
        self.assertEqual(len(tp.pages), 3)

        reorder_payload = json.dumps({
            "type": "merge_target_reorder",
            "from_index": 0
        })
        res = tp.handle_drop(reorder_payload, target_index=2)
        self.assertTrue(res)
        self.assertEqual(tp.pages[0]["page_index"], 1)
        self.assertEqual(tp.pages[1]["page_index"], 0)

    def test_handle_drop_invalid_payloads(self):
        tp = self.dialog.target_panel
        self.assertFalse(tp.handle_drop("invalid json"))
        self.assertFalse(tp.handle_drop(json.dumps({"type": "unknown"})))
        self.assertFalse(tp.handle_drop(json.dumps({"type": "merge_page_transfer"})))
        self.assertFalse(tp.handle_drop(json.dumps({"type": "merge_target_reorder", "from_index": 99})))

    def test_target_panel_move_page_to_insertion(self):
        tp = self.dialog.target_panel
        tp.handle_drop(json.dumps({"type": "merge_page_transfer", "role": "source_a", "page_index": 0}))
        tp.handle_drop(json.dumps({"type": "merge_page_transfer", "role": "source_a", "page_index": 1}))
        tp.handle_drop(json.dumps({"type": "merge_page_transfer", "role": "source_b", "page_index": 0}))

        tp.move_page_to_insertion(2, 0)
        self.assertEqual(tp.pages[0]["source_role"], "source_b")

        tp.move_page_to_insertion(0, 0)
        self.assertEqual(tp.pages[0]["source_role"], "source_b")

        tp.move_page_to_insertion(0, 1)
        self.assertEqual(tp.pages[0]["source_role"], "source_b")

    def test_save_button_sensitivity_on_drop(self):
        self.assertFalse(self.dialog.save_btn.get_sensitive())
        payload = json.dumps({
            "type": "merge_page_transfer",
            "role": "source_a",
            "page_index": 0
        })
        self.dialog.target_panel.handle_drop(payload)
        drain_events(5)
        self.assertTrue(self.dialog.save_btn.get_sensitive())

        self.dialog.target_panel.clear()
        drain_events(5)
        self.assertFalse(self.dialog.save_btn.get_sensitive())

    def test_source_card_double_click_preview(self):
        panel_a = self.dialog.panel_a
        self.assertTrue(len(panel_a.page_cards) > 0)
        card = panel_a.page_cards[0]
        preview_called = False
        def mock_preview():
            nonlocal preview_called
            preview_called = True
        card._preview_page = mock_preview

        card._on_gesture_pressed(None, 1, 0, 0)
        self.assertFalse(preview_called)

        card._on_gesture_pressed(None, 2, 0, 0)
        self.assertTrue(preview_called)


if __name__ == '__main__':
    unittest.main()



# ============================================================================
# SECTION: test_export.py
# ============================================================================
"""Comprehensive test suite for Export Dialog & Format Expansion."""

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
import unittest

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw, GLib, Gio
import fitz

from word_sys_pdf_editor.export_dialog import ExportDialog, FORMAT_ITEMS
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor import i18n
from word_sys_pdf_editor import locales


def run_main_loop(iterations=20, delay=0.02):
    """Pump the GLib main context to process idle callbacks."""
    ctx = GLib.MainContext.default()
    for _ in range(iterations):
        count = 0
        while ctx.pending() and count < 100:
            ctx.iteration(False)
            count += 1
        time.sleep(delay)


class TestExportLocalization(unittest.TestCase):
    """Verify localization keys across all 7 supported languages."""

    EXPORT_KEYS = [
        "menu_export",
        "export_dialog_title",
        "export_format_title",
        "export_format_label",
        "export_layout_mode_title",
        "export_mode_canvas",
        "export_mode_canvas_desc",
        "export_mode_flow",
        "export_mode_flow_desc",
        "export_btn_choose",
        "export_btn_confirm",
        "export_format_docx",
        "export_format_pptx",
        "export_format_odt",
        "export_format_odp",
        "export_format_txt",
        "export_in_progress",
    ]

    def test_all_languages_have_export_keys(self):
        supported_langs = [code for code, _ in i18n.get_supported_languages()]
        self.assertEqual(len(supported_langs), 7)

        for lang in supported_langs:
            table = i18n._STRINGS.get(lang)
            self.assertIsNotNone(table, f"Missing language table for {lang}")
            for key in self.EXPORT_KEYS:
                self.assertIn(key, table, f"Language '{lang}' missing key '{key}'")
                val = table[key]
                self.assertTrue(isinstance(val, str) and len(val) > 0, f"Empty translation for '{key}' in '{lang}'")
                # Strict check: ZERO emojis
                for char in val:
                    self.assertLess(ord(char), 0x1F000, f"Found potential emoji in '{lang}' key '{key}': {val}")


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestExportDialog(unittest.TestCase):
    """Unit tests for ExportDialog widget."""

    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.word_sys.test.export")

    def test_default_instantiation(self):
        dialog = ExportDialog(None, initial_format="DOCX", initial_mode="canvas")
        self.assertEqual(dialog.get_selected_format(), "DOCX")
        self.assertEqual(dialog.get_selected_mode(), "canvas")
        self.assertTrue(dialog.layout_group.get_sensitive())

    def test_flow_mode_selection(self):
        dialog = ExportDialog(None, initial_format="PPTX", initial_mode="flow")
        self.assertEqual(dialog.get_selected_format(), "PPTX")
        self.assertEqual(dialog.get_selected_mode(), "flow")
        self.assertTrue(dialog.layout_group.get_sensitive())

    def test_txt_format_disables_layout_group(self):
        dialog = ExportDialog(None, initial_format="TXT")
        self.assertEqual(dialog.get_selected_format(), "TXT")
        self.assertEqual(dialog.get_selected_mode(), "canvas")
        self.assertFalse(dialog.layout_group.get_sensitive())

    def test_format_switching_updates_sensitivity(self):
        dialog = ExportDialog(None, initial_format="DOCX")
        self.assertTrue(dialog.layout_group.get_sensitive())

        # Select TXT index
        txt_idx = [idx for idx, (k, _) in enumerate(FORMAT_ITEMS) if k == "TXT"][0]
        dialog.format_row.set_selected(txt_idx)
        self.assertEqual(dialog.get_selected_format(), "TXT")
        self.assertFalse(dialog.layout_group.get_sensitive())

        # Switch back to ODT
        odt_idx = [idx for idx, (k, _) in enumerate(FORMAT_ITEMS) if k == "ODT"][0]
        dialog.format_row.set_selected(odt_idx)
        self.assertEqual(dialog.get_selected_format(), "ODT")
        self.assertTrue(dialog.layout_group.get_sensitive())

    def test_confirm_callback_trigger(self):
        result = {}

        def on_confirm(fmt, mode):
            result["format"] = fmt
            result["mode"] = mode

        dialog = ExportDialog(None, initial_format="ODP", initial_mode="canvas", on_confirm_callback=on_confirm)
        dialog._on_export_clicked(dialog.export_btn)

        self.assertEqual(result.get("format"), "ODP")
        self.assertEqual(result.get("mode"), "canvas")


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestWindowExportActions(unittest.TestCase):
    """Unit tests for PdfEditorWindow export actions and UI states."""

    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.word_sys.test.window_export")
        cls.win = PdfEditorWindow(application=cls.app)

    def test_export_actions_registered(self):
        expected_actions = [
            "export_as",
            "export_docx",
            "export_pptx",
            "export_odt",
            "export_odp",
            "export_txt",
        ]
        for act in expected_actions:
            action_obj = self.win.lookup_action(act)
            self.assertIsNotNone(action_obj, f"Action {act} not registered on window")

    def test_actions_disabled_without_document(self):
        self.win.doc = None
        self.win._update_ui_state()

        expected_actions = [
            "export_as",
            "export_docx",
            "export_pptx",
            "export_odt",
            "export_odp",
            "export_txt",
            "protect_document",
            "digitally_sign_document",
            "inspect_digital_signatures",
            "flatten_annotations",
            "toggle_annotations",
            "close_tab",
        ]
        for act in expected_actions:
            action_obj = self.win.lookup_action(act)
            self.assertIsNotNone(action_obj, f"Action {act} not found")
            self.assertFalse(action_obj.get_enabled(), f"Action {act} should be disabled when no doc")

    def test_actions_enabled_with_document(self):
        doc = fitz.open()
        doc.new_page(width=300, height=300)
        self.win.doc = doc
        self.win._update_ui_state()

        expected_actions = [
            "export_as",
            "export_docx",
            "export_pptx",
            "export_odt",
            "export_odp",
            "export_txt",
            "protect_document",
            "digitally_sign_document",
            "inspect_digital_signatures",
            "flatten_annotations",
            "toggle_annotations",
            "close_tab",
        ]
        for act in expected_actions:
            action_obj = self.win.lookup_action(act)
            self.assertIsNotNone(action_obj, f"Action {act} not found")
            self.assertTrue(action_obj.get_enabled(), f"Action {act} should be enabled when doc loaded")
        doc.close()

    def test_direct_export_bypasses_dialog_and_uses_canvas(self):
        invoked_prompts = []

        def mock_prompt(fmt, mode="canvas"):
            invoked_prompts.append((fmt, mode))

        orig_prompt = self.win._prompt_export_destination
        self.win._prompt_export_destination = mock_prompt
        try:
            self.win.on_export_docx()
            self.win.on_export_pptx()
            self.win.on_export_odt()
            self.win.on_export_odp()
            self.win.on_export_txt()

            self.assertEqual(invoked_prompts, [
                ("DOCX", "canvas"),
                ("PPTX", "canvas"),
                ("ODT", "canvas"),
                ("ODP", "canvas"),
                ("TXT", "canvas"),
            ])
        finally:
            self.win._prompt_export_destination = orig_prompt

    def test_export_as_opens_settings_dialog(self):
        dialog_opened = []

        def mock_show_dialog(initial_format="DOCX"):
            dialog_opened.append(initial_format)

        orig_show = self.win.show_export_dialog
        self.win.show_export_dialog = mock_show_dialog
        try:
            self.win.on_export_as()
            self.assertEqual(dialog_opened, ["DOCX"])
        finally:
            self.win.show_export_dialog = orig_show

    def test_export_dialog_button_label_is_compact(self):
        dialog = ExportDialog(None, initial_format="DOCX")
        self.assertEqual(dialog.export_btn.get_label(), i18n._("export_btn_confirm"))


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestAsynchronousExportExecution(unittest.TestCase):
    """End-to-end tests for asynchronous export via _execute_export."""

    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.word_sys.test.async_export")
        cls.win = PdfEditorWindow(application=cls.app)

        # Create a test PDF with text and shapes
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_pdf = os.path.join(cls.temp_dir.name, "sample.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=400)
        page.insert_text(fitz.Point(50, 50), "Export Verification Header", fontsize=14)
        page.insert_text(fitz.Point(50, 100), "Testing AnyConvert asynchronous background export.", fontsize=11)
        doc.save(cls.test_pdf)
        doc.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        self.doc = fitz.open(self.test_pdf)
        self.win.doc = self.doc
        self.win.current_file_path = self.test_pdf

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def _wait_for_export(self, fmt, mode="canvas"):
        out_path = os.path.join(self.temp_dir.name, f"output_{mode}.{fmt.lower()}")
        finished_event = threading.Event()
        result = {}

        def on_done(success, err):
            result["success"] = success
            result["error"] = err
            finished_event.set()

        self.win._execute_export(fmt, out_path, mode=mode, on_finish=on_done)

        # Ensure UI returns immediately before finish
        self.assertIn(fmt.upper(), self.win.status_label.get_text())

        # Pump main context until worker completes
        start_time = time.time()
        while not finished_event.is_set():
            if time.time() - start_time > 15.0:
                self.fail(f"Export to {fmt} timed out after 15 seconds")
            run_main_loop(iterations=5, delay=0.02)

        return result, out_path

    def test_async_export_docx_canvas(self):
        res, out_path = self._wait_for_export("DOCX", mode="canvas")
        self.assertTrue(res.get("success"), f"DOCX canvas export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_docx_flow(self):
        res, out_path = self._wait_for_export("DOCX", mode="flow")
        self.assertTrue(res.get("success"), f"DOCX flow export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_pptx(self):
        res, out_path = self._wait_for_export("PPTX", mode="canvas")
        self.assertTrue(res.get("success"), f"PPTX export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_odt(self):
        res, out_path = self._wait_for_export("ODT", mode="canvas")
        self.assertTrue(res.get("success"), f"ODT export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_odp(self):
        res, out_path = self._wait_for_export("ODP", mode="canvas")
        self.assertTrue(res.get("success"), f"ODP export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_txt(self):
        res, out_path = self._wait_for_export("TXT", mode="canvas")
        self.assertTrue(res.get("success"), f"TXT export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        content = Path(out_path).read_text(encoding="utf-8")
        self.assertIn("Export Verification Header", content)

    def test_async_export_invalid_format(self):
        out_path = os.path.join(self.temp_dir.name, "output.xyz")
        finished_event = threading.Event()
        result = {}

        def on_done(success, err):
            result["success"] = success
            result["error"] = err
            finished_event.set()

        self.win._execute_export("XYZ", out_path, on_finish=on_done)

        start_time = time.time()
        while not finished_event.is_set():
            if time.time() - start_time > 5.0:
                self.fail("Timed out waiting for invalid format error callback")
            run_main_loop(iterations=5, delay=0.02)

        self.assertFalse(result.get("success"))
        self.assertEqual(result.get("error"), i18n._("err_unknown_export_format"))


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_anyconvert_integration.py
# ============================================================================
import unittest
import os
import sys
import tempfile
import pathlib
import zipfile

import fitz

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableText, EditableShape, EditableStroke


class TestAnyConvertIntegration(unittest.TestCase):
    """Thorough unit tests for AnyConvert Backend Integration."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = pathlib.Path(self.temp_dir.name)

        # Create a standard test PDF
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        self.page.insert_text((72, 100), "AnyConvert Integration Test", fontsize=20)
        self.page.insert_text((72, 150), "Testing Native Python Document Export.", fontsize=12)

        self.sample_pdf_path = str(self.temp_path / "sample.pdf")
        self.doc.save(self.sample_pdf_path)

    def tearDown(self):
        try:
            self.doc.close()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def test_01_purge_verification(self):
        """Verify that all LibreOffice and flatpak-spawn functions are completely purged."""
        self.assertFalse(hasattr(pdf_handler, "_is_flatpak_sandbox"))
        self.assertFalse(hasattr(pdf_handler, "_resolve_libreoffice_command"))
        self.assertFalse(hasattr(pdf_handler, "_export_via_libreoffice"))
        self.assertFalse(hasattr(pdf_handler, "_export_pdf_via_libreoffice"))
        self.assertTrue(pdf_handler.HAS_ANYCONVERT)
        self.assertTrue(hasattr(pdf_handler, "export_document"))

    def test_02_export_document_all_formats_canvas_mode(self):
        """Test export_document for docx, pptx, odt, odp, txt in canvas mode."""
        for fmt in ("docx", "pptx", "odt", "odp", "txt"):
            out_file = str(self.temp_path / f"export_canvas.{fmt}")
            success, err = pdf_handler.export_document(
                doc=self.doc,
                source_pdf_path=self.sample_pdf_path,
                output_path=out_file,
                target_format=fmt,
                mode="canvas",
            )
            self.assertTrue(success, f"Failed exporting {fmt} in canvas mode: {err}")
            self.assertIsNone(err)
            self.assertTrue(os.path.exists(out_file))
            self.assertGreater(os.path.getsize(out_file), 0)

            # Check ZIP validity for archive formats
            if fmt in ("docx", "pptx", "odt", "odp"):
                self.assertTrue(zipfile.is_zipfile(out_file), f"{out_file} is not a valid zip archive")

            # Check TXT content
            if fmt == "txt":
                with open(out_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("AnyConvert Integration Test", content)

    def test_03_export_document_all_formats_flow_mode(self):
        """Test export_document for docx, pptx, odt, odp, txt in flow mode."""
        for fmt in ("docx", "pptx", "odt", "odp", "txt"):
            out_file = str(self.temp_path / f"export_flow.{fmt}")
            success, err = pdf_handler.export_document(
                doc=self.doc,
                source_pdf_path=self.sample_pdf_path,
                output_path=out_file,
                target_format=fmt,
                mode="flow",
            )
            self.assertTrue(success, f"Failed exporting {fmt} in flow mode: {err}")
            self.assertIsNone(err)
            self.assertTrue(os.path.exists(out_file))
            self.assertGreater(os.path.getsize(out_file), 0)

            if fmt == "txt":
                with open(out_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("AnyConvert Integration Test", content)

    def test_04_in_memory_unsaved_edits_exported(self):
        """Verify that in-memory edits to doc convert directly without saving to disk first."""
        # Add edited elements to in-memory doc
        edited_doc = fitz.open()
        p = edited_doc.new_page(width=600, height=800)
        p.insert_text((72, 100), "Unsaved Original Title", fontsize=18)

        # Apply an in-memory modification
        text_obj = EditableText(
            x=72,
            y=180,
            text="Unsaved Modified Secret Content",
            font_size=16,
            color=(0, 0, 1),
            rotation=15.0,
            alignment="center",
        )
        text_obj.is_strikethrough = True
        pdf_handler._apply_single_object_to_page(edited_doc, p, text_obj)

        out_docx = str(self.temp_path / "in_memory_edit.docx")
        out_txt = str(self.temp_path / "in_memory_edit.txt")

        # Export without saving edited_doc to disk
        success_docx, err_docx = pdf_handler.export_pdf_as_docx(edited_doc, None, out_docx, mode="canvas")
        self.assertTrue(success_docx, f"DOCX in-memory export failed: {err_docx}")
        self.assertTrue(os.path.exists(out_docx))

        success_txt, err_txt = pdf_handler.export_pdf_as_text(edited_doc, out_txt, mode="canvas")
        self.assertTrue(success_txt, f"TXT in-memory export failed: {err_txt}")
        with open(out_txt, "r", encoding="utf-8") as f:
            txt_content = f.read()
        self.assertIn("SecretContent", txt_content.replace(" ", ""))
        edited_doc.close()

    def test_05_export_from_source_path_only(self):
        """Test exporting when doc is None and only source_pdf_path is provided."""
        out_docx = str(self.temp_path / "from_path.docx")
        success, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=self.sample_pdf_path,
            output_path=out_docx,
            target_format="docx",
        )
        self.assertTrue(success, f"Failed exporting from path: {err}")
        self.assertTrue(os.path.exists(out_docx))

    def test_06_format_wrappers(self):
        """Test format-specific wrappers export_pdf_as_*."""
        docx_path = str(self.temp_path / "wrapper.docx")
        odt_path = str(self.temp_path / "wrapper.odt")
        pptx_path = str(self.temp_path / "wrapper.pptx")
        odp_path = str(self.temp_path / "wrapper.odp")
        txt_path = str(self.temp_path / "wrapper.txt")

        s1, e1 = pdf_handler.export_pdf_as_docx(self.doc, self.sample_pdf_path, docx_path)
        self.assertTrue(s1, e1)
        self.assertTrue(os.path.exists(docx_path))

        s2, e2 = pdf_handler.export_pdf_as_odt(self.doc, self.sample_pdf_path, odt_path)
        self.assertTrue(s2, e2)
        self.assertTrue(os.path.exists(odt_path))

        s3, e3 = pdf_handler.export_pdf_as_pptx(self.doc, self.sample_pdf_path, pptx_path)
        self.assertTrue(s3, e3)
        self.assertTrue(os.path.exists(pptx_path))

        s4, e4 = pdf_handler.export_pdf_as_odp(self.doc, self.sample_pdf_path, odp_path)
        self.assertTrue(s4, e4)
        self.assertTrue(os.path.exists(odp_path))

        s5, e5 = pdf_handler.export_pdf_as_text(self.doc, txt_path)
        self.assertTrue(s5, e5)
        self.assertTrue(os.path.exists(txt_path))

    def test_07_invalid_inputs_and_error_handling(self):
        """Test error handling on invalid formats, missing paths, and missing documents."""
        # Missing output path
        s, err = pdf_handler.export_document(doc=self.doc, output_path="")
        self.assertFalse(s)
        self.assertIn("Destination output path must be specified", err)

        # Unsupported target format
        s, err = pdf_handler.export_document(
            doc=self.doc,
            output_path=str(self.temp_path / "out.xyz"),
            target_format="xyz",
        )
        self.assertFalse(s)
        self.assertIn("Unsupported export format", err)

        # No doc and no source path
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=None,
            output_path=str(self.temp_path / "out.docx"),
            target_format="docx",
        )
        self.assertFalse(s)
        self.assertIn("No valid document or file path", err)

    def test_08_password_protected_pdf_handling(self):
        """Test export behavior on encrypted/password-protected PDFs."""
        enc_doc = fitz.open()
        p = enc_doc.new_page()
        p.insert_text((72, 100), "Confidential AnyConvert Document")
        enc_bytes = enc_doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="securepass",
            owner_pw="ownerpass",
        )
        enc_path = str(self.temp_path / "encrypted.pdf")
        with open(enc_path, "wb") as f:
            f.write(enc_bytes)
        enc_doc.close()

        out_docx = str(self.temp_path / "decrypted.docx")

        # 1. Attempt export without password -> should report password required
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=enc_path,
            output_path=out_docx,
            target_format="docx",
            password="",
        )
        self.assertFalse(s)
        self.assertIn("password-protected", err.lower())

        # 2. Attempt export with wrong password -> should report incorrect password
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=enc_path,
            output_path=out_docx,
            target_format="docx",
            password="wrongpassword",
        )
        self.assertFalse(s)
        self.assertIn("incorrect", err.lower())

        # 3. Export with correct password -> should succeed cleanly
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=enc_path,
            output_path=out_docx,
            target_format="docx",
            password="securepass",
        )
        self.assertTrue(s, f"Export with correct password failed: {err}")
        self.assertTrue(os.path.exists(out_docx))
        self.assertGreater(os.path.getsize(out_docx), 0)

    def test_09_multilingual_unicode_content(self):
        """Test exporting text in FR, DE, ES, IT, RU, TR."""
        multi_doc = fitz.open()
        p = multi_doc.new_page(width=595, height=842)
        multilingual_text = (
            "Français: Déjà vu, été, forêt\n"
            "Deutsch: Äpfel, Grüße, Übertragen\n"
            "Español: Niño, año, pingüino, canción\n"
            "Italiano: Città, caffè, perché, più\n"
            "Русский: Привет, мир, редактирование PDF\n"
            "Türkçe: Şiir, ağaç, çağdaş, gün ışığı"
        )
        p.insert_text((50, 100), multilingual_text, fontsize=12)

        for fmt in ("docx", "odt", "txt"):
            out_file = str(self.temp_path / f"multilingual.{fmt}")
            s, err = pdf_handler.export_document(multi_doc, None, out_file, target_format=fmt, mode="canvas")
            self.assertTrue(s, f"Failed exporting multilingual {fmt}: {err}")
            self.assertTrue(os.path.exists(out_file))

        multi_doc.close()

    def test_10_multipage_complex_layout(self):
        """Test exporting multi-page PDF with shapes, text, and different aspect ratios."""
        doc = fitz.open()
        # Page 1: Portrait A4
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((72, 100), "Page 1 - Architecture Overview", fontsize=18)
        p1.draw_rect(fitz.Rect(72, 150, 500, 300), color=(0.2, 0.4, 0.8), fill=(0.95, 0.95, 1.0))
        p1.insert_text((90, 200), "Boxed layout content", fontsize=14)

        # Page 2: Landscape
        p2 = doc.new_page(width=842, height=595)
        p2.insert_text((72, 100), "Page 2 - Landscape Diagram Presentation", fontsize=18)
        p2.draw_rect(fitz.Rect(100, 200, 400, 400), color=(0.8, 0.2, 0.2), fill=(1.0, 0.95, 0.95))

        for fmt in ("pptx", "odp", "docx"):
            out_file = str(self.temp_path / f"multipage.{fmt}")
            s, err = pdf_handler.export_document(doc, None, out_file, target_format=fmt, mode="canvas")
            self.assertTrue(s, f"Failed multipage {fmt}: {err}")
            self.assertTrue(os.path.exists(out_file))
            self.assertGreater(os.path.getsize(out_file), 1000)

        doc.close()

    def test_11_conversion_mode_enum(self):
        """Test passing ConversionMode enum directly as mode argument."""
        from anyconvert import ConversionMode
        out_docx = str(self.temp_path / "enum_mode.docx")
        s, err = pdf_handler.export_document(
            doc=self.doc,
            output_path=out_docx,
            target_format="docx",
            mode=ConversionMode.CANVAS,
        )
        self.assertTrue(s, err)
        self.assertTrue(os.path.exists(out_docx))

    def test_12_case_insensitive_and_dotted_format(self):
        """Test formats specified with uppercase or leading dots."""
        for fmt, ext in [(".DOCX", "docx"), ("PpTx", "pptx"), (".odt", "odt"), ("ODP", "odp"), (".TXT", "txt")]:
            out_file = str(self.temp_path / f"case_test.{ext}")
            s, err = pdf_handler.export_document(
                doc=self.doc,
                output_path=out_file,
                target_format=fmt,
            )
            self.assertTrue(s, f"Failed on format specifier '{fmt}': {err}")
            self.assertTrue(os.path.exists(out_file))

    def test_13_corrupt_bytes_error_handling(self):
        """Test graceful error handling when invalid/corrupt PDF bytes are provided."""
        corrupt_path = str(self.temp_path / "corrupt.pdf")
        with open(corrupt_path, "wb") as f:
            f.write(b"NOT_A_REAL_PDF_HEADER_OR_BODY_DATA")

        out_docx = str(self.temp_path / "corrupt_out.docx")
        s, err = pdf_handler.export_document(
            doc=None,
            source_pdf_path=corrupt_path,
            output_path=out_docx,
            target_format="docx",
        )
        self.assertFalse(s)
        self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main()

