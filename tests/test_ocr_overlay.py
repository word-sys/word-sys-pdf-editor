"""Automated unit and integration tests for OCR Overlay (Inspect Searchable Text Layer)."""

from unittest.mock import MagicMock
import fitz
import pytest

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.window import PdfEditorWindow


def test_extract_ocr_word_boxes_plain_page():
    """Verify word bounding boxes are extracted accurately from a page."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), "Alpha Beta Gamma", fontsize=12)

    boxes = PdfEditorWindow._extract_ocr_word_boxes(page)
    assert len(boxes) == 3
    words = [b[4] for b in boxes]
    assert words == ["Alpha", "Beta", "Gamma"]

    # Check that bounding box coordinates are sensible
    for x0, y0, x1, y1, word in boxes:
        assert x1 > x0
        assert y1 > y0
        assert 40 <= x0 <= 250
        assert 80 <= y0 <= 120

    doc.close()


def test_extract_ocr_word_boxes_empty_page():
    """Verify empty or image-only page without text layer yields empty list."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)

    boxes = PdfEditorWindow._extract_ocr_word_boxes(page)
    assert boxes == []

    # None page handling
    assert PdfEditorWindow._extract_ocr_word_boxes(None) == []
    doc.close()


def test_draw_ocr_overlay_cairo_calls():
    """Verify Cairo drawing operations are properly issued for extracted word boxes."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), "TestOverlay", fontsize=14)

    mock_cr = MagicMock()
    zoom = 1.5
    offset_x = 20.0
    offset_y = 30.0

    PdfEditorWindow._draw_ocr_overlay(mock_cr, page, zoom, offset_x, offset_y)

    # Ensure cairo save and restore were called
    assert mock_cr.save.called
    assert mock_cr.restore.called

    # Ensure rectangle was drawn with scaled & offset coordinates
    rect_calls = mock_cr.rectangle.call_args_list
    assert len(rect_calls) == 1
    rx, ry, rw, rh = rect_calls[0][0]

    # Verify scaling applied
    assert rx >= offset_x
    assert ry >= offset_y
    assert rw > 0
    assert rh > 0

    # Ensure dashed stroke was configured and drawn
    assert mock_cr.set_dash.called
    assert mock_cr.fill_preserve.called
    assert mock_cr.stroke.called

    doc.close()


def test_set_ocr_overlay_mode():
    """Verify set_ocr_overlay_mode updates window state, button, and action."""
    # Create window mock or partial instance
    win = MagicMock(spec=PdfEditorWindow)
    win.show_ocr_overlay = False
    win.ocr_overlay_btn = MagicMock()
    win.ocr_overlay_btn.get_active.return_value = False
    win.pdf_view = MagicMock()

    mock_action = MagicMock()
    mock_action.get_state.return_value.get_boolean.return_value = False
    win.lookup_action.return_value = mock_action

    # Call original method
    PdfEditorWindow.set_ocr_overlay_mode(win, True)

    assert win.show_ocr_overlay is True
    win.ocr_overlay_btn.set_active.assert_called_with(True)
    assert mock_action.set_state.called
    win.pdf_view.queue_draw.assert_called_once()

    # Toggle off
    win.ocr_overlay_btn.get_active.return_value = True
    mock_action.get_state.return_value.get_boolean.return_value = True
    PdfEditorWindow.set_ocr_overlay_mode(win, False)

    assert win.show_ocr_overlay is False
    win.ocr_overlay_btn.set_active.assert_called_with(False)


def test_ocr_text_embedding_with_overlay_extraction():
    """Verify embedded OCR text from pdf_handler creates valid overlay boxes."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=400)

    # Synthetic OCR words
    ocr_words = [
        {"text": "Invoice", "bbox": (50, 50, 120, 75)},
        {"text": "Total", "bbox": (50, 90, 100, 115)},
        {"text": "$150.00", "bbox": (110, 90, 180, 115)},
    ]

    pdf_handler.embed_ocr_text_layer(
        doc,
        page_numbers=[0],
        ocr_words_by_page={0: ocr_words},
    )

    boxes = PdfEditorWindow._extract_ocr_word_boxes(page)
    words = [b[4] for b in boxes]
    assert "Invoice" in words
    assert "Total" in words
    assert "$150.00" in words

    doc.close()
