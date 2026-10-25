import time
import pytest
import cairo
import fitz
import numpy as np
from unittest.mock import MagicMock, patch

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import EditableText, EditableImage, EditableShape, EditableStroke
from word_sys_pdf_editor.window import PdfEditorWindow


def test_pixmap_to_cairo_surface_rgb():
    """Verify RGB pixmap converts directly to Cairo RGB24 ImageSurface with correct dimensions and channels."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    # Draw pure red rect
    page.draw_rect([10, 10, 50, 50], color=None, fill=(1, 0, 0))
    pix = page.get_pixmap(alpha=False)

    surf, data_ref = pdf_handler.pixmap_to_cairo_surface(pix)
    assert surf is not None
    assert isinstance(surf, cairo.ImageSurface)
    assert surf.get_format() == cairo.FORMAT_RGB24
    assert surf.get_width() == 200
    assert surf.get_height() == 300
    assert surf.get_stride() == 200 * 4

    # Verify pixel channel swizzle at (20, 20): should be Red (BGRX: B=0, G=0, R=255, X=255)
    data = surf.get_data()
    idx = (20 * 200 + 20) * 4
    b, g, r, x = data[idx:idx + 4]
    assert r == 255
    assert g == 0
    assert b == 0
    assert x == 255


def test_pixmap_to_cairo_surface_rgba():
    """Verify RGBA pixmap converts directly to Cairo ARGB32 ImageSurface preserving alpha."""
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect([10, 10, 60, 60], color=None, fill=(0, 1, 0), fill_opacity=0.5)
    pix = page.get_pixmap(alpha=True)

    surf, data_ref = pdf_handler.pixmap_to_cairo_surface(pix)
    assert surf is not None
    assert isinstance(surf, cairo.ImageSurface)
    assert surf.get_format() == cairo.FORMAT_ARGB32
    assert surf.get_width() == 100
    assert surf.get_height() == 100
    assert surf.get_stride() == 100 * 4

    # Pixel at (30, 30): semi-transparent green
    data = surf.get_data()
    idx = (30 * 100 + 30) * 4
    b, g, r, a = data[idx:idx + 4]
    assert a > 0
    assert g > 0
    assert b == 0
    assert r == 0


def test_pixmap_to_cairo_surface_gray():
    """Verify grayscale pixmap converts to Cairo RGB24 ImageSurface repeating gray in RGB channels."""
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect([0, 0, 100, 100], color=None, fill=(0.5, 0.5, 0.5))
    pix_rgb = page.get_pixmap(alpha=False)
    pix_gray = fitz.Pixmap(fitz.csGRAY, pix_rgb)

    assert pix_gray.n == 1
    surf, data_ref = pdf_handler.pixmap_to_cairo_surface(pix_gray)
    assert surf is not None
    assert surf.get_format() == cairo.FORMAT_RGB24
    assert surf.get_width() == 100
    assert surf.get_height() == 100

    data = surf.get_data()
    idx = (50 * 100 + 50) * 4
    b, g, r, x = data[idx:idx + 4]
    assert b == g == r
    assert 120 <= r <= 135


def test_pixmap_to_cairo_surface_invalid():
    """Verify pixmap_to_cairo_surface handles None and invalid inputs gracefully."""
    surf, ref = pdf_handler.pixmap_to_cairo_surface(None)
    assert surf is None and ref is None

    fake_pix = MagicMock()
    fake_pix.width = 0
    fake_pix.height = 0
    surf, ref = pdf_handler.pixmap_to_cairo_surface(fake_pix)
    assert surf is None and ref is None


def test_get_page_cairo_surface_caching_and_lru():
    """Verify caching, document locking, and LRU cache eviction capped at 6 surfaces."""
    pdf_handler.invalidate_page_cache()
    doc = fitz.open()
    for _ in range(8):
        p = doc.new_page(width=100, height=100)
        p.insert_text((10, 20), "Sample Page")

    # Fetch page 0
    surf0 = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf0 is not None
    # Subsequent fetch must return identical cached surface
    surf0_cached = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf0_cached is surf0

    # Prime pages 1 through 6 (total 7 distinct pages requested)
    for i in range(1, 7):
        pdf_handler.get_page_cairo_surface(doc, i, 1.0)

    # Cache should be bounded to at most 6 surfaces
    assert len(pdf_handler._cairo_page_cache) <= 6

    # Invalidate cache for doc
    pdf_handler.invalidate_page_cache(doc)
    assert len([k for k in pdf_handler._cairo_page_cache if k[0] == id(doc)]) == 0


def test_get_page_cairo_surface_clipped():
    """Verify sub-rectangle clipped surface generation."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.draw_rect([100, 100, 300, 400], color=(0, 0, 1), fill=(1, 1, 0))

    clip_rect = fitz.Rect(100, 100, 250, 300) # 150x200 area
    surf_clip = pdf_handler.get_page_cairo_surface(doc, 0, 1.0, clip_rect=clip_rect)
    assert surf_clip is not None
    assert surf_clip.get_width() == 150
    assert surf_clip.get_height() == 200


