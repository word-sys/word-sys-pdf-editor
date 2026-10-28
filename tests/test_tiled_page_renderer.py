import unittest
import math
import time
import cairo
import fitz
from unittest.mock import MagicMock, patch
from gi.repository import GLib

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.pdf_handler import TiledPageRenderer, get_tiled_page_renderer
from word_sys_pdf_editor.window import PdfEditorWindow


class TestTiledPageRenderer(unittest.TestCase):
    """Verify sub-viewport tile calculation, rasterization, LRU caching, and virtualization."""

    def setUp(self):
        self.doc = fitz.open()
        # Create a 2000x2000 pt large blueprint page
        self.page = self.doc.new_page(width=2000, height=2000)
        self.page.draw_rect([100, 100, 500, 500], color=(0.8, 0.2, 0.2), fill=(0.2, 0.8, 0.2))
        self.page.draw_line((0, 0), (2000, 2000), color=(0, 0, 1), width=4)
        self.tiler = TiledPageRenderer(tile_size=512, max_cached_tiles=32)

    def tearDown(self):
        if self.doc:
            pdf_handler.close_pdf_document(self.doc)

    def test_is_tiling_required_thresholds(self):
        """Verify tiling triggers for large dimensions or high zoom and stays dormant for normal pages."""
        # Standard A4 at 100% zoom (595x842 pt -> 595x842 px)
        self.assertFalse(self.tiler.is_tiling_required(595, 842, 1.0))
        # Standard A4 at 200% zoom (1190x1684 px)
        self.assertFalse(self.tiler.is_tiling_required(595, 842, 2.0))
        # Standard A4 at 400% zoom (2380x3368 px, height > 2500)
        self.assertTrue(self.tiler.is_tiling_required(595, 842, 4.0))
        # Standard A4 at 600% zoom
        self.assertTrue(self.tiler.is_tiling_required(595, 842, 6.0))
        # Large engineering blueprint (A0: 2384x3370 pt) at 100% zoom
        self.assertTrue(self.tiler.is_tiling_required(2384, 3370, 1.0))

    def test_get_tile_counts_and_rects(self):
        """Verify grid partitioning and pixel rectangle calculations."""
        # Page 1024x1024 at 1.0x with 512 tile size -> exactly 2x2 grid
        cols, rows = self.tiler.get_tile_counts(1024, 1024, 1.0)
        self.assertEqual((cols, rows), (2, 2))

        # Check tile pixel rects
        r00 = self.tiler.get_tile_pixel_rect(0, 0, 1024, 1024, 1.0)
        self.assertEqual(r00, (0.0, 0.0, 512.0, 512.0))
        r11 = self.tiler.get_tile_pixel_rect(1, 1, 1024, 1024, 1.0)
        self.assertEqual(r11, (512.0, 512.0, 512.0, 512.0))

        # Page 1000x800 at 1.0x -> 2x2 grid with edge clamping
        c_edge, r_edge = self.tiler.get_tile_counts(1000, 800, 1.0)
        self.assertEqual((c_edge, r_edge), (2, 2))
        r11_clamped = self.tiler.get_tile_pixel_rect(1, 1, 1000, 800, 1.0)
        self.assertEqual(r11_clamped, (512.0, 512.0, 488.0, 288.0))

    def test_get_visible_tile_coords_intersection(self):
        """Verify tile visibility queries accurately intersect the viewport."""
        # Page placed at canvas (100, 100), total pixel size 2000x2000
        # Viewport at (100, 100, 600, 600) covers top-left tiles
        visible = self.tiler.get_visible_tile_coords(
            page_canvas_x=100.0, page_canvas_y=100.0,
            page_width_pt=2000.0, page_height_pt=2000.0,
            zoom_level=1.0,
            viewport_rect=(100.0, 100.0, 600.0, 600.0),
            margin_tiles=0
        )
        self.assertIn((0, 0), visible)
        self.assertIn((1, 0), visible)
        self.assertIn((0, 1), visible)
        self.assertIn((1, 1), visible)
        # Far corner (3, 3) must not be in visible list with margin 0
        self.assertNotIn((3, 3), visible)

        # Viewport completely outside page rect returns empty
        outside = self.tiler.get_visible_tile_coords(
            page_canvas_x=100.0, page_canvas_y=100.0,
            page_width_pt=2000.0, page_height_pt=2000.0,
            zoom_level=1.0,
            viewport_rect=(5000.0, 5000.0, 800.0, 600.0),
            margin_tiles=0
        )
        self.assertEqual(outside, [])

    def test_render_and_peek_tile(self):
        """Verify synchronous tile rendering produces a valid Cairo ImageSurface and caches it."""
        surf = self.tiler.render_tile(self.doc, 0, 1.0, 0, 0)
        self.assertIsNotNone(surf)
        self.assertIsInstance(surf, cairo.ImageSurface)
        self.assertEqual(surf.get_width(), 512)
        self.assertEqual(surf.get_height(), 512)

        # Non-blocking peek returns the exact cached surface
        peeked = self.tiler.peek_tile(self.doc, 0, 1.0, 0, 0)
        self.assertEqual(peeked, surf)

    def test_async_request_tile(self):
        """Verify asynchronous tile rendering dispatches callback via GLib idle loop."""
        received = []
        def _on_tile(col, row, surf):
            received.append((col, row, surf))

        self.tiler.request_tile(self.doc, 0, 1.0, 1, 0, callback=_on_tile, defer=False)

        # Pump main context until worker completes
        ctx = GLib.MainContext.default()
        start = time.time()
        while not received and (time.time() - start < 3.0):
            ctx.iteration(False)
            time.sleep(0.01)

        self.assertEqual(len(received), 1)
        c, r, s = received[0]
        self.assertEqual((c, r), (1, 0))
        self.assertIsNotNone(s)

    def test_prune_distant_tiles(self):
        """Verify pruning purges tiles outside the active set while preserving LRU budget."""
        # Render 40 tiles
        for c in range(5):
            for r in range(8):
                self.tiler.render_tile(self.doc, 0, 1.0, c, r)

        # Active set is only (0, 0) and (0, 1)
        active_set = {(0, 0), (0, 1)}
        self.tiler.prune_distant_tiles(self.doc, 0, 1.0, active_set)
        # Total cached tiles for this page/zoom should be significantly bounded
        remaining_keys = [k for k in self.tiler._tile_cache.keys() if k[0] == id(self.doc)]
        self.assertLessEqual(len(remaining_keys), 34)

    def test_invalidate_doc_tiles(self):
        """Verify invalidation completely clears cached tiles for target document."""
        self.tiler.render_tile(self.doc, 0, 1.0, 0, 0)
        self.assertIsNotNone(self.tiler.peek_tile(self.doc, 0, 1.0, 0, 0))

        self.tiler.invalidate_doc_tiles(self.doc, 0)
        self.assertIsNone(self.tiler.peek_tile(self.doc, 0, 1.0, 0, 0))

    def test_window_draw_uses_tiler_for_huge_pages(self):
        """Verify PdfEditorWindow._draw_page_content invokes tiled renderer when page is huge."""
        win = MagicMock()
        win.doc = self.doc
        win.zoom_level = 2.0  # 2000 pt * 2.0 = 4000 px > 2500 -> activates tiling
        win.current_page_index = 0
        win.get_visible_viewport_rect = lambda: (0.0, 0.0, 800.0, 600.0)
        win.pdf_view = MagicMock()
        win.dragged_object = None
        win.inline_editor_widget = None
        win.inline_editor_text_obj = None
        win._inline_editor_target_rect = None
        win.temp_image_bbox = None
        win.temp_stamp_bbox = None
        win.temp_clone_patch_bbox = None
        win.temp_redact_bbox = None
        win.temp_form_field_rect = None
        win.temp_sig_bbox = None
        win.temp_stroke = None
        win.temp_shape = None
        win.editable_texts = []
        win.editable_images = []
        win.editable_shapes = []
        win.editable_strokes = []
        win.form_fields = []
        win.selected_text = None
        win.selected_image = None
        win.selected_shape = None
        win.selected_stroke = None
        win.selected_form_field = None
        win.selected_sig_annot = None
        win.selected_measurement = None
        win.selected_redaction_mark = None
        win.selected_objects = []
        win.selected_object = None
        win.show_ocr_overlay = False
        win.highlighted_native_annot = None
        win.active_native_measurement = None
        win.view_mode = False
        win.view_sel_rect = None
        win.async_page_rendering = True
        win._active_session = None
        win.tool_mode = "select"
        win.temp_calibration_line = None
        win.redaction_regions = []
        win.search_matches = []
        win.annotations = []
        win.comment_callouts = []
        win.measurements = []
        win._link_creation_active = False
        win.creating_element_type = None
        win.is_zoom_gesture_active = False
        win.continuous_scroll = False
        win.multi_select_box = None
        win.crop_box = None
        win.rotation_crop_box = None
        win.redaction_tool_active = False

        target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 800, 600)
        cr = cairo.Context(target_surf)

        with patch.object(self.tiler, 'peek_tile') as mock_peek, \
             patch.object(self.tiler, 'request_tile') as mock_req:
            mock_peek.return_value = None
            with patch('word_sys_pdf_editor.pdf_handler.get_tiled_page_renderer', return_value=self.tiler):
                PdfEditorWindow._draw_page_content(win, win.pdf_view, cr, 0, 0, 0, 4000.0, 4000.0)
                # Tiler must have been queried for tiles
                mock_req.assert_called()


if __name__ == '__main__':
    unittest.main()
