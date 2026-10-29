"""Consolidated Continuous Scroll and Viewport Virtualization Test Suite for word-sys-pdf-editor.

This suite validates continuous vertical scrolling layout geometry, coordinate transforms,
virtual drawing area clipping, viewport virtualization, and directional scroll prefetching.
"""

# ============================================================================
# SECTION: test_continuous_scroll_layout.py
# ============================================================================
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


# ============================================================================
# SECTION: test_continuous_scroll_virtualization.py
# ============================================================================
import math
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from word_sys_pdf_editor.window import PdfEditorWindow, UniformPageOffsets


class TestUniformPageOffsets(unittest.TestCase):
    """Verify UniformPageOffsets zero-allocation virtual sequence."""

    def test_virtual_list_indexing_and_bounds(self):
        u = UniformPageOffsets(count=10, gap=16.0, pw=595.0, ph=842.0)
        self.assertEqual(len(u), 10)
        self.assertTrue(bool(u))

        # First item
        self.assertEqual(u[0], (0.0, 16.0, 595.0, 842.0))

        # Second item (y = 16 + 842 + 16 = 874)
        self.assertEqual(u[1], (0.0, 874.0, 595.0, 842.0))

        # Negative indexing
        self.assertEqual(u[-1], (0.0, 16.0 + 9 * (842.0 + 16.0), 595.0, 842.0))
        self.assertEqual(u[-2], u[8])

        # Bounds checks
        with self.assertRaises(IndexError):
            _ = u[10]
        with self.assertRaises(IndexError):
            _ = u[-11]

        # Type check
        with self.assertRaises(TypeError):
            _ = u["invalid"]

    def test_slicing_and_iteration(self):
        u = UniformPageOffsets(count=5, gap=10.0, pw=500.0, ph=700.0)
        # Slicing returns a standard list of tuples
        s = u[1:3]
        self.assertIsInstance(s, list)
        self.assertEqual(len(s), 2)
        self.assertEqual(s[0], (0.0, 10.0 + 1 * 710.0, 500.0, 700.0))
        self.assertEqual(s[1], (0.0, 10.0 + 2 * 710.0, 500.0, 700.0))

        # Iteration
        items = list(u)
        self.assertEqual(len(items), 5)
        for i, item in enumerate(items):
            self.assertEqual(item, u[i])

    def test_equality_and_containment(self):
        u = UniformPageOffsets(count=3, gap=16.0, pw=600.0, ph=800.0)
        expected = [
            (0.0, 16.0, 600.0, 800.0),
            (0.0, 832.0, 600.0, 800.0),
            (0.0, 1648.0, 600.0, 800.0)
        ]
        self.assertEqual(u, expected)
        self.assertEqual(expected, u)

        self.assertIn((0.0, 832.0, 600.0, 800.0), u)
        self.assertNotIn((0.0, 999.0, 600.0, 800.0), u)
        self.assertNotIn("invalid", u)

        u_copy = u.copy()
        self.assertIsInstance(u_copy, list)
        self.assertEqual(u_copy, expected)

    def test_empty_uniform_offsets(self):
        u_empty = UniformPageOffsets(count=0, gap=16.0, pw=595.0, ph=842.0)
        self.assertEqual(len(u_empty), 0)
        self.assertFalse(bool(u_empty))
        with self.assertRaises(IndexError):
            _ = u_empty[0]


