"""Consolidated Object Manipulation, Dragging, Hit Testing, and Transform Handles Test Suite for word-sys-pdf-editor.

This suite validates text hit testing, textbox movement and undo, two-stage selection
and moving lifecycle, rotation stalk handles, and proportional corner transform resizing.
"""

# ============================================================================
# SECTION: test_text_hit_testing.py
# ============================================================================
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

    def test_extract_editable_text_rawdict_equivalence(self):
        """Verify extract_editable_text yields identical EditableText properties between rawdict and rawjson."""
        test_doc = fitz.open()
        page = test_doc.new_page(width=600, height=800)
        page.insert_text((50, 100), "Plain text sample", fontname="helv", fontsize=12)
        page.insert_text((50, 200), "Multi-font Times Roman", fontname="tiro", fontsize=14)
        page.insert_text((50, 300), "Courier Monospace", fontname="cour", fontsize=11)
        page.insert_text((50, 400), "Rotated text run", fontname="helv", fontsize=13, rotate=90)
        page.insert_text((50, 500), "Underlined text run", fontname="helv", fontsize=12)
        rect = fitz.Rect(50, 502, 180, 503)
        page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0))

        # 1. Extraction with primary rawdict path
        texts_rawdict, err1 = pdf_handler.extract_editable_text(test_doc, 0)
        self.assertIsNone(err1)
        self.assertGreaterEqual(len(texts_rawdict), 4)

        # 2. Extraction forced via rawjson path by monkeypatching get_text
        orig_get_text = fitz.Page.get_text
        def force_rawjson_get_text(p_self, opt, *args, **kwargs):
            if opt == "rawdict":
                raise RuntimeError("Force fallback to rawjson")
            return orig_get_text(p_self, opt, *args, **kwargs)

        try:
            fitz.Page.get_text = force_rawjson_get_text
            texts_rawjson, err2 = pdf_handler.extract_editable_text(test_doc, 0)
            self.assertIsNone(err2)
        finally:
            fitz.Page.get_text = orig_get_text

        self.assertEqual(len(texts_rawdict), len(texts_rawjson))
        for a, b in zip(texts_rawdict, texts_rawjson):
            self.assertEqual(a.text, b.text)
            self.assertEqual(a.bbox, b.bbox)
            self.assertAlmostEqual(a.baseline, b.baseline, places=2)
            self.assertAlmostEqual(a.rotation, b.rotation, places=2)
            self.assertEqual(a.font_size, b.font_size)
            self.assertEqual(a.font_properties, b.font_properties)
            self.assertEqual(a.is_underline, b.is_underline)
            self.assertEqual(len(a.char_boxes), len(b.char_boxes))
            for ca, cb in zip(a.char_boxes, b.char_boxes):
                self.assertEqual(ca["char"], cb["char"])
                self.assertEqual(ca["bbox"], cb["bbox"])
                self.assertEqual(ca["origin"], cb["origin"])
        test_doc.close()

    def test_extract_editable_text_performance_guard(self):
        """Timing guard: verify fast text extraction completes in under 250 ms for a 40-line page."""
        test_doc = fitz.open()
        page = test_doc.new_page(width=600, height=800)
        for i in range(40):
            page.insert_text((50, 40 + i * 18), f"Line {i}: Testing performance speedup with PyMuPDF rawdict extraction.", fontsize=11)

        import time
        t0 = time.perf_counter()
        texts, err = pdf_handler.extract_editable_text(test_doc, 0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertIsNone(err)
        self.assertGreaterEqual(len(texts), 35)
        self.assertLess(elapsed_ms, 250.0, f"extract_editable_text took {elapsed_ms:.1f} ms, expected < 250 ms")
        test_doc.close()


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


# ============================================================================
# SECTION: test_textbox_undo_and_object_drag.py
# ============================================================================
"""Tests for textbox undo/redo isolation and object dragging in select mode."""

import unittest
from unittest.mock import MagicMock, patch
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk

import fitz
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.models import EditableText, EditableShape, EditableImage, EditableStroke, SpatialGridIndex, AcroFormField
from word_sys_pdf_editor.undo_manager import UndoManager, EditObjectCommand


class DummyWindow:
    """Mock window for testing undo routing and dragging behavior."""
    def __init__(self):
        self.doc = [MagicMock()]
        self.current_page_index = 0
        self.current_pdf_page_width = 600.0
        self.current_pdf_page_height = 800.0
        self.zoom_level = 1.0
        self.tool_mode = "select"
        self.view_mode = False
        self.inline_editor_widget = None
        self.inline_editor_tv = None
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None
        self.selected_redaction_mark = None
        self.editable_texts = []
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.form_fields = []
        self._active_session = None
        self._spatial_indices = {}
        self.undo_manager = MagicMock()
        self.pdf_view = MagicMock()
        self.status_label = MagicMock()
        self.dragged_object = None
        self._can_drag_object = None
        self.dragging_to_create = False
        self.drag_start_pos = (0, 0)
        self.drag_object_start_pos = (0, 0)
        self.drag_begin_state = {}
        self.resize_handle = None
        self._focus_widget = None
        self.continuous_scroll = False
        self.temp_shape = None
        self.temp_stroke = None
        self.temp_image_bbox = None
        self.temp_stamp_bbox = None
        self.temp_sig_bbox = None
        self.temp_clone_patch_bbox = None
        self.temp_redact_bbox = None
        self.temp_form_field_rect = None
        self.temp_calibration_line = None
        self.temp_measurement_line = None
        self.temp_measurement_rect = None
        self.temp_polygon_vertices = []
        self.selected_word_start_char = None
        self.selected_word_end_char = None
        self.word_selection_mode = False
        self.show_ocr_overlay = False

    def get_focus(self):
        return self._focus_widget

    def get_page_canvas_rect(self, page_index):
        return (0, 0, 600, 800)

    def canvas_to_page_coords(self, x, y):
        return self.current_page_index, x / self.zoom_level, y / self.zoom_level

    def is_canvas_point_on_page(self, x, y, target_page):
        return True

    def _visual_to_unrotated_delta(self, dx, dy):
        return dx, dy

    def _visual_to_unrotated_page_coords(self, px, py, page_index=None):
        return px, py

    _on_undo_activated = PdfEditorWindow._on_undo_activated
    _on_redo_activated = PdfEditorWindow._on_redo_activated
    _on_inline_editor_key = PdfEditorWindow._on_inline_editor_key
    _invalidate_spatial_index = PdfEditorWindow._invalidate_spatial_index
    _get_page_spatial_index = PdfEditorWindow._get_page_spatial_index
    _find_text_at_pos = PdfEditorWindow._find_text_at_pos
    _find_image_at_pos = PdfEditorWindow._find_image_at_pos
    _find_shape_at_pos = PdfEditorWindow._find_shape_at_pos
    _find_stroke_at_pos = PdfEditorWindow._find_stroke_at_pos
    _find_form_field_at_pos = PdfEditorWindow._find_form_field_at_pos
    _find_measurement_at_pos = PdfEditorWindow._find_measurement_at_pos
    _find_resize_handle_at_pos = PdfEditorWindow._find_resize_handle_at_pos
    commit_pending_format_change = MagicMock()
    _close_active_form_field_editor = MagicMock()
    _update_ui_state = MagicMock()
    _update_text_format_controls = MagicMock()
    _update_stroke_format_controls = MagicMock()
    _apply_inline_editor_style = MagicMock()

    on_drag_begin = PdfEditorWindow.on_drag_begin
    on_drag_update = PdfEditorWindow.on_drag_update
    on_drag_end = PdfEditorWindow.on_drag_end
    get_selected_object = PdfEditorWindow.get_selected_object
    select_object = PdfEditorWindow.select_object
    deselect_all = PdfEditorWindow.deselect_all
    _find_any_object_at_pos = PdfEditorWindow._find_any_object_at_pos
    on_tool_selected = PdfEditorWindow.on_tool_selected
    _draw_page_content = PdfEditorWindow._draw_page_content


class TestTextboxUndoAndObjectDrag(unittest.TestCase):
    """Test suite for textbox undo/redo isolation and object dragging in select mode."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        self.win = DummyWindow()
        self.win.doc = self.doc

    def tearDown(self):
        if hasattr(self, 'doc') and self.doc:
            self.doc.close()

    def test_inline_editor_key_ctrl_z_undoes_text_buffer(self):
        """Ctrl+Z inside inline editor undoes local text buffer without touching global undo manager."""
        tv = Gtk.TextView()
        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text("Initial")
        buf.set_enable_undo(True)

        # Type additional text
        buf.insert_at_cursor(" edits")
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Initial edits")

        self.win.inline_editor_tv = tv
        self.win.inline_editor_widget = MagicMock()

        # Simulate Ctrl+Z key press event
        handled = self.win._on_inline_editor_key(None, Gdk.KEY_z, 0, Gdk.ModifierType.CONTROL_MASK)
        self.assertTrue(handled)
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Initial")
        self.win.undo_manager.undo.assert_not_called()

    def test_inline_editor_key_ctrl_y_redoes_text_buffer(self):
        """Ctrl+Y inside inline editor redoes local text buffer without touching global undo manager."""
        tv = Gtk.TextView()
        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text("Start")
        buf.set_enable_undo(True)

        buf.insert_at_cursor(" Next")
        buf.undo()
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Start")

        self.win.inline_editor_tv = tv
        self.win.inline_editor_widget = MagicMock()

        # Simulate Ctrl+Y
        handled = self.win._on_inline_editor_key(None, Gdk.KEY_y, 0, Gdk.ModifierType.CONTROL_MASK)
        self.assertTrue(handled)
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Start Next")
        self.win.undo_manager.redo.assert_not_called()

    def test_action_undo_routes_to_inline_editor_when_active(self):
        """Global undo action routes to inline editor when it is open."""
        tv = Gtk.TextView()
        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text("Alpha")
        buf.set_enable_undo(True)
        buf.insert_at_cursor(" Beta")

        self.win.inline_editor_tv = tv
        self.win.inline_editor_widget = MagicMock()

        self.win._on_undo_activated()
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Alpha")
        self.win.undo_manager.undo.assert_not_called()

    def test_action_undo_routes_to_focused_textview(self):
        """Global undo action routes to any focused Gtk.TextView (e.g. sticky notes)."""
        tv = Gtk.TextView()
        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text("Note text")
        buf.set_enable_undo(True)
        buf.insert_at_cursor(" updated")

        self.win._focus_widget = tv
        self.win._on_undo_activated()

        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Note text")
        self.win.undo_manager.undo.assert_not_called()

    def test_action_undo_delegates_to_document_undo_when_idle(self):
        """Global undo action calls document undo manager when no text field is active."""
        self.win._focus_widget = None
        self.win.inline_editor_tv = None
        self.win.inline_editor_widget = None

        self.win._on_undo_activated()
        self.win.undo_manager.undo.assert_called_once()

    def test_action_redo_delegates_to_document_redo_when_idle(self):
        """Global redo action calls document redo manager when no text field is active."""
        self.win._focus_widget = None
        self.win.inline_editor_tv = None
        self.win.inline_editor_widget = None

        self.win._on_redo_activated()
        self.win.undo_manager.redo.assert_called_once()

    def test_object_drag_and_move_in_select_mode(self):
        """Objects can be dragged and moved in 'select' tool mode."""
        text_obj = EditableText(100.0, 100.0, "Movable Text", font_size=12.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)
        self.win.tool_mode = "select"
        self.win.selected_text = text_obj

        gesture = MagicMock()
        # Drag start at (120, 110) inside the text bbox
        self.win.on_drag_begin(gesture, 120.0, 110.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, text_obj)
        self.assertEqual(self.win.selected_text, text_obj)

        # Drag update by delta (+50, +30)
        self.win.on_drag_update(gesture, 50.0, 30.0)
        self.assertEqual(text_obj.x, 150.0)
        self.assertEqual(text_obj.y, 130.0)
        self.assertEqual(text_obj.bbox, (150.0, 130.0, 250.0, 150.0))

        # Drag end commits move
        self.win.on_drag_end(gesture, 50.0, 30.0)
        self.win.undo_manager.add_command.assert_called_once()
        self.assertIsNone(self.win.dragged_object)

    def test_drag_deadspace_threshold_cancels_accidental_movement(self):
        """Mouse movement within deadspace threshold (< 5px) does not move object or record undo."""
        text_obj = EditableText(200.0, 200.0, "Stable Text", font_size=12.0)
        text_obj.bbox = (200.0, 200.0, 300.0, 220.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)
        self.win.tool_mode = "select"
        self.win.selected_text = text_obj

        gesture = MagicMock()
        # Mouse press initiates drag
        self.win.on_drag_begin(gesture, 210.0, 210.0)
        self.assertEqual(self.win.dragged_object, text_obj)
        self.assertFalse(self.win.drag_threshold_passed)

        # Micro-jitter of 2px (e.g. while double clicking)
        self.win.on_drag_update(gesture, 2.0, 1.0)
        # Position must NOT change
        self.assertEqual(text_obj.x, 200.0)
        self.assertEqual(text_obj.y, 200.0)
        self.assertFalse(self.win.drag_threshold_passed)

        # Mouse release without passing threshold
        self.win.on_drag_end(gesture, 2.0, 1.0)
        self.win.undo_manager.add_command.assert_not_called()
        self.assertIsNone(self.win.dragged_object)
        self.assertEqual(text_obj.x, 200.0)
        self.assertEqual(text_obj.y, 200.0)

    def test_movement_tool_alias_to_select(self):
        """Selecting redundant 'drag' tool mode aliases cleanly to 'select'."""
        self.win.tool_mode = "pen"
        self.win.on_tool_selected(None, "drag")
        self.assertEqual(self.win.tool_mode, "select")

    def test_inline_editor_tv_wrap_mode_none(self):
        """Inline text editor creates text view with WrapMode.NONE so text does not prematurely wrap."""
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.NONE)
        self.assertEqual(tv.get_wrap_mode(), Gtk.WrapMode.NONE)

    def test_dragged_rotated_object_applies_rotation_to_shadow_box(self):
        """When dragged object is rotated, both origin shadow box and destination box rotate."""
        import math
        text_obj = EditableText(100.0, 100.0, "Rotated Text", font_size=12.0, rotation=45.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.original_bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.original_rotation = 0.0  # Even if stale 0.0, rotation must be dynamic!
        text_obj.page_number = 0

        self.win.dragged_object = text_obj
        cr = MagicMock()
        cr.clip_extents.return_value = (-1000.0, -1000.0, 2000.0, 2000.0)
        area = MagicMock()

        with patch('word_sys_pdf_editor.window.PangoCairo.create_layout') as mock_layout, \
             patch('word_sys_pdf_editor.window.PangoCairo.show_layout'):
            layout_obj = MagicMock()
            layout_obj.get_size.return_value = (100 * 1024, 20 * 1024)
            mock_layout.return_value = layout_obj

            # Render canvas page
            PdfEditorWindow.draw_pdf_page(self.win, area, cr, 600, 800, dirty_rect=None)
            expected_rad = math.radians(45.0)
            rotate_calls = [call.args[0] for call in cr.rotate.call_args_list]
            self.assertTrue(any(abs(rad - expected_rad) < 1e-4 for rad in rotate_calls))
            # Verify destination blue box was drawn
            source_rgba_calls = [call.args for call in cr.set_source_rgba.call_args_list]
            self.assertIn((0.2, 0.5, 0.85, 0.12), source_rgba_calls)

    def test_all_objects_render_destination_drag_area_box(self):
        """All object types (Shape, Image, FormField, Stroke) render the blue destination drag area box."""
        # 1. EditableShape
        shape_obj = EditableShape(
            shape_type=EditableShape.SHAPE_RECTANGLE,
            bbox=(50.0, 50.0, 150.0, 150.0),
            page_number=0,
            rotation=30.0
        )
        shape_obj.original_bbox = (50.0, 50.0, 150.0, 150.0)
        self.win.dragged_object = shape_obj
        cr = MagicMock()
        cr.clip_extents.return_value = (-1000.0, -1000.0, 2000.0, 2000.0)
        PdfEditorWindow.draw_pdf_page(self.win, MagicMock(), cr, 600, 800, dirty_rect=None)
        source_rgba_calls = [call.args for call in cr.set_source_rgba.call_args_list]
        self.assertIn((0.2, 0.5, 0.85, 0.12), source_rgba_calls)
        self.assertIn((0.2, 0.5, 0.85, 0.6), source_rgba_calls)

        # 2. AcroFormField
        form_field = AcroFormField(
            field_id="field1",
            xref=10,
            page_number=0,
            rect=(100.0, 100.0, 200.0, 130.0),
            field_name="test_field"
        )
        form_field.original_bbox = form_field.bbox
        self.win.dragged_object = form_field
        cr = MagicMock()
        cr.clip_extents.return_value = (-1000.0, -1000.0, 2000.0, 2000.0)
        PdfEditorWindow.draw_pdf_page(self.win, MagicMock(), cr, 600, 800, dirty_rect=None)
        source_rgba_calls = [call.args for call in cr.set_source_rgba.call_args_list]
        self.assertIn((0.2, 0.5, 0.85, 0.12), source_rgba_calls)

    def test_stalk_handle_rotation_origin_and_destination_dynamic(self):
        """Free rotation via stalk handle dynamically updates object rotation and renders rotated boxes."""
        import math
        shape_obj = EditableShape(
            shape_type=EditableShape.SHAPE_RECTANGLE,
            bbox=(100.0, 100.0, 200.0, 200.0),
            page_number=0,
            rotation=0.0
        )
        self.win.selected_shape = shape_obj
        self.win.dragged_object = shape_obj
        shape_obj.original_bbox = shape_obj.bbox
        self.win.drag_start_pos = (150.0, 80.0)
        self.win.rotate_center = (150.0, 150.0)
        self.win.rotate_pointer_start_angle = -90.0
        self.win.rotate_start_angle = 0.0

        gesture_mock = MagicMock()
        gesture_mock.get_current_event_state.return_value = 0

        # Rotate by dragging pointer to the right (+90 degrees offset -> angle 0 deg -> delta +90 deg)
        PdfEditorWindow._handle_rotate_update(self.win, gesture_mock, offset_x=70.0, offset_y=70.0)
        self.assertAlmostEqual(shape_obj.rotation, 90.0, places=1)

        # Calling draw_pdf_page should rotate cr by 90 degrees
        cr = MagicMock()
        cr.clip_extents.return_value = (-1000.0, -1000.0, 2000.0, 2000.0)
        PdfEditorWindow.draw_pdf_page(self.win, MagicMock(), cr, 600, 800, dirty_rect=None)
        expected_rad = math.radians(90.0)
        rotate_calls = [call.args[0] for call in cr.rotate.call_args_list]
        self.assertTrue(any(abs(rad - expected_rad) < 1e-4 for rad in rotate_calls))

    def test_spatial_index_self_healing_on_stale_data(self):
        """When spatial index has stale entries, hit testing self-heals via linear scan."""
        shape_obj = EditableShape(
            shape_type=EditableShape.SHAPE_RECTANGLE,
            bbox=(300.0, 300.0, 400.0, 400.0),
            page_number=0
        )
        self.win.editable_shapes.append(shape_obj)

        # Set up an outdated spatial grid where the object was somewhere else
        grid = SpatialGridIndex(cell_size=100.0)
        grid.insert(shape_obj, bbox=(10.0, 10.0, 50.0, 50.0))
        self.win._spatial_indices = {(0, "shape"): grid}

        # Query at current position (350, 350)
        hit = self.win._find_shape_at_pos(350.0, 350.0)
        self.assertEqual(hit, shape_obj)
        # Verify stale index was invalidated
        self.assertNotIn((0, "shape"), self.win._spatial_indices)

    def test_undo_manager_invalidates_spatial_index(self):
        """UndoManager operations invalidate spatial cache on the window."""
        win_mock = MagicMock()
        win_mock.doc = [MagicMock()]
        um = UndoManager(win_mock)

        cmd = MagicMock(target_object=None, commands=[], page_index=0)
        um.add_command(cmd)
        win_mock._invalidate_spatial_index.assert_called()

        win_mock._invalidate_spatial_index.reset_mock()
        um.undo()
        win_mock._invalidate_spatial_index.assert_called()

        win_mock._invalidate_spatial_index.reset_mock()
        um.redo()
        win_mock._invalidate_spatial_index.assert_called()

    def test_single_page_margin_only_clearing_uses_even_odd(self):
        """Verify draw_pdf_page in single page mode clears margins with EVEN_ODD instead of blanking under the page."""
        import cairo
        self.win.dragged_object = None
        self.win.continuous_scroll = False
        self.win.current_pdf_page_width = 400.0
        self.win.current_pdf_page_height = 600.0

        cr = MagicMock()
        cr.clip_extents.return_value = (-1000.0, -1000.0, 2000.0, 2000.0)
        with patch.object(self.win, '_draw_page_content'):
            PdfEditorWindow.draw_pdf_page(self.win, MagicMock(), cr, 800, 1000, dirty_rect=None)
            cr.set_fill_rule.assert_called_with(cairo.FILL_RULE_EVEN_ODD)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_object_selection_and_moving_lifecycle.py
# ============================================================================
import unittest
import os
import copy
from unittest.mock import MagicMock

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk

from word_sys_pdf_editor.models import (
    EditableText, EditableImage, EditableShape, EditableStroke, AcroFormField
)
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.i18n import set_setting


class TestObjectSelectionAndMovingLifecycle(unittest.TestCase):
    """Test suite verifying that moving is only enabled when an object is already selected.

    First click always selects the object without moving it;
    second click and hold enables movement.
    """

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Adw.Application(application_id='org.word_sys.test_selection_move_lifecycle')
        except Exception:
            cls.app = None

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)

        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.set_continuous_scroll_mode(False)
        self.win.doc = self.doc
        self.win.current_page_index = 0
        self.win.current_pdf_page_width = 600
        self.win.current_pdf_page_height = 800
        self.win.zoom_level = 1.0
        self.win.view_mode = False
        self.win.tool_mode = "select"
        self.win.undo_manager = MagicMock()

    def tearDown(self):
        set_setting("view_mode", "single")
        if hasattr(self, 'win') and self.win:
            try:
                self.win.close_document()
                self.win.destroy()
            except Exception:
                pass
        doc = getattr(self, 'doc', None)
        if doc is not None and not getattr(doc, 'is_closed', True):
            try:
                doc.close()
            except Exception:
                pass

    def test_first_click_selects_text_without_moving_second_click_moves(self):
        """First click selects text without moving; second click and hold moves it."""
        text_obj = EditableText(100.0, 100.0, "Sample Text", font_size=12.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)

        gesture = MagicMock()

        # 1. First click: mouse press over text object
        self.win.on_pdf_view_pressed(gesture, 1, 120.0, 110.0)
        self.assertEqual(self.win.selected_text, text_obj)
        self.assertFalse(self.win._can_drag_object)

        # First drag begin attempt during first click
        self.win.on_drag_begin(gesture, 120.0, 110.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

        # Attempt to drag during first click
        self.win.on_drag_update(gesture, 60.0, 40.0)
        self.assertEqual(text_obj.x, 100.0)
        self.assertEqual(text_obj.y, 100.0)

        # Release first click
        self.win.on_drag_end(gesture, 60.0, 40.0)
        self.win._on_pdf_view_released(gesture, 1, 120.0, 110.0)
        self.win.undo_manager.add_command.assert_not_called()
        self.assertEqual(self.win.selected_text, text_obj)
        self.assertEqual(text_obj.x, 100.0)
        self.assertEqual(text_obj.y, 100.0)

        # 2. Second click and hold on the now-selected text object
        gesture.reset_mock()
        self.win.on_pdf_view_pressed(gesture, 1, 120.0, 110.0)
        self.assertTrue(self.win._can_drag_object)

        self.win.on_drag_begin(gesture, 120.0, 110.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, text_obj)

        # Drag update moves the object
        self.win.on_drag_update(gesture, 50.0, 30.0)
        self.assertEqual(text_obj.x, 150.0)
        self.assertEqual(text_obj.y, 130.0)

        # Release commits the move
        self.win.on_drag_end(gesture, 50.0, 30.0)
        self.win.undo_manager.add_command.assert_called_once()
        self.assertIsNone(self.win.dragged_object)

    def test_first_click_selects_image_without_moving_second_click_moves(self):
        """First click selects image without moving; second click and hold moves it."""
        image_obj = EditableImage(
            bbox=(200.0, 200.0, 300.0, 300.0),
            xref=1,
            page_number=0,
            image_bytes=b"dummy_data"
        )
        self.win.editable_images.append(image_obj)

        gesture = MagicMock()

        # First click: selects image
        self.win.on_pdf_view_pressed(gesture, 1, 250.0, 250.0)
        self.assertEqual(self.win.selected_image, image_obj)

        self.win.on_drag_begin(gesture, 250.0, 250.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

        self.win.on_drag_update(gesture, 40.0, 40.0)
        self.assertEqual(image_obj.bbox, (200.0, 200.0, 300.0, 300.0))

        self.win.on_drag_end(gesture, 40.0, 40.0)
        self.win._on_pdf_view_released(gesture, 1, 250.0, 250.0)

        # Second click and hold: moves image
        gesture.reset_mock()
        self.win.on_pdf_view_pressed(gesture, 1, 250.0, 250.0)
        self.win.on_drag_begin(gesture, 250.0, 250.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, image_obj)

        self.win.on_drag_update(gesture, 30.0, 20.0)
        self.assertEqual(image_obj.bbox, (230.0, 220.0, 330.0, 320.0))

        self.win.on_drag_end(gesture, 30.0, 20.0)
        self.win.undo_manager.add_command.assert_called_once()

    def test_first_click_selects_shape_without_moving_second_click_moves(self):
        """First click selects shape without moving; second click and hold moves it."""
        shape_obj = EditableShape(
            shape_type=EditableShape.SHAPE_RECTANGLE,
            bbox=(50.0, 50.0, 150.0, 150.0),
            page_number=0
        )
        self.win.editable_shapes.append(shape_obj)

        gesture = MagicMock()

        # First click
        self.win.on_pdf_view_pressed(gesture, 1, 100.0, 100.0)
        self.assertEqual(self.win.selected_shape, shape_obj)

        self.win.on_drag_begin(gesture, 100.0, 100.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

        self.win.on_drag_update(gesture, 30.0, 30.0)
        self.assertEqual(shape_obj.bbox, (50.0, 50.0, 150.0, 150.0))

        self.win.on_drag_end(gesture, 30.0, 30.0)
        self.win._on_pdf_view_released(gesture, 1, 100.0, 100.0)

        # Second click and hold
        gesture.reset_mock()
        self.win.on_pdf_view_pressed(gesture, 1, 100.0, 100.0)
        self.win.on_drag_begin(gesture, 100.0, 100.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, shape_obj)

        self.win.on_drag_update(gesture, 40.0, 50.0)
        self.assertEqual(shape_obj.bbox, (90.0, 100.0, 190.0, 200.0))
        self.win.on_drag_end(gesture, 40.0, 50.0)
        self.win.undo_manager.add_command.assert_called_once()

    def test_click_different_object_switches_selection_without_moving(self):
        """Clicking a different object selects it and does not move either object."""
        text_a = EditableText(50.0, 50.0, "Text A", font_size=12.0)
        text_a.bbox = (50.0, 50.0, 120.0, 70.0)
        text_a.page_number = 0
        self.win.editable_texts.append(text_a)

        text_b = EditableText(250.0, 250.0, "Text B", font_size=12.0)
        text_b.bbox = (250.0, 250.0, 320.0, 270.0)
        text_b.page_number = 0
        self.win.editable_texts.append(text_b)

        # Select Text A
        self.win.select_object(text_a)
        self.assertEqual(self.win.selected_text, text_a)

        gesture = MagicMock()

        # Click on Text B
        self.win.on_pdf_view_pressed(gesture, 1, 260.0, 260.0)
        self.assertEqual(self.win.selected_text, text_b)

        # Movement must be denied on first click of Text B
        self.win.on_drag_begin(gesture, 260.0, 260.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

        # Drag update does not move Text B
        self.win.on_drag_update(gesture, 50.0, 50.0)
        self.assertEqual(text_b.x, 250.0)
        self.assertEqual(text_b.y, 250.0)

        self.win.on_drag_end(gesture, 50.0, 50.0)
        self.win._on_pdf_view_released(gesture, 1, 260.0, 260.0)

        # Second click on Text B enables move
        gesture.reset_mock()
        self.win.on_pdf_view_pressed(gesture, 1, 260.0, 260.0)
        self.win.on_drag_begin(gesture, 260.0, 260.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, text_b)

    def test_click_empty_canvas_deselects_and_denies_movement(self):
        """Clicking empty space clears selection and prevents dragging."""
        text_obj = EditableText(100.0, 100.0, "Selected Text", font_size=12.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)
        self.win.select_object(text_obj)

        gesture = MagicMock()
        # Click on empty area (400, 400)
        self.win.on_pdf_view_pressed(gesture, 1, 400.0, 400.0)
        self.assertIsNone(self.win.selected_text)
        self.assertIsNone(self.win.get_selected_object())

        self.win.on_drag_begin(gesture, 400.0, 400.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

    def test_direct_on_drag_begin_on_unselected_object_selects_first_then_moves(self):
        """Direct call to on_drag_begin on unselected object selects on call 1 and moves on call 2."""
        text_obj = EditableText(100.0, 100.0, "Direct Drag Text", font_size=12.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)

        gesture = MagicMock()

        # Call 1: unselected -> selects without dragging
        self.win.on_drag_begin(gesture, 120.0, 110.0)
        self.assertEqual(self.win.selected_text, text_obj)
        self.assertIsNone(self.win.dragged_object)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)

        # Call 2: now selected -> enables movement
        gesture.reset_mock()
        self.win._on_pdf_view_released(gesture, 1, 120.0, 110.0)
        self.win.on_drag_begin(gesture, 120.0, 110.0)
        self.assertEqual(self.win.dragged_object, text_obj)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)


# ============================================================================
# SECTION: test_text_rotation_and_close_edit_bug.py
# ============================================================================
"""
Test reproducing and verifying fix for:
1. Text rotation duplicating other texts when rotated across/on top of them.
2. Editing text close to another text duplicating the nearby text (burn mark).
3. Ensuring 100% object independence for all text edits and rotations.
"""

import unittest
from unittest.mock import MagicMock
import fitz
import copy

from word_sys_pdf_editor.models import EditableText
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor import undo_manager


class MockWindow:
    def __init__(self, doc):
        self.doc = doc
        self.editable_texts = []
        self.editable_shapes = []
        self.editable_images = []
        self.editable_strokes = []
        self.selected_text = None
        self.pending_format_change_obj = None
        self.before_format_change_state = None
        self.document_modified = False
        self.status_label = MagicMock()
        self.undo_manager = undo_manager.UndoManager(self)
        self.pdf_view = self
        self.current_page_index = 0

    def _update_undo_redo_buttons(self): pass
    def _update_text_format_controls(self, obj): pass
    def _update_rotation_controls(self, obj): pass
    def _update_ui_state(self): pass
    def _refresh_thumbnail(self, p): pass
    def queue_draw(self): pass


class TestTextRotationAndIndependence(unittest.TestCase):
    def setUp(self):
        # Create a document with two text lines close to each other
        self.doc, _ = pdf_handler.create_new_pdf(width=500, height=500, num_pages=1)
        page = self.doc.load_page(0)
        # Line 0: Paragraph line at y=100
        page.insert_text(fitz.Point(50, 100), "Line Zero Paragraph Text", fontsize=11)
        # Line 1: URL / report line at y=115 (close to Line 0)
        page.insert_text(fitz.Point(50, 115), "Line One Report URL Text", fontsize=11)

        # Save snapshot of page 0
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)

        self.win = MockWindow(self.doc)

        # Create EditableText representations as extracted
        self.t0 = EditableText(50, 90, "Line Zero Paragraph Text", font_size=11, is_new=False, baseline=100, page_number=0)
        self.t0.bbox = (50, 89, 200, 103)
        self.t0.original_bbox = self.t0.bbox
        self.t0.original_baseline = self.t0.baseline
        self.t0.original_rotation = 0.0

        self.t1 = EditableText(50, 105, "Line One Report URL Text", font_size=11, is_new=False, baseline=115, page_number=0)
        self.t1.bbox = (50, 104, 200, 118)
        self.t1.original_bbox = self.t1.bbox
        self.t1.original_baseline = self.t1.baseline
        self.t1.original_rotation = 0.0

        self.win.editable_texts = [self.t0, self.t1]

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_rotating_text_does_not_affect_or_duplicate_other_texts(self):
        """Rotating text across another line must NOT mark the other line as _ghost_redacted or duplicate it."""
        cmd = undo_manager.RotateObjectCommand(self.win, self.t1, 0.0, 315.0)
        cmd.execute()

        # CRITICAL ASSERTION: t0 must NOT be marked _ghost_redacted!
        self.assertFalse(
            getattr(self.t0, '_ghost_redacted', False),
            "Line Zero was wrongly marked _ghost_redacted when rotating Line One!"
        )

        page = self.doc.load_page(0)
        page_text = page.get_text()

        count_t0 = page_text.count("Line Zero Paragraph Text")
        self.assertEqual(
            count_t0, 1,
            f"Line Zero was duplicated! Found {count_t0} occurrences instead of 1."
        )

    def test_editing_close_text_does_not_affect_or_duplicate_other_texts(self):
        """Editing text close to another text must NOT mark the other text as _ghost_redacted or duplicate it."""
        old_props = {'text': self.t1.text, 'bbox': self.t1.bbox, 'baseline': self.t1.baseline}
        new_props = {'text': "Edited Line One", 'bbox': self.t1.bbox, 'baseline': self.t1.baseline}

        cmd = undo_manager.EditObjectCommand(self.win, self.t1, old_props, new_props)
        cmd.execute()

        # CRITICAL ASSERTION: t0 must NOT be marked _ghost_redacted!
        self.assertFalse(
            getattr(self.t0, '_ghost_redacted', False),
            "Line Zero was wrongly marked _ghost_redacted when editing adjacent Line One!"
        )

        page = self.doc.load_page(0)
        page_text = page.get_text()

        count_t0 = page_text.count("Line Zero Paragraph Text")
        self.assertEqual(
            count_t0, 1,
            f"Line Zero was duplicated! Found {count_t0} occurrences instead of 1."
        )

    def test_original_text_erased_at_original_rotation_not_new_rotation(self):
        """Ghost erasure must erase the original text at its original rotation (0.0), not at the new angle."""
        cmd = undo_manager.RotateObjectCommand(self.win, self.t1, 0.0, 45.0)
        cmd.execute()

        page = self.doc.load_page(0)
        page_text = page.get_text()
        count_t1 = page_text.count("Line One Report URL Text")
        self.assertEqual(count_t1, 1, f"Found {count_t1} instances of Line One text")

    def test_sequential_rotations_and_undo_redo(self):
        """Sequential rotations 0 -> 45 -> 90 followed by undo and redo maintain exact single instances."""
        # 1. Rotate to 45 deg
        cmd1 = undo_manager.RotateObjectCommand(self.win, self.t1, 0.0, 45.0)
        cmd1.execute()
        self.win.undo_manager.add_command(cmd1)

        page = self.doc.load_page(0)
        text_45 = page.get_text()
        self.assertEqual(text_45.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(text_45.count("Line One Report URL Text"), 1)

        # 2. Rotate to 90 deg
        cmd2 = undo_manager.RotateObjectCommand(self.win, self.t1, 45.0, 90.0)
        cmd2.execute()
        self.win.undo_manager.add_command(cmd2)

        page = self.doc.load_page(0)
        text_90 = page.get_text()
        self.assertEqual(text_90.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(text_90.count("Line One Report URL Text"), 1)

        # 3. Undo back to 45 deg
        self.win.undo_manager.undo()
        self.assertAlmostEqual(self.t1.rotation, 45.0, places=1)
        page = self.doc.load_page(0)
        text_undo1 = page.get_text()
        self.assertEqual(text_undo1.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(text_undo1.count("Line One Report URL Text"), 1)

        # 4. Undo back to 0 deg
        self.win.undo_manager.undo()
        self.assertAlmostEqual(self.t1.rotation, 0.0, places=1)
        page = self.doc.load_page(0)
        text_undo2 = page.get_text()
        self.assertEqual(text_undo2.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(text_undo2.count("Line One Report URL Text"), 1)

    def test_touching_and_overlapping_bbox_close_editing(self):
        """When text bounding boxes touch or overlap by 1pt, editing one never corrupts or duplicates the other."""
        # Force bounding boxes to overlap by 2pt
        self.t0.bbox = (50, 89, 200, 106)
        self.t0.original_bbox = self.t0.bbox
        self.t1.bbox = (50, 104, 200, 118)
        self.t1.original_bbox = self.t1.bbox

        old_props = {'text': self.t1.text, 'bbox': self.t1.bbox, 'baseline': self.t1.baseline}
        new_props = {'text': "Modified Line One", 'bbox': self.t1.bbox, 'baseline': self.t1.baseline}

        cmd = undo_manager.EditObjectCommand(self.win, self.t1, old_props, new_props)
        cmd.execute()

        self.assertFalse(getattr(self.t0, '_ghost_redacted', False))
        page = self.doc.load_page(0)
        page_text = page.get_text()
        self.assertEqual(page_text.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(page_text.count("Modified Line One"), 1)

    def test_underline_link_text_rotation_across_paragraph(self):
        """Rotating a link/underlined text across paragraph lines preserves all other lines."""
        self.t1.is_underline = True
        self.t1.text = "https://datareportal.com/reports/example"
        self.t1.original_text = self.t1.text
        # Rotate across t0
        cmd = undo_manager.RotateObjectCommand(self.win, self.t1, 0.0, 310.0)
        cmd.execute()

        self.assertFalse(getattr(self.t0, '_ghost_redacted', False))
        page = self.doc.load_page(0)
        page_text = page.get_text()
        self.assertEqual(page_text.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(page_text.count("https://datareportal.com/reports/example"), 1)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_proportional_transform_handles.py
# ============================================================================
import unittest
from unittest.mock import MagicMock, patch
import fitz

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

from word_sys_pdf_editor.models import EditableImage, EditableShape, EditableStroke
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.undo_manager import UndoManager


class TestProportionalTransformHandles(unittest.TestCase):
    """Test suite for proportional vs free-form transform handles and Shift modifier inversion."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)

        self.window = MagicMock()
        self.window.doc = self.doc
        self.window.current_page_index = 0
        self.window.zoom_level = 1.0
        self.window.view_mode = False
        self.window.pdf_view = MagicMock()
        self.window._shift_pressed = False

        self.window.calculate_resize_geometry = PdfEditorWindow.calculate_resize_geometry.__get__(self.window, PdfEditorWindow)
        self.window._handle_resize_update = PdfEditorWindow._handle_resize_update.__get__(self.window, PdfEditorWindow)
        self.window._visual_to_unrotated_delta = lambda dx, dy: (dx, dy)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_corner_handle_se_proportional_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # delta_x=40, delta_y=10. Dominant axis is width (+40 / 200 = 0.20)
        res = self.window.calculate_resize_geometry(start_bbox, "se", 40.0, 10.0, shift_pressed=False)
        x1, y1, x2, y2 = res
        self.assertEqual(x1, 100.0)
        self.assertEqual(y1, 100.0)
        self.assertEqual(x2, 340.0)
        self.assertEqual(y2, 220.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_corner_handle_nw_proportional_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # delta_x=-40, delta_y=-10. Expands top-left
        res = self.window.calculate_resize_geometry(start_bbox, "nw", -40.0, -10.0, shift_pressed=False)
        x1, y1, x2, y2 = res
        self.assertEqual(x2, 300.0)
        self.assertEqual(y2, 200.0)
        self.assertEqual(x1, 60.0)
        self.assertEqual(y1, 80.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_corner_handle_ne_proportional_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # delta_x=40, delta_y=-10. Bottom-left anchor (100.0, 200.0)
        res = self.window.calculate_resize_geometry(start_bbox, "ne", 40.0, -10.0, shift_pressed=False)
        x1, y1, x2, y2 = res
        self.assertEqual(x1, 100.0)
        self.assertEqual(y2, 200.0)
        self.assertEqual(x2, 340.0)
        self.assertEqual(y1, 80.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_corner_handle_sw_proportional_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # delta_x=-40, delta_y=10. Top-right anchor (300.0, 100.0)
        res = self.window.calculate_resize_geometry(start_bbox, "sw", -40.0, 10.0, shift_pressed=False)
        x1, y1, x2, y2 = res
        self.assertEqual(x2, 300.0)
        self.assertEqual(y1, 100.0)
        self.assertEqual(x1, 60.0)
        self.assertEqual(y2, 220.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_corner_handle_freeform_with_shift(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # Holding Shift inverts corner drag to free-form
        res = self.window.calculate_resize_geometry(start_bbox, "se", 40.0, 10.0, shift_pressed=True)
        x1, y1, x2, y2 = res
        self.assertEqual(x1, 100.0)
        self.assertEqual(y1, 100.0)
        self.assertEqual(x2, 340.0)
        self.assertEqual(y2, 210.0)
        # Aspect ratio changed from 2.0 to 240 / 110 (~2.18)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 240.0 / 110.0, places=2)

        res_nw = self.window.calculate_resize_geometry(start_bbox, "nw", -15.0, -30.0, shift_pressed=True)
        self.assertEqual(res_nw, (85.0, 70.0, 300.0, 200.0))

    def test_edge_handles_freeform_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)

        # Right edge: only width changes
        res_e = self.window.calculate_resize_geometry(start_bbox, "e", 50.0, 30.0, shift_pressed=False)
        self.assertEqual(res_e, (100.0, 100.0, 350.0, 200.0))

        # Left edge: only left bound changes
        res_w = self.window.calculate_resize_geometry(start_bbox, "w", -40.0, 10.0, shift_pressed=False)
        self.assertEqual(res_w, (60.0, 100.0, 300.0, 200.0))

        # Bottom edge: only height changes
        res_s = self.window.calculate_resize_geometry(start_bbox, "s", 25.0, 40.0, shift_pressed=False)
        self.assertEqual(res_s, (100.0, 100.0, 300.0, 240.0))

        # Top edge: only top bound changes
        res_n = self.window.calculate_resize_geometry(start_bbox, "n", 15.0, -30.0, shift_pressed=False)
        self.assertEqual(res_n, (100.0, 70.0, 300.0, 200.0))

    def test_edge_handles_proportional_with_shift(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)  # w=200, h=100, aspect=2.0

        # Right edge with Shift: expands width to 250, scales height to 125 centered on Y
        res_e = self.window.calculate_resize_geometry(start_bbox, "e", 50.0, 0.0, shift_pressed=True)
        x1, y1, x2, y2 = res_e
        self.assertEqual(x1, 100.0)
        self.assertEqual(x2, 350.0)
        self.assertEqual(y1, 87.5)
        self.assertEqual(y2, 212.5)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

        # Left edge with Shift: expands width to 250, scales height to 125 centered on Y
        res_w = self.window.calculate_resize_geometry(start_bbox, "w", -50.0, 0.0, shift_pressed=True)
        x1, y1, x2, y2 = res_w
        self.assertEqual(x1, 50.0)
        self.assertEqual(x2, 300.0)
        self.assertEqual(y1, 87.5)
        self.assertEqual(y2, 212.5)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

        # Bottom edge with Shift: expands height to 150, scales width to 300 centered on X
        res_s = self.window.calculate_resize_geometry(start_bbox, "s", 0.0, 50.0, shift_pressed=True)
        x1, y1, x2, y2 = res_s
        self.assertEqual(y1, 100.0)
        self.assertEqual(y2, 250.0)
        self.assertEqual(x1, 50.0)
        self.assertEqual(x2, 350.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

        # Top edge with Shift: expands height to 150, scales width to 300 centered on X
        res_n = self.window.calculate_resize_geometry(start_bbox, "n", 0.0, -50.0, shift_pressed=True)
        x1, y1, x2, y2 = res_n
        self.assertEqual(y1, 50.0)
        self.assertEqual(y2, 200.0)
        self.assertEqual(x1, 50.0)
        self.assertEqual(x2, 350.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_min_size_clamping(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # Inward drag beyond bounds
        res = self.window.calculate_resize_geometry(start_bbox, "se", -500.0, -500.0, shift_pressed=False, min_size=20.0)
        x1, y1, x2, y2 = res
        w = x2 - x1
        h = y2 - y1
        self.assertGreaterEqual(w, 20.0)
        self.assertGreaterEqual(h, 10.0)
        self.assertAlmostEqual(w / h, 2.0, places=2)

    def test_handle_resize_update_with_image_object(self):
        image = EditableImage(bbox=(50.0, 50.0, 250.0, 150.0), page_number=0, xref=None, image_bytes=b"dummy")
        self.window.resize_handle = "se"
        self.window.resize_start_bbox = image.bbox
        self.window.dragged_object = image

        # Perform proportional update
        self.window._handle_resize_update(40.0, 20.0)

        self.assertEqual(image.bbox, (50.0, 50.0, 290.0, 170.0))
        self.window.pdf_view.queue_draw.assert_called()

    def test_handle_resize_update_with_shift_gesture(self):
        image = EditableImage(bbox=(50.0, 50.0, 250.0, 150.0), page_number=0, xref=None, image_bytes=b"dummy")
        self.window.resize_handle = "se"
        self.window.resize_start_bbox = image.bbox
        self.window.dragged_object = image

        gesture = MagicMock()
        gesture.get_current_event_state.return_value = Gdk.ModifierType.SHIFT_MASK

        # Shift held -> corner drag becomes free-form
        self.window._handle_resize_update(40.0, 10.0, gesture=gesture)

        self.assertEqual(image.bbox, (50.0, 50.0, 290.0, 160.0))


if __name__ == "__main__":
    unittest.main()

