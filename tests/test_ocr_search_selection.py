"""Automated unit tests for Part 62: Scanned Document Text Selection, Copy & Search Integration."""

import fitz
import pytest

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.search_engine import DocumentSearchEngine, SearchMatch


def _create_multi_page_pdf() -> fitz.Document:
    """Create a 3-page test PDF with distinct words."""
    doc = fitz.open()
    # Page 0
    p0 = doc.new_page(width=500, height=300)
    p0.insert_text(fitz.Point(50, 100), "Hello world from document search.", fontsize=14)
    p0.insert_text(fitz.Point(50, 150), "Case Sensitive Test Token.", fontsize=14)

    # Page 1
    p1 = doc.new_page(width=500, height=300)
    p1.insert_text(fitz.Point(60, 80), "Another page with hello world text.", fontsize=14)
    p1.insert_text(fitz.Point(60, 140), "case sensitive test token lowercase.", fontsize=14)

    # Page 2
    p2 = doc.new_page(width=500, height=300)
    p2.insert_text(fitz.Point(70, 120), "Final page world match here.", fontsize=14)

    return doc


def _create_ocr_pdf() -> fitz.Document:
    """Create a PDF with transparent OCR text layer (render_mode 3)."""
    doc = fitz.open()
    p = doc.new_page(width=500, height=300)
    # Insert invisible OCR text
    p.insert_text(
        fitz.Point(80, 100),
        "CONFIDENTIAL SCAN REPORT",
        fontsize=16,
        render_mode=3,
        color=(0, 0, 0),
    )
    p.insert_text(
        fitz.Point(80, 160),
        "ACCOUNT NUMBER 987654321",
        fontsize=14,
        render_mode=3,
        color=(0, 0, 0),
    )
    return doc


def test_search_engine_basic():
    doc = _create_multi_page_pdf()
    engine = DocumentSearchEngine()

    matches = engine.search(doc, "world", case_sensitive=False)
    assert len(matches) == 3
    assert matches[0].page_index == 0
    assert matches[1].page_index == 1
    assert matches[2].page_index == 2

    # Circular forward navigation
    assert engine.current_index == 0
    m1 = engine.next_match()
    assert m1.page_index == 1
    assert engine.current_index == 1

    m2 = engine.next_match()
    assert m2.page_index == 2
    assert engine.current_index == 2

    m0 = engine.next_match()
    assert m0.page_index == 0
    assert engine.current_index == 0

    # Circular backward navigation
    m_prev = engine.prev_match()
    assert m_prev.page_index == 2
    assert engine.current_index == 2

    doc.close()


def test_search_engine_case_sensitivity():
    doc = _create_multi_page_pdf()
    engine = DocumentSearchEngine()

    # Case insensitive
    matches_ci = engine.search(doc, "Case Sensitive", case_sensitive=False)
    assert len(matches_ci) == 2

    # Case sensitive
    matches_cs = engine.search(doc, "Case Sensitive", case_sensitive=True)
    assert len(matches_cs) == 1
    assert matches_cs[0].page_index == 0

    matches_lower = engine.search(doc, "case sensitive", case_sensitive=True)
    assert len(matches_lower) == 1
    assert matches_lower[0].page_index == 1

    doc.close()


def test_search_engine_nearest_match():
    doc = _create_multi_page_pdf()
    engine = DocumentSearchEngine()

    engine.search(doc, "world", case_sensitive=False)
    # Target page 1
    nearest = engine.find_nearest_match(current_page=1)
    assert nearest.page_index == 1
    assert engine.current_index == 1

    # Target page 2
    nearest2 = engine.find_nearest_match(current_page=2)
    assert nearest2.page_index == 2
    assert engine.current_index == 2

    doc.close()


def test_search_engine_empty_and_clear():
    doc = _create_multi_page_pdf()
    engine = DocumentSearchEngine()

    assert engine.search(doc, "") == []
    assert engine.search(doc, "   ") == []
    assert engine.search(None, "world") == []

    engine.search(doc, "world")
    assert len(engine.matches) > 0
    engine.clear()
    assert len(engine.matches) == 0
    assert engine.current_index == -1
    assert engine.get_current_match() is None

    doc.close()


def test_search_on_ocr_transparent_text_layer():
    doc = _create_ocr_pdf()
    engine = DocumentSearchEngine()

    matches = engine.search(doc, "CONFIDENTIAL", case_sensitive=False)
    assert len(matches) == 1
    assert matches[0].page_index == 0
    rect = matches[0].rect
    assert rect[0] >= 70 and rect[1] <= 110

    account_matches = engine.search(doc, "987654321", case_sensitive=False)
    assert len(account_matches) == 1
    assert account_matches[0].page_index == 0

    doc.close()


