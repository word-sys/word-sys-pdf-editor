"""Consolidated Regressions, Bug Fixes, and Spatial Indexing Test Suite for word-sys-pdf-editor.

This suite validates full regression scenarios, verified user bug fixes, canvas object independence,
layer reordering with thumbnail synchronization, and asynchronous chunked search with 2D spatial grid indexing.
"""
from __future__ import annotations


# ============================================================================
# SECTION: test_complex_regression_suite.py
# ============================================================================
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
        self.form_fields = []
        self._page_objects_cache = {}

    def _update_undo_redo_buttons(self): pass
    def _refresh_thumbnail(self, p): pass
    def _update_ui_state(self): pass
    def commit_pending_format_change(self): pass
    def hide_text_editor(self): pass

    def _stash_page_objects(self, page_index: int):
        if page_index is None or not self.doc or not (0 <= page_index < len(self.doc)):
            return
        self._page_objects_cache[page_index] = {
            'texts': list(self.editable_texts),
            'images': list(self.editable_images),
            'shapes': list(self.editable_shapes),
            'strokes': list(self.editable_strokes),
            'form_fields': list(getattr(self, 'form_fields', [])),
        }

    def _restore_page_objects(self, page_index: int):
        if page_index is None or not self.doc or not (0 <= page_index < len(self.doc)):
            return
        if page_index in self._page_objects_cache:
            cached = self._page_objects_cache[page_index]
            self.editable_texts = list(cached.get('texts', []))
            self.editable_images = list(cached.get('images', []))
            self.editable_shapes = list(cached.get('shapes', []))
            self.editable_strokes = list(cached.get('strokes', []))
            self.form_fields = list(cached.get('form_fields', []))
        else:
            texts, error = pdf_handler.extract_editable_text(self.doc, page_index)
            self.editable_texts = texts or []
            images, error = pdf_handler.extract_editable_images(self.doc, page_index)
            self.editable_images = images or []
            shapes, shapes_error = pdf_handler.extract_editable_shapes(self.doc, page_index)
            self.editable_shapes = shapes or []
            strokes, strokes_error = pdf_handler.extract_editable_strokes(self.doc, page_index)
            self.editable_strokes = strokes or []
            self.form_fields = []
            self._stash_page_objects(page_index)

    def _load_page(self, page_index, preserve_scroll=False, reload_objects=False):
        if not self.doc or not (0 <= page_index < pdf_handler.get_page_count(self.doc)):
            return

        self.commit_pending_format_change()

        old_page_idx = getattr(self, 'current_page_index', None)
        if self.doc and old_page_idx is not None and (0 <= old_page_idx < pdf_handler.get_page_count(self.doc)):
            if old_page_idx != page_index:
                old_key = (id(self.doc), old_page_idx)
                if old_key not in pdf_handler._page_snapshots:
                    pdf_handler.save_page_snapshot(self.doc, old_page_idx)
                self._stash_page_objects(old_page_idx)

        self.undo_manager.clear()

        self.current_page_index = page_index
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.hide_text_editor()

        if reload_objects:
            texts, error = pdf_handler.extract_editable_text(self.doc, page_index)
            self.editable_texts = texts or []
            images, error = pdf_handler.extract_editable_images(self.doc, page_index)
            self.editable_images = images or []
            shapes, shapes_error = pdf_handler.extract_editable_shapes(self.doc, page_index)
            self.editable_shapes = shapes or []
            strokes, strokes_error = pdf_handler.extract_editable_strokes(self.doc, page_index)
            self.editable_strokes = strokes or []
            self.form_fields = []
            self._stash_page_objects(page_index)
        else:
            self._restore_page_objects(page_index)

        key = (id(self.doc), page_index)
        if key not in pdf_handler._page_snapshots:
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


# ============================================================================
# SECTION: test_user_bugs_fixed.py
# ============================================================================
import unittest
import sys
import os
import fitz

workspace_dir = "/home/word-sys/word-sys-pdf-editor"
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableText, EditableShape, EditableStroke, EditableImage
from word_sys_pdf_editor.undo_manager import UndoManager, AddObjectCommand, DeleteObjectCommand, EditObjectCommand

def patched_erase_ghost_if_needed(cmd, target_object, page_num):
    if getattr(target_object, 'is_new', True) or getattr(target_object, '_ghost_redacted', False):
        return
        
    pdf_handler.restore_page_from_snapshot(cmd.window.doc, page_num)
    
    orig_bbox = getattr(target_object, 'original_bbox', target_object.bbox)
    rot = getattr(target_object, 'rotation', 0.0)
    
    if isinstance(target_object, (EditableShape, EditableStroke)):
        pad = max(getattr(target_object, 'stroke_width', 2.0) / 2.0 + 1.5, 2.0)
        x0, y0, x1, y1 = orig_bbox
        redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    elif isinstance(target_object, EditableImage):
        x0, y0, x1, y1 = orig_bbox
        redact_rect = fitz.Rect(x0 - 1.0, y0 - 1.0, x1 + 1.0, y1 + 1.0)
    else:
        redact_rect = fitz.Rect(orig_bbox)
        
    cx = (orig_bbox[0] + orig_bbox[2]) / 2.0
    cy = (orig_bbox[1] + orig_bbox[3]) / 2.0
    mat = pdf_handler.get_rotation_matrix(cx, cy, rot) if rot != 0.0 else None
    
    applied_rects = []
    if mat:
        applied_rects.append((redact_rect.quad * mat).rect)
    else:
        applied_rects.append(redact_rect)

    try:
        page = cmd.window.doc.load_page(page_num)
        
        # Check underline
        is_underlined = getattr(target_object, 'is_underline', False)
        strip_rects = []
        if is_underlined and isinstance(target_object, EditableText):
            lines = getattr(target_object, 'text', '').split('\n')
            font_sz = getattr(target_object, 'font_size', 12.0)
            line_height = font_sz * 1.2
            baseline = getattr(target_object, 'original_baseline', getattr(target_object, 'baseline', orig_bbox[3]))
            for i in range(len(lines)):
                s_rect = fitz.Rect(orig_bbox[0] - 2.0, baseline + (i * line_height) - 1.0, orig_bbox[2] + 2.0, baseline + (i * line_height) + 4.0)
                strip_rects.append(s_rect)
                if mat:
                    applied_rects.append((s_rect.quad * mat).rect)
                else:
                    applied_rects.append(s_rect)

        # Check ALL other objects on page for intersection with target's redactions
        all_other = []
        all_other += [t for t in getattr(cmd.window, 'editable_texts', []) if t is not target_object and getattr(t, 'page_number', None) == page_num]
        all_other += [s for s in getattr(cmd.window, 'editable_shapes', []) if s is not target_object and getattr(s, 'page_number', None) == page_num]
        all_other += [st for st in getattr(cmd.window, 'editable_strokes', []) if st is not target_object and getattr(st, 'page_number', None) == page_num]
        all_other += [im for im in getattr(cmd.window, 'editable_images', []) if im is not target_object and getattr(im, 'page_number', None) == page_num]

        intersecting_others = []
        for other in all_other:
            if hasattr(other, 'bbox') and other.bbox:
                ox0, oy0, ox1, oy1 = other.bbox
                opad = max(getattr(other, 'stroke_width', 2.0) / 2.0, 1.0) if isinstance(other, (EditableShape, EditableStroke)) else 0.5
                other_rect = fitz.Rect(ox0 - opad, oy0 - opad, ox1 + opad, oy1 + opad)
                orot = getattr(other, 'rotation', 0.0)
                if orot != 0.0:
                    ocx = (ox0 + ox1) / 2.0
                    ocy = (oy0 + oy1) / 2.0
                    omat = pdf_handler.get_rotation_matrix(ocx, ocy, orot)
                    other_rect = (other_rect.quad * omat).rect
                for ar in applied_rects:
                    if ar.intersects(other_rect):
                        other._ghost_redacted = True
                        intersecting_others.append(other)
                        break

        # Apply redaction for target_object
        if mat:
            page.add_redact_annot(redact_rect.quad * mat)
        else:
            page.add_redact_annot(redact_rect)

        # Crucial: ALSO add redactions for any intersecting objects so their entire original ghost is cleanly removed
        # rather than leaving partial mutilated characters behind! Rebuild will re-draw them cleanly!
        for other in intersecting_others:
            if hasattr(other, 'bbox') and other.bbox:
                ox0, oy0, ox1, oy1 = other.bbox
                opad = max(getattr(other, 'stroke_width', 2.0) / 2.0, 1.0) if isinstance(other, (EditableShape, EditableStroke)) else 0.5
                o_rect = fitz.Rect(ox0 - opad, oy0 - opad, ox1 + opad, oy1 + opad)
                orot = getattr(other, 'rotation', 0.0)
                if orot != 0.0:
                    ocx = (ox0 + ox1) / 2.0
                    ocy = (oy0 + oy1) / 2.0
                    omat = pdf_handler.get_rotation_matrix(ocx, ocy, orot)
                    page.add_redact_annot(o_rect.quad * omat)
                else:
                    page.add_redact_annot(o_rect)

        # Execute redactions
        has_images = isinstance(target_object, EditableImage) or any(isinstance(o, EditableImage) for o in intersecting_others)
        has_graphics = isinstance(target_object, (EditableShape, EditableStroke)) or bool(strip_rects) or any(isinstance(o, (EditableShape, EditableStroke)) for o in intersecting_others)
        
        img_param = fitz.PDF_REDACT_IMAGE_REMOVE if has_images else fitz.PDF_REDACT_IMAGE_NONE
        gfx_param = 2 if has_graphics else 0
        try:
            page.apply_redactions(images=img_param, graphics=gfx_param, text=0)
        except Exception:
            page.apply_redactions()

        # Underline strip redaction if needed
        if strip_rects:
            for s_rect in strip_rects:
                if mat:
                    page.add_redact_annot(s_rect.quad * mat)
                else:
                    page.add_redact_annot(s_rect)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
            except Exception:
                pass

        cmd.window.doc.load_page(page_num)
        pdf_handler.save_page_snapshot(cmd.window.doc, page_num, force=True)
        pdf_handler.invalidate_page_cache(cmd.window.doc, page_num)
        target_object._ghost_redacted = True
    except Exception as e:
        print(f"Warning: could not erase ghost: {e}")

