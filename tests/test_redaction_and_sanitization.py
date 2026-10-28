"""Consolidated Redaction and Document Sanitization Test Suite for word-sys-pdf-editor.

This suite merges context-menu redaction workflows, search-and-redact automation,
stream-level redaction engines, metadata stripping, hidden content removal, and
comprehensive PDF sanitization tests.
"""

# ============================================================================
# SECTION: test_context_menu_redact.py
# ============================================================================
import fitz
import pytest
from unittest.mock import MagicMock, patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk

from word_sys_pdf_editor.models import DocumentSession, RedactionMark, EditableText, EditableShape, EditableImage
from word_sys_pdf_editor.search_engine import DocumentSearchEngine
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
    button_labels = []
    all_texts = []
    current_child = child_box.get_first_child()
    while current_child:
        if isinstance(current_child, Gtk.Button):
            button_labels.append(current_child.get_label())
        elif isinstance(current_child, Gtk.Label):
            all_texts.append(current_child.get_text())
        current_child = current_child.get_next_sibling()

    # Header label displays selected word preview
    assert any("Programlama" in t for t in all_texts)
    # Action buttons have concise standard labels to prevent horizontal overflow
    assert _("menu_mark_for_redaction") in button_labels
    assert _("btn_delete_word") in button_labels
    # Also should contain paragraph fallbacks
    assert _("menu_mark_paragraph_for_redaction") in button_labels
    assert _("btn_delete_paragraph") in button_labels


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


def test_editable_text_width_height_properties():
    """Verify EditableText width and height properties and setters."""
    text_obj = EditableText(x=20.0, y=30.0, text="Sample", font_size=14.0)
    text_obj.bbox = (20.0, 30.0, 120.0, 48.0)
    assert text_obj.width == 100.0
    assert text_obj.height == 18.0

    text_obj.width = 150.0
    assert text_obj.width == 150.0
    assert text_obj.bbox[2] == 170.0

    text_obj.height = 25.0
    assert text_obj.height == 25.0
    assert text_obj.bbox[3] == 55.0


def test_split_at_range_with_char_boxes():
    """Verify split_at_range preserves sub-pixel geometry when char_boxes are present."""
    text_obj = EditableText(x=0.0, y=0.0, text="Word1 Word2 Word3", font_size=10.0)
    # Mock char_boxes: 5 chars for Word1, 1 space, 5 chars for Word2, 1 space, 5 chars for Word3 (total 17 chars)
    cbs = []
    curr_x = 10.0
    for idx, c in enumerate("Word1 Word2 Word3"):
        w = 4.0 if c == " " else 8.0
        cbs.append({
            "char": c,
            "bbox": (curr_x, 10.0, curr_x + w, 22.0),
            "origin": (curr_x, 20.0),
            "synthetic": False,
            "index": idx
        })
        curr_x += w
    text_obj.char_boxes = cbs
    text_obj.bbox = (10.0, 10.0, curr_x, 22.0)

    # Split Word2 (indices 6 to 11)
    spans = text_obj.split_at_range(6, 11)
    assert len(spans) == 3
    pre, mid, post = spans[0], spans[1], spans[2]

    assert pre.text == "Word1 "
    assert mid.text == "Word2"
    assert post.text == " Word3"

    # Exact sub-pixel char_boxes sliced
    assert len(pre.char_boxes) == 6
    assert len(mid.char_boxes) == 5
    assert len(post.char_boxes) == 6

    # Indexes reset
    assert [cb["index"] for cb in mid.char_boxes] == [0, 1, 2, 3, 4]

    # Sub-pixel exact bboxes matching char_boxes
    assert mid.bbox[0] == cbs[6]["bbox"][0]
    assert mid.bbox[2] == cbs[10]["bbox"][2]
    assert post.bbox[0] == cbs[11]["bbox"][0]


def test_get_selected_word_bbox_with_char_boxes():
    """Verify get_selected_word_bbox uses char_boxes for sub-pixel precision."""
    window = MagicMock()
    window.word_selection_mode = True
    window.selected_word_start_char = 3
    window.selected_word_end_char = 6

    text_obj = EditableText(x=0.0, y=0.0, text="ABCDEFGHI", font_size=12.0)
    cbs = [
        {"char": c, "bbox": (float(i * 10), 5.0, float((i + 1) * 10), 20.0), "index": i}
        for i, c in enumerate("ABCDEFGHI")
    ]
    text_obj.char_boxes = cbs
    text_obj.bbox = (0.0, 5.0, 90.0, 20.0)
    window.selected_text = text_obj

    func = PdfEditorWindow.get_selected_word_bbox.__get__(window, PdfEditorWindow)
    bbox = func()
    # Indices 3 to 6: DEF -> x0 = 30.0, x1 = 60.0
    assert bbox == (30.0, 5.0, 60.0, 20.0)


