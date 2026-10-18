import unittest
import tempfile
import os

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from word_sys_pdf_editor.models import DocumentSession, EditableText, EditableShape, EditableStroke, AcroFormField
from word_sys_pdf_editor.window import PdfEditorWindow


def has_screen_display():
    return Gdk.Display.get_default() is not None


class MockContinuousScrollWindow:
    """Mock window for continuous vertical scroll layout unit testing."""
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.view_mode = False
        self._continuous_scroll_val = False
        self._fallback_page_objects_cache = {}
        self._active_session = None
        self.page_gap = 16
        self.continuous_page_offsets = []
        self.continuous_total_height = 0.0
        self.continuous_max_width = 0.0
        self.drag_start_page_index = 0
        self.current_pdf_page_width = 595
        self.current_pdf_page_height = 842
        self.editable_texts = []
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.form_fields = []
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.inline_editor_widget = None
        self.pdf_view = Gtk.DrawingArea()
        self.pdf_view.set_content_width(595)
        self.pdf_view.set_content_height(842)

    continuous_scroll = PdfEditorWindow.continuous_scroll
    _page_objects_cache = PdfEditorWindow._page_objects_cache
    _recompute_continuous_layout = PdfEditorWindow._recompute_continuous_layout
    _update_canvas_content_size = PdfEditorWindow._update_canvas_content_size
    get_page_canvas_rect = PdfEditorWindow.get_page_canvas_rect
    canvas_to_page_coords = PdfEditorWindow.canvas_to_page_coords
    page_to_canvas_coords = PdfEditorWindow.page_to_canvas_coords
    is_canvas_point_on_page = PdfEditorWindow.is_canvas_point_on_page
    _get_page_objects = PdfEditorWindow._get_page_objects
    _stash_page_objects = PdfEditorWindow._stash_page_objects
    _restore_page_objects = PdfEditorWindow._restore_page_objects
    _switch_active_page = PdfEditorWindow._switch_active_page
    _visual_to_unrotated_page_coords = PdfEditorWindow._visual_to_unrotated_page_coords
    _unrotated_to_visual_page_coords = PdfEditorWindow._unrotated_to_visual_page_coords
    _visual_to_unrotated_delta = PdfEditorWindow._visual_to_unrotated_delta

    def commit_pending_format_change(self):
        pass

    def hide_text_editor(self):
        pass

    def _clear_form_field_overlays(self):
        pass

    def _sync_thumbnail_selection(self):
        pass

    def _update_ui_state(self):
        pass

    def _create_form_field_overlays(self):
        pass


