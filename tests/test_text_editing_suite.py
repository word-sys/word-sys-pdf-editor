"""Consolidated Inline Text Editing and Word-Level Typography Test Suite for word-sys-pdf-editor.

This suite validates the floating GtkTextView inline text editor, in-place text corrections,
word-level isolation, per-word styling/coloring/rotation, and typography state synchronizations.
"""

# ============================================================================
# SECTION: test_inline_text_editor.py
# ============================================================================
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
            self.win.set_continuous_scroll_mode(False)
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


# ============================================================================
# SECTION: test_inplace_text_correction_workflow.py
# ============================================================================
"""
Tests for Part 56: Scanned Document In-Place Text Correction Workflow.
Validates:
1. PatchObject and EditableText bidirectional linkage.
2. PDF stream baking and underlying OCR text purge under patches.
3. Canvas hit-testing priority (layered text selected before underlying patch).
4. Initiate text over patch workflow (double-click, Enter/T shortcuts, context menu).
5. Synchronized co-movement of patch and linked text (drag and arrow nudge).
6. Undo/Redo cycles with CompositeCommand for co-movement and co-deletion.
7. Localization coverage for Part 56 strings across all 7 supported locales.
"""

import os
import copy
import unittest
from unittest.mock import MagicMock, patch
import fitz

from word_sys_pdf_editor.models import (
    EditableText, EditableImage, EditableShape, PatchObject
)
from word_sys_pdf_editor.undo_manager import (
    UndoManager, AddObjectCommand, EditObjectCommand, DeleteObjectCommand,
    CompositeCommand
)
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.i18n import _, _STRINGS
from word_sys_pdf_editor.locales import (
    STRINGS_FR, STRINGS_DE, STRINGS_ES, STRINGS_IT, STRINGS_RU
)
from word_sys_pdf_editor.window import PdfEditorWindow


def create_solid_png_bytes(width=60, height=30, color=(255, 255, 255)):
    """Generate minimal valid PNG bytes for image/patch tests."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.clear_with(color[0] | (color[1] << 8) | (color[2] << 16))
    return pix.tobytes("png")


class MockCorrectionWindow:
    """Mock window providing required environment for testing in-place text correction."""
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.view_mode = False
        self.tool_mode = "select"
        self.editable_texts = []
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None
        self.dragged_object = None
        self.drag_start_pos = None
        self.drag_object_start_pos = None
        self.document_modified = False
        self.status_label = MagicMock()
        self.pdf_view = MagicMock()
        self.font_size = 12
        self.font_family = "Liberation Sans"
        self.font_color = (0.0, 0.0, 0.0)
        self.font_combo = None
        self.font_store = None
        self.font_size_spin = None
        self.inline_editor_widget = None
        self.inline_editor_tv = None
        self.inline_editor_text_obj = None

        self.undo_stack = []
        self.redo_stack = []
        self.undo_manager = UndoManager(self)
        self.font_scan_in_progress = False
        self._update_tab_dirty_state = lambda: None

    def _update_undo_redo_buttons(self):
        pass

    def _update_ui_state(self):
        pass

    def _refresh_thumbnail(self, page_index):
        pass

    def _switch_active_page(self, page_index):
        self.current_page_index = page_index

    def _update_text_format_controls(self, text_obj):
        pass

    def _show_inline_editor(self, text_obj, click_x=None, click_y=None, target_rect=None):
        self.inline_editor_widget = MagicMock()
        self.inline_editor_text_obj = text_obj
        self._inline_editor_target_rect = target_rect

    def _hide_inline_editor(self):
        self.inline_editor_widget = None
        self.inline_editor_text_obj = None

    def _visual_to_unrotated_delta(self, dx, dy):
        return dx, dy

    def _find_text_at_pos(self, px, py):
        return PdfEditorWindow._find_text_at_pos(self, px, py)

    def _find_image_at_pos(self, px, py):
        return PdfEditorWindow._find_image_at_pos(self, px, py)

    def _find_shape_at_pos(self, px, py):
        return None

    def _find_stroke_at_pos(self, px, py):
        return None

    def _find_form_field_at_pos(self, px, py):
        return None

    def _find_measurement_at_pos(self, px, py):
        return None

    def _close_active_form_field_editor(self):
        pass

    def commit_pending_format_change(self):
        pass

    get_selected_object = PdfEditorWindow.get_selected_object
    select_object = PdfEditorWindow.select_object

    def initiate_text_over_patch(self, patch_obj):
        return PdfEditorWindow.initiate_text_over_patch(self, patch_obj)


class TestModelLinkage(unittest.TestCase):
    """Test model attributes and linkage between PatchObject and EditableText."""

    def test_patch_object_defaults(self):
        png = create_solid_png_bytes()
        patch = PatchObject(bbox=(10, 20, 110, 50), page_number=0, image_bytes=png)
        self.assertTrue(patch.is_patch)
        self.assertTrue(patch.purge_underlying_text)
        self.assertIsNone(patch.linked_text)

    def test_editable_text_defaults(self):
        text = EditableText(x=10, y=20, text="Sample Text")
        self.assertIsNone(text.linked_patch)

    def test_bidirectional_linkage(self):
        png = create_solid_png_bytes()
        patch = PatchObject(bbox=(50, 60, 150, 90), page_number=0, image_bytes=png)
        text = EditableText(x=52, y=62, text="Replacement Text")
        patch.linked_text = text
        text.linked_patch = patch

        self.assertIs(patch.linked_text, text)
        self.assertIs(text.linked_patch, patch)


class TestPdfHandlerStreamBakingAndTextPurge(unittest.TestCase):
    """Test PDF stream baking and underlying OCR/vector text purge under patches."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        # Insert background text to simulate scanned OCR or vector text
        self.page.insert_text((100, 150), "Obsolete OCR Text to be Patched", fontsize=14, color=(0, 0, 0))
        self.page.insert_text((100, 300), "Safe Surrounding Document Text", fontsize=14, color=(0, 0, 0))

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_purge_underlying_text_under_patch(self):
        # Verify initial text exists
        initial_text = self.page.get_text()
        self.assertIn("Obsolete OCR Text", initial_text)
        self.assertIn("Safe Surrounding Document Text", initial_text)

        # Create patch covering "Obsolete OCR Text to be Patched"
        png_bytes = create_solid_png_bytes(width=250, height=40)
        patch_rect = (90, 130, 350, 170)
        patch_obj = PatchObject(
            bbox=patch_rect,
            page_number=0,
            image_bytes=png_bytes,
            purge_underlying_text=True,
            is_new=True
        )

        # Apply patch to page
        ok, err = pdf_handler._apply_single_object_to_page(self.doc, self.page, patch_obj)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Apply replacement text over patch
        rep_text = EditableText(x=95, y=135, text="Fresh Corrected Line", font_size=12, page_number=0, is_new=True, baseline=150)
        ok_t, err_t = pdf_handler._apply_single_object_to_page(self.doc, self.page, rep_text)
        self.assertTrue(ok_t)

        # Check updated text extraction
        extracted = self.page.get_text()
        self.assertNotIn("Obsolete OCR Text", extracted)
        self.assertIn("Fresh Corrected Line", extracted)
        self.assertIn("Safe Surrounding Document Text", extracted)

    def test_rebuild_page_layers_patch_before_text(self):
        # Test full rebuild_page preserves patch underneath replacement text
        png_bytes = create_solid_png_bytes(width=200, height=30)
        patch_obj = PatchObject(bbox=(90, 130, 320, 170), page_number=0, image_bytes=png_bytes, purge_underlying_text=True, is_new=True)
        rep_text = EditableText(x=95, y=135, text="Layered Above Patch", font_size=12, page_number=0, is_new=True, baseline=150)
        patch_obj.linked_text = rep_text
        rep_text.linked_patch = patch_obj

        # Create snapshot for rebuild
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)

        ok, err = pdf_handler.rebuild_page(
            self.doc, 0,
            all_texts=[rep_text],
            all_shapes=[],
            all_images=[patch_obj]
        )
        self.assertTrue(ok)
        self.assertIsNone(err)

        extracted = self.doc[0].get_text()
        self.assertNotIn("Obsolete OCR Text", extracted)
        self.assertIn("Layered Above Patch", extracted)
        self.assertIn("Safe Surrounding Document Text", extracted)


