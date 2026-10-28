"""Consolidated Cairo Rendering, Content Streams, Flattening, and Font Cache Test Suite for word-sys-pdf-editor.

This suite validates Cairo drawing surfaces, content stream token replacement, selective PDF flattening,
appearance stream baking, and global font caching.
"""

# ============================================================================
# SECTION: test_flatten.py
# ============================================================================
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


# ============================================================================
# SECTION: test_content_stream_replacement.py
# ============================================================================
import unittest
import os
import tempfile
import fitz
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw

from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.models import EditableText, decompose_font_name, BASE14_FALLBACK_MAP
from word_sys_pdf_editor import pdf_handler, undo_manager


def has_screen_display():
    """Check if graphical display is available."""
    display = Gdk.Display.get_default()
    return display is not None


class TestContentStreamReplacement(unittest.TestCase):
    """Test suite for Part 28 Content Stream Text Replacement and editor enhancements."""

    @classmethod
    def setUpClass(cls):
        if has_screen_display():
            try:
                cls.app = Adw.Application(application_id="org.wordsys.test.contentreplace")
                cls.app.register(None)
            except Exception:
                cls.app = None
        else:
            cls.app = None

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        # Create a sample PDF document
        self.sample_pdf_path = os.path.join(self.temp_dir.name, "sample_replacement.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=400)
        page.insert_text(fitz.Point(50, 100), "TAVSIYE MEKTUBU", fontsize=16)
        page.insert_text(fitz.Point(50, 160), "Ilgili Makama,", fontsize=12)
        doc.save(self.sample_pdf_path)
        doc.close()

        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.continuous_scroll = False

        loaded, err = pdf_handler.load_pdf_document(self.sample_pdf_path)
        self.assertIsNone(err)
        self.win._finish_loading(loaded, None, self.sample_pdf_path, 0, self.win._active_session)

    def tearDown(self):
        try:
            if hasattr(self.win, '_hide_inline_editor'):
                self.win._hide_inline_editor()
            if self.win.doc:
                self.win.doc.close()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def test_aptos_font_fallback_and_clean_lookup(self):
        """Verify Aptos font maps to standard Base14 sans-serif and does not cause errors."""
        self.assertIn('aptos', BASE14_FALLBACK_MAP)
        self.assertEqual(BASE14_FALLBACK_MAP['aptos'], 'helv')

        font_info = decompose_font_name("Aptos")
        self.assertEqual(font_info["matched_family"], "Liberation Sans")
        self.assertEqual(font_info["base14_code"], "helv")

        # Test embedded font lookup in window
        text_obj = EditableText(x=50, y=50, text="Aptos Test", font_family="Aptos")
        self.win._update_text_format_controls(text_obj)
        active_idx = self.win.font_combo.get_active()
        self.assertGreaterEqual(active_idx, 0)

    def test_apply_text_edit_redacts_and_replaces_in_content_stream(self):
        """Verify apply_text_edit removes original text from content stream and inserts new text."""
        doc = fitz.open(self.sample_pdf_path)
        page = doc[0]
        initial_text = page.get_text()
        self.assertIn("TAVSIYE MEKTUBU", initial_text)

        words = page.get_text("words")
        # Hit "TAVSIYE" word
        hit = pdf_handler.hit_test_text_word_at_pos(doc, (60, 95), page_index=0)
        self.assertIsNotNone(hit)

        span_hit = hit.get("span", {})
        span_box = span_hit.get("bbox", hit["bbox"])
        text_obj = EditableText(
            x=span_box[0],
            y=span_box[1],
            text=span_hit.get("text", hit["word"]),
            font_size=span_hit.get("size", 16),
            span_data=span_hit,
            page_number=0
        )
        text_obj.bbox = tuple(span_box)
        text_obj.original_bbox = tuple(span_box)

        # Apply edit: replace heading with "REFERANS BELGESI"
        success, err = pdf_handler.apply_text_edit(doc, text_obj, "REFERANS BELGESI")
        self.assertTrue(success)
        self.assertIsNone(err)

        updated_text = page.get_text()
        # Original text should be gone completely
        self.assertNotIn("TAVSIYE MEKTUBU", updated_text)
        # New text should be present
        self.assertIn("REFERANS BELGESI", updated_text)
        # Second line should remain untouched
        self.assertIn("Ilgili Makama,", updated_text)
        doc.close()

    def test_apply_text_edit_empty_text_erases_span(self):
        """Verify applying empty text redacts and completely erases the target text span."""
        doc = fitz.open(self.sample_pdf_path)
        page = doc[0]
        words = page.get_text("words")

        hit = pdf_handler.hit_test_text_word_at_pos(doc, (60, 155), page_index=0)
        self.assertIsNotNone(hit)

        span_hit = hit.get("span", {})
        span_box = span_hit.get("bbox", hit["bbox"])
        text_obj = EditableText(
            x=span_box[0],
            y=span_box[1],
            text=span_hit.get("text", hit["word"]),
            font_size=span_hit.get("size", 12),
            span_data=span_hit,
            page_number=0
        )
        text_obj.bbox = tuple(span_box)
        text_obj.original_bbox = tuple(span_box)

        # Apply empty edit (deletion)
        success, err = pdf_handler.apply_text_edit(doc, text_obj, "")
        self.assertTrue(success)

        updated_text = page.get_text()
        self.assertNotIn("Ilgili Makama,", updated_text)
        doc.close()

    def test_rebuild_page_preserves_text_redactions(self):
        """Verify rebuilding page from snapshot keeps redactions for modified text objects."""
        doc = fitz.open(self.sample_pdf_path)
        pdf_handler.save_page_snapshot(doc, 0)

        hit = pdf_handler.hit_test_text_word_at_pos(doc, (60, 95), page_index=0)
        span_hit = hit.get("span", {})
        span_box = span_hit.get("bbox", hit["bbox"])

        text_obj = EditableText(
            x=span_box[0],
            y=span_box[1],
            text="YENI BASLIK",
            font_size=span_hit.get("size", 16),
            span_data=span_hit,
            page_number=0
        )
        text_obj.bbox = tuple(span_box)
        text_obj.original_bbox = tuple(span_box)
        # Apply text edit which redacts original and inserts new
        success, err = pdf_handler.apply_text_edit(doc, text_obj, "YENI BASLIK")
        self.assertTrue(success)
        pdf_handler.save_page_snapshot(doc, 0, force=True)

        # Rebuild page with the modified text object
        success, err = pdf_handler.rebuild_page(
            doc, 0, all_texts=[text_obj], all_shapes=[], all_images=[]
        )
        self.assertTrue(success)

        text_after_rebuild = doc[0].get_text()
        self.assertNotIn("TAVSIYE MEKTUBU", text_after_rebuild)
        self.assertIn("YENI BASLIK", text_after_rebuild)
        doc.close()

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_inline_editor_opaque_white_styling(self):
        """Verify inline editor frame and textview have opaque white backgrounds."""
        self.win.view_mode = False
        target = self.win.editable_texts[0]
        self.win._show_inline_editor(target)

        self.assertIsNotNone(self.win.inline_editor_widget)
        self.assertIsNotNone(self.win.inline_editor_tv)
        self.assertIsNotNone(self.win._inline_editor_css_provider)

        css_str = self.win._inline_editor_css_provider.to_string()
        # Ensure white background is present for frame and textview
        self.assertTrue("rgb(255,255,255)" in css_str or "rgb(255, 255, 255)" in css_str or "#ffffff" in css_str)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_single_click_selects_underlying_text_and_return_key_opens_editor(self):
        """Verify single click on underlying PDF text selects it, and Return key opens editor."""
        self.win.font_scan_in_progress = False
        self.win.view_mode = False
        self.win.tool_mode = "select"
        self.win.selected_text = None
        self.win.editable_texts.clear()

        page_offset_x = max(0, (self.win.pdf_view.get_allocated_width() - self.win.current_pdf_page_width) / 2)
        page_offset_y = max(0, (self.win.pdf_view.get_allocated_height() - self.win.current_pdf_page_height) / 2)

        # Single click on "TAVSİYE MEKTUBU" at (60, 95)
        click_x = page_offset_x + 60 * self.win.zoom_level
        click_y = page_offset_y + 95 * self.win.zoom_level

        self.win.on_pdf_view_pressed(None, 1, click_x, click_y)

        # Selected text must be set on single click, but editor not opened yet
        self.assertIsNotNone(self.win.selected_text)
        self.assertIn("TAVSIYE", self.win.selected_text.text)
        self.assertIsNone(self.win.inline_editor_widget)

        # Now press Return key
        handled = self.win.on_key_pressed(None, Gdk.KEY_Return, 0, 0)
        self.assertTrue(handled)
        # Inline editor must now be active
        self.assertIsNotNone(self.win.inline_editor_widget)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_undo_redo_content_stream_replacement(self):
        """Verify committing an inline edit updates PDF and undo/redo cleanly reverts and reapplies."""
        self.win.font_scan_in_progress = False
        self.win.view_mode = False
        self.win.tool_mode = "select"

        page_offset_x = max(0, (self.win.pdf_view.get_allocated_width() - self.win.current_pdf_page_width) / 2)
        page_offset_y = max(0, (self.win.pdf_view.get_allocated_height() - self.win.current_pdf_page_height) / 2)

        # Double click to open editor on "TAVSIYE MEKTUBU"
        click_x = page_offset_x + 60 * self.win.zoom_level
        click_y = page_offset_y + 95 * self.win.zoom_level
        self.win.on_pdf_view_pressed(None, 2, click_x, click_y)

        self.assertIsNotNone(self.win.inline_editor_widget)
        buf = self.win.inline_editor_tv.get_buffer()
        buf.set_text("GUNCELLENMIS BASLIK")

        # Commit edit via Enter
        self.win._on_inline_editor_key(None, Gdk.KEY_Return, 0, 0)
        self.assertIsNone(self.win.inline_editor_widget)

        # Content stream in document must contain updated text
        text_now = self.win.doc[0].get_text()
        self.assertIn("GUNCELLENMIS BASLIK", text_now)
        self.assertNotIn("TAVSIYE MEKTUBU", text_now)

        # Test Undo
        self.assertTrue(self.win.undo_manager.can_undo())
        self.win.undo_manager.undo()
        text_after_undo = self.win.doc[0].get_text()
        self.assertIn("TAVSIYE MEKTUBU", text_after_undo)
        self.assertNotIn("GUNCELLENMIS BASLIK", text_after_undo)

        # Test Redo
        self.assertTrue(self.win.undo_manager.can_redo())
        self.win.undo_manager.redo()
        text_after_redo = self.win.doc[0].get_text()
        self.assertIn("GUNCELLENMIS BASLIK", text_after_redo)
        self.assertNotIn("TAVSIYE MEKTUBU", text_after_redo)


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_cairo_pipeline.py
# ============================================================================
import time
import pytest
import cairo
import fitz
import numpy as np
from unittest.mock import MagicMock, patch

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableText, EditableImage, EditableShape, EditableStroke
from word_sys_pdf_editor.window import PdfEditorWindow


def test_pixmap_to_cairo_surface_rgb():
    """Verify RGB pixmap converts directly to Cairo RGB24 ImageSurface with correct dimensions and channels."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    # Draw pure red rect
    page.draw_rect([10, 10, 50, 50], color=None, fill=(1, 0, 0))
    pix = page.get_pixmap(alpha=False)

    surf, data_ref = pdf_handler.pixmap_to_cairo_surface(pix)
    assert surf is not None
    assert isinstance(surf, cairo.ImageSurface)
    assert surf.get_format() == cairo.FORMAT_RGB24
    assert surf.get_width() == 200
    assert surf.get_height() == 300
    assert surf.get_stride() == 200 * 4

    # Verify pixel channel swizzle at (20, 20): should be Red (BGRX: B=0, G=0, R=255, X=255)
    data = surf.get_data()
    idx = (20 * 200 + 20) * 4
    b, g, r, x = data[idx:idx + 4]
    assert r == 255
    assert g == 0
    assert b == 0
    assert x == 255


def test_pixmap_to_cairo_surface_rgba():
    """Verify RGBA pixmap converts directly to Cairo ARGB32 ImageSurface preserving alpha."""
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect([10, 10, 60, 60], color=None, fill=(0, 1, 0), fill_opacity=0.5)
    pix = page.get_pixmap(alpha=True)

    surf, data_ref = pdf_handler.pixmap_to_cairo_surface(pix)
    assert surf is not None
    assert isinstance(surf, cairo.ImageSurface)
    assert surf.get_format() == cairo.FORMAT_ARGB32
    assert surf.get_width() == 100
    assert surf.get_height() == 100
    assert surf.get_stride() == 100 * 4

    # Pixel at (30, 30): semi-transparent green
    data = surf.get_data()
    idx = (30 * 100 + 30) * 4
    b, g, r, a = data[idx:idx + 4]
    assert a > 0
    assert g > 0
    assert b == 0
    assert r == 0


def test_pixmap_to_cairo_surface_gray():
    """Verify grayscale pixmap converts to Cairo RGB24 ImageSurface repeating gray in RGB channels."""
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect([0, 0, 100, 100], color=None, fill=(0.5, 0.5, 0.5))
    pix_rgb = page.get_pixmap(alpha=False)
    pix_gray = fitz.Pixmap(fitz.csGRAY, pix_rgb)

    assert pix_gray.n == 1
    surf, data_ref = pdf_handler.pixmap_to_cairo_surface(pix_gray)
    assert surf is not None
    assert surf.get_format() == cairo.FORMAT_RGB24
    assert surf.get_width() == 100
    assert surf.get_height() == 100

    data = surf.get_data()
    idx = (50 * 100 + 50) * 4
    b, g, r, x = data[idx:idx + 4]
    assert b == g == r
    assert 120 <= r <= 135


def test_pixmap_to_cairo_surface_invalid():
    """Verify pixmap_to_cairo_surface handles None and invalid inputs gracefully."""
    surf, ref = pdf_handler.pixmap_to_cairo_surface(None)
    assert surf is None and ref is None

    fake_pix = MagicMock()
    fake_pix.width = 0
    fake_pix.height = 0
    surf, ref = pdf_handler.pixmap_to_cairo_surface(fake_pix)
    assert surf is None and ref is None


def test_get_page_cairo_surface_caching_and_lru():
    """Verify caching, document locking, and LRU cache eviction capped at 6 surfaces."""
    pdf_handler.invalidate_page_cache()
    doc = fitz.open()
    for _ in range(8):
        p = doc.new_page(width=100, height=100)
        p.insert_text((10, 20), "Sample Page")

    # Fetch page 0
    surf0 = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf0 is not None
    # Subsequent fetch must return identical cached surface
    surf0_cached = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf0_cached is surf0

    # Prime pages 1 through 6 (total 7 distinct pages requested)
    for i in range(1, 7):
        pdf_handler.get_page_cairo_surface(doc, i, 1.0)

    # Cache should be bounded to at most 6 surfaces
    assert len(pdf_handler._cairo_page_cache) <= 6

    # Invalidate cache for doc
    pdf_handler.invalidate_page_cache(doc)
    assert len([k for k in pdf_handler._cairo_page_cache if k[0] == id(doc)]) == 0


def test_get_page_cairo_surface_clipped():
    """Verify sub-rectangle clipped surface generation."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.draw_rect([100, 100, 300, 400], color=(0, 0, 1), fill=(1, 1, 0))

    clip_rect = fitz.Rect(100, 100, 250, 300) # 150x200 area
    surf_clip = pdf_handler.get_page_cairo_surface(doc, 0, 1.0, clip_rect=clip_rect)
    assert surf_clip is not None
    assert surf_clip.get_width() == 150
    assert surf_clip.get_height() == 200


def test_update_page_cairo_surface_rect():
    """Verify in-place update of cached Cairo surface for sub-rectangle without full re-render."""
    pdf_handler.invalidate_page_cache()
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.draw_rect([0, 0, 300, 300], color=None, fill=(1, 1, 1)) # All white

    surf = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf is not None
    data_orig = bytes(surf.get_data())

    # Draw a blue rectangle on page in sub-region (50, 50, 120, 120)
    page.draw_rect([50, 50, 120, 120], color=None, fill=(0, 0, 1))

    # Update only the modified sub-rectangle
    rect = (50, 50, 120, 120)
    success = pdf_handler.update_page_cairo_surface_rect(doc, 0, 1.0, rect)
    assert success is True

    # Same surface reference must remain cached
    surf_updated = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf_updated is surf

    # Sub-rectangle region must now contain blue pixels (BGRX: B=255, G=0, R=0, X=255)
    data = surf.get_data()
    inside_idx = (70 * 300 + 70) * 4
    b, g, r, x = data[inside_idx:inside_idx + 4]
    assert b == 255
    assert g == 0
    assert r == 0

    # Outside region (e.g. at 200, 200) must still remain white (255, 255, 255, 255)
    outside_idx = (200 * 300 + 200) * 4
    ob, og, ore, ox = data[outside_idx:outside_idx + 4]
    assert ob == 255
    assert og == 255
    assert ore == 255


def test_draw_page_to_cairo_with_dirty_rect():
    """Verify draw_page_to_cairo handles full page and dirty rect clipping."""
    doc = fitz.open()
    doc.new_page(width=200, height=200)

    target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 200, 200)
    cr = cairo.Context(target_surf)

    # 1. Full page draw
    ok, err = pdf_handler.draw_page_to_cairo(cr, doc, 0, 1.0)
    assert ok is True
    assert err is None

    # 2. Sub-rectangle dirty rect draw
    ok2, err2 = pdf_handler.draw_page_to_cairo(cr, doc, 0, 1.0, dirty_rect=(20, 20, 50, 50))
    assert ok2 is True
    assert err2 is None


