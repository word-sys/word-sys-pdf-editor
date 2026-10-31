"""Consolidated OCR Test Suite for word-sys-pdf-editor.

This suite merges bilingual support, deskew algorithms, OCR dialog UI,
engine discovery, auto-inversion improvements, overlays, search selection,
and transparent text layer embedding into a single unified test module.
"""


# ============================================================================
# SECTION: test_ocr_bilingual.py
# ============================================================================

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



# ============================================================================
# SECTION: test_ocr_deskew.py
# ============================================================================

"""Automated unit and integration tests for OCR Page Deskew and Auto-Orientation."""

import io
import fitz
import pytest
from PIL import Image, ImageDraw

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.ocr_engine import (
    detect_page_skew_angle,
    detect_page_orientation,
    deskew_scanned_page,
    is_scanned_page,
)
from word_sys_pdf_editor.undo_manager import EmbedOCRTextCommand


def _create_tilted_scanned_pdf(angle_deg: float, width: float = 500, height: float = 350, dpi: int = 150) -> fitz.Document:
    """Create a synthetic 1-page scanned PDF tilted by angle_deg degrees."""
    doc = fitz.open()
    p = doc.new_page(width=width, height=height)

    # Render text lines onto high-res PIL canvas
    img = Image.new("RGB", (int(width * 2), int(height * 2)), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for y in range(80, int(height * 2) - 80, 70):
        draw.text(
            (100, y),
            "Sample scanned document paragraph for skew and rotation test.",
            fill=(0, 0, 0),
        )

    # In PIL, rotate(angle) rotates counter-clockwise.
    # To tilt text clockwise by angle_deg, rotate by -angle_deg:
    tilted = img.rotate(-angle_deg, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255))
    buf = io.BytesIO()
    tilted.save(buf, format="PNG")

    p.insert_image(p.rect, stream=buf.getvalue())
    return doc


def test_detect_page_skew_angle_precision():
    """Verify skew detection calculates angles with high accuracy."""
    # Test positive clockwise tilt (3.5 deg)
    doc_pos = _create_tilted_scanned_pdf(angle_deg=3.5)
    skew_pos = detect_page_skew_angle(doc_pos[0])
    assert pytest.approx(skew_pos, abs=0.6) == 3.5
    doc_pos.close()

    # Test negative tilt (-4.0 deg)
    doc_neg = _create_tilted_scanned_pdf(angle_deg=-4.0)
    skew_neg = detect_page_skew_angle(doc_neg[0])
    assert pytest.approx(skew_neg, abs=0.6) == -4.0
    doc_neg.close()


def test_detect_page_skew_straight_page_invariance():
    """Verify straight pages return 0.0 without false positives."""
    doc = _create_tilted_scanned_pdf(angle_deg=0.0)
    skew = detect_page_skew_angle(doc[0])
    assert skew == 0.0
    doc.close()


def test_deskew_scanned_page_levels_content():
    """Verify deskew_scanned_page permanently straightens the tilted raster scan."""
    doc = _create_tilted_scanned_pdf(angle_deg=3.5)
    page = doc[0]
    initial_skew = detect_page_skew_angle(page)
    assert abs(initial_skew) >= 3.0

    # Straighten the page
    success = deskew_scanned_page(doc, 0, initial_skew)
    assert success is True

    # After straightening, detected skew angle must drop to 0.0 (straight)
    post_skew = detect_page_skew_angle(doc[0])
    assert post_skew == 0.0
    doc.close()


def test_detect_page_orientation():
    """Verify coarse orientation correctly identifies upright vs rotated pages."""
    doc = fitz.open()
    p = doc.new_page(width=500, height=350)
    p.insert_text((50, 80), "The quick brown fox jumps over the lazy dog in this sample document.", fontsize=14)
    p.insert_text((50, 120), "Optical Character Recognition test page with standard English paragraphs.", fontsize=14)
    p.insert_text((50, 160), "Additional line of text to evaluate horizontal and vertical projection profiles.", fontsize=14)

    # 0 degrees (Upright)
    orient_0 = detect_page_orientation(p)
    assert orient_0 == 0

    # 90 degrees
    p.set_rotation(90)
    orient_90 = detect_page_orientation(p)
    assert orient_90 == 90

    doc.close()


