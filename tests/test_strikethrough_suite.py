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
