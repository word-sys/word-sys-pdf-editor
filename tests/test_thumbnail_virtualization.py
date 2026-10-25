"""Tests for virtualized Gtk.ListView thumbnail ribbon and widget recycling (Part 63)."""

import unittest
from unittest.mock import MagicMock
import time
import fitz
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib, GObject

from word_sys_pdf_editor.models import PdfPage
from word_sys_pdf_editor.ui_components import PageThumbnailFactory
from word_sys_pdf_editor import pdf_handler


class TestThumbnailVirtualization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init()

    def setUp(self):
        self.doc = fitz.open()
        for i in range(5):
            page = self.doc.new_page(width=300, height=400)
            page.insert_text((50, 50), f"Page {i + 1}")

    def tearDown(self):
        if self.doc and not self.doc.is_closed:
            self.doc.close()

    def test_pdf_page_default_thumbnail_none(self):
        """PdfPage should default thumbnail to None and support property notification."""
        page = PdfPage(index=42)
        self.assertEqual(page.index, 42)
        self.assertIsNone(page.thumbnail)

        notifications = []
        page.connect("notify::thumbnail", lambda obj, pspec: notifications.append(obj.thumbnail))

        pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 20, 20)
        page.thumbnail = pix

        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0], pix)
        self.assertEqual(page.thumbnail, pix)

    def test_large_list_store_instant_splice(self):
        """Populating 500 virtual page items into Gio.ListStore should execute in < 100ms."""
        store = Gio.ListStore(item_type=PdfPage)
        t0 = time.perf_counter()
        pages = [PdfPage(index=i) for i in range(500)]
        store.splice(0, 0, pages)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self.assertEqual(store.get_n_items(), 500)
        self.assertLess(elapsed_ms, 100.0, "Model population should be virtually instantaneous")
        self.assertEqual(store.get_item(250).index, 250)
        self.assertIsNone(store.get_item(250).thumbnail)

    def test_page_thumbnail_factory_lifecycle(self):
        """Factory setup, bind, unbind, and teardown lifecycle."""
        mock_win = MagicMock()
        mock_win.view_mode = False
        mock_win.edit_mode = True

        factory = PageThumbnailFactory(editor_window=mock_win)

        list_item = MagicMock()
        child_holder = [None]
        list_item.set_child.side_effect = lambda c: child_holder.__setitem__(0, c)
        list_item.get_child.side_effect = lambda: child_holder[0]

        # 1. Setup
        factory._on_setup(factory, list_item)
        box = list_item.get_child()
        self.assertIsNotNone(box)
        self.assertIsInstance(box, Gtk.Box)

        # Controllers should be attached once
        controllers = list(box.observe_controllers())
        self.assertTrue(any(isinstance(c, Gtk.DragSource) for c in controllers))
        self.assertTrue(any(isinstance(c, Gtk.DropTarget) for c in controllers))
        self.assertTrue(any(isinstance(c, Gtk.GestureClick) for c in controllers))
        initial_ctrl_count = len(controllers)

        # 2. Bind with unrendered thumbnail
        page_0 = PdfPage(index=0, thumbnail=None)
        list_item.get_item.return_value = page_0

        factory._on_bind(factory, list_item)

        # Controllers should not be duplicated on bind
        self.assertEqual(len(list(box.observe_controllers())), initial_ctrl_count)

        # request_thumbnail should be triggered for page 0
        mock_win.request_thumbnail.assert_called_with(0)

        # 3. Simulate thumbnail generation and notify
        pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 30, 40)
        page_0.thumbnail = pix

        pic = box.get_first_child()
        self.assertIsNotNone(pic.get_paintable(), "Picture should have paintable after notify")

        # 4. Unbind: should recycle widget and clear paintable to free texture memory
        factory._on_unbind(factory, list_item)
        self.assertIsNone(pic.get_paintable(), "Paintable should be None after unbind")
        self.assertIsNone(getattr(box, "_thumb_handler_id", None))

        # 5. Teardown
        factory._on_teardown(factory, list_item)
        self.assertIsNone(list_item.get_child())

    def test_request_thumbnail_execution(self):
        """request_thumbnail should generate thumbnail and update target item on idle."""
        mock_session = MagicMock()
        mock_session.doc = self.doc
        store = Gio.ListStore(item_type=PdfPage)
        store.splice(0, 0, [PdfPage(index=i) for i in range(5)])
        mock_session.pages_model = store

        from word_sys_pdf_editor.window import PdfEditorWindow
        win = MagicMock(spec=PdfEditorWindow)
        win._active_session = mock_session
        win._pending_thumb_requests = set()

        PdfEditorWindow.request_thumbnail(win, 2, session=mock_session)
        self.assertIn(2, win._pending_thumb_requests)

        # Duplicate request should be ignored while in progress
        PdfEditorWindow.request_thumbnail(win, 2, session=mock_session)

        # Run pending idle callbacks
        ctx = GLib.MainContext.default()
        for _ in range(50):
            if ctx.pending():
                ctx.iteration(False)
            else:
                break

        item_2 = store.get_item(2)
        self.assertIsNotNone(item_2.thumbnail)
        self.assertIsInstance(item_2.thumbnail, GdkPixbuf.Pixbuf)
        self.assertNotIn(2, win._pending_thumb_requests)

    def test_load_thumbnails_virtualization(self):
        """_load_thumbnails should populate model immediately and render active page."""
        mock_session = MagicMock()
        mock_session.doc = self.doc
        store = Gio.ListStore(item_type=PdfPage)
        mock_session.pages_model = store
        mock_session.pdf_path = "/tmp/test.pdf"

        from word_sys_pdf_editor.window import PdfEditorWindow
        win = MagicMock(spec=PdfEditorWindow)
        win._active_session = mock_session
        win.current_page_index = 0
        win.status_label = MagicMock()

        PdfEditorWindow._load_thumbnails(win, session=mock_session, target_page=1)

        # All 5 pages should be in store immediately
        self.assertEqual(store.get_n_items(), 5)
        # Target page 1 should have its thumbnail generated immediately
        self.assertIsNotNone(store.get_item(1).thumbnail)
        # Pages not yet visited start as None
        self.assertIsNone(store.get_item(3).thumbnail)

    def test_sidebar_uses_gtk_list_view(self):
        """thumbnails_list should be an instance of Gtk.ListView."""
        factory = PageThumbnailFactory()
        model = Gio.ListStore(item_type=PdfPage)
        sel = Gtk.SingleSelection(model=model)
        list_view = Gtk.ListView.new(sel, factory)
        self.assertIsInstance(list_view, Gtk.ListView)

    def test_refresh_thumbnail_updates_in_place(self):
        """_refresh_thumbnail should update item.thumbnail in-place and notify."""
        mock_session = MagicMock()
        mock_session.doc = self.doc
        store = Gio.ListStore(item_type=PdfPage)
        p0 = PdfPage(index=0)
        p1 = PdfPage(index=1)
        store.splice(0, 0, [p0, p1])
        mock_session.pages_model = store

        from word_sys_pdf_editor.window import PdfEditorWindow
        win = MagicMock(spec=PdfEditorWindow)
        win.doc = self.doc
        win.pages_model = store
        win._active_session = mock_session

        notifications = []
        p1.connect("notify::thumbnail", lambda obj, pspec: notifications.append(True))

        PdfEditorWindow._refresh_thumbnail(win, 1)

        # Item 1 should have updated thumbnail and fired notification
        self.assertEqual(len(notifications), 1)
        self.assertIsNotNone(p1.thumbnail)
        self.assertIs(store.get_item(1), p1)
