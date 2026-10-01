"""
Test reproducing and verifying fix for:
1. Text rotation duplicating other texts when rotated across/on top of them.
2. Editing text close to another text duplicating the nearby text (burn mark).
3. Ensuring 100% object independence for all text edits and rotations.
"""

import unittest
from unittest.mock import MagicMock
import fitz
import copy

from word_sys_pdf_editor.models import EditableText
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor import undo_manager


class MockWindow:
    def __init__(self, doc):
        self.doc = doc
        self.editable_texts = []
        self.editable_shapes = []
        self.editable_images = []
        self.editable_strokes = []
        self.selected_text = None
        self.pending_format_change_obj = None
        self.before_format_change_state = None
        self.document_modified = False
        self.status_label = MagicMock()
        self.undo_manager = undo_manager.UndoManager(self)
        self.pdf_view = self
        self.current_page_index = 0

    def _update_undo_redo_buttons(self): pass
    def _update_text_format_controls(self, obj): pass
    def _update_rotation_controls(self, obj): pass
    def _update_ui_state(self): pass
    def _refresh_thumbnail(self, p): pass
    def queue_draw(self): pass


class TestTextRotationAndIndependence(unittest.TestCase):
    def setUp(self):
        # Create a document with two text lines close to each other
        self.doc, _ = pdf_handler.create_new_pdf(width=500, height=500, num_pages=1)
        page = self.doc.load_page(0)
        # Line 0: Paragraph line at y=100
        page.insert_text(fitz.Point(50, 100), "Line Zero Paragraph Text", fontsize=11)
        # Line 1: URL / report line at y=115 (close to Line 0)
        page.insert_text(fitz.Point(50, 115), "Line One Report URL Text", fontsize=11)

        # Save snapshot of page 0
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)

        self.win = MockWindow(self.doc)

        # Create EditableText representations as extracted
        self.t0 = EditableText(50, 90, "Line Zero Paragraph Text", font_size=11, is_new=False, baseline=100, page_number=0)
        self.t0.bbox = (50, 89, 200, 103)
        self.t0.original_bbox = self.t0.bbox
        self.t0.original_baseline = self.t0.baseline
        self.t0.original_rotation = 0.0

        self.t1 = EditableText(50, 105, "Line One Report URL Text", font_size=11, is_new=False, baseline=115, page_number=0)
        self.t1.bbox = (50, 104, 200, 118)
        self.t1.original_bbox = self.t1.bbox
        self.t1.original_baseline = self.t1.baseline
        self.t1.original_rotation = 0.0

        self.win.editable_texts = [self.t0, self.t1]

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_rotating_text_does_not_affect_or_duplicate_other_texts(self):
        """Rotating text across another line must NOT mark the other line as _ghost_redacted or duplicate it."""
        cmd = undo_manager.RotateObjectCommand(self.win, self.t1, 0.0, 315.0)
        cmd.execute()

        # CRITICAL ASSERTION: t0 must NOT be marked _ghost_redacted!
        self.assertFalse(
            getattr(self.t0, '_ghost_redacted', False),
            "Line Zero was wrongly marked _ghost_redacted when rotating Line One!"
        )

        page = self.doc.load_page(0)
        page_text = page.get_text()

        count_t0 = page_text.count("Line Zero Paragraph Text")
        self.assertEqual(
            count_t0, 1,
            f"Line Zero was duplicated! Found {count_t0} occurrences instead of 1."
        )

    def test_editing_close_text_does_not_affect_or_duplicate_other_texts(self):
        """Editing text close to another text must NOT mark the other text as _ghost_redacted or duplicate it."""
        old_props = {'text': self.t1.text, 'bbox': self.t1.bbox, 'baseline': self.t1.baseline}
        new_props = {'text': "Edited Line One", 'bbox': self.t1.bbox, 'baseline': self.t1.baseline}

        cmd = undo_manager.EditObjectCommand(self.win, self.t1, old_props, new_props)
        cmd.execute()

        # CRITICAL ASSERTION: t0 must NOT be marked _ghost_redacted!
        self.assertFalse(
            getattr(self.t0, '_ghost_redacted', False),
            "Line Zero was wrongly marked _ghost_redacted when editing adjacent Line One!"
        )

        page = self.doc.load_page(0)
        page_text = page.get_text()

        count_t0 = page_text.count("Line Zero Paragraph Text")
        self.assertEqual(
            count_t0, 1,
            f"Line Zero was duplicated! Found {count_t0} occurrences instead of 1."
        )

    def test_original_text_erased_at_original_rotation_not_new_rotation(self):
        """Ghost erasure must erase the original text at its original rotation (0.0), not at the new angle."""
        cmd = undo_manager.RotateObjectCommand(self.win, self.t1, 0.0, 45.0)
        cmd.execute()

        page = self.doc.load_page(0)
        page_text = page.get_text()
        count_t1 = page_text.count("Line One Report URL Text")
        self.assertEqual(count_t1, 1, f"Found {count_t1} instances of Line One text")

    def test_sequential_rotations_and_undo_redo(self):
        """Sequential rotations 0 -> 45 -> 90 followed by undo and redo maintain exact single instances."""
        # 1. Rotate to 45 deg
        cmd1 = undo_manager.RotateObjectCommand(self.win, self.t1, 0.0, 45.0)
        cmd1.execute()
        self.win.undo_manager.add_command(cmd1)

        page = self.doc.load_page(0)
        text_45 = page.get_text()
        self.assertEqual(text_45.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(text_45.count("Line One Report URL Text"), 1)

        # 2. Rotate to 90 deg
        cmd2 = undo_manager.RotateObjectCommand(self.win, self.t1, 45.0, 90.0)
        cmd2.execute()
        self.win.undo_manager.add_command(cmd2)

        page = self.doc.load_page(0)
        text_90 = page.get_text()
        self.assertEqual(text_90.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(text_90.count("Line One Report URL Text"), 1)

        # 3. Undo back to 45 deg
        self.win.undo_manager.undo()
        self.assertAlmostEqual(self.t1.rotation, 45.0, places=1)
        page = self.doc.load_page(0)
        text_undo1 = page.get_text()
        self.assertEqual(text_undo1.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(text_undo1.count("Line One Report URL Text"), 1)

        # 4. Undo back to 0 deg
        self.win.undo_manager.undo()
        self.assertAlmostEqual(self.t1.rotation, 0.0, places=1)
        page = self.doc.load_page(0)
        text_undo2 = page.get_text()
        self.assertEqual(text_undo2.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(text_undo2.count("Line One Report URL Text"), 1)

    def test_touching_and_overlapping_bbox_close_editing(self):
        """When text bounding boxes touch or overlap by 1pt, editing one never corrupts or duplicates the other."""
        # Force bounding boxes to overlap by 2pt
        self.t0.bbox = (50, 89, 200, 106)
        self.t0.original_bbox = self.t0.bbox
        self.t1.bbox = (50, 104, 200, 118)
        self.t1.original_bbox = self.t1.bbox

        old_props = {'text': self.t1.text, 'bbox': self.t1.bbox, 'baseline': self.t1.baseline}
        new_props = {'text': "Modified Line One", 'bbox': self.t1.bbox, 'baseline': self.t1.baseline}

        cmd = undo_manager.EditObjectCommand(self.win, self.t1, old_props, new_props)
        cmd.execute()

        self.assertFalse(getattr(self.t0, '_ghost_redacted', False))
        page = self.doc.load_page(0)
        page_text = page.get_text()
        self.assertEqual(page_text.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(page_text.count("Modified Line One"), 1)

    def test_underline_link_text_rotation_across_paragraph(self):
        """Rotating a link/underlined text across paragraph lines preserves all other lines."""
        self.t1.is_underline = True
        self.t1.text = "https://datareportal.com/reports/example"
        self.t1.original_text = self.t1.text
        # Rotate across t0
        cmd = undo_manager.RotateObjectCommand(self.win, self.t1, 0.0, 310.0)
        cmd.execute()

        self.assertFalse(getattr(self.t0, '_ghost_redacted', False))
        page = self.doc.load_page(0)
        page_text = page.get_text()
        self.assertEqual(page_text.count("Line Zero Paragraph Text"), 1)
        self.assertEqual(page_text.count("https://datareportal.com/reports/example"), 1)


if __name__ == "__main__":
    unittest.main()