def test_embed_ocr_text_layer_with_auto_deskew():
    """Verify embed_ocr_text_layer_on_page automatically straightens tilted scans and embeds text."""
    doc = _create_tilted_scanned_pdf(angle_deg=3.8)
    assert is_scanned_page(doc[0]).is_scanned is True

    res = pdf_handler.embed_ocr_text_layer_on_page(
        doc,
        page_num=0,
        language="eng",
        dpi=150,
        auto_deskew=True,
        auto_rotate=False,
    )
    assert res["success"] is True
    assert res["words_embedded"] >= 5

    # Page should be straightened
    final_skew = detect_page_skew_angle(doc[0])
    assert final_skew == 0.0

    # Words must be searchable on the straightened page
    hits = doc[0].search_for("document") or doc[0].search_for("scanned")
    assert len(hits) >= 1
    doc.close()


def test_deskew_undo_reverts_to_original_tilted_scan():
    """Verify EmbedOCRTextCommand undo cleanly reverts to the original pre-deskew tilted scan."""
    doc = _create_tilted_scanned_pdf(angle_deg=3.5)
    page_num = 0

    class MockWindow:
        def __init__(self, document):
            self.doc = document
            self.current_page_index = 0
            self.current_page = 0
            self._active_session = None
            self.document_modified = False

    win = MockWindow(doc)
    cmd = EmbedOCRTextCommand(
        win,
        page_indices=[0],
        language="eng",
        dpi=150,
        auto_deskew=True,
        auto_rotate=False,
    )
    cmd.execute()
    assert detect_page_skew_angle(doc[0]) == 0.0

    # Undo
    cmd.undo()
    # Should revert to original tilted scan (~3.5 deg)
    reverted_skew = detect_page_skew_angle(doc[0])
    assert pytest.approx(reverted_skew, abs=0.8) == 3.5
    doc.close()


# ============================================================================
# SECTION: test_ocr_dialog.py
# ============================================================================

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



# ============================================================================
# SECTION: test_ocr_engine.py
# ============================================================================

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



# ============================================================================
# SECTION: test_ocr_improvements.py
# ============================================================================

import pytest
from unittest.mock import MagicMock, patch
import fitz

from word_sys_pdf_editor.i18n import _STRINGS
from word_sys_pdf_editor.locales import (
    STRINGS_DE,
    STRINGS_ES,
    STRINGS_FR,
    STRINGS_IT,
    STRINGS_RU,
)
from word_sys_pdf_editor.ocr_engine import (
    auto_invert_dark_background,
    estimate_word_confidence,
    perform_ocr_on_page,
)
from word_sys_pdf_editor.window import PdfEditorWindow


def test_ocr_auto_invert_strings_all_locales():
    """Verify that ocr_auto_invert and ocr_auto_invert_desc exist across all 7 supported locales."""
    required_keys = ["ocr_auto_invert", "ocr_auto_invert_desc"]
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


def test_auto_invert_dark_background_detection():
    """Test that a dark pixmap (e.g. white text on black background) is inverted."""
    # Create a small completely dark pixmap (RGB 0,0,0)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 10, 10), False)
    pix.clear_with(0x000000)

    # auto_invert should detect darkness and invert to bright
    inv_pix = auto_invert_dark_background(pix, threshold=120)
    samples = inv_pix.samples
    # Check that pixels are now high luminance (inverted)
    assert samples[0] > 200
    assert samples[1] > 200
    assert samples[2] > 200


def test_auto_invert_light_background_preserved():
    """Test that an already light pixmap is not inverted."""
    # Create a light pixmap (RGB 255, 255, 255)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 10, 10), False)
    pix.clear_with(0xFFFFFF)

    res_pix = auto_invert_dark_background(pix, threshold=120)
    samples = res_pix.samples
    assert samples[0] == 255
    assert samples[1] == 255
    assert samples[2] == 255


