import fitz
import pytest
from unittest.mock import MagicMock, patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk

from word_sys_pdf_editor.models import DocumentSession, RedactionMark, EditableText, EditableShape, EditableImage
from word_sys_pdf_editor.undo_manager import UndoManager
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.i18n import _


@pytest.fixture(scope="module", autouse=True)
def init_adw():
    Adw.init()


def test_mark_object_for_redaction_text():
    doc = fitz.open()
    doc.new_page(width=500, height=400)
    session = DocumentSession(doc=doc, pdf_path=None)

    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window.redact_default_fill = (0.0, 0.0, 0.0)
    window.redact_default_text_color = (1.0, 1.0, 1.0)
    window.redact_default_overlay = "[REDACTED]"
    window._update_undo_redo_buttons = MagicMock()
    undo_mgr = UndoManager(window)
    session.undo_manager = undo_mgr
    window.undo_manager = undo_mgr
    window._open_redaction_popover = MagicMock()
    window.mark_object_for_redaction = PdfEditorWindow.mark_object_for_redaction.__get__(window, PdfEditorWindow)

    def mock_add(mark, session=None):
        sess = session or window._active_session
        p = mark.page_number
        if p not in sess.redaction_marks:
            sess.redaction_marks[p] = []
        if mark not in sess.redaction_marks[p]:
            sess.redaction_marks[p].append(mark)

    def mock_remove(mark, session=None):
        sess = session or window._active_session
        p = mark.page_number
        if p in sess.redaction_marks and mark in sess.redaction_marks[p]:
            sess.redaction_marks[p].remove(mark)

    window._add_redaction_mark_to_session = mock_add
    window._remove_redaction_mark_from_session = mock_remove

    text_obj = EditableText(
        text="Confidential User",
        x=50.0,
        y=100.0,
        font_size=12.0,
        page_number=0,
    )
    text_obj.bbox = (50.0, 90.0, 150.0, 110.0)

    mark_func = PdfEditorWindow.mark_object_for_redaction.__get__(window, PdfEditorWindow)
    mark = mark_func(text_obj)

    assert mark is not None
    assert mark.page_number == 0
    assert mark.bbox == (50.0, 90.0, 150.0, 110.0)
    assert mark.overlay_text == "[REDACTED]"
    assert mark.fill_color == (0.0, 0.0, 0.0)
    assert mark in session.redaction_marks[0]

    # Undo
    assert undo_mgr.can_undo() is True
    undo_mgr.undo()
    assert mark not in session.redaction_marks[0]

    # Redo
    assert undo_mgr.can_redo() is True
    undo_mgr.redo()
    assert mark in session.redaction_marks[0]


def test_mark_object_for_redaction_shape_and_image():
    doc = fitz.open()
    doc.new_page(width=500, height=400)
    session = DocumentSession(doc=doc, pdf_path=None)

    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window.redact_default_fill = (1.0, 1.0, 1.0)
    window.redact_default_text_color = (0.0, 0.0, 0.0)
    window.redact_default_overlay = "SECRET"
    window._update_undo_redo_buttons = MagicMock()
    undo_mgr = UndoManager(window)
    session.undo_manager = undo_mgr
    window.undo_manager = undo_mgr
    window._open_redaction_popover = MagicMock()
    window.mark_object_for_redaction = PdfEditorWindow.mark_object_for_redaction.__get__(window, PdfEditorWindow)

    def mock_add(mark, session=None):
        sess = session or window._active_session
        p = mark.page_number
        if p not in sess.redaction_marks:
            sess.redaction_marks[p] = []
        if mark not in sess.redaction_marks[p]:
            sess.redaction_marks[p].append(mark)

    window._add_redaction_mark_to_session = mock_add

    shape_obj = EditableShape(
        shape_type="rectangle",
        bbox=(20.0, 30.0, 80.0, 90.0),
        page_number=0
    )

    image_obj = EditableImage(
        bbox=(100.0, 120.0, 200.0, 220.0),
        page_number=0,
        xref=1,
        image_bytes=b"fake"
    )

    mark_func = PdfEditorWindow.mark_object_for_redaction.__get__(window, PdfEditorWindow)

    mark_s = mark_func(shape_obj)
    assert mark_s.bbox == (20.0, 30.0, 80.0, 90.0)
    assert mark_s.overlay_text == "SECRET"
    assert mark_s.fill_color == (1.0, 1.0, 1.0)

    mark_i = mark_func(image_obj)
    assert mark_i.bbox == (100.0, 120.0, 200.0, 220.0)
    assert mark_i.overlay_text == "SECRET"


