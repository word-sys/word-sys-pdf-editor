import fitz
import pytest
from unittest.mock import MagicMock

from word_sys_pdf_editor.search_engine import DocumentSearchEngine, SearchMatch, PII_PATTERNS
from word_sys_pdf_editor.models import DocumentSession, RedactionMark
from word_sys_pdf_editor.undo_manager import UndoManager, CompositeCommand, AddRedactionCommand
from word_sys_pdf_editor import pdf_handler


def _create_sample_pii_pdf() -> fitz.Document:
    doc = fitz.open()
    # Page 0: SSN and Email
    p0 = doc.new_page(width=500, height=400)
    p0.insert_text(fitz.Point(50, 100), "Employee SSN: 123-45-6789", fontsize=12)
    p0.insert_text(fitz.Point(50, 150), "Contact email: test.user@example.com", fontsize=12)

    # Page 1: Credit Card and Phone
    p1 = doc.new_page(width=500, height=400)
    p1.insert_text(fitz.Point(50, 100), "Payment Card: 4111-2222-3333-4444", fontsize=12)
    p1.insert_text(fitz.Point(50, 150), "Direct phone: (555) 123-4567", fontsize=12)

    # Page 2: Date and repeated SSN
    p2 = doc.new_page(width=500, height=400)
    p2.insert_text(fitz.Point(50, 100), "Record created on 2026-10-23", fontsize=12)
    p2.insert_text(fitz.Point(50, 150), "Duplicate SSN: 987-65-4321", fontsize=12)

    return doc


def test_pii_patterns_exist():
    expected_keys = {"ssn", "credit_card", "email", "phone", "date"}
    assert expected_keys.issubset(set(PII_PATTERNS.keys()))
    for k in expected_keys:
        assert "regex" in PII_PATTERNS[k]
        assert "label_key" in PII_PATTERNS[k]


def test_search_pii_ssn_detection():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    # Entire document: pages 0 and 2 have SSNs
    matches = engine.search_pii(doc, "ssn")
    assert len(matches) == 2
    matched_pages = {m.page_index for m in matches}
    assert matched_pages == {0, 2}
    assert any("123-45-6789" in m.text for m in matches)
    assert any("987-65-4321" in m.text for m in matches)


def test_search_pii_scoped_to_single_page():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    # Only search page 0
    matches_p0 = engine.search_pii(doc, "ssn", page_indices=[0])
    assert len(matches_p0) == 1
    assert matches_p0[0].page_index == 0
    assert "123-45-6789" in matches_p0[0].text

    # Search page 1 (no SSN)
    matches_p1 = engine.search_pii(doc, "ssn", page_indices=[1])
    assert len(matches_p1) == 0


def test_search_pii_email_and_credit_card():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    email_matches = engine.search_pii(doc, "email")
    assert len(email_matches) == 1
    assert email_matches[0].page_index == 0
    assert "test.user@example.com" in email_matches[0].text

    cc_matches = engine.search_pii(doc, "credit_card")
    assert len(cc_matches) == 1
    assert cc_matches[0].page_index == 1
    assert "4111-2222-3333-4444" in cc_matches[0].text


def test_search_pii_phone_and_date():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    phone_matches = engine.search_pii(doc, "phone")
    assert len(phone_matches) >= 1
    assert any(m.page_index == 1 for m in phone_matches)

    date_matches = engine.search_pii(doc, "date")
    assert len(date_matches) >= 1
    assert any(m.page_index == 2 for m in date_matches)


def test_search_regex_custom_pattern():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    matches = engine.search_regex(doc, r"Employee\s+SSN")
    assert len(matches) == 1
    assert matches[0].page_index == 0