def test_estimate_word_confidence():
    """Verify that estimate_word_confidence correctly scores clean words vs OCR gibberish."""
    # Clean words
    assert estimate_word_confidence("Invoice") >= 0.85
    assert estimate_word_confidence("Application") >= 0.85
    assert estimate_word_confidence("12345") >= 0.80

    # Short / punctuation / symbols
    assert estimate_word_confidence("a") <= 0.70
    assert estimate_word_confidence("...") <= 0.40
    assert estimate_word_confidence("@#$!") <= 0.40
    assert estimate_word_confidence("x") <= 0.70


def test_perform_ocr_on_page_auto_invert():
    """Verify perform_ocr_on_page accepts auto_invert and passes correctly to pixmap handling."""
    doc = fitz.open()
    doc.new_page(width=200, height=200)

    mock_ocr_doc = fitz.open()

    with patch("word_sys_pdf_editor.ocr_engine.get_best_tessdata_dir_for_lang", return_value="/usr/share/tessdata"):
        with patch.object(fitz.Pixmap, "pdfocr_tobytes", create=True, return_value=b"%PDF-1.4 mock") as mock_ocr_pix:
            with patch("fitz.open", return_value=mock_ocr_doc):
                res = perform_ocr_on_page(doc, page_num=0, language="eng", dpi=100, auto_invert=True)
                assert res is mock_ocr_doc
                mock_ocr_pix.assert_called_once()
    doc.close()