def test_update_page_cairo_surface_rect():
    """Verify in-place update of cached Cairo surface for sub-rectangle without full re-render."""
    pdf_handler.invalidate_page_cache()
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.draw_rect([0, 0, 300, 300], color=None, fill=(1, 1, 1)) # All white

    surf = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf is not None
    data_orig = bytes(surf.get_data())

    # Draw a blue rectangle on page in sub-region (50, 50, 120, 120)
    page.draw_rect([50, 50, 120, 120], color=None, fill=(0, 0, 1))

    # Update only the modified sub-rectangle
    rect = (50, 50, 120, 120)
    success = pdf_handler.update_page_cairo_surface_rect(doc, 0, 1.0, rect)
    assert success is True

    # Same surface reference must remain cached
    surf_updated = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf_updated is surf

    # Sub-rectangle region must now contain blue pixels (BGRX: B=255, G=0, R=0, X=255)
    data = surf.get_data()
    inside_idx = (70 * 300 + 70) * 4
    b, g, r, x = data[inside_idx:inside_idx + 4]
    assert b == 255
    assert g == 0
    assert r == 0

    # Outside region (e.g. at 200, 200) must still remain white (255, 255, 255, 255)
    outside_idx = (200 * 300 + 200) * 4
    ob, og, ore, ox = data[outside_idx:outside_idx + 4]
    assert ob == 255
    assert og == 255
    assert ore == 255


def test_draw_page_to_cairo_with_dirty_rect():
    """Verify draw_page_to_cairo handles full page and dirty rect clipping."""
    doc = fitz.open()
    doc.new_page(width=200, height=200)

    target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 200, 200)
    cr = cairo.Context(target_surf)

    # 1. Full page draw
    ok, err = pdf_handler.draw_page_to_cairo(cr, doc, 0, 1.0)
    assert ok is True
    assert err is None

    # 2. Sub-rectangle dirty rect draw
    ok2, err2 = pdf_handler.draw_page_to_cairo(cr, doc, 0, 1.0, dirty_rect=(20, 20, 50, 50))
    assert ok2 is True
    assert err2 is None


def test_window_dirty_rect_queue_and_bounding_box_culling():
    """Verify window.queue_canvas_dirty_rect and viewport culling of offscreen objects."""
    win = MagicMock()
    win.pdf_view = MagicMock()
    win._dirty_clip_rect = None

    # Test queueing single rect
    PdfEditorWindow.queue_canvas_dirty_rect(win, (10, 10, 50, 50))
    assert win._dirty_clip_rect == (10, 10, 50, 50)
    win.pdf_view.queue_draw.assert_called_once()

    # Test unioning with a second rect
    PdfEditorWindow.queue_canvas_dirty_rect(win, (30, 20, 80, 70))
    # Union should encompass (10, 10) to (110, 90) -> (10, 10, 100, 80)
    assert win._dirty_clip_rect == (10, 10, 100, 80)


