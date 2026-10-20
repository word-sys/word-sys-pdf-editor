import unittest
from unittest.mock import MagicMock, patch
import io
import os
import fitz
from PIL import Image

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio

from word_sys_pdf_editor.models import EditableImage
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.undo_manager import UndoManager


class TestImageImportGeometry(unittest.TestCase):
    """Test suite for click-to-insert image workflow and aspect ratio preservation."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=612, height=792)

        self.window = MagicMock()
        self.window.doc = self.doc
        self.window.current_page_index = 0
        self.window.current_pdf_page_width = 612
        self.window.current_pdf_page_height = 792
        self.window.zoom_level = 1.0
        self.window.view_mode = False
        self.window.font_scan_in_progress = False
        self.window.document_modified = False
        self.window.tool_mode = "add_image"
        self.window.selected_image = None
        self.window.selected_text = None
        self.window.selected_shape = None
        self.window.selected_stroke = None
        self.window.selected_form_field = None
        self.window.selected_measurement = None
        self.window.temp_image_bbox = None
        self.window.temp_stroke = None
        self.window.temp_shape = None
        self.window.temp_stamp_bbox = None
        self.window.temp_sig_bbox = None
        self.window.temp_form_field_rect = None
        self.window.temp_highlight_rect = None
        self.window.active_stamp = None
        self.window.current_measurement = None
        self.window.is_resizing = False
        self.window.is_dragging_obj = False
        self.window.drag_start_page_pos = (120.0, 150.0)
        self.window.dragging_to_create = True
        self.window._active_session = None

        self.window.editable_images = []
        self.window.editable_texts = []
        self.window.editable_shapes = []
        self.window.editable_strokes = []
        self.window.measurements = []
        self.window.sticky_notes = []

        pdf_handler.save_page_snapshot(self.doc, 0)

        self.window.undo_manager = UndoManager(self.window)
        self.window.pdf_view = MagicMock()

        # Bind methods under test
        self.window.calculate_image_import_geometry = PdfEditorWindow.calculate_image_import_geometry.__get__(self.window, PdfEditorWindow)
        self.window._handle_add_image_click = PdfEditorWindow._handle_add_image_click.__get__(self.window, PdfEditorWindow)
        self.window.canvas_to_page_coords = MagicMock(return_value=(0, 120.0, 150.0))
        self.window.is_canvas_point_on_page = MagicMock(return_value=True)
        self.window._visual_to_unrotated_page_coords = MagicMock(return_value=(120.0, 150.0))
        self.window._refresh_thumbnail = MagicMock()
        self.window._update_ui_state = MagicMock()
        self.window.commit_pending_format_change = MagicMock()

        self.window.on_pdf_view_pressed = PdfEditorWindow.on_pdf_view_pressed.__get__(self.window, PdfEditorWindow)
        self.window.on_drag_end = PdfEditorWindow.on_drag_end.__get__(self.window, PdfEditorWindow)

        # Create temporary sample image files
        self.png_320_240_bytes = self._create_sample_png(320, 240)
        self.png_400_800_bytes = self._create_sample_png(400, 800)
        self.png_square_bytes = self._create_sample_png(300, 300)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def _create_sample_png(self, width: int, height: int) -> bytes:
        img = Image.new("RGBA", (width, height), color=(100, 150, 200, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_get_image_pixel_dimensions_valid(self):
        w, h = pdf_handler.get_image_pixel_dimensions(self.png_320_240_bytes)
        self.assertEqual(w, 320)
        self.assertEqual(h, 240)

        w2, h2 = pdf_handler.get_image_pixel_dimensions(self.png_400_800_bytes)
        self.assertEqual(w2, 400)
        self.assertEqual(h2, 800)

    def test_get_image_pixel_dimensions_empty_or_corrupt(self):
        w, h = pdf_handler.get_image_pixel_dimensions(b"")
        self.assertEqual((w, h), (200, 200))

        w2, h2 = pdf_handler.get_image_pixel_dimensions(b"not an image data bytes")
        self.assertEqual((w2, h2), (200, 200))

    def test_calculate_image_import_geometry_aspect_ratio_preservation(self):
        rect = self.window.calculate_image_import_geometry(
            intrinsic_w=800,
            intrinsic_h=600,
            click_pos=(50.0, 50.0),
            page_bounds=(612.0, 792.0),
            margin=36.0,
            dpi_scale=0.75
        )
        x0, y0, x1, y1 = rect
        width = x1 - x0
        height = y1 - y0
        self.assertAlmostEqual(width / height, 800.0 / 600.0, places=2)
        self.assertGreaterEqual(x0, 36.0)
        self.assertGreaterEqual(y0, 36.0)
        self.assertLessEqual(x1, 612.0 - 36.0)
        self.assertLessEqual(y1, 792.0 - 36.0)

    def test_calculate_image_import_geometry_tall_image_preservation(self):
        rect = self.window.calculate_image_import_geometry(
            intrinsic_w=200,
            intrinsic_h=800,
            click_pos=(100.0, 100.0),
            page_bounds=(612.0, 792.0),
            margin=36.0,
            dpi_scale=0.75
        )
        x0, y0, x1, y1 = rect
        width = x1 - x0
        height = y1 - y0
        self.assertAlmostEqual(width / height, 200.0 / 800.0, places=2)
        self.assertLessEqual(height, 792.0 - 72.0)

    def test_calculate_image_import_geometry_oversized_downscaling(self):
        rect = self.window.calculate_image_import_geometry(
            intrinsic_w=4000,
            intrinsic_h=2000,
            click_pos=(50.0, 50.0),
            page_bounds=(612.0, 792.0),
            margin=36.0,
            dpi_scale=0.75
        )
        x0, y0, x1, y1 = rect
        width = x1 - x0
        height = y1 - y0
        self.assertAlmostEqual(width / height, 2.0, places=2)
        self.assertLessEqual(width, 612.0 - 72.0 + 0.01)
        self.assertLessEqual(height, 792.0 - 72.0 + 0.01)

    def test_calculate_image_import_geometry_shifts_away_from_page_edge(self):
        rect = self.window.calculate_image_import_geometry(
            intrinsic_w=200,
            intrinsic_h=100,
            click_pos=(590.0, 780.0),
            page_bounds=(612.0, 792.0),
            margin=36.0,
            dpi_scale=0.75
        )
        x0, y0, x1, y1 = rect
        self.assertAlmostEqual(x1, 612.0 - 36.0, places=1)
        self.assertAlmostEqual(y1, 792.0 - 36.0, places=1)
        self.assertAlmostEqual((x1 - x0) / (y1 - y0), 2.0, places=2)

    @patch("word_sys_pdf_editor.window.show_open_file_dialog")
    def test_handle_add_image_click_inserts_object(self, mock_show_dialog):
        fake_file = MagicMock()
        fake_file.get_path.return_value = "/tmp/test_dummy_image.png"

        def invoke_cb(parent, title, filters, callback):
            with patch("builtins.open", unittest.mock.mock_open(read_data=self.png_320_240_bytes)):
                callback(fake_file)

        mock_show_dialog.side_effect = invoke_cb

        self.window._handle_add_image_click(100.0, 150.0, page_index=0)

        self.assertIsNotNone(self.window.selected_image)
        self.assertEqual(self.window.selected_image.page_number, 0)
        self.assertTrue(self.window.selected_image.is_new)
        self.assertEqual(self.window.tool_mode, "select")
        self.assertTrue(self.window.document_modified)
        self.window._refresh_thumbnail.assert_called_with(0)
        self.window.pdf_view.queue_draw.assert_called()

        bbox = self.window.selected_image.bbox
        aspect = (bbox[2] - bbox[0]) / (bbox[3] - bbox[1])
        self.assertAlmostEqual(aspect, 320.0 / 240.0, places=2)

    @patch("gi.repository.Gtk.EventController.get_current_event_state", return_value=0)
    def test_on_pdf_view_pressed_triggers_image_click_handler(self, mock_event_state):
        gesture = MagicMock()
        self.window.tool_mode = "add_image"
        with patch.object(self.window, "_handle_add_image_click") as mock_handler:
            self.window.on_pdf_view_pressed(gesture, 1, 120.0, 150.0)
            mock_handler.assert_called_once_with(120.0, 150.0, page_index=0)
            gesture.set_state.assert_called_with(Gtk.EventSequenceState.CLAIMED)

    def test_on_drag_end_small_drag_delegates_to_click(self):
        gesture = MagicMock()
        self.window.tool_mode = "add_image"
        self.window.temp_image_bbox = (100.0, 100.0, 105.0, 106.0)
        self.window.drag_start_page_pos = (100.0, 100.0)

        with patch.object(self.window, "_handle_add_image_click") as mock_handler:
            self.window.on_drag_end(gesture, 5.0, 6.0)
            self.assertIsNone(self.window.temp_image_bbox)
            mock_handler.assert_called_once_with(100.0, 100.0, page_index=0)

    @patch("word_sys_pdf_editor.window.show_open_file_dialog")
    def test_on_drag_end_marquee_drag_preserves_aspect_ratio(self, mock_show_dialog):
        gesture = MagicMock()
        self.window.tool_mode = "add_image"
        self.window.temp_image_bbox = (50.0, 50.0, 450.0, 250.0)

        fake_file = MagicMock()
        fake_file.get_path.return_value = "/tmp/test_square_image.png"

        def invoke_cb(parent, title, filters, callback):
            with patch("builtins.open", unittest.mock.mock_open(read_data=self.png_square_bytes)):
                callback(fake_file)

        mock_show_dialog.side_effect = invoke_cb

        self.window.on_drag_end(gesture, 400.0, 200.0)

        self.assertIsNotNone(self.window.selected_image)
        bbox = self.window.selected_image.bbox
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]

        # In a 400x200 box, a square image (aspect 1.0) must scale to 200x200 centered
        self.assertAlmostEqual(w, 200.0, places=1)
        self.assertAlmostEqual(h, 200.0, places=1)
        self.assertAlmostEqual(bbox[0], 150.0, places=1)
        self.assertAlmostEqual(bbox[1], 50.0, places=1)
        self.assertEqual(self.window.tool_mode, "select")


if __name__ == "__main__":
    unittest.main()