def test_extract_ocr_word_boxes_with_cache():
    """Verify _extract_ocr_word_boxes retrieves cached confidence ratings from document."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)

    # Attach mock cached OCR words to document
    doc._ocr_words_cache = {
        0: [
            {"bbox": (10, 10, 50, 25), "text": "Header", "confidence": 0.95},
            {"bbox": (10, 30, 45, 42), "text": "~!#", "confidence": 0.35},
        ]
    }

    boxes = PdfEditorWindow._extract_ocr_word_boxes(page)
    assert len(boxes) == 2
    # Verify 5-tuple unpacking compatibility
    x0, y0, x1, y1, text = boxes[0]
    assert text == "Header"
    assert boxes[0].confidence == 0.95
    assert boxes[1][4] == "~!#"
    assert boxes[1].confidence == 0.35

    doc.close()


def test_draw_ocr_overlay_confidence_heatmaps():
    """Verify _draw_ocr_overlay correctly renders green, amber, and red confidence heatmap elements."""
    cr_mock = MagicMock()
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)

    # Cache 3 words: High (>=80%), Medium (50-79%), Low (<50%)
    doc._ocr_words_cache = {
        0: [
            {"bbox": (10, 10, 50, 20), "text": "HighConf", "confidence": 0.92},
            {"bbox": (10, 25, 50, 35), "text": "MedConf", "confidence": 0.65},
            {"bbox": (10, 40, 50, 50), "text": "LowConf", "confidence": 0.30},
        ]
    }

    PdfEditorWindow._draw_ocr_overlay(cr_mock, page, zoom=1.0)

    # cr.save and cr.restore must be called
    cr_mock.save.assert_called_once()
    cr_mock.restore.assert_called_once()

    # Check set_source_rgba calls for the 3 confidence categories
    rgba_calls = [c[0] for c in cr_mock.set_source_rgba.call_args_list]

    # High conf green
    assert any(c[0] == 0.15 and c[1] == 0.68 for c in rgba_calls)
    # Medium conf amber
    assert any(c[0] == 0.92 and c[1] == 0.65 for c in rgba_calls)
    # Low conf red
    assert any(c[0] == 0.88 and c[1] == 0.15 for c in rgba_calls)

    doc.close()


# ============================================================================
# SECTION: test_ocr_overlay.py
# ============================================================================

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


# ============================================================================
# SECTION: test_ocr_search_selection.py
# ============================================================================

"""Automated unit tests for Scanned Document Text Selection, Copy & Search Integration."""

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
    assert "3" in win.ocr_banner_label.text and "5" in win.ocr_banner_label.text
    assert "{0}" not in win.ocr_banner_label.text and "{1}" not in win.ocr_banner_label.text

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


def test_search_engine_whole_word():
    """Test whole-word boundary matching vs substring matching."""
    doc = fitz.open()
    p = doc.new_page(width=500, height=300)
    p.insert_text(fitz.Point(50, 50), "password pass passport bypass", fontsize=14)
    p.insert_text(fitz.Point(50, 100), "The test was testing tested scripts.", fontsize=14)

    engine = DocumentSearchEngine()

    # Substring search matches 4 occurrences of "pass"
    matches_sub = engine.search(doc, "pass", whole_word=False)
    assert len(matches_sub) == 4

    # Whole word search matches only 1 exact standalone occurrence of "pass"
    matches_ww = engine.search(doc, "pass", whole_word=True)
    assert len(matches_ww) == 1
    assert matches_ww[0].text == "pass"

    # Whole word for "test" matches "test", not "testing" or "tested"
    matches_test_ww = engine.search(doc, "test", whole_word=True)
    assert len(matches_test_ww) == 1
    assert matches_test_ww[0].text == "test"

    # Substring for "test" matches 3 occurrences
    matches_test_sub = engine.search(doc, "test", whole_word=False)
    assert len(matches_test_sub) == 3

    doc.close()


def test_search_engine_circular_wrapping():
    """Test that circular wrap boundaries set last_wrapped attribute correctly."""
    doc = _create_multi_page_pdf()
    engine = DocumentSearchEngine()

    # Search for "world" (3 matches across pages 0, 1, 2)
    engine.search(doc, "world")
    assert engine.current_index == 0
    assert engine.last_wrapped is False

    # Next -> index 1 (no wrap)
    engine.next_match()
    assert engine.current_index == 1
    assert engine.last_wrapped is False

    # Next -> index 2 (no wrap)
    engine.next_match()
    assert engine.current_index == 2
    assert engine.last_wrapped is False

    # Next -> index 0 (WRAPPED from end to start!)
    engine.next_match()
    assert engine.current_index == 0
    assert engine.last_wrapped is True

    # Next -> index 1 (wrap resets to False)
    engine.next_match()
    assert engine.current_index == 1
    assert engine.last_wrapped is False

    # Prev -> index 0 (no wrap)
    engine.prev_match()
    assert engine.current_index == 0
    assert engine.last_wrapped is False

    # Prev -> index 2 (WRAPPED from start to end!)
    engine.prev_match()
    assert engine.current_index == 2
    assert engine.last_wrapped is True

    # Prev -> index 1 (wrap resets to False)
    engine.prev_match()
    assert engine.current_index == 1
    assert engine.last_wrapped is False

    doc.close()


def test_search_engine_accent_diacritics_normalization():
    """Test searching with accent/diacritic insensitive matching."""
    doc = fitz.open()
    p = doc.new_page(width=500, height=300)
    p.insert_text(fitz.Point(50, 60), "Please review my résumé at the café.", fontsize=14)
    p.insert_text(fitz.Point(50, 120), "Istanbul ve Türkiye için çözüm üretin.", fontsize=14)

    engine = DocumentSearchEngine()

    # Searching plain ASCII "resume" finds "résumé"
    matches_resume = engine.search(doc, "resume")
    assert len(matches_resume) == 1
    assert "résumé" in matches_resume[0].text or "resume" in matches_resume[0].text.lower()

    # Searching plain ASCII "cafe" finds "café"
    matches_cafe = engine.search(doc, "cafe")
    assert len(matches_cafe) == 1

    # Searching plain ASCII "turkiye" finds "Türkiye"
    matches_turkiye = engine.search(doc, "turkiye", case_sensitive=False)
    assert len(matches_turkiye) == 1

    # Searching plain ASCII "cozum" finds "çözüm"
    matches_cozum = engine.search(doc, "cozum", case_sensitive=False)
    assert len(matches_cozum) == 1

    # Searching "istanbul" finds "Istanbul"
    matches_ist = engine.search(doc, "istanbul", case_sensitive=False)
    assert len(matches_ist) == 1

    # Exact accented search still works
    matches_accented = engine.search(doc, "résumé")
    assert len(matches_accented) == 1

    doc.close()





# ============================================================================
# SECTION: test_ocr_text_layer.py
# ============================================================================

"""Automated unit tests for Transparent Searchable Text Layer Embedding."""

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


def test_streaming_ocr_incremental_page_delivery_and_single_undo():
    """Verify per-page OCR results are embedded incrementally as each page completes and share a single undo command."""
    from word_sys_pdf_editor.ocr_engine import StreamingOCRPipeline, format_ocr_eta
    from word_sys_pdf_editor.window import PdfEditorWindow

    doc = _create_scanned_pdf([
        [(40, 80, "STREAM PAGE ONE READY")],
        [(40, 80, "STREAM PAGE TWO READY")],
        [(40, 80, "STREAM PAGE THREE READY")],
    ])

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
            self.status_label = MagicMock()
            self.ocr_banner = MagicMock()
            self.ocr_banner_label = MagicMock()
            self.ocr_banner_progress = MagicMock()
            self.ocr_banner_pause_btn = MagicMock()
            self.ocr_banner_cancel_btn = MagicMock()
            self._ocr_cancel_requested = False
            self._ocr_paused = False
            self._active_ocr_pipeline = None
            self._active_streaming_ocr_cmd = None
            self.pdf_view = DummyView()

        def _update_ui_state(self):
            pass

        def _update_undo_redo_buttons(self):
            pass

        show_ocr_banner = PdfEditorWindow.show_ocr_banner
        update_ocr_banner = PdfEditorWindow.update_ocr_banner
        hide_ocr_banner = PdfEditorWindow.hide_ocr_banner
        _on_ocr_banner_pause_clicked = PdfEditorWindow._on_ocr_banner_pause_clicked
        _on_ocr_banner_cancel_clicked = PdfEditorWindow._on_ocr_banner_cancel_clicked
        begin_streaming_ocr_session = PdfEditorWindow.begin_streaming_ocr_session
        _on_ocr_page_streamed = PdfEditorWindow._on_ocr_page_streamed
        finish_streaming_ocr_session = PdfEditorWindow.finish_streaming_ocr_session
        start_streaming_ocr = PdfEditorWindow.start_streaming_ocr

    win = DummyWindow(doc)

    def fake_ocr_page(d, page_num, **_kwargs):
        res_doc = fitz.open()
        rp = res_doc.new_page(width=d[page_num].rect.width, height=d[page_num].rect.height)
        rp.insert_text(fitz.Point(40, 80), f"STREAMED_TOKEN_P{page_num}", fontsize=16)
        return res_doc

    mid_stream_assertions = []

    def on_page_ready(p_num, _payload, prog):
        # When page 0 is ready, page 0 must already be searchable while pages 1 and 2 are still un-OCR'd!
        if p_num == 0:
            p0_hits = doc[0].search_for("STREAMED_TOKEN_P0")
            p1_text = doc[1].get_text().strip()
            p2_text = doc[2].get_text().strip()
            mid_stream_assertions.append((len(p0_hits), p1_text, p2_text, prog.get("eta_seconds"), len(win.editable_texts)))

    with patch("word_sys_pdf_editor.ocr_engine.perform_ocr_on_page", side_effect=fake_ocr_page), \
         patch("word_sys_pdf_editor.ocr_engine.get_best_tessdata_dir_for_lang", return_value="/usr/share/tessdata"):
        win.start_streaming_ocr(
            target_pages=[0, 1, 2],
            language="eng",
            dpi=150,
            auto_deskew=False,
            auto_rotate=False,
            sync=True,
            on_page_ready=on_page_ready,
        )

    assert len(mid_stream_assertions) == 1
    p0_hit_count, p1_mid_text, p2_mid_text, eta_sec, p0_editable_count = mid_stream_assertions[0]
    assert p0_hit_count >= 1
    assert p1_mid_text == ""
    assert p2_mid_text == ""
    assert eta_sec is not None and eta_sec > 0
    assert format_ocr_eta(eta_sec).startswith("~")
    assert p0_editable_count >= 1

    # All 3 pages are now searchable
    for i in range(3):
        assert len(doc[i].search_for(f"STREAMED_TOKEN_P{i}")) >= 1

    # Undo is a single command for the entire 3-page streaming batch
    assert len(win.undo_manager.undo_stack) == 1
    win.undo_manager.undo()
    for i in range(3):
        assert doc[i].get_text().strip() == ""
    assert win.document_modified is False

    # Redo restores all 3 pages in one step
    win.undo_manager.redo()
    for i in range(3):
        assert len(doc[i].search_for(f"STREAMED_TOKEN_P{i}")) >= 1
    assert win.document_modified is True

    doc.close()


def test_streaming_ocr_cancel_preserves_finished_pages_and_stops_remaining():
    """Verify cancelling mid-stream stops remaining pages without corrupting finished ones and keeps a single undo command."""
    from word_sys_pdf_editor.window import PdfEditorWindow

    doc = _create_scanned_pdf([
        [(40, 80, "PAGE ZERO")],
        [(40, 80, "PAGE ONE")],
        [(40, 80, "PAGE TWO")],
    ])

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
            self.status_label = MagicMock()
            self.ocr_banner = MagicMock()
            self.ocr_banner_label = MagicMock()
            self.ocr_banner_progress = MagicMock()
            self.ocr_banner_pause_btn = MagicMock()
            self.ocr_banner_cancel_btn = MagicMock()
            self._ocr_cancel_requested = False
            self._ocr_paused = False
            self._active_ocr_pipeline = None
            self._active_streaming_ocr_cmd = None
            self.pdf_view = DummyView()

        def _update_ui_state(self):
            pass

        def _update_undo_redo_buttons(self):
            pass

        show_ocr_banner = PdfEditorWindow.show_ocr_banner
        update_ocr_banner = PdfEditorWindow.update_ocr_banner
        hide_ocr_banner = PdfEditorWindow.hide_ocr_banner
        _on_ocr_banner_pause_clicked = PdfEditorWindow._on_ocr_banner_pause_clicked
        _on_ocr_banner_cancel_clicked = PdfEditorWindow._on_ocr_banner_cancel_clicked
        begin_streaming_ocr_session = PdfEditorWindow.begin_streaming_ocr_session
        _on_ocr_page_streamed = PdfEditorWindow._on_ocr_page_streamed
        finish_streaming_ocr_session = PdfEditorWindow.finish_streaming_ocr_session
        start_streaming_ocr = PdfEditorWindow.start_streaming_ocr

    win = DummyWindow(doc)
    calls = []

    def fake_ocr_page(d, page_num, **_kwargs):
        calls.append(page_num)
        res_doc = fitz.open()
        rp = res_doc.new_page(width=d[page_num].rect.width, height=d[page_num].rect.height)
        rp.insert_text(fitz.Point(40, 80), f"CANCEL_TEST_P{page_num}", fontsize=16)
        return res_doc

    def cancel_after_page_one(p_num, _payload, _prog):
        if p_num == 1:
            win._on_ocr_banner_cancel_clicked(None)

    with patch("word_sys_pdf_editor.ocr_engine.perform_ocr_on_page", side_effect=fake_ocr_page), \
         patch("word_sys_pdf_editor.ocr_engine.get_best_tessdata_dir_for_lang", return_value="/usr/share/tessdata"):
        win.start_streaming_ocr(
            target_pages=[0, 1, 2],
            language="eng",
            dpi=150,
            auto_deskew=False,
            auto_rotate=False,
            sync=True,
            on_page_ready=cancel_after_page_one,
        )

    # Only pages 0 and 1 were processed; page 2 was never started
    assert calls == [0, 1]
    assert len(doc[0].search_for("CANCEL_TEST_P0")) >= 1
    assert len(doc[1].search_for("CANCEL_TEST_P1")) >= 1
    assert doc[2].get_text().strip() == ""

    # Finished pages (0 and 1) are grouped into a single undo command
    assert len(win.undo_manager.undo_stack) == 1
    win.undo_manager.undo()
    assert doc[0].get_text().strip() == ""
    assert doc[1].get_text().strip() == ""
    assert doc[2].get_text().strip() == ""

    doc.close()


def test_streaming_ocr_pause_resume_and_eta_helpers():
    """Verify pause/resume controls on StreamingOCRPipeline and live ETA formatting."""
    import threading
    from word_sys_pdf_editor.ocr_engine import StreamingOCRPipeline, format_ocr_eta

    assert format_ocr_eta(None) == ""
    assert format_ocr_eta(0) == "0s"
    assert format_ocr_eta(8.2) == "~8s"
    assert format_ocr_eta(60.0) == "~1m"
    assert format_ocr_eta(85.0) == "~1m 25s"

    doc = _create_scanned_pdf([
        [(40, 80, "PAUSE ONE")],
        [(40, 80, "PAUSE TWO")],
    ])

    page0_done = threading.Event()
    finished_evt = threading.Event()

    def fake_ocr_page(d, page_num, **_kwargs):
        res_doc = fitz.open()
        rp = res_doc.new_page(width=d[page_num].rect.width, height=d[page_num].rect.height)
        rp.insert_text(fitz.Point(40, 80), f"PAUSED_P{page_num}", fontsize=16)
        return res_doc

    pipeline_ref = {}

    def on_page_ready(p_num, _payload, _prog):
        if p_num == 0:
            pipeline_ref["p"].pause()
            page0_done.set()

    def on_finished(_summary):
        finished_evt.set()

    with patch("word_sys_pdf_editor.ocr_engine.perform_ocr_on_page", side_effect=fake_ocr_page), \
         patch("word_sys_pdf_editor.ocr_engine.get_best_tessdata_dir_for_lang", return_value="/usr/share/tessdata"):
        pipeline = StreamingOCRPipeline(
            doc=doc,
            target_pages=[0, 1],
            language="eng",
            dpi=150,
            auto_deskew=False,
            auto_rotate=False,
            on_page_ready=on_page_ready,
            on_finished=on_finished,
        )
        pipeline_ref["p"] = pipeline
        pipeline.start(sync=False)

        assert page0_done.wait(timeout=2.0)
        assert pipeline.is_paused is True
        # Give worker a brief moment to verify page 1 does not run while paused
        threading.Event().wait(0.08)
        assert pipeline.completed_pages == [0]

        # Resume and wait for completion
        pipeline.resume()
        assert pipeline.is_paused is False
        assert finished_evt.wait(timeout=2.0)
        assert pipeline.completed_pages == [0, 1]

    doc.close()


def test_streaming_ocr_localization_keys():
    """Verify pause/resume and ETA localization keys exist in all 7 supported languages."""
    required_keys = [
        "ocr_btn_pause",
        "ocr_btn_resume",
        "ocr_status_paused",
        "ocr_banner_paused",
        "ocr_eta_label",
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
            assert k in strings_dict, f"Missing key '{k}' in {loc_name}"
            assert len(strings_dict[k].strip()) > 0


def test_ocr_dialog_closes_immediately_on_start_and_hands_off_to_window():
    """Verify clicking Start OCR in OCRDialog delegates to parent_window.start_streaming_ocr and closes the dialog."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)

    fake_langs = {
        "eng": {"name": "English", "native": "English", "is_installed": True, "source": "system", "path": "/usr/share/tessdata/eng.traineddata"},
    }

    class ParentWin(Adw.Window):
        def __init__(self):
            super().__init__()
            self.start_streaming_ocr = MagicMock()

    parent = ParentWin()
    with patch("word_sys_pdf_editor.ocr_dialog.get_available_languages", return_value=fake_langs):
        dialog = OCRDialog(parent_window=parent, doc=doc, current_page_num=0)
        with patch.object(dialog, "close", wraps=dialog.close) as spy_close:
            dialog._on_start_ocr_clicked(None)
            parent.start_streaming_ocr.assert_called_once()
            spy_close.assert_called_once()
            # Ensure closing after handoff did not set the cancel flag
            assert dialog._closing_after_handoff is True
            assert dialog._cancel_ocr_flag is False

    doc.close()


