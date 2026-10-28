"""Consolidated Images and Clone Patch Test Suite for word-sys-pdf-editor.

This suite merges image extraction, replacement, geometry import, rotation,
clone patch tool manipulation, covering, and layer ordering tests.
"""

# ============================================================================
# SECTION: test_image_extraction_replacement.py
# ============================================================================
import os
import io
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor.models import EditableImage
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.undo_manager import ReplaceImageCommand
from word_sys_pdf_editor.i18n import _


class TestImageExtractionReplacement(unittest.TestCase):
    def setUp(self):
        # Create a test PDF with an embedded 100x100 red image
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=400, height=400)
        
        im_red = Image.new("RGB", (100, 100), (255, 0, 0))
        buf_red = io.BytesIO()
        im_red.save(buf_red, format="PNG")
        self.red_png_bytes = buf_red.getvalue()
        
        self.img_rect = fitz.Rect(50, 50, 150, 150)
        self.page.insert_image(self.img_rect, stream=self.red_png_bytes)
        
        # Save snapshot
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)
        
        images = self.page.get_images()
        self.assertTrue(len(images) > 0)
        self.xref = images[0][0]
        
        self.editable_img = EditableImage(
            bbox=(50.0, 50.0, 150.0, 150.0),
            page_number=0,
            xref=self.xref,
            image_bytes=self.red_png_bytes,
            is_new=False
        )

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_detect_image_extension(self):
        """Test image extension detection from magic header bytes."""
        png_data = b"\x89PNG\r\n\x1a\n\x00\x00"
        jpg_data = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        gif_data = b"GIF89a\x01\x00\x01\x00"
        bmp_data = b"BM\x36\x00\x00\x00\x00"
        webp_data = b"RIFF\x00\x00\x00\x00WEBPVP8 "
        
        self.assertEqual(pdf_handler._detect_image_extension(png_data), "png")
        self.assertEqual(pdf_handler._detect_image_extension(jpg_data), "jpeg")
        self.assertEqual(pdf_handler._detect_image_extension(gif_data), "gif")
        self.assertEqual(pdf_handler._detect_image_extension(bmp_data), "bmp")
        self.assertEqual(pdf_handler._detect_image_extension(webp_data), "webp")
        self.assertEqual(pdf_handler._detect_image_extension(b"unknown"), "png")

    def test_extract_image_data_from_pdf_xref(self):
        """Test extracting raw image data using PDF xref."""
        img_bytes, ext = pdf_handler.extract_image_data(self.doc, self.editable_img)
        self.assertIsNotNone(img_bytes)
        self.assertTrue(len(img_bytes) > 0)
        self.assertIn(ext, ("png", "jpeg"))

    def test_extract_image_data_fallback_in_memory(self):
        """Test extracting image data when xref is None, using in-memory bytes."""
        img_no_xref = EditableImage(
            bbox=(10, 10, 50, 50),
            page_number=0,
            xref=None,
            image_bytes=self.red_png_bytes,
            is_new=True
        )
        img_bytes, ext = pdf_handler.extract_image_data(None, img_no_xref)
        self.assertEqual(img_bytes, self.red_png_bytes)
        self.assertEqual(ext, "png")

    def test_fit_image_to_aspect_ratio_wide(self):
        """Test fitting a wide image into a square bounding box preserves aspect ratio with transparent padding."""
        # 200x100 wide image (2:1 aspect)
        im_wide = Image.new("RGB", (200, 100), (0, 255, 0))
        buf = io.BytesIO()
        im_wide.save(buf, format="PNG")
        wide_bytes = buf.getvalue()

        # Target bounding box is 100x100 (1:1 aspect)
        target_bbox = (50.0, 50.0, 150.0, 150.0)
        fitted_bytes = pdf_handler.fit_image_to_aspect_ratio(wide_bytes, target_bbox)

        # Inspect resulting image
        im_fitted = Image.open(io.BytesIO(fitted_bytes))
        self.assertEqual(im_fitted.mode, "RGBA")
        # Aspect ratio of the canvas should match target bbox (1:1)
        self.assertEqual(im_fitted.width, im_fitted.height)
        self.assertEqual(im_fitted.width, 200)
        self.assertEqual(im_fitted.height, 200)

        # Center should have green color
        center_pixel = im_fitted.getpixel((100, 100))
        self.assertEqual(center_pixel[:3], (0, 255, 0))
        self.assertEqual(center_pixel[3], 255)

        # Top padding should be completely transparent (alpha = 0)
        top_pixel = im_fitted.getpixel((100, 10))
        self.assertEqual(top_pixel[3], 0)

    def test_fit_image_to_aspect_ratio_tall(self):
        """Test fitting a tall image into a square bounding box preserves aspect ratio with transparent padding."""
        # 100x200 tall image (1:2 aspect)
        im_tall = Image.new("RGB", (100, 200), (0, 0, 255))
        buf = io.BytesIO()
        im_tall.save(buf, format="PNG")
        tall_bytes = buf.getvalue()

        target_bbox = (50.0, 50.0, 150.0, 150.0)
        fitted_bytes = pdf_handler.fit_image_to_aspect_ratio(tall_bytes, target_bbox)

        im_fitted = Image.open(io.BytesIO(fitted_bytes))
        self.assertEqual(im_fitted.mode, "RGBA")
        self.assertEqual(im_fitted.width, im_fitted.height)
        self.assertEqual(im_fitted.width, 200)
        self.assertEqual(im_fitted.height, 200)

        center_pixel = im_fitted.getpixel((100, 100))
        self.assertEqual(center_pixel[:3], (0, 0, 255))
        self.assertEqual(center_pixel[3], 255)

        # Left padding should be completely transparent
        left_pixel = im_fitted.getpixel((10, 100))
        self.assertEqual(left_pixel[3], 0)

    def test_fit_image_to_aspect_ratio_matches(self):
        """Test that an image already matching target aspect ratio does not add unnecessary padding."""
        im_sq = Image.new("RGB", (150, 150), (128, 128, 128))
        buf = io.BytesIO()
        im_sq.save(buf, format="PNG")
        sq_bytes = buf.getvalue()

        target_bbox = (50.0, 50.0, 150.0, 150.0)
        fitted_bytes = pdf_handler.fit_image_to_aspect_ratio(sq_bytes, target_bbox)
        im_fitted = Image.open(io.BytesIO(fitted_bytes))
        self.assertEqual(im_fitted.size, (150, 150))

    def test_replace_image_on_page(self):
        """Test replacing an embedded PDF image on a page via page.replace_image()."""
        # Create a blue replacement image
        im_blue = Image.new("RGB", (120, 80), (0, 0, 255))
        buf_blue = io.BytesIO()
        im_blue.save(buf_blue, format="PNG")
        blue_bytes = buf_blue.getvalue()

        success, err, new_xref = pdf_handler.replace_image_on_page(
            self.doc,
            self.editable_img,
            blue_bytes
        )

        self.assertTrue(success)
        self.assertIsNone(err)
        self.assertIsNotNone(new_xref)
        self.assertEqual(self.editable_img.xref, new_xref)
        self.assertTrue(self.editable_img.modified)

        # Verify page rendering has blue image inside the bounding box
        page = self.doc.load_page(0)
        pix = page.get_pixmap()
        # Pixel at center (100, 100) should be blue (0, 0, 255)
        color = pix.pixel(100, 100)
        self.assertEqual(color, (0, 0, 255))

        # Top padding pixel inside 100x100 box at (100, 60) should be page background white (255, 255, 255)
        # because the image was 120x80 (wider than 1:1), so vertical margins are transparent
        color_padded = pix.pixel(100, 60)
        self.assertEqual(color_padded, (255, 255, 255))

    def test_replace_image_command_undo_redo(self):
        """Test ReplaceImageCommand execute and undo cycles."""
        im_green = Image.new("RGB", (100, 100), (0, 255, 0))
        buf_green = io.BytesIO()
        im_green.save(buf_green, format="PNG")
        green_bytes = buf_green.getvalue()

        # Mock window
        mock_window = MagicMock()
        mock_window.doc = self.doc
        mock_window.current_page_index = 0
        mock_window.document_modified = False

        cmd = ReplaceImageCommand(mock_window, self.editable_img, green_bytes)
        
        # 1. Execute replacement
        exec_ok = cmd.execute()
        self.assertTrue(exec_ok)
        self.assertTrue(mock_window.document_modified)
        
        # Verify page rendering is green
        pix_exec = self.doc.load_page(0).get_pixmap()
        self.assertEqual(pix_exec.pixel(100, 100), (0, 255, 0))

        # 2. Undo replacement
        undo_ok = cmd.undo()
        self.assertTrue(undo_ok)
        
        # Verify page rendering is reverted to red
        pix_undo = self.doc.load_page(0).get_pixmap()
        self.assertEqual(pix_undo.pixel(100, 100), (255, 0, 0))

        # 3. Redo replacement
        redo_ok = cmd.execute()
        self.assertTrue(redo_ok)
        pix_redo = self.doc.load_page(0).get_pixmap()
        self.assertEqual(pix_redo.pixel(100, 100), (0, 255, 0))

    def test_extract_image_file_export(self):
        """Test writing extracted image data to a file."""
        import tempfile
        img_bytes, ext = pdf_handler.extract_image_data(self.doc, self.editable_img)
        self.assertIsNotNone(img_bytes)

        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tf:
            tf.write(img_bytes)
            tmp_path = tf.name

        try:
            self.assertTrue(os.path.exists(tmp_path))
            self.assertGreater(os.path.getsize(tmp_path), 0)
            with Image.open(tmp_path) as im:
                self.assertGreater(im.width, 0)
                self.assertGreater(im.height, 0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_image_context_popover_buttons(self):
        """Verify that right-clicking an image sets up Extract Image and Replace Image options."""
        from gi.repository import Gtk
        
        # Test labels match i18n
        lbl_extract = _("menu_extract_image")
        lbl_replace = _("menu_replace_image")
        lbl_delete = _("menu_delete_image")
        
        self.assertEqual(lbl_extract, "Extract Image")
        self.assertEqual(lbl_replace, "Replace Image")
        self.assertEqual(lbl_delete, "Delete Image")
        
        # Verify action dispatch bindings
        mock_win = MagicMock()
        mock_win._handle_context_action = MagicMock()
        
        from word_sys_pdf_editor.window import PdfEditorWindow
        win_inst = MagicMock(spec=PdfEditorWindow)
        win_inst.context_popover = MagicMock()
        
        PdfEditorWindow._handle_context_action(win_inst, "extract_image", self.editable_img, 100, 100)
        win_inst._extract_image.assert_called_once_with(self.editable_img)
        
        PdfEditorWindow._handle_context_action(win_inst, "replace_image", self.editable_img, 100, 100)
        win_inst._replace_image.assert_called_once_with(self.editable_img)


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_image_import_geometry.py
# ============================================================================
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


# ============================================================================
# SECTION: test_image_rotation.py
# ============================================================================
import os
import io
import unittest
from unittest.mock import MagicMock
from PIL import Image

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from word_sys_pdf_editor.models import EditableImage
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.undo_manager import RotateObjectCommand, UndoManager


class MockWindow:
    def __init__(self, doc, editable_images=None):
        self.doc = doc
        self.current_page_index = 0
        self.editable_texts = []
        self.editable_shapes = []
        self.editable_images = editable_images if editable_images is not None else []
        self.editable_strokes = []
        self.document_modified = False
        self.selected_text = None
        self.selected_image = self.editable_images[0] if self.editable_images else None
        self.selected_shape = None
        self.selected_stroke = None
        self.status_label = MagicMock()
        self.pdf_view = self
        self.undo_manager = UndoManager(self)

    def _update_undo_redo_buttons(self): pass
    def _update_rotation_controls(self, obj): pass
    def _update_ui_state(self): pass
    def _refresh_thumbnail(self, p): pass
    def queue_draw(self): pass


class TestImageRotation(unittest.TestCase):
    def setUp(self):
        # Create a test PDF with a 200x100 landscape image at (100, 100, 300, 200)
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=600)
        
        im = Image.new("RGBA", (200, 100), (255, 0, 0, 255))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        self.png_bytes = buf.getvalue()
        
        self.rect = fitz.Rect(100, 100, 300, 200)
        self.page.insert_image(self.rect, stream=self.png_bytes)
        
        pdf_handler.save_page_snapshot(self.doc, 0, force=True)
        images, _ = pdf_handler.extract_editable_images(self.doc, 0)
        self.img_obj = images[0]
        self.win = MockWindow(self.doc, [self.img_obj])

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_image_rotation_90_swaps_bounding_box_aspect_ratio(self):
        """90 degree rotation must swap width and height around center (100x200 portrait)."""
        cmd = RotateObjectCommand(self.win, self.img_obj, 0.0, 90.0)
        cmd.execute()
        
        p = self.doc.load_page(0)
        imgs = p.get_images()
        self.assertEqual(len(imgs), 1, "Expected exactly 1 image on page after 90 deg rotation")
        
        rects = p.get_image_rects(imgs[0][0])
        self.assertEqual(len(rects), 1)
        target_rect = rects[0]
        
        # Original center was (200, 150), w=200, h=100. Rotated box should be w=100, h=200 -> (150, 50, 250, 250)
        self.assertAlmostEqual(target_rect.width, 100.0, delta=1.0)
        self.assertAlmostEqual(target_rect.height, 200.0, delta=1.0)
        self.assertAlmostEqual((target_rect.x0 + target_rect.x1) / 2.0, 200.0, delta=1.0)
        self.assertAlmostEqual((target_rect.y0 + target_rect.y1) / 2.0, 150.0, delta=1.0)

    def test_image_rotation_270_swaps_bounding_box_aspect_ratio(self):
        """270 degree rotation must swap width and height around center (100x200 portrait)."""
        cmd = RotateObjectCommand(self.win, self.img_obj, 0.0, 270.0)
        cmd.execute()
        
        p = self.doc.load_page(0)
        imgs = p.get_images()
        self.assertEqual(len(imgs), 1, "Expected exactly 1 image on page after 270 deg rotation")
        
        rects = p.get_image_rects(imgs[0][0])
        target_rect = rects[0]
        self.assertAlmostEqual(target_rect.width, 100.0, delta=1.0)
        self.assertAlmostEqual(target_rect.height, 200.0, delta=1.0)

    def test_image_rotation_180_preserves_dimensions(self):
        """180 degree rotation must preserve original width and height (200x100 landscape)."""
        cmd = RotateObjectCommand(self.win, self.img_obj, 0.0, 180.0)
        cmd.execute()
        
        p = self.doc.load_page(0)
        imgs = p.get_images()
        self.assertEqual(len(imgs), 1)
        
        rects = p.get_image_rects(imgs[0][0])
        target_rect = rects[0]
        self.assertAlmostEqual(target_rect.width, 200.0, delta=1.0)
        self.assertAlmostEqual(target_rect.height, 100.0, delta=1.0)

    def test_image_arbitrary_45_rotation_expands_bounds(self):
        """Arbitrary 45 degree rotation must insert expanded bounds and rotate object model."""
        cmd = RotateObjectCommand(self.win, self.img_obj, 0.0, 45.0)
        cmd.execute()
        
        self.assertAlmostEqual(self.img_obj.rotation, 45.0, places=1)
        p = self.doc.load_page(0)
        imgs = p.get_images()
        self.assertEqual(len(imgs), 1)
        
        rects = p.get_image_rects(imgs[0][0])
        target_rect = rects[0]
        # Diagonal expansion for 200x100 at 45 deg is approx 212.1 x 212.1
        self.assertTrue(target_rect.width > 200.0)
        self.assertTrue(target_rect.height > 100.0)

    def test_sequential_image_rotations_and_undo(self):
        """Sequential rotations 0 -> 90 -> 180 and undo back maintain single image instance."""
        # Rotate 0 -> 90
        cmd1 = RotateObjectCommand(self.win, self.img_obj, 0.0, 90.0)
        cmd1.execute()
        self.win.undo_manager.add_command(cmd1)
        
        p = self.doc.load_page(0)
        self.assertEqual(len(p.get_images()), 1)
        self.assertAlmostEqual(self.img_obj.rotation, 90.0, places=1)
        
        # Rotate 90 -> 180
        cmd2 = RotateObjectCommand(self.win, self.img_obj, 90.0, 180.0)
        cmd2.execute()
        self.win.undo_manager.add_command(cmd2)
        
        self.assertAlmostEqual(self.img_obj.rotation, 180.0, places=1)
        
        # Undo 180 -> 90
        self.win.undo_manager.undo()
        self.assertAlmostEqual(self.img_obj.rotation, 90.0, places=1)
        
        # Undo 90 -> 0
        self.win.undo_manager.undo()
        self.assertAlmostEqual(self.img_obj.rotation, 0.0, places=1)

    def test_new_inserted_image_rotation(self):
        """A newly inserted image (is_new=True) rotates and bakes correctly."""
        new_img = EditableImage(
            bbox=(200.0, 200.0, 300.0, 250.0),
            page_number=0,
            xref=None,
            image_bytes=self.png_bytes,
            is_new=True
        )
        self.win.editable_images.append(new_img)
        
        cmd = RotateObjectCommand(self.win, new_img, 0.0, 90.0)
        cmd.execute()
        
        self.assertAlmostEqual(new_img.rotation, 90.0, places=1)
        self.assertTrue(new_img.is_baked)

    def test_image_rotation_direction_clockwise_pixels(self):
        """Verify that 90 deg rotates clockwise (left to top) and 270 deg rotates clockwise (left to bottom)."""
        # Create asymmetric image: Left half RED, Right half BLUE
        im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        for x in range(50):
            for y in range(100):
                im.putpixel((x, y), (255, 0, 0, 255))
        for x in range(50, 100):
            for y in range(100):
                im.putpixel((x, y), (0, 0, 255, 255))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        asym_bytes = buf.getvalue()

        # Test 90 degree clockwise rotation
        doc90 = fitz.open()
        p90 = doc90.new_page(width=300, height=300)
        p90.insert_image(fitz.Rect(100, 100, 200, 200), stream=asym_bytes)
        pdf_handler.save_page_snapshot(doc90, 0, force=True)
        imgs90, _ = pdf_handler.extract_editable_images(doc90, 0)
        win90 = MockWindow(doc90, imgs90)
        cmd90 = RotateObjectCommand(win90, imgs90[0], 0.0, 90.0)
        cmd90.execute()

        pix90 = p90.get_pixmap()
        # Center is (150, 150). Top half (y=120) should be Red, Bottom half (y=180) should be Blue
        top_color_90 = pix90.pixel(150, 120)
        bottom_color_90 = pix90.pixel(150, 180)
        self.assertEqual(top_color_90[:3], (255, 0, 0), "90 deg CW rotation must move left half (Red) to top half")
        self.assertEqual(bottom_color_90[:3], (0, 0, 255), "90 deg CW rotation must move right half (Blue) to bottom half")
        doc90.close()

        # Test 270 degree clockwise rotation
        doc270 = fitz.open()
        p270 = doc270.new_page(width=300, height=300)
        p270.insert_image(fitz.Rect(100, 100, 200, 200), stream=asym_bytes)
        pdf_handler.save_page_snapshot(doc270, 0, force=True)
        imgs270, _ = pdf_handler.extract_editable_images(doc270, 0)
        win270 = MockWindow(doc270, imgs270)
        cmd270 = RotateObjectCommand(win270, imgs270[0], 0.0, 270.0)
        cmd270.execute()

        pix270 = p270.get_pixmap()
        # Top half (y=120) should be Blue, Bottom half (y=180) should be Red
        top_color_270 = pix270.pixel(150, 120)
        bottom_color_270 = pix270.pixel(150, 180)
        self.assertEqual(top_color_270[:3], (0, 0, 255), "270 deg CW rotation must move right half (Blue) to top half")
        self.assertEqual(bottom_color_270[:3], (255, 0, 0), "270 deg CW rotation must move left half (Red) to bottom half")
        doc270.close()