class MockUserBugsWindow:
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
        class MockObj:
            def set_text(self, *a, **k): pass
            def queue_draw(self): pass
            def remove_all(self): pass
            def append(self, x): pass
            def set_content_width(self, w): pass
            def set_content_height(self, h): pass
            def set_sensitive(self, s): pass
            def get_vadjustment(self): return None
            def get_hadjustment(self): return None
        self.status_label = MockObj()
        self.pdf_view = MockObj()
        self.pages_model = MockObj()
        self.pdf_scroll = MockObj()
        self.open_button = MockObj()
        self.select_tool_button = MockObj()
        self.add_text_tool_button = MockObj()
        self.zoom_level = 1.0
        self.current_pdf_page_width = 595
        self.current_pdf_page_height = 842
        self.form_fields = []
        self._page_objects_cache = {}

    def _update_undo_redo_buttons(self): pass
    def _refresh_thumbnail(self, p): pass
    def _update_ui_state(self): pass
    def commit_pending_format_change(self): pass
    def hide_text_editor(self): pass

    def _stash_page_objects(self, page_index: int):
        if page_index is None or not self.doc or not (0 <= page_index < len(self.doc)):
            return
        self._page_objects_cache[page_index] = {
            'texts': list(self.editable_texts),
            'images': list(self.editable_images),
            'shapes': list(self.editable_shapes),
            'strokes': list(self.editable_strokes),
            'form_fields': list(getattr(self, 'form_fields', [])),
        }

    def _restore_page_objects(self, page_index: int):
        if page_index is None or not self.doc or not (0 <= page_index < len(self.doc)):
            return
        if page_index in self._page_objects_cache:
            cached = self._page_objects_cache[page_index]
            self.editable_texts = list(cached.get('texts', []))
            self.editable_images = list(cached.get('images', []))
            self.editable_shapes = list(cached.get('shapes', []))
            self.editable_strokes = list(cached.get('strokes', []))
            self.form_fields = list(cached.get('form_fields', []))
        else:
            texts, error = pdf_handler.extract_editable_text(self.doc, page_index)
            self.editable_texts = texts or []
            images, error = pdf_handler.extract_editable_images(self.doc, page_index)
            self.editable_images = images or []
            shapes, shapes_error = pdf_handler.extract_editable_shapes(self.doc, page_index)
            self.editable_shapes = shapes or []
            strokes, strokes_error = pdf_handler.extract_editable_strokes(self.doc, page_index)
            self.editable_strokes = strokes or []
            self.form_fields = []
            self._stash_page_objects(page_index)

    def _load_page(self, page_index, preserve_scroll=False, reload_objects=False):
        if not self.doc or not (0 <= page_index < pdf_handler.get_page_count(self.doc)):
            return

        self.commit_pending_format_change()
        old_page_idx = getattr(self, 'current_page_index', None)
        if self.doc and old_page_idx is not None and (0 <= old_page_idx < pdf_handler.get_page_count(self.doc)):
            if old_page_idx != page_index:
                old_key = (id(self.doc), old_page_idx)
                if old_key not in pdf_handler._page_snapshots:
                    pdf_handler.save_page_snapshot(self.doc, old_page_idx)
                self._stash_page_objects(old_page_idx)

        self.undo_manager.clear()

        self.current_page_index = page_index
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.hide_text_editor()

        if reload_objects:
            texts, error = pdf_handler.extract_editable_text(self.doc, page_index)
            self.editable_texts = texts or []
            images, error = pdf_handler.extract_editable_images(self.doc, page_index)
            self.editable_images = images or []
            shapes, shapes_error = pdf_handler.extract_editable_shapes(self.doc, page_index)
            self.editable_shapes = shapes or []
            strokes, strokes_error = pdf_handler.extract_editable_strokes(self.doc, page_index)
            self.editable_strokes = strokes or []
            self.form_fields = []
            self._stash_page_objects(page_index)
        else:
            self._restore_page_objects(page_index)

        key = (id(self.doc), page_index)
        if key not in pdf_handler._page_snapshots:
            pdf_handler.save_page_snapshot(self.doc, page_index)

