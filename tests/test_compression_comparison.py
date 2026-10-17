from __future__ import annotations

import io
import os
import tempfile
import pytest
import cairo
import pymupdf as fitz
from PIL import Image

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from word_sys_pdf_editor.compressor import (
    PRESET_BALANCED,
    PRESET_MAXIMUM,
    PRESET_HIGH_QUALITY,
    PRESET_LOSSLESS,
    PRESET_MAX_BW,
)
from word_sys_pdf_editor.compress_dialog import CompressionDialog
from word_sys_pdf_editor.compress_compare_dialog import CompressionCompareDialog


def _create_multi_page_pdf(num_pages: int = 3) -> bytes:
    doc = fitz.open()
    for p in range(num_pages):
        page = doc.new_page(width=400, height=500)
        img = Image.new("RGB", (300, 300), color=(50 + p * 40, 100, 150))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page.insert_image(fitz.Rect(50, 50, 350, 350), stream=buf.getvalue())
        page.insert_text(fitz.Point(50, 400), f"Test Page {p + 1}", fontsize=16)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_compare_dialog_initialization():
    pdf_bytes = _create_multi_page_pdf(3)
    dlg = CompressionCompareDialog(
        parent_window=None,
        pdf_bytes=pdf_bytes,
        initial_filename="test_doc.pdf",
        initial_preset=PRESET_BALANCED,
    )
    assert dlg.total_pages == 3
    assert dlg.current_page == 0
    assert dlg.zoom_level == 1.0
    assert dlg.view_mode == "side"
    assert dlg.active_preset == PRESET_BALANCED
    assert dlg.prev_page_btn.get_sensitive() is False
    assert dlg.next_page_btn.get_sensitive() is True
    dlg.destroy()


def test_compare_dialog_page_navigation():
    pdf_bytes = _create_multi_page_pdf(3)
    dlg = CompressionCompareDialog(
        parent_window=None,
        pdf_bytes=pdf_bytes,
    )

    dlg._change_page(1)
    assert dlg.current_page == 1
    assert dlg.prev_page_btn.get_sensitive() is True
    assert dlg.next_page_btn.get_sensitive() is True

    dlg._change_page(1)
    assert dlg.current_page == 2
    assert dlg.prev_page_btn.get_sensitive() is True
    assert dlg.next_page_btn.get_sensitive() is False

    # Should not advance past last page
    dlg._change_page(1)
    assert dlg.current_page == 2

    # Go back to start
    dlg._change_page(-2)
    assert dlg.current_page == 0
    assert dlg.prev_page_btn.get_sensitive() is False

    dlg.destroy()


def test_compare_dialog_zoom_controls():
    pdf_bytes = _create_multi_page_pdf(1)
    dlg = CompressionCompareDialog(
        parent_window=None,
        pdf_bytes=pdf_bytes,
    )

    dlg._adjust_zoom(0.25)
    assert dlg.zoom_level == 1.25
    assert dlg.zoom_label.get_text() == "125%"

    dlg._adjust_zoom(-0.5)
    assert dlg.zoom_level == 0.75

    # Test zoom clamping limits
    dlg._adjust_zoom(-5.0)
    assert dlg.zoom_level == 0.5

    dlg._adjust_zoom(10.0)
    assert dlg.zoom_level == 4.0

    dlg.destroy()


def test_compare_dialog_view_modes_and_split():
    pdf_bytes = _create_multi_page_pdf(1)
    dlg = CompressionCompareDialog(
        parent_window=None,
        pdf_bytes=pdf_bytes,
    )

    # Switch to wipe mode
    dlg.btn_mode_split.set_active(True)
    assert dlg.view_mode == "wipe"
    assert dlg.stack.get_visible_child_name() == "wipe"

    # Drag split position
    dlg._update_split_from_x(200.0)
    assert 0.0 <= dlg.split_pos <= 1.0

    # Draw wipe canvas
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 500)
    cr = cairo.Context(surface)
    dlg._on_draw_wipe(dlg.drawing_area, cr, 400, 500, None)

    # Switch back to side-by-side
    dlg.btn_mode_side.set_active(True)
    assert dlg.view_mode == "side"
    assert dlg.stack.get_visible_child_name() == "side"

    dlg.destroy()


def test_compare_dialog_preset_change():
    pdf_bytes = _create_multi_page_pdf(1)
    dlg = CompressionCompareDialog(
        parent_window=None,
        pdf_bytes=pdf_bytes,
    )

    dlg.radio_max.set_active(True)
    assert dlg.active_preset == PRESET_MAXIMUM

    dlg.radio_max_bw.set_active(True)
    assert dlg.active_preset == PRESET_MAX_BW
    assert dlg.gray_switch.get_sensitive() is False

    dlg.radio_high.set_active(True)
    assert dlg.active_preset == PRESET_HIGH_QUALITY
    assert dlg.gray_switch.get_sensitive() is True

    dlg.radio_lossless.set_active(True)
    assert dlg.active_preset == PRESET_LOSSLESS

    dlg.gray_switch.set_active(True)
    assert dlg.grayscale_enabled is True

    dlg.destroy()


def test_compress_dialog_has_compare_action():
    pdf_bytes = _create_multi_page_pdf(1)
    comp_dlg = CompressionDialog(
        parent_window=None,
        pdf_bytes=pdf_bytes,
        initial_filename="sample.pdf",
    )
    assert hasattr(comp_dlg, "compare_btn")
    assert hasattr(comp_dlg, "compare_row")
    assert hasattr(comp_dlg, "radio_max_bw")
    assert hasattr(comp_dlg, "row_max_bw")

    # Ensure clicking compare opens CompressionCompareDialog without crashing
    comp_dlg._on_compare_clicked(None)

    # Verify Black & White preset row is not empty
    assert comp_dlg.row_max_bw.get_title() is not None
    assert len(comp_dlg.row_max_bw.get_title()) > 0
    assert comp_dlg.row_max_bw.get_subtitle() is not None
    assert len(comp_dlg.row_max_bw.get_subtitle()) > 0

    comp_dlg.destroy()


def test_compare_dialog_save_action(monkeypatch):
    from unittest.mock import MagicMock
    from word_sys_pdf_editor.compressor import CompressionResult

    pdf_bytes = _create_multi_page_pdf(1)
    dlg = CompressionCompareDialog(
        parent_window=None,
        pdf_bytes=pdf_bytes,
        initial_filename="test_doc.pdf",
    )
    dlg.compressed_result = CompressionResult(
        pdf_bytes=pdf_bytes,
        original_size=len(pdf_bytes),
        compressed_size=len(pdf_bytes),
        savings_bytes=0,
        savings_percent=0.0,
        message="ok",
    )

    # Verify initial pictures are paintable
    assert dlg.pic_orig.get_paintable() is not None
    assert dlg.pic_comp.get_paintable() is not None

    mock_show = MagicMock()
    monkeypatch.setattr("word_sys_pdf_editor.compress_compare_dialog.show_save_file_dialog", mock_show)

    dlg._on_save_clicked(None)
    assert mock_show.called
    dlg.destroy()
