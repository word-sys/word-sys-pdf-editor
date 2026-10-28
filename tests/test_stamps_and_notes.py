"""Consolidated Stamps, Sticky Notes, and Annotations Sidebar Test Suite for word-sys-pdf-editor.

This suite merges custom dynamic stamp management, password-protected security stamps,
sticky note lifecycle, rendering, popover controls, and the Annotations Sidebar panel.
"""

# ============================================================================
# SECTION: test_stamp_manager.py
# ============================================================================
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk

from word_sys_pdf_editor.models import EditableImage
from word_sys_pdf_editor.stamp_manager import (
    CustomStamp,
    StampLibrary,
    StampManagerDialog,
    StampPopover,
    generate_cairo_stamp_png,
)
from word_sys_pdf_editor.undo_manager import UndoManager


@pytest.fixture
def temp_stamps_dir():
    temp_dir = tempfile.mkdtemp(prefix="test_stamps_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_custom_stamp_model(temp_stamps_dir):
    png_bytes = generate_cairo_stamp_png("TEST", (0.2, 0.4, 0.6), width=100, height=40)
    img_path = temp_stamps_dir / "test_stamp.png"
    img_path.write_bytes(png_bytes)

    stamp = CustomStamp(
        stamp_id="test_1",
        name="Test Stamp",
        category="Custom",
        image_path=str(img_path),
        image_bytes=png_bytes,
        default_width=120.0,
        default_height=40.0,
        is_builtin=False,
    )

    data = stamp.to_dict()
    assert data["id"] == "test_1"
    assert data["name"] == "Test Stamp"
    assert data["category"] == "Custom"
    assert data["default_width"] == 120.0

    restored = CustomStamp.from_dict(data, temp_stamps_dir)
    assert restored.id == "test_1"
    assert restored.name == "Test Stamp"
    assert restored.category == "Custom"
    assert len(restored.image_bytes) == len(png_bytes)
    assert restored.get_pixbuf() is not None
    assert restored.get_paintable() is not None


def test_generate_cairo_stamp_png():
    png_bytes = generate_cairo_stamp_png("APPROVED", (0.1, 0.7, 0.2), width=160, height=54)
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 500
    # Valid PNG header magic bytes
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_stamp_library_initialization_and_builtins(temp_stamps_dir):
    lib = StampLibrary(storage_dir=temp_stamps_dir)
    assert len(lib.stamps) == 6
    assert lib.active_stamp_id is not None
    active = lib.get_active_stamp()
    assert active is not None
    assert active.is_builtin is True

    # Check known builtins exist
    builtin_ids = {s.id for s in lib.stamps}
    assert "builtin_approved" in builtin_ids
    assert "builtin_confidential" in builtin_ids
    assert "builtin_draft" in builtin_ids
    assert "builtin_rejected" in builtin_ids
    assert "builtin_final" in builtin_ids
    assert "builtin_void" in builtin_ids

    # Manifest was created on disk
    assert (temp_stamps_dir / "stamps.json").exists()


def test_stamp_library_persistence_and_reload(temp_stamps_dir):
    lib1 = StampLibrary(storage_dir=temp_stamps_dir)
    lib1.set_active_stamp("builtin_draft")
    assert lib1.active_stamp_id == "builtin_draft"

    # Reload from same directory
    lib2 = StampLibrary(storage_dir=temp_stamps_dir)
    assert len(lib2.stamps) == 6
    assert lib2.active_stamp_id == "builtin_draft"
    assert lib2.get_active_stamp().id == "builtin_draft"


def test_stamp_library_import_and_deletion(temp_stamps_dir):
    sample_img = Path("word_sys_pdf_editor/img/f-pv1.png")
    assert sample_img.exists()

    lib = StampLibrary(storage_dir=temp_stamps_dir)
    imported = lib.import_stamp_from_file(str(sample_img), name="Office Seal", category="Signatures")
    assert imported is not None
    assert imported.name == "Office Seal"
    assert imported.category == "Signatures"
    assert imported.is_builtin is False
    assert lib.active_stamp_id == imported.id
    assert len(lib.stamps) == 7

    # Builtin stamp deletion must be denied
    assert lib.delete_stamp("builtin_approved") is False
    assert len(lib.stamps) == 7

    # Custom stamp deletion succeeds
    deleted_ok = lib.delete_stamp(imported.id)
    assert deleted_ok is True
    assert len(lib.stamps) == 6
    assert lib.get_stamp(imported.id) is None


def test_stamp_manager_dialog_flow(temp_stamps_dir):
    lib = StampLibrary(storage_dir=temp_stamps_dir)
    selected_stamps = []

    def on_selected(stamp):
        selected_stamps.append(stamp)

    dialog = StampManagerDialog(None, lib, on_stamp_selected_callback=on_selected)
    assert dialog.get_title() is not None

    # Test setting active stamp from dialog
    dialog._on_set_active_clicked(None, "builtin_rejected")
    assert lib.active_stamp_id == "builtin_rejected"
    assert len(selected_stamps) == 1
    assert selected_stamps[0].id == "builtin_rejected"

    # Test category filter toggle
    mock_btn = MagicMock()
    mock_btn.get_active.return_value = True
    dialog._on_category_toggled(mock_btn, "Review")
    assert dialog.active_filter_category == "Review"

    dialog.destroy()


def test_stamp_popover_interaction(temp_stamps_dir):
    lib = StampLibrary(storage_dir=temp_stamps_dir)
    chosen_stamps = []

    popover = StampPopover(
        lib,
        on_stamp_chosen_callback=lambda s: chosen_stamps.append(s),
        on_manage_clicked_callback=lambda: None
    )

    # Trigger click on a row
    popover._on_row_clicked(None, 1, 0, 0, "builtin_confidential")
    assert lib.active_stamp_id == "builtin_confidential"
    assert len(chosen_stamps) == 1
    assert chosen_stamps[0].id == "builtin_confidential"


class DummyPdfEditorWindow:
    """Mock window for testing stamp placement and undo/redo cycles."""

    def __init__(self, stamps_dir):
        self.stamp_library = StampLibrary(storage_dir=stamps_dir)
        self.active_stamp = self.stamp_library.get_active_stamp()
        self.tool_mode = "add_stamp"
        self.current_page_index = 0
        self.document_modified = False
        self.undo_manager = UndoManager(self)
        self.objects_by_page = {0: []}
        self.editable_images = []
        self.doc = None
        self.selected_image = None
        self.selected_text = None
        self.selected_shape = None
        self.selected_stroke = None
        self.temp_stamp_bbox = None
        self.drag_start_page_pos = (150.0, 200.0)
        self.status_label = MagicMock()
        self.pdf_view = MagicMock()

    def _refresh_thumbnail(self, page_index):
        pass

    def _update_ui_state(self):
        pass

    def _update_undo_redo_buttons(self):
        pass


def test_window_stamp_single_click_placement(temp_stamps_dir):
    win = DummyPdfEditorWindow(temp_stamps_dir)
    assert win.active_stamp is not None
    assert win.active_stamp.name == "APPROVED"

    # Simulate single click: start pos (150, 200), minimal drag (< 12 pt)
    win.drag_start_page_pos = (150.0, 200.0)
    win.temp_stamp_bbox = (150.0, 200.0, 152.0, 202.0)

    # Replicate gesture release placement logic
    x1, y1, x2, y2 = win.temp_stamp_bbox
    win.temp_stamp_bbox = None
    active_stamp = win.active_stamp
    cx, cy = win.drag_start_page_pos
    w = getattr(active_stamp, "default_width", 160.0)
    h = getattr(active_stamp, "default_height", 54.0)
    final_bbox = (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)

    stamp_obj = EditableImage(
        bbox=final_bbox,
        page_number=win.current_page_index,
        xref=None,
        image_bytes=active_stamp.image_bytes,
        is_new=True,
        is_stamp=True,
        stamp_name=active_stamp.name,
    )

    from word_sys_pdf_editor.undo_manager import AddObjectCommand
    cmd = AddObjectCommand(win, stamp_obj)
    cmd.execute()
    win.undo_manager.add_command(cmd)

    # Object is placed in editable_images
    assert len(win.editable_images) == 1
    placed = win.editable_images[0]
    assert placed.is_stamp is True
    assert placed.stamp_name == "APPROVED"
    assert placed.bbox == (70.0, 173.0, 230.0, 227.0)

    # Undo removes the placed stamp
    win.undo_manager.undo()
    assert len(win.editable_images) == 0

    # Redo restores the placed stamp
    win.undo_manager.redo()
    assert len(win.editable_images) == 1
    assert win.editable_images[0].stamp_name == "APPROVED"


def test_window_stamp_drag_placement(temp_stamps_dir):
    win = DummyPdfEditorWindow(temp_stamps_dir)

    # Simulate dragging a larger box: (100, 100) to (300, 220)
    win.drag_start_page_pos = (100.0, 100.0)
    win.temp_stamp_bbox = (100.0, 100.0, 300.0, 220.0)

    x1, y1, x2, y2 = win.temp_stamp_bbox
    final_bbox = (x1, y1, x2, y2)

    stamp_obj = EditableImage(
        bbox=final_bbox,
        page_number=win.current_page_index,
        xref=None,
        image_bytes=win.active_stamp.image_bytes,
        is_new=True,
        is_stamp=True,
        stamp_name=win.active_stamp.name,
    )

    from word_sys_pdf_editor.undo_manager import AddObjectCommand
    cmd = AddObjectCommand(win, stamp_obj)
    cmd.execute()
    win.undo_manager.add_command(cmd)

    assert len(win.editable_images) == 1
    placed = win.editable_images[0]
    assert placed.bbox == (100.0, 100.0, 300.0, 220.0)
    assert placed.is_stamp is True

    # Test undo and redo
    win.undo_manager.undo()
    assert len(win.editable_images) == 0
    win.undo_manager.redo()
    assert len(win.editable_images) == 1


def test_stamp_tool_layout_single_box_in_sidebar():
    """Verify Stamp tool is a single box in row 5 col 1, second box removed, calibrate merged."""
    import inspect
    from word_sys_pdf_editor import window
    src = inspect.getsource(window.PdfEditorWindow._create_sidebar)
    assert 'tools_grid.attach(self.stamp_tool_button, 1, 5, 1, 1)' in src
    assert 'tools_grid.attach(self.stamp_menu_button' not in src
    assert 'tools_grid.attach(self.calibrate_tool_button' not in src


def test_stamp_manager_import_invokes_open_file_dialog(temp_stamps_dir, monkeypatch):
    """Verify import button uses show_open_file_dialog without AttributeError."""
    from unittest.mock import MagicMock
    import word_sys_pdf_editor.ui_components as ui_comp

    mock_dialog = MagicMock()
    monkeypatch.setattr(ui_comp, "show_open_file_dialog", mock_dialog)

    lib = StampLibrary(storage_dir=temp_stamps_dir)
    dialog = StampManagerDialog(None, lib)
    dialog._on_import_clicked(None)

    assert mock_dialog.called
    dialog.destroy()


def test_keyboard_shortcuts_stamp_distance_area():
    """Verify single-key shortcuts: K for Stamp, D for Distance, A for Area."""
    from gi.repository import Gdk
    from word_sys_pdf_editor.window import PdfEditorWindow
    mock_win = MagicMock(spec=PdfEditorWindow)
    mock_win.view_mode = False
    mock_win.inline_editor_widget = None
    mock_win.input_overlay_widget = None
    mock_win.form_field_builder_overlay = None
    mock_win.selected_form_field = None
    mock_win.is_space_pressed = False
    mock_win.get_focus.return_value = None

    # Test lowercase k and uppercase K for stamp
    assert PdfEditorWindow.on_key_pressed(mock_win, None, Gdk.KEY_k, 0, 0) is True
    mock_win.on_tool_selected.assert_called_with(None, "add_stamp")

    mock_win.on_tool_selected.reset_mock()
    assert PdfEditorWindow.on_key_pressed(mock_win, None, Gdk.KEY_K, 0, 0) is True
    mock_win.on_tool_selected.assert_called_with(None, "add_stamp")

    # Test d and D for distance
    mock_win.on_tool_selected.reset_mock()
    assert PdfEditorWindow.on_key_pressed(mock_win, None, Gdk.KEY_d, 0, 0) is True
    mock_win.on_tool_selected.assert_called_with(None, "measure_distance")

    mock_win.on_tool_selected.reset_mock()
    assert PdfEditorWindow.on_key_pressed(mock_win, None, Gdk.KEY_D, 0, 0) is True
    mock_win.on_tool_selected.assert_called_with(None, "measure_distance")

    # Test a and A for area
    mock_win.on_tool_selected.reset_mock()
    assert PdfEditorWindow.on_key_pressed(mock_win, None, Gdk.KEY_a, 0, 0) is True
    mock_win.on_tool_selected.assert_called_with(None, "measure_area")

    mock_win.on_tool_selected.reset_mock()
    assert PdfEditorWindow.on_key_pressed(mock_win, None, Gdk.KEY_A, 0, 0) is True
    mock_win.on_tool_selected.assert_called_with(None, "measure_area")



# ============================================================================
# SECTION: test_stamp_password_protection.py
# ============================================================================
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk

from word_sys_pdf_editor.stamp_manager import (
    CustomStamp,
    StampLibrary,
    StampPasswordDialog,
    StampVerificationDialog,
    generate_cairo_stamp_png,
    hash_stamp_password,
    verify_stamp_password,
)
from word_sys_pdf_editor.models import EditableImage
from word_sys_pdf_editor.undo_manager import UndoManager, AddObjectCommand


@pytest.fixture
def temp_stamps_dir():
    temp_dir = tempfile.mkdtemp(prefix="test_stamp_pwd_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_password_hashing_and_verification():
    raw_pass = "SecurePass#2026"
    stored_hash = hash_stamp_password(raw_pass)

    assert stored_hash is not None
    assert stored_hash.startswith("pbkdf2:sha256:100000:")
    parts = stored_hash.split(":")
    assert len(parts) == 5

    # Correct password succeeds
    assert verify_stamp_password(raw_pass, stored_hash) is True
    # Incorrect password fails
    assert verify_stamp_password("WrongPassword", stored_hash) is False
    assert verify_stamp_password("", stored_hash) is False
    assert verify_stamp_password(raw_pass, None) is False
    assert verify_stamp_password(raw_pass, "invalid:format") is False

    # Empty raw password raises ValueError
    with pytest.raises(ValueError):
        hash_stamp_password("")
    with pytest.raises(ValueError):
        hash_stamp_password("   ")


def test_custom_stamp_password_protection_lifecycle(temp_stamps_dir):
    png_bytes = generate_cairo_stamp_png("APPROVED", (0.0, 0.5, 0.0), width=120, height=40)
    img_path = temp_stamps_dir / "approved.png"
    img_path.write_bytes(png_bytes)

    stamp = CustomStamp(
        stamp_id="stamp_sec_1",
        name="Official Seal",
        category="Legal",
        image_path=str(img_path),
        image_bytes=png_bytes,
        default_width=140.0,
        default_height=50.0,
        is_builtin=False,
    )

    # Initial state: unprotected
    assert stamp.has_password() is False
    assert stamp.is_password_protected is False
    assert stamp.password_hash is None
    assert stamp.verify_password("any_or_no_password") is True

    # Set password
    stamp.set_password("ManagerPIN#9988")
    assert stamp.has_password() is True
    assert stamp.is_password_protected is True
    assert stamp.password_hash.startswith("pbkdf2:sha256:")

    # Verification
    assert stamp.verify_password("ManagerPIN#9988") is True
    assert stamp.verify_password("WrongPIN") is False

    # Serialization and deserialization
    data = stamp.to_dict()
    assert data["is_password_protected"] is True
    assert data["password_hash"] == stamp.password_hash

    restored = CustomStamp.from_dict(data, temp_stamps_dir)
    assert restored.has_password() is True
    assert restored.is_password_protected is True
    assert restored.password_hash == stamp.password_hash
    assert restored.verify_password("ManagerPIN#9988") is True
    assert restored.verify_password("WrongPIN") is False

    # Remove password
    restored.remove_password()
    assert restored.has_password() is False
    assert restored.is_password_protected is False
    assert restored.password_hash is None
    assert restored.verify_password("ManagerPIN#9988") is True


def test_stamp_password_dialog_set_new_password(temp_stamps_dir):
    stamp = CustomStamp(
        stamp_id="test_dlg_1",
        name="Contract Stamp",
        image_bytes=b"dummy_bytes",
    )

    success_called = []
    dlg = StampPasswordDialog(
        parent_window=None,
        stamp=stamp,
        on_success_callback=lambda s: success_called.append(s),
    )

    # Mismatch passwords
    dlg.new_entry.set_text("Alpha123")
    dlg.confirm_entry.set_text("Alpha456")
    dlg._on_save_clicked(None)

    assert len(success_called) == 0
    assert stamp.has_password() is False
    assert dlg.error_label.get_visible() is True

    # Empty password
    dlg.new_entry.set_text("")
    dlg.confirm_entry.set_text("")
    dlg._on_save_clicked(None)
    assert len(success_called) == 0
    assert stamp.has_password() is False

    # Matching password
    dlg.new_entry.set_text("Alpha123")
    dlg.confirm_entry.set_text("Alpha123")
    dlg._on_save_clicked(None)

    assert len(success_called) == 1
    assert stamp.has_password() is True
    assert stamp.verify_password("Alpha123") is True


def test_stamp_password_dialog_change_and_remove(temp_stamps_dir):
    stamp = CustomStamp(
        stamp_id="test_dlg_2",
        name="Secret Stamp",
        image_bytes=b"dummy_bytes",
    )
    stamp.set_password("CurrentSecret123")

    success_called = []
    dlg = StampPasswordDialog(
        parent_window=None,
        stamp=stamp,
        on_success_callback=lambda s: success_called.append(s),
    )

    assert dlg.curr_entry is not None

    # Try removing with wrong current password
    dlg.curr_entry.set_text("WrongOldSecret")
    dlg._on_remove_clicked(None)
    assert len(success_called) == 0
    assert stamp.has_password() is True
    assert dlg.error_label.get_visible() is True

    # Remove with correct current password
    dlg.curr_entry.set_text("CurrentSecret123")
    dlg._on_remove_clicked(None)
    assert len(success_called) == 1
    assert stamp.has_password() is False


def test_stamp_verification_dialog():
    stamp = CustomStamp(
        stamp_id="test_ver_1",
        name="Confidential Stamp",
        image_bytes=b"dummy_bytes",
    )
    stamp.set_password("OpenSesame42")

    verified_calls = []
    cancelled_calls = []

    dlg = StampVerificationDialog(
        parent_window=None,
        stamp=stamp,
        on_verified_callback=lambda: verified_calls.append(True),
        on_cancelled_callback=lambda: cancelled_calls.append(True),
    )

    # Wrong password attempt
    dlg.password_entry.set_text("WrongCode")
    dlg._on_unlock_clicked(None)

    assert len(verified_calls) == 0
    assert dlg.error_label.get_visible() is True

    # Correct password attempt
    dlg.password_entry.set_text("OpenSesame42")
    dlg._on_unlock_clicked(None)

    assert len(verified_calls) == 1
    assert len(cancelled_calls) == 0


def test_stamp_verification_dialog_cancellation():
    stamp = CustomStamp(
        stamp_id="test_ver_2",
        name="Confidential Stamp 2",
        image_bytes=b"dummy_bytes",
    )
    stamp.set_password("OpenSesame42")

    verified_calls = []
    cancelled_calls = []

    dlg = StampVerificationDialog(
        parent_window=None,
        stamp=stamp,
        on_verified_callback=lambda: verified_calls.append(True),
        on_cancelled_callback=lambda: cancelled_calls.append(True),
    )

    # User clicks cancel
    dlg._on_cancel_clicked(None)
    dlg._on_window_destroyed(None)

    assert len(verified_calls) == 0
    assert len(cancelled_calls) == 1


# ============================================================================
# SECTION: test_sticky_notes.py
# ============================================================================
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


# ============================================================================
# SECTION: test_annotations_sidebar.py
# ============================================================================
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


class SidebarDummyWindow:
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
        self.window = SidebarDummyWindow()
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

