"""Unit tests for the Universal OCR Pipeline in word_sys_pdf_editor.ocr_engine."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest
import fitz

from word_sys_pdf_editor.ocr_engine import (
    get_tessdata_user_dir,
    get_tessdata_search_dirs,
    get_available_languages,
    get_best_tessdata_dir_for_lang,
    is_scanned_page,
    analyze_document_scans,
    perform_ocr_on_pixmap,
    perform_ocr_on_page,
    extract_ocr_text_from_page,
    check_ocr_support,
    delete_user_language_model,
    download_language_model,
    SUPPORTED_LANGUAGES,
)


def test_tessdata_paths():
    user_dir = get_tessdata_user_dir()
    assert isinstance(user_dir, Path)
    assert "word-sys-pdf-editor" in str(user_dir)
    assert str(user_dir).endswith("tessdata")

    search_dirs = get_tessdata_search_dirs()
    assert len(search_dirs) >= 1
    assert user_dir == search_dirs[0]


def test_available_languages_discovery():
    langs = get_available_languages()
    assert "eng" in langs
    assert "tur" in langs
    assert "deu" in langs
    assert "fra" in langs
    assert "spa" in langs
    assert "ita" in langs
    assert "rus" in langs

    assert langs["eng"]["is_installed"] is True
    assert langs["eng"]["source"] in ("system", "user", "bundle")
    assert langs["eng"]["path"] is not None


def test_get_best_tessdata_dir():
    best_dir = get_best_tessdata_dir_for_lang("eng")
    assert os.path.isdir(best_dir)
    assert os.path.isfile(os.path.join(best_dir, "eng.traineddata"))

    with pytest.raises(FileNotFoundError):
        get_best_tessdata_dir_for_lang("nonexistent_lang_xyz")


def test_is_scanned_page_detection():
    doc = fitz.open()
    page1 = doc.new_page(width=400, height=300)
    page1.insert_text(fitz.Point(50, 50), "This is a regular digital PDF document with selectable text characters.", fontsize=14)
    analysis1 = is_scanned_page(page1)
    assert analysis1.is_scanned is False
    assert analysis1.has_selectable_text is True
    assert analysis1.text_char_count > 20
    assert analysis1.image_count == 0

    page2 = doc.new_page(width=400, height=300)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 300, 200), 1)
    page2.insert_image(fitz.Rect(20, 20, 380, 280), pixmap=pix)
    analysis2 = is_scanned_page(page2)
    assert analysis2.is_scanned is True
    assert analysis2.has_selectable_text is False
    assert analysis2.image_count >= 1
    assert analysis2.image_coverage_ratio >= 0.35

    doc_analysis = analyze_document_scans(doc)
    assert doc_analysis["total_pages"] == 2
    assert doc_analysis["scanned_count"] == 1
    assert doc_analysis["scanned_pages"] == [1]


def test_perform_ocr_on_synthetic_raster_image():
    doc = fitz.open()
    page = doc.new_page(width=400, height=120)
    page.draw_rect(fitz.Rect(0, 0, 400, 120), color=(1, 1, 1), fill=(1, 1, 1))
    page.insert_text(fitz.Point(30, 60), "HELLO WORLD OCR", fontsize=18, color=(0, 0, 0))
    pix = page.get_pixmap(dpi=150)

    ocr_bytes = perform_ocr_on_pixmap(pix, language="eng")
    assert isinstance(ocr_bytes, (bytes, bytearray))
    assert len(ocr_bytes) > 0
    ocr_doc = fitz.open(stream=ocr_bytes)
    assert len(ocr_doc) == 1
    extracted = ocr_doc[0].get_text()
    assert "WORLD" in extracted or "HELLO" in extracted or "OCR" in extracted


def test_perform_ocr_on_page():
    doc = fitz.open()
    page = doc.new_page(width=400, height=120)
    page.draw_rect(fitz.Rect(0, 0, 400, 120), color=(1, 1, 1), fill=(1, 1, 1))
    page.insert_text(fitz.Point(30, 60), "AUTOMATED OCR TEST", fontsize=18, color=(0, 0, 0))

    text = extract_ocr_text_from_page(doc, 0, language="eng")
    assert "AUTOMATED" in text or "TEST" in text or "OCR" in text


def test_check_ocr_support():
    supported, msg = check_ocr_support()
    assert supported is True
    assert "ready" in msg.lower()


def test_delete_user_language_model_safety():
    # Safety test: trying to delete a system language model should return False
    # because it is not in the user profile directory
    res = delete_user_language_model("eng")
    # If user model didn't exist in ~/.local/share/..., it safely returns False
    assert res is False


def test_download_language_model_mock():
    import unittest.mock as mock
    with tempfile.TemporaryDirectory() as tmpdir:
        with mock.patch("word_sys_pdf_editor.ocr_engine.get_tessdata_user_dir", return_value=Path(tmpdir)):
            mock_resp = mock.MagicMock()
            mock_resp.headers.get.return_value = "100"
            mock_resp.read.side_effect = [b"a" * 50, b"b" * 50, b""]
            mock_cm = mock.MagicMock()
            mock_cm.__enter__.return_value = mock_resp

            progress_reports = []
            def on_progress(curr, total):
                progress_reports.append((curr, total))

            with mock.patch("urllib.request.urlopen", return_value=mock_cm):
                target = download_language_model("testlang", progress_callback=on_progress)
                assert target.is_file()
                assert target.read_bytes() == b"a" * 50 + b"b" * 50
                assert progress_reports[-1] == (100, 100)

                # Now test deletion of this user model
                assert delete_user_language_model("testlang") is True
                assert not target.exists()


def test_download_language_model_cancellation():
    import unittest.mock as mock
    with tempfile.TemporaryDirectory() as tmpdir:
        with mock.patch("word_sys_pdf_editor.ocr_engine.get_tessdata_user_dir", return_value=Path(tmpdir)):
            mock_resp = mock.MagicMock()
            mock_resp.headers.get.return_value = "100"
            mock_resp.read.side_effect = [b"a" * 50, b"b" * 50]
            mock_cm = mock.MagicMock()
            mock_cm.__enter__.return_value = mock_resp

            cancelled = False
            def cancel_check():
                return True

            with mock.patch("urllib.request.urlopen", return_value=mock_cm):
                with pytest.raises(InterruptedError):
                    download_language_model("cancelled_lang", cancel_check=cancel_check)

            # Ensure no temporary files are left over
            tmp_files = list(Path(tmpdir).glob("*.tmp*"))
            assert len(tmp_files) == 0