def test_toggle_word_style():
    """Verify _toggle_word_style toggles formatting and reflows subsequent text."""
    doc = fitz.open()
    doc.new_page(width=500, height=400)
    session = DocumentSession(doc=doc, pdf_path=None)

    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window.word_selection_mode = True
    window.undo_manager = UndoManager(window)
    session.undo_manager = window.undo_manager
    window._update_ui_state = MagicMock()
    window.pdf_view = Gtk.Box()

    text_obj = EditableText(x=10.0, y=10.0, text="First Second Third", font_size=12.0, page_number=0)
    text_obj.bbox = (10.0, 10.0, 200.0, 25.0)
    session.editable_texts = [text_obj]
    window.editable_texts = session.editable_texts
    window.selected_text = text_obj

    # "Second" (indices 6 to 12)
    window.selected_word = "Second"
    window.selected_word_start_char = 6
    window.selected_word_end_char = 12

    toggle_func = PdfEditorWindow._toggle_word_style.__get__(window, PdfEditorWindow)
    toggle_func(text_obj, "bold")

    # Target text should have been split into 3 spans in session.editable_texts
    assert len(session.editable_texts) == 3
    pre = session.editable_texts[0]
    mid = session.editable_texts[1]
    post = session.editable_texts[2]

    assert pre.text == "First "
    assert mid.text == "Second"
    assert post.text == " Third"
    assert mid.is_bold is True

    # Undo
    window.undo_manager.undo()
    assert len(session.editable_texts) == 1
    assert session.editable_texts[0].text == "First Second Third"


def test_word_styling_baked_flags_prevent_duplicate_canvas_overlay():
    """Verify that split_at_range and styling operations maintain is_baked=True so Cairo does not duplicate text."""
    text_obj = EditableText(x=10.0, y=10.0, text="Bilişim Sistemleri Mühendisliği 1.Sınıf", font_size=12.0, page_number=0)
    text_obj.bbox = (10.0, 10.0, 300.0, 25.0)

    # Split "1.Sınıf" (chars 32 to 39)
    spans = text_obj.split_at_range(32, 39)
    assert len(spans) == 2
    pre, mid = spans[0], spans[1]

    assert pre.text == "Bilişim Sistemleri Mühendisliği "
    assert mid.text == "1.Sınıf"

    # All generated spans MUST be flagged is_baked=True and is_new=True
    assert pre.is_baked is True
    assert pre.is_new is True
    assert pre.page_number == 0

    assert mid.is_baked is True
    assert mid.is_new is True
    assert mid.page_number == 0


def test_docked_search_redact_bar_workflow():
    """Verify Find & Redact operates as a docked bar above canvas rather than a modal dialog."""
    doc = fitz.open()
    p = doc.new_page(width=500, height=400)
    p.insert_text(fitz.Point(50, 100), "Confidential Secret Data with Secret Words", fontsize=12)
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

    # Real search bar and entry
    search_bar = Gtk.SearchBar()
    search_entry = Gtk.SearchEntry()
    search_bar.connect_entry(search_entry)
    search_redact_box = Gtk.Box()
    search_redact_box.set_visible(False)
    search_redact_btn = Gtk.ToggleButton()

    window.search_bar = search_bar
    window.search_entry = search_entry
    window.search_redact_box = search_redact_box
    window.search_redact_btn = search_redact_btn
    window.search_button = Gtk.ToggleButton()
    window.search_match_label = Gtk.Label()
    window.search_case_btn = Gtk.ToggleButton()
    window.search_whole_word_btn = Gtk.ToggleButton()
    window.search_engine = DocumentSearchEngine(doc)
    window.continuous_scroll = False
    window.zoom_level = 1.0

    def mock_add(mark, session=None):
        sess = session or window._active_session
        p_num = mark.page_number
        if p_num not in sess.redaction_marks:
            sess.redaction_marks[p_num] = []
        if mark not in sess.redaction_marks[p_num]:
            sess.redaction_marks[p_num].append(mark)

    def mock_remove(mark, session=None):
        sess = session or window._active_session
        p_num = mark.page_number
        if p_num in sess.redaction_marks and mark in sess.redaction_marks[p_num]:
            sess.redaction_marks[p_num].remove(mark)

    window._add_redaction_mark_to_session = mock_add
    window._remove_redaction_mark_from_session = mock_remove
    window._update_redaction_controls = MagicMock()
    window._unrotated_to_visual_page_coords = MagicMock(return_value=(50.0, 100.0))
    window.pdf_scroll = MagicMock()

    stage_func = PdfEditorWindow.stage_redactions_for_matches.__get__(window, PdfEditorWindow)
    window.stage_redactions_for_matches = stage_func

    nav_next_func = PdfEditorWindow._search_navigate_next.__get__(window, PdfEditorWindow)
    window._search_navigate_next = nav_next_func
    jump_func = PdfEditorWindow._jump_to_current_search_match.__get__(window, PdfEditorWindow)
    window._jump_to_current_search_match = jump_func

    exec_search = PdfEditorWindow._execute_search_query.__get__(window, PdfEditorWindow)
    window._execute_search_query = exec_search
    query_changed = PdfEditorWindow._on_search_query_changed.__get__(window, PdfEditorWindow)
    window._on_search_query_changed = query_changed

    find_redact_func = PdfEditorWindow.on_find_and_redact.__get__(window, PdfEditorWindow)
    redact_curr_func = PdfEditorWindow._redact_current_search_match.__get__(window, PdfEditorWindow)
    redact_all_func = PdfEditorWindow._redact_all_search_matches.__get__(window, PdfEditorWindow)

    # 1. Trigger on_find_and_redact with query "Secret"
    find_redact_func("Secret")

    # Verify docked bar is revealed in redaction mode without opening any modal dialog
    assert search_bar.get_search_mode() is True
    assert search_redact_box.get_visible() is True
    assert search_redact_btn.get_active() is True
    assert search_entry.get_text() == "Secret"

    # Search engine should have found matches on the document
    assert len(window.search_engine.matches) >= 2

    # 2. Redact current match
    redact_curr_func()
    assert len(session.redaction_marks[0]) == 1

    # 3. Redact all remaining matches
    redact_all_func()
    # All matches staged
    assert len(session.redaction_marks[0]) >= 2




