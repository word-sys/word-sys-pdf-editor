import pytest
from unittest.mock import MagicMock, patch
import fitz

from word_sys_pdf_editor.i18n import _STRINGS
from word_sys_pdf_editor.locales import (
    STRINGS_DE,
    STRINGS_ES,
    STRINGS_FR,
    STRINGS_IT,
    STRINGS_RU,
)
from word_sys_pdf_editor.ocr_engine import (
    auto_invert_dark_background,
    estimate_word_confidence,
    perform_ocr_on_page,
)
from word_sys_pdf_editor.window import PdfEditorWindow


def test_ocr_auto_invert_strings_all_locales():
    """Verify that ocr_auto_invert and ocr_auto_invert_desc exist across all 7 supported locales."""
    required_keys = ["ocr_auto_invert", "ocr_auto_invert_desc"]
    locales = [
        ("EN", _STRINGS["en"]),
        ("TR", _STRINGS["tr"]),
        ("FR", STRINGS_FR),
        ("DE", STRINGS_DE),
        ("ES", STRINGS_ES),
        ("IT", STRINGS_IT),
        ("RU", STRINGS_RU),
    ]
    for loc_name, strings_dict in locales:
        for k in required_keys:
            assert k in strings_dict, f"Missing key '{k}' in {loc_name} locale"
            assert len(strings_dict[k].strip()) > 0, f"Empty string for key '{k}' in {loc_name}"


def test_auto_invert_dark_background_detection():
    """Test that a dark pixmap (e.g. white text on black background) is inverted."""
    # Create a small completely dark pixmap (RGB 0,0,0)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 10, 10), False)
    pix.clear_with(0x000000)

    # auto_invert should detect darkness and invert to bright
    inv_pix = auto_invert_dark_background(pix, threshold=120)
    samples = inv_pix.samples
    # Check that pixels are now high luminance (inverted)
    assert samples[0] > 200
    assert samples[1] > 200
    assert samples[2] > 200


def test_auto_invert_light_background_preserved():
    """Test that an already light pixmap is not inverted."""
    # Create a light pixmap (RGB 255, 255, 255)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 10, 10), False)
    pix.clear_with(0xFFFFFF)

    res_pix = auto_invert_dark_background(pix, threshold=120)
    samples = res_pix.samples
    assert samples[0] == 255
    assert samples[1] == 255
    assert samples[2] == 255


def test_estimate_word_confidence():
    """Verify that estimate_word_confidence correctly scores clean words vs OCR gibberish."""
    # Clean words
    assert estimate_word_confidence("Invoice") >= 0.85
    assert estimate_word_confidence("Application") >= 0.85
    assert estimate_word_confidence("12345") >= 0.80

    # Short / punctuation / symbols
    assert estimate_word_confidence("a") <= 0.70
    assert estimate_word_confidence("...") <= 0.40
    assert estimate_word_confidence("@#$!") <= 0.40
    assert estimate_word_confidence("x") <= 0.70


def test_perform_ocr_on_page_auto_invert():
    """Verify perform_ocr_on_page accepts auto_invert and passes correctly to pixmap handling."""
    doc = fitz.open()
    doc.new_page(width=200, height=200)

    mock_ocr_doc = fitz.open()

    with patch("word_sys_pdf_editor.ocr_engine.get_best_tessdata_dir_for_lang", return_value="/usr/share/tessdata"):
        with patch.object(fitz.Pixmap, "pdfocr_tobytes", create=True, return_value=b"%PDF-1.4 mock") as mock_ocr_pix:
            with patch("fitz.open", return_value=mock_ocr_doc):
                res = perform_ocr_on_page(doc, page_num=0, language="eng", dpi=100, auto_invert=True)
                assert res is mock_ocr_doc
                mock_ocr_pix.assert_called_once()
    doc.close()


def test_extract_ocr_word_boxes_with_cache():
    """Verify _extract_ocr_word_boxes retrieves cached confidence ratings from document."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)

    # Attach mock cached OCR words to document
    doc._ocr_words_cache = {
        0: [
            {"bbox": (10, 10, 50, 25), "text": "Header", "confidence": 0.95},
            {"bbox": (10, 30, 45, 42), "text": "~!#", "confidence": 0.35},
        ]
    }

    boxes = PdfEditorWindow._extract_ocr_word_boxes(page)
    assert len(boxes) == 2
    # Verify 5-tuple unpacking compatibility
    x0, y0, x1, y1, text = boxes[0]
    assert text == "Header"
    assert boxes[0].confidence == 0.95
    assert boxes[1][4] == "~!#"
    assert boxes[1].confidence == 0.35

    doc.close()


def test_draw_ocr_overlay_confidence_heatmaps():
    """Verify _draw_ocr_overlay correctly renders green, amber, and red confidence heatmap elements."""
    cr_mock = MagicMock()
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)

    # Cache 3 words: High (>=80%), Medium (50-79%), Low (<50%)
    doc._ocr_words_cache = {
        0: [
            {"bbox": (10, 10, 50, 20), "text": "HighConf", "confidence": 0.92},
            {"bbox": (10, 25, 50, 35), "text": "MedConf", "confidence": 0.65},
            {"bbox": (10, 40, 50, 50), "text": "LowConf", "confidence": 0.30},
        ]
    }

    PdfEditorWindow._draw_ocr_overlay(cr_mock, page, zoom=1.0)

    # cr.save and cr.restore must be called
    cr_mock.save.assert_called_once()
    cr_mock.restore.assert_called_once()

    # Check set_source_rgba calls for the 3 confidence categories
    rgba_calls = [c[0] for c in cr_mock.set_source_rgba.call_args_list]

    # High conf green
    assert any(c[0] == 0.15 and c[1] == 0.68 for c in rgba_calls)
    # Medium conf amber
    assert any(c[0] == 0.92 and c[1] == 0.65 for c in rgba_calls)
    # Low conf red
    assert any(c[0] == 0.88 and c[1] == 0.15 for c in rgba_calls)

    doc.close()
