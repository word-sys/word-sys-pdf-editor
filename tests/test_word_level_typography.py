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
    type(window)._page_objects_cache = PdfEditorWindow._page_objects_cache
    type(window).form_fields = property(
        lambda self: self._active_session.form_fields if self._active_session else [],
        lambda self, val: setattr(self._active_session, 'form_fields', val) if self._active_session else None
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


def test_page_change_preserves_rotated_object_and_cache():
    """Verify that rotating an object on a page preserves its rotation, bbox, and undo history across page changes."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    window._stash_page_objects = PdfEditorWindow._stash_page_objects.__get__(window, PdfEditorWindow)
    window._restore_page_objects = PdfEditorWindow._restore_page_objects.__get__(window, PdfEditorWindow)
    window._load_page = PdfEditorWindow._load_page.__get__(window, PdfEditorWindow)
    window._switch_active_page = PdfEditorWindow._switch_active_page.__get__(window, PdfEditorWindow)
    window.continuous_scroll = False
    window.pdf_scroll = MagicMock()
    window._sync_thumbnail_selection = MagicMock()
    window._sync_window_title_and_subtitle = MagicMock()
    window._create_form_field_overlays = MagicMock()
    window._clear_form_field_overlays = MagicMock()
    window.hide_text_editor = MagicMock()
    window.commit_pending_format_change = MagicMock()

    t = EditableText(text="Mühendisliği", x=100.0, y=100.0, font_size=12.0, page_number=0)
    t.bbox = (100.0, 100.0, 200.0, 120.0)
    t.original_bbox = t.bbox
    session.editable_texts = [t]
    window._page_objects_cache[0] = {
        'texts': [t],
        'images': [],
        'shapes': [],
        'strokes': [],
        'form_fields': []
    }

    # Rotate object to 90 degrees
    from word_sys_pdf_editor.undo_manager import RotateObjectCommand
    cmd = RotateObjectCommand(window, t, 0.0, 90.0)
    cmd.execute()
    window.undo_manager.add_command(cmd)

    assert t.rotation == 90.0
    assert t.bbox == (100.0, 100.0, 200.0, 120.0) # Unrotated bbox is intact
    assert len(window.undo_manager.undo_stack) == 1

    # Navigate to page 1
    window._load_page(1)
    assert window.current_page_index == 1
    # Undo stack must NOT be cleared on page change!
    assert len(window.undo_manager.undo_stack) == 1

    # Navigate back to page 0
    window._load_page(0)
    assert window.current_page_index == 0
    assert len(window.undo_manager.undo_stack) == 1
    assert len(session.editable_texts) == 1

    restored_text = session.editable_texts[0]
    assert restored_text.text == "Mühendisliği"
    assert restored_text.rotation == 90.0
    # Must retain original unrotated bbox (width=100, height=20), NOT revert or double-rotate
    assert restored_text.bbox == (100.0, 100.0, 200.0, 120.0)

    # Undo rotation across pages
    window.undo_manager.undo()
    assert restored_text.rotation == 0.0


def test_page_change_preserves_multiparagraph_textbox():
    """Verify that a single multi-paragraph text box is not split into separate boxes on page change."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    window._stash_page_objects = PdfEditorWindow._stash_page_objects.__get__(window, PdfEditorWindow)
    window._restore_page_objects = PdfEditorWindow._restore_page_objects.__get__(window, PdfEditorWindow)
    window._load_page = PdfEditorWindow._load_page.__get__(window, PdfEditorWindow)
    window.continuous_scroll = False
    window.pdf_scroll = MagicMock()
    window._sync_thumbnail_selection = MagicMock()
    window._sync_window_title_and_subtitle = MagicMock()
    window._create_form_field_overlays = MagicMock()
    window._clear_form_field_overlays = MagicMock()
    window.hide_text_editor = MagicMock()
    window.commit_pending_format_change = MagicMock()

    multi_text = "Paragraph 1: Intro\nParagraph 2: Body\nParagraph 3: Discussion\nParagraph 4: Conclusion"
    t = EditableText(text=multi_text, x=50.0, y=50.0, font_size=12.0, page_number=0)
    t.bbox = (50.0, 50.0, 350.0, 200.0)
    session.editable_texts = [t]
    window._page_objects_cache[0] = {
        'texts': [t],
        'images': [],
        'shapes': [],
        'strokes': [],
        'form_fields': []
    }

    # Switch to page 1
    window._load_page(1)
    assert window.current_page_index == 1

    # Switch back to page 0
    window._load_page(0)
    assert window.current_page_index == 0

    # Must still be exactly ONE EditableText object with all 4 paragraphs
    assert len(session.editable_texts) == 1
    assert session.editable_texts[0].text == multi_text


def test_extract_editable_text_unrotates_rotated_pdf_text():
    """Verify extract_editable_text accurately unrotates bounding box and char boxes for rotated PDF text."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    unrot_rect = fitz.Rect(100, 100, 250, 120)
    cx = (unrot_rect.x0 + unrot_rect.x1) / 2.0
    cy = (unrot_rect.y0 + unrot_rect.y1) / 2.0
    rot = 90.0
    morph = (fitz.Point(cx, cy), fitz.Matrix(-rot))
    page.insert_text(fitz.Point(100, 115), "Muhendisligi", fontsize=12, morph=morph)

    texts, err = pdf_handler.extract_editable_text(doc, 0)
    assert err is None
    assert len(texts) == 1

    t = texts[0]
    assert t.text == "Muhendisligi"
    assert t.rotation == 90.0

    # Unrotated width must be horizontal (width > height), NOT vertical (height > width)
    w = t.bbox[2] - t.bbox[0]
    h = t.bbox[3] - t.bbox[1]
    assert w > h
    assert 50.0 < w < 100.0
    assert 10.0 < h < 25.0


def test_multipage_undo_redo_automatic_navigation():
    """Verify that undoing/redoing commands on different pages automatically navigates to that page."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    window._stash_page_objects = PdfEditorWindow._stash_page_objects.__get__(window, PdfEditorWindow)
    window._restore_page_objects = PdfEditorWindow._restore_page_objects.__get__(window, PdfEditorWindow)
    window._load_page = PdfEditorWindow._load_page.__get__(window, PdfEditorWindow)
    window.continuous_scroll = False
    window.pdf_scroll = MagicMock()
    window._sync_thumbnail_selection = MagicMock()
    window._sync_window_title_and_subtitle = MagicMock()
    window._create_form_field_overlays = MagicMock()
    window._clear_form_field_overlays = MagicMock()
    window.hide_text_editor = MagicMock()
    window.commit_pending_format_change = MagicMock()

    from word_sys_pdf_editor.undo_manager import RotateObjectCommand

    # Page 0: object t0 rotated to 45 deg
    t0 = EditableText(text="Page0Text", x=100.0, y=100.0, font_size=12.0, page_number=0)
    t0.bbox = (100.0, 100.0, 200.0, 120.0)
    session.editable_texts = [t0]
    window._page_objects_cache[0] = {'texts': [t0], 'images': [], 'shapes': [], 'strokes': [], 'form_fields': []}

    cmd0 = RotateObjectCommand(window, t0, 0.0, 45.0)
    cmd0.execute()
    window.undo_manager.add_command(cmd0)
    assert t0.rotation == 45.0

    # Switch to Page 1: object t1 rotated to 90 deg
    window._load_page(1)
    assert window.current_page_index == 1

    t1 = EditableText(text="Page1Text", x=50.0, y=50.0, font_size=12.0, page_number=1)
    t1.bbox = (50.0, 50.0, 150.0, 70.0)
    session.editable_texts = [t1]
    window._page_objects_cache[1] = {'texts': [t1], 'images': [], 'shapes': [], 'strokes': [], 'form_fields': []}

    cmd1 = RotateObjectCommand(window, t1, 0.0, 90.0)
    cmd1.execute()
    window.undo_manager.add_command(cmd1)
    assert t1.rotation == 90.0

    # Undo 1: Reverts t1 on page 1
    window.undo_manager.undo()
    assert window.current_page_index == 1
    assert t1.rotation == 0.0

    # Undo 2: Must automatically navigate to page 0 and revert t0
    window.undo_manager.undo()
    assert window.current_page_index == 0
    assert t0.rotation == 0.0

    # Redo 1: Must re-apply rotation on page 0
    window.undo_manager.redo()
    assert window.current_page_index == 0
    assert t0.rotation == 45.0

    # Redo 2: Must automatically navigate to page 1 and re-apply rotation on page 1
    window.undo_manager.redo()
    assert window.current_page_index == 1
    assert t1.rotation == 90.0


def test_rotated_shape_persists_across_page_change():
    """Verify that an EditableShape with rotation retains its angle and bounds when switching pages."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    window, session = create_mock_window(doc)

    window._stash_page_objects = PdfEditorWindow._stash_page_objects.__get__(window, PdfEditorWindow)
    window._restore_page_objects = PdfEditorWindow._restore_page_objects.__get__(window, PdfEditorWindow)
    window._load_page = PdfEditorWindow._load_page.__get__(window, PdfEditorWindow)
    window.continuous_scroll = False
    window.pdf_scroll = MagicMock()
    window._sync_thumbnail_selection = MagicMock()
    window._sync_window_title_and_subtitle = MagicMock()
    window._create_form_field_overlays = MagicMock()
    window._clear_form_field_overlays = MagicMock()
    window.hide_text_editor = MagicMock()
    window.commit_pending_format_change = MagicMock()

    from word_sys_pdf_editor.models import EditableShape
    from word_sys_pdf_editor.undo_manager import RotateObjectCommand

    shape = EditableShape(bbox=(100.0, 100.0, 200.0, 200.0), page_number=0, shape_type=EditableShape.SHAPE_RECTANGLE)
    shape.original_bbox = shape.bbox
    session.editable_shapes = [shape]
    window._page_objects_cache[0] = {'texts': [], 'images': [], 'shapes': [shape], 'strokes': [], 'form_fields': []}

    cmd = RotateObjectCommand(window, shape, 0.0, 45.0)
    cmd.execute()
    window.undo_manager.add_command(cmd)
    assert shape.rotation == 45.0

    # Switch to page 1
    window._load_page(1)
    assert window.current_page_index == 1

    # Switch back to page 0
    window._load_page(0)
    assert window.current_page_index == 0

    assert len(session.editable_shapes) == 1
    restored_shape = session.editable_shapes[0]
    assert restored_shape.rotation == 45.0
    assert restored_shape.bbox == (100.0, 100.0, 200.0, 200.0)


def test_multipage_rotate_page_change_undo_redo_and_save(tmp_path):
    """End-to-end test: rotate on page 0, navigate pages, undo/redo across pages, save, and reopen."""
    orig_path = str(tmp_path / "orig.pdf")
    saved_path = str(tmp_path / "saved.pdf")

    doc = fitz.open()
    p0 = doc.new_page(width=500, height=400)
    p0.insert_text(fitz.Point(100, 100), "Hello Page Zero", fontsize=14)
    p1 = doc.new_page(width=500, height=400)
    p1.insert_text(fitz.Point(100, 100), "Hello Page One", fontsize=14)
    doc.save(orig_path)
    doc.close()

    win = PdfEditorWindow()
    loaded, err = pdf_handler.load_pdf_document(orig_path)
    win._finish_loading(loaded, None, orig_path, 0, win._active_session)

    assert len(win.editable_texts) == 1
    obj = win.editable_texts[0]
    assert obj.rotation == 0.0

    from word_sys_pdf_editor.undo_manager import RotateObjectCommand
    cmd = RotateObjectCommand(win, obj, 0.0, 90.0)
    cmd.execute()
    win.undo_manager.add_command(cmd)
    assert obj.rotation == 90.0

    # Switch to page 1
    win._load_page(1)
    assert win.current_page_index == 1
    assert len(win.editable_texts) == 1
    assert win.editable_texts[0].text == "Hello Page One"

    # Switch back to page 0
    win._load_page(0)
    assert win.current_page_index == 0
    assert len(win.editable_texts) == 1
    restored_obj = win.editable_texts[0]
    assert restored_obj.rotation == 90.0

    # Switch to page 1 and undo
    win._load_page(1)
    assert win.current_page_index == 1
    win.undo_manager.undo()
    assert win.current_page_index == 0
    assert win.editable_texts[0].rotation == 0.0

    # Redo
    win.undo_manager.redo()
    assert win.current_page_index == 0
    assert win.editable_texts[0].rotation == 90.0

    # Save document
    win.save_document(saved_path)

    # Reopen saved document fresh
    win2 = PdfEditorWindow()
    loaded2, err2 = pdf_handler.load_pdf_document(saved_path)
    win2._finish_loading(loaded2, None, saved_path, 0, win2._active_session)

    assert len(win2.editable_texts) == 1
    reopened_obj = win2.editable_texts[0]
    assert reopened_obj.text == "Hello Page Zero"
    assert reopened_obj.rotation == 90.0






