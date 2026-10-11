# -*- coding: utf-8 -*-
"""Test suite for Part 33: Annotations Tree List Sidebar.

Verifies:
- AnnotationListItem model properties and formatting.
- AnnotationsSidebar layout, Gtk.ListView setup, and controls.
- Extraction and population of text, shapes, strokes, images, forms, measurements, and native PDF annotations.
- Real-time search query filtering and category dropdown filtering.
- Item activation and selection navigation, canvas highlighting, and scrolling.
- Bi-directional selection synchronization from canvas to sidebar.
- Toggle visibility and undo/redo synchronization.
"""

import sys
import unittest
import gi
import fitz

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GLib

from word_sys_pdf_editor.models import (
    EditableText,
    EditableShape,
    EditableStroke,
    EditableImage,
    AcroFormField,
    MeasurementObject,
    DocumentSession,
)
from word_sys_pdf_editor.annotations_sidebar import (
    AnnotationListItem,
    AnnotationsSidebar,
)
from word_sys_pdf_editor.undo_manager import UndoManager, Command


class DummyWindow:
    """Mock PdfEditorWindow for unit testing AnnotationsSidebar integration."""

    def __init__(self):
        self.doc = None
        self._active_session = None
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None
        self.highlighted_native_annot = None
        self.scrolled_rect = None
        self.loaded_pages = []
        self.queue_draw_called = False

        self.pdf_view = Gtk.DrawingArea()
        self.pdf_scroll = Gtk.ScrolledWindow()
        self.toggle_annotations_button = Gtk.ToggleButton()
        self.annotations_sidebar = None

    def _load_page(self, page_index, preserve_scroll=False, reload_objects=True):
        self.current_page_index = page_index
        self.loaded_pages.append(page_index)

    def _unrotated_to_visual_page_coords(self, x, y):
        return x, y

    @property
    def current_pdf_page_width(self):
        return 600

    @property
    def current_pdf_page_height(self):
        return 800

    def _update_ui_state(self):
        pass

    def _update_undo_redo_buttons(self):
        pass

    def select_and_scroll_to_annotation(self, item):
        from word_sys_pdf_editor.window import PdfEditorWindow
        PdfEditorWindow.select_and_scroll_to_annotation(self, item)

    def scroll_to_object_rect(self, page_index, bbox):
        self.scrolled_rect = (page_index, bbox)

    def refresh_annotations_list(self):
        if self.annotations_sidebar and self.annotations_sidebar.get_visible():
            self.annotations_sidebar.refresh()

    def toggle_annotations_sidebar(self, visible=None):
        from word_sys_pdf_editor.window import PdfEditorWindow
        PdfEditorWindow.toggle_annotations_sidebar(self, visible)


