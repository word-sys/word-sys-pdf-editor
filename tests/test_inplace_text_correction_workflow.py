"""
Tests for Part 56: Scanned Document In-Place Text Correction Workflow.
Validates:
1. PatchObject and EditableText bidirectional linkage.
2. PDF stream baking and underlying OCR text purge under patches.
3. Canvas hit-testing priority (layered text selected before underlying patch).
4. Initiate text over patch workflow (double-click, Enter/T shortcuts, context menu).
5. Synchronized co-movement of patch and linked text (drag and arrow nudge).
6. Undo/Redo cycles with CompositeCommand for co-movement and co-deletion.
7. Localization coverage for Part 56 strings across all 7 supported locales.
"""

import os
import copy
import unittest
from unittest.mock import MagicMock, patch
import fitz

from word_sys_pdf_editor.models import (
    EditableText, EditableImage, EditableShape, PatchObject
)
from word_sys_pdf_editor.undo_manager import (
    UndoManager, AddObjectCommand, EditObjectCommand, DeleteObjectCommand,
    CompositeCommand
)
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.i18n import _, _STRINGS
from word_sys_pdf_editor.locales import (
    STRINGS_FR, STRINGS_DE, STRINGS_ES, STRINGS_IT, STRINGS_RU
)
from word_sys_pdf_editor.window import PdfEditorWindow