# ============================================================================
# SECTION: test_search_redact.py
# ============================================================================
import fitz
import pytest
from unittest.mock import MagicMock

from word_sys_pdf_editor.search_engine import DocumentSearchEngine, SearchMatch, PII_PATTERNS
from word_sys_pdf_editor.models import DocumentSession, RedactionMark
from word_sys_pdf_editor.undo_manager import UndoManager, CompositeCommand, AddRedactionCommand
from word_sys_pdf_editor import pdf_handler


def _create_sample_pii_pdf() -> fitz.Document:
    doc = fitz.open()
    # Page 0: SSN and Email
    p0 = doc.new_page(width=500, height=400)
    p0.insert_text(fitz.Point(50, 100), "Employee SSN: 123-45-6789", fontsize=12)
    p0.insert_text(fitz.Point(50, 150), "Contact email: test.user@example.com", fontsize=12)

    # Page 1: Credit Card and Phone
    p1 = doc.new_page(width=500, height=400)
    p1.insert_text(fitz.Point(50, 100), "Payment Card: 4111-2222-3333-4444", fontsize=12)
    p1.insert_text(fitz.Point(50, 150), "Direct phone: (555) 123-4567", fontsize=12)

    # Page 2: Date and repeated SSN
    p2 = doc.new_page(width=500, height=400)
    p2.insert_text(fitz.Point(50, 100), "Record created on 2026-10-23", fontsize=12)
    p2.insert_text(fitz.Point(50, 150), "Duplicate SSN: 987-65-4321", fontsize=12)

    return doc


def test_pii_patterns_exist():
    expected_keys = {"ssn", "credit_card", "email", "phone", "date"}
    assert expected_keys.issubset(set(PII_PATTERNS.keys()))
    for k in expected_keys:
        assert "regex" in PII_PATTERNS[k]
        assert "label_key" in PII_PATTERNS[k]


def test_search_pii_ssn_detection():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    # Entire document: pages 0 and 2 have SSNs
    matches = engine.search_pii(doc, "ssn")
    assert len(matches) == 2
    matched_pages = {m.page_index for m in matches}
    assert matched_pages == {0, 2}
    assert any("123-45-6789" in m.text for m in matches)
    assert any("987-65-4321" in m.text for m in matches)


def test_search_pii_scoped_to_single_page():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    # Only search page 0
    matches_p0 = engine.search_pii(doc, "ssn", page_indices=[0])
    assert len(matches_p0) == 1
    assert matches_p0[0].page_index == 0
    assert "123-45-6789" in matches_p0[0].text

    # Search page 1 (no SSN)
    matches_p1 = engine.search_pii(doc, "ssn", page_indices=[1])
    assert len(matches_p1) == 0


def test_search_pii_email_and_credit_card():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    email_matches = engine.search_pii(doc, "email")
    assert len(email_matches) == 1
    assert email_matches[0].page_index == 0
    assert "test.user@example.com" in email_matches[0].text

    cc_matches = engine.search_pii(doc, "credit_card")
    assert len(cc_matches) == 1
    assert cc_matches[0].page_index == 1
    assert "4111-2222-3333-4444" in cc_matches[0].text


def test_search_pii_phone_and_date():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    phone_matches = engine.search_pii(doc, "phone")
    assert len(phone_matches) >= 1
    assert any(m.page_index == 1 for m in phone_matches)

    date_matches = engine.search_pii(doc, "date")
    assert len(date_matches) >= 1
    assert any(m.page_index == 2 for m in date_matches)


def test_search_regex_custom_pattern():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)

    matches = engine.search_regex(doc, r"Employee\s+SSN")
    assert len(matches) == 1
    assert matches[0].page_index == 0