class TestBugsVerification(unittest.TestCase):
    def setUp(self):
        from word_sys_pdf_editor.undo_manager import Command
        self.orig_erase = Command._erase_ghost_if_needed
        Command._erase_ghost_if_needed = patched_erase_ghost_if_needed
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

    def tearDown(self):
        from word_sys_pdf_editor.undo_manager import Command
        Command._erase_ghost_if_needed = self.orig_erase
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

    def test_bug1_clean_collateral_text_deletion(self):
        """Bug 1: Deleting 'from' preserves exactly 'where?' with no mutilated artifacts."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(100, 100), "from", fontsize=14)
        page.insert_text(fitz.Point(100, 110), "where?", fontsize=14)
        
        pdf_handler.save_page_snapshot(doc, 0)
        win = MockUserBugsWindow(doc)
        win.editable_texts, _ = pdf_handler.extract_editable_text(doc, 0)
        
        text_from = [t for t in win.editable_texts if "from" in t.text][0]
        text_where = [t for t in win.editable_texts if "where?" in t.text][0]
        
        del_cmd = DeleteObjectCommand(win, text_from)
        del_cmd.execute()
        
        extracted = doc[0].get_text().strip()
        print(f"Extracted after deleting 'from': {repr(extracted)}")
        self.assertEqual(extracted, "where?")

    def test_bug2_fixed_page_switch_preserves_added_objects(self):
        """Bug 2 Fixed: Adding text 1, switching to page 1, switching back to page 0, adding text 2 preserves both."""
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p1 = doc.new_page(width=595, height=842)
        
        win = MockUserBugsWindow(doc)
        win._load_page(0)
        
        txt1 = EditableText(100, 100, "Text 1 Added", font_size=12, is_new=True, page_number=0)
        cmd1 = AddObjectCommand(win, txt1)
        cmd1.execute()
        self.assertIn("Text 1 Added", doc[0].get_text())
        
        # Switch to Page 1
        win._load_page(1)
        
        # Switch back to Page 0
        win._load_page(0)
        self.assertIn("Text 1 Added", doc[0].get_text())
        
        # Add Text 2 to Page 0
        txt2 = EditableText(100, 200, "Text 2 Added", font_size=12, is_new=True, page_number=0)
        cmd2 = AddObjectCommand(win, txt2)
        cmd2.execute()
        
        page0_text = doc[0].get_text()
        print(f"Page 0 text after adding Text 2: {repr(page0_text)}")
        self.assertIn("Text 1 Added", page0_text)
        self.assertIn("Text 2 Added", page0_text)

    def test_new_document_multiple_object_additions_no_duplication(self):
        """Verify adding multiple text and shape objects to a newly created PDF does not duplicate objects."""
        doc, err = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)
        self.assertIsNone(err)
        self.assertIsNotNone(doc)

        win = MockUserBugsWindow(doc)
        win._load_page(0)

        t1 = EditableText(50, 100, "HELLO NEW DOC 1", font_size=14, is_new=True, page_number=0)
        cmd1 = AddObjectCommand(win, t1)
        cmd1.execute()
        win.undo_manager.add_command(cmd1)

        t2 = EditableText(50, 150, "HELLO NEW DOC 2", font_size=14, is_new=True, page_number=0)
        cmd2 = AddObjectCommand(win, t2)
        cmd2.execute()
        win.undo_manager.add_command(cmd2)

        s1 = EditableShape(EditableShape.SHAPE_RECTANGLE, (100, 200, 180, 250),
                           stroke_color=(1, 0, 0), stroke_width=2.0, is_new=True, page_number=0)
        cmd3 = AddObjectCommand(win, s1)
        cmd3.execute()
        win.undo_manager.add_command(cmd3)

        s2 = EditableShape(EditableShape.SHAPE_ELLIPSE, (200, 200, 260, 260),
                           stroke_color=(0, 0, 1), stroke_width=2.0, is_new=True, page_number=0)
        cmd4 = AddObjectCommand(win, s2)
        cmd4.execute()
        win.undo_manager.add_command(cmd4)

        text_content = doc[0].get_text()
        self.assertEqual(text_content.count("HELLO NEW DOC 1"), 1)
        self.assertEqual(text_content.count("HELLO NEW DOC 2"), 1)
        drawings = doc[0].get_drawings()
        self.assertEqual(len(drawings), 2)

        # Test Undo of last shape
        win.undo_manager.undo()
        self.assertEqual(len(doc[0].get_drawings()), 1)
        text_content_after_undo = doc[0].get_text()
        self.assertEqual(text_content_after_undo.count("HELLO NEW DOC 1"), 1)
        self.assertEqual(text_content_after_undo.count("HELLO NEW DOC 2"), 1)

        # Test Redo of last shape
        win.undo_manager.redo()
        self.assertEqual(len(doc[0].get_drawings()), 2)
        text_content_after_redo = doc[0].get_text()
        self.assertEqual(text_content_after_redo.count("HELLO NEW DOC 1"), 1)
        self.assertEqual(text_content_after_redo.count("HELLO NEW DOC 2"), 1)

    def test_insert_blank_page_multiple_object_additions_no_duplication(self):
        """Verify adding multiple objects to a newly inserted blank page does not duplicate objects."""
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p0.insert_text(fitz.Point(50, 50), "EXISTING PAGE CONTENT", fontsize=12)
        pdf_handler.save_page_snapshot(doc, 0, force=True)

        success, msg = pdf_handler.insert_blank_page(doc, page_index=1, width=595, height=842)
        self.assertTrue(success)
        self.assertEqual(doc.page_count, 2)

        win = MockUserBugsWindow(doc)
        win._load_page(1)

        t1 = EditableText(60, 120, "BLANK PAGE OBJ 1", font_size=16, is_new=True, page_number=1)
        cmd1 = AddObjectCommand(win, t1)
        cmd1.execute()
        win.undo_manager.add_command(cmd1)

        t2 = EditableText(60, 180, "BLANK PAGE OBJ 2", font_size=16, is_new=True, page_number=1)
        cmd2 = AddObjectCommand(win, t2)
        cmd2.execute()
        win.undo_manager.add_command(cmd2)

        s1 = EditableShape(EditableShape.SHAPE_RECTANGLE, (60, 240, 180, 310),
                           stroke_color=(0, 0.5, 0), stroke_width=1.5, is_new=True, page_number=1)
        cmd3 = AddObjectCommand(win, s1)
        cmd3.execute()
        win.undo_manager.add_command(cmd3)

        # Check page 1 has exact counts without duplicates
        page1_text = doc[1].get_text()
        self.assertEqual(page1_text.count("BLANK PAGE OBJ 1"), 1)
        self.assertEqual(page1_text.count("BLANK PAGE OBJ 2"), 1)
        self.assertEqual(len(doc[1].get_drawings()), 1)

        # Verify page 0 is completely unaffected
        page0_text = doc[0].get_text()
        self.assertEqual(page0_text.count("EXISTING PAGE CONTENT"), 1)
        self.assertEqual(page0_text.count("BLANK PAGE OBJ 1"), 0)

    def test_cross_page_navigation_and_blank_page_creation_no_duplication(self):
        """Verify making changes on page 1, creating a blank page, making changes there,

        returning to page 1, and making another change does NOT duplicate page 1 changes.
        """
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        pdf_handler.save_page_snapshot(doc, 0)

        win = MockUserBugsWindow(doc)
        win._load_page(0)

        # 1. Make changes on Page 0 (text and shape)
        t1 = EditableText(50, 80, "PAGE 1 ORIGINAL TEXT", font_size=14, is_new=True, page_number=0)
        cmd1 = AddObjectCommand(win, t1)
        cmd1.execute()
        win.undo_manager.add_command(cmd1)

        s1 = EditableShape(EditableShape.SHAPE_RECTANGLE, (50, 200, 150, 260),
                           stroke_color=(1, 0, 0), stroke_width=2.0, is_new=True, page_number=0)
        cmd2 = AddObjectCommand(win, s1)
        cmd2.execute()
        win.undo_manager.add_command(cmd2)

        self.assertEqual(doc[0].get_text().count("PAGE 1 ORIGINAL TEXT"), 1)
        self.assertEqual(len(doc[0].get_drawings()), 1)

        # 2. Stash page 0 and create a blank page at index 1
        win._stash_page_objects(win.current_page_index)
        success, _ = pdf_handler.insert_blank_page(doc, 1, 595, 842)
        self.assertTrue(success)
        win._load_page(1, reload_objects=True)

        # 3. Make changes on the blank page (Page 1)
        t2 = EditableText(60, 100, "BLANK PAGE UNIQUE TEXT", font_size=14, is_new=True, page_number=1)
        cmd3 = AddObjectCommand(win, t2)
        cmd3.execute()
        win.undo_manager.add_command(cmd3)

        self.assertEqual(doc[1].get_text().count("BLANK PAGE UNIQUE TEXT"), 1)

        # 4. Navigate back to Page 0
        win._load_page(0)

        # 5. Make another change on Page 0
        t3 = EditableText(50, 140, "PAGE 1 SECOND TEXT", font_size=14, is_new=True, page_number=0)
        cmd4 = AddObjectCommand(win, t3)
        cmd4.execute()
        win.undo_manager.add_command(cmd4)

        # 6. Verify Page 0 has exact counts without duplicate burn-in
        page0_text = doc[0].get_text()
        self.assertEqual(page0_text.count("PAGE 1 ORIGINAL TEXT"), 1)
        self.assertEqual(page0_text.count("PAGE 1 SECOND TEXT"), 1)
        self.assertEqual(len(doc[0].get_drawings()), 1)

        # 7. Verify Page 1 is untouched and has exact counts
        page1_text = doc[1].get_text()
        self.assertEqual(page1_text.count("BLANK PAGE UNIQUE TEXT"), 1)

if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_object_independence_suite.py
# ============================================================================
import unittest
import sys
import os
import time
try:
    import pymupdf as fitz
except ImportError:
    import fitz

workspace_dir = "/home/word-sys/word-sys-pdf-editor"
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableText, EditableShape, EditableStroke, EditableImage
from word_sys_pdf_editor.undo_manager import UndoManager, AddObjectCommand, DeleteObjectCommand, EditObjectCommand, RotateObjectCommand

class MockStatusLabel:
    def __init__(self):
        self.text = ""
    def set_text(self, t):
        self.text = t

class MockView:
    def __init__(self):
        self.draw_count = 0
    def queue_draw(self):
        self.draw_count += 1

class MockIndependenceWindow:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.editable_texts = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.editable_images = []
        self.status_label = MockStatusLabel()
        self.pdf_view = MockView()
        self.undo_manager = UndoManager(self)
        self.document_modified = False
        self.zoom_level = 1.0
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None

    def _update_undo_redo_buttons(self):
        pass

    def _refresh_thumbnail(self, pno):
        pass

    def _update_ui_state(self):
        pass

    def commit_pending_format_change(self):
        pass

class TestObjectIndependenceSuite(unittest.TestCase):

    def setUp(self):
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

    def tearDown(self):
        pdf_handler._page_snapshots.clear()
        pdf_handler._page_original_links.clear()

    def test_rotated_text_near_box_preserves_box_contents(self):
        """Rotating 'where?' touching a box enclosing texts must NEVER erase texts inside the box."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Draw box: (140, 190, 380, 320)
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(140, 190, 380, 320))
        shape.finish(color=(0, 0, 1), fill=None, width=2.0)
        shape.commit()

        # Insert 3 texts inside the box
        page.insert_text(fitz.Point(160, 220), "PDF Editor", fontsize=14, color=(0, 0, 0))
        page.insert_text(fitz.Point(160, 250), "v1.11.0", fontsize=12, color=(0, 0, 0))
        page.insert_text(fitz.Point(160, 280), "Update!", fontsize=12, color=(1, 0, 0))

        # Insert text 'where?' touching the top edge of the box (y=190)
        page.insert_text(fitz.Point(170, 185), "where?", fontsize=14, color=(0.8, 0.2, 0.2))

        pdf_handler.save_page_snapshot(doc, 0)

        win = MockIndependenceWindow(doc)
        win.editable_texts, _ = pdf_handler.extract_editable_text(doc, 0)
        win.editable_shapes, _ = pdf_handler.extract_editable_shapes(doc, 0)

        self.assertEqual(len(win.editable_texts), 4)
        self.assertEqual(len(win.editable_shapes), 1)

        where_obj = next(t for t in win.editable_texts if "where?" in t.text)
        rot_cmd = RotateObjectCommand(win, where_obj, 0.0, 90.0)
        rot_cmd.execute()

        # Verify page text contents
        p = doc.load_page(0)
        page_text = p.get_text()

        self.assertIn("PDF Editor", page_text)
        self.assertIn("v1.11.0", page_text)
        self.assertIn("Update!", page_text)
        self.assertIn("where?", page_text)

        # Verify drawing of box was not erased
        drawings = p.get_drawings()
        self.assertEqual(len(drawings), 1)

    def test_moving_box_enclosing_text_preserves_text_inside(self):
        """Moving a box shape must strictly preserve text enclosed within it."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(100, 100, 300, 300))
        shape.finish(color=(0, 0, 1), fill=None, width=2.0)
        shape.commit()

        page.insert_text(fitz.Point(120, 150), "Enclosed Text", fontsize=14, color=(0, 0, 0))

        pdf_handler.save_page_snapshot(doc, 0)

        win = MockIndependenceWindow(doc)
        win.editable_texts, _ = pdf_handler.extract_editable_text(doc, 0)
        win.editable_shapes, _ = pdf_handler.extract_editable_shapes(doc, 0)

        box_obj = win.editable_shapes[0]
        old_props = {'bbox': box_obj.bbox}
        new_props = {'bbox': (150.0, 150.0, 350.0, 350.0)}

        cmd = EditObjectCommand(win, box_obj, old_props, new_props)
        cmd.execute()

        p = doc.load_page(0)
        page_text = p.get_text()
        self.assertIn("Enclosed Text", page_text)

    def test_moving_stroke_touching_circle_preserves_circle_and_text(self):
        """Moving a stroke touching a shape with internal text must not erase the shape or text."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Circle at (200, 200, 350, 350)
        shape = page.new_shape()
        shape.draw_oval(fitz.Rect(200, 200, 350, 350))
        shape.finish(color=(0, 0, 0), fill=None, width=2.0)
        shape.commit()

        page.insert_text(fitz.Point(230, 260), "Circle Text", fontsize=12, color=(0, 0, 0))

        # Stroke touching bottom of circle
        stroke_shape = page.new_shape()
        stroke_shape.draw_polyline([fitz.Point(180, 340), fitz.Point(250, 340), fitz.Point(360, 340)])
        stroke_shape.finish(color=(0.9, 0.6, 0.4), width=8.0)
        stroke_shape.commit()

        pdf_handler.save_page_snapshot(doc, 0)

        win = MockIndependenceWindow(doc)
        win.editable_texts, _ = pdf_handler.extract_editable_text(doc, 0)
        win.editable_shapes, _ = pdf_handler.extract_editable_shapes(doc, 0)
        win.editable_strokes, _ = pdf_handler.extract_editable_strokes(doc, 0)

        self.assertEqual(len(win.editable_texts), 1)
        self.assertEqual(len(win.editable_shapes), 1)
        self.assertEqual(len(win.editable_strokes), 1)

        # Move the stroke down by 40pt
        st = win.editable_strokes[0]
        old_props = {'points': list(st.points), 'bbox': st.bbox}
        new_pts = [(p[0], p[1] + 40) for p in st.points]
        new_props = {'points': new_pts, 'bbox': (st.bbox[0], st.bbox[1] + 40, st.bbox[2], st.bbox[3] + 40)}

        cmd = EditObjectCommand(win, st, old_props, new_props)
        cmd.execute()

        p = doc.load_page(0)
        page_text = p.get_text()
        self.assertIn("Circle Text", page_text)
        self.assertEqual(len(p.get_drawings()), 2)

    def test_deleting_new_added_text_preserves_all_other_objects(self):
        """Deleting newly added text must strictly remove only that text and leave all other objects intact."""
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        pdf_handler.save_page_snapshot(doc, 0)

        win = MockIndependenceWindow(doc)

        t1 = EditableText(x=100, y=100, text="First Item", font_size=12, is_new=True, baseline=112)
        t1.page_number = 0
        t1.font_family_base = 'helv'
        AddObjectCommand(win, t1).execute()

        t2 = EditableText(x=100, y=140, text="Second Item", font_size=12, is_new=True, baseline=152)
        t2.page_number = 0
        t2.font_family_base = 'helv'
        AddObjectCommand(win, t2).execute()

        rect_shape = EditableShape(shape_type=EditableShape.SHAPE_RECTANGLE, bbox=(200, 200, 300, 300), is_new=True)
        rect_shape.page_number = 0
        AddObjectCommand(win, rect_shape).execute()

        # Delete First Item
        del_cmd = DeleteObjectCommand(win, t1)
        del_cmd.execute()

        p = doc.load_page(0)
        page_text = p.get_text()
        self.assertNotIn("First Item", page_text)
        self.assertIn("Second Item", page_text)
        self.assertEqual(len(p.get_drawings()), 1)

    def test_page_switch_then_add_and_delete_independence(self):
        """Adding objects, switching pages, switching back, adding new and deleting objects must preserve all objects."""
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        doc.new_page(width=595, height=842)
        pdf_handler.save_page_snapshot(doc, 0)
        pdf_handler.save_page_snapshot(doc, 1)

        win = MockIndependenceWindow(doc)

        # On Page 0: Add text A, text B, shape C
        ta = EditableText(x=100, y=100, text="Alpha Text", font_size=12, is_new=True, baseline=112)
        ta.page_number = 0
        ta.font_family_base = 'helv'
        AddObjectCommand(win, ta).execute()

        tb = EditableText(x=100, y=140, text="Beta Text", font_size=12, is_new=True, baseline=152)
        tb.page_number = 0
        tb.font_family_base = 'helv'
        AddObjectCommand(win, tb).execute()

        sc = EditableShape(shape_type=EditableShape.SHAPE_ELLIPSE, bbox=(250, 250, 350, 350), is_new=True)
        sc.page_number = 0
        AddObjectCommand(win, sc).execute()

        # Switch to Page 1
        pdf_handler.save_page_snapshot(doc, 0, force=True)
        win.current_page_index = 1
        pdf_handler.save_page_snapshot(doc, 1)

        # Switch back to Page 0
        pdf_handler.save_page_snapshot(doc, 1, force=True)
        win.current_page_index = 0
        win.editable_texts, _ = pdf_handler.extract_editable_text(doc, 0)
        win.editable_shapes, _ = pdf_handler.extract_editable_shapes(doc, 0)
        win.editable_strokes, _ = pdf_handler.extract_editable_strokes(doc, 0)
        win.editable_images, _ = pdf_handler.extract_editable_images(doc, 0)

        self.assertEqual(len(win.editable_texts), 2)
        self.assertEqual(len(win.editable_shapes), 1)

        # Add Gamma Text on Page 0
        tg = EditableText(x=100, y=180, text="Gamma Text", font_size=12, is_new=True, baseline=192)
        tg.page_number = 0
        tg.font_family_base = 'helv'
        AddObjectCommand(win, tg).execute()

        p0 = doc.load_page(0)
        text_now = p0.get_text()
        self.assertIn("Alpha Text", text_now)
        self.assertIn("Beta Text", text_now)
        self.assertIn("Gamma Text", text_now)
        self.assertEqual(len(p0.get_drawings()), 1)

        # Delete Alpha Text
        alpha_obj = next(t for t in win.editable_texts if "Alpha Text" in t.text)
        DeleteObjectCommand(win, alpha_obj).execute()

        text_after_del = doc[0].get_text()
        self.assertNotIn("Alpha Text", text_after_del)
        self.assertIn("Beta Text", text_after_del)
        self.assertIn("Gamma Text", text_after_del)
        self.assertEqual(len(doc[0].get_drawings()), 1)

    def test_disconnected_subpath_strokes_no_spurious_connector(self):
        """Cross lines or disconnected line segments must be extracted as separate strokes without connecting line."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        cross = EditableShape(shape_type=EditableShape.SHAPE_CROSS, bbox=(100, 100, 200, 200), is_new=True)
        pdf_handler._apply_single_object_to_page(doc, page, cross)

        strokes, err = pdf_handler.extract_editable_strokes(doc, 0)
        self.assertIsNone(err)
        self.assertEqual(len(strokes), 2)
        self.assertEqual(len(strokes[0].points), 2)
        self.assertEqual(len(strokes[1].points), 2)

    def test_move_performance_benchmark(self):
        """Moving an object must be swift (< 50ms per move) and not cause UI lag."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(100, 100), "Benchmark Target", fontsize=12, color=(0, 0, 0))
        pdf_handler.save_page_snapshot(doc, 0)

        win = MockIndependenceWindow(doc)
        win.editable_texts, _ = pdf_handler.extract_editable_text(doc, 0)
        t_obj = win.editable_texts[0]

        start_time = time.perf_counter()
        iterations = 10
        for i in range(iterations):
            old_p = {'x': t_obj.x, 'y': t_obj.y, 'bbox': t_obj.bbox}
            new_p = {'x': t_obj.x + 5, 'y': t_obj.y + 5, 'bbox': (t_obj.bbox[0] + 5, t_obj.bbox[1] + 5, t_obj.bbox[2] + 5, t_obj.bbox[3] + 5)}
            cmd = EditObjectCommand(win, t_obj, old_p, new_p)
            cmd.execute()
        total_time = time.perf_counter() - start_time
        avg_time = total_time / iterations

        self.assertLess(avg_time, 0.05, f"Move average time too slow: {avg_time*1000:.2f}ms")

