"""
Tests for Part 55: Texture Matching, In-Place Covering & Layer Ordering.
Validates PatchObject representation, auto-placement, layer reordering (bring to front/back/forward/backward),
undo/redo integration, and localization across all supported languages.
"""

import os
import unittest
from unittest.mock import MagicMock, patch
import fitz

from word_sys_pdf_editor.models import (
    EditableText, EditableImage, EditableShape, PatchObject
)
from word_sys_pdf_editor.undo_manager import (
    AddObjectCommand, ReorderObjectCommand
)
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.i18n import _, _STRINGS


class MockLayerWindow:
    """Mock window for testing object reordering and patch operations."""
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.view_mode = False
        self.tool_mode = "select"
        self.last_captured_patch = None
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
        self.document_modified = False
        self.status_label = MagicMock()
        self.pdf_view = MagicMock()
        self.undo_manager = MagicMock()
        self.undo_stack = []
        self.undo_manager.add_command.side_effect = lambda cmd: self.undo_stack.append(cmd)

    def _update_ui_state(self):
        pass

    def _refresh_thumbnail(self, page_index):
        pass

    def reorder_selected_object(self, direction):
        from word_sys_pdf_editor.window import PdfEditorWindow
        return PdfEditorWindow.reorder_selected_object(self, direction)

    def paste_clone_patch(self, center_pos=None):
        from word_sys_pdf_editor.window import PdfEditorWindow
        return PdfEditorWindow.paste_clone_patch(self, center_pos)


class TestPatchObject(unittest.TestCase):
    """Test PatchObject model creation, properties, and serialization."""

    def test_patch_object_initialization(self):
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        patch = PatchObject(
            bbox=(10.0, 20.0, 110.0, 120.0),
            page_number=0,
            image_bytes=dummy_png,
            opacity=0.85
        )
        self.assertIsInstance(patch, EditableImage)
        self.assertEqual(patch.bbox, (10.0, 20.0, 110.0, 120.0))
        self.assertEqual(patch.page_number, 0)
        self.assertEqual(patch.image_bytes, dummy_png)
        self.assertEqual(patch.opacity, 0.85)
        self.assertTrue(patch.is_new)

    def test_patch_object_properties(self):
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        patch = PatchObject(
            bbox=(15.0, 25.0, 115.0, 125.0),
            page_number=1,
            image_bytes=dummy_png,
            opacity=0.9
        )
        self.assertIsInstance(patch, EditableImage)
        self.assertEqual(patch.bbox, (15.0, 25.0, 115.0, 125.0))
        self.assertEqual(patch.page_number, 1)
        self.assertEqual(patch.image_bytes, dummy_png)
        self.assertEqual(patch.opacity, 0.9)
        self.assertTrue(patch.is_new)


class TestReorderObjectCommand(unittest.TestCase):
    """Test undoable ReorderObjectCommand execution."""

    def setUp(self):
        self.doc = fitz.open()
        self.win = MockLayerWindow(self.doc)

    def tearDown(self):
        self.doc.close()

    def test_reorder_command_execute_undo_redo(self):
        t1 = EditableText(x=10, y=10, text="First")
        t2 = EditableText(x=20, y=20, text="Second")
        t3 = EditableText(x=30, y=30, text="Third")
        self.win.editable_texts = [t1, t2, t3]

        # Reorder t1 from index 0 to index 2 (bring to front)
        cmd = ReorderObjectCommand(self.win, t1, 0, 2)
        cmd.execute()
        self.assertEqual(self.win.editable_texts, [t2, t3, t1])
        self.assertTrue(self.win.document_modified)

        # Undo command
        cmd.undo()
        self.assertEqual(self.win.editable_texts, [t1, t2, t3])

        # Redo command
        cmd.redo()
        self.assertEqual(self.win.editable_texts, [t2, t3, t1])

    def test_reorder_window_actions(self):
        img1 = EditableImage(bbox=(0, 0, 50, 50), page_number=0, xref=None, image_bytes=b"dummy1")
        img2 = EditableImage(bbox=(50, 50, 100, 100), page_number=0, xref=None, image_bytes=b"dummy2")
        img3 = EditableImage(bbox=(100, 100, 150, 150), page_number=0, xref=None, image_bytes=b"dummy3")
        self.win.editable_images = [img1, img2, img3]

        # Select middle object img2
        self.win.selected_image = img2

        # Move forward -> index 2
        res = self.win.reorder_selected_object("forward")
        self.assertTrue(res)
        self.assertEqual(self.win.editable_images, [img1, img3, img2])

        # Move to back -> index 0
        res = self.win.reorder_selected_object("back")
        self.assertTrue(res)
        self.assertEqual(self.win.editable_images, [img2, img1, img3])

        # Move to front -> index 2
        res = self.win.reorder_selected_object("front")
        self.assertTrue(res)
        self.assertEqual(self.win.editable_images, [img1, img3, img2])

        # Move backward -> index 1
        res = self.win.reorder_selected_object("backward")
        self.assertTrue(res)
        self.assertEqual(self.win.editable_images, [img1, img2, img3])

        # Boundary: move backward when already at 0
        self.win.selected_image = img1
        res = self.win.reorder_selected_object("backward")
        self.assertFalse(res)

        # Boundary: move forward when already at end
        self.win.selected_image = img3
        res = self.win.reorder_selected_object("forward")
        self.assertFalse(res)


