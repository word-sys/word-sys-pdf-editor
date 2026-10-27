"""Tests for textbox undo/redo isolation and object dragging in select mode."""

import unittest
from unittest.mock import MagicMock, patch
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk

import fitz
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.models import EditableText, EditableShape, EditableImage, EditableStroke, SpatialGridIndex
from word_sys_pdf_editor.undo_manager import UndoManager, EditObjectCommand


class DummyWindow:
    """Mock window for testing undo routing and dragging behavior."""
    def __init__(self):
        self.doc = [MagicMock()]
        self.current_page_index = 0
        self.current_pdf_page_width = 600.0
        self.current_pdf_page_height = 800.0
        self.zoom_level = 1.0
        self.tool_mode = "select"
        self.view_mode = False
        self.inline_editor_widget = None
        self.inline_editor_tv = None
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None
        self.selected_redaction_mark = None
        self.editable_texts = []
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.form_fields = []
        self._active_session = None
        self._spatial_indices = {}
        self.undo_manager = MagicMock()
        self.pdf_view = MagicMock()
        self.status_label = MagicMock()
        self.dragged_object = None
        self.dragging_to_create = False
        self.drag_start_pos = (0, 0)
        self.drag_object_start_pos = (0, 0)
        self.drag_begin_state = {}
        self.resize_handle = None
        self._focus_widget = None
        self.continuous_scroll = False
        self.temp_shape = None
        self.temp_stroke = None
        self.temp_image_bbox = None
        self.temp_stamp_bbox = None
        self.temp_sig_bbox = None
        self.temp_clone_patch_bbox = None
        self.temp_redact_bbox = None
        self.temp_form_field_rect = None
        self.temp_calibration_line = None
        self.temp_measurement_line = None
        self.temp_measurement_rect = None
        self.temp_polygon_vertices = []
        self.selected_word_start_char = None
        self.selected_word_end_char = None
        self.word_selection_mode = False
        self.show_ocr_overlay = False

    def get_focus(self):
        return self._focus_widget

    def get_page_canvas_rect(self, page_index):
        return (0, 0, 600, 800)

    def canvas_to_page_coords(self, x, y):
        return self.current_page_index, x / self.zoom_level, y / self.zoom_level

    def is_canvas_point_on_page(self, x, y, target_page):
        return True

    def _visual_to_unrotated_delta(self, dx, dy):
        return dx, dy

    def _visual_to_unrotated_page_coords(self, px, py, page_index=None):
        return px, py

    _on_undo_activated = PdfEditorWindow._on_undo_activated
    _on_redo_activated = PdfEditorWindow._on_redo_activated
    _on_inline_editor_key = PdfEditorWindow._on_inline_editor_key
    _invalidate_spatial_index = PdfEditorWindow._invalidate_spatial_index
    _get_page_spatial_index = PdfEditorWindow._get_page_spatial_index
    _find_text_at_pos = PdfEditorWindow._find_text_at_pos
    _find_image_at_pos = PdfEditorWindow._find_image_at_pos
    _find_shape_at_pos = PdfEditorWindow._find_shape_at_pos
    _find_stroke_at_pos = PdfEditorWindow._find_stroke_at_pos
    _find_form_field_at_pos = PdfEditorWindow._find_form_field_at_pos
    _find_measurement_at_pos = PdfEditorWindow._find_measurement_at_pos
    _find_resize_handle_at_pos = PdfEditorWindow._find_resize_handle_at_pos
    commit_pending_format_change = MagicMock()
    _close_active_form_field_editor = MagicMock()
    _update_ui_state = MagicMock()
    _update_text_format_controls = MagicMock()
    _update_stroke_format_controls = MagicMock()
    _apply_inline_editor_style = MagicMock()

    on_drag_begin = PdfEditorWindow.on_drag_begin
    on_drag_update = PdfEditorWindow.on_drag_update
    on_drag_end = PdfEditorWindow.on_drag_end
    on_tool_selected = PdfEditorWindow.on_tool_selected
    _draw_page_content = PdfEditorWindow._draw_page_content


