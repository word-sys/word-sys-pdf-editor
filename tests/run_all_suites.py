"""Unified Multi-Suite Automated Regression Runner for word-sys-pdf-editor.

Provides categorized suite discovery and execution across all 22 automated test suites:
- AcroForms & Form Builder
- Corporate Tools (Stamps, Sticky Notes, Measurements, Compression, Merge & Export)
- Digital Signatures & Security
- Redaction & Sanitization
- Optical Character Recognition (OCR)
- Continuous Scrolling & Core Navigation
- Memory Optimization, Cairo Streams, Rendering & Cache
- Performance Benchmarks & Regression Guards
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from typing import Dict, List

SUITE_CATEGORIES: Dict[str, List[str]] = {
    "acroforms": [
        "test_forms_and_acroforms.py",
    ],
    "corporate": [
        "test_stamps_and_notes.py",
        "test_measurements_suite.py",
        "test_compression_suite.py",
        "test_merge_and_export_suite.py",
    ],
    "signatures": [
        "test_signatures_and_security.py",
    ],
    "redaction": [
        "test_redaction_and_sanitization.py",
    ],
    "ocr": [
        "test_ocr_suite.py",
    ],
    "continuous": [
        "test_continuous_scroll_suite.py",
        "test_core_and_navigation.py",
    ],
    "editing": [
        "test_text_editing_suite.py",
        "test_formatting_and_alignment.py",
        "test_object_manipulation_suite.py",
        "test_images_and_patches.py",
        "test_i18n_and_locales.py",
    ],
    "memory": [
        "test_rendering_and_cache.py",
        "test_cairo_and_streams.py",
        "test_background_and_incremental_save_suite.py",
        "test_regressions_and_fixes.py",
        "test_v1120_atomic.py",
    ],
    "benchmarks": [
        "test_performance_benchmarks.py",
    ],
}


def get_all_suite_files() -> List[str]:
    """Return ordered list of all consolidated test suite filenames."""
    files: List[str] = []
    for cat_files in SUITE_CATEGORIES.values():
        for fname in cat_files:
            if fname not in files:
                files.append(fname)
    return files


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified regression test runner for word-sys-pdf-editor")
    parser.add_argument(
        "--category",
        choices=["all", *SUITE_CATEGORIES.keys()],
        default="all",
        help="Run a specific test suite category or all suites (default: all).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all registered suite files and exit.",
    )
    args, extra = parser.parse_known_args(argv)

    tests_dir = os.path.dirname(os.path.abspath(__file__))
    target_files = (
        get_all_suite_files()
        if args.category == "all"
        else SUITE_CATEGORIES[args.category]
    )

    if args.list:
        for fname in target_files:
            print(os.path.join(tests_dir, fname))
        return 0

    try:
        import pytest
        pytest_args = [os.path.join(tests_dir, f) for f in target_files] + extra
        return int(pytest.main(pytest_args))
    except ImportError:
        suite = unittest.TestSuite()
        loader = unittest.TestLoader()
        for fname in target_files:
            suite.addTests(loader.discover(start_dir=tests_dir, pattern=fname))
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