# ============================================================================
# SECTION: test_clone_patch_tool.py
# ============================================================================
import unittest
import tempfile
import os
import pymupdf as fitz
from unittest.mock import MagicMock

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.i18n import _STRINGS, _


class TestExtractPageRegionPatch(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        # Draw some content on the page
        self.page.draw_rect(fitz.Rect(50, 50, 250, 250), color=(0, 0, 1), fill=(0.8, 0.9, 1.0))
        self.page.insert_text((70, 100), "Snapshot Test Region", fontsize=14, color=(0, 0, 0))

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_extract_basic_patch(self):
        bbox = (50, 50, 200, 200)
        patch_bytes = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=300)
        self.assertIsNotNone(patch_bytes)
        self.assertTrue(patch_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        w_px, h_px = pdf_handler.get_image_pixel_dimensions(patch_bytes)
        # 150 pt at 300 DPI: (150 / 72) * 300 = 625 px (approx)
        expected_w = int(round((150.0 / 72.0) * 300.0))
        self.assertAlmostEqual(w_px, expected_w, delta=5)
        self.assertAlmostEqual(h_px, expected_w, delta=5)

    def test_extract_patch_on_rotated_pages(self):
        bbox = (100, 100, 250, 250)
        for rot in [0, 90, 180, 270]:
            doc_rot = fitz.open()
            page = doc_rot.new_page(width=600, height=800)
            page.set_rotation(rot)
            page.draw_rect(fitz.Rect(50, 50, 300, 300), color=(1, 0, 0), fill=(1, 0.9, 0.9))

            patch_bytes = pdf_handler.extract_page_region_patch(doc_rot, 0, bbox, dpi=300)
            self.assertIsNotNone(patch_bytes, f"Failed extraction for rotation {rot}")
            self.assertTrue(patch_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
            w_px, h_px = pdf_handler.get_image_pixel_dimensions(patch_bytes)
            self.assertGreater(w_px, 100)
            self.assertGreater(h_px, 100)
            doc_rot.close()

    def test_extract_patch_boundary_clamping(self):
        # Bounding box overlapping the right and bottom page boundary
        bbox = (500, 700, 750, 950)
        patch_bytes = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=300)
        self.assertIsNotNone(patch_bytes)
        self.assertTrue(patch_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # Width should clamp to 600 - 500 = 100 pt
        w_px, h_px = pdf_handler.get_image_pixel_dimensions(patch_bytes)
        expected_w = int(round((100.0 / 72.0) * 300.0))
        expected_h = int(round((100.0 / 72.0) * 300.0))
        self.assertAlmostEqual(w_px, expected_w, delta=5)
        self.assertAlmostEqual(h_px, expected_h, delta=5)

    def test_extract_patch_completely_outside(self):
        bbox = (800, 900, 1000, 1100)
        patch_bytes = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=300)
        self.assertIsNone(patch_bytes)

    def test_extract_patch_degenerate_bbox(self):
        # Zero or sub-threshold size
        patch_1 = pdf_handler.extract_page_region_patch(self.doc, 0, (100, 100, 101, 101), dpi=300)
        self.assertIsNone(patch_1)

        patch_2 = pdf_handler.extract_page_region_patch(self.doc, 0, (100, 100, 100, 100), dpi=300)
        self.assertIsNone(patch_2)

    def test_extract_patch_invalid_page_or_doc(self):
        self.assertIsNone(pdf_handler.extract_page_region_patch(None, 0, (50, 50, 150, 150)))
        self.assertIsNone(pdf_handler.extract_page_region_patch(self.doc, -1, (50, 50, 150, 150)))
        self.assertIsNone(pdf_handler.extract_page_region_patch(self.doc, 999, (50, 50, 150, 150)))

    def test_extract_patch_custom_dpi(self):
        bbox = (50, 50, 150, 150)
        patch_150 = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=150)
        patch_300 = pdf_handler.extract_page_region_patch(self.doc, 0, bbox, dpi=300)
        self.assertIsNotNone(patch_150)
        self.assertIsNotNone(patch_300)

        w_150, _ = pdf_handler.get_image_pixel_dimensions(patch_150)
        w_300, _ = pdf_handler.get_image_pixel_dimensions(patch_300)
        self.assertAlmostEqual(w_300, w_150 * 2, delta=6)