def test_flatpak_manifests_bundle_tessdata_and_ocr_permissions():
    """Verify both Flatpak manifests configure TESSDATA_PREFIX, network/pcsc permissions, and bundle tessdata-fast."""
    import json

    repo_root = Path(__file__).resolve().parent.parent
    manifest_names = [
        "io.github.word_sys.word-sys-pdf-editor.json",
        "org.word_sys.pdfeditor.json",
    ]
    for name in manifest_names:
        manifest_path = repo_root / name
        assert manifest_path.is_file(), f"Missing Flatpak manifest: {name}"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))

        finish_args = data.get("finish-args", [])
        assert "--share=network" in finish_args
        assert "--socket=pcsc" in finish_args
        assert "--env=TESSDATA_PREFIX=/app/share/tessdata" in finish_args

        modules = data.get("modules", [])
        tessdata_mod = next(
            (m for m in modules if isinstance(m, dict) and m.get("name") == "tessdata-fast"),
            None,
        )
        assert tessdata_mod is not None, f"tessdata-fast module missing in {name}"
        sources = tessdata_mod.get("sources", [])
        urls = [s.get("url", "") for s in sources]
        assert any("eng.traineddata" in u for u in urls)
        assert any("osd.traineddata" in u for u in urls)
        for src in sources:
            assert len(src.get("sha256", "")) == 64