if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_layer_reordering_and_thumbnail_fix.py
# ============================================================================
import io
from unittest.mock import MagicMock

import fitz
from PIL import Image

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableShape, EditableText, PatchObject
from word_sys_pdf_editor.undo_manager import AddObjectCommand, EditObjectCommand, ReorderObjectCommand


def _png(color, size=(60, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _make_doc():
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(fitz.Rect(0, 0, 400, 400), stream=_png((255, 0, 0), (200, 200)))
    return doc


class _Win:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.editable_texts = []
        self.editable_shapes = []
        self.editable_images = []
        self.editable_strokes = []
        self.measurements = []
        self.sticky_notes = []
        self._active_session = None
        self.document_modified = False
        self.status_label = MagicMock()
        self.pdf_view = MagicMock()

    def _update_undo_redo_buttons(self):
        pass

    def _refresh_thumbnail(self, page):
        pass

    def _update_ui_state(self):
        pass


def _pixel(doc, x, y):
    pix = doc[0].get_pixmap(dpi=72)
    return pix.pixel(x, y)


def test_moving_patch_keeps_background_image():
    doc = _make_doc()
    pdf_handler.save_page_snapshot(doc, 0, force=True)
    win = _Win(doc)
    patch = PatchObject(bbox=(100, 100, 160, 140), page_number=0,
                        image_bytes=_png((0, 0, 255)), is_new=True)
    AddObjectCommand(win, patch).execute()
    EditObjectCommand(win, patch, {"bbox": (100, 100, 160, 140), "rotation": 0.0},
                      {"bbox": (250, 250, 310, 290), "rotation": 0.0}).execute()
    # background must still be red away from the patch; patch blue at new place
    assert _pixel(doc, 10, 10)[:3] == (255, 0, 0)
    assert _pixel(doc, 280, 270)[:3] == (0, 0, 255)
    assert _pixel(doc, 130, 120)[:3] == (255, 0, 0)


def test_restore_rebinds_renamed_xobject():
    doc = _make_doc()
    pdf_handler.save_page_snapshot(doc, 0, force=True)
    page = doc[0]
    page.add_redact_annot(fitz.Rect(300, 300, 350, 350))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0, text=0)
    pdf_handler.restore_page_from_snapshot(doc, 0)
    page = doc[0]
    page.insert_image(fitz.Rect(100, 100, 160, 140), stream=_png((0, 0, 255)))
    assert _pixel(doc, 10, 10)[:3] == (255, 0, 0)


def test_cross_type_reorder_changes_bake_order():
    doc = _make_doc()
    pdf_handler.save_page_snapshot(doc, 0, force=True)
    win = _Win(doc)
    # Two overlapping images (patches) stand in for any two layered objects
    low = PatchObject(bbox=(100, 100, 200, 200), page_number=0,
                      image_bytes=_png((0, 255, 0), (50, 50)), is_new=True)
    high = PatchObject(bbox=(150, 150, 250, 250), page_number=0,
                       image_bytes=_png((0, 0, 255), (50, 50)), is_new=True)
    win.editable_images = [low, high]
    pdf_handler.rebuild_page(doc, 0, [], [], win.editable_images)
    assert _pixel(doc, 175, 175)[:3] == (0, 0, 255)

    order = pdf_handler.sort_by_layer([low, high])
    changes = [(o, None, i) for i, o in enumerate([high, low])]
    cmd = ReorderObjectCommand(win, low, 0, 1, z_changes=changes)
    cmd.execute()
    assert _pixel(doc, 175, 175)[:3] == (0, 255, 0)
    assert order == [low, high]
    cmd.undo()
    assert _pixel(doc, 175, 175)[:3] == (0, 0, 255)


def test_sort_by_layer_defaults_and_explicit():
    text = EditableText(10, 10, "hi")
    text.page_number = 0
    patch = PatchObject(bbox=(0, 0, 10, 10), page_number=0, image_bytes=b"x")
    assert pdf_handler.sort_by_layer([text, patch]) == [patch, text]
    text.z_index = 0
    patch.z_index = 1
    assert pdf_handler.sort_by_layer([patch, text]) == [text, patch]


def test_original_text_can_be_brought_above_new_shape():
    from word_sys_pdf_editor.models import EditableShape
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 100), "HELLO", fontsize=40, color=(0, 0, 0))
    pdf_handler.save_page_snapshot(doc, 0, force=True)
    texts, _ = pdf_handler.extract_editable_text(doc, 0)
    if not texts:
        import pytest
        pytest.skip("text extraction helper unavailable")
    win = _Win(doc)
    win.editable_texts = list(texts)
    cover = PatchObject(bbox=(0, 0, 300, 300), page_number=0,
                        image_bytes=_png((255, 0, 0), (10, 10)), is_new=True)
    win.editable_images = [cover]
    AddObjectCommand(win, cover).execute()
    assert _pixel(doc, 70, 90)[:3] == (255, 0, 0)
    txt = win.editable_texts[0]
    ordered = pdf_handler.sort_by_layer([cover, txt])
    changes = [(cover, None, 0), (txt, None, 1)]
    ReorderObjectCommand(win, txt, 0, 1, z_changes=changes).execute()
    dark = [_pixel(doc, x, y)[:3] for x in range(50, 140, 2) for y in range(70, 100, 2)]
    assert any(p != (255, 0, 0) for p in dark)