def test_window_dirty_rect_queue_and_bounding_box_culling():
    """Verify window.queue_canvas_dirty_rect and viewport culling of offscreen objects."""
    win = MagicMock()
    win.pdf_view = MagicMock()
    win._dirty_clip_rect = None

    # Test queueing single rect
    PdfEditorWindow.queue_canvas_dirty_rect(win, (10, 10, 50, 50))
    assert win._dirty_clip_rect == (10, 10, 50, 50)
    win.pdf_view.queue_draw.assert_called_once()

    # Test unioning with a second rect
    PdfEditorWindow.queue_canvas_dirty_rect(win, (30, 20, 80, 70))
    # Union should encompass (10, 10) to (110, 90) -> (10, 10, 100, 80)
    assert win._dirty_clip_rect == (10, 10, 100, 80)


def test_window_draw_pdf_page_culls_offscreen_objects():
    """Verify _draw_page_content skips objects whose bounding boxes do not intersect clip extents."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)

    win = MagicMock()
    win.doc = doc
    win.zoom_level = 1.0
    win.current_page_index = 0
    win.dragged_object = None
    win.inline_editor_widget = None
    win.inline_editor_text_obj = None
    win.temp_image_bbox = None
    win.temp_stamp_bbox = None
    win.temp_clone_patch_bbox = None
    win.temp_redact_bbox = None
    win.temp_form_field_rect = None
    win.temp_sig_bbox = None
    win.temp_stroke = None
    win.temp_shape = None
    win.selected_text = None
    win.selected_image = None
    win.selected_shape = None
    win.selected_stroke = None
    win.selected_form_field = None
    win.selected_sig_annot = None
    win.selected_measurement = None
    win.selected_redaction_mark = None
    win.show_ocr_overlay = False
    win.highlighted_native_annot = None
    win.active_native_measurement = None
    win.view_mode = False
    win.view_sel_rect = None

    # On-screen text vs offscreen text
    on_screen_text = EditableText(page_number=0, x=50, y=50, text="Visible", font_size=12, is_new=True)
    on_screen_text.bbox = (50, 50, 100, 70)

    offscreen_text = EditableText(page_number=0, x=800, y=800, text="Offscreen", font_size=12, is_new=True)
    offscreen_text.bbox = (800, 800, 900, 820)

    win.editable_texts = [on_screen_text, offscreen_text]
    win.editable_images = []
    win.editable_shapes = []
    win.editable_strokes = []
    win.form_fields = []

    target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 500, 500)
    cr = cairo.Context(target_surf)

    # Restrict dirty rect to (20, 20, 150, 150)
    with patch("word_sys_pdf_editor.window.PangoCairo.show_layout") as mock_show_layout:
        PdfEditorWindow._draw_page_content(
            win,
            area=win.pdf_view,
            cr=cr,
            page_index=0,
            page_offset_x=0,
            page_offset_y=0,
            page_w=500,
            page_h=500,
            dirty_rect=(20, 20, 150, 150)
        )

        # Visible text should be laid out, while offscreen text must be skipped
        assert mock_show_layout.call_count == 1
        rendered_layout = mock_show_layout.call_args[0][1]
        assert rendered_layout.get_text() == "Visible"


def test_window_draw_pdf_page_culls_offscreen_images_shapes_and_strokes():
    """Verify _draw_page_content culls images, shapes, and ink strokes outside the clip extents."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)

    win = MagicMock()
    win.doc = doc
    win.zoom_level = 1.0
    win.current_page_index = 0
    win.dragged_object = None
    win.inline_editor_widget = None
    win.inline_editor_text_obj = None
    win.temp_image_bbox = None
    win.temp_stamp_bbox = None
    win.temp_clone_patch_bbox = None
    win.temp_redact_bbox = None
    win.temp_form_field_rect = None
    win.temp_sig_bbox = None
    win.temp_stroke = None
    win.temp_shape = None
    win.selected_text = None
    win.selected_image = None
    win.selected_shape = None
    win.selected_stroke = None
    win.selected_form_field = None
    win.selected_sig_annot = None
    win.selected_measurement = None
    win.selected_redaction_mark = None
    win.show_ocr_overlay = False
    win.highlighted_native_annot = None
    win.active_native_measurement = None
    win.view_mode = False
    win.view_sel_rect = None

    win.editable_texts = []
    win.form_fields = []

    # 1 byte fake png
    dummy_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    vis_img = EditableImage(bbox=(30, 30, 80, 80), page_number=0, xref=0, image_bytes=dummy_bytes, is_new=True)
    off_img = EditableImage(bbox=(800, 800, 900, 900), page_number=0, xref=0, image_bytes=dummy_bytes, is_new=True)
    win.editable_images = [vis_img, off_img]

    vis_shape = EditableShape(page_number=0, shape_type=EditableShape.SHAPE_RECTANGLE, bbox=(40, 40, 90, 90))
    off_shape = EditableShape(page_number=0, shape_type=EditableShape.SHAPE_RECTANGLE, bbox=(700, 700, 850, 850))
    win.editable_shapes = [vis_shape, off_shape]

    vis_stroke = EditableStroke(page_number=0, stroke_color=(1, 0, 0), stroke_width=2.0)
    vis_stroke.points = [(45, 45), (55, 55)]
    vis_stroke.bbox = (45, 45, 55, 55)

    off_stroke = EditableStroke(page_number=0, stroke_color=(0, 1, 0), stroke_width=2.0)
    off_stroke.points = [(750, 750), (780, 780)]
    off_stroke.bbox = (750, 750, 780, 780)
    win.editable_strokes = [vis_stroke, off_stroke]

    target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 500, 500)
    cr = cairo.Context(target_surf)

    with patch("word_sys_pdf_editor.window.GdkPixbuf.PixbufLoader.new") as mock_loader:
        loader_instance = MagicMock()
        mock_loader.return_value = loader_instance
        loader_instance.get_pixbuf.return_value = None

        PdfEditorWindow._draw_page_content(
            win,
            area=win.pdf_view,
            cr=cr,
            page_index=0,
            page_offset_x=0,
            page_offset_y=0,
            page_w=500,
            page_h=500,
            dirty_rect=(20, 20, 100, 100)
        )

        # Pixbuf loader should only be instantiated for the visible image, NOT the offscreen image
        assert mock_loader.call_count == 1



