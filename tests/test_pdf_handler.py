import unittest
import tempfile
import os
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor import pdf_handler


class TestPdfHandler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sample_pdf = os.path.join(self.temp_dir.name, "sample.pdf")
        doc = fitz.open()
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((50, 100), "Hello PDF Test", fontsize=14)
        p1.draw_rect(fitz.Rect(50, 150, 200, 250), color=(1, 0, 0), fill=(0.9, 0.9, 0.9))
        p2 = doc.new_page(width=612, height=792)
        p2.insert_text((50, 100), "Second Page Content", fontsize=14)
        doc.save(self.sample_pdf)
        doc.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_page_count(self):
        doc = fitz.open(self.sample_pdf)
        self.assertEqual(pdf_handler.get_page_count(doc), 2)
        doc.close()
        self.assertEqual(pdf_handler.get_page_count(None), 0)

    def test_rotate_point(self):
        # 90 degrees around origin
        nx, ny = pdf_handler.rotate_point(10, 0, 0, 0, 90)
        self.assertAlmostEqual(nx, 0.0, places=4)
        self.assertAlmostEqual(ny, 10.0, places=4)

        # 0 degrees
        nx, ny = pdf_handler.rotate_point(15, 25, 0, 0, 0)
        self.assertEqual(nx, 15)
        self.assertEqual(ny, 25)

    def test_generate_thumbnail_headless(self):
        doc = fitz.open(self.sample_pdf)
        pixbuf = pdf_handler.generate_thumbnail(doc, 0, target_width=120)
        self.assertIsNotNone(pixbuf)
        self.assertEqual(pixbuf.get_width(), 120)
        self.assertGreater(pixbuf.get_height(), 100)
        doc.close()

    def test_extract_text_and_shapes(self):
        doc = fitz.open(self.sample_pdf)
        texts, _ = pdf_handler.extract_editable_text(doc, 0)
        shapes, _ = pdf_handler.extract_editable_shapes(doc, 0)
        self.assertGreaterEqual(len(texts), 1)
        self.assertTrue(any("Hello" in t.text for t in texts))
        self.assertGreaterEqual(len(shapes), 1)
        doc.close()


if __name__ == '__main__':
    unittest.main()
