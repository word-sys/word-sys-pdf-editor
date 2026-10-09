import unittest
import tempfile
import os
import math

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import (
    EditableText,
    FLAG_BOLD,
    FLAG_ITALIC,
    FLAG_SERIF,
    FLAG_MONOSPACED,
    decompose_font_name,
    extract_font_properties,
    get_base14_font_variant,
)


class TestFontDecompositionAndExtraction(unittest.TestCase):
    """Test suite for font name decomposition, flag parsing, and Base14 resolution."""

    def test_subset_prefix_stripping(self):
        """Verify 6-letter subset prefixes like ABCDEF+ are cleanly separated."""
        info = decompose_font_name("ABCDEF+LiberationSans-Bold")
        self.assertEqual(info["subset_prefix"], "ABCDEF+")
        self.assertEqual(info["name_without_prefix"], "LiberationSans-Bold")
        self.assertEqual(info["clean_family"], "LiberationSans")
        self.assertTrue(info["is_bold"])
        self.assertFalse(info["is_italic"])
        self.assertEqual(info["base14_variant"], "Helvetica-Bold")
        self.assertEqual(info["font_weight"], 700)
        self.assertEqual(info["font_slant"], "normal")

    def test_postscript_and_monotype_suffixes(self):
        """Verify PSMT, PS, and MT suffixes are cleanly handled."""
        info1 = decompose_font_name("TimesNewRomanPSMT")
        self.assertIsNone(info1["subset_prefix"])
        self.assertEqual(info1["base_family"], "Times New Roman")
        self.assertTrue(info1["is_serif"])
        self.assertFalse(info1["is_bold"])
        self.assertEqual(info1["base14_variant"], "Times-Roman")

        info2 = decompose_font_name("Arial-BoldItalicMT")
        self.assertTrue(info2["is_bold"])
        self.assertTrue(info2["is_italic"])
        self.assertEqual(info2["base14_variant"], "Helvetica-BoldOblique")
        self.assertEqual(info2["font_weight"], 700)
        self.assertEqual(info2["font_slant"], "italic")

    def test_style_tokens_detection(self):
        """Verify style tokens like Oblique, Kursiv, DemiBold, etc. are recognized."""
        info_oblique = decompose_font_name("Courier-Oblique")
        self.assertTrue(info_oblique["is_italic"])
        self.assertTrue(info_oblique["is_monospace"])
        self.assertFalse(info_oblique["is_bold"])
        self.assertEqual(info_oblique["base14_variant"], "Courier-Oblique")

        info_kursiv = decompose_font_name("CustomFont-Kursiv")
        self.assertTrue(info_kursiv["is_italic"])

        info_heavy = decompose_font_name("BrandSans-Heavy")
        self.assertTrue(info_heavy["is_bold"])

    def test_font_flags_integration(self):
        """Verify bitmask flags augment font property detection."""
        flags = FLAG_BOLD | FLAG_ITALIC | FLAG_MONOSPACED
        info = decompose_font_name("CustomFont", flags=flags)
        self.assertTrue(info["is_bold"])
        self.assertTrue(info["is_italic"])
        self.assertTrue(info["is_monospace"])
        self.assertEqual(info["base14_code"], "cour")
        self.assertEqual(info["base14_variant"], "Courier-BoldOblique")

    def test_base14_variants_all_combinations(self):
        """Verify get_base14_font_variant across all standard families and styles."""
        self.assertEqual(get_base14_font_variant("helv", False, False), "Helvetica")
        self.assertEqual(get_base14_font_variant("helv", True, False), "Helvetica-Bold")
        self.assertEqual(get_base14_font_variant("helv", False, True), "Helvetica-Oblique")
        self.assertEqual(get_base14_font_variant("helv", True, True), "Helvetica-BoldOblique")

        self.assertEqual(get_base14_font_variant("timr", False, False), "Times-Roman")
        self.assertEqual(get_base14_font_variant("timr", True, False), "Times-Bold")
        self.assertEqual(get_base14_font_variant("timr", False, True), "Times-Italic")
        self.assertEqual(get_base14_font_variant("timr", True, True), "Times-BoldItalic")

        self.assertEqual(get_base14_font_variant("cour", False, False), "Courier")
        self.assertEqual(get_base14_font_variant("cour", True, False), "Courier-Bold")
        self.assertEqual(get_base14_font_variant("cour", False, True), "Courier-Oblique")
        self.assertEqual(get_base14_font_variant("cour", True, True), "Courier-BoldOblique")

    def test_fallback_for_empty_and_unknown_fonts(self):
        """Verify graceful fallback for None or empty font strings."""
        info_none = extract_font_properties(None)
        self.assertEqual(info_none["base14_name"], "Helvetica")
        self.assertFalse(info_none["is_bold"])

        info_empty = extract_font_properties("")
        self.assertEqual(info_empty["base14_name"], "Helvetica")