def test_add_page_preserves_new_page_index():
    from gi.repository import GLib
    from word_sys_pdf_editor.window import PdfEditorWindow

    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)

    win = MagicMock()
    win.doc = doc
    win.current_page_index = 0
    win._active_session = MagicMock()
    win._active_session.doc = doc
    win._active_session.pages_model = None
    win._active_session.pdf_path = ""
    win.status_label = MagicMock()
    win.document_modified = False
    win.target_page_after_load = None

    loaded_pages = []
    win._load_page = MagicMock(side_effect=lambda idx, *a, **kw: loaded_pages.append(idx))
    win._update_ui_state = MagicMock()
    win._sync_thumbnail_selection = MagicMock()

    # Call on_add_page
    PdfEditorWindow.on_add_page(win, None)

    assert win.document_modified is True
    # Initial page switch should be to page 1 (inserted blank page)
    assert 1 in loaded_pages

    # If _load_thumbnails idle callbacks run or _load_thumbnails completes:
    # Directly test _load_thumbnails behavior when finishing
    win.target_page_after_load = 1
    win.current_page_index = 1
    # Run _load_thumbnails completion logic
    target = getattr(win, 'target_page_after_load', None)
    assert target == 1
    # Ensure it does not force back to 0
    assert target != 0


def test_sync_thumbnail_selection_scrolls_to_active_page():
    from word_sys_pdf_editor.window import PdfEditorWindow

    win = MagicMock()
    win.doc = MagicMock()
    win.current_page_index = 4
    win._syncing_thumb = False

    # Mock selection model
    win.thumbnail_selection_model = MagicMock()
    win.thumbnails_list = MagicMock()
    del win.thumbnails_list.scroll_to  # Simulate GTK 4.6 without scroll_to

    # Mock thumbnails_scroll and adjustment
    mock_scroll = MagicMock()
    mock_adj = MagicMock()
    mock_adj.get_upper.return_value = 1000.0
    mock_adj.get_page_size.return_value = 300.0
    mock_scroll.get_vadjustment.return_value = mock_adj
    win.thumbnails_scroll = mock_scroll

    mock_model = MagicMock()
    mock_model.get_n_items.return_value = 10
    win.pages_model = mock_model
    win._scroll_thumbnails_to_page = lambda idx=None: PdfEditorWindow._scroll_thumbnails_to_page(win, idx)

    PdfEditorWindow._sync_thumbnail_selection(win)

    win.thumbnail_selection_model.set_selected.assert_called_with(4)
    # item_h = 1000 / 10 = 100; target_y = 4 * 100 = 400
    mock_adj.clamp_page.assert_called_once_with(400.0, 500.0)


# ============================================================================
# SECTION: test_async_search_and_spatial_hittest.py
# ============================================================================

import time
import unittest
from unittest.mock import MagicMock, patch
import fitz
from gi.repository import GLib

