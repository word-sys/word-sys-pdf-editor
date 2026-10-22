import io
from unittest.mock import MagicMock, patch
import fitz
from PIL import Image

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import RedactionMark
from word_sys_pdf_editor.window import PdfEditorWindow


def _make_test_image_bytes(width=100, height=100, bg_color=(255, 255, 255), fg_rect=(30, 30, 70, 70), fg_color=(255, 0, 0)):
    im = Image.new("RGB", (width, height), bg_color)
    for x in range(fg_rect[0], fg_rect[2]):
        for y in range(fg_rect[1], fg_rect[3]):
            im.putpixel((x, y), fg_color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_text_eradication_from_stream():
    """Verify underlying text char spans and glyphs are permanently eradicated from the stream."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 80), "CONFIDENTIAL_API_KEY_12345", fontsize=14)

    # Confirm text is searchable before redaction
    assert "CONFIDENTIAL_API_KEY_12345" in page.get_text()
    assert len(page.search_for("CONFIDENTIAL_API_KEY_12345")) > 0

    # Apply redaction mark
    mark = RedactionMark(
        page_number=0,
        bbox=(40, 60, 300, 100),
        overlay_text="[REDACTED]",
        fill_color=(0.0, 0.0, 0.0),
        text_color=(1.0, 1.0, 1.0),
        font_size=10.0
    )
    success = pdf_handler.apply_redaction_marks(doc, {0: [mark]})
    assert success is True

    # 1. Page text check
    page_text = page.get_text()
    assert "CONFIDENTIAL_API_KEY_12345" not in page_text
    assert "[REDACTED]" in page_text

    # 2. Search check
    hits = page.search_for("CONFIDENTIAL_API_KEY_12345")
    assert len(hits) == 0

    # 3. Audit helper check
    purged = pdf_handler.verify_redaction_purge(doc, 0, (40, 60, 300, 100), search_term="CONFIDENTIAL_API_KEY_12345")
    assert purged is True

    # 4. Binary purge check with deflation
    cleaned_bytes = doc.tobytes(garbage=4, deflate=True, clean=True)
    assert b"CONFIDENTIAL_API_KEY_12345" not in cleaned_bytes


def test_image_pixel_blanking():
    """Verify overlapping image pixels are blanked out while surrounding image remains intact."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    img_data = _make_test_image_bytes(width=100, height=100, bg_color=(255, 255, 255), fg_rect=(40, 40, 60, 60), fg_color=(255, 0, 0))
    page.insert_image(fitz.Rect(50, 50, 250, 250), stream=img_data)

    # Redact only the red center square
    mark = RedactionMark(
        page_number=0,
        bbox=(130, 130, 170, 170),
        overlay_text="",
        fill_color=(0.0, 0.0, 0.0)
    )
    success = pdf_handler.apply_redaction_marks(doc, {0: [mark]})
    assert success is True

    pix = page.get_pixmap(dpi=72)
    # The center pixel should now be black (0, 0, 0)
    assert pix.pixel(150, 150)[:3] == (0, 0, 0)
    # The corner pixel outside redaction should still be white (255, 255, 255)
    assert pix.pixel(60, 60)[:3] == (255, 255, 255)


def test_custom_fill_and_overlay_text():
    """Verify white fill with black text and custom exemption codes."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 80), "RESTRICTED FINANCIAL DATA", fontsize=12)

    mark = RedactionMark(
        page_number=0,
        bbox=(45, 60, 280, 100),
        overlay_text="FOIA (b)(4)",
        fill_color=(1.0, 1.0, 1.0),
        text_color=(0.0, 0.0, 0.0),
        font_size=11.0
    )
    success = pdf_handler.apply_redaction_marks(doc, {0: [mark]})
    assert success is True

    text = page.get_text()
    assert "RESTRICTED FINANCIAL DATA" not in text
    assert "FOIA (b)(4)" in text


def test_safety_warning_dialog_rejection():
    """Verify rejecting the safety warning cancels redaction application."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)

    win = MagicMock()
    win.doc = doc
    mark = RedactionMark(page_number=0, bbox=(10, 10, 50, 50))
    win._active_session = MagicMock()
    win._active_session.redaction_marks = {0: [mark]}

    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=False):
        result = PdfEditorWindow.apply_all_redactions(win, prompt_warning=True)

    assert result is False
    # Staged mark must remain intact in session
    assert len(win._active_session.redaction_marks[0]) == 1


def test_safety_warning_dialog_acceptance():
    """Verify accepting the safety warning burns redactions and invalidates caches."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "TOP_SECRET", fontsize=12)
    pdf_handler.save_page_snapshot(doc, 0, force=True)

    win = MagicMock()
    win.doc = doc
    win.current_page_index = 0
    mark = RedactionMark(page_number=0, bbox=(40, 30, 200, 70), overlay_text="[REDACTED]")
    win._active_session = MagicMock()
    win._active_session.redaction_marks = {0: [mark]}
    win._page_objects_cache = {0: "old_cached_objects"}
    win.status_label = MagicMock()
    win.pdf_view = MagicMock()
    win.annotations_sidebar = MagicMock()

    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=True):
        result = PdfEditorWindow.apply_all_redactions(win, prompt_warning=True)

    assert result is True
    assert len(win._active_session.redaction_marks) == 0
    assert 0 not in win._page_objects_cache
    win._load_page.assert_called_once_with(0, reload_objects=True)
    win.status_label.set_text.assert_called()


def test_save_interception_when_marks_pending():
    """Verify save_document / on_save_clicked prompts user when pending marks exist."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)

    win = MagicMock()
    win.doc = doc
    win.current_file_path = "/tmp/test_save.pdf"
    win._active_session = MagicMock()
    mark = RedactionMark(page_number=0, bbox=(10, 10, 50, 50))
    win._active_session.redaction_marks = {0: [mark]}

    # User cancels prompt
    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=False):
        PdfEditorWindow.on_save_clicked(win, None)
        win.save_document.assert_not_called()

    # User confirms prompt
    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=True):
        PdfEditorWindow.on_save_clicked(win, None)
        win.apply_all_redactions.assert_called_with(prompt_warning=False)
        win.save_document.assert_called_with("/tmp/test_save.pdf", incremental=False)


def test_redaction_toolbar_and_controls_integration():
    """Verify live badge update on redaction apply button in toolbar."""
    win = MagicMock()
    win.redaction_apply_button = MagicMock()
    win._active_session = MagicMock()

    # 0 marks: button is disabled
    win._active_session.redaction_marks = {}
    PdfEditorWindow._update_redaction_controls(win)
    win.redaction_apply_button.set_sensitive.assert_called_with(False)

    # 3 marks: button is enabled and label includes count
    m1 = RedactionMark(page_number=0, bbox=(0, 0, 10, 10))
    m2 = RedactionMark(page_number=0, bbox=(20, 20, 30, 30))
    m3 = RedactionMark(page_number=1, bbox=(5, 5, 15, 15))
    win._active_session.redaction_marks = {0: [m1, m2], 1: [m3]}
    PdfEditorWindow._update_redaction_controls(win)
    win.redaction_apply_button.set_sensitive.assert_called_with(True)
    # Check that label was set with count 3
    args, _ = win.redaction_apply_button.set_label.call_args
    assert "3" in args[0]
