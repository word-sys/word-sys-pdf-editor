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
        win = MockWindow(doc)
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
        
        win = MockWindow(doc)
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

if __name__ == '__main__':
    unittest.main()