class MockClonePatchWindow:
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.view_mode = False
        self.tool_mode = "clone_patch"
        self.temp_clone_patch_bbox = None
        self.last_captured_patch = None
        self.temp_image_bbox = None
        self.temp_shape = None
        self.temp_stroke = None
        self.temp_stamp_bbox = None
        self.temp_sig_bbox = None
        self.temp_form_field_rect = None
        self.drag_start_page_pos = (0, 0)
        self.drag_start_page_index = 0
        self.dragging_to_create = False
        self.pdf_view = MagicMock()
        self.status_label = MagicMock()
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
        self.undo_manager = MagicMock()

    def get_focus(self):
        return None

    def _update_ui_state(self):
        pass

    def canvas_to_page_coords(self, x, y):
        return self.current_page_index, x / self.zoom_level, y / self.zoom_level

    def is_canvas_point_on_page(self, x, y, target_page):
        return True

    def _visual_to_unrotated_delta(self, dx, dy):
        return dx, dy

    def _visual_to_unrotated_page_coords(self, px, py, page_index=None):
        return px, py

    def _stash_page_objects(self, page_index):
        pass

    def _restore_page_objects(self, page_index):
        pass

    def _sync_thumbnail_selection(self):
        pass

    def _sync_window_title_and_subtitle(self):
        pass

    def _create_form_field_overlays(self):
        pass

    def _clear_form_field_overlays(self):
        pass

    def hide_text_editor(self):
        pass

    def commit_pending_format_change(self):
        pass

    _switch_active_page = PdfEditorWindow._switch_active_page
    on_drag_begin = PdfEditorWindow.on_drag_begin
    on_drag_update = PdfEditorWindow.on_drag_update
    on_drag_end = PdfEditorWindow.on_drag_end


