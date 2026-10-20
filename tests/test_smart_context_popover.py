import unittest
from unittest.mock import MagicMock, patch
import os
import fitz

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

from word_sys_pdf_editor.models import (
    EditableText, EditableShape, EditableImage, MeasurementObject, StickyNoteObject
)
from word_sys_pdf_editor.window import PdfEditorWindow


class TestSmartContextPopover(unittest.TestCase):
    """Test suite for smart non-obstructive context menu and popover positioning."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        self.window = MagicMock(spec=PdfEditorWindow)
        self.window.doc = self.doc
        self.window.current_page_index = 0
        self.window.zoom_level = 1.0
        self.window.current_pdf_page_width = 600
        self.window.current_pdf_page_height = 800
        self.window.continuous_scroll = False

        # Bind methods under test from PdfEditorWindow
        self.window.get_page_canvas_rect = PdfEditorWindow.get_page_canvas_rect.__get__(self.window, PdfEditorWindow)
        self.window.get_visible_viewport_rect = PdfEditorWindow.get_visible_viewport_rect.__get__(self.window, PdfEditorWindow)
        self.window.get_object_canvas_rect = PdfEditorWindow.get_object_canvas_rect.__get__(self.window, PdfEditorWindow)
        self.window.calculate_smart_popover_placement = PdfEditorWindow.calculate_smart_popover_placement.__get__(self.window, PdfEditorWindow)

        # Mock drawing area and scroll
        mock_pdf_view = MagicMock()
        mock_pdf_view.get_allocated_width.return_value = 1000
        mock_pdf_view.get_allocated_height.return_value = 1000
        self.window.pdf_view = mock_pdf_view

        mock_pdf_scroll = MagicMock()
        mock_pdf_scroll.get_allocated_width.return_value = 1000
        mock_pdf_scroll.get_allocated_height.return_value = 1000
        mock_h_adj = MagicMock()
        mock_h_adj.get_value.return_value = 0.0
        mock_h_adj.get_page_size.return_value = 1000.0
        mock_v_adj = MagicMock()
        mock_v_adj.get_value.return_value = 0.0
        mock_v_adj.get_page_size.return_value = 1000.0
        mock_pdf_scroll.get_hadjustment.return_value = mock_h_adj
        mock_pdf_scroll.get_vadjustment.return_value = mock_v_adj
        self.window.pdf_scroll = mock_pdf_scroll

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_get_object_canvas_rect_editable_text(self):
        """Verify canvas rect calculation for EditableText centered in viewport."""
        text_obj = EditableText(
            50.0, 100.0,
            text="Hello World",
            page_number=0,
            span_data={"bbox": (50.0, 100.0, 250.0, 130.0)}
        )
        canvas_rect = self.window.get_object_canvas_rect(text_obj)
        self.assertIsNotNone(canvas_rect)
        cx, cy, cw, ch = canvas_rect

        # In 1000x1000 view with 600x800 page, page offsets are (200, 100)
        self.assertEqual(cx, 200 + 50)
        self.assertEqual(cy, 100 + 100)
        self.assertEqual(cw, 200)
        self.assertEqual(ch, 30)

    def test_get_object_canvas_rect_with_zoom(self):
        """Verify canvas rect calculation scales accurately with zoom level."""
        self.window.zoom_level = 1.5
        self.window.current_pdf_page_width = 900
        self.window.current_pdf_page_height = 1200
        # In 1000x1000 view with 900x1200 page: px = (1000-900)/2 = 50, py = max(0, -100) = 0
        text_obj = EditableText(
            40.0, 80.0,
            text="Zoomed Text",
            page_number=0,
            span_data={"bbox": (40.0, 80.0, 140.0, 100.0)}
        )
        cx, cy, cw, ch = self.window.get_object_canvas_rect(text_obj)
        self.assertEqual(cx, int(50 + 40 * 1.5))
        self.assertEqual(cy, int(0 + 80 * 1.5))
        self.assertEqual(cw, int(100 * 1.5))
        self.assertEqual(ch, int(20 * 1.5))

    def test_get_object_canvas_rect_rotated_page(self):
        """Verify canvas rect computation on a 90-degree rotated PDF page."""
        self.page.set_rotation(90)
        text_obj = EditableText(
            50.0, 100.0,
            text="Rotated Page Text",
            page_number=0,
            span_data={"bbox": (50.0, 100.0, 250.0, 130.0)}
        )
        canvas_rect = self.window.get_object_canvas_rect(text_obj)
        self.assertIsNotNone(canvas_rect)
        cx, cy, cw, ch = canvas_rect
        self.assertGreater(cw, 0)
        self.assertGreater(ch, 0)

    def test_get_object_canvas_rect_sticky_note(self):
        """Verify canvas rect calculation for StickyNoteObject."""
        note = StickyNoteObject(
            x=60.0,
            y=120.0,
            width=24.0,
            height=24.0,
            page_number=0
        )
        canvas_rect = self.window.get_object_canvas_rect(note)
        self.assertIsNotNone(canvas_rect)
        cx, cy, cw, ch = canvas_rect
        self.assertEqual(cx, 200 + 60)
        self.assertEqual(cy, 100 + 120)
        self.assertEqual(cw, 24)
        self.assertEqual(ch, 24)

    def test_get_object_canvas_rect_none(self):
        """Verify None is returned when object is None or has invalid bbox."""
        self.assertIsNone(self.window.get_object_canvas_rect(None))
        invalid_obj = object()
        self.assertIsNone(self.window.get_object_canvas_rect(invalid_obj))

    def test_smart_placement_prefers_right(self):
        """Verify popover prefers RIGHT position when ample clearance is available."""
        # Object at (100, 100) with size (150, 40) in a 1000x1000 viewport
        # Space right = 1000 - 250 = 750 (>= 240 + 8) -> PositionType.RIGHT
        anchor = (100, 100, 150, 40)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, estimated_size=(240, 300), margin=8)

        self.assertEqual(pos, Gtk.PositionType.RIGHT)
        # Pointing rect right edge must be anchor_x + anchor_w + margin
        self.assertEqual(rect.x + rect.width, 100 + 150 + 8)
        self.assertEqual(rect.x, 100 - 8)

    def test_smart_placement_flips_left_when_right_blocked(self):
        """Verify popover flips to LEFT when right window edge obstructs."""
        # Object at (800, 100) with size (150, 40) in a 1000x1000 viewport
        # Space right = 1000 - 950 = 50 (< 248)
        # Space left = 800 - 0 = 800 (>= 248) -> PositionType.LEFT
        anchor = (800, 100, 150, 40)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, estimated_size=(240, 300), margin=8)

        self.assertEqual(pos, Gtk.PositionType.LEFT)
        # Pointing rect left edge must be anchor_x - margin
        self.assertEqual(rect.x, 800 - 8)

    def test_smart_placement_flips_bottom_when_sides_blocked(self):
        """Verify popover places BOTTOM when wide element spans horizontal viewport."""
        # Wide title bar spanning from x=40 to x=960 (width 920) in 1000x1000 viewport
        # Space right = 1000 - 960 = 40 (< 248)
        # Space left = 40 - 0 = 40 (< 248)
        # Space bottom = 1000 - 140 = 860 (>= 308) -> PositionType.BOTTOM
        anchor = (40, 100, 920, 40)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, estimated_size=(240, 300), margin=8)

        self.assertEqual(pos, Gtk.PositionType.BOTTOM)
        # Pointing rect bottom edge must be anchor_y + anchor_h + margin
        self.assertEqual(rect.y + rect.height, 100 + 40 + 8)

    def test_smart_placement_flips_top_when_bottom_blocked(self):
        """Verify popover places TOP when wide element is near bottom of viewport."""
        # Wide title bar at y=850 in 1000x1000 viewport
        # Space right = 40, Space left = 40, Space bottom = 1000 - 890 = 110 (< 308)
        # Space top = 850 - 0 = 850 (>= 308) -> PositionType.TOP
        anchor = (40, 850, 920, 40)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, estimated_size=(240, 300), margin=8)

        self.assertEqual(pos, Gtk.PositionType.TOP)
        self.assertEqual(rect.y, 850 - 8)

    def test_smart_placement_tall_object_slice_around_click(self):
        """Verify tall object pointing rect is vertically restricted near click position."""
        # Tall multi-line text box: height 400px (100 to 500)
        # Clicked near line at y = 250
        anchor = (100, 100, 200, 400)
        click_pos = (180.0, 250.0)
        rect, pos = self.window.calculate_smart_popover_placement(anchor, click_pos=click_pos)

        self.assertEqual(pos, Gtk.PositionType.RIGHT)
        # Vertical range must be centered around 250 (+/- 20)
        self.assertEqual(rect.y, 230)
        self.assertEqual(rect.height, 40)
        # Horizontal span must encompass full width + margin
        self.assertEqual(rect.x, 100 - 8)
        self.assertEqual(rect.x + rect.width, 100 + 200 + 8)

    def test_smart_placement_empty_space_click(self):
        """Verify empty space click produces 1x1 pointing rect at cursor coordinates."""
        rect, pos = self.window.calculate_smart_popover_placement(None, click_pos=(350.0, 450.0))
        self.assertEqual(rect.x, 350)
        self.assertEqual(rect.y, 450)
        self.assertEqual(rect.width, 1)
        self.assertEqual(rect.height, 1)

    def test_continuous_scroll_offset_integration(self):
        """Verify smart placement on subsequent pages in continuous scroll layout."""
        self.doc.new_page(width=600, height=800)
        self.window.continuous_scroll = True
        self.window.continuous_page_offsets = [
            (0.0, 0.0, 600.0, 800.0),
            (0.0, 824.0, 600.0, 800.0),
        ]
        # Scrolled down to page 1
        h_adj = self.window.pdf_scroll.get_hadjustment()
        v_adj = self.window.pdf_scroll.get_vadjustment()
        v_adj.get_value.return_value = 800.0
        v_adj.get_page_size.return_value = 600.0

        text_page_1 = EditableText(
            50.0, 50.0,
            text="Page 1 Text",
            page_number=1,
            span_data={"bbox": (50.0, 50.0, 200.0, 80.0)}
        )
        canvas_rect = self.window.get_object_canvas_rect(text_page_1)
        self.assertIsNotNone(canvas_rect)
        cx, cy, cw, ch = canvas_rect
        # py = 824.0, cy = 824 + 50 = 874
        self.assertEqual(cy, 874)

        rect, pos = self.window.calculate_smart_popover_placement(canvas_rect)
        self.assertEqual(pos, Gtk.PositionType.RIGHT)
        self.assertEqual(rect.x + rect.width, cx + cw + 8)

    def test_get_object_canvas_rect_shape_and_image(self):
        """Verify canvas rect calculation for EditableShape and EditableImage."""
        shape = EditableShape(
            shape_type="rectangle",
            bbox=(30.0, 40.0, 180.0, 120.0),
            page_number=0
        )
        shape_rect = self.window.get_object_canvas_rect(shape)
        self.assertIsNotNone(shape_rect)
        self.assertEqual(shape_rect[2], 150)
        self.assertEqual(shape_rect[3], 80)

        image = EditableImage(
            bbox=(100.0, 150.0, 300.0, 350.0),
            page_number=0,
            xref=1,
            image_bytes=b""
        )
        img_rect = self.window.get_object_canvas_rect(image)
        self.assertIsNotNone(img_rect)
        self.assertEqual(img_rect[2], 200)
        self.assertEqual(img_rect[3], 200)

    def test_get_object_canvas_rect_measurement(self):
        """Verify canvas rect calculation for MeasurementObject."""
        meas = MeasurementObject(
            measurement_type=MeasurementObject.TYPE_DISTANCE,
            points=[(20.0, 30.0), (120.0, 80.0)],
            page_number=0
        )
        meas_rect = self.window.get_object_canvas_rect(meas)
        self.assertIsNotNone(meas_rect)
        self.assertGreater(meas_rect[2], 0)
        self.assertGreater(meas_rect[3], 0)

    def test_zero_collision_popover_body_with_text(self):
        """Mathematically verify that popover body never intersects text object bounding box."""
        # Text object box: [cx, cy, cw, ch] = [200, 300, 300, 40]
        anchor = (200, 300, 300, 40)
        est_w, est_h = 240, 280
        margin = 10

        # 1. Right placement
        rect_r, pos_r = self.window.calculate_smart_popover_placement(anchor, estimated_size=(est_w, est_h), margin=margin)
        self.assertEqual(pos_r, Gtk.PositionType.RIGHT)
        # Popover body starts at rect_r.x + rect_r.width:
        popover_body_left = rect_r.x + rect_r.width
        text_right = anchor[0] + anchor[2]
        self.assertGreater(popover_body_left, text_right)
        self.assertGreaterEqual(popover_body_left - text_right, margin)

        # 2. Left placement (near right edge)
        anchor_left = (750, 300, 200, 40)
        rect_l, pos_l = self.window.calculate_smart_popover_placement(anchor_left, estimated_size=(est_w, est_h), margin=margin)
        self.assertEqual(pos_l, Gtk.PositionType.LEFT)
        popover_body_right = rect_l.x
        text_left = anchor_left[0]
        self.assertLess(popover_body_right, text_left)
        self.assertGreaterEqual(text_left - popover_body_right, margin)

        # 3. Bottom placement (wide bar)
        anchor_wide = (50, 200, 900, 40)
        rect_b, pos_b = self.window.calculate_smart_popover_placement(anchor_wide, estimated_size=(est_w, est_h), margin=margin)
        self.assertEqual(pos_b, Gtk.PositionType.BOTTOM)
        popover_body_top = rect_b.y + rect_b.height
        text_bottom = anchor_wide[1] + anchor_wide[3]
        self.assertGreater(popover_body_top, text_bottom)
        self.assertGreaterEqual(popover_body_top - text_bottom, margin)

        # 4. Top placement (wide bar near bottom)
        anchor_bot = (50, 850, 900, 40)
        rect_t, pos_t = self.window.calculate_smart_popover_placement(anchor_bot, estimated_size=(est_w, est_h), margin=margin)
        self.assertEqual(pos_t, Gtk.PositionType.TOP)
        popover_body_bottom = rect_t.y
        text_top = anchor_bot[1]
        self.assertLess(popover_body_bottom, text_top)
        self.assertGreaterEqual(text_top - popover_body_bottom, margin)


if __name__ == "__main__":
    unittest.main()
