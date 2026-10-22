import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz

from word_sys_pdf_editor.i18n import _STRINGS, _
from word_sys_pdf_editor.locales import (
    STRINGS_DE,
    STRINGS_ES,
    STRINGS_FR,
    STRINGS_IT,
    STRINGS_RU,
)
from word_sys_pdf_editor.ocr_engine import (
    SUPPORTED_LANGUAGES,
    get_best_tessdata_dir_for_lang,
    resolve_compound_language_model_dirs,
    detect_page_orientation,
    perform_ocr_on_page,
)


def test_bilingual_strings_completeness_across_all_locales():
    """Verify that all bilingual OCR keys exist in all 7 supported UI languages."""
    required_keys = [
        "ocr_lang_primary_label",
        "ocr_lang_secondary_label",
        "ocr_lang_secondary_desc",
        "ocr_lang_none",
        "ocr_lang_secondary_need_more",
        "ocr_mode_bilingual_active",
        "ocr_models_multilang_info",
    ]
    locales = [
        ("EN", _STRINGS["en"]),
        ("TR", _STRINGS["tr"]),
        ("FR", STRINGS_FR),
        ("DE", STRINGS_DE),
        ("ES", STRINGS_ES),
        ("IT", STRINGS_IT),
        ("RU", STRINGS_RU),
    ]
    for loc_name, strings_dict in locales:
        for k in required_keys:
            assert k in strings_dict, f"Missing key '{k}' in {loc_name} locale"
            assert len(strings_dict[k].strip()) > 0, f"Empty string for key '{k}' in {loc_name}"


def test_resolve_compound_language_model_dirs_single():
    """Test resolving tessdata directory for a single language code."""
    fake_langs = {
        "eng": {"path": "/usr/share/tessdata/eng.traineddata", "is_installed": True}
    }
    with patch("word_sys_pdf_editor.ocr_engine.get_available_languages", return_value=fake_langs):
        res = resolve_compound_language_model_dirs("eng")
        assert res == [Path("/usr/share/tessdata")]


def test_resolve_compound_language_model_dirs_bilingual():
    """Test resolving tessdata directories for compound bilingual language codes."""
    fake_langs = {
        "eng": {"path": "/usr/share/tessdata/eng.traineddata", "is_installed": True},
        "tur": {"path": "/home/user/.local/share/tessdata/tur.traineddata", "is_installed": True},
    }
    with patch("word_sys_pdf_editor.ocr_engine.get_available_languages", return_value=fake_langs):
        dirs = resolve_compound_language_model_dirs("eng+tur")
        assert dirs == [Path("/usr/share/tessdata"), Path("/home/user/.local/share/tessdata")]


def test_resolve_compound_language_model_dirs_deduplicate():
    """Test that duplicate directories are deduplicated while preserving order."""
    fake_langs = {
        "eng": {"path": "/usr/share/tessdata/eng.traineddata", "is_installed": True},
        "fra": {"path": "/usr/share/tessdata/fra.traineddata", "is_installed": True},
        "deu": {"path": "/usr/share/tessdata/deu.traineddata", "is_installed": True},
    }
    with patch("word_sys_pdf_editor.ocr_engine.get_available_languages", return_value=fake_langs):
        dirs = resolve_compound_language_model_dirs("eng+fra+deu")
        assert dirs == [Path("/usr/share/tessdata")]


def test_get_best_tessdata_dir_for_lang_compound_same_dir():
    """Verify get_best_tessdata_dir_for_lang returns direct folder when models share directory."""
    fake_langs = {
        "eng": {"path": "/usr/share/tessdata/eng.traineddata", "is_installed": True},
        "tur": {"path": "/usr/share/tessdata/tur.traineddata", "is_installed": True},
    }
    with patch("word_sys_pdf_editor.ocr_engine.get_available_languages", return_value=fake_langs):
        d = get_best_tessdata_dir_for_lang("eng+tur")
        assert d == "/usr/share/tessdata"


def test_perform_ocr_on_page_compound_resolution():
    """Test that perform_ocr_on_page properly prepares tessdata for compound languages."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    
    mock_ocr_doc = fitz.open()

    with patch("word_sys_pdf_editor.ocr_engine.get_best_tessdata_dir_for_lang", return_value="/usr/share/tessdata") as mock_best:
        with patch.object(fitz.Pixmap, "pdfocr_tobytes", create=True, return_value=b"%PDF-1.4 mock") as mock_ocr_pix:
            with patch("fitz.open", return_value=mock_ocr_doc):
                res = perform_ocr_on_page(doc, page_num=0, language="eng+tur", dpi=150)
                assert res is mock_ocr_doc
                mock_best.assert_called_once_with("eng+tur")
                mock_ocr_pix.assert_called_once()
                call_kwargs = mock_ocr_pix.call_args[1]
                assert call_kwargs["language"] == "eng+tur"
                assert call_kwargs["tessdata"] == "/usr/share/tessdata"
    doc.close()


def test_detect_page_orientation_compound_lang():
    """Test detect_page_orientation accepts compound languages without crashing."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)

    with patch("word_sys_pdf_editor.ocr_engine.get_best_tessdata_dir_for_lang", return_value="/usr/share/tessdata"):
        with patch("word_sys_pdf_editor.ocr_engine.perform_ocr_on_pixmap", return_value=b"%PDF-1.4 mock"):
            with patch("fitz.open") as mock_open:
                mock_test_doc = MagicMock()
                mock_test_page = MagicMock()
                mock_test_page.get_text.return_value = [(0, 0, 10, 10, "Hello", 0, 0, 0)]
                mock_test_doc.__getitem__.return_value = mock_test_page
                mock_open.return_value = mock_test_doc

                angle = detect_page_orientation(page, dpi=100, language="eng+tur")
                assert angle in (0, 90, 180, 270)
    doc.close()


def test_ocr_dialog_bilingual_selection_flow():
    """Verify OCRDialog initializes with secondary language row and toggling works as expected."""
    from word_sys_pdf_editor.ocr_dialog import OCRDialog

    doc = fitz.open()
    doc.new_page(width=300, height=300)

    fake_langs = {
        "eng": {"name": "English", "native": "English", "is_installed": True, "source": "system", "path": "/usr/share/tessdata/eng.traineddata"},
        "tur": {"name": "Turkish", "native": "Türkçe", "is_installed": True, "source": "system", "path": "/usr/share/tessdata/tur.traineddata"},
    }

    with patch("word_sys_pdf_editor.ocr_dialog.get_available_languages", return_value=fake_langs):
        dialog = OCRDialog(parent_window=None, doc=doc, current_page_num=0)
        assert dialog.lang_row is not None
        assert dialog.secondary_lang_row is not None

        # Check installed language count in primary and secondary models
        # primary: eng, tur -> 2 items
        assert dialog.lang_model.get_n_items() == 2
        # secondary: None, eng, tur -> 3 items
        assert dialog.secondary_lang_model.get_n_items() == 3

        # Secondary default should be None (0)
        assert dialog.secondary_lang_row.get_selected() == 0

        # Change secondary to Turkish (index 2: None=0, eng=1, tur=2)
        dialog.secondary_lang_row.set_selected(2)
        subtitle = dialog.secondary_lang_row.get_subtitle()
        assert "Bilingual" in subtitle or "English" in subtitle

        # If user selects English for secondary as well (same as primary), it auto-resets to None (0)
        dialog.secondary_lang_row.set_selected(1)
        assert dialog.secondary_lang_row.get_selected() == 0

        dialog.close()
    doc.close()