class TestClonePatchWindowIntegration(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.page1 = self.doc.new_page(width=500, height=700)
        self.page1.draw_rect(fitz.Rect(40, 40, 200, 200), fill=(0.9, 0.9, 0.9))
        self.page2 = self.doc.new_page(width=500, height=700)
        self.win = MockClonePatchWindow(self.doc)

    def tearDown(self):
        if self.doc:
            self.doc.close()

    def test_drag_and_capture_patch_success(self):
        gesture = MagicMock()

        # Begin drag at (50, 50)
        self.win.on_drag_begin(gesture, 50.0, 50.0)
        self.assertTrue(self.win.dragging_to_create)
        self.assertEqual(self.win.temp_clone_patch_bbox, (50.0, 50.0, 50.0, 50.0))

        # Update drag by (+80, +60) -> (130, 110)
        self.win.on_drag_update(gesture, 80.0, 60.0)
        self.assertEqual(self.win.temp_clone_patch_bbox, (50.0, 50.0, 130.0, 110.0))

        # End drag
        self.win.on_drag_end(gesture, 80.0, 60.0)
        self.assertFalse(self.win.dragging_to_create)
        self.assertIsNone(self.win.temp_clone_patch_bbox)

        # Verify patch was captured and stored in last_captured_patch
        self.assertIsNotNone(self.win.last_captured_patch)
        patch = self.win.last_captured_patch
        self.assertIn("image_bytes", patch)
        self.assertTrue(patch["image_bytes"].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(patch["bbox"], (50.0, 50.0, 130.0, 110.0))
        self.assertEqual(patch["page_number"], 0)
        self.assertEqual(patch["dpi"], 300)

        # Verify status label updated
        self.win.status_label.set_text.assert_called()

    def test_drag_and_capture_patch_too_small(self):
        gesture = MagicMock()

        # Begin drag at (50, 50)
        self.win.on_drag_begin(gesture, 50.0, 50.0)
        # Tiny drag +2, +1 (< 4 pt)
        self.win.on_drag_update(gesture, 2.0, 1.0)
        self.win.on_drag_end(gesture, 2.0, 1.0)

        self.assertIsNone(self.win.temp_clone_patch_bbox)
        self.assertIsNone(self.win.last_captured_patch)

    def test_captured_patch_preserved_on_page_switch(self):
        gesture = MagicMock()
        self.win.on_drag_begin(gesture, 60.0, 60.0)
        self.win.on_drag_update(gesture, 100.0, 100.0)
        self.win.on_drag_end(gesture, 100.0, 100.0)
        self.assertIsNotNone(self.win.last_captured_patch)

        # Switch to page 1
        self.win.continuous_scroll = False
        self.win._switch_active_page(1)
        self.assertEqual(self.win.current_page_index, 1)

        # Verify last_captured_patch is still preserved intact!
        self.assertIsNotNone(self.win.last_captured_patch)
        self.assertEqual(self.win.last_captured_patch["page_number"], 0)

    def test_on_pdf_view_pressed_does_not_block_drag(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        self.win.current_pdf_page_width = 500
        self.win.current_pdf_page_height = 700
        self.win.font_scan_in_progress = False
        self.win._find_text_at_pos = lambda x, y: None
        self.win.on_pdf_view_pressed = PdfEditorWindow.on_pdf_view_pressed.__get__(self.win)
        gesture = MagicMock()

        self.win.on_pdf_view_pressed(gesture, 1, 100.0, 100.0)
        gesture.set_state.assert_not_called()

    def test_shortcuts_c_and_e(self):
        import gi
        gi.require_version('Gdk', '4.0')
        from gi.repository import Gdk

        self.win.inline_editor_widget = None
        self.win.commit_pending_format_change = MagicMock()
        selected_tools = []
        self.win.on_tool_selected = lambda btn, tool_name: selected_tools.append(tool_name)
        self.win.on_key_pressed = PdfEditorWindow.on_key_pressed.__get__(self.win)

        handled_c = self.win.on_key_pressed(None, Gdk.KEY_c, 0, 0)
        self.assertTrue(handled_c)
        self.assertEqual(selected_tools[-1], "clone_patch")

        handled_C = self.win.on_key_pressed(None, Gdk.KEY_C, 0, 0)
        self.assertTrue(handled_C)
        self.assertEqual(selected_tools[-1], "clone_patch")

        handled_e = self.win.on_key_pressed(None, Gdk.KEY_e, 0, 0)
        self.assertTrue(handled_e)
        self.assertEqual(selected_tools[-1], "add_ellipse")

        handled_E = self.win.on_key_pressed(None, Gdk.KEY_E, 0, 0)
        self.assertTrue(handled_E)
        self.assertEqual(selected_tools[-1], "add_ellipse")

        handled_o = self.win.on_key_pressed(None, Gdk.KEY_o, 0, 0)
        self.assertTrue(handled_o)
        self.assertEqual(selected_tools[-1], "add_ellipse")

        handled_O = self.win.on_key_pressed(None, Gdk.KEY_O, 0, 0)
        self.assertTrue(handled_O)
        self.assertEqual(selected_tools[-1], "add_ellipse")


class TestClonePatchLocalization(unittest.TestCase):
    def test_all_locales_have_clone_patch_keys(self):
        required_keys = [
            "tool_clone_patch",
            "tool_clone_patch_tip",
            "patch_captured_status",
            "patch_capture_failed",
            "guide_sc_tool_clone_patch",
        ]
        for lang in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            self.assertIn(lang, _STRINGS)
            locale_dict = _STRINGS[lang]
            for key in required_keys:
                self.assertIn(key, locale_dict, f"Missing key '{key}' in locale '{lang}'")
                self.assertGreater(len(locale_dict[key]), 0, f"Empty string for key '{key}' in '{lang}'")

    def test_ellipse_shortcut_updated_to_e(self):
        for lang in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            self.assertIn(lang, _STRINGS)
            locale_dict = _STRINGS[lang]
            self.assertIn("(E)", locale_dict["tool_ellipse"], f"tool_ellipse shortcut not updated in '{lang}'")


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_patch_covering_and_layer_ordering.py
# ============================================================================
"""
Tests for Part 55: Texture Matching, In-Place Covering & Layer Ordering.
Validates PatchObject representation, auto-placement, layer reordering (bring to front/back/forward/backward),
undo/redo integration, and localization across all supported languages.
"""

import os
import unittest
from unittest.mock import MagicMock, patch
import fitz

from word_sys_pdf_editor.models import (
    EditableText, EditableImage, EditableShape, PatchObject
)
from word_sys_pdf_editor.undo_manager import (
    AddObjectCommand, ReorderObjectCommand
)
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.i18n import _, _STRINGS


class MockLayerWindow:
    """Mock window for testing object reordering and patch operations."""
    def __init__(self, doc):
        self.doc = doc
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.view_mode = False
        self.tool_mode = "select"
        self.last_captured_patch = None
        self.editable_texts = []
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None
        self.document_modified = False
        self.status_label = MagicMock()
        self.pdf_view = MagicMock()
        self.undo_manager = MagicMock()
        self.undo_stack = []
        self.undo_manager.add_command.side_effect = lambda cmd: self.undo_stack.append(cmd)

    def _update_ui_state(self):
        pass

    def _refresh_thumbnail(self, page_index):
        pass

    def reorder_selected_object(self, direction):
        from word_sys_pdf_editor.window import PdfEditorWindow
        return PdfEditorWindow.reorder_selected_object(self, direction)

    def paste_clone_patch(self, center_pos=None):
        from word_sys_pdf_editor.window import PdfEditorWindow
        return PdfEditorWindow.paste_clone_patch(self, center_pos)


class TestPatchObject(unittest.TestCase):
    """Test PatchObject model creation, properties, and serialization."""

    def test_patch_object_initialization(self):
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        patch = PatchObject(
            bbox=(10.0, 20.0, 110.0, 120.0),
            page_number=0,
            image_bytes=dummy_png,
            opacity=0.85
        )
        self.assertIsInstance(patch, EditableImage)
        self.assertEqual(patch.bbox, (10.0, 20.0, 110.0, 120.0))
        self.assertEqual(patch.page_number, 0)
        self.assertEqual(patch.image_bytes, dummy_png)
        self.assertEqual(patch.opacity, 0.85)
        self.assertTrue(patch.is_new)

    def test_patch_object_properties(self):
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        patch = PatchObject(
            bbox=(15.0, 25.0, 115.0, 125.0),
            page_number=1,
            image_bytes=dummy_png,
            opacity=0.9
        )
        self.assertIsInstance(patch, EditableImage)
        self.assertEqual(patch.bbox, (15.0, 25.0, 115.0, 125.0))
        self.assertEqual(patch.page_number, 1)
        self.assertEqual(patch.image_bytes, dummy_png)
        self.assertEqual(patch.opacity, 0.9)
        self.assertTrue(patch.is_new)


class TestReorderObjectCommand(unittest.TestCase):
    """Test undoable ReorderObjectCommand execution."""

    def setUp(self):
        self.doc = fitz.open()
        self.win = MockLayerWindow(self.doc)

    def tearDown(self):
        self.doc.close()

    def test_reorder_command_execute_undo_redo(self):
        t1 = EditableText(x=10, y=10, text="First")
        t2 = EditableText(x=20, y=20, text="Second")
        t3 = EditableText(x=30, y=30, text="Third")
        self.win.editable_texts = [t1, t2, t3]

        # Reorder t1 from index 0 to index 2 (bring to front)
        cmd = ReorderObjectCommand(self.win, t1, 0, 2)
        cmd.execute()
        self.assertEqual(self.win.editable_texts, [t2, t3, t1])
        self.assertTrue(self.win.document_modified)

        # Undo command
        cmd.undo()
        self.assertEqual(self.win.editable_texts, [t1, t2, t3])

        # Redo command
        cmd.redo()
        self.assertEqual(self.win.editable_texts, [t2, t3, t1])

    def test_reorder_window_actions(self):
        img1 = EditableImage(bbox=(0, 0, 50, 50), page_number=0, xref=None, image_bytes=b"dummy1")
        img2 = EditableImage(bbox=(50, 50, 100, 100), page_number=0, xref=None, image_bytes=b"dummy2")
        img3 = EditableImage(bbox=(100, 100, 150, 150), page_number=0, xref=None, image_bytes=b"dummy3")
        self.win.editable_images = [img1, img2, img3]

        # Select middle object img2
        self.win.selected_image = img2

        # Move forward -> index 2
        res = self.win.reorder_selected_object("forward")
        self.assertTrue(res)
        self.assertEqual(self.win.editable_images, [img1, img3, img2])

        # Move to back -> index 0
        res = self.win.reorder_selected_object("back")
        self.assertTrue(res)
        self.assertEqual(self.win.editable_images, [img2, img1, img3])

        # Move to front -> index 2
        res = self.win.reorder_selected_object("front")
        self.assertTrue(res)
        self.assertEqual(self.win.editable_images, [img1, img3, img2])

        # Move backward -> index 1
        res = self.win.reorder_selected_object("backward")
        self.assertTrue(res)
        self.assertEqual(self.win.editable_images, [img1, img2, img3])

        # Boundary: move backward when already at 0
        self.win.selected_image = img1
        res = self.win.reorder_selected_object("backward")
        self.assertFalse(res)

        # Boundary: move forward when already at end
        self.win.selected_image = img3
        res = self.win.reorder_selected_object("forward")
        self.assertFalse(res)


class TestPasteClonePatch(unittest.TestCase):
    """Test pasting captured clone patches onto document canvas."""

    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=600, height=800)
        self.win = MockLayerWindow(self.doc)
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        self.win.last_captured_patch = {
            "image_bytes": dummy_png,
            "bbox": (50.0, 50.0, 150.0, 110.0),
            "page_number": 0,
            "dpi": 300
        }

    def tearDown(self):
        self.doc.close()

    def test_paste_clone_patch_explicit_position(self):
        res = self.win.paste_clone_patch(center_pos=(300.0, 400.0))
        self.assertTrue(res)
        self.assertEqual(len(self.win.editable_images), 1)
        patch = self.win.editable_images[0]
        self.assertIsInstance(patch, PatchObject)
        # Size was (150-50)=100w, (110-50)=60h. Centered at (300, 400) -> (250, 370, 350, 430)
        self.assertEqual(patch.bbox, (250.0, 370.0, 350.0, 430.0))
        self.assertEqual(self.win.selected_image, patch)
        self.assertEqual(self.win.tool_mode, "select")

    def test_paste_clone_patch_boundary_clamping(self):
        # Center near right edge (580, 780)
        res = self.win.paste_clone_patch(center_pos=(580.0, 780.0))
        self.assertTrue(res)
        patch = self.win.editable_images[0]
        x1, y1, x2, y2 = patch.bbox
        self.assertGreaterEqual(x1, 0.0)
        self.assertGreaterEqual(y1, 0.0)
        self.assertLessEqual(x2, 600.0)
        self.assertLessEqual(y2, 800.0)

    def test_paste_clone_patch_without_captured_data(self):
        self.win.last_captured_patch = None
        res = self.win.paste_clone_patch((200, 200))
        self.assertFalse(res)


class TestPart55Localization(unittest.TestCase):
    """Ensure all 7 locales have complete translations for Part 55."""

    REQUIRED_KEYS = [
        "patch_placed_status",
        "patch_pasted_status",
        "action_bring_to_front",
        "action_send_to_back",
        "action_bring_forward",
        "action_send_backward",
        "status_reordered_front",
        "status_reordered_back",
        "status_reordered_forward",
        "status_reordered_backward",
        "btn_paste_patch",
        "guide_sc_layer_front",
        "guide_sc_layer_back",
        "guide_sc_layer_forward",
        "guide_sc_layer_backward",
    ]

    def test_all_locales_have_part55_keys(self):
        for lang, trans in _STRINGS.items():
            for key in self.REQUIRED_KEYS:
                self.assertIn(
                    key, trans,
                    f"Language '{lang}' missing required Part 55 localization key '{key}'"
                )
                self.assertTrue(
                    len(trans[key].strip()) > 0,
                    f"Language '{lang}' has empty text for key '{key}'"
                )


if __name__ == "__main__":
    unittest.main()