def test_stage_redactions_composite_command_and_undo():
    doc = _create_sample_pii_pdf()
    session = DocumentSession(doc=doc, pdf_path=None)

    # Mock editor window
    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window._update_undo_redo_buttons = MagicMock()
    undo_mgr = UndoManager(window)
    session.undo_manager = undo_mgr
    window.undo_manager = undo_mgr
    window.document_modified = False

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

    from word_sys_pdf_editor.window import PdfEditorWindow
    stage_func = PdfEditorWindow.stage_redactions_for_matches.__get__(window, PdfEditorWindow)

    engine = DocumentSearchEngine(doc)
    matches = engine.search_pii(doc, "ssn")
    assert len(matches) == 2

    # Stage redactions
    count = stage_func(matches, overlay_text="CONFIDENTIAL", fill_color=(0.0, 0.0, 0.0))
    assert count == 2

    total_staged = sum(len(marks) for marks in session.redaction_marks.values())
    assert total_staged == 2
    assert len(session.redaction_marks[0]) == 1
    assert len(session.redaction_marks[2]) == 1
    assert session.redaction_marks[0][0].overlay_text == "CONFIDENTIAL"

    # Single Undo reverts all staged marks
    assert undo_mgr.can_undo() is True
    undo_mgr.undo()

    total_after_undo = sum(len(marks) for marks in session.redaction_marks.values())
    assert total_after_undo == 0

    # Redo restores all staged marks
    assert undo_mgr.can_redo() is True
    undo_mgr.redo()

    total_after_redo = sum(len(marks) for marks in session.redaction_marks.values())
    assert total_after_redo == 2


def test_batch_search_and_redact_permanent_purge():
    doc = _create_sample_pii_pdf()
    engine = DocumentSearchEngine(doc)
    matches = engine.search_pii(doc, "email")
    assert len(matches) == 1

    # Stage mark
    m = matches[0]
    mark = RedactionMark(
        page_number=m.page_index,
        bbox=m.bbox,
        fill_color=(0.0, 0.0, 0.0),
        overlay_text="[REDACTED]"
    )

    # Burn redaction permanently into stream
    success = pdf_handler.apply_redaction_marks(doc, {m.page_index: [mark]})
    assert success is True

    # Verify stream eradication
    page = doc[0]
    assert "test.user@example.com" not in page.get_text()
    cleaned_bytes = doc.tobytes(garbage=4, deflate=True, clean=True)
    assert b"test.user@example.com" not in cleaned_bytes


def test_search_redact_dialog_ui():
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw
    Adw.init()

    from word_sys_pdf_editor.search_redact_dialog import SearchRedactDialog

    doc = _create_sample_pii_pdf()
    confirmed_data = []

    def on_confirm(matches, overlay_text, fill_color, text_color):
        confirmed_data.append((matches, overlay_text, fill_color, text_color))

    dialog = SearchRedactDialog(
        parent_window=None,
        doc=doc,
        current_page_num=0,
        initial_query="Employee",
        default_fill=(0.0, 0.0, 0.0),
        default_overlay="[REDACTED]",
        on_confirm_callback=on_confirm
    )

    # Initial query should trigger matching immediately
    assert len(dialog.current_matches) == 1
    assert dialog.confirm_btn.get_sensitive() is True

    # Switching to PII pattern mode
    dialog.mode_dropdown.set_selected(1)
    dialog._on_mode_changed(dialog.mode_dropdown, None)
    # Default pattern is SSN (index 0)
    assert len(dialog.current_matches) == 2
    assert dialog.confirm_btn.get_sensitive() is True

    # Confirm action
    dialog._on_confirm_clicked(dialog.confirm_btn)
    assert len(confirmed_data) == 1
    matches, overlay, fill, text_col = confirmed_data[0]
    assert len(matches) == 2
    assert overlay == "[REDACTED]"
    assert fill == (0.0, 0.0, 0.0)
    assert text_col == (1.0, 1.0, 1.0)



# ============================================================================
# SECTION: test_stream_redaction_engine.py
# ============================================================================
import io
from unittest.mock import MagicMock, patch
import fitz
from PIL import Image

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import RedactionMark
from word_sys_pdf_editor.window import PdfEditorWindow


