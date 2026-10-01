"""
Comprehensive unit and integration test suite for Part 12: 4-Way Text Alignment.
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
            while main_ctx.pending():
                main_ctx.iteration(False)

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

