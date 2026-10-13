import os
import tempfile
import unittest
import gi

try:
    import pymupdf as fitz
except ImportError:
    import fitz

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.flatten_dialog import FlattenDialog
from word_sys_pdf_editor.models import EditableShape, EditableStroke, StickyNoteObject
from word_sys_pdf_editor.undo_manager import FlattenCommand, UndoManager


class DummyWindow:
    """Minimal test fixture mimicking PdfEditorWindow for unit testing."""
    def __init__(self, doc=None):
        self.doc = doc
        self.current_page_index = 0
        self.document_modified = False
        self.editable_strokes = []
        self.editable_shapes = []
        self.measurement_objects = []
        self.editable_texts = []
        self.editable_images = []
        self.form_fields = []
        self.sticky_notes = []
        self.selected_object = None

        self.status_label = Gtk.Label()
        self.pdf_view = Gtk.DrawingArea()
        self.undo_manager = UndoManager(self)

    def _update_undo_redo_buttons(self):
        pass

    def _refresh_thumbnail(self, page_index):
        pass

    def refresh_annotations_list(self):
        pass

    def get_selected_object(self):
        return self.selected_object

    def clear_selection(self):
        self.selected_object = None


class TestPdfHandlerFlatten(unittest.TestCase):
    """Test backend flattening functions in pdf_handler.py."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            try:
                os.remove(self.temp_file.name)
            except OSError:
                pass

    def test_flatten_page_annotations_single_page(self):
        """Single-page flattening bakes highlight annotations into permanent content."""
        doc = fitz.open()
        p0 = doc.new_page()
        p0.draw_rect(fitz.Rect(10, 10, 100, 100), color=(1, 0, 0))
        p0.add_highlight_annot(fitz.Rect(20, 20, 80, 80))
        doc.save(self.temp_file.name)
        doc.close()

        doc = fitz.open(self.temp_file.name)
        self.assertEqual(len(list(doc[0].annots())), 1)

        ok, err = pdf_handler.flatten_page_annotations(doc, 0, include_forms=False)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Annotations on page 0 are baked and removed from /Annots
        self.assertEqual(len(list(doc[0].annots())), 0)
        doc.close()

    def test_flatten_page_annotations_preserves_sticky_notes(self):
        """Flattening preserves sticky notes (Text annotations) as interactive comments."""
        doc = fitz.open()
        p0 = doc.new_page()
        p0.add_highlight_annot(fitz.Rect(10, 10, 50, 50))
        p0.add_text_annot(fitz.Point(30, 40), "Important review note")
        doc.save(self.temp_file.name)
        doc.close()

        doc = fitz.open(self.temp_file.name)
        annots_before = list(doc[0].annots())
        self.assertEqual(len(annots_before), 2)

        ok, err = pdf_handler.flatten_page_annotations(doc, 0, include_forms=False)
        self.assertTrue(ok)
        self.assertIsNone(err)

        page_after = doc.load_page(0)
        annots_after = list(page_after.annots())
        # Only the sticky note should remain
        self.assertEqual(len(annots_after), 1)
        self.assertEqual(annots_after[0].type[0], 0)  # PDF_ANNOT_TEXT
        self.assertEqual(annots_after[0].info.get("content"), "Important review note")
        doc.close()

    def test_true_oled_burnin_no_selectable_text_or_shapes(self):
        """Verify true OLED-style burn-in: text and shapes become permanent unselectable pixels."""
        doc = fitz.open()
        p0 = doc.new_page()
        p0.insert_text((50, 100), "Confidential Unburned Text", fontsize=14)
        p0.draw_rect(fitz.Rect(50, 120, 200, 220), color=(1, 0, 0), fill=(0, 0, 1))
        p0.add_highlight_annot(fitz.Rect(50, 90, 250, 115))
        doc.save(self.temp_file.name)
        doc.close()

        doc = fitz.open(self.temp_file.name)
        self.assertEqual(len(doc[0].get_text("blocks")), 1)
        self.assertEqual(len(list(doc[0].annots())), 1)

        ok, err = pdf_handler.flatten_page_annotations(doc, 0, include_forms=False)
        self.assertTrue(ok)
        self.assertIsNone(err)

        burned_page = doc.load_page(0)
        # 1. Text is 100% burned in: 0 text blocks, cannot be selected or copied
        self.assertEqual(len(burned_page.get_text("blocks")), 0)
        # 2. Annotations are 100% burned in: 0 annots remaining
        self.assertEqual(len(list(burned_page.annots())), 0)
        # 3. Vector shapes are 100% burned into pixels: extract_editable_shapes returns 0
        extracted_shapes, _ = pdf_handler.extract_editable_shapes(doc, 0)
        self.assertEqual(len(extracted_shapes), 0)
        # 4. Background image is static: extract_editable_images returns 0
        extracted_images, _ = pdf_handler.extract_editable_images(doc, 0)
        self.assertEqual(len(extracted_images), 0)
        doc.close()

    def test_flatten_document_annotations_scope_page(self):
        """Flattening with scope=[0] leaves page 1 annotations unflattened."""
        doc = fitz.open()
        p0 = doc.new_page()
        p0.add_highlight_annot(fitz.Rect(10, 10, 50, 50))
        p1 = doc.new_page()
        p1.add_highlight_annot(fitz.Rect(20, 20, 60, 60))
        doc.save(self.temp_file.name)
        doc.close()

        doc = fitz.open(self.temp_file.name)
        self.assertEqual(len(list(doc[0].annots())), 1)
        self.assertEqual(len(list(doc[1].annots())), 1)

        ok, err = pdf_handler.flatten_document_annotations(doc, page_indices=[0], include_forms=False)
        self.assertTrue(ok)
        self.assertIsNone(err)

        self.assertEqual(len(list(doc[0].annots())), 0)
        self.assertEqual(len(list(doc[1].annots())), 1)
        doc.close()

    def test_flatten_document_annotations_scope_all(self):
        """Flattening with scope=None flattens all pages across the document."""
        doc = fitz.open()
        p0 = doc.new_page()
        p0.add_highlight_annot(fitz.Rect(10, 10, 50, 50))
        p1 = doc.new_page()
        p1.add_highlight_annot(fitz.Rect(20, 20, 60, 60))
        doc.save(self.temp_file.name)
        doc.close()

        doc = fitz.open(self.temp_file.name)
        ok, err = pdf_handler.flatten_document_annotations(doc, page_indices=None, include_forms=False)
        self.assertTrue(ok)
        self.assertIsNone(err)

        self.assertEqual(len(list(doc[0].annots())), 0)
        self.assertEqual(len(list(doc[1].annots())), 0)
        doc.close()

    def test_flatten_form_fields_option(self):
        """When include_forms=False widgets remain, when True widgets are baked into content."""
        doc = fitz.open()
        p0 = doc.new_page()
        p0.draw_rect(fitz.Rect(10, 10, 100, 100), color=(1, 0, 0))
        widget = fitz.Widget()
        widget.rect = fitz.Rect(20, 20, 80, 50)
        widget.field_name = "test_text"
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value = "Sample Value"
        p0.add_widget(widget)
        doc.save(self.temp_file.name)
        doc.close()

        # Test include_forms=False leaves widget
        doc = fitz.open(self.temp_file.name)
        self.assertEqual(len(list(doc[0].widgets())), 1)
        ok, err = pdf_handler.flatten_page_annotations(doc, 0, include_forms=False)
        self.assertTrue(ok)
        self.assertEqual(len(list(doc[0].widgets())), 1)

        # Test include_forms=True bakes widget
        ok, err = pdf_handler.flatten_page_annotations(doc, 0, include_forms=True)
        self.assertTrue(ok)
        self.assertEqual(len(list(doc[0].widgets())), 0)
        doc.close()


class TestFlattenCommandUndoRedo(unittest.TestCase):
    """Test undoable FlattenCommand execute and undo cycles."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self.temp_file.close()

        doc = fitz.open()
        p0 = doc.new_page()
        p0.add_highlight_annot(fitz.Rect(15, 15, 65, 45))
        doc.save(self.temp_file.name)
        doc.close()

        self.doc = fitz.open(self.temp_file.name)
        self.window = DummyWindow(self.doc)

    def tearDown(self):
        self.doc.close()
        if os.path.exists(self.temp_file.name):
            try:
                os.remove(self.temp_file.name)
            except OSError:
                pass

    def test_flatten_command_in_memory_and_pdf_roundtrip(self):
        """FlattenCommand burns in-memory canvas objects and undo restores them."""
        # Add in-memory vector shape and stroke
        shape = EditableShape(
            shape_type=EditableShape.SHAPE_RECTANGLE,
            bbox=(30, 30, 90, 70),
            page_number=0,
            is_new=True,
        )
        stroke = EditableStroke(
            points=[(10, 10), (20, 20), (30, 10)],
            stroke_color=(0.2, 0.4, 0.8),
            stroke_width=3.0,
            page_number=0,
            is_new=True,
        )
        self.window.editable_shapes.append(shape)
        self.window.editable_strokes.append(stroke)
        self.window.selected_object = shape

        self.assertEqual(len(self.window.editable_shapes), 1)
        self.assertEqual(len(self.window.editable_strokes), 1)
        self.assertEqual(len(list(self.doc[0].annots())), 1)

        cmd = FlattenCommand(self.window, page_indices=[0], include_forms=False)
        cmd.execute()
        self.window.undo_manager.record(cmd)

        # After execution: in-memory objects on page 0 cleared, PDF annots cleared
        self.assertEqual(len(self.window.editable_shapes), 0)
        self.assertEqual(len(self.window.editable_strokes), 0)
        self.assertEqual(len(list(self.doc[0].annots())), 0)
        self.assertIsNone(self.window.selected_object)
        self.assertTrue(self.window.document_modified)
        self.assertTrue(self.window.undo_manager.can_undo())

        # Undo execution: restores in-memory objects and PDF highlight annot
        self.window.undo_manager.undo()
        self.assertEqual(len(self.window.editable_shapes), 1)
        self.assertEqual(len(self.window.editable_strokes), 1)
        self.assertEqual(len(list(self.doc[0].annots())), 1)

        # Redo execution: re-applies flattening cleanly
        self.window.undo_manager.redo()
        self.assertEqual(len(self.window.editable_shapes), 0)
        self.assertEqual(len(self.window.editable_strokes), 0)
        self.assertEqual(len(list(self.doc[0].annots())), 0)


