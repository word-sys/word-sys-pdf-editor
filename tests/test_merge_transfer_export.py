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
        while ctx.pending():
            ctx.iteration(False)


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

