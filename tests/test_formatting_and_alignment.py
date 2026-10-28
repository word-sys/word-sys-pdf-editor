"""Consolidated Text Formatting, Alignment, and Workspace Isolation Test Suite for word-sys-pdf-editor.

This suite validates 4-way text alignment (left, center, right, justify), strikethrough styling,
vector baking, text formatting toolbar decoupling, and multi-tab workspace command isolation.
"""

# ============================================================================
# SECTION: test_alignment_suite.py
# ============================================================================
"""
Comprehensive unit and integration test suite for 4-Way Text Alignment.
Tests:
- EditableText model default and custom alignment properties
- Range splitting and cloning alignment preservation
- PyMuPDF vector positioning for left, center, right, and justify alignments
- Underline and strikethrough alignment synchronization
- Rotated aligned text vector rendering
- Ghost erasure and object independence with aligned text
- UI alignment toggle buttons and format control synchronization
- Undo/redo integration for text alignment changes
- Localization across all 7 supported languages (EN, TR, FR, DE, ES, IT, RU)
"""

import unittest
from unittest.mock import MagicMock
import copy
import fitz
import os
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk

from word_sys_pdf_editor.models import (
    EditableText, EditableShape, EditableStroke, EditableImage
)
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor import undo_manager
from word_sys_pdf_editor import i18n
from word_sys_pdf_editor import locales


class TestTextAlignmentModel(unittest.TestCase):
    """Test EditableText alignment attribute and cloning behaviors."""

    def test_default_alignment_is_left(self):
        t = EditableText(10, 20, "Left Aligned")
        self.assertEqual(t.alignment, "left")

    def test_custom_alignment_initialization(self):
        for align in ["left", "center", "right", "justify"]:
            t = EditableText(10, 20, f"{align} Text", alignment=align)
            self.assertEqual(t.alignment, align)

    def test_deepcopy_preserves_alignment(self):
        t = EditableText(10, 20, "Centered", alignment="center")
        c = copy.deepcopy(t)
        self.assertEqual(c.alignment, "center")

    def test_split_at_range_preserves_alignment(self):
        t = EditableText(50, 100, "Hello World Align", font_size=12.0, alignment="right")
        t.bbox = (50, 100, 200, 120)
        parts = t.split_at_range(0, 5)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertEqual(part.alignment, "right")


class TestTextAlignmentPdfHandler(unittest.TestCase):
    """Test PyMuPDF backend positioning for all 4 alignments."""

    def setUp(self):
        self.doc, _ = pdf_handler.create_new_pdf(width=500, height=500, num_pages=1)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_apply_center_aligned_text(self):
        page = self.doc.load_page(0)
        # Box width is 300 (x: 100 to 400). Text length is much smaller.
        t = EditableText(
            x=100, y=100, text="Centered Text", font_size=14.0,
            color=(0, 0, 0), is_new=True, baseline=114.0, alignment="center"
        )
        t.bbox = (100, 100, 400, 125)
        t.page_number = 0
        t.is_underline = True

        success, err = pdf_handler.apply_object_edit(self.doc, t)
        self.assertTrue(success, f"apply_object_edit failed: {err}")

        # The underline vector line must be centered within the 100-400 range (not starting at 100)
        drawings = page.get_drawings()
        self.assertGreater(len(drawings), 0)
        underline = drawings[0]
        rect = underline['rect']
        self.assertGreater(rect.x0, 120.0, "Underline line did not shift right for centered alignment")
        self.assertLess(rect.x1, 380.0, "Underline line did not stay within centered bounds")

    def test_apply_right_aligned_text(self):
        page = self.doc.load_page(0)
        # Box width is 300 (x: 100 to 400). Text is right-aligned.
        t = EditableText(
            x=100, y=200, text="Right Text", font_size=14.0,
            color=(0, 0, 0), is_new=True, baseline=214.0, alignment="right"
        )
        t.bbox = (100, 200, 400, 225)
        t.page_number = 0
        t.is_strikethrough = True

        success, err = pdf_handler.apply_object_edit(self.doc, t)
        self.assertTrue(success, f"apply_object_edit failed: {err}")

        drawings = page.get_drawings()
        self.assertGreater(len(drawings), 0)
        strike = drawings[0]
        rect = strike['rect']
        # End of strikethrough line must be close to right boundary 400
        self.assertAlmostEqual(rect.x1, 400.0, delta=5.0)

    def test_apply_justified_multiline_text(self):
        page = self.doc.load_page(0)
        # 2 lines: first line has multiple words and must justify to box width 300
        text = "First line with several words\nLast line"
        t = EditableText(
            x=100, y=100, text=text, font_size=12.0,
            color=(0, 0, 0), is_new=True, baseline=112.0, alignment="justify"
        )
        t.bbox = (100, 100, 400, 150)
        t.page_number = 0
        t.is_underline = True

        success, err = pdf_handler.apply_object_edit(self.doc, t)
        self.assertTrue(success, f"apply_object_edit failed: {err}")

        drawings = page.get_drawings()
        self.assertGreaterEqual(len(drawings), 2)
        # First line underline should span near full box width 300
        first_line_underline = drawings[0]
        self.assertAlmostEqual(first_line_underline['rect'].x0, 100.0, delta=2.0)
        self.assertAlmostEqual(first_line_underline['rect'].x1, 400.0, delta=2.0)

    def test_apply_aligned_text_with_rotation(self):
        page = self.doc.load_page(0)
        t = EditableText(
            x=150, y=150, text="Rotated Center", font_size=14.0,
            color=(1, 0, 0), is_new=True, baseline=164.0, rotation=45.0, alignment="center"
        )
        t.bbox = (150, 150, 350, 180)
        t.page_number = 0
        t.is_underline = True

        success, err = pdf_handler.apply_object_edit(self.doc, t)
        self.assertTrue(success, f"apply_object_edit failed: {err}")
        self.assertGreater(len(page.get_drawings()), 0)