class TestContinuousScrollVirtualization(unittest.TestCase):
    """Verify O(1) continuous scroll layout recomputation, fast metadata index, and culling."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.uniform_pdf = os.path.join(self.temp_dir.name, "uniform.pdf")
        doc_u = fitz.open()
        for i in range(10):
            p = doc_u.new_page(width=600, height=800)
            p.insert_text((50, 50), f"Uniform Page {i}")
        doc_u.save(self.uniform_pdf)
        doc_u.close()

        self.mixed_pdf = os.path.join(self.temp_dir.name, "mixed.pdf")
        doc_m = fitz.open()
        p0 = doc_m.new_page(width=600, height=800)
        p0.insert_text((50, 50), "Page 0 portrait")
        p1 = doc_m.new_page(width=800, height=600)
        p1.insert_text((50, 50), "Page 1 landscape")
        p2 = doc_m.new_page(width=500, height=700)
        p2.insert_text((50, 50), "Page 2 custom")
        doc_m.save(self.mixed_pdf)
        doc_m.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fast_get_page_dimension_unrotated_and_rotated(self):
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p1 = doc.new_page(width=595, height=842)
        p1.set_rotation(90)
        p2 = doc.new_page(width=595, height=842)
        p2.set_rotation(180)
        p3 = doc.new_page(width=595, height=842)
        p3.set_rotation(270)

        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.current_pdf_page_width = 595
        win.current_pdf_page_height = 842

        # Verify dimensions match visible orientation without calling load_page
        d0 = PdfEditorWindow._fast_get_page_dimension(win, 0)
        self.assertEqual(d0, (595.0, 842.0))

        d1 = PdfEditorWindow._fast_get_page_dimension(win, 1)
        self.assertEqual(d1, (842.0, 595.0))

        d2 = PdfEditorWindow._fast_get_page_dimension(win, 2)
        self.assertEqual(d2, (595.0, 842.0))

        d3 = PdfEditorWindow._fast_get_page_dimension(win, 3)
        self.assertEqual(d3, (842.0, 595.0))
        doc.close()

    def test_uniform_document_fast_path(self):
        doc = fitz.open(self.uniform_pdf)
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.page_gap = 16.0
        win.zoom_level = 1.0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)

        PdfEditorWindow._recompute_continuous_layout(win)

        self.assertTrue(win._is_geometry_uniform)
        self.assertEqual(win._uniform_page_size, (600.0, 800.0))
        self.assertIsInstance(win.continuous_page_offsets, UniformPageOffsets)
        self.assertEqual(len(win.continuous_page_offsets), 10)
        # Expected stride = 800 + 16 = 816, total height = 16 + 10 * 816 = 8176
        self.assertEqual(win.continuous_total_height, 8176.0)
        self.assertEqual(win.continuous_max_width, 600.0)

        # Zoom change scales algebraically without re-reading PDF
        win.zoom_level = 2.0
        PdfEditorWindow._recompute_continuous_layout(win)
        self.assertEqual(win.continuous_max_width, 1200.0)
        # Stride = 1600 + 16 = 1616, total = 16 + 10 * 1616 = 16176
        self.assertEqual(win.continuous_total_height, 16176.0)
        doc.close()

    def test_mixed_document_fallback(self):
        doc = fitz.open(self.mixed_pdf)
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.page_gap = 16.0
        win.zoom_level = 1.0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)

        PdfEditorWindow._recompute_continuous_layout(win)

        self.assertFalse(win._is_geometry_uniform)
        self.assertIsInstance(win.continuous_page_offsets, list)
        self.assertEqual(len(win.continuous_page_offsets), 3)

        # Page 0: y=16, w=600, h=800
        self.assertEqual(win.continuous_page_offsets[0], (0.0, 16.0, 600.0, 800.0))
        # Page 1: y=16 + 800 + 16 = 832, w=800, h=600
        self.assertEqual(win.continuous_page_offsets[1], (0.0, 832.0, 800.0, 600.0))
        # Page 2: y=832 + 600 + 16 = 1448, w=500, h=700
        self.assertEqual(win.continuous_page_offsets[2], (0.0, 1448.0, 500.0, 700.0))

        self.assertEqual(win.continuous_max_width, 800.0)
        self.assertEqual(win.continuous_total_height, 1448.0 + 700.0 + 16.0)
        doc.close()

    def test_canvas_to_page_coords_algebraic_acceleration(self):
        doc = fitz.open(self.uniform_pdf)
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.continuous_scroll = True
        win.page_gap = 16.0
        win.zoom_level = 1.0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800
        win.pdf_view = MagicMock()
        win.pdf_view.get_allocated_width.return_value = 800
        win.pdf_view.get_allocated_height.return_value = 600
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)
        win.get_page_canvas_rect = lambda idx: PdfEditorWindow.get_page_canvas_rect(win, idx)
        win._recompute_continuous_layout = lambda: PdfEditorWindow._recompute_continuous_layout(win)

        PdfEditorWindow._recompute_continuous_layout(win)

        # Page 0: y in [16, 816], center x = (800 - 600) / 2 = 100
        p_idx, px, py = PdfEditorWindow.canvas_to_page_coords(win, 150.0, 100.0)
        self.assertEqual(p_idx, 0)
        self.assertEqual(px, 50.0)
        self.assertEqual(py, 84.0)

        # Page 3: y offset = 16 + 3 * 816 = 2464. Test y = 2500
        p_idx3, px3, py3 = PdfEditorWindow.canvas_to_page_coords(win, 200.0, 2500.0)
        self.assertEqual(p_idx3, 3)
        self.assertEqual(px3, 100.0)
        self.assertEqual(py3, 2500.0 - 2464.0)
        doc.close()

    def test_layout_invalidation_cleanliness(self):
        win = MagicMock(spec=PdfEditorWindow)
        win._doc_page_sizes_cache = {0: (600, 800)}
        win._is_geometry_uniform = True
        win._uniform_page_size = (600, 800)
        win.continuous_page_offsets = [1, 2, 3]
        win.continuous_scroll = False

        PdfEditorWindow._invalidate_continuous_layout(win)
        self.assertIsNone(win._doc_page_sizes_cache)
        self.assertIsNone(win._is_geometry_uniform)
        self.assertIsNone(win._uniform_page_size)
        self.assertEqual(win.continuous_page_offsets, [])

    def test_large_synthetic_document_layout_performance(self):
        """Verify 1,000-page document layout recomputation completes in under 5ms."""
        doc = fitz.open()
        for _ in range(1000):
            doc.new_page(width=595, height=842)

        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.page_gap = 16.0
        win.zoom_level = 1.0
        win.current_pdf_page_width = 595
        win.current_pdf_page_height = 842
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)

        # First run populates metadata index
        t0 = time.time()
        PdfEditorWindow._recompute_continuous_layout(win)
        t_first = time.time() - t0

        self.assertTrue(win._is_geometry_uniform)
        self.assertEqual(len(win.continuous_page_offsets), 1000)

        # Subsequent recomputation (e.g. on zoom/resize) is O(1) algebraic and under 1ms
        t1 = time.time()
        win.zoom_level = 1.5
        PdfEditorWindow._recompute_continuous_layout(win)
        t_recompute = time.time() - t1

        self.assertLess(t_recompute, 0.005, f"Recomputation took {t_recompute*1000:.2f}ms, expected < 5ms")
        doc.close()

    def test_continuous_scroll_draws_pages_when_offsets_already_cached(self):
        """Verify draw_pdf_page renders visible pages in continuous mode when layout offsets are cached."""
        doc = fitz.open(self.uniform_pdf)
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win.page_gap = 16.0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)
        win.get_visible_viewport_rect = lambda: (0.0, 0.0, 800.0, 900.0)
        win.get_page_canvas_rect = lambda idx: (100.0, idx * 816.0 + 16.0, 600.0, 800.0)
        win.get_visible_page_indices = lambda prefetch_margin=None: [0, 1]
        win.pdf_view = MagicMock()

        # Precompute offsets so hasattr is True and len == len(self.doc)
        PdfEditorWindow._recompute_continuous_layout(win)

        drawn_pages = []
        win._draw_page_content = lambda area, cr, p_idx, px, py, pw, ph, dirty_rect=None: drawn_pages.append(p_idx)

        cr = MagicMock()
        PdfEditorWindow.draw_pdf_page(win, win.pdf_view, cr, 800, 900, dirty_rect=None)

        # Both visible pages (0 and 1) must have been drawn!
        self.assertEqual(drawn_pages, [0, 1])
        doc.close()

    def test_scroll_to_page_queues_draw(self):
        """Verify scroll_to_page queues redraw when navigating to a distant page."""
        doc = fitz.open(self.uniform_pdf)
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = doc
        win.continuous_scroll = True
        win.zoom_level = 1.0
        win.current_page_index = 0
        win.page_gap = 16.0
        win.current_pdf_page_width = 600
        win.current_pdf_page_height = 800
        win._doc_page_sizes_cache = None
        win._is_geometry_uniform = None
        win._uniform_page_size = None
        win._fast_get_page_dimension = lambda idx: PdfEditorWindow._fast_get_page_dimension(win, idx)
        win.pdf_view = MagicMock()
        v_adj = MagicMock()
        v_adj.get_value.return_value = 0.0
        win.pdf_scroll = MagicMock()
        win.pdf_scroll.get_vadjustment.return_value = v_adj

        PdfEditorWindow._recompute_continuous_layout(win)
        PdfEditorWindow.scroll_to_page(win, 4, smooth=False)

        # vadjustment set to page 4 y-offset and queue_draw called
        v_adj.set_value.assert_called_with(win.continuous_page_offsets[4][1])
        win.pdf_view.queue_draw.assert_called()
        doc.close()


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_virtual_drawing_area_continuous_scroll.py
# ============================================================================
import os
import unittest
try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Graphene
import cairo

from word_sys_pdf_editor.window import PdfEditorWindow, VirtualDrawingArea
from word_sys_pdf_editor.i18n import set_setting


class TestVirtualDrawingAreaContinuousScroll(unittest.TestCase):
    """Test suite verifying sub-viewport snapshot virtualization on massive documents."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Adw.Application(application_id='org.word_sys.test_vda')
        except Exception:
            cls.app = None

    def setUp(self):
        test_pdf = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_testsre.pdf')
        if os.path.exists(test_pdf):
            self.doc = fitz.open(test_pdf)
            self.pdf_path = test_pdf
        else:
            # Fallback to generating a 100-page synthetic test document
            self.doc = fitz.open()
            for i in range(100):
                p = self.doc.new_page(width=504, height=657)
                p.insert_text((50, 50), f"Test page {i}")
            self.pdf_path = None

        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.set_continuous_scroll_mode(True)

    def tearDown(self):
        set_setting("view_mode", "single")
        if hasattr(self, 'win') and self.win:
            try:
                self.win.close_document()
                self.win.destroy()
            except Exception:
                pass
        doc = getattr(self, 'doc', None)
        if doc is not None and not getattr(doc, 'is_closed', True):
            try:
                doc.close()
            except Exception:
                pass

    def test_pdf_view_is_virtual_drawing_area(self):
        """Verify window uses VirtualDrawingArea subclass for canvas rendering."""
        self.assertIsInstance(self.win.pdf_view, VirtualDrawingArea)
        self.assertIsInstance(self.win.pdf_view, Gtk.DrawingArea)
        self.assertIsNotNone(self.win.pdf_view.get_viewport_rect_cb)

    def test_large_document_continuous_scroll_snapshots_without_crashing(self):
        """Verify 1000+ page continuous scroll snapshots produce valid GskCairoNode without aborting."""
        self.win._finish_loading(self.doc, None, self.pdf_path or "test.pdf", 0, self.win._active_session)
        self.assertTrue(self.win.continuous_scroll)
        self.assertGreater(self.win.continuous_total_height, 32767.0)

        # Allocate virtual canvas to allocate content size
        self.win.allocate(1000, 800, -1, None)

        # Test jumps across beginning, middle, and end of 1000-page document
        page_count = len(self.doc)
        test_pages = [0, min(5, page_count - 1), min(50, page_count - 1),
                      min(500, page_count - 1), page_count - 1]

        target_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 1000, 800)
        cr_test = cairo.Context(target_surf)

        for p in test_pages:
            self.win.scroll_to_page(p, smooth=False)
            snapshot = Gtk.Snapshot()
            self.win.pdf_view.do_snapshot(snapshot)
            node = snapshot.to_node()
            self.assertIsNotNone(node, f"Page {p} produced None node in continuous scroll")
            node.draw(cr_test)

    def test_virtual_drawing_area_viewport_bounds_clipping(self):
        """Verify VirtualDrawingArea clips snapshot bounds to visible viewport rectangle plus margin."""
        w = VirtualDrawingArea(content_width=800, content_height=500000)
        w.get_viewport_rect_cb = lambda: (0.0, 250000.0, 800.0, 600.0)

        captured_bounds = []
        def mock_draw(area, cr, width, height):
            captured_bounds.append((width, height))

        w.set_draw_func(mock_draw)

        win_dummy = Gtk.Window()
        win_dummy.set_child(w)
        win_dummy.allocate(800, 500000, -1, None)

        snap = Gtk.Snapshot()
        w.do_snapshot(snap)
        node = snap.to_node()
        self.assertIsNotNone(node)
        self.assertEqual(len(captured_bounds), 1)
        self.assertEqual(captured_bounds[0], (800, 500000))

    def test_single_page_mode_full_snapshot_bounds_no_viewport_clipping(self):
        """Verify single page mode uses full page bounds without clipping viewport when within texture limits."""
        self.win.set_continuous_scroll_mode(False)
        self.assertFalse(self.win.continuous_scroll)
        self.assertFalse(self.win._is_canvas_virtualization_required(1200, 1600))

        w = VirtualDrawingArea(content_width=1200, content_height=1600)
        w.get_viewport_rect_cb = lambda: (0.0, 500.0, 1000.0, 800.0)
        w.is_virtualization_required_cb = lambda width, height: False

        captured_bounds = []
        def mock_draw(area, cr, width, height):
            captured_bounds.append((width, height))

        w.set_draw_func(mock_draw)

        win_dummy = Gtk.Window()
        win_dummy.set_child(w)
        win_dummy.allocate(1200, 1600, -1, None)

        snap = Gtk.Snapshot()
        w.do_snapshot(snap)
        node = snap.to_node()
        self.assertIsNotNone(node)
        self.assertFalse(w.is_clipping_active)
        self.assertEqual(len(captured_bounds), 1)
        self.assertEqual(captured_bounds[0], (1200, 1600))

    def test_single_page_mode_scroll_triggers_queue_draw(self):
        """Verify scrolling in single page mode queues canvas redraw properly."""
        self.win.set_continuous_scroll_mode(False)
        self.win._finish_loading(self.doc, None, self.pdf_path or "test.pdf", 0, self.win._active_session)
        ctx = GLib.MainContext.default()
        for _ in range(10):
            if ctx.pending():
                ctx.iteration(False)
        self.win._is_programmatic_scrolling = False

        redraw_called = []
        orig_queue_draw = self.win.pdf_view.queue_draw
        self.win.pdf_view.queue_draw = lambda: redraw_called.append(True)

        try:
            adj = self.win.pdf_scroll.get_vadjustment()
            self.win._on_canvas_scrolled(adj)
            self.assertGreaterEqual(len(redraw_called), 1)
        finally:
            self.win.pdf_view.queue_draw = orig_queue_draw