# ============================================================================
# SECTION: test_font_cache.py
# ============================================================================
"""Tests for Part 66: Instant App Launch & Persistent Fontconfig Disk I/O Cache."""

import os
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from word_sys_pdf_editor import utils
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.models import EditableText


def test_get_font_cache_path(monkeypatch):
    """Verify font cache path resolution adheres to XDG_CACHE_HOME and default ~/.cache."""
    temp_dir = tempfile.mkdtemp()
    monkeypatch.setenv("XDG_CACHE_HOME", temp_dir)
    cache_path = utils.get_font_cache_path()
    assert str(cache_path).startswith(temp_dir)
    assert cache_path.name == "font_cache.json"
    assert cache_path.parent.name == "word-sys-pdf-editor"


def test_save_and_load_persistent_font_cache():
    """Verify saving font data to disk cache and restoring it with directory mtime validation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "test_font_cache.json"
        dummy_font_dir = Path(temp_dir) / "fonts"
        dummy_font_dir.mkdir()

        dummy_fonts = {
            "Custom Sans": {
                "Regular": str(dummy_font_dir / "CustomSans-Regular.ttf"),
                "Bold": str(dummy_font_dir / "CustomSans-Bold.ttf")
            },
            "Custom Serif": {
                "Regular": str(dummy_font_dir / "CustomSerif-Regular.ttf")
            }
        }
        dummy_families = ["Custom Sans", "Custom Serif"]

        # Save cache
        saved = utils.save_persistent_font_cache(
            dummy_fonts, dummy_families, [dummy_font_dir], cache_path=cache_file
        )
        assert saved is True
        assert cache_file.is_file()

        # Patch _get_font_dirs to return our dummy_font_dir
        with patch.object(utils, "_get_font_dirs", return_value=[dummy_font_dir]):
            utils.SYSTEM_FONTS.clear()
            utils.FONT_FAMILY_LIST_SORTED.clear()
            utils.FONT_SCAN_COMPLETED.clear()

            loaded = utils.load_persistent_font_cache(cache_path=cache_file)
            assert loaded is True
            assert utils.FONT_SCAN_COMPLETED.is_set()
            assert "Custom Sans" in utils.SYSTEM_FONTS
            assert utils.FONT_FAMILY_LIST_SORTED == dummy_families


def test_persistent_font_cache_invalidation_on_mtime_change():
    """Verify persistent cache is invalidated when font directory mtime changes."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "test_font_cache.json"
        dummy_font_dir = Path(temp_dir) / "fonts"
        dummy_font_dir.mkdir()

        dummy_fonts = {"TestFont": {"Regular": "TestFont.ttf"}}
        dummy_families = ["TestFont"]

        utils.save_persistent_font_cache(
            dummy_fonts, dummy_families, [dummy_font_dir], cache_path=cache_file
        )

        with patch.object(utils, "_get_font_dirs", return_value=[dummy_font_dir]):
            # 1. Fresh cache matches
            assert utils.load_persistent_font_cache(cache_path=cache_file) is True

            # 2. Touch directory to advance mtime by 10 seconds
            current_mtime = dummy_font_dir.stat().st_mtime
            os.utime(dummy_font_dir, (current_mtime + 10.0, current_mtime + 10.0))

            # 3. Cache must be detected as stale
            assert utils.load_persistent_font_cache(cache_path=cache_file) is False