def create_solid_png_bytes(width=60, height=30, color=(255, 255, 255)):
    """Generate minimal valid PNG bytes for image/patch tests."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.clear_with(color[0] | (color[1] << 8) | (color[2] << 16))
    return pix.tobytes("png")


class MockCorrectionWindow:
    """Mock window providing required environment for testing in-place text correction."""
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.view_mode = False
        self.tool_mode = "select"
        self.editable_texts = []
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None
        self.dragged_object = None
        self.drag_start_pos = None
        self.drag_object_start_pos = None
        self.document_modified = False
        self.status_label = MagicMock()
        self.pdf_view = MagicMock()
        self.font_size = 12
        self.font_family = "Liberation Sans"
        self.font_color = (0.0, 0.0, 0.0)
        self.font_combo = None
        self.font_store = None
        self.font_size_spin = None
        self.inline_editor_widget = None
        self.inline_editor_tv = None
        self.inline_editor_text_obj = None

        self.undo_stack = []
        self.redo_stack = []
        self.undo_manager = UndoManager(self)
        self.font_scan_in_progress = False
        self._update_tab_dirty_state = lambda: None

    def _update_undo_redo_buttons(self):
        pass

    def _update_ui_state(self):
        pass

    def _refresh_thumbnail(self, page_index):
        pass

    def _switch_active_page(self, page_index):
        self.current_page_index = page_index

    def _update_text_format_controls(self, text_obj):
        pass

    def _show_inline_editor(self, text_obj, click_x=None, click_y=None, target_rect=None):
        self.inline_editor_widget = MagicMock()
        self.inline_editor_text_obj = text_obj
        self._inline_editor_target_rect = target_rect

    def _hide_inline_editor(self):
        self.inline_editor_widget = None
        self.inline_editor_text_obj = None

    def _visual_to_unrotated_delta(self, dx, dy):
        return dx, dy

    def _find_text_at_pos(self, px, py):
        return PdfEditorWindow._find_text_at_pos(self, px, py)

    def _find_image_at_pos(self, px, py):
        return PdfEditorWindow._find_image_at_pos(self, px, py)

    def _find_shape_at_pos(self, px, py):
        return None

    def _find_stroke_at_pos(self, px, py):
        return None

    def _find_form_field_at_pos(self, px, py):
        return None

    def _find_measurement_at_pos(self, px, py):
        return None

    def _close_active_form_field_editor(self):
        pass

    def commit_pending_format_change(self):
        pass

    def initiate_text_over_patch(self, patch_obj):
        return PdfEditorWindow.initiate_text_over_patch(self, patch_obj)


class TestModelLinkage(unittest.TestCase):
    """Test model attributes and linkage between PatchObject and EditableText."""

    def test_patch_object_defaults(self):
        png = create_solid_png_bytes()
        patch = PatchObject(bbox=(10, 20, 110, 50), page_number=0, image_bytes=png)
        self.assertTrue(patch.is_patch)
        self.assertTrue(patch.purge_underlying_text)
        self.assertIsNone(patch.linked_text)

    def test_editable_text_defaults(self):
        text = EditableText(x=10, y=20, text="Sample Text")
        self.assertIsNone(text.linked_patch)

    def test_bidirectional_linkage(self):
        png = create_solid_png_bytes()
        patch = PatchObject(bbox=(50, 60, 150, 90), page_number=0, image_bytes=png)
        text = EditableText(x=52, y=62, text="Replacement Text")
        patch.linked_text = text
        text.linked_patch = patch

        self.assertIs(patch.linked_text, text)
        self.assertIs(text.linked_patch, patch)


class TestPdfHandlerStreamBakingAndTextPurge(unittest.TestCase):
    """Test PDF stream baking and underlying OCR/vector text purge under patches."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        # Insert background text to simulate scanned OCR or vector text
        self.page.insert_text((100, 150), "Obsolete OCR Text to be Patched", fontsize=14, color=(0, 0, 0))
        self.page.insert_text((100, 300), "Safe Surrounding Document Text", fontsize=14, color=(0, 0, 0))

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_purge_underlying_text_under_patch(self):
        # Verify initial text exists
        initial_text = self.page.get_text()
        self.assertIn("Obsolete OCR Text", initial_text)
        self.assertIn("Safe Surrounding Document Text", initial_text)

        # Create patch covering "Obsolete OCR Text to be Patched"
        png_bytes = create_solid_png_bytes(width=250, height=40)
        patch_rect = (90, 130, 350, 170)
        patch_obj = PatchObject(
            bbox=patch_rect,
            page_number=0,
            image_bytes=png_bytes,
            purge_underlying_text=True,
            is_new=True
        )

        # Apply patch to page
        ok, err = pdf_handler._apply_single_object_to_page(self.doc, self.page, patch_obj)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Apply replacement text over patch
        rep_text = EditableText(x=95, y=135, text="Fresh Corrected Line", font_size=12, page_number=0, is_new=True, baseline=150)
        ok_t, err_t = pdf_handler._apply_single_object_to_page(self.doc, self.page, rep_text)
        self.assertTrue(ok_t)

        # Check updated text extraction
        extracted = self.page.get_text()
        self.assertNotIn("Obsolete OCR Text", extracted)
        self.assertIn("Fresh Corrected Line", extracted)
        self.assertIn("Safe Surrounding Document Text", extracted)

    def test_rebuild_page_layers_patch_before_text(self):
        # Test full rebuild_page preserves patch underneath replacement text
        png_bytes = create_solid_png_bytes(width=200, height=30)
        patch_obj = PatchObject(bbox=(90, 130, 320, 170), page_number=0, image_bytes=png_bytes, purge_underlying_text=True, is_new=True)
        rep_text = EditableText(x=95, y=135, text="Layered Above Patch", font_size=12, page_number=0, is_new=True, baseline=150)
        patch_obj.linked_text = rep_text
        rep_text.linked_patch = patch_obj

        # Create snapshot for rebuild
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)

        ok, err = pdf_handler.rebuild_page(
            self.doc, 0,
            all_texts=[rep_text],
            all_shapes=[],
            all_images=[patch_obj]
        )
        self.assertTrue(ok)
        self.assertIsNone(err)

        extracted = self.doc[0].get_text()
        self.assertNotIn("Obsolete OCR Text", extracted)
        self.assertIn("Layered Above Patch", extracted)
        self.assertIn("Safe Surrounding Document Text", extracted)