def _make_test_image_bytes(width=100, height=100, bg_color=(255, 255, 255), fg_rect=(30, 30, 70, 70), fg_color=(255, 0, 0)):
    im = Image.new("RGB", (width, height), bg_color)
    for x in range(fg_rect[0], fg_rect[2]):
        for y in range(fg_rect[1], fg_rect[3]):
            im.putpixel((x, y), fg_color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_text_eradication_from_stream():
    """Verify underlying text char spans and glyphs are permanently eradicated from the stream."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 80), "CONFIDENTIAL_API_KEY_12345", fontsize=14)

    # Confirm text is searchable before redaction
    assert "CONFIDENTIAL_API_KEY_12345" in page.get_text()
    assert len(page.search_for("CONFIDENTIAL_API_KEY_12345")) > 0

    # Apply redaction mark
    mark = RedactionMark(
        page_number=0,
        bbox=(40, 60, 300, 100),
        overlay_text="[REDACTED]",
        fill_color=(0.0, 0.0, 0.0),
        text_color=(1.0, 1.0, 1.0),
        font_size=10.0
    )
    success = pdf_handler.apply_redaction_marks(doc, {0: [mark]})
    assert success is True

    # 1. Page text check
    page_text = page.get_text()
    assert "CONFIDENTIAL_API_KEY_12345" not in page_text
    assert "[REDACTED]" in page_text

    # 2. Search check
    hits = page.search_for("CONFIDENTIAL_API_KEY_12345")
    assert len(hits) == 0

    # 3. Audit helper check
    purged = pdf_handler.verify_redaction_purge(doc, 0, (40, 60, 300, 100), search_term="CONFIDENTIAL_API_KEY_12345")
    assert purged is True

    # 4. Binary purge check with deflation
    cleaned_bytes = doc.tobytes(garbage=4, deflate=True, clean=True)
    assert b"CONFIDENTIAL_API_KEY_12345" not in cleaned_bytes


def test_image_pixel_blanking():
    """Verify overlapping image pixels are blanked out while surrounding image remains intact."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    img_data = _make_test_image_bytes(width=100, height=100, bg_color=(255, 255, 255), fg_rect=(40, 40, 60, 60), fg_color=(255, 0, 0))
    page.insert_image(fitz.Rect(50, 50, 250, 250), stream=img_data)

    # Redact only the red center square
    mark = RedactionMark(
        page_number=0,
        bbox=(130, 130, 170, 170),
        overlay_text="",
        fill_color=(0.0, 0.0, 0.0)
    )
    success = pdf_handler.apply_redaction_marks(doc, {0: [mark]})
    assert success is True

    pix = page.get_pixmap(dpi=72)
    # The center pixel should now be black (0, 0, 0)
    assert pix.pixel(150, 150)[:3] == (0, 0, 0)
    # The corner pixel outside redaction should still be white (255, 255, 255)
    assert pix.pixel(60, 60)[:3] == (255, 255, 255)


def test_custom_fill_and_overlay_text():
    """Verify white fill with black text and custom exemption codes."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 80), "RESTRICTED FINANCIAL DATA", fontsize=12)

    mark = RedactionMark(
        page_number=0,
        bbox=(45, 60, 280, 100),
        overlay_text="FOIA (b)(4)",
        fill_color=(1.0, 1.0, 1.0),
        text_color=(0.0, 0.0, 0.0),
        font_size=11.0
    )
    success = pdf_handler.apply_redaction_marks(doc, {0: [mark]})
    assert success is True

    text = page.get_text()
    assert "RESTRICTED FINANCIAL DATA" not in text
    assert "FOIA (b)(4)" in text


def test_safety_warning_dialog_rejection():
    """Verify rejecting the safety warning cancels redaction application."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)

    win = MagicMock()
    win.doc = doc
    mark = RedactionMark(page_number=0, bbox=(10, 10, 50, 50))
    win._active_session = MagicMock()
    win._active_session.redaction_marks = {0: [mark]}

    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=False):
        result = PdfEditorWindow.apply_all_redactions(win, prompt_warning=True)

    assert result is False
    # Staged mark must remain intact in session
    assert len(win._active_session.redaction_marks[0]) == 1


def test_safety_warning_dialog_acceptance():
    """Verify accepting the safety warning burns redactions and invalidates caches."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "TOP_SECRET", fontsize=12)
    pdf_handler.save_page_snapshot(doc, 0, force=True)

    win = MagicMock()
    win.doc = doc
    win.current_page_index = 0
    mark = RedactionMark(page_number=0, bbox=(40, 30, 200, 70), overlay_text="[REDACTED]")
    win._active_session = MagicMock()
    win._active_session.redaction_marks = {0: [mark]}
    win._page_objects_cache = {0: "old_cached_objects"}
    win.status_label = MagicMock()
    win.pdf_view = MagicMock()
    win.annotations_sidebar = MagicMock()

    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=True):
        result = PdfEditorWindow.apply_all_redactions(win, prompt_warning=True)

    assert result is True
    assert len(win._active_session.redaction_marks) == 0
    assert 0 not in win._page_objects_cache
    win._load_page.assert_called_once_with(0, reload_objects=True)
    win.status_label.set_text.assert_called()


def test_save_interception_when_marks_pending():
    """Verify save_document / on_save_clicked prompts user when pending marks exist."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)

    win = MagicMock()
    win.doc = doc
    win.current_file_path = "/tmp/test_save.pdf"
    win._active_session = MagicMock()
    mark = RedactionMark(page_number=0, bbox=(10, 10, 50, 50))
    win._active_session.redaction_marks = {0: [mark]}

    # User cancels prompt
    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=False):
        PdfEditorWindow.on_save_clicked(win, None)
        win.save_document.assert_not_called()

    # User confirms prompt
    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=True):
        PdfEditorWindow.on_save_clicked(win, None)
        win.apply_all_redactions.assert_called_with(prompt_warning=False)
        win.save_document.assert_called_with("/tmp/test_save.pdf", incremental=False)