def test_ocr_word_and_block_hit_testing():
    doc = _create_ocr_pdf()

    # Hit test word on invisible OCR text
    word_info = pdf_handler.get_word_at_pos(doc, 0, (90, 95))
    assert word_info is not None
    assert word_info["text"] == "CONFIDENTIAL"
    assert len(word_info["bbox"]) == 4

    # Hit test block on invisible OCR text
    block_info = pdf_handler.get_block_at_pos(doc, 0, (90, 95))
    assert block_info is not None
    assert "CONFIDENTIAL" in block_info["text"]
    assert "SCAN" in block_info["text"]

    # Word hit test on account number line
    num_word = pdf_handler.get_word_at_pos(doc, 0, (230, 155))
    assert num_word is not None
    assert num_word["text"] == "987654321"

    # Region text extraction
    text_in_rect = pdf_handler.get_text_in_rect(doc, 0, (70, 80, 400, 180))
    assert "CONFIDENTIAL" in text_in_rect
    assert "987654321" in text_in_rect

    doc.close()


def test_ocr_banner_lifecycle_mocked():
    class MockLabel:
        def __init__(self):
            self.text = ""

        def set_text(self, t):
            self.text = t

    class MockProgressBar:
        def __init__(self):
            self.fraction = 0.0

        def set_fraction(self, f):
            self.fraction = f

    class MockButton:
        def __init__(self):
            self.sensitive = True

        def set_sensitive(self, s):
            self.sensitive = s

    class MockBanner:
        def __init__(self):
            self.visible = False

        def set_visible(self, v):
            self.visible = v

    class MockWindow:
        def __init__(self):
            self.ocr_banner = MockBanner()
            self.ocr_banner_label = MockLabel()
            self.ocr_banner_progress = MockProgressBar()
            self.ocr_banner_cancel_btn = MockButton()
            self.status_label = MockLabel()
            self._ocr_cancel_requested = False

        from word_sys_pdf_editor.window import PdfEditorWindow
        show_ocr_banner = PdfEditorWindow.show_ocr_banner
        update_ocr_banner = PdfEditorWindow.update_ocr_banner
        hide_ocr_banner = PdfEditorWindow.hide_ocr_banner
        _on_ocr_banner_cancel_clicked = PdfEditorWindow._on_ocr_banner_cancel_clicked

    win = MockWindow()
    win.show_ocr_banner(total_pages=5)
    assert win.ocr_banner.visible is True
    assert win._ocr_cancel_requested is False
    assert win.ocr_banner_progress.fraction == 0.0

    win.update_ocr_banner(current_page=3, total_pages=5, fraction=0.6)
    assert win.ocr_banner_progress.fraction == 0.6
    assert "3/5" in win.ocr_banner_label.text

    win._on_ocr_banner_cancel_clicked(None)
    assert win._ocr_cancel_requested is True
    assert win.ocr_banner_cancel_btn.sensitive is False

    win.hide_ocr_banner(cancelled=True)
    assert win.ocr_banner.visible is False


def test_search_button_toggle_sync():
    class MockSearchBar:
        def __init__(self):
            self.mode = False

        def get_search_mode(self):
            return self.mode

        def set_search_mode(self, val):
            self.mode = val

    class MockToggleButton:
        def __init__(self):
            self.active = False

        def get_active(self):
            return self.active

        def set_active(self, val):
            self.active = val

    class MockWindow:
        def __init__(self):
            self.search_bar = MockSearchBar()
            self.search_button = MockToggleButton()
            self.search_engine = DocumentSearchEngine()
            self.search_match_label = None
            self.search_entry = None
            self.pdf_view = None
            self.view_selected_text = ""

        from word_sys_pdf_editor.window import PdfEditorWindow
        toggle_search_bar = PdfEditorWindow.toggle_search_bar
        close_search_bar = PdfEditorWindow.close_search_bar
        _on_search_button_toggled = PdfEditorWindow._on_search_button_toggled

    win = MockWindow()
    assert win.search_bar.get_search_mode() is False
    assert win.search_button.get_active() is False

    # Toggle open
    win.toggle_search_bar()
    assert win.search_bar.get_search_mode() is True
    assert win.search_button.get_active() is True

    # Toggle close
    win.close_search_bar()
    assert win.search_bar.get_search_mode() is False
    assert win.search_button.get_active() is False

    # Trigger via button toggle
    win.search_button.set_active(True)
    win._on_search_button_toggled(win.search_button)
    assert win.search_bar.get_search_mode() is True

    win.search_button.set_active(False)
    win._on_search_button_toggled(win.search_button)
    assert win.search_bar.get_search_mode() is False