class TestFlattenDialogUI(unittest.TestCase):
    """Test modern Libadwaita FlattenDialog options and callbacks."""

    def test_dialog_defaults_and_confirm_page_scope(self):
        """Dialog defaults to current page scope and calls callback with expected parameters."""
        parent = DummyWindow()
        callback_results = []

        def _on_confirm(scope, include_forms):
            callback_results.append((scope, include_forms))

        dialog = FlattenDialog(
            parent_window=None,
            current_page=0,
            total_pages=3,
            on_confirm_callback=_on_confirm,
        )

        self.assertTrue(dialog.scope_page_check.get_active())
        self.assertFalse(dialog.scope_all_check.get_active())
        self.assertFalse(dialog.forms_switch.get_active())

        dialog.confirm_btn.emit("clicked")
        self.assertEqual(len(callback_results), 1)
        self.assertEqual(callback_results[0], ("page", False))

    def test_dialog_all_scope_and_forms_enabled(self):
        """Toggling scope to 'all' and forms to True sends updated options."""
        callback_results = []

        def _on_confirm(scope, include_forms):
            callback_results.append((scope, include_forms))

        dialog = FlattenDialog(
            parent_window=None,
            current_page=1,
            total_pages=5,
            on_confirm_callback=_on_confirm,
        )

        dialog.scope_all_check.set_active(True)
        dialog.forms_switch.set_active(True)

        dialog.confirm_btn.emit("clicked")
        self.assertEqual(len(callback_results), 1)
        self.assertEqual(callback_results[0], ("all", True))


