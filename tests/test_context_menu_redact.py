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


