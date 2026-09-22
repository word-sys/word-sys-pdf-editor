import json

from word_sys_pdf_editor import i18n


def test_translation_uses_active_language_and_english_fallback(monkeypatch):
    monkeypatch.setitem(i18n._STRINGS, "test", {"btn_cancel": "Test Cancel"})
    monkeypatch.setattr(i18n, "_active_lang", "test")

    assert i18n._("btn_cancel") == "Test Cancel"
    assert i18n._("filter_pdf") == i18n._STRINGS["en"]["filter_pdf"]
    assert i18n._("missing_translation") == "missing_translation"


def test_translation_formats_arguments_and_tolerates_bad_format(monkeypatch):
    monkeypatch.setattr(i18n, "_active_lang", "en")

    assert i18n._("loading", "document.pdf") == "Loading document.pdf…"
    assert i18n._("page_info_count", "one") == "Page {} / {}"


def test_settings_are_saved_as_json(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_file = config_dir / "settings.json"
    monkeypatch.setattr(i18n, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(i18n, "_CONFIG_FILE", config_file)
    monkeypatch.setattr(i18n, "_settings", {})

    i18n.set_setting("theme", "dark")

    assert i18n.get_setting("theme") == "dark"
    assert json.loads(config_file.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_supported_languages_are_returned():
    languages = dict(i18n.get_supported_languages())

    assert languages["en"] == "English"
    assert languages["tr"] == "Türkçe"