class TestWindowFlattenIntegration(unittest.TestCase):
    """Test PdfEditorWindow flatten integration methods."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self.temp_file.close()

        doc = fitz.open()
        p0 = doc.new_page()
        p0.add_highlight_annot(fitz.Rect(10, 10, 50, 50))
        doc.save(self.temp_file.name)
        doc.close()

        self.doc = fitz.open(self.temp_file.name)
        self.window = DummyWindow(self.doc)

    def tearDown(self):
        self.doc.close()
        if os.path.exists(self.temp_file.name):
            try:
                os.remove(self.temp_file.name)
            except OSError:
                pass

    def test_window_flatten_annotations_and_undo(self):
        """Testing window flatten_annotations triggers FlattenCommand and records in UndoManager."""
        from word_sys_pdf_editor.window import PdfEditorWindow
        self.window.flatten_annotations = PdfEditorWindow.flatten_annotations.__get__(self.window, DummyWindow)

        self.assertEqual(len(list(self.doc[0].annots())), 1)
        self.window.flatten_annotations(page_indices=[0], include_forms=False)

        # After flatten
        self.assertEqual(len(list(self.doc[0].annots())), 0)
        self.assertTrue(self.window.undo_manager.can_undo())

        # After undo
        self.window.undo_manager.undo()
        page0 = self.doc.load_page(0)
        self.assertEqual(len(list(page0.annots())), 1)


if __name__ == '__main__':
    unittest.main()