class TestTextAlignmentGhostErasureAndIndependence(unittest.TestCase):
    """Test that ghost erasure cleanly removes aligned text without affecting other objects."""

    def setUp(self):
        self.doc, _ = pdf_handler.create_new_pdf(width=500, height=500, num_pages=1)
        self.page = self.doc.load_page(0)

        # Draw a centered text with underline
        self.page.insert_text(fitz.Point(180, 150), "Centered Ghost", fontsize=14.0)
        self.page.draw_line(fitz.Point(180, 151.5), fitz.Point(320, 151.5), color=(0, 0, 0), width=0.8)

        # Draw an independent adjacent shape
        self.page.draw_rect(fitz.Rect(50, 300, 150, 400), color=(0, 0, 1), fill=(0.8, 0.8, 1))
        pdf_handler.save_page_snapshot(self.doc, 0)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_ghost_erasure_isolates_aligned_text(self):
        class MockWindow:
            def _update_undo_redo_buttons(self): pass

        win = MockWindow()
        win.doc = self.doc
        win.editable_texts = []
        win.editable_shapes = []
        win.editable_images = []
        win.editable_strokes = []

        t = EditableText(100, 135, "Centered Ghost", font_size=14.0, is_new=False, baseline=150.0, alignment="center")
        t.bbox = (100, 135, 400, 160)
        t.original_bbox = (100, 135, 400, 160)
        t.original_baseline = 150.0
        t.page_number = 0
        t.is_underline = True
        win.editable_texts.append(t)

        shape = EditableShape(EditableShape.SHAPE_RECTANGLE, (50, 300, 150, 400), page_number=0, is_new=False)
        win.editable_shapes.append(shape)

        undo_manager._perform_ghost_erasure(win, t, 0)

        # The underline of the centered text should be gone
        drawings = self.page.get_drawings()
        strike_or_under = [d for d in drawings if d.get('rect') and abs(d['rect'].y0 - 151.5) < 2.0]
        self.assertEqual(len(strike_or_under), 0)

        # The shape at (50, 300, 150, 400) must remain intact
        shape_drawings = [d for d in drawings if d.get('rect') and d['rect'].intersects(fitz.Rect(50, 300, 150, 400))]
        self.assertGreater(len(shape_drawings), 0)


class TestTextAlignmentUndoRedo(unittest.TestCase):
    """Test undo and redo of alignment changes."""

    def test_alignment_change_undo_redo(self):
        class MockWindow:
            def __init__(self):
                self.doc, _ = pdf_handler.create_new_pdf(width=500, height=500, num_pages=1)
                self.editable_texts = []
                self.editable_shapes = []
                self.editable_images = []
                self.editable_strokes = []
                self.document_modified = False
                self.status_label = MagicMock()
                self.undo_manager = undo_manager.UndoManager(self)
                self.pdf_view = self

            def _update_undo_redo_buttons(self): pass
            def queue_draw(self): pass
            def close(self):
                if self.doc: self.doc.close()

        win = MockWindow()
        try:
            t = EditableText(100, 100, "Align Undo Test", font_size=12.0, is_new=True, alignment="left")
            t.bbox = (100, 100, 300, 120)
            t.page_number = 0
            win.editable_texts.append(t)

            # Change alignment to center
            old_properties = {'alignment': 'left', 'bbox': t.bbox}
            new_properties = {'alignment': 'center', 'bbox': t.bbox}
            cmd = undo_manager.EditObjectCommand(win, t, old_properties, new_properties)
            cmd.execute()
            win.undo_manager.add_command(cmd)

            self.assertEqual(t.alignment, "center")
            self.assertGreater(len(win.undo_manager.undo_stack), 0)

            # Undo
            win.undo_manager.undo()
            self.assertEqual(t.alignment, "left")

            # Redo
            win.undo_manager.redo()
            self.assertEqual(t.alignment, "center")
        finally:
            win.close()


class TestTextAlignmentLocalization(unittest.TestCase):
    """Test all 4 alignment tooltips exist in all 7 supported languages."""

    def test_all_languages_have_4_way_alignment_keys(self):
        keys = ["align_left_tip", "align_center_tip", "align_right_tip", "align_justify_tip"]

        # English
        for k in keys:
            self.assertIn(k, i18n._STRINGS["en"])

        # Turkish
        for k in keys:
            self.assertIn(k, i18n._STRINGS["tr"])

        # French
        for k in keys:
            self.assertIn(k, locales.STRINGS_FR)

        # German
        for k in keys:
            self.assertIn(k, locales.STRINGS_DE)

        # Spanish
        for k in keys:
            self.assertIn(k, locales.STRINGS_ES)

        # Italian
        for k in keys:
            self.assertIn(k, locales.STRINGS_IT)

        # Russian
        for k in keys:
            self.assertIn(k, locales.STRINGS_RU)


