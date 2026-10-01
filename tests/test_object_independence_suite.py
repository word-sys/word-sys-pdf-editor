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

class MockWindow:
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

        win = MockWindow(doc)
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

        win = MockWindow(doc)
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

        win = MockWindow(doc)
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

        win = MockWindow(doc)

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

        win = MockWindow(doc)

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

        win = MockWindow(doc)
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