class TestPasteClonePatch(unittest.TestCase):
    """Test pasting captured clone patches onto document canvas."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        self.win = MockLayerWindow(self.doc)
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        self.win.last_captured_patch = {
            "image_bytes": dummy_png,
            "bbox": (50.0, 50.0, 150.0, 110.0),
            "page_number": 0,
            "dpi": 300
        }

    def tearDown(self):
        self.doc.close()

    def test_paste_clone_patch_explicit_position(self):
        res = self.win.paste_clone_patch(center_pos=(300.0, 400.0))
        self.assertTrue(res)
        self.assertEqual(len(self.win.editable_images), 1)
        patch = self.win.editable_images[0]
        self.assertIsInstance(patch, PatchObject)
        # Size was (150-50)=100w, (110-50)=60h. Centered at (300, 400) -> (250, 370, 350, 430)
        self.assertEqual(patch.bbox, (250.0, 370.0, 350.0, 430.0))
        self.assertEqual(self.win.selected_image, patch)
        self.assertEqual(self.win.tool_mode, "select")

    def test_paste_clone_patch_boundary_clamping(self):
        # Center near right edge (580, 780)
        res = self.win.paste_clone_patch(center_pos=(580.0, 780.0))
        self.assertTrue(res)
        patch = self.win.editable_images[0]
        x1, y1, x2, y2 = patch.bbox
        self.assertGreaterEqual(x1, 0.0)
        self.assertGreaterEqual(y1, 0.0)
        self.assertLessEqual(x2, 600.0)
        self.assertLessEqual(y2, 800.0)

    def test_paste_clone_patch_without_captured_data(self):
        self.win.last_captured_patch = None
        res = self.win.paste_clone_patch((200, 200))
        self.assertFalse(res)


class TestPart55Localization(unittest.TestCase):
    """Ensure all 7 locales have complete translations for Part 55."""

    REQUIRED_KEYS = [
        "patch_placed_status",
        "patch_pasted_status",
        "action_bring_to_front",
        "action_send_to_back",
        "action_bring_forward",
        "action_send_backward",
        "status_reordered_front",
        "status_reordered_back",
        "status_reordered_forward",
        "status_reordered_backward",
        "btn_paste_patch",
        "guide_sc_layer_front",
        "guide_sc_layer_back",
        "guide_sc_layer_forward",
        "guide_sc_layer_backward",
    ]

    def test_all_locales_have_part55_keys(self):
        for lang, trans in _STRINGS.items():
            for key in self.REQUIRED_KEYS:
                self.assertIn(
                    key, trans,
                    f"Language '{lang}' missing required Part 55 localization key '{key}'"
                )
                self.assertTrue(
                    len(trans[key].strip()) > 0,
                    f"Language '{lang}' has empty text for key '{key}'"
                )


if __name__ == "__main__":
    unittest.main()