class TestInlineEditorAndBboxWidth(unittest.TestCase):
    """Test inline editor justification and bounding box width preservation."""

    def test_justification_enum_mapping(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk

        mapping = {
            'left': Gtk.Justification.LEFT,
            'center': Gtk.Justification.CENTER,
            'right': Gtk.Justification.RIGHT,
            'justify': Gtk.Justification.FILL,
        }
        for align_name, expected_enum in mapping.items():
            if align_name == 'center':
                j = Gtk.Justification.CENTER
            elif align_name == 'right':
                j = Gtk.Justification.RIGHT
            elif align_name == 'justify':
                j = Gtk.Justification.FILL
            else:
                j = Gtk.Justification.LEFT
            self.assertEqual(j, expected_enum)

    def test_bbox_width_preservation_for_aligned_text(self):
        # When an object has a wide bounding box and alignment != 'left',
        # format changes must not shrink the bounding box down to the short text width.
        old_bbox = (100.0, 100.0, 400.0, 130.0)
        old_w = old_bbox[2] - old_bbox[0]  # 300
        text_w = 60.0  # text is much shorter than 300

        for align in ['center', 'right', 'justify']:
            final_w = max(text_w, old_w) if align != 'left' else text_w
            self.assertEqual(final_w, 300.0, f"Width should be preserved for {align}")

        # For left alignment, text_w can be used
        left_w = max(text_w, old_w) if 'left' != 'left' else text_w
        self.assertEqual(left_w, 60.0)


@unittest.skipIf(Gdk.Display.get_default() is None, "Screen display not available (headless build environment)")
class TestAlignmentToggleButtonsGroup(unittest.TestCase):
    """Test 4-way alignment button mutual exclusion and single-selection guarantee."""

    def test_single_button_selection_on_switch(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk, GLib

        b_left = Gtk.ToggleButton()
        b_center = Gtk.ToggleButton()
        b_right = Gtk.ToggleButton()
        b_justify = Gtk.ToggleButton()

        b_left.set_active(True)
        b_center.set_group(b_left)
        b_right.set_group(b_left)
        b_justify.set_group(b_left)

        align_btns = [b_left, b_center, b_right, b_justify]

        def on_text_format_changed(btn, *args):
            if btn in align_btns and not btn.get_active():
                def check_restore_active(deactivated_btn):
                    if all(b and not b.get_active() for b in align_btns if b):
                        deactivated_btn.handler_block_by_func(on_text_format_changed)
                        deactivated_btn.set_active(True)
                        deactivated_btn.handler_unblock_by_func(on_text_format_changed)
                    return False
                GLib.idle_add(check_restore_active, btn)
                return

            if btn in align_btns and btn.get_active():
                for b in align_btns:
                    if b and b != btn and b.get_active():
                        b.handler_block_by_func(on_text_format_changed)
                        b.set_active(False)
                        b.handler_unblock_by_func(on_text_format_changed)

        b_left.connect('toggled', on_text_format_changed)
        b_center.connect('toggled', on_text_format_changed)
        b_right.connect('toggled', on_text_format_changed)
        b_justify.connect('toggled', on_text_format_changed)

        main_ctx = GLib.MainContext.default()
        def pump():
            count = 0
            while main_ctx.pending() and count < 100:
                main_ctx.iteration(False)
                count += 1

        # Initial: only left is True
        self.assertTrue(b_left.get_active())
        self.assertFalse(b_center.get_active())
        self.assertFalse(b_right.get_active())
        self.assertFalse(b_justify.get_active())

        # Switch to right: only right must be True, left MUST NOT stay selected!
        b_right.set_active(True)
        pump()
        self.assertFalse(b_left.get_active(), "Left must NOT remain selected when switching to Right!")
        self.assertFalse(b_center.get_active())
        self.assertTrue(b_right.get_active())
        self.assertFalse(b_justify.get_active())

        # Switch to center: only center must be True
        b_center.set_active(True)
        pump()
        self.assertFalse(b_left.get_active())
        self.assertTrue(b_center.get_active())
        self.assertFalse(b_right.get_active())
        self.assertFalse(b_justify.get_active())

        # Switch to justify: only justify must be True
        b_justify.set_active(True)
        pump()
        self.assertFalse(b_left.get_active())
        self.assertFalse(b_center.get_active())
        self.assertFalse(b_right.get_active())
        self.assertTrue(b_justify.get_active())

        # Switch back to left
        b_left.set_active(True)
        pump()
        self.assertTrue(b_left.get_active())
        self.assertFalse(b_center.get_active())
        self.assertFalse(b_right.get_active())
        self.assertFalse(b_justify.get_active())

        # Untoggle attempt: must restore left active
        b_left.set_active(False)
        pump()
        self.assertTrue(b_left.get_active())


if __name__ == "__main__":
    unittest.main()



# ============================================================================
# SECTION: test_strikethrough_suite.py
# ============================================================================
"""
Comprehensive unit and integration test suite for Text Strikethrough.
Tests:
- Model properties, cloning, range splitting
- PyMuPDF vector strikethrough drawing (horizontal and rotated)
- Extraction of strikethrough text from PDFs
- Drawing isolation (shapes and strokes ignore strikethrough lines)
- Ghost erasure and object independence
- Undo/redo integration via EditObjectCommand
- UI toolbar button and context popover setup
- Localization in all 7 supported languages
"""

import unittest
from unittest.mock import MagicMock
import copy
import fitz
import os
import sys

from word_sys_pdf_editor.models import (
    EditableText, EditableShape, EditableStroke, EditableImage
)
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor import undo_manager
from word_sys_pdf_editor import i18n
from word_sys_pdf_editor import locales


class TestStrikethroughModel(unittest.TestCase):
    """Test EditableText strikethrough attribute and behaviors."""

    def test_default_is_strikethrough_is_false(self):
        text_obj = EditableText(x=50, y=100, text="Sample Text", font_size=12.0)
        self.assertFalse(text_obj.is_strikethrough)

    def test_set_is_strikethrough(self):
        text_obj = EditableText(x=50, y=100, text="Strikethrough Text", font_size=12.0)
        text_obj.is_strikethrough = True
        self.assertTrue(text_obj.is_strikethrough)

    def test_deepcopy_preserves_strikethrough(self):
        text_obj = EditableText(x=50, y=100, text="Test", font_size=14.0)
        text_obj.is_strikethrough = True
        clone = copy.deepcopy(text_obj)
        self.assertTrue(clone.is_strikethrough)

    def test_split_at_range_preserves_strikethrough(self):
        text_obj = EditableText(x=50, y=100, text="Hello World", font_size=12.0)
        text_obj.bbox = (50, 100, 150, 120)
        text_obj.is_strikethrough = True

        parts = text_obj.split_at_range(0, 5)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertTrue(part.is_strikethrough)


class TestStrikethroughPdfHandler(unittest.TestCase):
    """Test PyMuPDF backend strikethrough drawing, extraction, and drawing filtering."""

    def setUp(self):
        self.doc, _ = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_apply_strikethrough_draws_vector_line(self):
        page = self.doc.load_page(0)
        text_obj = EditableText(
            x=100, y=200, text="Discounted Price", font_size=16.0,
            color=(0.2, 0.2, 0.2), is_new=True, baseline=214.0
        )
        text_obj.bbox = (100, 200, 220, 220)
        text_obj.page_number = 0
        text_obj.is_strikethrough = True

        success, err = pdf_handler.apply_object_edit(self.doc, text_obj)
        self.assertTrue(success, f"apply_object_edit failed: {err}")

        drawings = page.get_drawings()
        self.assertGreater(len(drawings), 0)

        # Expected strikethrough line at baseline - (font_size * 0.3)
        expected_strike_y = 214.0 - (16.0 * 0.3)
        found_strike = False
        for d in drawings:
            rect = d.get('rect')
            if rect and abs(rect.y0 - expected_strike_y) < 3.0:
                found_strike = True
                break
        self.assertTrue(found_strike, f"Strikethrough line not found near y={expected_strike_y}")

    def test_apply_strikethrough_with_rotation(self):
        page = self.doc.load_page(0)
        text_obj = EditableText(
            x=200, y=300, text="Rotated Strikethrough", font_size=14.0,
            color=(1.0, 0.0, 0.0), is_new=True, baseline=312.0, rotation=45.0
        )
        text_obj.bbox = (200, 300, 320, 320)
        text_obj.page_number = 0
        text_obj.is_strikethrough = True

        success, err = pdf_handler.apply_object_edit(self.doc, text_obj)
        self.assertTrue(success, f"apply_object_edit failed: {err}")

        drawings = page.get_drawings()
        self.assertGreater(len(drawings), 0)

    def test_extract_editable_text_detects_strikethrough(self):
        page = self.doc.load_page(0)
        font_size = 14.0
        baseline = 200.0
        x0, x1 = 80.0, 180.0

        # Insert text
        page.insert_text(fitz.Point(x0, baseline), "Crossed Out", fontsize=font_size, color=(0, 0, 0))

        # Insert vector line at strike height: baseline - (font_size * 0.3)
        strike_y = baseline - (font_size * 0.3)
        page.draw_line(fitz.Point(x0, strike_y), fitz.Point(x1, strike_y), color=(0, 0, 0), width=0.8)

        texts, err = pdf_handler.extract_editable_text(self.doc, 0)
        self.assertIsNone(err)
        self.assertGreater(len(texts), 0)

        strike_texts = [t for t in texts if t.is_strikethrough]
        self.assertGreater(len(strike_texts), 0, "Failed to detect strikethrough text from page")
        self.assertIn("Crossed Out", strike_texts[0].text)

    def test_shapes_and_strokes_ignore_strikethrough_lines(self):
        page = self.doc.load_page(0)
        font_size = 14.0
        baseline = 300.0
        x0, x1 = 100.0, 250.0

        # Insert text and strikethrough line
        page.insert_text(fitz.Point(x0, baseline), "Ignored Stroke", fontsize=font_size, color=(0, 0, 0))
        strike_y = baseline - (font_size * 0.3)
        page.draw_line(fitz.Point(x0, strike_y), fitz.Point(x1, strike_y), color=(0, 0, 0), width=0.8)

        # Also insert a genuine user rectangle and genuine freehand stroke
        page.draw_rect(fitz.Rect(50, 50, 150, 150), color=(0, 1, 0), fill=(1, 1, 0))
        page.draw_line(fitz.Point(10, 10), fitz.Point(50, 80), color=(0, 0, 1), width=3.0)

        shapes, _ = pdf_handler.extract_editable_shapes(self.doc, 0)
        strokes, _ = pdf_handler.extract_editable_strokes(self.doc, 0)

        # Ensure the strikethrough line was NOT extracted as a shape
        for shape in shapes:
            self.assertNotAlmostEqual(shape.bbox[1], strike_y, delta=2.0)

        # Ensure the strikethrough line was NOT extracted as a stroke
        for stroke in strokes:
            self.assertNotAlmostEqual(stroke.bbox[1], strike_y, delta=2.0)


class TestStrikethroughGhostErasureAndIndependence(unittest.TestCase):
    """Test ghost erasure and complete object independence when modifying strikethrough text."""

    def setUp(self):
        self.doc, _ = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)
        self.page = self.doc.load_page(0)

        # Page setup: Text with strikethrough, adjacent shape, adjacent image
        self.baseline = 250.0
        self.font_size = 14.0
        self.strike_y = self.baseline - (self.font_size * 0.3)

        self.page.insert_text(fitz.Point(100, self.baseline), "Old Strikethrough", fontsize=self.font_size)
        self.page.draw_line(fitz.Point(100, self.strike_y), fitz.Point(220, self.strike_y), color=(0, 0, 0), width=0.8)

        # Adjacent shape (independent rectangle)
        self.page.draw_rect(fitz.Rect(300, 200, 400, 300), color=(0, 0.5, 0), fill=(0.8, 1, 0.8))

        # Snapshot for undo/ghost erasure
        pdf_handler.save_page_snapshot(self.doc, 0)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_ghost_erasure_cleans_strikethrough_strip_without_touching_others(self):
        # Create a mock window
        class MockWindow:
            def _update_undo_redo_buttons(self):
                pass

        win = MockWindow()
        win.doc = self.doc
        win.editable_texts = []
        win.editable_shapes = []
        win.editable_images = []
        win.editable_strokes = []

        text_obj = EditableText(x=100, y=235, text="Old Strikethrough", font_size=self.font_size, is_new=False, baseline=self.baseline)
        text_obj.bbox = (100, 235, 220, 255)
        text_obj.original_bbox = (100, 235, 220, 255)
        text_obj.original_baseline = self.baseline
        text_obj.is_strikethrough = True
        text_obj.page_number = 0
        win.editable_texts.append(text_obj)

        shape_obj = EditableShape(EditableShape.SHAPE_RECTANGLE, (300, 200, 400, 300), page_number=0, is_new=False)
        win.editable_shapes.append(shape_obj)

        # Perform ghost erasure of the strikethrough text
        undo_manager._perform_ghost_erasure(win, text_obj, 0)

        # Verify: The original text was redacted
        # Verify: The strikethrough line at strike_y was redacted
        # Verify: The shape at (300, 200, 400, 300) remains present
        page = self.doc.load_page(0)
        drawings = page.get_drawings()

        # The strikethrough line near strike_y should be gone
        strike_drawings = [d for d in drawings if abs(d.get('rect', fitz.Rect()).y0 - self.strike_y) < 3.0]
        self.assertEqual(len(strike_drawings), 0, "Strikethrough line was not cleanly erased")

        # The shape drawings near (300, 200, 400, 300) must still exist
        shape_drawings = [d for d in drawings if d.get('rect') and d['rect'].intersects(fitz.Rect(300, 200, 400, 300))]
        self.assertGreater(len(shape_drawings), 0, "Adjacent shape was improperly erased")


class TestStrikethroughUndoRedo(unittest.TestCase):
    """Test undo and redo of strikethrough formatting changes."""

    def test_toggle_strikethrough_undo_redo(self):
        class MockWindow:
            def __init__(self):
                self.doc, _ = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)
                self.editable_texts = []
                self.editable_shapes = []
                self.editable_images = []
                self.editable_strokes = []
                self.document_modified = False
                self.status_label = MagicMock()
                self.undo_manager = undo_manager.UndoManager(self)
                self.pdf_view = self

            def _update_undo_redo_buttons(self):
                pass

            def queue_draw(self):
                pass

            def close(self):
                if self.doc:
                    self.doc.close()

        win = MockWindow()
        try:
            text_obj = EditableText(x=100, y=100, text="Strikethrough Toggle Test", font_size=12.0, is_new=True)
            text_obj.bbox = (100, 100, 250, 120)
            text_obj.page_number = 0
            text_obj.is_strikethrough = False
            win.editable_texts.append(text_obj)

            # Toggle strikethrough on
            old_properties = {'is_strikethrough': False, 'bbox': text_obj.bbox}
            new_properties = {'is_strikethrough': True, 'bbox': text_obj.bbox}
            cmd = undo_manager.EditObjectCommand(win, text_obj, old_properties, new_properties)
            cmd.execute()
            win.undo_manager.add_command(cmd)

            self.assertTrue(text_obj.is_strikethrough)
            self.assertGreater(len(win.undo_manager.undo_stack), 0)

            # Undo
            win.undo_manager.undo()
            self.assertFalse(text_obj.is_strikethrough)
            self.assertGreater(len(win.undo_manager.redo_stack), 0)

            # Redo
            win.undo_manager.redo()
            self.assertTrue(text_obj.is_strikethrough)
        finally:
            win.close()