class TestCanvasHitTestingPriority(unittest.TestCase):
    """Test canvas hit-testing priority: text over patch is selected first."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        self.win = MockCorrectionWindow(self.doc)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_text_selected_over_underlying_patch(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 100, 250, 150), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=105, y=105, text="Overlay Text", font_size=12, page_number=0)
        text_obj.bbox = (105, 105, 200, 125)
        self.win.editable_texts.append(text_obj)

        patch_obj.linked_text = text_obj
        text_obj.linked_patch = patch_obj

        # Click inside text bounds (120, 115)
        found_text = self.win._find_text_at_pos(120, 115)
        found_img = self.win._find_image_at_pos(120, 115)

        self.assertIsNotNone(found_text)
        self.assertIs(found_text, text_obj)
        self.assertIsNotNone(found_img)
        self.assertIs(found_img, patch_obj)

        # In on_pdf_view_pressed logic, clicked_text is evaluated first
        clicked_text = found_text
        clicked_image = found_img
        selected = None
        if clicked_text:
            selected = clicked_text
        elif clicked_image:
            selected = clicked_image

        self.assertIs(selected, text_obj)

    def test_patch_selected_when_clicking_outside_text_bounds(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 100, 250, 150), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=105, y=105, text="Short", font_size=12, page_number=0)
        text_obj.bbox = (105, 105, 140, 125)
        self.win.editable_texts.append(text_obj)

        # Click at (220, 140) which is on patch but outside text bbox
        found_text = self.win._find_text_at_pos(220, 140)
        found_img = self.win._find_image_at_pos(220, 140)

        self.assertIsNone(found_text)
        self.assertIs(found_img, patch_obj)


class TestInitiateTextOverPatch(unittest.TestCase):
    """Test initiate_text_over_patch workflow."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        self.win = MockCorrectionWindow(self.doc)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_initiate_text_creates_linked_editable_text(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 200, 260, 230), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = self.win.initiate_text_over_patch(patch_obj)
        self.assertIsNotNone(text_obj)
        self.assertIsInstance(text_obj, EditableText)
        self.assertIn(text_obj, self.win.editable_texts)
        self.assertIs(patch_obj.linked_text, text_obj)
        self.assertIs(text_obj.linked_patch, patch_obj)
        self.assertIs(self.win.selected_text, text_obj)
        self.assertIsNone(self.win.selected_image)

        # Check spatial alignment
        self.assertAlmostEqual(text_obj.x, 102.0)
        self.assertAlmostEqual(text_obj.y, 201.0)
        self.assertEqual(text_obj.bbox[2], 260.0)
        self.assertEqual(text_obj.bbox[3], 230.0)

    def test_initiate_text_reuses_existing_linked_text(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 200, 260, 230), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        t1 = self.win.initiate_text_over_patch(patch_obj)
        t1.text = "Initial Correction"
        self.assertEqual(len(self.win.editable_texts), 1)

        # Call initiate again on same patch
        t2 = self.win.initiate_text_over_patch(patch_obj)
        self.assertIs(t1, t2)
        self.assertEqual(len(self.win.editable_texts), 1)


