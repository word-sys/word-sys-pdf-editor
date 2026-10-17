from __future__ import annotations

import io
import os
import tempfile
import pytest
import pymupdf as fitz
from PIL import Image

from word_sys_pdf_editor.compressor import (
    PRESET_BALANCED,
    PRESET_MAXIMUM,
    PRESET_HIGH_QUALITY,
    PRESET_LOSSLESS,
    PRESET_MAX_BW,
    PRESET_TARGET,
    CompressionOptions,
    CompressionResult,
    get_preset_options,
    compress_pdf_bytes,
    solve_target_size,
    format_bytes,
)
from word_sys_pdf_editor.i18n import _STRINGS, set_language, get_language


def _create_synthetic_image_pdf(width_px: int = 800, height_px: int = 800, has_alpha: bool = False) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)

    mode = "RGBA" if has_alpha else "RGB"
    img = Image.new(mode, (width_px, height_px), color=(200, 50, 80, 180) if has_alpha else (200, 50, 80))
    for x in range(0, width_px, 20):
        for y in range(0, height_px, 20):
            img.putpixel((x, y), (50, 180, 200, 255) if has_alpha else (50, 180, 200))

    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_bytes = img_buf.getvalue()

    rect = fitz.Rect(50, 50, 350, 350)
    page.insert_image(rect, stream=img_bytes)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_get_preset_options():
    bal = get_preset_options(PRESET_BALANCED)
    assert bal.target_dpi == 150
    assert bal.jpeg_quality == 75
    assert bal.compress_images is True

    max_opt = get_preset_options(PRESET_MAXIMUM)
    assert max_opt.target_dpi == 72
    assert max_opt.jpeg_quality == 50
    assert max_opt.compress_images is True

    max_bw = get_preset_options(PRESET_MAX_BW)
    assert max_bw.target_dpi == 150
    assert max_bw.grayscale is True
    assert max_bw.monochrome_bw is True

    high = get_preset_options(PRESET_HIGH_QUALITY)
    assert high.target_dpi == 300
    assert high.jpeg_quality == 85
    assert high.compress_images is True

    lossless = get_preset_options(PRESET_LOSSLESS)
    assert lossless.target_dpi is None
    assert lossless.compress_images is False

    unknown = get_preset_options("nonexistent")
    assert unknown.target_dpi == 150


def test_format_bytes():
    assert format_bytes(500) == "500 B"
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(15 * 1024 * 1024) == "15.00 MB"
    assert format_bytes(3 * 1024 * 1024 * 1024) == "3.00 GB"


def test_compress_empty_and_invalid():
    res_empty = compress_pdf_bytes(b"")
    assert res_empty.compressed_size == 0
    assert res_empty.achieved_target is True

    res_corrupt = compress_pdf_bytes(b"not a valid pdf data")
    assert res_corrupt.achieved_target is False
    assert res_corrupt.compressed_size == len(b"not a valid pdf data")
    assert "Invalid PDF" in (res_corrupt.message or "")


def test_compress_presets_image_pdf():
    orig_bytes = _create_synthetic_image_pdf(800, 800)
    orig_len = len(orig_bytes)

    res_bal = compress_pdf_bytes(orig_bytes, get_preset_options(PRESET_BALANCED))
    assert res_bal.compressed_size < orig_len
    assert res_bal.savings_bytes > 0
    assert res_bal.savings_percent > 0
    doc_bal = fitz.open(stream=res_bal.pdf_bytes, filetype="pdf")
    assert len(doc_bal) == 1
    doc_bal.close()

    res_max = compress_pdf_bytes(orig_bytes, get_preset_options(PRESET_MAXIMUM))
    assert res_max.compressed_size < res_bal.compressed_size
    assert res_max.savings_percent > res_bal.savings_percent

    res_high = compress_pdf_bytes(orig_bytes, get_preset_options(PRESET_HIGH_QUALITY))
    assert res_high.compressed_size <= orig_len

    res_lossless = compress_pdf_bytes(orig_bytes, get_preset_options(PRESET_LOSSLESS))
    assert len(res_lossless.pdf_bytes) > 0

    res_bw = compress_pdf_bytes(orig_bytes, get_preset_options(PRESET_MAX_BW))
    assert res_bw.compressed_size < orig_len
    assert res_bw.savings_bytes > 0
    doc_bw = fitz.open(stream=res_bw.pdf_bytes, filetype="pdf")
    assert len(doc_bw) == 1
    doc_bw.close()


def test_compress_alpha_image_preservation():
    orig_bytes = _create_synthetic_image_pdf(400, 400, has_alpha=True)
    res = compress_pdf_bytes(orig_bytes, get_preset_options(PRESET_BALANCED))
    assert len(res.pdf_bytes) > 0

    doc = fitz.open(stream=res.pdf_bytes, filetype="pdf")
    page = doc[0]
    imgs = page.get_images()
    assert len(imgs) >= 1
    doc.close()