class TestTextLayoutExtraction(unittest.TestCase):
    """Test suite for raw JSON text extraction and character-level layout data."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.temp_dir.name, "layout_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        page.insert_text((50, 100), "Hello World", fontname="helv", fontsize=12)
        page.insert_text((50, 150), "Bold Heading", fontname="hebo", fontsize=16)
        doc.save(self.pdf_path)
        doc.close()
        self.doc = fitz.open(self.pdf_path)

    def tearDown(self):
        self.doc.close()
        self.temp_dir.cleanup()

    def test_extract_page_text_raw_with_rawjson(self):
        """Verify extract_page_text_raw uses PyMuPDF rawjson format and returns valid structure."""
        data = pdf_handler.extract_page_text_raw(self.doc, 0, use_rawjson=True)
        self.assertIn("blocks", data)
        self.assertIn("width", data)
        self.assertIn("height", data)
        self.assertGreaterEqual(len(data["blocks"]), 1)
        # Check that characters are present in spans
        first_span = data["blocks"][0]["lines"][0]["spans"][0]
        self.assertIn("chars", first_span)
        self.assertIn("font", first_span)
        self.assertIn("origin", first_span)

    def test_extract_page_text_raw_with_rawdict(self):
        """Verify extract_page_text_raw with use_rawjson=False returns rawdict structure."""
        data = pdf_handler.extract_page_text_raw(self.doc, 0, use_rawjson=False)
        self.assertIn("blocks", data)
        self.assertGreaterEqual(len(data["blocks"]), 1)

    def test_extract_page_text_raw_page_instance(self):
        """Verify passing a Page object directly works identically."""
        page = self.doc[0]
        data = pdf_handler.extract_page_text_raw(page, use_rawjson=True)
        self.assertIn("blocks", data)

    def test_extract_page_text_raw_invalid_inputs(self):
        """Verify robust error handling for invalid doc, out of bounds page index, etc."""
        res1 = pdf_handler.extract_page_text_raw(None, 0)
        self.assertEqual(res1["blocks"], [])

        res2 = pdf_handler.extract_page_text_raw(self.doc, 999)
        self.assertEqual(res2["blocks"], [])

    def test_extract_text_spans_with_char_boxes(self):
        """Verify span extraction includes exact character bounding boxes, origins, and fonts."""
        spans = pdf_handler.extract_text_spans_with_char_boxes(self.doc, 0)
        self.assertGreaterEqual(len(spans), 2)

        span1 = spans[0]
        self.assertEqual(span1["text"], "Hello World")
        self.assertEqual(span1["font"], "Helvetica")
        self.assertEqual(span1["font_properties"]["base14_variant"], "Helvetica")
        self.assertAlmostEqual(span1["size"], 12.0, places=1)
        self.assertAlmostEqual(span1["baseline"], 100.0, places=1)

        char_boxes = span1["char_boxes"]
        self.assertEqual(len(char_boxes), 11)  # "Hello World" is 11 chars
        self.assertEqual("".join(cb["char"] for cb in char_boxes), "Hello World")

        # Verify char 0 'H'
        c0 = char_boxes[0]
        self.assertEqual(c0["char"], "H")
        self.assertEqual(c0["index"], 0)
        self.assertAlmostEqual(c0["origin"][0], 50.0, places=1)
        self.assertAlmostEqual(c0["origin"][1], 100.0, places=1)
        self.assertGreater(c0["bbox"][2], c0["bbox"][0])  # width > 0
        self.assertGreater(c0["bbox"][3], c0["bbox"][1])  # height > 0

        # Verify heading span
        span2 = spans[1]
        self.assertEqual(span2["text"], "Bold Heading")
        self.assertEqual(span2["font"], "Helvetica-Bold")
        self.assertTrue(span2["font_properties"]["is_bold"])
        self.assertAlmostEqual(span2["size"], 16.0, places=1)
        self.assertAlmostEqual(span2["baseline"], 150.0, places=1)


class TestTextHitTesting(unittest.TestCase):
    """Test suite for character, word, span, and line hit testing."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.temp_dir.name, "hittest_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        # Line 1: (50, 100) "Hello World"
        page.insert_text((50, 100), "Hello World", fontname="helv", fontsize=12)
        # Line 2: (50, 150) "Testing Part 26 Engine"
        page.insert_text((50, 150), "Testing Part 26 Engine", fontname="tiro", fontsize=14)
        doc.save(self.pdf_path)
        doc.close()
        self.doc = fitz.open(self.pdf_path)

    def tearDown(self):
        self.doc.close()
        self.temp_dir.cleanup()

    def test_hit_test_character_exact(self):
        """Hit test clicking right in the center of character 'H'."""
        spans = pdf_handler.extract_text_spans_with_char_boxes(self.doc, 0)
        c0 = spans[0]["char_boxes"][0]  # 'H'
        mid_x = (c0["bbox"][0] + c0["bbox"][2]) / 2.0
        mid_y = (c0["bbox"][1] + c0["bbox"][3]) / 2.0

        hit = pdf_handler.hit_test_text_char_at_pos(self.doc, (mid_x, mid_y), page_index=0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["char"], "H")
        self.assertEqual(hit["index"], 0)
        self.assertEqual(hit["font"], "Helvetica")
        self.assertAlmostEqual(hit["baseline"], 100.0, places=1)

    def test_hit_test_character_middle_and_end(self):
        """Hit test clicking middle character 'o' and last character 'd'."""
        spans = pdf_handler.extract_text_spans_with_char_boxes(self.doc, 0)
        c_o = spans[0]["char_boxes"][4]  # 'o' in 'Hello'
        mid_x = (c_o["bbox"][0] + c_o["bbox"][2]) / 2.0
        mid_y = (c_o["bbox"][1] + c_o["bbox"][3]) / 2.0

        hit_o = pdf_handler.hit_test_text_char_at_pos(self.doc, (mid_x, mid_y), page_index=0)
        self.assertIsNotNone(hit_o)
        self.assertEqual(hit_o["char"], "o")
        self.assertEqual(hit_o["index"], 4)

        c_d = spans[0]["char_boxes"][10]  # 'd' in 'World'
        mid_x_d = (c_d["bbox"][0] + c_d["bbox"][2]) / 2.0
        mid_y_d = (c_d["bbox"][1] + c_d["bbox"][3]) / 2.0

        hit_d = pdf_handler.hit_test_text_char_at_pos(self.doc, (mid_x_d, mid_y_d), page_index=0)
        self.assertIsNotNone(hit_d)
        self.assertEqual(hit_d["char"], "d")
        self.assertEqual(hit_d["index"], 10)

    def test_hit_test_tolerance(self):
        """Verify clicking slightly outside the bbox (within tolerance) still hits character."""
        spans = pdf_handler.extract_text_spans_with_char_boxes(self.doc, 0)
        c0 = spans[0]["char_boxes"][0]  # 'H'
        # Click 1.5 pt above top boundary
        near_x = (c0["bbox"][0] + c0["bbox"][2]) / 2.0
        near_y = c0["bbox"][1] - 1.5

        hit = pdf_handler.hit_test_text_char_at_pos(self.doc, (near_x, near_y), page_index=0, tolerance=2.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["char"], "H")

    def test_hit_test_miss_outside_tolerance(self):
        """Clicking far outside text returns None."""
        hit = pdf_handler.hit_test_text_char_at_pos(self.doc, (300, 500), page_index=0, tolerance=2.0)
        self.assertIsNone(hit)

    def test_hit_test_word_first_and_second_word(self):
        """Hit test word resolves full word and word bounding box."""
        spans = pdf_handler.extract_text_spans_with_char_boxes(self.doc, 0)
        c1 = spans[0]["char_boxes"][1]  # 'e' in "Hello"
        mid_x1 = (c1["bbox"][0] + c1["bbox"][2]) / 2.0
        mid_y1 = (c1["bbox"][1] + c1["bbox"][3]) / 2.0

        hit_word1 = pdf_handler.hit_test_text_word_at_pos(self.doc, (mid_x1, mid_y1), page_index=0)
        self.assertIsNotNone(hit_word1)
        self.assertEqual(hit_word1["word"], "Hello")
        self.assertEqual(hit_word1["start_char_index"], 0)
        self.assertEqual(hit_word1["end_char_index"], 4)
        self.assertEqual(len(hit_word1["char_boxes"]), 5)

        c2 = spans[0]["char_boxes"][7]  # 'o' in "World"
        mid_x2 = (c2["bbox"][0] + c2["bbox"][2]) / 2.0
        mid_y2 = (c2["bbox"][1] + c2["bbox"][3]) / 2.0

        hit_word2 = pdf_handler.hit_test_text_word_at_pos(self.doc, (mid_x2, mid_y2), page_index=0)
        self.assertIsNotNone(hit_word2)
        self.assertEqual(hit_word2["word"], "World")
        self.assertEqual(hit_word2["start_char_index"], 6)
        self.assertEqual(hit_word2["end_char_index"], 10)

    def test_hit_test_line(self):
        """Hit test line returns complete line text, line bbox, and spans."""
        spans = pdf_handler.extract_text_spans_with_char_boxes(self.doc, 0)
        c = spans[1]["char_boxes"][2]  # 's' in "Testing"
        mid_x = (c["bbox"][0] + c["bbox"][2]) / 2.0
        mid_y = (c["bbox"][1] + c["bbox"][3]) / 2.0

        hit_line = pdf_handler.hit_test_text_line_at_pos(self.doc, (mid_x, mid_y), page_index=0)
        self.assertIsNotNone(hit_line)
        self.assertEqual(hit_line["text"], "Testing Part 26 Engine")
        self.assertAlmostEqual(hit_line["baseline"], 150.0, places=1)
        self.assertEqual(hit_line["primary_font"], "Times-Roman")
        self.assertTrue(hit_line["primary_font_properties"]["is_serif"])

    def test_hit_test_span(self):
        """Hit test span returns span metadata."""
        hit_span = pdf_handler.hit_test_text_span_at_pos(self.doc, (55, 95), page_index=0)
        self.assertIsNotNone(hit_span)
        self.assertEqual(hit_span["text"], "Hello World")
        self.assertEqual(hit_span["font"], "Helvetica")

    def test_get_text_hit_info_at_pos_unified(self):
        """Verify master unified hit info function returns char, word, span, and line."""
        info = pdf_handler.get_text_hit_info_at_pos(self.doc, (52, 98), page_index=0)
        self.assertIsNotNone(info)
        self.assertIn("char", info)
        self.assertIn("word", info)
        self.assertIn("span", info)
        self.assertIn("line", info)
        self.assertEqual(info["char"]["char"], "H")
        self.assertEqual(info["word"]["text"], "Hello")
        self.assertEqual(info["span"]["text"], "Hello World")
        self.assertEqual(info["line"]["text"], "Hello World")
        self.assertEqual(info["page_index"], 0)

    def test_get_word_at_pos_with_tolerance_fallback(self):
        """Verify get_word_at_pos resolves word even with 1.5 pt offset via hit_test_text_word_at_pos fallback."""
        spans = pdf_handler.extract_text_spans_with_char_boxes(self.doc, 0)
        c0 = spans[0]["char_boxes"][0]  # 'H'
        # Offset slightly outside tight fitz words box
        off_x = c0["bbox"][0] - 1.0
        off_y = c0["bbox"][1] - 1.0

        res = pdf_handler.get_word_at_pos(self.doc, 0, (off_x, off_y))
        self.assertIsNotNone(res)
        self.assertEqual(res["text"], "Hello")


