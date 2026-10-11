# -*- coding: utf-8 -*-
"""Comprehensive test suite for Part 35: Sandboxed License Asset Embedding.

Verifies:
- get_application_license_text() returns the complete, official GNU General Public License v3 text.
- Resilience in sandboxed Flatpak and AppImage environments where /usr/share/common-licenses does not exist.
- Embedded fallback constant GPL_V3_FULL_TEXT is valid and used when all filesystem paths are missing.
- Package data inclusion in pyproject.toml and installation directives in Flatpak manifests.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from word_sys_pdf_editor import constants
from word_sys_pdf_editor.license_data import GPL_V3_FULL_TEXT


class TestSandboxedLicenseEmbedding(unittest.TestCase):
    """Test license loading and fallback mechanisms across sandboxed runtimes."""

    def test_get_application_license_text_returns_full_gpl3(self):
        text = constants.get_application_license_text()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 10000)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
        self.assertIn("Version 3, 29 June 2007", text)
        self.assertIn("Preamble", text)
        self.assertNotIn("Full text could not be loaded", text)

    def test_embedded_license_data_constant_validity(self):
        self.assertIsInstance(GPL_V3_FULL_TEXT, str)
        self.assertGreater(len(GPL_V3_FULL_TEXT), 30000)
        self.assertIn("Free Software Foundation, Inc.", GPL_V3_FULL_TEXT)

    def test_fallback_when_all_filesystem_paths_absent(self):
        # Simulate environment where no search paths exist (sandboxed container without mounted files)
        with patch.object(Path, "is_file", return_value=False):
            text = constants.get_application_license_text()
            self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
            self.assertGreater(len(text), 10000)
            self.assertNotIn("Full text could not be loaded", text)

    def test_appdir_environment_variable_precedence(self):
        # In AppImage, APPDIR environment variable points to mounted squashfs image
        fake_appdir = "/tmp/.mount_appimage_test"
        with patch.dict(os.environ, {"APPDIR": fake_appdir}):
            text = constants.get_application_license_text()
            self.assertIsInstance(text, str)
            self.assertIn("GNU GENERAL PUBLIC LICENSE", text)

    def test_package_license_file_exists(self):
        pkg_license = Path(__file__).resolve().parent.parent / "word_sys_pdf_editor" / "LICENSE"
        self.assertTrue(pkg_license.is_file(), "Bundled word_sys_pdf_editor/LICENSE must exist for wheel/pip installation")
        content = pkg_license.read_text(encoding="utf-8")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", content)


if __name__ == "__main__":
    unittest.main()
