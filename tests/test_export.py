"""Comprehensive test suite for Part 14: Export Dialog & Format Expansion."""

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
import unittest

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw, GLib, Gio
import fitz

from word_sys_pdf_editor.export_dialog import ExportDialog, FORMAT_ITEMS
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor import i18n
from word_sys_pdf_editor import locales


def run_main_loop(iterations=20, delay=0.02):
    """Pump the GLib main context to process idle callbacks."""
    ctx = GLib.MainContext.default()
    for _ in range(iterations):
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(delay)


class TestExportLocalization(unittest.TestCase):
    """Verify localization keys across all 7 supported languages."""

    EXPORT_KEYS = [
        "menu_export",
        "export_dialog_title",
        "export_format_title",
        "export_format_label",
        "export_layout_mode_title",
        "export_mode_canvas",
        "export_mode_canvas_desc",
        "export_mode_flow",
        "export_mode_flow_desc",
        "export_btn_choose",
        "export_btn_confirm",
        "export_format_docx",
        "export_format_pptx",
        "export_format_odt",
        "export_format_odp",
        "export_format_txt",
        "export_in_progress",
    ]

    def test_all_languages_have_export_keys(self):
        supported_langs = [code for code, _ in i18n.get_supported_languages()]
        self.assertEqual(len(supported_langs), 7)

        for lang in supported_langs:
            table = i18n._STRINGS.get(lang)
            self.assertIsNotNone(table, f"Missing language table for {lang}")
            for key in self.EXPORT_KEYS:
                self.assertIn(key, table, f"Language '{lang}' missing key '{key}'")
                val = table[key]
                self.assertTrue(isinstance(val, str) and len(val) > 0, f"Empty translation for '{key}' in '{lang}'")
                # Strict check: ZERO emojis
                for char in val:
                    self.assertLess(ord(char), 0x1F000, f"Found potential emoji in '{lang}' key '{key}': {val}")


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestExportDialog(unittest.TestCase):
    """Unit tests for ExportDialog widget."""

    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.word_sys.test.export")

    def test_default_instantiation(self):
        dialog = ExportDialog(None, initial_format="DOCX", initial_mode="canvas")
        self.assertEqual(dialog.get_selected_format(), "DOCX")
        self.assertEqual(dialog.get_selected_mode(), "canvas")
        self.assertTrue(dialog.layout_group.get_sensitive())

    def test_flow_mode_selection(self):
        dialog = ExportDialog(None, initial_format="PPTX", initial_mode="flow")
        self.assertEqual(dialog.get_selected_format(), "PPTX")
        self.assertEqual(dialog.get_selected_mode(), "flow")
        self.assertTrue(dialog.layout_group.get_sensitive())

    def test_txt_format_disables_layout_group(self):
        dialog = ExportDialog(None, initial_format="TXT")
        self.assertEqual(dialog.get_selected_format(), "TXT")
        self.assertEqual(dialog.get_selected_mode(), "canvas")
        self.assertFalse(dialog.layout_group.get_sensitive())

    def test_format_switching_updates_sensitivity(self):
        dialog = ExportDialog(None, initial_format="DOCX")
        self.assertTrue(dialog.layout_group.get_sensitive())

        # Select TXT index
        txt_idx = [idx for idx, (k, _) in enumerate(FORMAT_ITEMS) if k == "TXT"][0]
        dialog.format_row.set_selected(txt_idx)
        self.assertEqual(dialog.get_selected_format(), "TXT")
        self.assertFalse(dialog.layout_group.get_sensitive())

        # Switch back to ODT
        odt_idx = [idx for idx, (k, _) in enumerate(FORMAT_ITEMS) if k == "ODT"][0]
        dialog.format_row.set_selected(odt_idx)
        self.assertEqual(dialog.get_selected_format(), "ODT")
        self.assertTrue(dialog.layout_group.get_sensitive())

    def test_confirm_callback_trigger(self):
        result = {}

        def on_confirm(fmt, mode):
            result["format"] = fmt
            result["mode"] = mode

        dialog = ExportDialog(None, initial_format="ODP", initial_mode="canvas", on_confirm_callback=on_confirm)
        dialog._on_export_clicked(dialog.export_btn)

        self.assertEqual(result.get("format"), "ODP")
        self.assertEqual(result.get("mode"), "canvas")


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestWindowExportActions(unittest.TestCase):
    """Unit tests for PdfEditorWindow export actions and UI states."""

    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.word_sys.test.window_export")
        cls.win = PdfEditorWindow(application=cls.app)

    def test_export_actions_registered(self):
        expected_actions = [
            "export_as",
            "export_docx",
            "export_pptx",
            "export_odt",
            "export_odp",
            "export_txt",
        ]
        for act in expected_actions:
            action_obj = self.win.lookup_action(act)
            self.assertIsNotNone(action_obj, f"Action {act} not registered on window")

    def test_actions_disabled_without_document(self):
        self.win.doc = None
        self.win._update_ui_state()

        expected_actions = [
            "export_as",
            "export_docx",
            "export_pptx",
            "export_odt",
            "export_odp",
            "export_txt",
        ]
        for act in expected_actions:
            action_obj = self.win.lookup_action(act)
            self.assertFalse(action_obj.get_enabled(), f"Action {act} should be disabled when no doc")

    def test_actions_enabled_with_document(self):
        doc = fitz.open()
        doc.new_page(width=300, height=300)
        self.win.doc = doc
        self.win._update_ui_state()

        expected_actions = [
            "export_as",
            "export_docx",
            "export_pptx",
            "export_odt",
            "export_odp",
            "export_txt",
        ]
        for act in expected_actions:
            action_obj = self.win.lookup_action(act)
            self.assertTrue(action_obj.get_enabled(), f"Action {act} should be enabled when doc loaded")
        doc.close()

    def test_direct_export_bypasses_dialog_and_uses_canvas(self):
        invoked_prompts = []

        def mock_prompt(fmt, mode="canvas"):
            invoked_prompts.append((fmt, mode))

        orig_prompt = self.win._prompt_export_destination
        self.win._prompt_export_destination = mock_prompt
        try:
            self.win.on_export_docx()
            self.win.on_export_pptx()
            self.win.on_export_odt()
            self.win.on_export_odp()
            self.win.on_export_txt()

            self.assertEqual(invoked_prompts, [
                ("DOCX", "canvas"),
                ("PPTX", "canvas"),
                ("ODT", "canvas"),
                ("ODP", "canvas"),
                ("TXT", "canvas"),
            ])
        finally:
            self.win._prompt_export_destination = orig_prompt

    def test_export_as_opens_settings_dialog(self):
        dialog_opened = []

        def mock_show_dialog(initial_format="DOCX"):
            dialog_opened.append(initial_format)

        orig_show = self.win.show_export_dialog
        self.win.show_export_dialog = mock_show_dialog
        try:
            self.win.on_export_as()
            self.assertEqual(dialog_opened, ["DOCX"])
        finally:
            self.win.show_export_dialog = orig_show

    def test_export_dialog_button_label_is_compact(self):
        dialog = ExportDialog(None, initial_format="DOCX")
        self.assertEqual(dialog.export_btn.get_label(), i18n._("export_btn_confirm"))


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestAsynchronousExportExecution(unittest.TestCase):
    """End-to-end tests for asynchronous export via _execute_export."""

    @classmethod
    def setUpClass(cls):
        cls.app = Adw.Application(application_id="org.word_sys.test.async_export")
        cls.win = PdfEditorWindow(application=cls.app)

        # Create a test PDF with text and shapes
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_pdf = os.path.join(cls.temp_dir.name, "sample.pdf")
        doc = fitz.open()
        page = doc.new_page(width=400, height=400)
        page.insert_text(fitz.Point(50, 50), "Part 14 Export Verification Header", fontsize=14)
        page.insert_text(fitz.Point(50, 100), "Testing AnyConvert asynchronous background export.", fontsize=11)
        doc.save(cls.test_pdf)
        doc.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        self.doc = fitz.open(self.test_pdf)
        self.win.doc = self.doc
        self.win.current_file_path = self.test_pdf

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def _wait_for_export(self, fmt, mode="canvas"):
        out_path = os.path.join(self.temp_dir.name, f"output_{mode}.{fmt.lower()}")
        finished_event = threading.Event()
        result = {}

        def on_done(success, err):
            result["success"] = success
            result["error"] = err
            finished_event.set()

        self.win._execute_export(fmt, out_path, mode=mode, on_finish=on_done)

        # Ensure UI returns immediately before finish
        self.assertIn(fmt.upper(), self.win.status_label.get_text())

        # Pump main context until worker completes
        start_time = time.time()
        while not finished_event.is_set():
            if time.time() - start_time > 15.0:
                self.fail(f"Export to {fmt} timed out after 15 seconds")
            run_main_loop(iterations=5, delay=0.02)

        return result, out_path

    def test_async_export_docx_canvas(self):
        res, out_path = self._wait_for_export("DOCX", mode="canvas")
        self.assertTrue(res.get("success"), f"DOCX canvas export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_docx_flow(self):
        res, out_path = self._wait_for_export("DOCX", mode="flow")
        self.assertTrue(res.get("success"), f"DOCX flow export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_pptx(self):
        res, out_path = self._wait_for_export("PPTX", mode="canvas")
        self.assertTrue(res.get("success"), f"PPTX export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_odt(self):
        res, out_path = self._wait_for_export("ODT", mode="canvas")
        self.assertTrue(res.get("success"), f"ODT export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_odp(self):
        res, out_path = self._wait_for_export("ODP", mode="canvas")
        self.assertTrue(res.get("success"), f"ODP export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_async_export_txt(self):
        res, out_path = self._wait_for_export("TXT", mode="canvas")
        self.assertTrue(res.get("success"), f"TXT export failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path))
        content = Path(out_path).read_text(encoding="utf-8")
        self.assertIn("Part 14 Export Verification Header", content)

    def test_async_export_invalid_format(self):
        out_path = os.path.join(self.temp_dir.name, "output.xyz")
        finished_event = threading.Event()
        result = {}

        def on_done(success, err):
            result["success"] = success
            result["error"] = err
            finished_event.set()

        self.win._execute_export("XYZ", out_path, on_finish=on_done)

        start_time = time.time()
        while not finished_event.is_set():
            if time.time() - start_time > 5.0:
                self.fail("Timed out waiting for invalid format error callback")
            run_main_loop(iterations=5, delay=0.02)

        self.assertFalse(result.get("success"))
        self.assertEqual(result.get("error"), i18n._("err_unknown_export_format"))


if __name__ == "__main__":
    unittest.main()
