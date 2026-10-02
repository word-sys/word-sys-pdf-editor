import unittest
import sys
import os
import math
import fitz

workspace_dir = "/home/word-sys/word-sys-pdf-editor"
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableText, EditableShape, EditableStroke, EditableImage
from word_sys_pdf_editor.undo_manager import (
    UndoManager, AddObjectCommand, DeleteObjectCommand, EditObjectCommand, RotateObjectCommand
)

class MockWindow:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.editable_texts = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.editable_images = []
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.undo_manager = UndoManager(self)
        self.document_modified = False
        class MockWidget:
            def set_text(self, *a, **k): pass
            def queue_draw(self): pass
            def remove_all(self): pass
            def append(self, x): pass
            def set_content_width(self, w): pass
            def set_content_height(self, h): pass
            def set_sensitive(self, s): pass
            def get_vadjustment(self): return None
            def get_hadjustment(self): return None
        self.status_label = MockWidget()
        self.pdf_view = MockWidget()
        self.pages_model = MockWidget()
        self.pdf_scroll = MockWidget()
        self.open_button = MockWidget()
        self.select_tool_button = MockWidget()
        self.add_text_tool_button = MockWidget()
        self.zoom_level = 1.0
        self.current_pdf_page_width = 595
        self.current_pdf_page_height = 842

    def _update_undo_redo_buttons(self): pass
    def _refresh_thumbnail(self, p): pass
    def _update_ui_state(self): pass
    def commit_pending_format_change(self): pass
    def hide_text_editor(self): pass

    def _load_page(self, page_index, preserve_scroll=False):
        if not self.doc or not (0 <= page_index < pdf_handler.get_page_count(self.doc)):
            return

        self.commit_pending_format_change()

        old_page_idx = getattr(self, 'current_page_index', None)
        if self.doc and old_page_idx is not None and (0 <= old_page_idx < pdf_handler.get_page_count(self.doc)):
            if old_page_idx != page_index:
                pdf_handler.save_page_snapshot(self.doc, old_page_idx, force=True)

        self.undo_manager.clear()

        self.current_page_index = page_index
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.hide_text_editor()

        texts, error = pdf_handler.extract_editable_text(self.doc, page_index)
        self.editable_texts = texts or []
        images, error = pdf_handler.extract_editable_images(self.doc, page_index)
        self.editable_images = images or []
        shapes, shapes_error = pdf_handler.extract_editable_shapes(self.doc, page_index)
        self.editable_shapes = shapes or []
        strokes, strokes_error = pdf_handler.extract_editable_strokes(self.doc, page_index)
        self.editable_strokes = strokes or []

        if self.doc:
            pdf_handler.save_page_snapshot(self.doc, page_index)