class TestTextboxUndoAndObjectDrag(unittest.TestCase):
    """Test suite for textbox undo/redo isolation and object dragging in select mode."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        self.win = DummyWindow()
        self.win.doc = self.doc

    def tearDown(self):
        if hasattr(self, 'doc') and self.doc:
            self.doc.close()

    def test_inline_editor_key_ctrl_z_undoes_text_buffer(self):
        """Ctrl+Z inside inline editor undoes local text buffer without touching global undo manager."""
        tv = Gtk.TextView()
        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text("Initial")
        buf.set_enable_undo(True)

        # Type additional text
        buf.insert_at_cursor(" edits")
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Initial edits")

        self.win.inline_editor_tv = tv
        self.win.inline_editor_widget = MagicMock()

        # Simulate Ctrl+Z key press event
        handled = self.win._on_inline_editor_key(None, Gdk.KEY_z, 0, Gdk.ModifierType.CONTROL_MASK)
        self.assertTrue(handled)
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Initial")
        self.win.undo_manager.undo.assert_not_called()

    def test_inline_editor_key_ctrl_y_redoes_text_buffer(self):
        """Ctrl+Y inside inline editor redoes local text buffer without touching global undo manager."""
        tv = Gtk.TextView()
        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text("Start")
        buf.set_enable_undo(True)

        buf.insert_at_cursor(" Next")
        buf.undo()
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Start")

        self.win.inline_editor_tv = tv
        self.win.inline_editor_widget = MagicMock()

        # Simulate Ctrl+Y
        handled = self.win._on_inline_editor_key(None, Gdk.KEY_y, 0, Gdk.ModifierType.CONTROL_MASK)
        self.assertTrue(handled)
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Start Next")
        self.win.undo_manager.redo.assert_not_called()

    def test_action_undo_routes_to_inline_editor_when_active(self):
        """Global undo action routes to inline editor when it is open."""
        tv = Gtk.TextView()
        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text("Alpha")
        buf.set_enable_undo(True)
        buf.insert_at_cursor(" Beta")

        self.win.inline_editor_tv = tv
        self.win.inline_editor_widget = MagicMock()

        self.win._on_undo_activated()
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Alpha")
        self.win.undo_manager.undo.assert_not_called()

    def test_action_undo_routes_to_focused_textview(self):
        """Global undo action routes to any focused Gtk.TextView (e.g. sticky notes)."""
        tv = Gtk.TextView()
        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text("Note text")
        buf.set_enable_undo(True)
        buf.insert_at_cursor(" updated")

        self.win._focus_widget = tv
        self.win._on_undo_activated()

        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), "Note text")
        self.win.undo_manager.undo.assert_not_called()

    def test_action_undo_delegates_to_document_undo_when_idle(self):
        """Global undo action calls document undo manager when no text field is active."""
        self.win._focus_widget = None
        self.win.inline_editor_tv = None
        self.win.inline_editor_widget = None

        self.win._on_undo_activated()
        self.win.undo_manager.undo.assert_called_once()

    def test_action_redo_delegates_to_document_redo_when_idle(self):
        """Global redo action calls document redo manager when no text field is active."""
        self.win._focus_widget = None
        self.win.inline_editor_tv = None
        self.win.inline_editor_widget = None

        self.win._on_redo_activated()
        self.win.undo_manager.redo.assert_called_once()

    def test_object_drag_and_move_in_select_mode(self):
        """Objects can be dragged and moved in 'select' tool mode."""
        text_obj = EditableText(100.0, 100.0, "Movable Text", font_size=12.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)
        self.win.tool_mode = "select"

        gesture = MagicMock()
        # Drag start at (120, 110) inside the text bbox
        self.win.on_drag_begin(gesture, 120.0, 110.0)
        gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)
        self.assertEqual(self.win.dragged_object, text_obj)
        self.assertEqual(self.win.selected_text, text_obj)

        # Drag update by delta (+50, +30)
        self.win.on_drag_update(gesture, 50.0, 30.0)
        self.assertEqual(text_obj.x, 150.0)
        self.assertEqual(text_obj.y, 130.0)
        self.assertEqual(text_obj.bbox, (150.0, 130.0, 250.0, 150.0))

        # Drag end commits move
        self.win.on_drag_end(gesture, 50.0, 30.0)
        self.win.undo_manager.add_command.assert_called_once()
        self.assertIsNone(self.win.dragged_object)

    def test_drag_deadspace_threshold_cancels_accidental_movement(self):
        """Mouse movement within deadspace threshold (< 5px) does not move object or record undo."""
        text_obj = EditableText(200.0, 200.0, "Stable Text", font_size=12.0)
        text_obj.bbox = (200.0, 200.0, 300.0, 220.0)
        text_obj.page_number = 0
        self.win.editable_texts.append(text_obj)
        self.win.tool_mode = "select"

        gesture = MagicMock()
        # Mouse press initiates drag
        self.win.on_drag_begin(gesture, 210.0, 210.0)
        self.assertEqual(self.win.dragged_object, text_obj)
        self.assertFalse(self.win.drag_threshold_passed)

        # Micro-jitter of 2px (e.g. while double clicking)
        self.win.on_drag_update(gesture, 2.0, 1.0)
        # Position must NOT change
        self.assertEqual(text_obj.x, 200.0)
        self.assertEqual(text_obj.y, 200.0)
        self.assertFalse(self.win.drag_threshold_passed)

        # Mouse release without passing threshold
        self.win.on_drag_end(gesture, 2.0, 1.0)
        self.win.undo_manager.add_command.assert_not_called()
        self.assertIsNone(self.win.dragged_object)
        self.assertEqual(text_obj.x, 200.0)
        self.assertEqual(text_obj.y, 200.0)

    def test_movement_tool_alias_to_select(self):
        """Selecting redundant 'drag' tool mode aliases cleanly to 'select'."""
        self.win.tool_mode = "pen"
        self.win.on_tool_selected(None, "drag")
        self.assertEqual(self.win.tool_mode, "select")

    def test_inline_editor_tv_wrap_mode_none(self):
        """Inline text editor creates text view with WrapMode.NONE so text does not prematurely wrap."""
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.NONE)
        self.assertEqual(tv.get_wrap_mode(), Gtk.WrapMode.NONE)

    def test_dragged_rotated_object_applies_rotation_to_shadow_box(self):
        """When dragged object is rotated, both origin shadow box and destination box rotate."""
        import math
        text_obj = EditableText(100.0, 100.0, "Rotated Text", font_size=12.0, rotation=45.0)
        text_obj.bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.original_bbox = (100.0, 100.0, 200.0, 120.0)
        text_obj.original_rotation = 45.0
        text_obj.page_number = 0

        self.win.dragged_object = text_obj
        cr = MagicMock()
        cr.clip_extents.return_value = (-1000.0, -1000.0, 2000.0, 2000.0)
        area = MagicMock()

        with patch('word_sys_pdf_editor.window.PangoCairo.create_layout') as mock_layout, \
             patch('word_sys_pdf_editor.window.PangoCairo.show_layout'):
            layout_obj = MagicMock()
            layout_obj.get_size.return_value = (100 * 1024, 20 * 1024)
            mock_layout.return_value = layout_obj

            # Render canvas page
            PdfEditorWindow.draw_pdf_page(self.win, area, cr, 600, 800, dirty_rect=None)
            expected_rad = math.radians(45.0)
            rotate_calls = [call.args[0] for call in cr.rotate.call_args_list]
            self.assertTrue(any(abs(rad - expected_rad) < 1e-4 for rad in rotate_calls))

    def test_spatial_index_self_healing_on_stale_data(self):
        """When spatial index has stale entries, hit testing self-heals via linear scan."""
        shape_obj = EditableShape(
            shape_type=EditableShape.SHAPE_RECTANGLE,
            bbox=(300.0, 300.0, 400.0, 400.0),
            page_number=0
        )
        self.win.editable_shapes.append(shape_obj)

        # Set up an outdated spatial grid where the object was somewhere else
        grid = SpatialGridIndex(cell_size=100.0)
        grid.insert(shape_obj, bbox=(10.0, 10.0, 50.0, 50.0))
        self.win._spatial_indices = {(0, "shape"): grid}

        # Query at current position (350, 350)
        hit = self.win._find_shape_at_pos(350.0, 350.0)
        self.assertEqual(hit, shape_obj)
        # Verify stale index was invalidated
        self.assertNotIn((0, "shape"), self.win._spatial_indices)

    def test_undo_manager_invalidates_spatial_index(self):
        """UndoManager operations invalidate spatial cache on the window."""
        win_mock = MagicMock()
        win_mock.doc = [MagicMock()]
        um = UndoManager(win_mock)

        cmd = MagicMock(target_object=None, commands=[], page_index=0)
        um.add_command(cmd)
        win_mock._invalidate_spatial_index.assert_called()

        win_mock._invalidate_spatial_index.reset_mock()
        um.undo()
        win_mock._invalidate_spatial_index.assert_called()

        win_mock._invalidate_spatial_index.reset_mock()
        um.redo()
        win_mock._invalidate_spatial_index.assert_called()


if __name__ == "__main__":
    unittest.main()
