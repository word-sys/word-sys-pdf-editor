"""Automated unit tests for Part 61: Transparent Searchable Text Layer Embedding."""

import fitz
import pytest

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.ocr_engine import is_scanned_page, perform_ocr_on_page
from word_sys_pdf_editor.undo_manager import EmbedOCRTextCommand, UndoManager
from word_sys_pdf_editor.models import DocumentSession


def _create_scanned_pdf(lines_per_page: list[list[tuple[float, float, str]]], width: float = 500, height: float = 300, dpi: int = 150) -> fitz.Document:
    """Create a synthetic scanned PDF where each page contains only a raster image of rendered text."""
    src_doc = fitz.open()
    for page_lines in lines_per_page:
        p = src_doc.new_page(width=width, height=height)
        p.draw_rect(fitz.Rect(0, 0, width, height), color=(1, 1, 1), fill=(1, 1, 1))
        for x, y, text in page_lines:
            p.insert_text(fitz.Point(x, y), text, fontsize=18, fontname="helv", color=(0, 0, 0))

    scanned_doc = fitz.open()
    for i in range(len(src_doc)):
        pix = src_doc[i].get_pixmap(dpi=dpi, alpha=False)
        sp = scanned_doc.new_page(width=width, height=height)
        sp.insert_image(fitz.Rect(0, 0, width, height), pixmap=pix)

    src_doc.close()
    return scanned_doc


def test_extract_ocr_words_coordinate_scaling():
    target_doc = fitz.open()
    target_page = target_doc.new_page(width=600, height=400)

    ocr_doc = fitz.open()
    ocr_page = ocr_doc.new_page(width=300, height=200)
    ocr_page.insert_text(fitz.Point(30, 50), "SCALED WORD", fontsize=12)

    words = pdf_handler.extract_ocr_words_for_page(target_page, ocr_doc)
    assert len(words) == 2
    assert words[0]["text"] == "SCALED"
    assert words[1]["text"] == "WORD"

    orig_words = ocr_page.get_text("words")
    assert pytest.approx(words[0]["bbox"][0], rel=1e-2) == orig_words[0][0] * 2.0
    assert pytest.approx(words[0]["bbox"][1], rel=1e-2) == orig_words[0][1] * 2.0
    assert pytest.approx(words[0]["bbox"][2], rel=1e-2) == orig_words[0][2] * 2.0
    assert pytest.approx(words[0]["bbox"][3], rel=1e-2) == orig_words[0][3] * 2.0

    ocr_doc.close()
    target_doc.close()


def test_embed_ocr_text_layer_on_scanned_page_and_visual_invariance():
    doc = _create_scanned_pdf([[(30, 80, "SEARCHABLE SCAN LAYER EMBEDDED TEXT")]])
    page = doc[0]

    assert page.get_text().strip() == ""
    assert is_scanned_page(page).is_scanned is True

    before_pix = page.get_pixmap(dpi=100, alpha=False)
    before_samples = bytes(before_pix.samples)

    res = pdf_handler.embed_ocr_text_layer_on_page(doc, 0, language="eng", dpi=150)
    assert res["success"] is True
    assert res["words_embedded"] >= 3

    after_pix = page.get_pixmap(dpi=100, alpha=False)
    after_samples = bytes(after_pix.samples)
    assert before_samples == after_samples

    extracted_text = page.get_text().upper()
    assert "SEARCHABLE" in extracted_text or "SCAN" in extracted_text or "LAYER" in extracted_text
    assert is_scanned_page(page).has_selectable_text is True
    assert is_scanned_page(page).is_scanned is False

    hits = page.search_for("SCAN") or page.search_for("LAYER") or page.search_for("SEARCHABLE")
    assert len(hits) >= 1
    hit_rect = hits[0]
    assert 20 <= hit_rect.x0 <= 450
    assert 40 <= hit_rect.y0 <= 110

    rect_text = pdf_handler.get_text_in_rect(doc, 0, (20, 40, 480, 120)).upper()
    assert "SCAN" in rect_text or "LAYER" in rect_text or "SEARCHABLE" in rect_text
    doc.close()


def test_embed_ocr_text_layer_idempotency():
    doc = _create_scanned_pdf([[(40, 80, "UNIQUE TOKEN ALPHA")]])
    res1 = pdf_handler.embed_ocr_text_layer_on_page(doc, 0, language="eng", dpi=150)
    assert res1["success"] is True
    words_after_first = doc[0].get_text("words")
    count_first = len(words_after_first)
    assert count_first >= 2

    res2 = pdf_handler.embed_ocr_text_layer_on_page(doc, 0, language="eng", dpi=150, replace_existing=False)
    assert res2["success"] is True
    assert res2["words_embedded"] == 0
    assert len(doc[0].get_text("words")) == count_first

    res3 = pdf_handler.embed_ocr_text_layer_on_page(doc, 0, language="eng", dpi=150, replace_existing=True)
    assert res3["success"] is True
    assert len(doc[0].get_text("words")) == count_first
    doc.close()