class TestAnnotationsSidebar(unittest.TestCase):
    """Test suite covering Part 33 Annotations Tree List Sidebar functionality."""

    @classmethod
    def setUpClass(cls):
        Gtk.init()

    def setUp(self):
        self.window = DummyWindow()
        self.sidebar = AnnotationsSidebar(editor_window=self.window)
        self.window.annotations_sidebar = self.sidebar

        # Create a test PDF with 2 pages and native annotations
        self.doc = fitz.open()
        self.doc.new_page(width=612, height=792)
        self.doc.new_page(width=612, height=792)
        p1 = self.doc[0]
        p2 = self.doc[1]

        # Native highlight and text note on page 1
        hl = p1.add_highlight_annot(fitz.Rect(50, 50, 200, 70))
        hl.set_info({"content": "Sample Highlight Text"})
        note = p1.add_text_annot(fitz.Point(100, 150), "Important Note")

        # Native rect annot on page 2
        p2.add_rect_annot(fitz.Rect(60, 60, 160, 160))

        self.window.doc = self.doc

        # Create session with editable objects
        self.session = DocumentSession()
        self.session.doc = self.doc

        self.t1 = EditableText(x=50, y=100, text="Header Title", font_size=16.0, page_number=0)
        self.t2 = EditableText(x=50, y=200, text="Body paragraph", font_size=12.0, page_number=1)
        self.session.editable_texts = [self.t1, self.t2]

        self.s1 = EditableShape(shape_type="rectangle", bbox=(10, 10, 100, 100), page_number=0)
        self.session.editable_shapes = [self.s1]

        self.stk1 = EditableStroke(tool_type="pen", points=[(10, 10), (20, 20)], stroke_width=2.0, page_number=0)
        self.session.editable_strokes = [self.stk1]

        self.ff1 = AcroFormField(field_id="f1", xref=10, field_type="text", field_name="UserFullName", rect=(50, 300, 250, 325), page_number=0)
        self.session.form_fields = [self.ff1]

        self.img1 = EditableImage((20, 20, 120, 120), page_number=0, xref=1, image_bytes=b"fake")
        self.session.editable_images = [self.img1]

        self.m1 = MeasurementObject(measurement_type="distance", points=[(100, 100), (200, 100)], page_number=1, label="Wall Length")
        self.session.measurements = {1: [self.m1]}

        self.window._active_session = self.session

    def tearDown(self):
        if self.doc and not self.doc.is_closed:
            self.doc.close()

    def test_annotation_list_item_creation(self):
        """Verify AnnotationListItem fields and properties."""
        item = AnnotationListItem(
            item_id="test_1",
            item_type="text",
            category="text",
            title="Sample Text",
            subtitle="Helvetica, 12pt",
            page_number=0,
            icon_name="insert-text-symbolic",
            target_obj=self.t1,
            bbox=(50, 100, 150, 120),
        )
        self.assertEqual(item.item_id, "test_1")
        self.assertEqual(item.item_type, "text")
        self.assertEqual(item.category, "text")
        self.assertEqual(item.title, "Sample Text")
        self.assertEqual(item.subtitle, "Helvetica, 12pt")
        self.assertEqual(item.page_number, 0)
        self.assertEqual(item.icon_name, "insert-text-symbolic")
        self.assertIn("1", item.badge_text)
        self.assertIs(item.target_obj, self.t1)
        self.assertEqual(item.bbox, (50, 100, 150, 120))

    def test_sidebar_ui_components(self):
        """Verify sidebar contains all required widgets and structures."""
        self.assertIsNotNone(self.sidebar.search_entry)
        self.assertIsNotNone(self.sidebar.category_dropdown)
        self.assertIsNotNone(self.sidebar.list_view)
        self.assertIsNotNone(self.sidebar.list_store)
        self.assertIsNotNone(self.sidebar.filter_model)
        self.assertIsNotNone(self.sidebar.selection_model)
        self.assertIsNotNone(self.sidebar.count_badge)

    def test_sidebar_population(self):
        """Verify sidebar extracts all session objects and native annotations."""
        self.sidebar.populate(self.doc, self.session)
        total = self.sidebar.list_store.get_n_items()
        self.assertGreater(total, 0)

        # Collect titles and categories
        categories = set()
        titles = []
        for i in range(total):
            it = self.sidebar.list_store.get_item(i)
            categories.add(it.category)
            titles.append(it.title)

        self.assertIn(AnnotationsSidebar.CATEGORY_TEXT, categories)
        self.assertIn(AnnotationsSidebar.CATEGORY_IMAGES, categories)
        self.assertIn(AnnotationsSidebar.CATEGORY_SHAPES, categories)
        self.assertIn(AnnotationsSidebar.CATEGORY_PEN, categories)
        self.assertIn(AnnotationsSidebar.CATEGORY_HIGHLIGHTS, categories)
        self.assertIn(AnnotationsSidebar.CATEGORY_FORMS, categories)
        self.assertIn(AnnotationsSidebar.CATEGORY_MEASUREMENTS, categories)
        self.assertIn(AnnotationsSidebar.CATEGORY_NOTES, categories)

        # Verify specific items exist
        self.assertTrue(any("Header Title" in t for t in titles))
        self.assertTrue(any("Image" in t for t in titles))
        self.assertTrue(any("Wall Length" in t or "10.0 m" in t for t in titles))
        self.assertTrue(any("UserFullName" in t for t in titles))

    def test_search_filtering(self):
        """Verify real-time search query filtering."""
        self.sidebar.populate(self.doc, self.session)
        initial_count = self.sidebar.filter_model.get_n_items()

        # Search for "Header"
        self.sidebar.search_entry.set_text("Header")
        filtered_count = self.sidebar.filter_model.get_n_items()
        self.assertGreater(filtered_count, 0)
        self.assertLess(filtered_count, initial_count)
        self.assertEqual(self.sidebar.filter_model.get_item(0).title, "Header Title")

        # Clear search
        self.sidebar.search_entry.set_text("")
        self.assertEqual(self.sidebar.filter_model.get_n_items(), initial_count)

    def test_category_filtering(self):
        """Verify category dropdown filtering."""
        self.sidebar.populate(self.doc, self.session)

        # Category: Text Blocks (index 1)
        self.sidebar.category_dropdown.set_selected(1)
        n_text = self.sidebar.filter_model.get_n_items()
        self.assertGreater(n_text, 0)
        for i in range(n_text):
            it = self.sidebar.filter_model.get_item(i)
            self.assertEqual(it.category, AnnotationsSidebar.CATEGORY_TEXT)

        # Category: Images (index 2)
        self.sidebar.category_dropdown.set_selected(2)
        n_img = self.sidebar.filter_model.get_n_items()
        self.assertGreater(n_img, 0)
        for i in range(n_img):
            it = self.sidebar.filter_model.get_item(i)
            self.assertEqual(it.category, AnnotationsSidebar.CATEGORY_IMAGES)

        # Category: Measurements (index 7)
        self.sidebar.category_dropdown.set_selected(7)
        n_meas = self.sidebar.filter_model.get_n_items()
        self.assertGreater(n_meas, 0)
        for i in range(n_meas):
            it = self.sidebar.filter_model.get_item(i)
            self.assertEqual(it.category, AnnotationsSidebar.CATEGORY_MEASUREMENTS)

    def test_select_and_scroll_to_editable_text(self):
        """Verify selecting an EditableText switches page, sets selected_text, and scrolls."""
        self.sidebar.populate(self.doc, self.session)

        # Find item corresponding to t2 (page 1)
        target_item = None
        for i in range(self.sidebar.list_store.get_n_items()):
            it = self.sidebar.list_store.get_item(i)
            if it.target_obj is self.t2:
                target_item = it
                break

        self.assertIsNotNone(target_item)
        self.window.current_page_index = 0
        self.window.select_and_scroll_to_annotation(target_item)

        # Verify page switched to 1
        self.assertEqual(self.window.current_page_index, 1)
        self.assertIs(self.window.selected_text, self.t2)
        self.assertIsNotNone(self.window.scrolled_rect)
        self.assertEqual(self.window.scrolled_rect[0], 1)

    def test_select_and_scroll_to_native_annotation(self):
        """Verify selecting a native annotation highlights it on canvas."""
        self.sidebar.populate(self.doc, self.session)

        # Find native highlight item
        native_item = None
        for i in range(self.sidebar.list_store.get_n_items()):
            it = self.sidebar.list_store.get_item(i)
            if it.item_type == "native_highlight":
                native_item = it
                break

        self.assertIsNotNone(native_item)
        self.window.select_and_scroll_to_annotation(native_item)

        self.assertIsNotNone(self.window.highlighted_native_annot)
        self.assertEqual(self.window.highlighted_native_annot["type"], "native_highlight")
        self.assertEqual(self.window.highlighted_native_annot["page"], 0)
        self.assertIsNotNone(self.window.scrolled_rect)

    def test_sync_selection_from_canvas(self):
        """Verify canvas object selection updates sidebar ListView selection."""
        self.sidebar.populate(self.doc, self.session)

        # Select s1 on canvas and sync
        self.sidebar.sync_selection(self.s1)
        selected_idx = self.sidebar.selection_model.get_selected()
        self.assertNotEqual(selected_idx, Gtk.INVALID_LIST_POSITION)
        selected_item = self.sidebar.filter_model.get_item(selected_idx)
        self.assertIs(selected_item.target_obj, self.s1)

    def test_toggle_visibility(self):
        """Verify toggling annotations sidebar visibility."""
        self.sidebar.set_visible(False)
        self.window.toggle_annotations_button.set_active(False)

        # Toggle on
        self.window.toggle_annotations_sidebar()
        self.assertTrue(self.sidebar.get_visible())
        self.assertTrue(self.window.toggle_annotations_button.get_active())

        # Toggle off
        self.window.toggle_annotations_sidebar()
        self.assertFalse(self.sidebar.get_visible())
        self.assertFalse(self.window.toggle_annotations_button.get_active())

    def test_undo_redo_refreshes_sidebar(self):
        """Verify UndoManager invokes refresh_annotations_list on undo/redo."""
        self.sidebar.set_visible(True)
        mgr = UndoManager(self.window)
        refreshed = []

        self.sidebar.refresh = lambda: refreshed.append(True)

        class DummyCommand(Command):
            def execute(self): pass
            def undo(self): pass

        cmd = DummyCommand(self.window)
        mgr.add_command(cmd)
        self.assertEqual(len(refreshed), 1)

        mgr.undo()
        self.assertEqual(len(refreshed), 2)

        mgr.redo()
        self.assertEqual(len(refreshed), 3)


if __name__ == "__main__":
    unittest.main()