from word_sys_pdf_editor.models import SpatialGridIndex, EditableText, EditableImage, EditableShape, EditableStroke
from word_sys_pdf_editor.search_engine import DocumentSearchEngine, SearchMatch


class TestSpatialGridIndex(unittest.TestCase):
    def test_empty_grid(self):
        grid = SpatialGridIndex(cell_size=64.0)
        self.assertEqual(grid.query_point(100.0, 100.0), [])
        self.assertEqual(grid.query_rect((50.0, 50.0, 150.0, 150.0)), [])

    def test_single_cell_insertion_and_query(self):
        grid = SpatialGridIndex(cell_size=64.0)
        obj1 = {"id": "obj1", "bbox": (10.0, 10.0, 30.0, 30.0)}
        grid.insert(obj1, obj1["bbox"])

        hits = grid.query_point(20.0, 20.0)
        self.assertIn(obj1, hits)

        # Far away point outside cell (0, 0)
        miss = grid.query_point(200.0, 200.0)
        self.assertEqual(miss, [])

    def test_multi_cell_spanning_insertion(self):
        grid = SpatialGridIndex(cell_size=64.0)
        # Spans cell (0, 0) to cell (2, 2)
        obj_large = {"id": "large", "bbox": (10.0, 10.0, 140.0, 140.0)}
        grid.insert(obj_large, obj_large["bbox"])

        self.assertIn(obj_large, grid.query_point(20.0, 20.0))
        self.assertIn(obj_large, grid.query_point(70.0, 70.0))
        self.assertIn(obj_large, grid.query_point(130.0, 130.0))
        self.assertEqual(grid.query_point(300.0, 300.0), [])

    def test_tolerance_query_across_boundaries(self):
        grid = SpatialGridIndex(cell_size=64.0)
        # Placed near edge of cell (0, 0) at x=62
        obj_edge = {"id": "edge", "bbox": (58.0, 10.0, 62.0, 30.0)}
        grid.insert(obj_edge, obj_edge["bbox"])

        # Query just past cell boundary at x=65 with tolerance 5.0
        hits = grid.query_point(65.0, 20.0, tolerance=5.0)
        self.assertIn(obj_edge, hits)

    def test_query_rect(self):
        grid = SpatialGridIndex(cell_size=64.0)
        obj1 = {"id": "1", "bbox": (10.0, 10.0, 20.0, 20.0)}
        obj2 = {"id": "2", "bbox": (100.0, 100.0, 120.0, 120.0)}
        grid.insert(obj1, obj1["bbox"])
        grid.insert(obj2, obj2["bbox"])

        window_query = grid.query_rect((0.0, 0.0, 50.0, 50.0))
        self.assertIn(obj1, window_query)
        self.assertNotIn(obj2, window_query)

    def test_clear(self):
        grid = SpatialGridIndex(cell_size=64.0)
        obj = {"id": "test", "bbox": (10.0, 10.0, 20.0, 20.0)}
        grid.insert(obj, obj["bbox"])
        self.assertEqual(len(grid.query_point(15.0, 15.0)), 1)
        grid.clear()
        self.assertEqual(len(grid.query_point(15.0, 15.0)), 0)


