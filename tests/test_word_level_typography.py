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
    window._isolate_selected_word_span = PdfEditorWindow._isolate_selected_word_span.__get__(window, PdfEditorWindow)
    window.on_rotate_object_cw_clicked = PdfEditorWindow.on_rotate_object_cw_clicked.__get__(window, PdfEditorWindow)
    window.on_object_rotation_spin_changed = PdfEditorWindow.on_object_rotation_spin_changed.__get__(window, PdfEditorWindow)
    window._update_rotation_controls = MagicMock()
    window._update_text_format_controls = MagicMock()

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


def test_moved_text_single_word_hit_test_and_bbox():
    """Verify that moving a text object dynamically synchronizes char_boxes and word selection bbox."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    t = EditableText(text="Hello World", x=50.0, y=50.0, font_size=12.0, page_number=0)
    # Populate char_boxes at original location [50..120, 50..62]
    cbs = []
    cx = 50.0
    for idx, char in enumerate("Hello World"):
        w = 4.0 if char == ' ' else 7.0
        cbs.append({
            "char": char,
            "bbox": (cx, 50.0, cx + w, 62.0),
            "origin": (cx, 60.0),
            "index": idx
        })
        cx += w
    t.char_boxes = cbs
    t.bbox = (50.0, 50.0, cx, 62.0)
    session.editable_texts = [t]

    # Move text object by (100, 150)
    new_bbox = (150.0, 200.0, cx + 100.0, 212.0)
    t.bbox = new_bbox
    t.x, t.y = new_bbox[0], new_bbox[1]

    # Hit test at old location must fail, hit test at new location must succeed
    assert t.hit_test_char(55.0, 55.0) is None
    hit = t.hit_test_char(155.0, 205.0)
    assert hit is not None
    assert hit["char"] == "H"

    # Select word "World" (indices 6 to 11)
    window.selected_text = t
    window.selected_word = "World"
    window.selected_word_start_char = 6
    window.selected_word_end_char = 11
    window.word_selection_mode = True

    w_bbox = window.get_selected_word_bbox()
    assert w_bbox is not None
    # Word bbox must be at new moved location [>= 150.0, >= 200.0]
    assert w_bbox[0] >= 150.0
    assert w_bbox[1] >= 200.0
    assert w_bbox[3] <= 213.0

    # Split at range must produce spans at the new moved coordinates
    spans = t.split_at_range(6, 11)
    assert len(spans) == 2
    pre_span, mid_span = spans[0], spans[1]
    assert pre_span.bbox[0] == pytest.approx(150.0, abs=0.1)
    assert mid_span.bbox[1] == pytest.approx(200.0, abs=0.1)


def test_rotated_text_single_word_split_alignment():
    """Verify that splitting a rotated text object produces spans that align on the exact visual line."""
    import math
    doc = fitz.open()
    doc.new_page(width=500, height=500)

    for rot in [90.0, 180.0, 270.0]:
        t = EditableText(text="Rotated Paragraph Text", x=100.0, y=100.0, font_size=12.0, rotation=rot, page_number=0)
        cbs = []
        cx = 100.0
        for idx, char in enumerate("Rotated Paragraph Text"):
            w = 4.0 if char == ' ' else 7.0
            cbs.append({
                "char": char,
                "bbox": (cx, 100.0, cx + w, 114.0),
                "origin": (cx, 111.0),
                "index": idx
            })
            cx += w
        t.char_boxes = cbs
        t.bbox = (100.0, 100.0, cx, 114.0)

        p_cx = (t.bbox[0] + t.bbox[2]) / 2.0
        p_cy = (t.bbox[1] + t.bbox[3]) / 2.0

        # Split "Paragraph" (index 8 to 17)
        spans = t.split_at_range(8, 17, compensate_rotation=True)
        assert len(spans) == 3
        pre, mid, post = spans[0], spans[1], spans[2]
        assert pre.text == "Rotated "
        assert mid.text == "Paragraph"
        assert post.text == " Text"

        # Check visual position of characters in each span vs parent
        for span, start_idx in [(pre, 0), (mid, 8), (post, 17)]:
            s_cx = (span.bbox[0] + span.bbox[2]) / 2.0
            s_cy = (span.bbox[1] + span.bbox[3]) / 2.0
            for cb in span.char_boxes:
                char_idx = start_idx + cb["index"]
                orig_cb = t.char_boxes[char_idx]

                # Visual pos in parent
                pt_p = fitz.Point((orig_cb["bbox"][0] + orig_cb["bbox"][2]) / 2.0, (orig_cb["bbox"][1] + orig_cb["bbox"][3]) / 2.0)
                vis_p = (pt_p - fitz.Point(p_cx, p_cy)) * fitz.Matrix(rot) + fitz.Point(p_cx, p_cy)

                # Visual pos in span
                pt_s = fitz.Point((cb["bbox"][0] + cb["bbox"][2]) / 2.0, (cb["bbox"][1] + cb["bbox"][3]) / 2.0)
                vis_s = (pt_s - fitz.Point(s_cx, s_cy)) * fitz.Matrix(rot) + fitz.Point(s_cx, s_cy)

                diff = abs(vis_p.x - vis_s.x) + abs(vis_p.y - vis_s.y)
                assert diff < 0.05, f"Rot {rot} char {orig_cb['char']} misaligned by {diff} pt"


def test_rotation_handle_stalk_detection_for_editable_text():
    """Verify that _find_resize_handle_at_pos detects the rotation handle stalk for EditableText."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    t = EditableText(text="Hello", x=100.0, y=100.0, font_size=12.0, page_number=0)
    t.bbox = (100.0, 100.0, 150.0, 115.0)

    # Bind _find_resize_handle_at_pos
    window._find_resize_handle_at_pos = PdfEditorWindow._find_resize_handle_at_pos.__get__(window, PdfEditorWindow)
    window._visual_to_unrotated_page_coords = PdfEditorWindow._visual_to_unrotated_page_coords.__get__(window, PdfEditorWindow)
    window.zoom_level = 1.0
    window.current_pdf_page_width = 500
    window.current_pdf_page_height = 500
    window.pdf_view.get_allocated_width.return_value = 500
    window.pdf_view.get_allocated_height.return_value = 500

    # Rotation stalk is centered at x = (100 + 150) / 2 = 125, y = 100 - padding - 22 = 75
    # Hit testing at (125, 75)
    handle = window._find_resize_handle_at_pos(125.0, 75.0, t)
    assert handle == "rotate"


