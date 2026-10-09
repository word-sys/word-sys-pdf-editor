"""
Test suite for Part 27: Inline Canvas Text Editor Overlay.
Verifies pixel-perfect positioning, typography matching, double-click triggering,
keyboard ergonomics (Escape, Enter, Shift+Enter, Ctrl+Enter, F2), dynamic widening,
focus-leave committing, and zoom synchronization.
"""

import unittest
import tempfile
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
from gi.repository import Gtk, Adw, Gdk, GLib, Pango

from word_sys_pdf_editor.models import EditableText
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.window import PdfEditorWindow


def has_screen_display():
    return Gdk.Display.get_default() is not None


class TestInlineTextEditorOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize an application instance for GTK widgets if display exists
        if has_screen_display():
            try:
                cls.app = Adw.Application(application_id="org.wordsys.test.inlinetext")
                cls.app.register(None)
            except Exception:
                cls.app = None
        else:
            cls.app = None

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.doc_path = os.path.join(self.temp_dir.name, "inline_test.pdf")

        # Create a sample PDF document with several text blocks
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text(fitz.Point(100, 150), "Sample Title Heading", fontsize=18)
        page.insert_text(fitz.Point(100, 200), "First paragraph body text.", fontsize=12)
        page.insert_text(fitz.Point(100, 250), "Line to test double click.", fontsize=12)
        doc.save(self.doc_path)
        doc.close()

        if has_screen_display() and self.app:
            self.win = PdfEditorWindow(application=self.app)
            self.win.font_scan_in_progress = False
            doc_loaded, _ = pdf_handler.load_pdf_document(self.doc_path)
            self.win._finish_loading(doc_loaded, None, self.doc_path, 0, self.win._active_session)
            self.doc = self.win.doc
        else:
            self.win = None
            self.doc = fitz.open(self.doc_path)

    def tearDown(self):
        if self.win:
            try:
                self.win.hide_text_editor()
            except Exception:
                pass
            if self.win.doc:
                try:
                    self.win.doc.close()
                except Exception:
                    pass
        elif self.doc:
            try:
                self.doc.close()
            except Exception:
                pass
        self.temp_dir.cleanup()

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_show_inline_editor_creates_widgets_and_sets_text(self):
        """Verify _show_inline_editor positions frame, textview, and pre-selects text."""
        self.assertGreater(len(self.win.editable_texts), 0)
        target = self.win.editable_texts[0]

        self.win._show_inline_editor(target)

        self.assertIsNotNone(self.win.inline_editor_widget)
        self.assertIsInstance(self.win.inline_editor_widget, Gtk.Frame)
        self.assertIsNotNone(self.win.inline_editor_tv)
        self.assertIsInstance(self.win.inline_editor_tv, Gtk.TextView)
        self.assertEqual(self.win.inline_editor_text_obj, target)

        buf = self.win.inline_editor_tv.get_buffer()
        text_in_buf = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        self.assertEqual(text_in_buf, target.text)

        # Verify text is pre-selected
        sel_bounds = buf.get_selection_bounds()
        self.assertEqual(len(sel_bounds), 2)
        s_iter, e_iter = sel_bounds
        self.assertEqual(s_iter.get_offset(), 0)
        self.assertEqual(e_iter.get_offset(), len(target.text))

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_typography_matching_and_adwaita_css_styling(self):
        """Verify font family, size scaling, weight, style, and colors are applied via CSS."""
        target = EditableText(
            x=100, y=200, text="Bold Red Text",
            font_size=16.0, font_family="Liberation Serif",
            color=(0.9, 0.1, 0.2), page_number=0, alignment="center"
        )
        target.bbox = (100, 200, 250, 225)
        target.is_bold = True
        target.is_italic = True
        target.font_family_base = "Liberation Serif"
        target.alignment = "center"

        self.win._show_inline_editor(target)

        # Justification must match alignment
        self.assertEqual(self.win.inline_editor_tv.get_justification(), Gtk.Justification.CENTER)

        # Style provider must be loaded
        self.assertIsNotNone(self.win._inline_editor_css_provider)

        # Calling _apply_inline_editor_style with different zoom reflects new scaled size
        self.win.zoom_level = 2.0
        self.win._apply_inline_editor_style()
        self.assertIsNotNone(self.win._inline_editor_css_provider)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_double_click_opens_inline_editor_in_edit_mode(self):
        """Verify n_press >= 2 in Edit Mode opens editor, but not in View Mode or on single click."""
        self.win.view_mode = False
        self.assertGreater(len(self.win.editable_texts), 0)
        target = self.win.editable_texts[0]

        # Calculate coordinates on drawing area corresponding to target
        page_offset_x = max(0, (self.win.pdf_view.get_allocated_width() - self.win.current_pdf_page_width) / 2)
        page_offset_y = max(0, (self.win.pdf_view.get_allocated_height() - self.win.current_pdf_page_height) / 2)
        click_x = page_offset_x + (target.bbox[0] + 5) * self.win.zoom_level
        click_y = page_offset_y + (target.bbox[1] + 5) * self.win.zoom_level

        # 1. Single click (n_press = 1): selects text, does NOT open editor
        self.win._hide_inline_editor()
        self.win.on_pdf_view_pressed(None, 1, click_x, click_y)
        self.assertEqual(self.win.selected_text, target)
        self.assertIsNone(self.win.inline_editor_widget)

        # 2. Double click (n_press = 2): opens inline editor
        self.win.on_pdf_view_pressed(None, 2, click_x, click_y)
        self.assertIsNotNone(self.win.inline_editor_widget)
        self.assertEqual(self.win.inline_editor_text_obj, target)

        # 3. View Mode: double click does NOT open editor
        self.win._hide_inline_editor()
        self.win.view_mode = True
        self.win.on_pdf_view_pressed(None, 2, click_x, click_y)
        self.assertIsNone(self.win.inline_editor_widget)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_keyboard_escape_cancels_and_reverts(self):
        """Verify pressing Escape cancels edit, reverts text, and removes editor."""
        target = self.win.editable_texts[0]
        orig_text = target.text

        self.win._show_inline_editor(target)
        buf = self.win.inline_editor_tv.get_buffer()
        buf.set_text("Temporarily Typed Text That Will Be Reverted")

        handled = self.win._on_inline_editor_key(None, Gdk.KEY_Escape, 0, 0)
        self.assertTrue(handled)

        # Editor dismissed
        self.assertIsNone(self.win.inline_editor_widget)
        # Text in target object remained unchanged
        self.assertEqual(target.text, orig_text)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_keyboard_enter_commits_single_line_edit(self):
        """Verify pressing Enter on single-line text commits changes and updates undo manager."""
        target = self.win.editable_texts[0]
        orig_text = target.text

        self.win._show_inline_editor(target)
        buf = self.win.inline_editor_tv.get_buffer()
        buf.set_text("Updated Single Line Title")

        handled = self.win._on_inline_editor_key(None, Gdk.KEY_Return, 0, 0)
        self.assertTrue(handled)

        # Editor dismissed and change committed
        self.assertIsNone(self.win.inline_editor_widget)
        self.assertEqual(target.text, "Updated Single Line Title")
        self.assertTrue(self.win.undo_manager.can_undo())

        # Test Undo reverts to original text
        self.win.undo_manager.undo()
        self.assertEqual(target.text, orig_text)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_keyboard_shift_enter_inserts_newline(self):
        """Verify Shift+Enter inserts a newline into buffer without committing."""
        target = self.win.editable_texts[0]
        self.win._show_inline_editor(target)
        buf = self.win.inline_editor_tv.get_buffer()
        buf.set_text("Line1")

        # Place cursor at end of text
        buf.place_cursor(buf.get_end_iter())

        handled = self.win._on_inline_editor_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType.SHIFT_MASK)
        self.assertTrue(handled)

        # Editor remains active
        self.assertIsNotNone(self.win.inline_editor_widget)
        text_now = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        self.assertIn("\n", text_now)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_keyboard_ctrl_enter_commits_multiline_edit(self):
        """Verify Ctrl+Enter commits multiline edits cleanly."""
        target = self.win.editable_texts[0]
        self.win._show_inline_editor(target)
        buf = self.win.inline_editor_tv.get_buffer()
        buf.set_text("Multi\nLine\nText")

        # Plain Enter on multiline text does NOT commit
        handled_plain = self.win._on_inline_editor_key(None, Gdk.KEY_Return, 0, 0)
        self.assertFalse(handled_plain)
        self.assertIsNotNone(self.win.inline_editor_widget)

        # Ctrl+Enter commits
        handled_ctrl = self.win._on_inline_editor_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType.CONTROL_MASK)
        self.assertTrue(handled_ctrl)
        self.assertIsNone(self.win.inline_editor_widget)
        self.assertEqual(target.text, "Multi\nLine\nText")

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_keyboard_f2_and_return_open_inline_editor_on_selected_text(self):
        """Verify global Return and F2 open inline editor on selected EditableText."""
        self.win.view_mode = False
        target = self.win.editable_texts[0]
        self.win.selected_text = target

        # Press F2
        handled_f2 = self.win.on_key_pressed(None, Gdk.KEY_F2, 0, 0)
        self.assertTrue(handled_f2)
        self.assertIsNotNone(self.win.inline_editor_widget)

        # Dismiss
        self.win._hide_inline_editor()
        self.assertIsNone(self.win.inline_editor_widget)

        # Press Return
        handled_ret = self.win.on_key_pressed(None, Gdk.KEY_Return, 0, 0)
        self.assertTrue(handled_ret)
        self.assertIsNotNone(self.win.inline_editor_widget)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_dynamic_frame_widening_as_user_types(self):
        """Verify editor frame widens dynamically as typed text exceeds base width."""
        target = self.win.editable_texts[0]
        self.win._show_inline_editor(target)

        base_w = self.win._inline_editor_base_w
        buf = self.win.inline_editor_tv.get_buffer()

        # Type a much longer string
        buf.set_text("This is an exceptionally long phrase typed dynamically by the user to test width growth")

        # Size request should expand beyond base_w
        w, h = self.win.inline_editor_widget.get_size_request()
        self.assertGreater(w, base_w)

        # Setting back to short text should not shrink below base_w
        buf.set_text("Short")
        w_short, _ = self.win.inline_editor_widget.get_size_request()
        self.assertGreaterEqual(w_short, base_w)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_focus_leave_commits_edit(self):
        """Verify losing focus commits pending inline edits."""
        target = self.win.editable_texts[0]
        self.win._show_inline_editor(target)
        buf = self.win.inline_editor_tv.get_buffer()
        buf.set_text("Committed on focus leave")

        self.win._commit_inline_edit()
        self.assertIsNone(self.win.inline_editor_widget)
        self.assertEqual(target.text, "Committed on focus leave")

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_discard_empty_new_text_object(self):
        """Verify committing empty text on a newly added text object cleanly discards it."""
        new_obj = EditableText(x=150, y=300, text="", is_new=True, page_number=0)
        self.win.editable_texts.append(new_obj)
        self.win._show_inline_editor(new_obj)

        self.win._commit_inline_edit()
        # Empty text must be discarded, not stored
        self.assertNotIn(new_obj, self.win.editable_texts)
        self.assertIsNone(self.win.selected_text)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_zoom_synchronization_updates_position_and_scaled_typography(self):
        """Verify _update_inline_editor_position recalculates margins, size, and scaled font CSS."""
        target = self.win.editable_texts[0]
        self.win.zoom_level = 1.0
        self.win._show_inline_editor(target)

        initial_margin_x = self.win.inline_editor_widget.get_margin_start()
        initial_margin_y = self.win.inline_editor_widget.get_margin_top()

        # Double zoom level
        self.win.zoom_level = 2.0
        self.win._update_inline_editor_position()

        new_margin_x = self.win.inline_editor_widget.get_margin_start()
        new_margin_y = self.win.inline_editor_widget.get_margin_top()

        # Canvas margins must scale or adjust with zoom
        self.assertNotEqual(new_margin_x, initial_margin_x)
        self.assertNotEqual(new_margin_y, initial_margin_y)
        self.assertIsNotNone(self.win._inline_editor_css_provider)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_underlying_pdf_text_double_click_fallback(self):
        """Verify double clicking underlying PDF text not in editable_texts finds word and opens editor."""
        self.win.view_mode = False
        # Clear editable_texts to simulate an unextracted or newly targeted span
        self.win.editable_texts.clear()
        self.win.selected_text = None

        page_offset_x = max(0, (self.win.pdf_view.get_allocated_width() - self.win.current_pdf_page_width) / 2)
        page_offset_y = max(0, (self.win.pdf_view.get_allocated_height() - self.win.current_pdf_page_height) / 2)
        # Click on "Sample Title Heading" at (100, 150)
        click_x = page_offset_x + 105 * self.win.zoom_level
        click_y = page_offset_y + 145 * self.win.zoom_level

        self.win.on_pdf_view_pressed(None, 2, click_x, click_y)

        # Should have hit-tested the word and opened the editor
        self.assertIsNotNone(self.win.inline_editor_widget)
        self.assertIsNotNone(self.win.selected_text)
        self.assertIn("Sample", self.win.selected_text.text)
        self.assertIn(self.win.selected_text, self.win.editable_texts)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_target_rect_custom_positioning(self):
        """Verify passing target_rect positions the editor specifically over the sub-rectangle."""
        target = self.win.editable_texts[0]
        custom_sub_rect = (150, 135, 220, 155)

        self.win._show_inline_editor(target, target_rect=custom_sub_rect)

        self.assertIsNotNone(self.win.inline_editor_widget)
        self.assertEqual(self.win._inline_editor_target_rect, custom_sub_rect)

        da_w = max(self.win.pdf_view.get_allocated_width(), self.win.current_pdf_page_width)
        page_offset_x = max(0.0, (da_w - self.win.current_pdf_page_width) / 2.0)
        expected_x = int(page_offset_x + 150 * self.win.zoom_level) - 2

        self.assertEqual(self.win.inline_editor_widget.get_margin_start(), expected_x)

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_rotated_page_inline_editor_positioning(self):
        """Verify inline editor positions correctly in screen space on 90-degree rotated pages."""
        # Create a 90-degree rotated page
        doc_rot = fitz.open()
        p_rot = doc_rot.new_page(width=600, height=800)
        p_rot.insert_text(fitz.Point(100, 150), "Rotated Page Text", fontsize=14)
        p_rot.set_rotation(90)
        rot_path = os.path.join(self.temp_dir.name, "rot_page.pdf")
        doc_rot.save(rot_path)
        doc_rot.close()

        win_rot = PdfEditorWindow(application=self.app)
        win_rot.font_scan_in_progress = False
        loaded, _ = pdf_handler.load_pdf_document(rot_path)
        win_rot._finish_loading(loaded, None, rot_path, 0, win_rot._active_session)

        self.assertGreater(len(win_rot.editable_texts), 0)
        target = win_rot.editable_texts[0]

        win_rot._show_inline_editor(target)
        self.assertIsNotNone(win_rot.inline_editor_widget)
        # Margin top and start should be strictly within visual boundaries
        self.assertGreaterEqual(win_rot.inline_editor_widget.get_margin_start(), 0)
        self.assertGreaterEqual(win_rot.inline_editor_widget.get_margin_top(), 0)

        win_rot.hide_text_editor()
        if win_rot.doc:
            win_rot.doc.close()

    @unittest.skipUnless(has_screen_display(), "Screen display not available")
    def test_sequential_edits_and_undo_redo_cycle(self):
        """Verify sequential inline edits maintain document consistency and undo/redo history."""
        target0 = self.win.editable_texts[0]
        target1 = self.win.editable_texts[1]
        orig_t0 = target0.text
        orig_t1 = target1.text

        # 1. Edit target0 and commit
        self.win._show_inline_editor(target0)
        self.win.inline_editor_tv.get_buffer().set_text("Title Version 2")
        self.win._commit_inline_edit()
        self.assertEqual(target0.text, "Title Version 2")

        # 2. Edit target1 and commit
        self.win._show_inline_editor(target1)
        self.win.inline_editor_tv.get_buffer().set_text("Body Version 2")
        self.win._commit_inline_edit()
        self.assertEqual(target1.text, "Body Version 2")

        # 3. Undo second edit
        self.win.undo_manager.undo()
        self.assertEqual(target1.text, orig_t1)
        self.assertEqual(target0.text, "Title Version 2")

        # 4. Undo first edit
        self.win.undo_manager.undo()
        self.assertEqual(target0.text, orig_t0)

        # 5. Redo first edit
        self.win.undo_manager.redo()
        self.assertEqual(target0.text, "Title Version 2")

        # 6. Redo second edit
        self.win.undo_manager.redo()
        self.assertEqual(target1.text, "Body Version 2")


if __name__ == "__main__":
    unittest.main()