class TestRotatedPageHitTesting(unittest.TestCase):
    """Test suite for hit testing on rotated PDF pages (90, 180, 270 degrees)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_90_degree_rotated_page(self):
        """Test hit testing on a 90-degree clockwise rotated page."""
        pdf_path = os.path.join(self.temp_dir.name, "rot90.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((100, 150), "Rotated 90 Deg", fontname="helv", fontsize=12)
        page.set_rotation(90)
        doc.save(pdf_path)
        doc.close()

        doc = fitz.open(pdf_path)
        page = doc[0]
        # Verify page rotation
        self.assertEqual(page.rotation, 90)

        # Unrotated point (100, 150) mapped to visual space via rotation_matrix
        p_unrot = fitz.Point(105, 145)  # Inside 'R'
        p_vis = p_unrot * page.rotation_matrix

        # Hit test using visual coordinates
        hit = pdf_handler.hit_test_text_char_at_pos(doc, (p_vis.x, p_vis.y), page_index=0, visual_coords=True)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["char"], "R")
        self.assertIn("visual_bbox", hit)
        # Visual bbox should be within visual page rect
        v_bbox = hit["visual_bbox"]
        self.assertGreaterEqual(v_bbox[0], 0)
        self.assertLessEqual(v_bbox[2], page.rect.width)

        # Hit test word using visual coordinates
        word_hit = pdf_handler.hit_test_text_word_at_pos(doc, (p_vis.x, p_vis.y), page_index=0, visual_coords=True)
        self.assertIsNotNone(word_hit)
        self.assertEqual(word_hit["word"], "Rotated")

        doc.close()

    def test_180_degree_rotated_page(self):
        """Test hit testing on a 180-degree rotated page."""
        pdf_path = os.path.join(self.temp_dir.name, "rot180.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((100, 150), "Upside Down Text", fontname="helv", fontsize=12)
        page.set_rotation(180)
        doc.save(pdf_path)
        doc.close()

        doc = fitz.open(pdf_path)
        page = doc[0]
        p_unrot = fitz.Point(105, 145)  # Inside 'U'
        p_vis = p_unrot * page.rotation_matrix

        hit = pdf_handler.hit_test_text_char_at_pos(doc, (p_vis.x, p_vis.y), page_index=0, visual_coords=True)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["char"], "U")

        word_hit = pdf_handler.hit_test_text_word_at_pos(doc, (p_vis.x, p_vis.y), page_index=0, visual_coords=True)
        self.assertIsNotNone(word_hit)
        self.assertEqual(word_hit["word"], "Upside")

        doc.close()

    def test_270_degree_rotated_page(self):
        """Test hit testing on a 270-degree rotated page."""
        pdf_path = os.path.join(self.temp_dir.name, "rot270.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((100, 150), "Vertical 270 Text", fontname="helv", fontsize=12)
        page.set_rotation(270)
        doc.save(pdf_path)
        doc.close()

        doc = fitz.open(pdf_path)
        page = doc[0]
        p_unrot = fitz.Point(105, 145)  # Inside 'V'
        p_vis = p_unrot * page.rotation_matrix

        hit = pdf_handler.hit_test_text_char_at_pos(doc, (p_vis.x, p_vis.y), page_index=0, visual_coords=True)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["char"], "V")

        doc.close()


class TestEditableTextIntegration(unittest.TestCase):
    """Test suite for EditableText char_boxes, hit_test_char, and caret indexing."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.temp_dir.name, "editable_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        page.insert_text((50, 100), "Editable Target Text", fontname="helv", fontsize=12)
        doc.save(self.pdf_path)
        doc.close()
        self.doc = fitz.open(self.pdf_path)

    def tearDown(self):
        self.doc.close()
        self.temp_dir.cleanup()

    def test_extract_editable_text_populates_char_boxes_and_font_props(self):
        """Verify extract_editable_text populates char_boxes and font_properties on EditableText models."""
        texts, err = pdf_handler.extract_editable_text(self.doc, 0)
        self.assertIsNone(err)
        self.assertGreaterEqual(len(texts), 1)

        t = texts[0]
        self.assertEqual(t.text, "Editable Target Text")
        self.assertIsNotNone(t.char_boxes)
        self.assertEqual(len(t.char_boxes), len("Editable Target Text"))
        self.assertEqual("".join(cb["char"] for cb in t.char_boxes), "Editable Target Text")

        self.assertIsNotNone(t.font_properties)
        self.assertEqual(t.font_properties["base14_variant"], "Helvetica")
        self.assertAlmostEqual(t.baseline, 100.0, places=1)

    def test_editable_text_hit_test_char(self):
        """Verify EditableText.hit_test_char accurately identifies characters."""
        texts, _ = pdf_handler.extract_editable_text(self.doc, 0)
        t = texts[0]

        # First char 'E'
        c0 = t.char_boxes[0]
        mid_x = (c0["bbox"][0] + c0["bbox"][2]) / 2.0
        mid_y = (c0["bbox"][1] + c0["bbox"][3]) / 2.0

        hit = t.hit_test_char(mid_x, mid_y)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["char"], "E")
        self.assertEqual(hit["index"], 0)

        # 9th char 'T' in "Target"
        c9 = t.char_boxes[9]
        mid_x9 = (c9["bbox"][0] + c9["bbox"][2]) / 2.0
        mid_y9 = (c9["bbox"][1] + c9["bbox"][3]) / 2.0

        hit9 = t.hit_test_char(mid_x9, mid_y9)
        self.assertIsNotNone(hit9)
        self.assertEqual(hit9["char"], "T")
        self.assertEqual(hit9["index"], 9)

    def test_editable_text_get_caret_index_at_pos(self):
        """Verify EditableText.get_caret_index_at_pos computes exact text cursor insertion index."""
        texts, _ = pdf_handler.extract_editable_text(self.doc, 0)
        t = texts[0]

        # Far left of first char -> index 0
        self.assertEqual(t.get_caret_index_at_pos(t.char_boxes[0]["bbox"][0] - 10), 0)

        # Far right of last char -> index len(text)
        self.assertEqual(t.get_caret_index_at_pos(t.char_boxes[-1]["bbox"][2] + 10), len(t.text))

        # Right before first char
        self.assertEqual(t.get_caret_index_at_pos(t.char_boxes[0]["bbox"][0]), 0)

        # Middle of first char -> index 0 or 1
        mid_c0 = (t.char_boxes[0]["bbox"][0] + t.char_boxes[0]["bbox"][2]) / 2.0
        idx = t.get_caret_index_at_pos(mid_c0)
        self.assertIn(idx, (0, 1))

        # Right edge of first char -> index 1
        self.assertEqual(t.get_caret_index_at_pos(t.char_boxes[0]["bbox"][2]), 1)


if __name__ == "__main__":
    unittest.main()