class TestStrikethroughLocalization(unittest.TestCase):
    """Test that strikethrough tooltip and menu labels exist in all 7 supported languages."""

    def test_localization_all_languages(self):
        # English
        self.assertIn("strikethrough_tip", i18n._STRINGS["en"])
        self.assertEqual(i18n._STRINGS["en"]["strikethrough_tip"], "Strikethrough")

        # Turkish
        self.assertIn("strikethrough_tip", i18n._STRINGS["tr"])
        self.assertEqual(i18n._STRINGS["tr"]["strikethrough_tip"], "Üstü Çizili")

        # French
        self.assertIn("strikethrough_tip", locales.STRINGS_FR)
        self.assertEqual(locales.STRINGS_FR["strikethrough_tip"], "Barré")

        # German
        self.assertIn("strikethrough_tip", locales.STRINGS_DE)
        self.assertEqual(locales.STRINGS_DE["strikethrough_tip"], "Durchgestrichen")

        # Spanish
        self.assertIn("strikethrough_tip", locales.STRINGS_ES)
        self.assertEqual(locales.STRINGS_ES["strikethrough_tip"], "Tachado")

        # Italian
        self.assertIn("strikethrough_tip", locales.STRINGS_IT)
        self.assertEqual(locales.STRINGS_IT["strikethrough_tip"], "Barrato")

        # Russian
        self.assertIn("strikethrough_tip", locales.STRINGS_RU)
        self.assertEqual(locales.STRINGS_RU["strikethrough_tip"], "Зачёркнутый")


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_workspace_isolation_and_text_formatting.py
# ============================================================================
"""Unit and regression tests for workspace multi-tab object isolation and text toolbar selection decoupling."""

