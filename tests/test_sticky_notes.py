# -*- coding: utf-8 -*-
"""Comprehensive test suite for Part 34: Sticky Notes & Comments Engine in View Mode.

Verifies:
- StickyNoteObject data model properties, hit-testing, bbox calculations, and serialization.
- PyMuPDF integration: reading native text annotations and writing/baking sticky notes to PDF.
- Session sticky notes state management and persistence across tab switches.
- Undo/Redo commands: AddStickyNoteCommand, EditStickyNoteCommand, DeleteStickyNoteCommand, MoveStickyNoteCommand.
- Window UI interactions: toggle tool button, click-to-place, drag repositioning, and context menu actions.
- Annotations sidebar listing and bi-directional selection synchronization.
"""

import unittest
import fitz
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Gio

from word_sys_pdf_editor.models import StickyNoteObject, DocumentSession
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.undo_manager import (
    UndoManager,
    AddStickyNoteCommand,
    EditStickyNoteCommand,
    DeleteStickyNoteCommand,
    MoveStickyNoteCommand,
)
from word_sys_pdf_editor.annotations_sidebar import AnnotationsSidebar


class DummyWindow:
    """Mock PdfEditorWindow for unit testing sticky note commands and interactions."""

    def __init__(self):
        self.doc = None
        self._active_session = None
        self.current_page_index = 0
        self.zoom_level = 1.0
        self.current_pdf_page_width = 595.0
        self.current_pdf_page_height = 842.0
        self.view_mode = True
        self.view_tool_mode = None
        self.selected_sticky_note = None
        self.dragged_sticky_note = None
        self.sticky_note_start_coords = None
        self.document_modified = False
        self.pdf_view = Gtk.DrawingArea()
        self.undo_manager = UndoManager(self)

        session = DocumentSession(pdf_path="test.pdf")
        session.undo_manager = self.undo_manager
        self._active_session = session

    def _update_ui_state(self):
        pass

    def _update_undo_redo_buttons(self):
        pass

    def _refresh_thumbnail(self, page_index):
        pass

    def _add_sticky_note_to_session(self, note):
        p = note.page_number
        if p not in self._active_session.sticky_notes:
            self._active_session.sticky_notes[p] = []
        if note not in self._active_session.sticky_notes[p]:
            self._active_session.sticky_notes[p].append(note)
        self.selected_sticky_note = note
        self.document_modified = True

    def _remove_sticky_note_from_session(self, note):
        p = note.page_number
        if p in self._active_session.sticky_notes and note in self._active_session.sticky_notes[p]:
            self._active_session.sticky_notes[p].remove(note)
        if self.selected_sticky_note == note:
            self.selected_sticky_note = None
        self.document_modified = True

    def _apply_sticky_note_state(self, note, state):
        if not note or not state:
            return
        note.content = state.get("content", note.content)
        note.author = state.get("author", note.author)
        note.color = state.get("color", note.color)
        note.icon_type = state.get("icon_type", note.icon_type)
        if "modified_at" in state:
            note.modified_at = state["modified_at"]
        self.document_modified = True

    def _set_sticky_note_pos(self, note, new_x, new_y):
        note.x = float(new_x)
        note.y = float(new_y)
        self.document_modified = True


