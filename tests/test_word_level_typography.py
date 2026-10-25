import copy
import fitz
import pytest
from unittest.mock import MagicMock

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk

from word_sys_pdf_editor.models import DocumentSession, EditableText, measure_text_width
from word_sys_pdf_editor.undo_manager import UndoManager, EditObjectCommand, CompositeCommand
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor import pdf_handler


@pytest.fixture(scope="module", autouse=True)
def init_adw():
    Adw.init()


def create_mock_window(doc):
    session = DocumentSession(doc=doc, pdf_path=None)
    window = MagicMock()
    window.doc = doc
    window._active_session = session
    window.current_page_index = 0
    window._update_undo_redo_buttons = MagicMock()
    window._update_ui_state = MagicMock()
    window.status_label = MagicMock()
    window.pdf_view = MagicMock()
    window._last_font_family = "Liberation Sans"
    window._last_font_size = 11.0
    window._get_current_alignment = MagicMock(return_value='left')
    window.font_scan_in_progress = False
    window.inline_editor_tv = None
    window.inline_editor_text_obj = None
    window.inline_editor_widget = None
    window.underline_button = None
    window.strikethrough_button = None
    window.align_left_button = None
    window.align_center_button = None
    window.align_right_button = None
    window.align_justify_button = None

    undo_mgr = UndoManager(window)
    session.undo_manager = undo_mgr
    window.undo_manager = undo_mgr

    # Bind property accessors to session
    type(window).editable_texts = property(
        lambda self: self._active_session.editable_texts if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'editable_texts', val) if self._active_session else None
    )
    type(window).editable_shapes = property(
        lambda self: self._active_session.editable_shapes if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'editable_shapes', val) if self._active_session else None
    )
    type(window).editable_images = property(
        lambda self: self._active_session.editable_images if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'editable_images', val) if self._active_session else None
    )
    type(window).editable_strokes = property(
        lambda self: self._active_session.editable_strokes if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'editable_strokes', val) if self._active_session else None
    )
    type(window).selected_text = property(
        lambda self: self._active_session.selected_text if self._active_session else None,
        lambda self, val: PdfEditorWindow.selected_text.fset(self, val)
    )
    type(window).word_selection_mode = property(
        lambda self: self._active_session.word_selection_mode if self._active_session else False,
        lambda self, val: setattr(self._active_session, 'word_selection_mode', val) if self._active_session else None
    )

    # Bind methods
    window.commit_pending_format_change = PdfEditorWindow.commit_pending_format_change.__get__(window, PdfEditorWindow)
    window._toggle_word_style = PdfEditorWindow._toggle_word_style.__get__(window, PdfEditorWindow)
    window.on_text_format_changed = PdfEditorWindow.on_text_format_changed.__get__(window, PdfEditorWindow)
    window.get_selected_word_bbox = PdfEditorWindow.get_selected_word_bbox.__get__(window, PdfEditorWindow)

    return window, session


def test_commit_pending_format_change_guards():
    """Verify commit_pending_format_change ignores deleted objects and internal flags."""
    doc = fitz.open()
    doc.new_page(width=500, height=200)
    window, session = create_mock_window(doc)

    t = EditableText(text="Hello world", x=50.0, y=50.0, page_number=0)
    session.editable_texts = [t]

    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    # Case 1: Only internal flags changed (_ghost_redacted, is_baked)
    t._ghost_redacted = True
    t.is_baked = True
    window.commit_pending_format_change()
    assert len(window.undo_manager.undo_stack) == 0

    # Case 2: Object is deleted (not in editable_texts)
    session.editable_texts = []
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)
    t.text = "Changed text"
    window.commit_pending_format_change()
    assert len(window.undo_manager.undo_stack) == 0