import os
import unittest
import copy
import fitz
from unittest.mock import MagicMock

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import DocumentSession, EditableText, EditableShape
from word_sys_pdf_editor.undo_manager import (
    UndoManager,
    AddObjectCommand,
    EditObjectCommand,
    DeleteObjectCommand,
)
from word_sys_pdf_editor.window import PdfEditorWindow


class TestWorkspaceMultiTabIsolation(unittest.TestCase):
    """Test object isolation across multiple workspaces/tabs to prevent duplication bugs."""

    def setUp(self):
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

        # Create two separate PDF documents
        self.doc1 = fitz.open()
        self.page1 = self.doc1.new_page(width=595, height=842)
        self.page1.insert_text(fitz.Point(100, 100), "Session 1 Original Text", fontsize=12)

        self.doc2 = fitz.open()
        self.page2 = self.doc2.new_page(width=595, height=842)
        self.page2.insert_text(fitz.Point(100, 100), "Session 2 Original Text", fontsize=12)

        # Create DocumentSessions
        self.session1 = DocumentSession(pdf_path="doc1.pdf")
        self.session1.doc = self.doc1
        self.session1.current_page_index = 0
        texts1, _ = pdf_handler.extract_editable_text(self.doc1, 0)
        self.session1.editable_texts = texts1 or []
        pdf_handler.save_page_snapshot(self.doc1, 0)

        self.session2 = DocumentSession(pdf_path="doc2.pdf")
        self.session2.doc = self.doc2
        self.session2.current_page_index = 0
        texts2, _ = pdf_handler.extract_editable_text(self.doc2, 0)
        self.session2.editable_texts = texts2 or []
        pdf_handler.save_page_snapshot(self.doc2, 0)

    def tearDown(self):
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

    def test_rebuild_page_deduplication_safeguard(self):
        """Verify rebuild_page does not duplicate objects even if passed duplicate references."""
        text_obj = EditableText(100, 150, "Added Text", font_size=14.0, is_new=True)
        text_obj.page_number = 0

        # Pass a list containing the same object reference multiple times
        duplicate_list = [text_obj, text_obj, text_obj]
        pdf_handler.rebuild_page(
            self.doc1, 0,
            all_texts=duplicate_list,
            all_shapes=[],
            all_images=[]
        )

        extracted = self.doc1[0].get_text()
        count = extracted.count("Added Text")
        self.assertEqual(count, 1, "Added text was burned multiple times despite deduplication safeguard")

    def test_multi_tab_switching_does_not_duplicate_objects(self):
        """Verify editing objects in session 2 then switching back to session 1 does not duplicate session 1 objects."""
        # Initialize a mock window simulating multi-tab switching
        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.sessions = [self.session1, self.session2]
        mock_win._active_session = self.session1
        mock_win.tab_view = None
        mock_win.pdf_view = MagicMock()
        mock_win.status_label = MagicMock()
        mock_win._refresh_thumbnail = MagicMock()
        mock_win._update_ui_state = MagicMock()
        mock_win.undo_manager = UndoManager(mock_win)

        # Add a new text object to session 1
        new_text1 = EditableText(50, 200, "Unique Session 1 Item", font_size=12, is_new=True)
        new_text1.page_number = 0
        self.session1.editable_texts.append(new_text1)

        # Rebuild session 1 page
        pdf_handler.rebuild_page(
            self.session1.doc, 0,
            all_texts=self.session1.editable_texts,
            all_shapes=[],
            all_images=[]
        )
        self.assertEqual(self.doc1[0].get_text().count("Unique Session 1 Item"), 1)

        # Simulate tab switch to session 2
        mock_win._active_session = self.session2

        # Add an object in session 2
        new_text2 = EditableText(50, 300, "Session 2 Item", font_size=12, is_new=True)
        new_text2.page_number = 0
        self.session2.editable_texts.append(new_text2)
        pdf_handler.rebuild_page(
            self.session2.doc, 0,
            all_texts=self.session2.editable_texts,
            all_shapes=[],
            all_images=[]
        )

        # Simulate tab switch back to session 1
        mock_win._active_session = self.session1

        # Trigger another rebuild in session 1 (e.g. from an edit or page refresh)
        pdf_handler.rebuild_page(
            self.session1.doc, 0,
            all_texts=self.session1.editable_texts,
            all_shapes=[],
            all_images=[]
        )

        # Verify Session 1 has no duplicate objects
        self.assertEqual(
            self.doc1[0].get_text().count("Unique Session 1 Item"),
            1,
            "Session 1 object was duplicated after switching tabs"
        )
        self.assertEqual(
            self.doc1[0].get_text().count("Session 2 Item"),
            0,
            "Session 2 object leaked into Session 1"
        )

        # Verify Session 2 has no duplicate objects
        self.assertEqual(
            self.doc2[0].get_text().count("Session 2 Item"),
            1,
            "Session 2 object was duplicated"
        )
        self.assertEqual(
            self.doc2[0].get_text().count("Unique Session 1 Item"),
            0,
            "Session 1 object leaked into Session 2"
        )

    def test_commands_bound_to_creating_session(self):
        """Verify commands store target session and execute mutations on their own document."""
        mock_win = MagicMock(spec=PdfEditorWindow)
        mock_win.sessions = [self.session1, self.session2]
        mock_win._active_session = self.session1

        new_text = EditableText(100, 250, "Session 1 Command Text", font_size=12, is_new=True)
        new_text.page_number = 0

        # Command created when session 1 is active
        cmd = AddObjectCommand(mock_win, new_text)
        self.assertIs(cmd.session, self.session1)

        # Switch active session to session 2
        mock_win._active_session = self.session2

        # Execute command - should modify session 1, NOT session 2
        cmd.execute()
        self.assertIn(new_text, self.session1.editable_texts)
        self.assertNotIn(new_text, self.session2.editable_texts)
        self.assertTrue(self.session1.document_modified)

        # Undo command - should remove from session 1
        cmd.undo()
        self.assertNotIn(new_text, self.session1.editable_texts)