def test_debian_and_appimage_packaging_ocr_and_runtime_configuration(tmp_path, monkeypatch):
    """Verify debian/control, debian/postinst, build-appimage.sh, and find_tesseract_binary OCR support."""
    import subprocess
    from word_sys_pdf_editor.ocr_engine import find_tesseract_binary

    repo_root = Path(__file__).resolve().parent.parent

    # 1. debian/control OCR Recommends & Suggests
    control_text = (repo_root / "debian" / "control").read_text(encoding="utf-8")
    assert "tesseract-ocr" in control_text
    assert "tesseract-ocr-eng" in control_text
    for lang_pkg in (
        "tesseract-ocr-tur",
        "tesseract-ocr-deu",
        "tesseract-ocr-fra",
        "tesseract-ocr-spa",
        "tesseract-ocr-ita",
        "tesseract-ocr-rus",
    ):
        assert lang_pkg in control_text

    # 2. debian/postinst dependencies
    postinst_text = (repo_root / "debian" / "postinst").read_text(encoding="utf-8")
    assert "pyhanko-certvalidator" in postinst_text
    assert "Pillow" in postinst_text

    # 3. build-appimage.sh syntax & OCR bundling
    appimage_script = repo_root / "build-appimage.sh"
    script_text = appimage_script.read_text(encoding="utf-8")
    assert "AppDir/usr/share/tessdata" in script_text
    assert "TESSDATA_PREFIX" in script_text
    assert "PYTHONDONTWRITEBYTECODE=1" in script_text
    assert "pyhanko-certvalidator" in script_text

    syntax_check = subprocess.run(["bash", "-n", str(appimage_script)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, f"build-appimage.sh syntax error: {syntax_check.stderr}"

    # 4. find_tesseract_binary resolves $APPDIR/usr/bin/tesseract when system PATH lacks tesseract
    fake_appdir = tmp_path / "AppDir"
    fake_bin = fake_appdir / "usr" / "bin"
    fake_bin.mkdir(parents=True)
    fake_tess = fake_bin / "tesseract"
    fake_tess.write_text("#!/bin/sh\necho tesseract\n", encoding="utf-8")
    fake_tess.chmod(0o755)

    monkeypatch.setenv("APPDIR", str(fake_appdir))
    with patch("word_sys_pdf_editor.ocr_engine.shutil.which", return_value=None):
        resolved = find_tesseract_binary()
        assert resolved == str(fake_tess)