def test_edit_mode_context_menu_has_mark_for_redaction():
    """Verify right click on objects in Edit Mode includes Mark for Redaction."""
    doc = fitz.open()
    doc.new_page(width=500, height=400)
    session = DocumentSession(doc=doc, pdf_path=None)

    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window.view_mode = False
    window.word_selection_mode = False
    window.selected_word = None
    window.temp_polygon_vertices = []
    window.canvas_to_page_coords = MagicMock(return_value=(0, 50.0, 100.0))
    window.is_canvas_point_on_page = MagicMock(return_value=True)
    window._find_measurement_at_pos = MagicMock(return_value=None)
    window._update_ui_state = MagicMock()
    window.pdf_view = Gtk.Box()
    window.calculate_smart_popover_placement = MagicMock(return_value=(Gdk.Rectangle(), Gtk.PositionType.BOTTOM))

    text_obj = EditableText(x=50.0, y=100.0, text="Test Text", font_size=12.0, page_number=0)
    text_obj.bbox = (50.0, 90.0, 120.0, 110.0)

    window._find_text_at_pos = MagicMock(return_value=text_obj)
    window._find_shape_at_pos = MagicMock(return_value=None)
    window._find_image_at_pos = MagicMock(return_value=None)
    window._keep_topmost_hit = MagicMock(return_value=(text_obj, None, None))

    on_right_click_func = PdfEditorWindow._on_right_click.__get__(window, PdfEditorWindow)

    gesture_mock = MagicMock()
    with patch('gi.repository.Gtk.EventController.get_current_event_state', return_value=0):
        with patch('gi.repository.Gtk.Popover.popup'):
            on_right_click_func(gesture_mock, 1, 50.0, 100.0)

    assert hasattr(window, 'context_popover') and window.context_popover is not None
    child_box = window.context_popover.get_child()
    assert isinstance(child_box, Gtk.Box)

    labels = []
    current_child = child_box.get_first_child()
    while current_child:
        if isinstance(current_child, Gtk.Button):
            labels.append(current_child.get_label())
        current_child = current_child.get_next_sibling()

    assert _("menu_mark_for_redaction") in labels


def test_view_mode_context_menu_never_has_mark_for_redaction():
    """Verify right click in View Mode NEVER contains Mark for Redaction."""
    doc = fitz.open()
    doc.new_page(width=500, height=400)
    session = DocumentSession(doc=doc, pdf_path=None)

    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window.view_mode = True
    window.temp_polygon_vertices = []
    window.canvas_to_page_coords = MagicMock(return_value=(0, 50.0, 100.0))
    window.is_canvas_point_on_page = MagicMock(return_value=True)
    window._visual_to_unrotated_page_coords = MagicMock(return_value=(50.0, 100.0))
    window._find_sticky_note_at_pos = MagicMock(return_value=None)
    window.view_sel_rect = (40.0, 90.0, 120.0, 110.0)
    window.view_selected_text = "View Mode Selected Text"
    window.pdf_view = Gtk.Box()
    window.get_object_canvas_rect = MagicMock(return_value=None)
    window.calculate_smart_popover_placement = MagicMock(return_value=(Gdk.Rectangle(), Gtk.PositionType.BOTTOM))

    on_right_click_func = PdfEditorWindow._on_right_click.__get__(window, PdfEditorWindow)

    gesture_mock = MagicMock()
    with patch('gi.repository.Gtk.EventController.get_current_event_state', return_value=0):
        with patch('gi.repository.Gtk.Popover.popup'):
            on_right_click_func(gesture_mock, 1, 50.0, 100.0)

    assert hasattr(window, 'context_popover') and window.context_popover is not None
    child_box = window.context_popover.get_child()
    assert isinstance(child_box, Gtk.Box)

    labels = []
    current_child = child_box.get_first_child()
    while current_child:
        if isinstance(current_child, Gtk.Button):
            labels.append(current_child.get_label())
        current_child = current_child.get_next_sibling()

    # In View Mode: Copy, Edit Text, Highlight, Add Note are present
    assert _("btn_copy_text") in labels
    # MUST NOT CONTAIN Mark for Redaction
    assert _("menu_mark_for_redaction") not in labels


def test_word_selection_mode_redacts_only_word_bbox():
    """Verify that when word selection mode is active, only the word bbox is redacted."""
    doc = fitz.open()
    doc.new_page(width=500, height=400)
    session = DocumentSession(doc=doc, pdf_path=None)

    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window.redact_default_fill = (0.0, 0.0, 0.0)
    window.redact_default_text_color = (1.0, 1.0, 1.0)
    window.redact_default_overlay = "[REDACTED]"
    window._update_undo_redo_buttons = MagicMock()
    undo_mgr = UndoManager(window)
    session.undo_manager = undo_mgr
    window.undo_manager = undo_mgr
    window._open_redaction_popover = MagicMock()
    window.mark_object_for_redaction = PdfEditorWindow.mark_object_for_redaction.__get__(window, PdfEditorWindow)

    staged_marks = []
    def mock_add(mark, session=None):
        staged_marks.append(mark)
    window._add_redaction_mark_to_session = mock_add

    # Text: "BSM1011 Algoritmalar ve Programlama I" (36 chars)
    # Bbox: (50.0, 100.0, 410.0, 120.0) -> width = 360.0
    text_obj = EditableText(x=50.0, y=100.0, text="BSM1011 Algoritmalar ve Programlama I", font_size=12.0, page_number=0)
    text_obj.bbox = (50.0, 100.0, 410.0, 120.0)

    window.selected_text = text_obj
    window.word_selection_mode = True
    window.selected_word = "Programlama"
    # "Programlama" starts at index 24, length 11 (24 to 35)
    window.selected_word_start_char = 24
    window.selected_word_end_char = 35
    window.selected_word_bbox = None

    mark_sel_func = PdfEditorWindow.mark_selection_for_redaction.__get__(window, PdfEditorWindow)
    mark_sel_func()

    assert len(staged_marks) == 1
    mark = staged_marks[0]
    # Mark bbox must NOT be the whole text bbox (50.0 to 410.0)
    assert mark.bbox != text_obj.bbox
    # Expected x range roughly 50 + 360 * (24/37) ~ 283.5
    assert mark.bbox[0] > 200.0
    assert mark.bbox[2] <= 410.0
    assert mark.bbox[1] == 100.0
    assert mark.bbox[3] == 120.0


