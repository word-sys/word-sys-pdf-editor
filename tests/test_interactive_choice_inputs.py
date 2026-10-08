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