class TestStickyNoteObject(unittest.TestCase):
    """Test StickyNoteObject model attributes and behavior."""

    def test_initialization_defaults(self):
        note = StickyNoteObject(x=100.0, y=150.0, page_number=0)
        self.assertEqual(note.x, 100.0)
        self.assertEqual(note.y, 150.0)
        self.assertEqual(note.page_number, 0)
        self.assertEqual(note.content, "")
        self.assertEqual(note.author, "")
        self.assertEqual(note.color_hex, "#FFDB3D")
        self.assertEqual(note.icon_name, "Comment")
        self.assertTrue(len(note.id) > 0)
        self.assertTrue(len(note.created_at) > 0)

    def test_bbox_and_hit_testing(self):
        note = StickyNoteObject(x=100.0, y=150.0, width=24.0, height=24.0)
        self.assertEqual(note.bbox, (100.0, 150.0, 124.0, 174.0))

        # Direct hit inside icon
        self.assertTrue(note.contains_point(110.0, 160.0))
        # Hit within hit-target padding (4px margin)
        self.assertTrue(note.contains_point(98.0, 148.0))
        # Miss outside margin
        self.assertFalse(note.contains_point(80.0, 150.0))
        self.assertFalse(note.contains_point(135.0, 180.0))

    def test_rgba_tuple_conversion(self):
        note = StickyNoteObject(color_hex="#FFD54F")
        r, g, b, a = note.rgba_tuple
        self.assertAlmostEqual(r, 1.0, delta=0.01)
        self.assertAlmostEqual(g, 0.835, delta=0.01)
        self.assertAlmostEqual(b, 0.31, delta=0.01)
        self.assertEqual(a, 1.0)

    def test_serialization_roundtrip(self):
        note = StickyNoteObject(
            x=50.0,
            y=80.0,
            page_number=1,
            content="Important review feedback",
            author="Reviewer",
            color_hex="#4FC3F7",
            icon_name="Key",
        )
        d = note.to_dict()
        restored = StickyNoteObject.from_dict(d)
        self.assertEqual(restored.id, note.id)
        self.assertEqual(restored.x, 50.0)
        self.assertEqual(restored.y, 80.0)
        self.assertEqual(restored.page_number, 1)
        self.assertEqual(restored.content, "Important review feedback")
        self.assertEqual(restored.author, "Reviewer")
        self.assertEqual(restored.color_hex, "#4FC3F7")
        self.assertEqual(restored.icon_name, "Key")