def test_single_word_styling_no_duplicate_command_and_exact_gap():
    """Verify styling a word inside paragraph causes no duplicate commands and maintains exact gap."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    text_str = "z yazı ve sözlük kodunu yazınız."
    t = EditableText(
        text=text_str,
        x=50.0,
        y=50.0,
        font_family="Liberation Sans",
        font_size=11.0,
        page_number=0
    )
    t.bbox = (50.0, 38.0, 207.0, 53.0)
    session.editable_texts = [t]

    # Simulate middle-click selection on word "yazı"
    start_c = 2
    end_c = 6
    window.selected_text = t
    window.selected_word = "yazı"
    window.selected_word_start_char = start_c
    window.selected_word_end_char = end_c
    window.word_selection_mode = True
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    # Apply bold style
    window._toggle_word_style(t, "bold")

    # Undo stack must contain exactly 1 composite command, NOT an EditObjectCommand on t
    assert len(window.undo_manager.undo_stack) == 1
    top_cmd = window.undo_manager.undo_stack[0]
    assert isinstance(top_cmd, CompositeCommand)

    # In editable_texts, original paragraph must be replaced by 3 spans
    assert len(session.editable_texts) == 3
    pre_s, mid_s, post_s = session.editable_texts
    assert pre_s.text == "z "
    assert mid_s.text == "yazı"
    assert post_s.text == " ve sözlük kodunu yazınız."

    assert mid_s.is_bold is True
    assert window.selected_text is mid_s

    # Sub-pixel gap check: post_span must start exactly at the right boundary of mid_span
    assert abs(post_s.bbox[0] - mid_s.bbox[2]) < 0.01


def test_single_word_color_change_via_on_text_format_changed():
    """Verify color change in word selection mode splits cleanly and sets color."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    text_str = "z yazı ve sözlük kodunu yazınız."
    t = EditableText(
        text=text_str,
        x=50.0,
        y=50.0,
        font_family="Liberation Sans",
        font_size=11.0,
        page_number=0
    )
    t.bbox = (50.0, 38.0, 207.0, 53.0)
    session.editable_texts = [t]

    start_c = 2
    end_c = 6
    window.selected_text = t
    window.selected_word = "yazı"
    window.selected_word_start_char = start_c
    window.selected_word_end_char = end_c
    window.word_selection_mode = True
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    # Mock format controls on window
    font_combo = MagicMock()
    font_combo.get_active.return_value = 0
    font_combo.get_active_iter.return_value = None
    font_combo.get_model.return_value = [["Liberation Sans"]]
    window.font_combo = font_combo

    font_size_spin = MagicMock()
    font_size_spin.get_value.return_value = 11.0
    window.font_size_spin = font_size_spin

    bold_btn = MagicMock()
    bold_btn.get_active.return_value = False
    window.bold_button = bold_btn

    italic_btn = MagicMock()
    italic_btn.get_active.return_value = False
    window.italic_button = italic_btn

    color_btn = MagicMock()
    red_rgba = Gdk.RGBA()
    red_rgba.red = 1.0
    red_rgba.green = 0.0
    red_rgba.blue = 0.0
    red_rgba.alpha = 1.0
    color_btn.get_rgba.return_value = red_rgba
    window.color_button = color_btn

    window.inline_editor_widget = None

    window.on_text_format_changed()

    # Verify exactly 1 composite command in undo history
    assert len(window.undo_manager.undo_stack) == 1
    assert isinstance(window.undo_manager.undo_stack[0], CompositeCommand)

    # Verify 3 spans, mid span is red
    assert len(session.editable_texts) == 3
    pre_s, mid_s, post_s = session.editable_texts
    assert mid_s.text == "yazı"
    assert mid_s.color == (1.0, 0.0, 0.0)
    assert abs(post_s.bbox[0] - mid_s.bbox[2]) < 0.01