def test_compress_grayscale():
    orig_bytes = _create_synthetic_image_pdf(500, 500)
    opts_color = CompressionOptions(target_dpi=100, jpeg_quality=70, grayscale=False)
    opts_gray = CompressionOptions(target_dpi=100, jpeg_quality=70, grayscale=True)

    res_color = compress_pdf_bytes(orig_bytes, opts_color)
    res_gray = compress_pdf_bytes(orig_bytes, opts_gray)

    assert len(res_gray.pdf_bytes) > 0
    assert res_gray.compressed_size <= res_color.compressed_size


def test_solve_target_size():
    orig_bytes = _create_synthetic_image_pdf(800, 800)
    orig_len = len(orig_bytes)

    res_already = solve_target_size(orig_bytes, target_bytes=orig_len + 50000)
    assert res_already.achieved_target is True
    assert res_already.iterations_count == 1

    target_bytes = int(orig_len * 0.4)
    res_solved = solve_target_size(orig_bytes, target_bytes=target_bytes)
    assert res_solved.achieved_target is True
    assert res_solved.compressed_size <= target_bytes
    assert res_solved.iterations_count >= 1

    impossible_target = 100
    res_impossible = solve_target_size(orig_bytes, target_bytes=impossible_target)
    assert res_impossible.achieved_target is False
    assert "could not be reached" in (res_impossible.message or "")


def test_all_locales_contain_compression_keys():
    required_keys = [
        "menu_compress_document",
        "compress_title",
        "compress_preset_balanced",
        "compress_preset_maximum",
        "compress_preset_high",
        "compress_preset_lossless",
        "compress_preset_target_size",
        "compress_target_size_label",
        "compress_btn_compress",
        "compress_success",
        "compress_error",
        "compress_already_smaller",
    ]

    for lang in ["en", "tr", "fr", "de", "es", "it", "ru"]:
        assert lang in _STRINGS, f"Language '{lang}' missing in _STRINGS"
        table = _STRINGS[lang]
        for key in required_keys:
            assert key in table, f"Key '{key}' missing in language '{lang}'"
            assert isinstance(table[key], str)
            assert len(table[key].strip()) > 0


def test_compression_dialog_ui():
    from word_sys_pdf_editor.compress_dialog import CompressionDialog

    pdf_bytes = _create_synthetic_image_pdf(200, 200)
    dlg = CompressionDialog(
        parent_window=None,
        pdf_bytes=pdf_bytes,
        initial_filename="sample_test.pdf",
    )
    assert dlg.radio_bal.get_active() is True

    dlg.radio_max.set_active(True)
    assert dlg.radio_max.get_active() is True

    dlg.radio_high.set_active(True)
    assert dlg.radio_high.get_active() is True

    dlg.radio_lossless.set_active(True)
    assert dlg.radio_lossless.get_active() is True

    dlg.grayscale_switch.set_active(True)
    assert dlg.grayscale_switch.get_active() is True

    dlg.destroy()


def test_window_compress_document_action():
    from gi.repository import Gio, GLib
    from word_sys_pdf_editor.main import PdfEditorApplication
    from word_sys_pdf_editor.window import PdfEditorWindow

    app = PdfEditorApplication(
        application_id=f"org.word_sys.test_compress_{os.getpid()}",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def on_startup(a):
        win = PdfEditorWindow(application=a)
        a.window = win

        act = win.lookup_action("compress_document")
        assert act is not None
        assert act.get_enabled() is False

        win.do_close_request()
        GLib.idle_add(a.quit)

    app.connect("startup", on_startup)
    app.run([])


def test_compress_pdf_with_smask():
    import subprocess
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    img_rgba = Image.new("RGBA", (200, 200), color=(100, 150, 200, 128))
    for i in range(50, 150):
        for j in range(50, 150):
            img_rgba.putpixel((i, j), (250, 50, 50, 255))
    buf = io.BytesIO()
    img_rgba.save(buf, format="PNG")
    page.insert_image(fitz.Rect(50, 50, 250, 250), stream=buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()

    res = compress_pdf_bytes(pdf_bytes, get_preset_options(PRESET_BALANCED))
    assert res.compressed_size > 0
    assert res.achieved_target is True

    # Ensure Poppler renders without 'Bad image parameters' or syntax errors
    p = subprocess.run(
        ["pdftoppm", "-png", "-r", "72", "-", "/tmp/test_smask_check"],
        input=res.pdf_bytes,
        capture_output=True,
    )
    assert p.returncode == 0
    assert "Syntax Error" not in p.stderr.decode()