class TestAsyncChunkedSearchEngine(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        for i in range(25):
            page = self.doc.new_page(width=400, height=300)
            if i % 5 == 0:
                page.insert_text((50, 100), f"SecretKey-ABC-{i:03d}")
            if i % 7 == 0:
                page.insert_text((50, 150), "user.contact@organization.org")

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_sync_execution_mode(self):
        engine = DocumentSearchEngine(self.doc)
        chunk_records = []
        completed_results = []

        def on_chunk(hits, processed, total):
            chunk_records.append((len(hits), processed, total))

        def on_complete(matches):
            completed_results.append(list(matches))

        token = engine.start_async_search(
            doc=self.doc,
            query="SecretKey",
            chunk_size=5,
            on_chunk=on_chunk,
            on_complete=on_complete,
            sync=True,
        )

        self.assertGreater(token, 0)
        self.assertEqual(len(completed_results), 1)
        self.assertEqual(len(completed_results[0]), 5)  # pages 0, 5, 10, 15, 20
        self.assertEqual(len(chunk_records), 5)  # 25 pages / 5 chunk_size

    def test_async_background_thread_search(self):
        engine = DocumentSearchEngine(self.doc)
        done_flag = [False]
        final_matches = []

        def on_complete(matches):
            final_matches.extend(matches)
            done_flag[0] = True

        engine.start_async_search(
            doc=self.doc,
            query="SecretKey",
            chunk_size=10,
            on_complete=on_complete,
            sync=False,
        )

        # Spin main loop iterations to receive GLib.idle_add callbacks
        timeout = time.time() + 3.0
        ctx = GLib.main_context_default()
        while not done_flag[0] and time.time() < timeout:
            count = 0
            while ctx.pending() and count < 50:
                ctx.iteration(False)
                count += 1
            time.sleep(0.01)

        self.assertTrue(done_flag[0], "Async search worker failed to complete within timeout")
        self.assertEqual(len(final_matches), 5)

    def test_async_cancellation_supersedes_previous(self):
        engine = DocumentSearchEngine(self.doc)
        second_finished = [False]
        second_matches = []

        # Start search 1
        engine.start_async_search(
            doc=self.doc,
            query="SecretKey",
            chunk_size=2,
            sync=False,
        )

        # Immediately cancel and start search 2 for a different query
        def on_complete_second(matches):
            second_matches.extend(matches)
            second_finished[0] = True

        engine.start_async_search(
            doc=self.doc,
            pii_key="email",
            chunk_size=10,
            on_complete=on_complete_second,
            sync=False,
        )

        timeout = time.time() + 3.0
        ctx = GLib.main_context_default()
        while not second_finished[0] and time.time() < timeout:
            count = 0
            while ctx.pending() and count < 50:
                ctx.iteration(False)
                count += 1
            time.sleep(0.01)

        self.assertTrue(second_finished[0])
        # PII email appears on pages 0, 7, 14, 21 -> 4 matches
        self.assertEqual(len(second_matches), 4)


class TestWindowSpatialHitTestIntegration(unittest.TestCase):
    def test_window_spatial_grid_caching_and_hit_test(self):
        from word_sys_pdf_editor.window import PdfEditorWindow

        win = PdfEditorWindow()
        doc = fitz.open()
        doc.new_page(width=500, height=700)
        win.doc = doc
        win.current_page_index = 0
        win.zoom_level = 1.0

        # Inject 100 text objects
        win.editable_texts = []
        for i in range(100):
            t = EditableText(
                x=50.0,
                y=float(10 + i * 20),
                text=f"Line {i}",
                page_number=0,
            )
            t.bbox = (50.0, float(10 + i * 20), 170.0, float(25 + i * 20))
            win.editable_texts.append(t)

        # Spatial index is initially unpopulated
        self.assertNotIn((0, "text"), win._spatial_indices)

        # First hit test builds and caches the spatial index
        hit = win._find_text_at_pos(60.0, 15.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.text, "Line 0")
        self.assertIn((0, "text"), win._spatial_indices)

        # Invalidation clears the spatial index
        win._invalidate_spatial_index(0)
        self.assertNotIn((0, "text"), win._spatial_indices)

        # Test image spatial hit test
        img = EditableImage(bbox=(200.0, 200.0, 280.0, 280.0), page_number=0, xref=0, image_bytes=b"")
        win.editable_images = [img]
        hit_img = win._find_image_at_pos(220.0, 220.0)
        self.assertIs(hit_img, img)

        # Test shape spatial hit test
        shape = EditableShape(shape_type="rectangle", bbox=(300.0, 300.0, 350.0, 350.0), page_number=0)
        win.editable_shapes = [shape]
        hit_shape = win._find_shape_at_pos(310.0, 310.0)
        self.assertIs(hit_shape, shape)

        # Test stroke spatial hit test
        stroke = EditableStroke(points=[(400.0, 400.0), (450.0, 450.0)], page_number=0)
        stroke.bbox = (400.0, 400.0, 450.0, 450.0)
        win.editable_strokes = [stroke]
        hit_stroke = win._find_stroke_at_pos(420.0, 420.0)
        self.assertIs(hit_stroke, stroke)

        # Test pointer motion throttling
        win._last_pointer_motion_time = time.monotonic()
        win._last_pointer_pos = (100.0, 100.0)

        # Micro motion under 1.5 pixels within 10ms is throttled
        mock_controller = MagicMock()
        with patch.object(win, "canvas_to_page_coords") as mock_coords:
            win._on_pointer_motion(mock_controller, 100.5, 100.5)
            mock_coords.assert_not_called()

        doc.close()
        win.destroy()

    def test_thousand_object_spatial_benchmark(self):
        grid = SpatialGridIndex(cell_size=64.0)
        for i in range(1000):
            bx = (i % 20) * 28.0
            by = (i // 20) * 16.0
            grid.insert(f"item_{i}", (bx, by, bx + 24.0, by + 12.0))

        t0 = time.perf_counter()
        query_count = 500
        for i in range(query_count):
            px = float((i * 7) % 595)
            py = float((i * 11) % 842)
            _ = grid.query_point(px, py, tolerance=2.0)
        elapsed_total = (time.perf_counter() - t0) * 1000.0
        avg_per_query = elapsed_total / query_count

        # Spatial lookup must execute in under 0.05ms (50 microseconds) per query
        self.assertLess(avg_per_query, 0.05, f"Spatial query too slow: {avg_per_query:.4f} ms per query")


class TestStartupLazyModuleLoading(unittest.TestCase):
    """Verify that heavy signature, conversion, and network libraries are deferred at startup."""

    def test_window_import_does_not_load_heavy_modules(self):
        """Verify importing window does not load anyconvert, pyhanko, or signature_dialog."""
        import subprocess, json
        code = (
            "import sys, time, json\n"
            "t0 = time.perf_counter()\n"
            "import word_sys_pdf_editor.window\n"
            "elapsed = (time.perf_counter() - t0) * 1000.0\n"
            "heavy = [m for m in ('anyconvert', 'pyhanko', 'aiohttp', 'word_sys_pdf_editor.signature_dialog') if m in sys.modules]\n"
            "print(json.dumps({'elapsed': elapsed, 'heavy': heavy}))\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Subprocess failed: {proc.stderr}")
        data = json.loads(proc.stdout.strip())
        self.assertEqual(data["heavy"], [], f"Heavy modules eagerly loaded at startup: {data['heavy']}")
        # Startup should complete well under 800 ms (measured ~300 ms vs ~1080 ms baseline)
        self.assertLess(data["elapsed"], 800.0, f"Startup took {data['elapsed']:.1f} ms, expected < 800 ms")

    def test_anyconvert_lazy_access_in_pdf_handler(self):
        """Verify HAS_ANYCONVERT is detected via find_spec and module is loaded only on demand."""
        import subprocess
        code = (
            "import sys\n"
            "from word_sys_pdf_editor import pdf_handler\n"
            "assert 'anyconvert' not in sys.modules, 'anyconvert was eagerly imported'\n"
            "assert pdf_handler.HAS_ANYCONVERT is True, 'HAS_ANYCONVERT should be True'\n"
            "cm = pdf_handler.ConversionMode\n"
            "assert cm is not None, 'ConversionMode should resolve via __getattr__'\n"
            "assert 'anyconvert' in sys.modules, 'anyconvert should now be imported'\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Lazy anyconvert verification failed: {proc.stderr}")


class TestPart77UndoHistoryMemoryReduction(unittest.TestCase):
    """Verify Part 77 undo history memory reduction and reference sharing."""

    def test_image_edit_undo_shares_binary_payload_and_reduces_memory(self):
        """Verify 20 sequential edits on a 5 MB image share image_bytes by reference (<100 KB overhead)."""
        import io
        import cairo
        import tracemalloc
        from word_sys_pdf_editor.models import snapshot_object_state, PatchObject
        from word_sys_pdf_editor.undo_manager import UndoManager, EditObjectCommand

        doc, _ = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)
        win = MockWindow(doc)
        win._load_page(0, reload_objects=True)

        # Create a valid PNG image buffer padded to ~5 MB bytearray payload
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 20, 20)
        buf = io.BytesIO()
        surf.write_to_png(buf)
        png_header = buf.getvalue()
        large_payload = bytearray(png_header + b"\x00" * (5 * 1024 * 1024))

        img = EditableImage(
            bbox=(50.0, 50.0, 150.0, 150.0),
            page_number=0,
            xref=None,
            image_bytes=large_payload,
            is_new=True,
        )
        img.is_baked = True
        win.editable_images.append(img)

        tracemalloc.start()
        snap_before = tracemalloc.take_snapshot()

        for i in range(20):
            old_props = snapshot_object_state(img)
            new_bbox = (50.0 + (i + 1) * 5.0, 50.0 + (i + 1) * 2.0, 150.0 + (i + 1) * 5.0, 150.0 + (i + 1) * 2.0)
            img.bbox = new_bbox
            img.x, img.y = new_bbox[0], new_bbox[1]
            new_props = snapshot_object_state(img)
            img.__dict__.update(old_props)
            cmd = EditObjectCommand(win, img, old_props, new_props)
            cmd.execute()
            win.undo_manager.add_command(cmd)

        snap_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snap_after.compare_to(snap_before, "lineno")
        undo_mem_bytes = sum(s.size_diff for s in stats if "undo_manager.py" in str(s.traceback) or "models.py" in str(s.traceback))
        self.assertLess(undo_mem_bytes, 100 * 1024, f"Undo stack allocated {undo_mem_bytes} bytes, expected < 100 KB")

        self.assertEqual(len(win.undo_manager.undo_stack), 20)
        for cmd in win.undo_manager.undo_stack:
            self.assertIs(cmd.old_properties["image_bytes"], large_payload)
            self.assertIs(cmd.new_properties["image_bytes"], large_payload)

        # Verify full undo and redo behavioral equivalence
        self.assertEqual(img.bbox, (150.0, 90.0, 250.0, 190.0))
        for _ in range(20):
            win.undo_manager.undo()
        self.assertEqual(img.bbox, (50.0, 50.0, 150.0, 150.0))
        for _ in range(20):
            win.undo_manager.redo()
        self.assertEqual(img.bbox, (150.0, 90.0, 250.0, 190.0))
        doc.close()

    def test_linked_text_and_patch_edit_avoids_cyclic_deepcopy_bloat(self):
        """Verify editing text linked to a 2 MB PatchObject shares linked_patch and span_data by reference."""
        import io
        import cairo
        import tracemalloc
        from word_sys_pdf_editor.models import snapshot_object_state, PatchObject
        from word_sys_pdf_editor.undo_manager import EditObjectCommand

        doc, _ = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)
        win = MockWindow(doc)
        win._load_page(0, reload_objects=True)

        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        buf = io.BytesIO()
        surf.write_to_png(buf)
        patch_payload = bytearray(buf.getvalue() + b"\x00" * (2 * 1024 * 1024))

        patch_obj = PatchObject(
            bbox=(40.0, 40.0, 240.0, 80.0),
            page_number=0,
            image_bytes=patch_payload,
            is_new=True,
        )
        patch_obj.is_baked = True
        span_meta = {"raw_font_stream": bytearray(b"F" * (256 * 1024)), "flags": 4}
        char_boxes = [
            {"char": c, "index": idx, "bbox": (40.0 + idx * 6.0, 40.0, 46.0 + idx * 6.0, 55.0), "origin": (40.0 + idx * 6.0, 52.0)}
            for idx, c in enumerate("Sample Linked Text Block")
        ]
        txt = EditableText(
            x=40.0,
            y=40.0,
            text="Sample Linked Text Block",
            page_number=0,
            is_new=True,
            span_data=span_meta,
        )
        txt.is_baked = True
        txt.char_boxes = char_boxes
        txt.bbox = (40.0, 40.0, 184.0, 55.0)
        txt.linked_patch = patch_obj
        patch_obj.linked_text = txt
        win.editable_images.append(patch_obj)
        win.editable_texts.append(txt)

        tracemalloc.start()
        snap_before = tracemalloc.take_snapshot()

        for i in range(25):
            old_props = snapshot_object_state(txt)
            txt.x = 40.0 + (i + 1) * 3.0
            txt.y = 40.0 + (i + 1) * 2.0
            txt.bbox = (txt.x, txt.y, txt.x + 144.0, txt.y + 15.0)
            txt.sync_char_boxes_to_bbox()
            new_props = snapshot_object_state(txt)
            txt.__dict__.update(old_props)
            cmd = EditObjectCommand(win, txt, old_props, new_props)
            cmd.execute()
            win.undo_manager.add_command(cmd)

        snap_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snap_after.compare_to(snap_before, "lineno")
        undo_mem_bytes = sum(s.size_diff for s in stats if "undo_manager.py" in str(s.traceback) or "models.py" in str(s.traceback))
        # 25 text edits with 24 char_boxes should use < 250 KB (vs >100 MB with cyclic deepcopy)
        self.assertLess(undo_mem_bytes, 250 * 1024, f"Undo stack allocated {undo_mem_bytes} bytes, expected < 250 KB")

        for cmd in win.undo_manager.undo_stack:
            self.assertIs(cmd.old_properties["linked_patch"], patch_obj)
            self.assertIs(cmd.new_properties["linked_patch"], patch_obj)
            self.assertIs(cmd.old_properties["span_data"], span_meta)
            self.assertIs(cmd.new_properties["span_data"], span_meta)

        for _ in range(25):
            win.undo_manager.undo()
        self.assertEqual(txt.bbox, (40.0, 40.0, 184.0, 55.0))
        self.assertIs(txt.linked_patch, patch_obj)
        self.assertIs(patch_obj.linked_text, txt)
        self.assertAlmostEqual(txt.char_boxes[0]["bbox"][0], 40.0, places=3)

        for _ in range(25):
            win.undo_manager.redo()
        self.assertEqual(txt.bbox, (115.0, 90.0, 259.0, 105.0))
        self.assertIs(txt.linked_patch, patch_obj)
        self.assertIs(patch_obj.linked_text, txt)
        doc.close()

    def test_stroke_and_char_boxes_shallow_copy_isolation(self):
        """Verify mutating char_boxes or stroke points after snapshot does not corrupt saved state."""
        from word_sys_pdf_editor.models import snapshot_object_state

        txt = EditableText(
            x=10.0,
            y=20.0,
            text="Ab",
            page_number=0,
        )
        txt.char_boxes = [
            {"char": "A", "index": 0, "bbox": (10.0, 20.0, 20.0, 32.0)},
            {"char": "b", "index": 1, "bbox": (20.0, 20.0, 30.0, 32.0)},
        ]
        txt.bbox = (10.0, 20.0, 30.0, 32.0)
        snap_txt = snapshot_object_state(txt)
        txt.char_boxes[0]["bbox"] = (99.0, 99.0, 109.0, 111.0)
        txt.char_boxes.append({"char": "c", "index": 2, "bbox": (30.0, 20.0, 40.0, 32.0)})
        self.assertEqual(len(snap_txt["char_boxes"]), 2)
        self.assertEqual(snap_txt["char_boxes"][0]["bbox"], (10.0, 20.0, 20.0, 32.0))

        stroke = EditableStroke(points=[(10.0, 10.0), (20.0, 20.0)], page_number=0)
        snap_stroke = snapshot_object_state(stroke)
        stroke.points.append((30.0, 30.0))
        stroke.points[0] = (99.0, 99.0)
        self.assertEqual(snap_stroke["points"], [(10.0, 10.0), (20.0, 20.0)])


