import unittest
from unittest.mock import MagicMock, patch
import fitz

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

from word_sys_pdf_editor.models import EditableImage, EditableShape, EditableStroke
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.undo_manager import UndoManager


class TestProportionalTransformHandles(unittest.TestCase):
    """Test suite for proportional vs free-form transform handles and Shift modifier inversion."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)

        self.window = MagicMock()
        self.window.doc = self.doc
        self.window.current_page_index = 0
        self.window.zoom_level = 1.0
        self.window.view_mode = False
        self.window.pdf_view = MagicMock()
        self.window._shift_pressed = False

        self.window.calculate_resize_geometry = PdfEditorWindow.calculate_resize_geometry.__get__(self.window, PdfEditorWindow)
        self.window._handle_resize_update = PdfEditorWindow._handle_resize_update.__get__(self.window, PdfEditorWindow)
        self.window._visual_to_unrotated_delta = lambda dx, dy: (dx, dy)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_corner_handle_se_proportional_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # delta_x=40, delta_y=10. Dominant axis is width (+40 / 200 = 0.20)
        res = self.window.calculate_resize_geometry(start_bbox, "se", 40.0, 10.0, shift_pressed=False)
        x1, y1, x2, y2 = res
        self.assertEqual(x1, 100.0)
        self.assertEqual(y1, 100.0)
        self.assertEqual(x2, 340.0)
        self.assertEqual(y2, 220.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_corner_handle_nw_proportional_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # delta_x=-40, delta_y=-10. Expands top-left
        res = self.window.calculate_resize_geometry(start_bbox, "nw", -40.0, -10.0, shift_pressed=False)
        x1, y1, x2, y2 = res
        self.assertEqual(x2, 300.0)
        self.assertEqual(y2, 200.0)
        self.assertEqual(x1, 60.0)
        self.assertEqual(y1, 80.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_corner_handle_ne_proportional_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # delta_x=40, delta_y=-10. Bottom-left anchor (100.0, 200.0)
        res = self.window.calculate_resize_geometry(start_bbox, "ne", 40.0, -10.0, shift_pressed=False)
        x1, y1, x2, y2 = res
        self.assertEqual(x1, 100.0)
        self.assertEqual(y2, 200.0)
        self.assertEqual(x2, 340.0)
        self.assertEqual(y1, 80.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_corner_handle_sw_proportional_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # delta_x=-40, delta_y=10. Top-right anchor (300.0, 100.0)
        res = self.window.calculate_resize_geometry(start_bbox, "sw", -40.0, 10.0, shift_pressed=False)
        x1, y1, x2, y2 = res
        self.assertEqual(x2, 300.0)
        self.assertEqual(y1, 100.0)
        self.assertEqual(x1, 60.0)
        self.assertEqual(y2, 220.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_corner_handle_freeform_with_shift(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # Holding Shift inverts corner drag to free-form
        res = self.window.calculate_resize_geometry(start_bbox, "se", 40.0, 10.0, shift_pressed=True)
        x1, y1, x2, y2 = res
        self.assertEqual(x1, 100.0)
        self.assertEqual(y1, 100.0)
        self.assertEqual(x2, 340.0)
        self.assertEqual(y2, 210.0)
        # Aspect ratio changed from 2.0 to 240 / 110 (~2.18)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 240.0 / 110.0, places=2)

        res_nw = self.window.calculate_resize_geometry(start_bbox, "nw", -15.0, -30.0, shift_pressed=True)
        self.assertEqual(res_nw, (85.0, 70.0, 300.0, 200.0))

    def test_edge_handles_freeform_by_default(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)

        # Right edge: only width changes
        res_e = self.window.calculate_resize_geometry(start_bbox, "e", 50.0, 30.0, shift_pressed=False)
        self.assertEqual(res_e, (100.0, 100.0, 350.0, 200.0))

        # Left edge: only left bound changes
        res_w = self.window.calculate_resize_geometry(start_bbox, "w", -40.0, 10.0, shift_pressed=False)
        self.assertEqual(res_w, (60.0, 100.0, 300.0, 200.0))

        # Bottom edge: only height changes
        res_s = self.window.calculate_resize_geometry(start_bbox, "s", 25.0, 40.0, shift_pressed=False)
        self.assertEqual(res_s, (100.0, 100.0, 300.0, 240.0))

        # Top edge: only top bound changes
        res_n = self.window.calculate_resize_geometry(start_bbox, "n", 15.0, -30.0, shift_pressed=False)
        self.assertEqual(res_n, (100.0, 70.0, 300.0, 200.0))

    def test_edge_handles_proportional_with_shift(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)  # w=200, h=100, aspect=2.0

        # Right edge with Shift: expands width to 250, scales height to 125 centered on Y
        res_e = self.window.calculate_resize_geometry(start_bbox, "e", 50.0, 0.0, shift_pressed=True)
        x1, y1, x2, y2 = res_e
        self.assertEqual(x1, 100.0)
        self.assertEqual(x2, 350.0)
        self.assertEqual(y1, 87.5)
        self.assertEqual(y2, 212.5)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

        # Left edge with Shift: expands width to 250, scales height to 125 centered on Y
        res_w = self.window.calculate_resize_geometry(start_bbox, "w", -50.0, 0.0, shift_pressed=True)
        x1, y1, x2, y2 = res_w
        self.assertEqual(x1, 50.0)
        self.assertEqual(x2, 300.0)
        self.assertEqual(y1, 87.5)
        self.assertEqual(y2, 212.5)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

        # Bottom edge with Shift: expands height to 150, scales width to 300 centered on X
        res_s = self.window.calculate_resize_geometry(start_bbox, "s", 0.0, 50.0, shift_pressed=True)
        x1, y1, x2, y2 = res_s
        self.assertEqual(y1, 100.0)
        self.assertEqual(y2, 250.0)
        self.assertEqual(x1, 50.0)
        self.assertEqual(x2, 350.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

        # Top edge with Shift: expands height to 150, scales width to 300 centered on X
        res_n = self.window.calculate_resize_geometry(start_bbox, "n", 0.0, -50.0, shift_pressed=True)
        x1, y1, x2, y2 = res_n
        self.assertEqual(y1, 50.0)
        self.assertEqual(y2, 200.0)
        self.assertEqual(x1, 50.0)
        self.assertEqual(x2, 350.0)
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2.0, places=2)

    def test_min_size_clamping(self):
        start_bbox = (100.0, 100.0, 300.0, 200.0)
        # Inward drag beyond bounds
        res = self.window.calculate_resize_geometry(start_bbox, "se", -500.0, -500.0, shift_pressed=False, min_size=20.0)
        x1, y1, x2, y2 = res
        w = x2 - x1
        h = y2 - y1
        self.assertGreaterEqual(w, 20.0)
        self.assertGreaterEqual(h, 10.0)
        self.assertAlmostEqual(w / h, 2.0, places=2)

    def test_handle_resize_update_with_image_object(self):
        image = EditableImage(bbox=(50.0, 50.0, 250.0, 150.0), page_number=0, xref=None, image_bytes=b"dummy")
        self.window.resize_handle = "se"
        self.window.resize_start_bbox = image.bbox
        self.window.dragged_object = image

        # Perform proportional update
        self.window._handle_resize_update(40.0, 20.0)

        self.assertEqual(image.bbox, (50.0, 50.0, 290.0, 170.0))
        self.window.pdf_view.queue_draw.assert_called()

    def test_handle_resize_update_with_shift_gesture(self):
        image = EditableImage(bbox=(50.0, 50.0, 250.0, 150.0), page_number=0, xref=None, image_bytes=b"dummy")
        self.window.resize_handle = "se"
        self.window.resize_start_bbox = image.bbox
        self.window.dragged_object = image

        gesture = MagicMock()
        gesture.get_current_event_state.return_value = Gdk.ModifierType.SHIFT_MASK

        # Shift held -> corner drag becomes free-form
        self.window._handle_resize_update(40.0, 10.0, gesture=gesture)

        self.assertEqual(image.bbox, (50.0, 50.0, 290.0, 160.0))


if __name__ == "__main__":
    unittest.main()
