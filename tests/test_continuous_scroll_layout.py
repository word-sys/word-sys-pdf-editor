import unittest
from unittest import mock
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
from word_sys_pdf_editor.i18n import get_setting, set_setting


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
        self.pdf_scroll = Gtk.ScrolledWindow()
        self.v_adj = Gtk.Adjustment(value=0.0, lower=0.0, upper=3000.0, step_increment=10.0, page_increment=100.0, page_size=600.0)
        self.h_adj = Gtk.Adjustment(value=0.0, lower=0.0, upper=2000.0, step_increment=10.0, page_increment=100.0, page_size=800.0)
        self.pdf_scroll.set_vadjustment(self.v_adj)
        self.pdf_scroll.set_hadjustment(self.h_adj)
        self._is_programmatic_scrolling = False
        self.window_title_widget = Adw.WindowTitle()
        self.page_label = Gtk.Label()
        self.status_label = Gtk.Label()
        self.thumbnail_selection_model = None
        self.undo_manager = unittest.mock.MagicMock()
        self._title = ""
        self._scroll_anim_id = None
        self._actions = {}
        self.continuous_scroll_btn = Gtk.ToggleButton()
        self.continuous_scroll_btn.set_icon_name("view-continuous-symbolic" if self.continuous_scroll else "view-paged-symbolic")
        self.continuous_scroll_btn.set_active(self.continuous_scroll)

    continuous_scroll = PdfEditorWindow.continuous_scroll
    _page_objects_cache = PdfEditorWindow._page_objects_cache
    _fast_get_page_dimension = PdfEditorWindow._fast_get_page_dimension
    _invalidate_continuous_layout = PdfEditorWindow._invalidate_continuous_layout
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
    _load_page = PdfEditorWindow._load_page
    _visual_to_unrotated_page_coords = PdfEditorWindow._visual_to_unrotated_page_coords
    _unrotated_to_visual_page_coords = PdfEditorWindow._unrotated_to_visual_page_coords
    _visual_to_unrotated_delta = PdfEditorWindow._visual_to_unrotated_delta
    get_visible_viewport_rect = PdfEditorWindow.get_visible_viewport_rect
    get_visible_page_indices = PdfEditorWindow.get_visible_page_indices
    get_dominant_visible_page_index = PdfEditorWindow.get_dominant_visible_page_index
    _on_canvas_scrolled = PdfEditorWindow._on_canvas_scrolled
    _sync_window_title_and_subtitle = PdfEditorWindow._sync_window_title_and_subtitle
    update_page_label = PdfEditorWindow.update_page_label
    set_continuous_scroll_mode = PdfEditorWindow.set_continuous_scroll_mode
    scroll_to_page = PdfEditorWindow.scroll_to_page
    go_to_page = PdfEditorWindow.go_to_page
    on_prev_page = PdfEditorWindow.on_prev_page
    on_next_page = PdfEditorWindow.on_next_page
    on_thumbnail_selected = PdfEditorWindow.on_thumbnail_selected

    def commit_pending_format_change(self):
        pass

    def hide_text_editor(self):
        pass

    def _clear_form_field_overlays(self):
        pass

    def _sync_thumbnail_selection(self):
        if not self.doc or not self.thumbnail_selection_model:
            return
        self._syncing_thumb = True
        self.thumbnail_selection_model.set_selected(self.current_page_index)
        self._syncing_thumb = False

    def _update_ui_state(self):
        if hasattr(self, 'page_label') and self.page_label:
            self.update_page_label()

    def _create_form_field_overlays(self):
        pass

    def set_title(self, title):
        self._title = title

    def get_title(self):
        return getattr(self, '_title', "")

    def lookup_action(self, name):
        return self._actions.get(name, None)

    def add_action(self, action):
        self._actions[action.get_name()] = action


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
        set_setting("view_mode", "single")

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

    def test_get_visible_viewport_rect(self):
        win = MockContinuousScrollWindow(self.doc)
        win.v_adj.set_value(250.0)
        win.h_adj.set_value(75.0)

        vx, vy, vw, vh = win.get_visible_viewport_rect()
        self.assertEqual(vx, 75.0)
        self.assertEqual(vy, 250.0)
        self.assertEqual(vw, 800.0)
        self.assertEqual(vh, 600.0)

    def test_get_visible_page_indices_single_page(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = False
        win.current_page_index = 1
        visible = win.get_visible_page_indices()
        self.assertEqual(visible, [1])

    def test_get_visible_page_indices_continuous_culling(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win._recompute_continuous_layout()

        # At top of document: y=0, viewport height=600, prefetch margin=300
        # Visible range: [-300, 900].
        # Page 0: [16, 816] -> visible
        # Page 1: [832, 1532] -> visible (832 <= 900)
        # Page 2: [1548, 2448] -> culled (1548 > 900)
        win.v_adj.set_value(0.0)
        visible_top = win.get_visible_page_indices(prefetch_margin=300.0)
        self.assertEqual(visible_top, [0, 1])

        # Scrolled to bottom: y=1800, viewport height=600, prefetch margin=200
        # Visible range: [1600, 2600].
        # Page 0: [16, 816] -> culled (816 < 1600)
        # Page 1: [832, 1532] -> culled (1532 < 1600)
        # Page 2: [1548, 2448] -> visible (2448 >= 1600 and 1548 <= 2600)
        win.v_adj.set_value(1800.0)
        visible_bottom = win.get_visible_page_indices(prefetch_margin=200.0)
        self.assertEqual(visible_bottom, [2])

    def test_get_dominant_visible_page_index(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win._recompute_continuous_layout()

        # At top: y=0, viewport height=600
        # Page 0 covers 16 to 600 = 584px
        win.v_adj.set_value(0.0)
        self.assertEqual(win.get_dominant_visible_page_index(), 0)

        # Scrolled down: y=900, viewport height=600 (range: [900, 1500])
        # Page 0 ends at 816 -> 0px visible
        # Page 1 covers 900 to 1500 = 600px visible
        win.v_adj.set_value(900.0)
        self.assertEqual(win.get_dominant_visible_page_index(), 1)

        # Scrolled to bottom: y=1900, viewport height=600 (range: [1900, 2500])
        # Page 2 covers 1900 to 2448 = 548px visible
        win.v_adj.set_value(1900.0)
        self.assertEqual(win.get_dominant_visible_page_index(), 2)

    def test_on_canvas_scrolled_dominant_page_sync(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win._recompute_continuous_layout()

        # Create mock thumbnail selection model
        win.thumbnail_selection_model = Gtk.SingleSelection()

        # Scroll to page 1 region: y=900
        win.v_adj.set_value(900.0)
        win._on_canvas_scrolled(win.v_adj)

        # Active page should have switched to 1
        self.assertEqual(win.current_page_index, 1)
        # Page counter label and header subtitle should be updated
        self.assertIn("2", win.page_label.get_text())
        self.assertIn("2", win.window_title_widget.get_subtitle())

    def test_programmatic_scrolling_guard(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win._recompute_continuous_layout()

        win._is_programmatic_scrolling = True
        win.v_adj.set_value(900.0)
        win._on_canvas_scrolled(win.v_adj)

        # Guard prevented page switch
        self.assertEqual(win.current_page_index, 0)

    def test_sync_window_title_and_subtitle(self):
        win = MockContinuousScrollWindow(self.doc)
        win.current_page_index = 0
        win._active_session = DocumentSession()
        win._active_session.doc = self.doc
        win._active_session.pdf_path = "/path/to/test_sample.pdf"

        win._sync_window_title_and_subtitle()
        self.assertIn("test_sample.pdf", win.window_title_widget.get_title())
        self.assertIn("1", win.window_title_widget.get_subtitle())
        self.assertIn("3", win.window_title_widget.get_subtitle())

        # Switch to page 2 (index 1)
        win.current_page_index = 1
        win._sync_window_title_and_subtitle()
        self.assertIn("2", win.window_title_widget.get_subtitle())
        self.assertIn("3", win.window_title_widget.get_subtitle())

    def test_view_mode_settings_persistence(self):
        orig_mode = get_setting("view_mode", "single")
        try:
            set_setting("view_mode", "continuous")
            self.assertEqual(get_setting("view_mode"), "continuous")
            set_setting("view_mode", "single")
            self.assertEqual(get_setting("view_mode"), "single")
        finally:
            set_setting("view_mode", orig_mode)

    def test_set_continuous_scroll_mode_toggle(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = False
        self.assertFalse(win.continuous_scroll)

        # Toggle to continuous
        win.set_continuous_scroll_mode(True)
        self.assertTrue(win.continuous_scroll)
        self.assertTrue(win.continuous_scroll_btn.get_active())
        self.assertEqual(win.continuous_scroll_btn.get_icon_name(), "view-continuous-symbolic")

        # Toggle back to single
        win.set_continuous_scroll_mode(False)
        self.assertFalse(win.continuous_scroll)
        self.assertFalse(win.continuous_scroll_btn.get_active())
        self.assertEqual(win.continuous_scroll_btn.get_icon_name(), "view-paged-symbolic")

    def test_scroll_to_page_instant(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win._recompute_continuous_layout()

        # Instant jump to page 1
        win.scroll_to_page(1, smooth=False)
        self.assertEqual(win.current_page_index, 1)
        self.assertEqual(win.v_adj.get_value(), 832.0)

        # Instant jump to page 2
        win.scroll_to_page(2, smooth=False)
        self.assertEqual(win.current_page_index, 2)
        self.assertEqual(win.v_adj.get_value(), 1548.0)

    def test_scroll_to_page_smooth(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win._recompute_continuous_layout()

        win.scroll_to_page(1, smooth=True, duration_ms=50)
        self.assertIsNotNone(win._scroll_anim_id)
        if win._scroll_anim_id:
            try:
                GLib.source_remove(win._scroll_anim_id)
            except Exception:
                pass
            win._scroll_anim_id = None

    def test_go_to_page_navigation(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win._recompute_continuous_layout()

        # User enters page 2 (index 1)
        win.go_to_page(2, smooth=False)
        self.assertEqual(win.current_page_index, 1)
        self.assertEqual(win.v_adj.get_value(), 832.0)

        # Clamped out of bounds
        win.go_to_page(999, smooth=False)
        self.assertEqual(win.current_page_index, 2)
        self.assertEqual(win.v_adj.get_value(), 1548.0)

    def test_prev_next_page_continuous_navigation(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win._recompute_continuous_layout()

        # Instant navigation
        win.on_next_page(None, smooth=False)
        self.assertEqual(win.current_page_index, 1)
        self.assertEqual(win.v_adj.get_value(), 832.0)

        win.on_prev_page(None, smooth=False)
        self.assertEqual(win.current_page_index, 0)
        self.assertEqual(win.v_adj.get_value(), 16.0)

        # Smooth navigation starts animation
        win.on_next_page(None, smooth=True)
        self.assertEqual(win.current_page_index, 1)
        self.assertIsNotNone(win._scroll_anim_id)
        if win._scroll_anim_id:
            try:
                GLib.source_remove(win._scroll_anim_id)
            except Exception:
                pass
            win._scroll_anim_id = None

    def test_thumbnail_selected_continuous_scroll(self):
        win = MockContinuousScrollWindow(self.doc)
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win._recompute_continuous_layout()

        mock_sel = unittest.mock.MagicMock()
        mock_sel.get_selected.return_value = 2

        win.on_thumbnail_selected(mock_sel, 0, 0, smooth=False)
        self.assertEqual(win.current_page_index, 2)
        self.assertEqual(win.v_adj.get_value(), 1548.0)

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

        # Verify viewport focus scroll prevention and autoselect guard
        self.assertFalse(win.pdf_viewport.get_scroll_to_focus())
        self.assertFalse(win.thumbnail_selection_model.get_autoselect())


if __name__ == '__main__':
    unittest.main()