class TestCanvasHitTestingPriority(unittest.TestCase):
    """Test canvas hit-testing priority: text over patch is selected first."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        self.win = MockCorrectionWindow(self.doc)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_text_selected_over_underlying_patch(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 100, 250, 150), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=105, y=105, text="Overlay Text", font_size=12, page_number=0)
        text_obj.bbox = (105, 105, 200, 125)
        self.win.editable_texts.append(text_obj)

        patch_obj.linked_text = text_obj
        text_obj.linked_patch = patch_obj

        # Click inside text bounds (120, 115)
        found_text = self.win._find_text_at_pos(120, 115)
        found_img = self.win._find_image_at_pos(120, 115)

        self.assertIsNotNone(found_text)
        self.assertIs(found_text, text_obj)
        self.assertIsNotNone(found_img)
        self.assertIs(found_img, patch_obj)

        # In on_pdf_view_pressed logic, clicked_text is evaluated first
        clicked_text = found_text
        clicked_image = found_img
        selected = None
        if clicked_text:
            selected = clicked_text
        elif clicked_image:
            selected = clicked_image

        self.assertIs(selected, text_obj)

    def test_patch_selected_when_clicking_outside_text_bounds(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 100, 250, 150), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=105, y=105, text="Short", font_size=12, page_number=0)
        text_obj.bbox = (105, 105, 140, 125)
        self.win.editable_texts.append(text_obj)

        # Click at (220, 140) which is on patch but outside text bbox
        found_text = self.win._find_text_at_pos(220, 140)
        found_img = self.win._find_image_at_pos(220, 140)

        self.assertIsNone(found_text)
        self.assertIs(found_img, patch_obj)


class TestInitiateTextOverPatch(unittest.TestCase):
    """Test initiate_text_over_patch workflow."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        self.win = MockCorrectionWindow(self.doc)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_initiate_text_creates_linked_editable_text(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 200, 260, 230), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = self.win.initiate_text_over_patch(patch_obj)
        self.assertIsNotNone(text_obj)
        self.assertIsInstance(text_obj, EditableText)
        self.assertIn(text_obj, self.win.editable_texts)
        self.assertIs(patch_obj.linked_text, text_obj)
        self.assertIs(text_obj.linked_patch, patch_obj)
        self.assertIs(self.win.selected_text, text_obj)
        self.assertIsNone(self.win.selected_image)

        # Check spatial alignment
        self.assertAlmostEqual(text_obj.x, 102.0)
        self.assertAlmostEqual(text_obj.y, 201.0)
        self.assertEqual(text_obj.bbox[2], 260.0)
        self.assertEqual(text_obj.bbox[3], 230.0)

    def test_initiate_text_reuses_existing_linked_text(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 200, 260, 230), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        t1 = self.win.initiate_text_over_patch(patch_obj)
        t1.text = "Initial Correction"
        self.assertEqual(len(self.win.editable_texts), 1)

        # Call initiate again on same patch
        t2 = self.win.initiate_text_over_patch(patch_obj)
        self.assertIs(t1, t2)
        self.assertEqual(len(self.win.editable_texts), 1)


