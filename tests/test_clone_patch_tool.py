import unittest
import tempfile
import os
import pymupdf as fitz
from unittest.mock import MagicMock

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.i18n import _STRINGS, _


class TestExtractPageRegionPatch(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        # Draw some content on the page
        self.page.draw_rect(fitz.Rect(50, 50, 250, 250), color=(0, 0, 1), fill=(0.8, 0.9, 1.0))
        self.page.insert_text((70, 100), "Snapshot Test Region", fontsize=14, color=(0, 0, 0))

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_extract_basic_patch(self):
        bbox = (50, 50, 200, 200)
        patch_bytes = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=300)
        self.assertIsNotNone(patch_bytes)
        self.assertTrue(patch_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        w_px, h_px = pdf_handler.get_image_pixel_dimensions(patch_bytes)
        # 150 pt at 300 DPI: (150 / 72) * 300 = 625 px (approx)
        expected_w = int(round((150.0 / 72.0) * 300.0))
        self.assertAlmostEqual(w_px, expected_w, delta=5)
        self.assertAlmostEqual(h_px, expected_w, delta=5)

    def test_extract_patch_on_rotated_pages(self):
        bbox = (100, 100, 250, 250)
        for rot in [0, 90, 180, 270]:
            doc_rot = fitz.open()
            page = doc_rot.new_page(width=600, height=800)
            page.set_rotation(rot)
            page.draw_rect(fitz.Rect(50, 50, 300, 300), color=(1, 0, 0), fill=(1, 0.9, 0.9))

            patch_bytes = pdf_handler.extract_page_region_patch(doc_rot, 0, bbox, dpi=300)
            self.assertIsNotNone(patch_bytes, f"Failed extraction for rotation {rot}")
            self.assertTrue(patch_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
            w_px, h_px = pdf_handler.get_image_pixel_dimensions(patch_bytes)
            self.assertGreater(w_px, 100)
            self.assertGreater(h_px, 100)
            doc_rot.close()

    def test_extract_patch_boundary_clamping(self):
        # Bounding box overlapping the right and bottom page boundary
        bbox = (500, 700, 750, 950)
        patch_bytes = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=300)
        self.assertIsNotNone(patch_bytes)
        self.assertTrue(patch_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # Width should clamp to 600 - 500 = 100 pt
        w_px, h_px = pdf_handler.get_image_pixel_dimensions(patch_bytes)
        expected_w = int(round((100.0 / 72.0) * 300.0))
        expected_h = int(round((100.0 / 72.0) * 300.0))
        self.assertAlmostEqual(w_px, expected_w, delta=5)
        self.assertAlmostEqual(h_px, expected_h, delta=5)

    def test_extract_patch_completely_outside(self):
        bbox = (800, 900, 1000, 1100)
        patch_bytes = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=300)
        self.assertIsNone(patch_bytes)

    def test_extract_patch_degenerate_bbox(self):
        # Zero or sub-threshold size
        patch_1 = pdf_handler.extract_page_region_patch(self.doc, 0, (100, 100, 101, 101), dpi=300)
        self.assertIsNone(patch_1)

        patch_2 = pdf_handler.extract_page_region_patch(self.doc, 0, (100, 100, 100, 100), dpi=300)
        self.assertIsNone(patch_2)

    def test_extract_patch_invalid_page_or_doc(self):
        self.assertIsNone(pdf_handler.extract_page_region_patch(None, 0, (50, 50, 150, 150)))
        self.assertIsNone(pdf_handler.extract_page_region_patch(self.doc, -1, (50, 50, 150, 150)))
        self.assertIsNone(pdf_handler.extract_page_region_patch(self.doc, 999, (50, 50, 150, 150)))

    def test_extract_patch_custom_dpi(self):
        bbox = (50, 50, 150, 150)
        patch_150 = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=150)
        patch_300 = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=300)
        self.assertIsNotNone(patch_150)
        self.assertIsNotNone(patch_300)

        w_150, _ = pdf_handler.get_image_pixel_dimensions(patch_150)
        w_300, _ = pdf_handler.get_image_pixel_dimensions(patch_300)
        self.assertAlmostEqual(w_300, w_150 * 2, delta=6)