def test_persistent_font_cache_corrupt_file_handling():
    """Verify corrupt, empty, or incompatible cache files return False safely."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "corrupt_font_cache.json"

        # 1. Non-existent file
        assert utils.load_persistent_font_cache(cache_path=cache_file) is False

        # 2. Corrupt JSON syntax
        with open(cache_file, "w") as f:
            f.write("{invalid_json_data:")
        assert utils.load_persistent_font_cache(cache_path=cache_file) is False

        # 3. Wrong schema version
        with open(cache_file, "w") as f:
            json.dump({"version": 999, "dir_mtimes": {}}, f)
        assert utils.load_persistent_font_cache(cache_path=cache_file) is False


def test_scan_system_fonts_direct_discovers_fonts():
    """Verify _scan_system_fonts_direct retrieves system fonts via fc-list or directory traversal."""
    font_dirs = utils._get_font_dirs()
    fonts_data = utils._scan_system_fonts_direct(font_dirs)
    assert isinstance(fonts_data, dict)
    assert len(fonts_data) > 0

    # System fonts should discover standard Linux fonts (e.g., Liberation Sans or Noto Sans or DejaVu Sans)
    common_names = {"Liberation Sans", "DejaVu Sans", "Noto Sans", "Ubuntu", "Free Sans", "Sans"}
    assert any(name in fonts_data for name in common_names)


def test_scan_system_fonts_async_instant_cache_hit():
    """Verify scan_system_fonts_async returns in < 15ms when persistent cache is warm."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_file = Path(temp_dir) / "fast_cache.json"
        dummy_dir = Path(temp_dir) / "fonts"
        dummy_dir.mkdir()

        dummy_fonts = {f"Font {i}": {"Regular": f"font_{i}.ttf"} for i in range(100)}
        dummy_families = sorted(dummy_fonts.keys())

        utils.save_persistent_font_cache(
            dummy_fonts, dummy_families, [dummy_dir], cache_path=cache_file
        )

        with patch.object(utils, "_get_font_dirs", return_value=[dummy_dir]):
            utils.SYSTEM_FONTS.clear()
            utils.FONT_FAMILY_LIST_SORTED.clear()
            utils.FONT_SCAN_COMPLETED.clear()

            callback_mock = MagicMock()
            t0 = time.perf_counter()
            utils.scan_system_fonts_async(callback_on_done=callback_mock, cache_path=cache_file)
            duration_ms = (time.perf_counter() - t0) * 1000

            # Instant cache load should complete in under 15ms
            assert duration_ms < 15.0
            assert utils.FONT_SCAN_COMPLETED.is_set()
            assert len(utils.FONT_FAMILY_LIST_SORTED) == 100