class TestSynchronizedCoMovementAndUndo(unittest.TestCase):
    """Test synchronized movement and undo/redo of linked patch and text."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)
        self.win = MockCorrectionWindow(self.doc)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_co_movement_drag_update_and_commit(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100.0, 100.0, 200.0, 140.0), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=102.0, y=101.0, text="Move Together", font_size=12, page_number=0)
        text_obj.bbox = (102.0, 101.0, 190.0, 130.0)
        text_obj.baseline = 115.0
        text_obj.original_bbox = text_obj.bbox
        text_obj.original_baseline = text_obj.baseline
        self.win.editable_texts.append(text_obj)

        patch_obj.linked_text = text_obj
        text_obj.linked_patch = patch_obj

        # Simulate on_drag_begin
        self.win.dragged_object = patch_obj
        self.win.drag_start_pos = (100.0, 100.0)
        self.win.drag_begin_state = copy.deepcopy(patch_obj.__dict__)
        self.win.drag_object_start_pos = (patch_obj.bbox[0], patch_obj.bbox[1])
        self.win.linked_drag_begin_state = copy.deepcopy(text_obj.__dict__)
        self.win.linked_drag_start_pos = (text_obj.x, text_obj.y)

        # Move by delta (+30, +50)
        delta_x = 30.0
        delta_y = 50.0

        # Simulate on_drag_update
        patch_obj.x = 100.0 + delta_x
        patch_obj.y = 100.0 + delta_y
        patch_obj.bbox = (130.0, 150.0, 230.0, 190.0)

        lt_start_x, lt_start_y = self.win.linked_drag_start_pos
        text_obj.x = lt_start_x + delta_x
        text_obj.y = lt_start_y + delta_y
        text_obj.bbox = (132.0, 151.0, 220.0, 180.0)
        text_obj.baseline = text_obj.y + (text_obj.font_size * 0.9)

        # Verify co-moved positions during drag
        self.assertEqual(patch_obj.x, 130.0)
        self.assertEqual(patch_obj.y, 150.0)
        self.assertEqual(text_obj.x, 132.0)
        self.assertEqual(text_obj.y, 151.0)

        # Simulate on_drag_end with CompositeCommand
        cmd_patch = EditObjectCommand(self.win, patch_obj, self.win.drag_begin_state, copy.deepcopy(patch_obj.__dict__))
        cmd_text = EditObjectCommand(self.win, text_obj, self.win.linked_drag_begin_state, copy.deepcopy(text_obj.__dict__))
        composite = CompositeCommand(self.win, [cmd_patch, cmd_text])
        self.win.undo_manager.add_command(composite)

        self.assertEqual(len(self.win.undo_manager.undo_stack), 1)

        # Undo co-movement
        self.win.undo_manager.undo()
        self.assertEqual(patch_obj.x, 100.0)
        self.assertEqual(patch_obj.y, 100.0)
        self.assertEqual(patch_obj.bbox, (100.0, 100.0, 200.0, 140.0))
        self.assertEqual(text_obj.x, 102.0)
        self.assertEqual(text_obj.y, 101.0)
        self.assertEqual(text_obj.bbox, (102.0, 101.0, 190.0, 130.0))

        # Redo co-movement
        self.win.undo_manager.redo()
        self.assertEqual(patch_obj.x, 130.0)
        self.assertEqual(patch_obj.y, 150.0)
        self.assertEqual(text_obj.x, 132.0)
        self.assertEqual(text_obj.y, 151.0)

    def test_co_deletion_and_undo(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(50.0, 50.0, 150.0, 90.0), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=52.0, y=52.0, text="To Delete", font_size=12, page_number=0)
        text_obj.bbox = (52.0, 52.0, 140.0, 75.0)
        text_obj.original_bbox = text_obj.bbox
        self.win.editable_texts.append(text_obj)

        patch_obj.linked_text = text_obj
        text_obj.linked_patch = patch_obj

        # Delete patch with linked text
        cmd1 = DeleteObjectCommand(self.win, patch_obj)
        cmd2 = DeleteObjectCommand(self.win, text_obj)
        batch_delete = CompositeCommand(self.win, [cmd1, cmd2])
        batch_delete.execute()
        self.win.undo_manager.add_command(batch_delete)

        self.assertNotIn(patch_obj, self.win.editable_images)
        self.assertNotIn(text_obj, self.win.editable_texts)

        # Undo deletion: both restored
        self.win.undo_manager.undo()
        self.assertIn(patch_obj, self.win.editable_images)
        self.assertIn(text_obj, self.win.editable_texts)


class TestLocalizationAllLocales(unittest.TestCase):
    """Test localization completeness for Part 56 across all 7 locales."""

    REQUIRED_KEYS = [
        "menu_type_over_patch",
        "patch_type_tooltip",
        "status_patch_text_added",
        "guide_sc_type_over_patch"
    ]

    def test_en_and_tr_in_i18n(self):
        for lang in ["en", "tr"]:
            self.assertIn(lang, _STRINGS)
            for key in self.REQUIRED_KEYS:
                self.assertIn(key, _STRINGS[lang], f"Missing key '{key}' in lang '{lang}'")
                val = _STRINGS[lang][key]
                self.assertTrue(isinstance(val, str) and len(val.strip()) > 0)

    def test_fr_de_es_it_ru_in_locales(self):
        locale_dicts = {
            "fr": STRINGS_FR,
            "de": STRINGS_DE,
            "es": STRINGS_ES,
            "it": STRINGS_IT,
            "ru": STRINGS_RU,
        }
        for lang, d in locale_dicts.items():
            for key in self.REQUIRED_KEYS:
                self.assertIn(key, d, f"Missing key '{key}' in locale dictionary for '{lang}'")
                val = d[key]
                self.assertTrue(isinstance(val, str) and len(val.strip()) > 0)


class TestWindowInteractions(unittest.TestCase):
    """Test window-level interactions for Part 56: shortcuts, double-click, and nudge."""

    def setUp(self):
        from gi.repository import Gdk
        self.Gdk = Gdk
        self.doc = fitz.open()
        self.doc.new_page(width=600, height=800)
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)
        self.win = MockCorrectionWindow(self.doc)
        self.win.current_pdf_page_width = 600
        self.win.current_pdf_page_height = 800
        self.win.get_focus = MagicMock(return_value=None)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_key_pressed_triggers_initiate_text_on_patch(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100, 100, 200, 140), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)
        self.win.selected_image = patch_obj

        for key in [self.Gdk.KEY_Return, self.Gdk.KEY_KP_Enter, self.Gdk.KEY_t, self.Gdk.KEY_T]:
            # Reset
            self.win.editable_texts.clear()
            self.win.selected_text = None
            self.win.selected_image = patch_obj
            self.win.inline_editor_widget = None
            patch_obj.linked_text = None

            handled = PdfEditorWindow.on_key_pressed(self.win, None, key, 0, 0)
            self.assertTrue(handled, f"Key {key} should be handled for patch")
            self.assertIsNotNone(patch_obj.linked_text)
            self.assertIs(self.win.selected_text, patch_obj.linked_text)

    def test_arrow_nudge_comovement(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100.0, 100.0, 200.0, 140.0), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        text_obj = EditableText(x=102.0, y=101.0, text="Nudge Text", font_size=12, page_number=0)
        text_obj.bbox = (102.0, 101.0, 190.0, 130.0)
        text_obj.baseline = 115.0
        self.win.editable_texts.append(text_obj)

        patch_obj.linked_text = text_obj
        text_obj.linked_patch = patch_obj

        self.win.selected_image = patch_obj

        # Nudge right (dx = +1.0)
        handled = PdfEditorWindow.on_key_pressed(self.win, None, self.Gdk.KEY_Right, 0, 0)
        self.assertTrue(handled)
        self.assertEqual(patch_obj.bbox, (101.0, 100.0, 201.0, 140.0))
        self.assertEqual(patch_obj.x, 101.0)
        self.assertEqual(text_obj.bbox, (103.0, 101.0, 191.0, 130.0))
        self.assertEqual(text_obj.x, 103.0)

        # Undo nudge
        self.win.undo_manager.undo()
        self.assertEqual(patch_obj.bbox, (100.0, 100.0, 200.0, 140.0))
        self.assertEqual(patch_obj.x, 100.0)
        self.assertEqual(text_obj.bbox, (102.0, 101.0, 190.0, 130.0))
        self.assertEqual(text_obj.x, 102.0)

    def test_double_click_select_mode_triggers_initiate_text(self):
        png = create_solid_png_bytes()
        patch_obj = PatchObject(bbox=(100.0, 100.0, 200.0, 140.0), page_number=0, image_bytes=png)
        self.win.editable_images.append(patch_obj)

        self.win.canvas_to_page_coords = MagicMock(return_value=(0, 150.0, 120.0))
        self.win.is_canvas_point_on_page = MagicMock(return_value=True)

        # Double click (n_press = 2) at (150, 120) which is on patch
        PdfEditorWindow.on_pdf_view_pressed(self.win, None, 2, 150.0, 120.0)

        self.assertIsNotNone(patch_obj.linked_text)
        self.assertIs(self.win.selected_text, patch_obj.linked_text)
        self.assertIn(patch_obj.linked_text, self.win.editable_texts)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_word_level_typography.py
# ============================================================================
import copy
import fitz
import pytest
from unittest.mock import MagicMock

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk

from word_sys_pdf_editor.models import DocumentSession, EditableText, measure_text_width
from word_sys_pdf_editor.undo_manager import UndoManager, EditObjectCommand, CompositeCommand
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor import pdf_handler


@pytest.fixture(scope="module", autouse=True)
def init_adw():
    Adw.init()


def create_mock_window(doc):
    session = DocumentSession(doc=doc, pdf_path=None)
    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window._update_undo_redo_buttons = MagicMock()
    window._update_ui_state = MagicMock()
    window.status_label = MagicMock()
    window.pdf_view = MagicMock()
    window._last_font_family = "Liberation Sans"
    window._last_font_size = 11.0
    window._get_current_alignment = MagicMock(return_value='left')
    window.font_scan_in_progress = False
    window.inline_editor_tv = None
    window.inline_editor_text_obj = None
    window.inline_editor_widget = None
    window.underline_button = None
    window.strikethrough_button = None
    window.align_left_button = None
    window.align_center_button = None
    window.align_right_button = None
    window.align_justify_button = None

    undo_mgr = UndoManager(window)
    session.undo_manager = undo_mgr
    window.undo_manager = undo_mgr

    # Bind property accessors to session
    type(window).editable_texts = property(
        lambda self: self._active_session.editable_texts if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'editable_texts', val) if self._active_session else None
    )
    type(window).editable_shapes = property(
        lambda self: self._active_session.editable_shapes if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'editable_shapes', val) if self._active_session else None
    )
    type(window).editable_images = property(
        lambda self: self._active_session.editable_images if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'editable_images', val) if self._active_session else None
    )
    type(window).editable_strokes = property(
        lambda self: self._active_session.editable_strokes if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'editable_strokes', val) if self._active_session else None
    )
    type(window).selected_text = property(
        lambda self: self._active_session.selected_text if self._active_session else None,
        lambda self, val: PdfEditorWindow.selected_text.fset(self, val)
    )
    type(window).word_selection_mode = property(
        lambda self: self._active_session.word_selection_mode if self._active_session else False,
        lambda self, val: setattr(self._active_session, 'word_selection_mode', val) if self._active_session else None
    )
    type(window)._page_objects_cache = PdfEditorWindow._page_objects_cache
    type(window).form_fields = property(
        lambda self: self._active_session.form_fields if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'form_fields', val) if self._active_session else None
    )

    # Bind methods
    window.commit_pending_format_change = PdfEditorWindow.commit_pending_format_change.__get__(window, PdfEditorWindow)
    window._toggle_word_style = PdfEditorWindow._toggle_word_style.__get__(window, PdfEditorWindow)
    window.on_text_format_changed = PdfEditorWindow.on_text_format_changed.__get__(window, PdfEditorWindow)
    window.get_selected_word_bbox = PdfEditorWindow.get_selected_word_bbox.__get__(window, PdfEditorWindow)
    window._isolate_selected_word_span = PdfEditorWindow._isolate_selected_word_span.__get__(window, PdfEditorWindow)
    window.on_rotate_object_cw_clicked = PdfEditorWindow.on_rotate_object_cw_clicked.__get__(window, PdfEditorWindow)
    window.on_object_rotation_spin_changed = PdfEditorWindow.on_object_rotation_spin_changed.__get__(window, PdfEditorWindow)
    window._update_rotation_controls = MagicMock()
    window._update_text_format_controls = MagicMock()

    return window, session


def test_commit_pending_format_change_guards():
    """Verify commit_pending_format_change ignores deleted objects and internal flags."""
    doc = fitz.open()
    doc.new_page(width=500, height=200)
    window, session = create_mock_window(doc)

    t = EditableText(text="Hello world", x=50.0, y=50.0, page_number=0)
    session.editable_texts = [t]

    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    # Case 1: Only internal flags changed (_ghost_redacted, is_baked)
    t._ghost_redacted = True
    t.is_baked = True
    window.commit_pending_format_change()
    assert len(window.undo_manager.undo_stack) == 0

    # Case 2: Object is deleted (not in editable_texts)
    session.editable_texts = []
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)
    t.text = "Changed text"
    window.commit_pending_format_change()
    assert len(window.undo_manager.undo_stack) == 0


def test_single_word_styling_no_duplicate_command_and_exact_gap():
    """Verify styling a word inside paragraph causes no duplicate commands and maintains exact gap."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    text_str = "z yazı ve sözlük kodunu yazınız."
    t = EditableText(
        text=text_str,
        x=50.0,
        y=50.0,
        font_family="Liberation Sans",
        font_size=11.0,
        page_number=0
    )
    t.bbox = (50.0, 38.0, 207.0, 53.0)
    session.editable_texts = [t]

    # Simulate middle-click selection on word "yazı"
    start_c = 2
    end_c = 6
    window.selected_text = t
    window.selected_word = "yazı"
    window.selected_word_start_char = start_c
    window.selected_word_end_char = end_c
    window.word_selection_mode = True
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    # Apply bold style
    window._toggle_word_style(t, "bold")

    # Undo stack must contain exactly 1 composite command, NOT an EditObjectCommand on t
    assert len(window.undo_manager.undo_stack) == 1
    top_cmd = window.undo_manager.undo_stack[0]
    assert isinstance(top_cmd, CompositeCommand)

    # In editable_texts, original paragraph must be replaced by 3 spans
    assert len(session.editable_texts) == 3
    pre_s, mid_s, post_s = session.editable_texts
    assert pre_s.text == "z "
    assert mid_s.text == "yazı"
    assert post_s.text == " ve sözlük kodunu yazınız."

    assert mid_s.is_bold is True
    assert window.selected_text is mid_s

    # Sub-pixel gap check: post_span must start exactly at the right boundary of mid_span
    assert abs(post_s.bbox[0] - mid_s.bbox[2]) < 0.01