class MockClonePatchWindow:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.view_mode = False
        self.tool_mode = "clone_patch"
        self.temp_clone_patch_bbox = None
        self.last_captured_patch = None
        self.temp_image_bbox = None
        self.temp_shape = None
        self.temp_stroke = None
        self.temp_stamp_bbox = None
        self.temp_sig_bbox = None
        self.temp_form_field_rect = None
        self.drag_start_page_pos = (0, 0)
        self.drag_start_page_index = 0
        self.dragging_to_create = False
        self.pdf_view = MagicMock()
        self.status_label = MagicMock()
        self.editable_texts = []
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.form_fields = []
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.inline_editor_widget = None

    def get_focus(self):
        return None

    def _update_ui_state(self):
        pass

    def canvas_to_page_coords(self, x, y):
        return self.current_page_index, x / self.zoom_level, y / self.zoom_level

    def is_canvas_point_on_page(self, x, y, target_page):
        return True

    def _visual_to_unrotated_delta(self, dx, dy):
        return dx, dy

    def _visual_to_unrotated_page_coords(self, px, py, page_index=None):
        return px, py

    def _stash_page_objects(self, page_index):
        pass

    def _restore_page_objects(self, page_index):
        pass

    def _sync_thumbnail_selection(self):
        pass

    def _sync_window_title_and_subtitle(self):
        pass

    def _create_form_field_overlays(self):
        pass

    def _clear_form_field_overlays(self):
        pass

    def hide_text_editor(self):
        pass

    def commit_pending_format_change(self):
        pass

    _switch_active_page = PdfEditorWindow._switch_active_page
    on_drag_begin = PdfEditorWindow.on_drag_begin
    on_drag_update = PdfEditorWindow.on_drag_update
    on_drag_end = PdfEditorWindow.on_drag_end