class TestContinuousScrollLayout(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pdf_path = os.path.join(self.temp_dir.name, "multi_page.pdf")
        doc = fitz.open()
        # Page 0: 600 x 800
        p0 = doc.new_page(width=600, height=800)
        p0.insert_text((50, 50), "Page 0 content")
        # Page 1: 500 x 700
        p1 = doc.new_page(width=500, height=700)
        p1.insert_text((50, 50), "Page 1 content")
        # Page 2: 650 x 900
        p2 = doc.new_page(width=650, height=900)
        p2.insert_text((50, 50), "Page 2 content")
        doc.save(self.pdf_path)
        doc.close()
        self.doc = fitz.open(self.pdf_path)

    def tearDown(self):
        if self.doc:
            self.doc.close()
        self.temp_dir.cleanup()

    def test_document_session_continuous_scroll_defaults(self):
        sess = DocumentSession()
        self.assertFalse(sess.continuous_scroll)
        self.assertIsInstance(sess.page_objects_cache, dict)
        self.assertEqual(len(sess.page_objects_cache), 0)

        sess.page_objects_cache[0] = {'texts': ['mock']}
        sess.close()
        self.assertEqual(len(sess.page_objects_cache), 0)

    def test_recompute_continuous_layout_offsets(self):
        win = MockContinuousScrollWindow(self.doc)
        win.zoom_level = 1.0
        win.page_gap = 16
        win._recompute_continuous_layout()

        self.assertEqual(len(win.continuous_page_offsets), 3)

        # Page 0: (x=0, y=16, w=600, h=800)
        p0 = win.continuous_page_offsets[0]
        self.assertEqual(p0[1], 16.0)
        self.assertEqual(p0[2], 600.0)
        self.assertEqual(p0[3], 800.0)

        # Page 1: (x=0, y=16 + 800 + 16 = 832, w=500, h=700)
        p1 = win.continuous_page_offsets[1]
        self.assertEqual(p1[1], 832.0)
        self.assertEqual(p1[2], 500.0)
        self.assertEqual(p1[3], 700.0)

        # Page 2: (x=0, y=832 + 700 + 16 = 1548, w=650, h=900)
        p2 = win.continuous_page_offsets[2]
        self.assertEqual(p2[1], 1548.0)
        self.assertEqual(p2[2], 650.0)
        self.assertEqual(p2[3], 900.0)

        # Total height: 1548 + 900 + 16 = 2464
        self.assertEqual(win.continuous_total_height, 2464.0)
        self.assertEqual(win.continuous_max_width, 650.0)

    def test_recompute_continuous_layout_zoomed(self):
        win = MockContinuousScrollWindow(self.doc)
        win.zoom_level = 1.5
        win.page_gap = 16
        win._recompute_continuous_layout()

        self.assertEqual(len(win.continuous_page_offsets), 3)
        p0 = win.continuous_page_offsets[0]
        self.assertEqual(p0[1], 16.0)
        self.assertAlmostEqual(p0[2], 600.0 * 1.5)
        self.assertAlmostEqual(p0[3], 800.0 * 1.5)

    def test_get_page_canvas_rect_continuous_mode(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0

        rect0 = win.get_page_canvas_rect(0)
        self.assertEqual(rect0[1], 16.0)
        self.assertEqual(rect0[2], 600.0)
        self.assertEqual(rect0[3], 800.0)

        rect1 = win.get_page_canvas_rect(1)
        self.assertEqual(rect1[1], 832.0)
        self.assertEqual(rect1[2], 500.0)
        self.assertEqual(rect1[3], 700.0)

        rect2 = win.get_page_canvas_rect(2)
        self.assertEqual(rect2[1], 1548.0)
        self.assertEqual(rect2[2], 650.0)
        self.assertEqual(rect2[3], 900.0)

    def test_get_page_canvas_rect_single_page_mode(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = False
        win.current_page_index = 0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800

        rect = win.get_page_canvas_rect(0)
        self.assertEqual(rect[2], 600.0)
        self.assertEqual(rect[3], 800.0)

    def test_canvas_to_page_coords_continuous_mode(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win._recompute_continuous_layout()

        # Canvas point on Page 0: y = 100
        px0, py0, pw0, ph0 = win.get_page_canvas_rect(0)
        page_idx, x_unzoomed, y_unzoomed = win.canvas_to_page_coords(px0 + 50.0, py0 + 100.0)
        self.assertEqual(page_idx, 0)
        self.assertAlmostEqual(x_unzoomed, 50.0)
        self.assertAlmostEqual(y_unzoomed, 100.0)

        # Canvas point on Page 1: y = 900
        px1, py1, pw1, ph1 = win.get_page_canvas_rect(1)
        page_idx, x_unzoomed, y_unzoomed = win.canvas_to_page_coords(px1 + 80.0, py1 + 120.0)
        self.assertEqual(page_idx, 1)
        self.assertAlmostEqual(x_unzoomed, 80.0)
        self.assertAlmostEqual(y_unzoomed, 120.0)

        # Canvas point on Page 2: y = 1600
        px2, py2, pw2, ph2 = win.get_page_canvas_rect(2)
        page_idx, x_unzoomed, y_unzoomed = win.canvas_to_page_coords(px2 + 40.0, py2 + 50.0)
        self.assertEqual(page_idx, 2)
        self.assertAlmostEqual(x_unzoomed, 40.0)
        self.assertAlmostEqual(y_unzoomed, 50.0)

        # Top margin before page 0
        page_idx, _, _ = win.canvas_to_page_coords(100.0, 5.0)
        self.assertEqual(page_idx, 0)

        # Bottom margin beyond last page
        page_idx, _, _ = win.canvas_to_page_coords(100.0, 3000.0)
        self.assertEqual(page_idx, 2)

    def test_page_to_canvas_coords_continuous_mode(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win._recompute_continuous_layout()

        px1, py1, _, _ = win.get_page_canvas_rect(1)
        cx, cy = win.page_to_canvas_coords(1, 45.0, 85.0)
        self.assertAlmostEqual(cx, px1 + 45.0)
        self.assertAlmostEqual(cy, py1 + 85.0)

    def test_is_canvas_point_on_page(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win._recompute_continuous_layout()

        px1, py1, pw1, ph1 = win.get_page_canvas_rect(1)
        # Inside page 1
        self.assertTrue(win.is_canvas_point_on_page(px1 + 10, py1 + 10, 1))
        # Not on page 0
        self.assertFalse(win.is_canvas_point_on_page(px1 + 10, py1 + 10, 0))
        # Gap between page 0 and 1: py0 + ph0 + 8
        px0, py0, pw0, ph0 = win.get_page_canvas_rect(0)
        gap_y = py0 + ph0 + 8.0
        self.assertFalse(win.is_canvas_point_on_page(px0 + 10, gap_y, 0))
        self.assertFalse(win.is_canvas_point_on_page(px0 + 10, gap_y, 1))

    def test_page_objects_stash_and_restore(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.current_page_index = 0

        txt0 = EditableText(x=10, y=10, text="Edited P0", font_size=12, page_number=0)
        win.editable_texts = [txt0]

        # Stash page 0
        win._stash_page_objects(0)
        self.assertIn(0, win._page_objects_cache)
        self.assertEqual(win._page_objects_cache[0]['texts'][0].text, "Edited P0")

        # Simulate moving to page 1
        win.current_page_index = 1
        win.editable_texts = []

        txt1 = EditableText(x=20, y=20, text="Edited P1", font_size=14, page_number=1)
        win.editable_texts = [txt1]
        win._stash_page_objects(1)

        # Verify page 0 cached objects remain intact
        cached0 = win._get_page_objects(0)
        self.assertEqual(cached0['texts'][0].text, "Edited P0")

        # Restore page 0 into active collection
        win.current_page_index = 0
        win._restore_page_objects(0)
        self.assertEqual(len(win.editable_texts), 1)
        self.assertEqual(win.editable_texts[0].text, "Edited P0")

    def test_switch_active_page_preserves_objects(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.current_page_index = 0

        shape0 = EditableShape(shape_type=EditableShape.SHAPE_RECTANGLE, bbox=(10, 10, 50, 50), page_number=0)
        win.editable_shapes = [shape0]

        # Switch to page 1
        win._switch_active_page(1)
        self.assertEqual(win.current_page_index, 1)
        self.assertIn(0, win._page_objects_cache)
        self.assertEqual(len(win._page_objects_cache[0]['shapes']), 1)

        # Add shape on page 1
        shape1 = EditableShape(shape_type=EditableShape.SHAPE_ELLIPSE, bbox=(20, 20, 80, 80), page_number=1)
        win.editable_shapes = [shape1]

        # Switch back to page 0
        win._switch_active_page(0)
        self.assertEqual(win.current_page_index, 0)
        self.assertEqual(len(win.editable_shapes), 1)
        self.assertEqual(win.editable_shapes[0].shape_type, EditableShape.SHAPE_RECTANGLE)

        # Switch back to page 1
        win._switch_active_page(1)
        self.assertEqual(win.current_page_index, 1)
        self.assertEqual(len(win.editable_shapes), 1)
        self.assertEqual(win.editable_shapes[0].shape_type, EditableShape.SHAPE_ELLIPSE)

    @unittest.skipUnless(has_screen_display(), "Screen display not available (headless build environment)")
    def test_window_continuous_scroll_integration(self):
        app = Adw.Application(application_id="org.wordsys.test.continuous")
        app.register(None)

        win = PdfEditorWindow(application=app)
        doc = fitz.open(self.pdf_path)
        win._active_session.doc = doc
        win._active_session.pdf_path = self.pdf_path

        win.continuous_scroll = True
        self.assertTrue(win.continuous_scroll)
        self.assertTrue(win._active_session.continuous_scroll)

        win._recompute_continuous_layout()
        self.assertEqual(len(win.continuous_page_offsets), 3)

        rect0 = win.get_page_canvas_rect(0)
        rect1 = win.get_page_canvas_rect(1)
        self.assertGreater(rect1[1], rect0[1] + rect0[3])

        win.continuous_scroll = False
        self.assertFalse(win.continuous_scroll)
        self.assertFalse(win._active_session.continuous_scroll)


if __name__ == '__main__':
    unittest.main()