def test_deferred_font_combo_population():
    """Verify deferred population of font combo dropdown on first text formatting interaction."""
    win = MagicMock()
    win._is_closing = False
    win._is_closed = False
    win.font_store = MagicMock()
    win.font_store.__len__.return_value = 50
    win.font_combo = MagicMock()
    win._font_combo_populated = False
    win.selected_text = None
    win.current_file_path = None
    win.doc = None
    win.status_label = MagicMock()
    win._populate_font_combo = lambda: PdfEditorWindow._populate_font_combo(win)

    # Initial mock font list
    mock_families = [f"Family {i}" for i in range(50)]
    with patch.object(utils, "FONT_FAMILY_LIST_SORTED", mock_families), \
         patch.object(utils, "UNICODE_FONT_PATH", "/usr/share/fonts/dummy.ttf"):

        # 1. Initial font scan finish: defers full population, sets default font
        PdfEditorWindow._on_font_scan_complete(win)
        assert win._font_combo_populated is False
        win.font_store.clear.assert_called_once()
        win.font_store.append.assert_called_once_with(["Family 0", "Family 0"])

        # 2. First call to _ensure_font_combo_populated: populates all 50 items
        PdfEditorWindow._ensure_font_combo_populated(win)
        assert win._font_combo_populated is True
        assert win.font_store.append.call_count == 51 # 1 from startup + 50 from full populate

        # 3. Second call is idempotent: does not re-append
        win.font_store.append.reset_mock()
        PdfEditorWindow._ensure_font_combo_populated(win)
        win.font_store.append.assert_not_called()

