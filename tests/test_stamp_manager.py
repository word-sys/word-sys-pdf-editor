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

