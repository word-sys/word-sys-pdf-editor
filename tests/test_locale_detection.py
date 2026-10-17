import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

import word_sys_pdf_editor.i18n as i18n
from word_sys_pdf_editor.i18n import (
    _normalize_lang_code,
    _detect_system_language,
    detect_system_language,
    get_language,
    set_language,
    get_supported_languages,
    _save_settings,
    _load_settings,
    _STRINGS,
)
from word_sys_pdf_editor.welcome_view import WelcomeView


class TestLocaleDetectionAndPersistence(unittest.TestCase):
    def test_normalize_lang_code(self):
        self.assertEqual(_normalize_lang_code("tr_TR.UTF-8"), "tr")
        self.assertEqual(_normalize_lang_code("de_DE@euro"), "de")
        self.assertEqual(_normalize_lang_code("fr-FR"), "fr")
        self.assertEqual(_normalize_lang_code("es_ES"), "es")
        self.assertEqual(_normalize_lang_code("it_IT.UTF-8"), "it")
        self.assertEqual(_normalize_lang_code("ru_RU.CP1251"), "ru")
        self.assertEqual(_normalize_lang_code("en_US.UTF-8"), "en")
        self.assertIsNone(_normalize_lang_code("C"))
        self.assertIsNone(_normalize_lang_code("POSIX"))
        self.assertIsNone(_normalize_lang_code(""))
        self.assertIsNone(_normalize_lang_code(None))

    def test_detect_system_language_glib(self):
        with patch("gi.repository.GLib.get_language_names", return_value=["tr_TR.UTF-8", "tr", "en_US"]):
            self.assertEqual(_detect_system_language(), "tr")

        with patch("gi.repository.GLib.get_language_names", return_value=["de_DE@euro", "de"]):
            self.assertEqual(_detect_system_language(), "de")

        with patch("gi.repository.GLib.get_language_names", return_value=["fr_FR.UTF-8", "fr"]):
            self.assertEqual(_detect_system_language(), "fr")

        with patch("gi.repository.GLib.get_language_names", return_value=["ru_RU.UTF-8", "ru"]):
            self.assertEqual(_detect_system_language(), "ru")

    def test_detect_system_language_env_vars(self):
        with patch("gi.repository.GLib.get_language_names", side_effect=Exception("No GLib")):
            with patch.dict(os.environ, {"LC_ALL": "es_ES.UTF-8", "LANG": "C"}, clear=False):
                self.assertEqual(_detect_system_language(), "es")

            with patch.dict(os.environ, {"LC_ALL": "", "LANG": "it_IT.UTF-8"}, clear=False):
                self.assertEqual(_detect_system_language(), "it")

            with patch.dict(os.environ, {"LC_ALL": "", "LANG": "", "LANGUAGE": "de:fr:en"}, clear=False):
                self.assertEqual(_detect_system_language(), "de")

    def test_detect_system_language_unsupported_fallback(self):
        with patch("gi.repository.GLib.get_language_names", return_value=["ja_JP.UTF-8", "ja", "C"]):
            with patch.dict(os.environ, {"LC_ALL": "C", "LANG": "C", "LANGUAGE": ""}, clear=False):
                self.assertEqual(_detect_system_language(), "en")

    def test_atomic_settings_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            orig_dir = i18n._CONFIG_DIR
            orig_file = i18n._CONFIG_FILE
            try:
                i18n._CONFIG_DIR = tmp_path
                i18n._CONFIG_FILE = tmp_path / "settings.json"

                test_data = {"language": "de", "confirm_delete_objects": False}
                _save_settings(test_data)

                # Ensure target file exists and is valid JSON
                self.assertTrue(i18n._CONFIG_FILE.is_file())
                loaded = _load_settings()
                self.assertEqual(loaded, test_data)

                # Ensure temporary files are cleaned up
                temp_files = list(tmp_path.glob(".settings.json.tmp.*"))
                self.assertEqual(len(temp_files), 0)
            finally:
                i18n._CONFIG_DIR = orig_dir
                i18n._CONFIG_FILE = orig_file

    def test_saved_language_precedence_over_system_locale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            orig_dir = i18n._CONFIG_DIR
            orig_file = i18n._CONFIG_FILE
            orig_lang = i18n._active_lang
            try:
                i18n._CONFIG_DIR = tmp_path
                i18n._CONFIG_FILE = tmp_path / "settings.json"

                # 1. First run: no settings file -> uses detected system language
                with patch("gi.repository.GLib.get_language_names", return_value=["tr_TR.UTF-8", "en"]):
                    loaded = _load_settings()
                    self.assertNotIn("language", loaded)
                    self.assertEqual(_detect_system_language(), "tr")

                # 2. User explicitly saves "fr"
                set_language("fr", restart=False)
                self.assertEqual(get_language(), "fr")

                # 3. Subsequent reload respects explicit "fr" even if system locale is "de"
                with patch("gi.repository.GLib.get_language_names", return_value=["de_DE.UTF-8"]):
                    reloaded = _load_settings()
                    self.assertEqual(reloaded.get("language"), "fr")
            finally:
                i18n._CONFIG_DIR = orig_dir
                i18n._CONFIG_FILE = orig_file
                i18n._active_lang = orig_lang

    def test_welcome_view_pill_button_and_display_update(self):
        mock_win = MagicMock()
        mock_win.doc = None
        mock_win.document_modified = False

        view = WelcomeView(parent_window=mock_win)
        self.assertIsNotNone(view.lang_menu_btn)
        self.assertIsNotNone(view._lang_dropdown)
        self.assertTrue(view.lang_menu_btn.has_css_class("pill"))
        self.assertEqual(len(view._languages), 7)

        # Update display
        view.update_language_display("tr")
        self.assertEqual(view.lang_btn_label.get_text(), "Türkçe")

        view.update_language_display("de")
        self.assertEqual(view.lang_btn_label.get_text(), "Deutsch")

        view.update_language_display("en")
        self.assertEqual(view.lang_btn_label.get_text(), "English")

    def test_request_language_change_unsaved_guard(self):
        from word_sys_pdf_editor.window import PdfEditorWindow

        mock_win = MagicMock()
        mock_sess = MagicMock()
        mock_sess.is_modified = True
        mock_sess.doc = MagicMock()
        mock_win.sessions = [mock_sess]

        orig_lang = get_language()
        with patch("word_sys_pdf_editor.ui_components.show_confirm_dialog", return_value=False):
            # User cancels unsaved changes warning -> language switch should be aborted
            PdfEditorWindow.request_language_change(mock_win, "de" if orig_lang != "de" else "fr")
            # State should remain unchanged
            self.assertEqual(get_language(), orig_lang)