def test_already_isolated_word_styling_shifts_subsequent_spans():
    """Verify that toggling style on an already-split word shifts subsequent spans on the line."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    # Line consists of pre, mid, post as separate objects on the same line
    pre_s = EditableText(text="z ", x=50.0, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    pre_s.bbox = (50.0, 38.0, 58.5, 53.0)
    pre_s.baseline = 50.0

    mid_s = EditableText(text="yazı", x=58.5, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    mid_s.bbox = (58.5, 38.0, 78.5, 53.0)
    mid_s.baseline = 50.0

    post_s = EditableText(text=" ve sözlük", x=78.5, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    post_s.bbox = (78.5, 38.0, 140.0, 53.0)
    post_s.baseline = 50.0

    session.editable_texts = [pre_s, mid_s, post_s]

    window.selected_text = mid_s
    window.selected_word = "yazı"
    window.selected_word_start_char = 0
    window.selected_word_end_char = len(mid_s.text)
    window.word_selection_mode = True
    window.pending_format_change_obj = mid_s
    window.before_format_change_state = copy.deepcopy(mid_s.__dict__)

    # Toggle bold on mid_s
    window._toggle_word_style(mid_s, "bold")

    assert mid_s.is_bold is True
    # mid_s width changed, post_s should be shifted by dx
    assert abs(post_s.bbox[0] - mid_s.bbox[2]) < 0.01

    # Undo must restore both mid_s and post_s positions
    window.undo_manager.undo()
    assert mid_s.is_bold is False
    assert abs(mid_s.bbox[2] - 78.5) < 0.01
    assert abs(post_s.bbox[0] - 78.5) < 0.01


def test_undo_redo_reversibility_single_word_style():
    """Verify full undo/redo cleanly reverses single-word styling without phantoms."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    text_str = "z yazı ve sözlük"
    t = EditableText(text=text_str, x=50.0, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    t.bbox = (50.0, 38.0, 150.0, 53.0)
    session.editable_texts = [t]

    window.selected_text = t
    window.selected_word = "yazı"
    window.selected_word_start_char = 2
    window.selected_word_end_char = 6
    window.word_selection_mode = True
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    window._toggle_word_style(t, "bold")
    assert len(session.editable_texts) == 3

    # Undo
    window.undo_manager.undo()
    assert len(session.editable_texts) == 1
    assert session.editable_texts[0].text == text_str
    assert session.editable_texts[0].is_bold is False

    # Redo
    window.undo_manager.redo()
    assert len(session.editable_texts) == 3
    assert session.editable_texts[1].text == "yazı"
    assert session.editable_texts[1].is_bold is True


def test_full_text_format_changed_no_unbound_local_error():
    """Verify that formatting an entire text object (word_selection_mode=False) does not raise UnboundLocalError."""
    doc = fitz.open()
    doc.new_page(width=400, height=100)
    window, session = create_mock_window(doc)

    t = EditableText(text="Complete line of text", x=50.0, y=50.0, font_family="Liberation Sans", font_size=11.0, page_number=0)
    t.bbox = (50.0, 38.0, 150.0, 53.0)
    session.editable_texts = [t]

    window.word_selection_mode = False
    window.selected_text = t
    window.pending_format_change_obj = t
    window.before_format_change_state = copy.deepcopy(t.__dict__)

    font_combo = MagicMock()
    font_combo.get_active.return_value = 0
    font_combo.get_active_iter.return_value = None
    font_combo.get_model.return_value = [["Liberation Sans"]]
    window.font_combo = font_combo

    font_size_spin = MagicMock()
    font_size_spin.get_value.return_value = 14.0
    window.font_size_spin = font_size_spin

    bold_btn = MagicMock()
    bold_btn.get_active.return_value = True
    window.bold_button = bold_btn

    italic_btn = MagicMock()
    italic_btn.get_active.return_value = False
    window.italic_button = italic_btn

    color_btn = MagicMock()
    blue_rgba = Gdk.RGBA()
    blue_rgba.red = 0.0
    blue_rgba.green = 0.0
    blue_rgba.blue = 1.0
    blue_rgba.alpha = 1.0
    color_btn.get_rgba.return_value = blue_rgba
    window.color_button = color_btn

    window.inline_editor_widget = None

    # This previously raised UnboundLocalError: cannot access local variable 'EditObjectCommand'
    window.on_text_format_changed()

    assert len(window.undo_manager.undo_stack) == 1
    assert isinstance(window.undo_manager.undo_stack[0], EditObjectCommand)
    assert t.font_size == 14.0
    assert t.is_bold is True
    assert t.color == (0.0, 0.0, 1.0)