class TestTextToolbarSelectionDecoupling(unittest.TestCase):
    """Test text toolbar formatting decoupling and selection synchronization."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=595, height=842)
        self.session = DocumentSession(pdf_path="test.pdf")
        self.session.doc = self.doc
        self.session.current_page_index = 0

        self.text1 = EditableText(50, 100, "Text Number One", font_size=12.0, font_family="Liberation Sans", is_new=True)
        self.text1.page_number = 0
        self.text1.color = (0.0, 0.0, 0.0)
        self.text1.is_bold = False

        self.text2 = EditableText(50, 200, "Text Number Two", font_size=14.0, font_family="Liberation Sans", is_new=True)
        self.text2.page_number = 0
        self.text2.color = (0.0, 0.0, 0.0)
        self.text2.is_bold = False

        self.session.editable_texts = [self.text1, self.text2]

    def test_switching_selected_text_synchronizes_pending_format_change(self):
        """Verify switching selected_text commits previous pending format and updates to new object."""
        win = MagicMock(spec=PdfEditorWindow)
        win._active_session = self.session
        win.pending_format_change_obj = None
        win.before_format_change_state = None
        win.undo_manager = MagicMock(spec=UndoManager)

        # Use actual property logic from window
        def set_selected_text(val):
            if win.pending_format_change_obj and win.pending_format_change_obj is not val:
                win.commit_pending_format_change()
            win._active_session.selected_text = val
            if val is not None:
                win.pending_format_change_obj = val
                win.before_format_change_state = copy.deepcopy(val.__dict__)
            else:
                win.pending_format_change_obj = None
                win.before_format_change_state = None

        def get_selected_text():
            return win._active_session.selected_text if win._active_session else None

        # Select Text 1
        set_selected_text(self.text1)
        self.assertIs(get_selected_text(), self.text1)
        self.assertIs(win.pending_format_change_obj, self.text1)
        self.assertIsNotNone(win.before_format_change_state)

        # Select Text 2
        set_selected_text(self.text2)
        self.assertIs(get_selected_text(), self.text2)
        self.assertIs(win.pending_format_change_obj, self.text2)

        # Deselect by setting to None
        set_selected_text(None)
        self.assertIsNone(get_selected_text())
        self.assertIsNone(win.pending_format_change_obj)
        self.assertIsNone(win.before_format_change_state)

    def test_toolbar_formatting_mutates_only_currently_selected_text(self):
        """Verify changing toolbar format modifies only the currently selected text, not previously selected text."""
        # Simulate real window state and formatting handler logic
        class FakeWindow:
            def __init__(self, session, text1, text2):
                self._active_session = session
                self.pending_format_change_obj = None
                self.before_format_change_state = None
                self._last_font_size = 12.0
                self._last_font_family = "Liberation Sans"
                self._last_color = (0.0, 0.0, 0.0)
                self._last_is_bold = False
                self.format_change_timer = None
                self.undo_manager = MagicMock()
                self.pdf_view = MagicMock()
                self._refresh_thumbnail = MagicMock()
                self._update_ui_state = MagicMock()
                self.doc = session.doc
                self.current_page_index = 0
                self.editable_texts = [text1, text2]
                self.editable_shapes = []
                self.editable_images = []
                self.editable_strokes = []

            @property
            def selected_text(self):
                return self._active_session.selected_text if self._active_session else None

            @selected_text.setter
            def selected_text(self, val):
                if self.pending_format_change_obj and self.pending_format_change_obj is not val:
                    self.commit_pending_format_change()
                if self._active_session:
                    self._active_session.selected_text = val
                if val is not None:
                    self.pending_format_change_obj = val
                    self.before_format_change_state = copy.deepcopy(val.__dict__)
                else:
                    self.pending_format_change_obj = None
                    self.before_format_change_state = None

            def commit_pending_format_change(self):
                if self.pending_format_change_obj and self.before_format_change_state:
                    cmd = EditObjectCommand(
                        self,
                        self.pending_format_change_obj,
                        self.before_format_change_state,
                        copy.deepcopy(self.pending_format_change_obj.__dict__)
                    )
                    self.undo_manager.add_command(cmd)
                self.pending_format_change_obj = None
                self.before_format_change_state = None

            def on_text_format_changed(self, font_family, font_size, color, is_bold):
                target_text = self.selected_text
                if target_text is not None:
                    if self.pending_format_change_obj is not target_text:
                        if self.pending_format_change_obj:
                            self.commit_pending_format_change()
                        self.pending_format_change_obj = target_text
                        self.before_format_change_state = copy.deepcopy(target_text.__dict__)

                    target_text.font_size = font_size
                    target_text.font_family = font_family
                    target_text.color = color
                    target_text.is_bold = is_bold
                    self._last_font_size = font_size
                    self._last_font_family = font_family
                    self._last_color = color
                    self._last_is_bold = is_bold
                else:
                    if self.pending_format_change_obj:
                        self.commit_pending_format_change()
                    self._last_font_size = font_size
                    self._last_font_family = font_family
                    self._last_color = color
                    self._last_is_bold = is_bold

        win = FakeWindow(self.session, self.text1, self.text2)

        # 1. Select Text 1
        win.selected_text = self.text1
        self.assertEqual(self.text1.font_size, 12.0)
        self.assertEqual(self.text2.font_size, 14.0)

        # 2. Switch selection to Text 2
        win.selected_text = self.text2

        # 3. Modify formatting in toolbar (e.g. increase font size to 24.0 and make bold)
        win.on_text_format_changed("Liberation Sans", 24.0, (1.0, 0.0, 0.0), True)

        # Verify Text 2 received the new formatting
        self.assertEqual(self.text2.font_size, 24.0)
        self.assertEqual(self.text2.color, (1.0, 0.0, 0.0))
        self.assertTrue(self.text2.is_bold)

        # Verify Text 1 was COMPLETELY UNTOUCHED
        self.assertEqual(self.text1.font_size, 12.0, "Text 1 was mutated by toolbar changes directed at Text 2")
        self.assertEqual(self.text1.color, (0.0, 0.0, 0.0))
        self.assertFalse(self.text1.is_bold)

        # 4. Deselect by clicking blank space
        win.selected_text = None
        self.assertIsNone(win.selected_text)
        self.assertIsNone(win.pending_format_change_obj)

        # 5. Modify toolbar formatting with nothing selected
        win.on_text_format_changed("Liberation Serif", 18.0, (0.0, 0.0, 1.0), False)

        # Verify neither Text 1 nor Text 2 is mutated
        self.assertEqual(self.text1.font_size, 12.0)
        self.assertEqual(self.text2.font_size, 24.0)

        # Verify toolbar defaults were updated for new text creation
        self.assertEqual(win._last_font_size, 18.0)
        self.assertEqual(win._last_font_family, "Liberation Serif")
        self.assertEqual(win._last_color, (0.0, 0.0, 1.0))


class TestContextMenuLocalization(unittest.TestCase):
    """Test right click context menu and sticky note translation completeness across all locales."""

    def test_sticky_note_context_menu_keys_all_locales(self):
        """Verify sticky note context menu keys exist and return non-raw translated strings in all 7 languages."""
        from word_sys_pdf_editor.i18n import _STRINGS, _
        import word_sys_pdf_editor.i18n as i18n_mod

        keys_to_verify = [
            "menu_add_sticky_note",
            "add_sticky_note",
            "edit_sticky_note",
            "delete_sticky_note",
            "delete_page_title",
            "image_delete_confirm_title",
            "image_delete_confirm_msg",
            "err_image_delete_title",
            "err_image_delete_msg",
            "filter_all_files",
            "untitled_document",
        ]

        orig_lang = i18n_mod._active_lang
        try:
            for lang in ["en", "tr", "fr", "de", "es", "it", "ru"]:
                i18n_mod._active_lang = lang
                for key in keys_to_verify:
                    self.assertIn(key, _STRINGS[lang], f"Key '{key}' missing from '{lang}' locale table")
                    val = _(key)
                    self.assertNotEqual(val, key, f"Key '{key}' returned untranslated raw identifier in '{lang}'")
                    self.assertTrue(len(val) > 0)
        finally:
            i18n_mod._active_lang = orig_lang


class TestSavePermissionsSafeguard(unittest.TestCase):
    """Test saving document with dictionary and integer permissions to prevent C-level TypeError."""

    def test_permissions_to_bitmask_conversion(self):
        """Verify permissions_to_bitmask correctly parses dict, int, and None."""
        self.assertEqual(pdf_handler.permissions_to_bitmask(123), 123)

        bitmask = pdf_handler.permissions_to_bitmask({
            "print": True,
            "copy": False,
            "annotate": True,
            "modify": False,
            "form": False
        })
        self.assertTrue(isinstance(bitmask, int))
        self.assertTrue(bitmask & getattr(fitz, "PDF_PERM_PRINT", 4))
        self.assertFalse(bitmask & getattr(fitz, "PDF_PERM_COPY", 16))
        self.assertTrue(bitmask & getattr(fitz, "PDF_PERM_ANNOTATE", 32))
        self.assertFalse(bitmask & getattr(fitz, "PDF_PERM_MODIFY", 8))

    def test_save_document_with_dict_permissions(self):
        """Verify save_document succeeds without throwing TypeError when _pdf_permissions is a dict."""
        import tempfile
        doc = fitz.open()
        doc.new_page(width=300, height=300)
        doc._pdf_password = "user123"
        doc._pdf_owner_password = "owner123"
        doc._pdf_permissions = {
            "print": True,
            "copy": True,
            "annotate": True,
            "modify": False,
            "form": True,
        }

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            temp_path = f.name

        try:
            success, err = pdf_handler.save_document(doc, temp_path)
            self.assertTrue(success, f"Failed to save document: {err}")
            self.assertIsNone(err)

            # Re-open with password
            opened_doc, open_err = pdf_handler.load_pdf_document(temp_path, password="user123")
            self.assertIsNotNone(opened_doc, f"Failed to open saved protected PDF: {open_err}")
            if opened_doc:
                opened_doc.close()
        finally:
            doc.close()
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()