def test_single_word_rotation_isolates_only_that_word():
    """Verify that rotating a selected word isolates it and rotates ONLY that word, leaving the paragraph untouched."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    t = EditableText(text="KONU: ODEV PART-2", x=50.0, y=50.0, font_size=12.0, page_number=0)
    # Populate char boxes
    cbs = []
    cx = 50.0
    for idx, c in enumerate("KONU: ODEV PART-2"):
        w = 4.0 if c == ' ' else 7.0
        cbs.append({
            "char": c,
            "bbox": (cx, 50.0, cx + w, 64.0),
            "origin": (cx, 61.0),
            "index": idx
        })
        cx += w
    t.char_boxes = cbs
    t.bbox = (50.0, 50.0, cx, 64.0)
    session.editable_texts = [t]

    # Middle click selects "ODEV" (start_char=6, end_char=10)
    window.selected_text = t
    window.selected_word = "ODEV"
    window.selected_word_start_char = 6
    window.selected_word_end_char = 10
    window.word_selection_mode = True

    # User clicks rotate 90 degrees CW
    window.on_rotate_object_cw_clicked()

    # Original paragraph should be split into 3 spans: pre, mid, post
    assert len(session.editable_texts) == 3
    pre, mid, post = session.editable_texts
    assert pre.text == "KONU: "
    assert mid.text == "ODEV"
    assert post.text == " PART-2"

    # Crucial assertion: ONLY mid ("ODEV") is rotated 90 degrees!
    assert mid.rotation == 90.0
    # pre and post remain horizontal at 0 degrees!
    assert pre.rotation == 0.0
    assert post.rotation == 0.0

    # Undo must restore original un-rotated, un-split paragraph
    window.undo_manager.undo() # undoes rotation
    window.undo_manager.undo() # undoes split
    assert len(session.editable_texts) == 1
    assert session.editable_texts[0].text == "KONU: ODEV PART-2"
    assert session.editable_texts[0].rotation == 0.0


def test_single_word_selection_has_its_own_rotation_stalk():
    """Verify that in word_selection_mode, the rotation stalk handle is located right on the word's box."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    t = EditableText(text="KONU: ODEV PART-2", x=50.0, y=100.0, font_size=12.0, page_number=0)
    cbs = []
    cx = 50.0
    for idx, c in enumerate("KONU: ODEV PART-2"):
        w = 4.0 if c == ' ' else 8.0
        cbs.append({
            "char": c,
            "bbox": (cx, 100.0, cx + w, 115.0),
            "origin": (cx, 112.0),
            "index": idx
        })
        cx += w
    t.char_boxes = cbs
    t.bbox = (50.0, 100.0, cx, 115.0)

    # Word "ODEV" is indices 6 to 10:
    # 6 chars ("KONU: ") = 5*8 + 4 = 44 -> x from 94 to 94 + 4*8 = 126
    # Word center is ~110.0
    window.selected_text = t
    window.selected_word = "ODEV"
    window.selected_word_start_char = 6
    window.selected_word_end_char = 10
    window.word_selection_mode = True

    w_bbox = window.get_selected_word_bbox()
    assert w_bbox is not None
    word_cx = (w_bbox[0] + w_bbox[2]) / 2.0
    word_stalk_y = w_bbox[1] - 3.0 - 22.0 # rect_y - stalk_len

    window._find_resize_handle_at_pos = PdfEditorWindow._find_resize_handle_at_pos.__get__(window, PdfEditorWindow)
    window._visual_to_unrotated_page_coords = PdfEditorWindow._visual_to_unrotated_page_coords.__get__(window, PdfEditorWindow)
    window.zoom_level = 1.0
    window.current_pdf_page_width = 500
    window.current_pdf_page_height = 500
    window.pdf_view.get_allocated_width.return_value = 500
    window.pdf_view.get_allocated_height.return_value = 500

    # Test rotation handle at the word's stalk tip
    handle = window._find_resize_handle_at_pos(word_cx, word_stalk_y, t)
    assert handle == "rotate"

    # Far away from the word (e.g. above "KONU:") should NOT detect the word's rotation stalk
    handle_away = window._find_resize_handle_at_pos(60.0, word_stalk_y, t)
    assert handle_away is None