def test_redaction_toolbar_and_controls_integration():
    """Verify live badge update on redaction apply button in toolbar."""
    win = MagicMock()
    win.redaction_apply_button = MagicMock()
    win._active_session = MagicMock()

    # 0 marks: button is disabled
    win._active_session.redaction_marks = {}
    PdfEditorWindow._update_redaction_controls(win)
    win.redaction_apply_button.set_sensitive.assert_called_with(False)

    # 3 marks: button is enabled and label includes count
    m1 = RedactionMark(page_number=0, bbox=(0, 0, 10, 10))
    m2 = RedactionMark(page_number=0, bbox=(20, 20, 30, 30))
    m3 = RedactionMark(page_number=1, bbox=(5, 5, 15, 15))
    win._active_session.redaction_marks = {0: [m1, m2], 1: [m3]}
    PdfEditorWindow._update_redaction_controls(win)
    win.redaction_apply_button.set_sensitive.assert_called_with(True)
    # Check that label was set with count 3
    args, _ = win.redaction_apply_button.set_label.call_args
    assert "3" in args[0]


# ============================================================================
# SECTION: test_document_sanitization.py
# ============================================================================
import io
from unittest.mock import MagicMock, patch
import fitz
import pytest

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.models import RedactionMark
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.sanitize_dialog import SanitizeDialog


def test_redaction_cairo_cache_invalidation():
    """Verify that after applying redactions, the cached Cairo surface is invalidated

    and the newly fetched Cairo surface reflects the applied redactions immediately on UI.
    """
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "KONU: ODEV PART-2", fontsize=12)

    # 1. Simulate UI drawing the page prior to redaction
    surf1 = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf1 is not None

    # 2. Add staged redaction mark and burn into PDF stream
    mark = RedactionMark(
        page_number=0,
        bbox=(40, 35, 220, 65),
        overlay_text="CONFIDENTIAL",
        fill_color=(0.0, 0.0, 0.0),
        text_color=(1.0, 1.0, 1.0)
    )
    success = pdf_handler.apply_redaction_marks(doc, {0: [mark]})
    assert success is True

    # 3. Requesting Cairo surface again must return a fresh, re-rendered surface
    surf2 = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf2 is not None
    assert surf2 is not surf1, "Cairo surface cache was not invalidated after redaction!"

    # 4. Underlying text must be eradicated from page
    assert "KONU: ODEV PART-2" not in page.get_text()
    assert "CONFIDENTIAL" in page.get_text()


def test_redaction_ui_flow_cache_invalidation():
    """Verify apply_all_redactions in PdfEditorWindow invalidates page cache and triggers redraw."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "CONFIDENTIAL_REPORT", fontsize=12)

    # Prime cairo surface cache
    surf_before = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf_before is not None

    win = MagicMock()
    win.doc = doc
    win.current_page_index = 0
    mark = RedactionMark(page_number=0, bbox=(40, 30, 250, 70), overlay_text="[REDACTED]")
    win._active_session = MagicMock()
    win._active_session.redaction_marks = {0: [mark]}
    win._page_objects_cache = {0: {}}
    win.status_label = MagicMock()
    win.pdf_view = MagicMock()
    win.annotations_sidebar = MagicMock()

    with patch("word_sys_pdf_editor.window.show_confirm_dialog", return_value=True):
        result = PdfEditorWindow.apply_all_redactions(win, prompt_warning=True)

    assert result is True
    # Verify cache key was purged
    cache_key = (id(doc), 0, 1.0)
    assert cache_key not in pdf_handler._cairo_page_cache

    surf_after = pdf_handler.get_page_cairo_surface(doc, 0, 1.0)
    assert surf_after is not surf_before


def test_sanitize_metadata_and_xmp():
    """Verify sanitize_document strips all standard metadata, trailer Info dict, and XMP packets."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.set_metadata({
        "title": "Secret Strategy",
        "author": "Chief Officer",
        "subject": "Acquisition",
        "keywords": "confidential, merger",
        "creator": "WordSys Internal Tool",
        "producer": "Enterprise PDF",
    })
    doc.set_xml_metadata(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator><rdf:Seq>'
        '<rdf:li>Internal Department</rdf:li></rdf:Seq></dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>'
    )

    # Verify document is dirty before sanitization
    hygiene_before = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_before["is_clean"] is False
    assert "sensitive_metadata" in hygiene_before["details"]
    assert "has_xmp" in hygiene_before["details"]

    # Sanitize document
    res = pdf_handler.sanitize_document(doc, strip_metadata=True, purge_xmp=True)
    assert res["success"] is True
    assert res["metadata_stripped"] is True
    assert res["xmp_purged"] is True

    # Verify metadata is blank
    meta = doc.metadata
    for field in ("title", "author", "subject", "keywords", "creator", "producer"):
        assert meta.get(field, "") == ""

    # Verify XMP is gone
    assert doc.get_xml_metadata() == ""
    cat = doc.pdf_catalog()
    assert "Metadata" not in doc.xref_get_keys(cat)

    # Verify hygiene check passes
    hygiene_after = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_after["is_clean"] is True


