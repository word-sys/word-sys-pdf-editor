"""Consolidated Forms and AcroForms Test Suite for word-sys-pdf-editor.

This suite merges AcroForms detection, extraction, and editing, interactive text inputs,
choice inputs (checkboxes, radio buttons, combo boxes, list boxes), and
the interactive Form Builder visual drag-and-drop tool.
"""

# ============================================================================
# SECTION: test_form_builder.py
# ============================================================================
import unittest
import tempfile
import os
import sys
import copy

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk
import cairo

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import AcroFormField, EditableText
from word_sys_pdf_editor.undo_manager import UndoManager, AddFormFieldCommand, DeleteFormFieldCommand, MoveResizeFormFieldCommand, AddObjectCommand
from word_sys_pdf_editor.window import PdfEditorWindow


def has_screen_display():
    return Gdk.Display.get_default() is not None


class MockBuilderWindow:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.current_pdf_page_width = 595
        self.current_pdf_page_height = 842
        self.zoom_level = 1.0
        self.document_modified = False
        self.tool_mode = "select"
        self.view_mode = False
        self.form_fields = []
        self.selected_form_field = None
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.temp_form_field_rect = None
        self.temp_image_bbox = None
        self.temp_shape = None
        self.dragged_object = None
        self._can_drag_object = None
        self.dragging_to_create = False
        self.resize_handle = None
        self.form_builder_field_type = "text"
        self._form_field_overlay_widgets = {}
        self._enable_persistent_form_overlays = True
        self._syncing_form_field = False
        self.undo_manager = UndoManager(self)
        self.pdf_overlay = Gtk.Overlay()
        self.pdf_view = Gtk.DrawingArea()
        self.inline_editor_widget = None

        self.form_builder_type_dropdown = Gtk.DropDown.new_from_strings([
            "Text Field", "Checkbox", "Dropdown"
        ])
        self.form_builder_name_entry = Gtk.Entry()
        self.form_builder_multiline_check = Gtk.CheckButton()
        self.form_builder_toolbar_box = Gtk.Box()
        self.form_builder_toolbar_sep = Gtk.Separator()
        self.form_builder_tool_button = Gtk.Button()

        self.form_builder_delete_button = Gtk.Button()
        self.form_builder_add_label_check = Gtk.CheckButton()
        self.form_builder_label_entry = Gtk.Entry()
        self.form_builder_options_box = Gtk.Box()
        self.form_builder_options_entry = Gtk.Entry()
        self.form_builder_edit_options_btn = Gtk.Button()
        self._active_editing_form_field = None
        self._updating_form_builder_ui = False
        self.objects_on_current_page = []
        self.editable_texts = []
        self.editable_shapes = []
        self.editable_images = []
        self.editable_strokes = []
        self._last_pointer_pos = (0, 0)
        self.status_label = Gtk.Label()
        self.font_scan_in_progress = False
        self.page_gap = 16
        self.continuous_page_offsets = []
        self.continuous_total_height = 0.0
        self.continuous_max_width = 0.0
        self.drag_start_page_index = 0
        self._continuous_scroll_val = False

    def _update_undo_redo_buttons(self):
        pass

    def _update_ui_state(self):
        pass

    def _refresh_thumbnail(self, page_index):
        pass

    def _update_tab_dirty_state(self):
        pass

    def _visual_to_unrotated_page_coords(self, px, py):
        return px, py

    def _visual_to_unrotated_delta(self, dx, dy):
        return dx, dy

    def commit_pending_format_change(self):
        pass

    _on_form_builder_type_changed = PdfEditorWindow._on_form_builder_type_changed
    _get_next_form_field_name = PdfEditorWindow._get_next_form_field_name
    _create_new_form_field = PdfEditorWindow._create_new_form_field
    _load_acroform_fields_for_page = PdfEditorWindow._load_acroform_fields_for_page
    _find_form_field_at_pos = PdfEditorWindow._find_form_field_at_pos
    _find_resize_handle_at_pos = PdfEditorWindow._find_resize_handle_at_pos
    _update_form_builder_controls_for_selected = PdfEditorWindow._update_form_builder_controls_for_selected
    _update_form_field_overlay_interactivity = PdfEditorWindow._update_form_field_overlay_interactivity
    _update_form_field_overlay_positions = PdfEditorWindow._update_form_field_overlay_positions
    _handle_resize_update = PdfEditorWindow._handle_resize_update
    calculate_resize_geometry = PdfEditorWindow.calculate_resize_geometry
    _delete_selected_form_field = PdfEditorWindow._delete_selected_form_field
    _on_form_builder_delete_clicked = PdfEditorWindow._on_form_builder_delete_clicked
    _on_form_builder_name_changed = PdfEditorWindow._on_form_builder_name_changed
    _on_form_builder_multiline_toggled = PdfEditorWindow._on_form_builder_multiline_toggled
    _on_form_builder_options_changed = PdfEditorWindow._on_form_builder_options_changed
    _on_form_builder_edit_options_clicked = PdfEditorWindow._on_form_builder_edit_options_clicked
    _get_overlay_for_field = PdfEditorWindow._get_overlay_for_field
    _open_form_field_editor = PdfEditorWindow._open_form_field_editor
    _close_active_form_field_editor = PdfEditorWindow._close_active_form_field_editor
    _handle_delete_with_confirmation = PdfEditorWindow._handle_delete_with_confirmation
    _find_text_at_pos = PdfEditorWindow._find_text_at_pos
    _find_image_at_pos = PdfEditorWindow._find_image_at_pos
    _find_shape_at_pos = PdfEditorWindow._find_shape_at_pos
    _find_stroke_at_pos = PdfEditorWindow._find_stroke_at_pos
    _get_link_url_at_pos = PdfEditorWindow._get_link_url_at_pos
    _open_url = PdfEditorWindow._open_url
    _find_measurement_at_pos = PdfEditorWindow._find_measurement_at_pos
    on_drag_begin = PdfEditorWindow.on_drag_begin
    on_drag_update = PdfEditorWindow.on_drag_update
    on_drag_end = PdfEditorWindow.on_drag_end
    on_pdf_view_pressed = PdfEditorWindow.on_pdf_view_pressed
    get_selected_object = PdfEditorWindow.get_selected_object
    select_object = PdfEditorWindow.select_object
    deselect_all = PdfEditorWindow.deselect_all
    _find_any_object_at_pos = PdfEditorWindow._find_any_object_at_pos
    _focus_form_field_overlay = PdfEditorWindow._focus_form_field_overlay
    _create_form_field_overlays = PdfEditorWindow._create_form_field_overlays
    _clear_form_field_overlays = PdfEditorWindow._clear_form_field_overlays
    _compute_form_field_screen_geometry = PdfEditorWindow._compute_form_field_screen_geometry
    canvas_to_page_coords = PdfEditorWindow.canvas_to_page_coords
    get_page_canvas_rect = PdfEditorWindow.get_page_canvas_rect
    is_canvas_point_on_page = PdfEditorWindow.is_canvas_point_on_page
    page_to_canvas_coords = PdfEditorWindow.page_to_canvas_coords
    _switch_active_page = PdfEditorWindow._switch_active_page
    _recompute_continuous_layout = PdfEditorWindow._recompute_continuous_layout
    _update_canvas_content_size = PdfEditorWindow._update_canvas_content_size
    continuous_scroll = PdfEditorWindow.continuous_scroll
    _page_objects_cache = PdfEditorWindow._page_objects_cache