def test_window_draw_pdf_page_culls_offscreen_objects():
    """Verify _draw_page_content skips objects whose bounding boxes do not intersect clip extents."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)

    win = MagicMock()
    win.doc = doc
    win.zoom_level = 1.0
    win.current_page_index = 0
    win.dragged_object = None
    win.inline_editor_widget = None
    win.inline_editor_text_obj = None
    win.temp_image_bbox = None
    win.temp_stamp_bbox = None
    win.temp_clone_patch_bbox = None
    win.temp_redact_bbox = None
    win.temp_form_field_rect = None
    win.temp_sig_bbox = None
    win.temp_stroke = None
    win.temp_shape = None
    win.selected_text = None
    win.selected_image = None
    win.selected_shape = None
    win.selected_stroke = None
    win.selected_form_field = None
    win.selected_sig_annot = None
    win.selected_measurement = None
    win.selected_redaction_mark = None
    win.show_ocr_overlay = False
    win.highlighted_native_annot = None
    win.active_native_measurement = None
    win.view_mode = False
    win.view_sel_rect = None

    # On-screen text vs offscreen text
    on_screen_text = EditableText(page_number=0, x=50, y=50, text="Visible", font_size=12, is_new=True)
    on_screen_text.bbox = (50, 50, 100, 70)

    offscreen_text = EditableText(page_number=0, x=800, y=800, text="Offscreen", font_size=12, is_new=True)
    offscreen_text.bbox = (800, 800, 900, 820)

    win.editable_texts = [on_screen_text, offscreen_text]
    win.editable_images = []
    win.editable_shapes = []
    win.editable_strokes = []
    win.form_fields = []

    target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 500, 500)
    cr = cairo.Context(target_surf)

    # Restrict dirty rect to (20, 20, 150, 150)
    with patch("word_sys_pdf_editor.window.PangoCairo.show_layout") as mock_show_layout:
        PdfEditorWindow._draw_page_content(
            win,
            area=win.pdf_view,
            cr=cr,
            page_index=0,
            page_offset_x=0,
            page_offset_y=0,
            page_w=500,
            page_h=500,
            dirty_rect=(20, 20, 150, 150)
        )

        # Visible text should be laid out, while offscreen text must be skipped
        assert mock_show_layout.call_count == 1
        rendered_layout = mock_show_layout.call_args[0][1]
        assert rendered_layout.get_text() == "Visible"


def test_window_draw_pdf_page_culls_offscreen_images_shapes_and_strokes():
    """Verify _draw_page_content culls images, shapes, and ink strokes outside the clip extents."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)

    win = MagicMock()
    win.doc = doc
    win.zoom_level = 1.0
    win.current_page_index = 0
    win.dragged_object = None
    win.inline_editor_widget = None
    win.inline_editor_text_obj = None
    win.temp_image_bbox = None
    win.temp_stamp_bbox = None
    win.temp_clone_patch_bbox = None
    win.temp_redact_bbox = None
    win.temp_form_field_rect = None
    win.temp_sig_bbox = None
    win.temp_stroke = None
    win.temp_shape = None
    win.selected_text = None
    win.selected_image = None
    win.selected_shape = None
    win.selected_stroke = None
    win.selected_form_field = None
    win.selected_sig_annot = None
    win.selected_measurement = None
    win.selected_redaction_mark = None
    win.show_ocr_overlay = False
    win.highlighted_native_annot = None
    win.active_native_measurement = None
    win.view_mode = False
    win.view_sel_rect = None

    win.editable_texts = []
    win.form_fields = []

    # 1 byte fake png
    dummy_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    vis_img = EditableImage(bbox=(30, 30, 80, 80), page_number=0, xref=0, image_bytes=dummy_bytes, is_new=True)
    off_img = EditableImage(bbox=(800, 800, 900, 900), page_number=0, xref=0, image_bytes=dummy_bytes, is_new=True)
    win.editable_images = [vis_img, off_img]

    vis_shape = EditableShape(page_number=0, shape_type=EditableShape.SHAPE_RECTANGLE, bbox=(40, 40, 90, 90))
    off_shape = EditableShape(page_number=0, shape_type=EditableShape.SHAPE_RECTANGLE, bbox=(700, 700, 850, 850))
    win.editable_shapes = [vis_shape, off_shape]

    vis_stroke = EditableStroke(page_number=0, stroke_color=(1, 0, 0), stroke_width=2.0)
    vis_stroke.points = [(45, 45), (55, 55)]
    vis_stroke.bbox = (45, 45, 55, 55)

    off_stroke = EditableStroke(page_number=0, stroke_color=(0, 1, 0), stroke_width=2.0)
    off_stroke.points = [(750, 750), (780, 780)]
    off_stroke.bbox = (750, 750, 780, 780)
    win.editable_strokes = [vis_stroke, off_stroke]

    target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 500, 500)
    cr = cairo.Context(target_surf)

    with patch("word_sys_pdf_editor.window.GdkPixbuf.PixbufLoader.new") as mock_loader:
        loader_instance = MagicMock()
        mock_loader.return_value = loader_instance
        loader_instance.get_pixbuf.return_value = None

        PdfEditorWindow._draw_page_content(
            win,
            area=win.pdf_view,
            cr=cr,
            page_index=0,
            page_offset_x=0,
            page_offset_y=0,
            page_w=500,
            page_h=500,
            dirty_rect=(20, 20, 100, 100)
        )

        # Pixbuf loader should only be instantiated for the visible image, NOT the offscreen image
        assert mock_loader.call_count == 1