def test_stage_redactions_composite_command_and_undo():
    doc = _create_sample_pii_pdf()
    session = DocumentSession(doc=doc, pdf_path=None)

    # Mock editor window
    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window._update_undo_redo_buttons = MagicMock()
    undo_mgr = UndoManager(window)
    session.undo_manager = undo_mgr
    window.undo_manager = undo_mgr
    window.document_modified = False

    def mock_add(mark, session=None):
        sess = session or window._active_session
        p = mark.page_number
        if p not in sess.redaction_marks:
            sess.redaction_marks[p] = []
        if mark not in sess.redaction_marks[p]:
            sess.redaction_marks[p].append(mark)

    def mock_remove(mark, session=None):
        sess = session or window._active_session
        p = mark.page_number
        if p in sess.redaction_marks and mark in sess.redaction_marks[p]:
            sess.redaction_marks[p].remove(mark)

    window._add_redaction_mark_to_session = mock_add
    window._remove_redaction_mark_from_session = mock_remove

    from word_sys_pdf_editor.window import PdfEditorWindow
    stage_func = PdfEditorWindow.stage_redactions_for_matches.__get__(window, PdfEditorWindow)

    engine = DocumentSearchEngine(doc)
    matches = engine.search_pii(doc, "ssn")
    assert len(matches) == 2

    # Stage redactions
    count = stage_func(matches, overlay_text="CONFIDENTIAL", fill_color=(0.0, 0.0, 0.0))
    assert count == 2

    total_staged = sum(len(marks) for marks in session.redaction_marks.values())
    assert total_staged == 2
    assert len(session.redaction_marks[0]) == 1
    assert len(session.redaction_marks[2]) == 1
    assert session.redaction_marks[0][0].overlay_text == "CONFIDENTIAL"

    # Single Undo reverts all staged marks
    assert undo_mgr.can_undo() is True
    undo_mgr.undo()

    total_after_undo = sum(len(marks) for marks in session.redaction_marks.values())
    assert total_after_undo == 0

    # Redo restores all staged marks
    assert undo_mgr.can_redo() is True
    undo_mgr.redo()

    total_after_redo = sum(len(marks) for marks in session.redaction_marks.values())
    assert total_after_redo == 2


def test_batch_search_and_redact_permanent_purge():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)
    matches = engine.search_pii(doc, "email")
    assert len(matches) == 1

    # Stage mark
    m = matches[0]
    mark = RedactionMark(
        page_number=m.page_index,
        bbox=m.bbox,
        fill_color=(0.0, 0.0, 0.0),
        overlay_text="[REDACTED]"
    )

    # Burn redaction permanently into stream
    success = pdf_handler.apply_redaction_marks(doc, {m.page_index: [mark]})
    assert success is True

    # Verify stream eradication
    page = doc[0]
    assert "test.user@example.com" not in page.get_text()
    cleaned_bytes = doc.tobytes(garbage=4, deflate=True, clean=True)
    assert b"test.user@example.com" not in cleaned_bytes


def test_search_redact_dialog_ui():
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw
    Adw.init()

    from word_sys_pdf_editor.search_redact_dialog import SearchRedactDialog

    doc = _create_sample_pii_pdf()
    confirmed_data = []

    def on_confirm(matches, overlay_text, fill_color, text_color):
        confirmed_data.append((matches, overlay_text, fill_color, text_color))

    dialog = SearchRedactDialog(
        parent_window=None,
        doc=doc,
        current_page_num=0,
        initial_query="Employee",
        default_fill=(0.0, 0.0, 0.0),
        default_overlay="[REDACTED]",
        on_confirm_callback=on_confirm
    )

    # Initial query should trigger matching immediately
    assert len(dialog.current_matches) == 1
    assert dialog.confirm_btn.get_sensitive() is True

    # Switching to PII pattern mode
    dialog.mode_dropdown.set_selected(1)
    dialog._on_mode_changed(dialog.mode_dropdown, None)
    # Default pattern is SSN (index 0)
    assert len(dialog.current_matches) == 2
    assert dialog.confirm_btn.get_sensitive() is True

    # Confirm action
    dialog._on_confirm_clicked(dialog.confirm_btn)
    assert len(confirmed_data) == 1
    matches, overlay, fill, text_col = confirmed_data[0]
    assert len(matches) == 2
    assert overlay == "[REDACTED]"
    assert fill == (0.0, 0.0, 0.0)
    assert text_col == (1.0, 1.0, 1.0)