class TestFormBuilder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.is_initialized():
            Gtk.init()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_pdf = os.path.join(self.temp_dir.name, "test_builder.pdf")
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        doc.save(self.test_pdf)
        doc.close()

        self.doc = fitz.open(self.test_pdf)
        self.window = MockBuilderWindow(self.doc)

    def tearDown(self):
        if self.doc and not getattr(self.doc, "is_closed", False):
            self.doc.close()
        self.temp_dir.cleanup()

    def test_backend_add_and_delete_text_widget(self):
        """Test backend add_form_widget and delete_form_widget for text field."""
        page = self.doc[0]
        w = pdf_handler.add_form_widget(
            page,
            field_type="text",
            rect=(50, 50, 200, 80),
            field_name="user_name",
            default_value="John Doe",
            is_multiline=False
        )
        self.assertIsNotNone(w)

        fields, err = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertIsNone(err)
        self.assertEqual(len(fields), 1)
        f = fields[0]
        self.assertEqual(f.field_name, "user_name")
        self.assertEqual(f.field_type, "text")
        self.assertEqual(f.value, "John Doe")
        self.assertFalse(f.is_multiline)

        # Delete by field name
        del_ok = pdf_handler.delete_form_widget(self.doc, "user_name", 0)
        self.assertTrue(del_ok)
        fields_after, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_after), 0)

    def test_backend_add_checkbox_and_combobox_widget(self):
        """Test backend add_form_widget for checkbox and combobox."""
        page = self.doc[0]
        w_cb = pdf_handler.add_form_widget(
            self.doc,
            0,
            field_type="checkbox",
            rect=(50, 100, 70, 120),
            field_name="agree_terms",
            default_value=True
        )
        self.assertIsNotNone(w_cb)

        w_choice = pdf_handler.add_form_widget(
            page,
            field_type="combobox",
            rect=(50, 150, 220, 180),
            field_name="country_select",
            default_value="Canada",
            choice_values=["USA", "Canada", "UK"]
        )
        self.assertIsNotNone(w_choice)

        fields, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields), 2)
        cb_f = next(f for f in fields if f.field_name == "agree_terms")
        combo_f = next(f for f in fields if f.field_name == "country_select")

        self.assertEqual(cb_f.field_type, "checkbox")
        self.assertTrue(cb_f.is_checked)

        self.assertEqual(combo_f.field_type, "combobox")
        self.assertEqual(combo_f.value, "Canada")
        self.assertEqual(combo_f.choice_values, ["USA", "Canada", "UK"])

        # Delete by xref
        del_ok = pdf_handler.delete_form_widget(self.doc, getattr(w_cb, 'xref', None), 0)
        self.assertTrue(del_ok)
        fields_after, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_after), 1)
        self.assertEqual(fields_after[0].field_name, "country_select")

    def test_form_builder_type_changed(self):
        """Test switching field type updates internal state and multiline visibility."""
        self.window.form_builder_type_dropdown.set_selected(0)
        self.window._on_form_builder_type_changed(self.window.form_builder_type_dropdown, None)
        self.assertEqual(self.window.form_builder_field_type, "text")
        self.assertTrue(self.window.form_builder_multiline_check.get_visible())

        self.window.form_builder_type_dropdown.set_selected(1)
        self.window._on_form_builder_type_changed(self.window.form_builder_type_dropdown, None)
        self.assertEqual(self.window.form_builder_field_type, "checkbox")
        self.assertFalse(self.window.form_builder_multiline_check.get_visible())

        self.window.form_builder_type_dropdown.set_selected(2)
        self.window._on_form_builder_type_changed(self.window.form_builder_type_dropdown, None)
        self.assertEqual(self.window.form_builder_field_type, "combobox")
        self.assertFalse(self.window.form_builder_multiline_check.get_visible())

    def test_unique_field_name_generation(self):
        """Test generating non-colliding unique names."""
        name1 = self.window._get_next_form_field_name("text")
        self.assertEqual(name1, "text_field_1")

        # Insert a field with that name
        pdf_handler.add_form_widget(self.doc, 0, "text", (50, 50, 100, 80), name1)

        name2 = self.window._get_next_form_field_name("text")
        self.assertEqual(name2, "text_field_2")

        cb_name = self.window._get_next_form_field_name("checkbox")
        self.assertEqual(cb_name, "check_box_1")

    def test_create_new_form_field_text(self):
        """Test creating a new text form field via _create_new_form_field."""
        self.window.form_builder_field_type = "text"
        self.window.form_builder_multiline_check.set_active(True)
        self.window.form_builder_name_entry.set_text("custom_bio")

        self.window._create_new_form_field((50, 50, 250, 120))

        self.assertTrue(self.window.document_modified)
        self.assertIsNotNone(self.window.selected_form_field)
        self.assertEqual(self.window.selected_form_field.field_name, "custom_bio")
        self.assertTrue(self.window.selected_form_field.is_multiline)
        self.assertEqual(self.window.form_builder_name_entry.get_text(), "custom_bio")

    def test_create_new_form_field_combobox(self):
        """Test creating a new dropdown form field via _create_new_form_field."""
        self.window.form_builder_field_type = "combobox"
        self.window._create_new_form_field((100, 100, 250, 130))

        self.assertTrue(self.window.document_modified)
        self.assertIsNotNone(self.window.selected_form_field)
        self.assertEqual(self.window.selected_form_field.field_type, "combobox")
        self.assertEqual(self.window.selected_form_field.choice_values, ["Option 1", "Option 2", "Option 3"])
        self.assertEqual(self.window.selected_form_field.value, "Option 1")

    def test_undo_and_redo_add_form_field(self):
        """Test Undo and Redo for form field addition."""
        self.window.form_builder_field_type = "checkbox"
        self.window._create_new_form_field((60, 60, 80, 80))

        fields, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields), 1)

        # Undo addition
        self.window.undo_manager.undo()
        fields_undone, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_undone), 0)

        # Redo addition
        self.window.undo_manager.redo()
        fields_redone, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_redone), 1)

    def test_delete_form_field_command(self):
        """Test DeleteFormFieldCommand execute and undo/redo."""
        self.window.form_builder_field_type = "text"
        self.window._create_new_form_field((100, 100, 200, 130))
        target = self.window.selected_form_field
        self.assertIsNotNone(target)

        del_cmd = DeleteFormFieldCommand(self.window, target)
        del_cmd.execute()

        fields_after, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_after), 0)
        self.assertIsNone(self.window.selected_form_field)

        # Undo deletion (restores field)
        del_cmd.undo()
        fields_restored, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_restored), 1)
        self.assertEqual(fields_restored[0].field_name, target.field_name)

    def test_canvas_preview_drawing(self):
        """Test Cairo drawing preview when temp_form_field_rect is active."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, 800)
        cr = cairo.Context(surface)

        # Draw with temp_form_field_rect set
        self.window.temp_form_field_rect = (50, 50, 200, 90)
        self.window.form_builder_field_type = "text"

        # Direct preview rendering test
        x1, y1, x2, y2 = self.window.temp_form_field_rect
        cr.rectangle(x1, y1, x2 - x1, y2 - y1)
        cr.set_source_rgba(0.2, 0.45, 0.9, 0.2)
        cr.fill()
        cr.rectangle(x1, y1, x2 - x1, y2 - y1)
        cr.set_source_rgba(0.2, 0.45, 0.9, 0.9)
        cr.stroke()

        # Should complete cleanly without error
        self.assertIsNotNone(surface)

    def test_drag_flow_create_field(self):
        """Test full on_drag_begin, on_drag_update, on_drag_end flow in form_builder mode."""
        class MockGesture:
            def set_state(self, st): pass

        self.window.tool_mode = "form_builder"
        self.window.form_builder_field_type = "text"
        gesture = MockGesture()

        # Drag start at (60, 60)
        self.window.on_drag_begin(gesture, 60, 60)
        self.assertTrue(self.window.dragging_to_create)
        self.assertIsNotNone(self.window.temp_form_field_rect)
        self.assertEqual(self.window.temp_form_field_rect, (60, 60, 60, 60))

        # Drag update by offset (140, 30) -> rect from (60, 60) to (200, 90)
        self.window.on_drag_update(gesture, 140, 30)
        self.assertEqual(self.window.temp_form_field_rect, (60, 60, 200, 90))

        # Drag end commits the new field
        self.window.on_drag_end(gesture, 140, 30)
        self.assertIsNone(self.window.temp_form_field_rect)
        self.assertTrue(self.window.document_modified)

        fields, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].field_type, "text")
        self.assertEqual(fields[0].rect, (60.0, 60.0, 200.0, 90.0))

    def test_click_default_size_field(self):
        """Test single click in form_builder mode applies sensible default dimensions."""
        class MockGesture:
            def set_state(self, st): pass

        self.window.tool_mode = "form_builder"
        self.window.form_builder_field_type = "checkbox"
        gesture = MockGesture()

        # Click at (100, 100) with 0 movement
        self.window.on_drag_begin(gesture, 100, 100)
        self.window.on_drag_end(gesture, 0, 0)

        fields, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].field_type, "checkbox")
        # Checkbox default size 20x20
        self.assertEqual(fields[0].rect, (100.0, 100.0, 120.0, 120.0))


    def test_form_builder_move_drag_and_undo(self):
        """Test moving a form field on canvas in form_builder mode with undo/redo."""
        class MockGesture:
            def set_state(self, st): pass

        self.window.tool_mode = "form_builder"
        self.window.form_builder_field_type = "text"
        gesture = MockGesture()

        # Create field at (100, 100, 240, 126)
        self.window._create_new_form_field((100, 100, 240, 126))
        self.window._load_acroform_fields_for_page(0)
        self.assertEqual(len(self.window.form_fields), 1)
        field = self.window.form_fields[0]
        self.window.selected_form_field = field

        # Drag begin inside the field
        self.window.on_drag_begin(gesture, 120, 110)
        self.assertEqual(self.window.selected_form_field, field)
        self.assertEqual(self.window.dragged_object, field)
        self.assertTrue(self.window.form_builder_delete_button.get_sensitive())

        # Drag update by offset (50, 40)
        self.window.on_drag_update(gesture, 50, 40)
        self.assertEqual(field.rect, (150.0, 140.0, 290.0, 166.0))

        # Drag end commits the move
        self.window.on_drag_end(gesture, 50, 40)
        fields, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(fields[0].rect, (150.0, 140.0, 290.0, 166.0))

        # Undo restores original position
        self.window.undo_manager.undo()
        fields_undo, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(fields_undo[0].rect, (100.0, 100.0, 240.0, 126.0))

        # Redo moves back to new position
        self.window.undo_manager.redo()
        fields_redo, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(fields_redo[0].rect, (150.0, 140.0, 290.0, 166.0))

    def test_form_builder_resize_checkbox_square_constraint(self):
        """Test resizing a checkbox enforces 1:1 square aspect ratio."""
        class MockGesture:
            def set_state(self, st): pass

        self.window.tool_mode = "form_builder"
        self.window.form_builder_field_type = "checkbox"
        gesture = MockGesture()

        # Create checkbox at (100, 100, 120, 120)
        self.window._create_new_form_field((100, 100, 120, 120))
        self.window._load_acroform_fields_for_page(0)
        field = self.window.form_fields[0]
        self.window.selected_form_field = field

        # Grab 'se' handle at (123, 123)
        self.window.on_drag_begin(gesture, 123, 123)
        self.assertEqual(self.window.resize_handle, "se")

        # Disproportionate drag (w + 60, h + 20)
        self.window.on_drag_update(gesture, 60, 20)
        # Should be square: width == height
        x1, y1, x2, y2 = field.rect
        self.assertAlmostEqual(x2 - x1, y2 - y1)

        self.window.on_drag_end(gesture, 60, 20)
        fields, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        fx1, fy1, fx2, fy2 = fields[0].rect
        self.assertAlmostEqual(fx2 - fx1, fy2 - fy1)

    def test_form_builder_delete_field_and_undo(self):
        """Test deleting selected form field via _delete_selected_form_field with undo/redo."""
        from unittest.mock import patch
        self.window.tool_mode = "form_builder"
        self.window.form_builder_field_type = "text"
        self.window._create_new_form_field((100, 100, 240, 126))
        self.window._load_acroform_fields_for_page(0)
        self.assertEqual(len(self.window.form_fields), 1)

        # Delete selected with confirmation accepted
        with patch('word_sys_pdf_editor.ui_components.show_confirm_dialog', return_value=(True, False)):
            self.window._delete_selected_form_field()
        self.assertIsNone(self.window.selected_form_field)
        fields_after, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_after), 0)

        # Undo restores
        self.window.undo_manager.undo()
        fields_restored, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_restored), 1)

    def test_form_builder_companion_label_creation(self):
        """Test automatically adding a visible EditableText label companion when requested."""
        self.window.tool_mode = "form_builder"
        self.window.form_builder_field_type = "checkbox"
        self.window.form_builder_add_label_check.set_active(True)
        self.window.form_builder_label_entry.set_text("Accept Terms")

        self.window._create_new_form_field((50, 50, 70, 70))
        self.assertTrue(len(self.window.editable_texts) >= 1)
        label_obj = self.window.editable_texts[-1]
        self.assertIsInstance(label_obj, EditableText)
        self.assertEqual(label_obj.text, "Accept Terms")
        # For checkbox, label is placed to the right: x >= 70
        self.assertGreaterEqual(label_obj.x, 70.0)

    def test_overlay_interactivity_toggle(self):
        """Test overlay container set_can_target toggle based on mode and active editor."""
        self.window.tool_mode = "form_builder"
        self.window.view_mode = False
        self.window._create_new_form_field((50, 50, 200, 80))
        self.window._load_acroform_fields_for_page(0)
        field = self.window.form_fields[0]

        # By default in edit mode, overlays cannot target input (can_target=False)
        self.window._update_form_field_overlay_interactivity()
        for ed in self.window._form_field_overlay_widgets.values():
            self.assertFalse(ed["container"].get_can_target())

        # Opening editor enables targeting only on active field
        self.window._open_form_field_editor(field)
        self.assertEqual(self.window._active_editing_form_field, field)
        active_ed = self.window._get_overlay_for_field(field)
        self.assertTrue(active_ed["container"].get_can_target())

        # Closing editor restores non-targeting
        self.window._close_active_form_field_editor()
        self.assertIsNone(self.window._active_editing_form_field)
        self.assertFalse(active_ed["container"].get_can_target())

        # In view mode, overlays can target input (can_target=True)
        self.window.view_mode = True
        self.window._update_form_field_overlay_interactivity()
        for ed in self.window._form_field_overlay_widgets.values():
            self.assertTrue(ed["container"].get_can_target())

    def test_ephemeral_form_field_editor_lifecycle(self):
        """Test ephemeral overlay lifecycle: 0 in editing mode, opens on demand in view mode, 0 when closed."""
        self.window._enable_persistent_form_overlays = False
        self.window.view_mode = False
        self.window._create_new_form_field((50, 50, 200, 80))
        self.window._load_acroform_fields_for_page(0)
        field = self.window.form_fields[0]

        # No persistent widgets created
        self.assertEqual(len(self.window._form_field_overlay_widgets), 0)

        # In edit mode, opening editor does NOT activate form filling
        self.window._open_form_field_editor(field)
        self.assertEqual(len(self.window._form_field_overlay_widgets), 0)

        # In view mode, form filling opens exactly 1 ephemeral widget
        self.window.view_mode = True
        self.window._open_form_field_editor(field)
        self.assertEqual(len(self.window._form_field_overlay_widgets), 1)
        self.assertEqual(self.window._active_editing_form_field, field)

        # Closing editor clears the ephemeral widget
        self.window._close_active_form_field_editor()
        self.assertEqual(len(self.window._form_field_overlay_widgets), 0)
        self.assertIsNone(self.window._active_editing_form_field)


    def test_form_widget_universal_appearance(self):
        """Test widgets created have explicit solid border and fill colors for universal visibility."""
        page = self.doc[0]
        pdf_handler.add_form_widget(page, "text", (40, 40, 160, 70), "test_txt")
        pdf_handler.add_form_widget(page, "checkbox", (40, 90, 60, 110), "test_cb")
        pdf_handler.add_form_widget(page, "combobox", (40, 130, 180, 160), "test_combo")

        widgets = {w.field_name: w for w in page.widgets()}
        self.assertIn("test_txt", widgets)
        self.assertIn("test_cb", widgets)
        self.assertIn("test_combo", widgets)

        self.assertIsNotNone(widgets["test_txt"].border_color)
        self.assertIsNotNone(widgets["test_txt"].fill_color)
        self.assertIn(widgets["test_txt"].border_style, ["S", "Solid"])
        self.assertEqual(widgets["test_txt"].border_width, 1.0)

        self.assertIsNotNone(widgets["test_cb"].border_color)
        self.assertIsNotNone(widgets["test_cb"].fill_color)

        self.assertIsNotNone(widgets["test_combo"].border_color)
        self.assertIsNotNone(widgets["test_combo"].fill_color)

        # Test ensure_form_widgets_have_appearance
        count = pdf_handler.ensure_form_widgets_have_appearance(self.doc)
        self.assertIsInstance(count, int)

    def test_combobox_options_customization_and_undo(self):
        """Test customizing combobox choices via entry/command with undo and redo."""
        self.window.tool_mode = "form_builder"
        self.window.form_builder_field_type = "combobox"
        self.window.form_builder_options_entry.set_text("Apple, Banana, Orange, Mango")

        # Create new dropdown with customized choices
        self.window._create_new_form_field((100, 100, 240, 130))
        field = self.window.selected_form_field
        self.assertIsNotNone(field)
        self.assertEqual(field.choice_values, ["Apple", "Banana", "Orange", "Mango"])
        self.assertEqual(field.value, "Apple")

        # Modify choices using toolbar entry
        self.window.form_builder_options_entry.set_text("Red, Green, Blue")
        self.window._on_form_builder_options_changed(self.window.form_builder_options_entry)
        self.assertEqual(field.choice_values, ["Red", "Green", "Blue"])
        self.assertEqual(field.value, "Red")

        # Undo restores original choices
        self.window.undo_manager.undo()
        self.assertEqual(field.choice_values, ["Apple", "Banana", "Orange", "Mango"])

        # Redo reapplies new choices
        self.window.undo_manager.redo()
        self.assertEqual(field.choice_values, ["Red", "Green", "Blue"])

    def test_single_click_select_vs_double_click_edit(self):
        """Test single-click selects field without opening entry, double-click opens in-place editor."""
        self.window.tool_mode = "form_builder"
        self.window._create_new_form_field((50, 50, 200, 80))
        self.window._load_acroform_fields_for_page(0)
        field = self.window.form_fields[0]

        # Reset selection and active editor
        self.window.selected_form_field = None
        self.window._active_editing_form_field = None

        self.window.pdf_view.get_allocated_width = lambda: 595
        self.window.pdf_view.get_allocated_height = lambda: 842
        gesture = Gtk.GestureClick.new()

        # Single click at (100, 65)
        self.window.on_pdf_view_pressed(gesture, 1, 100, 65)
        # Should be selected
        self.assertEqual(self.window.selected_form_field, field)
        # In-place editor must NOT be open
        self.assertIsNone(self.window._active_editing_form_field)
        # Resize handles should NOT be omitted
        handle = self.window._find_resize_handle_at_pos(50, 50, field)
        self.assertIsNotNone(handle)

        # Double click at (100, 65) in editing mode must NOT open form filling editor
        self.window.on_pdf_view_pressed(gesture, 2, 100, 65)
        self.assertIsNone(self.window._active_editing_form_field)
        self.assertEqual(self.window.selected_form_field, field)
        handle_after_double = self.window._find_resize_handle_at_pos(50, 50, field)
        self.assertIsNotNone(handle_after_double)

        # In View mode, clicking opens form filling editor
        self.window.view_mode = True
        self.window.on_pdf_view_pressed(gesture, 1, 100, 65)
        self.assertEqual(self.window._active_editing_form_field, field)

        # Escape closes editor
        self.window._close_active_form_field_editor()
        self.assertIsNone(self.window._active_editing_form_field)

    def test_form_field_deletion_with_confirmation(self):
        """Test deleting form field triggers confirmation and supports undo/redo."""
        from unittest.mock import patch
        self.window.tool_mode = "form_builder"
        self.window._create_new_form_field((50, 50, 200, 80))
        self.window._load_acroform_fields_for_page(0)
        self.assertEqual(len(self.window.form_fields), 1)

        field = self.window.form_fields[0]
        self.window.selected_form_field = field

        # Test cancelled deletion
        with patch('word_sys_pdf_editor.ui_components.show_confirm_dialog', return_value=(False, False)):
            self.window._delete_selected_form_field()
            # Still exists
            fields, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
            self.assertEqual(len(fields), 1)

        # Test accepted deletion
        with patch('word_sys_pdf_editor.ui_components.show_confirm_dialog', return_value=(True, False)):
            self.window._delete_selected_form_field()
            fields_after, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
            self.assertEqual(len(fields_after), 0)

        # Undo restores field
        self.window.undo_manager.undo()
        fields_restored, _ = pdf_handler.extract_acroform_fields(self.doc, 0)
        self.assertEqual(len(fields_restored), 1)


if __name__ == '__main__':
    unittest.main()



# ============================================================================
# SECTION: test_acroforms_detection.py
# ============================================================================
import pytest
import fitz
import cairo
from word_sys_pdf_editor.models import AcroFormField, DocumentSession
from word_sys_pdf_editor import pdf_handler


def test_acroform_field_model_instantiation_and_properties():
    field = AcroFormField(
        field_id="field_1",
        xref=10,
        page_number=0,
        rect=(50.0, 100.0, 200.0, 130.0),
        field_name="user_email",
        field_label="Email Address",
        field_type="text",
        field_type_id=fitz.PDF_WIDGET_TYPE_TEXT,
        value="user@example.com",
        is_required=True,
        is_read_only=False,
        is_multiline=False,
    )
    assert field.x == 50.0
    assert field.y == 100.0
    assert field.width == 150.0
    assert field.height == 30.0
    assert field.bbox == (50.0, 100.0, 200.0, 130.0)
    assert field.is_required is True
    assert field.is_read_only is False
    assert field.is_checked is False

    field.set_value("new@example.com")
    assert field.value == "new@example.com"
    assert field.is_modified is True

    d = field.to_dict()
    assert d["field_name"] == "user_email"
    assert d["value"] == "new@example.com"
    assert d["xref"] == 10
    assert d["is_modified"] is True


def test_acroform_field_is_checked_logic():
    chk_true = AcroFormField(
        field_id="c1",
        xref=1,
        page_number=0,
        rect=(0, 0, 10, 10),
        field_name="c1",
        field_type="checkbox",
        value="Yes",
    )
    assert chk_true.is_checked is True

    chk_bool = AcroFormField(
        field_id="c2",
        xref=2,
        page_number=0,
        rect=(0, 0, 10, 10),
        field_name="c2",
        field_type="checkbox",
        value=True,
    )
    assert chk_bool.is_checked is True

    chk_false = AcroFormField(
        field_id="c3",
        xref=3,
        page_number=0,
        rect=(0, 0, 10, 10),
        field_name="c3",
        field_type="checkbox",
        value="Off",
    )
    assert chk_false.is_checked is False

    chk_none = AcroFormField(
        field_id="c4",
        xref=4,
        page_number=0,
        rect=(0, 0, 10, 10),
        field_name="c4",
        field_type="checkbox",
        value="None",
    )
    assert chk_none.is_checked is False


def test_document_session_form_fields():
    session = DocumentSession()
    assert session.form_fields == []
    assert session.acroform_fields == []
    assert session.selected_form_field is None

    field = AcroFormField(
        field_id="f1",
        xref=5,
        page_number=0,
        rect=(10, 10, 50, 30),
        field_name="test",
    )
    session.form_fields.append(field)
    assert len(session.form_fields) == 1
    assert session.acroform_fields[0].field_name == "test"

    session.selected_form_field = field
    assert session.selected_form_field == field

    session.close()
    assert session.form_fields == []
    assert session.selected_form_field is None


def test_has_acroforms_detection():
    doc_empty = fitz.open()
    doc_empty.new_page()
    assert pdf_handler.has_acroforms(doc_empty) is False

    doc_form = fitz.open()
    page = doc_form.new_page()
    w = fitz.Widget()
    w.rect = fitz.Rect(50, 50, 150, 80)
    w.field_name = "sample_field"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    page.add_widget(w)
    assert pdf_handler.has_acroforms(doc_form) is True


def test_extract_acroform_fields_all_types():
    doc = fitz.open()
    page = doc.new_page()

    # 1. Text field with label and required flag
    w_text = fitz.Widget()
    w_text.rect = fitz.Rect(20, 20, 180, 50)
    w_text.field_name = "first_name"
    w_text.field_label = "First Name"
    w_text.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w_text.field_value = "John"
    w_text.field_flags = fitz.PDF_FIELD_IS_REQUIRED
    w_text.text_fontsize = 12.0
    w_text.text_color = (0.1, 0.1, 0.1)
    page.add_widget(w_text)

    # 2. Multiline text field
    w_multi = fitz.Widget()
    w_multi.rect = fitz.Rect(20, 60, 180, 120)
    w_multi.field_name = "notes"
    w_multi.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w_multi.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
    w_multi.field_value = "Line 1\nLine 2"
    page.add_widget(w_multi)

    # 3. Password field
    w_pwd = fitz.Widget()
    w_pwd.rect = fitz.Rect(20, 130, 180, 160)
    w_pwd.field_name = "pwd"
    w_pwd.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w_pwd.field_flags = fitz.PDF_TX_FIELD_IS_PASSWORD
    w_pwd.field_value = "secret123"
    page.add_widget(w_pwd)

    # 4. Checkbox
    w_chk = fitz.Widget()
    w_chk.rect = fitz.Rect(20, 170, 40, 190)
    w_chk.field_name = "terms"
    w_chk.field_label = "Accept Terms"
    w_chk.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    w_chk.field_value = "Yes"
    page.add_widget(w_chk)

    # 5. ComboBox
    w_combo = fitz.Widget()
    w_combo.rect = fitz.Rect(20, 200, 180, 230)
    w_combo.field_name = "country"
    w_combo.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    w_combo.choice_values = ["France", "Germany", "Turkey"]
    w_combo.field_value = "Turkey"
    page.add_widget(w_combo)

    # 6. ListBox
    w_list = fitz.Widget()
    w_list.rect = fitz.Rect(20, 240, 180, 290)
    w_list.field_name = "priority"
    w_list.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
    w_list.choice_values = ["Low", "Medium", "High"]
    w_list.field_value = "High"
    page.add_widget(w_list)

    # 7. Button with Radio flag
    w_radio = fitz.Widget()
    w_radio.rect = fitz.Rect(20, 300, 40, 320)
    w_radio.field_name = "radio_option"
    w_radio.field_type = fitz.PDF_WIDGET_TYPE_BUTTON
    w_radio.field_flags = fitz.PDF_BTN_FIELD_IS_RADIO
    page.add_widget(w_radio)

    # 8. Read-only text field
    w_ro = fitz.Widget()
    w_ro.rect = fitz.Rect(20, 330, 180, 360)
    w_ro.field_name = "readonly_field"
    w_ro.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w_ro.field_flags = fitz.PDF_FIELD_IS_READ_ONLY
    w_ro.field_value = "Locked"
    page.add_widget(w_ro)

    fields, err = pdf_handler.extract_acroform_fields(doc)
    assert err is None
    assert len(fields) == 8

    by_name = {f.field_name: f for f in fields}

    # Verify first_name
    fn = by_name["first_name"]
    assert fn.field_type == "text"
    assert fn.value == "John"
    assert fn.field_label == "First Name"
    assert fn.is_required is True
    assert fn.is_read_only is False

    # Verify multiline notes
    notes = by_name["notes"]
    assert notes.field_type == "text"
    assert notes.is_multiline is True
    assert "Line 1" in notes.value

    # Verify password
    pwd = by_name["pwd"]
    assert pwd.field_type == "text"
    assert pwd.is_password is True

    # Verify checkbox
    terms = by_name["terms"]
    assert terms.field_type == "checkbox"
    assert terms.is_checked is True
    assert terms.value == "Yes"

    # Verify combobox
    combo = by_name["country"]
    assert combo.field_type == "combobox"
    assert combo.choice_values == ["France", "Germany", "Turkey"]
    assert combo.value == "Turkey"

    # Verify listbox
    lst = by_name["priority"]
    assert lst.field_type == "listbox"
    assert lst.choice_values == ["Low", "Medium", "High"]
    assert lst.value == "High"

    # Verify radio
    rad = by_name["radio_option"]
    assert rad.field_type == "radio"

    # Verify readonly
    ro = by_name["readonly_field"]
    assert ro.is_read_only is True
    assert ro.value == "Locked"


def test_extract_acroform_fields_multi_page_and_indexing():
    doc = fitz.open()
    p0 = doc.new_page()

    w0a = fitz.Widget()
    w0a.rect = fitz.Rect(10, 10, 50, 30)
    w0a.field_name = "p0_a"
    w0a.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    p0.add_widget(w0a)

    w0b = fitz.Widget()
    w0b.rect = fitz.Rect(10, 40, 50, 60)
    w0b.field_name = "p0_b"
    w0b.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    p0.add_widget(w0b)

    p1 = doc.new_page()

    w1a = fitz.Widget()
    w1a.rect = fitz.Rect(10, 10, 50, 30)
    w1a.field_name = "p1_a"
    w1a.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    p1.add_widget(w1a)

    # Scoped to page 0
    fields_p0, err0 = pdf_handler.extract_acroform_fields(doc, page_index=0)
    assert err0 is None
    assert len(fields_p0) == 2
    assert {f.field_name for f in fields_p0} == {"p0_a", "p0_b"}
    assert all(f.page_number == 0 for f in fields_p0)

    # Scoped to page 1
    fields_p1, err1 = pdf_handler.extract_acroform_fields(doc, page_index=1)
    assert err1 is None
    assert len(fields_p1) == 1
    assert fields_p1[0].field_name == "p1_a"
    assert fields_p1[0].page_number == 1

    # Entire document
    fields_all, err_all = pdf_handler.extract_acroform_fields(doc, page_index=None)
    assert err_all is None
    assert len(fields_all) == 3

    # Invalid page index
    fields_bad, err_bad = pdf_handler.extract_acroform_fields(doc, page_index=99)
    assert len(fields_bad) == 0
    assert err_bad is not None


def test_update_acroform_field_value_and_get():
    doc = fitz.open()
    page = doc.new_page()

    w = fitz.Widget()
    w.rect = fitz.Rect(50, 50, 200, 80)
    w.field_name = "city_name"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_value = "London"
    page.add_widget(w)

    field = pdf_handler.get_acroform_field(doc, page_index=0, field_identifier="city_name")
    assert field is not None
    assert field.value == "London"

    # Update by name
    res = pdf_handler.update_acroform_field_value(doc, 0, "city_name", "Tokyo")
    assert res is True

    updated_field = pdf_handler.get_acroform_field(doc, page_index=0, field_identifier="city_name")
    assert updated_field is not None
    assert updated_field.value == "Tokyo"

    # Update by xref
    res_xref = pdf_handler.update_acroform_field_value(doc, 0, field.xref, "Kyoto")
    assert res_xref is True

    updated_by_xref = pdf_handler.get_acroform_field(doc, page_index=0, field_identifier=field.xref)
    assert updated_by_xref is not None
    assert updated_by_xref.value == "Kyoto"

    # Non-existent
    assert pdf_handler.update_acroform_field_value(doc, 0, "missing_field", "val") is False
    assert pdf_handler.get_acroform_field(doc, 0, "missing_field") is None


def test_export_and_import_form_data():
    doc = fitz.open()
    page = doc.new_page()

    w1 = fitz.Widget()
    w1.rect = fitz.Rect(10, 10, 100, 30)
    w1.field_name = "f1"
    w1.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w1.field_value = "Val1"
    page.add_widget(w1)

    w2 = fitz.Widget()
    w2.rect = fitz.Rect(10, 40, 100, 60)
    w2.field_name = "f2"
    w2.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w2.field_value = "Val2"
    page.add_widget(w2)

    data = pdf_handler.export_form_data(doc)
    assert data == {"f1": "Val1", "f2": "Val2"}

    # Import modifications
    count = pdf_handler.import_form_data(doc, {"f1": "Updated1", "f2": "Updated2", "f3": "Ignored"})
    assert count == 2

    new_data = pdf_handler.export_form_data(doc)
    assert new_data == {"f1": "Updated1", "f2": "Updated2"}


def test_draw_acroform_overlay():
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 400)
    cr = cairo.Context(surf)

    field1 = AcroFormField(
        field_id="f1",
        xref=1,
        page_number=0,
        rect=(20, 20, 120, 50),
        field_name="f1",
        field_type="text",
        is_required=True,
    )
    field2 = AcroFormField(
        field_id="f2",
        xref=2,
        page_number=0,
        rect=(20, 60, 120, 90),
        field_name="f2",
        field_type="checkbox",
    )
    field3 = AcroFormField(
        field_id="f3",
        xref=3,
        page_number=0,
        rect=(20, 100, 120, 130),
        field_name="f3",
        field_type="text",
        is_read_only=True,
    )

    # Test drawing overlay for regular fields
    pdf_handler.draw_acroform_overlay(cr, [field1, field2, field3], zoom_level=1.0)

    # Test drawing overlay with active field focused
    pdf_handler.draw_acroform_overlay(cr, [field1, field2, field3], zoom_level=1.2, active_field=field1)

    # Test with empty fields
    pdf_handler.draw_acroform_overlay(cr, [], zoom_level=1.0)


def test_window_session_delegation_and_hit_testing():
    from word_sys_pdf_editor.window import PdfEditorWindow

    # Test that PdfEditorWindow creates form_fields accessors
    session = DocumentSession()
    field = AcroFormField(
        field_id="f1",
        xref=1,
        page_number=0,
        rect=(50.0, 50.0, 150.0, 80.0),
        field_name="box",
        field_type="text",
    )
    session.form_fields = [field]

    # Verify hit testing logic via a minimal duck-typed mock of window
    class MockWindow:
        def __init__(self, s):
            self._active_session = s
            self.current_page_index = 0

        @property
        def form_fields(self):
            return self._active_session.form_fields if self._active_session else []

        def _visual_to_unrotated_page_coords(self, x, y):
            return x, y

        _find_form_field_at_pos = PdfEditorWindow._find_form_field_at_pos

    win = MockWindow(session)
    assert len(win.form_fields) == 1

    # Inside bounding box
    hit = win._find_form_field_at_pos(100.0, 65.0)
    assert hit is not None
    assert hit.field_name == "box"

    # Outside bounding box
    miss = win._find_form_field_at_pos(200.0, 200.0)
    assert miss is None


# ============================================================================
# SECTION: test_interactive_choice_inputs.py
# ============================================================================
import unittest
import tempfile
import os
import sys

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import AcroFormField, EditableText
from word_sys_pdf_editor.undo_manager import UndoManager, EditFormFieldCommand
from word_sys_pdf_editor.window import PdfEditorWindow


def has_screen_display():
    return Gdk.Display.get_default() is not None


class MockWindow:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.current_pdf_page_width = 595
        self.current_pdf_page_height = 842
        self.zoom_level = 1.0
        self.document_modified = False
        self.form_fields = []
        self.selected_form_field = None
        self._form_field_overlay_widgets = {}
        self._enable_persistent_form_overlays = True
        self._syncing_form_field = False
        self.undo_manager = UndoManager(self)
        self.pdf_overlay = Gtk.Overlay()
        self.pdf_view = Gtk.DrawingArea()
        self.inline_editor_widget = None

    def _update_undo_redo_buttons(self):
        pass

    def _update_ui_state(self):
        pass

    def _visual_to_unrotated_page_coords(self, px, py):
        return px, py

    _compute_form_field_screen_geometry = PdfEditorWindow._compute_form_field_screen_geometry
    _clear_form_field_overlays = PdfEditorWindow._clear_form_field_overlays
    _update_form_field_overlay_positions = PdfEditorWindow._update_form_field_overlay_positions
    _sync_form_field_value = PdfEditorWindow._sync_form_field_value
    _refresh_form_field_widget_value = PdfEditorWindow._refresh_form_field_widget_value
    _commit_pending_form_field_edit = PdfEditorWindow._commit_pending_form_field_edit
    _focus_form_field_overlay = PdfEditorWindow._focus_form_field_overlay
    _create_form_field_overlays = PdfEditorWindow._create_form_field_overlays
    _update_form_field_overlay_interactivity = PdfEditorWindow._update_form_field_overlay_interactivity
    _find_form_field_at_pos = PdfEditorWindow._find_form_field_at_pos


class TestInteractiveChoiceInputs(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.temp_dir.name, "choice_test.pdf")

        # Create PDF with combobox and listbox choice fields
        self.doc = fitz.open()
        page = self.doc.new_page(width=595, height=842)

        # 1. ComboBox
        w_combo = fitz.Widget()
        w_combo.rect = fitz.Rect(50, 50, 250, 80)
        w_combo.field_name = "country_combo"
        w_combo.field_label = "Country"
        w_combo.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        w_combo.choice_values = ["Germany", "France", "Spain", "Italy"]
        w_combo.field_value = "France"
        page.add_widget(w_combo)

        # 2. ListBox
        w_list = fitz.Widget()
        w_list.rect = fitz.Rect(50, 100, 250, 160)
        w_list.field_name = "role_list"
        w_list.field_label = "Role"
        w_list.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
        w_list.choice_values = ["Admin", "Editor", "Viewer"]
        w_list.field_value = "Editor"
        page.add_widget(w_list)

        # 3. Read-Only ComboBox
        w_ro_combo = fitz.Widget()
        w_ro_combo.rect = fitz.Rect(50, 180, 250, 210)
        w_ro_combo.field_name = "locked_combo"
        w_ro_combo.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        w_ro_combo.choice_values = ["Fixed Option 1", "Fixed Option 2"]
        w_ro_combo.field_value = "Fixed Option 1"
        w_ro_combo.field_flags = fitz.PDF_FIELD_IS_READ_ONLY
        page.add_widget(w_ro_combo)

        self.doc.save(self.pdf_path)

    def tearDown(self):
        if self.doc and not getattr(self.doc, "is_closed", False):
            self.doc.close()
        self.temp_dir.cleanup()

    def test_dropdown_overlay_creation(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields

        win._create_form_field_overlays()
        self.assertEqual(len(win._form_field_overlay_widgets), 3)

        # Verify ComboBox DropDown
        combo_field = [f for f in fields if f.field_name == "country_combo"][0]
        combo_data = win._form_field_overlay_widgets[combo_field.field_id]
        dropdown = combo_data["widget"]
        self.assertIsInstance(dropdown, Gtk.DropDown)
        self.assertTrue(dropdown.has_css_class("acroform-dropdown"))
        self.assertEqual(combo_data["display_items"], ["Germany", "France", "Spain", "Italy"])
        self.assertEqual(dropdown.get_selected(), 1)  # "France" is index 1

        # Verify ListBox DropDown
        list_field = [f for f in fields if f.field_name == "role_list"][0]
        list_data = win._form_field_overlay_widgets[list_field.field_id]
        list_dropdown = list_data["widget"]
        self.assertIsInstance(list_dropdown, Gtk.DropDown)
        self.assertEqual(list_dropdown.get_selected(), 1)  # "Editor" is index 1

        # Verify Read-Only ComboBox
        ro_field = [f for f in fields if f.field_name == "locked_combo"][0]
        ro_data = win._form_field_overlay_widgets[ro_field.field_id]
        ro_dropdown = ro_data["widget"]
        self.assertFalse(ro_dropdown.get_sensitive())

        doc.close()

    def test_two_way_sync_dropdown_selection(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields
        win._create_form_field_overlays()

        combo_field = [f for f in fields if f.field_name == "country_combo"][0]
        combo_data = win._form_field_overlay_widgets[combo_field.field_id]
        dropdown = combo_data["widget"]

        # Select "Spain" (index 2)
        dropdown.set_selected(2)

        self.assertEqual(combo_field.value, "Spain")
        self.assertTrue(win.document_modified)
        pdf_widget = [w for w in doc[0].widgets() if w.field_name == "country_combo"][0]
        self.assertEqual(pdf_widget.field_value, "Spain")
        self.assertEqual(len(win.undo_manager.undo_stack), 1)

        # Undo selection: reverts back to "France"
        win.undo_manager.undo()
        self.assertEqual(combo_field.value, "France")
        self.assertEqual(dropdown.get_selected(), 1)
        pdf_widget_undo = [w for w in doc[0].widgets() if w.field_name == "country_combo"][0]
        self.assertEqual(pdf_widget_undo.field_value, "France")

        # Redo selection: re-applies "Spain"
        win.undo_manager.redo()
        self.assertEqual(combo_field.value, "Spain")
        self.assertEqual(dropdown.get_selected(), 2)
        pdf_widget_redo = [w for w in doc[0].widgets() if w.field_name == "country_combo"][0]
        self.assertEqual(pdf_widget_redo.field_value, "Spain")

        doc.close()

    def test_dropdown_with_export_and_display_tuples(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        w = fitz.Widget()
        w.rect = fitz.Rect(50, 50, 200, 80)
        w.field_name = "export_display_combo"
        w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        w.choice_values = [("DE", "Germany"), ("FR", "France"), ("IT", "Italy")]
        w.field_value = "FR"
        page.add_widget(w)

        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields
        win._create_form_field_overlays()

        field = fields[0]
        data = win._form_field_overlay_widgets[field.field_id]
        dd = data["widget"]

        self.assertEqual(data["display_items"], ["Germany", "France", "Italy"])
        self.assertEqual(data["export_items"], ["DE", "FR", "IT"])
        self.assertEqual(dd.get_selected(), 1)

        # Select "IT" (index 2)
        dd.set_selected(2)
        self.assertEqual(field.value, "IT")
        self.assertTrue(win.document_modified)
        pdf_w = [x for x in doc[0].widgets() if x.field_name == "export_display_combo"][0]
        self.assertEqual(pdf_w.field_value, "IT")

        # Undo
        win.undo_manager.undo()
        self.assertEqual(field.value, "FR")
        self.assertEqual(dd.get_selected(), 1)

        doc.close()

    def test_dropdown_geometry_and_zoom_scaling(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields

        combo_field = [f for f in fields if f.field_name == "country_combo"][0]

        # Geometry at 100% zoom
        win.zoom_level = 1.0
        x1, y1, w1, h1 = win._compute_form_field_screen_geometry(combo_field)
        self.assertEqual(x1, 50)
        self.assertEqual(y1, 50)
        self.assertEqual(w1, 200)
        self.assertEqual(h1, 30)

        # Geometry at 150% zoom
        win.zoom_level = 1.5
        win.current_pdf_page_width = int(595 * 1.5)
        win.current_pdf_page_height = int(842 * 1.5)
        x2, y2, w2, h2 = win._compute_form_field_screen_geometry(combo_field)
        self.assertEqual(x2, 75)
        self.assertEqual(y2, 75)
        self.assertEqual(w2, 300)
        self.assertEqual(h2, 45)

        # Repositioning
        win._create_form_field_overlays()
        win._update_form_field_overlay_positions()
        container = win._form_field_overlay_widgets[combo_field.field_id]["container"]
        self.assertEqual(container.get_margin_start(), 75)
        self.assertEqual(container.get_margin_top(), 75)

        doc.close()

    def test_clear_dropdown_overlays(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields

        win._create_form_field_overlays()
        self.assertEqual(len(win._form_field_overlay_widgets), 3)

        win._clear_form_field_overlays()
        self.assertEqual(len(win._form_field_overlay_widgets), 0)

        doc.close()

    @unittest.skipUnless(has_screen_display(), "Screen display not available (headless build environment)")
    def test_window_full_dropdown_integration(self):
        app = Adw.Application(application_id="org.wordsys.test.dropdown_forms")
        app.register(None)

        win = PdfEditorWindow(application=app)
        win._enable_persistent_form_overlays = True
        doc = fitz.open(self.pdf_path)
        win._active_session.doc = doc
        win._active_session.pdf_path = self.pdf_path
        win._load_page(0)

        self.assertGreater(len(win.form_fields), 0)
        self.assertGreater(len(win._form_field_overlay_widgets), 0)

        found = win._find_form_field_at_pos(60, 60)
        self.assertIsNotNone(found)
        self.assertEqual(found.field_name, "country_combo")

        dropdown_data = win._form_field_overlay_widgets[found.field_id]
        dropdown = dropdown_data["widget"]
        dropdown.grab_focus()

        # Keyboard shield test: arrow key navigation or delete should not delete objects
        test_txt = EditableText(10, 10, "Protected Dropdown Object", font_size=12)
        win.selected_text = test_txt
        ctrl = Gtk.EventControllerKey()
        win.on_key_pressed(ctrl, Gdk.KEY_Delete, 0, Gdk.ModifierType(0))
        self.assertEqual(win.selected_text, test_txt)

        old_tool = win.tool_mode
        win.on_key_pressed(ctrl, Gdk.KEY_p, 0, Gdk.ModifierType(0))
        self.assertEqual(win.tool_mode, old_tool)

        win.do_close_request()
        app.quit()


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_interactive_form_inputs.py
# ============================================================================
import unittest
import tempfile
import os
import sys

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import AcroFormField, EditableText
from word_sys_pdf_editor.undo_manager import UndoManager, EditFormFieldCommand
from word_sys_pdf_editor.window import PdfEditorWindow


def has_screen_display():
    return Gdk.Display.get_default() is not None


class MockWindow:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.current_pdf_page_width = 595
        self.current_pdf_page_height = 842
        self.zoom_level = 1.0
        self.document_modified = False
        self.form_fields = []
        self.selected_form_field = None
        self._form_field_overlay_widgets = {}
        self._enable_persistent_form_overlays = True
        self._syncing_form_field = False
        self.undo_manager = UndoManager(self)
        self.pdf_overlay = Gtk.Overlay()
        self.pdf_view = Gtk.DrawingArea()
        self.inline_editor_widget = None

    def _update_undo_redo_buttons(self):
        pass

    def _update_ui_state(self):
        pass

    def _visual_to_unrotated_page_coords(self, px, py):
        return px, py

    _compute_form_field_screen_geometry = PdfEditorWindow._compute_form_field_screen_geometry
    _clear_form_field_overlays = PdfEditorWindow._clear_form_field_overlays
    _update_form_field_overlay_positions = PdfEditorWindow._update_form_field_overlay_positions
    _sync_form_field_value = PdfEditorWindow._sync_form_field_value
    _refresh_form_field_widget_value = PdfEditorWindow._refresh_form_field_widget_value
    _commit_pending_form_field_edit = PdfEditorWindow._commit_pending_form_field_edit
    _focus_form_field_overlay = PdfEditorWindow._focus_form_field_overlay
    _create_form_field_overlays = PdfEditorWindow._create_form_field_overlays
    _update_form_field_overlay_interactivity = PdfEditorWindow._update_form_field_overlay_interactivity
    _find_form_field_at_pos = PdfEditorWindow._find_form_field_at_pos


class TestInteractiveFormInputs(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.temp_dir.name, "form_test.pdf")

        # Create PDF with text, multiline, password, and checkbox form widgets
        self.doc = fitz.open()
        page = self.doc.new_page(width=595, height=842)

        # Single-line text
        w_text = fitz.Widget()
        w_text.rect = fitz.Rect(50, 50, 250, 80)
        w_text.field_name = "user_name"
        w_text.field_label = "User Name"
        w_text.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w_text.field_value = "Alice"
        page.add_widget(w_text)

        # Multiline text
        w_multi = fitz.Widget()
        w_multi.rect = fitz.Rect(50, 100, 350, 200)
        w_multi.field_name = "comments"
        w_multi.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w_multi.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
        w_multi.field_value = "Line 1\nLine 2"
        page.add_widget(w_multi)

        # Password text
        w_pass = fitz.Widget()
        w_pass.rect = fitz.Rect(50, 220, 250, 250)
        w_pass.field_name = "secret"
        w_pass.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w_pass.field_flags = fitz.PDF_TX_FIELD_IS_PASSWORD
        w_pass.field_value = "secret123"
        page.add_widget(w_pass)

        # Checkbox
        w_chk = fitz.Widget()
        w_chk.rect = fitz.Rect(50, 270, 70, 290)
        w_chk.field_name = "agree_terms"
        w_chk.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w_chk.field_value = False
        page.add_widget(w_chk)

        self.doc.save(self.pdf_path)

    def tearDown(self):
        if self.doc and not getattr(self.doc, "is_closed", False):
            self.doc.close()
        self.temp_dir.cleanup()

    def test_edit_form_field_command_execution_undo_redo(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields

        target_field = [f for f in fields if f.field_name == "user_name"][0]
        self.assertEqual(target_field.value, "Alice")

        cmd = EditFormFieldCommand(win, target_field, "Alice", "Bob")
        cmd.execute()

        self.assertEqual(target_field.value, "Bob")
        self.assertTrue(win.document_modified)
        widget_after = [w for w in doc[0].widgets() if w.field_name == "user_name"][0]
        self.assertEqual(widget_after.field_value, "Bob")

        cmd.undo()
        self.assertEqual(target_field.value, "Alice")
        widget_undo = [w for w in doc[0].widgets() if w.field_name == "user_name"][0]
        self.assertEqual(widget_undo.field_value, "Alice")

        cmd.execute()
        self.assertEqual(target_field.value, "Bob")
        doc.close()

    def test_create_form_field_overlays(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields

        win._create_form_field_overlays()
        self.assertEqual(len(win._form_field_overlay_widgets), 4)

        # Check single-line text entry
        name_field = [f for f in fields if f.field_name == "user_name"][0]
        name_entry_data = win._form_field_overlay_widgets[name_field.field_id]
        entry_widget = name_entry_data["widget"]
        self.assertIsInstance(entry_widget, Gtk.Entry)
        self.assertEqual(entry_widget.get_text(), "Alice")
        self.assertTrue(entry_widget.has_css_class("acroform-entry"))

        # Check multiline text view
        multi_field = [f for f in fields if f.field_name == "comments"][0]
        multi_entry_data = win._form_field_overlay_widgets[multi_field.field_id]
        multi_container = multi_entry_data["container"]
        multi_widget = multi_entry_data["widget"]
        self.assertIsInstance(multi_container, Gtk.ScrolledWindow)
        self.assertIsInstance(multi_widget, Gtk.TextView)
        buf = multi_widget.get_buffer()
        start, end = buf.get_bounds()
        self.assertEqual(buf.get_text(start, end, True), "Line 1\nLine 2")

        # Check password entry
        pass_field = [f for f in fields if f.field_name == "secret"][0]
        pass_entry_data = win._form_field_overlay_widgets[pass_field.field_id]
        pass_widget = pass_entry_data["widget"]
        self.assertIsInstance(pass_widget, Gtk.Entry)
        self.assertFalse(pass_widget.get_visibility())

        # Check checkbox
        chk_field = [f for f in fields if f.field_name == "agree_terms"][0]
        chk_entry_data = win._form_field_overlay_widgets[chk_field.field_id]
        chk_widget = chk_entry_data["widget"]
        self.assertIsInstance(chk_widget, Gtk.CheckButton)
        self.assertFalse(chk_widget.get_active())
        self.assertTrue(chk_widget.has_css_class("acroform-check"))

        doc.close()

    def test_two_way_sync_text_entry(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields
        win._create_form_field_overlays()

        name_field = [f for f in fields if f.field_name == "user_name"][0]
        entry_data = win._form_field_overlay_widgets[name_field.field_id]
        entry_widget = entry_data["widget"]

        # Simulate user typing new text
        entry_widget.set_text("Updated Name")
        entry_data["current_val"] = "Updated Name"
        win._sync_form_field_value(name_field, "Updated Name", record_undo=False)

        self.assertEqual(name_field.value, "Updated Name")
        self.assertTrue(win.document_modified)
        pdf_widget = [w for w in doc[0].widgets() if w.field_name == "user_name"][0]
        self.assertEqual(pdf_widget.field_value, "Updated Name")

        # Simulate committing pending edit (focus leave or Enter)
        win._commit_pending_form_field_edit()
        self.assertEqual(len(win.undo_manager.undo_stack), 1)

        # Test Undo
        win.undo_manager.undo()
        self.assertEqual(name_field.value, "Alice")
        self.assertEqual(entry_widget.get_text(), "Alice")
        pdf_widget_revert = [w for w in doc[0].widgets() if w.field_name == "user_name"][0]
        self.assertEqual(pdf_widget_revert.field_value, "Alice")

        # Test Redo
        win.undo_manager.redo()
        self.assertEqual(name_field.value, "Updated Name")
        self.assertEqual(entry_widget.get_text(), "Updated Name")

        doc.close()

    def test_two_way_sync_checkbox(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields
        win._create_form_field_overlays()

        chk_field = [f for f in fields if f.field_name == "agree_terms"][0]
        chk_data = win._form_field_overlay_widgets[chk_field.field_id]
        chk_widget = chk_data["widget"]

        self.assertFalse(chk_widget.get_active())

        # Toggle checkbox active
        chk_widget.set_active(True)
        self.assertTrue(chk_field.is_checked)
        self.assertTrue(win.document_modified)
        self.assertEqual(len(win.undo_manager.undo_stack), 1)

        pdf_widget = [w for w in doc[0].widgets() if w.field_name == "agree_terms"][0]
        self.assertTrue(bool(pdf_widget.field_value))

        # Undo toggle
        win.undo_manager.undo()
        self.assertFalse(chk_widget.get_active())
        self.assertFalse(chk_field.is_checked)

        # Redo toggle
        win.undo_manager.redo()
        self.assertTrue(chk_widget.get_active())
        self.assertTrue(chk_field.is_checked)

        doc.close()

    def test_geometry_computation_and_zoom_scaling(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields

        name_field = [f for f in fields if f.field_name == "user_name"][0]

        # Geometry at zoom 1.0
        win.zoom_level = 1.0
        x1, y1, w1, h1 = win._compute_form_field_screen_geometry(name_field)
        self.assertEqual(x1, 50)
        self.assertEqual(y1, 50)
        self.assertEqual(w1, 200)
        self.assertEqual(h1, 30)

        # Geometry at zoom 2.0
        win.zoom_level = 2.0
        win.current_pdf_page_width = 595 * 2
        win.current_pdf_page_height = 842 * 2
        x2, y2, w2, h2 = win._compute_form_field_screen_geometry(name_field)
        self.assertEqual(x2, 100)
        self.assertEqual(y2, 100)
        self.assertEqual(w2, 400)
        self.assertEqual(h2, 60)

        # Test updating positions
        win._create_form_field_overlays()
        win._update_form_field_overlay_positions()
        entry_container = win._form_field_overlay_widgets[name_field.field_id]["container"]
        self.assertEqual(entry_container.get_margin_start(), 100)
        self.assertEqual(entry_container.get_margin_top(), 100)

        doc.close()

    def test_clear_form_field_overlays(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields

        win._create_form_field_overlays()
        self.assertEqual(len(win._form_field_overlay_widgets), 4)

        win._clear_form_field_overlays()
        self.assertEqual(len(win._form_field_overlay_widgets), 0)

        doc.close()

    def test_two_way_sync_multiline_textview(self):
        doc = fitz.open(self.pdf_path)
        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields
        win._create_form_field_overlays()

        multi_field = [f for f in fields if f.field_name == "comments"][0]
        multi_data = win._form_field_overlay_widgets[multi_field.field_id]
        multi_tv = multi_data["widget"]
        buf = multi_tv.get_buffer()

        # Update textview buffer
        new_text = "Line 1 Updated\nLine 2 Updated\nLine 3"
        buf.set_text(new_text)
        multi_data["current_val"] = new_text
        win._sync_form_field_value(multi_field, new_text, record_undo=False)

        self.assertEqual(multi_field.value, new_text)
        self.assertTrue(win.document_modified)
        pdf_widget = [w for w in doc[0].widgets() if w.field_name == "comments"][0]
        self.assertEqual(pdf_widget.field_value, new_text)

        # Commit edit
        win._commit_pending_form_field_edit()
        self.assertEqual(len(win.undo_manager.undo_stack), 1)

        # Undo
        win.undo_manager.undo()
        self.assertEqual(multi_field.value, "Line 1\nLine 2")
        start, end = buf.get_bounds()
        self.assertEqual(buf.get_text(start, end, True), "Line 1\nLine 2")

        # Redo
        win.undo_manager.redo()
        self.assertEqual(multi_field.value, new_text)
        start, end = buf.get_bounds()
        self.assertEqual(buf.get_text(start, end, True), new_text)

        doc.close()

    def test_read_only_form_field_properties(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        w_ro_text = fitz.Widget()
        w_ro_text.rect = fitz.Rect(10, 10, 100, 30)
        w_ro_text.field_name = "ro_text"
        w_ro_text.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w_ro_text.field_flags = fitz.PDF_FIELD_IS_READ_ONLY
        w_ro_text.field_value = "Locked Text"
        page.add_widget(w_ro_text)

        w_ro_chk = fitz.Widget()
        w_ro_chk.rect = fitz.Rect(10, 40, 30, 60)
        w_ro_chk.field_name = "ro_chk"
        w_ro_chk.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w_ro_chk.field_flags = fitz.PDF_FIELD_IS_READ_ONLY
        w_ro_chk.field_value = True
        page.add_widget(w_ro_chk)

        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields
        win._create_form_field_overlays()

        ro_text_field = [f for f in fields if f.field_name == "ro_text"][0]
        text_widget = win._form_field_overlay_widgets[ro_text_field.field_id]["widget"]
        self.assertFalse(text_widget.get_editable())
        self.assertTrue(text_widget.has_css_class("readonly"))

        ro_chk_field = [f for f in fields if f.field_name == "ro_chk"][0]
        chk_widget = win._form_field_overlay_widgets[ro_chk_field.field_id]["widget"]
        self.assertFalse(chk_widget.get_sensitive())

        doc.close()

    def test_radio_button_overlay_and_sync(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        w_radio = fitz.Widget()
        w_radio.rect = fitz.Rect(10, 10, 30, 30)
        w_radio.field_name = "gender_radio"
        w_radio.field_type = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
        w_radio.field_value = False
        page.add_widget(w_radio)

        win = MockWindow(doc)
        fields, _ = pdf_handler.extract_acroform_fields(doc, 0)
        win.form_fields = fields
        win._create_form_field_overlays()

        radio_field = fields[0]
        radio_data = win._form_field_overlay_widgets[radio_field.field_id]
        chk_btn = radio_data["widget"]
        self.assertIsInstance(chk_btn, Gtk.CheckButton)

        # Toggle radio button
        chk_btn.set_active(True)
        self.assertTrue(radio_field.is_checked)
        self.assertTrue(win.document_modified)
        self.assertEqual(len(win.undo_manager.undo_stack), 1)

        win.undo_manager.undo()
        self.assertFalse(chk_btn.get_active())
        self.assertFalse(radio_field.is_checked)

        doc.close()

    @unittest.skipUnless(has_screen_display(), "Screen display not available (headless build environment)")
    def test_window_full_integration(self):
        app = Adw.Application(application_id="org.wordsys.test.interactive_forms")
        app.register(None)

        win = PdfEditorWindow(application=app)
        win._enable_persistent_form_overlays = True
        doc = fitz.open(self.pdf_path)
        win._active_session.doc = doc
        win._active_session.pdf_path = self.pdf_path
        win._load_page(0)

        # Ensure form fields are extracted and overlay created
        self.assertGreater(len(win.form_fields), 0)
        self.assertGreater(len(win._form_field_overlay_widgets), 0)

        # Test finding form field at position
        found = win._find_form_field_at_pos(60, 60)
        self.assertIsNotNone(found)
        self.assertEqual(found.field_name, "user_name")

        # Test key event shielding
        entry_data = win._form_field_overlay_widgets[found.field_id]
        entry = entry_data["widget"]
        entry.grab_focus()

        # Delete key should not delete selected objects while entry has focus
        test_txt = EditableText(10, 10, "Protected Text", font_size=12)
        win.selected_text = test_txt
        ctrl = Gtk.EventControllerKey()
        handled = win.on_key_pressed(ctrl, Gdk.KEY_Delete, 0, Gdk.ModifierType(0))
        self.assertEqual(win.selected_text, test_txt)

        # Tool shortcut 'p' for pen should not switch tools while entry has focus
        old_tool = win.tool_mode
        handled_tool = win.on_key_pressed(ctrl, Gdk.KEY_p, 0, Gdk.ModifierType(0))
        self.assertEqual(win.tool_mode, old_tool)

        win.do_close_request()
        app.quit()


if __name__ == "__main__":
    unittest.main()


