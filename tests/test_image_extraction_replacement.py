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
