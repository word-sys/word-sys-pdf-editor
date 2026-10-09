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