def test_sanitize_embedded_attachments():
    """Verify document-level embedded files and page-level file attachment annotations are purged."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    doc.embfile_add("payload.bin", b"sensitive binary stream", filename="payload.bin")
    page.add_file_annot((100, 100), b"attached evidence notes", "notes.txt")

    assert doc.embfile_count() == 1
    assert any(a.type[1] == "FileAttachment" for a in page.annots())

    res = pdf_handler.sanitize_document(doc, strip_metadata=False, purge_xmp=False, purge_attachments=True)
    assert res["success"] is True
    assert res["attachments_purged"] >= 2
    assert doc.embfile_count() == 0
    assert not any(a.type[1] == "FileAttachment" for a in page.annots())


def test_sanitize_comments_and_markup_preserving_forms_and_links():
    """Verify sticky notes and review comments are purged while form fields and links are preserved."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)

    # 1. Add comment & review markup
    page.add_text_annot((50, 50), "Reviewer Comment 1")
    page.add_highlight_annot(fitz.Rect(60, 60, 150, 80))

    # 2. Add an AcroForm widget (Form field)
    widget = fitz.Widget()
    widget.rect = fitz.Rect(100, 150, 250, 180)
    widget.field_name = "UserFullName"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    page.add_widget(widget)

    # 3. Add a hyperlink
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(100, 200, 200, 220), "uri": "https://example.com"})

    # Re-open doc from memory to ensure PyMuPDF parses the link structures
    doc = fitz.open("pdf", doc.tobytes())
    page = doc[0]

    # Add comments
    page.add_text_annot((50, 50), "Reviewer Comment 1")
    page.add_highlight_annot(fitz.Rect(60, 60, 150, 80))

    annots_before = [a.type[1] for a in page.annots()]
    assert "Text" in annots_before
    assert "Highlight" in annots_before
    assert len(list(page.widgets())) == 1
    assert len(page.get_links()) == 1

    # Sanitize comments with preserve_forms=True and preserve_links=True
    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=True,
        preserve_forms=True,
        preserve_links=True
    )

    assert res["success"] is True
    assert res["comments_purged"] >= 2

    annots_after = [a.type[1] for a in page.annots()]
    assert "Text" not in annots_after
    assert "Highlight" not in annots_after
    assert len(list(page.widgets())) == 1, "Form field widget should have been preserved!"
    assert len(page.get_links()) > 0, "Hyperlink should have been preserved!"


def test_sanitize_hidden_layers_ocgs():
    """Verify Optional Content Groups (OCGs) are purged during sanitization."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    doc.add_ocg("Visible Design", on=1)
    doc.add_ocg("Hidden Confidential Annotations", on=0)

    ocgs_before = doc.get_ocgs()
    assert len(ocgs_before) >= 2

    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=True
    )

    assert res["success"] is True
    assert res["hidden_layers_purged"] >= 2
    assert len(doc.get_ocgs()) == 0


def test_sanitize_orphaned_and_redacted_toc_bookmarks():
    """Verify bookmarks pointing to redacted or invalid pages are cleanly purged."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)

    toc = [
        [1, "Public Chapter 1", 1],
        [1, "Confidential Section 2", 2],
        [2, "Sub-secret 2.1", 2],
        [1, "Public Conclusion", 3],
        [1, "Dangling Reference", 99]
    ]
    doc.set_toc(toc)

    # Page 1 (0-indexed, which corresponds to page 2 in 1-based TOC) was redacted
    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        purge_orphaned_toc=True,
        redacted_pages={1}
    )

    assert res["success"] is True
    assert res["toc_items_purged"] >= 2

    cleaned_toc = doc.get_toc()
    titles = [item[1] for item in cleaned_toc]
    assert "Public Chapter 1" in titles
    assert "Public Conclusion" in titles
    assert "Confidential Section 2" not in titles
    assert "Sub-secret 2.1" not in titles


def test_sanitize_strip_all_bookmarks():
    """Verify strip_bookmarks option completely clears the entire Table of Contents."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)
    doc.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])

    assert len(doc.get_toc()) == 2

    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        strip_bookmarks=True
    )

    assert res["success"] is True
    assert res["toc_items_purged"] == 2
    assert len(doc.get_toc()) == 0


def test_sanitize_dialog_ui_and_window_integration():
    """Verify SanitizeDialog controls and PdfEditorWindow sanitize_active_document."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    doc.set_metadata({"author": "Target User", "title": "Classified"})

    win = MagicMock()
    win.doc = doc
    win.current_page_index = 0
    win._active_session = MagicMock()
    win._active_session.sticky_note_objects = [MagicMock()]
    win.sticky_notes = [MagicMock()]
    win._page_objects_cache = {0: {}}
    win.status_label = MagicMock()
    win.pdf_view = MagicMock()
    win.annotations_sidebar = MagicMock()

    options = {
        "strip_metadata": True,
        "purge_xmp": True,
        "purge_attachments": True,
        "purge_hidden_layers": True,
        "purge_comments": True,
        "purge_orphaned_toc": True,
        "strip_bookmarks": False,
    }

    with patch("word_sys_pdf_editor.window.show_info_dialog") as mock_info:
        res = PdfEditorWindow.sanitize_active_document(win, options)

    assert res["success"] is True
    assert res["metadata_stripped"] is True
    assert len(win._active_session.sticky_note_objects) == 0
    assert len(win.sticky_notes) == 0
    win.status_label.set_text.assert_called()
    mock_info.assert_called_once()