def test_embed_ocr_text_layer_unicode_support():
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 300, 150), 1)
    page.insert_image(fitz.Rect(0, 0, 400, 200), pixmap=pix)

    unicode_words = [
        {"bbox": (40.0, 50.0, 140.0, 72.0), "text": "Türkçe"},
        {"bbox": (150.0, 50.0, 260.0, 72.0), "text": "ğüşiöçİĞÜŞÖÇ"},
        {"bbox": (40.0, 90.0, 180.0, 112.0), "text": "Привет"},
    ]
    res = pdf_handler.embed_ocr_text_layer_on_page(doc, 0, ocr_words=unicode_words)
    assert res["success"] is True
    assert res["words_embedded"] == 3

    page_text = page.get_text()
    assert "Türkçe" in page_text
    assert "ğüşiöçİĞÜŞÖÇ" in page_text
    assert "Привет" in page_text
    assert len(page.search_for("Türkçe")) == 1
    doc.close()


def test_embed_ocr_text_layer_rotated_page():
    doc = _create_scanned_pdf([[(40, 80, "ROTATED PAGE TEXT")]])
    page = doc[0]
    page.set_rotation(90)

    ocr_words = [
        {"bbox": (50.0, 60.0, 130.0, 80.0), "text": "ROTATED"},
        {"bbox": (140.0, 60.0, 220.0, 80.0), "text": "SEARCH"},
    ]
    res = pdf_handler.embed_ocr_text_layer_on_page(doc, 0, ocr_words=ocr_words)
    assert res["success"] is True
    assert res["words_embedded"] == 2

    hits = page.search_for("ROTATED")
    assert len(hits) == 1
    assert pytest.approx(hits[0].x0, abs=10.0) == 50.0
    doc.close()


def test_batch_embed_and_pdf_serialization_roundtrip():
    doc = _create_scanned_pdf([
        [(40, 80, "FIRST PAGE CONTENT")],
        [(40, 80, "SECOND PAGE DATA")],
    ])
    batch_res = pdf_handler.embed_ocr_text_layer(doc, page_numbers=[0, 1], language="eng", dpi=150)
    assert batch_res["success"] is True
    assert batch_res["pages_processed"] == 2
    assert batch_res["total_words_embedded"] >= 4

    saved_bytes = doc.tobytes(deflate=True, garbage=3)
    doc.close()

    reopened = fitz.open(stream=saved_bytes, filetype="pdf")
    assert len(reopened) == 2
    assert "FIRST" in reopened[0].get_text().upper() or "CONTENT" in reopened[0].get_text().upper()
    assert "SECOND" in reopened[1].get_text().upper() or "DATA" in reopened[1].get_text().upper()
    reopened.close()


def test_embed_ocr_command_undo_redo_cycle():
    doc = _create_scanned_pdf([[(40, 80, "UNDOABLE OCR COMMAND")]])

    class DummyView:
        def queue_draw(self):
            pass

    class DummyWindow:
        def __init__(self, d):
            self.session = DocumentSession(doc=d)
            self._active_session = self.session
            self.doc = d
            self.current_page_index = 0
            self.editable_texts = []
            self._page_objects_cache = {}
            self.document_modified = False
            self.undo_manager = UndoManager(self)
            self.status_label = None
            self.pdf_view = DummyView()

        def _update_ui_state(self):
            pass

        def _update_undo_redo_buttons(self):
            pass

    win = DummyWindow(doc)
    assert doc[0].get_text().strip() == ""
    assert len(win.editable_texts) == 0

    ocr_doc = perform_ocr_on_page(doc, 0, language="eng", dpi=150)
    cmd = EmbedOCRTextCommand(win, page_indices=[0], ocr_results={0: ocr_doc})
    cmd.execute()
    win.undo_manager.record(cmd)

    assert win.document_modified is True
    assert "UNDOABLE" in doc[0].get_text().upper() or "COMMAND" in doc[0].get_text().upper()
    assert len(win.editable_texts) >= 1

    win.undo_manager.undo()
    assert doc[0].get_text().strip() == ""
    assert len(win.editable_texts) == 0
    assert win.document_modified is False

    win.undo_manager.redo()
    assert "UNDOABLE" in doc[0].get_text().upper() or "COMMAND" in doc[0].get_text().upper()
    assert len(win.editable_texts) >= 1
    assert win.document_modified is True

    doc.close()
