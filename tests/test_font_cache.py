"""Tests for Part 66: Instant App Launch & Persistent Fontconfig Disk I/O Cache."""

import os
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from word_sys_pdf_editor import utils
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.models import EditableText


def test_get_font_cache_path(monkeypatch):
    """Verify font cache path resolution adheres to XDG_CACHE_HOME and default ~/.cache."""
    temp_dir = tempfile.mkdtemp()
    monkeypatch.setenv("XDG_CACHE_HOME", temp_dir)
    cache_path = utils.get_font_cache_path()
    assert str(cache_path).startswith(temp_dir)
    assert cache_path.name == "font_cache.json"
    assert cache_path.parent.name == "word-sys-pdf-editor"


def test_save_and_load_persistent_font_cache():
    """Verify saving font data to disk cache and restoring it with directory mtime validation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "test_font_cache.json"
        dummy_font_dir = Path(temp_dir) / "fonts"
        dummy_font_dir.mkdir()

        dummy_fonts = {
            "Custom Sans": {
                "Regular": str(dummy_font_dir / "CustomSans-Regular.ttf"),
                "Bold": str(dummy_font_dir / "CustomSans-Bold.ttf")
            },
            "Custom Serif": {
                "Regular": str(dummy_font_dir / "CustomSerif-Regular.ttf")
            }
        }
        dummy_families = ["Custom Sans", "Custom Serif"]

        # Save cache
        saved = utils.save_persistent_font_cache(
            dummy_fonts, dummy_families, [dummy_font_dir], cache_path=cache_file
        )
        assert saved is True
        assert cache_file.is_file()

        # Patch _get_font_dirs to return our dummy_font_dir
        with patch.object(utils, "_get_font_dirs", return_value=[dummy_font_dir]):
            utils.SYSTEM_FONTS.clear()
            utils.FONT_FAMILY_LIST_SORTED.clear()
            utils.FONT_SCAN_COMPLETED.clear()

            loaded = utils.load_persistent_font_cache(cache_path=cache_file)
            assert loaded is True
            assert utils.FONT_SCAN_COMPLETED.is_set()
            assert "Custom Sans" in utils.SYSTEM_FONTS
            assert utils.FONT_FAMILY_LIST_SORTED == dummy_families


def test_persistent_font_cache_invalidation_on_mtime_change():
    """Verify persistent cache is invalidated when font directory mtime changes."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "test_font_cache.json"
        dummy_font_dir = Path(temp_dir) / "fonts"
        dummy_font_dir.mkdir()

        dummy_fonts = {"TestFont": {"Regular": "TestFont.ttf"}}
        dummy_families = ["TestFont"]

        utils.save_persistent_font_cache(
            dummy_fonts, dummy_families, [dummy_font_dir], cache_path=cache_file
        )

        with patch.object(utils, "_get_font_dirs", return_value=[dummy_font_dir]):
            # 1. Fresh cache matches
            assert utils.load_persistent_font_cache(cache_path=cache_file) is True

            # 2. Touch directory to advance mtime by 10 seconds
            current_mtime = dummy_font_dir.stat().st_mtime
            os.utime(dummy_font_dir, (current_mtime + 10.0, current_mtime + 10.0))

            # 3. Cache must be detected as stale
            assert utils.load_persistent_font_cache(cache_path=cache_file) is False


def test_persistent_font_cache_corrupt_file_handling():
    """Verify corrupt, empty, or incompatible cache files return False safely."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "corrupt_font_cache.json"

        # 1. Non-existent file
        assert utils.load_persistent_font_cache(cache_path=cache_file) is False

        # 2. Corrupt JSON syntax
        with open(cache_file, "w") as f:
            f.write("{invalid_json_data:")
        assert utils.load_persistent_font_cache(cache_path=cache_file) is False

        # 3. Wrong schema version
        with open(cache_file, "w") as f:
            json.dump({"version": 999, "dir_mtimes": {}}, f)
        assert utils.load_persistent_font_cache(cache_path=cache_file) is False


def test_scan_system_fonts_direct_discovers_fonts():
    """Verify _scan_system_fonts_direct retrieves system fonts via fc-list or directory traversal."""
    font_dirs = utils._get_font_dirs()
    fonts_data = utils._scan_system_fonts_direct(font_dirs)
    assert isinstance(fonts_data, dict)
    assert len(fonts_data) > 0

    # System fonts should discover standard Linux fonts (e.g., Liberation Sans or Noto Sans or DejaVu Sans)
    common_names = {"Liberation Sans", "DejaVu Sans", "Noto Sans", "Ubuntu", "Free Sans", "Sans"}
    assert any(name in fonts_data for name in common_names)


def test_scan_system_fonts_async_instant_cache_hit():
    """Verify scan_system_fonts_async returns in < 15ms when persistent cache is warm."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "fast_cache.json"
        dummy_dir = Path(temp_dir) / "fonts"
        dummy_dir.mkdir()

        dummy_fonts = {f"Font {i}": {"Regular": f"font_{i}.ttf"} for i in range(100)}
        dummy_families = sorted(dummy_fonts.keys())

        utils.save_persistent_font_cache(
            dummy_fonts, dummy_families, [dummy_dir], cache_path=cache_file
        )

        with patch.object(utils, "_get_font_dirs", return_value=[dummy_dir]):
            utils.SYSTEM_FONTS.clear()
            utils.FONT_FAMILY_LIST_SORTED.clear()
            utils.FONT_SCAN_COMPLETED.clear()

            callback_mock = MagicMock()
            t0 = time.perf_counter()
            utils.scan_system_fonts_async(callback_on_done=callback_mock, cache_path=cache_file)
            duration_ms = (time.perf_counter() - t0) * 1000

            # Instant cache load should complete in under 15ms
            assert duration_ms < 15.0
            assert utils.FONT_SCAN_COMPLETED.is_set()
            assert len(utils.FONT_FAMILY_LIST_SORTED) == 100


def test_deferred_font_combo_population():
    """Verify deferred population of font combo dropdown on first text formatting interaction."""
    win = MagicMock()
    win._is_closing = False
    win._is_closed = False
    win.font_store = MagicMock()
    win.font_store.__len__.return_value = 50
    win.font_combo = MagicMock()
    win._font_combo_populated = False
    win.selected_text = None
    win.current_file_path = None
    win.doc = None
    win.status_label = MagicMock()
    win._populate_font_combo = lambda: PdfEditorWindow._populate_font_combo(win)

    # Initial mock font list
    mock_families = [f"Family {i}" for i in range(50)]
    with patch.object(utils, "FONT_FAMILY_LIST_SORTED", mock_families), \
         patch.object(utils, "UNICODE_FONT_PATH", "/usr/share/fonts/dummy.ttf"):

        # 1. Initial font scan finish: defers full population, sets default font
        PdfEditorWindow._on_font_scan_complete(win)
        assert win._font_combo_populated is False
        win.font_store.clear.assert_called_once()
        win.font_store.append.assert_called_once_with(["Family 0", "Family 0"])

        # 2. First call to _ensure_font_combo_populated: populates all 50 items
        PdfEditorWindow._ensure_font_combo_populated(win)
        assert win._font_combo_populated is True
        assert win.font_store.append.call_count == 51 # 1 from startup + 50 from full populate

        # 3. Second call is idempotent: does not re-append
        win.font_store.append.reset_mock()
        PdfEditorWindow._ensure_font_combo_populated(win)
        win.font_store.append.assert_not_called()
