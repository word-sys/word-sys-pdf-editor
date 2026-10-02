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
        while ctx.pending():
            ctx.iteration(False)


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