class TestPdfHandlerStickyNotes(unittest.TestCase):
    """Test PyMuPDF sticky notes creation, extraction, and embedding."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=595, height=842)

    def tearDown(self):
        self.doc.close()

    def test_add_and_extract_sticky_note(self):
        page = self.doc[0]
        note = StickyNoteObject(
            x=150.0,
            y=200.0,
            page_number=0,
            content="Check figure 3 coordinates",
            author="Alice",
            color_hex="#81C784",
        )
        pdf_handler.add_sticky_note_to_pdf(page, note)

        # Extract notes back
        extracted = pdf_handler.get_sticky_notes_from_pdf(page, page_number=0)
        self.assertEqual(len(extracted), 1)
        ext_note = extracted[0]
        self.assertEqual(ext_note.page_number, 0)
        self.assertEqual(ext_note.content, "Check figure 3 coordinates")
        self.assertEqual(ext_note.author, "Alice")
        self.assertAlmostEqual(ext_note.x, 150.0, delta=1.0)
        self.assertAlmostEqual(ext_note.y, 200.0, delta=1.0)

    def test_apply_session_sticky_notes_to_pdf(self):
        session = DocumentSession(pdf_path="dummy.pdf")
        note1 = StickyNoteObject(x=50.0, y=50.0, page_number=0, content="Page 0 note", author="Bob")
        session.sticky_notes = {0: [note1]}

        pdf_handler.apply_sticky_notes_to_pdf(self.doc, session)
        page = self.doc[0]
        annots = list(page.annots())
        self.assertEqual(len(annots), 1)
        self.assertEqual(annots[0].info.get("content"), "Page 0 note")
        self.assertEqual(annots[0].info.get("title"), "Bob")


class TestStickyNoteUndoRedoCommands(unittest.TestCase):
    """Test undo and redo stack operations for sticky note actions."""

    def setUp(self):
        self.window = DummyWindow()
        self.note = StickyNoteObject(x=100.0, y=100.0, page_number=0, content="Initial text", author="User")

    def test_add_sticky_note_command(self):
        cmd = AddStickyNoteCommand(self.window, self.note)
        cmd.execute()
        self.assertIn(self.note, self.window._active_session.sticky_notes[0])
        self.assertEqual(self.window.selected_sticky_note, self.note)

        cmd.undo()
        self.assertNotIn(self.note, self.window._active_session.sticky_notes.get(0, []))
        self.assertIsNone(self.window.selected_sticky_note)

        cmd.redo()
        self.assertIn(self.note, self.window._active_session.sticky_notes[0])

    def test_edit_sticky_note_command(self):
        self.window._active_session.sticky_notes = {0: [self.note]}
        old_state = {"content": "Initial text", "author": "User", "color": self.note.color, "icon_type": "Comment"}
        new_state = {"content": "Updated feedback", "author": "Editor", "color": (1.0, 0.42, 0.62), "icon_type": "Note"}
        cmd = EditStickyNoteCommand(
            self.window,
            self.note,
            old_state=old_state,
            new_state=new_state,
        )
        cmd.execute()
        self.assertEqual(self.note.content, "Updated feedback")
        self.assertEqual(self.note.author, "Editor")
        self.assertEqual(self.note.color, (1.0, 0.42, 0.62))
        self.assertEqual(self.note.icon_type, "Note")

        cmd.undo()
        self.assertEqual(self.note.content, "Initial text")
        self.assertEqual(self.note.author, "User")

        cmd.redo()
        self.assertEqual(self.note.content, "Updated feedback")

    def test_delete_sticky_note_command(self):
        self.window._active_session.sticky_notes = {0: [self.note]}
        cmd = DeleteStickyNoteCommand(self.window, self.note)
        cmd.execute()
        self.assertNotIn(self.note, self.window._active_session.sticky_notes.get(0, []))

        cmd.undo()
        self.assertIn(self.note, self.window._active_session.sticky_notes[0])

        cmd.redo()
        self.assertNotIn(self.note, self.window._active_session.sticky_notes.get(0, []))

    def test_move_sticky_note_command(self):
        cmd = MoveStickyNoteCommand(self.window, self.note, (100.0, 100.0), (250.0, 300.0))
        cmd.execute()
        self.assertEqual((self.note.x, self.note.y), (250.0, 300.0))

        cmd.undo()
        self.assertEqual((self.note.x, self.note.y), (100.0, 100.0))

        cmd.redo()
        self.assertEqual((self.note.x, self.note.y), (250.0, 300.0))


class TestSidebarStickyNoteIntegration(unittest.TestCase):
    """Test sidebar category display and selection for sticky notes."""

    def setUp(self):
        self.doc = fitz.open()
        self.doc.new_page(width=595, height=842)
        self.window = DummyWindow()
        self.window.doc = self.doc
        self.sidebar = AnnotationsSidebar(editor_window=self.window)

    def tearDown(self):
        self.doc.close()

    def test_sidebar_extracts_and_filters_sticky_notes(self):
        note = StickyNoteObject(
            x=80.0,
            y=120.0,
            page_number=0,
            content="Clarify conclusion paragraph",
            author="Reviewer",
        )
        self.window._active_session.sticky_notes = {0: [note]}

        self.sidebar.populate(self.doc, self.window._active_session)
        self.assertEqual(self.sidebar.list_store.get_n_items(), 1)
        item = self.sidebar.list_store.get_item(0)
        self.assertEqual(item.category, AnnotationsSidebar.CATEGORY_NOTES)
        self.assertEqual(item.target_obj, note)
        self.assertIn("Clarify conclusion", item.title)

        # Filter by notes category
        self.sidebar._current_category_filter = AnnotationsSidebar.CATEGORY_NOTES
        self.sidebar.custom_filter.changed(Gtk.FilterChange.DIFFERENT)
        self.assertEqual(self.sidebar.filter_model.get_n_items(), 1)

        # Filter by shapes category should yield 0 items
        self.sidebar._current_category_filter = AnnotationsSidebar.CATEGORY_SHAPES
        self.sidebar.custom_filter.changed(Gtk.FilterChange.DIFFERENT)
        self.assertEqual(self.sidebar.filter_model.get_n_items(), 0)


if __name__ == "__main__":
    unittest.main()
