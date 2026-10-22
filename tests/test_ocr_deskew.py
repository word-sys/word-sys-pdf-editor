"""Automated unit and integration tests for OCR Page Deskew and Auto-Orientation."""

import io
import fitz
import pytest
from PIL import Image, ImageDraw

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.ocr_engine import (
    detect_page_skew_angle,
    detect_page_orientation,
    deskew_scanned_page,
    is_scanned_page,
)
from word_sys_pdf_editor.undo_manager import EmbedOCRTextCommand


def _create_tilted_scanned_pdf(angle_deg: float, width: float = 500, height: float = 350, dpi: int = 150) -> fitz.Document:
    """Create a synthetic 1-page scanned PDF tilted by angle_deg degrees."""
    doc = fitz.open()
    p = doc.new_page(width=width, height=height)

    # Render text lines onto high-res PIL canvas
    img = Image.new("RGB", (int(width * 2), int(height * 2)), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for y in range(80, int(height * 2) - 80, 70):
        draw.text(
            (100, y),
            "Sample scanned document paragraph for skew and rotation test.",
            fill=(0, 0, 0),
        )

    # In PIL, rotate(angle) rotates counter-clockwise.
    # To tilt text clockwise by angle_deg, rotate by -angle_deg:
    tilted = img.rotate(-angle_deg, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255))
    buf = io.BytesIO()
    tilted.save(buf, format="PNG")

    p.insert_image(p.rect, stream=buf.getvalue())
    return doc


def test_detect_page_skew_angle_precision():
    """Verify skew detection calculates angles with high accuracy."""
    # Test positive clockwise tilt (3.5 deg)
    doc_pos = _create_tilted_scanned_pdf(angle_deg=3.5)
    skew_pos = detect_page_skew_angle(doc_pos[0])
    assert pytest.approx(skew_pos, abs=0.6) == 3.5
    doc_pos.close()

    # Test negative tilt (-4.0 deg)
    doc_neg = _create_tilted_scanned_pdf(angle_deg=-4.0)
    skew_neg = detect_page_skew_angle(doc_neg[0])
    assert pytest.approx(skew_neg, abs=0.6) == -4.0
    doc_neg.close()


def test_detect_page_skew_straight_page_invariance():
    """Verify straight pages return 0.0 without false positives."""
    doc = _create_tilted_scanned_pdf(angle_deg=0.0)
    skew = detect_page_skew_angle(doc[0])
    assert skew == 0.0
    doc.close()


def test_deskew_scanned_page_levels_content():
    """Verify deskew_scanned_page permanently straightens the tilted raster scan."""
    doc = _create_tilted_scanned_pdf(angle_deg=3.5)
    page = doc[0]
    initial_skew = detect_page_skew_angle(page)
    assert abs(initial_skew) >= 3.0

    # Straighten the page
    success = deskew_scanned_page(doc, 0, initial_skew)
    assert success is True

    # After straightening, detected skew angle must drop to 0.0 (straight)
    post_skew = detect_page_skew_angle(doc[0])
    assert post_skew == 0.0
    doc.close()


def test_detect_page_orientation():
    """Verify coarse orientation correctly identifies upright vs rotated pages."""
    doc = fitz.open()
    p = doc.new_page(width=500, height=350)
    p.insert_text((50, 80), "The quick brown fox jumps over the lazy dog in this sample document.", fontsize=14)
    p.insert_text((50, 120), "Optical Character Recognition test page with standard English paragraphs.", fontsize=14)
    p.insert_text((50, 160), "Additional line of text to evaluate horizontal and vertical projection profiles.", fontsize=14)

    # 0 degrees (Upright)
    orient_0 = detect_page_orientation(p)
    assert orient_0 == 0

    # 90 degrees
    p.set_rotation(90)
    orient_90 = detect_page_orientation(p)
    assert orient_90 == 90

    doc.close()


def test_embed_ocr_text_layer_with_auto_deskew():
    """Verify embed_ocr_text_layer_on_page automatically straightens tilted scans and embeds text."""
    doc = _create_tilted_scanned_pdf(angle_deg=3.8)
    assert is_scanned_page(doc[0]).is_scanned is True

    res = pdf_handler.embed_ocr_text_layer_on_page(
        doc,
        page_num=0,
        language="eng",
        dpi=150,
        auto_deskew=True,
        auto_rotate=False,
    )
    assert res["success"] is True
    assert res["words_embedded"] >= 5

    # Page should be straightened
    final_skew = detect_page_skew_angle(doc[0])
    assert final_skew == 0.0

    # Words must be searchable on the straightened page
    hits = doc[0].search_for("document") or doc[0].search_for("scanned")
    assert len(hits) >= 1
    doc.close()


def test_deskew_undo_reverts_to_original_tilted_scan():
    """Verify EmbedOCRTextCommand undo cleanly reverts to the original pre-deskew tilted scan."""
    doc = _create_tilted_scanned_pdf(angle_deg=3.5)
    page_num = 0

    class MockWindow:
        def __init__(self, document):
            self.doc = document
            self.current_page_index = 0
            self.current_page = 0
            self._active_session = None
            self.document_modified = False

    win = MockWindow(doc)
    cmd = EmbedOCRTextCommand(
        win,
        page_indices=[0],
        language="eng",
        dpi=150,
        auto_deskew=True,
        auto_rotate=False,
    )
    cmd.execute()
    assert detect_page_skew_angle(doc[0]) == 0.0

    # Undo
    cmd.undo()
    # Should revert to original tilted scan (~3.5 deg)
    reverted_skew = detect_page_skew_angle(doc[0])
    assert pytest.approx(reverted_skew, abs=0.8) == 3.5
    doc.close()