def test_word_selection_mode_context_menu_options():
    """Verify right click in Edit Mode with a word selected shows word-specific redact and delete."""
    doc = fitz.open()
    doc.new_page(width=500, height=400)
    session = DocumentSession(doc=doc, pdf_path=None)

    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window.view_mode = False
    window.word_selection_mode = False
    window.selected_word = None
    window.temp_polygon_vertices = []
    window.canvas_to_page_coords = MagicMock(return_value=(0, 50.0, 100.0))
    window.is_canvas_point_on_page = MagicMock(return_value=True)
    window._find_measurement_at_pos = MagicMock(return_value=None)
    window._update_ui_state = MagicMock()
    window.pdf_view = Gtk.Box()
    window.calculate_smart_popover_placement = MagicMock(return_value=(Gdk.Rectangle(), Gtk.PositionType.BOTTOM))

    text_obj = EditableText(x=50.0, y=100.0, text="BSM1011 Algoritmalar ve Programlama I", font_size=12.0, page_number=0)
    text_obj.bbox = (50.0, 100.0, 410.0, 120.0)

    window.selected_text = text_obj
    window.word_selection_mode = True
    window.selected_word = "Programlama"
    window.selected_word_start_char = 24
    window.selected_word_end_char = 35
    window.selected_word_bbox = None

    window._find_text_at_pos = MagicMock(return_value=text_obj)
    window._find_shape_at_pos = MagicMock(return_value=None)
    window._find_image_at_pos = MagicMock(return_value=None)
    window._keep_topmost_hit = MagicMock(return_value=(text_obj, None, None))

    on_right_click_func = PdfEditorWindow._on_right_click.__get__(window, PdfEditorWindow)

    gesture_mock = MagicMock()
    with patch('gi.repository.Gtk.EventController.get_current_event_state', return_value=0):
        with patch('gi.repository.Gtk.Popover.popup'):
            on_right_click_func(gesture_mock, 1, 50.0, 100.0)

    child_box = window.context_popover.get_child()
    labels = []
    current_child = child_box.get_first_child()
    while current_child:
        if isinstance(current_child, Gtk.Button):
            labels.append(current_child.get_label())
        current_child = current_child.get_next_sibling()

    # Should contain word-specific redact and delete buttons
    assert any("Programlama" in lbl and _("menu_mark_for_redaction") in lbl for lbl in labels)
    assert any("Programlama" in lbl and _("btn_delete_word") in lbl for lbl in labels)
    # Also should contain paragraph fallbacks
    assert _("menu_mark_paragraph_for_redaction") in labels
    assert _("btn_delete_paragraph") in labels


def test_delete_selected_word_from_text():
    """Verify deleting selected word updates text and bbox with undo support."""
    doc = fitz.open()
    doc.new_page(width=500, height=400)
    session = DocumentSession(doc=doc, pdf_path=None)

    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window.document_modified = False
    window.pdf_view = Gtk.Box()
    window._update_undo_redo_buttons = MagicMock()
    undo_mgr = UndoManager(window)
    session.undo_manager = undo_mgr
    window.undo_manager = undo_mgr

    text_obj = EditableText(x=50.0, y=100.0, text="Hello beautiful world", font_size=12.0, page_number=0)
    text_obj.bbox = (50.0, 100.0, 250.0, 120.0)
    text_obj.width = 200.0

    window.selected_text = text_obj
    window.word_selection_mode = True
    window.selected_word = "beautiful"
    window.selected_word_start_char = 6
    window.selected_word_end_char = 15

    del_func = PdfEditorWindow._delete_selected_word_from_text.__get__(window, PdfEditorWindow)
    del_func(text_obj)

    assert text_obj.text == "Hello world"
    assert window.word_selection_mode is False

    # Undo restores "Hello beautiful world"
    assert undo_mgr.can_undo() is True
    undo_mgr.undo()
    assert text_obj.text == "Hello beautiful world"