class TestFullRegressionSuite(unittest.TestCase):
    def tearDown(self):
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

    # =========================================================================
    # Section 1: Collateral Deletion Tests (Bug 1 & Variants)
    # =========================================================================

    def test_collateral_deletion_adjacent_text(self):
        """Deleting a text adjacent/overlapping another text must preserve the neighbor with zero corruption."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(100, 100), "Hello from word-sys", fontsize=14)
        page.insert_text(fitz.Point(100, 112), "where?", fontsize=14, color=(1, 0, 0))

        pdf_handler.save_page_snapshot(doc, 0)
        win = MockWindow(doc)
        win._load_page(0)

        self.assertEqual(len(win.editable_texts), 2)
        t_from = [t for t in win.editable_texts if "from" in t.text][0]
        t_where = [t for t in win.editable_texts if "where?" in t.text][0]

        DeleteObjectCommand(win, t_from).execute()

        text_content = doc[0].get_text()
        self.assertNotIn("Hello from word-sys", text_content)
        self.assertIn("where?", text_content)
        self.assertNotIn("whwhere?", text_content)

    def test_collateral_deletion_text_overlapping_shape(self):
        """Deleting a text overlapping a rectangle shape must preserve the rectangle shape."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # Draw a rectangle
        rect = fitz.Rect(80, 80, 220, 140)
        shape = page.new_shape()
        shape.draw_rect(rect)
        shape.finish(color=(0, 0, 1), fill=None, width=2.0)
        shape.commit()
        # Text inside the rectangle
        page.insert_text(fitz.Point(90, 110), "Text Inside Box", fontsize=12)

        pdf_handler.save_page_snapshot(doc, 0)
        win = MockWindow(doc)
        win._load_page(0)

        self.assertEqual(len(win.editable_texts), 1)
        self.assertEqual(len(win.editable_shapes), 1)

        txt_obj = win.editable_texts[0]
        DeleteObjectCommand(win, txt_obj).execute()

        # Text must be gone
        self.assertNotIn("Text Inside Box", doc[0].get_text())
        # Rectangle drawing must still exist on page
        drawings = doc[0].get_drawings()
        self.assertGreaterEqual(len(drawings), 1)

    def test_collateral_deletion_moving_text_preserves_underlying_text(self):
        """Moving text that was placed directly on top of another text must preserve the underlying text."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(100, 100), "BASE TEXT", fontsize=14)
        page.insert_text(fitz.Point(105, 102), "TOP TEXT", fontsize=14)

        pdf_handler.save_page_snapshot(doc, 0)
        win = MockWindow(doc)
        win._load_page(0)

        t_base = [t for t in win.editable_texts if "BASE" in t.text][0]
        t_top = [t for t in win.editable_texts if "TOP" in t.text][0]

        # Move top text to (300, 300)
        old_props = {'bbox': t_top.bbox, 'x': t_top.x, 'y': t_top.y}
        new_bbox = (300, 300, 380, 315)
        new_props = {'bbox': new_bbox, 'x': 300, 'y': 300}
        cmd = EditObjectCommand(win, t_top, old_props, new_props)
        cmd.execute()

        text_content = doc[0].get_text()
        self.assertIn("BASE TEXT", text_content)
        self.assertIn("TOP TEXT", text_content)

    def test_collateral_deletion_rotated_text_preserves_adjacent(self):
        """Deleting a rotated text that touches another text preserves the neighbor."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(100, 100), "Adjacent Normal", fontsize=12)

        pdf_handler.save_page_snapshot(doc, 0)
        win = MockWindow(doc)
        win._load_page(0)

        # Add a rotated text near the normal text
        rot_text = EditableText(100, 105, "Rotated Touch", font_size=12, is_new=True, rotation=45.0, page_number=0)
        AddObjectCommand(win, rot_text).execute()

        self.assertIn("Adjacent Normal", doc[0].get_text())
        self.assertIn("Rotated Touch", doc[0].get_text())

        # Now delete the rotated text
        DeleteObjectCommand(win, rot_text).execute()

        text_content = doc[0].get_text()
        self.assertNotIn("Rotated Touch", text_content)
        self.assertIn("Adjacent Normal", text_content)

    # =========================================================================
    # Section 2: Page Switching and Addition Tests (Bug 2 & Variants)
    # =========================================================================

    def test_page_switch_multiple_texts_and_add_after_return(self):
        """Adding multiple texts on Page 0, switching pages, returning, and adding more texts preserves all."""
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p1 = doc.new_page(width=595, height=842)

        win = MockWindow(doc)
        win._load_page(0)

        # Add 3 texts to Page 0
        t1 = EditableText(50, 50, "P0 Item Alpha", font_size=12, is_new=True, page_number=0)
        t2 = EditableText(50, 100, "P0 Item Beta", font_size=12, is_new=True, page_number=0)
        t3 = EditableText(50, 150, "P0 Item Gamma", font_size=12, is_new=True, page_number=0)
        AddObjectCommand(win, t1).execute()
        AddObjectCommand(win, t2).execute()
        AddObjectCommand(win, t3).execute()

        # Switch to Page 1
        win._load_page(1)
        t_p1 = EditableText(50, 50, "P1 Item Delta", font_size=12, is_new=True, page_number=1)
        AddObjectCommand(win, t_p1).execute()

        # Switch back to Page 0
        win._load_page(0)
        self.assertIn("P0 Item Alpha", doc[0].get_text())
        self.assertIn("P0 Item Beta", doc[0].get_text())
        self.assertIn("P0 Item Gamma", doc[0].get_text())

        # Add a 4th text to Page 0
        t4 = EditableText(50, 200, "P0 Item Epsilon", font_size=12, is_new=True, page_number=0)
        AddObjectCommand(win, t4).execute()

        p0_text = doc[0].get_text()
        self.assertIn("P0 Item Alpha", p0_text)
        self.assertIn("P0 Item Beta", p0_text)
        self.assertIn("P0 Item Gamma", p0_text)
        self.assertIn("P0 Item Epsilon", p0_text)

        # Switch to Page 1 and verify Page 1 is also completely intact
        win._load_page(1)
        p1_text = doc[1].get_text()
        self.assertIn("P1 Item Delta", p1_text)

    def test_page_switch_shapes_and_strokes_preservation(self):
        """Adding shapes and freehand strokes across page switches preserves all vector graphics."""
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p1 = doc.new_page(width=595, height=842)

        win = MockWindow(doc)
        win._load_page(0)

        # Add checkmark and cross shapes on Page 0
        chk = EditableShape(EditableShape.SHAPE_CHECKMARK, (100, 100, 200, 200), page_number=0, is_new=True)
        cross = EditableShape(EditableShape.SHAPE_CROSS, (250, 100, 350, 200), page_number=0, is_new=True)
        AddObjectCommand(win, chk).execute()
        AddObjectCommand(win, cross).execute()

        # Add freehand stroke on Page 0
        stroke = EditableStroke([(50, 50), (60, 70), (80, 90)], stroke_color=(0, 0, 0), stroke_width=2.0, page_number=0, is_new=True)
        AddObjectCommand(win, stroke).execute()

        # Switch to Page 1
        win._load_page(1)

        # Switch back to Page 0
        win._load_page(0)

        # Verify drawings on Page 0 exist
        drawings_before = len(doc[0].get_drawings())
        self.assertGreaterEqual(drawings_before, 3)

        # Now add another shape (ellipse) on Page 0
        ellipse = EditableShape(EditableShape.SHAPE_ELLIPSE, (400, 100, 500, 200), page_number=0, is_new=True)
        AddObjectCommand(win, ellipse).execute()

        drawings_after = len(doc[0].get_drawings())
        self.assertGreater(drawings_after, drawings_before)

    def test_multi_hop_page_navigation_and_editing(self):
        """Objects survive complex multi-hop navigation: Page 0 -> 1 -> 2 -> 0 -> 1 -> 0."""
        doc = fitz.open()
        for _ in range(3):
            doc.new_page(width=595, height=842)

        win = MockWindow(doc)
        win._load_page(0)
        AddObjectCommand(win, EditableText(50, 50, "P0 First", font_size=12, is_new=True, page_number=0)).execute()

        win._load_page(1)
        AddObjectCommand(win, EditableText(50, 50, "P1 First", font_size=12, is_new=True, page_number=1)).execute()

        win._load_page(2)
        AddObjectCommand(win, EditableText(50, 50, "P2 First", font_size=12, is_new=True, page_number=2)).execute()

        # Navigate: 2 -> 0 -> 1 -> 0
        win._load_page(0)
        win._load_page(1)
        win._load_page(0)

        # Add second item on Page 0
        AddObjectCommand(win, EditableText(50, 100, "P0 Second", font_size=12, is_new=True, page_number=0)).execute()

        p0_text = doc[0].get_text()
        self.assertIn("P0 First", p0_text)
        self.assertIn("P0 Second", p0_text)

        win._load_page(1)
        self.assertIn("P1 First", doc[1].get_text())

        win._load_page(2)
        self.assertIn("P2 First", doc[2].get_text())

    # =========================================================================
    # Section 3: Page Lifecycle & Snapshot Remapping Tests
    # =========================================================================

    def test_delete_page_remaps_snapshots_correctly(self):
        """Deleting a page shifts snapshot keys so remaining pages do not restore deleted content."""
        doc = fitz.open()
        for i in range(3):
            p = doc.new_page(width=595, height=842)
            p.insert_text(fitz.Point(100, 100), f"ORIGINAL PAGE {i}", fontsize=14)
            pdf_handler.save_page_snapshot(doc, i)

        # Page 0 has "PAGE 0", Page 1 has "PAGE 1", Page 2 has "PAGE 2"
        # Delete Page 1
        success, _ = pdf_handler.delete_page(doc, 1)
        self.assertTrue(success)
        self.assertEqual(doc.page_count, 2)

        # Old Page 2 is now Page 1 in doc
        self.assertIn("ORIGINAL PAGE 2", doc[1].get_text())

        # Test rebuild on Page 1: must restore "ORIGINAL PAGE 2", NOT deleted "ORIGINAL PAGE 1"
        win = MockWindow(doc)
        win._load_page(1)
        new_text = EditableText(100, 200, "Appended to Page 1", font_size=12, is_new=True, page_number=1)
        AddObjectCommand(win, new_text).execute()

        page1_content = doc[1].get_text()
        self.assertIn("ORIGINAL PAGE 2", page1_content)
        self.assertIn("Appended to Page 1", page1_content)
        self.assertNotIn("ORIGINAL PAGE 1", page1_content)

    def test_move_page_remaps_snapshots_correctly(self):
        """Moving Page 0 to Page 1 swaps snapshots so rebuild restores the correct content for each page."""
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p0.insert_text(fitz.Point(100, 100), "Alpha Content", fontsize=14)
        pdf_handler.save_page_snapshot(doc, 0)

        p1 = doc.new_page(width=595, height=842)
        p1.insert_text(fitz.Point(100, 100), "Beta Content", fontsize=14)
        pdf_handler.save_page_snapshot(doc, 1)

        # Move Page 0 to Page 1 (Beta becomes page 0, Alpha becomes page 1)
        success, _ = pdf_handler.move_page(doc, 0, 1)
        self.assertTrue(success)

        self.assertIn("Beta Content", doc[0].get_text())
        self.assertIn("Alpha Content", doc[1].get_text())

        # Test rebuild on Page 0: must restore Beta Content
        win = MockWindow(doc)
        win._load_page(0)
        AddObjectCommand(win, EditableText(100, 200, "Extra Beta", font_size=12, is_new=True, page_number=0)).execute()

        p0_text = doc[0].get_text()
        self.assertIn("Beta Content", p0_text)
        self.assertIn("Extra Beta", p0_text)
        self.assertNotIn("Alpha Content", p0_text)

    def test_insert_blank_page_at_index_shifts_snapshots(self):
        """Inserting a blank page at index 1 shifts snapshots of subsequent pages."""
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p0.insert_text(fitz.Point(100, 100), "Page Zero", fontsize=14)
        pdf_handler.save_page_snapshot(doc, 0)

        p1 = doc.new_page(width=595, height=842)
        p1.insert_text(fitz.Point(100, 100), "Page One Initial", fontsize=14)
        pdf_handler.save_page_snapshot(doc, 1)

        # Insert blank page at index 1: old Page 1 becomes Page 2
        success, _ = pdf_handler.insert_blank_page(doc, page_index=1, width=595, height=842)
        self.assertTrue(success)
        self.assertEqual(doc.page_count, 3)

        # Page 1 should be empty blank page
        self.assertEqual(doc[1].get_text().strip(), "")
        # Page 2 should have "Page One Initial"
        self.assertIn("Page One Initial", doc[2].get_text())

        # Rebuilding on Page 2 must preserve "Page One Initial"
        win = MockWindow(doc)
        win._load_page(2)
        AddObjectCommand(win, EditableText(100, 200, "Added to Shifted Page", font_size=12, is_new=True, page_number=2)).execute()

        p2_text = doc[2].get_text()
        self.assertIn("Page One Initial", p2_text)
        self.assertIn("Added to Shifted Page", p2_text)

    # =========================================================================
    # Section 4: Rotated Redaction & Direction Extraction Tests
    # =========================================================================

    def test_rotated_text_redaction_quad_accuracy(self):
        """Deleting an existing rotated text redacts its quad area accurately without leaving ghosts."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # Insert 90 degree rotated text via morph matrix (-90 in PyMuPDF matrix convention)
        mat = fitz.Matrix(-90)
        page.insert_text(fitz.Point(200, 200), "Vertical Ghost Test", fontsize=14, morph=(fitz.Point(200, 200), mat))
        pdf_handler.save_page_snapshot(doc, 0)

        win = MockWindow(doc)
        win._load_page(0)

        # Verify rotation was extracted from direction vector
        self.assertEqual(len(win.editable_texts), 1)
        txt = win.editable_texts[0]
        self.assertAlmostEqual(txt.rotation % 360.0, 90.0, delta=1.0)

        # Delete the rotated text
        DeleteObjectCommand(win, txt).execute()

        self.assertNotIn("Vertical Ghost Test", doc[0].get_text())

if __name__ == '__main__':
    unittest.main()
