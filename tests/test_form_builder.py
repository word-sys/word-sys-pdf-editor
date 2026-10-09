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
    on_drag_begin = PdfEditorWindow.on_drag_begin
    on_drag_update = PdfEditorWindow.on_drag_update
    on_drag_end = PdfEditorWindow.on_drag_end
    on_pdf_view_pressed = PdfEditorWindow.on_pdf_view_pressed
    _focus_form_field_overlay = PdfEditorWindow._focus_form_field_overlay
    _create_form_field_overlays = PdfEditorWindow._create_form_field_overlays
    _clear_form_field_overlays = PdfEditorWindow._clear_form_field_overlays
    _compute_form_field_screen_geometry = PdfEditorWindow._compute_form_field_screen_geometry


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