class TestClonePatchWindowIntegration(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.page1 = self.doc.new_page(width=500, height=700)
        self.page1.draw_rect(fitz.Rect(40, 40, 200, 200), fill=(0.9, 0.9, 0.9))
        self.page2 = self.doc.new_page(width=500, height=700)
        self.win = MockClonePatchWindow(self.doc)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_drag_and_capture_patch_success(self):
        gesture = MagicMock()

        # Begin drag at (50, 50)
        self.win.on_drag_begin(gesture, 50.0, 50.0)
        self.assertTrue(self.win.dragging_to_create)
        self.assertEqual(self.win.temp_clone_patch_bbox, (50.0, 50.0, 50.0, 50.0))

        # Update drag by (+80, +60) -> (130, 110)
        self.win.on_drag_update(gesture, 80.0, 60.0)
        self.assertEqual(self.win.temp_clone_patch_bbox, (50.0, 50.0, 130.0, 110.0))

        # End drag
        self.win.on_drag_end(gesture, 80.0, 60.0)
        self.assertFalse(self.win.dragging_to_create)
        self.assertIsNone(self.win.temp_clone_patch_bbox)

        # Verify patch was captured and stored in last_captured_patch
        self.assertIsNotNone(self.win.last_captured_patch)
        patch = self.win.last_captured_patch
        self.assertIn("image_bytes", patch)
        self.assertTrue(patch["image_bytes"].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(patch["bbox"], (50.0, 50.0, 130.0, 110.0))
        self.assertEqual(patch["page_number"], 0)
        self.assertEqual(patch["dpi"], 300)

        # Verify status label updated
        self.win.status_label.set_text.assert_called()

    def test_drag_and_capture_patch_too_small(self):
        gesture = MagicMock()

        # Begin drag at (50, 50)
        self.win.on_drag_begin(gesture, 50.0, 50.0)
        # Tiny drag +2, +1 (< 4 pt)
        self.win.on_drag_update(gesture, 2.0, 1.0)
        self.win.on_drag_end(gesture, 2.0, 1.0)

        self.assertIsNone(self.win.temp_clone_patch_bbox)
        self.assertIsNone(self.win.last_captured_patch)

    def test_captured_patch_preserved_on_page_switch(self):
        gesture = MagicMock()
        self.win.on_drag_begin(gesture, 60.0, 60.0)
        self.win.on_drag_update(gesture, 100.0, 100.0)
        self.win.on_drag_end(gesture, 100.0, 100.0)
        self.assertIsNotNone(self.win.last_captured_patch)

        # Switch to page 1
        self.win.continuous_scroll = False
        self.win._switch_active_page(1)
        self.assertEqual(self.win.current_page_index, 1)

        # Verify last_captured_patch is still preserved intact!
        self.assertIsNotNone(self.win.last_captured_patch)
        self.assertEqual(self.win.last_captured_patch["page_number"], 0)

    def test_on_pdf_view_pressed_claims_gesture(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        self.win.current_pdf_page_width = 500
        self.win.current_pdf_page_height = 700
        self.win.font_scan_in_progress = False
        self.win._find_text_at_pos = lambda x, y: None
        self.win.on_pdf_view_pressed = PdfEditorWindow.on_pdf_view_pressed.__get__(self.win)
        gesture = MagicMock()

        self.win.on_pdf_view_pressed(gesture, 1, 100.0, 100.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)

    def test_shortcuts_c_and_e(self):
        import gi
        gi.require_version('Gdk', '4.0')
        from gi.repository import Gdk

        self.win.inline_editor_widget = None
        self.win.commit_pending_format_change = MagicMock()
        selected_tools = []
        self.win.on_tool_selected = lambda btn, tool_name: selected_tools.append(tool_name)
        self.win.on_key_pressed = PdfEditorWindow.on_key_pressed.__get__(self.win)

        handled_c = self.win.on_key_pressed(None, Gdk.KEY_c, 0, 0)
        self.assertTrue(handled_c)
        self.assertEqual(selected_tools[-1], "clone_patch")

        handled_C = self.win.on_key_pressed(None, Gdk.KEY_C, 0, 0)
        self.assertTrue(handled_C)
        self.assertEqual(selected_tools[-1], "clone_patch")

        handled_e = self.win.on_key_pressed(None, Gdk.KEY_e, 0, 0)
        self.assertTrue(handled_e)
        self.assertEqual(selected_tools[-1], "add_ellipse")

        handled_E = self.win.on_key_pressed(None, Gdk.KEY_E, 0, 0)
        self.assertTrue(handled_E)
        self.assertEqual(selected_tools[-1], "add_ellipse")

        handled_o = self.win.on_key_pressed(None, Gdk.KEY_o, 0, 0)
        self.assertTrue(handled_o)
        self.assertEqual(selected_tools[-1], "add_ellipse")

        handled_O = self.win.on_key_pressed(None, Gdk.KEY_O, 0, 0)
        self.assertTrue(handled_O)
        self.assertEqual(selected_tools[-1], "add_ellipse")


class TestClonePatchLocalization(unittest.TestCase):
    def test_all_locales_have_clone_patch_keys(self):
        required_keys = [
            "tool_clone_patch",
            "tool_clone_patch_tip",
            "patch_captured_status",
            "patch_capture_failed",
            "guide_sc_tool_clone_patch",
        ]
        for lang in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            self.assertIn(lang, _STRINGS)
            locale_dict = _STRINGS[lang]
            for key in required_keys:
                self.assertIn(key, locale_dict, f"Missing key '{key}' in locale '{lang}'")
                self.assertGreater(len(locale_dict[key]), 0, f"Empty string for key '{key}' in '{lang}'")

    def test_ellipse_shortcut_updated_to_e(self):
        for lang in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            self.assertIn(lang, _STRINGS)
            locale_dict = _STRINGS[lang]
            self.assertIn("(E)", locale_dict["tool_ellipse"], f"tool_ellipse shortcut not updated in '{lang}'")


if __name__ == "__main__":
    unittest.main()