def test_single_word_color_change_via_on_text_format_changed():
    """Verify color change in word selection mode splits cleanly and sets color."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    text_str = "z yazı ve sözlük kodunu yazınız."
    t = EditableText(
        text=text_str,
        x=50.0,
        y=50.0,
        font_family="Liberation Sans",
        font_size=11.0,
        page_number=0
    )
    t.bbox = (50.0, 38.0, 207.0, 53.0)
    session.editable_texts = [t]

    start_c = 2
    end_c = 6
    window.selected_text = t
    window.selected_word = "yazı"
    window.selected_word_start_char = start_c
    window.selected_word_end_char = end_c
    window.word_selection_mode = True
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    # Mock format controls on window
    font_combo = MagicMock()
    font_combo.get_active.return_value = 0
    font_combo.get_active_iter.return_value = None
    font_combo.get_model.return_value = [["Liberation Sans"]]
    window.font_combo = font_combo

    font_size_spin = MagicMock()
    font_size_spin.get_value.return_value = 11.0
    window.font_size_spin = font_size_spin

    bold_btn = MagicMock()
    bold_btn.get_active.return_value = False
    window.bold_button = bold_btn

    italic_btn = MagicMock()
    italic_btn.get_active.return_value = False
    window.italic_button = italic_btn

    color_btn = MagicMock()
    red_rgba = Gdk.RGBA()
    red_rgba.red = 1.0
    red_rgba.green = 0.0
    red_rgba.blue = 0.0
    red_rgba.alpha = 1.0
    color_btn.get_rgba.return_value = red_rgba
    window.color_button = color_btn

    window.inline_editor_widget = None

    window.on_text_format_changed()

    # Verify exactly 1 composite command in undo history
    assert len(window.undo_manager.undo_stack) == 1
    assert isinstance(window.undo_manager.undo_stack[0], CompositeCommand)

    # Verify 3 spans, mid span is red
    assert len(session.editable_texts) == 3
    pre_s, mid_s, post_s = session.editable_texts
    assert mid_s.text == "yazı"
    assert mid_s.color == (1.0, 0.0, 0.0)
    assert abs(post_s.bbox[0] - mid_s.bbox[2]) < 0.01


def test_already_isolated_word_styling_shifts_subsequent_spans():
    """Verify that toggling style on an already-split word shifts subsequent spans on the line."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    # Line consists of pre, mid, post as separate objects on the same line
    pre_s = EditableText(text="z ", x=50.0, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    pre_s.bbox = (50.0, 38.0, 58.5, 53.0)
    pre_s.baseline = 50.0

    mid_s = EditableText(text="yazı", x=58.5, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    mid_s.bbox = (58.5, 38.0, 78.5, 53.0)
    mid_s.baseline = 50.0

    post_s = EditableText(text=" ve sözlük", x=78.5, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    post_s.bbox = (78.5, 38.0, 140.0, 53.0)
    post_s.baseline = 50.0

    session.editable_texts = [pre_s, mid_s, post_s]

    window.selected_text = mid_s
    window.selected_word = "yazı"
    window.selected_word_start_char = 0
    window.selected_word_end_char = len(mid_s.text)
    window.word_selection_mode = True
    window.pending_format_change_obj = mid_s
    window.before_format_change_state = copy.deepcopy(mid_s.__dict__)

    # Toggle bold on mid_s
    window._toggle_word_style(mid_s, "bold")

    assert mid_s.is_bold is True
    # mid_s width changed, post_s should be shifted by dx
    assert abs(post_s.bbox[0] - mid_s.bbox[2]) < 0.01

    # Undo must restore both mid_s and post_s positions
    window.undo_manager.undo()
    assert mid_s.is_bold is False
    assert abs(mid_s.bbox[2] - 78.5) < 0.01
    assert abs(post_s.bbox[0] - 78.5) < 0.01


def test_undo_redo_reversibility_single_word_style():
    """Verify full undo/redo cleanly reverses single-word styling without phantoms."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    text_str = "z yazı ve sözlük"
    t = EditableText(text=text_str, x=50.0, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    t.bbox = (50.0, 38.0, 150.0, 53.0)
    session.editable_texts = [t]

    window.selected_text = t
    window.selected_word = "yazı"
    window.selected_word_start_char = 2
    window.selected_word_end_char = 6
    window.word_selection_mode = True
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    window._toggle_word_style(t, "bold")
    assert len(session.editable_texts) == 3

    # Undo
    window.undo_manager.undo()
    assert len(session.editable_texts) == 1
    assert session.editable_texts[0].text == text_str
    assert session.editable_texts[0].is_bold is False

    # Redo
    window.undo_manager.redo()
    assert len(session.editable_texts) == 3
    assert session.editable_texts[1].text == "yazı"
    assert session.editable_texts[1].is_bold is True


def test_full_text_format_changed_no_unbound_local_error():
    """Verify that formatting an entire text object (word_selection_mode=False) does not raise UnboundLocalError."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    t = EditableText(text="Complete line of text", x=50.0, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    t.bbox = (50.0, 38.0, 150.0, 53.0)
    session.editable_texts = [t]

    window.word_selection_mode = False
    window.selected_text = t
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    font_combo = MagicMock()
    font_combo.get_active.return_value = 0
    font_combo.get_active_iter.return_value = None
    font_combo.get_model.return_value = [["Liberation Sans"]]
    window.font_combo = font_combo

    font_size_spin = MagicMock()
    font_size_spin.get_value.return_value = 14.0
    window.font_size_spin = font_size_spin

    bold_btn = MagicMock()
    bold_btn.get_active.return_value = True
    window.bold_button = bold_btn

    italic_btn = MagicMock()
    italic_btn.get_active.return_value = False
    window.italic_button = italic_btn

    color_btn = MagicMock()
    blue_rgba = Gdk.RGBA()
    blue_rgba.red = 0.0
    blue_rgba.green = 0.0
    blue_rgba.blue = 1.0
    blue_rgba.alpha = 1.0
    color_btn.get_rgba.return_value = blue_rgba
    window.color_button = color_btn

    window.inline_editor_widget = None

    # This previously raised UnboundLocalError: cannot access local variable 'EditObjectCommand'
    window.on_text_format_changed()

    assert len(window.undo_manager.undo_stack) == 1
    assert isinstance(window.undo_manager.undo_stack[0], EditObjectCommand)
    assert t.font_size == 14.0
    assert t.is_bold is True
    assert t.color == (0.0, 0.0, 1.0)


def test_moved_text_single_word_hit_test_and_bbox():
    """Verify that moving a text object dynamically synchronizes char_boxes and word selection bbox."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    t = EditableText(text="Hello World", x=50.0, y=50.0, font_size=12.0, page_number=0)
    # Populate char_boxes at original location [50..120, 50..62]
    cbs = []
    cx = 50.0
    for idx, char in enumerate("Hello World"):
        w = 4.0 if char == ' ' else 7.0
        cbs.append({
            "char": char,
            "bbox": (cx, 50.0, cx + w, 62.0),
            "origin": (cx, 60.0),
            "index": idx
        })
        cx += w
    t.char_boxes = cbs
    t.bbox = (50.0, 50.0, cx, 62.0)
    session.editable_texts = [t]

    # Move text object by (100, 150)
    new_bbox = (150.0, 200.0, cx + 100.0, 212.0)
    t.bbox = new_bbox
    t.x, t.y = new_bbox[0], new_bbox[1]

    # Hit test at old location must fail, hit test at new location must succeed
    assert t.hit_test_char(55.0, 55.0) is None
    hit = t.hit_test_char(155.0, 205.0)
    assert hit is not None
    assert hit["char"] == "H"

    # Select word "World" (indices 6 to 11)
    window.selected_text = t
    window.selected_word = "World"
    window.selected_word_start_char = 6
    window.selected_word_end_char = 11
    window.word_selection_mode = True

    w_bbox = window.get_selected_word_bbox()
    assert w_bbox is not None
    # Word bbox must be at new moved location [>= 150.0, >= 200.0]
    assert w_bbox[0] >= 150.0
    assert w_bbox[1] >= 200.0
    assert w_bbox[3] <= 213.0

    # Split at range must produce spans at the new moved coordinates
    spans = t.split_at_range(6, 11)
    assert len(spans) == 2
    pre_span, mid_span = spans[0], spans[1]
    assert pre_span.bbox[0] == pytest.approx(150.0, abs=0.1)
    assert mid_span.bbox[1] == pytest.approx(200.0, abs=0.1)


def test_rotated_text_single_word_split_alignment():
    """Verify that splitting a rotated text object produces spans that align on the exact visual line."""
    import math
    doc = fitz.open()
    doc.new_page(width=500, height=500)

    for rot in [90.0, 180.0, 270.0]:
        t = EditableText(text="Rotated Paragraph Text", x=100.0, y=100.0, font_size=12.0, rotation=rot, page_number=0)
        cbs = []
        cx = 100.0
        for idx, char in enumerate("Rotated Paragraph Text"):
            w = 4.0 if char == ' ' else 7.0
            cbs.append({
                "char": char,
                "bbox": (cx, 100.0, cx + w, 114.0),
                "origin": (cx, 111.0),
                "index": idx
            })
            cx += w
        t.char_boxes = cbs
        t.bbox = (100.0, 100.0, cx, 114.0)

        p_cx = (t.bbox[0] + t.bbox[2]) / 2.0
        p_cy = (t.bbox[1] + t.bbox[3]) / 2.0

        # Split "Paragraph" (index 8 to 17)
        spans = t.split_at_range(8, 17, compensate_rotation=True)
        assert len(spans) == 3
        pre, mid, post = spans[0], spans[1], spans[2]
        assert pre.text == "Rotated "
        assert mid.text == "Paragraph"
        assert post.text == " Text"

        # Check visual position of characters in each span vs parent
        for span, start_idx in [(pre, 0), (mid, 8), (post, 17)]:
            s_cx = (span.bbox[0] + span.bbox[2]) / 2.0
            s_cy = (span.bbox[1] + span.bbox[3]) / 2.0
            for cb in span.char_boxes:
                char_idx = start_idx + cb["index"]
                orig_cb = t.char_boxes[char_idx]

                # Visual pos in parent
                pt_p = fitz.Point((orig_cb["bbox"][0] + orig_cb["bbox"][2]) / 2.0, (orig_cb["bbox"][1] + orig_cb["bbox"][3]) / 2.0)
                vis_p = (pt_p - fitz.Point(p_cx, p_cy)) * fitz.Matrix(rot) + fitz.Point(p_cx, p_cy)

                # Visual pos in span
                pt_s = fitz.Point((cb["bbox"][0] + cb["bbox"][2]) / 2.0, (cb["bbox"][1] + cb["bbox"][3]) / 2.0)
                vis_s = (pt_s - fitz.Point(s_cx, s_cy)) * fitz.Matrix(rot) + fitz.Point(s_cx, s_cy)

                diff = abs(vis_p.x - vis_s.x) + abs(vis_p.y - vis_s.y)
                assert diff < 0.05, f"Rot {rot} char {orig_cb['char']} misaligned by {diff} pt"


def test_rotation_handle_stalk_detection_for_editable_text():
    """Verify that _find_resize_handle_at_pos detects the rotation handle stalk for EditableText."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    t = EditableText(text="Hello", x=100.0, y=100.0, font_size=12.0, page_number=0)
    t.bbox = (100.0, 100.0, 150.0, 115.0)

    # Bind _find_resize_handle_at_pos
    window._find_resize_handle_at_pos = PdfEditorWindow._find_resize_handle_at_pos.__get__(window, PdfEditorWindow)
    window._visual_to_unrotated_page_coords = PdfEditorWindow._visual_to_unrotated_page_coords.__get__(window, PdfEditorWindow)
    window.zoom_level = 1.0
    window.current_pdf_page_width = 500
    window.current_pdf_page_height = 500
    window.pdf_view.get_allocated_width.return_value = 500
    window.pdf_view.get_allocated_height.return_value = 500

    # Rotation stalk is centered at x = (100 + 150) / 2 = 125, y = 100 - padding - 22 = 75
    # Hit testing at (125, 75)
    handle = window._find_resize_handle_at_pos(125.0, 75.0, t)
    assert handle == "rotate"


def test_single_word_rotation_isolates_only_that_word():
    """Verify that rotating a selected word isolates it and rotates ONLY that word, leaving the paragraph untouched."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    t = EditableText(text="KONU: ODEV PART-2", x=50.0, y=50.0, font_size=12.0, page_number=0)
    # Populate char boxes
    cbs = []
    cx = 50.0
    for idx, c in enumerate("KONU: ODEV PART-2"):
        w = 4.0 if c == ' ' else 7.0
        cbs.append({
            "char": c,
            "bbox": (cx, 50.0, cx + w, 64.0),
            "origin": (cx, 61.0),
            "index": idx
        })
        cx += w
    t.char_boxes = cbs
    t.bbox = (50.0, 50.0, cx, 64.0)
    session.editable_texts = [t]

    # Middle click selects "ODEV" (start_char=6, end_char=10)
    window.selected_text = t
    window.selected_word = "ODEV"
    window.selected_word_start_char = 6
    window.selected_word_end_char = 10
    window.word_selection_mode = True

    # User clicks rotate 90 degrees CW
    window.on_rotate_object_cw_clicked()

    # Original paragraph should be split into 3 spans: pre, mid, post
    assert len(session.editable_texts) == 3
    pre, mid, post = session.editable_texts
    assert pre.text == "KONU: "
    assert mid.text == "ODEV"
    assert post.text == " PART-2"

    # Crucial assertion: ONLY mid ("ODEV") is rotated 90 degrees!
    assert mid.rotation == 90.0
    # pre and post remain horizontal at 0 degrees!
    assert pre.rotation == 0.0
    assert post.rotation == 0.0

    # Undo must restore original un-rotated, un-split paragraph
    window.undo_manager.undo() # undoes rotation
    window.undo_manager.undo() # undoes split
    assert len(session.editable_texts) == 1
    assert session.editable_texts[0].text == "KONU: ODEV PART-2"
    assert session.editable_texts[0].rotation == 0.0


def test_single_word_selection_has_its_own_rotation_stalk():
    """Verify that in word_selection_mode, the rotation stalk handle is located right on the word's box."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    t = EditableText(text="KONU: ODEV PART-2", x=50.0, y=100.0, font_size=12.0, page_number=0)
    cbs = []
    cx = 50.0
    for idx, c in enumerate("KONU: ODEV PART-2"):
        w = 4.0 if c == ' ' else 8.0
        cbs.append({
            "char": c,
            "bbox": (cx, 100.0, cx + w, 115.0),
            "origin": (cx, 112.0),
            "index": idx
        })
        cx += w
    t.char_boxes = cbs
    t.bbox = (50.0, 100.0, cx, 115.0)

    # Word "ODEV" is indices 6 to 10:
    # 6 chars ("KONU: ") = 5*8 + 4 = 44 -> x from 94 to 94 + 4*8 = 126
    # Word center is ~110.0
    window.selected_text = t
    window.selected_word = "ODEV"
    window.selected_word_start_char = 6
    window.selected_word_end_char = 10
    window.word_selection_mode = True

    w_bbox = window.get_selected_word_bbox()
    assert w_bbox is not None
    word_cx = (w_bbox[0] + w_bbox[2]) / 2.0
    word_stalk_y = w_bbox[1] - 3.0 - 22.0 # rect_y - stalk_len

    window._find_resize_handle_at_pos = PdfEditorWindow._find_resize_handle_at_pos.__get__(window, PdfEditorWindow)
    window._visual_to_unrotated_page_coords = PdfEditorWindow._visual_to_unrotated_page_coords.__get__(window, PdfEditorWindow)
    window.zoom_level = 1.0
    window.current_pdf_page_width = 500
    window.current_pdf_page_height = 500
    window.pdf_view.get_allocated_width.return_value = 500
    window.pdf_view.get_allocated_height.return_value = 500

    # Test rotation handle at the word's stalk tip
    handle = window._find_resize_handle_at_pos(word_cx, word_stalk_y, t)
    assert handle == "rotate"

    # Far away from the word (e.g. above "KONU:") should NOT detect the word's rotation stalk
    handle_away = window._find_resize_handle_at_pos(60.0, word_stalk_y, t)
    assert handle_away is None


def test_page_change_preserves_rotated_object_and_cache():
    """Verify that rotating an object on a page preserves its rotation, bbox, and undo history across page changes."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    window._stash_page_objects = PdfEditorWindow._stash_page_objects.__get__(window, PdfEditorWindow)
    window._restore_page_objects = PdfEditorWindow._restore_page_objects.__get__(window, PdfEditorWindow)
    window._load_page = PdfEditorWindow._load_page.__get__(window, PdfEditorWindow)
    window._switch_active_page = PdfEditorWindow._switch_active_page.__get__(window, PdfEditorWindow)
    window.continuous_scroll = False
    window.pdf_scroll = MagicMock()
    window._sync_thumbnail_selection = MagicMock()
    window._sync_window_title_and_subtitle = MagicMock()
    window._create_form_field_overlays = MagicMock()
    window._clear_form_field_overlays = MagicMock()
    window.hide_text_editor = MagicMock()
    window.commit_pending_format_change = MagicMock()

    t = EditableText(text="Mühendisliği", x=100.0, y=100.0, font_size=12.0, page_number=0)
    t.bbox = (100.0, 100.0, 200.0, 120.0)
    t.original_bbox = t.bbox
    session.editable_texts = [t]
    window._page_objects_cache[0] = {
        'texts': [t],
        'images': [],
        'shapes': [],
        'strokes': [],
        'form_fields': []
    }

    # Rotate object to 90 degrees
    from word_sys_pdf_editor.undo_manager import RotateObjectCommand
    cmd = RotateObjectCommand(window, t, 0.0, 90.0)
    cmd.execute()
    window.undo_manager.add_command(cmd)

    assert t.rotation == 90.0
    assert t.bbox == (100.0, 100.0, 200.0, 120.0) # Unrotated bbox is intact
    assert len(window.undo_manager.undo_stack) == 1

    # Navigate to page 1
    window._load_page(1)
    assert window.current_page_index == 1
    # Undo stack must NOT be cleared on page change!
    assert len(window.undo_manager.undo_stack) == 1

    # Navigate back to page 0
    window._load_page(0)
    assert window.current_page_index == 0
    assert len(window.undo_manager.undo_stack) == 1
    assert len(session.editable_texts) == 1

    restored_text = session.editable_texts[0]
    assert restored_text.text == "Mühendisliği"
    assert restored_text.rotation == 90.0
    # Must retain original unrotated bbox (width=100, height=20), NOT revert or double-rotate
    assert restored_text.bbox == (100.0, 100.0, 200.0, 120.0)

    # Undo rotation across pages
    window.undo_manager.undo()
    assert restored_text.rotation == 0.0


def test_page_change_preserves_multiparagraph_textbox():
    """Verify that a single multi-paragraph text box is not split into separate boxes on page change."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    window._stash_page_objects = PdfEditorWindow._stash_page_objects.__get__(window, PdfEditorWindow)
    window._restore_page_objects = PdfEditorWindow._restore_page_objects.__get__(window, PdfEditorWindow)
    window._load_page = PdfEditorWindow._load_page.__get__(window, PdfEditorWindow)
    window.continuous_scroll = False
    window.pdf_scroll = MagicMock()
    window._sync_thumbnail_selection = MagicMock()
    window._sync_window_title_and_subtitle = MagicMock()
    window._create_form_field_overlays = MagicMock()
    window._clear_form_field_overlays = MagicMock()
    window.hide_text_editor = MagicMock()
    window.commit_pending_format_change = MagicMock()

    multi_text = "Paragraph 1: Intro\nParagraph 2: Body\nParagraph 3: Discussion\nParagraph 4: Conclusion"
    t = EditableText(text=multi_text, x=50.0, y=50.0, font_size=12.0, page_number=0)
    t.bbox = (50.0, 50.0, 350.0, 200.0)
    session.editable_texts = [t]
    window._page_objects_cache[0] = {
        'texts': [t],
        'images': [],
        'shapes': [],
        'strokes': [],
        'form_fields': []
    }

    # Switch to page 1
    window._load_page(1)
    assert window.current_page_index == 1

    # Switch back to page 0
    window._load_page(0)
    assert window.current_page_index == 0

    # Must still be exactly ONE EditableText object with all 4 paragraphs
    assert len(session.editable_texts) == 1
    assert session.editable_texts[0].text == multi_text


def test_extract_editable_text_unrotates_rotated_pdf_text():
    """Verify extract_editable_text accurately unrotates bounding box and char boxes for rotated PDF text."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    unrot_rect = fitz.Rect(100, 100, 250, 120)
    cx = (unrot_rect.x0 + unrot_rect.x1) / 2.0
    cy = (unrot_rect.y0 + unrot_rect.y1) / 2.0
    rot = 90.0
    morph = (fitz.Point(cx, cy), fitz.Matrix(-rot))
    page.insert_text(fitz.Point(100, 115), "Muhendisligi", fontsize=12, morph=morph)

    texts, err = pdf_handler.extract_editable_text(doc, 0)
    assert err is None
    assert len(texts) == 1

    t = texts[0]
    assert t.text == "Muhendisligi"
    assert t.rotation == 90.0

    # Unrotated width must be horizontal (width > height), NOT vertical (height > width)
    w = t.bbox[2] - t.bbox[0]
    h = t.bbox[3] - t.bbox[1]
    assert w > h
    assert 50.0 < w < 100.0
    assert 10.0 < h < 25.0


def test_multipage_undo_redo_automatic_navigation():
    """Verify that undoing/redoing commands on different pages automatically navigates to that page."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    window._stash_page_objects = PdfEditorWindow._stash_page_objects.__get__(window, PdfEditorWindow)
    window._restore_page_objects = PdfEditorWindow._restore_page_objects.__get__(window, PdfEditorWindow)
    window._load_page = PdfEditorWindow._load_page.__get__(window, PdfEditorWindow)
    window.continuous_scroll = False
    window.pdf_scroll = MagicMock()
    window._sync_thumbnail_selection = MagicMock()
    window._sync_window_title_and_subtitle = MagicMock()
    window._create_form_field_overlays = MagicMock()
    window._clear_form_field_overlays = MagicMock()
    window.hide_text_editor = MagicMock()
    window.commit_pending_format_change = MagicMock()

    from word_sys_pdf_editor.undo_manager import RotateObjectCommand

    # Page 0: object t0 rotated to 45 deg
    t0 = EditableText(text="Page0Text", x=100.0, y=100.0, font_size=12.0, page_number=0)
    t0.bbox = (100.0, 100.0, 200.0, 120.0)
    session.editable_texts = [t0]
    window._page_objects_cache[0] = {'texts': [t0], 'images': [], 'shapes': [], 'strokes': [], 'form_fields': []}

    cmd0 = RotateObjectCommand(window, t0, 0.0, 45.0)
    cmd0.execute()
    window.undo_manager.add_command(cmd0)
    assert t0.rotation == 45.0

    # Switch to Page 1: object t1 rotated to 90 deg
    window._load_page(1)
    assert window.current_page_index == 1

    t1 = EditableText(text="Page1Text", x=50.0, y=50.0, font_size=12.0, page_number=1)
    t1.bbox = (50.0, 50.0, 150.0, 70.0)
    session.editable_texts = [t1]
    window._page_objects_cache[1] = {'texts': [t1], 'images': [], 'shapes': [], 'strokes': [], 'form_fields': []}

    cmd1 = RotateObjectCommand(window, t1, 0.0, 90.0)
    cmd1.execute()
    window.undo_manager.add_command(cmd1)
    assert t1.rotation == 90.0

    # Undo 1: Reverts t1 on page 1
    window.undo_manager.undo()
    assert window.current_page_index == 1
    assert t1.rotation == 0.0

    # Undo 2: Must automatically navigate to page 0 and revert t0
    window.undo_manager.undo()
    assert window.current_page_index == 0
    assert t0.rotation == 0.0

    # Redo 1: Must re-apply rotation on page 0
    window.undo_manager.redo()
    assert window.current_page_index == 0
    assert t0.rotation == 45.0

    # Redo 2: Must automatically navigate to page 1 and re-apply rotation on page 1
    window.undo_manager.redo()
    assert window.current_page_index == 1
    assert t1.rotation == 90.0


def test_rotated_shape_persists_across_page_change():
    """Verify that an EditableShape with rotation retains its angle and bounds when switching pages."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    window._stash_page_objects = PdfEditorWindow._stash_page_objects.__get__(window, PdfEditorWindow)
    window._restore_page_objects = PdfEditorWindow._restore_page_objects.__get__(window, PdfEditorWindow)
    window._load_page = PdfEditorWindow._load_page.__get__(window, PdfEditorWindow)
    window.continuous_scroll = False
    window.pdf_scroll = MagicMock()
    window._sync_thumbnail_selection = MagicMock()
    window._sync_window_title_and_subtitle = MagicMock()
    window._create_form_field_overlays = MagicMock()
    window._clear_form_field_overlays = MagicMock()
    window.hide_text_editor = MagicMock()
    window.commit_pending_format_change = MagicMock()

    from word_sys_pdf_editor.models import EditableShape
    from word_sys_pdf_editor.undo_manager import RotateObjectCommand

    shape = EditableShape(bbox=(100.0, 100.0, 200.0, 200.0), page_number=0, shape_type=EditableShape.SHAPE_RECTANGLE)
    shape.original_bbox = shape.bbox
    session.editable_shapes = [shape]
    window._page_objects_cache[0] = {'texts': [], 'images': [], 'shapes': [shape], 'strokes': [], 'form_fields': []}

    cmd = RotateObjectCommand(window, shape, 0.0, 45.0)
    cmd.execute()
    window.undo_manager.add_command(cmd)
    assert shape.rotation == 45.0

    # Switch to page 1
    window._load_page(1)
    assert window.current_page_index == 1

    # Switch back to page 0
    window._load_page(0)
    assert window.current_page_index == 0

    assert len(session.editable_shapes) == 1
    restored_shape = session.editable_shapes[0]
    assert restored_shape.rotation == 45.0
    assert restored_shape.bbox == (100.0, 100.0, 200.0, 200.0)


def test_multipage_rotate_page_change_undo_redo_and_save(tmp_path):
    """End-to-end test: rotate on page 0, navigate pages, undo/redo across pages, save, and reopen."""
    orig_path = str(tmp_path / "orig.pdf")
    saved_path = str(tmp_path / "saved.pdf")

    doc = fitz.open()
    p0 = doc.new_page(width=500, height=400)
    p0.insert_text(fitz.Point(100, 100), "Hello Page Zero", fontsize=14)
    p1 = doc.new_page(width=500, height=400)
    p1.insert_text(fitz.Point(100, 100), "Hello Page One", fontsize=14)
    doc.save(orig_path)
    doc.close()

    win = PdfEditorWindow()
    loaded, err = pdf_handler.load_pdf_document(orig_path)
    win._finish_loading(loaded, None, orig_path, 0, win._active_session)

    assert len(win.editable_texts) == 1
    obj = win.editable_texts[0]
    assert obj.rotation == 0.0

    from word_sys_pdf_editor.undo_manager import RotateObjectCommand
    cmd = RotateObjectCommand(win, obj, 0.0, 90.0)
    cmd.execute()
    win.undo_manager.add_command(cmd)
    assert obj.rotation == 90.0

    # Switch to page 1
    win._load_page(1)
    assert win.current_page_index == 1
    assert len(win.editable_texts) == 1
    assert win.editable_texts[0].text == "Hello Page One"

    # Switch back to page 0
    win._load_page(0)
    assert win.current_page_index == 0
    assert len(win.editable_texts) == 1
    restored_obj = win.editable_texts[0]
    assert restored_obj.rotation == 90.0

    # Switch to page 1 and undo
    win._load_page(1)
    assert win.current_page_index == 1
    win.undo_manager.undo()
    assert win.current_page_index == 0
    assert win.editable_texts[0].rotation == 0.0

    # Redo
    win.undo_manager.redo()
    assert win.current_page_index == 0
    assert win.editable_texts[0].rotation == 90.0

    # Save document
    win.save_document(saved_path)

    # Reopen saved document fresh
    win2 = PdfEditorWindow()
    loaded2, err2 = pdf_handler.load_pdf_document(saved_path)
    win2._finish_loading(loaded2, None, saved_path, 0, win2._active_session)

    assert len(win2.editable_texts) == 1
    reopened_obj = win2.editable_texts[0]
    assert reopened_obj.text == "Hello Page Zero"
    assert reopened_obj.rotation == 90.0