def test_sanitize_dialog_rows_and_markup():
    """Verify SanitizeDialog ActionRows have valid titles and subtitles rendered without Pango markup errors."""
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw
    Adw.init()

    dlg = SanitizeDialog(None)
    rows = [
        dlg.metadata_row,
        dlg.xmp_row,
        dlg.attachments_row,
        dlg.hidden_layers_row,
        dlg.comments_row,
        dlg.orphaned_toc_row,
        dlg.strip_bookmarks_row,
        dlg.thumbnails_row,
        dlg.javascript_row,
        dlg.document_id_row,
    ]
    for row in rows:
        title = row.get_title()
        subtitle = row.get_subtitle()
        assert title and len(title) > 0, f"Row title is empty for row {row}!"
        assert subtitle and len(subtitle) > 0, f"Row subtitle is empty for row {row}!"


def test_sanitize_page_thumbnails():
    """Verify embedded page thumbnails (/Thumb) in page dictionaries are cleanly purged."""
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)
    p0 = doc[0]
    p1 = doc[1]

    # Attach dummy /Thumb references to pages
    doc.xref_set_key(p0.xref, "Thumb", "1 0 R")
    doc.xref_set_key(p1.xref, "Thumb", "2 0 R")

    hygiene_before = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_before["is_clean"] is False
    assert hygiene_before["details"].get("thumbnails_count") == 2

    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        purge_orphaned_toc=False,
        purge_thumbnails=True,
    )

    assert res["success"] is True
    assert res["thumbnails_purged"] == 2
    assert doc.xref_get_key(p0.xref, "Thumb")[0] == "null"
    assert doc.xref_get_key(p1.xref, "Thumb")[0] == "null"

    hygiene_after = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_after["is_clean"] is True


def test_sanitize_javascript_and_actions():
    """Verify OpenAction, AA dictionaries, Names/JavaScript, and widget actions are purged."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    cat = doc.pdf_catalog()

    # Add OpenAction with JS
    doc.xref_set_key(cat, "OpenAction", "<< /S /JavaScript /JS (app.alert('malicious');) >>")
    # Add Catalog /AA
    doc.xref_set_key(cat, "AA", "<< /WS << /S /JavaScript /JS (app.alert('close');) >> >>")
    # Add Page /AA
    doc.xref_set_key(page.xref, "AA", "<< /O << /S /JavaScript /JS (app.alert('open');) >> >>")
    # Add a widget with /AA
    w = fitz.Widget()
    w.rect = fitz.Rect(10, 10, 100, 30)
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_name = "SecureField"
    page.add_widget(w)
    for widget in page.widgets():
        doc.xref_set_key(widget.xref, "AA", "<< /K << /S /JavaScript /JS (app.alert('key');) >> >>")

    hygiene_before = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_before["is_clean"] is False
    assert hygiene_before["details"].get("has_javascript_or_actions") is True

    res = pdf_handler.sanitize_document(
        doc,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        purge_orphaned_toc=False,
        purge_thumbnails=False,
        purge_javascript=True,
    )

    assert res["success"] is True
    assert res["javascript_actions_purged"] >= 4
    assert doc.xref_get_key(cat, "OpenAction")[0] == "null"
    assert doc.xref_get_key(cat, "AA")[0] == "null"
    assert doc.xref_get_key(page.xref, "AA")[0] == "null"
    for widget in page.widgets():
        assert doc.xref_get_key(widget.xref, "AA")[0] == "null"

    hygiene_after = pdf_handler.verify_document_sanitization(doc)
    assert hygiene_after["is_clean"] is True


def test_sanitize_scrub_and_randomize_document_id(tmp_path):
    """Verify document ID (/ID trailer) is anonymized and randomized."""
    orig_path = str(tmp_path / "doc.pdf")
    doc = fitz.open()
    doc.new_page(width=300, height=300)
    doc.save(orig_path)
    doc.close()

    doc2 = fitz.open(orig_path)
    old_id = doc2.xref_get_key(-1, "ID")[1]
    assert old_id != "null"

    res = pdf_handler.sanitize_document(
        doc2,
        strip_metadata=False,
        purge_xmp=False,
        purge_attachments=False,
        purge_comments=False,
        purge_hidden_layers=False,
        purge_orphaned_toc=False,
        scrub_document_id=True,
    )

    assert res["success"] is True
    assert res["document_id_scrubbed"] is True
    new_id = doc2.xref_get_key(-1, "ID")[1]
    assert new_id != "null"
    assert new_id != old_id
    doc2.close()