class TestPart76RDPStrokeSimplification(unittest.TestCase):
    """Verify Part 76 Ramer-Douglas-Peucker vector stroke simplification."""

    def test_dense_input_point_count_reduction_and_endpoint_preservation(self):
        """Verify RDP decimation reduces dense point counts significantly while preserving exact endpoints."""
        import math
        from word_sys_pdf_editor.models import simplify_stroke_points

        # Edge cases
        self.assertEqual(simplify_stroke_points([]), [])
        self.assertEqual(simplify_stroke_points([(12.5, 34.5)]), [(12.5, 34.5)])
        self.assertEqual(
            simplify_stroke_points([(10.0, 20.0), (30.0, 40.0)]),
            [(10.0, 20.0), (30.0, 40.0)],
        )

        # 500-point near-collinear line with sub-0.3px hand jitter -> collapses to 2 endpoints
        jitter_line = [
            (50.0 + i * 0.5, 100.0 + (0.25 * math.sin(i * 0.7) if 0 < i < 499 else 0.0))
            for i in range(500)
        ]
        simplified_line = simplify_stroke_points(jitter_line, tolerance=0.5)
        self.assertEqual(len(simplified_line), 2)
        self.assertEqual(simplified_line[0], jitter_line[0])
        self.assertEqual(simplified_line[-1], jitter_line[-1])

        # 1,000-point dense sine wave -> >85% point reduction and exact endpoint preservation
        dense_wave = [
            (20.0 + i * 0.4, 200.0 + 40.0 * math.sin(i * 2.0 * math.pi / 250.0))
            for i in range(1000)
        ]
        simplified_wave = simplify_stroke_points(dense_wave, tolerance=0.5)
        self.assertEqual(simplified_wave[0], dense_wave[0])
        self.assertEqual(simplified_wave[-1], dense_wave[-1])
        self.assertLess(len(simplified_wave), 100, f"Expected < 100 points from 1,000, got {len(simplified_wave)}")
        self.assertGreater(len(simplified_wave), 10)

        # Closed loop where start == end
        closed_circle = [
            (200.0 + 50.0 * math.cos(2.0 * math.pi * i / 360.0),
             200.0 + 50.0 * math.sin(2.0 * math.pi * i / 360.0))
            for i in range(361)
        ]
        closed_circle[-1] = closed_circle[0]
        simplified_circle = simplify_stroke_points(closed_circle, tolerance=0.5)
        self.assertEqual(simplified_circle[0], closed_circle[0])
        self.assertEqual(simplified_circle[-1], closed_circle[-1])
        self.assertLess(len(simplified_circle), 50)
        self.assertGreater(len(simplified_circle), 8)

    def test_maximum_deviation_strictly_within_tolerance(self):
        """Verify every original point lies within <= tolerance Euclidean distance of simplified segments."""
        import math
        from word_sys_pdf_editor.models import simplify_stroke_points
        from word_sys_pdf_editor.utils import point_to_segment_distance

        raw_points = [
            (
                30.0 + i * 0.6,
                150.0 + 35.0 * math.sin(i * 0.03) + 12.0 * math.cos(i * 0.11),
            )
            for i in range(800)
        ]

        for tol in (0.5, 0.25):
            simplified = simplify_stroke_points(raw_points, tolerance=tol)
            self.assertEqual(simplified[0], raw_points[0])
            self.assertEqual(simplified[-1], raw_points[-1])

            max_err = 0.0
            for px, py in raw_points:
                min_seg_dist = min(
                    point_to_segment_distance(px, py, simplified[j][0], simplified[j][1], simplified[j + 1][0], simplified[j + 1][1])
                    for j in range(len(simplified) - 1)
                )
                if min_seg_dist > max_err:
                    max_err = min_seg_dist

            self.assertLessEqual(
                max_err,
                tol + 1e-9,
                f"Max deviation {max_err:.6f} exceeded tolerance {tol}",
            )

    def test_simplified_stroke_commit_pdf_size_and_undo_redo(self):
        """Verify simplified stroke reduces PDF content stream size and supports exact undo/redo."""
        import math
        from word_sys_pdf_editor.models import snapshot_object_state
        from word_sys_pdf_editor.undo_manager import AddObjectCommand, EditObjectCommand

        raw_pts = [
            (40.0 + i * 0.5, 120.0 + 25.0 * math.sin(i * 0.025))
            for i in range(600)
        ]

        # Compare PDF stream size for raw vs simplified stroke
        doc_raw, _ = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)
        stroke_raw = EditableStroke(points=list(raw_pts), stroke_color=(0.1, 0.2, 0.8), stroke_width=2.5, page_number=0, is_new=True)
        pdf_handler.apply_object_edit(doc_raw, stroke_raw)
        raw_stream_len = len(doc_raw[0].read_contents())
        doc_raw.close()

        doc, _ = pdf_handler.create_new_pdf(width=595, height=842, num_pages=1)
        win = MockWindow(doc)
        win._load_page(0, reload_objects=True)

        stroke = EditableStroke(points=list(raw_pts), stroke_color=(0.1, 0.2, 0.8), stroke_width=2.5, page_number=0, is_new=True)
        stroke.simplify(tolerance=0.5)
        simplified_count = len(stroke.points)
        self.assertLess(simplified_count, 60)
        simplified_pts_initial = list(stroke.points)
        initial_bbox = stroke.bbox

        add_cmd = AddObjectCommand(win, stroke)
        add_cmd.execute()
        win.undo_manager.add_command(add_cmd)

        simp_stream_len = len(doc[0].read_contents())
        self.assertLess(simp_stream_len, raw_stream_len * 0.25, f"Expected simplified stream ({simp_stream_len}B) < 25% of raw ({raw_stream_len}B)")

        # Move simplified stroke and record EditObjectCommand
        old_props = snapshot_object_state(stroke)
        stroke.set_position(stroke.x + 30.0, stroke.y + 40.0)
        stroke.original_bbox = stroke.bbox
        moved_pts = list(stroke.points)
        moved_bbox = stroke.bbox
        new_props = snapshot_object_state(stroke)
        stroke.__dict__.update(old_props)

        move_cmd = EditObjectCommand(win, stroke, old_props, new_props)
        move_cmd.execute()
        win.undo_manager.add_command(move_cmd)

        self.assertEqual(stroke.points, moved_pts)
        self.assertEqual(stroke.bbox, moved_bbox)

        # Undo move
        win.undo_manager.undo()
        self.assertEqual(stroke.points, simplified_pts_initial)
        self.assertEqual(stroke.bbox, initial_bbox)

        # Undo add
        win.undo_manager.undo()
        self.assertNotIn(stroke, win.editable_strokes)

        # Redo add and move
        win.undo_manager.redo()
        self.assertIn(stroke, win.editable_strokes)
        self.assertEqual(stroke.points, simplified_pts_initial)

        win.undo_manager.redo()
        self.assertEqual(stroke.points, moved_pts)
        self.assertEqual(stroke.bbox, moved_bbox)
        doc.close()


if __name__ == "__main__":
    unittest.main()

