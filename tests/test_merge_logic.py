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
