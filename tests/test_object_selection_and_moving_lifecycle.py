import unittest
import os
import copy
from unittest.mock import MagicMock

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk

from word_sys_pdf_editor.models import (
    EditableText, EditableImage, EditableShape, EditableStroke, AcroFormField
)
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.i18n import set_setting


class TestObjectSelectionAndMovingLifecycle(unittest.TestCase):
    """Test suite verifying that moving is only enabled when an object is already selected.

    First click always selects the object without moving it;
    second click and hold enables movement.
    """

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Adw.Application(application_id='org.word_sys.test_selection_move_lifecycle')
        except Exception:
            cls.app = None

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)

        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.set_continuous_scroll_mode(False)
        self.win.doc = self.doc
        self.win.current_page_index = 0
        self.win.current_pdf_page_width = 600
        self.win.current_pdf_page_height = 800
        self.win.zoom_level = 1.0
        self.win.view_mode = False
        self.win.tool_mode = "select"
        self.win.undo_manager = MagicMock()

    def tearDown(self):
        set_setting("view_mode", "single")
        if hasattr(self, 'win') and self.win:
            try:
                self.win.close_document()
                self.win.destroy()
            except Exception:
                pass
        doc = getattr(self, 'doc', None)
        if doc is not None and not getattr(doc, 'is_closed', True):
            try:
                doc.close()
            except Exception:
                pass

    def test_first_click_selects_text_without_moving_second_click_moves(self):
        """First click selects text without moving; second click and hold moves it."""
        text_obj = EditableText(100.0, 100.0, "Sample Text", font_size=12.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)

        gesture = MagicMock()

        # 1. First click: mouse press over text object
        self.win.on_pdf_view_pressed(gesture, 1, 120.0, 110.0)
        self.assertEqual(self.win.selected_text, text_obj)
        self.assertFalse(self.win._can_drag_object)

        # First drag begin attempt during first click
        self.win.on_drag_begin(gesture, 120.0, 110.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

        # Attempt to drag during first click
        self.win.on_drag_update(gesture, 60.0, 40.0)
        self.assertEqual(text_obj.x, 100.0)
        self.assertEqual(text_obj.y, 100.0)

        # Release first click
        self.win.on_drag_end(gesture, 60.0, 40.0)
        self.win._on_pdf_view_released(gesture, 1, 120.0, 110.0)
        self.win.undo_manager.add_command.assert_not_called()
        self.assertEqual(self.win.selected_text, text_obj)
        self.assertEqual(text_obj.x, 100.0)
        self.assertEqual(text_obj.y, 100.0)

        # 2. Second click and hold on the now-selected text object
        gesture.reset_mock()
        self.win.on_pdf_view_pressed(gesture, 1, 120.0, 110.0)
        self.assertTrue(self.win._can_drag_object)

        self.win.on_drag_begin(gesture, 120.0, 110.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, text_obj)

        # Drag update moves the object
        self.win.on_drag_update(gesture, 50.0, 30.0)
        self.assertEqual(text_obj.x, 150.0)
        self.assertEqual(text_obj.y, 130.0)

        # Release commits the move
        self.win.on_drag_end(gesture, 50.0, 30.0)
        self.win.undo_manager.add_command.assert_called_once()
        self.assertIsNone(self.win.dragged_object)

    def test_first_click_selects_image_without_moving_second_click_moves(self):
        """First click selects image without moving; second click and hold moves it."""
        image_obj = EditableImage(
            bbox=(200.0, 200.0, 300.0, 300.0),
            xref=1,
            page_number=0,
            image_bytes=b"dummy_data"
        )
        self.win.editable_images.append(image_obj)

        gesture = MagicMock()

        # First click: selects image
        self.win.on_pdf_view_pressed(gesture, 1, 250.0, 250.0)
        self.assertEqual(self.win.selected_image, image_obj)

        self.win.on_drag_begin(gesture, 250.0, 250.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

        self.win.on_drag_update(gesture, 40.0, 40.0)
        self.assertEqual(image_obj.bbox, (200.0, 200.0, 300.0, 300.0))

        self.win.on_drag_end(gesture, 40.0, 40.0)
        self.win._on_pdf_view_released(gesture, 1, 250.0, 250.0)

        # Second click and hold: moves image
        gesture.reset_mock()
        self.win.on_pdf_view_pressed(gesture, 1, 250.0, 250.0)
        self.win.on_drag_begin(gesture, 250.0, 250.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, image_obj)

        self.win.on_drag_update(gesture, 30.0, 20.0)
        self.assertEqual(image_obj.bbox, (230.0, 220.0, 330.0, 320.0))

        self.win.on_drag_end(gesture, 30.0, 20.0)
        self.win.undo_manager.add_command.assert_called_once()

    def test_first_click_selects_shape_without_moving_second_click_moves(self):
        """First click selects shape without moving; second click and hold moves it."""
        shape_obj = EditableShape(
            shape_type=EditableShape.SHAPE_RECTANGLE,
            bbox=(50.0, 50.0, 150.0, 150.0),
            page_number=0
        )
        self.win.editable_shapes.append(shape_obj)

        gesture = MagicMock()

        # First click
        self.win.on_pdf_view_pressed(gesture, 1, 100.0, 100.0)
        self.assertEqual(self.win.selected_shape, shape_obj)

        self.win.on_drag_begin(gesture, 100.0, 100.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

        self.win.on_drag_update(gesture, 30.0, 30.0)
        self.assertEqual(shape_obj.bbox, (50.0, 50.0, 150.0, 150.0))

        self.win.on_drag_end(gesture, 30.0, 30.0)
        self.win._on_pdf_view_released(gesture, 1, 100.0, 100.0)

        # Second click and hold
        gesture.reset_mock()
        self.win.on_pdf_view_pressed(gesture, 1, 100.0, 100.0)
        self.win.on_drag_begin(gesture, 100.0, 100.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, shape_obj)

        self.win.on_drag_update(gesture, 40.0, 50.0)
        self.assertEqual(shape_obj.bbox, (90.0, 100.0, 190.0, 200.0))
        self.win.on_drag_end(gesture, 40.0, 50.0)
        self.win.undo_manager.add_command.assert_called_once()

    def test_click_different_object_switches_selection_without_moving(self):
        """Clicking a different object selects it and does not move either object."""
        text_a = EditableText(50.0, 50.0, "Text A", font_size=12.0)
        text_a.bbox = (50.0, 50.0, 120.0, 70.0)
        text_a.page_number = 0
        self.win.editable_texts.append(text_a)

        text_b = EditableText(250.0, 250.0, "Text B", font_size=12.0)
        text_b.bbox = (250.0, 250.0, 320.0, 270.0)
        text_b.page_number = 0
        self.win.editable_texts.append(text_b)

        # Select Text A
        self.win.select_object(text_a)
        self.assertEqual(self.win.selected_text, text_a)

        gesture = MagicMock()

        # Click on Text B
        self.win.on_pdf_view_pressed(gesture, 1, 260.0, 260.0)
        self.assertEqual(self.win.selected_text, text_b)

        # Movement must be denied on first click of Text B
        self.win.on_drag_begin(gesture, 260.0, 260.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

        # Drag update does not move Text B
        self.win.on_drag_update(gesture, 50.0, 50.0)
        self.assertEqual(text_b.x, 250.0)
        self.assertEqual(text_b.y, 250.0)

        self.win.on_drag_end(gesture, 50.0, 50.0)
        self.win._on_pdf_view_released(gesture, 1, 260.0, 260.0)

        # Second click on Text B enables move
        gesture.reset_mock()
        self.win.on_pdf_view_pressed(gesture, 1, 260.0, 260.0)
        self.win.on_drag_begin(gesture, 260.0, 260.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, text_b)

    def test_click_empty_canvas_deselects_and_denies_movement(self):
        """Clicking empty space clears selection and prevents dragging."""
        text_obj = EditableText(100.0, 100.0, "Selected Text", font_size=12.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)
        self.win.select_object(text_obj)

        gesture = MagicMock()
        # Click on empty area (400, 400)
        self.win.on_pdf_view_pressed(gesture, 1, 400.0, 400.0)
        self.assertIsNone(self.win.selected_text)
        self.assertIsNone(self.win.get_selected_object())

        self.win.on_drag_begin(gesture, 400.0, 400.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.win.dragged_object)

    def test_direct_on_drag_begin_on_unselected_object_selects_first_then_moves(self):
        """Direct call to on_drag_begin on unselected object selects on call 1 and moves on call 2."""
        text_obj = EditableText(100.0, 100.0, "Direct Drag Text", font_size=12.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)

        gesture = MagicMock()

        # Call 1: unselected -> selects without dragging
        self.win.on_drag_begin(gesture, 120.0, 110.0)
        self.assertEqual(self.win.selected_text, text_obj)
        self.assertIsNone(self.win.dragged_object)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.DENIED)

        # Call 2: now selected -> enables movement
        gesture.reset_mock()
        self.win._on_pdf_view_released(gesture, 1, 120.0, 110.0)
        self.win.on_drag_begin(gesture, 120.0, 110.0)
        self.assertEqual(self.win.dragged_object, text_obj)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
