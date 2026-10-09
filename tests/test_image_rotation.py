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