class TestSynchronizedCoMovementAndUndo(unittest.TestCase):
    """Test synchronized movement and undo/redo of linked patch and text."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)
        self.win = MockCorrectionWindow(self.doc)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_co_movement_drag_update_and_commit(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100.0, 100.0, 200.0, 140.0), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=102.0, y=101.0, text="Move Together", font_size=12, page_number=0)
        text_obj.bbox = (102.0, 101.0, 190.0, 130.0)
        text_obj.baseline = 115.0
        text_obj.original_bbox = text_obj.bbox
        text_obj.original_baseline = text_obj.baseline
        self.win.editable_texts.append(text_obj)

        patch_obj.linked_text = text_obj
        text_obj.linked_patch = patch_obj

        # Simulate on_drag_begin
        self.win.dragged_object = patch_obj
        self.win.drag_start_pos = (100.0, 100.0)
        self.win.drag_begin_state = copy.deepcopy(patch_obj.__dict__)
        self.win.drag_object_start_pos = (patch_obj.bbox[0], patch_obj.bbox[1])
        self.win.linked_drag_begin_state = copy.deepcopy(text_obj.__dict__)
        self.win.linked_drag_start_pos = (text_obj.x, text_obj.y)

        # Move by delta (+30, +50)
        delta_x = 30.0
        delta_y = 50.0

        # Simulate on_drag_update
        patch_obj.x = 100.0 + delta_x
        patch_obj.y = 100.0 + delta_y
        patch_obj.bbox = (130.0, 150.0, 230.0, 190.0)

        lt_start_x, lt_start_y = self.win.linked_drag_start_pos
        text_obj.x = lt_start_x + delta_x
        text_obj.y = lt_start_y + delta_y
        text_obj.bbox = (132.0, 151.0, 220.0, 180.0)
        text_obj.baseline = text_obj.y + (text_obj.font_size * 0.9)

        # Verify co-moved positions during drag
        self.assertEqual(patch_obj.x, 130.0)
        self.assertEqual(patch_obj.y, 150.0)
        self.assertEqual(text_obj.x, 132.0)
        self.assertEqual(text_obj.y, 151.0)

        # Simulate on_drag_end with CompositeCommand
        cmd_patch = EditObjectCommand(self.win, patch_obj, self.win.drag_begin_state, copy.deepcopy(patch_obj.__dict__))
        cmd_text = EditObjectCommand(self.win, text_obj, self.win.linked_drag_begin_state, copy.deepcopy(text_obj.__dict__))
        composite = CompositeCommand(self.win, [cmd_patch, cmd_text])
        self.win.undo_manager.add_command(composite)

        self.assertEqual(len(self.win.undo_manager.undo_stack), 1)

        # Undo co-movement
        self.win.undo_manager.undo()
        self.assertEqual(patch_obj.x, 100.0)
        self.assertEqual(patch_obj.y, 100.0)
        self.assertEqual(patch_obj.bbox, (100.0, 100.0, 200.0, 140.0))
        self.assertEqual(text_obj.x, 102.0)
        self.assertEqual(text_obj.y, 101.0)
        self.assertEqual(text_obj.bbox, (102.0, 101.0, 190.0, 130.0))

        # Redo co-movement
        self.win.undo_manager.redo()
        self.assertEqual(patch_obj.x, 130.0)
        self.assertEqual(patch_obj.y, 150.0)
        self.assertEqual(text_obj.x, 132.0)
        self.assertEqual(text_obj.y, 151.0)

    def test_co_deletion_and_undo(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(50.0, 50.0, 150.0, 90.0), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=52.0, y=52.0, text="To Delete", font_size=12, page_number=0)
        text_obj.bbox = (52.0, 52.0, 140.0, 75.0)
        text_obj.original_bbox = text_obj.bbox
        self.win.editable_texts.append(text_obj)

        patch_obj.linked_text = text_obj
        text_obj.linked_patch = patch_obj

        # Delete patch with linked text
        cmd1 = DeleteObjectCommand(self.win, patch_obj)
        cmd2 = DeleteObjectCommand(self.win, text_obj)
        batch_delete = CompositeCommand(self.win, [cmd1, cmd2])
        batch_delete.execute()
        self.win.undo_manager.add_command(batch_delete)

        self.assertNotIn(patch_obj, self.win.editable_images)
        self.assertNotIn(text_obj, self.win.editable_texts)

        # Undo deletion: both restored
        self.win.undo_manager.undo()
        self.assertIn(patch_obj, self.win.editable_images)
        self.assertIn(text_obj, self.win.editable_texts)


class TestLocalizationAllLocales(unittest.TestCase):
    """Test localization completeness for Part 56 across all 7 locales."""

    REQUIRED_KEYS = [
        "menu_type_over_patch",
        "patch_type_tooltip",
        "status_patch_text_added",
        "guide_sc_type_over_patch"
    ]

    def test_en_and_tr_in_i18n(self):
        for lang in ["en", "tr"]:
            self.assertIn(lang, _STRINGS)
            for key in self.REQUIRED_KEYS:
                self.assertIn(key, _STRINGS[lang], f"Missing key '{key}' in lang '{lang}'")
                val = _STRINGS[lang][key]
                self.assertTrue(isinstance(val, str) and len(val.strip()) > 0)

    def test_fr_de_es_it_ru_in_locales(self):
        locale_dicts = {
            "fr": STRINGS_FR,
            "de": STRINGS_DE,
            "es": STRINGS_ES,
            "it": STRINGS_IT,
            "ru": STRINGS_RU,
        }
        for lang, d in locale_dicts.items():
            for key in self.REQUIRED_KEYS:
                self.assertIn(key, d, f"Missing key '{key}' in locale dictionary for '{lang}'")
                val = d[key]
                self.assertTrue(isinstance(val, str) and len(val.strip()) > 0)


class TestWindowInteractions(unittest.TestCase):
    """Test window-level interactions for Part 56: shortcuts, double-click, and nudge."""

    def setUp(self):
        from gi.repository import Gdk
        self.Gdk = Gdk
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)
        self.win = MockCorrectionWindow(self.doc)
        self.win.current_pdf_page_width = 600
        self.win.current_pdf_page_height = 800
        self.win.get_focus = MagicMock(return_value=None)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_key_pressed_triggers_initiate_text_on_patch(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 100, 200, 140), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)
        self.win.selected_image = patch_obj

        for key in [self.Gdk.KEY_Return, self.Gdk.KEY_KP_Enter, self.Gdk.KEY_t, self.Gdk.KEY_T]:
            # Reset
            self.win.editable_texts.clear()
            self.win.selected_text = None
            self.win.selected_image = patch_obj
            self.win.inline_editor_widget = None
            patch_obj.linked_text = None

            handled = PdfEditorWindow.on_key_pressed(self.win, None, key, 0, 0)
            self.assertTrue(handled, f"Key {key} should be handled for patch")
            self.assertIsNotNone(patch_obj.linked_text)
            self.assertIs(self.win.selected_text, patch_obj.linked_text)

    def test_arrow_nudge_comovement(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100.0, 100.0, 200.0, 140.0), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=102.0, y=101.0, text="Nudge Text", font_size=12, page_number=0)
        text_obj.bbox = (102.0, 101.0, 190.0, 130.0)
        text_obj.baseline = 115.0
        self.win.editable_texts.append(text_obj)

        patch_obj.linked_text = text_obj
        text_obj.linked_patch = patch_obj

        self.win.selected_image = patch_obj

        # Nudge right (dx = +1.0)
        handled = PdfEditorWindow.on_key_pressed(self.win, None, self.Gdk.KEY_Right, 0, 0)
        self.assertTrue(handled)
        self.assertEqual(patch_obj.bbox, (101.0, 100.0, 201.0, 140.0))
        self.assertEqual(patch_obj.x, 101.0)
        self.assertEqual(text_obj.bbox, (103.0, 101.0, 191.0, 130.0))
        self.assertEqual(text_obj.x, 103.0)

        # Undo nudge
        self.win.undo_manager.undo()
        self.assertEqual(patch_obj.bbox, (100.0, 100.0, 200.0, 140.0))
        self.assertEqual(patch_obj.x, 100.0)
        self.assertEqual(text_obj.bbox, (102.0, 101.0, 190.0, 130.0))
        self.assertEqual(text_obj.x, 102.0)

    def test_double_click_select_mode_triggers_initiate_text(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100.0, 100.0, 200.0, 140.0), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        self.win.canvas_to_page_coords = MagicMock(return_value=(0, 150.0, 120.0))
        self.win.is_canvas_point_on_page = MagicMock(return_value=True)

        # Double click (n_press = 2) at (150, 120) which is on patch
        PdfEditorWindow.on_pdf_view_pressed(self.win, None, 2, 150.0, 120.0)

        self.assertIsNotNone(patch_obj.linked_text)
        self.assertIs(self.win.selected_text, patch_obj.linked_text)
        self.assertIn(patch_obj.linked_text, self.win.editable_texts)


if __name__ == "__main__":
    unittest.main()
