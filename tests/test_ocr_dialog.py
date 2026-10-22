"""Tests for OCRDialog and language model UI interactions."""

import os
import tempfile
from pathlib import Path
import pytest
import fitz
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from word_sys_pdf_editor.ocr_dialog import OCRDialog
from word_sys_pdf_editor.ocr_engine import (
    get_available_languages,
    get_tessdata_user_dir,
    SUPPORTED_LANGUAGES,
)


@pytest.fixture
def sample_pdf():
    doc = fitz.open()
    # Page 0: Digital text
    p0 = doc.new_page(width=400, height=300)
    p0.insert_text(fitz.Point(30, 40), "Selectable digital text on page zero of this test document.", fontsize=12)

    # Page 1: Scanned image
    p1 = doc.new_page(width=400, height=300)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 300, 250), 1)
    p1.insert_image(fitz.Rect(10, 10, 390, 290), pixmap=pix)
    return doc


def test_ocr_dialog_init(sample_pdf):
    parent = Adw.Window()
    dialog = OCRDialog(parent_window=parent, doc=sample_pdf, current_page_num=0)

    assert dialog is not None
    assert dialog.get_title() is not None
    assert dialog.scan_stats["total_pages"] == 2
    assert dialog.scan_stats["scanned_count"] == 1
    assert dialog.scan_stats["scanned_pages"] == [1]

    # Verify scope dropdown populated
    assert len(dialog.scope_options) >= 2
    assert "scanned_only" in dialog.scope_options
    assert "current" in dialog.scope_options
    assert "all" in dialog.scope_options

    # Verify language dropdown populated
    installed = [c for c, d in get_available_languages().items() if d["is_installed"]]
    assert len(dialog.installed_lang_codes) == len(installed)

    dialog.destroy()


def test_ocr_dialog_scope_selection(sample_pdf):
    parent = Adw.Window()
    completed_called = False
    received_pages = []

    def on_complete(target_pages, results):
        nonlocal completed_called, received_pages
        completed_called = True
        received_pages = target_pages

    dialog = OCRDialog(
        parent_window=parent,
        doc=sample_pdf,
        current_page_num=1,
        on_completed_callback=on_complete,
    )

    # Scope index for scanned_only
    scanned_idx = dialog.scope_options.index("scanned_only")
    dialog.scope_row.set_selected(scanned_idx)
    assert dialog.scope_row.get_selected() == scanned_idx

    # Simulate callback
    dialog._on_ocr_finished([1], {1: "fake_doc"})
    assert completed_called is True
    assert received_pages == [1]

    dialog.destroy()


def test_ocr_dialog_transparent_storage_info(sample_pdf):
    parent = Adw.Window()
    dialog = OCRDialog(parent_window=parent, doc=sample_pdf)

    # User storage path must be visible in dialog
    user_dir_str = str(get_tessdata_user_dir())
    assert user_dir_str is not None
    assert "word-sys-pdf-editor" in user_dir_str

    dialog.destroy()


def test_ocr_dialog_active_page_display():
    doc = fitz.open()
    for _ in range(10):
        doc.new_page()

    parent = Adw.Window()

    # When on page 5 (0-based index 4)
    dialog5 = OCRDialog(parent_window=parent, doc=doc, current_page_num=4)
    item_str_p5 = dialog5.scope_model.get_string(0)
    assert "5" in item_str_p5, f"Expected page 5 in label, got: {item_str_p5}"
    assert dialog5.scope_row.get_selected() == 0
    dialog5.destroy()

    # When on page 3 (0-based index 2)
    dialog3 = OCRDialog(parent_window=parent, doc=doc, current_page_num=2)
    item_str_p3 = dialog3.scope_model.get_string(0)
    assert "3" in item_str_p3, f"Expected page 3 in label, got: {item_str_p3}"
    assert dialog3.scope_row.get_selected() == 0
    dialog3.destroy()

