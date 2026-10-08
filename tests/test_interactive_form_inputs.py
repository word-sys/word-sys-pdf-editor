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