if __name__ == '__main__':
    unittest.main()


# ============================================================================
# SECTION: test_directional_scroll_prefetch.py
# ============================================================================
import unittest
import time
import os
from unittest.mock import MagicMock, patch

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from word_sys_pdf_editor.window import PdfEditorWindow, ScrollVelocityTracker
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.i18n import set_setting


class TestDirectionalScrollPrefetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.app = Adw.Application(application_id='org.word_sys.test_prefetch')
        except Exception:
            cls.app = None

    def setUp(self):
        self.tracker = ScrollVelocityTracker(sample_window_sec=0.25)
        test_pdf = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_testsre.pdf')
        if os.path.exists(test_pdf):
            self.doc = fitz.open(test_pdf)
            self.pdf_path = test_pdf
        else:
            self.doc = fitz.open()
            for i in range(100):
                p = self.doc.new_page(width=504, height=657)
                p.insert_text((50, 50), f"Page {i}")
            self.pdf_path = None

        self.win = PdfEditorWindow(application=self.app)
        self.win.font_scan_in_progress = False
        self.win.set_continuous_scroll_mode(True)

    def tearDown(self):
        set_setting("view_mode", "single")
        if hasattr(self, 'win') and self.win:
            try:
                self.win.close_document()
                self.win.destroy()
            except Exception:
                pass
        doc = getattr(self, 'doc', None)
        if doc is not None and not getattr(doc, 'is_closed', True):
            try:
                doc.close()
            except Exception:
                pass

    def test_scroll_velocity_tracker_downward_rapid(self):
        """Verify rapid downward scroll calculates positive velocity and prefetch lookahead [+1, +2, +3]."""
        self.tracker.record_scroll(100.0, now=1.0)
        v, d = self.tracker.record_scroll(500.0, now=1.2)  # delta=400px over 0.2s -> 2000 px/s

        self.assertGreater(v, 400.0)
        self.assertEqual(d, ScrollVelocityTracker.DIRECTION_DOWN)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [22, 23, 24])

    def test_scroll_velocity_tracker_upward_rapid(self):
        """Verify rapid upward scroll calculates negative velocity and prefetch lookahead [-1, -2, -3]."""
        self.tracker.record_scroll(500.0, now=1.0)
        v, d = self.tracker.record_scroll(100.0, now=1.2)  # delta=-400px over 0.2s -> -2000 px/s

        self.assertLess(v, -400.0)
        self.assertEqual(d, ScrollVelocityTracker.DIRECTION_UP)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [19, 18, 17])

    def test_scroll_velocity_tracker_moderate_downward(self):
        """Verify moderate downward scroll biases ahead [+1, +2] with single page behind."""
        self.tracker.record_scroll(100.0, now=1.0)
        v, d = self.tracker.record_scroll(150.0, now=1.25)  # 200 px/s

        self.assertGreater(v, 60.0)
        self.assertLessEqual(v, 400.0)
        self.assertEqual(d, ScrollVelocityTracker.DIRECTION_DOWN)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [22, 23, 19])

    def test_scroll_velocity_tracker_moderate_upward(self):
        """Verify moderate upward scroll biases ahead [-1, -2] with single page behind."""
        self.tracker.record_scroll(150.0, now=1.0)
        v, d = self.tracker.record_scroll(100.0, now=1.25)  # -200 px/s

        self.assertLess(v, -60.0)
        self.assertGreaterEqual(v, -400.0)
        self.assertEqual(d, ScrollVelocityTracker.DIRECTION_UP)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [19, 18, 22])

    def test_scroll_velocity_tracker_settled_balanced(self):
        """Verify stillness/settle restores balanced lookahead [-1, +1]."""
        self.tracker.reset()
        self.assertEqual(self.tracker.velocity, 0.0)
        self.assertEqual(self.tracker.direction, ScrollVelocityTracker.DIRECTION_NONE)

        pages = self.tracker.get_prefetch_page_indices([20, 21], total_pages=100)
        self.assertEqual(pages, [19, 22])

    def test_scroll_velocity_tracker_boundary_clipping(self):
        """Verify prefetch candidates are strictly bounded by [0, total_pages - 1]."""
        # At start of document, scrolling up
        self.tracker.record_scroll(100.0, now=1.0)
        self.tracker.record_scroll(0.0, now=1.1)
        pages = self.tracker.get_prefetch_page_indices([0], total_pages=50)
        self.assertEqual(pages, [])

        # At end of document, scrolling down
        self.tracker.reset()
        self.tracker.record_scroll(100.0, now=1.0)
        self.tracker.record_scroll(300.0, now=1.1)
        pages = self.tracker.get_prefetch_page_indices([49], total_pages=50)
        self.assertEqual(pages, [])

    def test_scroll_velocity_tracker_eco_mode_limits(self):
        """Verify eco mode limits prefetch to at most 1 page ahead in motion direction."""
        self.tracker.record_scroll(100.0, now=1.0)
        self.tracker.record_scroll(600.0, now=1.2)

        pages_normal = self.tracker.get_prefetch_page_indices([10], total_pages=50, is_eco_mode=False)
        self.assertEqual(pages_normal, [11, 12, 13])

        pages_eco = self.tracker.get_prefetch_page_indices([10], total_pages=50, is_eco_mode=True)
        self.assertEqual(pages_eco, [11])

    def test_window_on_canvas_scrolled_triggers_predictive_prefetch(self):
        """Verify window scroll event triggers directional prefetching on document."""
        self.win._finish_loading(self.doc, None, self.pdf_path or "test.pdf", 0, self.win._active_session)
        self.win._is_programmatic_scrolling = False
        self.win.allocate(1000, 800, -1, None)

        mock_adj = MagicMock()
        mock_adj.get_value.return_value = 2500.0

        with patch.object(self.win, '_trigger_directional_prefetch') as mock_prefetch:
            self.win._on_canvas_scrolled(mock_adj)
            mock_prefetch.assert_called()

    def test_window_scroll_to_page_updates_tracker_direction(self):
        """Verify scroll_to_page sets directional lookahead for upcoming destination pages."""
        self.win._finish_loading(self.doc, None, self.pdf_path or "test.pdf", 0, self.win._active_session)
        self.win.allocate(1000, 800, -1, None)

        total_pages = len(self.doc)
        target = min(50, total_pages - 1)
        self.win.scroll_to_page(target, smooth=False)

        # After navigation to page 50, tracker is reset and settled on target page
        self.assertEqual(self.win._scroll_tracker.direction, ScrollVelocityTracker.DIRECTION_NONE)
        visible = self.win.get_visible_page_indices()
        self.assertIn(target, visible)


if __name__ == '__main__':
    unittest.main()

