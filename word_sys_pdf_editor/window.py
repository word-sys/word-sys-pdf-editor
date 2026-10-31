import copy
import collections
from typing import Optional, List, Dict, Tuple, Any
from .undo_manager import (
    UndoManager, EditObjectCommand, AddObjectCommand, DeleteObjectCommand,
    RotatePageCommand, RotateObjectCommand, EditFormFieldCommand, AddFormFieldCommand,
    DeleteFormFieldCommand, MoveResizeFormFieldCommand, EditFormFieldChoicesCommand,
    ReplaceImageCommand, CalibrateScaleCommand, AddMeasurementCommand, DeleteMeasurementCommand,
    AddStickyNoteCommand, DeleteStickyNoteCommand, EditStickyNoteCommand, MoveStickyNoteCommand,
    ReorderObjectCommand, CompositeCommand, EmbedOCRTextCommand
)
from .i18n import _, get_language, set_language, get_supported_languages, get_setting, set_setting

import gi
import os
import gc
import time
from pathlib import Path
import cairo
import threading
import math
import re
try:
    import pymupdf as fitz
except ImportError:
    import fitz

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GLib, Adw, Gdk, GdkPixbuf, Pango, GObject, PangoCairo, Graphene

from . import constants
from . import pdf_handler
from . import print_handler
from .welcome_view import WelcomeView
from .models import (
    PdfPage, EditableText, BASE14_FALLBACK_MAP, EditableImage, EditableShape, EditableStroke,
    DocumentSession, AcroFormField, ScaleCalibration, PRESET_SCALES, MeasurementObject,
    StickyNoteObject, PatchObject, RedactionMark, measure_text_width, snapshot_object_state,
    simplify_stroke_points
)
from .ui_components import (
    PageThumbnailFactory, show_error_dialog, show_info_dialog, show_confirm_dialog,
    show_save_changes_dialog, show_open_file_dialog, show_save_file_dialog,
    SymbolsPopover, render_emoji_to_png_bytes, show_new_document_dialog
)
from .quick_guide_dialog import QuickGuideDialog
from .annotations_sidebar import AnnotationsSidebar, AnnotationListItem
from . import utils
from .utils import point_to_segment_distance, point_in_polygon
from .stamp_manager import (
    StampLibrary, CustomStamp, StampManagerDialog, StampPopover,
    StampPasswordDialog, StampVerificationDialog
)
from .search_engine import DocumentSearchEngine, SearchMatch
from .protect_dialog import ProtectDocumentDialog, DocumentUnlockDialog
from .hardware import is_eco_mode_enabled, set_eco_mode_enabled, detect_hardware_spec


class UniformPageOffsets(list):
    """Virtual zero-allocation sequence of page offset tuples for uniform-dimension documents."""
    def __init__(self, count: int, gap: float, pw: float, ph: float):
        super().__init__()
        self._count = int(count)
        self.gap = float(gap)
        self.pw = float(pw)
        self.ph = float(ph)
        self.stride = self.ph + self.gap

    def __len__(self) -> int:
        return self._count

    def __bool__(self) -> bool:
        return self._count > 0

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return [self[i] for i in range(*idx.indices(self._count))]
        if isinstance(idx, int):
            if idx < 0:
                idx += self._count
            if not (0 <= idx < self._count):
                raise IndexError("list index out of range")
            return (0.0, self.gap + idx * self.stride, self.pw, self.ph)
        raise TypeError(f"list indices must be integers or slices, not {type(idx).__name__}")

    def __iter__(self):
        for i in range(self._count):
            yield (0.0, self.gap + i * self.stride, self.pw, self.ph)

    def __eq__(self, other):
        if not hasattr(other, "__len__") or len(self) != len(other):
            return False
        for a, b in zip(self, other):
            if a != b:
                return False
        return True

    def __contains__(self, item) -> bool:
        if not isinstance(item, (tuple, list)) or len(item) != 4:
            return False
        if abs(item[0] - 0.0) > 0.001 or abs(item[2] - self.pw) > 0.001 or abs(item[3] - self.ph) > 0.001:
            return False
        idx_f = (item[1] - self.gap) / max(self.stride, 0.001)
        idx_round = round(idx_f)
        if 0 <= idx_round < self._count and abs(idx_f - idx_round) < 0.001:
            return True
        return False

    def copy(self):
        return list(self)


class VirtualDrawingArea(Gtk.DrawingArea):
    """Sub-viewport virtualized DrawingArea for massive documents and extreme zoom levels.

    Instead of allocating an unbounded Cairo surface for the entire canvas height
    (which exhausts GPU textures and triggers GSK/Cairo aborts on large multi-page PDFs),
    VirtualDrawingArea dynamically clips snapshot Cairo bounds to the visible viewport
    rectangle queried from get_viewport_rect_cb().
    """
    __gtype_name__ = 'VirtualDrawingArea'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.get_viewport_rect_cb = None
        self._user_draw_func = None
        self.is_virtualization_required_cb = None
        self.is_clipping_active = False

    def set_draw_func(self, func, user_data=None):
        """Set the draw function called during snapshotting."""
        self._user_draw_func = func

    def do_snapshot(self, snapshot):
        """Render virtualized snapshot clipped strictly to the active viewport when required."""
        w = self.get_width()
        h = self.get_height()
        if w <= 0 or h <= 0:
            return

        needs_clip = False
        if self.is_virtualization_required_cb is not None:
            try:
                needs_clip = bool(self.is_virtualization_required_cb(w, h))
            except Exception:
                needs_clip = (w > 8192 or h > 8192)
        elif self.get_viewport_rect_cb is not None:
            needs_clip = (w > 8192 or h > 8192)

        self.is_clipping_active = needs_clip

        if needs_clip and self.get_viewport_rect_cb:
            try:
                vx, vy, vw, vh = self.get_viewport_rect_cb()
                margin = 80.0
                clip_x = max(0.0, float(vx) - margin)
                clip_y = max(0.0, float(vy) - margin)
                clip_w = max(1.0, min(float(w) - clip_x, float(vw) + margin * 2.0))
                clip_h = max(1.0, min(float(h) - clip_y, float(vh) + margin * 2.0))
                rect = Graphene.Rect().init(clip_x, clip_y, clip_w, clip_h)
            except Exception:
                rect = Graphene.Rect().init(0, 0, w, h)
        else:
            rect = Graphene.Rect().init(0, 0, w, h)

        cr = snapshot.append_cairo(rect)
        if cr is not None and self._user_draw_func:
            try:
                self._user_draw_func(self, cr, w, h)
            except Exception as e:
                import traceback
                traceback.print_exc()


class ScrollVelocityTracker:
    """Tracks scroll velocity and direction to predictively prefetch upcoming pages."""

    DIRECTION_NONE = 0
    DIRECTION_DOWN = 1
    DIRECTION_UP = -1

    def __init__(self, sample_window_sec: float = 0.25):
        self.sample_window_sec = float(sample_window_sec)
        self._samples: collections.deque = collections.deque(maxlen=10)
        self._last_velocity: float = 0.0
        self._last_direction: int = self.DIRECTION_NONE

    def record_scroll(self, y: float, now: Optional[float] = None) -> Tuple[float, int]:
        """Record scroll position and compute smoothed velocity (px/sec) and direction.

        Returns: (velocity_px_per_sec, direction)
        direction is:
          1  (downwards / increasing y)
          -1 (upwards / decreasing y)
          0  (stationary / stopped)
        """
        if now is None:
            now = time.perf_counter()

        self._samples.append((now, float(y)))

        cutoff = now - self.sample_window_sec
        while len(self._samples) > 2 and self._samples[0][0] < cutoff:
            self._samples.popleft()

        if len(self._samples) < 2:
            return (self._last_velocity, self._last_direction)

        t_first, y_first = self._samples[0]
        t_last, y_last = self._samples[-1]
        dt = t_last - t_first
        if dt < 0.001:
            return (self._last_velocity, self._last_direction)

        raw_v = (y_last - y_first) / dt
        if abs(self._last_velocity) < 0.001:
            smoothed_v = raw_v
        else:
            smoothed_v = 0.7 * raw_v + 0.3 * self._last_velocity

        self._last_velocity = smoothed_v

        # Thresholds: 60 px/s threshold for directional motion
        if smoothed_v > 60.0:
            self._last_direction = self.DIRECTION_DOWN
        elif smoothed_v < -60.0:
            self._last_direction = self.DIRECTION_UP
        else:
            self._last_direction = self.DIRECTION_NONE

        return (self._last_velocity, self._last_direction)

    def reset(self):
        """Reset velocity tracking when scrolling stops or settles."""
        self._samples.clear()
        self._last_velocity = 0.0
        self._last_direction = self.DIRECTION_NONE

    @property
    def velocity(self) -> float:
        """Return latest smoothed velocity in pixels per second."""
        return self._last_velocity

    @property
    def direction(self) -> int:
        """Return latest scroll direction (DIRECTION_DOWN=1, DIRECTION_UP=-1, DIRECTION_NONE=0)."""
        return self._last_direction

    def get_prefetch_page_indices(
        self,
        visible_pages: List[int],
        total_pages: int,
        is_eco_mode: bool = False
    ) -> List[int]:
        """Compute directional lookahead pages to prefetch based on current velocity and direction.

        - Downwards rapid scroll: prefetch ahead [+1, +2, +3], zero behind.
        - Upwards rapid scroll: prefetch ahead [-1, -2, -3], zero behind.
        - Moderate scroll: directionally biased ahead, single page behind.
        - Stationary / decelerated: balanced [-1, +1].
        """
        if not visible_pages or total_pages <= 0:
            return []

        min_p = min(visible_pages)
        max_p = max(visible_pages)
        abs_v = abs(self._last_velocity)
        candidates: List[int] = []

        if self._last_direction == self.DIRECTION_DOWN:
            if is_eco_mode:
                candidates = [max_p + 1]
            elif abs_v > 400.0:
                # Rapid downwards scroll: aggressive lookahead ahead, zero behind
                candidates = [max_p + 1, max_p + 2, max_p + 3]
            else:
                # Moderate downwards scroll: biased ahead, 1 behind
                candidates = [max_p + 1, max_p + 2, min_p - 1]
        elif self._last_direction == self.DIRECTION_UP:
            if is_eco_mode:
                candidates = [min_p - 1]
            elif abs_v > 400.0:
                # Rapid upwards scroll: aggressive lookahead ahead, zero behind
                candidates = [min_p - 1, min_p - 2, min_p - 3]
            else:
                # Moderate upwards scroll: biased ahead, 1 behind
                candidates = [min_p - 1, min_p - 2, max_p + 1]
        else:
            # Stationary or decelerated to a stop: balanced lookahead
            if is_eco_mode:
                candidates = [max_p + 1]
            else:
                candidates = [min_p - 1, max_p + 1]

        vis_set = set(visible_pages)
        valid: List[int] = []
        for p in candidates:
            if 0 <= p < total_pages and p not in vis_set and p not in valid:
                valid.append(p)
        return valid


class StickyNotePopover(Gtk.Popover):
    """Floating comment and sticky note editor popover."""
    def __init__(self, editor_window, note, on_close_callback=None):
        super().__init__(autohide=True, has_arrow=True)
        self.editor_window = editor_window
        self.note = note
        self.on_close_callback = on_close_callback
        self.set_parent(editor_window.pdf_view)

        # Snapshot for undo tracking
        self.initial_state = {
            "content": note.content,
            "author": note.author,
            "color": note.color,
            "icon_type": note.icon_type,
            "modified_at": note.modified_at,
        }
        self.is_committing = False

        self._build_ui()
        self.connect("closed", self._on_popover_closed)

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main_box.set_margin_top(8)
        main_box.set_margin_bottom(8)
        main_box.set_margin_start(8)
        main_box.set_margin_end(8)
        main_box.set_size_request(280, -1)

        # 1. Header Row
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        icon_options = [
            ("Comment", _("note_icon_comment")),
            ("Note", _("note_icon_note")),
            ("Help", _("note_icon_help")),
            ("Key", _("note_icon_key")),
            ("NewParagraph", _("note_icon_paragraph")),
        ]
        self.icon_keys = [opt[0] for opt in icon_options]
        icon_labels = [opt[1] for opt in icon_options]

        self.icon_dropdown = Gtk.DropDown.new_from_strings(icon_labels)
        current_icon = getattr(self.note, 'icon_type', 'Comment')
        if current_icon in self.icon_keys:
            self.icon_dropdown.set_selected(self.icon_keys.index(current_icon))
        else:
            self.icon_dropdown.set_selected(0)
        self.icon_dropdown.connect("notify::selected", self._on_icon_changed)
        header_box.append(self.icon_dropdown)

        # Color palette chips
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        colors = [
            ("yellow", (1.0, 0.86, 0.24)),
            ("blue", (0.25, 0.60, 1.0)),
            ("green", (0.30, 0.82, 0.45)),
            ("pink", (1.0, 0.42, 0.62)),
            ("purple", (0.68, 0.45, 0.98)),
        ]
        for name, rgb in colors:
            btn = Gtk.Button()
            btn.add_css_class("flat")
            provider = Gtk.CssProvider()
            css = f"button {{ background-color: rgb({int(rgb[0]*255)}, {int(rgb[1]*255)}, {int(rgb[2]*255)}); min-width: 18px; min-height: 18px; border-radius: 9px; border: 1px solid rgba(0,0,0,0.3); padding: 0; margin: 1px; }}"
            provider.load_from_data(css.encode('utf-8'))
            btn.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            btn.connect("clicked", lambda b, c=rgb: self._on_color_selected(c))
            color_box.append(btn)
        header_box.append(color_box)

        spacer = Gtk.Box(hexpand=True)
        header_box.append(spacer)

        del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        del_btn.add_css_class("flat")
        del_btn.set_tooltip_text(_("btn_delete_note"))
        del_btn.connect("clicked", self._on_delete_clicked)
        header_box.append(del_btn)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.connect("clicked", lambda b: self.popdown())
        header_box.append(close_btn)

        main_box.append(header_box)

        # 2. Metadata Row
        meta_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.author_entry = Gtk.Entry()
        self.author_entry.set_placeholder_text(_("sticky_note_author_placeholder"))
        self.author_entry.set_text(self.note.author or "")
        self.author_entry.set_hexpand(True)
        self.author_entry.connect("changed", self._on_author_changed)
        meta_box.append(self.author_entry)

        date_str = self.note.created_at[:16] if getattr(self.note, 'created_at', None) else ""
        self.date_label = Gtk.Label(label=date_str)
        self.date_label.add_css_class("dim-label")
        meta_box.append(self.date_label)
        main_box.append(meta_box)

        # 3. Content Area
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(100)
        scroller.set_max_content_height(180)
        scroller.set_propagate_natural_height(True)

        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.buffer = self.text_view.get_buffer()
        self.buffer.set_text(self.note.content or "")
        self.buffer.set_enable_undo(True)
        self.buffer.connect("changed", self._on_text_changed)
        scroller.set_child(self.text_view)
        main_box.append(scroller)

        self.set_child(main_box)

    def _on_icon_changed(self, dropdown, param):
        idx = dropdown.get_selected()
        if 0 <= idx < len(self.icon_keys):
            self.note.icon_type = self.icon_keys[idx]
            self.note.modified = True
            if self.editor_window:
                self.editor_window.document_modified = True
                self.editor_window.pdf_view.queue_draw()

    def _on_color_selected(self, color_tuple):
        self.note.color = color_tuple
        self.note.modified = True
        if self.editor_window:
            self.editor_window.document_modified = True
            self.editor_window.pdf_view.queue_draw()

    def _on_author_changed(self, entry):
        self.note.author = entry.get_text()
        self.note.modified = True
        if self.editor_window:
            self.editor_window.document_modified = True

    def _on_text_changed(self, text_buffer):
        start = text_buffer.get_start_iter()
        end = text_buffer.get_end_iter()
        new_text = text_buffer.get_text(start, end, True)
        self.note.content = new_text
        self.note.modified = True
        import datetime
        self.note.modified_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        if self.editor_window:
            self.editor_window.document_modified = True
            self.editor_window.pdf_view.queue_draw()

    def _on_delete_clicked(self, btn):
        self.popdown()
        if self.editor_window:
            self.editor_window.delete_sticky_note(self.note)

    def _on_popover_closed(self, popover):
        if self.is_committing:
            return
        self.is_committing = True
        current_state = {
            "content": self.note.content,
            "author": self.note.author,
            "color": self.note.color,
            "icon_type": self.note.icon_type,
            "modified_at": self.note.modified_at,
        }
        if current_state != self.initial_state and self.editor_window:
            from .undo_manager import EditStickyNoteCommand
            cmd = EditStickyNoteCommand(self.editor_window, self.note, self.initial_state, current_state)
            if self.editor_window.undo_manager:
                self.editor_window.undo_manager.record(cmd)
            if hasattr(self.editor_window, 'annotations_sidebar'):
                self.editor_window.annotations_sidebar.refresh()
        if self.on_close_callback:
            self.on_close_callback()


class RedactionInspectorPopover(Gtk.Popover):
    """Floating inspector popover for editing staged redaction mark properties."""
    PRESET_CODES = [
        "[REDACTED]",
        "CONFIDENTIAL",
        "FOIA Exemption (b)(4)",
        "FOIA Exemption (b)(6)",
        "FOIA Exemption (b)(7)(C)",
        "PRIVILEGED & CONFIDENTIAL",
        "",
    ]

    def __init__(self, editor_window, mark, on_close_callback=None):
        super().__init__(autohide=True, has_arrow=True)
        self.editor_window = editor_window
        self.mark = mark
        self.on_close_callback = on_close_callback
        self.set_parent(editor_window.pdf_view)

        self.initial_state = {
            "bbox": mark.bbox,
            "fill_color": mark.fill_color,
            "overlay_text": mark.overlay_text,
            "text_color": mark.text_color,
            "font_size": mark.font_size,
        }
        self.is_committing = False

        self._build_ui()
        self.connect("closed", self._on_popover_closed)

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main_box.set_margin_top(8)
        main_box.set_margin_bottom(8)
        main_box.set_margin_start(8)
        main_box.set_margin_end(8)
        main_box.set_size_request(280, -1)

        # Header: Title & Delete / Close
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_lbl = Gtk.Label(label=_("redaction_mark_title"))
        title_lbl.add_css_class("heading")
        header_box.append(title_lbl)

        spacer = Gtk.Box(hexpand=True)
        header_box.append(spacer)

        del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        del_btn.add_css_class("flat")
        del_btn.add_css_class("destructive-action")
        del_btn.set_tooltip_text(_("redaction_btn_delete"))
        del_btn.connect("clicked", self._on_delete_clicked)
        header_box.append(del_btn)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.connect("clicked", lambda b: self.popdown())
        header_box.append(close_btn)

        main_box.append(header_box)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Fill Color Row: Black vs White
        fill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        fill_lbl = Gtk.Label(label=_("redaction_fill_color"), xalign=0.0, hexpand=True)
        fill_box.append(fill_lbl)

        btn_black = Gtk.Button(label=_("color_black"))
        btn_black.add_css_class("flat")
        btn_white = Gtk.Button(label=_("color_white"))
        btn_white.add_css_class("flat")

        is_white = (getattr(self.mark, 'fill_color', (0.0, 0.0, 0.0)) == (1.0, 1.0, 1.0))
        if is_white:
            btn_white.add_css_class("suggested-action")
        else:
            btn_black.add_css_class("suggested-action")

        def set_fill(color):
            self.mark.fill_color = color
            if color == (0.0, 0.0, 0.0):
                self.mark.text_color = (1.0, 1.0, 1.0)
                btn_black.add_css_class("suggested-action")
                btn_white.remove_css_class("suggested-action")
            else:
                self.mark.text_color = (0.0, 0.0, 0.0)
                btn_white.add_css_class("suggested-action")
                btn_black.remove_css_class("suggested-action")
            self.editor_window.pdf_view.queue_draw()

        btn_black.connect("clicked", lambda b: set_fill((0.0, 0.0, 0.0)))
        btn_white.connect("clicked", lambda b: set_fill((1.0, 1.0, 1.0)))
        fill_box.append(btn_black)
        fill_box.append(btn_white)
        main_box.append(fill_box)

        # Overlay Text Row
        text_lbl = Gtk.Label(label=_("redaction_overlay_text"), xalign=0.0)
        main_box.append(text_lbl)

        self.text_entry = Gtk.Entry()
        self.text_entry.set_text(self.mark.overlay_text or "")
        def on_text_changed(entry):
            self.mark.overlay_text = entry.get_text()
            self.editor_window.pdf_view.queue_draw()
        self.text_entry.connect("changed", on_text_changed)
        main_box.append(self.text_entry)

        # Quick Presets Dropdown
        preset_strings = [
            _("redaction_mark") + " ([REDACTED])",
            "CONFIDENTIAL",
            "FOIA Exemption (b)(4)",
            "FOIA Exemption (b)(6)",
            "FOIA Exemption (b)(7)(C)",
            "PRIVILEGED & CONFIDENTIAL",
            "[None] (Solid)",
        ]
        self.preset_dropdown = Gtk.DropDown.new_from_strings(preset_strings)
        def on_preset_selected(dd, param):
            idx = dd.get_selected()
            if 0 <= idx < len(self.PRESET_CODES):
                code = self.PRESET_CODES[idx]
                self.text_entry.set_text(code)
                self.mark.overlay_text = code
                self.editor_window.pdf_view.queue_draw()
        self.preset_dropdown.connect("notify::selected", on_preset_selected)
        main_box.append(self.preset_dropdown)

        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        apply_btn = Gtk.Button(label=_("redaction_btn_apply"))
        apply_btn.add_css_class("destructive-action")
        def on_apply_clicked(b):
            self.is_committing = True
            self.popdown()
            if self.editor_window:
                self.editor_window.apply_all_redactions(prompt_warning=True)
        apply_btn.connect("clicked", on_apply_clicked)
        main_box.append(apply_btn)

        self.set_child(main_box)

    def _on_delete_clicked(self, btn):
        self.is_committing = True
        self.popdown()
        if self.editor_window:
            self.editor_window.delete_redaction_mark(self.mark)

    def _on_popover_closed(self, popover):
        if not self.is_committing and self.editor_window:
            current_state = {
                "bbox": self.mark.bbox,
                "fill_color": self.mark.fill_color,
                "overlay_text": self.mark.overlay_text,
                "text_color": self.mark.text_color,
                "font_size": self.mark.font_size,
            }
            if current_state != self.initial_state:
                from .undo_manager import EditRedactionCommand
                cmd = EditRedactionCommand(self.editor_window, self.mark, self.initial_state, current_state)
                if self.editor_window.undo_manager:
                    self.editor_window.undo_manager.record(cmd)
                self.editor_window.document_modified = True
                if hasattr(self.editor_window, "annotations_sidebar"):
                    self.editor_window.annotations_sidebar.refresh()
        if self.on_close_callback:
            self.on_close_callback()


class PdfEditorWindow(Adw.ApplicationWindow):
    """Main application window providing PDF viewing, editing, annotation, and exporting capabilities."""
    _active_session = None
    sessions = None
    tab_view = None
    tab_bar = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_title(constants.APP_NAME)
        self.set_default_size(1200, 800)
        self.set_icon_name("f-pv1")
        self._is_programmatic_scrolling = False
        self._scroll_anim_id = None
        self._scroll_tracker = ScrollVelocityTracker()
        self._scroll_settle_timer_id = None

        saved_view_mode = get_setting("view_mode", "single")
        is_cont = (saved_view_mode == "continuous")
        self._continuous_scroll_fallback = is_cont
        self.is_eco_mode = is_eco_mode_enabled()
        pdf_handler.configure_memory_limits(self.is_eco_mode)
        self.async_page_rendering = True

        self.sessions = []
        self._active_session = DocumentSession(undo_manager=UndoManager(self))
        self._active_session.continuous_scroll = is_cont
        self.sessions.append(self._active_session)
        self.tab_view = None
        self.tab_bar = None
        self._is_switching_tabs = False

        self.current_file_path = None
        self.original_file_path = None
        self.allow_incremental_save = True
        self.doc = None 
        self.current_page_index = 0
        self.zoom_level = 1.0
        self._last_pointer_pos = None
        self.is_zoom_gesture_active = False
        self._zoom_debounce_timer = None
        self._zoom_settle_delay_ms = 120
        self._pinch_initial_zoom = 1.0
        self._pinch_focal_point = None
        self.pages_model = Gio.ListStore(item_type=PdfPage)
        self.editable_texts = [] 
        self.editable_images = []
        self.editable_shapes = []
        self.editable_strokes = []
        self.form_fields = []
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self._form_field_overlay_widgets = {}
        self._enable_persistent_form_overlays = False
        self._active_form_field_editor_container = None
        self._active_form_field_editor_widget = None
        self._active_form_field_initial_val = None
        self._syncing_form_field = False
        self.text_edit_popover = None
        self.text_edit_view = None
        self.is_saving = False
        self._show_ocr_overlay_fallback = False
        self._ocr_words_cache = {}
        self.dragged_object = None
        self._can_drag_object = None
        self.drag_start_pos = (0, 0)
        self.drag_object_start_pos = (0, 0)
        self.resize_handle = None  
        self.resize_start_bbox = None  
        self.dragging_to_create = False  
        self.temp_shape = None  
        self.temp_stroke = None
        self.temp_image_bbox = None  
        self.temp_image_path = None  
        self.drag_start_page_pos = None  
        self.next_shape_fill = (255, 255, 255)
        self.next_shape_stroke = (0, 0, 0)
        self.next_shape_stroke_width = 2.0
        self.next_shape_transparent = True
        self.pen_color = (0.0, 0.0, 0.0)
        self.pen_width = 2.0
        self.highlighter_color = (1.0, 0.9, 0.0)
        self.highlighter_width = 14.0
        self.highlighter_opacity = 0.35
        self.document_modified = False 
        self.tool_mode = "select" 
        self.stamp_library = StampLibrary()
        self.active_stamp = self.stamp_library.get_active_stamp()
        self.temp_stamp_bbox = None
        self.temp_sig_bbox = None
        self.temp_clone_patch_bbox = None
        self.last_captured_patch = None
        self.clone_patch_tool_button = None
        self.temp_redact_bbox = None
        self.selected_redaction_mark = None
        self.redact_tool_button = None
        self._image_dialog_open = False
        self.temp_form_field_rect = None
        self.form_builder_field_type = "text"
        self.form_builder_tool_button = None
        self.form_builder_delete_button = None
        self.form_builder_add_label_check = None
        self.form_builder_label_entry = None
        self.form_builder_options_box = None
        self.form_builder_options_entry = None
        self.form_builder_edit_options_btn = None
        self.calibrate_tool_button = None
        self.temp_calibration_line = None
        self.calibration_toolbar_box = None
        self.calibration_scale_label = None
        self.calibration_preset_dropdown = None
        self.calibrate_dialog_btn = None
        self.calibrate_reset_btn = None
        self.measure_distance_tool_button = None
        self.measure_area_tool_button = None
        self.temp_measurement_line = None
        self.temp_measurement_rect = None
        self.temp_polygon_vertices = []
        self.selected_measurement = None
        self.page_gap = 16
        self.continuous_page_offsets = []
        self.continuous_total_height = 0.0
        self.continuous_max_width = 0.0
        self.drag_start_page_index = 0
        self.measurement_toolbar_box = None
        self.measurement_toolbar_sep = None
        self.measurement_scale_indicator = None
        self.measurement_calibrate_btn = None
        self.measurement_hint_lbl = None
        self.measurement_clear_btn = None
        self.stamp_toolbar_box = None
        self.stamp_toolbar_sep = None
        self.stamp_toolbar_pic = None
        self.stamp_toolbar_name_lbl = None
        self.stamp_toolbar_lock_icon = None
        self.stamp_quick_menu_btn = None
        self.stamp_library_btn = None
        self.stamp_tool_button = None
        self.signature_tool_button = None
        self.stamp_menu_button = None
        self.selected_sticky_note = None
        self.active_sticky_popover = None
        self.dragged_sticky_note = None
        self.sticky_note_start_coords = None
        self.view_tool_mode = None
        self.view_mode_secondary_toolbar = None
        self.view_sticky_note_btn = None
        self._updating_form_builder_ui = False
        self._active_editing_form_field = None
        self.current_pdf_page_width = 0
        self.current_pdf_page_height = 0
        self.thumbnails_scroll = None
        self.redaction_toolbar_box = None
        self.redaction_apply_button = None
        self.redact_default_fill = (0.0, 0.0, 0.0)
        self.redact_default_text_color = (1.0, 1.0, 1.0)
        self.redact_default_overlay = "[REDACTED]"
        self.bold_button = None
        self.italic_button = None
        self.font_scan_in_progress = True
        self.undo_manager = UndoManager(self)
        self.pending_format_change_obj = None
        self.before_format_change_state = None
        self.is_repaired_file = False
        self._last_font_family = None
        self._last_font_size = 11.0
        self._last_is_bold = False
        self._last_is_italic = False
        self._last_is_strikethrough = False
        self._last_alignment = 'left'
        self._last_color = (0.0, 0.0, 0.0)

        self.view_mode = True
        self.view_sel_start = None
        self.view_sel_rect = None
        self.view_selected_text = ""
        self.view_drag_active = False
        
        self.selected_word = None
        self.selected_word_start_char = None
        self.selected_word_end_char = None
        self.word_selection_mode = False

        self.inline_editor_widget = None
        self.inline_editor_text_obj = None

        self.search_engine = DocumentSearchEngine()
        self._spatial_indices = {}
        self._cached_page_links = {}
        self._last_pointer_motion_time = 0.0
        self.search_bar = None
        self.search_button = None
        self.search_entry = None
        self.search_prev_btn = None
        self.search_next_btn = None
        self.search_match_label = None
        self.search_case_btn = None
        self.search_whole_word_btn = None
        self.search_redact_btn = None
        self.search_redact_box = None
        self._search_pii_key = None
        self._search_scope_current_page = False
        self._search_debounce_source = None
        self.ocr_banner = None
        self.ocr_banner_label = None
        self.ocr_banner_progress = None
        self.ocr_banner_pause_btn = None
        self.ocr_banner_cancel_btn = None
        self._ocr_cancel_requested = False
        self._ocr_paused = False
        self._active_ocr_pipeline = None
        self._active_streaming_ocr_cmd = None
        self._font_combo_populated = False

        self._build_ui()
        self._setup_controllers()
        self._connect_actions()
        self._apply_css()
        self._update_ui_state() 

        self.status_label.set_text(_("scan_fonts"))
        utils.scan_system_fonts_async(callback_on_done=self._on_font_scan_complete)

    def _on_font_scan_complete(self):
        """Callback when background system font scan finishes, populating font combo."""
        if getattr(self, '_is_closing', None) is True or getattr(self, '_is_closed', None) is True:
            return
        self.font_scan_in_progress = False
        utils.get_default_unicode_font_path()

        if getattr(self, 'selected_text', None) is not None or getattr(self, '_font_combo_populated', False) is True:
            self._populate_font_combo()
        else:
            default_font = "Liberation Sans"
            if utils.FONT_FAMILY_LIST_SORTED and default_font not in utils.FONT_FAMILY_LIST_SORTED:
                default_font = utils.FONT_FAMILY_LIST_SORTED[0]
            signals_blocked = False
            try:
                self.font_combo.handler_block_by_func(self.on_text_format_changed)
                signals_blocked = True
            except Exception:
                pass
            try:
                self.font_store.clear()
                self.font_store.append([default_font, default_font])
                self.font_combo.set_active(0)
            finally:
                if signals_blocked:
                    try:
                        self.font_combo.handler_unblock_by_func(self.on_text_format_changed)
                    except Exception:
                        pass

        if not utils.UNICODE_FONT_PATH:
             show_error_dialog(self, _("font_warning_msg"), _("font_warning_title"))

        if not self.doc:
            self.status_label.set_text(_("fonts_loaded_open"))
        elif self.current_file_path:
            self.status_label.set_text(_("loaded").format(os.path.basename(self.current_file_path)))
        else:
            self.status_label.set_text(_("new_doc_loaded"))
        self._update_ui_state()

    def _ensure_font_combo_populated(self):
        """Lazily populate font combo dropdown with discovered system fonts on first interaction."""
        if getattr(self, '_font_combo_populated', False) is True or getattr(self, '_is_closing', None) is True or getattr(self, '_is_closed', None) is True:
            return
        self._populate_font_combo()

    def _populate_font_combo(self):
        """Populate font selector dropdown with discovered system fonts."""
        if getattr(self, '_is_closing', None) is True or getattr(self, '_is_closed', None) is True:
            return
        self._font_combo_populated = True

        signals_blocked = False
        try:
            self.font_combo.handler_block_by_func(self.on_text_format_changed)
            signals_blocked = True
        except Exception:
            pass

        try:
            self.font_store.clear() 
            if utils.FONT_FAMILY_LIST_SORTED:
                for family_name in utils.FONT_FAMILY_LIST_SORTED:
                    self.font_store.append([family_name, family_name])
                if len(self.font_store) > 0:
                    default_font = "Liberation Sans"
                    if default_font in utils.FONT_FAMILY_LIST_SORTED:
                        idx = utils.FONT_FAMILY_LIST_SORTED.index(default_font)
                    else:
                        idx = 0
                    self.font_combo.set_active(idx)
                else:
                    self.font_store.append([_("font_none_error"), ""])
                    self.font_combo.set_active(0)
            else:
                self.font_store.append([_("font_none"), ""])
                self.font_combo.set_active(0)
        finally:
            if signals_blocked:
                try:
                    self.font_combo.handler_unblock_by_func(self.on_text_format_changed)
                except Exception:
                    pass
        
        self._update_ui_state()

    def _apply_css(self):
        """Apply custom application stylesheet for toolbars, canvas, and popovers."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .toolbar { padding: 6px; }
            .pdf-view { background-color: #6c6c6c; }
            .statusbar { padding: 4px 8px; border-top: 1px solid @borders; background-color: @theme_bg_color; }
            popover > .box { padding: 10px; }

            textview {
                font-family: monospace;
                min-height: 80px;
                margin-bottom: 6px;
                border-radius: 6px;
                border: 1px solid @borders;
                background-color: @theme_bg_color;
                padding: 4px 6px;
            }

            textview.new-text-entry {
                border: 2px solid @accent_color;
                background-color: @popover_bg_color;
            }

            .inline-editor-frame {
                background-color: @card_bg_color;
                border: 1.5px solid @accent_color;
                border-radius: 4px;
                box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
                padding: 0;
                margin: 0;
            }

            .inline-editor-tv {
                min-height: 0px;
                min-width: 0px;
                margin: 0;
                padding: 2px 3px;
                border: none;
                border-radius: 3px;
                background-color: transparent;
            }

            .tool-button.active { background-color: @theme_selected_bg_color; }
            .acroform-entry {
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(53, 132, 228, 0.6);
                border-radius: 3px;
                padding: 1px 4px;
                min-height: 18px;
                color: #111111;
                font-size: 13px;
            }
            .acroform-entry:focus {
                border: 2px solid @accent_color;
                background-color: #ffffff;
            }
            .acroform-entry.readonly {
                background-color: rgba(240, 240, 240, 0.75);
                border: 1px dashed rgba(130, 130, 130, 0.5);
                color: #555555;
            }
            .acroform-frame {
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(53, 132, 228, 0.6);
                border-radius: 3px;
            }
            .acroform-textview {
                background-color: transparent;
                padding: 2px;
                font-family: inherit;
                font-size: 13px;
                color: #111111;
            }
            .acroform-check {
                background: transparent;
                padding: 0;
                margin: 0;
            }
            .acroform-check check {
                min-width: 16px;
                min-height: 16px;
                border: 1.5px solid #333333;
                border-radius: 3px;
                background-color: #ffffff;
            }
            .acroform-check:checked check {
                background-color: @accent_color;
                border-color: @accent_color;
                color: #ffffff;
            }
            .acroform-check.radio check {
                border-radius: 50%;
            }
            .acroform-dropdown {
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(53, 132, 228, 0.6);
                border-radius: 3px;
                min-height: 20px;
                font-size: 13px;
                padding: 0 4px;
                color: #111111;
            }
            .acroform-dropdown:focus {
                border: 2px solid @accent_color;
            }
            .annotations-sidebar {
                background-color: @theme_bg_color;
                border-left: 1px solid @borders;
            }
            .annotations-header {
                border-bottom: 1px solid @borders;
            }
            .annotation-row {
                border-radius: 6px;
                padding: 4px;
                transition: background-color 150ms ease;
            }
            .annotation-row:hover {
                background-color: alpha(@accent_color, 0.08);
            }
            .annotation-row:selected, .annotation-row:active {
                background-color: alpha(@accent_color, 0.18);
            }
            .annotation-title {
                font-weight: 600;
                font-size: 13px;
            }
            .annotation-subtitle {
                font-size: 11px;
            }
            .annotation-badge {
                font-size: 11px;
                padding: 2px 6px;
                border-radius: 10px;
                background-color: alpha(@theme_fg_color, 0.08);
            }
            .annotation-count-pill {
                font-size: 11px;
                padding: 2px 7px;
                border-radius: 10px;
                background-color: alpha(@accent_color, 0.15);
                color: @accent_color;
                font-weight: bold;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    @property
    def active_session(self) -> DocumentSession:
        """Get current active DocumentSession."""
        return self._active_session

    @active_session.setter
    def active_session(self, session: DocumentSession):
        """Set active DocumentSession."""
        self.set_active_session(session)

    def set_active_session(self, session: DocumentSession):
        """Switch the active document session with clean state isolation and tab synchronization."""
        if session is None:
            return

        if self._active_session is session:
            if hasattr(self, 'stack') and self.stack and session.doc is not None:
                self.stack.set_visible_child_name("editor")
                self.set_title(f"{constants.APP_NAME} - {session.display_title}")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_autohide(False)
                    self.tab_bar.set_visible(True)
            # Ensure paned is parented correctly even if session unchanged
            if getattr(session, 'bin_widget', None) and hasattr(self, 'paned'):
                if self.paned.get_parent() != session.bin_widget:
                    old_parent = self.paned.get_parent()
                    if old_parent:
                        old_parent.set_child(None)
                    session.bin_widget.set_child(self.paned)
            if hasattr(self, 'tab_view') and self.tab_view and getattr(session, 'tab_page', None):
                if self.tab_view.get_selected_page() != session.tab_page:
                    self._is_switching_tabs = True
                    try:
                        self.tab_view.set_selected_page(session.tab_page)
                    finally:
                        self._is_switching_tabs = False
            return

        if self._active_session and self._active_session.doc:
            try:
                self.commit_pending_format_change()
                if self.inline_editor_widget is not None:
                    self._apply_and_hide_editor(force_apply=True)
                self._clear_form_field_overlays()
                if hasattr(self, 'pdf_scroll') and self.pdf_scroll:
                    v_adj = self.pdf_scroll.get_vadjustment()
                    h_adj = self.pdf_scroll.get_hadjustment()
                    if v_adj:
                        self._active_session.scroll_y = v_adj.get_value()
                    if h_adj:
                        self._active_session.scroll_x = h_adj.get_value()
            except Exception:
                pass

        self._active_session = session
        self.pending_format_change_obj = None
        self.before_format_change_state = None
        self.dragged_object = None
        self._can_drag_object = None
        self.temp_polygon_vertices = []
        self.temp_measurement_line = None
        self.temp_measurement_rect = None

        if session not in self.sessions:
            self.sessions.append(session)

        # Ensure tab exists in TabView
        if hasattr(self, 'tab_view') and self.tab_view:
            if getattr(session, 'tab_page', None) is None:
                self._create_tab_for_session(session)

            self._is_switching_tabs = True
            try:
                if session.tab_page and self.tab_view.get_selected_page() != session.tab_page:
                    self.tab_view.set_selected_page(session.tab_page)
            finally:
                self._is_switching_tabs = False

        # Attach self.paned to active session's bin_widget
        if getattr(session, 'bin_widget', None) is not None and hasattr(self, 'paned'):
            current_parent = self.paned.get_parent()
            if current_parent != session.bin_widget:
                if current_parent:
                    current_parent.set_child(None)
                session.bin_widget.set_child(self.paned)

        if hasattr(self, 'thumbnail_selection_model') and self.thumbnail_selection_model is not None:
            if session.pages_model is not None:
                self._syncing_thumb = True
                try:
                    self.thumbnail_selection_model.set_model(session.pages_model)
                finally:
                    self._syncing_thumb = False

        if session.doc is not None:
            self.set_title(f"{constants.APP_NAME} - {session.display_title}")
            if hasattr(self, 'stack') and self.stack:
                self.stack.set_visible_child_name("editor")
            if hasattr(self, 'tab_bar') and self.tab_bar:
                self.tab_bar.set_autohide(False)
                self.tab_bar.set_visible(True)
            if hasattr(self, 'pdf_scroll'):
                has_objects = bool(session.editable_texts or session.editable_shapes or session.editable_strokes or session.editable_images or session.form_fields or session.is_modified)
                self._load_page(session.current_page_index, reload_objects=(not has_objects))
            if hasattr(self, 'thumbnail_selection_model') and self.thumbnail_selection_model:
                try:
                    self.thumbnail_selection_model.set_selected(session.current_page_index)
                except Exception:
                    pass
            self.update_zoom_label()

            if hasattr(self, 'continuous_scroll_btn') and self.continuous_scroll_btn:
                is_cont = self.continuous_scroll
                if self.continuous_scroll_btn.get_active() != is_cont:
                    self.continuous_scroll_btn.set_active(is_cont)
                self.continuous_scroll_btn.set_icon_name("view-continuous-symbolic" if is_cont else "view-paged-symbolic")
            action = self.lookup_action("toggle_continuous_scroll")
            if action:
                action.set_state(GLib.Variant.new_boolean(self.continuous_scroll))

            if hasattr(self, 'ocr_overlay_btn') and self.ocr_overlay_btn:
                is_overlay = getattr(session, 'show_ocr_overlay', False)
                if self.ocr_overlay_btn.get_active() != is_overlay:
                    self.ocr_overlay_btn.set_active(is_overlay)
            action_overlay = self.lookup_action("toggle_ocr_overlay")
            if action_overlay:
                action_overlay.set_state(GLib.Variant.new_boolean(getattr(session, 'show_ocr_overlay', False)))

            if hasattr(self, 'pdf_scroll') and self.pdf_scroll:
                saved_sx = getattr(session, 'scroll_x', 0.0)
                saved_sy = getattr(session, 'scroll_y', 0.0)
                if saved_sx > 0 or saved_sy > 0:
                    def _restore_tab_scroll(sess=session, sx=saved_sx, sy=saved_sy):
                        if getattr(self, '_active_session', None) == sess and hasattr(self, 'pdf_scroll') and self.pdf_scroll:
                            v = self.pdf_scroll.get_vadjustment()
                            h = self.pdf_scroll.get_hadjustment()
                            if v and sy > 0:
                                max_v = max(0.0, v.get_upper() - v.get_page_size())
                                v.set_value(min(sy, max_v))
                            if h and sx > 0:
                                max_h = max(0.0, h.get_upper() - h.get_page_size())
                                h.set_value(min(sx, max_h))
                        return GLib.SOURCE_REMOVE
                    GLib.idle_add(_restore_tab_scroll)
            self._update_signature_banner(
                getattr(session, "digital_signatures", None),
                verifying=bool(getattr(session, "sig_inspection_in_progress", False)),
            )
            if hasattr(self, 'search_bar') and self.search_bar and self.search_bar.get_search_mode():
                self._on_search_query_changed(self.search_entry)
            elif hasattr(self, 'search_engine'):
                self.search_engine.clear()
        else:
            if hasattr(self, 'search_engine'):
                self.search_engine.clear()
            self._update_signature_banner(None)
            self.set_title(constants.APP_NAME)
            if hasattr(self, 'stack') and self.stack:
                any_docs = any(s.doc is not None for s in self.sessions)
                if not any_docs:
                    self.stack.set_visible_child_name("welcome")
                    if hasattr(self, 'tab_bar') and self.tab_bar:
                        self.tab_bar.set_visible(False)
                        self.tab_bar.set_autohide(True)
                else:
                    self.stack.set_visible_child_name("editor")
                    if hasattr(self, 'tab_bar') and self.tab_bar:
                        self.tab_bar.set_autohide(False)
                        self.tab_bar.set_visible(True)

        self._update_tab_title(session)
        self._update_ui_state()
        if hasattr(self, 'refresh_annotations_list'):
            self.refresh_annotations_list()
        if hasattr(self, '_update_text_format_controls'):
            self._update_text_format_controls(self.selected_text)
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def _create_tab_for_session(self, session: DocumentSession):
        """Create and bind an Adw.TabPage in tab_view for the given DocumentSession."""
        if not hasattr(self, 'tab_view') or self.tab_view is None:
            return None
        if getattr(session, 'tab_page', None) is not None:
            return session.tab_page

        bin_widget = Adw.Bin()
        bin_widget.set_vexpand(True)
        bin_widget.set_hexpand(True)
        page = self.tab_view.append(bin_widget)
        session.tab_page = page
        session.bin_widget = bin_widget

        if hasattr(self, 'paned') and self.paned is not None:
            if session == self._active_session or self.paned.get_parent() is None:
                old_parent = self.paned.get_parent()
                if old_parent:
                    old_parent.set_child(None)
                bin_widget.set_child(self.paned)

        self._update_tab_title(session)
        return page

    def _update_tab_title(self, session: DocumentSession):
        """Sync tab title, tooltip, and dirty indicators for the given session."""
        if not session or not getattr(session, 'tab_page', None):
            return
        try:
            page = session.tab_page
            display_title = session.display_title
            page.set_title(display_title)
            page.set_tooltip(session.pdf_path or _("untitled_document") if "_" in dir() else (session.pdf_path or "Untitled Document"))
            is_secured = getattr(session, 'is_vault', False) or getattr(session, 'pdf_password', None) is not None
            page.set_icon(Gio.ThemedIcon.new("channel-secure-symbolic" if is_secured else "application-pdf-symbolic"))
            page.set_needs_attention(session.is_modified)
        except Exception:
            pass

    def get_session_by_tab_page(self, page) -> Optional[DocumentSession]:
        """Find the DocumentSession associated with the specified Adw.TabPage."""
        if not page or not self.sessions:
            return None
        page_child = page.get_child() if hasattr(page, 'get_child') else None
        for s in self.sessions:
            if getattr(s, 'tab_page', None) == page:
                return s
            if page_child is not None and getattr(s, 'bin_widget', None) == page_child:
                return s
        return None

    def _on_tab_selected_page_changed(self, tab_view, pspec):
        """Handle user tab selection changes from Adw.TabBar or keyboard navigation."""
        if getattr(self, '_is_switching_tabs', False):
            return
        if not hasattr(self, 'tab_view') or self.tab_view is None:
            return
        selected_page = self.tab_view.get_selected_page()
        if not selected_page:
            return
        target_session = self.get_session_by_tab_page(selected_page)
        if target_session:
            if hasattr(self, 'stack') and self.stack and self.stack.get_visible_child_name() == "welcome":
                self.stack.set_visible_child_name("editor")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_autohide(False)
                    self.tab_bar.set_visible(True)
            if target_session != self._active_session:
                self.set_active_session(target_session)
            elif target_session.doc is not None:
                self.set_title(f"{constants.APP_NAME} - {target_session.display_title}")

    def _on_tab_close_page(self, tab_view, page) -> bool:
        """Handle tab close request, prompting to save unsaved modifications."""
        if getattr(self, 'is_saving', False) is True:
            self.wait_for_save()
        target_session = self.get_session_by_tab_page(page)
        if target_session:
            if target_session.is_modified:
                self.set_active_session(target_session)
                response = show_save_changes_dialog(self)
                if response == Gtk.ResponseType.ACCEPT:
                    if target_session.pdf_path:
                        self.save_document(target_session.pdf_path, incremental=False, background=False)
                    else:
                        self.on_save_as(None, None)
                        if target_session.is_modified:
                            self.tab_view.close_page_finish(page, False)
                            return True
                elif response == Gtk.ResponseType.REJECT:
                    pass
                else:  # Cancel
                    self.tab_view.close_page_finish(page, False)
                    return True

            try:
                page.set_icon(None)
            except Exception:
                pass
            self.tab_view.close_page_finish(page, True)
            target_session.tab_page = None
            self.remove_session(target_session)
            return True

        try:
            page.set_icon(None)
        except Exception:
            pass
        self.tab_view.close_page_finish(page, True)
        return True

    def _on_tab_page_reordered(self, tab_view, page, position):
        """Update internal session list order when user drags and reorders tabs."""
        session = self.get_session_by_tab_page(page)
        if session and session in self.sessions:
            self.sessions.remove(session)
            self.sessions.insert(position, session)

    def _on_tab_extra_drag_drop(self, tab_bar, page, value):
        """Handle dropping a PDF file onto the TabBar to open it in a new tab."""
        if isinstance(value, Gio.File):
            filepath = value.get_path()
            if filepath and filepath.lower().endswith('.pdf'):
                GLib.idle_add(self.load_document, filepath, 0, True)
                return True
        return False

    def create_session(self, doc=None, filepath=None) -> DocumentSession:
        """Create a new DocumentSession configured for this window."""
        session = DocumentSession(
            doc=doc,
            pdf_path=filepath,
            original_file_path=filepath,
            continuous_scroll=self.continuous_scroll,
            undo_manager=UndoManager(self)
        )
        return session

    def add_session(self, session: DocumentSession, switch_to: bool = True):
        """Add a session to the session pool and create a tab for it."""
        if session not in self.sessions:
            self.sessions.append(session)
        if hasattr(self, 'tab_view') and self.tab_view:
            if getattr(session, 'tab_page', None) is None:
                self._create_tab_for_session(session)
        if switch_to:
            self.set_active_session(session)

    def remove_session(self, session_or_id):
        """Remove a session from the session pool, close its tab, and cleanly close it."""
        target_session = None
        if isinstance(session_or_id, DocumentSession):
            target_session = session_or_id
        elif isinstance(session_or_id, str):
            target_session = self.get_session_by_id(session_or_id)

        if not target_session or target_session not in self.sessions:
            return

        self.sessions.remove(target_session)

        if hasattr(self, 'paned') and self.paned.get_parent() == getattr(target_session, 'bin_widget', None):
            if target_session.bin_widget:
                target_session.bin_widget.set_child(None)

        if hasattr(self, 'tab_view') and self.tab_view and getattr(target_session, 'tab_page', None):
            page = target_session.tab_page
            target_session.tab_page = None
            try:
                page.set_icon(None)
                self.tab_view.close_page(page)
            except Exception:
                pass

        target_session.close()
        gc.collect(1)

        if getattr(self, '_is_closing', False):
            return

        if self._active_session == target_session or self._active_session not in self.sessions:
            selected_page = self.tab_view.get_selected_page() if hasattr(self, 'tab_view') and self.tab_view else None
            candidate = self.get_session_by_tab_page(selected_page) if selected_page else None
            if candidate and candidate != target_session and candidate in self.sessions:
                self.set_active_session(candidate)
            else:
                remaining_with_doc = [s for s in self.sessions if s.doc is not None]
                if remaining_with_doc:
                    self.set_active_session(remaining_with_doc[-1])
                elif self.sessions:
                    self.set_active_session(self.sessions[-1])
                else:
                    new_session = self.create_session()
                    self._active_session = new_session
                    self.sessions = [new_session]
                    if hasattr(self, 'tab_view') and self.tab_view:
                        self._create_tab_for_session(new_session)
                    self.close_document()
                    if hasattr(self, 'stack') and self.stack:
                        self.stack.set_visible_child_name("welcome")
                    if hasattr(self, 'tab_bar') and self.tab_bar:
                        self.tab_bar.set_visible(False)

    def get_session_by_id(self, session_id: str):
        """Retrieve session by UUID."""
        for s in self.sessions:
            if s.session_id == session_id:
                return s
        return None

    def get_session_by_path(self, filepath: str):
        """Retrieve session by canonical file path."""
        if not filepath:
            return None
        try:
            norm_target = os.path.realpath(filepath)
        except Exception:
            norm_target = filepath
        for s in self.sessions:
            if s.pdf_path:
                try:
                    if os.path.realpath(s.pdf_path) == norm_target:
                        return s
                except Exception:
                    if s.pdf_path == filepath:
                        return s
        return None

    @property
    def doc(self):
        """Active document object."""
        return self._active_session.doc if self._active_session else None

    @doc.setter
    def doc(self, val):
        if self._active_session:
            self._active_session.doc = val

    @property
    def current_file_path(self):
        """Active document file path."""
        return self._active_session.pdf_path if self._active_session else None

    @current_file_path.setter
    def current_file_path(self, val):
        if self._active_session:
            self._active_session.pdf_path = val
            self._update_tab_title(self._active_session)

    @property
    def original_file_path(self):
        """Active document original file path."""
        return self._active_session.original_file_path if self._active_session else None

    @original_file_path.setter
    def original_file_path(self, val):
        if self._active_session:
            self._active_session.original_file_path = val

    @property
    def current_page_index(self):
        """Active document current page index."""
        return self._active_session.current_page_index if self._active_session else 0

    @current_page_index.setter
    def current_page_index(self, val):
        if self._active_session:
            self._active_session.current_page_index = val

    @property
    def current_page(self) -> int:
        """Active document current page index (0-based, respecting continuous scroll dominant page)."""
        if getattr(self, "continuous_scroll", False):
            return self.get_dominant_visible_page_index()
        return self._active_session.current_page_index if self._active_session else 0

    @current_page.setter
    def current_page(self, val: int):
        self.current_page_index = val

    @property
    def zoom_level(self):
        """Active document zoom level."""
        return self._active_session.zoom_level if self._active_session else 1.0

    @zoom_level.setter
    def zoom_level(self, val):
        if self._active_session:
            self._active_session.zoom_level = val

    @property
    def view_mode(self):
        """Active document view mode flag."""
        return self._active_session.view_mode if self._active_session else True

    @view_mode.setter
    def view_mode(self, val):
        if self._active_session:
            self._active_session.view_mode = val

    @property
    def continuous_scroll(self) -> bool:
        """Active document continuous vertical scroll mode flag."""
        sess = getattr(self, '_active_session', None)
        return sess.continuous_scroll if sess else getattr(self, '_continuous_scroll_fallback', False)

    @continuous_scroll.setter
    def continuous_scroll(self, val: bool):
        sess = getattr(self, '_active_session', None)
        if sess:
            sess.continuous_scroll = bool(val)
        else:
            self._continuous_scroll_fallback = bool(val)
        if hasattr(self, 'pdf_view'):
            self._update_canvas_content_size()
            self.pdf_view.queue_draw()

    @property
    def show_ocr_overlay(self) -> bool:
        """Active document OCR text layer inspector overlay flag."""
        sess = getattr(self, '_active_session', None)
        return sess.show_ocr_overlay if sess else getattr(self, '_show_ocr_overlay_fallback', False)

    @show_ocr_overlay.setter
    def show_ocr_overlay(self, val: bool):
        sess = getattr(self, '_active_session', None)
        if sess:
            sess.show_ocr_overlay = bool(val)
        else:
            self._show_ocr_overlay_fallback = bool(val)
        if hasattr(self, 'pdf_view'):
            self.pdf_view.queue_draw()

    @property
    def _page_objects_cache(self) -> Dict[int, Any]:
        """Active document per-page objects cache."""
        sess = getattr(self, '_active_session', None)
        if sess is not None:
            return sess.page_objects_cache
        if not hasattr(self, '_fallback_page_objects_cache'):
            self._fallback_page_objects_cache = {}
        return self._fallback_page_objects_cache

    @property
    def document_modified(self):
        """Active document modified flag."""
        return self._active_session.is_modified if self._active_session else False

    @document_modified.setter
    def document_modified(self, val):
        if self._active_session:
            self._active_session.is_modified = val
            if self._active_session.doc is not None:
                try:
                    self._active_session.doc._is_modified = bool(val)
                except Exception:
                    pass
            self._update_tab_title(self._active_session)
            if val and hasattr(self, 'get_title'):
                title = self.get_title()
                if not title.endswith("*"):
                    self.set_title(title + "*")
            elif not val and hasattr(self, 'get_title'):
                title = self.get_title()
                if title.endswith("*"):
                    self.set_title(title[:-1])

    @property
    def allow_incremental_save(self):
        """Active document allow incremental save flag."""
        return self._active_session.allow_incremental_save if self._active_session else True

    @allow_incremental_save.setter
    def allow_incremental_save(self, val):
        if self._active_session:
            self._active_session.allow_incremental_save = val

    @property
    def is_repaired_file(self):
        """Active document repaired file flag."""
        return self._active_session.is_repaired_file if self._active_session else False

    @is_repaired_file.setter
    def is_repaired_file(self, val):
        if self._active_session:
            self._active_session.is_repaired_file = val

    @property
    def undo_manager(self):
        """Active document undo manager."""
        return self._active_session.undo_manager if self._active_session else None

    @undo_manager.setter
    def undo_manager(self, val):
        if self._active_session:
            self._active_session.undo_manager = val

    @property
    def pages_model(self):
        """Active document pages model."""
        return self._active_session.pages_model if self._active_session else None

    @pages_model.setter
    def pages_model(self, val):
        if self._active_session:
            self._active_session.pages_model = val

    @property
    def editable_texts(self):
        """Active document editable texts list."""
        if self._active_session:
            return self._active_session.editable_texts
        return getattr(self, '_fallback_editable_texts', [])

    @editable_texts.setter
    def editable_texts(self, val):
        if self._active_session:
            self._active_session.editable_texts = val
        else:
            self._fallback_editable_texts = val

    @property
    def editable_images(self):
        """Active document editable images list."""
        if self._active_session:
            return self._active_session.editable_images
        return getattr(self, '_fallback_editable_images', [])

    @editable_images.setter
    def editable_images(self, val):
        if self._active_session:
            self._active_session.editable_images = val
        else:
            self._fallback_editable_images = val

    @property
    def editable_shapes(self):
        """Active document editable shapes list."""
        if self._active_session:
            return self._active_session.editable_shapes
        return getattr(self, '_fallback_editable_shapes', [])

    @editable_shapes.setter
    def editable_shapes(self, val):
        if self._active_session:
            self._active_session.editable_shapes = val
        else:
            self._fallback_editable_shapes = val

    @property
    def editable_strokes(self):
        """Active document editable strokes list."""
        if self._active_session:
            return self._active_session.editable_strokes
        return getattr(self, '_fallback_editable_strokes', [])

    @editable_strokes.setter
    def editable_strokes(self, val):
        if self._active_session:
            self._active_session.editable_strokes = val
        else:
            self._fallback_editable_strokes = val

    @property
    def form_fields(self):
        """Active document interactive AcroForm fields."""
        if self._active_session:
            return self._active_session.form_fields
        return getattr(self, '_fallback_form_fields', [])

    @form_fields.setter
    def form_fields(self, val):
        if self._active_session:
            self._active_session.form_fields = val
        else:
            self._fallback_form_fields = val

    @property
    def selected_text(self):
        """Active document selected text."""
        if self._active_session:
            return self._active_session.selected_text
        return getattr(self, '_fallback_selected_text', None)

    @selected_text.setter
    def selected_text(self, val):
        if hasattr(self, 'pending_format_change_obj') and self.pending_format_change_obj and self.pending_format_change_obj is not val:
            self.commit_pending_format_change()
        if self._active_session:
            self._active_session.selected_text = val
        else:
            self._fallback_selected_text = val
        if val is not None:
            self.pending_format_change_obj = val
            self.before_format_change_state = snapshot_object_state(val)
        else:
            self.pending_format_change_obj = None
            self.before_format_change_state = None

    @property
    def selected_image(self):
        """Active document selected image."""
        if self._active_session:
            return self._active_session.selected_image
        return getattr(self, '_fallback_selected_image', None)

    @selected_image.setter
    def selected_image(self, val):
        if self._active_session:
            self._active_session.selected_image = val
        else:
            self._fallback_selected_image = val

    @property
    def selected_shape(self):
        """Active document selected shape."""
        if self._active_session:
            return self._active_session.selected_shape
        return getattr(self, '_fallback_selected_shape', None)

    @selected_shape.setter
    def selected_shape(self, val):
        if self._active_session:
            self._active_session.selected_shape = val
        else:
            self._fallback_selected_shape = val

    @property
    def selected_stroke(self):
        """Active document selected stroke."""
        if self._active_session:
            return self._active_session.selected_stroke
        return getattr(self, '_fallback_selected_stroke', None)

    @selected_stroke.setter
    def selected_stroke(self, val):
        if self._active_session:
            self._active_session.selected_stroke = val
        else:
            self._fallback_selected_stroke = val

    @property
    def selected_form_field(self):
        """Active document selected form field."""
        if self._active_session:
            return self._active_session.selected_form_field
        return getattr(self, '_fallback_selected_form_field', None)

    @selected_form_field.setter
    def selected_form_field(self, val):
        if self._active_session:
            self._active_session.selected_form_field = val
        else:
            self._fallback_selected_form_field = val

    @property
    def view_sel_start(self):
        """Active document view mode selection start."""
        return self._active_session.view_sel_start if self._active_session else None

    @view_sel_start.setter
    def view_sel_start(self, val):
        if self._active_session:
            self._active_session.view_sel_start = val

    @property
    def view_sel_rect(self):
        """Active document view mode selection rectangle."""
        return self._active_session.view_sel_rect if self._active_session else None

    @view_sel_rect.setter
    def view_sel_rect(self, val):
        if self._active_session:
            self._active_session.view_sel_rect = val

    @property
    def view_selected_text(self):
        """Active document view mode selected text."""
        return self._active_session.view_selected_text if self._active_session else ""

    @view_selected_text.setter
    def view_selected_text(self, val):
        if self._active_session:
            self._active_session.view_selected_text = val

    @property
    def view_drag_active(self):
        """Active document view drag active flag."""
        return self._active_session.view_drag_active if self._active_session else False

    @view_drag_active.setter
    def view_drag_active(self, val):
        if self._active_session:
            self._active_session.view_drag_active = val

    @property
    def selected_word(self):
        """Active document selected word."""
        return self._active_session.selected_word if self._active_session else None

    @selected_word.setter
    def selected_word(self, val):
        if self._active_session:
            self._active_session.selected_word = val

    @property
    def selected_word_start_char(self):
        """Active document selected word start char index."""
        return self._active_session.selected_word_start_char if self._active_session else None

    @selected_word_start_char.setter
    def selected_word_start_char(self, val):
        if self._active_session:
            self._active_session.selected_word_start_char = val

    @property
    def selected_word_end_char(self):
        """Active document selected word end char index."""
        return self._active_session.selected_word_end_char if self._active_session else None

    @selected_word_end_char.setter
    def selected_word_end_char(self, val):
        if self._active_session:
            self._active_session.selected_word_end_char = val

    @property
    def word_selection_mode(self):
        """Active document word selection mode flag."""
        return self._active_session.word_selection_mode if self._active_session else False

    @word_selection_mode.setter
    def word_selection_mode(self, val):
        if self._active_session:
            self._active_session.word_selection_mode = val

    @property
    def scale_calibration(self):
        """Active document scale calibration."""
        return self._active_session.scale_calibration if self._active_session else None

    @scale_calibration.setter
    def scale_calibration(self, val):
        if self._active_session:
            self._active_session.scale_calibration = val

    def _build_ui(self):
        """Build UI."""
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.main_box)

        header = Adw.HeaderBar()
        self.header_bar = header
        self.window_title_widget = Adw.WindowTitle()
        self.window_title_widget.set_title(constants.APP_NAME)
        header.set_title_widget(self.window_title_widget)
        self.main_box.append(header)

        self.new_button = Gtk.Button(label=_("btn_new_doc"))
        self.new_button.set_tooltip_text(f"{_('btn_new_doc')} (Ctrl+N)")
        self.new_button.connect("clicked", self.on_new_clicked)
        header.pack_start(self.new_button)

        self.open_button = Gtk.Button(label=_("btn_open_doc"))
        self.open_button.set_tooltip_text(f"{_('btn_open_doc')} (Ctrl+O)")
        self.open_button.connect("clicked", self.on_open_clicked)
        header.pack_start(self.open_button)

        save_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        save_button_box.get_style_context().add_class("linked")

        self.save_button = Gtk.Button(label=_("btn_save"))
        self.save_button.get_style_context().add_class("suggested-action")
        self.save_button.connect("clicked", self.on_save_clicked)
        save_button_box.append(self.save_button)

        header.pack_start(save_button_box)

        self.undo_button = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        self.undo_button.set_tooltip_text(_("undo_tip"))
        self.undo_button.connect("clicked", lambda w: self._on_undo_activated())
        header.pack_start(self.undo_button)

        self.redo_button = Gtk.Button.new_from_icon_name("edit-redo-symbolic")
        self.redo_button.set_tooltip_text(_("redo_tip"))
        self.redo_button.connect("clicked", lambda w: self._on_redo_activated())
        header.pack_start(self.redo_button)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        header.pack_end(menu_button)

        self.toggle_annotations_button = Gtk.ToggleButton(icon_name="sidebar-show-right-symbolic")
        self.toggle_annotations_button.set_tooltip_text(_("toggle_annotations_sidebar_tip"))
        self.toggle_annotations_button.connect("toggled", lambda b: self.toggle_annotations_sidebar(b.get_active()))
        header.pack_end(self.toggle_annotations_button)

        self.home_button = Gtk.Button.new_from_icon_name("go-home-symbolic")
        self.home_button.set_tooltip_text(_("home_button_tip"))
        self.home_button.connect("clicked", lambda w: self.go_to_welcome())
        self.home_button.add_css_class("flat")
        header.pack_end(self.home_button)
        self.print_button = Gtk.Button.new_from_icon_name("printer-symbolic")
        self.print_button.set_tooltip_text(_("print_tip"))
        self.print_button.connect("clicked", lambda w: self.on_print_activated(None, None))
        header.pack_end(self.print_button)

        self.search_button = Gtk.ToggleButton(icon_name="system-search-symbolic")
        self.search_button.set_tooltip_text(_("search_placeholder"))
        self.search_button.connect("toggled", self._on_search_button_toggled)
        header.pack_end(self.search_button)

        self.mode_toggle_button = Gtk.Button(label=_("mode_edit"))
        self.mode_toggle_button.set_tooltip_text(_("mode_toggle_tip"))
        self.mode_toggle_button.get_style_context().add_class("suggested-action")
        self.mode_toggle_button.connect("clicked", self._toggle_view_edit_mode)
        header.pack_end(self.mode_toggle_button)
        menu = Gio.Menu()
        menu.append(_("menu_save_as"), "win.save_as")
        menu.append(_("menu_compress_document"), "win.compress_document")
        menu.append(_("protect_document"), "win.protect_document")
        menu.append(_("digitally_sign_document"), "win.digitally_sign_document")
        menu.append(_("inspect_digital_signatures"), "win.inspect_digital_signatures")
        menu.append(_("menu_merge_documents"), "win.merge_documents")
        menu.append(_("menu_flatten"), "win.flatten_annotations")
        menu.append(_("menu_manage_stamps"), "win.manage_stamps")
        menu.append(_("menu_sanitize_document"), "win.sanitize_document")
        menu.append(_("menu_ocr_document"), "win.ocr_document")

        export_menu = Gio.Menu()
        export_menu.append(_("menu_export_as"), "win.export_as")
        export_formats_section = Gio.Menu()
        export_formats_section.append(_("export_format_docx"), "win.export_docx")
        export_formats_section.append(_("export_format_pptx"), "win.export_pptx")
        export_formats_section.append(_("export_format_odt"), "win.export_odt")
        export_formats_section.append(_("export_format_odp"), "win.export_odp")
        export_formats_section.append(_("export_format_txt"), "win.export_txt")
        export_menu.append_section(None, export_formats_section)
        menu.append_submenu(_("menu_export"), export_menu)
        
        pref_section = Gio.Menu()
        pref_section.append(_("menu_toggle_continuous_scroll"), "win.toggle_continuous_scroll")
        pref_section.append(_("menu_toggle_eco_mode"), "win.toggle_eco_mode")
        pref_section.append(_("menu_reveal_ocr_text"), "win.toggle_ocr_overlay")
        pref_section.append(_("menu_toggle_annotations"), "win.toggle_annotations")
        pref_section.append(_("menu_confirm_delete"), "win.confirm_delete")

        lang_menu = Gio.Menu()
        for code, name in get_supported_languages():
            lang_item = Gio.MenuItem.new(name, f"win.change_language('{code}')")
            lang_menu.append_item(lang_item)
        pref_section.append_submenu(_("lang_label"), lang_menu)

        menu.append_section(None, pref_section)

        menu.append_section(None, Gio.Menu())
        menu.append(_("menu_quick_guide"), "win.quick_guide")
        menu.append(_("menu_about"), "win.about")
        menu.append(_("menu_quit"), "app.quit")
        popover_menu = Gtk.PopoverMenu.new_from_model(menu)
        menu_button.set_popover(popover_menu)

        self.tab_view = Adw.TabView()
        self.tab_bar = Adw.TabBar()
        self.tab_bar.set_view(self.tab_view)
        self.tab_bar.set_autohide(True)
        self.tab_bar.set_visible(False)

        new_tab_btn = Gtk.Button.new_from_icon_name("tab-new-symbolic")
        new_tab_btn.add_css_class("flat")
        new_tab_btn.set_tooltip_text(_("btn_new_doc"))
        new_tab_btn.connect("clicked", lambda b: self.on_new_clicked())
        self.tab_bar.set_end_action_widget(new_tab_btn)

        try:
            self.tab_bar.setup_extra_drop_target(Gdk.DragAction.COPY, [Gio.File])
            self.tab_bar.connect("extra-drag-drop", self._on_tab_extra_drag_drop)
        except Exception:
            pass

        self.tab_view.connect("notify::selected-page", self._on_tab_selected_page_changed)
        self.tab_view.connect("close-page", self._on_tab_close_page)
        self.tab_view.connect("page-reordered", self._on_tab_page_reordered)

        tab_click = Gtk.GestureClick.new()
        tab_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        tab_click.connect("pressed", self._on_tab_bar_pressed)
        self.tab_bar.add_controller(tab_click)

        self.main_box.append(self.tab_bar)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.main_box.append(self.stack)

        welcome_view = WelcomeView(parent_window=self)
        self.stack.add_named(welcome_view, "welcome")

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True, vexpand=True, shrink_start_child=False)
        
        self._create_sidebar()

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, vexpand=True)
        self._create_main_toolbar()
        content_box.append(self.main_toolbar)

        self.signature_banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.signature_banner.set_margin_start(12)
        self.signature_banner.set_margin_end(12)
        self.signature_banner.set_margin_top(6)
        self.signature_banner.set_margin_bottom(6)
        self.signature_banner.add_css_class("card")
        self.signature_banner_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self.signature_banner_label = Gtk.Label(xalign=0.0, hexpand=True)
        self.signature_banner_label.set_wrap(True)
        self.signature_banner_btn = Gtk.Button(label=_("sig_banner_btn_view"))
        self.signature_banner_btn.connect("clicked", lambda b: self.on_inspect_digital_signatures(None, None))
        self.signature_banner.append(self.signature_banner_icon)
        self.signature_banner.append(self.signature_banner_label)
        self.signature_banner.append(self.signature_banner_btn)
        close_banner_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_banner_btn.add_css_class("flat")
        close_banner_btn.connect("clicked", lambda b: self.signature_banner.set_visible(False))
        self.signature_banner.append(close_banner_btn)
        self.signature_banner.set_visible(False)
        content_box.append(self.signature_banner)

        # OCR Progress / Status Banner
        self.ocr_banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.ocr_banner.set_margin_start(12)
        self.ocr_banner.set_margin_end(12)
        self.ocr_banner.set_margin_top(4)
        self.ocr_banner.set_margin_bottom(4)
        self.ocr_banner.add_css_class("card")
        ocr_banner_icon = Gtk.Image.new_from_icon_name("scanner-symbolic")
        self.ocr_banner_label = Gtk.Label(xalign=0.0, hexpand=True)
        self.ocr_banner_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.ocr_banner_label.set_text(_("ocr_banner_processing", 1, 1))
        self.ocr_banner_progress = Gtk.ProgressBar()
        self.ocr_banner_progress.set_size_request(160, -1)
        self.ocr_banner_progress.set_valign(Gtk.Align.CENTER)
        self.ocr_banner_progress.set_show_text(True)
        self.ocr_banner_pause_btn = Gtk.Button(label=_("ocr_btn_pause"))
        self.ocr_banner_pause_btn.connect("clicked", self._on_ocr_banner_pause_clicked)
        self.ocr_banner_cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.ocr_banner_cancel_btn.connect("clicked", self._on_ocr_banner_cancel_clicked)
        self.ocr_banner.append(ocr_banner_icon)
        self.ocr_banner.append(self.ocr_banner_label)
        self.ocr_banner.append(self.ocr_banner_progress)
        self.ocr_banner.append(self.ocr_banner_pause_btn)
        self.ocr_banner.append(self.ocr_banner_cancel_btn)
        self.ocr_banner.set_visible(False)
        content_box.append(self.ocr_banner)

        # Search Bar
        self.search_bar = Gtk.SearchBar()
        self.search_bar.set_key_capture_widget(self)
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        search_box.set_margin_start(8)
        search_box.set_margin_end(8)
        search_box.set_margin_top(4)
        search_box.set_margin_bottom(4)

        self.search_entry = Gtk.SearchEntry(placeholder_text=_("search_placeholder"))
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_query_changed)
        self.search_entry.connect("activate", lambda e: self._on_search_entry_activate())
        self.search_bar.connect_entry(self.search_entry)
        search_box.append(self.search_entry)

        self.search_prev_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
        self.search_prev_btn.set_tooltip_text(f"{_('search_prev')} (Shift+F3)")
        self.search_prev_btn.connect("clicked", lambda b: self._search_navigate_prev())
        search_box.append(self.search_prev_btn)

        self.search_next_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
        self.search_next_btn.set_tooltip_text(f"{_('search_next')} (F3 / Enter)")
        self.search_next_btn.connect("clicked", lambda b: self._search_navigate_next())
        search_box.append(self.search_next_btn)

        self.search_match_label = Gtk.Label(label=_("search_no_results"))
        self.search_match_label.add_css_class("dim-label")
        search_box.append(self.search_match_label)

        self.search_case_btn = Gtk.ToggleButton(label="aA")
        self.search_case_btn.set_tooltip_text(_("search_case_sensitive_tip"))
        self.search_case_btn.connect("toggled", self._on_search_case_toggled)
        search_box.append(self.search_case_btn)

        self.search_whole_word_btn = Gtk.ToggleButton(label="[W]")
        self.search_whole_word_btn.set_tooltip_text(_("search_whole_word_tip"))
        self.search_whole_word_btn.connect("toggled", self._on_search_whole_word_toggled)
        search_box.append(self.search_whole_word_btn)

        # Redaction controls docked directly inside search bar
        self.search_redact_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.search_redact_box.set_visible(False)

        sep_sr = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.search_redact_box.append(sep_sr)

        self.btn_search_redact_current = Gtk.Button(label=_("redaction_mark_match"))
        self.btn_search_redact_current.set_tooltip_text(_("redaction_mark_match_tip"))
        self.btn_search_redact_current.add_css_class("suggested-action")
        self.btn_search_redact_current.connect("clicked", lambda b: self._redact_current_search_match())
        self.search_redact_box.append(self.btn_search_redact_current)

        self.btn_search_redact_all = Gtk.Button(label=_("search_redact_btn_stage"))
        self.btn_search_redact_all.set_tooltip_text(_("search_redact_all_tip"))
        self.btn_search_redact_all.add_css_class("destructive-action")
        self.btn_search_redact_all.connect("clicked", lambda b: self._redact_all_search_matches())
        self.search_redact_box.append(self.btn_search_redact_all)

        self.search_redact_options_btn = Gtk.MenuButton()
        self.search_redact_options_btn.set_icon_name("preferences-system-symbolic")
        self.search_redact_options_btn.set_tooltip_text(_("redaction_options"))
        self.search_redact_options_btn.set_popover(self._create_search_redact_options_popover())
        self.search_redact_box.append(self.search_redact_options_btn)

        search_box.append(self.search_redact_box)

        self.search_redact_btn = Gtk.ToggleButton()
        self.search_redact_btn.set_icon_name("edit-clear-symbolic")
        self.search_redact_btn.set_tooltip_text(_("redaction_find_and_redact"))
        self.search_redact_btn.connect("toggled", lambda b: self.search_redact_box.set_visible(b.get_active()))
        search_box.append(self.search_redact_btn)

        search_close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        search_close_btn.add_css_class("flat")
        search_close_btn.set_tooltip_text(_("search_close"))
        search_close_btn.connect("clicked", lambda b: self.close_search_bar())
        search_box.append(search_close_btn)

        self.search_bar.set_child(search_box)
        self.search_bar.connect("notify::search-mode-enabled", lambda sb, ps: (
            self.search_button.set_active(sb.get_search_mode()) if hasattr(self, 'search_button') and self.search_button and self.search_button.get_active() != sb.get_search_mode() else None
        ))
        content_box.append(self.search_bar)
        
        self.pdf_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True,
                                            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        v_adj = self.pdf_scroll.get_vadjustment()
        if v_adj:
            v_adj.connect("value-changed", self._on_canvas_scrolled)
        h_adj = self.pdf_scroll.get_hadjustment()
        if h_adj:
            h_adj.connect("value-changed", self._on_canvas_scrolled)
        self.pdf_view = VirtualDrawingArea(content_width=1, content_height=1,
                                           hexpand=True, vexpand=True)
        self.pdf_view.get_viewport_rect_cb = self.get_visible_viewport_rect
        self.pdf_view.is_virtualization_required_cb = self._is_canvas_virtualization_required
        self.pdf_view.set_draw_func(self.draw_pdf_page)
        self.pdf_view.add_css_class('pdf-view')
        self.pdf_view.set_focusable(True)
        self.pdf_view.connect("notify::allocated-width", lambda *a: self._update_form_field_overlay_positions())
        self.pdf_view.connect("notify::allocated-height", lambda *a: self._update_form_field_overlay_positions())

        self.pdf_overlay = Gtk.Overlay()
        self.pdf_overlay.set_child(self.pdf_view)

        self.pdf_viewport = Gtk.Viewport()
        self.pdf_viewport.set_scroll_to_focus(False)
        self.pdf_viewport.set_child(self.pdf_overlay)
        self.pdf_scroll.set_child(self.pdf_viewport)
        
        content_box.append(self.pdf_scroll)

        self.main_content_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True, vexpand=True, shrink_end_child=False)
        self.main_content_paned.set_start_child(content_box)

        self.annotations_sidebar = AnnotationsSidebar(editor_window=self)
        self.annotations_sidebar.set_visible(False)
        self.main_content_paned.set_end_child(self.annotations_sidebar)
        self.main_content_paned.set_position(950)

        self.paned.set_end_child(self.main_content_paned)
        self.paned.set_position(200)

        self.stack.add_named(self.tab_view, "editor")

        if self._active_session:
            self._create_tab_for_session(self._active_session)
            if getattr(self._active_session, 'bin_widget', None) is not None:
                if self.paned.get_parent() != self._active_session.bin_widget:
                    old_parent = self.paned.get_parent()
                    if old_parent:
                        old_parent.set_child(None)
                    self._active_session.bin_widget.set_child(self.paned)

        status_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, vexpand=False)
        status_bar_box.add_css_class('statusbar')
        self.status_label = Gtk.Label(label=_('new_doc_loaded'), xalign=0.0)
        status_bar_box.append(self.status_label)
        self.save_spinner = Gtk.Spinner()
        self.save_spinner.set_visible(False)
        status_bar_box.append(self.save_spinner)
        self.main_box.append(status_bar_box)

    def _create_sidebar(self):
        """Create sidebar."""
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                            margin_start=6, margin_end=6, margin_top=10, margin_bottom=6)
        sidebar_box.set_size_request(190, -1)

        tools_label = Gtk.Label(label=_("tools"), xalign=0.0)
        tools_label.add_css_class('title-4')
        sidebar_box.append(tools_label)

        tools_grid = Gtk.Grid(
            row_spacing=6, 
            column_spacing=6,
            column_homogeneous=True
        )
        
        def _make_tool_btn(icon_name, label_text, tooltip, tool_id):
            btn = Gtk.Button()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_halign(Gtk.Align.CENTER)
            img = Gtk.Image.new_from_icon_name(icon_name)
            lbl = Gtk.Label(label=label_text)
            box.append(img)
            box.append(lbl)
            btn.set_child(box)
            btn.set_tooltip_text(tooltip)
            btn.add_css_class("tool-button")
            btn.connect('clicked', self.on_tool_selected, tool_id)
            return btn

        self.select_tool_button = _make_tool_btn("input-mouse-symbolic", _("tool_select"), _("tool_select_tip"), "select")
        tools_grid.attach(self.select_tool_button, 0, 0, 1, 1)

        self.add_text_tool_button = _make_tool_btn("insert-text-symbolic", _("tool_add_text"), _("tool_add_text_tip"), "add_text")
        tools_grid.attach(self.add_text_tool_button, 1, 0, 1, 1)

        self.add_image_tool_button = _make_tool_btn("insert-image-symbolic", _("tool_add_image"), _("tool_add_image_tip"), "add_image")
        tools_grid.attach(self.add_image_tool_button, 0, 1, 1, 1)

        self.redact_tool_button = _make_tool_btn("edit-clear-symbolic", _("tool_redact"), _("tool_redact_tip"), "redact")
        tools_grid.attach(self.redact_tool_button, 1, 1, 1, 1)

        self.drag_tool_button = None

        self.add_ellipse_tool_button = _make_tool_btn("media-record-symbolic", _("tool_ellipse"), _("tool_ellipse_tip"), "add_ellipse")
        tools_grid.attach(self.add_ellipse_tool_button, 0, 2, 1, 1)

        self.add_rectangle_tool_button = _make_tool_btn("checkbox-symbolic", _("tool_rectangle"), _("tool_rectangle_tip"), "add_rectangle")
        tools_grid.attach(self.add_rectangle_tool_button, 1, 2, 1, 1)

        self.pen_tool_button = _make_tool_btn("document-edit-symbolic", _("tool_pen"), _("tool_pen_tip"), "pen")
        tools_grid.attach(self.pen_tool_button, 0, 3, 1, 1)

        self.highlighter_tool_button = _make_tool_btn("marker-symbolic", _("tool_highlighter"), _("tool_highlighter_tip"), "highlighter")
        tools_grid.attach(self.highlighter_tool_button, 1, 3, 1, 1)

        self.checkmark_tool_button = _make_tool_btn("emblem-ok-symbolic", _("tool_checkmark"), _("tool_checkmark_tip"), "add_checkmark")
        tools_grid.attach(self.checkmark_tool_button, 0, 4, 1, 1)

        self.cross_tool_button = _make_tool_btn("window-close-symbolic", _("tool_cross"), _("tool_cross_tip"), "add_cross")
        tools_grid.attach(self.cross_tool_button, 1, 4, 1, 1)

        self.form_builder_tool_button = _make_tool_btn("edit-select-all-symbolic", _("tool_form_builder"), _("tool_form_builder_tip"), "form_builder")
        tools_grid.attach(self.form_builder_tool_button, 0, 5, 1, 1)

        self.stamp_tool_button = _make_tool_btn("tag-symbolic", _("tool_stamp"), _("tool_stamp_tip"), "add_stamp")
        tools_grid.attach(self.stamp_tool_button, 1, 5, 1, 1)

        self.measure_distance_tool_button = _make_tool_btn("straighten-symbolic", _("tool_measure_distance"), _("tool_measure_distance_tip"), "measure_distance")
        tools_grid.attach(self.measure_distance_tool_button, 0, 6, 1, 1)

        self.measure_area_tool_button = _make_tool_btn("view-grid-symbolic", _("tool_measure_area"), _("tool_measure_area_tip"), "measure_area")
        tools_grid.attach(self.measure_area_tool_button, 1, 6, 1, 1)

        self.clone_patch_tool_button = _make_tool_btn("image-crop-symbolic", _("tool_clone_patch"), _("tool_clone_patch_tip"), "clone_patch")
        tools_grid.attach(self.clone_patch_tool_button, 0, 7, 1, 1)

        self.signature_tool_button = _make_tool_btn("channel-secure-symbolic", _("tool_place_signature"), _("tool_place_signature_tip"), "place_signature")
        tools_grid.attach(self.signature_tool_button, 1, 7, 1, 1)

        self.calibrate_tool_button = None
        self.stamp_menu_button = None
        
        sidebar_box.append(tools_grid)

        sidebar_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=6, margin_bottom=6))

        pages_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        thumbnails_label = Gtk.Label(label=_("pages_label"), xalign=0.0, hexpand=True)
        thumbnails_label.add_css_class('title-4')
        pages_header.append(thumbnails_label)

        self.rotate_page_ccw_button = Gtk.Button.new_from_icon_name("object-rotate-left-symbolic")
        self.rotate_page_ccw_button.set_tooltip_text(_("rotate_page_ccw_tip"))
        self.rotate_page_ccw_button.connect('clicked', lambda b: self.rotate_current_page(-90))
        self.rotate_page_ccw_button.add_css_class('flat')
        pages_header.append(self.rotate_page_ccw_button)

        self.rotate_page_cw_button = Gtk.Button.new_from_icon_name("object-rotate-right-symbolic")
        self.rotate_page_cw_button.set_tooltip_text(_("rotate_page_cw_tip"))
        self.rotate_page_cw_button.connect('clicked', lambda b: self.rotate_current_page(90))
        self.rotate_page_cw_button.add_css_class('flat')
        pages_header.append(self.rotate_page_cw_button)

        self.delete_page_button = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self.delete_page_button.set_tooltip_text(_("delete_page_tip"))
        self.delete_page_button.connect('clicked', self.on_delete_page)
        self.delete_page_button.add_css_class('flat')
        pages_header.append(self.delete_page_button)

        sidebar_box.append(pages_header)

        factory = PageThumbnailFactory(editor_window=self)
        self.thumbnail_selection_model = Gtk.SingleSelection(model=self.pages_model)
        self.thumbnail_selection_model.set_autoselect(False)
        self.thumbnail_selection_model.set_can_unselect(False)
        self.thumbnail_selection_model.connect("selection-changed", self.on_thumbnail_selected)

        self.thumbnails_list = Gtk.ListView.new(self.thumbnail_selection_model, factory)
        self.thumbnails_list.set_vexpand(True)

        self.thumbnails_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.thumbnails_scroll.set_child(self.thumbnails_list)
        self.thumbnails_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_box.append(self.thumbnails_scroll)

        self.paned.set_start_child(sidebar_box)

    def _create_main_toolbar(self):
        """Create main toolbar."""
        self.main_toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.main_toolbar.add_css_class('toolbar')

        self.toolbar_row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.toolbar_row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.main_toolbar.append(self.toolbar_row1)
        self.main_toolbar.append(self.toolbar_row2)

        zoom_out = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        zoom_out.set_tooltip_text(_("zoom_out_tip"))
        zoom_out.connect("clicked", self.on_zoom_out)
        self.zoom_label = Gtk.Label(label="100%")
        zoom_in = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        zoom_in.set_tooltip_text(_("zoom_in_tip"))
        zoom_in.connect("clicked", self.on_zoom_in)
        self.toolbar_row1.append(zoom_out)
        self.toolbar_row1.append(self.zoom_label)
        self.toolbar_row1.append(zoom_in)

        self.continuous_scroll_btn = Gtk.ToggleButton()
        self.continuous_scroll_btn.set_icon_name("view-continuous-symbolic" if self.continuous_scroll else "view-paged-symbolic")
        self.continuous_scroll_btn.set_tooltip_text(_("tooltip_continuous_scroll"))
        self.continuous_scroll_btn.set_active(self.continuous_scroll)
        self.continuous_scroll_btn.connect("toggled", lambda b: self.set_continuous_scroll_mode(b.get_active()))
        self.toolbar_row1.append(self.continuous_scroll_btn)

        self.ocr_overlay_btn = Gtk.ToggleButton()
        self.ocr_overlay_btn.set_icon_name("view-reveal-symbolic")
        self.ocr_overlay_btn.set_tooltip_text(_("tooltip_ocr_overlay"))
        self.ocr_overlay_btn.set_active(self.show_ocr_overlay)
        self.ocr_overlay_btn.connect("toggled", lambda b: self.set_ocr_overlay_mode(b.get_active()))
        self.toolbar_row1.append(self.ocr_overlay_btn)

        self.toolbar_row1.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6))

        self.prev_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.prev_button.set_tooltip_text(_("prev_page_tip"))
        self.prev_button.connect("clicked", self.on_prev_page)
        self.page_label = Gtk.Label(label=_("page_info_count").format(0, 0))
        self.next_button = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_button.set_tooltip_text(_("next_page_tip"))
        self.next_button.connect("clicked", self.on_next_page)
        self.add_page_button = Gtk.Button.new_from_icon_name("document-new-symbolic")
        self.add_page_button.set_tooltip_text(_("add_page_tip"))
        self.add_page_button.connect("clicked", self.on_add_page)
        self.toolbar_row1.append(self.prev_button)
        self.toolbar_row1.append(self.page_label)
        self.toolbar_row1.append(self.next_button)
        self.toolbar_row1.append(self.add_page_button)

        self.toolbar_row1.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6))

        self.symbols_button = Gtk.MenuButton()
        self.symbols_button.set_icon_name("face-smile-symbolic")
        self.symbols_button.set_tooltip_text(_("tooltip_symbols"))
        self.symbols_popover = SymbolsPopover(editor_window=self)
        self.symbols_button.set_popover(self.symbols_popover)
        self.toolbar_row1.append(self.symbols_button)

        self.text_format_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.text_format_sep)
        self.text_format_sep.set_visible(False)

        self.text_format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.font_store = Gtk.ListStore(str, str)
        self.font_store.append([_("font_loading"), ""])
        self.font_combo = Gtk.ComboBox(model=self.font_store)
        cell = Gtk.CellRendererText()
        self.font_combo.pack_start(cell, True)
        self.font_combo.add_attribute(cell, "text", 0)
        self.font_combo.set_active(0)
        self.font_combo.set_tooltip_text(_("font_tip"))
        self.font_combo.connect("changed", self.on_text_format_changed)
        self.font_combo.connect("notify::popup-shown", lambda *a: self._ensure_font_combo_populated())
        self.font_combo.set_sensitive(False)
        self.text_format_box.append(self.font_combo)

        self.font_size_spin = Gtk.SpinButton.new_with_range(6, 96, 1)
        self.font_size_spin.set_value(11)
        self.font_size_spin.set_tooltip_text(_("font_size_tip"))
        self.font_size_spin.connect("value-changed", self.on_text_format_changed)
        self.text_format_box.append(self.font_size_spin)

        self.bold_button = Gtk.ToggleButton(icon_name="format-text-bold-symbolic")
        self.bold_button.set_tooltip_text(_("bold_tip"))
        self.bold_button.connect("toggled", self.on_text_format_changed)
        self.text_format_box.append(self.bold_button)

        self.italic_button = Gtk.ToggleButton(icon_name="format-text-italic-symbolic")
        self.italic_button.set_tooltip_text(_("italic_tip"))
        self.italic_button.connect("toggled", self.on_text_format_changed)
        self.text_format_box.append(self.italic_button)

        self.underline_button = Gtk.ToggleButton(icon_name="format-text-underline-symbolic")
        self.underline_button.set_tooltip_text(_("underline_tip"))
        self.underline_button.connect("toggled", self.on_text_format_changed)
        self.text_format_box.append(self.underline_button)

        self.strikethrough_button = Gtk.ToggleButton(icon_name="format-text-strikethrough-symbolic")
        self.strikethrough_button.set_tooltip_text(_("strikethrough_tip"))
        self.strikethrough_button.connect("toggled", self.on_text_format_changed)
        self.text_format_box.append(self.strikethrough_button)

        align_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        align_box.add_css_class("linked")

        self.align_left_button = Gtk.ToggleButton(icon_name="format-justify-left-symbolic")
        self.align_left_button.set_tooltip_text(_("align_left_tip"))
        self.align_left_button.set_active(True)
        self.align_left_button.connect("toggled", self.on_text_format_changed)
        align_box.append(self.align_left_button)

        self.align_center_button = Gtk.ToggleButton(icon_name="format-justify-center-symbolic")
        self.align_center_button.set_tooltip_text(_("align_center_tip"))
        self.align_center_button.set_group(self.align_left_button)
        self.align_center_button.connect("toggled", self.on_text_format_changed)
        align_box.append(self.align_center_button)

        self.align_right_button = Gtk.ToggleButton(icon_name="format-justify-right-symbolic")
        self.align_right_button.set_tooltip_text(_("align_right_tip"))
        self.align_right_button.set_group(self.align_left_button)
        self.align_right_button.connect("toggled", self.on_text_format_changed)
        align_box.append(self.align_right_button)

        self.align_justify_button = Gtk.ToggleButton(icon_name="format-justify-fill-symbolic")
        self.align_justify_button.set_tooltip_text(_("align_justify_tip"))
        self.align_justify_button.set_group(self.align_left_button)
        self.align_justify_button.connect("toggled", self.on_text_format_changed)
        align_box.append(self.align_justify_button)

        self.text_format_box.append(align_box)

        self.color_button = Gtk.ColorButton()
        default_rgba = Gdk.RGBA()
        default_rgba.parse("black")
        self.color_button.set_rgba(default_rgba)
        self.color_button.set_tooltip_text(_("color_tip"))
        self.color_button.connect("color-set", self.on_text_format_changed)
        self.text_format_box.append(self.color_button)

        self.link_button = Gtk.Button.new_from_icon_name("insert-link-symbolic")
        self.link_button.set_tooltip_text(_("insert_link_tip"))
        self.link_button.connect("clicked", self.on_insert_edit_link_clicked)
        self.text_format_box.append(self.link_button)

        self.toolbar_row2.append(self.text_format_box)

        self.shape_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.shape_toolbar_sep)
        self.shape_toolbar_sep.set_visible(False)

        self.shape_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.shape_fill_button = Gtk.ColorButton()
        self.shape_fill_button.set_title(_("shape_fill_dialog_title"))
        fill_rgba = Gdk.RGBA()
        fill_rgba.parse("white")
        self.shape_fill_button.set_rgba(fill_rgba)
        self.shape_fill_button.set_tooltip_text(_("shape_fill_tip"))
        self.shape_fill_button.connect("color-set", self.on_shape_format_changed)
        self.shape_toolbar_box.append(self.shape_fill_button)

        self.shape_transparent_toggle = Gtk.ToggleButton(label=_("transparent_label"))
        self.shape_transparent_toggle.set_active(True)
        self.shape_transparent_toggle.set_tooltip_text(_("shape_transparent_tip"))
        self.shape_transparent_toggle.connect("toggled", self.on_shape_format_changed)
        self.shape_toolbar_box.append(self.shape_transparent_toggle)

        self.shape_stroke_button = Gtk.ColorButton()
        self.shape_stroke_button.set_title(_("shape_stroke_dialog_title"))
        stroke_rgba = Gdk.RGBA()
        stroke_rgba.parse("black")
        self.shape_stroke_button.set_rgba(stroke_rgba)
        self.shape_stroke_button.set_tooltip_text(_("shape_stroke_tip"))
        self.shape_stroke_button.connect("color-set", self.on_shape_format_changed)
        self.shape_toolbar_box.append(self.shape_stroke_button)

        self.shape_stroke_width_spin = Gtk.SpinButton.new_with_range(0.5, 10, 0.5)
        self.shape_stroke_width_spin.set_value(2.0)
        self.shape_stroke_width_spin.set_tooltip_text(_("shape_width_tip"))
        self.shape_stroke_width_spin.connect("value-changed", self.on_shape_format_changed)
        self.shape_toolbar_box.append(self.shape_stroke_width_spin)
        self.toolbar_row2.append(self.shape_toolbar_box)
        self.shape_toolbar_box.set_visible(False)

        self.stroke_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.stroke_toolbar_sep)
        self.stroke_toolbar_sep.set_visible(False)

        self.stroke_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.stroke_color_button = Gtk.ColorButton()
        self.stroke_color_button.set_tooltip_text(_("stroke_color_tip"))
        stroke_color_rgba = Gdk.RGBA()
        stroke_color_rgba.parse("black")
        self.stroke_color_button.set_rgba(stroke_color_rgba)
        self.stroke_color_button.connect("color-set", self.on_stroke_format_changed)
        self.stroke_toolbar_box.append(self.stroke_color_button)

        self.stroke_width_spin = Gtk.SpinButton.new_with_range(0.5, 40, 0.5)
        self.stroke_width_spin.set_value(2.0)
        self.stroke_width_spin.set_tooltip_text(_("stroke_width_tip"))
        self.stroke_width_spin.connect("value-changed", self.on_stroke_format_changed)
        self.stroke_toolbar_box.append(self.stroke_width_spin)
        self.toolbar_row2.append(self.stroke_toolbar_box)
        self.stroke_toolbar_box.set_visible(False)

        self.rotation_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.rotation_toolbar_sep)
        self.rotation_toolbar_sep.set_visible(False)

        self.rotation_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self.rotate_obj_ccw_button = Gtk.Button.new_from_icon_name("object-rotate-left-symbolic")
        self.rotate_obj_ccw_button.set_tooltip_text(_("rotate_obj_ccw_tip"))
        self.rotate_obj_ccw_button.connect("clicked", self.on_rotate_object_ccw_clicked)
        self.rotation_toolbar_box.append(self.rotate_obj_ccw_button)

        self.rotate_obj_cw_button = Gtk.Button.new_from_icon_name("object-rotate-right-symbolic")
        self.rotate_obj_cw_button.set_tooltip_text(_("rotate_obj_cw_tip"))
        self.rotate_obj_cw_button.connect("clicked", self.on_rotate_object_cw_clicked)
        self.rotation_toolbar_box.append(self.rotate_obj_cw_button)

        rot_adj = Gtk.Adjustment.new(0.0, 0.0, 360.0, 1.0, 15.0, 0.0)
        self.rotation_spin = Gtk.SpinButton(adjustment=rot_adj, climb_rate=1.0, digits=0)
        self.rotation_spin.set_wrap(True)
        self.rotation_spin.set_tooltip_text(_("rotation_angle_tip"))
        self.rotation_spin.connect("value-changed", self.on_object_rotation_spin_changed)
        self.rotation_toolbar_box.append(self.rotation_spin)

        rot_deg_lbl = Gtk.Label(label="°")
        rot_deg_lbl.add_css_class("dim-label")
        self.rotation_toolbar_box.append(rot_deg_lbl)

        self.rotate_obj_reset_button = Gtk.Button(label="0°")
        self.rotate_obj_reset_button.set_tooltip_text(_("rotation_reset_tip"))
        self.rotate_obj_reset_button.connect("clicked", self.on_rotate_object_reset_clicked)
        self.rotation_toolbar_box.append(self.rotate_obj_reset_button)

        self.toolbar_row2.append(self.rotation_toolbar_box)
        self.rotation_toolbar_box.set_visible(False)

        self.form_builder_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.form_builder_toolbar_sep)
        self.form_builder_toolbar_sep.set_visible(False)

        self.form_builder_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        fb_type_label = Gtk.Label(label=_("form_field_type_label"))
        self.form_builder_toolbar_box.append(fb_type_label)
        self.form_builder_type_dropdown = Gtk.DropDown.new_from_strings([
            _("field_type_text"),
            _("field_type_checkbox"),
            _("field_type_dropdown")
        ])
        self.form_builder_type_dropdown.connect("notify::selected", self._on_form_builder_type_changed)
        self.form_builder_toolbar_box.append(self.form_builder_type_dropdown)

        fb_name_label = Gtk.Label(label=_("form_field_name_label"))
        self.form_builder_toolbar_box.append(fb_name_label)
        self.form_builder_name_entry = Gtk.Entry()
        self.form_builder_name_entry.set_placeholder_text(_("form_field_name_placeholder"))
        self.form_builder_name_entry.set_tooltip_text(_("form_field_name_tip"))
        self.form_builder_name_entry.set_width_chars(12)
        self.form_builder_name_entry.connect("changed", self._on_form_builder_name_changed)
        self.form_builder_toolbar_box.append(self.form_builder_name_entry)

        self.form_builder_multiline_check = Gtk.CheckButton(label=_("form_field_multiline"))
        self.form_builder_multiline_check.set_tooltip_text(_("form_field_multiline_tip"))
        self.form_builder_multiline_check.connect("toggled", self._on_form_builder_multiline_toggled)
        self.form_builder_toolbar_box.append(self.form_builder_multiline_check)

        self.form_builder_add_label_check = Gtk.CheckButton(label=_("form_field_add_label"))
        self.form_builder_add_label_check.set_tooltip_text(_("form_field_add_label_tip"))
        self.form_builder_toolbar_box.append(self.form_builder_add_label_check)

        self.form_builder_label_entry = Gtk.Entry()
        self.form_builder_label_entry.set_placeholder_text(_("form_field_label_placeholder"))
        self.form_builder_label_entry.set_tooltip_text(_("form_field_add_label_tip"))
        self.form_builder_label_entry.set_width_chars(11)
        self.form_builder_toolbar_box.append(self.form_builder_label_entry)

        self.form_builder_options_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        fb_opt_label = Gtk.Label(label=_("form_field_options_label"))
        self.form_builder_options_box.append(fb_opt_label)
        self.form_builder_options_entry = Gtk.Entry()
        self.form_builder_options_entry.set_placeholder_text(_("form_field_options_placeholder"))
        self.form_builder_options_entry.set_tooltip_text(_("form_field_options_tip"))
        self.form_builder_options_entry.set_width_chars(16)
        self.form_builder_options_entry.connect("changed", self._on_form_builder_options_changed)
        self.form_builder_options_box.append(self.form_builder_options_entry)

        self.form_builder_edit_options_btn = Gtk.Button.new_from_icon_name("view-list-bullet-symbolic")
        self.form_builder_edit_options_btn.set_tooltip_text(_("form_field_edit_options"))
        self.form_builder_edit_options_btn.add_css_class("flat")
        self.form_builder_edit_options_btn.connect("clicked", self._on_form_builder_edit_options_clicked)
        self.form_builder_options_box.append(self.form_builder_edit_options_btn)

        self.form_builder_toolbar_box.append(self.form_builder_options_box)
        self.form_builder_options_box.set_visible(False)

        fb_del_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.form_builder_toolbar_box.append(fb_del_sep)

        self.form_builder_delete_button = Gtk.Button.new_from_icon_name("edit-delete-symbolic")
        self.form_builder_delete_button.set_tooltip_text(_("form_field_delete_tip"))
        self.form_builder_delete_button.add_css_class("flat")
        self.form_builder_delete_button.set_sensitive(False)
        self.form_builder_delete_button.connect("clicked", self._on_form_builder_delete_clicked)
        self.form_builder_toolbar_box.append(self.form_builder_delete_button)

        fb_hint_label = Gtk.Label(label=_("form_builder_hint"))
        fb_hint_label.add_css_class("dim-label")
        self.form_builder_toolbar_box.append(fb_hint_label)

        self.toolbar_row2.append(self.form_builder_toolbar_box)
        self.form_builder_toolbar_box.set_visible(False)

        self.calibration_toolbar_sep = None
        self.calibration_toolbar_box = None

        # Measurement Toolbar (Distance, Area & Calibration merged)
        self.measurement_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.measurement_toolbar_sep)
        self.measurement_toolbar_sep.set_visible(False)

        self.measurement_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        meas_lbl = Gtk.Label(label=_("measurement_toolbar_label"))
        meas_lbl.add_css_class("heading")
        self.measurement_toolbar_box.append(meas_lbl)

        self.measurement_scale_indicator = Gtk.Label(label=_("scale_uncalibrated"))
        self.measurement_scale_indicator.add_css_class("dim-label")
        self.measurement_toolbar_box.append(self.measurement_scale_indicator)
        self.calibration_scale_label = self.measurement_scale_indicator

        preset_strings = [_("scale_preset_custom")] + list(PRESET_SCALES.keys())
        self.calibration_preset_dropdown = Gtk.DropDown.new_from_strings(preset_strings)
        self.calibration_preset_dropdown.connect("notify::selected", self.on_calibration_preset_changed)
        self.measurement_toolbar_box.append(self.calibration_preset_dropdown)

        self.measurement_calibrate_btn = Gtk.Button(label=_("btn_calibrate"))
        self.measurement_calibrate_btn.add_css_class("flat")
        self.measurement_calibrate_btn.connect("clicked", self.on_calibrate_dialog_clicked)
        self.measurement_toolbar_box.append(self.measurement_calibrate_btn)
        self.calibrate_dialog_btn = self.measurement_calibrate_btn

        self.calibrate_reset_btn = Gtk.Button(label=_("btn_reset_scale"))
        self.calibrate_reset_btn.add_css_class("flat")
        self.calibrate_reset_btn.connect("clicked", self.on_calibration_reset_clicked)
        self.measurement_toolbar_box.append(self.calibrate_reset_btn)

        sep_m = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.measurement_toolbar_box.append(sep_m)

        self.measurement_hint_lbl = Gtk.Label(label="")
        self.measurement_hint_lbl.add_css_class("dim-label")
        self.measurement_toolbar_box.append(self.measurement_hint_lbl)

        sep_m2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.measurement_toolbar_box.append(sep_m2)

        self.measurement_clear_btn = Gtk.Button(label=_("btn_clear_measurements"))
        self.measurement_clear_btn.set_tooltip_text(_("btn_clear_measurements_tip"))
        self.measurement_clear_btn.add_css_class("flat")
        self.measurement_clear_btn.connect("clicked", self.on_clear_measurements_clicked)
        self.measurement_toolbar_box.append(self.measurement_clear_btn)

        self.toolbar_row2.append(self.measurement_toolbar_box)
        self.measurement_toolbar_box.set_visible(False)

        # Stamp Toolbar
        self.stamp_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row2.append(self.stamp_toolbar_sep)
        self.stamp_toolbar_sep.set_visible(False)

        self.stamp_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        stamp_title_lbl = Gtk.Label(label=_("tool_stamp"))
        stamp_title_lbl.add_css_class("heading")
        self.stamp_toolbar_box.append(stamp_title_lbl)

        self.stamp_toolbar_pic = Gtk.Picture()
        self.stamp_toolbar_pic.set_can_shrink(True)
        self.stamp_toolbar_pic.set_size_request(60, 24)
        self.stamp_toolbar_box.append(self.stamp_toolbar_pic)

        self.stamp_toolbar_name_lbl = Gtk.Label(label="")
        self.stamp_toolbar_name_lbl.add_css_class("bold")
        self.stamp_toolbar_box.append(self.stamp_toolbar_name_lbl)

        self.stamp_toolbar_lock_icon = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        self.stamp_toolbar_lock_icon.set_visible(False)
        self.stamp_toolbar_lock_icon.add_css_class("accent")
        self.stamp_toolbar_box.append(self.stamp_toolbar_lock_icon)

        self.stamp_popover = StampPopover(
            self.stamp_library,
            on_stamp_chosen_callback=self._on_stamp_chosen_from_popover,
            on_manage_clicked_callback=self.on_manage_stamps
        )
        self.stamp_quick_menu_btn = Gtk.MenuButton()
        self.stamp_quick_menu_btn.set_icon_name("tag-symbolic")
        self.stamp_quick_menu_btn.set_tooltip_text(_("stamp_quick_menu"))
        self.stamp_quick_menu_btn.set_popover(self.stamp_popover)
        self.stamp_toolbar_box.append(self.stamp_quick_menu_btn)

        self.stamp_library_btn = Gtk.Button(label=_("menu_manage_stamps"))
        self.stamp_library_btn.add_css_class("flat")
        self.stamp_library_btn.connect("clicked", self.on_manage_stamps)
        self.stamp_toolbar_box.append(self.stamp_library_btn)

        sep_s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.stamp_toolbar_box.append(sep_s)

        stamp_hint_lbl = Gtk.Label(label=_("tool_stamp_tip"))
        stamp_hint_lbl.add_css_class("dim-label")
        self.stamp_toolbar_box.append(stamp_hint_lbl)

        self.toolbar_row2.append(self.stamp_toolbar_box)
        self.stamp_toolbar_box.set_visible(False)

        # Redaction secondary toolbar
        self.redaction_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_redact = Gtk.Label(label=_("redaction_toolbar_label"))
        lbl_redact.add_css_class("heading")
        self.redaction_toolbar_box.append(lbl_redact)

        btn_fill_black = Gtk.Button(label=_("color_black"))
        btn_fill_black.add_css_class("flat")
        btn_fill_black.add_css_class("suggested-action")
        btn_fill_white = Gtk.Button(label=_("color_white"))
        btn_fill_white.add_css_class("flat")

        def _on_default_fill_black(b):
            self.redact_default_fill = (0.0, 0.0, 0.0)
            self.redact_default_text_color = (1.0, 1.0, 1.0)
            btn_fill_black.add_css_class("suggested-action")
            btn_fill_white.remove_css_class("suggested-action")

        def _on_default_fill_white(b):
            self.redact_default_fill = (1.0, 1.0, 1.0)
            self.redact_default_text_color = (0.0, 0.0, 0.0)
            btn_fill_white.add_css_class("suggested-action")
            btn_fill_black.remove_css_class("suggested-action")

        btn_fill_black.connect("clicked", _on_default_fill_black)
        btn_fill_white.connect("clicked", _on_default_fill_white)
        self.redaction_toolbar_box.append(btn_fill_black)
        self.redaction_toolbar_box.append(btn_fill_white)

        sep_r1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.redaction_toolbar_box.append(sep_r1)

        preset_strings_tb = [
            _("redaction_mark") + " ([REDACTED])",
            "CONFIDENTIAL",
            "FOIA Exemption (b)(4)",
            "FOIA Exemption (b)(6)",
            "FOIA Exemption (b)(7)(C)",
            "PRIVILEGED & CONFIDENTIAL",
            "[None] (Solid)",
        ]
        dd_preset = Gtk.DropDown.new_from_strings(preset_strings_tb)
        def _on_toolbar_preset(dd, param):
            idx = dd.get_selected()
            if 0 <= idx < len(RedactionInspectorPopover.PRESET_CODES):
                self.redact_default_overlay = RedactionInspectorPopover.PRESET_CODES[idx]
        dd_preset.connect("notify::selected", _on_toolbar_preset)
        self.redaction_toolbar_box.append(dd_preset)

        sep_r2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.redaction_toolbar_box.append(sep_r2)

        self.redaction_apply_button = Gtk.Button(label=_("redaction_btn_apply"))
        self.redaction_apply_button.add_css_class("destructive-action")
        self.redaction_apply_button.set_tooltip_text(_("redaction_warning_title"))
        self.redaction_apply_button.connect("clicked", lambda b: self.apply_all_redactions(prompt_warning=True))
        self.redaction_apply_button.set_sensitive(False)
        self.redaction_toolbar_box.append(self.redaction_apply_button)

        sep_r3 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.redaction_toolbar_box.append(sep_r3)

        self.btn_find_redact = Gtk.Button(label=_("redaction_find_and_redact"))
        self.btn_find_redact.set_tooltip_text(_("redaction_find_and_redact_tip"))
        self.btn_find_redact.connect("clicked", lambda b: self.on_find_and_redact())
        self.redaction_toolbar_box.append(self.btn_find_redact)

        sep_r4 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        self.redaction_toolbar_box.append(sep_r4)

        self.btn_sanitize_doc = Gtk.Button(label=_("menu_sanitize_document"))
        self.btn_sanitize_doc.set_tooltip_text(_("sanitize_dialog_title"))
        self.btn_sanitize_doc.connect("clicked", lambda b: self.on_sanitize_document())
        self.redaction_toolbar_box.append(self.btn_sanitize_doc)

        self.toolbar_row2.append(self.redaction_toolbar_box)
        self.redaction_toolbar_box.set_visible(False)

        self.view_toolbar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6)
        self.toolbar_row1.append(self.view_toolbar_sep)
        self.view_toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        
        self.highlight_color_button = Gtk.ColorButton()
        hl_rgba = Gdk.RGBA()
        hl_rgba.parse("yellow")
        self.highlight_color_button.set_rgba(hl_rgba)
        self.highlight_color_button.set_tooltip_text(_("highlight_color_tip"))
        self.view_toolbar_box.append(self.highlight_color_button)
        
        def _make_icon_label_btn(icon_name, label_text, tooltip, callback):
            btn = Gtk.Button()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            img = Gtk.Image.new_from_icon_name(icon_name)
            lbl = Gtk.Label(label=label_text)
            box.append(img)
            box.append(lbl)
            btn.set_child(box)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", callback)
            return btn

        self.highlight_button = _make_icon_label_btn("marker-symbolic", _("highlight"), _("highlight_tip"), self.on_highlight_clicked)
        self.view_toolbar_box.append(self.highlight_button)
        
        self.remove_highlight_button = _make_icon_label_btn("edit-clear-symbolic", _("remove_highlight"), _("remove_highlight_tip"), self.on_remove_highlight_clicked)
        self.view_toolbar_box.append(self.remove_highlight_button)

        self.view_sticky_note_btn = Gtk.ToggleButton()
        sn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sn_img = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        sn_lbl = Gtk.Label(label=_("tool_sticky_note"))
        sn_box.append(sn_img)
        sn_box.append(sn_lbl)
        self.view_sticky_note_btn.set_child(sn_box)
        self.view_sticky_note_btn.set_tooltip_text(_("tool_sticky_note_tip"))
        self.view_sticky_note_btn.add_css_class("tool-button")
        self.view_sticky_note_btn.connect("toggled", self.on_view_sticky_note_toggled)
        self.view_toolbar_box.append(self.view_sticky_note_btn)

        self.toolbar_row1.append(self.view_toolbar_box)
        self.view_toolbar_box.set_visible(False)
        self.view_toolbar_sep.set_visible(False)

        # View Mode Secondary Toolbar in row 2
        self.view_mode_secondary_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.toolbar_row2.append(self.view_mode_secondary_toolbar)
        self.view_mode_secondary_toolbar.set_visible(False)

    def _setup_controllers(self):
        """Setup controllers."""
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect('drop', self.on_drop)
        self.add_controller(drop_target)

        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect('scroll', self.on_scroll_zoom)
        self.pdf_view.add_controller(scroll_controller)

        # Touchpad and touchscreen fluid pinch-to-zoom gesture
        pinch_zoom = Gtk.GestureZoom.new()
        pinch_zoom.connect("begin", self._on_pinch_zoom_begin)
        pinch_zoom.connect("scale-changed", self._on_pinch_zoom_scale_changed)
        pinch_zoom.connect("end", self._on_pinch_zoom_end)
        pinch_zoom.connect("cancel", self._on_pinch_zoom_cancel)
        self.pdf_view.add_controller(pinch_zoom)

        motion_controller = Gtk.EventControllerMotion.new()
        motion_controller.connect('motion', self._on_pointer_motion)
        self.pdf_view.add_controller(motion_controller)

        click_controller = Gtk.GestureClick.new()
        click_controller.connect('pressed', self.on_pdf_view_pressed)
        click_controller.connect('released', self._on_pdf_view_released)
        self.pdf_view.add_controller(click_controller)

        right_click_controller = Gtk.GestureClick.new()
        right_click_controller.set_button(3)
        right_click_controller.connect('pressed', self._on_right_click)
        self.pdf_view.add_controller(right_click_controller)

        middle_click_controller = Gtk.GestureClick.new()
        middle_click_controller.set_button(2)
        middle_click_controller.connect('pressed', self._on_middle_click)
        self.pdf_view.add_controller(middle_click_controller)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect('key-pressed', self.on_key_pressed)
        self.add_controller(key_controller)

        drag_controller = Gtk.GestureDrag.new()
        drag_controller.set_button(Gdk.BUTTON_PRIMARY)
        drag_controller.connect("drag-begin", self.on_drag_begin)
        drag_controller.connect("drag-update", self.on_drag_update)
        drag_controller.connect("drag-end", self.on_drag_end)
        self.pdf_view.add_controller(drag_controller)

        thumbnail_drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        thumbnail_drop.connect('drop', self.on_thumbnail_drop)
        self.thumbnails_list.add_controller(thumbnail_drop)

    def _on_undo_activated(self, *args):
        """Undo either in the currently active text editor widget or the document undo manager."""
        if getattr(self, 'inline_editor_tv', None) is not None:
            buf = self.inline_editor_tv.get_buffer()
            if hasattr(buf, 'can_undo') and buf.can_undo():
                buf.undo()
                return
            elif hasattr(buf, 'undo'):
                buf.undo()
                return
            return

        focus_w = self.get_focus()
        if isinstance(focus_w, Gtk.TextView):
            buf = focus_w.get_buffer()
            if hasattr(buf, 'can_undo') and buf.can_undo():
                buf.undo()
                return
            elif hasattr(buf, 'undo'):
                buf.undo()
                return
            return
        elif isinstance(focus_w, Gtk.Editable):
            return

        if hasattr(self, 'undo_manager') and self.undo_manager:
            self.undo_manager.undo()

    def _on_redo_activated(self, *args):
        """Redo either in the currently active text editor widget or the document undo manager."""
        if getattr(self, 'inline_editor_tv', None) is not None:
            buf = self.inline_editor_tv.get_buffer()
            if hasattr(buf, 'can_redo') and buf.can_redo():
                buf.redo()
                return
            elif hasattr(buf, 'redo'):
                buf.redo()
                return
            return

        focus_w = self.get_focus()
        if isinstance(focus_w, Gtk.TextView):
            buf = focus_w.get_buffer()
            if hasattr(buf, 'can_redo') and buf.can_redo():
                buf.redo()
                return
            elif hasattr(buf, 'redo'):
                buf.redo()
                return
            return
        elif isinstance(focus_w, Gtk.Editable):
            return

        if hasattr(self, 'undo_manager') and self.undo_manager:
            self.undo_manager.redo()

    def _connect_actions(self):
        """Connect actions."""
        action_save_as = Gio.SimpleAction.new('save_as', None)
        action_save_as.connect('activate', self.on_save_as)
        self.add_action(action_save_as)

        action_compress = Gio.SimpleAction.new('compress_document', None)
        action_compress.connect('activate', self.on_compress_document_clicked)
        self.add_action(action_compress)

        action_protect = Gio.SimpleAction.new('protect_document', None)
        action_protect.connect('activate', self.on_protect_document_clicked)
        self.add_action(action_protect)

        action_sign = Gio.SimpleAction.new('digitally_sign_document', None)
        action_sign.connect('activate', self.on_sign_pdf_clicked)
        self.add_action(action_sign)

        action_inspect_sig = Gio.SimpleAction.new('inspect_digital_signatures', None)
        action_inspect_sig.connect('activate', self.on_inspect_digital_signatures)
        self.add_action(action_inspect_sig)

        action_merge = Gio.SimpleAction.new('merge_documents', None)
        action_merge.connect('activate', self.on_merge_documents)
        self.add_action(action_merge)

        action_flatten = Gio.SimpleAction.new('flatten_annotations', None)
        action_flatten.connect('activate', self.on_flatten_annotations)
        self.add_action(action_flatten)

        action_sanitize = Gio.SimpleAction.new('sanitize_document', None)
        action_sanitize.connect('activate', self.on_sanitize_document)
        self.add_action(action_sanitize)

        action_ocr = Gio.SimpleAction.new('ocr_document', None)
        action_ocr.connect('activate', self.on_ocr_document)
        self.add_action(action_ocr)

        action_manage_stamps = Gio.SimpleAction.new('manage_stamps', None)
        action_manage_stamps.connect('activate', self.on_manage_stamps)
        self.add_action(action_manage_stamps)

        action_export_as = Gio.SimpleAction.new('export_as', None)
        action_export_as.connect('activate', self.on_export_as)
        self.add_action(action_export_as)

        for fmt in ("docx", "pptx", "odt", "odp", "txt"):
            act = Gio.SimpleAction.new(f"export_{fmt}", None)
            act.connect("activate", getattr(self, f"on_export_{fmt}"))
            self.add_action(act)

        action_print = Gio.SimpleAction.new('print', None)
        action_print.connect('activate', self.on_print_activated)
        self.add_action(action_print)

        action_about = Gio.SimpleAction.new('about', None)
        action_about.connect('activate', self.on_about_activated)
        self.add_action(action_about)

        action_new = Gio.SimpleAction.new('new', None)
        action_new.connect('activate', lambda a, p: self.on_new_clicked(None))
        self.add_action(action_new)

        action_open = Gio.SimpleAction.new('open', None)
        action_open.connect('activate', lambda a, p: self.on_open_clicked(None))
        self.add_action(action_open)

        action_quick_guide = Gio.SimpleAction.new('quick_guide', None)
        action_quick_guide.connect('activate', self._on_quick_guide_activated)
        self.add_action(action_quick_guide)

        action_save = Gio.SimpleAction.new('save', None)
        action_save.connect('activate', lambda a, p: self.on_save_clicked(None))
        self.add_action(action_save)

        action_undo = Gio.SimpleAction.new("undo", None)
        action_undo.connect("activate", lambda a, p: self._on_undo_activated())
        self.add_action(action_undo)

        action_redo = Gio.SimpleAction.new("redo", None)
        action_redo.connect("activate", lambda a, p: self._on_redo_activated())
        self.add_action(action_redo)

        current_confirm = bool(get_setting("confirm_delete_objects", True))
        self.action_confirm_delete = Gio.SimpleAction.new_stateful(
            'confirm_delete', None, GLib.Variant.new_boolean(current_confirm)
        )
        def on_confirm_delete_change(action, value):
            new_val = value.get_boolean()
            action.set_state(value)
            set_setting("confirm_delete_objects", new_val)
        self.action_confirm_delete.connect('change-state', on_confirm_delete_change)
        self.add_action(self.action_confirm_delete)

        current_lang = get_language()
        self.action_change_language = Gio.SimpleAction.new_stateful(
            'change_language', GLib.VariantType.new('s'), GLib.Variant.new_string(current_lang)
        )
        def on_change_language_activate(action, value):
            new_lang = value.get_string()
            self.request_language_change(new_lang)
        self.action_change_language.connect('activate', on_change_language_activate)
        self.add_action(self.action_change_language)

        action_close_tab = Gio.SimpleAction.new('close_tab', None)
        action_close_tab.connect('activate', self.on_close_tab)
        self.add_action(action_close_tab)

        action_next_tab = Gio.SimpleAction.new('next_tab', None)
        action_next_tab.connect('activate', self.on_next_tab)
        self.add_action(action_next_tab)

        action_prev_tab = Gio.SimpleAction.new('prev_tab', None)
        action_prev_tab.connect('activate', self.on_prev_tab)
        self.add_action(action_prev_tab)

        action_toggle_annots = Gio.SimpleAction.new('toggle_annotations', None)
        action_toggle_annots.connect('activate', lambda a, p: self.toggle_annotations_sidebar())
        self.add_action(action_toggle_annots)

        action_toggle_continuous = Gio.SimpleAction.new_stateful(
            'toggle_continuous_scroll',
            None,
            GLib.Variant.new_boolean(self.continuous_scroll)
        )
        def on_toggle_continuous_activate(action, value):
            new_val = not action.get_state().get_boolean()
            self.set_continuous_scroll_mode(new_val)
        action_toggle_continuous.connect('activate', on_toggle_continuous_activate)
        self.add_action(action_toggle_continuous)

        action_toggle_ocr_overlay = Gio.SimpleAction.new_stateful(
            'toggle_ocr_overlay',
            None,
            GLib.Variant.new_boolean(self.show_ocr_overlay)
        )
        def on_toggle_ocr_overlay_activate(action, value):
            new_val = not action.get_state().get_boolean()
            self.set_ocr_overlay_mode(new_val)
        action_toggle_ocr_overlay.connect('activate', on_toggle_ocr_overlay_activate)
        self.add_action(action_toggle_ocr_overlay)

        action_toggle_eco = Gio.SimpleAction.new_stateful(
            'toggle_eco_mode',
            None,
            GLib.Variant.new_boolean(getattr(self, 'is_eco_mode', False))
        )
        def on_toggle_eco_activate(action, value):
            new_val = not action.get_state().get_boolean()
            self.set_eco_mode(new_val)
        action_toggle_eco.connect('activate', on_toggle_eco_activate)
        self.add_action(action_toggle_eco)

        action_go_to_page = Gio.SimpleAction.new('go_to_page', None)
        action_go_to_page.connect('activate', lambda a, p: self.show_go_to_page_dialog())
        self.add_action(action_go_to_page)

        action_find = Gio.SimpleAction.new('find', None)
        action_find.connect('activate', lambda a, p: self.toggle_search_bar())
        self.add_action(action_find)

        app = self.get_application()
        if app:
            app.set_accels_for_action("win.find", ["<Control>f"])
            app.set_accels_for_action("win.new", ["<Control>n"])
            app.set_accels_for_action("win.open", ["<Control>o"])
            app.set_accels_for_action("win.close_tab", ["<Control>w"])
            app.set_accels_for_action("win.next_tab", ["<Control>Page_Down", "<Control>Tab"])
            app.set_accels_for_action("win.prev_tab", ["<Control>Page_Up", "<Control><Shift>Tab", "<Control><Shift>ISO_Left_Tab"])
            app.set_accels_for_action("win.save", ["<Control>s"])
            app.set_accels_for_action("win.save_as", ["<Control><Shift>s"])
            app.set_accels_for_action("win.merge_documents", ["<Control><Shift>m"])
            app.set_accels_for_action("win.undo", ["<Control>z"])
            app.set_accels_for_action("win.redo", ["<Control>y", "<Control><Shift>z"])
            app.set_accels_for_action("win.print", ["<Control>p"])
            app.set_accels_for_action("win.quick_guide", ["F1"])
            app.set_accels_for_action("win.toggle_annotations", ["F7"])
            app.set_accels_for_action("win.toggle_continuous_scroll", ["<Control><Shift>c"])
            app.set_accels_for_action("win.toggle_ocr_overlay", ["<Control><Shift>u"])
            app.set_accels_for_action("win.go_to_page", ["<Control>g"])
            app.set_accels_for_action("win.rotate_page_cw", ["<Control><Shift>r"])
            app.set_accels_for_action("win.rotate_page_ccw", ["<Control><Shift>l"])
            app.set_accels_for_action("win.bring_to_front", ["<Control><Shift>bracketright"])
            app.set_accels_for_action("win.send_to_back", ["<Control><Shift>bracketleft"])
            app.set_accels_for_action("win.bring_forward", ["<Control>bracketright"])
            app.set_accels_for_action("win.send_backward", ["<Control>bracketleft"])

        action_rotate_cw = Gio.SimpleAction.new('rotate_page_cw', None)
        action_rotate_cw.connect('activate', lambda a, p: self.rotate_current_page(90))
        self.add_action(action_rotate_cw)

        action_rotate_ccw = Gio.SimpleAction.new('rotate_page_ccw', None)
        action_rotate_ccw.connect('activate', lambda a, p: self.rotate_current_page(-90))
        self.add_action(action_rotate_ccw)

        action_bring_front = Gio.SimpleAction.new('bring_to_front', None)
        action_bring_front.connect('activate', lambda a, p: self.reorder_selected_object("front"))
        self.add_action(action_bring_front)

        action_send_back = Gio.SimpleAction.new('send_to_back', None)
        action_send_back.connect('activate', lambda a, p: self.reorder_selected_object("back"))
        self.add_action(action_send_back)

        action_bring_fwd = Gio.SimpleAction.new('bring_forward', None)
        action_bring_fwd.connect('activate', lambda a, p: self.reorder_selected_object("forward"))
        self.add_action(action_bring_fwd)

        action_send_bkwd = Gio.SimpleAction.new('send_backward', None)
        action_send_bkwd.connect('activate', lambda a, p: self.reorder_selected_object("backward"))
        self.add_action(action_send_bkwd)

    def _update_ui_state(self):
        """Update UI state."""
        has_doc = self.doc is not None
        page_count = pdf_handler.get_page_count(self.doc) if self.doc else 0
        has_pages = page_count > 0
        can_go_prev = has_pages and self.current_page_index > 0
        can_go_next = has_pages and self.current_page_index < page_count - 1

        self.save_button.set_sensitive(has_doc and self.document_modified)
        if self.lookup_action("save"):
            self.lookup_action("save").set_enabled(has_doc and self.document_modified)
        if self.lookup_action("save_as"):
            self.lookup_action("save_as").set_enabled(has_doc)
        for act_name in ("export_as", "export_docx", "export_pptx", "export_odt", "export_odp", "export_txt"):
            act = self.lookup_action(act_name)
            if act:
                act.set_enabled(has_doc)
        if self.lookup_action("print"):
            self.lookup_action("print").set_enabled(has_doc)

        doc_actions = (
            "compress_document",
            "protect_document",
            "digitally_sign_document",
            "inspect_digital_signatures",
            "flatten_annotations",
            "sanitize_document",
            "ocr_document",
            "find",
            "toggle_annotations",
            "close_tab",
        )
        for act_name in doc_actions:
            act = self.lookup_action(act_name)
            if act:
                act.set_enabled(has_doc)

        has_multiple_tabs = len(getattr(self, "sessions", [])) > 1
        for tab_act_name in ("next_tab", "prev_tab"):
            tab_act = self.lookup_action(tab_act_name)
            if tab_act:
                tab_act.set_enabled(has_multiple_tabs)

        if hasattr(self, 'toggle_annotations_button') and self.toggle_annotations_button:
            self.toggle_annotations_button.set_sensitive(has_doc)

        can_undo = has_doc and bool(getattr(self.undo_manager, "undo_stack", []))
        can_redo = has_doc and bool(getattr(self.undo_manager, "redo_stack", []))
        if hasattr(self, 'undo_button') and self.undo_button:
            self.undo_button.set_sensitive(can_undo)
        if hasattr(self, 'redo_button') and self.redo_button:
            self.redo_button.set_sensitive(can_redo)
        if self.lookup_action("undo"):
            self.lookup_action("undo").set_enabled(can_undo)
        if self.lookup_action("redo"):
            self.lookup_action("redo").set_enabled(can_redo)

        self.print_button.set_sensitive(has_doc)
        if hasattr(self, 'search_button') and self.search_button:
            self.search_button.set_sensitive(has_doc)
        self.prev_button.set_sensitive(can_go_prev)
        self.next_button.set_sensitive(can_go_next)
        if hasattr(self, 'page_label') and self.page_label:
            self.update_page_label()

        in_edit = not self.view_mode
        if hasattr(self, 'mode_toggle_button'):
            self.mode_toggle_button.set_sensitive(has_doc)
            if self.view_mode:
                self.mode_toggle_button.set_label(_("mode_edit"))
            else:
                self.mode_toggle_button.set_label(_("mode_view"))

        sidebar_tools = [self.select_tool_button, self.add_text_tool_button,
                         self.add_image_tool_button, self.drag_tool_button,
                         self.add_ellipse_tool_button, self.add_rectangle_tool_button,
                         self.pen_tool_button, self.highlighter_tool_button,
                         getattr(self, 'checkmark_tool_button', None),
                         getattr(self, 'cross_tool_button', None),
                         getattr(self, 'form_builder_tool_button', None),
                         getattr(self, 'stamp_tool_button', None),
                         getattr(self, 'measure_distance_tool_button', None),
                         getattr(self, 'measure_area_tool_button', None),
                         getattr(self, 'clone_patch_tool_button', None),
                         getattr(self, 'signature_tool_button', None),
                         getattr(self, 'redact_tool_button', None)]
        for btn in sidebar_tools:
            if btn:
                btn.set_sensitive(in_edit and has_doc)
            
        if hasattr(self, 'add_page_button'):
            self.add_page_button.set_sensitive(in_edit and has_doc)

        if hasattr(self, 'rotate_page_cw_button'):
            self.rotate_page_cw_button.set_sensitive(has_doc and has_pages)
        if hasattr(self, 'rotate_page_ccw_button'):
            self.rotate_page_ccw_button.set_sensitive(has_doc and has_pages)
        if self.lookup_action("rotate_page_cw"):
            self.lookup_action("rotate_page_cw").set_enabled(has_doc and has_pages)
        if self.lookup_action("rotate_page_ccw"):
            self.lookup_action("rotate_page_ccw").set_enabled(has_doc and has_pages)

        if hasattr(self, 'delete_page_button'):
            self.delete_page_button.set_sensitive(in_edit and has_doc and page_count > 1)

        if hasattr(self, 'symbols_button'):
            self.symbols_button.set_sensitive(in_edit and has_doc)

        shape_selected = self.selected_shape is not None
        stroke_selected = getattr(self, 'selected_stroke', None) is not None
        text_selected = self.selected_text is not None
        meas_selected = getattr(self, 'selected_measurement', None) is not None
        shape_controls_active = in_edit and (shape_selected or self.tool_mode in ("add_ellipse", "add_rectangle", "add_checkmark", "add_cross"))
        stroke_controls_active = in_edit and (stroke_selected or self.tool_mode in ("pen", "highlighter"))
        form_builder_active = in_edit and (self.tool_mode == "form_builder")
        calibrate_active = in_edit and (self.tool_mode == "calibrate")
        measure_active = in_edit and (self.tool_mode in ("measure_distance", "measure_area", "calibrate") or meas_selected)
        stamp_active = in_edit and (self.tool_mode == "add_stamp" or (getattr(self, 'selected_image', None) and getattr(self.selected_image, 'is_stamp', False)))
        view_text_selected = self.view_mode and (getattr(self, 'view_sel_rect', None) is not None or getattr(self, 'selected_word', None) is not None)
        format_enabled_base = in_edit and ((text_selected or self.tool_mode == "add_text") and
                               self.selected_image is None and not shape_selected and not stroke_selected and not form_builder_active and not calibrate_active and not measure_active and not stamp_active)

        if hasattr(self, 'toolbar_row2'):
            self.toolbar_row2.set_visible(has_doc)

        if hasattr(self, 'view_mode_secondary_toolbar') and self.view_mode_secondary_toolbar:
            self.view_mode_secondary_toolbar.set_visible(self.view_mode and has_doc)
            if hasattr(self, 'view_sticky_note_btn') and self.view_sticky_note_btn:
                self.view_sticky_note_btn.set_sensitive(has_doc)

        if hasattr(self, 'form_builder_toolbar_box'):
            self.form_builder_toolbar_box.set_visible(form_builder_active)
            self.form_builder_toolbar_sep.set_visible(form_builder_active)
            self.form_builder_type_dropdown.set_sensitive(has_doc)
            self.form_builder_name_entry.set_sensitive(has_doc)
            self.form_builder_multiline_check.set_sensitive(has_doc)
            if hasattr(self, 'form_builder_add_label_check') and self.form_builder_add_label_check:
                self.form_builder_add_label_check.set_sensitive(has_doc)
            if hasattr(self, 'form_builder_label_entry') and self.form_builder_label_entry:
                self.form_builder_label_entry.set_sensitive(has_doc)
            if hasattr(self, 'form_builder_delete_button') and self.form_builder_delete_button:
                self.form_builder_delete_button.set_sensitive(has_doc and getattr(self, 'selected_form_field', None) is not None)
            if hasattr(self, '_update_form_field_overlay_interactivity'):
                self._update_form_field_overlay_interactivity()

        if hasattr(self, 'measurement_toolbar_box') and self.measurement_toolbar_box:
            self.measurement_toolbar_box.set_visible(measure_active)
            if hasattr(self, 'measurement_toolbar_sep') and self.measurement_toolbar_sep:
                self.measurement_toolbar_sep.set_visible(measure_active)
            if measure_active:
                self._update_measurement_controls()

        if hasattr(self, 'stamp_toolbar_box') and self.stamp_toolbar_box:
            self.stamp_toolbar_box.set_visible(stamp_active)
            if hasattr(self, 'stamp_toolbar_sep') and self.stamp_toolbar_sep:
                self.stamp_toolbar_sep.set_visible(stamp_active)
            if stamp_active:
                self._update_stamp_controls()

        redact_active = (getattr(self, 'tool_mode', None) == "redact")
        if hasattr(self, 'redaction_toolbar_box') and self.redaction_toolbar_box:
            self.redaction_toolbar_box.set_visible(redact_active)
            if redact_active:
                self._update_redaction_controls()

        if hasattr(self, 'text_format_box'):
            self.text_format_box.set_visible(in_edit and not shape_controls_active and not stroke_controls_active and not form_builder_active and not calibrate_active and not measure_active and not stamp_active and not redact_active and self.selected_image is None)
            self.text_format_sep.set_visible(False)

        self.font_combo.set_sensitive(format_enabled_base and not self.font_scan_in_progress)
        self.font_size_spin.set_sensitive(format_enabled_base)
        self.color_button.set_sensitive(format_enabled_base)
        if self.bold_button: self.bold_button.set_sensitive(format_enabled_base)
        if self.italic_button: self.italic_button.set_sensitive(format_enabled_base)
        if hasattr(self, 'underline_button') and self.underline_button:
            self.underline_button.set_sensitive(format_enabled_base)
        if hasattr(self, 'strikethrough_button') and self.strikethrough_button:
            self.strikethrough_button.set_sensitive(format_enabled_base)
        for btn in [getattr(self, 'align_left_button', None), getattr(self, 'align_center_button', None),
                    getattr(self, 'align_right_button', None), getattr(self, 'align_justify_button', None)]:
            if btn: btn.set_sensitive(format_enabled_base)

        if hasattr(self, 'shape_toolbar_box'):
            self.shape_toolbar_box.set_visible(shape_controls_active)
            self.shape_toolbar_sep.set_visible(False)

        self.shape_fill_button.set_sensitive(shape_controls_active)
        self.shape_stroke_button.set_sensitive(shape_controls_active)
        self.shape_stroke_width_spin.set_sensitive(shape_controls_active)
        self.shape_transparent_toggle.set_sensitive(shape_controls_active)

        if hasattr(self, 'stroke_toolbar_box'):
            self.stroke_toolbar_box.set_visible(stroke_controls_active)
            self.stroke_toolbar_sep.set_visible(False)

        if hasattr(self, 'stroke_color_button'):
            self.stroke_color_button.set_sensitive(stroke_controls_active)
        if hasattr(self, 'stroke_width_spin'):
            self.stroke_width_spin.set_sensitive(stroke_controls_active)

        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        has_selected_obj = in_edit and (selected_obj is not None)

        if hasattr(self, 'rotation_toolbar_box'):
            self.rotation_toolbar_box.set_visible(has_selected_obj)
            self.rotation_toolbar_sep.set_visible(has_selected_obj)
            self.rotation_toolbar_box.set_sensitive(has_selected_obj)
            self._update_rotation_controls(selected_obj)

        if hasattr(self, 'view_toolbar_box'):
            self.view_toolbar_box.set_visible(has_doc)
            self.view_toolbar_sep.set_visible(has_doc)
            
            can_highlight = False
            if self.view_mode:
                can_highlight = self.view_sel_rect is not None
            else:
                can_highlight = self.selected_text is not None
                
            if hasattr(self, 'highlight_button'):
                self.highlight_button.set_sensitive(can_highlight)
            if hasattr(self, 'remove_highlight_button'):
                self.remove_highlight_button.set_sensitive(can_highlight)
            if hasattr(self, 'highlight_color_button'):
                self.highlight_color_button.set_sensitive(can_highlight)

        if shape_selected:
            self.shape_transparent_toggle.handler_block_by_func(self.on_shape_format_changed)
            self.shape_transparent_toggle.set_active(self.selected_shape.is_transparent)
            self.shape_transparent_toggle.handler_unblock_by_func(self.on_shape_format_changed)

        if text_selected:
            self._update_text_format_controls(self.selected_text)
        elif not self.inline_editor_widget:
            self._update_text_format_controls(None)

        if shape_selected:
            self._update_shape_format_controls(self.selected_shape)
        else:
            self._update_shape_format_controls(None)

        if stroke_selected:
            self._update_stroke_format_controls(self.selected_stroke)
        elif stroke_controls_active:
            self._update_stroke_format_controls(None)

        self.select_tool_button.get_style_context().remove_class('active')
        self.add_text_tool_button.get_style_context().remove_class('active')
        self.add_image_tool_button.get_style_context().remove_class('active')
        if getattr(self, 'drag_tool_button', None):
            self.drag_tool_button.get_style_context().remove_class('active')
        self.add_ellipse_tool_button.get_style_context().remove_class('active')
        self.add_rectangle_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'pen_tool_button'):
            self.pen_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'highlighter_tool_button'):
            self.highlighter_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'checkmark_tool_button'):
            self.checkmark_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'cross_tool_button'):
            self.cross_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'form_builder_tool_button') and self.form_builder_tool_button:
            self.form_builder_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'calibrate_tool_button') and self.calibrate_tool_button:
            self.calibrate_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'measure_distance_tool_button') and self.measure_distance_tool_button:
            self.measure_distance_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'measure_area_tool_button') and self.measure_area_tool_button:
            self.measure_area_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'stamp_tool_button') and self.stamp_tool_button:
            self.stamp_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'clone_patch_tool_button') and self.clone_patch_tool_button:
            self.clone_patch_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'signature_tool_button') and self.signature_tool_button:
            self.signature_tool_button.get_style_context().remove_class('active')
        if hasattr(self, 'redact_tool_button') and self.redact_tool_button:
            self.redact_tool_button.get_style_context().remove_class('active')

        if self.view_mode:
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("text"))
        elif self.tool_mode == "select":
            self.select_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(None)
        elif self.tool_mode == "add_text":
            self.add_text_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_image":
            self.add_image_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("cell"))
        elif self.tool_mode == "drag":
            if getattr(self, 'drag_tool_button', None):
                self.drag_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("move"))
        elif self.tool_mode == "add_ellipse":
            self.add_ellipse_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_rectangle":
            self.add_rectangle_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_checkmark":
            if hasattr(self, 'checkmark_tool_button'):
                self.checkmark_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_cross":
            if hasattr(self, 'cross_tool_button'):
                self.cross_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "pen":
            if hasattr(self, 'pen_tool_button'):
                self.pen_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "highlighter":
            if hasattr(self, 'highlighter_tool_button'):
                self.highlighter_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "form_builder":
            if hasattr(self, 'form_builder_tool_button') and self.form_builder_tool_button:
                self.form_builder_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "calibrate":
            if hasattr(self, 'calibrate_tool_button') and self.calibrate_tool_button:
                self.calibrate_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "measure_distance":
            if hasattr(self, 'measure_distance_tool_button') and self.measure_distance_tool_button:
                self.measure_distance_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "measure_area":
            if hasattr(self, 'measure_area_tool_button') and self.measure_area_tool_button:
                self.measure_area_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_stamp":
            if hasattr(self, 'stamp_tool_button') and self.stamp_tool_button:
                self.stamp_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "clone_patch":
            if hasattr(self, 'clone_patch_tool_button') and self.clone_patch_tool_button:
                self.clone_patch_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "place_signature":
            if hasattr(self, 'signature_tool_button') and self.signature_tool_button:
                self.signature_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "redact":
            if hasattr(self, 'redact_tool_button') and self.redact_tool_button:
                self.redact_tool_button.get_style_context().add_class('active')
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))

        if has_doc:
            self.stack.set_visible_child_name("editor")
        else:
            self.stack.set_visible_child_name("welcome")

        if has_doc:
            self.update_page_label()
            self.update_zoom_label()
            if self.document_modified and not self.get_title().endswith("*"):
                self.set_title(self.get_title() + "*")
            elif not self.document_modified and self.get_title().endswith("*"):
                self.set_title(self.get_title()[:-1])
        else:
            self.page_label.set_text(_("page_info_count").format(0, 0))
            self.update_zoom_label()

        selected_obj = (self.selected_text or self.selected_image or self.selected_shape or
                        getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None) or
                        getattr(self, 'selected_measurement', None) or getattr(self, 'selected_sticky_note', None))
        if hasattr(self, 'annotations_sidebar') and self.annotations_sidebar.get_visible():
            self.annotations_sidebar.sync_selection(selected_obj)
            self.status_label.set_text(_("status_open_or_drop"))
            self.set_title(constants.APP_NAME)
            self.document_modified = False

        self._update_undo_redo_buttons()

    def on_about_activated(self, action, param):
        """Show the application About dialog."""
        about_dialog = Gtk.AboutDialog(transient_for=self, modal=True)

        about_dialog.set_default_size(560, 450)
        about_dialog.set_program_name(constants.APP_NAME)
        about_dialog.set_version(constants.APP_VERSION)
        about_dialog.set_authors(["Barın Güzeldemirci (word-sys)"])

        try:
            about_dialog.set_license_type(Gtk.License.GPL_3_0_OR_LATER)
        except AttributeError:
            try:
                about_dialog.set_license_type(Gtk.License.GPL_3_0)
            except AttributeError:
                about_dialog.set_license_type(Gtk.License.CUSTOM)
        try:
            license_text = constants.get_application_license_text()
            about_dialog.set_license(license_text)
            about_dialog.set_wrap_license(True)
        except Exception as e:
            print(f"Error loading license text: {e}")
            about_dialog.set_license("GNU General Public License v3.0 or later.")

        about_dialog.set_website("https://github.com/word-sys/word-sys-pdf-editor")
        about_dialog.set_website_label(_("about_website_label"))
        about_dialog.set_comments(_("about_comments"))

        try:
            about_dialog.set_logo_icon_name("f-pv1")
        except Exception as e:
            print(f"Warning: Could not load application icon for About dialog: {e}")
            about_dialog.set_logo_icon_name("application-x-executable")

        about_dialog.set_copyright("© 2024-2026 Barın Güzeldemirci (word-sys)")

        if hasattr(about_dialog, "add_credit_section"):
            raw_title = _("about_credit_libraries")
            safe_title = GLib.markup_escape_text(raw_title)
            library_items = [
                "PyMuPDF / MuPDF (AGPL-3.0 / Artifex Software)",
                "pyHanko (MIT / Matthias Valvekens)",
                "pyhanko-certvalidator (MIT / Will Bond, Matthias Valvekens)",
                "cryptography (Apache-2.0 or BSD-3-Clause / PyCA)",
                "certifi (MPL-2.0 / Kenneth Reitz, Mozilla)",
                "anyconvert (GPL-3.0-or-later / Barın Güzeldemirci)",
                "NumPy (BSD-3-Clause / NumPy Developers)",
                "Pillow (HPND / Jeffrey 'Alex' Clark, Secret Labs)",
                "asn1crypto (MIT / Will Bond)",
                "python-pkcs11 (MIT / Danielle Madeley)",
                "fonttools (MIT / Just van Rossum)",
            ]
            about_dialog.add_credit_section(
                safe_title,
                [GLib.markup_escape_text(item) for item in library_items]
            )

        tab_map = {
            "About": _("about_tab_about"),
            "Credits": _("about_tab_credits"),
            "License": _("about_tab_license"),
        }
        def _localize_about_tabs(widget):
            if isinstance(widget, Gtk.Label):
                txt = widget.get_label()
                if txt in tab_map:
                    widget.set_label(tab_map[txt])
            child = widget.get_first_child() if hasattr(widget, 'get_first_child') else None
            while child:
                _localize_about_tabs(child)
                child = child.get_next_sibling()

        _localize_about_tabs(about_dialog)
        about_dialog.present()


    def _record_recent_file(self, filepath):
        """Prepend filepath to recent_opened_files setting, deduplicate, and limit to 15."""
        if not filepath:
            return
        try:
            filepath_str = str(filepath)
            norm_path = os.path.abspath(os.path.normpath(filepath_str))
            recents = get_setting("recent_opened_files", [])
            if not isinstance(recents, list):
                recents = []
            updated = [
                p for p in recents
                if isinstance(p, str) and os.path.abspath(os.path.normpath(p)) != norm_path
            ]
            updated.insert(0, norm_path)
            updated = updated[:15]
            set_setting("recent_opened_files", updated)
        except Exception as e:
            print(f"Warning: Failed to record recent file {filepath}: {e}")

    def load_document(self, filepath, target_page=0, in_new_tab=None, password=None, force_reload=False):
        """Load document into active session or a new tab."""
        existing_session = self.get_session_by_path(filepath)
        if existing_session and not force_reload:
            self.set_active_session(existing_session)
            if target_page != 0:
                self._load_page(target_page)
            return

        if existing_session and force_reload:
            target_sess = existing_session
            self.set_active_session(target_sess)
            if target_sess.doc:
                pdf_handler.release_page_snapshots(target_sess.doc)
                pdf_handler.close_pdf_document(target_sess.doc)
                target_sess.doc = None
            target_sess.page_cache.clear()
            target_sess.editable_texts.clear()
            target_sess.editable_shapes.clear()
            target_sess.editable_strokes.clear()
            target_sess.editable_images.clear()
            target_sess.form_fields.clear()
            target_sess.measurements.clear()
            target_sess.sticky_notes.clear()
            target_sess.is_modified = False
            if target_sess.undo_manager:
                target_sess.undo_manager.clear()
        else:
            if in_new_tab is None:
                in_new_tab = (self._active_session is not None and self._active_session.doc is not None)

            if in_new_tab:
                new_session = self.create_session(filepath=filepath)
                self.add_session(new_session, switch_to=True)
                target_sess = new_session
            else:
                if self.check_unsaved_changes():
                    return
                self.close_document()
                if self._active_session is None:
                    self._active_session = self.create_session(filepath=filepath)
                    self.sessions = [self._active_session]
                target_sess = self._active_session
                target_sess.pdf_path = filepath
                target_sess.original_file_path = filepath
                if hasattr(self, 'tab_view') and self.tab_view:
                    if getattr(target_sess, 'tab_page', None) is None:
                        self._create_tab_for_session(target_sess)
                self._update_tab_title(target_sess)

        self._record_recent_file(filepath)
        self.status_label.set_text(_("loading").format(os.path.basename(filepath)))
        GLib.idle_add(self._show_loading_state)

        pw_to_try = password
        if pw_to_try is None and target_sess:
            pw_to_try = getattr(target_sess, 'vault_password', None) or getattr(target_sess, 'pdf_password', None)

        def _load_async():
            doc, error_msg = pdf_handler.load_pdf_document(filepath, password=pw_to_try)
            GLib.idle_add(self._finish_loading, doc, error_msg, filepath, target_page, target_sess)

        thread = threading.Thread(target=_load_async)
        thread.daemon = True
        thread.start()

    def _show_loading_state(self):
        """Show loading state."""
        self.open_button.set_sensitive(False)
        self.save_button.set_sensitive(False)
        if self.lookup_action("save"):
            self.lookup_action("save").set_enabled(False)
        if self.lookup_action("save_as"):
            self.lookup_action("save_as").set_enabled(False)
        for act_name in ("export_as", "export_docx", "export_pptx", "export_odt", "export_odp", "export_txt"):
            act = self.lookup_action(act_name)
            if act:
                act.set_enabled(False)
        for act_name in (
            "compress_document",
            "protect_document",
            "digitally_sign_document",
            "inspect_digital_signatures",
            "flatten_annotations",
            "sanitize_document",
            "ocr_document",
            "find",
            "toggle_annotations",
            "close_tab",
            "print",
        ):
            act = self.lookup_action(act_name)
            if act:
                act.set_enabled(False)
        if hasattr(self, 'toggle_annotations_button') and self.toggle_annotations_button:
            self.toggle_annotations_button.set_sensitive(False)
        if hasattr(self, 'print_button') and self.print_button:
            self.print_button.set_sensitive(False)
        if hasattr(self, 'search_button') and self.search_button:
            self.search_button.set_sensitive(False)
        if hasattr(self, 'mode_toggle_button') and self.mode_toggle_button:
            self.mode_toggle_button.set_sensitive(False)
        if hasattr(self, 'undo_button') and self.undo_button:
            self.undo_button.set_sensitive(False)
        if hasattr(self, 'redo_button') and self.redo_button:
            self.redo_button.set_sensitive(False)
        if self.lookup_action("undo"):
            self.lookup_action("undo").set_enabled(False)
        if self.lookup_action("redo"):
            self.lookup_action("redo").set_enabled(False)
        self.prev_button.set_sensitive(False)
        self.next_button.set_sensitive(False)
        self.font_combo.set_sensitive(False)
        self.font_size_spin.set_sensitive(False)
        self.color_button.set_sensitive(False)
        self.select_tool_button.set_sensitive(False)
        self.add_text_tool_button.set_sensitive(False)
        if getattr(self, 'calibrate_tool_button', None):
            self.calibrate_tool_button.set_sensitive(False)
        if getattr(self, 'measure_distance_tool_button', None):
            self.measure_distance_tool_button.set_sensitive(False)
        if getattr(self, 'measure_area_tool_button', None):
            self.measure_area_tool_button.set_sensitive(False)
        if not any(s.doc is not None for s in self.sessions):
            if hasattr(self, 'stack') and self.stack:
                self.stack.set_visible_child_name("welcome")


    def _finish_loading(self, doc, error_msg, filepath, target_page=0, target_session=None):
        """Finalize document loading, set active session state, and start thumbnail generation."""
        sess = target_session or getattr(self, '_active_session', None)
        if error_msg in ("PASSWORD_REQUIRED_WSPDF", "PASSWORD_REQUIRED_STANDARD", "INVALID_PASSWORD"):
            is_vault = (error_msg == "PASSWORD_REQUIRED_WSPDF" or filepath.lower().endswith(".wspdf"))
            from .protect_dialog import DocumentUnlockDialog

            def on_unlock(entered_pw):
                if hasattr(self, '_current_unlock_dialog') and self._current_unlock_dialog:
                    self._current_unlock_dialog.destroy()
                    self._current_unlock_dialog = None
                def _retry_load():
                    doc2, err2 = pdf_handler.load_pdf_document(filepath, password=entered_pw)
                    GLib.idle_add(self._finish_loading, doc2, err2, filepath, target_page, sess)
                t = threading.Thread(target=_retry_load)
                t.daemon = True
                t.start()

            def on_cancel():
                self._current_unlock_dialog = None
                self.status_label.set_text(_("doc_load_failed"))
                if len(self.sessions) > 1 and sess:
                    self.remove_session(sess)
                else:
                    self.close_document()
                self.open_button.set_sensitive(True)
                self.select_tool_button.set_sensitive(True)
                self.add_text_tool_button.set_sensitive(True)
                self._update_ui_state()

            unlock_dlg = DocumentUnlockDialog(
                parent_window=self,
                filepath=filepath,
                is_vault=is_vault,
                on_unlock_callback=on_unlock,
                on_cancel_callback=on_cancel
            )
            self._current_unlock_dialog = unlock_dlg
            if error_msg == "INVALID_PASSWORD":
                unlock_dlg.show_error()
            unlock_dlg.present()
            return
        elif error_msg:
            show_error_dialog(self, error_msg)
            self.status_label.set_text(_("doc_load_failed"))
            if len(self.sessions) > 1 and sess:
                self.remove_session(sess)
            else:
                self.close_document()
            self.open_button.set_sensitive(True)
            self.select_tool_button.set_sensitive(True)
            self.add_text_tool_button.set_sensitive(True)
            if getattr(self, 'calibrate_tool_button', None):
                self.calibrate_tool_button.set_sensitive(True)
            if getattr(self, 'measure_distance_tool_button', None):
                self.measure_distance_tool_button.set_sensitive(True)
            if getattr(self, 'measure_area_tool_button', None):
                self.measure_area_tool_button.set_sensitive(True)
            self._update_ui_state()
            return
        elif doc and sess:
            sess.doc = doc
            sess.is_repaired_file = getattr(doc, 'is_repaired', False)
            sess.pdf_path = filepath
            sess.original_file_path = filepath
            sess.allow_incremental_save = True
            sess.is_modified = False
            sess.current_page_index = target_page
            sess.pdf_password = getattr(doc, '_pdf_password', None)
            sess.pdf_owner_password = getattr(doc, '_pdf_owner_password', None)
            sess.pdf_permissions = getattr(doc, '_pdf_permissions', None)
            sess.is_vault = getattr(doc, '_is_vault', False)
            sess.vault_password = getattr(doc, '_vault_password', None)
            self._update_tab_title(sess)

            calib_data = pdf_handler.extract_scale_calibration(doc)
            if calib_data:
                try:
                    sess.scale_calibration = ScaleCalibration.from_dict(calib_data)
                except Exception as e:
                    print(f"Warning restoring scale calibration: {e}")

            meas_data = pdf_handler.extract_measurements(doc)
            if meas_data:
                sess.measurements.clear()
                for item in meas_data:
                    try:
                        m_obj = MeasurementObject.from_dict(item)
                        if m_obj.page_number not in sess.measurements:
                            sess.measurements[m_obj.page_number] = []
                        sess.measurements[m_obj.page_number].append(m_obj)
                    except Exception as e:
                        print(f"Warning restoring measurement: {e}")

            notes_data = pdf_handler.extract_sticky_notes(doc)
            if notes_data:
                sess.sticky_notes = notes_data

            if getattr(sess, 'is_repaired_file', False):
                print(_("dbg_repaired_while_opening"))
            # Check digital signatures asynchronously so document open never blocks
            self._start_signature_inspection(sess, doc)

            self._record_recent_file(filepath)
            self.set_active_session(sess)
            self._invalidate_continuous_layout()

            self.target_page_after_load = target_page
            self._load_page(target_page, reload_objects=True)
            if hasattr(self, 'annotations_sidebar') and self.annotations_sidebar.get_visible():
                self.annotations_sidebar.refresh()
            self._load_thumbnails(sess)

        self.open_button.set_sensitive(True)
        self.select_tool_button.set_sensitive(True)
        self.add_text_tool_button.set_sensitive(True)
        if getattr(self, 'calibrate_tool_button', None):
            self.calibrate_tool_button.set_sensitive(True)
        if getattr(self, 'measure_distance_tool_button', None):
            self.measure_distance_tool_button.set_sensitive(True)
        if getattr(self, 'measure_area_tool_button', None):
            self.measure_area_tool_button.set_sensitive(True)
        self._update_ui_state()

    def request_thumbnail(self, page_index, session=None, priority=None):
        """On-demand thumbnail request for a visible or prefetch sidebar item."""
        sess = session or self._active_session
        if not sess or not sess.doc:
            return
        if not (0 <= page_index < pdf_handler.get_page_count(sess.doc)):
            return
        target_model = sess.pages_model
        if not target_model or page_index >= target_model.get_n_items():
            return
        item = target_model.get_item(page_index)
        if not item or getattr(item, 'thumbnail', None) is not None:
            return

        gen_id = getattr(self, '_thumb_generation_id', 1)
        prio = pdf_handler.PRIORITY_VISIBLE if priority is None else priority
        thumb_w = 100 if getattr(self, 'is_eco_mode', False) else 150
        is_mod = (
            getattr(sess, 'is_modified', False)
            or getattr(self, 'document_modified', False)
            or getattr(sess.doc, '_is_modified', False)
        )
        allow_disk = not is_mod
        pdf_handler.request_thumbnail_async(
            gen_id,
            sess.doc,
            page_index,
            target_width=thumb_w,
            priority=prio,
            callback=self._on_thumbnail_rendered,
            filepath=sess.pdf_path,
            save_to_disk=allow_disk
        )

        if prio == pdf_handler.PRIORITY_VISIBLE:
            page_count = pdf_handler.get_page_count(sess.doc)
            for adj in (page_index - 1, page_index + 1):
                if 0 <= adj < page_count and adj < target_model.get_n_items():
                    adj_item = target_model.get_item(adj)
                    if adj_item and getattr(adj_item, 'thumbnail', None) is None:
                        pdf_handler.request_thumbnail_async(
                            gen_id,
                            sess.doc,
                            adj,
                            target_width=thumb_w,
                            priority=pdf_handler.PRIORITY_PREFETCH,
                            callback=self._on_thumbnail_rendered,
                            filepath=sess.pdf_path,
                            save_to_disk=allow_disk
                        )

    def cancel_thumbnail_request(self, page_index):
        """Cancel pending render request for a page that scrolled out of view."""
        gen_id = getattr(self, '_thumb_generation_id', None)
        if gen_id is not None:
            pdf_handler.cancel_thumbnail_async(gen_id, page_index)

    def _on_thumbnail_rendered(self, page_index, thumb, gen_id):
        """Receive asynchronously rendered thumbnail pixbuf and update model item."""
        if getattr(self, '_thumb_generation_id', None) != gen_id:
            return False
        sess = self._active_session
        if not sess or not sess.pages_model:
            return False
        if 0 <= page_index < sess.pages_model.get_n_items():
            item = sess.pages_model.get_item(page_index)
            if item and getattr(item, 'index', None) == page_index:
                item.thumbnail = thumb
        return False

    def _load_thumbnails(self, session=None, target_page=None):
        """Asynchronously populate sidebar thumbnail model and progressively load page pixbufs."""
        sess = session or self._active_session
        if not sess or not sess.doc:
            return

        if target_page is not None:
            self.target_page_after_load = target_page

        target_doc = sess.doc
        target_model = sess.pages_model
        if target_model is None:
            return

        page_count = pdf_handler.get_page_count(target_doc)
        old_count = target_model.get_n_items()

        # Cancel any previous thumbnail generation tasks for previous documents
        old_gen = getattr(self, '_thumb_generation_id', None)
        if old_gen is not None:
            pdf_handler.cancel_generation_thumbnails(old_gen)
        self._thumb_generation_id = (old_gen or 0) + 1
        current_gen = self._thumb_generation_id

        # Check if document has unsaved in-memory changes
        is_mod = (
            getattr(sess, 'is_modified', False)
            or getattr(self, 'document_modified', False)
            or getattr(target_doc, '_is_modified', False)
        )
        allow_disk = not is_mod

        # Generate thumbnail for active page
        active_target = target_page if target_page is not None else getattr(self, 'current_page_index', 0)
        active_thumb = None
        thumb_w = 100 if getattr(self, 'is_eco_mode', False) else 150
        if 0 <= active_target < page_count:
            try:
                active_thumb = pdf_handler.generate_thumbnail(
                    target_doc, active_target, target_width=thumb_w, filepath=sess.pdf_path, save_to_disk=allow_disk
                )
            except Exception:
                pass

        # Progressive model population: populate initial visible slice (up to 30) with disk cache if clean
        init_slice_size = min(page_count, 30)
        disk_cache = pdf_handler.get_disk_thumbnail_cache() if allow_disk else None
        init_items = []
        for i in range(init_slice_size):
            if i == active_target and active_thumb:
                init_items.append(PdfPage(index=i, thumbnail=active_thumb))
            else:
                disk_thumb = disk_cache.get_thumbnail(target_doc, i, target_width=thumb_w, filepath=sess.pdf_path) if disk_cache else None
                init_items.append(PdfPage(index=i, thumbnail=disk_thumb))

        target_model.splice(0, old_count, init_items)

        if page_count > init_slice_size:
            rem_iter = [init_slice_size]
            def _feed_model_chunk():
                if getattr(self, '_thumb_generation_id', None) != current_gen:
                    return GLib.SOURCE_REMOVE
                if sess.doc != target_doc:
                    return GLib.SOURCE_REMOVE
                if rem_iter[0] >= page_count:
                    return GLib.SOURCE_REMOVE

                chunk_end = min(page_count, rem_iter[0] + 50)
                chunk_items = []
                for i in range(rem_iter[0], chunk_end):
                    if i == active_target and active_thumb:
                        chunk_items.append(PdfPage(index=i, thumbnail=active_thumb))
                    else:
                        disk_thumb = disk_cache.get_thumbnail(target_doc, i, target_width=thumb_w, filepath=sess.pdf_path) if disk_cache else None
                        chunk_items.append(PdfPage(index=i, thumbnail=disk_thumb))
                target_model.splice(rem_iter[0], 0, chunk_items)
                rem_iter[0] = chunk_end
                if rem_iter[0] < page_count:
                    return GLib.SOURCE_CONTINUE
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_feed_model_chunk, priority=GLib.PRIORITY_LOW)

        # Update document title and status immediately without waiting for off-screen pages
        if self._active_session == sess:
            if sess.pdf_path:
                self.status_label.set_text(_("loaded").format(os.path.basename(sess.pdf_path)))
            else:
                self.status_label.set_text(_("new_doc_loaded"))

            if page_count > 0:
                target = getattr(self, 'target_page_after_load', None)
                self.target_page_after_load = None
                if target is not None:
                    if target >= page_count:
                        target = page_count - 1
                    if target < 0:
                        target = 0
                    if getattr(self, 'current_page_index', None) != target:
                        self._load_page(target)
                    else:
                        self._sync_thumbnail_selection()
                        self._update_ui_state()
                else:
                    curr = getattr(self, 'current_page_index', 0)
                    if curr >= page_count:
                        curr = max(0, page_count - 1)
                        self._load_page(curr)
                    else:
                        self._sync_thumbnail_selection()
                        self._update_ui_state()
            else:
                self._update_ui_state()

        # Request high-priority thumbnail for active page
        active_target = getattr(self, 'current_page_index', 0)
        if 0 <= active_target < page_count:
            self.request_thumbnail(active_target, priority=pdf_handler.PRIORITY_VISIBLE)

        # Progressive background feed for remaining off-screen pages in chunks of 50
        bg_iter = [0]
        def _feed_bg_chunk():
            if getattr(self, '_thumb_generation_id', None) != current_gen:
                return GLib.SOURCE_REMOVE
            if sess.doc != target_doc:
                return GLib.SOURCE_REMOVE

            chunk_end = min(page_count, bg_iter[0] + 50)
            for idx in range(bg_iter[0], chunk_end):
                if idx != active_target:
                    item = target_model.get_item(idx) if idx < target_model.get_n_items() else None
                    if item and getattr(item, 'thumbnail', None) is None:
                        pdf_handler.request_thumbnail_async(
                            current_gen,
                            target_doc,
                            idx,
                            target_width=150,
                            priority=pdf_handler.PRIORITY_BACKGROUND,
                            callback=self._on_thumbnail_rendered,
                            filepath=sess.pdf_path,
                            save_to_disk=allow_disk
                        )
            bg_iter[0] = chunk_end
            if bg_iter[0] < page_count:
                return GLib.SOURCE_CONTINUE
            return GLib.SOURCE_REMOVE

        GLib.idle_add(_feed_bg_chunk, priority=GLib.PRIORITY_LOW)

    def _invalidate_continuous_layout(self):
        """Invalidate continuous layout geometry cache upon page structure or orientation change."""
        self._doc_page_sizes_cache = None
        self._is_geometry_uniform = None
        self._uniform_page_size = None
        self.continuous_page_offsets = []
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index()
        if getattr(self, 'continuous_scroll', False):
            self._update_canvas_content_size()

    def _fast_get_page_dimension(self, page_index: int) -> Tuple[float, float]:
        """Query page dimensions via fast PyMuPDF page_cropbox and Rotate metadata without parsing content streams."""
        try:
            box = self.doc.page_cropbox(page_index)
            rot = 0
            try:
                type_str, val_str = self.doc.xref_get_key(self.doc.page_xref(page_index), "Rotate")
                if type_str == "int":
                    rot = int(val_str)
            except Exception:
                pass
            if (rot % 360) in (90, 270):
                return (float(box.height), float(box.width))
            return (float(box.width), float(box.height))
        except Exception:
            try:
                page = self.doc.load_page(page_index)
                return (float(page.rect.width), float(page.rect.height))
            except Exception:
                return (float(getattr(self, 'current_pdf_page_width', 595)), float(getattr(self, 'current_pdf_page_height', 842)))

    def _recompute_continuous_layout(self):
        """Compute cumulative vertical offsets and dimensions for all pages using fast metadata and O(1) uniform indexing."""
        if not self.doc or len(self.doc) == 0:
            self.continuous_page_offsets = []
            self.continuous_total_height = 0.0
            self.continuous_max_width = 0.0
            return

        num_pages = len(self.doc)
        gap = float(self.page_gap)
        zoom = float(getattr(self, 'zoom_level', 1.0))

        # Check / build dimension metadata cache
        if not hasattr(self, '_doc_page_sizes_cache') or self._doc_page_sizes_cache is None or len(self._doc_page_sizes_cache) != num_pages:
            self._doc_page_sizes_cache = {}
            is_uniform = True
            first_dim = None

            for i in range(num_pages):
                dim = self._fast_get_page_dimension(i)
                self._doc_page_sizes_cache[i] = dim
                if first_dim is None:
                    first_dim = dim
                elif is_uniform and (abs(dim[0] - first_dim[0]) > 0.001 or abs(dim[1] - first_dim[1]) > 0.001):
                    is_uniform = False

            self._is_geometry_uniform = is_uniform
            self._uniform_page_size = first_dim

        if getattr(self, '_is_geometry_uniform', False) and self._uniform_page_size is not None:
            base_w, base_h = self._uniform_page_size
            pw = float(base_w * zoom)
            ph = float(base_h * zoom)
            stride = ph + gap
            self.continuous_page_offsets = UniformPageOffsets(num_pages, gap, pw, ph)
            self.continuous_total_height = gap + num_pages * stride
            self.continuous_max_width = pw
            return

        # Non-uniform document fallback (fast cached dimensions, no fitz re-parsing)
        offsets = []
        current_y = gap
        max_w = 0.0
        for i in range(num_pages):
            base_w, base_h = self._doc_page_sizes_cache.get(i) or self._fast_get_page_dimension(i)
            pw = float(base_w * zoom)
            ph = float(base_h * zoom)
            if pw > max_w:
                max_w = pw
            offsets.append((0.0, current_y, pw, ph))
            current_y += ph + gap

        self.continuous_page_offsets = offsets
        self.continuous_total_height = current_y
        self.continuous_max_width = max_w

    def _update_canvas_content_size(self):
        """Update drawing area content width and height based on mode."""
        if not hasattr(self, 'pdf_view') or not self.pdf_view:
            return
        if self.continuous_scroll:
            self._recompute_continuous_layout()
            alloc_w = float(self.pdf_view.get_allocated_width()) if hasattr(self, 'pdf_view') else 0.0
            w = max(int(self.continuous_max_width), int(alloc_w), 1)
            h = max(int(self.continuous_total_height), 1)
            self.pdf_view.set_content_width(w)
            self.pdf_view.set_content_height(h)
            v_adj = self.pdf_scroll.get_vadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
            if v_adj and v_adj.get_upper() < h:
                v_adj.set_upper(float(h))
                if v_adj.get_page_size() <= 0:
                    v_adj.set_page_size(800.0)
        else:
            self.pdf_view.set_content_width(max(self.current_pdf_page_width, 1))
            self.pdf_view.set_content_height(max(self.current_pdf_page_height, 1))

    def get_page_canvas_rect(self, page_index: int) -> Tuple[float, float, float, float]:
        """Return (x, y, width, height) of the given page in canvas coordinates."""
        if not self.doc or not (0 <= page_index < len(self.doc)):
            return (0.0, 0.0, float(self.current_pdf_page_width), float(self.current_pdf_page_height))

        alloc_w = float(self.pdf_view.get_allocated_width()) if hasattr(self, 'pdf_view') and self.pdf_view.get_allocated_width() > 0 else float(self.current_pdf_page_width)
        alloc_h = float(self.pdf_view.get_allocated_height()) if hasattr(self, 'pdf_view') and self.pdf_view.get_allocated_height() > 0 else float(self.current_pdf_page_height)

        if not self.continuous_scroll:
            pw = float(self.current_pdf_page_width)
            ph = float(self.current_pdf_page_height)
            px = max(0.0, (alloc_w - pw) / 2.0)
            py = max(0.0, (alloc_h - ph) / 2.0)
            return (px, py, pw, ph)

        if not hasattr(self, 'continuous_page_offsets') or len(self.continuous_page_offsets) != len(self.doc):
            self._recompute_continuous_layout()

        if 0 <= page_index < len(self.continuous_page_offsets):
            _, py, pw, ph = self.continuous_page_offsets[page_index]
            px = max(0.0, (alloc_w - pw) / 2.0)
            return (px, py, pw, ph)

        return (0.0, 0.0, float(self.current_pdf_page_width), float(self.current_pdf_page_height))

    def get_visible_viewport_rect(self) -> Tuple[float, float, float, float]:
        """Return visible canvas viewport (scroll_x, scroll_y, viewport_width, viewport_height)."""
        h_adj = self.pdf_scroll.get_hadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
        v_adj = self.pdf_scroll.get_vadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None

        scroll_x = float(h_adj.get_value()) if h_adj else 0.0
        scroll_y = float(v_adj.get_value()) if v_adj else 0.0

        vp_w = float(h_adj.get_page_size()) if h_adj and h_adj.get_page_size() > 0 else (
            float(self.pdf_scroll.get_allocated_width()) if hasattr(self, 'pdf_scroll') and self.pdf_scroll and self.pdf_scroll.get_allocated_width() > 0 else (
                float(self.pdf_view.get_allocated_width()) if hasattr(self, 'pdf_view') and self.pdf_view and self.pdf_view.get_allocated_width() > 0 else float(getattr(self, 'current_pdf_page_width', 600))
            )
        )
        vp_h = float(v_adj.get_page_size()) if v_adj and v_adj.get_page_size() > 0 else (
            float(self.pdf_scroll.get_allocated_height()) if hasattr(self, 'pdf_scroll') and self.pdf_scroll and self.pdf_scroll.get_allocated_height() > 0 else (
                float(self.pdf_view.get_allocated_height()) if hasattr(self, 'pdf_view') and self.pdf_view and self.pdf_view.get_allocated_height() > 0 else float(getattr(self, 'current_pdf_page_height', 800))
            )
        )

        return (scroll_x, scroll_y, vp_w, vp_h)

    def _is_canvas_virtualization_required(self, w: float, h: float) -> bool:
        """Determine whether Cairo sub-viewport clipping is required to avoid GPU texture limits."""
        # Continuous scroll mode tiles across dozens/hundreds of stacked pages (can exceed 100k px)
        if getattr(self, 'continuous_scroll', False):
            return True
        # In single page mode, only clip if dimensions exceed standard safe GPU texture bounds
        return (w > 8192.0 or h > 8192.0 or (w * h) > 33_554_432.0)

    def get_object_canvas_rect(
        self,
        obj: Any,
        page_index: Optional[int] = None,
        is_visual_coords: bool = False
    ) -> Optional[Tuple[int, int, int, int]]:
        """Return (x, y, width, height) of an object in canvas pixel coordinates."""
        if obj is None:
            return None

        p_idx = page_index if isinstance(page_index, int) else (
            getattr(obj, 'page_number', None) if isinstance(getattr(obj, 'page_number', None), int) else getattr(self, 'current_page_index', 0)
        )
        if not isinstance(p_idx, int):
            p_idx = 0

        raw_bbox = None
        if hasattr(obj, 'bbox') and getattr(obj, 'bbox', None) is not None:
            raw_bbox = getattr(obj, 'bbox')
        elif hasattr(obj, 'x') and hasattr(obj, 'width') and hasattr(obj, 'y') and hasattr(obj, 'height'):
            try:
                raw_bbox = (float(obj.x), float(obj.y), float(obj.x + obj.width), float(obj.y + obj.height))
            except (TypeError, ValueError):
                raw_bbox = None
        elif hasattr(obj, 'rect') and getattr(obj, 'rect', None) is not None:
            raw_bbox = getattr(obj, 'rect')
        elif isinstance(obj, (tuple, list)) and len(obj) == 4:
            raw_bbox = obj

        if not raw_bbox or len(raw_bbox) != 4:
            return None

        try:
            x0 = float(min(raw_bbox[0], raw_bbox[2]))
            y0 = float(min(raw_bbox[1], raw_bbox[3]))
            x1 = float(max(raw_bbox[0], raw_bbox[2]))
            y1 = float(max(raw_bbox[1], raw_bbox[3]))
        except (TypeError, ValueError):
            return None

        rot = getattr(obj, 'rotation', 0.0) % 360.0 if hasattr(obj, 'rotation') else 0.0
        if rot != 0.0:
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            p1 = pdf_handler.rotate_point(x0, y0, cx, cy, rot)
            p2 = pdf_handler.rotate_point(x1, y0, cx, cy, rot)
            p3 = pdf_handler.rotate_point(x1, y1, cx, cy, rot)
            p4 = pdf_handler.rotate_point(x0, y1, cx, cy, rot)
            x0 = min(p1[0], p2[0], p3[0], p4[0])
            y0 = min(p1[1], p2[1], p3[1], p4[1])
            x1 = max(p1[0], p2[0], p3[0], p4[0])
            y1 = max(p1[1], p2[1], p3[1], p4[1])

        if is_visual_coords:
            vis_r = fitz.Rect(x0, y0, x1, y1).normalize()
        else:
            try:
                page = self.doc[p_idx] if self.doc and 0 <= p_idx < len(self.doc) else None
                if page and (page.rotation % 360) != 0:
                    vis_r = (fitz.Rect(x0, y0, x1, y1) * page.rotation_matrix).normalize()
                else:
                    vis_r = fitz.Rect(x0, y0, x1, y1).normalize()
            except Exception:
                vis_r = fitz.Rect(x0, y0, x1, y1).normalize()

        page_offset_x, page_offset_y, _, _ = self.get_page_canvas_rect(p_idx)
        zoom = float(getattr(self, 'zoom_level', 1.0))
        cx = int(page_offset_x + vis_r.x0 * zoom)
        cy = int(page_offset_y + vis_r.y0 * zoom)
        cw = max(1, int(vis_r.width * zoom))
        ch = max(1, int(vis_r.height * zoom))

        return (cx, cy, cw, ch)

    def calculate_smart_popover_placement(
        self,
        anchor_rect: Optional[Tuple[int, int, int, int]] = None,
        click_pos: Optional[Tuple[float, float]] = None,
        estimated_size: Tuple[int, int] = (240, 300),
        margin: int = 8
    ) -> Tuple[Gdk.Rectangle, Gtk.PositionType]:
        """Compute non-obstructive pointing rectangle and Gtk.PositionType for popovers."""
        if anchor_rect is None:
            if click_pos is not None:
                anchor_rect = (int(click_pos[0]), int(click_pos[1]), 1, 1)
            else:
                anchor_rect = (0, 0, 1, 1)

        ax, ay, aw, ah = anchor_rect
        is_point = (aw <= 1 and ah <= 1)

        vp_x, vp_y, vp_w, vp_h = self.get_visible_viewport_rect()
        vp_right = vp_x + vp_w
        vp_bottom = vp_y + vp_h

        est_w, est_h = estimated_size

        space_right = vp_right - (ax + aw)
        space_left = ax - vp_x
        space_bottom = vp_bottom - (ay + ah)
        space_top = ay - vp_y

        if space_right >= est_w + margin:
            chosen_pos = Gtk.PositionType.RIGHT
        elif space_left >= est_w + margin:
            chosen_pos = Gtk.PositionType.LEFT
        elif space_bottom >= est_h + margin:
            chosen_pos = Gtk.PositionType.BOTTOM
        elif space_top >= est_h + margin:
            chosen_pos = Gtk.PositionType.TOP
        else:
            scores = [
                (space_right / max(est_w, 1), Gtk.PositionType.RIGHT),
                (space_left / max(est_w, 1), Gtk.PositionType.LEFT),
                (space_bottom / max(est_h, 1), Gtk.PositionType.BOTTOM),
                (space_top / max(est_h, 1), Gtk.PositionType.TOP),
            ]
            chosen_pos = max(scores, key=lambda s: s[0])[1]

        rect = Gdk.Rectangle()
        if is_point:
            rect.x = max(0, ax)
            rect.y = max(0, ay)
            rect.width = 1
            rect.height = 1
            return rect, chosen_pos

        if chosen_pos in (Gtk.PositionType.RIGHT, Gtk.PositionType.LEFT):
            rx0 = max(0, ax - margin)
            rx1 = ax + aw + margin
            rect.x = rx0
            rect.width = max(1, rx1 - rx0)
            if click_pos is not None and ah > 120:
                cy_min = max(ay, int(click_pos[1] - 20))
                cy_max = min(ay + ah, int(click_pos[1] + 20))
                ry0 = max(0, cy_min)
                ry1 = max(ry0 + 1, cy_max)
                rect.y = ry0
                rect.height = ry1 - ry0
            else:
                rect.y = max(0, ay)
                rect.height = max(1, ah)
        else:
            ry0 = max(0, ay - margin)
            ry1 = ay + ah + margin
            rect.y = ry0
            rect.height = max(1, ry1 - ry0)
            if click_pos is not None and aw > 160:
                cx_min = max(ax, int(click_pos[0] - 20))
                cx_max = min(ax + aw, int(click_pos[0] + 20))
                rx0 = max(0, cx_min)
                rx1 = max(rx0 + 1, cx_max)
                rect.x = rx0
                rect.width = rx1 - rx0
            else:
                rect.x = max(0, ax)
                rect.width = max(1, aw)

        return rect, chosen_pos

    def get_visible_page_indices(self, prefetch_margin: Optional[float] = None) -> List[int]:
        """Return sorted list of page indices intersecting visible viewport plus prefetch buffer."""
        if not self.doc or len(self.doc) == 0:
            return []

        if not self.continuous_scroll:
            if 0 <= self.current_page_index < len(self.doc):
                return [self.current_page_index]
            return [0]

        if not hasattr(self, 'continuous_page_offsets') or len(self.continuous_page_offsets) != len(self.doc):
            self._recompute_continuous_layout()

        num_pages = len(self.doc)
        _, scroll_y, _, vp_h = self.get_visible_viewport_rect()

        if prefetch_margin is None:
            if getattr(self, 'is_eco_mode', False):
                prefetch_margin = 0.0
            else:
                avg_h = (self.continuous_total_height / max(num_pages, 1)) if getattr(self, 'continuous_total_height', 0) > 0 else 800.0
                prefetch_margin = min(float(vp_h), float(avg_h) * 1.0)

        cull_top = scroll_y - prefetch_margin
        cull_bottom = scroll_y + vp_h + prefetch_margin

        fallback_idx = max(0, min(num_pages - 1, getattr(self, 'current_page_index', 0)))

        # Fast O(1) algebraic path for uniform geometry
        if getattr(self, '_is_geometry_uniform', False) and hasattr(self.continuous_page_offsets, 'stride'):
            stride = self.continuous_page_offsets.stride
            gap = self.continuous_page_offsets.gap
            ph = self.continuous_page_offsets.ph
            min_i = max(0, int(math.floor((cull_top - gap - ph) / stride) + 1))
            max_i = min(num_pages - 1, int(math.floor((cull_bottom - gap) / stride)))
            if min_i <= max_i:
                return list(range(min_i, max_i + 1))
            return [fallback_idx]

        if num_pages <= 32:
            visible = []
            for p_idx in range(num_pages):
                px, py, pw, ph = self.get_page_canvas_rect(p_idx)
                if (py + ph >= cull_top) and (py <= cull_bottom):
                    visible.append(p_idx)
            return visible if visible else [fallback_idx]

        # Binary search O(log N) for first visible page in large non-uniform documents
        lo, hi = 0, num_pages - 1
        while lo < hi:
            mid = (lo + hi) // 2
            _, py, _, ph = self.continuous_page_offsets[mid]
            if py + ph >= cull_top:
                hi = mid
            else:
                lo = mid + 1
        first_idx = lo

        visible = []
        for p_idx in range(first_idx, num_pages):
            _, py, _, ph = self.continuous_page_offsets[p_idx]
            if py > cull_bottom:
                break
            visible.append(p_idx)
        return visible if visible else [fallback_idx]

    def get_dominant_visible_page_index(self) -> int:
        """Calculate the page index with the largest visible area in the viewport."""
        if not self.doc or len(self.doc) == 0:
            return 0

        if not self.continuous_scroll:
            return self.current_page_index

        if not hasattr(self, 'continuous_page_offsets') or len(self.continuous_page_offsets) != len(self.doc):
            self._recompute_continuous_layout()

        _, scroll_y, _, vp_h = self.get_visible_viewport_rect()
        vp_top = scroll_y
        vp_bottom = scroll_y + vp_h

        # Fast O(1): only inspect candidate pages currently in viewport (prefetch_margin=0.0)
        candidate_pages = self.get_visible_page_indices(prefetch_margin=0.0)
        if not candidate_pages:
            candidate_pages = [max(0, min(len(self.doc) - 1, self.current_page_index))]

        max_vis_height = -1.0
        dominant_page = self.current_page_index

        for p_idx in candidate_pages:
            px, py, pw, ph = self.get_page_canvas_rect(p_idx)
            p_top = py
            p_bottom = py + ph

            vis_top = max(vp_top, p_top)
            vis_bottom = min(vp_bottom, p_bottom)
            vis_h = max(0.0, vis_bottom - vis_top)

            if vis_h > max_vis_height:
                max_vis_height = vis_h
                dominant_page = p_idx

        if max_vis_height <= 0.0:
            focal_y = vp_top + (vp_h * 0.4)
            closest_dist = float('inf')
            for p_idx in candidate_pages:
                _, py, _, ph = self.get_page_canvas_rect(p_idx)
                center_y = py + ph / 2.0
                dist = abs(center_y - focal_y)
                if dist < closest_dist:
                    closest_dist = dist
                    dominant_page = p_idx
        elif dominant_page != self.current_page_index and 0 <= self.current_page_index < len(self.doc):
            _, cpy, _, cph = self.get_page_canvas_rect(self.current_page_index)
            c_top = max(vp_top, cpy)
            c_bottom = min(vp_bottom, cpy + cph)
            cur_vis_h = max(0.0, c_bottom - c_top)
            if cur_vis_h > 0.0 and max_vis_height < cur_vis_h + 24.0:
                dominant_page = self.current_page_index

        return dominant_page

    def _on_canvas_scrolled(self, adjustment):
        """Handle canvas scroll adjustment value change to track visible page and sync indicators."""
        if not self.doc:
            return
        if getattr(self, '_is_programmatic_scrolling', False):
            return

        if not self.continuous_scroll:
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        # Directional predictive scroll velocity tracking and lookahead prefetching
        if hasattr(self, '_scroll_tracker'):
            cur_y = float(adjustment.get_value())
            self._scroll_tracker.record_scroll(cur_y)
            self._trigger_directional_prefetch()

        # Debounce settle timer to restore balanced lookahead when scrolling stops
        if getattr(self, '_scroll_settle_timer_id', None) is not None:
            try:
                GLib.source_remove(self._scroll_settle_timer_id)
            except Exception:
                pass
            self._scroll_settle_timer_id = None

        def _on_scroll_settle_timeout():
            self._scroll_settle_timer_id = None
            if hasattr(self, '_scroll_tracker'):
                self._scroll_tracker.reset()
                self._trigger_directional_prefetch()
            return GLib.SOURCE_REMOVE

        self._scroll_settle_timer_id = GLib.timeout_add(150, _on_scroll_settle_timeout)

        dominant = self.get_dominant_visible_page_index()
        if dominant != self.current_page_index:
            self._switch_active_page(dominant)
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def _trigger_directional_prefetch(self):
        """Submit non-blocking background rasterization for lookahead pages based on scroll velocity."""
        if not self.doc or getattr(self.doc, 'is_closed', False):
            return
        if not getattr(self, 'async_page_rendering', True):
            return
        if getattr(self, 'is_zoom_gesture_active', False):
            return

        total_pages = pdf_handler.get_page_count(self.doc)
        if total_pages <= 0:
            return

        if getattr(self, 'continuous_scroll', False):
            visible_pages = self.get_visible_page_indices(prefetch_margin=0.0)
        else:
            visible_pages = [self.current_page_index] if 0 <= self.current_page_index < total_pages else []

        if not visible_pages:
            return

        is_eco = getattr(self, 'is_eco_mode', False)
        prefetch_pages = self._scroll_tracker.get_prefetch_page_indices(
            visible_pages, total_pages, is_eco_mode=is_eco
        )

        for p_idx in prefetch_pages:
            if pdf_handler.peek_page_cairo_surface(self.doc, p_idx, self.zoom_level) is None:
                def _on_prefetched_ready(p, z, surf):
                    if not self.doc or getattr(self.doc, 'is_closed', False):
                        return
                    if abs(self.zoom_level - z) < 0.001 or pdf_handler.peek_page_cairo_surface(self.doc, p, self.zoom_level) is None:
                        if hasattr(self, 'pdf_view') and self.pdf_view:
                            vis_now = self.get_visible_page_indices(prefetch_margin=0.0) if getattr(self, 'continuous_scroll', False) else [self.current_page_index]
                            if p in vis_now:
                                self.pdf_view.queue_draw()

                pdf_handler.request_page_cairo_surface(
                    self.doc, p_idx, self.zoom_level,
                    callback=_on_prefetched_ready,
                    progressive=True
                )

    def _sync_window_title_and_subtitle(self):
        """Update window title and header subtitle with current session and page info."""
        if not self.doc:
            title = constants.APP_NAME
            subtitle = ""
        else:
            title = self._active_session.display_title if self._active_session else constants.APP_NAME
            count = pdf_handler.get_page_count(self.doc)
            subtitle = _("page_info_count").format(self.current_page_index + 1, count) if count > 0 else ""
            self.set_title(f"{constants.APP_NAME} - {title}")
        if hasattr(self, 'window_title_widget') and self.window_title_widget:
            self.window_title_widget.set_title(title)
            self.window_title_widget.set_subtitle(subtitle)

    def set_continuous_scroll_mode(self, enabled: bool):
        """Switch viewing mode between continuous vertical scrolling and single-page view."""
        enabled = bool(enabled)
        if self.continuous_scroll == enabled:
            if hasattr(self, 'continuous_scroll_btn') and self.continuous_scroll_btn:
                if self.continuous_scroll_btn.get_active() != enabled:
                    self.continuous_scroll_btn.set_active(enabled)
                self.continuous_scroll_btn.set_icon_name("view-continuous-symbolic" if enabled else "view-paged-symbolic")
            return

        target_page = self.get_dominant_visible_page_index() if self.continuous_scroll else self.current_page_index

        self.continuous_scroll = enabled
        set_setting("view_mode", "continuous" if enabled else "single")

        if hasattr(self, 'continuous_scroll_btn') and self.continuous_scroll_btn:
            if self.continuous_scroll_btn.get_active() != enabled:
                self.continuous_scroll_btn.set_active(enabled)
            self.continuous_scroll_btn.set_icon_name("view-continuous-symbolic" if enabled else "view-paged-symbolic")

        action = self.lookup_action("toggle_continuous_scroll")
        if action and action.get_state().get_boolean() != enabled:
            action.set_state(GLib.Variant.new_boolean(enabled))

        if not self.doc or len(self.doc) == 0:
            return

        if enabled:
            self._recompute_continuous_layout()
            self._update_canvas_content_size()
            if hasattr(self, 'continuous_page_offsets') and 0 <= target_page < len(self.continuous_page_offsets):
                target_y = self.continuous_page_offsets[target_page][1]
                v_adj = self.pdf_scroll.get_vadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
                if v_adj:
                    self._is_programmatic_scrolling = True
                    v_adj.set_value(target_y)
                    self._is_programmatic_scrolling = False
            self._switch_active_page(target_page)
        else:
            self._load_page(target_page)

    def set_ocr_overlay_mode(self, enabled: bool):
        """Toggle visualization overlay of OCR / invisible searchable text bounding boxes."""
        self.show_ocr_overlay = bool(enabled)
        if hasattr(self, 'ocr_overlay_btn') and self.ocr_overlay_btn:
            if self.ocr_overlay_btn.get_active() != self.show_ocr_overlay:
                self.ocr_overlay_btn.set_active(self.show_ocr_overlay)

        action = self.lookup_action("toggle_ocr_overlay")
        if action and action.get_state().get_boolean() != self.show_ocr_overlay:
            action.set_state(GLib.Variant.new_boolean(self.show_ocr_overlay))

        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def set_eco_mode(self, enabled: bool):
        """Enable or disable hardware-adaptive Eco / Low-Spec Mode."""
        self.is_eco_mode = bool(enabled)
        set_eco_mode_enabled(self.is_eco_mode)
        pdf_handler.configure_memory_limits(self.is_eco_mode)

        action = self.lookup_action("toggle_eco_mode")
        if action and action.get_state().get_boolean() != self.is_eco_mode:
            action.set_state(GLib.Variant.new_boolean(self.is_eco_mode))

        # Clamp zoom if exceeding eco DPI ceiling (150 DPI = 150/72 = 2.0833x)
        if self.is_eco_mode and getattr(self, 'zoom_level', 1.0) > (150.0 / 72.0):
            self._set_zoom(150.0 / 72.0)

        # Evict cache surfaces down to eco budget
        if hasattr(pdf_handler, '_cairo_page_cache'):
            pdf_handler._cairo_page_cache._evict_as_needed()
        gc.collect(1)

        if getattr(self, 'continuous_scroll', False):
            self._invalidate_continuous_layout()

        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def scroll_to_page(self, page_index: int, smooth: bool = True, duration_ms: int = 250):
        """Navigate to target page, using smooth animation in continuous mode if requested."""
        if not self.doc or not (0 <= page_index < len(self.doc)):
            return

        if not self.continuous_scroll:
            self._load_page(page_index)
            return

        if not hasattr(self, 'continuous_page_offsets') or len(self.continuous_page_offsets) != len(self.doc):
            self._recompute_continuous_layout()

        target_y = self.continuous_page_offsets[page_index][1]
        v_adj = self.pdf_scroll.get_vadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
        if not v_adj:
            self._switch_active_page(page_index)
            return

        if hasattr(self, '_scroll_anim_id') and self._scroll_anim_id:
            try:
                GLib.source_remove(self._scroll_anim_id)
            except Exception:
                pass
            self._scroll_anim_id = None

        self._switch_active_page(page_index)

        start_y = v_adj.get_value()
        delta_y = target_y - start_y

        if hasattr(self, '_scroll_tracker'):
            if delta_y > 2.0:
                self._scroll_tracker._last_direction = ScrollVelocityTracker.DIRECTION_DOWN
                self._scroll_tracker._last_velocity = 800.0
            elif delta_y < -2.0:
                self._scroll_tracker._last_direction = ScrollVelocityTracker.DIRECTION_UP
                self._scroll_tracker._last_velocity = -800.0
            self._trigger_directional_prefetch()

        if (not smooth) or duration_ms <= 0 or abs(delta_y) < 2.0:
            self._is_programmatic_scrolling = True
            v_adj.set_value(target_y)
            self._is_programmatic_scrolling = False
            if hasattr(self, '_scroll_tracker'):
                self._scroll_tracker.reset()
                self._trigger_directional_prefetch()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        start_time = GLib.get_monotonic_time() / 1000.0
        duration = float(duration_ms)
        self._is_programmatic_scrolling = True

        def _step():
            now = GLib.get_monotonic_time() / 1000.0
            elapsed = now - start_time
            t = min(1.0, max(0.0, elapsed / duration))
            ease = 1.0 - (1.0 - t) ** 3
            current_y = start_y + (delta_y * ease)
            v_adj.set_value(current_y)
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            if t >= 1.0:
                v_adj.set_value(target_y)
                self._is_programmatic_scrolling = False
                self._scroll_anim_id = None
                if hasattr(self, '_scroll_tracker'):
                    self._scroll_tracker.reset()
                    self._trigger_directional_prefetch()
                if hasattr(self, 'pdf_view') and self.pdf_view:
                    self.pdf_view.queue_draw()
                return False
            return True

        self._scroll_anim_id = GLib.timeout_add(16, _step)

    def go_to_page(self, page_number: int, smooth: bool = True):
        """Navigate to 1-based page number."""
        if not self.doc or len(self.doc) == 0:
            return
        target_idx = max(0, min(int(page_number) - 1, len(self.doc) - 1))
        self.scroll_to_page(target_idx, smooth=smooth)

    def show_go_to_page_dialog(self):
        """Display Go to Page modal dialog to jump to user-entered page number."""
        if not self.doc or len(self.doc) == 0:
            return

        total_pages = len(self.doc)
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("go_to_page_title"),
            body=_("go_to_page_label").format(total_pages)
        )
        dialog.add_response("cancel", _("btn_cancel"))
        dialog.add_response("go", _("btn_go"))
        dialog.set_response_appearance("go", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("go")
        dialog.set_close_response("cancel")

        spin = Gtk.SpinButton.new_with_range(1, total_pages, 1)
        spin.set_value(self.current_page_index + 1)
        spin.set_halign(Gtk.Align.CENTER)
        spin.set_activates_default(True)
        dialog.set_extra_child(spin)

        def on_response(dlg, response):
            if response == "go":
                target_page_num = int(spin.get_value())
                self.go_to_page(target_page_num)
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.present()

    def canvas_to_page_coords(self, canvas_x: float, canvas_y: float) -> Tuple[int, float, float]:
        """Convert canvas coordinates to (page_index, unzoomed_page_x, unzoomed_page_y)."""
        if not self.doc or len(self.doc) == 0:
            return (0, canvas_x / max(self.zoom_level, 0.001), canvas_y / max(self.zoom_level, 0.001))

        if not self.continuous_scroll:
            px, py, _, _ = self.get_page_canvas_rect(self.current_page_index)
            page_x = (canvas_x - px) / max(self.zoom_level, 0.001)
            page_y = (canvas_y - py) / max(self.zoom_level, 0.001)
            return (self.current_page_index, page_x, page_y)

        if not hasattr(self, 'continuous_page_offsets') or len(self.continuous_page_offsets) != len(self.doc):
            self._recompute_continuous_layout()

        target_page = 0
        num_pages = len(self.doc)
        if canvas_y < self.continuous_page_offsets[0][1]:
            target_page = 0
        elif canvas_y >= self.continuous_page_offsets[-1][1] + self.continuous_page_offsets[-1][3]:
            target_page = num_pages - 1
        else:
            if getattr(self, '_is_geometry_uniform', False) and hasattr(self.continuous_page_offsets, 'stride'):
                stride = self.continuous_page_offsets.stride
                gap = self.continuous_page_offsets.gap
                target_page = int(math.floor((canvas_y - gap / 2.0) / max(stride, 1.0)))
                target_page = max(0, min(num_pages - 1, target_page))
            elif num_pages <= 32:
                for idx in range(num_pages):
                    _, py, _, ph = self.continuous_page_offsets[idx]
                    gap_boundary = py + ph + (self.page_gap / 2.0)
                    if canvas_y < gap_boundary:
                        target_page = idx
                        break
            else:
                lo, hi = 0, num_pages - 1
                half_gap = self.page_gap / 2.0
                while lo < hi:
                    mid = (lo + hi) // 2
                    _, py, _, ph = self.continuous_page_offsets[mid]
                    if canvas_y < py + ph + half_gap:
                        hi = mid
                    else:
                        lo = mid + 1
                target_page = lo

        px, py, _, _ = self.get_page_canvas_rect(target_page)
        page_x = (canvas_x - px) / max(self.zoom_level, 0.001)
        page_y = (canvas_y - py) / max(self.zoom_level, 0.001)
        return (target_page, page_x, page_y)

    def page_to_canvas_coords(self, page_index: int, page_x_unzoomed: float, page_y_unzoomed: float) -> Tuple[float, float]:
        """Convert unzoomed page coordinates on page_index to canvas coordinates."""
        px, py, _, _ = self.get_page_canvas_rect(page_index)
        canvas_x = px + page_x_unzoomed * self.zoom_level
        canvas_y = py + page_y_unzoomed * self.zoom_level
        return (canvas_x, canvas_y)

    def is_canvas_point_on_page(self, canvas_x: float, canvas_y: float, page_index: int) -> bool:
        """Return True if canvas (x, y) is inside the boundary of page_index."""
        px, py, pw, ph = self.get_page_canvas_rect(page_index)
        return (px <= canvas_x < px + pw) and (py <= canvas_y < py + ph)

    def _get_page_objects(self, page_index: int, extract_if_missing: bool = False) -> Dict[str, Any]:
        """Retrieve editable objects for a page, using cache if available."""
        if not self.doc or not (0 <= page_index < len(self.doc)):
            return {'texts': [], 'images': [], 'shapes': [], 'strokes': [], 'form_fields': []}
        if page_index == self.current_page_index:
            return {
                'texts': self.editable_texts,
                'images': self.editable_images,
                'shapes': self.editable_shapes,
                'strokes': self.editable_strokes,
                'form_fields': self.form_fields,
            }
        if page_index in self._page_objects_cache:
            return self._page_objects_cache[page_index]

        if not extract_if_missing:
            return {'texts': [], 'images': [], 'shapes': [], 'strokes': [], 'form_fields': []}

        texts, _ = pdf_handler.extract_editable_text(self.doc, page_index)
        images, _ = pdf_handler.extract_editable_images(self.doc, page_index)
        shapes, _ = pdf_handler.extract_editable_shapes(self.doc, page_index)
        strokes, _ = pdf_handler.extract_editable_strokes(self.doc, page_index)
        form_fields, _ = pdf_handler.extract_acroform_fields(self.doc, page_index)

        objs = {
            'texts': texts or [],
            'images': images or [],
            'shapes': shapes or [],
            'strokes': strokes or [],
            'form_fields': form_fields or [],
        }
        self._page_objects_cache[page_index] = objs
        return objs

    def _stash_page_objects(self, page_index: int):
        """Stash active collections into page objects cache."""
        if page_index is None or not self.doc or not (0 <= page_index < len(self.doc)):
            return
        self._page_objects_cache[page_index] = {
            'texts': list(self.editable_texts),
            'images': list(self.editable_images),
            'shapes': list(self.editable_shapes),
            'strokes': list(self.editable_strokes),
            'form_fields': list(self.form_fields),
        }

    def _restore_page_objects(self, page_index: int):
        """Restore collections for page_index from cache or extract from PDF."""
        if page_index is None or not self.doc or not (0 <= page_index < len(self.doc)):
            return
        if page_index in self._page_objects_cache:
            cached = self._page_objects_cache[page_index]
            self.editable_texts = cached.get('texts', [])
            self.editable_images = cached.get('images', [])
            self.editable_shapes = cached.get('shapes', [])
            self.editable_strokes = cached.get('strokes', [])
            self.form_fields = cached.get('form_fields', [])
        else:
            texts, _ = pdf_handler.extract_editable_text(self.doc, page_index)
            self.editable_texts = texts or []
            images, _ = pdf_handler.extract_editable_images(self.doc, page_index)
            self.editable_images = images or []
            shapes, _ = pdf_handler.extract_editable_shapes(self.doc, page_index)
            self.editable_shapes = shapes or []
            strokes, _ = pdf_handler.extract_editable_strokes(self.doc, page_index)
            self.editable_strokes = strokes or []
            form_fields, _ = pdf_handler.extract_acroform_fields(self.doc, page_index)
            self.form_fields = form_fields or []
            self._page_objects_cache[page_index] = {
                'texts': self.editable_texts,
                'images': self.editable_images,
                'shapes': self.editable_shapes,
                'strokes': self.editable_strokes,
                'form_fields': self.form_fields,
            }
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(page_index)

    def _switch_active_page(self, page_index: int):
        """Switch active page without resetting entire canvas layout in continuous mode."""
        if not self.doc or not (0 <= page_index < len(self.doc)):
            return
        if page_index == self.current_page_index:
            return

        self.commit_pending_format_change()
        if self.inline_editor_widget is not None:
            self._apply_and_hide_editor(force_apply=True)

        old_page = self.current_page_index
        if old_page is not None and (0 <= old_page < len(self.doc)):
            self._stash_page_objects(old_page)
            if abs(page_index - old_page) > 2:
                gc.collect(1)

        self.current_page_index = page_index
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.hide_text_editor()
        self._clear_form_field_overlays()

        self._restore_page_objects(page_index)

        page = self.doc.load_page(page_index)
        self.current_pdf_page_width = int(page.rect.width * self.zoom_level)
        self.current_pdf_page_height = int(page.rect.height * self.zoom_level)

        if not self.continuous_scroll:
            self.pdf_view.set_content_width(self.current_pdf_page_width)
            self.pdf_view.set_content_height(self.current_pdf_page_height)

        self._sync_thumbnail_selection()
        self._update_ui_state()
        self._sync_window_title_and_subtitle()
        self._create_form_field_overlays()
        self.pdf_view.queue_draw()

    def _load_page(self, page_index, preserve_scroll=False, reload_objects=False):
        """Extract editable objects, dimensions, and render page at given index."""
        current_v_scroll = 0
        current_h_scroll = 0
        if preserve_scroll:
            v_adj = self.pdf_scroll.get_vadjustment()
            h_adj = self.pdf_scroll.get_hadjustment()
            if v_adj:
                current_v_scroll = v_adj.get_value()
            if h_adj:
                current_h_scroll = h_adj.get_value()

        if not self.doc or not (0 <= page_index < pdf_handler.get_page_count(self.doc)):
            print(f"Warning: Invalid attempt to load page {page_index}.")
            return

        self.commit_pending_format_change()

        old_page_idx = getattr(self, 'current_page_index', None)
        if hasattr(self, '_scroll_tracker') and old_page_idx is not None:
            if page_index > old_page_idx:
                self._scroll_tracker._last_direction = ScrollVelocityTracker.DIRECTION_DOWN
                self._scroll_tracker._last_velocity = 200.0
            elif page_index < old_page_idx:
                self._scroll_tracker._last_direction = ScrollVelocityTracker.DIRECTION_UP
                self._scroll_tracker._last_velocity = -200.0
        if self.doc and old_page_idx is not None and (0 <= old_page_idx < pdf_handler.get_page_count(self.doc)):
            if old_page_idx != page_index:
                old_key = (id(self.doc), old_page_idx)
                if old_key not in pdf_handler._page_snapshots:
                    pdf_handler.save_page_snapshot(self.doc, old_page_idx)
                self._stash_page_objects(old_page_idx)
                if abs(page_index - old_page_idx) > 2:
                    gc.collect(1)

        # Do not clear undo_manager on page navigation! Undo history belongs to the document session.

        self.current_page_index = page_index
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.hide_text_editor()
        self._clear_form_field_overlays()

        if reload_objects:
            pdf_handler.invalidate_page_cache(self.doc, page_index)
            texts, error = pdf_handler.extract_editable_text(self.doc, page_index)
            if error:
                show_error_dialog(self, _("text_extract_error", page_index + 1, error))
                self.editable_texts = []
            else:
                self.editable_texts = texts
                
            images, error = pdf_handler.extract_editable_images(self.doc, page_index)
            if error:
                show_error_dialog(self, _("image_extract_error").format(page_index + 1, error))
                self.editable_images = []
            else:
                self.editable_images = images

            shapes, shapes_error = pdf_handler.extract_editable_shapes(self.doc, page_index)
            if shapes_error:
                print(f"Warning: Could not extract shapes from page {page_index + 1}: {shapes_error}")
                self.editable_shapes = []
            else:
                self.editable_shapes = shapes

            strokes, strokes_error = pdf_handler.extract_editable_strokes(self.doc, page_index)
            if strokes_error:
                print(f"Warning: Could not extract strokes from page {page_index + 1}: {strokes_error}")
                self.editable_strokes = []
            else:
                self.editable_strokes = strokes

            form_fields, form_fields_error = pdf_handler.extract_acroform_fields(self.doc, page_index)
            if form_fields_error:
                print(f"Warning: Could not extract form fields from page {page_index + 1}: {form_fields_error}")
                self.form_fields = []
            else:
                self.form_fields = form_fields

            self._page_objects_cache[page_index] = {
                'texts': self.editable_texts,
                'images': self.editable_images,
                'shapes': self.editable_shapes,
                'strokes': self.editable_strokes,
                'form_fields': self.form_fields,
            }
        else:
            self._restore_page_objects(page_index)

        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(page_index)

        page = self.doc.load_page(page_index)
        self.current_pdf_page_width = int(page.rect.width * self.zoom_level)
        self.current_pdf_page_height = int(page.rect.height * self.zoom_level)

        if self.continuous_scroll:
            self._update_canvas_content_size()
        else:
            self.pdf_view.set_content_width(self.current_pdf_page_width)
            self.pdf_view.set_content_height(self.current_pdf_page_height)

        self.pdf_view.queue_draw()
        if getattr(self, 'async_page_rendering', True) and self.doc and not getattr(self.doc, 'is_closed', False):
            pdf_handler.request_page_cairo_surface(self.doc, page_index, self.zoom_level, progressive=True)
            if hasattr(self, '_trigger_directional_prefetch'):
                self._trigger_directional_prefetch()
            elif not getattr(self, 'is_eco_mode', False):
                if page_index + 1 < pdf_handler.get_page_count(self.doc):
                    pdf_handler.request_page_cairo_surface(self.doc, page_index + 1, self.zoom_level)
                if page_index - 1 >= 0:
                    pdf_handler.request_page_cairo_surface(self.doc, page_index - 1, self.zoom_level)
        
        if preserve_scroll:
            self._is_programmatic_scrolling = True
            def _restore_scroll():
                v_adj = self.pdf_scroll.get_vadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
                h_adj = self.pdf_scroll.get_hadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
                if v_adj:
                    v_adj.set_value(current_v_scroll)
                if h_adj:
                    h_adj.set_value(current_h_scroll)
                self._is_programmatic_scrolling = False
                return False
            GLib.idle_add(_restore_scroll)
        elif self.continuous_scroll and hasattr(self, 'continuous_page_offsets') and 0 <= page_index < len(self.continuous_page_offsets):
            target_y = self.continuous_page_offsets[page_index][1]
            self._is_programmatic_scrolling = True
            def _apply_scroll():
                v_adj = self.pdf_scroll.get_vadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
                if v_adj:
                    v_adj.set_value(target_y)
                self._is_programmatic_scrolling = False
                return False
            GLib.idle_add(_apply_scroll)
        elif not self.continuous_scroll:
            self._is_programmatic_scrolling = True
            def _reset_single_page_scroll():
                v_adj = self.pdf_scroll.get_vadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
                h_adj = self.pdf_scroll.get_hadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
                if v_adj:
                    v_adj.set_value(0.0)
                if h_adj:
                    h_adj.set_value(0.0)
                self._is_programmatic_scrolling = False
                return False
            GLib.idle_add(_reset_single_page_scroll)

        self._sync_thumbnail_selection()
        self._update_ui_state()
        self._sync_window_title_and_subtitle()
        self._create_form_field_overlays()
        
        fallback_font = None
        for text_obj in self.editable_texts:
            if getattr(text_obj, 'font_fallback_used', False):
                fallback_font = text_obj.font_fallback_used
                break
        if fallback_font:
            self.status_label.set_text(f"font cannot be determinated, using {fallback_font}")
        
        if self.doc:
            key = (id(self.doc), page_index)
            if key not in pdf_handler._page_snapshots:
                pdf_handler.save_page_snapshot(self.doc, page_index)

    def close_document(self):
        """Close document."""
        if hasattr(self, '_active_session') and self._active_session:
            if self._active_session.undo_manager:
                self._active_session.undo_manager.clear()
            self._active_session.is_repaired_file = False
            if self._active_session.doc:
                pdf_handler.release_page_snapshots(self._active_session.doc)
                pdf_handler.close_pdf_document(self._active_session.doc)
            self._active_session.close()
            self._active_session.pdf_path = None
            self._active_session.original_file_path = None
            self._active_session.current_page_index = 0
            self._active_session.is_modified = False
            if self._active_session.pages_model:
                self._active_session.pages_model.remove_all()
        self._update_signature_banner(None)
        self.temp_stroke = None
        self.selected_form_field = None
        if hasattr(self, 'search_engine') and self.search_engine:
            self.search_engine.cancel_async_search()
            self.search_engine.clear()
        self.hide_text_editor()
        self._clear_form_field_overlays()
        self._page_objects_cache.clear()
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index()
        self._invalidate_continuous_layout()
        if getattr(self, '_scroll_settle_timer_id', None) is not None:
            try:
                GLib.source_remove(self._scroll_settle_timer_id)
            except Exception:
                pass
            self._scroll_settle_timer_id = None
        if hasattr(self, '_scroll_tracker'):
            self._scroll_tracker.reset()
        self.pdf_view.set_content_width(1)
        self.pdf_view.set_content_height(1)
        self.pdf_view.queue_draw()
        self._update_ui_state()
        gc.collect(1)

    def _on_tab_bar_pressed(self, gesture, n_press, x, y):
        """Switch back to editor if clicking the tab bar while on welcome screen."""
        if hasattr(self, 'stack') and self.stack and self.stack.get_visible_child_name() == "welcome":
            if any(s.doc is not None for s in self.sessions):
                self.stack.set_visible_child_name("editor")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_autohide(False)
                    self.tab_bar.set_visible(True)
                if self._active_session and self._active_session.doc is not None:
                    self.set_title(f"{constants.APP_NAME} - {self._active_session.display_title}")

    def go_to_welcome(self):
        """Navigate to welcome hub view."""
        if hasattr(self, 'stack') and self.stack:
            if self.stack.get_visible_child_name() == "welcome":
                # Toggle back to editor if any document is open
                active = self._active_session if (self._active_session and self._active_session.doc is not None) else None
                if not active:
                    for s in self.sessions:
                        if s.doc is not None:
                            active = s
                            break
                if active:
                    self.set_active_session(active)
                    self.stack.set_visible_child_name("editor")
                    if hasattr(self, 'tab_bar') and self.tab_bar:
                        self.tab_bar.set_autohide(False)
                        self.tab_bar.set_visible(True)
                    self.set_title(f"{constants.APP_NAME} - {active.display_title}")
                    return

        if self.check_unsaved_changes():
            return

        old_welcome = self.stack.get_child_by_name("welcome")
        if old_welcome:
            self.stack.remove(old_welcome)
        new_welcome = WelcomeView(parent_window=self)
        self.stack.add_named(new_welcome, "welcome")

        self.stack.set_visible_child_name("welcome")
        has_open_docs = any(s.doc is not None for s in self.sessions)
        if hasattr(self, 'tab_bar') and self.tab_bar:
            self.tab_bar.set_autohide(not has_open_docs)
            self.tab_bar.set_visible(has_open_docs)
        self.set_title(constants.APP_NAME)

    def on_close_tab(self, action=None, param=None):
        """Close the currently active tab or document."""
        if hasattr(self, 'tab_view') and self.tab_view:
            selected_page = self.tab_view.get_selected_page()
            if selected_page:
                self.tab_view.close_page(selected_page)
                return
        if self.check_unsaved_changes():
            return
        self.close_document()

    def on_next_tab(self, action=None, param=None):
        """Switch to next document tab."""
        if hasattr(self, 'tab_view') and self.tab_view and self.tab_view.get_n_pages() > 1:
            self.tab_view.select_next_page()

    def on_prev_tab(self, action=None, param=None):
        """Switch to previous document tab."""
        if hasattr(self, 'tab_view') and self.tab_view and self.tab_view.get_n_pages() > 1:
            self.tab_view.select_previous_page()



    def save_document(self, save_path, incremental=False, background=True, on_finish=None):
        """Save document using background worker thread or synchronous rewrite."""
        if not self.doc or (getattr(self, 'is_saving', False) is True):
            if getattr(self, 'is_saving', False) is True:
                print("Save already in progress, skipping concurrent save.")
            return
        page_to_restore = self.current_page_index
        target_sess = self._active_session
        self.is_saving = True
        if target_sess:
            target_sess.is_saving = True

        if hasattr(self, 'save_spinner') and self.save_spinner:
            self.save_spinner.set_visible(True)
            self.save_spinner.start()

        self.status_label.set_text(_("saving").format(os.path.basename(save_path)))
        if self.inline_editor_widget is not None:
            self._apply_and_hide_editor(force_apply=True)
        if hasattr(self, '_commit_pending_form_field_edit'):
            self._commit_pending_form_field_edit()

        if target_sess and getattr(target_sess, 'scale_calibration', None):
            pdf_handler.embed_scale_calibration(self.doc, target_sess.scale_calibration.to_dict())

        if target_sess:
            all_meas_dicts = []
            for p_idx, m_list in target_sess.measurements.items():
                for m in m_list:
                    all_meas_dicts.append(m.to_dict())
            if all_meas_dicts:
                pdf_handler.embed_measurements(self.doc, all_meas_dicts)
            pdf_handler.sync_sticky_notes(self.doc, getattr(target_sess, 'sticky_notes', {}))
            if getattr(target_sess, 'redaction_marks', None):
                self.apply_all_redactions(prompt_warning=False)
            if hasattr(target_sess, 'pdf_password'):
                self.doc._pdf_password = target_sess.pdf_password
            if hasattr(target_sess, 'pdf_owner_password'):
                self.doc._pdf_owner_password = target_sess.pdf_owner_password
            if hasattr(target_sess, 'pdf_permissions'):
                self.doc._pdf_permissions = target_sess.pdf_permissions
            if getattr(target_sess, 'is_vault', False):
                self.doc._is_vault = True
                self.doc._vault_password = getattr(target_sess, 'vault_password', None)

        def _do_save_worker():
            try:
                return pdf_handler.save_document(self.doc, save_path, incremental=incremental)
            except Exception as e:
                return False, str(e)

        def _on_save_completed(success, error_msg):
            self.is_saving = False
            if target_sess:
                target_sess.is_saving = False

            if hasattr(self, 'save_spinner') and self.save_spinner:
                self.save_spinner.stop()
                self.save_spinner.set_visible(False)

            if success:
                print(_("dbg_save_success", save_path))
                self.document_modified = False 
                if target_sess:
                    target_sess.is_modified = False
                    target_sess.pdf_path = save_path
                    target_sess.original_file_path = save_path
                    self._update_tab_title(target_sess)
                    self.set_title(f"{constants.APP_NAME} - {target_sess.display_title}")
                if self.doc:
                    self.doc._is_modified = False

                # File is now actually saved on disk; write thumbnail for the saved file to disk cache
                try:
                    thumb_w = 100 if getattr(self, 'is_eco_mode', False) else 150
                    if self.doc and 0 <= page_to_restore < pdf_handler.get_page_count(self.doc):
                        pdf_handler.generate_thumbnail(
                            self.doc, page_to_restore, target_width=thumb_w, filepath=save_path, save_to_disk=True
                        )
                        if thumb_w != 150:
                            pdf_handler.generate_thumbnail(
                                self.doc, page_to_restore, target_width=150, filepath=save_path, save_to_disk=True
                            )
                except Exception as e:
                    print(f"Warning caching thumbnail on save: {e}")

                self.load_document(save_path, target_page=page_to_restore, in_new_tab=False)
                self.status_label.set_text(_("saved").format(os.path.basename(save_path)))
            else:
                show_error_dialog(self, _("err_pdf_save", error_msg))
                self.status_label.set_text(_("save_failed"))

            self._update_ui_state()

            if on_finish and callable(on_finish):
                try:
                    on_finish(success, error_msg)
                except Exception as cb_err:
                    print(f"Warning in on_finish save callback: {cb_err}")

            return False

        if background:
            def _thread_target():
                succ, err = _do_save_worker()
                GLib.idle_add(_on_save_completed, succ, err)

            self._save_thread = threading.Thread(target=_thread_target, daemon=True)
            self._save_thread.start()
        else:
            succ, err = _do_save_worker()
            _on_save_completed(succ, err)

    def wait_for_save(self, timeout=5.0):
        """Wait for in-flight background save to complete and process idle callbacks."""
        thread = getattr(self, '_save_thread', None)
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        ctx = GLib.MainContext.default()
        iterations = 0
        while (getattr(self, 'is_saving', False) is True or ctx.pending()) and iterations < 100:
            ctx.iteration(False)
            iterations += 1

    def queue_canvas_dirty_rect(self, rect):
        """Schedule a sub-rectangle dirty region repaint on the canvas."""
        if rect:
            if getattr(self, '_dirty_clip_rect', None) is None:
                self._dirty_clip_rect = rect
            else:
                x1 = min(self._dirty_clip_rect[0], rect[0])
                y1 = min(self._dirty_clip_rect[1], rect[1])
                x2 = max(self._dirty_clip_rect[0] + self._dirty_clip_rect[2], rect[0] + rect[2])
                y2 = max(self._dirty_clip_rect[1] + self._dirty_clip_rect[3], rect[1] + rect[3])
                self._dirty_clip_rect = (x1, y1, x2 - x1, y2 - y1)
        self.pdf_view.queue_draw()

    def draw_pdf_page(self, area, cr, width, height, dirty_rect=None):
        """Draw PDF page with optional sub-rectangle dirty clipping."""
        if not self.doc:
            cr.set_source_rgb(0.42, 0.42, 0.42)
            cr.paint()
            return

        if dirty_rect is None and getattr(self, '_dirty_clip_rect', None) is not None:
            dirty_rect = self._dirty_clip_rect
            self._dirty_clip_rect = None

        if getattr(self, 'continuous_scroll', False):
            vx, vy, vw, vh = self.get_visible_viewport_rect()
            cr.save()
            cr.rectangle(max(0.0, vx - 20.0), max(0.0, vy - 20.0), vw + 40.0, vh + 40.0)
            cr.clip()
            cr.set_source_rgb(0.42, 0.42, 0.42)
            cr.paint()
            cr.restore()
        else:
            if self.current_pdf_page_width <= 0:
                cr.set_source_rgb(0.42, 0.42, 0.42)
                cr.paint()
                return

            page_w = float(self.current_pdf_page_width)
            page_h = float(self.current_pdf_page_height)
            page_offset_x = max(0.0, (width - page_w) / 2.0)
            page_offset_y = max(0.0, (height - page_h) / 2.0)

            # Paint canvas background only in the margins outside the page, preventing dark gray flashing
            cr.save()
            cr.set_source_rgb(0.42, 0.42, 0.42)
            cr.rectangle(0, 0, width, height)
            cr.rectangle(page_offset_x, page_offset_y, page_w, page_h)
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            cr.fill()
            cr.restore()

            cr.save()
            cr.set_source_rgba(0, 0, 0, 0.15)
            cr.rectangle(page_offset_x + 4.0, page_offset_y + 4.0, page_w, page_h)
            cr.fill()
            cr.restore()

            self._draw_page_content(area, cr, self.current_page_index, page_offset_x, page_offset_y, page_w, page_h, dirty_rect=dirty_rect)
            return

        if not hasattr(self, 'continuous_page_offsets') or len(self.continuous_page_offsets) != len(self.doc):
            self._recompute_continuous_layout()

        visible_pages = self.get_visible_page_indices()
        for p_idx in visible_pages:
            px, py, pw, ph = self.get_page_canvas_rect(p_idx)

            # Skip pages completely outside dirty rect when specified
            if dirty_rect is not None:
                dx, dy, dw, dh = dirty_rect
                if px + pw < dx or px > dx + dw or py + ph < dy or py > dy + dh:
                    continue

            cr.save()
            cr.set_source_rgba(0, 0, 0, 0.15)
            cr.rectangle(px + 4.0, py + 4.0, pw, ph)
            cr.fill()
            cr.restore()

            self._draw_page_content(area, cr, p_idx, px, py, pw, ph, dirty_rect=dirty_rect)

    def _draw_page_content(self, area, cr, page_index, page_offset_x, page_offset_y, page_w, page_h, dirty_rect=None):
        """Render single page contents including Cairo surface, objects, annotations, and overlays."""
        cr.save()
        cr.translate(page_offset_x, page_offset_y)
        if dirty_rect is not None:
            cr.rectangle(dirty_rect[0] * self.zoom_level, dirty_rect[1] * self.zoom_level,
                         dirty_rect[2] * self.zoom_level, dirty_rect[3] * self.zoom_level)
            cr.clip()

        tiler = pdf_handler.get_tiled_page_renderer()
        page_unscaled_w = page_w / self.zoom_level
        page_unscaled_h = page_h / self.zoom_level
        use_tiling = tiler.is_tiling_required(page_unscaled_w, page_unscaled_h, self.zoom_level)

        if use_tiling:
            vp_rect = self.get_visible_viewport_rect()
            visible_tiles = tiler.get_visible_tile_coords(
                page_offset_x, page_offset_y, page_unscaled_w, page_unscaled_h,
                self.zoom_level, vp_rect, margin_tiles=1
            )
            active_tile_set = set(visible_tiles)

            for col, row in visible_tiles:
                tx0, ty0, tw, th = tiler.get_tile_pixel_rect(
                    col, row, page_unscaled_w, page_unscaled_h, self.zoom_level
                )
                tile_surf = tiler.peek_tile(self.doc, page_index, self.zoom_level, col, row)
                if (
                    tile_surf is not None
                    and getattr(tile_surf, 'get_width', lambda: 0)() > 0
                    and getattr(tile_surf, 'get_height', lambda: 0)() > 0
                ):
                    cr.save()
                    cr.set_source_surface(tile_surf, tx0, ty0)
                    cr.rectangle(tx0, ty0, tw, th)
                    cr.fill()
                    cr.restore()
                else:
                    def _on_tile_ready(c, r, surf):
                        if not self.doc or getattr(self.doc, 'is_closed', False):
                            return
                        if hasattr(self, 'pdf_view') and self.pdf_view:
                            self.pdf_view.queue_draw()

                    tiler.request_tile(
                        self.doc, page_index, self.zoom_level, col, row, callback=_on_tile_ready
                    )

                    best_match = pdf_handler.get_page_rasterizer_pool().find_best_cached_surface(
                        self.doc, page_index, self.zoom_level
                    )
                    rendered_tile_fallback = False
                    if best_match is not None:
                        alt_surf, alt_zoom = best_match
                        if alt_zoom > 0:
                            scale_factor = self.zoom_level / alt_zoom
                            cr.save()
                            cr.rectangle(tx0, ty0, tw, th)
                            cr.clip()
                            cr.scale(scale_factor, scale_factor)
                            cr.set_source_surface(alt_surf, 0, 0)
                            pat = cr.get_source()
                            if pat is not None:
                                pat.set_filter(cairo.FILTER_BILINEAR)
                            cr.paint()
                            cr.restore()
                            rendered_tile_fallback = True

                    if not rendered_tile_fallback:
                        cr.save()
                        cr.set_source_rgb(1.0, 1.0, 1.0)
                        cr.rectangle(tx0, ty0, tw, th)
                        cr.fill()
                        cr.set_source_rgb(0.9, 0.9, 0.9)
                        cr.set_line_width(1.0)
                        cr.rectangle(tx0, ty0, tw, th)
                        cr.stroke()
                        cr.restore()

            tiler.prune_distant_tiles(self.doc, page_index, self.zoom_level, active_tile_set)
        else:
            use_async = getattr(self, 'async_page_rendering', True)
            cached_surf = None
            if use_async:
                cached_surf = pdf_handler.peek_page_cairo_surface(self.doc, page_index, self.zoom_level)
            else:
                cached_surf = pdf_handler.get_page_cairo_surface(self.doc, page_index, self.zoom_level)

            if (
                cached_surf is not None
                and getattr(cached_surf, 'get_width', lambda: 0)() > 0
                and getattr(cached_surf, 'get_height', lambda: 0)() > 0
            ):
                cr.set_source_surface(cached_surf, 0, 0)
                cr.paint()
            else:
                if use_async and self.doc and not getattr(self.doc, 'is_closed', False):
                    is_gesturing = getattr(self, 'is_zoom_gesture_active', False)
                    if not is_gesturing:
                        def _on_async_page_ready(p_idx, z_val, surf):
                            if not self.doc or getattr(self.doc, 'is_closed', False):
                                return
                            if getattr(self, '_active_session', None) is None:
                                return
                            is_visible = False
                            if getattr(self, 'continuous_scroll', False):
                                is_visible = (p_idx in self.get_visible_page_indices() or p_idx == self.current_page_index)
                            else:
                                is_visible = (p_idx == self.current_page_index)
                            if is_visible:
                                # Redraw if target zoom arrived or low-res preview arrived before target
                                if abs(self.zoom_level - z_val) < 0.001 or pdf_handler.peek_page_cairo_surface(self.doc, p_idx, self.zoom_level) is None:
                                    if hasattr(self, 'pdf_view') and self.pdf_view:
                                        self.pdf_view.queue_draw()

                        pdf_handler.request_page_cairo_surface(
                            self.doc, page_index, self.zoom_level,
                            callback=_on_async_page_ready,
                            progressive=True
                        )

                    rendered_fallback = False
                    best_match = pdf_handler.get_page_rasterizer_pool().find_best_cached_surface(self.doc, page_index, self.zoom_level)
                    if best_match is not None:
                        alt_surf, alt_zoom = best_match
                        if alt_zoom > 0:
                            scale_factor = self.zoom_level / alt_zoom
                            cr.save()
                            cr.scale(scale_factor, scale_factor)
                            cr.set_source_surface(alt_surf, 0, 0)
                            pat = cr.get_source()
                            if pat is not None:
                                pat.set_filter(cairo.FILTER_BILINEAR)
                            cr.paint()
                            cr.restore()
                            rendered_fallback = True

                    if not rendered_fallback:
                        cr.save()
                        cr.set_source_rgb(1.0, 1.0, 1.0)
                        cr.rectangle(0, 0, page_w, page_h)
                        cr.fill()
                        cr.set_source_rgb(0.85, 0.85, 0.85)
                        cr.set_line_width(1.0)
                        cr.rectangle(0, 0, page_w, page_h)
                        cr.stroke()
                        cr.restore()
                else:
                    pdf_handler.draw_page_to_cairo(cr, self.doc, page_index, self.zoom_level)
        cr.restore()

        page = self.doc[page_index]
        page_rot = page.rotation % 360
        cr.save()
        cr.translate(page_offset_x, page_offset_y)
        cr.scale(self.zoom_level, self.zoom_level)
        if page_rot != 0:
            mat = page.rotation_matrix
            cr.transform(cairo.Matrix(mat.a, mat.b, mat.c, mat.d, mat.e, mat.f))

        pw_unscaled = page.rect.width
        ph_unscaled = page.rect.height
        cr.rectangle(0, 0, pw_unscaled, ph_unscaled)
        cr.clip()

        if dirty_rect is not None:
            cr.rectangle(*dirty_rect)
            cr.clip()

        clip_x1, clip_y1, clip_x2, clip_y2 = cr.clip_extents()

        if page_index == self.current_page_index:
            texts = self.editable_texts
            images = getattr(self, 'editable_images', [])
            shapes = self.editable_shapes
            strokes = getattr(self, 'editable_strokes', [])
            fields = getattr(self, 'form_fields', [])
        else:
            page_objs = self._get_page_objects(page_index)
            texts = page_objs.get('texts', [])
            images = page_objs.get('images', [])
            shapes = page_objs.get('shapes', [])
            strokes = page_objs.get('strokes', [])
            fields = page_objs.get('form_fields', [])

        active_create_page = getattr(self, 'drag_start_page_index', self.current_page_index)

        # Mask original underlying text on canvas while inline editor is actively editing
        if page_index == self.current_page_index and getattr(self, 'inline_editor_widget', None) is not None and getattr(self, 'inline_editor_text_obj', None) is not None:
            active_ed_obj = self.inline_editor_text_obj
            target_mask_box = getattr(self, '_inline_editor_target_rect', None) or getattr(active_ed_obj, 'bbox', None)
            if target_mask_box:
                mx1, my1, mx2, my2 = target_mask_box
                cr.save()
                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.rectangle(mx1 - 1.5, my1 - 1.5, (mx2 - mx1) + 3.0, (my2 - my1) + 3.0)
                cr.fill()
                cr.restore()

        if self.dragged_object and getattr(self.dragged_object, 'page_number', self.current_page_index) == page_index:
            if self.dragged_object.original_bbox:
                orig_x1, orig_y1, orig_x2, orig_y2 = self.dragged_object.original_bbox
                orig_w = orig_x2 - orig_x1
                orig_h = orig_y2 - orig_y1
                cr.save()
                orig_rot = getattr(self.dragged_object, 'rotation', 0.0) % 360.0
                if orig_rot != 0.0:
                    orig_cx = orig_x1 + orig_w / 2.0
                    orig_cy = orig_y1 + orig_h / 2.0
                    cr.translate(orig_cx, orig_cy)
                    cr.rotate(math.radians(orig_rot))
                    cr.translate(-orig_cx, -orig_cy)
                cr.set_source_rgba(0.85, 0.85, 0.85, 0.55)
                cr.rectangle(orig_x1, orig_y1, orig_w, orig_h)
                cr.fill()
                cr.set_source_rgba(0.5, 0.5, 0.5, 0.7)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.set_dash([4.0 / self.zoom_level, 3.0 / self.zoom_level])
                cr.rectangle(orig_x1, orig_y1, orig_w, orig_h)
                cr.stroke()
                cr.set_dash([])
                cr.restore()

            lt = getattr(self.dragged_object, 'linked_text', None)
            if lt and getattr(lt, 'original_bbox', None):
                lt_orig_x1, lt_orig_y1, lt_orig_x2, lt_orig_y2 = lt.original_bbox
                lt_orig_w = lt_orig_x2 - lt_orig_x1
                lt_orig_h = lt_orig_y2 - lt_orig_y1
                cr.save()
                lt_rot = getattr(lt, 'rotation', getattr(self.dragged_object, 'rotation', 0.0)) % 360.0
                if lt_rot != 0.0:
                    lt_orig_cx = lt_orig_x1 + lt_orig_w / 2.0
                    lt_orig_cy = lt_orig_y1 + lt_orig_h / 2.0
                    cr.translate(lt_orig_cx, lt_orig_cy)
                    cr.rotate(math.radians(lt_rot))
                    cr.translate(-lt_orig_cx, -lt_orig_cy)
                cr.set_source_rgba(0.85, 0.85, 0.85, 0.55)
                cr.rectangle(lt_orig_x1, lt_orig_y1, lt_orig_w, lt_orig_h)
                cr.fill()
                cr.set_source_rgba(0.5, 0.5, 0.5, 0.7)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.set_dash([4.0 / self.zoom_level, 3.0 / self.zoom_level])
                cr.rectangle(lt_orig_x1, lt_orig_y1, lt_orig_w, lt_orig_h)
                cr.stroke()
                cr.set_dash([])
                cr.restore()

            x1, y1, x2, y2 = self.dragged_object.bbox
            ghost_x = x1
            ghost_y = y1
            ghost_w = x2 - x1
            ghost_h = y2 - y1

            cr.save()
            rot = getattr(self.dragged_object, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = ghost_x + ghost_w / 2.0
                cy = ghost_y + ghost_h / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)

            if ghost_w > 0 and ghost_h > 0:
                cr.save()
                cr.set_source_rgba(0.2, 0.5, 0.85, 0.12)
                cr.rectangle(ghost_x, ghost_y, ghost_w, ghost_h)
                cr.fill()
                cr.set_source_rgba(0.2, 0.5, 0.85, 0.6)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.set_dash([4.0 / self.zoom_level, 3.0 / self.zoom_level])
                cr.rectangle(ghost_x, ghost_y, ghost_w, ghost_h)
                cr.stroke()
                cr.set_dash([])
                cr.restore()

            if isinstance(self.dragged_object, EditableImage) and self.dragged_object.image_bytes:
                try:
                    pixbuf = utils.get_decoded_pixbuf(self.dragged_object.image_bytes)
                    if pixbuf and ghost_w > 0 and ghost_h > 0:
                        cr.save()
                        cr.translate(ghost_x, ghost_y)
                        cr.scale(ghost_w / pixbuf.get_width(), ghost_h / pixbuf.get_height())
                        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
                        cr.paint_with_alpha(0.6)
                        cr.restore()
                except Exception as e:
                    cr.set_source_rgba(0.2, 0.5, 0.8, 0.5)
                    cr.rectangle(ghost_x, ghost_y, ghost_w, ghost_h)
                    cr.fill()
                if lt and getattr(lt, 'bbox', None) and getattr(lt, 'text', None):
                    lx1, ly1, lx2, ly2 = lt.bbox
                    cr.save()
                    layout = PangoCairo.create_layout(cr)
                    font_desc_str = f"{getattr(lt, 'font_family_base', 'Liberation Sans')} {getattr(lt, 'font_size', 11)}"
                    if getattr(lt, 'is_bold', False): font_desc_str += " Bold"
                    if getattr(lt, 'is_italic', False): font_desc_str += " Italic"
                    font_desc = Pango.FontDescription(font_desc_str)
                    font_desc.set_absolute_size(int(getattr(lt, 'font_size', 11) * Pango.SCALE))
                    layout.set_font_description(font_desc)
                    layout.set_text(lt.text, -1)
                    r, g, b = getattr(lt, 'color', (0.0, 0.0, 0.0))[:3]
                    cr.set_source_rgba(r, g, b, 0.75)
                    cr.move_to(lx1, ly1)
                    PangoCairo.show_layout(cr, layout)
                    cr.restore()
            elif isinstance(self.dragged_object, EditableText):
                layout = PangoCairo.create_layout(cr)
                font_desc_str = f"{self.dragged_object.font_family_base} {self.dragged_object.font_size}"
                if self.dragged_object.is_bold: font_desc_str += " Bold"
                if self.dragged_object.is_italic: font_desc_str += " Italic"

                font_desc = Pango.FontDescription(font_desc_str)
                font_desc.set_absolute_size(int(self.dragged_object.font_size * Pango.SCALE))
                layout.set_font_description(font_desc)
                layout.set_text(self.dragged_object.text, -1)
                align = getattr(self.dragged_object, 'alignment', 'left')
                if ghost_w > 0:
                    nat_pw, _ = layout.get_size()
                    w_to_set = max(ghost_w, nat_pw / Pango.SCALE)
                    layout.set_width(int(w_to_set * Pango.SCALE))
                    if align == 'center':
                        layout.set_alignment(Pango.Alignment.CENTER)
                    elif align == 'right':
                        layout.set_alignment(Pango.Alignment.RIGHT)
                    elif align == 'justify':
                        layout.set_justify(True)

                r, g, b = self.dragged_object.color
                cr.set_source_rgba(r, g, b, 0.6)
                
                attr_list = Pango.AttrList()
                
                for match in re.finditer(r'(https?://[^\s]+|www\.[^\s]+)', self.dragged_object.text):
                    start_byte = len(self.dragged_object.text[:match.start()].encode('utf-8'))
                    end_byte = len(self.dragged_object.text[:match.end()].encode('utf-8'))
                    
                    color_attr = Pango.attr_foreground_new(0, int(0.33*65535), int(0.8*65535))
                    color_attr.start_index = start_byte
                    color_attr.end_index = end_byte
                    attr_list.insert(color_attr)
                    
                    underline_attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                    underline_attr.start_index = start_byte
                    underline_attr.end_index = end_byte
                    attr_list.insert(underline_attr)
                
                if getattr(self.dragged_object, 'is_underline', False):
                    attr_list.insert(Pango.attr_underline_new(Pango.Underline.SINGLE))
                if getattr(self.dragged_object, 'is_strikethrough', False):
                    attr_list.insert(Pango.attr_strikethrough_new(True))
                
                layout.set_attributes(attr_list)
                
                cr.move_to(ghost_x, ghost_y)
                PangoCairo.show_layout(cr, layout)
            elif isinstance(self.dragged_object, EditableShape):
                if not self.dragged_object.is_transparent:
                    fill_r, fill_g, fill_b = self.dragged_object.fill_color
                    cr.set_source_rgba(fill_r, fill_g, fill_b, 0.4)
                    if self.dragged_object.shape_type == EditableShape.SHAPE_RECTANGLE:
                        cr.rectangle(ghost_x, ghost_y, ghost_w, ghost_h)
                        cr.fill()
                    elif self.dragged_object.shape_type == EditableShape.SHAPE_ELLIPSE:
                        if ghost_w > 0 and ghost_h > 0:
                            cr.save()
                            cr.translate(ghost_x + ghost_w / 2.0, ghost_y + ghost_h / 2.0)
                            cr.scale(ghost_w / 2.0, ghost_h / 2.0)
                            cr.arc(0, 0, 1, 0, 2 * math.pi)
                            cr.restore()
                            cr.fill()
                stroke_r, stroke_g, stroke_b = self.dragged_object.stroke_color
                cr.set_source_rgba(stroke_r, stroke_g, stroke_b, 0.6)
                cr.set_line_width(self.dragged_object.stroke_width)
                if self.dragged_object.shape_type == EditableShape.SHAPE_RECTANGLE:
                    cr.rectangle(ghost_x, ghost_y, ghost_w, ghost_h)
                    cr.stroke()
                elif self.dragged_object.shape_type == EditableShape.SHAPE_ELLIPSE:
                    if ghost_w > 0 and ghost_h > 0:
                        cr.save()
                        cr.translate(ghost_x + ghost_w / 2.0, ghost_y + ghost_h / 2.0)
                        cr.scale(ghost_w / 2.0, ghost_h / 2.0)
                        cr.arc(0, 0, 1, 0, 2 * math.pi)
                        cr.restore()
                        cr.stroke()
                elif self.dragged_object.shape_type == EditableShape.SHAPE_CHECKMARK:
                    pts = self.dragged_object.get_checkmark_points()
                    cr.set_line_cap(cairo.LINE_CAP_ROUND)
                    cr.set_line_join(cairo.LINE_JOIN_ROUND)
                    cr.move_to(pts[0][0], pts[0][1])
                    for pt in pts[1:]:
                        cr.line_to(pt[0], pt[1])
                    cr.stroke()
                elif self.dragged_object.shape_type == EditableShape.SHAPE_CROSS:
                    lines = self.dragged_object.get_cross_lines()
                    cr.set_line_cap(cairo.LINE_CAP_ROUND)
                    cr.set_line_join(cairo.LINE_JOIN_ROUND)
                    for (p1, p2) in lines:
                        cr.move_to(p1[0], p1[1])
                        cr.line_to(p2[0], p2[1])
                    cr.stroke()
            elif isinstance(self.dragged_object, EditableStroke):
                r, g, b = self.dragged_object.stroke_color
                cr.set_source_rgba(r, g, b, 0.6)
                cr.set_line_width(self.dragged_object.stroke_width)
                is_hl = getattr(self.dragged_object, 'tool_type', None) in ("highlighter", EditableStroke.TOOL_HIGHLIGHTER) or self.dragged_object.stroke_width >= 8.0
                if is_hl:
                    cr.set_line_cap(cairo.LINE_CAP_SQUARE)
                    cr.set_line_join(cairo.LINE_JOIN_BEVEL)
                else:
                    cr.set_line_cap(cairo.LINE_CAP_ROUND)
                    cr.set_line_join(cairo.LINE_JOIN_ROUND)
                if len(self.dragged_object.points) == 1:
                    px, py = self.dragged_object.points[0]
                    rad = max(self.dragged_object.stroke_width / 2.0, 1.0 / self.zoom_level)
                    if is_hl:
                        cr.rectangle(px - rad, py - rad, rad * 2.0, rad * 2.0)
                    else:
                        cr.arc(px, py, rad, 0, 2 * math.pi)
                    cr.fill()
                elif self.dragged_object.points:
                    p0 = self.dragged_object.points[0]
                    cr.move_to(p0[0], p0[1])
                    for pt in self.dragged_object.points[1:]:
                        cr.line_to(pt[0], pt[1])
                    cr.stroke()
            cr.restore()
            
        for img_obj in images:
            if getattr(img_obj, 'page_number', page_index) != page_index:
                continue
            if getattr(img_obj, 'is_baked', False):
                continue
            if getattr(img_obj, 'is_new', True) is False:
                continue
            if img_obj is self.dragged_object:
                continue
            if not getattr(img_obj, 'bbox', None) or not getattr(img_obj, 'image_bytes', None):
                continue
            x1, y1, x2, y2 = img_obj.bbox
            if x2 < clip_x1 or x1 > clip_x2 or y2 < clip_y1 or y1 > clip_y2:
                continue
            draw_w = x2 - x1
            draw_h = y2 - y1
            if draw_w <= 0 or draw_h <= 0:
                continue
            cr.save()
            rot = getattr(img_obj, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = x1 + draw_w / 2.0
                cy = y1 + draw_h / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            try:
                pixbuf = utils.get_decoded_pixbuf(img_obj.image_bytes)
                if pixbuf:
                    cr.save()
                    cr.translate(x1, y1)
                    cr.scale(draw_w / pixbuf.get_width(), draw_h / pixbuf.get_height())
                    Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
                    img_opacity = getattr(img_obj, 'opacity', 1.0)
                    if img_opacity < 1.0:
                        cr.paint_with_alpha(img_opacity)
                    else:
                        cr.paint()
                    cr.restore()
            except Exception:
                pass
            cr.restore()

        for text_obj in texts:
            if getattr(text_obj, 'page_number', page_index) != page_index:
                continue
            if not text_obj.is_new:
                continue 
            if getattr(text_obj, 'is_baked', False):
                continue
            if text_obj is self.dragged_object:
                continue
            if not text_obj.bbox or not text_obj.text:
                continue
            x1, y1, x2, y2 = text_obj.bbox
            if x2 < clip_x1 or x1 > clip_x2 or y2 < clip_y1 or y1 > clip_y2:
                continue
            draw_x = x1
            draw_y = y1
            cr.save()
            rot = getattr(text_obj, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = draw_x + (x2 - x1) / 2.0
                cy = draw_y + (y2 - y1) / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            layout = PangoCairo.create_layout(cr)
            font_family = f"{text_obj.font_family_base}, DejaVu Sans, FreeSans, sans-serif"
            font_desc = Pango.FontDescription.from_string(font_family)
            if text_obj.is_bold: font_desc.set_weight(Pango.Weight.BOLD)
            if text_obj.is_italic: font_desc.set_style(Pango.Style.ITALIC)
            font_desc.set_absolute_size(int(text_obj.font_size * Pango.SCALE))
            layout.set_font_description(font_desc)
            layout.set_text(text_obj.text, -1)
            align = getattr(text_obj, 'alignment', 'left')
            box_w = (x2 - x1)
            if box_w > 0:
                nat_pw, _ = layout.get_size()
                w_to_set = max(box_w, nat_pw / Pango.SCALE)
                layout.set_width(int(w_to_set * Pango.SCALE))
                if align == 'center':
                    layout.set_alignment(Pango.Alignment.CENTER)
                elif align == 'right':
                    layout.set_alignment(Pango.Alignment.RIGHT)
                elif align == 'justify':
                    layout.set_justify(True)
            r, g, b = text_obj.color
            cr.set_source_rgba(r, g, b, 1.0)
            
            attr_list = Pango.AttrList()

            if getattr(text_obj, 'link_url', None):
                color_attr = Pango.attr_foreground_new(0, 0, int((238.0 / 255.0) * 65535))
                color_attr.start_index = 0
                color_attr.end_index = 65535
                attr_list.change(color_attr)
                u_attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                u_attr.start_index = 0
                u_attr.end_index = 65535
                attr_list.change(u_attr)
            
            for match in re.finditer(r'(https?://[^\s]+|www\.[^\s]+)', text_obj.text):
                start_byte = len(text_obj.text[:match.start()].encode('utf-8'))
                end_byte = len(text_obj.text[:match.end()].encode('utf-8'))
                
                color_attr = Pango.attr_foreground_new(0, int(0.33*65535), int(0.8*65535))
                color_attr.start_index = start_byte
                color_attr.end_index = end_byte
                attr_list.change(color_attr)
                
                underline_attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                underline_attr.start_index = start_byte
                underline_attr.end_index = end_byte
                attr_list.change(underline_attr)
            
            if getattr(text_obj, 'is_underline', False):
                u_attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                u_attr.start_index = 0
                u_attr.end_index = 65535 
                attr_list.change(u_attr)
            if getattr(text_obj, 'is_strikethrough', False):
                s_attr = Pango.attr_strikethrough_new(True)
                s_attr.start_index = 0
                s_attr.end_index = 65535
                attr_list.change(s_attr)
            
            if not self.view_mode and self.selected_text == text_obj and getattr(self, 'word_selection_mode', False) and page_index == self.current_page_index:
                if hasattr(self, 'selected_word_start_char') and hasattr(self, 'selected_word_end_char'):
                    start_byte = len(text_obj.text[:self.selected_word_start_char].encode('utf-8'))
                    end_byte = len(text_obj.text[:self.selected_word_end_char].encode('utf-8'))
                    
                    bg_attr = Pango.attr_background_new(int(0.2*65535), int(0.6*65535), int(1.0*65535))
                    bg_attr.start_index = start_byte
                    bg_attr.end_index = end_byte
                    attr_list.insert(bg_attr)
                    
                    fg_attr = Pango.attr_foreground_new(65535, 65535, 65535)
                    fg_attr.start_index = start_byte
                    fg_attr.end_index = end_byte
                    attr_list.insert(fg_attr)
            
            layout.set_attributes(attr_list)
            cr.move_to(draw_x, draw_y)
            PangoCairo.show_layout(cr, layout)
            cr.restore()

        for shape in shapes:
            if getattr(shape, 'page_number', page_index) != page_index:
                continue
            if getattr(shape, 'is_baked', False):
                continue
            if shape is self.dragged_object:
                continue
            
            x1, y1, x2, y2 = shape.bbox
            if x2 < clip_x1 or x1 > clip_x2 or y2 < clip_y1 or y1 > clip_y2:
                continue
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1
            
            if abs(draw_w) < 1.0 or abs(draw_h) < 1.0:
                continue
            
            cr.save()
            rot = getattr(shape, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                cx = draw_x + draw_w / 2.0
                cy = draw_y + draw_h / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            if not shape.is_transparent:
                fill_r, fill_g, fill_b = shape.fill_color
                cr.set_source_rgba(fill_r, fill_g, fill_b, 1.0)
                if shape.shape_type == EditableShape.SHAPE_RECTANGLE:
                    cr.rectangle(draw_x, draw_y, draw_w, draw_h)
                    cr.fill()
                elif shape.shape_type == EditableShape.SHAPE_ELLIPSE:
                    cr.save()
                    cr.translate(draw_x + draw_w / 2.0, draw_y + draw_h / 2.0)
                    cr.scale(draw_w / 2.0, draw_h / 2.0)
                    cr.arc(0, 0, 1, 0, 2 * math.pi)
                    cr.restore()
                    cr.fill()
            
            stroke_r, stroke_g, stroke_b = shape.stroke_color
            cr.set_source_rgba(stroke_r, stroke_g, stroke_b, 1.0)
            cr.set_line_width(shape.stroke_width)
            
            if shape.shape_type == EditableShape.SHAPE_RECTANGLE:
                cr.rectangle(draw_x, draw_y, draw_w, draw_h)
                cr.stroke()
            elif shape.shape_type == EditableShape.SHAPE_ELLIPSE:
                cr.save()
                cr.translate(draw_x + draw_w / 2.0, draw_y + draw_h / 2.0)
                cr.scale(draw_w / 2.0, draw_h / 2.0)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.stroke()
            elif shape.shape_type == EditableShape.SHAPE_CHECKMARK:
                pts = shape.get_checkmark_points()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.move_to(pts[0][0], pts[0][1])
                for pt in pts[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.stroke()
            elif shape.shape_type == EditableShape.SHAPE_CROSS:
                lines = shape.get_cross_lines()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                for (p1, p2) in lines:
                    cr.move_to(p1[0], p1[1])
                    cr.line_to(p2[0], p2[1])
                cr.stroke()
            cr.restore()

        
        if self.temp_shape:
            x1, y1, x2, y2 = self.temp_shape.bbox
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1
            
            stroke_r, stroke_g, stroke_b = self.temp_shape.stroke_color
            cr.set_source_rgba(stroke_r, stroke_g, stroke_b, 0.7)  
            cr.set_line_width(self.temp_shape.stroke_width)
            
            if self.temp_shape.shape_type == EditableShape.SHAPE_RECTANGLE:
                cr.rectangle(draw_x, draw_y, draw_w, draw_h)
                cr.stroke()
            elif self.temp_shape.shape_type == EditableShape.SHAPE_ELLIPSE:
                cr.save()
                cr.translate(draw_x + draw_w / 2.0, draw_y + draw_h / 2.0)
                cr.scale(draw_w / 2.0, draw_h / 2.0)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.stroke()
            elif self.temp_shape.shape_type == EditableShape.SHAPE_CHECKMARK:
                pts = self.temp_shape.get_checkmark_points()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.move_to(pts[0][0], pts[0][1])
                for pt in pts[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.stroke()
            elif self.temp_shape.shape_type == EditableShape.SHAPE_CROSS:
                lines = self.temp_shape.get_cross_lines()
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                for (p1, p2) in lines:
                    cr.move_to(p1[0], p1[1])
                    cr.line_to(p2[0], p2[1])
                cr.stroke()

        if self.temp_image_bbox:
            x1, y1, x2, y2 = self.temp_image_bbox
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1

            style_context = area.get_style_context()
            found_img, img_rgba = style_context.lookup_color("accent_color")
            if not found_img:
                found_img, img_rgba = style_context.lookup_color("theme_selected_bg_color")
            if not found_img:
                img_rgba = Gdk.RGBA()
                img_rgba.parse("#3584e4")

            cr.set_source_rgba(img_rgba.red, img_rgba.green, img_rgba.blue, 0.25)
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.fill()

            cr.set_source_rgba(img_rgba.red, img_rgba.green, img_rgba.blue, 0.85)
            cr.set_line_width(2.0 / self.zoom_level)
            cr.set_dash([5.0 / self.zoom_level, 4.0 / self.zoom_level])
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.stroke()
            cr.set_dash([])

        if getattr(self, 'temp_stamp_bbox', None) and page_index == active_create_page:
            x1, y1, x2, y2 = self.temp_stamp_bbox
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1

            active_stamp = getattr(self, 'active_stamp', None)
            if (draw_w < 12 or draw_h < 12) and active_stamp:
                cx, cy = self.drag_start_page_pos
                w = getattr(active_stamp, 'default_width', 160.0)
                h = getattr(active_stamp, 'default_height', 54.0)
                draw_x = cx - w / 2.0
                draw_y = cy - h / 2.0
                draw_w = w
                draw_h = h

            cr.set_source_rgba(0.2, 0.5, 0.9, 0.2)
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.fill()

            cr.set_source_rgba(0.2, 0.5, 0.9, 0.85)
            cr.set_line_width(2.0 / self.zoom_level)
            cr.set_dash([5.0 / self.zoom_level, 4.0 / self.zoom_level])
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.stroke()
            cr.set_dash([])

        if getattr(self, 'temp_sig_bbox', None) and page_index == active_create_page:
            x1, y1, x2, y2 = self.temp_sig_bbox
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1

            style_context = area.get_style_context()
            found_col, col_rgba = style_context.lookup_color("accent_color")
            if not found_col:
                col_rgba = Gdk.RGBA()
                col_rgba.parse("#1c71d8")

            cr.set_source_rgba(col_rgba.red, col_rgba.green, col_rgba.blue, 0.18)
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.fill()

            cr.set_source_rgba(col_rgba.red, col_rgba.green, col_rgba.blue, 0.90)
            cr.set_line_width(2.0 / self.zoom_level)
            cr.set_dash([6.0 / self.zoom_level, 4.0 / self.zoom_level])
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.stroke()
            cr.set_dash([])

        if getattr(self, 'temp_clone_patch_bbox', None) is not None and page_index == active_create_page:
            x1, y1, x2, y2 = self.temp_clone_patch_bbox
            draw_x = min(x1, x2)
            draw_y = min(y1, y2)
            draw_w = abs(x2 - x1)
            draw_h = abs(y2 - y1)

            cr.set_source_rgba(0.12, 0.65, 0.85, 0.20)
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.fill()

            cr.set_source_rgba(0.08, 0.55, 0.80, 0.95)
            cr.set_line_width(2.0 / self.zoom_level)
            cr.set_dash([4.0 / self.zoom_level, 3.0 / self.zoom_level])
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.stroke()
            cr.set_dash([])

        if getattr(self, 'temp_redact_bbox', None) is not None and page_index == active_create_page:
            x1, y1, x2, y2 = self.temp_redact_bbox
            draw_x = min(x1, x2)
            draw_y = min(y1, y2)
            draw_w = abs(x2 - x1)
            draw_h = abs(y2 - y1)

            cr.set_source_rgba(0.90, 0.15, 0.15, 0.22)
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.fill()

            cr.set_source_rgba(0.85, 0.15, 0.15, 0.95)
            cr.set_line_width(2.0 / self.zoom_level)
            cr.set_dash([4.0 / self.zoom_level, 3.0 / self.zoom_level])
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.stroke()
            cr.set_dash([])

            cr.save()
            font_sz = max(min(11.0 / self.zoom_level, max(draw_h * 0.6, 6.0)), 7.0)
            cr.set_font_size(font_sz)
            cr.set_source_rgba(0.85, 0.15, 0.15, 0.95)
            cr.move_to(draw_x + 4.0 / self.zoom_level, draw_y + min(font_sz + 2.0 / self.zoom_level, max(draw_h - 2.0, 8.0)))
            cr.show_text("[REDACTION MARK]")
            cr.restore()

        if getattr(self, 'temp_form_field_rect', None) is not None and page_index == active_create_page:
            x1, y1, x2, y2 = self.temp_form_field_rect
            draw_x = x1
            draw_y = y1
            draw_w = x2 - x1
            draw_h = y2 - y1

            style_context = area.get_style_context()
            found_col, col_rgba = style_context.lookup_color("accent_color")
            if not found_col:
                found_col, col_rgba = style_context.lookup_color("theme_selected_bg_color")
            if not found_col:
                col_rgba = Gdk.RGBA()
                col_rgba.parse("#3584e4")

            cr.set_source_rgba(col_rgba.red, col_rgba.green, col_rgba.blue, 0.20)
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.fill()

            cr.set_source_rgba(col_rgba.red, col_rgba.green, col_rgba.blue, 0.90)
            cr.set_line_width(2.0 / self.zoom_level)
            cr.set_dash([5.0 / self.zoom_level, 3.0 / self.zoom_level])
            cr.rectangle(draw_x, draw_y, draw_w, draw_h)
            cr.stroke()
            cr.set_dash([])

            field_type_name = getattr(self, 'form_builder_field_type', 'text').capitalize()
            if field_type_name == 'Combobox':
                field_type_name = 'Dropdown'
            badge_text = f"[{field_type_name}]"
            cr.save()
            font_sz = max(10.0 / self.zoom_level, 8.0)
            cr.set_font_size(font_sz)
            cr.set_source_rgba(col_rgba.red, col_rgba.green, col_rgba.blue, 0.95)
            cr.move_to(draw_x + 4.0 / self.zoom_level, draw_y + font_sz + 2.0 / self.zoom_level)
            cr.show_text(badge_text)
            cr.restore()

        # Render editable strokes on current page
        for stroke in strokes:
            if getattr(stroke, 'page_number', page_index) != page_index:
                continue
            if getattr(stroke, 'is_baked', False):
                continue
            if stroke is self.dragged_object:
                continue
            if getattr(stroke, 'bbox', None):
                sx1, sy1, sx2, sy2 = stroke.bbox
                if sx2 < clip_x1 or sx1 > clip_x2 or sy2 < clip_y1 or sy1 > clip_y2:
                    continue
            cr.save()
            rot = getattr(stroke, 'rotation', 0.0) % 360.0
            if rot != 0.0 and stroke.bbox:
                sx1, sy1, sx2, sy2 = stroke.bbox
                cx = (sx1 + sx2) / 2.0
                cy = (sy1 + sy2) / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)
            r, g, b = stroke.stroke_color
            opacity = getattr(stroke, 'opacity', 1.0)
            cr.set_source_rgba(r, g, b, opacity)
            cr.set_line_width(stroke.stroke_width)
            is_hl = getattr(stroke, 'tool_type', None) in ("highlighter", EditableStroke.TOOL_HIGHLIGHTER) or stroke.stroke_width >= 8.0
            if is_hl:
                cr.set_line_cap(cairo.LINE_CAP_SQUARE)
                cr.set_line_join(cairo.LINE_JOIN_BEVEL)
            else:
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)

            if len(stroke.points) == 1:
                px, py = stroke.points[0]
                rad = max(stroke.stroke_width / 2.0, 1.0 / self.zoom_level)
                if is_hl:
                    cr.rectangle(px - rad, py - rad, rad * 2.0, rad * 2.0)
                else:
                    cr.arc(px, py, rad, 0, 2 * math.pi)
                cr.fill()
            else:
                p0 = stroke.points[0]
                cr.move_to(p0[0], p0[1])
                for pt in stroke.points[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.stroke()
            cr.restore()

        # Render live drawing temp stroke
        if page_index == active_create_page and getattr(self, 'temp_stroke', None) and self.temp_stroke.points:
            cr.save()
            r, g, b = self.temp_stroke.stroke_color
            opacity = getattr(self.temp_stroke, 'opacity', 1.0)
            cr.set_source_rgba(r, g, b, opacity)
            cr.set_line_width(self.temp_stroke.stroke_width)
            is_hl = getattr(self.temp_stroke, 'tool_type', None) in ("highlighter", EditableStroke.TOOL_HIGHLIGHTER) or self.tool_mode == "highlighter" or self.temp_stroke.stroke_width >= 8.0
            if is_hl:
                cr.set_line_cap(cairo.LINE_CAP_SQUARE)
                cr.set_line_join(cairo.LINE_JOIN_BEVEL)
            else:
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)

            if len(self.temp_stroke.points) == 1:
                px, py = self.temp_stroke.points[0]
                rad = max(self.temp_stroke.stroke_width / 2.0, 1.0 / self.zoom_level)
                if is_hl:
                    cr.rectangle(px - rad, py - rad, rad * 2.0, rad * 2.0)
                else:
                    cr.arc(px, py, rad, 0, 2 * math.pi)
                cr.fill()
            else:
                p0 = self.temp_stroke.points[0]
                cr.move_to(p0[0], p0[1])
                for pt in self.temp_stroke.points[1:]:
                    cr.line_to(pt[0], pt[1])
                cr.stroke()
            cr.restore()

        # Render AcroForm field overlays
        current_fields = [f for f in fields if getattr(f, 'page_number', page_index) == page_index]
        if current_fields:
            is_design = (not self.view_mode and getattr(self, 'tool_mode', '') == "form_builder" and page_index == self.current_page_index)
            pdf_handler.draw_acroform_overlay(
                cr,
                current_fields,
                self.zoom_level,
                active_field=(self.selected_form_field if (self.view_mode and page_index == self.current_page_index) else None),
                is_design_mode=is_design
            )

        selected_obj = (self.selected_text or self.selected_image or self.selected_shape or 
                        self.selected_stroke or getattr(self, 'selected_form_field', None) or
                        getattr(self, 'selected_measurement', None) or
                        getattr(self, 'selected_redaction_mark', None))
        if page_index == self.current_page_index and selected_obj and not self.dragged_object and not (
            isinstance(selected_obj, AcroFormField) and getattr(self, '_active_editing_form_field', None) == selected_obj
        ) and not (self.inline_editor_widget is not None and selected_obj == getattr(self, 'inline_editor_text_obj', None)):
            is_image = isinstance(selected_obj, EditableImage)
            style_context = area.get_style_context()
            color_name = "accent_color"
            default_color = "#3584e4"

            found, rgba = style_context.lookup_color("accent_color")
            if not found:
                found, rgba = style_context.lookup_color("theme_selected_bg_color")
            if not found:
                rgba = Gdk.RGBA()
                rgba.parse("#3584e4")

            x1, y1, x2, y2 = selected_obj.bbox
            if bool(getattr(self, 'word_selection_mode', False)) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
                w_bbox = self.get_selected_word_bbox()
                if isinstance(w_bbox, (tuple, list)) and len(w_bbox) == 4:
                    x1, y1, x2, y2 = w_bbox

            padding = 3.0 / self.zoom_level
            rect_x = x1 - padding
            rect_y = y1 - padding
            rect_w = (x2 - x1) + (2 * padding)
            rect_h = (y2 - y1) + (2 * padding)

            cr.save()
            rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
            if rot != 0.0:
                if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
                    cx = (selected_obj.bbox[0] + selected_obj.bbox[2]) / 2.0
                    cy = (selected_obj.bbox[1] + selected_obj.bbox[3]) / 2.0
                else:
                    cx = rect_x + rect_w / 2.0
                    cy = rect_y + rect_h / 2.0
                cr.translate(cx, cy)
                cr.rotate(math.radians(rot))
                cr.translate(-cx, -cy)

            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.95)
            cr.set_line_width((2.5 if is_image else 2.0) / self.zoom_level)
            if is_image:
                cr.set_dash([4.0 / self.zoom_level, 4.0 / self.zoom_level])

            radius = min(5.0 / self.zoom_level, rect_w / 2.0, rect_h / 2.0)
            cr.new_sub_path()
            cr.arc(rect_x + radius, rect_y + radius, radius, math.pi, 1.5 * math.pi)
            cr.arc(rect_x + rect_w - radius, rect_y + radius, radius, 1.5 * math.pi, 2.0 * math.pi)
            cr.arc(rect_x + rect_w - radius, rect_y + rect_h - radius, radius, 0, 0.5 * math.pi)
            cr.arc(rect_x + radius, rect_y + rect_h - radius, radius, 0.5 * math.pi, math.pi)
            cr.close_path()
            cr.stroke()

            # Stalk rotation handle (available on all rotatable objects including EditableText and single word selection)
            is_form = isinstance(selected_obj, AcroFormField) or hasattr(selected_obj, 'field_name') or isinstance(selected_obj, MeasurementObject)
            if not is_form:
                stalk_len = 22.0 / self.zoom_level
                stalk_x = rect_x + rect_w / 2.0
                stalk_base_y = rect_y
                stalk_tip_y = rect_y - stalk_len
                rot_handle_r = 5.0 / self.zoom_level

                cr.save()
                cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.9)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.set_dash([])
                cr.move_to(stalk_x, stalk_base_y)
                cr.line_to(stalk_x, stalk_tip_y)
                cr.stroke()

                cr.arc(stalk_x, stalk_tip_y, rot_handle_r, 0, 2 * math.pi)
                cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                cr.fill_preserve()
                cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1.0)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.stroke()
                cr.restore()

            is_text = isinstance(selected_obj, EditableText)
            if not is_text:
                handle_size = 8.0 / self.zoom_level
                handle_color_rgba = rgba
                
                handles = [
                    ("nw", rect_x, rect_y),                                   # top-left
                    ("ne", rect_x + rect_w, rect_y),                          # top-right
                    ("sw", rect_x, rect_y + rect_h),                          # bottom-left
                    ("se", rect_x + rect_w, rect_y + rect_h),                 # bottom-right
                    ("n", rect_x + rect_w / 2.0, rect_y),                     # top
                    ("s", rect_x + rect_w / 2.0, rect_y + rect_h),            # bottom
                    ("w", rect_x, rect_y + rect_h / 2.0),                     # left
                    ("e", rect_x + rect_w, rect_y + rect_h / 2.0),            # right
                ]
                
                for handle_name, handle_x, handle_y in handles:
                    cr.set_source_rgba(handle_color_rgba.red, handle_color_rgba.green, handle_color_rgba.blue, 1.0)
                    cr.rectangle(handle_x - handle_size / 2.0, handle_y - handle_size / 2.0, handle_size, handle_size)
                    cr.fill()
                    cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                    cr.rectangle(handle_x - handle_size / 2.0, handle_y - handle_size / 2.0, handle_size, handle_size)
                    cr.set_line_width(1.0 / self.zoom_level)
                    cr.stroke()
            cr.restore()

        # Draw active scale calibration reference line or saved reference line
        calib_line = getattr(self, 'temp_calibration_line', None) if page_index == active_create_page else None
        active_calib = self.get_scale_calibration(page_index) if hasattr(self, 'get_scale_calibration') else None
        is_calib_tool = (getattr(self, 'tool_mode', None) == "calibrate" and page_index == self.current_page_index)
        
        if calib_line or (is_calib_tool and active_calib and active_calib.reference_line):
            line_to_draw = calib_line or active_calib.reference_line
            sx, sy, ex, ey = line_to_draw
            pt_len = math.hypot(ex - sx, ey - sy)
            if pt_len > 1.0:
                cr.save()
                is_temp = (calib_line is not None)
                if is_temp:
                    cr.set_source_rgba(0.0, 0.65, 0.95, 0.95)
                    cr.set_line_width(2.0 / self.zoom_level)
                else:
                    cr.set_source_rgba(0.0, 0.50, 0.85, 0.70)
                    cr.set_line_width(1.5 / self.zoom_level)
                    cr.set_dash([4.0 / self.zoom_level, 3.0 / self.zoom_level])

                # Main reference line
                cr.move_to(sx, sy)
                cr.line_to(ex, ey)
                cr.stroke()
                cr.set_dash([])

                # Perpendicular end ticks
                theta = math.atan2(ey - sy, ex - sx)
                perp = theta + math.pi / 2.0
                tick_h = 7.0 / self.zoom_level
                dx_p = tick_h * math.cos(perp)
                dy_p = tick_h * math.sin(perp)

                cr.move_to(sx - dx_p, sy - dy_p)
                cr.line_to(sx + dx_p, sy + dy_p)
                cr.stroke()

                cr.move_to(ex - dx_p, ey - dy_p)
                cr.line_to(ex + dx_p, ey + dy_p)
                cr.stroke()

                # Endpoint crosshair circles
                rad = 3.0 / self.zoom_level
                cr.arc(sx, sy, rad, 0, 2 * math.pi)
                cr.stroke()
                cr.arc(ex, ey, rad, 0, 2 * math.pi)
                cr.stroke()

                # Midpoint readout pill badge
                mx = (sx + ex) / 2.0
                my = (sy + ey) / 2.0
                badge_str = f"{pt_len:.1f} pt"
                if active_calib and active_calib.points_per_unit > 0:
                    badge_str += f" ({active_calib.format_distance(pt_len)})"

                cr.set_font_size(max(10.0 / self.zoom_level, 9.0))
                ext = cr.text_extents(badge_str)
                pad_x = 6.0 / self.zoom_level
                pad_y = 3.0 / self.zoom_level
                bw = ext.width + pad_x * 2.0
                bh = ext.height + pad_y * 2.0
                bx = mx - bw / 2.0
                by = my - bh / 2.0 - (12.0 / self.zoom_level)

                # Background pill
                cr.set_source_rgba(0.12, 0.15, 0.20, 0.88)
                cr.rectangle(bx, by, bw, bh)
                cr.fill()

                cr.set_source_rgba(0.0, 0.70, 1.0, 0.95)
                cr.set_line_width(1.0 / self.zoom_level)
                cr.rectangle(bx, by, bw, bh)
                cr.stroke()

                # Text
                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.move_to(bx + pad_x - ext.x_bearing, by + pad_y - ext.y_bearing)
                cr.show_text(badge_str)
                cr.restore()

        # Draw persistent measurement objects (Distance & Area)
        if self._active_session:
            page_measurements = self._active_session.measurements.get(page_index, [])
            for m in page_measurements:
                is_selected = (getattr(self, 'selected_measurement', None) == m and page_index == self.current_page_index)
                active_calib = self.get_scale_calibration(page_index) if hasattr(self, 'get_scale_calibration') else None
                cr.save()

                if m.measurement_type == MeasurementObject.TYPE_DISTANCE and len(m.points) >= 2:
                    p0, p1 = m.points[0], m.points[1]
                    sx, sy = p0
                    ex, ey = p1
                    pt_len = math.hypot(ex - sx, ey - sy)
                    if pt_len > 1.0:
                        if is_selected:
                            cr.set_source_rgba(1.0, 0.75, 0.0, 1.0)
                            cr.set_line_width(2.2 / self.zoom_level)
                        else:
                            cr.set_source_rgba(m.color[0], m.color[1], m.color[2], 0.95)
                            cr.set_line_width(m.stroke_width / self.zoom_level)

                        # Main dimension line
                        cr.move_to(sx, sy)
                        cr.line_to(ex, ey)
                        cr.stroke()

                        # Perpendicular ticks
                        theta = math.atan2(ey - sy, ex - sx)
                        perp = theta + math.pi / 2.0
                        tick_h = 7.0 / self.zoom_level
                        dx_p = tick_h * math.cos(perp)
                        dy_p = tick_h * math.sin(perp)

                        cr.move_to(sx - dx_p, sy - dy_p)
                        cr.line_to(sx + dx_p, sy + dy_p)
                        cr.stroke()

                        cr.move_to(ex - dx_p, ey - dy_p)
                        cr.line_to(ex + dx_p, ey + dy_p)
                        cr.stroke()

                        # Vertex circles
                        rad = 3.0 / self.zoom_level
                        cr.arc(sx, sy, rad, 0, 2 * math.pi)
                        cr.stroke()
                        cr.arc(ex, ey, rad, 0, 2 * math.pi)
                        cr.stroke()

                        # Midpoint readout pill badge
                        mx = (sx + ex) / 2.0
                        my = (sy + ey) / 2.0
                        badge_str = m.format_measurement(active_calib)

                        cr.set_font_size(max(10.0 / self.zoom_level, 9.0))
                        ext = cr.text_extents(badge_str)
                        pad_x = 6.0 / self.zoom_level
                        pad_y = 3.0 / self.zoom_level
                        bw = ext.width + pad_x * 2.0
                        bh = ext.height + pad_y * 2.0
                        bx = mx - bw / 2.0
                        by = my - bh / 2.0 - (12.0 / self.zoom_level)

                        # Background pill
                        cr.set_source_rgba(0.12, 0.15, 0.20, 0.88)
                        cr.rectangle(bx, by, bw, bh)
                        cr.fill()

                        if is_selected:
                            cr.set_source_rgba(1.0, 0.75, 0.0, 1.0)
                            cr.set_line_width(1.5 / self.zoom_level)
                        else:
                            cr.set_source_rgba(m.color[0], m.color[1], m.color[2], 0.95)
                            cr.set_line_width(1.0 / self.zoom_level)
                        cr.rectangle(bx, by, bw, bh)
                        cr.stroke()

                        cr.set_source_rgb(1.0, 1.0, 1.0)
                        cr.move_to(bx + pad_x - ext.x_bearing, by + pad_y - ext.y_bearing)
                        cr.show_text(badge_str)

                elif m.measurement_type == MeasurementObject.TYPE_AREA and len(m.points) >= 3:
                    # Closed polygon path
                    cr.move_to(m.points[0][0], m.points[0][1])
                    for p in m.points[1:]:
                        cr.line_to(p[0], p[1])
                    cr.close_path()

                    # Translucent fill
                    cr.set_source_rgba(m.fill_color[0], m.fill_color[1], m.fill_color[2], m.fill_color[3])
                    cr.fill_preserve()

                    # Border stroke
                    if is_selected:
                        cr.set_source_rgba(1.0, 0.75, 0.0, 1.0)
                        cr.set_line_width(2.2 / self.zoom_level)
                    else:
                        cr.set_source_rgba(m.color[0], m.color[1], m.color[2], 0.95)
                        cr.set_line_width(m.stroke_width / self.zoom_level)
                    cr.stroke()

                    # Vertex markers
                    rad = 3.0 / self.zoom_level
                    for p in m.points:
                        cr.arc(p[0], p[1], rad, 0, 2 * math.pi)
                        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                        cr.fill_preserve()
                        cr.set_source_rgba(m.color[0], m.color[1], m.color[2], 1.0)
                        cr.stroke()

                    # Centroid readout badge
                    cx, cy = m.get_centroid()
                    badge_str = m.format_measurement(active_calib)

                    cr.set_font_size(max(10.0 / self.zoom_level, 9.0))
                    ext = cr.text_extents(badge_str)
                    pad_x = 6.0 / self.zoom_level
                    pad_y = 3.0 / self.zoom_level
                    bw = ext.width + pad_x * 2.0
                    bh = ext.height + pad_y * 2.0
                    bx = cx - bw / 2.0
                    by = cy - bh / 2.0

                    cr.set_source_rgba(0.12, 0.15, 0.20, 0.88)
                    cr.rectangle(bx, by, bw, bh)
                    cr.fill()

                    if is_selected:
                        cr.set_source_rgba(1.0, 0.75, 0.0, 1.0)
                        cr.set_line_width(1.5 / self.zoom_level)
                    else:
                        cr.set_source_rgba(m.color[0], m.color[1], m.color[2], 0.95)
                        cr.set_line_width(1.0 / self.zoom_level)
                    cr.rectangle(bx, by, bw, bh)
                    cr.stroke()

                    cr.set_source_rgb(1.0, 1.0, 1.0)
                    cr.move_to(bx + pad_x - ext.x_bearing, by + pad_y - ext.y_bearing)
                    cr.show_text(badge_str)

                cr.restore()

        # Draw persistent sticky note & comment annotations
        if self._active_session:
            page_notes = self._active_session.sticky_notes.get(page_index, [])
            for note in page_notes:
                is_selected = (getattr(self, 'selected_sticky_note', None) == note and page_index == self.current_page_index)
                cr.save()
                nx = note.x
                ny = note.y
                nw = getattr(note, 'width', 24.0)
                nh = getattr(note, 'height', 24.0)
                nc = getattr(note, 'color', (1.0, 0.86, 0.24))

                # If selected, render glowing halo
                if is_selected:
                    cr.set_source_rgba(0.2, 0.55, 0.95, 0.40)
                    cr.arc(nx + nw / 2.0, ny + nh / 2.0, max(nw, nh) * 0.85, 0, 2 * math.pi)
                    cr.fill()
                    cr.set_source_rgba(0.2, 0.55, 0.95, 0.9)
                    cr.set_line_width(1.8 / self.zoom_level)
                    cr.set_dash([3.0 / self.zoom_level, 3.0 / self.zoom_level])
                    cr.arc(nx + nw / 2.0, ny + nh / 2.0, max(nw, nh) * 0.85, 0, 2 * math.pi)
                    cr.stroke()
                    cr.set_dash([])

                # Drop shadow
                cr.set_source_rgba(0.0, 0.0, 0.0, 0.22)
                cr.rectangle(nx + 1.5 / self.zoom_level, ny + 1.5 / self.zoom_level, nw, nh)
                cr.fill()

                # Main note body with accent color fill
                cr.set_source_rgb(nc[0], nc[1], nc[2])
                cr.rectangle(nx, ny, nw, nh)
                cr.fill_preserve()

                # Dark border
                cr.set_source_rgba(0.15, 0.15, 0.15, 0.85)
                cr.set_line_width(1.2 / self.zoom_level)
                cr.stroke()

                # Folded top-right corner effect
                fold_s = min(6.0, nw * 0.3)
                cr.move_to(nx + nw - fold_s, ny)
                cr.line_to(nx + nw, ny + fold_s)
                cr.line_to(nx + nw - fold_s, ny + fold_s)
                cr.close_path()
                cr.set_source_rgba(0.0, 0.0, 0.0, 0.18)
                cr.fill()

                # Vector icon symbol inside note
                itype = getattr(note, 'icon_type', 'Comment')
                cr.set_source_rgba(0.12, 0.12, 0.12, 0.9)
                cr.set_line_width(1.2 / self.zoom_level)

                if itype == "Help":
                    cx = nx + nw / 2.0
                    cy = ny + nh / 2.0
                    cr.arc(cx, cy - 2.0, 3.0, -math.pi, 0)
                    cr.stroke()
                    cr.arc(cx, cy + 4.0, 1.0, 0, 2 * math.pi)
                    cr.fill()
                elif itype == "Key":
                    cx = nx + nw / 2.0
                    cy = ny + nh / 2.0
                    cr.arc(cx - 3.0, cy, 3.0, 0, 2 * math.pi)
                    cr.stroke()
                    cr.move_to(cx, cy)
                    cr.line_to(cx + 6.0, cy)
                    cr.line_to(cx + 6.0, cy + 3.0)
                    cr.stroke()
                else:
                    pad_in = 5.0
                    l_x = nx + pad_in
                    l_w = nw - pad_in * 2.0
                    cy = ny + nh / 2.0
                    cr.move_to(l_x, cy - 3.0)
                    cr.line_to(l_x + l_w - fold_s * 0.5, cy - 3.0)
                    cr.stroke()
                    cr.move_to(l_x, cy + 1.5)
                    cr.line_to(l_x + l_w, cy + 1.5)
                    cr.stroke()
                    cr.move_to(l_x, cy + 5.5)
                    cr.line_to(l_x + l_w * 0.65, cy + 5.5)
                    cr.stroke()

                cr.restore()

        # Draw persistent visual redaction marks
        if self._active_session:
            page_redacts = self._active_session.redaction_marks.get(page_index, [])
            for mark in page_redacts:
                if getattr(mark, 'is_applied', False):
                    continue
                x0, y0, x1, y1 = mark.bbox
                rw = abs(x1 - x0)
                rh = abs(y1 - y0)
                if rw <= 0 or rh <= 0:
                    continue

                min_x = min(x0, x1)
                min_y = min(y0, y1)

                cr.save()
                # 1. Fill preview (semi-transparent representation of target fill color)
                fc = getattr(mark, 'fill_color', (0.0, 0.0, 0.0))
                fill_alpha = 0.75 if fc == (0.0, 0.0, 0.0) else 0.85
                cr.set_source_rgba(fc[0], fc[1], fc[2], fill_alpha)
                cr.rectangle(min_x, min_y, rw, rh)
                cr.fill()

                # 2. Hazard diagonal warning hatch stripes (45 degrees) in red tint
                cr.save()
                cr.rectangle(min_x, min_y, rw, rh)
                cr.clip()
                cr.set_source_rgba(0.85, 0.15, 0.15, 0.32)
                cr.set_line_width(1.5 / self.zoom_level)
                diag_step = max(12.0 / self.zoom_level, 6.0)
                diag_start = min_x - rh
                diag_end = min_x + rw + rh
                d = diag_start
                while d <= diag_end:
                    cr.move_to(d, min_y)
                    cr.line_to(d + rh, min_y + rh)
                    d += diag_step
                cr.stroke()
                cr.restore()

                # 3. Solid red outline
                bc = getattr(mark, 'border_color', (0.85, 0.15, 0.15, 0.95))
                cr.set_source_rgba(bc[0], bc[1], bc[2], bc[3] if len(bc) > 3 else 0.95)
                cr.set_line_width(1.5 / self.zoom_level)
                cr.rectangle(min_x, min_y, rw, rh)
                cr.stroke()

                # 4. Overlay Text centered in bounding box
                otext = getattr(mark, 'overlay_text', '')
                if otext and otext.strip():
                    cr.save()
                    tc = getattr(mark, 'text_color', (1.0, 1.0, 1.0))
                    cr.set_source_rgb(tc[0], tc[1], tc[2])
                    target_sz = getattr(mark, 'font_size', 10.0) / self.zoom_level
                    target_sz = max(min(target_sz, rh * 0.7), 6.0)
                    cr.set_font_size(target_sz)
                    extents = cr.text_extents(otext)
                    if extents.width > rw - (6.0 / self.zoom_level):
                        scale_factor = (rw - (6.0 / self.zoom_level)) / max(extents.width, 1.0)
                        target_sz = max(target_sz * scale_factor, 5.0)
                        cr.set_font_size(target_sz)
                        extents = cr.text_extents(otext)
                    tx = min_x + (rw - extents.width) / 2.0 - extents.x_bearing
                    ty = min_y + (rh - extents.height) / 2.0 - extents.y_bearing
                    cr.move_to(tx, ty)
                    cr.show_text(otext)
                    cr.restore()

                cr.restore()

        # In-progress distance measurement
        if page_index == active_create_page and getattr(self, 'temp_measurement_line', None) is not None:
            sx, sy, ex, ey = self.temp_measurement_line
            pt_len = math.hypot(ex - sx, ey - sy)
            if pt_len > 1.0:
                cr.save()
                cr.set_source_rgba(0.0, 0.65, 0.95, 0.95)
                cr.set_line_width(2.0 / self.zoom_level)
                cr.move_to(sx, sy)
                cr.line_to(ex, ey)
                cr.stroke()

                theta = math.atan2(ey - sy, ex - sx)
                perp = theta + math.pi / 2.0
                tick_h = 7.0 / self.zoom_level
                dx_p = tick_h * math.cos(perp)
                dy_p = tick_h * math.sin(perp)

                cr.move_to(sx - dx_p, sy - dy_p)
                cr.line_to(sx + dx_p, sy + dy_p)
                cr.stroke()
                cr.move_to(ex - dx_p, ey - dy_p)
                cr.line_to(ex + dx_p, ey + dy_p)
                cr.stroke()

                rad = 3.0 / self.zoom_level
                cr.arc(sx, sy, rad, 0, 2 * math.pi)
                cr.stroke()
                cr.arc(ex, ey, rad, 0, 2 * math.pi)
                cr.stroke()

                active_calib = self.get_scale_calibration(page_index) if hasattr(self, 'get_scale_calibration') else None
                if active_calib and active_calib.points_per_unit > 0:
                    badge_str = active_calib.format_distance(pt_len)
                else:
                    mm_len = (pt_len * 25.4) / 72.0
                    badge_str = f"{pt_len:.1f} pt ({mm_len:.1f} mm)"

                mx = (sx + ex) / 2.0
                my = (sy + ey) / 2.0
                cr.set_font_size(max(10.0 / self.zoom_level, 9.0))
                ext = cr.text_extents(badge_str)
                pad_x = 6.0 / self.zoom_level
                pad_y = 3.0 / self.zoom_level
                bw = ext.width + pad_x * 2.0
                bh = ext.height + pad_y * 2.0
                bx = mx - bw / 2.0
                by = my - bh / 2.0 - (12.0 / self.zoom_level)

                cr.set_source_rgba(0.12, 0.15, 0.20, 0.88)
                cr.rectangle(bx, by, bw, bh)
                cr.fill()

                cr.set_source_rgba(0.0, 0.70, 1.0, 0.95)
                cr.set_line_width(1.0 / self.zoom_level)
                cr.rectangle(bx, by, bw, bh)
                cr.stroke()

                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.move_to(bx + pad_x - ext.x_bearing, by + pad_y - ext.y_bearing)
                cr.show_text(badge_str)
                cr.restore()

        # In-progress area measurement (drag rectangle)
        if page_index == active_create_page and getattr(self, 'temp_measurement_rect', None) is not None:
            x1, y1, x2, y2 = self.temp_measurement_rect
            rw = x2 - x1
            rh = y2 - y1
            if abs(rw) > 1.0 and abs(rh) > 1.0:
                cr.save()
                cr.set_source_rgba(0.0, 0.55, 0.95, 0.22)
                cr.rectangle(x1, y1, rw, rh)
                cr.fill_preserve()

                cr.set_source_rgba(0.0, 0.70, 1.0, 0.95)
                cr.set_line_width(1.8 / self.zoom_level)
                cr.rectangle(x1, y1, rw, rh)
                cr.stroke()

                pt_area = abs(rw * rh)
                active_calib = self.get_scale_calibration(page_index) if hasattr(self, 'get_scale_calibration') else None
                if active_calib and active_calib.points_per_unit > 0:
                    badge_str = active_calib.format_area(pt_area)
                else:
                    badge_str = f"{pt_area:.1f} pt²"

                cx = x1 + rw / 2.0
                cy = y1 + rh / 2.0
                cr.set_font_size(max(10.0 / self.zoom_level, 9.0))
                ext = cr.text_extents(badge_str)
                pad_x = 6.0 / self.zoom_level
                pad_y = 3.0 / self.zoom_level
                bw = ext.width + pad_x * 2.0
                bh = ext.height + pad_y * 2.0
                bx = cx - bw / 2.0
                by = cy - bh / 2.0

                cr.set_source_rgba(0.12, 0.15, 0.20, 0.88)
                cr.rectangle(bx, by, bw, bh)
                cr.fill()

                cr.set_source_rgba(0.0, 0.70, 1.0, 0.95)
                cr.set_line_width(1.0 / self.zoom_level)
                cr.rectangle(bx, by, bw, bh)
                cr.stroke()

                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.move_to(bx + pad_x - ext.x_bearing, by + pad_y - ext.y_bearing)
                cr.show_text(badge_str)
                cr.restore()

        # In-progress multi-click polygon area measurement
        if page_index == active_create_page and getattr(self, 'temp_polygon_vertices', None) and len(self.temp_polygon_vertices) > 0 and getattr(self, 'tool_mode', None) == "measure_area":
            pts = list(self.temp_polygon_vertices)
            last_mouse = getattr(self, 'last_mouse_page_pos', None)
            render_pts = pts + [last_mouse] if last_mouse else pts
            if len(render_pts) >= 2:
                cr.save()
                if len(render_pts) >= 3:
                    cr.move_to(render_pts[0][0], render_pts[0][1])
                    for p in render_pts[1:]:
                        cr.line_to(p[0], p[1])
                    cr.close_path()
                    cr.set_source_rgba(0.0, 0.55, 0.95, 0.18)
                    cr.fill_preserve()
                    cr.set_source_rgba(0.0, 0.70, 1.0, 0.95)
                    cr.set_line_width(1.8 / self.zoom_level)
                    cr.stroke()
                else:
                    cr.set_source_rgba(0.0, 0.70, 1.0, 0.95)
                    cr.set_line_width(1.8 / self.zoom_level)
                    cr.move_to(render_pts[0][0], render_pts[0][1])
                    cr.line_to(render_pts[1][0], render_pts[1][1])
                    cr.stroke()

                # Vertex handles
                rad = 3.5 / self.zoom_level
                for p in pts:
                    cr.arc(p[0], p[1], rad, 0, 2 * math.pi)
                    cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
                    cr.fill_preserve()
                    cr.set_source_rgba(0.0, 0.70, 1.0, 1.0)
                    cr.stroke()
                cr.restore()

        cr.restore()

        # Highlighted native annotation from Annotations Sidebar
        if getattr(self, 'highlighted_native_annot', None):
            ha = self.highlighted_native_annot
            if ha.get('page') == page_index and ha.get('bbox'):
                bx1, by1, bx2, by2 = ha['bbox']
                v_x1, v_y1 = self._unrotated_to_visual_page_coords(bx1, by1, page_index=page_index)
                v_x2, v_y2 = self._unrotated_to_visual_page_coords(bx2, by2, page_index=page_index)
                min_vx = min(v_x1, v_x2)
                max_vx = max(v_x1, v_x2)
                min_vy = min(v_y1, v_y2)
                max_vy = max(v_y1, v_y2)

                sel_dx = page_offset_x + min_vx * self.zoom_level
                sel_dy = page_offset_y + min_vy * self.zoom_level
                sel_dw = (max_vx - min_vx) * self.zoom_level
                sel_dh = (max_vy - min_vy) * self.zoom_level

                cr.save()
                cr.set_source_rgba(0.0, 0.45, 1.0, 0.22)
                cr.rectangle(sel_dx, sel_dy, sel_dw, sel_dh)
                cr.fill_preserve()
                cr.set_source_rgba(0.0, 0.45, 1.0, 0.90)
                cr.set_line_width(2.0)
                cr.set_dash([4.0, 3.0])
                cr.stroke()
                cr.restore()

        # Search match highlights
        if getattr(self, 'search_engine', None) and self.search_engine.matches:
            matches_for_page = self.search_engine.get_matches_for_page(page_index)
            curr_match = self.search_engine.get_current_match()
            for m in matches_for_page:
                is_active = (curr_match is not None and m == curr_match)
                bx1, by1, bx2, by2 = m.rect
                v_x1, v_y1 = self._unrotated_to_visual_page_coords(bx1, by1, page_index=page_index)
                v_x2, v_y2 = self._unrotated_to_visual_page_coords(bx2, by2, page_index=page_index)
                min_vx = min(v_x1, v_x2)
                max_vx = max(v_x1, v_x2)
                min_vy = min(v_y1, v_y2)
                max_vy = max(v_y1, v_y2)

                m_dx = page_offset_x + min_vx * self.zoom_level
                m_dy = page_offset_y + min_vy * self.zoom_level
                m_dw = (max_vx - min_vx) * self.zoom_level
                m_dh = (max_vy - min_vy) * self.zoom_level

                cr.save()
                if is_active:
                    cr.set_source_rgba(1.0, 0.55, 0.0, 0.45)
                    cr.rectangle(m_dx, m_dy, m_dw, m_dh)
                    cr.fill_preserve()
                    cr.set_source_rgba(0.9, 0.35, 0.0, 0.95)
                    cr.set_line_width(2.0)
                    cr.stroke()
                else:
                    cr.set_source_rgba(1.0, 0.92, 0.23, 0.35)
                    cr.rectangle(m_dx, m_dy, m_dw, m_dh)
                    cr.fill_preserve()
                    cr.set_source_rgba(0.85, 0.70, 0.0, 0.8)
                    cr.set_line_width(1.0)
                    cr.stroke()
                cr.restore()

        if self.view_mode and self.view_sel_rect and getattr(self, 'drag_start_page_index', self.current_page_index) == page_index:
            sx1, sy1, sx2, sy2 = self.view_sel_rect
            sel_dx = page_offset_x + sx1 * self.zoom_level
            sel_dy = page_offset_y + sy1 * self.zoom_level
            sel_dw = (sx2 - sx1) * self.zoom_level
            sel_dh = (sy2 - sy1) * self.zoom_level
            cr.save()
            cr.set_source_rgba(0.12, 0.47, 0.9, 0.25)
            cr.rectangle(sel_dx, sel_dy, sel_dw, sel_dh)
            cr.fill()
            cr.set_source_rgba(0.12, 0.47, 0.9, 0.85)
            cr.set_line_width(1.5)
            cr.rectangle(sel_dx, sel_dy, sel_dw, sel_dh)
            cr.stroke()
            cr.restore()

        # OCR / Searchable text layer inspection overlay
        if self.show_ocr_overlay and self.doc and 0 <= page_index < len(self.doc):
            PdfEditorWindow._draw_ocr_overlay(cr, self.doc[page_index], self.zoom_level, page_offset_x, page_offset_y)

    class OcrWordBox(tuple):
        """Word box tuple (x0, y0, x1, y1, word) preserving 5-element unpacking with confidence attribute."""
        confidence: float = 0.90

        def __new__(cls, x0, y0, x1, y1, word, confidence: float = 0.90):
            obj = super().__new__(cls, (float(x0), float(y0), float(x1), float(y1), str(word)))
            obj.confidence = float(confidence)
            return obj

    @staticmethod
    def _extract_ocr_word_boxes(page):
        """Extract word bounding boxes and confidence ratings from a PyMuPDF page.
        
        Returns a list of OcrWordBox tuples: (x0, y0, x1, y1, word_text).
        """
        if page is None:
            return []
        
        # 1. Check if cached from recent OCR run on document
        doc = getattr(page, "parent", None)
        p_num = getattr(page, "number", 0)
        if doc and hasattr(doc, "_ocr_words_cache") and p_num in doc._ocr_words_cache:
            cached_words = doc._ocr_words_cache[p_num]
            res = []
            for item in cached_words:
                bbox = item.get("bbox")
                if bbox and len(bbox) >= 4:
                    text = str(item.get("text", "")).strip()
                    conf = float(item.get("confidence", 0.90))
                    res.append(PdfEditorWindow.OcrWordBox(bbox[0], bbox[1], bbox[2], bbox[3], text, conf))
            if res:
                return res

        # 2. Extract words directly from page text layer with heuristic confidence
        try:
            from .ocr_engine import estimate_word_confidence
            words = page.get_text("words")
            res = []
            for w in words:
                text = str(w[4])
                conf = estimate_word_confidence(text)
                res.append(PdfEditorWindow.OcrWordBox(w[0], w[1], w[2], w[3], text, conf))
            return res
        except Exception:
            return []

    @staticmethod
    def _draw_ocr_overlay(cr, page, zoom: float, offset_x: float = 0.0, offset_y: float = 0.0):
        """Draw transparent bounding boxes and confidence heatmaps over recognized OCR words."""
        boxes = PdfEditorWindow._extract_ocr_word_boxes(page)
        if not boxes:
            return

        cr.save()
        for item in boxes:
            x0, y0, x1, y1, _text = item[:5]
            conf = getattr(item, "confidence", item[5] if len(item) >= 6 else 0.90)

            bx = offset_x + x0 * zoom
            by = offset_y + y0 * zoom
            bw = (x1 - x0) * zoom
            bh = (y1 - y0) * zoom

            if bw <= 0 or bh <= 0:
                continue

            # Confidence Heatmap Color Coding:
            # High Confidence (>= 80%): Crisp Green
            # Medium Confidence (50% - 79%): Amber / Yellow
            # Low Confidence (< 50%): Vivid Red Alert
            if conf >= 0.80:
                fill_rgba = (0.15, 0.68, 0.38, 0.22)
                border_rgba = (0.15, 0.68, 0.38, 0.80)
                dash = [3.0, 2.0]
            elif conf >= 0.50:
                fill_rgba = (0.92, 0.65, 0.05, 0.28)
                border_rgba = (0.92, 0.65, 0.05, 0.85)
                dash = [2.0, 2.0]
            else:
                fill_rgba = (0.88, 0.15, 0.15, 0.38)
                border_rgba = (0.88, 0.15, 0.15, 0.95)
                dash = []

            cr.set_source_rgba(*fill_rgba)
            cr.rectangle(bx, by, bw, bh)
            cr.fill_preserve()

            cr.set_source_rgba(*border_rgba)
            cr.set_line_width(1.2 if conf < 0.50 else 1.0)
            if dash:
                cr.set_dash(dash)
            cr.stroke()
            cr.set_dash([])

        cr.restore()

    def _visual_to_unrotated_page_coords(self, vis_x, vis_y, page_index=None):
        """Convert visual page coordinates to unrotated PDF cropbox coordinates."""
        p_idx = page_index if page_index is not None else self.current_page_index
        if not self.doc or not (0 <= p_idx < len(self.doc)):
            return vis_x, vis_y
        page = self.doc[p_idx]
        if (page.rotation % 360) == 0:
            return vis_x, vis_y
        p = fitz.Point(vis_x, vis_y) * (~page.rotation_matrix)
        return p.x, p.y

    def _unrotated_to_visual_page_coords(self, unrot_x, unrot_y, page_index=None):
        """Convert unrotated PDF cropbox coordinates to visual page coordinates."""
        p_idx = page_index if page_index is not None else self.current_page_index
        if not self.doc or not (0 <= p_idx < len(self.doc)):
            return unrot_x, unrot_y
        page = self.doc[p_idx]
        if (page.rotation % 360) == 0:
            return unrot_x, unrot_y
        p = fitz.Point(unrot_x, unrot_y) * page.rotation_matrix
        return p.x, p.y

    def _visual_to_unrotated_delta(self, dx, dy, page_index=None):
        """Convert a visual delta vector to an unrotated page delta vector."""
        p_idx = page_index if page_index is not None else self.current_page_index
        if not self.doc or not (0 <= p_idx < len(self.doc)):
            return dx, dy
        page = self.doc[p_idx]
        if (page.rotation % 360) == 0:
            return dx, dy
        inv_mat = ~page.rotation_matrix
        p0 = fitz.Point(0, 0) * inv_mat
        p1 = fitz.Point(dx, dy) * inv_mat
        return p1.x - p0.x, p1.y - p0.y

    def _invalidate_spatial_index(self, page_index: Optional[int] = None):
        """Invalidate spatial hash grid acceleration index for specified page or entire document."""
        if not hasattr(self, '_spatial_indices'):
            self._spatial_indices = {}
        if not hasattr(self, '_cached_page_links'):
            self._cached_page_links = {}

        if page_index is None:
            self._spatial_indices.clear()
            self._cached_page_links.clear()
        else:
            keys_to_del = [k for k in self._spatial_indices if k[0] == page_index]
            for k in keys_to_del:
                self._spatial_indices.pop(k, None)
            self._cached_page_links.pop(page_index, None)

    def _get_page_spatial_index(self, page_index: int, category: str = "text"):
        """Retrieve or construct on-demand 2D spatial grid index for page objects."""
        if not hasattr(self, '_spatial_indices') or not isinstance(getattr(self, '_spatial_indices', None), dict):
            self._spatial_indices = {}

        key = (page_index, category)
        grid = self._spatial_indices.get(key)
        if grid is not None:
            return grid

        from .models import SpatialGridIndex
        grid = SpatialGridIndex(cell_size=64.0)

        def _get_obj_aabb(obj):
            box = getattr(obj, 'bbox', None)
            if not box:
                return None
            rot = getattr(obj, 'rotation', 0.0) % 360.0
            if rot == 0.0:
                return box
            x0, y0, x1, y1 = box
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            corners = [
                pdf_handler.rotate_point(x0, y0, cx, cy, rot),
                pdf_handler.rotate_point(x1, y0, cx, cy, rot),
                pdf_handler.rotate_point(x1, y1, cx, cy, rot),
                pdf_handler.rotate_point(x0, y1, cx, cy, rot),
            ]
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            return (min(xs), min(ys), max(xs), max(ys))

        if category == "text":
            for t in getattr(self, 'editable_texts', []):
                if getattr(t, 'page_number', None) == page_index:
                    box = _get_obj_aabb(t)
                    if box:
                        grid.insert(t, box)
        elif category == "image":
            for img in getattr(self, 'editable_images', []):
                if getattr(img, 'page_number', None) == page_index:
                    box = _get_obj_aabb(img)
                    if box:
                        grid.insert(img, box)
        elif category == "shape":
            for s in getattr(self, 'editable_shapes', []):
                if getattr(s, 'page_number', None) == page_index:
                    box = _get_obj_aabb(s)
                    if box:
                        grid.insert(s, box)
        elif category == "stroke":
            for st in getattr(self, 'editable_strokes', []):
                if getattr(st, 'page_number', None) == page_index:
                    box = _get_obj_aabb(st)
                    if box:
                        grid.insert(st, box)

        self._spatial_indices[key] = grid
        return grid

    def _find_text_at_pos(self, page_x, page_y):
        """Find text at pos."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        tolerance = 2 / max(self.zoom_level, 0.001)

        def _test_candidates(cands):
            for text_obj in reversed(cands):
                if getattr(text_obj, 'page_number', self.current_page_index) != self.current_page_index:
                    continue
                if not getattr(text_obj, 'bbox', None): continue
                x1, y1, x2, y2 = text_obj.bbox
                rot = getattr(text_obj, 'rotation', 0.0) % 360.0
                px, py = page_x, page_y
                if rot != 0.0:
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    px, py = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
                if (x1 - tolerance) <= px <= (x2 + tolerance) and \
                   (y1 - tolerance) <= py <= (y2 + tolerance):
                    return text_obj
            return None

        if hasattr(self, '_get_page_spatial_index') and hasattr(self, '_spatial_indices') and isinstance(getattr(self, '_spatial_indices', None), dict):
            grid = self._get_page_spatial_index(self.current_page_index, "text")
            candidates = grid.query_point(page_x, page_y, tolerance=tolerance)
            hit = _test_candidates(candidates)
            if hit is not None:
                return hit
            # Fallback to direct linear search in case the spatial index is stale
            fallback_hit = _test_candidates(getattr(self, 'editable_texts', []))
            if fallback_hit is not None:
                self._invalidate_spatial_index(self.current_page_index)
                return fallback_hit
            return None
        return _test_candidates(getattr(self, 'editable_texts', []))

    def _keep_topmost_hit(self, clicked_text, clicked_image, clicked_shape):
        """Return (text, image, shape) with only the topmost-by-layer hit kept."""
        hits = [o for o in (clicked_text, clicked_image, clicked_shape) if o is not None]
        if len(hits) <= 1:
            return clicked_text, clicked_image, clicked_shape
        page_objs = []
        for coll in (getattr(self, 'editable_images', []), self.editable_shapes,
                     getattr(self, 'editable_strokes', []), self.editable_texts):
            page_objs.extend(o for o in coll
                             if getattr(o, 'page_number', None) == self.current_page_index)
        ordered = pdf_handler.sort_by_layer(page_objs)
        def rank(o):
            for i, p in enumerate(ordered):
                if p is o:
                    return i
            return -1
        top = max(hits, key=rank)
        return (top if top is clicked_text else None,
                top if top is clicked_image else None,
                top if top is clicked_shape else None)

    def _find_image_at_pos(self, page_x, page_y):
        """Find image at pos."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        tolerance = 2 / max(self.zoom_level, 0.001)

        def _test_candidates(cands):
            for img_obj in reversed(cands):
                if getattr(img_obj, 'page_number', self.current_page_index) != self.current_page_index:
                    continue
                if not getattr(img_obj, 'bbox', None): continue
                x1, y1, x2, y2 = img_obj.bbox
                rot = getattr(img_obj, 'rotation', 0.0) % 360.0
                px, py = page_x, page_y
                if rot != 0.0:
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    px, py = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
                if (x1 - tolerance) <= px <= (x2 + tolerance) and (y1 - tolerance) <= py <= (y2 + tolerance):
                    return img_obj
            return None

        if hasattr(self, '_get_page_spatial_index') and hasattr(self, '_spatial_indices') and isinstance(getattr(self, '_spatial_indices', None), dict):
            grid = self._get_page_spatial_index(self.current_page_index, "image")
            candidates = grid.query_point(page_x, page_y, tolerance=tolerance)
            hit = _test_candidates(candidates)
            if hit is not None:
                return hit
            fallback_hit = _test_candidates(getattr(self, 'editable_images', []))
            if fallback_hit is not None:
                self._invalidate_spatial_index(self.current_page_index)
                return fallback_hit
            return None
        return _test_candidates(getattr(self, 'editable_images', []))

    def _find_shape_at_pos(self, page_x, page_y):
        """Find shape at pos."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        tolerance = 3 / max(self.zoom_level, 0.001)

        def _test_candidates(cands):
            for shape_obj in reversed(cands):
                if getattr(shape_obj, 'page_number', self.current_page_index) != self.current_page_index:
                    continue
                if not getattr(shape_obj, 'bbox', None): 
                    continue
                x1, y1, x2, y2 = shape_obj.bbox
                rot = getattr(shape_obj, 'rotation', 0.0) % 360.0
                px, py = page_x, page_y
                if rot != 0.0:
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    px, py = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
                if (x1 - tolerance) <= px <= (x2 + tolerance) and \
                   (y1 - tolerance) <= py <= (y2 + tolerance):
                    return shape_obj
            return None

        if hasattr(self, '_get_page_spatial_index') and hasattr(self, '_spatial_indices') and isinstance(getattr(self, '_spatial_indices', None), dict):
            grid = self._get_page_spatial_index(self.current_page_index, "shape")
            candidates = grid.query_point(page_x, page_y, tolerance=tolerance)
            hit = _test_candidates(candidates)
            if hit is not None:
                return hit
            fallback_hit = _test_candidates(getattr(self, 'editable_shapes', []))
            if fallback_hit is not None:
                self._invalidate_spatial_index(self.current_page_index)
                return fallback_hit
            return None
        return _test_candidates(getattr(self, 'editable_shapes', []))

    def _find_stroke_at_pos(self, page_x, page_y):
        """Find stroke at pos."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        tolerance = 8.0 / max(self.zoom_level, 0.001)

        def _test_candidates(cands):
            for stroke in reversed(cands):
                if getattr(stroke, 'page_number', self.current_page_index) != self.current_page_index:
                    continue
                if not getattr(stroke, 'bbox', None):
                    continue
                x1, y1, x2, y2 = stroke.bbox
                rot = getattr(stroke, 'rotation', 0.0) % 360.0
                px, py = page_x, page_y
                if rot != 0.0:
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    px, py = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
                tol = max(getattr(stroke, 'stroke_width', 2.0), 8.0) / max(self.zoom_level, 0.001)
                if (x1 - tol) <= px <= (x2 + tol) and \
                   (y1 - tol) <= py <= (y2 + tol):
                    return stroke
            return None

        if hasattr(self, '_get_page_spatial_index') and hasattr(self, '_spatial_indices') and isinstance(getattr(self, '_spatial_indices', None), dict):
            grid = self._get_page_spatial_index(self.current_page_index, "stroke")
            candidates = grid.query_point(page_x, page_y, tolerance=tolerance)
            hit = _test_candidates(candidates)
            if hit is not None:
                return hit
            fallback_hit = _test_candidates(getattr(self, 'editable_strokes', []))
            if fallback_hit is not None:
                self._invalidate_spatial_index(self.current_page_index)
                return fallback_hit
            return None
        return _test_candidates(getattr(self, 'editable_strokes', []))

    def _find_form_field_at_pos(self, page_x, page_y):
        """Find interactive form field at page position."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        for field in reversed(getattr(self, 'form_fields', [])):
            if getattr(field, 'page_number', self.current_page_index) != self.current_page_index:
                continue
            x1, y1, x2, y2 = field.rect
            min_x, max_x = min(x1, x2), max(x1, x2)
            min_y, max_y = min(y1, y2), max(y1, y2)
            tolerance = 3.0 / getattr(self, 'zoom_level', 1.0)
            if (min_x - tolerance) <= page_x <= (max_x + tolerance) and (min_y - tolerance) <= page_y <= (max_y + tolerance):
                return field
        return None

    def _find_measurement_at_pos(self, page_x, page_y):
        """Find linear or area measurement object at page position."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        if not self._active_session:
            return None
        measurements = self._active_session.measurements.get(self.current_page_index, [])
        for m in reversed(measurements):
            bx1, by1, bx2, by2 = m.bbox
            tolerance = 6.0 / getattr(self, 'zoom_level', 1.0)
            if (bx1 - tolerance) <= page_x <= (bx2 + tolerance) and (by1 - tolerance) <= page_y <= (by2 + tolerance):
                if m.measurement_type == MeasurementObject.TYPE_DISTANCE and len(m.points) >= 2:
                    p0, p1 = m.points[0], m.points[1]
                    dist_to_seg = point_to_segment_distance(page_x, page_y, p0[0], p0[1], p1[0], p1[1])
                    if dist_to_seg <= (12.0 / getattr(self, 'zoom_level', 1.0)):
                        return m
                elif m.measurement_type == MeasurementObject.TYPE_AREA and len(m.points) >= 3:
                    if point_in_polygon(page_x, page_y, m.points):
                        return m
                cx, cy = m.get_centroid()
                if math.hypot(page_x - cx, page_y - cy) <= (22.0 / getattr(self, 'zoom_level', 1.0)):
                    return m
        return None

    def _compute_form_field_screen_geometry(self, field):
        """Compute pixel position and size for an AcroFormField on the overlay matching canvas centering."""
        if not self.doc or not (0 <= self.current_page_index < len(self.doc)):
            return 0, 0, 0, 0
        field_page = getattr(field, 'page_number', self.current_page_index)
        if hasattr(self, 'get_page_canvas_rect'):
            page_offset_x, page_offset_y, _, _ = self.get_page_canvas_rect(field_page)
        else:
            alloc_w = self.pdf_view.get_allocated_width() if hasattr(self, 'pdf_view') and self.pdf_view else 0
            alloc_h = self.pdf_view.get_allocated_height() if hasattr(self, 'pdf_view') and self.pdf_view else 0
            da_w = alloc_w if alloc_w > 0 else getattr(self, 'current_pdf_page_width', 0)
            da_h = alloc_h if alloc_h > 0 else getattr(self, 'current_pdf_page_height', 0)
            page_offset_x = max(0.0, (da_w - getattr(self, 'current_pdf_page_width', 0)) / 2.0)
            page_offset_y = max(0.0, (da_h - getattr(self, 'current_pdf_page_height', 0)) / 2.0)

        try:
            page = self.doc[field.page_number]
            vis_rect = (fitz.Rect(field.rect) * page.rotation_matrix).normalize()
        except Exception:
            vis_rect = fitz.Rect(field.rect).normalize()

        wx = int(page_offset_x + vis_rect.x0 * self.zoom_level)
        wy = int(page_offset_y + vis_rect.y0 * self.zoom_level)
        ww = max(1, int(vis_rect.width * self.zoom_level))
        wh = max(1, int(vis_rect.height * self.zoom_level))

        if getattr(field, 'field_type', 'text') in ("checkbox", "radio"):
            ww = max(18, ww)
            wh = max(18, wh)
        else:
            ww = max(30, ww)
            wh = max(18, wh)

        return wx, wy, ww, wh

    def _clear_form_field_overlays(self):
        """Remove all existing interactive form field overlay widgets."""
        active_container = getattr(self, '_active_form_field_editor_container', None)
        if active_container and hasattr(self, 'pdf_overlay') and self.pdf_overlay:
            try:
                self.pdf_overlay.remove_overlay(active_container)
            except Exception:
                pass
        self._active_form_field_editor_container = None
        self._active_form_field_editor_widget = None
        self._active_editing_form_field = None
        if hasattr(self, 'pdf_overlay') and self.pdf_overlay and hasattr(self, '_form_field_overlay_widgets'):
            for item in list(self._form_field_overlay_widgets.values()):
                container = item.get("container")
                if container:
                    try:
                        self.pdf_overlay.remove_overlay(container)
                    except Exception:
                        pass
        if hasattr(self, '_form_field_overlay_widgets'):
            self._form_field_overlay_widgets.clear()

    def _update_form_field_overlay_positions(self):
        """Recalculate and update position and size of active ephemeral or persistent form field overlay widgets."""
        if not self.doc or not (0 <= self.current_page_index < len(self.doc)):
            return

        # Update active ephemeral editor if open
        if getattr(self, '_active_form_field_editor_container', None) and getattr(self, '_active_editing_form_field', None):
            field = self._active_editing_form_field
            container = self._active_form_field_editor_container
            wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)
            container.set_margin_start(wx)
            container.set_margin_top(wy)
            container.set_size_request(ww, wh)

        if not hasattr(self, '_form_field_overlay_widgets') or not self._form_field_overlay_widgets:
            return

        for entry_data in list(self._form_field_overlay_widgets.values()):
            field = entry_data.get("field")
            container = entry_data.get("container")
            if not field or not container or container == getattr(self, '_active_form_field_editor_container', None):
                continue
            wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)
            container.set_margin_start(wx)
            container.set_margin_top(wy)
            container.set_size_request(ww, wh)

    def _sync_form_field_value(self, field, new_value, record_undo=False, old_val_override=None):
        """Update field value in memory and in PyMuPDF doc, marking document modified."""
        if getattr(self, '_syncing_form_field', False):
            return
        old_val = old_val_override if old_val_override is not None else field.value
        if old_val == new_value:
            return

        self._syncing_form_field = True
        try:
            field.set_value(new_value)
            if self.doc:
                pdf_handler.update_acroform_field_value(
                    self.doc,
                    field.page_number,
                    field.xref,
                    new_value
                )
            self.document_modified = True
            if record_undo:
                cmd = EditFormFieldCommand(self, field, old_val, new_value)
                self.undo_manager.add_command(cmd)
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            self._update_ui_state()
        finally:
            self._syncing_form_field = False

    def _refresh_form_field_widget_value(self, field):
        """Update displayed value in overlay widget to match field.value without feedback loop."""
        if not hasattr(self, '_form_field_overlay_widgets') or not field:
            return
        fid = getattr(field, 'field_id', None)
        entry_data = self._form_field_overlay_widgets.get(fid)
        if not entry_data:
            for data in self._form_field_overlay_widgets.values():
                if getattr(data.get("field"), 'xref', -1) == getattr(field, 'xref', -2):
                    entry_data = data
                    break
        if not entry_data:
            return

        widget = entry_data.get("widget")
        if not widget:
            return

        self._syncing_form_field = True
        try:
            entry_data["current_val"] = field.value
            entry_data["initial_val"] = field.value
            if isinstance(widget, Gtk.Entry):
                val_str = str(field.value if field.value is not None else "")
                if widget.get_text() != val_str:
                    widget.set_text(val_str)
            elif isinstance(widget, Gtk.TextView):
                val_str = str(field.value if field.value is not None else "")
                buf = widget.get_buffer()
                start, end = buf.get_bounds()
                if buf.get_text(start, end, True) != val_str:
                    buf.set_text(val_str)
            elif isinstance(widget, Gtk.CheckButton):
                active_bool = bool(field.is_checked)
                if widget.get_active() != active_bool:
                    widget.set_active(active_bool)
            elif isinstance(widget, Gtk.DropDown):
                export_items = entry_data.get("export_items", [])
                display_items = entry_data.get("display_items", [])
                val_str = str(field.value if field.value is not None else "")
                target_idx = None
                if val_str in export_items:
                    target_idx = export_items.index(val_str)
                elif val_str in display_items:
                    target_idx = display_items.index(val_str)
                if target_idx is not None and widget.get_selected() != target_idx:
                    widget.set_selected(target_idx)
        finally:
            self._syncing_form_field = False

    def _commit_pending_form_field_edit(self):
        """Commit any uncommitted text changes in active form field overlays."""
        if not hasattr(self, '_form_field_overlay_widgets') or not self._form_field_overlay_widgets:
            return
        for entry_data in list(self._form_field_overlay_widgets.values()):
            field = entry_data.get("field")
            cur = entry_data.get("current_val")
            init = entry_data.get("initial_val")
            if field and cur is not None and cur != init:
                cmd = EditFormFieldCommand(self, field, init, cur)
                self.undo_manager.add_command(cmd)
                entry_data["initial_val"] = cur

    def _on_form_builder_type_changed(self, dropdown, pspec):
        """Update active form field type when selected in toolbar dropdown."""
        idx = dropdown.get_selected()
        mapping = ["text", "checkbox", "combobox"]
        if 0 <= idx < len(mapping):
            self.form_builder_field_type = mapping[idx]
        if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
            self.form_builder_multiline_check.set_visible(self.form_builder_field_type == "text")
        if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
            self.form_builder_options_box.set_visible(self.form_builder_field_type == "combobox")

    def _get_next_form_field_name(self, field_type: str) -> str:
        """Generate a guaranteed unique field name for a newly created form field."""
        prefix_map = {
            "text": "text_field",
            "checkbox": "check_box",
            "combobox": "combo_box",
            "choice": "combo_box",
            "listbox": "list_box",
            "signature": "signature_field"
        }
        prefix = prefix_map.get(field_type, "form_field")
        existing_names = set()
        if self.doc and not getattr(self.doc, "is_closed", False):
            for p in self.doc:
                for w in p.widgets():
                    if getattr(w, 'field_name', None):
                        existing_names.add(w.field_name)

        idx = 1
        while f"{prefix}_{idx}" in existing_names:
            idx += 1
        return f"{prefix}_{idx}"

    def _create_new_form_field(self, rect: tuple):
        """Create a new AcroForm interactive widget on current page and set up undo history."""
        if not self.doc or getattr(self.doc, "is_closed", False):
            return

        field_type = getattr(self, 'form_builder_field_type', 'text')
        user_name = ""
        if hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry:
            user_name = self.form_builder_name_entry.get_text().strip()

        field_name = user_name or self._get_next_form_field_name(field_type)

        if hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry and user_name:
            self.form_builder_name_entry.set_text("")

        is_multiline = False
        default_val = None
        choices = None

        if field_type == "text":
            if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
                is_multiline = self.form_builder_multiline_check.get_active()
            default_val = ""
        elif field_type == "checkbox":
            default_val = False
        elif field_type in ("combobox", "choice"):
            opt_str = ""
            if hasattr(self, 'form_builder_options_entry') and self.form_builder_options_entry:
                opt_str = self.form_builder_options_entry.get_text().strip()
            if opt_str:
                choices = [c.strip() for c in opt_str.split(",") if c.strip()]
            if not choices:
                choices = ["Option 1", "Option 2", "Option 3"]
            default_val = choices[0] if choices else "Option 1"

        command = AddFormFieldCommand(
            self,
            self.current_page_index,
            field_type,
            rect,
            field_name,
            default_value=default_val,
            choice_values=choices,
            is_multiline=is_multiline
        )
        command.execute()
        self.undo_manager.add_command(command)
        self.document_modified = True

        add_label = (hasattr(self, 'form_builder_add_label_check') and 
                     self.form_builder_add_label_check and 
                     self.form_builder_add_label_check.get_active())
        label_text = ""
        if hasattr(self, 'form_builder_label_entry') and self.form_builder_label_entry:
            label_text = self.form_builder_label_entry.get_text().strip()

        if add_label or label_text:
            if not label_text:
                label_text = f"{field_name}:"
            x1, y1, x2, y2 = rect
            h = y2 - y1
            if field_type == "checkbox":
                lbl_x = x2 + 8.0
                lbl_y = y1 + (h / 2.0) - 7.0
            else:
                lbl_x = x1
                lbl_y = max(4.0, y1 - 18.0)

            font_size = 11.0
            lbl_obj = EditableText(
                x=lbl_x,
                y=lbl_y,
                text=label_text,
                font_size=font_size,
                color=(0.1, 0.1, 0.1),
                is_new=True,
                baseline=lbl_y + (font_size * 0.9)
            )
            lbl_obj.font_family_base = "Liberation Sans"
            lbl_obj.page_number = self.current_page_index
            lbl_cmd = AddObjectCommand(self, lbl_obj)
            lbl_cmd.execute()
            self.undo_manager.add_command(lbl_cmd)

        new_field = pdf_handler.get_acroform_field(self.doc, self.current_page_index, field_name)
        if new_field:
            self.selected_form_field = new_field
            self._update_form_builder_controls_for_selected()
            self._update_form_field_overlay_interactivity()

    def _update_form_builder_controls_for_selected(self):
        """Synchronize toolbar controls with selected form field or reset to defaults."""
        self._updating_form_builder_ui = True
        try:
            if getattr(self, 'selected_form_field', None):
                ftype = getattr(self.selected_form_field, 'field_type', 'text').lower()
                if ftype in ("text", "tx"):
                    if hasattr(self, 'form_builder_type_dropdown') and self.form_builder_type_dropdown:
                        self.form_builder_type_dropdown.set_selected(0)
                    self.form_builder_field_type = "text"
                    if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
                        self.form_builder_multiline_check.set_visible(True)
                        self.form_builder_multiline_check.set_active(getattr(self.selected_form_field, 'is_multiline', False))
                    if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
                        self.form_builder_options_box.set_visible(False)
                elif ftype in ("checkbox", "check", "cb"):
                    if hasattr(self, 'form_builder_type_dropdown') and self.form_builder_type_dropdown:
                        self.form_builder_type_dropdown.set_selected(1)
                    self.form_builder_field_type = "checkbox"
                    if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
                        self.form_builder_multiline_check.set_visible(False)
                    if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
                        self.form_builder_options_box.set_visible(False)
                elif ftype in ("combobox", "choice", "dropdown", "ch", "listbox"):
                    if hasattr(self, 'form_builder_type_dropdown') and self.form_builder_type_dropdown:
                        self.form_builder_type_dropdown.set_selected(2)
                    self.form_builder_field_type = "combobox"
                    if hasattr(self, 'form_builder_multiline_check') and self.form_builder_multiline_check:
                        self.form_builder_multiline_check.set_visible(False)
                    if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
                        self.form_builder_options_box.set_visible(True)
                    if hasattr(self, 'form_builder_options_entry') and self.form_builder_options_entry:
                        c_vals = getattr(self.selected_form_field, 'choice_values', []) or []
                        flat_choices = []
                        for c in c_vals:
                            if isinstance(c, (list, tuple)):
                                flat_choices.append(str(c[1] if len(c) > 1 else c[0]))
                            else:
                                flat_choices.append(str(c))
                        self.form_builder_options_entry.set_text(", ".join(flat_choices))
                if hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry:
                    self.form_builder_name_entry.set_text(getattr(self.selected_form_field, 'field_name', ''))
                if hasattr(self, 'form_builder_delete_button') and self.form_builder_delete_button:
                    self.form_builder_delete_button.set_sensitive(True)
            else:
                next_name = self._get_next_form_field_name(getattr(self, 'form_builder_field_type', 'text'))
                if hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry:
                    self.form_builder_name_entry.set_text(next_name)
                if hasattr(self, 'form_builder_delete_button') and self.form_builder_delete_button:
                    self.form_builder_delete_button.set_sensitive(False)
                if hasattr(self, 'form_builder_options_box') and self.form_builder_options_box:
                    self.form_builder_options_box.set_visible(getattr(self, 'form_builder_field_type', 'text') == 'combobox')
        finally:
            self._updating_form_builder_ui = False

    def _on_form_builder_options_changed(self, entry):
        """Handle editing comma-separated choices for selected combobox."""
        if getattr(self, '_updating_form_builder_ui', False):
            return
        if not getattr(self, 'selected_form_field', None) or not self.doc:
            return
        ftype = getattr(self.selected_form_field, 'field_type', '').lower()
        if ftype not in ("combobox", "choice", "dropdown", "ch", "listbox"):
            return
        text = entry.get_text()
        new_choices = [c.strip() for c in text.split(",") if c.strip()]
        if not new_choices:
            return
        old_choices = getattr(self.selected_form_field, 'choice_values', []) or []
        if new_choices == old_choices:
            return
        command = EditFormFieldChoicesCommand(self, self.selected_form_field, old_choices, new_choices)
        command.execute()
        self.undo_manager.add_command(command)
        self.document_modified = True
        self._update_tab_dirty_state()

    def _on_form_builder_edit_options_clicked(self, button):
        """Open a dialog allowing user to edit choices line by line."""
        current_text = ""
        if hasattr(self, 'form_builder_options_entry') and self.form_builder_options_entry:
            current_text = self.form_builder_options_entry.get_text().strip()
        if not current_text and getattr(self, 'selected_form_field', None):
            c_vals = getattr(self.selected_form_field, 'choice_values', []) or []
            flat_choices = []
            for c in c_vals:
                if isinstance(c, (list, tuple)):
                    flat_choices.append(str(c[1] if len(c) > 1 else c[0]))
                else:
                    flat_choices.append(str(c))
            current_text = ", ".join(flat_choices)
        
        initial_lines = [s.strip() for s in current_text.split(",") if s.strip()] if current_text else ["Option 1", "Option 2", "Option 3"]

        dialog = Adw.Window()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_destroy_with_parent(True)

        clean_title = _("form_field_edit_options_title").replace(":", "").strip()
        dialog.set_title(clean_title)
        dialog.set_default_size(440, 420)
        dialog.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog.set_content(main_box)

        header = Adw.HeaderBar()
        cancel_btn = Gtk.Button(label=_("btn_cancel"))
        cancel_btn.connect("clicked", lambda b: dialog.close())
        header.pack_start(cancel_btn)

        apply_btn = Gtk.Button(label=_("btn_apply"))
        apply_btn.add_css_class("suggested-action")
        header.pack_end(apply_btn)
        main_box.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=400)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        clamp.set_child(content_box)

        pref_group = Adw.PreferencesGroup()
        pref_group.set_title(_("form_field_options_label").replace(":", "").strip())
        pref_group.set_description(clean_title)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")

        inner_scroll = Gtk.ScrolledWindow()
        inner_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        inner_scroll.set_min_content_height(200)
        inner_scroll.set_vexpand(True)

        tv = Gtk.TextView()
        tv.set_top_margin(12)
        tv.set_bottom_margin(12)
        tv.set_left_margin(14)
        tv.set_right_margin(14)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv_buf = tv.get_buffer()
        tv_buf.set_text("\n".join(initial_lines))
        inner_scroll.set_child(tv)
        card.append(inner_scroll)
        pref_group.add(card)
        content_box.append(pref_group)

        tip_lbl = Gtk.Label(label=_("form_field_options_tip"))
        tip_lbl.add_css_class("dim-label")
        tip_lbl.add_css_class("caption")
        tip_lbl.set_halign(Gtk.Align.START)
        content_box.append(tip_lbl)

        def _on_apply(b):
            start, end = tv_buf.get_bounds()
            text_val = tv_buf.get_text(start, end, True)
            new_opts = [line.strip() for line in text_val.splitlines() if line.strip()]
            if not new_opts:
                new_opts = ["Option 1"]
            joined = ", ".join(new_opts)
            if hasattr(self, 'form_builder_options_entry') and self.form_builder_options_entry:
                self.form_builder_options_entry.set_text(joined)
            if getattr(self, 'selected_form_field', None):
                old_opts = getattr(self.selected_form_field, 'choice_values', []) or []
                if new_opts != old_opts:
                    cmd = EditFormFieldChoicesCommand(self, self.selected_form_field, old_opts, new_opts)
                    cmd.execute()
                    self.undo_manager.add_command(cmd)
                    self.document_modified = True
                    self._update_tab_dirty_state()
            dialog.close()

        apply_btn.connect("clicked", _on_apply)

        key_ctrl = Gtk.EventControllerKey()
        def _on_key(ctrl, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                dialog.close()
                return True
            elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and (state & Gdk.ModifierType.CONTROL_MASK):
                _on_apply(None)
                return True
            return False
        key_ctrl.connect("key-pressed", _on_key)
        dialog.add_controller(key_ctrl)

        dialog.present()

    def _on_form_builder_name_changed(self, entry):
        """Handle user editing the field name entry for the selected form field."""
        if getattr(self, '_updating_form_builder_ui', False):
            return
        if not getattr(self, 'selected_form_field', None) or not self.doc:
            return
        new_name = entry.get_text().strip()
        old_name = getattr(self.selected_form_field, 'field_name', '')
        if not new_name or new_name == old_name:
            return
        self.selected_form_field.field_name = new_name
        try:
            page = self.doc.load_page(getattr(self.selected_form_field, 'page_number', self.current_page_index))
            for w in page.widgets():
                if getattr(w, 'xref', None) == getattr(self.selected_form_field, 'xref', None) or getattr(w, 'field_name', None) == old_name:
                    w.field_name = new_name
                    w.update()
                    break
            self.document_modified = True
            self._update_tab_dirty_state()
        except Exception as e:
            print(f"Error updating form field name: {e}")

    def _on_form_builder_multiline_toggled(self, check):
        """Handle user toggling multiline checkbutton for selected form field."""
        if getattr(self, '_updating_form_builder_ui', False):
            return
        if not getattr(self, 'selected_form_field', None) or not self.doc:
            return
        if getattr(self.selected_form_field, 'field_type', 'text') != 'text':
            return
        is_multi = check.get_active()
        if getattr(self.selected_form_field, 'is_multiline', False) == is_multi:
            return
        self.selected_form_field.is_multiline = is_multi
        try:
            page = self.doc.load_page(getattr(self.selected_form_field, 'page_number', self.current_page_index))
            for w in page.widgets():
                if getattr(w, 'xref', None) == getattr(self.selected_form_field, 'xref', None) or getattr(w, 'field_name', None) == self.selected_form_field.field_name:
                    if is_multi:
                        w.field_flags |= fitz.PDF_TX_FIELD_IS_MULTILINE
                    else:
                        w.field_flags &= ~fitz.PDF_TX_FIELD_IS_MULTILINE
                    w.update()
                    break
            self.document_modified = True
            self._update_tab_dirty_state()
            self._load_acroform_fields_for_page(self.current_page_index)
        except Exception as e:
            print(f"Error updating multiline flag: {e}")

    def _on_form_builder_delete_clicked(self, button):
        """Handle clicking delete button in Form Builder toolbar."""
        self._delete_selected_form_field()

    def _delete_selected_form_field(self):
        """Delete currently selected form field with confirmation and undo support."""
        if not getattr(self, 'selected_form_field', None):
            return
        field = self.selected_form_field
        self._handle_delete_with_confirmation(field, "delete_form_field_confirm")

    def _get_overlay_for_field(self, field):
        """Retrieve overlay entry dictionary for a given field."""
        if not field or not hasattr(self, '_form_field_overlay_widgets'):
            return None
        fid = getattr(field, 'field_id', None)
        ed = self._form_field_overlay_widgets.get(fid)
        if not ed:
            for d in self._form_field_overlay_widgets.values():
                if (d.get("field") == field or 
                    getattr(d.get("field"), 'xref', None) == getattr(field, 'xref', -1) or
                    getattr(d.get("field"), 'field_name', None) == getattr(field, 'field_name', None)):
                    return d
        return ed

    def _open_form_field_editor(self, field):
        """Open in-place editor or toggle field upon view-mode activation."""
        if not field:
            return
        self.selected_form_field = field

        # Form filling is only enabled in View Mode!
        if not getattr(self, 'view_mode', False) and not getattr(self, '_enable_persistent_form_overlays', False):
            self._update_form_builder_controls_for_selected()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        ftype = getattr(field, 'field_type', 'text').lower()
        if ftype in ("checkbox", "check", "cb"):
            if not getattr(field, 'is_read_only', False):
                old_val = field.value
                new_val = not bool(field.is_checked)
                self._sync_form_field_value(field, new_val, record_undo=True, old_val_override=old_val)
            self._update_form_builder_controls_for_selected()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        if ftype == "radio":
            if not getattr(field, 'is_read_only', False):
                old_val = field.value
                self._sync_form_field_value(field, True, record_undo=True, old_val_override=old_val)
            self._update_form_builder_controls_for_selected()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        if ftype in ("combobox", "choice", "dropdown", "ch", "listbox"):
            if not getattr(field, 'is_read_only', False):
                self._open_form_field_dropdown_popover(field)
            self._update_form_builder_controls_for_selected()
            return

        # Handle persistent overlay if one exists in legacy mode
        entry_data = self._get_overlay_for_field(field)
        if entry_data and entry_data.get("widget") and entry_data.get("container") != getattr(self, '_active_form_field_editor_container', None):
            self._active_editing_form_field = field
            container = entry_data.get("container")
            if container and hasattr(container, "set_can_target"):
                container.set_can_target(True)
            w = entry_data["widget"]
            try:
                w.grab_focus()
                if isinstance(w, Gtk.Entry):
                    w.select_region(0, -1)
            except Exception:
                pass
            self._update_form_builder_controls_for_selected()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        # Text field: spawn ephemeral in-place editor over canvas
        if getattr(field, 'is_read_only', False):
            return

        self._close_active_form_field_editor()
        self._active_editing_form_field = field
        self._active_form_field_initial_val = field.value

        wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)

        if getattr(field, 'is_multiline', False):
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.add_css_class("acroform-frame")
            scroll.set_halign(Gtk.Align.START)
            scroll.set_valign(Gtk.Align.START)
            scroll.set_margin_start(wx)
            scroll.set_margin_top(wy)
            scroll.set_size_request(ww, wh)

            tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
            tv.add_css_class("acroform-textview")
            buf = tv.get_buffer()
            buf.set_text(str(field.value if field.value is not None else ""))
            scroll.set_child(tv)
            container = scroll
            widget = tv
        else:
            entry = Gtk.Entry()
            entry.add_css_class("acroform-entry")
            if getattr(field, 'is_password', False):
                entry.set_visibility(False)
            if getattr(field, 'max_length', 0) > 0:
                entry.set_max_length(field.max_length)
            entry.set_text(str(field.value if field.value is not None else ""))
            entry.set_halign(Gtk.Align.START)
            entry.set_valign(Gtk.Align.START)
            entry.set_margin_start(wx)
            entry.set_margin_top(wy)
            entry.set_size_request(ww, wh)
            container = entry
            widget = entry

        entry_data = {
            "field": field,
            "container": container,
            "widget": widget,
            "initial_val": field.value,
            "current_val": field.value,
        }
        self._form_field_overlay_widgets[field.field_id] = entry_data
        self._active_form_field_editor_container = container
        self._active_form_field_editor_widget = widget

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", lambda *a: self._close_active_form_field_editor())
        widget.add_controller(focus_ctrl)

        key_ctrl = Gtk.EventControllerKey()
        def _on_key(ctrl, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                self._cancel_active_form_field_editor()
                return True
            elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not getattr(field, 'is_multiline', False):
                self._close_active_form_field_editor()
                return True
            return False
        key_ctrl.connect("key-pressed", _on_key)
        widget.add_controller(key_ctrl)

        if isinstance(widget, Gtk.Entry):
            widget.connect("activate", lambda *a: self._close_active_form_field_editor())

        if hasattr(self, 'pdf_overlay') and self.pdf_overlay:
            self.pdf_overlay.add_overlay(container)

        try:
            widget.grab_focus()
            if isinstance(widget, Gtk.Entry):
                widget.select_region(0, -1)
        except Exception:
            pass

        self._update_form_builder_controls_for_selected()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def _close_active_form_field_editor(self):
        """Close active in-place form field editor, save value, and remove ephemeral widget."""
        if getattr(self, '_active_editing_form_field', None) is None:
            return
        active_field = self._active_editing_form_field
        init_val = getattr(self, '_active_form_field_initial_val', active_field.value)
        widget = getattr(self, '_active_form_field_editor_widget', None)

        entry_data = self._get_overlay_for_field(active_field)
        if entry_data and not getattr(self, '_active_form_field_editor_container', None):
            cur = entry_data.get("current_val", active_field.value)
            init = entry_data.get("initial_val", active_field.value)
            if cur != init:
                cmd = EditFormFieldCommand(self, active_field, init, cur)
                self.undo_manager.add_command(cmd)
                entry_data["initial_val"] = cur
            for ed in getattr(self, '_form_field_overlay_widgets', {}).values():
                c = ed.get("container")
                if c and hasattr(c, "set_can_target"):
                    c.set_can_target(bool(getattr(self, 'view_mode', False)))
            self._active_editing_form_field = None
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.grab_focus()
                self.pdf_view.queue_draw()
            return

        new_val = active_field.value
        if isinstance(widget, Gtk.Entry):
            new_val = widget.get_text()
        elif isinstance(widget, Gtk.TextView):
            buf = widget.get_buffer()
            start, end = buf.get_bounds()
            new_val = buf.get_text(start, end, True)

        container = getattr(self, '_active_form_field_editor_container', None)
        if container and hasattr(self, 'pdf_overlay') and self.pdf_overlay:
            try:
                self.pdf_overlay.remove_overlay(container)
            except Exception:
                pass

        fid = getattr(active_field, 'field_id', None)
        if fid and fid in self._form_field_overlay_widgets:
            del self._form_field_overlay_widgets[fid]

        self._active_editing_form_field = None
        self._active_form_field_editor_container = None
        self._active_form_field_editor_widget = None

        if new_val != init_val:
            self._sync_form_field_value(active_field, new_val, record_undo=True, old_val_override=init_val)

        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.grab_focus()
            self.pdf_view.queue_draw()

    def _cancel_active_form_field_editor(self):
        """Cancel active in-place editing without saving changes."""
        if getattr(self, '_active_editing_form_field', None) is None:
            return
        container = getattr(self, '_active_form_field_editor_container', None)
        if container and hasattr(self, 'pdf_overlay') and self.pdf_overlay:
            try:
                self.pdf_overlay.remove_overlay(container)
            except Exception:
                pass
        fid = getattr(self._active_editing_form_field, 'field_id', None)
        if fid and fid in self._form_field_overlay_widgets:
            del self._form_field_overlay_widgets[fid]
        self._active_editing_form_field = None
        self._active_form_field_editor_container = None
        self._active_form_field_editor_widget = None
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.grab_focus()
            self.pdf_view.queue_draw()

    def _open_form_field_dropdown_popover(self, field):
        """Open a native GTK Popover menu to select dropdown choices without permanent overlay widgets."""
        if not field:
            return
        self.selected_form_field = field

        wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)

        popover = Gtk.Popover()
        popover.set_parent(self.pdf_view)
        rect = Gdk.Rectangle()
        rect.x = wx
        rect.y = wy
        rect.width = ww
        rect.height = wh
        popover.set_pointing_to(rect)
        popover.set_position(Gtk.PositionType.BOTTOM)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(240)
        scroll.set_propagate_natural_height(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(4)
        box.set_margin_end(4)

        raw_choices = getattr(field, 'choice_values', []) or []
        if not raw_choices:
            raw_choices = ["Option 1", "Option 2", "Option 3"]

        for item in raw_choices:
            if isinstance(item, (list, tuple)):
                exp_val = str(item[0]) if len(item) > 0 else ""
                disp_val = str(item[1]) if len(item) > 1 else exp_val
            else:
                exp_val = str(item)
                disp_val = exp_val

            btn = Gtk.Button(label=disp_val)
            btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)
            if exp_val == field.value:
                btn.add_css_class("suggested-action")

            def _on_choice_picked(b, val=exp_val):
                popover.popdown()
                old_val = field.value
                self._sync_form_field_value(field, val, record_undo=True, old_val_override=old_val)
                if hasattr(self, 'pdf_view') and self.pdf_view:
                    self.pdf_view.queue_draw()

            btn.connect("clicked", _on_choice_picked)
            box.append(btn)

        scroll.set_child(box)
        popover.set_child(scroll)

        def _on_closed(p):
            GLib.idle_add(p.unparent)

        popover.connect("closed", _on_closed)
        popover.popup()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def _update_form_field_overlay_interactivity(self):
        """Update whether form field overlays capture mouse input or pass through to canvas."""
        for ed in getattr(self, '_form_field_overlay_widgets', {}).values():
            container = ed.get("container")
            if container and hasattr(container, "set_can_target"):
                if getattr(self, 'view_mode', False):
                    container.set_can_target(True)
                else:
                    is_active = (getattr(self, '_active_editing_form_field', None) is not None and
                                 (ed.get("field") == self._active_editing_form_field or
                                  getattr(ed.get("field"), 'xref', None) == getattr(self._active_editing_form_field, 'xref', -1)))
                    container.set_can_target(bool(is_active))

    def _load_acroform_fields_for_page(self, page_index=None):
        """Reload AcroForm fields and rebuild overlays for the specified or current page."""
        if not self.doc or getattr(self.doc, "is_closed", False):
            self.form_fields = []
            if hasattr(self, '_create_form_field_overlays'):
                self._create_form_field_overlays()
            return
        if page_index is None:
            page_index = self.current_page_index
        fields, err = pdf_handler.extract_acroform_fields(self.doc, page_index)
        if not err:
            self.form_fields = fields
        else:
            self.form_fields = []
        if hasattr(self, '_create_form_field_overlays'):
            self._create_form_field_overlays()

    def _focus_form_field_overlay(self, field):
        """Focus the overlay widget corresponding to field if available, or open in-place editor."""
        if not field:
            return
        entry_data = self._get_overlay_for_field(field)
        if entry_data and entry_data.get("widget"):
            try:
                entry_data["widget"].grab_focus()
                return
            except Exception:
                pass
        self._open_form_field_editor(field)

    def _create_form_field_overlays(self):
        """Create and place GTK overlay widgets for form fields on current page."""
        self._clear_form_field_overlays()
        if not getattr(self, '_enable_persistent_form_overlays', False):
            return
        if not self.doc or not hasattr(self, 'pdf_overlay') or not self.pdf_overlay:
            return
        if not (0 <= self.current_page_index < len(self.doc)):
            return

        current_fields = [
            f for f in getattr(self, 'form_fields', [])
            if getattr(f, 'page_number', self.current_page_index) == self.current_page_index
        ]

        for field in current_fields:
            ftype = getattr(field, 'field_type', 'text')
            wx, wy, ww, wh = self._compute_form_field_screen_geometry(field)

            if ftype == "text":
                if getattr(field, 'is_multiline', False):
                    scroll = Gtk.ScrolledWindow()
                    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
                    scroll.add_css_class("acroform-frame")
                    scroll.set_halign(Gtk.Align.START)
                    scroll.set_valign(Gtk.Align.START)
                    scroll.set_margin_start(wx)
                    scroll.set_margin_top(wy)
                    scroll.set_size_request(ww, wh)

                    tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
                    tv.add_css_class("acroform-textview")
                    if getattr(field, 'is_read_only', False):
                        tv.set_editable(False)
                    buf = tv.get_buffer()
                    buf.set_text(str(field.value if field.value is not None else ""))
                    scroll.set_child(tv)

                    container = scroll
                    input_widget = tv

                    entry_data = {
                        "field": field,
                        "container": container,
                        "widget": input_widget,
                        "initial_val": field.value,
                        "current_val": field.value,
                    }

                    def _on_tv_changed(b, ed=entry_data):
                        if getattr(self, '_syncing_form_field', False):
                            return
                        start, end = b.get_bounds()
                        txt = b.get_text(start, end, True)
                        ed["current_val"] = txt
                        self._sync_form_field_value(ed["field"], txt, record_undo=False)

                    def _on_tv_focus_leave(ctrl, ed=entry_data):
                        if getattr(self, '_syncing_form_field', False):
                            return
                        cur = ed.get("current_val", "")
                        init = ed.get("initial_val", "")
                        if cur != init:
                            cmd = EditFormFieldCommand(self, ed["field"], init, cur)
                            self.undo_manager.add_command(cmd)
                            ed["initial_val"] = cur
                        if getattr(self, '_active_editing_form_field', None) == ed.get("field"):
                            self._close_active_form_field_editor()

                    def _on_tv_focus_enter(ctrl, ed=entry_data):
                        ed["initial_val"] = ed.get("current_val", ed["field"].value)
                        self.selected_form_field = ed["field"]
                        if hasattr(self, 'pdf_view') and self.pdf_view:
                            self.pdf_view.queue_draw()
                        self._update_ui_state()

                    buf.connect("changed", _on_tv_changed)
                    focus_ctrl = Gtk.EventControllerFocus()
                    focus_ctrl.connect("enter", _on_tv_focus_enter)
                    focus_ctrl.connect("leave", _on_tv_focus_leave)
                    tv.add_controller(focus_ctrl)

                    key_ctrl = Gtk.EventControllerKey()
                    def _on_tv_key(ctrl, keyval, keycode, state):
                        if keyval == Gdk.KEY_Escape:
                            self._close_active_form_field_editor()
                            return True
                        return False
                    key_ctrl.connect("key-pressed", _on_tv_key)
                    tv.add_controller(key_ctrl)

                else:
                    entry = Gtk.Entry()
                    entry.add_css_class("acroform-entry")
                    if getattr(field, 'is_read_only', False):
                        entry.set_editable(False)
                        entry.add_css_class("readonly")
                    if getattr(field, 'is_password', False):
                        entry.set_visibility(False)
                    if getattr(field, 'max_length', 0) > 0:
                        entry.set_max_length(field.max_length)

                    entry.set_text(str(field.value if field.value is not None else ""))
                    entry.set_halign(Gtk.Align.START)
                    entry.set_valign(Gtk.Align.START)
                    entry.set_margin_start(wx)
                    entry.set_margin_top(wy)
                    entry.set_size_request(ww, wh)

                    container = entry
                    input_widget = entry

                    entry_data = {
                        "field": field,
                        "container": container,
                        "widget": input_widget,
                        "initial_val": field.value,
                        "current_val": field.value,
                    }

                    def _on_entry_changed(w, ed=entry_data):
                        if getattr(self, '_syncing_form_field', False):
                            return
                        txt = w.get_text()
                        ed["current_val"] = txt
                        self._sync_form_field_value(ed["field"], txt, record_undo=False)

                    def _on_entry_focus_leave(ctrl, ed=entry_data):
                        if getattr(self, '_syncing_form_field', False):
                            return
                        cur = ed.get("current_val", "")
                        init = ed.get("initial_val", "")
                        if cur != init:
                            cmd = EditFormFieldCommand(self, ed["field"], init, cur)
                            self.undo_manager.add_command(cmd)
                            ed["initial_val"] = cur
                        if getattr(self, '_active_editing_form_field', None) == ed.get("field"):
                            self._close_active_form_field_editor()

                    def _on_entry_focus_enter(ctrl, ed=entry_data):
                        ed["initial_val"] = ed.get("current_val", ed["field"].value)
                        self.selected_form_field = ed["field"]
                        if hasattr(self, 'pdf_view') and self.pdf_view:
                            self.pdf_view.queue_draw()
                        self._update_ui_state()

                    entry.connect("changed", _on_entry_changed)
                    entry.connect("activate", lambda w, ed=entry_data: self._close_active_form_field_editor())
                    focus_ctrl = Gtk.EventControllerFocus()
                    focus_ctrl.connect("enter", _on_entry_focus_enter)
                    focus_ctrl.connect("leave", _on_entry_focus_leave)
                    entry.add_controller(focus_ctrl)

                    key_ctrl = Gtk.EventControllerKey()
                    def _on_entry_key(ctrl, keyval, keycode, state):
                        if keyval == Gdk.KEY_Escape:
                            self._close_active_form_field_editor()
                            return True
                        return False
                    key_ctrl.connect("key-pressed", _on_entry_key)
                    entry.add_controller(key_ctrl)

                self.pdf_overlay.add_overlay(container)
                self._form_field_overlay_widgets[field.field_id] = entry_data

            elif ftype in ("checkbox", "radio"):
                chk = Gtk.CheckButton()
                chk.add_css_class("acroform-check")
                chk.set_active(bool(field.is_checked))
                if getattr(field, 'is_read_only', False):
                    chk.set_sensitive(False)
                chk.set_halign(Gtk.Align.START)
                chk.set_valign(Gtk.Align.START)
                chk.set_margin_start(wx)
                chk.set_margin_top(wy)
                chk.set_size_request(ww, wh)

                container = chk
                input_widget = chk

                entry_data = {
                    "field": field,
                    "container": container,
                    "widget": input_widget,
                    "initial_val": field.value,
                    "current_val": field.value,
                }

                def _on_check_toggled(btn, ed=entry_data):
                    if getattr(self, '_syncing_form_field', False):
                        return
                    new_val = btn.get_active()
                    old_val = ed["field"].value
                    ed["current_val"] = new_val
                    ed["initial_val"] = new_val
                    self._sync_form_field_value(ed["field"], new_val, record_undo=True, old_val_override=old_val)

                def _on_check_focus_enter(ctrl, ed=entry_data):
                    self.selected_form_field = ed["field"]
                    if hasattr(self, 'pdf_view') and self.pdf_view:
                        self.pdf_view.queue_draw()
                    self._update_ui_state()

                chk.connect("toggled", _on_check_toggled)
                focus_ctrl = Gtk.EventControllerFocus()
                focus_ctrl.connect("enter", _on_check_focus_enter)
                chk.add_controller(focus_ctrl)

                self.pdf_overlay.add_overlay(container)
                self._form_field_overlay_widgets[field.field_id] = entry_data

            elif ftype in ("combobox", "listbox", "choice"):
                raw_choices = getattr(field, 'choice_values', []) or []
                display_items = []
                export_items = []
                for item in raw_choices:
                    if isinstance(item, (list, tuple)):
                        exp = str(item[0]) if len(item) > 0 else ""
                        disp = str(item[1]) if len(item) > 1 else exp
                    else:
                        exp = str(item)
                        disp = str(item)
                    display_items.append(disp)
                    export_items.append(exp)

                if not display_items:
                    init_str = str(field.value if field.value is not None else "")
                    display_items = [init_str] if init_str else [""]
                    export_items = [init_str] if init_str else [""]

                dropdown = Gtk.DropDown.new_from_strings(display_items)
                dropdown.add_css_class("acroform-dropdown")
                if getattr(field, 'is_read_only', False):
                    dropdown.set_sensitive(False)

                val_str = str(field.value if field.value is not None else "")
                selected_idx = 0
                if val_str in export_items:
                    selected_idx = export_items.index(val_str)
                elif val_str in display_items:
                    selected_idx = display_items.index(val_str)
                dropdown.set_selected(selected_idx)

                dropdown.set_halign(Gtk.Align.START)
                dropdown.set_valign(Gtk.Align.START)
                dropdown.set_margin_start(wx)
                dropdown.set_margin_top(wy)
                dropdown.set_size_request(ww, wh)

                container = dropdown
                input_widget = dropdown

                entry_data = {
                    "field": field,
                    "container": container,
                    "widget": input_widget,
                    "initial_val": field.value,
                    "current_val": field.value,
                    "display_items": display_items,
                    "export_items": export_items,
                }

                def _on_dropdown_selected(dd, pspec, ed=entry_data):
                    if getattr(self, '_syncing_form_field', False):
                        return
                    sel_idx = dd.get_selected()
                    exp_items = ed.get("export_items", [])
                    if sel_idx < 0 or sel_idx >= len(exp_items):
                        return
                    new_val = exp_items[sel_idx]
                    old_val = ed["field"].value
                    if new_val == old_val:
                        return
                    ed["current_val"] = new_val
                    ed["initial_val"] = new_val
                    self._sync_form_field_value(ed["field"], new_val, record_undo=True, old_val_override=old_val)

                def _on_dropdown_focus_enter(ctrl, ed=entry_data):
                    self.selected_form_field = ed["field"]
                    if hasattr(self, 'pdf_view') and self.pdf_view:
                        self.pdf_view.queue_draw()
                    self._update_ui_state()

                dropdown.connect("notify::selected", _on_dropdown_selected)
                focus_ctrl = Gtk.EventControllerFocus()
                focus_ctrl.connect("enter", _on_dropdown_focus_enter)
                dropdown.add_controller(focus_ctrl)

                self.pdf_overlay.add_overlay(container)
                self._form_field_overlay_widgets[field.field_id] = entry_data

        if hasattr(self, "_update_form_field_overlay_interactivity"):
            self._update_form_field_overlay_interactivity()

    def _find_resize_handle_at_pos(self, drawn_x, drawn_y, selected_obj):
        """Find resize handle or rotation stalk handle at pos."""
        if not selected_obj or not selected_obj.bbox:
            return None
        if isinstance(selected_obj, AcroFormField) and getattr(self, '_active_editing_form_field', None) == selected_obj:
            return None
        
        x1, y1, x2, y2 = selected_obj.bbox
        if bool(getattr(self, 'word_selection_mode', False)) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
            w_bbox = self.get_selected_word_bbox()
            if isinstance(w_bbox, (tuple, list)) and len(w_bbox) == 4:
                x1, y1, x2, y2 = w_bbox
        obj_page = getattr(selected_obj, 'page_number', self.current_page_index)
        rect = None
        if hasattr(self, 'get_page_canvas_rect'):
            try:
                rect = self.get_page_canvas_rect(obj_page)
            except Exception:
                rect = None
        if isinstance(rect, (tuple, list)) and len(rect) == 4:
            page_offset_x, page_offset_y, _, _ = rect
        else:
            alloc_w = self.pdf_view.get_allocated_width() if hasattr(self, 'pdf_view') and hasattr(self.pdf_view, 'get_allocated_width') else getattr(self, 'current_pdf_page_width', 0)
            alloc_h = self.pdf_view.get_allocated_height() if hasattr(self, 'pdf_view') and hasattr(self.pdf_view, 'get_allocated_height') else getattr(self, 'current_pdf_page_height', 0)
            page_offset_x = max(0, (alloc_w - getattr(self, 'current_pdf_page_width', 0)) / 2)
            page_offset_y = max(0, (alloc_h - getattr(self, 'current_pdf_page_height', 0)) / 2)
        
        vis_x = (drawn_x - page_offset_x) / self.zoom_level
        vis_y = (drawn_y - page_offset_y) / self.zoom_level
        unrot_x, unrot_y = vis_x, vis_y
        try:
            coords = self._visual_to_unrotated_page_coords(vis_x, vis_y, page_index=obj_page)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                unrot_x, unrot_y = coords
        except Exception:
            pass

        padding = 3.0 / self.zoom_level
        rect_x = x1 - padding
        rect_y = y1 - padding
        rect_w = (x2 - x1) + (2 * padding)
        rect_h = (y2 - y1) + (2 * padding)

        rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
            cx = (selected_obj.bbox[0] + selected_obj.bbox[2]) / 2.0
            cy = (selected_obj.bbox[1] + selected_obj.bbox[3]) / 2.0
        else:
            cx = rect_x + rect_w / 2.0
            cy = rect_y + rect_h / 2.0

        if rot != 0.0:
            px, py = pdf_handler.rotate_point(unrot_x, unrot_y, cx, cy, -rot)
        else:
            px, py = unrot_x, unrot_y

        is_form_field = isinstance(selected_obj, AcroFormField) or hasattr(selected_obj, 'field_name')
        if not is_form_field:
            stalk_len = 22.0 / self.zoom_level
            rot_hx = rect_x + rect_w / 2.0
            rot_hy = rect_y - stalk_len
            rot_tolerance = 8.0 / self.zoom_level
            if math.hypot(px - rot_hx, py - rot_hy) <= rot_tolerance:
                return "rotate"
        
        if isinstance(selected_obj, EditableText):
            return None
        
        handle_size = 8.0 / self.zoom_level
        handle_tolerance = (6.0 if is_form_field else (4.0 if getattr(self, 'tool_mode', None) in ("pen", "highlighter") else 4.5)) / self.zoom_level
        
        handles = [
            ("nw", rect_x, rect_y),
            ("ne", rect_x + rect_w, rect_y),
            ("sw", rect_x, rect_y + rect_h),
            ("se", rect_x + rect_w, rect_y + rect_h),
            ("n", rect_x + rect_w / 2.0, rect_y),
            ("s", rect_x + rect_w / 2.0, rect_y + rect_h),
            ("w", rect_x, rect_y + rect_h / 2.0),
            ("e", rect_x + rect_w, rect_y + rect_h / 2.0),
        ]
        
        for handle_name, handle_x, handle_y in handles:
            if abs(px - handle_x) <= handle_tolerance and abs(py - handle_y) <= handle_tolerance:
                return handle_name
        
        return None

    def calculate_resize_geometry(
        self,
        start_bbox: Tuple[float, float, float, float],
        handle_name: str,
        delta_x: float,
        delta_y: float,
        shift_pressed: bool = False,
        min_size: float = 10.0
    ) -> Tuple[float, float, float, float]:
        """Calculate transformed bounding box for corner/edge handles with proportional vs free-form rules."""
        x1, y1, x2, y2 = float(start_bbox[0]), float(start_bbox[1]), float(start_bbox[2]), float(start_bbox[3])
        orig_w = max(1.0, x2 - x1)
        orig_h = max(1.0, y2 - y1)
        aspect = orig_w / orig_h

        is_corner = handle_name in ("nw", "ne", "sw", "se")
        is_edge = handle_name in ("n", "s", "w", "e")

        if not is_corner and not is_edge:
            return (x1, y1, x2, y2)

        # Corner handles preserve aspect ratio by default; Shift inverts to free-form
        # Edge handles resize free-form along axis by default; Shift inverts to uniform scaling
        proportional = (not shift_pressed) if is_corner else shift_pressed

        if is_corner:
            if not proportional:
                new_x1, new_y1, new_x2, new_y2 = x1, y1, x2, y2
                if "w" in handle_name:
                    new_x1 = x1 + delta_x
                if "e" in handle_name:
                    new_x2 = x2 + delta_x
                if "n" in handle_name:
                    new_y1 = y1 + delta_y
                if "s" in handle_name:
                    new_y2 = y2 + delta_y

                if new_x2 - new_x1 < min_size:
                    if "e" in handle_name:
                        new_x2 = new_x1 + min_size
                    else:
                        new_x1 = new_x2 - min_size
                if new_y2 - new_y1 < min_size:
                    if "s" in handle_name:
                        new_y2 = new_y1 + min_size
                    else:
                        new_y1 = new_y2 - min_size
                return (round(new_x1, 2), round(new_y1, 2), round(new_x2, 2), round(new_y2, 2))
            else:
                dir_x = 1.0 if "e" in handle_name else -1.0
                dir_y = 1.0 if "s" in handle_name else -1.0

                eff_dx = dir_x * delta_x
                eff_dy = dir_y * delta_y

                sx = (orig_w + eff_dx) / orig_w
                sy = (orig_h + eff_dy) / orig_h

                scale = sx if abs(sx - 1.0) >= abs(sy - 1.0) else sy

                scaled_w = orig_w * scale
                scaled_h = orig_h * scale

                if scaled_w < min_size:
                    scaled_w = min_size
                    scaled_h = scaled_w / aspect
                if scaled_h < min_size:
                    scaled_h = min_size
                    scaled_w = scaled_h * aspect

                if handle_name == "se":
                    new_x1 = x1
                    new_y1 = y1
                    new_x2 = x1 + scaled_w
                    new_y2 = y1 + scaled_h
                elif handle_name == "nw":
                    new_x2 = x2
                    new_y2 = y2
                    new_x1 = x2 - scaled_w
                    new_y1 = y2 - scaled_h
                elif handle_name == "ne":
                    new_x1 = x1
                    new_y2 = y2
                    new_x2 = x1 + scaled_w
                    new_y1 = y2 - scaled_h
                elif handle_name == "sw":
                    new_x2 = x2
                    new_y1 = y1
                    new_x1 = x2 - scaled_w
                    new_y2 = y1 + scaled_h

                return (round(new_x1, 2), round(new_y1, 2), round(new_x2, 2), round(new_y2, 2))

        else:
            if not proportional:
                new_x1, new_y1, new_x2, new_y2 = x1, y1, x2, y2
                if handle_name == "e":
                    new_x2 = max(x1 + min_size, x2 + delta_x)
                elif handle_name == "w":
                    new_x1 = min(x2 - min_size, x1 + delta_x)
                elif handle_name == "s":
                    new_y2 = max(y1 + min_size, y2 + delta_y)
                elif handle_name == "n":
                    new_y1 = min(y2 - min_size, y1 + delta_y)

                return (round(new_x1, 2), round(new_y1, 2), round(new_x2, 2), round(new_y2, 2))
            else:
                if handle_name in ("e", "w"):
                    eff_dx = delta_x if handle_name == "e" else -delta_x
                    scaled_w = max(min_size, orig_w + eff_dx)
                    scale = scaled_w / orig_w
                    scaled_h = max(min_size, orig_h * scale)
                    cy = (y1 + y2) / 2.0
                    new_y1 = cy - scaled_h / 2.0
                    new_y2 = cy + scaled_h / 2.0
                    if handle_name == "e":
                        new_x1 = x1
                        new_x2 = x1 + scaled_w
                    else:
                        new_x2 = x2
                        new_x1 = x2 - scaled_w
                else:
                    eff_dy = delta_y if handle_name == "s" else -delta_y
                    scaled_h = max(min_size, orig_h + eff_dy)
                    scale = scaled_h / orig_h
                    scaled_w = max(min_size, orig_w * scale)
                    cx = (x1 + x2) / 2.0
                    new_x1 = cx - scaled_w / 2.0
                    new_x2 = cx + scaled_w / 2.0
                    if handle_name == "s":
                        new_y1 = y1
                        new_y2 = y1 + scaled_h
                    else:
                        new_y2 = y2
                        new_y1 = y2 - scaled_h

                return (round(new_x1, 2), round(new_y1, 2), round(new_x2, 2), round(new_y2, 2))

    def calculate_image_import_geometry(
        self,
        intrinsic_w: int,
        intrinsic_h: int,
        click_pos: Tuple[float, float],
        page_bounds: Tuple[float, float],
        margin: float = 36.0,
        dpi_scale: float = 0.75
    ) -> Tuple[float, float, float, float]:
        """Calculate natural scale bounding box fitted within page margins preserving aspect ratio."""
        if intrinsic_w <= 0 or intrinsic_h <= 0:
            intrinsic_w, intrinsic_h = 200, 200

        aspect_ratio = float(intrinsic_w) / float(intrinsic_h)
        page_w, page_h = float(page_bounds[0]), float(page_bounds[1])

        effective_margin = min(margin, page_w * 0.1, page_h * 0.1)
        max_w = max(40.0, page_w - 2.0 * effective_margin)
        max_h = max(40.0, page_h - 2.0 * effective_margin)

        target_w = float(intrinsic_w) * dpi_scale
        target_h = float(intrinsic_h) * dpi_scale

        if target_w > max_w:
            target_w = max_w
            target_h = target_w / aspect_ratio
        if target_h > max_h:
            target_h = max_h
            target_w = target_h * aspect_ratio
        if target_w > max_w:
            target_w = max_w
            target_h = target_w / aspect_ratio

        click_x, click_y = float(click_pos[0]), float(click_pos[1])
        x0 = click_x
        y0 = click_y

        if x0 + target_w > page_w - effective_margin:
            x0 = (page_w - effective_margin) - target_w
        if x0 < effective_margin:
            x0 = effective_margin

        if y0 + target_h > page_h - effective_margin:
            y0 = (page_h - effective_margin) - target_h
        if y0 < effective_margin:
            y0 = effective_margin

        x1 = x0 + target_w
        y1 = y0 + target_h

        return (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))

    def _handle_add_image_click(self, page_x_unzoomed: float, page_y_unzoomed: float, page_index: Optional[int] = None):
        """Handle single-click image insertion at specified page position."""
        target_page = page_index if page_index is not None else self.current_page_index
        if not self.doc or not (0 <= target_page < len(self.doc)):
            return
        if getattr(self, '_image_dialog_open', False) is True:
            return
        self._image_dialog_open = True

        filter_img = Gtk.FileFilter(name=_("image_filter_label"))
        for mime in ["image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif", "image/tiff"]:
            filter_img.add_mime_type(mime)
        for pat in ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp", "*.gif", "*.tiff", "*.PNG", "*.JPG", "*.JPEG"]:
            filter_img.add_pattern(pat)

        def on_open_finish(file):
            self._image_dialog_open = False
            if not file:
                return
            image_path = file.get_path()
            try:
                with open(image_path, 'rb') as f:
                    image_bytes = f.read()
                if not image_bytes:
                    return

                img_w, img_h = pdf_handler.get_image_pixel_dimensions(image_bytes)

                page = self.doc[target_page]
                page_bounds = (float(page.rect.width), float(page.rect.height))

                rect = self.calculate_image_import_geometry(
                    img_w, img_h,
                    (page_x_unzoomed, page_y_unzoomed),
                    page_bounds
                )

                new_image_obj = EditableImage(
                    bbox=rect,
                    page_number=target_page,
                    xref=None,
                    image_bytes=image_bytes,
                    is_new=True
                )

                command = AddObjectCommand(self, new_image_obj)
                command.execute()
                self.undo_manager.add_command(command)

                self.selected_image = new_image_obj
                self.selected_text = None
                self.selected_shape = None
                self.selected_stroke = None
                self.selected_form_field = None
                self.selected_measurement = None

                self.tool_mode = "select"
                self.document_modified = True
                self._refresh_thumbnail(target_page)
                self.pdf_view.queue_draw()
                self._update_ui_state()
            except Exception as e:
                self._image_dialog_open = False
                show_error_dialog(self, _("image_add_error", e), _("image_error_title"))

        show_open_file_dialog(self, _("image_select_title"), filters=[filter_img], callback=on_open_finish)

    def _handle_add_image_action(self, page_x_unzoomed, page_y_unzoomed):
        """Alias for backward compatibility."""
        self._handle_add_image_click(page_x_unzoomed, page_y_unzoomed)

    def _update_text_format_controls(self, text_obj):
        """Update text format controls."""
        if not text_obj or self.font_scan_in_progress:
            if self.tool_mode == "add_text":
                return
            if not self.font_scan_in_progress and self.font_combo.get_sensitive():
                self.font_combo.handler_block_by_func(self.on_text_format_changed)
                self.font_combo.set_active(0)
                self.font_combo.handler_unblock_by_func(self.on_text_format_changed)

            self.font_size_spin.handler_block_by_func(self.on_text_format_changed)
            self.font_size_spin.set_value(11)
            self.font_size_spin.handler_unblock_by_func(self.on_text_format_changed)

            default_rgba = Gdk.RGBA(); default_rgba.parse("black")
            self.color_button.handler_block_by_func(self.on_text_format_changed)
            self.color_button.set_rgba(default_rgba)
            self.color_button.handler_unblock_by_func(self.on_text_format_changed)

            if self.bold_button:
                self.bold_button.handler_block_by_func(self.on_text_format_changed)
                self.bold_button.set_active(False)
                self.bold_button.handler_unblock_by_func(self.on_text_format_changed)
            if self.italic_button:
                self.italic_button.handler_block_by_func(self.on_text_format_changed)
                self.italic_button.set_active(False)
                self.italic_button.handler_unblock_by_func(self.on_text_format_changed)
            if hasattr(self, 'underline_button') and self.underline_button:
                self.underline_button.handler_block_by_func(self.on_text_format_changed)
                self.underline_button.set_active(False)
                self.underline_button.handler_unblock_by_func(self.on_text_format_changed)
            if hasattr(self, 'strikethrough_button') and self.strikethrough_button:
                self.strikethrough_button.handler_block_by_func(self.on_text_format_changed)
                self.strikethrough_button.set_active(False)
                self.strikethrough_button.handler_unblock_by_func(self.on_text_format_changed)
            if hasattr(self, 'link_button') and self.link_button:
                self.link_button.set_sensitive(False)
                self.link_button.set_tooltip_text(_("insert_link_tip"))
            align_btns = [getattr(self, 'align_left_button', None), getattr(self, 'align_center_button', None),
                          getattr(self, 'align_right_button', None), getattr(self, 'align_justify_button', None)]
            for b in align_btns:
                if b:
                    b.handler_block_by_func(self.on_text_format_changed)
            cur_align = getattr(self, '_last_alignment', 'left')
            target_btn = getattr(self, 'align_left_button', None)
            if cur_align == 'center' and getattr(self, 'align_center_button', None):
                target_btn = self.align_center_button
            elif cur_align == 'right' and getattr(self, 'align_right_button', None):
                target_btn = self.align_right_button
            elif cur_align == 'justify' and getattr(self, 'align_justify_button', None):
                target_btn = self.align_justify_button

            for b in align_btns:
                if b and b != target_btn and b.get_active():
                    b.set_active(False)
            if target_btn and not target_btn.get_active():
                target_btn.set_active(True)

            for b in align_btns:
                if b:
                    b.handler_unblock_by_func(self.on_text_format_changed)
            return

        self._ensure_font_combo_populated()
        signals_blocked = False
        align_btns = [getattr(self, 'align_left_button', None), getattr(self, 'align_center_button', None),
                      getattr(self, 'align_right_button', None), getattr(self, 'align_justify_button', None)]
        try:
            widgets_to_block = [self.font_combo, self.font_size_spin, self.color_button, self.bold_button,
                                self.italic_button, getattr(self, 'underline_button', None),
                                getattr(self, 'strikethrough_button', None)] + [b for b in align_btns if b]
            for widget in widgets_to_block:
                if widget: widget.handler_block_by_func(self.on_text_format_changed)
            signals_blocked = True

            active_font_index = -1
            target_family_base = text_obj.font_family_base 
            normalized_target_family_base = target_family_base.replace(" ", "").lower() if target_family_base else ""

            if target_family_base and utils.FONT_FAMILY_LIST_SORTED:
                model = self.font_combo.get_model()
                if model:
                    for i, row in enumerate(model):
                        combo_family_key = row[1]
                        normalized_combo_key = combo_family_key.replace(" ", "").lower()
                        if normalized_combo_key == normalized_target_family_base:
                            active_font_index = i
                            break
                
                if active_font_index == -1 and model:
                    for i, row in enumerate(model):
                        combo_family_key = row[1]
                        if target_family_base and combo_family_key and target_family_base.lower() in combo_family_key.lower():
                            active_font_index = i
                            break
                        elif target_family_base and combo_family_key and combo_family_key.lower() in target_family_base.lower():
                            active_font_index = i
                            break
                    if active_font_index == -1 and target_family_base:
                        # Register embedded/document font into combo store
                        self.font_store.append([target_family_base, target_family_base])
                        active_font_index = len(self.font_store) - 1
                    elif active_font_index == -1 and len(model) > 0:
                        active_font_index = 0


            if active_font_index != -1 and active_font_index < len(self.font_store):
                 self.font_combo.set_active(active_font_index)
            elif len(self.font_store) > 0:
                 self.font_combo.set_active(0)
            
            self.font_combo.set_tooltip_text(_("font_tip_original", text_obj.font_family_original))

            self.font_size_spin.set_value(text_obj.font_size)
            rgba = Gdk.RGBA(); rgba.red, rgba.green, rgba.blue = text_obj.color; rgba.alpha = 1.0
            self.color_button.set_rgba(rgba)
            if self.bold_button: self.bold_button.set_active(text_obj.is_bold)
            if self.italic_button: self.italic_button.set_active(text_obj.is_italic)
            if hasattr(self, 'underline_button') and self.underline_button:
                self.underline_button.set_active(getattr(text_obj, 'is_underline', False))
            if hasattr(self, 'strikethrough_button') and self.strikethrough_button:
                self.strikethrough_button.set_active(getattr(text_obj, 'is_strikethrough', False))
            if hasattr(self, 'link_button') and self.link_button:
                self.link_button.set_sensitive(True)
                eff_url = getattr(text_obj, 'link_url', None) or (text_obj.get_link_url() if hasattr(text_obj, 'get_link_url') else None)
                if eff_url:
                    self.link_button.set_tooltip_text(_("edit_link_tip", eff_url))
                else:
                    self.link_button.set_tooltip_text(_("insert_link_tip"))

            cur_align = getattr(text_obj, 'alignment', 'left')
            target_btn = getattr(self, 'align_left_button', None)
            if cur_align == 'center' and getattr(self, 'align_center_button', None):
                target_btn = self.align_center_button
            elif cur_align == 'right' and getattr(self, 'align_right_button', None):
                target_btn = self.align_right_button
            elif cur_align == 'justify' and getattr(self, 'align_justify_button', None):
                target_btn = self.align_justify_button

            for b in align_btns:
                if b and b != target_btn and b.get_active():
                    b.set_active(False)
            if target_btn and not target_btn.get_active():
                target_btn.set_active(True)

            self._last_font_family = target_family_base
            self._last_font_size = text_obj.font_size
            self._last_color = text_obj.color
            self._last_is_bold = text_obj.is_bold
            self._last_is_italic = text_obj.is_italic
            self._last_is_strikethrough = getattr(text_obj, 'is_strikethrough', False)
            self._last_alignment = cur_align

        finally:
            if signals_blocked:
                widgets_to_unblock = [self.font_combo, self.font_size_spin, self.color_button, self.bold_button,
                                      self.italic_button, getattr(self, 'underline_button', None),
                                      getattr(self, 'strikethrough_button', None)] + [b for b in align_btns if b]
                for widget in widgets_to_unblock:
                    if widget: widget.handler_unblock_by_func(self.on_text_format_changed)

    def _get_current_alignment(self):
        """Get the current alignment string."""
        if hasattr(self, 'align_center_button') and self.align_center_button and self.align_center_button.get_active():
            return 'center'
        if hasattr(self, 'align_right_button') and self.align_right_button and self.align_right_button.get_active():
            return 'right'
        if hasattr(self, 'align_justify_button') and self.align_justify_button and self.align_justify_button.get_active():
            return 'justify'
        return 'left'

    def _get_current_format_settings(self):
        """Get the current format settings."""
        font_family_display = "Sans"
        font_pdf_name = "helv"
        iter = self.font_combo.get_active_iter()
        if iter:
            font_family_display = self.font_store[iter][0]
            font_pdf_name = self.font_store[iter][1]

        font_size = self.font_size_spin.get_value()

        rgba = self.color_button.get_rgba()
        color = (rgba.red, rgba.green, rgba.blue)

        is_bold = self.bold_button.get_active() if self.bold_button else False
        is_italic = self.italic_button.get_active() if self.italic_button else False
        is_underline = self.underline_button.get_active() if hasattr(self, 'underline_button') and self.underline_button else False
        is_strikethrough = self.strikethrough_button.get_active() if hasattr(self, 'strikethrough_button') and self.strikethrough_button else False
        alignment = self._get_current_alignment()

        return font_family_display, font_pdf_name, font_size, color, is_bold, is_italic, is_underline, is_strikethrough, alignment

    def _update_shape_format_controls(self, shape_obj):
        """Update shape format controls."""
        try:
            self.shape_fill_button.handler_block_by_func(self.on_shape_format_changed)
            self.shape_stroke_button.handler_block_by_func(self.on_shape_format_changed)
            self.shape_stroke_width_spin.handler_block_by_func(self.on_shape_format_changed)

            if not shape_obj:
                fill_rgba = Gdk.RGBA()
                fill_rgba.parse("white")
                self.shape_fill_button.set_rgba(fill_rgba)

                stroke_rgba = Gdk.RGBA()
                stroke_rgba.parse("black")
                self.shape_stroke_button.set_rgba(stroke_rgba)

                self.shape_stroke_width_spin.set_value(2.0)
            else:
                fill_r, fill_g, fill_b = shape_obj.fill_color
                fill_rgba = Gdk.RGBA()
                fill_rgba.red, fill_rgba.green, fill_rgba.blue = fill_r, fill_g, fill_b
                fill_rgba.alpha = 1.0
                self.shape_fill_button.set_rgba(fill_rgba)

                stroke_r, stroke_g, stroke_b = shape_obj.stroke_color
                stroke_rgba = Gdk.RGBA()
                stroke_rgba.red, stroke_rgba.green, stroke_rgba.blue = stroke_r, stroke_g, stroke_b
                stroke_rgba.alpha = 1.0
                self.shape_stroke_button.set_rgba(stroke_rgba)

                self.shape_stroke_width_spin.set_value(shape_obj.stroke_width)

        finally:
            self.shape_fill_button.handler_unblock_by_func(self.on_shape_format_changed)
            self.shape_stroke_button.handler_unblock_by_func(self.on_shape_format_changed)
            self.shape_stroke_width_spin.handler_unblock_by_func(self.on_shape_format_changed)

    def _update_stroke_format_controls(self, stroke_obj):
        """Update stroke format controls."""
        try:
            self.stroke_color_button.handler_block_by_func(self.on_stroke_format_changed)
            self.stroke_width_spin.handler_block_by_func(self.on_stroke_format_changed)

            if not stroke_obj:
                if self.tool_mode == "highlighter":
                    r, g, b = self.highlighter_color
                    w = self.highlighter_width
                else:
                    r, g, b = self.pen_color
                    w = self.pen_width
            else:
                r, g, b = stroke_obj.stroke_color
                w = stroke_obj.stroke_width

            rgba = Gdk.RGBA()
            rgba.red, rgba.green, rgba.blue, rgba.alpha = r, g, b, 1.0
            self.stroke_color_button.set_rgba(rgba)
            self.stroke_width_spin.set_value(w)
        finally:
            self.stroke_color_button.handler_unblock_by_func(self.on_stroke_format_changed)
            self.stroke_width_spin.handler_unblock_by_func(self.on_stroke_format_changed)

    def _update_rotation_controls(self, selected_obj):
        """Sync rotation spin button and reset button with selected object's rotation angle."""
        if not hasattr(self, 'rotation_spin'):
            return

        self.rotation_spin.handler_block_by_func(self.on_object_rotation_spin_changed)
        try:
            if selected_obj:
                rot = round(getattr(selected_obj, 'rotation', 0.0)) % 360
                self.rotation_spin.set_value(rot)
                if hasattr(self, 'rotate_obj_reset_button'):
                    self.rotate_obj_reset_button.set_sensitive(rot != 0)
                if hasattr(self, 'rotate_obj_cw_button'):
                    self.rotate_obj_cw_button.set_sensitive(True)
                if hasattr(self, 'rotate_obj_ccw_button'):
                    self.rotate_obj_ccw_button.set_sensitive(True)
            else:
                self.rotation_spin.set_value(0)
                if hasattr(self, 'rotate_obj_reset_button'):
                    self.rotate_obj_reset_button.set_sensitive(False)
                if hasattr(self, 'rotate_obj_cw_button'):
                    self.rotate_obj_cw_button.set_sensitive(False)
                if hasattr(self, 'rotate_obj_ccw_button'):
                    self.rotate_obj_ccw_button.set_sensitive(False)
        finally:
            self.rotation_spin.handler_unblock_by_func(self.on_object_rotation_spin_changed)

    def on_rotate_object_cw_clicked(self, button=None):
        """Rotate the currently selected object 90 degrees clockwise."""
        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        if not selected_obj:
            return
        if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
            selected_obj = self._isolate_selected_word_span()

        old_rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        new_rot = (old_rot + 90.0) % 360.0

        command = RotateObjectCommand(self, selected_obj, old_rot, new_rot)
        command.execute()
        self.undo_manager.add_command(command)
        if isinstance(selected_obj, EditableText):
            self.selected_text = selected_obj
            self.pending_format_change_obj = selected_obj
            self.before_format_change_state = snapshot_object_state(selected_obj)
            self._update_text_format_controls(selected_obj)

    def on_rotate_object_ccw_clicked(self, button=None):
        """Rotate the currently selected object 90 degrees counterclockwise."""
        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        if not selected_obj:
            return
        if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
            selected_obj = self._isolate_selected_word_span()

        old_rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        new_rot = (old_rot - 90.0) % 360.0

        command = RotateObjectCommand(self, selected_obj, old_rot, new_rot)
        command.execute()
        self.undo_manager.add_command(command)
        if isinstance(selected_obj, EditableText):
            self.selected_text = selected_obj
            self.pending_format_change_obj = selected_obj
            self.before_format_change_state = snapshot_object_state(selected_obj)
            self._update_text_format_controls(selected_obj)

    def on_rotate_object_reset_clicked(self, button=None):
        """Reset rotation of selected object to 0 degrees."""
        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        if not selected_obj:
            return
        if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
            selected_obj = self._isolate_selected_word_span()

        old_rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        if old_rot == 0.0:
            return

        command = RotateObjectCommand(self, selected_obj, old_rot, 0.0)
        command.execute()
        self.undo_manager.add_command(command)
        if isinstance(selected_obj, EditableText):
            self.selected_text = selected_obj
            self.pending_format_change_obj = selected_obj
            self.before_format_change_state = snapshot_object_state(selected_obj)
            self._update_text_format_controls(selected_obj)

    def on_object_rotation_spin_changed(self, spin_button):
        """Handle numeric spin button changes for object rotation."""
        selected_obj = self.selected_text or self.selected_image or self.selected_shape or getattr(self, 'selected_stroke', None)
        if not selected_obj:
            return
        if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
            selected_obj = self._isolate_selected_word_span()

        old_rot = getattr(selected_obj, 'rotation', 0.0) % 360.0
        new_rot = float(spin_button.get_value()) % 360.0

        if abs(old_rot - new_rot) < 0.1:
            return

        command = RotateObjectCommand(self, selected_obj, old_rot, new_rot)
        command.execute()
        self.undo_manager.add_command(command)
        if isinstance(selected_obj, EditableText):
            self.selected_text = selected_obj
            self.pending_format_change_obj = selected_obj
            self.before_format_change_state = snapshot_object_state(selected_obj)
            self._update_text_format_controls(selected_obj)

    def _apply_inline_editor_style(self):
        """Apply dynamic typography styling and Adwaita theme colors to the inline text editor."""
        if not getattr(self, 'inline_editor_widget', None) or not getattr(self, 'inline_editor_tv', None):
            return
        text_obj = getattr(self, 'inline_editor_text_obj', None)
        if not text_obj:
            return

        if hasattr(self, '_inline_editor_css_provider') and self._inline_editor_css_provider:
            try:
                self.inline_editor_tv.get_style_context().remove_provider(self._inline_editor_css_provider)
                self.inline_editor_widget.get_style_context().remove_provider(self._inline_editor_css_provider)
            except Exception:
                pass
            self._inline_editor_css_provider = None

        family = getattr(text_obj, 'font_family_base', 'Liberation Sans') or 'Liberation Sans'
        scaled_font_size = max(9, int(round(text_obj.font_size * self.zoom_level)))
        weight_css = "bold" if getattr(text_obj, 'is_bold', False) else "normal"
        style_css = "italic" if getattr(text_obj, 'is_italic', False) else "normal"

        col = getattr(text_obj, 'color', (0, 0, 0))
        if isinstance(col, (tuple, list)) and len(col) >= 3:
            r = max(0, min(255, int(round(col[0] * 255))))
            g = max(0, min(255, int(round(col[1] * 255))))
            b = max(0, min(255, int(round(col[2] * 255))))
        else:
            r, g, b = 0, 0, 0
        color_css = f"rgb({r}, {g}, {b})"

        css_str = f"""
            .inline-editor-tv {{
                min-height: 0px;
                min-width: 0px;
                margin: 0px;
                padding: 1px 3px;
                background-color: #ffffff;
                border: none;
                box-shadow: none;
                font-family: '{family}', 'Liberation Sans', 'DejaVu Sans', sans-serif;
                font-size: {scaled_font_size}px;
                font-weight: {weight_css};
                font-style: {style_css};
                color: {color_css};
            }}
            .inline-editor-frame {{
                min-height: 0px;
                min-width: 0px;
                padding: 0px;
                margin: 0px;
                border: 1.5px solid @accent_color;
                border-radius: 4px;
                background-color: #ffffff;
                box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
            }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css_str.encode('utf-8'))
        self._inline_editor_css_provider = provider

        self.inline_editor_tv.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self.inline_editor_widget.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def _on_inline_editor_text_changed(self, buffer):
        """Dynamically expand inline editor width and height as text is typed."""
        if not getattr(self, 'inline_editor_widget', None) or not getattr(self, 'inline_editor_tv', None):
            return
        text_obj = getattr(self, 'inline_editor_text_obj', None)
        if not text_obj:
            return

        buf = self.inline_editor_tv.get_buffer()
        current_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

        try:
            pango_ctx = self.inline_editor_tv.get_pango_context()
            layout = Pango.Layout(pango_ctx)
            family = getattr(text_obj, 'font_family_base', 'Liberation Sans') or 'Liberation Sans'
            font_desc = Pango.FontDescription.from_string(family)
            if getattr(text_obj, 'is_bold', False):
                font_desc.set_weight(Pango.Weight.BOLD)
            if getattr(text_obj, 'is_italic', False):
                font_desc.set_style(Pango.Style.ITALIC)
            scaled_font_size = max(9.0, text_obj.font_size * self.zoom_level)
            font_desc.set_absolute_size(int(scaled_font_size * Pango.SCALE))
            layout.set_font_description(font_desc)
            layout.set_text(current_text or " ", -1)
            pw, ph = layout.get_size()
            calc_w = int(pw / Pango.SCALE) + 20
            calc_h = int(ph / Pango.SCALE) + 6
        except Exception:
            calc_w = getattr(self, '_inline_editor_base_w', 60)
            calc_h = getattr(self, '_inline_editor_base_h', 24)

        base_w = getattr(self, '_inline_editor_base_w', 60)
        base_h = getattr(self, '_inline_editor_base_h', 24)

        new_w = max(base_w, calc_w)
        new_h = max(base_h, calc_h)

        da_w = max(self.pdf_view.get_allocated_width(), self.current_pdf_page_width)
        max_w = max(base_w, int(da_w - getattr(self, '_inline_editor_base_x', 0) - 20))
        clamped_w = min(new_w, max_w)

        if calc_w > max_w:
            self.inline_editor_tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        else:
            self.inline_editor_tv.set_wrap_mode(Gtk.WrapMode.NONE)

        self.inline_editor_widget.set_size_request(clamped_w, new_h)

    def _show_inline_editor(self, text_obj, click_x=None, click_y=None, target_rect=None):
        """Show inline editor overlay exactly positioned over target text."""
        self._hide_inline_editor()
        if not text_obj or not self.doc or not (0 <= self.current_page_index < pdf_handler.get_page_count(self.doc)):
            return

        self.inline_editor_text_obj = text_obj
        self._inline_editor_target_rect = target_rect
        self._inline_editor_initial_text = text_obj.text

        page_offset_x, page_offset_y, _, _ = self.get_page_canvas_rect(self.current_page_index)

        target_box = target_rect or getattr(text_obj, 'bbox', None)
        if target_box:
            page = self.doc[self.current_page_index]
            vis_rect = (fitz.Rect(target_box) * page.rotation_matrix).normalize()
            ed_x = int(page_offset_x + vis_rect.x0 * self.zoom_level) - 2
            ed_y = int(page_offset_y + vis_rect.y0 * self.zoom_level) - 2
            scaled_font = max(9.0, text_obj.font_size * self.zoom_level)
            ed_w = max(60, int(vis_rect.width * self.zoom_level) + 20)
            ed_h = max(int(scaled_font * 1.3) + 6, int(vis_rect.height * self.zoom_level) + 6)
        elif click_x is not None and click_y is not None:
            ed_x = int(click_x) - 2
            ed_y = int(click_y) - 2
            scaled_font = max(9.0, text_obj.font_size * self.zoom_level)
            ed_w = 140
            ed_h = max(int(scaled_font * 1.3) + 6, 28)
        else:
            ed_x = int(page_offset_x + 10)
            ed_y = int(page_offset_y + 10)
            scaled_font = max(9.0, text_obj.font_size * self.zoom_level)
            ed_w = 140
            ed_h = 28

        self._inline_editor_base_x = ed_x
        self._inline_editor_base_y = ed_y
        self._inline_editor_base_w = ed_w
        self._inline_editor_base_h = ed_h

        frame = Gtk.Frame()
        frame.add_css_class("inline-editor-frame")
        frame.set_halign(Gtk.Align.START)
        frame.set_valign(Gtk.Align.START)
        frame.set_margin_start(ed_x)
        frame.set_margin_top(ed_y)
        frame.set_size_request(ed_w, ed_h)

        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.NONE)
        tv.set_left_margin(3)
        tv.set_right_margin(3)
        tv.set_top_margin(1)
        tv.set_bottom_margin(1)
        align_val = getattr(text_obj, 'alignment', 'left')
        if align_val == 'center':
            tv.set_justification(Gtk.Justification.CENTER)
        elif align_val == 'right':
            tv.set_justification(Gtk.Justification.RIGHT)
        elif align_val == 'justify':
            tv.set_justification(Gtk.Justification.FILL)
        else:
            tv.set_justification(Gtk.Justification.LEFT)

        buf = tv.get_buffer()
        buf.set_enable_undo(False)
        buf.set_text(text_obj.text or "")
        buf.set_enable_undo(True)
        buf.select_range(buf.get_start_iter(), buf.get_end_iter())
        buf.connect("changed", self._on_inline_editor_text_changed)

        tv.add_css_class("inline-editor-tv")
        frame.set_child(tv)

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", self._on_inline_editor_focus_leave)
        tv.add_controller(focus_ctrl)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_inline_editor_key)
        tv.add_controller(key_ctrl)

        self.pdf_overlay.add_overlay(frame)
        self.inline_editor_widget = frame
        self.inline_editor_tv = tv
        self._apply_inline_editor_style()
        self._on_inline_editor_text_changed(buf)

        GLib.idle_add(tv.grab_focus)
        self.pdf_view.queue_draw()

    def _cancel_inline_editor(self):
        """Cancel inline editing and revert text changes."""
        if not getattr(self, 'inline_editor_widget', None):
            return
        text_obj = getattr(self, 'inline_editor_text_obj', None)
        if text_obj:
            if getattr(text_obj, 'is_new', False):
                if text_obj in getattr(self, 'editable_texts', []):
                    self.editable_texts.remove(text_obj)
                if getattr(text_obj, 'linked_patch', None):
                    text_obj.linked_patch.linked_text = None
                self.selected_text = None
            else:
                init_text = getattr(self, '_inline_editor_initial_text', None)
                if init_text is not None:
                    text_obj.text = init_text
        self._hide_inline_editor()
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(self.current_page_index)
        self.drag_threshold_passed = False
        self._update_ui_state()
        self.pdf_view.queue_draw()

    def _hide_inline_editor(self):
        """Hide inline editor and clean up references."""
        if hasattr(self, '_inline_editor_css_provider') and self._inline_editor_css_provider:
            try:
                if self.inline_editor_tv:
                    self.inline_editor_tv.get_style_context().remove_provider(self._inline_editor_css_provider)
                if self.inline_editor_widget:
                    self.inline_editor_widget.get_style_context().remove_provider(self._inline_editor_css_provider)
            except Exception:
                pass
            self._inline_editor_css_provider = None

        if self.inline_editor_widget:
            if hasattr(self, 'pdf_overlay') and self.pdf_overlay:
                try:
                    self.pdf_overlay.remove_overlay(self.inline_editor_widget)
                except Exception:
                    pass
            self.inline_editor_widget = None
            self.inline_editor_tv = None
            self.inline_editor_text_obj = None
            self._inline_editor_target_rect = None
            self._inline_editor_initial_text = None

    def _commit_inline_edit(self):
        """Commit inline edit."""
        if not getattr(self, 'inline_editor_tv', None) or not getattr(self, 'inline_editor_text_obj', None) or not getattr(self, 'inline_editor_widget', None):
            self._hide_inline_editor()
            return

        text_obj_to_apply = self.inline_editor_text_obj
        old_properties = snapshot_object_state(text_obj_to_apply)

        buf = self.inline_editor_tv.get_buffer()
        new_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

        self._hide_inline_editor()

        def _calc_bbox(obj, text):
            """Calculate updated bounding box after text modification."""
            x1, y1 = obj.x, obj.y
            _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
            _cr = cairo.Context(_surf)
            layout = PangoCairo.create_layout(_cr)
            family = getattr(obj, 'font_family_base', 'Liberation Sans') or 'Liberation Sans'
            desc = Pango.FontDescription.from_string(family)
            if getattr(obj, 'is_bold', False): desc.set_weight(Pango.Weight.BOLD)
            if getattr(obj, 'is_italic', False): desc.set_style(Pango.Style.ITALIC)
            desc.set_absolute_size(int(obj.font_size * Pango.SCALE))
            layout.set_font_description(desc)
            layout.set_text(text or "A", -1)
            pw, ph = layout.get_size()
            calc_w = pw / Pango.SCALE
            if getattr(obj, 'bbox', None):
                old_w = obj.bbox[2] - obj.bbox[0]
                final_w = max(calc_w, old_w) if getattr(obj, 'alignment', 'left') != 'left' else calc_w
            else:
                final_w = calc_w
            return (x1, y1, x1 + final_w, y1 + ph / Pango.SCALE)

        if text_obj_to_apply.is_new:
            if not new_text.strip():
                if text_obj_to_apply in getattr(self, 'editable_texts', []):
                    self.editable_texts.remove(text_obj_to_apply)
                if getattr(text_obj_to_apply, 'linked_patch', None):
                    text_obj_to_apply.linked_patch.linked_text = None
                self.selected_text = None
                self._update_ui_state()
                self.pdf_view.queue_draw()
                return

            text_obj_to_apply.text = new_text
            text_obj_to_apply.is_baked = True
            text_obj_to_apply.bbox = _calc_bbox(text_obj_to_apply, new_text)
            command = AddObjectCommand(self, text_obj_to_apply)
            command.execute()
            self.undo_manager.add_command(command)
            self._refresh_thumbnail(self.current_page_index)
        else:
            if not new_text.strip():
                if getattr(text_obj_to_apply, 'linked_patch', None):
                    text_obj_to_apply.linked_patch.linked_text = None
                command = DeleteObjectCommand(self, text_obj_to_apply)
                command.execute()
                self.undo_manager.add_command(command)
                self.selected_text = None
                self._update_ui_state()
                self.pdf_view.queue_draw()
                return

            new_properties = snapshot_object_state(text_obj_to_apply)
            new_properties['text'] = new_text
            if not getattr(text_obj_to_apply, 'original_bbox', None):
                text_obj_to_apply.original_bbox = old_properties.get('original_bbox', old_properties.get('bbox'))
            new_properties['original_bbox'] = text_obj_to_apply.original_bbox
            if old_properties['text'] != new_text:
                x1, y1 = new_properties['bbox'][0], new_properties['bbox'][1]
                _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
                _cr = cairo.Context(_surf)
                layout = PangoCairo.create_layout(_cr)
                family = new_properties.get('font_family_base', 'Liberation Sans') or 'Liberation Sans'
                desc = Pango.FontDescription.from_string(family)
                if new_properties.get('is_bold'): desc.set_weight(Pango.Weight.BOLD)
                if new_properties.get('is_italic'): desc.set_style(Pango.Style.ITALIC)
                desc.set_absolute_size(int(new_properties['font_size'] * Pango.SCALE))
                layout.set_font_description(desc)
                layout.set_text(new_text or "A", -1)
                pw, ph = layout.get_size()
                calc_w = pw / Pango.SCALE
                if old_properties.get('bbox'):
                    old_w = old_properties['bbox'][2] - old_properties['bbox'][0]
                    final_w = max(calc_w, old_w) if new_properties.get('alignment', 'left') != 'left' else calc_w
                else:
                    final_w = calc_w
                new_properties['bbox'] = (x1, y1, x1 + final_w, y1 + ph / Pango.SCALE)
                command = EditObjectCommand(self, text_obj_to_apply, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self._refresh_thumbnail(self.current_page_index)

        if text_obj_to_apply:
            self.selected_text = text_obj_to_apply
            self.pending_format_change_obj = text_obj_to_apply
            self.before_format_change_state = snapshot_object_state(text_obj_to_apply)
            self._update_text_format_controls(text_obj_to_apply)

        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(self.current_page_index)
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(self.current_page_index)
        self.drag_threshold_passed = False
        self._update_ui_state()
        self.pdf_view.queue_draw()

    def _on_inline_editor_focus_leave(self, controller):
        """Commit active inline text edit when editor widget loses focus."""
        if not getattr(self, 'inline_editor_widget', None):
            return
        focus_widget = self.get_focus()
        if focus_widget:
            curr = focus_widget
            while curr:
                if curr == getattr(self, 'main_toolbar', None):
                    return
                curr = curr.get_parent()

        GLib.idle_add(self._commit_inline_edit)

    def _on_inline_editor_key(self, controller, keyval, keycode, state):
        """Handle keyboard shortcuts inside inline editor: Escape, Enter, Ctrl+Enter, Shift+Enter, Ctrl+Z, Ctrl+Y."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if ctrl and not shift and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
                buf = self.inline_editor_tv.get_buffer()
                if hasattr(buf, 'can_undo') and buf.can_undo():
                    buf.undo()
                elif hasattr(buf, 'undo'):
                    buf.undo()
            return True

        if (ctrl and not shift and keyval in (Gdk.KEY_y, Gdk.KEY_Y)) or (ctrl and shift and keyval in (Gdk.KEY_z, Gdk.KEY_Z)):
            if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
                buf = self.inline_editor_tv.get_buffer()
                if hasattr(buf, 'can_redo') and buf.can_redo():
                    buf.redo()
                elif hasattr(buf, 'redo'):
                    buf.redo()
            return True

        if keyval == Gdk.KEY_Escape:
            self._cancel_inline_editor()
            return True

        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if shift:
                if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
                    buf = self.inline_editor_tv.get_buffer()
                    buf.insert_at_cursor("\n")
                return True
            elif ctrl:
                self._commit_inline_edit()
                return True
            else:
                if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
                    buf = self.inline_editor_tv.get_buffer()
                    current_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
                    if "\n" not in current_text:
                        self._commit_inline_edit()
                        return True
                    else:
                        return False

        return False

    def hide_text_editor(self):
        """Dismiss the inline text editing widget."""
        self._hide_inline_editor()

    def _apply_and_hide_editor(self, force_apply=False):
        """Commit pending changes and dismiss inline text editor."""
        self._commit_inline_edit()

    def check_unsaved_changes(self, session: Optional[DocumentSession] = None):
        """Prompt user to save pending modifications. Returns True if cancelled."""
        if getattr(self, 'is_saving', False) is True:
            self.wait_for_save()
        target_session = session or getattr(self, '_active_session', None)
        if not target_session or not target_session.is_modified:
            return False

        if target_session != self._active_session:
            self.set_active_session(target_session)

        response = show_save_changes_dialog(self)
        
        if response == Gtk.ResponseType.ACCEPT:
            if target_session.pdf_path:
                self.save_document(target_session.pdf_path, incremental=False, background=False)
                return False
            else:
                self.on_save_as(None, None)
                return target_session.is_modified
        elif response == Gtk.ResponseType.REJECT:
            print(_("dbg_discarding_unsaved"))
            target_session.is_modified = False
            return False
        else:
            return True

        return False

    def on_drop(self, drop_target, value, x, y):
        """Handle drag-and-drop of PDF documents into the main viewer."""
        if isinstance(value, Gio.File):
            filepath = value.get_path()
            if filepath and filepath.lower().endswith('.pdf'):
                if self.doc:
                    self._offer_merge_or_open(filepath)
                else:
                    GLib.idle_add(self.load_document, filepath)
                return True
        return False

    def _offer_merge_or_open(self, filepath):
        """Prompt whether to append dropped PDF pages or open as a separate document."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=_("import_pdf_title"),
            secondary_text=_("import_pdf_confirm", os.path.basename(filepath))
        )
        
        dialog.add_buttons(
            _("btn_cancel"), Gtk.ResponseType.CANCEL,
            _("btn_confirm"), Gtk.ResponseType.ACCEPT
        )
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        
        def on_response(d, resp_id):
            d.destroy()
            if resp_id == Gtk.ResponseType.ACCEPT:
                self._merge_pdf_at_position(filepath, self.current_page_index + 1)
            elif resp_id == Gtk.ResponseType.CANCEL:
                GLib.idle_add(self.load_document, filepath, 0, True)
        
        dialog.connect("response", on_response)
        dialog.present()

    def _merge_pdf_at_position(self, source_pdf_path, insert_position):
        """Insert pages from another PDF file into the active document at insert_position."""
        # Stash current page objects into cache before any page insertion/shifting
        self._stash_page_objects(self.current_page_index)

        success, message, pages_inserted = pdf_handler.merge_pdf_pages(
            self.doc, source_pdf_path, insert_position
        )
        
        if success:
            if hasattr(self, '_page_objects_cache') and self._page_objects_cache:
                new_cache = {}
                for p, objs in self._page_objects_cache.items():
                    if p >= insert_position:
                        new_cache[p + 1] = objs
                        for coll_key in ('texts', 'images', 'shapes', 'strokes', 'form_fields'):
                            for obj in objs.get(coll_key, []):
                                if hasattr(obj, 'page_number') and obj.page_number is not None:
                                    obj.page_number += 1
                    else:
                        new_cache[p] = objs
                self._page_objects_cache.clear()
                self._page_objects_cache.update(new_cache)

            self.document_modified = True
            self.status_label.set_text(message)
            self._invalidate_continuous_layout()
            self._load_page(insert_position, reload_objects=True)
            self._load_thumbnails(target_page=insert_position)
            self._update_ui_state()
        else:
            show_error_dialog(self, message, _("err_merge_title"))

    def on_thumbnail_drop(self, drop_target, value, x, y):
        """Handle drag-and-drop of a PDF onto the thumbnail sidebar to append pages."""
        if isinstance(value, Gio.File):
            filepath = value.get_path()
            if filepath and filepath.lower().endswith('.pdf'):
                insert_position = pdf_handler.get_page_count(self.doc)
                self._merge_pdf_at_position(filepath, insert_position)
                return True
        
        return False

    def on_open_clicked(self, button=None):
        """Prompt open file dialog to load an existing PDF into active or new tab."""
        filter_pdf = Gtk.FileFilter(name=_("filter_pdf"))
        filter_pdf.add_pattern("*.pdf")
        filter_pdf.add_mime_type("application/pdf")
        filter_wspdf = Gtk.FileFilter(name=_("filter_wspdf"))
        filter_wspdf.add_pattern("*.wspdf")
        filter_all = Gtk.FileFilter(name=_("filter_all"))
        filter_all.add_pattern("*")

        def on_open_finish(file):
            if file:
                GLib.idle_add(self.load_document, file.get_path())

        show_open_file_dialog(
            self,
            _("open_pdf_title"),
            filters=[filter_pdf, filter_wspdf, filter_all],
            default_filter=filter_pdf,
            callback=on_open_finish
        )

    def on_save_clicked(self, button):
        """Save active document to current path or prompt Save As if untitled."""
        if not self.doc or (getattr(self, 'is_saving', False) is True):
            return

        redacts = getattr(self._active_session, 'redaction_marks', {}) if self._active_session else {}
        total_marks = sum(len(marks) for marks in redacts.values())
        if total_marks > 0:
            confirmed = show_confirm_dialog(
                self,
                _("redaction_save_prompt_msg", total_marks),
                _("redaction_save_prompt_title"),
                destructive=True
            )
            if not confirmed:
                return
            self.apply_all_redactions(prompt_warning=False)

        if self.current_file_path:
            self.commit_pending_format_change()
            use_incr = (total_marks == 0) and getattr(self, "allow_incremental_save", True)
            self.save_document(self.current_file_path, incremental=use_incr)
        else:
            self.on_save_as(None, None)

    def on_save_as(self, action=None, param=None):
        """Prompt save file dialog to write PDF to a new destination."""
        if getattr(self, 'is_saving', False) is True:
            return
        self.commit_pending_format_change()
        if not self.doc: return

        redacts = getattr(self._active_session, 'redaction_marks', {}) if self._active_session else {}
        total_marks = sum(len(marks) for marks in redacts.values())
        if total_marks > 0:
            confirmed = show_confirm_dialog(
                self,
                _("redaction_save_prompt_msg", total_marks),
                _("redaction_save_prompt_title"),
                destructive=True
            )
            if not confirmed:
                return
            self.apply_all_redactions(prompt_warning=False)

        is_vault = bool(getattr(self._active_session, 'is_vault', False) or getattr(self.doc, '_is_vault', False))
        if is_vault:
            initial_name = os.path.basename(self.current_file_path or "vault_document.wspdf")
            if not initial_name.lower().endswith('.wspdf'):
                initial_name = os.path.splitext(initial_name)[0] + '.wspdf'
            filter_wspdf = Gtk.FileFilter(name=_("filter_wspdf"))
            filter_wspdf.add_pattern("*.wspdf")
            filters = [filter_wspdf]
            default_filter = filter_wspdf
        else:
            initial_name = os.path.basename(self.current_file_path or "edited_document.pdf")
            filter_pdf = Gtk.FileFilter(name=_("filter_pdf"))
            filter_pdf.add_pattern("*.pdf")
            filter_pdf.add_mime_type("application/pdf")
            filters = [filter_pdf]
            default_filter = filter_pdf

        def on_save_finish(file):
            if file:
                path = file.get_path()
                if is_vault:
                    if not path.lower().endswith('.wspdf'): path += '.wspdf'
                else:
                    if not path.lower().endswith('.pdf'): path += '.pdf'
                self.save_document(path, incremental=False)

        show_save_file_dialog(
            self,
            _("save_as_title"),
            initial_name=initial_name,
            filters=filters,
            default_filter=default_filter,
            callback=on_save_finish
        )

    def on_compress_document_clicked(self, _action=None, _param=None):
        """Show Compression dialog to compress the active PDF."""
        if not self.doc:
            return
        from .compress_dialog import CompressionDialog
        if getattr(self, "_compress_dialog", None) is not None:
            self._compress_dialog.present()
            return

        try:
            pdf_bytes = self.doc.tobytes()
        except Exception:
            if self.current_file_path and os.path.exists(self.current_file_path):
                with open(self.current_file_path, "rb") as f:
                    pdf_bytes = f.read()
            else:
                return

        def _on_saved(saved_path: str):
            self._compress_dialog = None
            if saved_path and os.path.exists(saved_path):
                GLib.idle_add(self.load_document, saved_path)

        self._compress_dialog = CompressionDialog(
            parent_window=self,
            pdf_bytes=pdf_bytes,
            initial_filename=self.current_file_path or "document.pdf",
            on_saved_callback=_on_saved,
        )
        self._compress_dialog.connect("close-request", self._on_compress_dialog_closed)
        self._compress_dialog.present()

    def _on_compress_dialog_closed(self, dialog):
        self._compress_dialog = None
        return False

    def on_protect_document_clicked(self, _action=None, _param=None):
        """Show Protect Document dialog."""
        if not self.doc:
            return
        from .protect_dialog import ProtectDocumentDialog
        if getattr(self, "_protect_dialog", None) is not None:
            self._protect_dialog.present()
            return
        self._protect_dialog = ProtectDocumentDialog(
            parent_window=self,
            on_protect_callback=self._execute_protect_from_dialog
        )
        self._protect_dialog.connect("close-request", self._on_protect_dialog_closed)
        self._protect_dialog.present()

    def _on_protect_dialog_closed(self, dialog):
        self._protect_dialog = None
        return False

    def _execute_protect_from_dialog(self, mode: str, settings: Dict[str, Any]):
        """Apply encryption/vault protection settings and prompt Save As."""
        if not self.doc or not self._active_session:
            return
        if mode == "standard":
            user_pw = settings.get("user_pw", "")
            owner_pw = settings.get("owner_pw", user_pw)
            perms = {
                "print": settings.get("allow_print", True),
                "copy": settings.get("allow_copy", True),
                "annotate": settings.get("allow_annotate", True),
                "modify": settings.get("allow_modify", True),
                "form": settings.get("allow_form_fill", True),
            }
            perm_int = pdf_handler.permissions_to_bitmask(perms)
            self._active_session.pdf_password = user_pw
            self._active_session.pdf_owner_password = owner_pw
            self._active_session.pdf_permissions = perm_int
            self._active_session.is_vault = False
            self.doc._pdf_password = user_pw
            self.doc._pdf_owner_password = owner_pw
            self.doc._pdf_permissions = perm_int
            self.on_save_as()
        elif mode == "vault":
            vault_pw = settings.get("password", "")
            self._active_session.is_vault = True
            self._active_session.vault_password = vault_pw
            self.doc._is_vault = True
            self.doc._vault_password = vault_pw
            self.on_save_as()

    def on_sign_pdf_clicked(self, _action=None, _param=None):
        """Show Digital Signature dialog to configure and apply a digital signature."""
        if not self.doc:
            return
        from .signature_dialog import DigitalSignatureDialog
        if getattr(self, "_digital_sig_dialog", None) is not None:
            self._digital_sig_dialog.present()
            return
        self._digital_sig_dialog = DigitalSignatureDialog(
            parent_window=self,
            page_count=self.doc.page_count,
            current_page=self.current_page_index,
            on_sign_callback=self._execute_sign_from_dialog,
            on_draw_canvas_requested=self._on_draw_signature_on_canvas_requested,
        )
        self._digital_sig_dialog.connect("close-request", self._on_digital_sig_dialog_closed)
        self._digital_sig_dialog.present()

    def _on_draw_signature_on_canvas_requested(self):
        """Switch to interactive signature canvas placement tool."""
        self.on_tool_selected(None, "place_signature")

    def _on_digital_sig_dialog_closed(self, dialog):
        self._digital_sig_dialog = None
        return False

    def on_inspect_digital_signatures(self, _action=None, _param=None):
        """Show inspection dialog displaying digital signatures in active document."""
        if not self.doc or not self._active_session:
            return
        from .signature_dialog import SignatureDetailsDialog
        sess = self._active_session
        sigs = getattr(sess, "digital_signatures", None)
        if sigs is None:
            doc_ref = self.doc

            def _present_when_ready(resolved_sigs):
                if getattr(self, "_active_session", None) is not sess or getattr(sess, "doc", None) is not doc_ref:
                    return
                dialog = SignatureDetailsDialog(parent_window=self, signatures=resolved_sigs or [])
                dialog.present()

            if getattr(sess, "sig_inspection_in_progress", False):
                sess._sig_inspection_on_complete = _present_when_ready
            else:
                self._start_signature_inspection(sess, doc_ref, on_complete=_present_when_ready)
            return

        dialog = SignatureDetailsDialog(parent_window=self, signatures=sigs or [])
        dialog.present()

    def _execute_sign_from_dialog(self, options: Dict[str, Any]):
        """Execute digital signing of active document and prompt save path."""
        if not self.doc or not self._active_session:
            return

        filter_pdf = Gtk.FileFilter(name=_("filter_pdf"))
        filter_pdf.add_pattern("*.pdf")
        filter_pdf.add_mime_type("application/pdf")

        base_name = os.path.basename(self.current_file_path or "document.pdf")
        root, ext = os.path.splitext(base_name)
        initial_name = f"{root}_signed.pdf"

        def on_signed_save_finish(file, _filter=None):
            if not file:
                return
            save_path = file.get_path()
            if not save_path.lower().endswith(".pdf"):
                save_path += ".pdf"

            try:
                # Byte-Range Preservation:
                # If document already contains signatures, preserve raw file bytes to prevent xref mutation
                orig_path = getattr(self._active_session, "original_file_path", None) or getattr(self._active_session, "pdf_path", None)
                has_existing_sigs = bool(getattr(self._active_session, "digital_signatures", None))
                if has_existing_sigs and orig_path and os.path.isfile(orig_path):
                    with open(orig_path, "rb") as f:
                        pdf_bytes = f.read()
                else:
                    self.commit_pending_format_change()
                    pdf_bytes = self.doc.tobytes()

                target_page_idx = options.get("page_index", 0)
                page_height = None
                page_width = None
                if target_page_idx < len(self.doc):
                    page_rect = self.doc[target_page_idx].rect
                    page_height = page_rect.height
                    page_width = page_rect.width

                box = options.get("box")
                if box is None and options.get("visual_stamp", True):
                    from .digital_signature import _sanitize_visual_stamp_text, _wrap_stamp_field
                    display_name = options.get("signer_name") or ""
                    display_loc = options.get("location") or ""
                    display_cnt = options.get("contact_info") or ""
                    display_rsn = options.get("reason") or ""

                    s_signer = _sanitize_visual_stamp_text(display_name)
                    s_rsn, _lines_r = _wrap_stamp_field("Reason", _sanitize_visual_stamp_text(display_rsn))
                    s_loc, _lines_l = _wrap_stamp_field("Location", _sanitize_visual_stamp_text(display_loc))
                    s_cnt, _lines_c = _wrap_stamp_field("Contact", _sanitize_visual_stamp_text(display_cnt))

                    rendered_lines = [
                        f"Digitally signed by: {s_signer}",
                        "Date: YYYY-MM-DD HH:MM:SS +00",
                    ]
                    rendered_lines.extend(f"Reason: {s_rsn}".split("\n"))
                    if display_loc:
                        rendered_lines.extend(f"Location: {s_loc}".split("\n"))
                    if display_cnt:
                        rendered_lines.extend(f"Contact: {s_cnt}".split("\n"))

                    pw = page_width or 595.0
                    ph = page_height or 842.0
                    max_chars = max(len(l) for l in rendered_lines)
                    max_w = min(260.0, float(pw - 30.0))
                    if max_chars <= 34:
                        stamp_w = 175.0
                    else:
                        stamp_w = min(max_chars * 4.3 + 12.0, max_w)
                    stamp_h = max(42.0, 8.0 + len(rendered_lines) * 8.6)

                    pos = options.get("position", "bottom_right")
                    if pos == "bottom_left":
                        bx = 30.0
                        by = max(15.0, ph - stamp_h - 35.0)
                    elif pos == "top_right":
                        bx = max(15.0, pw - stamp_w - 30.0)
                        by = 30.0
                    elif pos == "top_left":
                        bx = 30.0
                        by = 30.0
                    else:  # bottom_right
                        bx = max(15.0, pw - stamp_w - 30.0)
                        by = max(15.0, ph - stamp_h - 35.0)
                    box = (bx, by, stamp_w, stamp_h)

                signed_bytes, err = pdf_handler.sign_pdf_document(
                    pdf_bytes=pdf_bytes,
                    pfx_data_or_path=options.get("cert_data") or options.get("cert_path"),
                    passphrase=options.get("passphrase"),
                    reason=options.get("reason"),
                    location=options.get("location"),
                    contact_info=options.get("contact_info"),
                    signer_name=options.get("signer_name"),
                    page_index=target_page_idx,
                    box=box,
                    page_height=page_height,
                    page_width=page_width,
                    visual_stamp=options.get("visual_stamp", True),
                    signature_image_bytes=options.get("signature_image_bytes"),
                    certify=options.get("certify", False),
                    docmdp_permissions=options.get("docmdp_permissions"),
                    pades_profile=options.get("pades_profile", "B-B"),
                    tsa_config=options.get("tsa_config"),
                    timestamper=options.get("timestamper"),
                    signer=options.get("signer"),
                    pkcs11_driver=options.get("pkcs11_driver"),
                    pkcs11_slot_id=options.get("pkcs11_slot_id"),
                    pkcs11_token_label=options.get("pkcs11_token_label"),
                    pkcs11_pin=options.get("pkcs11_pin"),
                    pkcs11_cert_label=options.get("pkcs11_cert_label"),
                    pkcs11_cert_id=options.get("pkcs11_cert_id"),
                )

                if err or not signed_bytes:
                    err_msg = _("sig_error_failed", err or "Unknown error")
                    if hasattr(self, "toast_overlay") and self.toast_overlay:
                        self.toast_overlay.add_toast(Adw.Toast(title=err_msg))
                    elif hasattr(self, "status_label") and self.status_label:
                        self.status_label.set_text(err_msg)
                    return

                with open(save_path, "wb") as f:
                    f.write(signed_bytes)

                if hasattr(self, "toast_overlay") and self.toast_overlay:
                    self.toast_overlay.add_toast(Adw.Toast(title=_("sig_success_signed")))
                elif hasattr(self, "status_label") and self.status_label:
                    self.status_label.set_text(_("sig_success_signed"))

                self.document_modified = False
                if self._active_session:
                    self._active_session.is_modified = False
                    self._active_session.pdf_path = save_path
                    self._active_session.original_file_path = save_path
                    self._update_tab_title(self._active_session)
                    self.set_title(f"{constants.APP_NAME} - {self._active_session.display_title}")

                def _do_reload():
                    self.load_document(
                        save_path,
                        target_page=target_page_idx,
                        in_new_tab=False,
                        force_reload=True,
                    )
                    return GLib.SOURCE_REMOVE

                GLib.idle_add(_do_reload)

            except Exception as ex:
                err_msg = _("sig_error_failed", str(ex))
                if hasattr(self, "toast_overlay") and self.toast_overlay:
                    self.toast_overlay.add_toast(Adw.Toast(title=err_msg))
                elif hasattr(self, "status_label") and self.status_label:
                    self.status_label.set_text(err_msg)

        show_save_file_dialog(
            self,
            _("sig_save_signed_title"),
            initial_name=initial_name,
            filters=[filter_pdf],
            default_filter=filter_pdf,
            callback=on_signed_save_finish,
        )

    def _start_signature_inspection(self, sess, doc, on_complete=None):
        """Run digital signature inspection on a background worker and update the session/banner on the main thread."""
        if sess is None or doc is None:
            return
        token = getattr(sess, "sig_inspection_token", 0) + 1
        sess.sig_inspection_token = token
        sess.sig_inspection_in_progress = True
        sess.digital_signatures = None
        sess._sig_inspection_on_complete = on_complete

        if getattr(self, "_active_session", None) is sess:
            self._update_signature_banner(None, verifying=True)

        def _worker():
            try:
                if getattr(doc, "is_closed", False):
                    return
                sigs = pdf_handler.inspect_document_signatures(doc)
            except Exception:
                sigs = []
            GLib.idle_add(self._apply_signature_inspection_result, sess, doc, token, sigs)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _apply_signature_inspection_result(self, sess, doc, token: int, sigs: List[Dict[str, Any]]):
        """Main-thread completion callback for background signature inspection with stale-result guards."""
        if sess is None or doc is None:
            return GLib.SOURCE_REMOVE
        sessions = getattr(self, "sessions", None)
        if sessions is not None and sess not in sessions:
            return GLib.SOURCE_REMOVE
        if getattr(sess, "doc", None) is not doc:
            return GLib.SOURCE_REMOVE
        if getattr(doc, "is_closed", False):
            return GLib.SOURCE_REMOVE
        if getattr(sess, "sig_inspection_token", 0) != token:
            return GLib.SOURCE_REMOVE

        sess.sig_inspection_in_progress = False
        sess.digital_signatures = sigs if sigs is not None else []
        cb = getattr(sess, "_sig_inspection_on_complete", None)
        sess._sig_inspection_on_complete = None

        if getattr(self, "_active_session", None) is sess:
            self._update_signature_banner(sess.digital_signatures, verifying=False)

        if callable(cb):
            cb(sess.digital_signatures)
        return GLib.SOURCE_REMOVE

    def _update_signature_banner(self, sigs: Optional[List[Dict[str, Any]]], verifying: bool = False):
        """Update top signature notification banner based on active document signatures."""
        if not hasattr(self, 'signature_banner') or not self.signature_banner:
            return
        if verifying:
            self.signature_banner_label.set_text(_("sig_banner_verifying"))
            self.signature_banner_icon.set_from_icon_name("content-loading-symbolic")
            if hasattr(self, "signature_banner_btn") and self.signature_banner_btn:
                self.signature_banner_btn.set_visible(False)
            self.signature_banner.set_visible(True)
            return

        if hasattr(self, "signature_banner_btn") and self.signature_banner_btn:
            self.signature_banner_btn.set_visible(True)

        if not sigs:
            self.signature_banner.set_visible(False)
            return

        total = len(sigs)
        all_intact = all(s.get("intact", False) for s in sigs)
        all_trusted = all(s.get("trusted", False) for s in sigs)

        if all_intact:
            if total == 1:
                signer_name = sigs[0].get("signer_cn") or sigs[0].get("signer_friendly") or "Signer"
                if all_trusted:
                    self.signature_banner_label.set_text(_("sig_banner_single_valid", signer_name))
                    self.signature_banner_icon.set_from_icon_name("emblem-ok-symbolic")
                else:
                    self.signature_banner_label.set_text(_("sig_banner_untrusted_single", signer_name))
                    self.signature_banner_icon.set_from_icon_name("dialog-information-symbolic")
            else:
                self.signature_banner_label.set_text(_("sig_banner_multi_valid", total))
                self.signature_banner_icon.set_from_icon_name("emblem-ok-symbolic" if all_trusted else "dialog-information-symbolic")
        else:
            self.signature_banner_label.set_text(_("sig_banner_invalid"))
            self.signature_banner_icon.set_from_icon_name("dialog-warning-symbolic")

        self.signature_banner.set_visible(True)

    def show_ocr_banner(self, total_pages=1):
        """Display background OCR progress banner."""
        if hasattr(self, 'ocr_banner') and self.ocr_banner:
            self._ocr_cancel_requested = False
            self._ocr_paused = False
            if hasattr(self, 'ocr_banner_pause_btn') and self.ocr_banner_pause_btn:
                self.ocr_banner_pause_btn.set_sensitive(True)
                if hasattr(self.ocr_banner_pause_btn, 'set_label'):
                    self.ocr_banner_pause_btn.set_label(_("ocr_btn_pause"))
            if hasattr(self, 'ocr_banner_cancel_btn') and self.ocr_banner_cancel_btn:
                self.ocr_banner_cancel_btn.set_sensitive(True)
            if hasattr(self, 'ocr_banner_progress') and self.ocr_banner_progress:
                self.ocr_banner_progress.set_fraction(0.0)
            if hasattr(self, 'ocr_banner_label') and self.ocr_banner_label:
                self.ocr_banner_label.set_text(_("ocr_banner_processing", 1, max(1, total_pages)))
            self.ocr_banner.set_visible(True)

    def update_ocr_banner(self, current_page, total_pages, fraction=None, eta_seconds=None, paused=None):
        """Update progress and live ETA on background OCR banner."""
        if hasattr(self, 'ocr_banner') and self.ocr_banner:
            frac = fraction if fraction is not None else (current_page / max(total_pages, 1))
            if hasattr(self, 'ocr_banner_progress') and self.ocr_banner_progress:
                self.ocr_banner_progress.set_fraction(frac)
            if hasattr(self, 'ocr_banner_label') and self.ocr_banner_label:
                label_text = _("ocr_banner_processing", current_page, total_pages)
                if eta_seconds is not None and eta_seconds > 0:
                    from .ocr_engine import format_ocr_eta
                    eta_str = format_ocr_eta(eta_seconds)
                    if eta_str:
                        label_text = f"{label_text} — {_('ocr_eta_label', eta_str)}"
                is_paused = paused if paused is not None else bool(getattr(self, '_ocr_paused', False))
                if is_paused:
                    label_text = f"{label_text} [{_('ocr_status_paused')}]"
                self.ocr_banner_label.set_text(label_text)

    def hide_ocr_banner(self, cancelled=False, completed_count=0):
        """Hide background OCR banner and update status."""
        if hasattr(self, 'ocr_banner') and self.ocr_banner:
            self.ocr_banner.set_visible(False)
            self._ocr_paused = False
            if cancelled:
                self.status_label.set_text(_("ocr_cancelling"))
            elif completed_count > 0:
                self.status_label.set_text(_("ocr_msg_completed", completed_count))

    def _on_ocr_banner_pause_clicked(self, btn=None):
        """Toggle pause/resume on the active streaming OCR pipeline."""
        pipeline = getattr(self, '_active_ocr_pipeline', None)
        if pipeline is not None and hasattr(pipeline, 'toggle_pause'):
            paused = pipeline.toggle_pause()
        else:
            paused = not bool(getattr(self, '_ocr_paused', False))
        self._ocr_paused = paused
        if hasattr(self, 'ocr_banner_pause_btn') and self.ocr_banner_pause_btn:
            if hasattr(self.ocr_banner_pause_btn, 'set_label'):
                self.ocr_banner_pause_btn.set_label(_("ocr_btn_resume") if paused else _("ocr_btn_pause"))
        if paused and hasattr(self, 'ocr_banner_label') and self.ocr_banner_label:
            self.ocr_banner_label.set_text(_("ocr_banner_paused"))
        return paused

    def _on_ocr_banner_cancel_clicked(self, btn):
        """Handle user clicking Cancel on the background OCR banner."""
        self._ocr_cancel_requested = True
        self._ocr_paused = False
        pipeline = getattr(self, '_active_ocr_pipeline', None)
        if pipeline is not None and hasattr(pipeline, 'cancel'):
            pipeline.cancel()
        if hasattr(self, 'ocr_banner_label') and self.ocr_banner_label:
            self.ocr_banner_label.set_text(_("ocr_cancelling"))
        if hasattr(self, 'ocr_banner_pause_btn') and self.ocr_banner_pause_btn:
            self.ocr_banner_pause_btn.set_sensitive(False)
        if hasattr(self, 'ocr_banner_cancel_btn') and self.ocr_banner_cancel_btn:
            self.ocr_banner_cancel_btn.set_sensitive(False)

    def toggle_search_bar(self):
        """Toggle search bar visibility and focus."""
        if not hasattr(self, 'search_bar') or not self.search_bar:
            return
        if self.search_bar.get_search_mode():
            self.close_search_bar()
        else:
            self.search_bar.set_search_mode(True)
            if hasattr(self, 'search_button') and self.search_button and not self.search_button.get_active():
                self.search_button.set_active(True)
            prefill = (self.view_selected_text or getattr(self, 'selected_word', '') or "").strip()
            if prefill and '\n' not in prefill and len(prefill) <= 120 and hasattr(self, 'search_entry') and self.search_entry:
                self.search_entry.set_text(prefill)
                self.search_entry.select_region(0, -1)
                self._on_search_query_changed(self.search_entry, immediate=True)
            if hasattr(self, 'search_entry') and self.search_entry:
                self.search_entry.grab_focus()

    def close_search_bar(self):
        """Close search bar and clear search highlights."""
        if hasattr(self, '_search_debounce_source') and self._search_debounce_source:
            GLib.source_remove(self._search_debounce_source)
            self._search_debounce_source = None
        if hasattr(self, 'search_bar') and self.search_bar:
            self.search_bar.set_search_mode(False)
        if hasattr(self, 'search_button') and self.search_button and self.search_button.get_active():
            self.search_button.set_active(False)
        if hasattr(self, 'search_redact_btn') and self.search_redact_btn and self.search_redact_btn.get_active():
            self.search_redact_btn.set_active(False)
        if hasattr(self, 'search_redact_box') and self.search_redact_box:
            self.search_redact_box.set_visible(False)
        if hasattr(self, 'search_engine') and self.search_engine:
            self.search_engine.clear()
        if hasattr(self, 'search_match_label') and self.search_match_label:
            self.search_match_label.set_text(_("search_no_results"))
        if hasattr(self, 'btn_search_redact_current') and self.btn_search_redact_current:
            self.btn_search_redact_current.set_sensitive(False)
        if hasattr(self, 'btn_search_redact_all') and self.btn_search_redact_all:
            self.btn_search_redact_all.set_sensitive(False)
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()
            self.pdf_view.grab_focus()

    def _on_search_button_toggled(self, button):
        """Handle header bar search toggle button clicks."""
        if not hasattr(self, 'search_bar') or not self.search_bar:
            return
        is_active = button.get_active()
        if is_active != self.search_bar.get_search_mode():
            if is_active:
                self.toggle_search_bar()
            else:
                self.close_search_bar()

    def _on_search_query_changed(self, entry, immediate: bool = False):
        """Handle search query string modifications with smooth 150ms debouncing."""
        if hasattr(self, '_search_debounce_source') and self._search_debounce_source:
            GLib.source_remove(self._search_debounce_source)
            self._search_debounce_source = None

        if immediate:
            self._execute_search_query(entry)
        else:
            self._search_debounce_source = GLib.timeout_add(150, self._execute_search_query_from_timer, entry)

    def _execute_search_query_from_timer(self, entry):
        self._search_debounce_source = None
        self._execute_search_query(entry)
        return GLib.SOURCE_REMOVE

    def _execute_search_query(self, entry):
        query = entry.get_text() if entry else ""
        case_sensitive = self.search_case_btn.get_active() if hasattr(self, 'search_case_btn') and self.search_case_btn else False
        whole_word = self.search_whole_word_btn.get_active() if hasattr(self, 'search_case_btn') and self.search_whole_word_btn else False
        if not self.doc or not query.strip():
            if hasattr(self, 'search_engine') and self.search_engine:
                self.search_engine.cancel_async_search()
                self.search_engine.clear()
            if hasattr(self, 'search_match_label') and self.search_match_label:
                self.search_match_label.set_text(_("search_no_results"))
            if hasattr(self, 'btn_search_redact_current') and self.btn_search_redact_current:
                self.btn_search_redact_current.set_sensitive(False)
            if hasattr(self, 'btn_search_redact_all') and self.btn_search_redact_all:
                self.btn_search_redact_all.set_sensitive(False)
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()
            return

        from .search_engine import PII_PATTERNS
        target_pages = [self.current_page_index] if getattr(self, '_search_scope_current_page', False) is True else None
        pii_key = getattr(self, '_search_pii_key', None)
        actual_pii = pii_key if (isinstance(pii_key, str) and pii_key in PII_PATTERNS) else None

        if hasattr(self, 'search_match_label') and self.search_match_label:
            self.search_match_label.set_text("...")

        first_jump_done = False

        def on_chunk(new_hits, processed, total):
            nonlocal first_jump_done
            total_matches = len(self.search_engine.matches)
            if total_matches > 0:
                if not first_jump_done:
                    first_jump_done = True
                    self.search_engine.find_nearest_match(self.current_page_index)
                    self._jump_to_current_search_match()
                curr = self.search_engine.current_index
                if hasattr(self, 'search_match_label') and self.search_match_label:
                    self.search_match_label.set_text(f"{curr + 1}/{total_matches}...")
                if hasattr(self, 'btn_search_redact_current') and self.btn_search_redact_current:
                    self.btn_search_redact_current.set_sensitive(True)
                if hasattr(self, 'btn_search_redact_all') and self.btn_search_redact_all:
                    self.btn_search_redact_all.set_sensitive(True)
            else:
                if hasattr(self, 'search_match_label') and self.search_match_label:
                    self.search_match_label.set_text(f"0 ({processed}/{total})")
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()

        def on_complete(all_matches):
            if all_matches:
                if not first_jump_done:
                    self.search_engine.find_nearest_match(self.current_page_index)
                    self._jump_to_current_search_match()
                curr = self.search_engine.current_index
                if hasattr(self, 'search_match_label') and self.search_match_label:
                    self.search_match_label.set_text(f"{curr + 1}/{len(all_matches)}")
                if hasattr(self, 'btn_search_redact_current') and self.btn_search_redact_current:
                    self.btn_search_redact_current.set_sensitive(True)
                if hasattr(self, 'btn_search_redact_all') and self.btn_search_redact_all:
                    self.btn_search_redact_all.set_sensitive(True)
            else:
                if hasattr(self, 'search_match_label') and self.search_match_label:
                    self.search_match_label.set_text(_("search_no_results"))
                if hasattr(self, 'btn_search_redact_current') and self.btn_search_redact_current:
                    self.btn_search_redact_current.set_sensitive(False)
                if hasattr(self, 'btn_search_redact_all') and self.btn_search_redact_all:
                    self.btn_search_redact_all.set_sensitive(False)
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()

        sync_mode = bool(getattr(self, '_force_sync_search', False) or len(self.doc) <= 3)

        self.search_engine.start_async_search(
            doc=self.doc,
            query=query,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
            pii_key=actual_pii,
            page_indices=target_pages,
            chunk_size=10,
            on_chunk=on_chunk,
            on_complete=on_complete,
            sync=sync_mode,
        )

    def _on_search_entry_activate(self):
        """Handle Enter key in search entry: run search query immediately if pending, then jump next."""
        if hasattr(self, '_search_debounce_source') and self._search_debounce_source:
            GLib.source_remove(self._search_debounce_source)
            self._search_debounce_source = None
            self._execute_search_query(self.search_entry)
        else:
            self._search_navigate_next()

    def _on_search_case_toggled(self, btn):
        """Re-run search immediately when case sensitivity toggle button changes."""
        self._on_search_query_changed(self.search_entry, immediate=True)

    def _on_search_whole_word_toggled(self, btn):
        """Re-run search immediately when whole word toggle button changes."""
        self._on_search_query_changed(self.search_entry, immediate=True)

    def _search_navigate_next(self):
        """Navigate to next search match."""
        if not hasattr(self, 'search_engine') or not self.search_engine or not self.search_engine.matches:
            return
        m = self.search_engine.next_match()
        if m:
            curr = self.search_engine.current_index
            wrap_hint = " ⟲" if getattr(self.search_engine, 'last_wrapped', False) else ""
            if hasattr(self, 'search_match_label') and self.search_match_label:
                self.search_match_label.set_text(f"{curr + 1}/{len(self.search_engine.matches)}{wrap_hint}")
            if getattr(self.search_engine, 'last_wrapped', False):
                if hasattr(self, 'toast_overlay') and self.toast_overlay:
                    toast = Adw.Toast(title=_("search_wrapped_start"))
                    toast.set_timeout(1)
                    self.toast_overlay.add_toast(toast)
            self._jump_to_current_search_match()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()

    def _search_navigate_prev(self):
        """Navigate to previous search match."""
        if not hasattr(self, 'search_engine') or not self.search_engine or not self.search_engine.matches:
            return
        m = self.search_engine.prev_match()
        if m:
            curr = self.search_engine.current_index
            wrap_hint = " ⟲" if getattr(self.search_engine, 'last_wrapped', False) else ""
            if hasattr(self, 'search_match_label') and self.search_match_label:
                self.search_match_label.set_text(f"{curr + 1}/{len(self.search_engine.matches)}{wrap_hint}")
            if getattr(self.search_engine, 'last_wrapped', False):
                if hasattr(self, 'toast_overlay') and self.toast_overlay:
                    toast = Adw.Toast(title=_("search_wrapped_end"))
                    toast.set_timeout(1)
                    self.toast_overlay.add_toast(toast)
            self._jump_to_current_search_match()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()

    def _jump_to_current_search_match(self):
        """Scroll canvas to make current search match visible."""
        if not hasattr(self, 'search_engine') or not self.search_engine:
            return
        m = self.search_engine.get_current_match()
        if not m or not self.doc:
            return
        v_adj = self.pdf_scroll.get_vadjustment() if hasattr(self, 'pdf_scroll') and self.pdf_scroll else None
        if self.continuous_scroll:
            if hasattr(self, 'continuous_page_offsets') and 0 <= m.page_index < len(self.continuous_page_offsets):
                _, py, _, _ = self.continuous_page_offsets[m.page_index]
                v_x1, v_y1 = self._unrotated_to_visual_page_coords(m.rect[0], m.rect[1], page_index=m.page_index)
                target_y = py + v_y1 * self.zoom_level
                if v_adj:
                    v_adj.set_value(max(0.0, target_y - 120.0))
                if m.page_index != self.current_page_index:
                    self._switch_active_page(m.page_index)
        else:
            if self.current_page_index != m.page_index:
                self._load_page(m.page_index)
            v_x1, v_y1 = self._unrotated_to_visual_page_coords(m.rect[0], m.rect[1], page_index=m.page_index)
            if v_adj:
                target_y = v_y1 * self.zoom_level
                v_adj.set_value(max(0.0, target_y - 120.0))

    def on_merge_documents(self, _action=None, _param=None):
        from .merge_dialog import MergeDialog
        if getattr(self, "_merge_dialog", None) is not None:
            self._merge_dialog.present()
            return
        self._merge_dialog = MergeDialog(parent_window=self)
        self._merge_dialog.connect("close-request", self._on_merge_dialog_closed)
        self._merge_dialog.present()

    def _on_merge_dialog_closed(self, dialog):
        if hasattr(dialog, "cleanup"):
            dialog.cleanup()
        self._merge_dialog = None
        return False

    def on_flatten_annotations(self, _action=None, _param=None):
        """Show the Flatten Annotations dialog."""
        if not self.doc:
            return
        from .flatten_dialog import FlattenDialog
        if getattr(self, "_flatten_dialog", None) is not None:
            self._flatten_dialog.present()
            return
        self._flatten_dialog = FlattenDialog(
            parent_window=self,
            current_page=self.current_page_index,
            total_pages=self.doc.page_count,
            on_confirm_callback=self._execute_flatten_from_dialog,
        )
        self._flatten_dialog.connect("close-request", self._on_flatten_dialog_closed)
        self._flatten_dialog.present()

    def _on_flatten_dialog_closed(self, dialog):
        self._flatten_dialog = None
        return False

    def _execute_flatten_from_dialog(self, scope: str, include_forms: bool):
        """Execute flattening of annotations triggered from FlattenDialog."""
        if not self.doc:
            return
        if scope == "all":
            page_indices = list(range(self.doc.page_count))
        else:
            page_indices = [self.current_page_index]
        self.flatten_annotations(page_indices=page_indices, include_forms=include_forms)

    def flatten_annotations(self, page_indices: Optional[List[int]] = None, include_forms: bool = False):
        """Flatten annotations across specified page indices with complete undo/redo support."""
        if not self.doc:
            return
        if page_indices is None:
            page_indices = [self.current_page_index]

        from .undo_manager import FlattenCommand
        cmd = FlattenCommand(self, page_indices=page_indices, include_forms=include_forms)
        cmd.execute()
        if self.undo_manager:
            self.undo_manager.record(cmd)

    def on_sanitize_document(self, _action=None, _param=None):
        """Show the Document Sanitization dialog."""
        if not self.doc:
            return
        from .sanitize_dialog import SanitizeDialog
        if getattr(self, "_sanitize_dialog", None) is not None:
            self._sanitize_dialog.present()
            return
        self._sanitize_dialog = SanitizeDialog(
            parent_window=self,
            on_confirm_callback=self._execute_sanitize_from_dialog,
        )
        self._sanitize_dialog.connect("close-request", self._on_sanitize_dialog_closed)
        self._sanitize_dialog.present()

    def _on_sanitize_dialog_closed(self, dialog):
        self._sanitize_dialog = None
        return False

    def on_ocr_document(self, _action=None, _param=None):
        """Show the Optical Character Recognition (OCR) dialog."""
        if not self.doc:
            return
        from .ocr_dialog import OCRDialog
        if getattr(self, "_ocr_dialog", None) is not None:
            try:
                if self._ocr_dialog.get_visible():
                    self._ocr_dialog.present()
                    return
            except Exception:
                pass
            self._ocr_dialog = None

        active_page = self.current_page
        self._ocr_dialog = OCRDialog(
            parent_window=self,
            doc=self.doc,
            current_page_num=active_page,
            on_completed_callback=self._on_ocr_completed,
        )
        self._ocr_dialog.connect("close-request", self._on_ocr_dialog_closed)
        self._ocr_dialog.connect("destroy", self._on_ocr_dialog_closed)
        self._ocr_dialog.present()

    def _on_ocr_dialog_closed(self, dialog=None):
        self._ocr_dialog = None
        return False

    def begin_streaming_ocr_session(
        self,
        language: str = "eng",
        dpi: int = 200,
        auto_deskew: bool = True,
        auto_rotate: bool = True,
        auto_invert: bool = True,
        enhance_contrast: bool = True,
    ) -> Optional[EmbedOCRTextCommand]:
        """Initialize a single Undo command before streaming OCR pages begin."""
        if not self.doc:
            self._active_streaming_ocr_cmd = None
            return None
        cmd = EmbedOCRTextCommand(
            self,
            page_indices=[],
            language=language,
            dpi=dpi,
            auto_deskew=auto_deskew,
            auto_rotate=auto_rotate,
            auto_invert=auto_invert,
            enhance_contrast=enhance_contrast,
        )
        self._active_streaming_ocr_cmd = cmd
        return cmd

    def _on_ocr_page_streamed(self, page_num: int, page_payload: dict, progress: Optional[dict] = None):
        """Main-thread handler invoked as soon as a single page finishes OCR so it becomes searchable immediately."""
        if not self.doc or getattr(self.doc, "is_closed", False):
            return
        cmd = getattr(self, "_active_streaming_ocr_cmd", None)
        if cmd is None:
            cmd = self.begin_streaming_ocr_session(
                language=page_payload.get("language", "eng"),
                dpi=page_payload.get("dpi", 200),
            )
        if cmd is not None:
            cmd.record_streamed_page(
                page_num,
                ocr_words=page_payload.get("ocr_words"),
                ocr_doc=page_payload.get("ocr_doc"),
                pre_snapshot=page_payload.get("pre_snapshot"),
            )
        if progress:
            self.update_ocr_banner(
                progress.get("current_index", 1),
                progress.get("total_pages", 1),
                fraction=progress.get("fraction"),
                eta_seconds=progress.get("eta_seconds"),
                paused=progress.get("paused"),
            )

    def finish_streaming_ocr_session(self, cancelled: bool = False) -> Optional[EmbedOCRTextCommand]:
        """Finalize the streaming OCR session and record a single Undo command for all completed pages."""
        cmd = getattr(self, "_active_streaming_ocr_cmd", None)
        self._active_streaming_ocr_cmd = None
        self._active_ocr_pipeline = None
        if cmd is not None and len(cmd.page_indices) > 0:
            if hasattr(self, "undo_manager") and self.undo_manager:
                self.undo_manager.record(cmd)
            if not cancelled and hasattr(self, "status_label") and self.status_label:
                self.status_label.set_text(_("ocr_msg_completed", len(cmd.page_indices)))
            return cmd
        return None

    def start_streaming_ocr(
        self,
        target_pages: list[int],
        language: str = "eng",
        dpi: int = 200,
        tessdata_dir: Optional[str] = None,
        auto_deskew: bool = True,
        auto_rotate: bool = True,
        auto_invert: bool = True,
        enhance_contrast: bool = True,
        on_progress=None,
        on_page_ready=None,
        on_finished=None,
        sync: bool = False,
    ):
        """Run the streaming OCR pipeline on target_pages, publishing each page incrementally."""
        if not self.doc:
            return None
        from .ocr_engine import StreamingOCRPipeline

        self.begin_streaming_ocr_session(
            language=language,
            dpi=dpi,
            auto_deskew=auto_deskew,
            auto_rotate=auto_rotate,
            auto_invert=auto_invert,
            enhance_contrast=enhance_contrast,
        )
        self.show_ocr_banner(len(target_pages))

        def _handle_progress(prog: dict):
            self.update_ocr_banner(
                prog.get("current_index", 1),
                prog.get("total_pages", 1),
                fraction=prog.get("fraction"),
                eta_seconds=prog.get("eta_seconds"),
                paused=prog.get("paused"),
            )
            if callable(on_progress):
                on_progress(prog)

        def _handle_page(p_num: int, payload: dict, prog: dict):
            self._on_ocr_page_streamed(p_num, payload, prog)
            if callable(on_page_ready):
                on_page_ready(p_num, payload, prog)

        def _handle_done(summary: dict):
            is_cancelled = bool(summary.get("cancelled", False))
            completed = summary.get("completed_pages", [])
            self.finish_streaming_ocr_session(cancelled=is_cancelled)
            self.hide_ocr_banner(cancelled=is_cancelled, completed_count=len(completed))
            if callable(on_finished):
                on_finished(summary)

        pipeline = StreamingOCRPipeline(
            doc=self.doc,
            target_pages=target_pages,
            language=language,
            dpi=dpi,
            tessdata_dir=tessdata_dir,
            auto_deskew=auto_deskew,
            auto_rotate=auto_rotate,
            auto_invert=auto_invert,
            enhance_contrast=enhance_contrast,
            on_progress=_handle_progress,
            on_page_ready=_handle_page,
            on_finished=_handle_done,
            dispatch_callback=None if sync else GLib.idle_add,
            external_cancel_check=lambda: bool(getattr(self, "_ocr_cancel_requested", False)),
        )
        self._active_ocr_pipeline = pipeline
        pipeline.start(sync=sync)
        return pipeline

    def _on_ocr_completed(self, target_pages: list[int], results: dict, language: str = "eng"):
        """Handle completion of OCR recognition by embedding transparent searchable text layers."""
        if not self.doc:
            return
        # If pages were already incrementally embedded via streaming session, finalize that single command
        active_cmd = getattr(self, "_active_streaming_ocr_cmd", None)
        if active_cmd is not None and len(active_cmd.page_indices) > 0:
            self.finish_streaming_ocr_session(cancelled=False)
            return
        if results:
            pages = [p for p in target_pages if p in results]
            if not pages:
                pages = sorted(results.keys())
            cmd = EmbedOCRTextCommand(
                self,
                page_indices=pages,
                ocr_results=results,
                language=language,
            )
            cmd.execute()
            if hasattr(self, "undo_manager") and self.undo_manager:
                self.undo_manager.record(cmd)
        elif hasattr(self, "status_label") and self.status_label:
            self.status_label.set_text(_("ocr_msg_completed", 0))

    def _execute_sanitize_from_dialog(self, options: dict):
        """Execute document-wide sanitization triggered from SanitizeDialog."""
        if not self.doc:
            return
        self.sanitize_active_document(options)

    def sanitize_active_document(self, options: dict) -> dict:
        """Purge metadata, hidden layers, comments, attachments and bookmarks based on options."""
        if not self.doc:
            return {"success": False, "error": "No document"}

        res = pdf_handler.sanitize_document(self.doc, **options)
        if res.get("success"):
            # If comments were purged, clear in-memory sticky notes as well
            if options.get("purge_comments"):
                if hasattr(self, "_active_session") and self._active_session:
                    if hasattr(self._active_session, "sticky_note_objects"):
                        self._active_session.sticky_note_objects.clear()
                if hasattr(self, "sticky_notes"):
                    self.sticky_notes.clear()

            self.document_modified = True

            # Invalidate caches across all pages
            pdf_handler.invalidate_page_cache(self.doc)
            for pno in range(self.doc.page_count):
                pdf_handler.save_page_snapshot(self.doc, pno, force=True)
                if hasattr(self, '_page_objects_cache') and pno in self._page_objects_cache:
                    del self._page_objects_cache[pno]
                self._refresh_thumbnail(pno)

            # Reload active page
            self._load_page(self.current_page_index, reload_objects=True)

            if hasattr(self, 'annotations_sidebar') and self.annotations_sidebar.get_visible():
                self.annotations_sidebar.refresh()

            self._update_ui_state()
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.set_text(_("status_document_sanitized"))

            msg = _(
                "sanitize_summary_msg",
                res.get("attachments_purged", 0),
                res.get("comments_purged", 0),
                res.get("hidden_layers_purged", 0),
                res.get("toc_items_purged", 0),
                res.get("thumbnails_purged", 0),
                res.get("javascript_actions_purged", 0),
            )
            show_info_dialog(self, msg, _("sanitize_summary_title"))

        return res

    def on_manage_stamps(self, _action=None, _param=None):
        """Open modern Libadwaita StampManagerDialog."""
        if not hasattr(self, 'stamp_library') or not self.stamp_library:
            self.stamp_library = StampLibrary()

        def _on_stamp_chosen(stamp):
            if stamp:
                self.active_stamp = stamp
                self.on_tool_selected(None, "add_stamp")
                self._update_stamp_controls()
                if hasattr(self, 'stamp_popover') and self.stamp_popover:
                    self.stamp_popover.refresh()

        dialog = StampManagerDialog(self, self.stamp_library, on_stamp_selected_callback=_on_stamp_chosen)
        dialog.present()

    def _on_stamp_chosen_from_popover(self, stamp):
        """Callback when a stamp is picked from the quick popover."""
        if stamp:
            self.active_stamp = stamp
            self.on_tool_selected(None, "add_stamp")
            self._update_stamp_controls()
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.set_text(f"{_('stamp_active_label')}: {stamp.name}")

    def on_export_as(self, action=None, param=None):
        """Show modern export dialog with format and layout mode options."""
        self.show_export_dialog(initial_format="DOCX")

    def on_export_docx(self, action=None, param=None):
        """Direct export to DOCX: prompt destination directly, defaulting to 1:1 canvas mode."""
        self._prompt_export_destination("DOCX", mode="canvas")

    def on_export_pptx(self, action=None, param=None):
        """Direct export to PPTX: prompt destination directly, defaulting to 1:1 canvas mode."""
        self._prompt_export_destination("PPTX", mode="canvas")

    def on_export_odt(self, action=None, param=None):
        """Direct export to ODT: prompt destination directly, defaulting to 1:1 canvas mode."""
        self._prompt_export_destination("ODT", mode="canvas")

    def on_export_odp(self, action=None, param=None):
        """Direct export to ODP: prompt destination directly, defaulting to 1:1 canvas mode."""
        self._prompt_export_destination("ODP", mode="canvas")

    def on_export_txt(self, action=None, param=None):
        """Direct export to TXT: prompt destination directly."""
        self._prompt_export_destination("TXT", mode="canvas")

    def show_export_dialog(self, initial_format="DOCX"):
        """Show modern Libadwaita ExportDialog for document export settings."""
        if not self.doc:
            return
        from .export_dialog import ExportDialog
        dialog = ExportDialog(
            parent_window=self,
            initial_format=initial_format,
            initial_mode="canvas",
            on_confirm_callback=self._on_export_dialog_confirmed
        )
        dialog.present()

    def _on_export_dialog_confirmed(self, format_name, mode):
        """Handle confirmed format and mode selection from ExportDialog."""
        self._prompt_export_destination(format_name, mode=mode)

    def _prompt_export_destination(self, format_name, mode="canvas"):
        """Prompt file save dialog for chosen format and mode, then execute export."""
        if not self.doc:
            return

        base_name = Path(self.current_file_path).stem if self.current_file_path else "document"
        fmt_upper = str(format_name).upper().strip()
        fmt_lower = fmt_upper.lower()

        export_filters = {
            "DOCX": (_("filter_word"), "*.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "PPTX": (_("filter_pptx"), "*.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
            "ODT": (_("filter_odt"), "*.odt", "application/vnd.oasis.opendocument.text"),
            "ODP": (_("filter_odp"), "*.odp", "application/vnd.oasis.opendocument.presentation"),
            "TXT": (_("filter_txt"), "*.txt", "text/plain"),
        }

        filter_list = []
        default_ff = None
        for name, (pattern_name, pattern, mime) in export_filters.items():
            ff = Gtk.FileFilter()
            ff.set_name(f"{name} - {pattern_name}")
            ff.add_pattern(pattern)
            if mime:
                ff.add_mime_type(mime)
            filter_list.append(ff)
            if name == fmt_upper:
                default_ff = ff

        def on_export_finish(file, selected_filter=None):
            if not file:
                return
            path = file.get_path()
            if not path:
                return
            self._execute_export(fmt_upper, path, mode=mode)

        show_save_file_dialog(
            self,
            _("export_as_title"),
            initial_name=f"{base_name}.{fmt_lower}",
            filters=filter_list,
            default_filter=default_ff,
            callback=on_export_finish
        )

    def _execute_export(self, format_name, output_path, mode="canvas", on_finish=None):
        """Execute export asynchronously in a background worker thread."""
        if not self.doc:
            if on_finish and callable(on_finish):
                on_finish(False, _("err_no_doc_msg"))
            return

        fmt_upper = str(format_name).upper().strip()
        fmt_lower = fmt_upper.lower()

        if not output_path.lower().endswith(f".{fmt_lower}"):
            output_path = f"{output_path}.{fmt_lower}"

        self.status_label.set_text(_("status_exporting", fmt_upper))

        try:
            pdf_bytes = self.doc.tobytes(garbage=4, clean=True, deflate=True)
        except Exception:
            try:
                pdf_bytes = self.doc.tobytes()
            except Exception:
                pdf_bytes = None

        doc_payload = pdf_bytes if pdf_bytes is not None else self.doc
        src_path = self.current_file_path

        def worker():
            success = False
            error_msg = _("err_unknown_export_format")
            try:
                if fmt_lower == "docx":
                    success, error_msg = pdf_handler.export_pdf_as_docx(
                        doc_payload, src_path, output_path, mode=mode
                    )
                elif fmt_lower == "odt":
                    success, error_msg = pdf_handler.export_pdf_as_odt(
                        doc_payload, src_path, output_path, mode=mode
                    )
                elif fmt_lower == "pptx":
                    success, error_msg = pdf_handler.export_pdf_as_pptx(
                        doc_payload, src_path, output_path, mode=mode
                    )
                elif fmt_lower == "odp":
                    success, error_msg = pdf_handler.export_pdf_as_odp(
                        doc_payload, src_path, output_path, mode=mode
                    )
                elif fmt_lower == "txt":
                    success, error_msg = pdf_handler.export_pdf_as_text(
                        doc_payload, output_path, mode=mode
                    )
                elif fmt_lower == "pdf":
                    success, error_msg = pdf_handler.save_document(
                        self.doc, output_path, incremental=False
                    )
                else:
                    success, error_msg = False, _("err_unknown_export_format")
            except Exception as e:
                success = False
                error_msg = str(e)

            GLib.idle_add(self._on_export_finished, success, error_msg, fmt_upper, output_path, on_finish)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _on_export_finished(self, success, error_msg, format_name, output_path, on_finish=None):
        """Handle export completion on the main GTK thread."""
        try:
            if success:
                self.status_label.set_text(_("status_exported", format_name, os.path.basename(output_path)))
                if format_name.lower() == "pdf":
                    self._update_ui_state()
            else:
                self.status_label.set_text(_("status_export_failed"))
                show_error_dialog(self, _("err_export_failed_msg", error_msg or _("status_export_failed")))
        finally:
            if on_finish and callable(on_finish):
                try:
                    on_finish(success, error_msg)
                except Exception:
                    pass
        return False

    def on_print_activated(self, action, param):
        """Initiate standard GTK print dialog workflow for the current document."""
        if not self.doc:
            show_error_dialog(self, _("print_no_doc"), _("print_no_doc_title"))
            return
        
        success, message = print_handler.print_document(self, self.doc)
        
        if success:
            if message:
                self.status_label.set_text(message)
        else:
            if message:
                show_error_dialog(self, message, _("print_error_title"))
                self.status_label.set_text(_("print_failed"))
            else:
                self.status_label.set_text(_("print_cancelled"))

    def _update_cursor_for_tool(self):
        """Restore cursor based on active tool mode."""
        if getattr(self, 'view_mode', False):
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("text"))
        elif self.tool_mode == "select":
            self.pdf_view.set_cursor(None)
        elif self.tool_mode in ("add_text", "add_ellipse", "add_rectangle", "add_checkmark", "add_cross", "pen", "highlighter", "form_builder", "calibrate", "place_signature"):
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        elif self.tool_mode == "add_image":
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("cell"))
        elif self.tool_mode == "drag":
            self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("move"))
        else:
            self.pdf_view.set_cursor(None)

    def _on_pointer_motion(self, controller, x, y):
        """Track last pointer position on pdf_view for focal zoom and update handle cursor."""
        now = time.monotonic()
        last_t = getattr(self, '_last_pointer_motion_time', 0.0)
        last_pos = getattr(self, '_last_pointer_pos', None)
        if last_pos is not None:
            dx = abs(x - last_pos[0])
            dy = abs(y - last_pos[1])
            if dx < 1.5 and dy < 1.5 and (now - last_t) < 0.010:
                return

        self._last_pointer_motion_time = now
        self._last_pointer_pos = (x, y)
        target_page, vis_x, vis_y = self.canvas_to_page_coords(x, y)
        unrot_x, unrot_y = self._visual_to_unrotated_page_coords(vis_x, vis_y, page_index=target_page)

        if getattr(self, 'view_mode', False):
            if getattr(self, 'view_tool_mode', None) == "add_sticky_note":
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
                self.pdf_view.set_tooltip_text(None)
                return

            hovered_note = self._find_sticky_note_at_pos(unrot_x, unrot_y) if hasattr(self, '_find_sticky_note_at_pos') else None
            if hovered_note:
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("pointer"))
                tip = f"{hovered_note.author or _('author_user')}: {hovered_note.content[:60]}" if hovered_note.content else _("sticky_note")
                self.pdf_view.set_tooltip_text(tip)
                return

            url = self._get_link_url_at_pos(unrot_x, unrot_y)
            if url:
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("pointer"))
                self.pdf_view.set_tooltip_text(url)
            else:
                self.pdf_view.set_tooltip_text(None)
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("text"))
            return

        modifiers = controller.get_current_event_state() if controller else 0
        ctrl_pressed = bool(modifiers & Gdk.ModifierType.CONTROL_MASK)
        if ctrl_pressed:
            url = self._get_link_url_at_pos(unrot_x, unrot_y)
            if url:
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("pointer"))
                self.pdf_view.set_tooltip_text(url)
                return

        self.pdf_view.set_tooltip_text(None)

        if not getattr(self, 'view_mode', False) and getattr(self, 'tool_mode', None) == "measure_area" and len(getattr(self, 'temp_polygon_vertices', [])) > 0:
            self.last_mouse_page_pos = (unrot_x, unrot_y)
            self.pdf_view.queue_draw()

        if not getattr(self, 'dragged_object', None):
            selected_obj = (self.selected_text or self.selected_image or self.selected_shape or 
                            getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None))
            if selected_obj:
                handle = self._find_resize_handle_at_pos(x, y, selected_obj)
                if handle == "rotate":
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
                    return
                elif handle in ("nw", "se"):
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("nwse-resize"))
                    return
                elif handle in ("ne", "sw"):
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("nesw-resize"))
                    return
                elif handle in ("n", "s"):
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("ns-resize"))
                    return
                elif handle in ("w", "e"):
                    self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("ew-resize"))
                    return
                elif getattr(self, 'tool_mode', None) in ("form_builder", "drag", "select") and hasattr(selected_obj, 'bbox') and selected_obj.bbox:
                    bx1, by1, bx2, by2 = selected_obj.bbox
                    padding = 4.0 / max(self.zoom_level, 0.001)
                    if (min(bx1, bx2) - padding) <= unrot_x <= (max(bx1, bx2) + padding) and (min(by1, by2) - padding) <= unrot_y <= (max(by1, by2) + padding):
                        self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("grab"))
                        return
            self._update_cursor_for_tool()

    def _update_inline_editor_position(self):
        """Update inline editor position, size, and font scaling after zoom changes."""
        if not getattr(self, 'inline_editor_widget', None) or not getattr(self, 'inline_editor_text_obj', None):
            return
        text_obj = self.inline_editor_text_obj
        if not text_obj.bbox:
            return
        page_offset_x, page_offset_y, _, _ = self.get_page_canvas_rect(self.current_page_index)
        page = self.doc[self.current_page_index]
        target_box = getattr(self, '_inline_editor_target_rect', None) or text_obj.bbox
        vis_rect = (fitz.Rect(target_box) * page.rotation_matrix).normalize()
        ed_x = int(page_offset_x + vis_rect.x0 * self.zoom_level) - 2
        ed_y = int(page_offset_y + vis_rect.y0 * self.zoom_level) - 2
        scaled_font = max(9.0, text_obj.font_size * self.zoom_level)
        ed_w = max(60, int(vis_rect.width * self.zoom_level) + 14)
        ed_h = max(int(scaled_font * 1.3) + 6, int(vis_rect.height * self.zoom_level) + 6)

        self._inline_editor_base_x = ed_x
        self._inline_editor_base_y = ed_y
        self._inline_editor_base_w = ed_w
        self._inline_editor_base_h = ed_h

        self.inline_editor_widget.set_margin_start(ed_x)
        self.inline_editor_widget.set_margin_top(ed_y)
        self._apply_inline_editor_style()
        if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
            self._on_inline_editor_text_changed(self.inline_editor_tv.get_buffer())
        else:
            self.inline_editor_widget.set_size_request(ed_w, ed_h)

    def _set_zoom(self, new_zoom, focal_point=None, is_gesture: bool = False):
        """Set zoom level smoothly with focal point anchoring, without reloading page."""
        if not self.doc or not (0 <= self.current_page_index < pdf_handler.get_page_count(self.doc)):
            return

        max_zoom = (150.0 / 72.0) if getattr(self, 'is_eco_mode', False) else 8.0
        clamped_zoom = max(0.1, min(max_zoom, new_zoom))
        if abs(clamped_zoom - self.zoom_level) < 0.001:
            return

        old_zoom = self.zoom_level
        self.zoom_level = clamped_zoom
        self.update_zoom_label()

        if is_gesture:
            self.is_zoom_gesture_active = True
            self._schedule_zoom_settled(immediate=False)
        else:
            self.is_zoom_gesture_active = False
            if getattr(self, '_zoom_debounce_timer', None) is not None:
                try:
                    GLib.source_remove(self._zoom_debounce_timer)
                except Exception:
                    pass
                self._zoom_debounce_timer = None

        page = self.doc.load_page(self.current_page_index)
        new_page_w = int(page.rect.width * self.zoom_level)
        new_page_h = int(page.rect.height * self.zoom_level)

        h_adj = self.pdf_scroll.get_hadjustment()
        v_adj = self.pdf_scroll.get_vadjustment()

        # Viewport dimensions
        vp_w = h_adj.get_page_size() if h_adj and h_adj.get_page_size() > 0 else float(self.pdf_scroll.get_allocated_width())
        vp_h = v_adj.get_page_size() if v_adj and v_adj.get_page_size() > 0 else float(self.pdf_scroll.get_allocated_height())

        scroll_x = h_adj.get_value() if h_adj else 0.0
        scroll_y = v_adj.get_value() if v_adj else 0.0

        # Current allocated drawing area dimensions
        da_w = max(self.pdf_view.get_allocated_width(), self.current_pdf_page_width)
        da_h = max(self.pdf_view.get_allocated_height(), self.current_pdf_page_height)
        page_offset_x = max(0.0, (da_w - self.current_pdf_page_width) / 2.0)
        page_offset_y = max(0.0, (da_h - self.current_pdf_page_height) / 2.0)

        # Determine focal anchor on the PDF page and screen viewport
        if focal_point is not None:
            focus_x, focus_y = focal_point
            doc_x = (focus_x - page_offset_x) / old_zoom
            doc_y = (focus_y - page_offset_y) / old_zoom
            vp_x = focus_x - scroll_x
            vp_y = focus_y - scroll_y
        else:
            center_x = scroll_x + (vp_w / 2.0)
            center_y = scroll_y + (vp_h / 2.0)
            doc_x = (center_x - page_offset_x) / old_zoom
            doc_y = (center_y - page_offset_y) / old_zoom
            vp_x = vp_w / 2.0
            vp_y = vp_h / 2.0

        # Update content dimensions
        self.current_pdf_page_width = new_page_w
        self.current_pdf_page_height = new_page_h
        if self.continuous_scroll:
            self._update_canvas_content_size()
        else:
            self.pdf_view.set_content_width(new_page_w)
            self.pdf_view.set_content_height(new_page_h)

        # Reposition active inline editor if open
        self._update_inline_editor_position()
        self._update_form_field_overlay_positions()

        if self.continuous_scroll:
            ratio = self.zoom_level / max(old_zoom, 0.001)
            if focal_point is not None:
                new_scroll_y = (scroll_y + focal_point[1]) * ratio - focal_point[1]
                new_scroll_x = (scroll_x + focal_point[0]) * ratio - focal_point[0]
            else:
                new_scroll_y = (scroll_y + vp_h / 2.0) * ratio - (vp_h / 2.0)
                new_scroll_x = (scroll_x + vp_w / 2.0) * ratio - (vp_w / 2.0)
        else:
            # Calculate new offsets for new page size vs viewport
            new_da_w = max(new_page_w, int(vp_w))
            new_da_h = max(new_page_h, int(vp_h))
            new_offset_x = max(0.0, (new_da_w - new_page_w) / 2.0)
            new_offset_y = max(0.0, (new_da_h - new_page_h) / 2.0)

            new_focus_x = new_offset_x + (doc_x * self.zoom_level)
            new_focus_y = new_offset_y + (doc_y * self.zoom_level)

            new_scroll_x = new_focus_x - vp_x
            new_scroll_y = new_focus_y - vp_y

        def _apply_scroll():
            if h_adj:
                max_x = max(0.0, h_adj.get_upper() - h_adj.get_page_size())
                h_adj.set_value(max(0.0, min(new_scroll_x, max_x)))
            if v_adj:
                max_y = max(0.0, v_adj.get_upper() - v_adj.get_page_size())
                v_adj.set_value(max(0.0, min(new_scroll_y, max_y)))
            return False

        _apply_scroll()
        GLib.idle_add(_apply_scroll)

        self.pdf_view.queue_draw()

    def _on_pinch_zoom_begin(self, gesture, sequence):
        """Handle start of touchpad or touchscreen pinch-to-zoom gesture."""
        if not self.doc:
            return
        self.is_zoom_gesture_active = True
        self._pinch_initial_zoom = self.zoom_level
        success, x, y = gesture.get_bounding_box_center()
        if success:
            self._pinch_focal_point = (x, y)
        else:
            self._pinch_focal_point = getattr(self, '_last_pointer_pos', None)
        if getattr(self, '_zoom_debounce_timer', None) is not None:
            try:
                GLib.source_remove(self._zoom_debounce_timer)
            except Exception:
                pass
            self._zoom_debounce_timer = None

    def _on_pinch_zoom_scale_changed(self, gesture, scale):
        """Track continuous pinch-to-zoom scaling in real-time."""
        if not self.doc or scale <= 0.0:
            return
        new_zoom = self._pinch_initial_zoom * scale
        self._set_zoom(new_zoom, focal_point=self._pinch_focal_point, is_gesture=True)

    def _on_pinch_zoom_end(self, gesture, sequence):
        """Settle zoom level once pinch gesture completes."""
        self._schedule_zoom_settled(immediate=False)

    def _on_pinch_zoom_cancel(self, gesture, sequence):
        """Cancel pinch gesture and settle zoom level immediately."""
        self._schedule_zoom_settled(immediate=True)

    def _schedule_zoom_settled(self, immediate: bool = False):
        """Schedule or immediately trigger high-DPI rasterization after zoom gesture finishes."""
        if getattr(self, '_zoom_debounce_timer', None) is not None:
            try:
                GLib.source_remove(self._zoom_debounce_timer)
            except Exception:
                pass
            self._zoom_debounce_timer = None

        if immediate:
            self._on_zoom_settled()
        else:
            self._zoom_debounce_timer = GLib.timeout_add(self._zoom_settle_delay_ms, self._on_zoom_settled)

    def _on_zoom_settled(self):
        """Debounced callback fired when zoom gesture settles (default 120ms).
        
        Clears active gesture flag and triggers progressive high-DPI rasterization
        for all visible pages.
        """
        self._zoom_debounce_timer = None
        self.is_zoom_gesture_active = False
        if not self.doc or getattr(self.doc, 'is_closed', False):
            return False
        if getattr(self, '_active_session', None) is None:
            return False

        if getattr(self, 'continuous_scroll', False):
            visible_indices = self.get_visible_page_indices() or [self.current_page_index]
        else:
            visible_indices = [self.current_page_index]

        target_zoom = self.zoom_level

        def _make_ready_cb(expected_idx, expected_zoom):
            def _on_ready(p, z, s):
                if not self.doc or getattr(self.doc, 'is_closed', False):
                    return
                if getattr(self, '_active_session', None) is None:
                    return
                is_vis = (p in self.get_visible_page_indices()) if getattr(self, 'continuous_scroll', False) else (p == self.current_page_index)
                if is_vis and abs(self.zoom_level - expected_zoom) < 0.001:
                    if hasattr(self, 'pdf_view') and self.pdf_view:
                        self.pdf_view.queue_draw()
            return _on_ready

        for p_idx in visible_indices:
            if 0 <= p_idx < pdf_handler.get_page_count(self.doc):
                pdf_handler.request_page_cairo_surface(
                    self.doc, p_idx, target_zoom,
                    callback=_make_ready_cb(p_idx, target_zoom),
                    progressive=True
                )

        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()
        return False

    def on_zoom_in(self, button=None, focal_point=None):
        if not self.doc: return
        self._set_zoom(self.zoom_level * 1.2, focal_point=focal_point, is_gesture=True)

    def on_zoom_out(self, button=None, focal_point=None):
        if not self.doc: return
        self._set_zoom(self.zoom_level / 1.2, focal_point=focal_point, is_gesture=True)

    def on_scroll_zoom(self, controller, dx, dy):
        """Zoom canvas in or out when Ctrl key is held during mouse scroll."""
        if controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            focal_point = getattr(self, '_last_pointer_pos', None)
            if dy < 0:
                self.on_zoom_in(focal_point=focal_point)
            elif dy > 0:
                self.on_zoom_out(focal_point=focal_point)
            return True
        return False

    def on_prev_page(self, button=None, smooth: bool = True):
        if self.doc and self.current_page_index > 0:
            if self.continuous_scroll:
                self.scroll_to_page(self.current_page_index - 1, smooth=smooth)
            else:
                self._load_page(self.current_page_index - 1)

    def on_next_page(self, button=None, smooth: bool = True):
        if self.doc and self.current_page_index < pdf_handler.get_page_count(self.doc) - 1:
            if self.continuous_scroll:
                self.scroll_to_page(self.current_page_index + 1, smooth=smooth)
            else:
                self._load_page(self.current_page_index + 1)

    def on_add_page(self, button):
        """Insert a new blank page with matching dimensions after current page."""
        if not self.doc:
            show_error_dialog(self, _("err_no_doc_msg"), _("err_no_doc_title"))
            return

        current_page = self.doc.load_page(self.current_page_index)
        page_width = current_page.rect.width
        page_height = current_page.rect.height
        insert_position = self.current_page_index + 1

        # Stash current page objects into cache before any page insertion/shifting
        self._stash_page_objects(self.current_page_index)

        success, message = pdf_handler.insert_blank_page(self.doc, insert_position, page_width, page_height)

        if success:
            if hasattr(self, '_page_objects_cache') and self._page_objects_cache:
                new_cache = {}
                for p, objs in self._page_objects_cache.items():
                    if p >= insert_position:
                        new_cache[p + 1] = objs
                        for coll_key in ('texts', 'images', 'shapes', 'strokes', 'form_fields'):
                            for obj in objs.get(coll_key, []):
                                if hasattr(obj, 'page_number') and obj.page_number is not None:
                                    obj.page_number += 1
                    else:
                        new_cache[p] = objs
                self._page_objects_cache.clear()
                self._page_objects_cache.update(new_cache)

            self.document_modified = True
            self.status_label.set_text(message)
            self._invalidate_continuous_layout()
            self._load_page(insert_position, reload_objects=True)
            self._load_thumbnails(target_page=insert_position)
            self._update_ui_state()
        else:
            show_error_dialog(self, message, _("err_add_page_title"))

    def on_delete_page(self, button):
        if getattr(self, 'is_saving', False) is True:
            return
        self._delete_page_at_index(self.current_page_index)

    def _delete_page_at_index(self, page_to_delete):
        """Delete the specified page index with confirmation."""
        if not self.doc or (getattr(self, 'is_saving', False) is True):
            if not self.doc:
                show_error_dialog(self, _("err_no_doc_open_msg"), _("err_no_doc_title"))
            return

        page_count = pdf_handler.get_page_count(self.doc)
        if page_count <= 1:
            show_error_dialog(self, _("err_cannot_delete_last_page"), _("err_cannot_delete_last_page_title"))
            return

        confirmed = show_confirm_dialog(
            self,
            _("delete_page_warn_msg", page_to_delete + 1),
            _("delete_page_warn_title"),
            destructive=True
        )

        if not confirmed:
            self.status_label.set_text("Sayfa silme iptal edildi.")
            return

        success, message = pdf_handler.delete_page(self.doc, page_to_delete)

        if success:
            if hasattr(self, '_page_objects_cache') and self._page_objects_cache:
                new_cache = {}
                for p, objs in self._page_objects_cache.items():
                    if p == page_to_delete:
                        continue
                    elif p > page_to_delete:
                        new_cache[p - 1] = objs
                        for coll_key in ('texts', 'images', 'shapes', 'strokes', 'form_fields'):
                            for obj in objs.get(coll_key, []):
                                if hasattr(obj, 'page_number') and obj.page_number is not None:
                                    obj.page_number -= 1
                    else:
                        new_cache[p] = objs
                self._page_objects_cache.clear()
                self._page_objects_cache.update(new_cache)

            self.document_modified = True
            self.status_label.set_text(message)
            self._invalidate_continuous_layout()
            new_page_count = pdf_handler.get_page_count(self.doc)
            new_page_index = min(page_to_delete, new_page_count - 1)
            self._load_page(new_page_index)
            self._load_thumbnails(target_page=new_page_index)
            self._update_ui_state()
        else:
            show_error_dialog(self, message, _("err_delete_page_title"))

    def rotate_current_page(self, angle_delta, page_index=None):
        """Rotate the specified or current page by angle_delta degrees (+90 or -90)."""
        if not self.doc or (getattr(self, 'is_saving', False) is True):
            return
        target_idx = self.current_page_index if page_index is None else page_index
        if not (0 <= target_idx < pdf_handler.get_page_count(self.doc)):
            return
        from .undo_manager import RotatePageCommand
        cmd = RotatePageCommand(self, target_idx, angle_delta)
        cmd.execute()
        self.undo_manager.add_command(cmd)
        msg_key = "status_page_rotated_cw" if angle_delta > 0 else "status_page_rotated_ccw"
        self.status_label.set_text(_(msg_key, target_idx + 1))

    def show_thumbnail_context_menu(self, parent_widget, x, y, page_index):
        """Show context menu for a page thumbnail with rotation and deletion options."""
        if not self.doc:
            return

        if hasattr(self, '_thumb_context_popover') and self._thumb_context_popover:
            self._thumb_context_popover.popdown()
            self._thumb_context_popover.unparent()
            self._thumb_context_popover = None

        popover = Gtk.Popover(autohide=True, has_arrow=True)
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        popover_box.set_margin_start(6)
        popover_box.set_margin_end(6)
        popover_box.set_margin_top(6)
        popover_box.set_margin_bottom(6)

        btn_cw = Gtk.Button(label=_("rotate_cw"))
        btn_cw.add_css_class("flat")
        btn_cw.set_tooltip_text("Ctrl+Shift+R")
        def on_cw(b):
            popover.popdown()
            self.rotate_current_page(90, page_index=page_index)
        btn_cw.connect("clicked", on_cw)
        popover_box.append(btn_cw)

        btn_ccw = Gtk.Button(label=_("rotate_ccw"))
        btn_ccw.add_css_class("flat")
        btn_ccw.set_tooltip_text("Ctrl+Shift+L")
        def on_ccw(b):
            popover.popdown()
            self.rotate_current_page(-90, page_index=page_index)
        btn_ccw.connect("clicked", on_ccw)
        popover_box.append(btn_ccw)

        in_edit = not getattr(self, 'view_mode', False)
        page_count = pdf_handler.get_page_count(self.doc) if self.doc else 0
        if in_edit and page_count > 1:
            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            btn_del = Gtk.Button(label=_("delete_page_title"))
            btn_del.add_css_class("flat")
            btn_del.add_css_class("destructive-action")
            def on_del(b):
                popover.popdown()
                self._delete_page_at_index(page_index)
            btn_del.connect("clicked", on_del)
            popover_box.append(btn_del)

        popover.set_child(popover_box)
        popover.set_parent(parent_widget)
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        self._thumb_context_popover = popover
        popover.popup()

    def update_page_label(self):
        """Update the page indicator label with current page number and total count."""
        count = pdf_handler.get_page_count(self.doc) if self.doc else 0
        if hasattr(self, 'page_label') and self.page_label:
            self.page_label.set_text(_("page_info_count").format(self.current_page_index + 1, count) if count > 0 else _("page_info_count").format(0, 0))
        self._sync_window_title_and_subtitle()

    def update_zoom_label(self):
        """Update the zoom indicator label with current active session zoom level."""
        zoom = getattr(self, 'zoom_level', 1.0)
        if hasattr(self, 'zoom_label') and self.zoom_label is not None:
            self.zoom_label.set_text(f"{int(round(zoom * 100))}%")

    def on_thumbnail_selected(self, selection_model, position=0, n_items=0, smooth: bool = True):
         """Navigate to page selected in the thumbnail sidebar."""
         selected_index = selection_model.get_selected()
         if selected_index != Gtk.INVALID_LIST_POSITION and selected_index != self.current_page_index:
              if hasattr(self, '_syncing_thumb') and self._syncing_thumb: return
              if self.continuous_scroll:
                  self.scroll_to_page(selected_index, smooth=smooth)
              else:
                  self._load_page(selected_index)

    def _sync_thumbnail_selection(self, page_index=None):
         """Update sidebar thumbnail selection without re-triggering navigation."""
         if not self.doc or not self.thumbnail_selection_model: return
         target_idx = self.current_page_index if page_index is None else page_index
         self._syncing_thumb = True
         self.thumbnail_selection_model.set_selected(target_idx)
         scrolled = False
         if hasattr(self, 'thumbnails_list') and hasattr(self.thumbnails_list, 'scroll_to'):
             try:
                 flags = getattr(Gtk.ListScrollFlags, 'NONE', 0) if hasattr(Gtk, 'ListScrollFlags') else 0
                 self.thumbnails_list.scroll_to(target_idx, flags, None)
                 scrolled = True
             except Exception:
                 pass
         if not scrolled:
             self._scroll_thumbnails_to_page(target_idx)
         self._syncing_thumb = False

    def _scroll_thumbnails_to_page(self, page_index=None):
        """Scroll the thumbnail sidebar to make the specified page visible."""
        if not hasattr(self, 'thumbnails_scroll') or not self.thumbnails_scroll:
            return
        target_idx = self.current_page_index if page_index is None else page_index
        model = getattr(self, 'pages_model', None)
        n = model.get_n_items() if model else 0
        if n <= 0 or not (0 <= target_idx < n):
            return

        adj = self.thumbnails_scroll.get_vadjustment()
        if not adj:
            return

        upper = adj.get_upper()
        page_size = adj.get_page_size()
        if upper > page_size and upper > 0:
            item_h = upper / n
            target_y = target_idx * item_h
            adj.clamp_page(target_y, target_y + item_h)
        else:
            attempts = [0]
            def _retry_scroll():
                attempts[0] += 1
                u = adj.get_upper()
                ps = adj.get_page_size()
                m = getattr(self, 'pages_model', None)
                total = m.get_n_items() if m else 0
                if total > 0 and 0 <= target_idx < total and u > ps and u > 0:
                    ih = u / total
                    ty = target_idx * ih
                    adj.clamp_page(ty, ty + ih)
                    return False
                return attempts[0] < 5
            GLib.timeout_add(25, _retry_scroll)

    @property
    def edit_mode(self):
        """Return True if currently in edit mode."""
        return not getattr(self, 'view_mode', True)

    def on_page_reorder(self, from_index, to_index):
         """Move a page in the document when reordered via drag-and-drop in thumbnail list."""
         if getattr(self, 'view_mode', False) or not self.edit_mode:
             return
         if from_index == to_index or from_index < 0 or to_index < 0:
             return
         
         success, message = pdf_handler.move_page(self.doc, from_index, to_index)
         
         if success:
             self.document_modified = True
             self.status_label.set_text(message)
             self._load_page(to_index)
             self._load_thumbnails(target_page=to_index)
             self._update_ui_state()
         else:
             show_error_dialog(self, message, _("err_move_page_title"))

    def get_selected_object(self):
        """Return the currently selected canvas object, if any."""
        return (
            getattr(self, 'selected_text', None) or
            getattr(self, 'selected_image', None) or
            getattr(self, 'selected_shape', None) or
            getattr(self, 'selected_stroke', None) or
            getattr(self, 'selected_form_field', None) or
            getattr(self, 'selected_measurement', None) or
            getattr(self, 'selected_redaction_mark', None)
        )

    def select_object(self, obj):
        """Select a single canvas object and clear all other selections."""
        if hasattr(self, '_close_active_form_field_editor'):
            self._close_active_form_field_editor()

        self.selected_text = obj if isinstance(obj, EditableText) else None
        self.selected_image = obj if isinstance(obj, EditableImage) else None
        self.selected_shape = obj if isinstance(obj, EditableShape) else None
        self.selected_stroke = obj if isinstance(obj, EditableStroke) else None
        self.selected_form_field = obj if isinstance(obj, AcroFormField) else None
        self.selected_measurement = obj if isinstance(obj, MeasurementObject) else None
        self.selected_redaction_mark = obj if isinstance(obj, RedactionMark) else None

        if self.selected_text:
            self.word_selection_mode = False
            self.pending_format_change_obj = self.selected_text
            self.before_format_change_state = snapshot_object_state(self.selected_text)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(self.selected_text)
        elif self.selected_stroke:
            if hasattr(self, '_update_stroke_format_controls'):
                self._update_stroke_format_controls(self.selected_stroke)
        elif self.selected_form_field:
            if hasattr(self, '_update_form_builder_controls_for_selected'):
                self._update_form_builder_controls_for_selected()
        elif self.selected_redaction_mark:
            if hasattr(self, '_open_redaction_popover'):
                self._open_redaction_popover(self.selected_redaction_mark)

        if hasattr(self, '_update_ui_state'):
            self._update_ui_state()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def deselect_all(self):
        """Deselect all canvas objects and reset drag authorization."""
        if hasattr(self, '_close_active_form_field_editor'):
            self._close_active_form_field_editor()
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None
        self.selected_redaction_mark = None
        self._can_drag_object = None
        if hasattr(self, '_update_ui_state'):
            self._update_ui_state()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()

    def _find_any_object_at_pos(self, page_x, page_y):
        """Find the topmost canvas object at unrotated page coordinates, if any."""
        obj = self._find_text_at_pos(page_x, page_y)
        if obj:
            return obj
        obj = self._find_image_at_pos(page_x, page_y)
        if obj:
            return obj
        obj = self._find_shape_at_pos(page_x, page_y)
        if obj:
            return obj
        obj = self._find_stroke_at_pos(page_x, page_y)
        if obj:
            return obj
        obj = self._find_form_field_at_pos(page_x, page_y)
        if obj:
            return obj
        if hasattr(self, '_find_measurement_at_pos'):
            obj = self._find_measurement_at_pos(page_x, page_y)
            if obj:
                return obj
        if hasattr(self, '_find_redaction_mark_at_pos'):
            obj = self._find_redaction_mark_at_pos(page_x, page_y)
            if obj:
                return obj
        return None

    def _on_pdf_view_released(self, gesture, n_press, x, y):
        """Reset transient click-drag authorization on mouse button release."""
        self._can_drag_object = None

    def on_pdf_view_pressed(self, gesture, n_press, x, y):
        """Handle primary mouse button press for object selection, links, or tool starts."""
        if not self.doc or self.current_pdf_page_width == 0 or self.current_pdf_page_height == 0:
            return

        target_page, page_x_unzoomed, page_y_unzoomed = self.canvas_to_page_coords(x, y)
        is_on_page = self.is_canvas_point_on_page(x, y, target_page)
        if is_on_page and target_page != self.current_page_index:
            self._switch_active_page(target_page)

        modifiers = Gtk.EventController.get_current_event_state(gesture) if isinstance(gesture, Gtk.EventController) else 0
        ctrl_pressed = bool(modifiers & Gdk.ModifierType.CONTROL_MASK)

        clicked_text = self._find_text_at_pos(page_x_unzoomed, page_y_unzoomed)
        
        if ctrl_pressed:
            url = self._get_link_url_at_pos(page_x_unzoomed, page_y_unzoomed) if hasattr(self, '_get_link_url_at_pos') else None
            if url:
                self._open_url(url)
                return

        if self.view_mode:
            if n_press == 1:
                if getattr(self, 'view_tool_mode', None) == "add_sticky_note" or (hasattr(self, 'view_sticky_note_btn') and self.view_sticky_note_btn and self.view_sticky_note_btn.get_active()):
                    if hasattr(self, 'view_sticky_note_btn') and self.view_sticky_note_btn:
                        self.view_sticky_note_btn.set_active(False)
                    self.view_tool_mode = None
                    self._create_sticky_note_at(page_x_unzoomed, page_y_unzoomed)
                    return

                clicked_note = self._find_sticky_note_at_pos(page_x_unzoomed, page_y_unzoomed) if hasattr(self, '_find_sticky_note_at_pos') else None
                if clicked_note:
                    self.selected_sticky_note = clicked_note
                    self._open_sticky_note_popover(clicked_note)
                    self.pdf_view.queue_draw()
                    self._update_ui_state()
                    return

                self.selected_sticky_note = None
                url = self._get_link_url_at_pos(page_x_unzoomed, page_y_unzoomed) if hasattr(self, '_get_link_url_at_pos') else None
                if url:
                    self._open_url(url)
                    return
                clicked_form_field = self._find_form_field_at_pos(page_x_unzoomed, page_y_unzoomed)
                if clicked_form_field:
                    self.selected_form_field = clicked_form_field
                    self._open_form_field_editor(clicked_form_field)
                    self.view_sel_start = None
                    self.view_sel_rect = None
                    self.view_selected_text = ""
                    self.word_selection_mode = False
                    self.pdf_view.queue_draw()
                    self._update_ui_state()
                    return
                else:
                    self._close_active_form_field_editor()

                clicked_block = pdf_handler.get_block_at_pos(self.doc, self.current_page_index, (page_x_unzoomed, page_y_unzoomed))
                if clicked_block:
                    self.selected_form_field = None
                    self.view_sel_rect = clicked_block['bbox']
                    self.view_selected_text = clicked_block['text']
                    self.selected_word = None
                    self.word_selection_mode = False
                else:
                    self.selected_form_field = None
                    self.view_sel_start = None
                    self.view_sel_rect = None
                    self.view_selected_text = ""
                    self.selected_word = None
                    self.word_selection_mode = False
                self.pdf_view.queue_draw()
                self._update_ui_state()
            elif n_press >= 2:
                clicked_word = pdf_handler.get_word_at_pos(self.doc, self.current_page_index, (page_x_unzoomed, page_y_unzoomed))
                if clicked_word:
                    self.selected_form_field = None
                    self.selected_word = clicked_word['text']
                    self.view_selected_text = clicked_word['text']
                    self.view_sel_rect = clicked_word['bbox']
                    self.word_selection_mode = True
                    self.pdf_view.queue_draw()
                    self._update_ui_state()
            return

        if getattr(self, 'is_saving', False) is True:
            return

        if self.font_scan_in_progress:
            show_error_dialog(self, _("err_fonts_scanning_msg"), _("err_fonts_scanning_title"))
            return

        self.commit_pending_format_change()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.grab_focus()

        obj_before_press = self.get_selected_object() if hasattr(self, 'get_selected_object') else (
            getattr(self, 'selected_text', None) or 
            getattr(self, 'selected_image', None) or 
            getattr(self, 'selected_shape', None) or 
            getattr(self, 'selected_stroke', None) or
            getattr(self, 'selected_form_field', None) or
            getattr(self, 'selected_measurement', None) or
            getattr(self, 'selected_redaction_mark', None)
        )
        self._can_drag_object = None

        if not is_on_page:
            if self.inline_editor_widget is not None:
                self._apply_and_hide_editor()
            if hasattr(self, 'deselect_all'):
                self.deselect_all()
            else:
                self.selected_text = None
                self.selected_image = None
                self.selected_shape = None
                self.selected_stroke = None
                self.selected_form_field = None
                self.selected_measurement = None
            self._can_drag_object = False
            return


        if self.tool_mode == "select":
            if self.inline_editor_widget is not None:
                self._apply_and_hide_editor()

            clicked_text = self._find_text_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_image = self._find_image_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_shape = self._find_shape_at_pos(page_x_unzoomed, page_y_unzoomed)
            if hasattr(self, '_keep_topmost_hit'):
                clicked_text, clicked_image, clicked_shape = self._keep_topmost_hit(
                    clicked_text, clicked_image, clicked_shape)
            clicked_stroke = self._find_stroke_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_form_field = self._find_form_field_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_measurement = self._find_measurement_at_pos(page_x_unzoomed, page_y_unzoomed)
            clicked_redaction = self._find_redaction_mark_at_pos(page_x_unzoomed, page_y_unzoomed) if hasattr(self, '_find_redaction_mark_at_pos') else None

            if clicked_redaction:
                self._can_drag_object = (clicked_redaction is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_redaction)
                else:
                    self.selected_redaction_mark = clicked_redaction
                return

            if clicked_text:
                self._can_drag_object = (clicked_text is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_text)
                else:
                    self.selected_text = clicked_text
                if n_press >= 2 and not self.view_mode:
                    self._show_inline_editor(clicked_text, click_x=x, click_y=y)
            elif clicked_image:
                self._can_drag_object = (clicked_image is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_image)
                else:
                    self.selected_image = clicked_image
                    self.selected_text = None
                if n_press >= 2 and not self.view_mode and getattr(clicked_image, 'is_patch', False):
                    self.initiate_text_over_patch(clicked_image)
                    return
            elif clicked_shape:
                self._can_drag_object = (clicked_shape is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_shape)
                else:
                    self.selected_shape = clicked_shape
            elif clicked_stroke:
                self._can_drag_object = (clicked_stroke is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_stroke)
                else:
                    self.selected_stroke = clicked_stroke
            elif clicked_form_field:
                self._can_drag_object = (clicked_form_field is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_form_field)
                else:
                    self.selected_form_field = clicked_form_field
            elif clicked_measurement:
                self._can_drag_object = (clicked_measurement is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_measurement)
                else:
                    self.selected_measurement = clicked_measurement
            else:
                if not self.view_mode and self.doc and 0 <= self.current_page_index < pdf_handler.get_page_count(self.doc):
                    hit_word = pdf_handler.hit_test_text_word_at_pos(
                        self.doc, (page_x_unzoomed, page_y_unzoomed), page_index=self.current_page_index, visual_coords=True
                    )
                    if hit_word:
                        found_text = None
                        wb = hit_word["bbox"]
                        for et in self.editable_texts:
                            if getattr(et, 'page_number', self.current_page_index) == self.current_page_index and getattr(et, 'bbox', None):
                                eb = et.bbox
                                if not (wb[2] < eb[0] or wb[0] > eb[2] or wb[3] < eb[1] or wb[1] > eb[3]):
                                    found_text = et
                                    break
                        if not found_text:
                            span_hit = hit_word.get("span", {})
                            span_text = span_hit.get("text", hit_word["word"])
                            span_bbox = span_hit.get("bbox", hit_word["bbox"])
                            span_origin = span_hit.get("origin", (span_bbox[0], span_bbox[3]))
                            found_text = EditableText(
                                x=span_bbox[0],
                                y=span_bbox[1],
                                text=span_text,
                                font_size=span_hit.get("size", 11),
                                font_family=span_hit.get("font", "Liberation Sans"),
                                color=span_hit.get("color", (0, 0, 0)),
                                span_data=span_hit,
                                baseline=span_origin[1],
                                rotation=span_hit.get("rotation", 0.0),
                                page_number=self.current_page_index
                            )
                            found_text.bbox = tuple(span_bbox)
                            found_text.original_bbox = tuple(span_bbox)
                            found_text.char_boxes = hit_word.get("char_boxes", [])
                            self.editable_texts.append(found_text)

                        self._can_drag_object = (found_text is obj_before_press)
                        if hasattr(self, 'select_object'):
                            self.select_object(found_text)
                        else:
                            self.selected_text = found_text
                        if n_press >= 2:
                            self._show_inline_editor(found_text, click_x=x, click_y=y)
                        return

                if hasattr(self, 'deselect_all'):
                    self.deselect_all()
                else:
                    self.selected_text = None
                    self.selected_image = None
                    self.selected_shape = None
                    self.selected_stroke = None
                    self.selected_form_field = None
                    self.selected_measurement = None
                self._can_drag_object = False

        elif self.tool_mode in ("measure_area", "measure_distance"):
            clicked_m = self._find_measurement_at_pos(page_x_unzoomed, page_y_unzoomed)
            if clicked_m is not None:
                self._can_drag_object = (clicked_m is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_m)
                else:
                    self.selected_measurement = clicked_m
                self.temp_polygon_vertices = []
                self.temp_measurement_line = None
                self.temp_measurement_rect = None
                self.last_mouse_page_pos = None
                return

        elif self.tool_mode == "form_builder":
            unrot_px, unrot_py = self._visual_to_unrotated_page_coords(page_x_unzoomed, page_y_unzoomed)
            clicked_form_field = self._find_form_field_at_pos(unrot_px, unrot_py)
            if clicked_form_field:
                self._can_drag_object = (clicked_form_field is obj_before_press)
                if hasattr(self, 'select_object'):
                    self.select_object(clicked_form_field)
                else:
                    self.selected_form_field = clicked_form_field
            else:
                if hasattr(self, 'deselect_all'):
                    self.deselect_all()
                else:
                    self.selected_form_field = None
                self._can_drag_object = False

            if self.tool_mode == "measure_area":
                unrot_x, unrot_y = self._visual_to_unrotated_page_coords(page_x_unzoomed, page_y_unzoomed)
                if n_press >= 2:
                    if len(getattr(self, 'temp_polygon_vertices', [])) >= 3:
                        pts = list(self.temp_polygon_vertices)
                        self.temp_polygon_vertices = []
                        self.last_mouse_page_pos = None
                        meas = MeasurementObject(
                            measurement_type=MeasurementObject.TYPE_AREA,
                            points=pts,
                            page_number=self.current_page_index
                        )
                        cmd = AddMeasurementCommand(self, meas)
                        cmd.execute()
                        self.undo_manager.add_command(cmd)
                        self.pdf_view.queue_draw()
                        self._update_ui_state()
                        return
                    else:
                        self.temp_polygon_vertices = []
                        self.last_mouse_page_pos = None
                        self.pdf_view.queue_draw()
                        return
                elif n_press == 1:
                    if len(getattr(self, 'temp_polygon_vertices', [])) >= 3:
                        start_pt = self.temp_polygon_vertices[0]
                        if math.hypot(unrot_x - start_pt[0], unrot_y - start_pt[1]) <= (15.0 / self.zoom_level):
                            pts = list(self.temp_polygon_vertices)
                            self.temp_polygon_vertices = []
                            self.last_mouse_page_pos = None
                            meas = MeasurementObject(
                                measurement_type=MeasurementObject.TYPE_AREA,
                                points=pts,
                                page_number=self.current_page_index
                            )
                            cmd = AddMeasurementCommand(self, meas)
                            cmd.execute()
                            self.undo_manager.add_command(cmd)
                            self.pdf_view.queue_draw()
                            self._update_ui_state()
                            return
                    if not hasattr(self, 'temp_polygon_vertices') or self.temp_polygon_vertices is None:
                        self.temp_polygon_vertices = []
                    self.temp_polygon_vertices.append((unrot_x, unrot_y))
                    self.pdf_view.queue_draw()
                    return

        elif self.tool_mode == "add_text":
            if self.inline_editor_widget is not None:
                self._apply_and_hide_editor()
                return

            font_fam_display, font_pdf_name, font_size, color, is_bold, is_italic, is_underline, is_strikethrough, alignment = self._get_current_format_settings()
            if self._last_font_family is not None:
                font_fam_display = self._last_font_family
                font_size = self._last_font_size
                is_bold = self._last_is_bold
                is_italic = self._last_is_italic
                is_underline = getattr(self, 'underline_button', None).get_active() if hasattr(self, 'underline_button') else False
                is_strikethrough = getattr(self, 'strikethrough_button', None).get_active() if hasattr(self, 'strikethrough_button') else False
                alignment = self._get_current_alignment()
                color = self._last_color
            unrot_x, unrot_y = self._visual_to_unrotated_page_coords(page_x_unzoomed, page_y_unzoomed)
            baseline_y_unzoomed = unrot_y + (font_size * 0.9)

            target_family_key = font_fam_display
            target_base14 = 'helv'
            iter = self.font_combo.get_active_iter()
            if iter:
                model_key = self.font_store[iter][1]
                normalized_for_base14 = re.sub(r'[^a-zA-Z0-9]', '', model_key).lower()
                for name_key, base14_val in BASE14_FALLBACK_MAP.items():
                    if name_key in normalized_for_base14:
                        target_base14 = base14_val
                        break

            new_text_obj = EditableText(
                x=unrot_x,
                y=unrot_y,
                text=_("default_new_text"),
                font_size=font_size,
                color=color,
                is_new=True,
                baseline=baseline_y_unzoomed
            )
            new_text_obj.font_family_base = target_family_key
            new_text_obj.font_family_original = _("font_user_added", target_family_key)
            new_text_obj.is_bold = is_bold
            new_text_obj.is_italic = is_italic
            new_text_obj.is_underline = is_underline
            new_text_obj.is_strikethrough = is_strikethrough
            new_text_obj.alignment = alignment
            new_text_obj.pdf_fontname_base14 = target_base14
            new_text_obj.page_number = self.current_page_index

            clicked_patch = self._find_image_at_pos(page_x_unzoomed, page_y_unzoomed)
            if clicked_patch and getattr(clicked_patch, 'is_patch', False):
                new_text_obj.linked_patch = clicked_patch
                clicked_patch.linked_text = new_text_obj

            self.selected_text = new_text_obj
            self.selected_image = None
            self._update_text_format_controls(self.selected_text)
            self._show_inline_editor(new_text_obj, click_x=x, click_y=y)
            self._update_ui_state()

        elif self.tool_mode == "add_image":
            unrot_x, unrot_y = self._visual_to_unrotated_page_coords(page_x_unzoomed, page_y_unzoomed, page_index=target_page)
            self._handle_add_image_click(unrot_x, unrot_y, page_index=target_page)
            if gesture is not None:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            return

        elif self.tool_mode == "clone_patch":
            # Handled by drag controller (on_drag_begin / on_drag_update / on_drag_end)
            pass

        elif self.tool_mode == "redact":
            clicked_redaction = self._find_redaction_mark_at_pos(page_x_unzoomed, page_y_unzoomed) if hasattr(self, '_find_redaction_mark_at_pos') else None
            if clicked_redaction:
                self.selected_redaction_mark = clicked_redaction
                self._open_redaction_popover(clicked_redaction)
                self.pdf_view.queue_draw()
                return

        elif self.tool_mode == "add_ellipse":
            # patched
            pass

        elif self.tool_mode == "add_rectangle":
            # patched
            pass

        elif self.tool_mode == "form_builder":
            clicked_form_field = self._find_form_field_at_pos(page_x_unzoomed, page_y_unzoomed)
            if clicked_form_field:
                self._close_active_form_field_editor()
                self.selected_text = None
                self.selected_image = None
                self.selected_shape = None
                self.selected_stroke = None
                self.selected_form_field = clicked_form_field
                self._update_form_builder_controls_for_selected()
                if n_press >= 2 and hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry and self.form_builder_name_entry.get_visible():
                    self.form_builder_name_entry.grab_focus()
                    self.form_builder_name_entry.select_region(0, -1)
            else:
                self._close_active_form_field_editor()
                self.selected_form_field = None
                self._update_form_builder_controls_for_selected()
            self.pdf_view.queue_draw()
            self._update_ui_state()
            return

    def on_text_format_changed(self, widget=None, *args):
        """Apply typography updates (font family, size, style, color, alignment) to selected text."""
        if getattr(self, 'is_saving', False) is True:
            return

        if self.font_scan_in_progress:
            return

        iter = self.font_combo.get_active_iter()
        if iter:
            self._last_font_family = self.font_store[iter][1]
        self._last_font_size = self.font_size_spin.get_value()
        self._last_is_bold = self.bold_button.get_active() if self.bold_button else False
        self._last_is_italic = self.italic_button.get_active() if self.italic_button else False
        self._last_is_strikethrough = self.strikethrough_button.get_active() if getattr(self, 'strikethrough_button', None) else False
        rgba = self.color_button.get_rgba()
        self._last_color = (rgba.red, rgba.green, rgba.blue)
        
        font_family_key = self._last_font_family
        font_size = self._last_font_size
        color = self._last_color
        is_bold = self._last_is_bold
        is_italic = self._last_is_italic
        is_underline = self.underline_button.get_active() if getattr(self, 'underline_button', None) else False
        is_strikethrough = self.strikethrough_button.get_active() if getattr(self, 'strikethrough_button', None) else False
        align_btns = [b for b in (getattr(self, 'align_left_button', None), getattr(self, 'align_center_button', None),
                                   getattr(self, 'align_right_button', None), getattr(self, 'align_justify_button', None)) if b is not None]
        if widget and widget in align_btns and not widget.get_active():
            def check_restore_active(deactivated_btn):
                if all(b and not b.get_active() for b in align_btns if b):
                    deactivated_btn.handler_block_by_func(self.on_text_format_changed)
                    deactivated_btn.set_active(True)
                    deactivated_btn.handler_unblock_by_func(self.on_text_format_changed)
                return False
            GLib.idle_add(check_restore_active, widget)
            return

        if widget and widget in align_btns and widget.get_active():
            for b in align_btns:
                if b and b != widget and b.get_active():
                    b.handler_block_by_func(self.on_text_format_changed)
                    b.set_active(False)
                    b.handler_unblock_by_func(self.on_text_format_changed)

        alignment = self._get_current_alignment()
        self._last_alignment = alignment
        
        if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv:
            if alignment == 'center':
                self.inline_editor_tv.set_justification(Gtk.Justification.CENTER)
            elif alignment == 'right':
                self.inline_editor_tv.set_justification(Gtk.Justification.RIGHT)
            elif alignment == 'justify':
                self.inline_editor_tv.set_justification(Gtk.Justification.FILL)
            else:
                self.inline_editor_tv.set_justification(Gtk.Justification.LEFT)
        
        if hasattr(self, 'inline_editor_tv') and self.inline_editor_tv and self.inline_editor_text_obj:
            buf = self.inline_editor_tv.get_buffer()
            has_sel, start_iter, end_iter = buf.get_selection_bounds()
            if has_sel:
                start_char = start_iter.get_offset()
                end_char = end_iter.get_offset()
                current_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
                
                self._hide_inline_editor()
                
                target_obj = self.inline_editor_text_obj
                target_obj.text = current_text
                spans = target_obj.split_at_range(start_char, end_char, compensate_rotation=False)
                
                if len(spans) > 1:
                    mid_index = 0 if start_char == 0 else 1
                    mid_span = spans[mid_index]
                    mid_span.font_family_base = font_family_key
                    mid_span.font_size = font_size
                    mid_span.color = color
                    mid_span.is_bold = is_bold
                    mid_span.is_italic = is_italic
                    mid_span.is_underline = is_underline
                    mid_span.is_strikethrough = is_strikethrough
                    mid_span.alignment = alignment

                    new_mid_w = measure_text_width(
                        mid_span.text, mid_span.font_family_base, mid_span.font_size,
                        mid_span.is_bold, mid_span.is_italic, mid_span
                    )
                    mx0, my0, mx1, my1 = mid_span.bbox
                    mid_span.bbox = (mx0, my0, mx0 + new_mid_w, my1)
                    mid_span.original_bbox = mid_span.bbox
                    dx = (mx0 + new_mid_w) - mx1

                    for s_idx in range(mid_index + 1, len(spans)):
                        post_span = spans[s_idx]
                        px0, py0, px1, py1 = post_span.bbox
                        post_span.bbox = (px0 + dx, py0, px1 + dx, py1)
                        post_span.original_bbox = post_span.bbox
                        post_span.x = post_span.bbox[0]

                    rot = getattr(target_obj, 'rotation', 0.0) % 360.0
                    if rot != 0.0 and target_obj.bbox:
                        p_cx = (target_obj.bbox[0] + target_obj.bbox[2]) / 2.0
                        p_cy = (target_obj.bbox[1] + target_obj.bbox[3]) / 2.0
                        for span in spans:
                            span.compensate_for_rotation((p_cx, p_cy), rot)
                    
                    target_page_num = getattr(target_obj, 'page_number', self.current_page_index)
                    commands = [DeleteObjectCommand(self, target_obj)]
                    for span in spans:
                        span.is_new = True
                        span.is_baked = True
                        span.page_number = target_page_num
                        commands.append(AddObjectCommand(self, span))
                    
                    batch_cmd = CompositeCommand(self, commands)
                    batch_cmd.execute()
                    self.undo_manager.add_command(batch_cmd)
                    self.selected_text = mid_span
                    self.pending_format_change_obj = mid_span
                    if hasattr(self, '_update_text_format_controls'):
                        self._update_text_format_controls(mid_span)
                    self._update_ui_state()
                    self.pdf_view.queue_draw()
                    return

        if getattr(self, 'word_selection_mode', False) and self.selected_text and hasattr(self, 'selected_word_start_char') and hasattr(self, 'selected_word_end_char'):
            start_char = self.selected_word_start_char
            end_char = self.selected_word_end_char
            target_obj = self.selected_text

            # Prevent pending format change tracking from firing an unwanted EditObjectCommand on target_obj
            if getattr(self, 'pending_format_change_obj', None) is target_obj:
                self.pending_format_change_obj = None
                self.before_format_change_state = None

            if start_char == 0 and end_char == len(target_obj.text):
                # Target is already an isolated word span
                old_props = snapshot_object_state(target_obj)
                new_props = snapshot_object_state(target_obj)
                if font_family_key:
                    new_props['font_family_base'] = font_family_key
                elif getattr(self, '_last_font_family', None):
                    new_props['font_family_base'] = self._last_font_family
                new_props['font_size'] = font_size
                new_props['is_bold'] = is_bold
                new_props['is_italic'] = is_italic
                new_props['is_underline'] = is_underline
                new_props['is_strikethrough'] = is_strikethrough
                new_props['alignment'] = alignment
                new_props['color'] = color

                new_w = measure_text_width(
                    target_obj.text, new_props['font_family_base'], new_props['font_size'],
                    new_props['is_bold'], new_props['is_italic'], target_obj
                )
                x0, y0, x1, y1 = target_obj.bbox
                dw = new_w - (x1 - x0)
                rot = getattr(target_obj, 'rotation', 0.0) % 360.0
                if rot != 0.0 and abs(dw) > 0.001:
                    dc_x, dc_y = dw / 2.0, 0.0
                    rad = math.radians(rot)
                    rdx = dc_x * math.cos(rad) - dc_y * math.sin(rad)
                    rdy = dc_x * math.sin(rad) + dc_y * math.cos(rad)
                    d_x = rdx - dc_x
                    d_y = rdy - dc_y
                else:
                    d_x, d_y = 0.0, 0.0

                new_props['bbox'] = (x0 + d_x, y0 + d_y, x0 + new_w + d_x, y1 + d_y)
                new_props['x'] = new_props['bbox'][0]
                new_props['y'] = new_props['bbox'][1]
                if 'baseline' in new_props and new_props['baseline'] is not None:
                    new_props['baseline'] += d_y
                dx = (x0 + new_w) - x1

                orig_w = max(0.1, float(x1 - x0))
                if target_obj.char_boxes and orig_w > 0:
                    scale_x = new_w / orig_w
                    new_cbs = []
                    for cb in target_obj.char_boxes:
                        ncb = dict(cb)
                        cbx0, cby0, cbx1, cby1 = ncb["bbox"]
                        ncb["bbox"] = (x0 + d_x + (cbx0 - x0) * scale_x, cby0 + d_y, x0 + d_x + (cbx1 - x0) * scale_x, cby1 + d_y)
                        if "visual_bbox" in ncb:
                            ncb["visual_bbox"] = ncb["bbox"]
                        if "origin" in ncb:
                            ncb["origin"] = (x0 + d_x + (ncb["origin"][0] - x0) * scale_x, ncb["origin"][1] + d_y)
                        new_cbs.append(ncb)
                    new_props['char_boxes'] = new_cbs

                commands = [EditObjectCommand(self, target_obj, old_props, new_props)]

                if abs(dx) > 0.001:
                    t_base = getattr(target_obj, 'baseline', y1)
                    t_page = getattr(target_obj, 'page_number', self.current_page_index)
                    for other in getattr(self, 'editable_texts', []):
                        if other is target_obj or getattr(other, 'page_number', None) != t_page:
                            continue
                        o_base = getattr(other, 'baseline', other.bbox[3] if other.bbox else other.y)
                        if abs(o_base - t_base) < 2.5 and other.bbox and other.bbox[0] >= x1 - 0.5:
                            o_old = {'bbox': other.bbox}
                            ox0, oy0, ox1, oy1 = other.bbox
                            o_new = {'bbox': (ox0 + dx, oy0, ox1 + dx, oy1)}
                            if getattr(other, 'char_boxes', None):
                                o_old['char_boxes'] = [dict(cb) for cb in other.char_boxes]
                                shifted_cbs = []
                                for cb in other.char_boxes:
                                    ncb = dict(cb)
                                    cbx0, cby0, cbx1, cby1 = ncb["bbox"]
                                    ncb["bbox"] = (cbx0 + dx, cby0, cbx1 + dx, cby1)
                                    if "visual_bbox" in ncb:
                                        ncb["visual_bbox"] = ncb["bbox"]
                                    if "origin" in ncb:
                                        ncb["origin"] = (ncb["origin"][0] + dx, ncb["origin"][1])
                                    shifted_cbs.append(ncb)
                                o_new['char_boxes'] = shifted_cbs
                            commands.append(EditObjectCommand(self, other, o_old, o_new))

                if len(commands) == 1:
                    cmd = commands[0]
                    cmd.execute()
                    self.undo_manager.add_command(cmd)
                else:
                    batch_cmd = CompositeCommand(self, commands)
                    batch_cmd.execute()
                    self.undo_manager.add_command(batch_cmd)

                self.pending_format_change_obj = target_obj
                self.before_format_change_state = snapshot_object_state(target_obj)
                self.selected_word_bbox = target_obj.bbox
                if hasattr(self, '_update_text_format_controls'):
                    self._update_text_format_controls(target_obj)
                if self.doc and self.current_page_index is not None:
                    pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return

            spans = target_obj.split_at_range(start_char, end_char, compensate_rotation=False)
            if len(spans) > 1:
                mid_index = 0 if start_char == 0 else 1
                mid_span = spans[mid_index]
                if font_family_key:
                    mid_span.font_family_base = font_family_key
                elif getattr(self, '_last_font_family', None):
                    mid_span.font_family_base = self._last_font_family
                mid_span.font_size = font_size
                mid_span.is_bold = is_bold
                mid_span.is_italic = is_italic
                mid_span.is_underline = is_underline
                mid_span.is_strikethrough = is_strikethrough
                mid_span.alignment = alignment
                mid_span.color = color

                new_mid_w = measure_text_width(
                    mid_span.text, mid_span.font_family_base, mid_span.font_size,
                    mid_span.is_bold, mid_span.is_italic, mid_span
                )
                mx0, my0, mx1, my1 = mid_span.bbox
                orig_mid_w = max(0.1, float(mx1 - mx0))
                mid_span.bbox = (mx0, my0, mx0 + new_mid_w, my1)
                mid_span.original_bbox = mid_span.bbox
                dx = (mx0 + new_mid_w) - mx1

                if mid_span.char_boxes and orig_mid_w > 0:
                    scale_x = new_mid_w / orig_mid_w
                    for cb in mid_span.char_boxes:
                        cbx0, cby0, cbx1, cby1 = cb["bbox"]
                        cb["bbox"] = (mx0 + (cbx0 - mx0) * scale_x, cby0, mx0 + (cbx1 - mx0) * scale_x, cby1)
                        if "visual_bbox" in cb:
                            cb["visual_bbox"] = cb["bbox"]
                        if "origin" in cb:
                            cb["origin"] = (mx0 + (cb["origin"][0] - mx0) * scale_x, cb["origin"][1])

                for s_idx in range(mid_index + 1, len(spans)):
                    post_span = spans[s_idx]
                    px0, py0, px1, py1 = post_span.bbox
                    post_span.bbox = (px0 + dx, py0, px1 + dx, py1)
                    post_span.original_bbox = post_span.bbox
                    post_span.x = post_span.bbox[0]
                    if post_span.char_boxes:
                        for cb in post_span.char_boxes:
                            cbx0, cby0, cbx1, cby1 = cb["bbox"]
                            cb["bbox"] = (cbx0 + dx, cby0, cbx1 + dx, cby1)
                            if "visual_bbox" in cb:
                                cb["visual_bbox"] = cb["bbox"]
                            if "origin" in cb:
                                cb["origin"] = (cb["origin"][0] + dx, cb["origin"][1])

                rot = getattr(target_obj, 'rotation', 0.0) % 360.0
                if rot != 0.0 and target_obj.bbox:
                    p_cx = (target_obj.bbox[0] + target_obj.bbox[2]) / 2.0
                    p_cy = (target_obj.bbox[1] + target_obj.bbox[3]) / 2.0
                    for span in spans:
                        span.compensate_for_rotation((p_cx, p_cy), rot)

                target_page_num = getattr(target_obj, 'page_number', self.current_page_index)
                commands = [DeleteObjectCommand(self, target_obj)]
                for span in spans:
                    span.is_new = True
                    span.is_baked = True
                    span.page_number = target_page_num
                    commands.append(AddObjectCommand(self, span))

                batch_cmd = CompositeCommand(self, commands)
                batch_cmd.execute()
                self.undo_manager.add_command(batch_cmd)

                self.pending_format_change_obj = None
                self.before_format_change_state = None
                self.selected_text = mid_span
                self.pending_format_change_obj = mid_span
                self.before_format_change_state = snapshot_object_state(mid_span)

                self.selected_word_start_char = 0
                self.selected_word_end_char = len(mid_span.text)
                self.selected_word_bbox = mid_span.bbox

                if hasattr(self, '_update_text_format_controls'):
                    self._update_text_format_controls(mid_span)
                if self.doc and self.current_page_index is not None:
                    pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return

        target_text = self.selected_text
        if target_text:
            if self.pending_format_change_obj is not target_text:
                if self.pending_format_change_obj:
                    self.commit_pending_format_change()
                self.pending_format_change_obj = target_text
                self.before_format_change_state = snapshot_object_state(target_text)
            changed = False

            if font_family_key and self.pending_format_change_obj.font_family_base != font_family_key:
                self.pending_format_change_obj.font_family_base = font_family_key
                changed = True
            
            if self.pending_format_change_obj.font_size != font_size:
                self.pending_format_change_obj.font_size = font_size
                changed = True
                obj = self.pending_format_change_obj
                if obj.bbox:
                    x1, y1, x2, y2 = obj.bbox
                    old_h = y2 - y1
                    old_w = x2 - x1
                    try:
                        _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
                        _cr = cairo.Context(_surf)
                        _layout = PangoCairo.create_layout(_cr)
                        _fd_str = f"{obj.font_family_base} {font_size}"
                        if obj.is_bold: _fd_str += " Bold"
                        if obj.is_italic: _fd_str += " Italic"
                        _layout.set_font_description(Pango.FontDescription.from_string(_fd_str))
                        _layout.set_text(obj.text if obj.text else "Ay", -1)
                        _p_w, _p_h = _layout.get_size()
                        
                        _w = (_p_w / Pango.SCALE) * 0.75
                        _h = (_p_h / Pango.SCALE) * 0.75
                        
                        new_w = max(_w, old_w) if _w > 0 else old_w
                        new_h = _h if _h > 0 else old_h
                        obj.bbox = (x1, y1, x1 + new_w, y1 + new_h)
                    except Exception as e:
                        print(f"DEBUG: Error recalculating text bbox: {e}")
                        pass
                
            if self.pending_format_change_obj.is_bold != is_bold:
                self.pending_format_change_obj.is_bold = is_bold
                changed = True
            if self.pending_format_change_obj.is_italic != is_italic:
                self.pending_format_change_obj.is_italic = is_italic
                changed = True
            if getattr(self.pending_format_change_obj, 'is_underline', False) != is_underline:
                self.pending_format_change_obj.is_underline = is_underline
                changed = True
            if getattr(self.pending_format_change_obj, 'is_strikethrough', False) != is_strikethrough:
                self.pending_format_change_obj.is_strikethrough = is_strikethrough
                changed = True
            if getattr(self.pending_format_change_obj, 'alignment', 'left') != alignment:
                self.pending_format_change_obj.alignment = alignment
                changed = True

            if self.pending_format_change_obj.color != color:
                self.pending_format_change_obj.color = color
                changed = True
                
            if changed and self.pending_format_change_obj.bbox:
                obj = self.pending_format_change_obj
                x1, y1, x2, y2 = obj.bbox
                try:
                    new_w = measure_text_width(
                        obj.text if obj.text else "Ay", obj.font_family_base, obj.font_size,
                        obj.is_bold, obj.is_italic, obj
                    )
                    old_w = x2 - x1
                    final_w = max(new_w, old_w) if getattr(obj, 'alignment', 'left') != 'left' else new_w
                    new_h = max(y2 - y1, obj.font_size * 1.15)
                    obj.bbox = (x1, y1, x1 + final_w, y1 + new_h)
                except Exception as e:
                    print(f"DEBUG: Error recalculating text bbox on format change: {e}")

            if changed:
                obj = self.pending_format_change_obj
                if self.inline_editor_widget is not None:
                    self._apply_and_hide_editor(force_apply=True)
                else:
                    new_properties = snapshot_object_state(obj)
                    obj.__dict__.update(self.before_format_change_state)
                    command = EditObjectCommand(self, obj, self.before_format_change_state, new_properties)
                    command.execute()
                    self.undo_manager.add_command(command)
                    self.before_format_change_state = snapshot_object_state(obj)
                    self.pdf_view.queue_draw()
                    self._update_ui_state()
        else:
            if self.pending_format_change_obj:
                self.commit_pending_format_change()
            self._update_ui_state()
            return

    def on_shape_format_changed(self, widget, *args):
        """Apply shape fill, stroke color, and line width updates to selection or next shape."""
        fill_rgba = self.shape_fill_button.get_rgba()
        fill_color = (fill_rgba.red, fill_rgba.green, fill_rgba.blue)
        stroke_rgba = self.shape_stroke_button.get_rgba()
        stroke_color = (stroke_rgba.red, stroke_rgba.green, stroke_rgba.blue)
        stroke_width = self.shape_stroke_width_spin.get_value()
        is_transparent = self.shape_transparent_toggle.get_active()
        self.next_shape_fill = fill_color
        self.next_shape_stroke = stroke_color
        self.next_shape_stroke_width = stroke_width
        self.next_shape_transparent = is_transparent

        if self.selected_shape:
            old_properties = snapshot_object_state(self.selected_shape)
            changed = False
            if self.selected_shape.fill_color != fill_color:
                self.selected_shape.fill_color = fill_color
                changed = True
            if self.selected_shape.stroke_color != stroke_color:
                self.selected_shape.stroke_color = stroke_color
                changed = True
            if self.selected_shape.stroke_width != stroke_width:
                self.selected_shape.stroke_width = stroke_width
                changed = True
            if self.selected_shape.is_transparent != is_transparent:
                self.selected_shape.is_transparent = is_transparent
                changed = True

            if changed:
                new_properties = snapshot_object_state(self.selected_shape)
                self.selected_shape.__dict__.update(old_properties)
                
                command = EditObjectCommand(self, self.selected_shape, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self.pdf_view.queue_draw()
                self._update_ui_state()

    def on_stroke_format_changed(self, widget, *args):
        """Apply stroke color or line width updates to active drawing tool or selected stroke."""
        stroke_rgba = self.stroke_color_button.get_rgba()
        stroke_color = (stroke_rgba.red, stroke_rgba.green, stroke_rgba.blue)
        stroke_width = self.stroke_width_spin.get_value()

        if self.tool_mode == "highlighter" or (self.selected_stroke and self.selected_stroke.tool_type == "highlighter"):
            self.highlighter_color = stroke_color
            self.highlighter_width = stroke_width
        else:
            self.pen_color = stroke_color
            self.pen_width = stroke_width

        if self.selected_stroke:
            old_properties = snapshot_object_state(self.selected_stroke)
            changed = False
            if self.selected_stroke.stroke_color != stroke_color:
                self.selected_stroke.stroke_color = stroke_color
                changed = True
            if self.selected_stroke.stroke_width != stroke_width:
                self.selected_stroke.stroke_width = stroke_width
                self.selected_stroke.recalculate_bbox()
                changed = True

            if changed:
                new_properties = snapshot_object_state(self.selected_stroke)
                self.selected_stroke.__dict__.update(old_properties)

                command = EditObjectCommand(self, self.selected_stroke, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self.pdf_view.queue_draw()
                self._update_ui_state()

    def on_text_edit_done(self, button):
        """Explicitly commit pending inline text edits and dismiss the editor."""
        self._apply_and_hide_editor(force_apply=True)

    def on_key_pressed(self, controller, keyval, keycode, state):
        """Handle global keyboard shortcuts (undo/redo, delete, zoom, navigation, escape)."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if ctrl and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.toggle_search_bar()
            return True

        if keyval == Gdk.KEY_F3:
            if shift:
                self._search_navigate_prev()
            else:
                self._search_navigate_next()
            return True

        if keyval == Gdk.KEY_Escape:
            if hasattr(self, 'search_bar') and self.search_bar and self.search_bar.get_search_mode():
                self.close_search_bar()
                return True

        if keyval == Gdk.KEY_F7:
            self.toggle_annotations_sidebar()
            return True

        if self.view_mode:
            if keyval == Gdk.KEY_Escape:
                self.view_sel_rect = None
                self.view_sel_start = None
                self.view_selected_text = ""
                self.selected_word = None
                self.word_selection_mode = False
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return True
            if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
                copy_text = self.view_selected_text or getattr(self, 'selected_word', '')
                if copy_text:
                    clipboard = self.get_clipboard()
                    clipboard.set(copy_text)
                return True
            if ctrl and keyval in (Gdk.KEY_n, Gdk.KEY_N):
                self.on_new_clicked(None)
                return True
            if ctrl and keyval in (Gdk.KEY_o, Gdk.KEY_O):
                self.on_open_clicked(None)
                return True
            if ctrl and keyval in (Gdk.KEY_w, Gdk.KEY_W):
                self.on_close_tab()
                return True
            if ctrl and keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Tab):
                self.on_next_tab()
                return True
            if ctrl and keyval in (Gdk.KEY_Page_Up, Gdk.KEY_ISO_Left_Tab):
                self.on_prev_tab()
                return True
            return False

        if (getattr(self, 'is_saving', False) is True) and (
            (ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z, Gdk.KEY_y, Gdk.KEY_Y))
            or keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace)
        ):
            return True

        if keyval == Gdk.KEY_Escape:
            if getattr(self, 'temp_polygon_vertices', None):
                self.temp_polygon_vertices = []
                self.last_mouse_page_pos = None
                self.pdf_view.queue_draw()
                return True
            if getattr(self, 'temp_measurement_line', None) or getattr(self, 'temp_measurement_rect', None):
                self.temp_measurement_line = None
                self.temp_measurement_rect = None
                self.last_mouse_page_pos = None
                self.pdf_view.queue_draw()
                return True
            if getattr(self, '_active_editing_form_field', None) is not None:
                self._close_active_form_field_editor()
                return True
            elif self.inline_editor_widget is not None:
                 self.hide_text_editor()
                 if self.selected_text and self.selected_text.is_new:
                      self.selected_text = None
                      self.pdf_view.queue_draw()
                 elif self.selected_text:
                      self.pdf_view.queue_draw()
                 self._update_ui_state()
                 return True
            elif self.selected_text:
                 self.selected_text = None
                 self.pdf_view.queue_draw()
                 self._update_ui_state()
                 return True
            elif getattr(self, 'selected_form_field', None):
                 self.selected_form_field = None
                 self._update_form_builder_controls_for_selected()
                 self.pdf_view.queue_draw()
                 self._update_ui_state()
                 return True
            elif getattr(self, 'selected_stroke', None):
                 self.selected_stroke = None
                 self.pdf_view.queue_draw()
                 self._update_ui_state()
                 return True
            elif self.tool_mode in ("add_text", "pen", "highlighter"):
                 self.on_tool_selected(None, "select")
                 return True

        if keyval == Gdk.KEY_F1:
            self.activate_action("quick_guide", None)
            return True

        if ctrl and keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self.on_new_clicked(None)
            return True
        elif ctrl and keyval in (Gdk.KEY_o, Gdk.KEY_O):
            self.on_open_clicked(None)
            return True
        elif ctrl and keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self.on_close_tab()
            return True
        elif ctrl and keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Tab):
            self.on_next_tab()
            return True
        elif ctrl and keyval in (Gdk.KEY_Page_Up, Gdk.KEY_ISO_Left_Tab):
            self.on_prev_tab()
            return True
        elif ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.on_save_clicked(None)
            return True
        elif ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.on_zoom_in(focal_point=getattr(self, '_last_pointer_pos', None))
            return True
        elif ctrl and keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.on_zoom_out(focal_point=getattr(self, '_last_pointer_pos', None))
            return True
        elif ctrl and keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self._set_zoom(1.0, focal_point=getattr(self, '_last_pointer_pos', None))
            return True

        focus_w = self.get_focus()
        is_editing_form = (getattr(self, '_active_editing_form_field', None) is not None)
        is_editing_entry = (
            (self.inline_editor_widget is not None)
            or is_editing_form
            or (focus_w is not None and focus_w is getattr(self, 'form_builder_name_entry', None))
            or (focus_w is not None and focus_w is getattr(self, 'form_builder_label_entry', None))
            or (focus_w is not None and focus_w is getattr(self, 'form_builder_options_entry', None))
        )
        is_input_focused = is_editing_entry or isinstance(focus_w, (Gtk.Editable, Gtk.TextView, Gtk.DropDown))

        if ctrl and not is_input_focused:
            shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
            if keyval in (Gdk.KEY_c, Gdk.KEY_C):
                if getattr(self, 'word_selection_mode', False) and getattr(self, 'selected_word', None):
                    self.get_clipboard().set(self.selected_word)
                    return True
                elif getattr(self, 'selected_text', None) and getattr(self.selected_text, 'text', None):
                    self.get_clipboard().set(self.selected_text.text)
                    return True
            elif keyval in (Gdk.KEY_v, Gdk.KEY_V):
                if getattr(self, 'last_captured_patch', None):
                    if self.paste_clone_patch():
                        return True
                clipboard = self.get_clipboard()
                def _on_paste_finished(cb, task):
                    try:
                        text = cb.read_text_finish(task)
                        if text and text.strip():
                            cx = getattr(self, 'last_mouse_page_pos', (100.0, 100.0))[0] if getattr(self, 'last_mouse_page_pos', None) else 100.0
                            cy = getattr(self, 'last_mouse_page_pos', (100.0, 100.0))[1] if getattr(self, 'last_mouse_page_pos', None) else 100.0
                            self._create_text_from_paste(cx, cy, text)
                    except Exception:
                        pass
                clipboard.read_text_async(None, _on_paste_finished)
                return True
            elif keyval in (Gdk.KEY_bracketright, Gdk.KEY_braceright):
                return self.reorder_selected_object("front" if shift else "forward")
            elif keyval in (Gdk.KEY_bracketleft, Gdk.KEY_braceleft):
                return self.reorder_selected_object("back" if shift else "backward")

        if getattr(self, 'selected_text', None) and not is_input_focused and not getattr(self, 'view_mode', False):
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_F2):
                self._show_inline_editor(self.selected_text)
                return True

        if getattr(self, 'selected_image', None) and getattr(self.selected_image, 'is_patch', False) and not is_input_focused and not getattr(self, 'view_mode', False):
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_t, Gdk.KEY_T):
                self.initiate_text_over_patch(self.selected_image)
                return True

        if getattr(self, 'selected_form_field', None) and not is_input_focused:
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_F2):
                if getattr(self, 'view_mode', False):
                    self._open_form_field_editor(self.selected_form_field)
                    return True
                elif getattr(self, 'tool_mode', '') == "form_builder" and hasattr(self, 'form_builder_name_entry') and self.form_builder_name_entry and self.form_builder_name_entry.get_visible():
                    self.form_builder_name_entry.grab_focus()
                    self.form_builder_name_entry.select_region(0, -1)
                    return True

        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            if getattr(self, 'selected_form_field', None) and not is_editing_entry:
                self._delete_selected_form_field()
                return True
            if getattr(self, 'selected_redaction_mark', None) and not is_editing_entry:
                self.delete_redaction_mark(self.selected_redaction_mark)
                return True

        if keyval == Gdk.KEY_Delete:
            self.commit_pending_format_change()
            obj_to_delete = (self.selected_text or self.selected_image or self.selected_shape or 
                             getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None) or
                             getattr(self, 'selected_measurement', None))
            if obj_to_delete and not is_input_focused:
                self._handle_delete_with_confirmation(obj_to_delete, "delete_confirm_title")
                return True
            elif self.selected_image:
                confirm = show_confirm_dialog(self, _("image_delete_confirm_msg"), _("image_delete_confirm_title"))
                if confirm:
                    self.status_label.set_text(_("deleting_image"))
                    success, error_msg = pdf_handler.delete_image_from_page(self.doc, self.selected_image)
                    if success:
                        self.document_modified = True
                        self._load_page(self.current_page_index)
                        self.status_label.set_text(_("object_deleted"))
                    else:
                        show_error_dialog(self, _("err_image_delete_msg", error_msg), _("err_image_delete_title"))
                    self.selected_image = None
                    self._update_ui_state()
        # Arrow key nudge movement (1pt normal / 10pt with Shift) for selected objects
        if not is_input_focused and keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down):
            selected_obj = (self.selected_text or self.selected_image or self.selected_shape or 
                            getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None) or
                            getattr(self, 'selected_measurement', None) or getattr(self, 'selected_redaction_mark', None))
            if selected_obj:
                step = 10.0 if bool(state & Gdk.ModifierType.SHIFT_MASK) else 1.0
                dx, dy = 0.0, 0.0
                if keyval == Gdk.KEY_Left:
                    dx = -step
                elif keyval == Gdk.KEY_Right:
                    dx = step
                elif keyval == Gdk.KEY_Up:
                    dy = -step
                elif keyval == Gdk.KEY_Down:
                    dy = step

                orig_lt = getattr(selected_obj, 'linked_text', None)
                orig_lp = getattr(selected_obj, 'linked_patch', None)

                old_properties = snapshot_object_state(selected_obj)
                if orig_lt is not None:
                    old_properties['linked_text'] = orig_lt
                if orig_lp is not None:
                    old_properties['linked_patch'] = orig_lp

                if isinstance(selected_obj, EditableText):
                    selected_obj.x += dx
                    selected_obj.y += dy
                    if getattr(selected_obj, 'baseline', None) is not None:
                        selected_obj.baseline += dy
                    if selected_obj.bbox:
                        x1, y1, x2, y2 = selected_obj.bbox
                        selected_obj.bbox = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                elif isinstance(selected_obj, EditableStroke):
                    selected_obj.points = [(p[0] + dx, p[1] + dy) for p in selected_obj.points]
                    selected_obj.recalculate_bbox()
                    selected_obj.original_bbox = selected_obj.bbox
                elif isinstance(selected_obj, MeasurementObject):
                    selected_obj.points = [(p[0] + dx, p[1] + dy) for p in selected_obj.points]
                    selected_obj.recalculate_bbox()
                elif isinstance(selected_obj, AcroFormField):
                    x1, y1, x2, y2 = selected_obj.rect
                    new_rect = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                    selected_obj.rect = new_rect
                    command = MoveResizeFormFieldCommand(self, selected_obj, (x1, y1, x2, y2), new_rect)
                    command.execute()
                    self.undo_manager.add_command(command)
                    self.document_modified = True
                    self._update_tab_dirty_state()
                    self._update_form_field_overlay_positions()
                    self._refresh_thumbnail(self.current_page_index)
                    self.pdf_view.queue_draw()
                    self._update_ui_state()
                    return True
                elif isinstance(selected_obj, (EditableShape, EditableImage, RedactionMark)):
                    x1, y1, x2, y2 = selected_obj.bbox
                    selected_obj.bbox = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                    selected_obj.x = selected_obj.bbox[0]
                    selected_obj.y = selected_obj.bbox[1]

                new_properties = snapshot_object_state(selected_obj)
                if orig_lt is not None:
                    new_properties['linked_text'] = orig_lt
                if orig_lp is not None:
                    new_properties['linked_patch'] = orig_lp

                selected_obj.__dict__.update(old_properties)
                if orig_lt is not None:
                    selected_obj.linked_text = orig_lt
                if orig_lp is not None:
                    selected_obj.linked_patch = orig_lp

                lt = orig_lt
                if lt and lt in getattr(self, 'editable_texts', []):
                    orig_lt_patch = getattr(lt, 'linked_patch', None)
                    old_lt_props = snapshot_object_state(lt)
                    if orig_lt_patch is not None:
                        old_lt_props['linked_patch'] = orig_lt_patch

                    lt.x += dx
                    lt.y += dy
                    if getattr(lt, 'baseline', None) is not None:
                        lt.baseline += dy
                    if lt.bbox:
                        lx1, ly1, lx2, ly2 = lt.bbox
                        lt.bbox = (lx1 + dx, ly1 + dy, lx2 + dx, ly2 + dy)

                    new_lt_props = snapshot_object_state(lt)
                    if orig_lt_patch is not None:
                        new_lt_props['linked_patch'] = orig_lt_patch

                    lt.__dict__.update(old_lt_props)
                    if orig_lt_patch is not None:
                        lt.linked_patch = orig_lt_patch

                    cmd1 = EditObjectCommand(self, selected_obj, old_properties, new_properties)
                    cmd2 = EditObjectCommand(self, lt, old_lt_props, new_lt_props)
                    command = CompositeCommand(self, [cmd1, cmd2])
                elif isinstance(selected_obj, RedactionMark):
                    from .undo_manager import EditRedactionCommand
                    command = EditRedactionCommand(self, selected_obj, old_properties, new_properties)
                else:
                    command = EditObjectCommand(self, selected_obj, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self._refresh_thumbnail(self.current_page_index)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return True

        # Single-key tool selection shortcuts (when not editing text)
        if not ctrl and not (state & Gdk.ModifierType.ALT_MASK) and not is_input_focused:
            tool_shortcuts = {
                Gdk.KEY_v: "add_checkmark",
                Gdk.KEY_V: "add_checkmark",
                Gdk.KEY_x: "add_cross",
                Gdk.KEY_X: "add_cross",
                Gdk.KEY_p: "pen",
                Gdk.KEY_P: "pen",
                Gdk.KEY_h: "highlighter",
                Gdk.KEY_H: "highlighter",
                Gdk.KEY_s: "select",
                Gdk.KEY_S: "select",
                Gdk.KEY_t: "add_text",
                Gdk.KEY_T: "add_text",
                Gdk.KEY_i: "add_image",
                Gdk.KEY_I: "add_image",
                Gdk.KEY_m: "select",
                Gdk.KEY_M: "select",
                Gdk.KEY_c: "clone_patch",
                Gdk.KEY_C: "clone_patch",
                Gdk.KEY_e: "add_ellipse",
                Gdk.KEY_E: "add_ellipse",
                Gdk.KEY_o: "add_ellipse",
                Gdk.KEY_O: "add_ellipse",
                Gdk.KEY_r: "add_rectangle",
                Gdk.KEY_R: "add_rectangle",
                Gdk.KEY_f: "form_builder",
                Gdk.KEY_F: "form_builder",
                Gdk.KEY_d: "measure_distance",
                Gdk.KEY_D: "measure_distance",
                Gdk.KEY_a: "measure_area",
                Gdk.KEY_A: "measure_area",
                Gdk.KEY_k: "add_stamp",
                Gdk.KEY_K: "add_stamp",
                Gdk.KEY_g: "place_signature",
                Gdk.KEY_G: "place_signature",
            }
            if keyval in tool_shortcuts:
                self.on_tool_selected(None, tool_shortcuts[keyval])
                return True

        return False

    def on_tool_selected(self, button, tool_name):
        """Switch active editor tool mode (select, text, shapes, pen, highlighter)."""
        if self.inline_editor_widget is not None:
             print(_("dbg_applying_changes_before_tool"))
             self._apply_and_hide_editor(force_apply=True)

        self.commit_pending_format_change()
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        if hasattr(self, 'selected_stroke') and self.selected_stroke:
            self.selected_stroke = None

        self.pdf_view.queue_draw()

        if tool_name == "drag":
            tool_name = "select"
        self.tool_mode = tool_name
        print(_("dbg_tool_changed", self.tool_mode))
        self.temp_calibration_line = None
        self.temp_measurement_line = None
        self.temp_measurement_rect = None
        self.temp_polygon_vertices = []
        self.last_mouse_page_pos = None
        self._update_ui_state()
        if self.tool_mode in ("pen", "highlighter"):
            self._update_stroke_format_controls(None)
        elif self.tool_mode == "calibrate":
            self._update_calibration_controls()
        elif self.tool_mode == "place_signature":
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.set_text(_("tool_place_signature_tip"))

    def get_scale_calibration(self, page_index: Optional[int] = None) -> Optional[ScaleCalibration]:
        """Return the active scale calibration for the specified page or whole document."""
        if not self._active_session:
            return None
        idx = page_index if page_index is not None else self.current_page_index
        page_calib = self._active_session.scale_calibrations.get(idx)
        if page_calib:
            return page_calib
        return self._active_session.scale_calibration

    def set_scale_calibration(self, calibration: Optional[ScaleCalibration],
                              page_index: Optional[int] = None, entire_document: bool = True):
        """Set or update scale calibration recording an undoable action in the history stack."""
        if not self._active_session:
            return
        old_calib = self.get_scale_calibration(page_index)
        cmd = CalibrateScaleCommand(self, old_calib, calibration, page_index=page_index, entire_document=entire_document)
        cmd.execute()
        self.undo_manager.add_command(cmd)

    def _apply_scale_calibration_state(self, calibration: Optional[ScaleCalibration],
                                       page_index: Optional[int] = None, entire_document: bool = True):
        """Apply scale calibration directly to the active session and synchronize UI components."""
        if not self._active_session:
            return
        idx = page_index if page_index is not None else self.current_page_index
        if entire_document:
            self._active_session.scale_calibration = calibration
            self._active_session.scale_calibrations.clear()
        else:
            if calibration is not None:
                self._active_session.scale_calibrations[idx] = calibration
            else:
                self._active_session.scale_calibrations.pop(idx, None)

        self.document_modified = True
        self._update_calibration_controls()
        if hasattr(self, 'status_label') and self.status_label:
            if calibration:
                self.status_label.set_text(_("scale_applied_success", calibration.unit, calibration.points_per_unit))
            else:
                self.status_label.set_text(_("scale_reset_success"))
        self.pdf_view.queue_draw()

    def _add_measurement_to_session(self, measurement, session=None):
        """Add measurement to active session storage."""
        sess = session or self._active_session
        if not sess:
            return
        p_idx = getattr(measurement, 'page_number', getattr(sess, 'current_page_index', self.current_page_index))
        if p_idx not in sess.measurements:
            sess.measurements[p_idx] = []
        if measurement not in sess.measurements[p_idx]:
            sess.measurements[p_idx].append(measurement)
        sess.document_modified = True
        self.document_modified = True
        if sess is self._active_session:
            self.selected_measurement = measurement
            if hasattr(self, '_update_tab_dirty_state'):
                self._update_tab_dirty_state()
            if hasattr(self, '_update_ui_state'):
                self._update_ui_state()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()

    def _remove_measurement_from_session(self, measurement, session=None):
        """Remove measurement from active session storage."""
        sess = session or self._active_session
        if not sess:
            return
        p_idx = getattr(measurement, 'page_number', getattr(sess, 'current_page_index', self.current_page_index))
        if p_idx in sess.measurements:
            if measurement in sess.measurements[p_idx]:
                sess.measurements[p_idx].remove(measurement)
        sess.document_modified = True
        self.document_modified = True
        if sess is self._active_session:
            if getattr(self, 'selected_measurement', None) == measurement:
                self.selected_measurement = None
            if hasattr(self, '_update_tab_dirty_state'):
                self._update_tab_dirty_state()
            if hasattr(self, '_update_ui_state'):
                self._update_ui_state()
            if hasattr(self, 'pdf_view') and self.pdf_view:
                self.pdf_view.queue_draw()

    def on_clear_measurements_clicked(self, button=None):
        """Clear all measurements on the current page."""
        if not self._active_session:
            return
        meas_list = list(self._active_session.measurements.get(self.current_page_index, []))
        if not meas_list:
            return
        from .undo_manager import CompositeCommand, DeleteMeasurementCommand
        commands = [DeleteMeasurementCommand(self, m) for m in meas_list]
        composite = CompositeCommand(self, commands)
        composite.execute()
        self.undo_manager.add_command(composite)
        self.selected_measurement = None
        self.document_modified = True
        if hasattr(self, '_update_tab_dirty_state'):
            self._update_tab_dirty_state()
        if hasattr(self, '_update_ui_state'):
            self._update_ui_state()
        if hasattr(self, 'pdf_view') and self.pdf_view:
            self.pdf_view.queue_draw()
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("measurements_cleared_success"))

    def _update_measurement_controls(self):
        """Update scale indicator, hint label, and clear button in measurement toolbar."""
        if not hasattr(self, 'measurement_toolbar_box') or not self.measurement_toolbar_box:
            return
        calib = self.get_scale_calibration(self.current_page_index) if hasattr(self, 'get_scale_calibration') else None
        if calib:
            self.measurement_scale_indicator.set_text(calib.format_scale_ratio())
            self.measurement_scale_indicator.remove_css_class("dim-label")
            self.measurement_scale_indicator.add_css_class("accent")
        else:
            self.measurement_scale_indicator.set_text(_("scale_uncalibrated"))
            self.measurement_scale_indicator.remove_css_class("accent")
            self.measurement_scale_indicator.add_css_class("dim-label")

        if self.tool_mode == "measure_distance":
            self.measurement_hint_lbl.set_text(_("measure_distance_hint"))
        elif self.tool_mode == "measure_area":
            self.measurement_hint_lbl.set_text(_("measure_area_hint"))
        else:
            self.measurement_hint_lbl.set_text("")

        has_meas = False
        if self._active_session:
            has_meas = bool(self._active_session.measurements.get(self.current_page_index, []))
        self.measurement_clear_btn.set_sensitive(has_meas)

    def _update_calibration_controls(self):
        """Update scale label, preset dropdown, and buttons in calibration toolbar."""
        self._update_measurement_controls()
        calib = self.get_scale_calibration(self.current_page_index) if hasattr(self, 'get_scale_calibration') else None
        if calib:
            summary = calib.format_scale_ratio()
            if hasattr(self, 'calibration_scale_label') and self.calibration_scale_label:
                self.calibration_scale_label.set_text(summary)
                self.calibration_scale_label.remove_css_class("dim-label")
                self.calibration_scale_label.add_css_class("accent")
            if hasattr(self, 'calibrate_reset_btn') and self.calibrate_reset_btn:
                self.calibrate_reset_btn.set_sensitive(True)
        else:
            if hasattr(self, 'calibration_scale_label') and self.calibration_scale_label:
                self.calibration_scale_label.set_text(_("scale_uncalibrated"))
                self.calibration_scale_label.remove_css_class("accent")
                self.calibration_scale_label.add_css_class("dim-label")
            if hasattr(self, 'calibrate_reset_btn') and self.calibrate_reset_btn:
                self.calibrate_reset_btn.set_sensitive(False)

    def _update_stamp_controls(self):
        """Update active stamp thumbnail and label in the upper stamp toolbar."""
        if not hasattr(self, 'stamp_toolbar_box') or not self.stamp_toolbar_box:
            return
        active_stamp = getattr(self, 'active_stamp', None)
        if not active_stamp and hasattr(self, 'stamp_library') and self.stamp_library:
            active_stamp = self.stamp_library.get_active_stamp()

        if active_stamp:
            paintable = active_stamp.get_paintable()
            if paintable and hasattr(self, 'stamp_toolbar_pic') and self.stamp_toolbar_pic:
                self.stamp_toolbar_pic.set_paintable(paintable)
                self.stamp_toolbar_pic.set_visible(True)
            elif hasattr(self, 'stamp_toolbar_pic') and self.stamp_toolbar_pic:
                self.stamp_toolbar_pic.set_visible(False)
            if hasattr(self, 'stamp_toolbar_name_lbl') and self.stamp_toolbar_name_lbl:
                self.stamp_toolbar_name_lbl.set_text(active_stamp.name)
            if hasattr(self, 'stamp_toolbar_lock_icon') and self.stamp_toolbar_lock_icon:
                is_prot = active_stamp.has_password()
                self.stamp_toolbar_lock_icon.set_visible(is_prot)
                if is_prot:
                    self.stamp_toolbar_lock_icon.set_tooltip_text(_("stamp_protected_badge"))
        if hasattr(self, 'stamp_popover') and self.stamp_popover:
            self.stamp_popover.refresh()

    def on_calibration_preset_changed(self, dropdown, param):
        """Apply selected preset scale from dropdown."""
        sel_idx = dropdown.get_selected()
        if sel_idx == 0:
            return  # Custom / Reference Line item
        preset_keys = list(PRESET_SCALES.keys())
        if 1 <= sel_idx <= len(preset_keys):
            key = preset_keys[sel_idx - 1]
            try:
                new_calib = ScaleCalibration.from_preset(key)
                self.set_scale_calibration(new_calib, page_index=self.current_page_index, entire_document=True)
            except Exception as e:
                print(f"Error applying preset scale {key}: {e}")

    def on_calibration_reset_clicked(self, button=None):
        """Reset active scale calibration."""
        self.temp_calibration_line = None
        if hasattr(self, 'calibration_preset_dropdown') and self.calibration_preset_dropdown:
            self.calibration_preset_dropdown.set_selected(0)
        self.set_scale_calibration(None, page_index=self.current_page_index, entire_document=True)

    def on_calibrate_dialog_clicked(self, button=None):
        """Open calibration dialog using drawn reference line or current scale dimensions."""
        calib = self.get_scale_calibration(self.current_page_index)
        ref_line = getattr(self, 'temp_calibration_line', None) or (calib.reference_line if calib else None)
        if ref_line:
            sx, sy, ex, ey = ref_line
            pt_len = math.hypot(ex - sx, ey - sy)
        else:
            pt_len = calib.points_len if (calib and calib.points_len > 0) else 100.0
        self.show_scale_calibration_dialog(pt_len, reference_line=ref_line)

    def show_scale_calibration_dialog(self, measured_points: float, reference_line=None):
        """Display popover dialog allowing user to set known real-world distance and unit."""
        if not self.doc:
            return

        dialog = Gtk.Popover(autohide=True, has_arrow=True)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)

        title_lbl = Gtk.Label(label=_("dialog_calibrate_title"))
        title_lbl.add_css_class("title-4")
        title_lbl.set_halign(Gtk.Align.START)
        content_box.append(title_lbl)

        desc_lbl = Gtk.Label(label=_("dialog_calibrate_desc"))
        desc_lbl.add_css_class("dim-label")
        desc_lbl.set_halign(Gtk.Align.START)
        content_box.append(desc_lbl)

        # Measured points display
        meas_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        meas_lbl = Gtk.Label(label=_("label_reference_length"))
        meas_lbl.set_halign(Gtk.Align.START)
        meas_box.append(meas_lbl)

        mm_len = (measured_points * 25.4) / 72.0
        meas_val_lbl = Gtk.Label(label=f"{measured_points:.2f} pt ({mm_len:.1f} mm)")
        meas_val_lbl.add_css_class("heading")
        meas_box.append(meas_val_lbl)
        content_box.append(meas_box)

        # Input grid: Known Distance and Unit
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)

        dist_lbl = Gtk.Label(label=_("label_known_distance"))
        dist_lbl.set_halign(Gtk.Align.START)
        grid.attach(dist_lbl, 0, 0, 1, 1)

        # Initial distance and unit from existing calibration if any
        current_calib = self.get_scale_calibration(self.current_page_index)
        init_dist = current_calib.known_distance if current_calib else 5.0
        init_unit = current_calib.unit if current_calib else "m"

        dist_spin = Gtk.SpinButton.new_with_range(0.001, 1000000.0, 0.5)
        dist_spin.set_digits(2)
        dist_spin.set_value(init_dist)
        dist_spin.set_hexpand(True)
        grid.attach(dist_spin, 1, 0, 1, 1)

        unit_lbl = Gtk.Label(label=_("label_unit"))
        unit_lbl.set_halign(Gtk.Align.START)
        grid.attach(unit_lbl, 0, 1, 1, 1)

        unit_keys = ["m", "cm", "mm", "ft", "in", "yd"]
        unit_names = [
            _("unit_meter"), _("unit_centimeter"), _("unit_millimeter"),
            _("unit_foot"), _("unit_inch"), _("unit_yard")
        ]
        unit_dropdown = Gtk.DropDown.new_from_strings(unit_names)
        if init_unit in unit_keys:
            unit_dropdown.set_selected(unit_keys.index(init_unit))
        else:
            unit_dropdown.set_selected(0)
        grid.attach(unit_dropdown, 1, 1, 1, 1)

        content_box.append(grid)

        # Scope options: Entire Document vs Current Page
        scope_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        doc_radio = Gtk.CheckButton(label=_("opt_entire_document"))
        doc_radio.set_active(True)
        page_radio = Gtk.CheckButton(label=_("opt_current_page"))
        page_radio.set_group(doc_radio)
        scope_box.append(doc_radio)
        scope_box.append(page_radio)
        content_box.append(scope_box)

        # Live preview label
        preview_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prev_title = Gtk.Label(label=_("label_calculated_scale"))
        prev_title.set_halign(Gtk.Align.START)
        preview_box.append(prev_title)

        prev_val_lbl = Gtk.Label(label="")
        prev_val_lbl.add_css_class("accent")
        preview_box.append(prev_val_lbl)
        content_box.append(preview_box)

        def update_preview(*a):
            dist = max(dist_spin.get_value(), 1e-9)
            u_idx = unit_dropdown.get_selected()
            u_key = unit_keys[u_idx] if 0 <= u_idx < len(unit_keys) else "m"
            ppu = measured_points / dist
            prev_val_lbl.set_text(f"1 {u_key} = {ppu:.2f} pt")

        dist_spin.connect("value-changed", update_preview)
        unit_dropdown.connect("notify::selected", update_preview)
        update_preview()

        # Action Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.END)

        def on_cancel(b):
            dialog.popdown()
            self.temp_calibration_line = None
            self.pdf_view.queue_draw()

        def on_apply(b):
            dist = max(dist_spin.get_value(), 1e-9)
            u_idx = unit_dropdown.get_selected()
            u_key = unit_keys[u_idx] if 0 <= u_idx < len(unit_keys) else "m"
            entire_doc = doc_radio.get_active()

            rl = reference_line
            if rl:
                new_calib = ScaleCalibration.from_reference_line(
                    rl[0], rl[1], rl[2], rl[3],
                    known_distance=dist, unit=u_key,
                    page_index=(None if entire_doc else self.current_page_index)
                )
            else:
                ppu = measured_points / dist
                new_calib = ScaleCalibration(
                    points_per_unit=ppu,
                    unit=u_key,
                    known_distance=dist,
                    points_len=measured_points,
                    reference_line=reference_line,
                    page_index=(None if entire_doc else self.current_page_index)
                )

            dialog.popdown()
            self.temp_calibration_line = None
            self.set_scale_calibration(new_calib, page_index=self.current_page_index, entire_document=entire_doc)
            if hasattr(self, 'calibration_preset_dropdown') and self.calibration_preset_dropdown:
                self.calibration_preset_dropdown.set_selected(0)

        cancel_btn = Gtk.Button(label=_("btn_cancel"))
        cancel_btn.connect("clicked", on_cancel)
        btn_box.append(cancel_btn)

        apply_btn = Gtk.Button(label=_("btn_apply"))
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", on_apply)
        btn_box.append(apply_btn)

        content_box.append(btn_box)
        dialog.set_child(content_box)

        anchor = getattr(self, 'calibrate_dialog_btn', self.pdf_view)
        dialog.set_parent(anchor)
        dialog.popup()

    def on_drag_begin(self, gesture, start_x, start_y):
        """Initiate canvas drag gesture for selection, movement, resizing, or freehand drawing."""
        if not self.doc:
            return

        target_page, page_x, page_y = self.canvas_to_page_coords(start_x, start_y)
        self.drag_start_page_index = target_page
        if not self.view_mode and self.is_canvas_point_on_page(start_x, start_y, target_page):
            if target_page != self.current_page_index:
                self._switch_active_page(target_page)

        if self.view_mode:
            unrot_px, unrot_py = self._visual_to_unrotated_page_coords(page_x, page_y)
            clicked_note = self._find_sticky_note_at_pos(unrot_px, unrot_py) if hasattr(self, '_find_sticky_note_at_pos') else None
            if clicked_note:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self.dragged_sticky_note = clicked_note
                self.sticky_note_start_coords = (clicked_note.x, clicked_note.y)
                self.drag_start_pos = (unrot_px, unrot_py)
                return

            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.view_drag_active = True
            self.view_sel_start = (page_x, page_y)
            self.view_sel_rect = (page_x, page_y, page_x, page_y)
            self.view_selected_text = ""
            self.pdf_view.queue_draw()
            return

        if getattr(self, 'is_saving', False) is True:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return

        # Allow direct resize handle interaction on already selected objects regardless of active tool
        selected_obj = (self.selected_text or self.selected_image or self.selected_shape or 
                        getattr(self, 'selected_stroke', None) or getattr(self, 'selected_form_field', None) or
                        getattr(self, 'selected_measurement', None) or getattr(self, 'selected_redaction_mark', None))
        if selected_obj:
            resize_handle = self._find_resize_handle_at_pos(start_x, start_y, selected_obj)
            if resize_handle:
                self.temp_polygon_vertices = []
                self.last_mouse_page_pos = None
                self.resize_handle = resize_handle
                if resize_handle == "rotate" and getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char') and isinstance(selected_obj, EditableText):
                    selected_obj = self._isolate_selected_word_span()

                self.resize_start_bbox = selected_obj.bbox
                self.dragged_object = selected_obj
                self.dragged_object.original_bbox = selected_obj.bbox
                self.drag_threshold_passed = True
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self.drag_start_pos = (start_x, start_y)
                self.drag_begin_state = snapshot_object_state(selected_obj)

                if resize_handle == "rotate" and not isinstance(selected_obj, AcroFormField) and not hasattr(selected_obj, 'field_name'):
                    x1, y1, x2, y2 = selected_obj.bbox
                    unrot_cx = (x1 + x2) / 2.0
                    unrot_cy = (y1 + y2) / 2.0
                    vis_cx, vis_cy = self._unrotated_to_visual_page_coords(unrot_cx, unrot_cy, page_index=self.current_page_index)
                    cx, cy = self.page_to_canvas_coords(self.current_page_index, vis_cx, vis_cy)
                    self.rotate_center = (cx, cy)
                    self.rotate_start_angle = getattr(selected_obj, 'rotation', 0.0) % 360.0
                    start_dx = start_x - cx
                    start_dy = start_y - cy
                    self.rotate_pointer_start_angle = math.degrees(math.atan2(start_dy, start_dx))
                return

        unrot_px, unrot_py = self._visual_to_unrotated_page_coords(page_x, page_y)

        if self.tool_mode in ("pen", "highlighter"):
            self.selected_stroke = None
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            color = self.pen_color if self.tool_mode == "pen" else self.highlighter_color
            width = self.pen_width if self.tool_mode == "pen" else self.highlighter_width
            opacity = 1.0 if self.tool_mode == "pen" else self.highlighter_opacity
            self.temp_stroke = EditableStroke(
                points=[(unrot_px, unrot_py)],
                stroke_color=color,
                stroke_width=width,
                opacity=opacity,
                tool_type=self.tool_mode,
                page_number=self.current_page_index,
                is_new=True
            )
            self.pdf_view.queue_draw()
            return
        elif self.tool_mode == "add_ellipse":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_shape = EditableShape(
                shape_type=EditableShape.SHAPE_ELLIPSE,
                bbox=(unrot_px, unrot_py, unrot_px, unrot_py),
                fill_color=self.next_shape_fill,
                stroke_color=self.next_shape_stroke,
                stroke_width=self.next_shape_stroke_width,
                page_number=self.current_page_index,
                is_new=True,
                is_transparent=self.next_shape_transparent
            )
            return
        elif self.tool_mode == "add_rectangle":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_shape = EditableShape(
                shape_type=EditableShape.SHAPE_RECTANGLE,
                bbox=(unrot_px, unrot_py, unrot_px, unrot_py),
                fill_color=self.next_shape_fill,
                stroke_color=self.next_shape_stroke,
                stroke_width=self.next_shape_stroke_width,
                page_number=self.current_page_index,
                is_new=True,
                is_transparent=self.next_shape_transparent
            )
            return
        elif self.tool_mode == "add_checkmark":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            color = self.next_shape_stroke if hasattr(self, 'next_shape_stroke') else (0.1, 0.65, 0.25)
            width = max(getattr(self, 'next_shape_stroke_width', 2.5), 2.0)
            self.temp_shape = EditableShape(
                shape_type=EditableShape.SHAPE_CHECKMARK,
                bbox=(unrot_px, unrot_py, unrot_px, unrot_py),
                fill_color=(1, 1, 1),
                stroke_color=color,
                stroke_width=width,
                page_number=self.current_page_index,
                is_new=True,
                is_transparent=True
            )
            return
        elif self.tool_mode == "add_cross":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            color = self.next_shape_stroke if hasattr(self, 'next_shape_stroke') else (0.85, 0.15, 0.15)
            width = max(getattr(self, 'next_shape_stroke_width', 2.5), 2.0)
            self.temp_shape = EditableShape(
                shape_type=EditableShape.SHAPE_CROSS,
                bbox=(unrot_px, unrot_py, unrot_px, unrot_py),
                fill_color=(1, 1, 1),
                stroke_color=color,
                stroke_width=width,
                page_number=self.current_page_index,
                is_new=True,
                is_transparent=True
            )
            return
        elif self.tool_mode == "add_image":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_image_bbox = (unrot_px, unrot_py, unrot_px, unrot_py)
            return
        elif self.tool_mode == "add_stamp":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_stamp_bbox = (unrot_px, unrot_py, unrot_px, unrot_py)
            return
        elif self.tool_mode == "place_signature":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_sig_bbox = (unrot_px, unrot_py, unrot_px, unrot_py)
            self.pdf_view.queue_draw()
            return
        elif self.tool_mode == "clone_patch":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_clone_patch_bbox = (unrot_px, unrot_py, unrot_px, unrot_py)
            self.pdf_view.queue_draw()
            return
        elif self.tool_mode == "redact":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_redact_bbox = (unrot_px, unrot_py, unrot_px, unrot_py)
            self.pdf_view.queue_draw()
            return
        elif self.tool_mode == "form_builder":
            self._close_active_form_field_editor()
            clicked_form_field = self._find_form_field_at_pos(unrot_px, unrot_py)
            if clicked_form_field:
                is_already_selected = (
                    self.selected_form_field is clicked_form_field and
                    getattr(self, '_can_drag_object', None) is not False
                )
                self.select_object(clicked_form_field)
                
                if is_already_selected:
                    self.dragged_object = clicked_form_field
                    self.drag_threshold_passed = False
                    gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                    self.drag_start_pos = (start_x, start_y)
                    self.drag_begin_state = snapshot_object_state(clicked_form_field)
                    if not hasattr(clicked_form_field, 'original_bbox') or not clicked_form_field.original_bbox:
                        clicked_form_field.original_bbox = clicked_form_field.bbox
                    x1, y1, _, _ = clicked_form_field.bbox
                    self.drag_object_start_pos = (x1, y1)
                else:
                    self.dragged_object = None
                    self._can_drag_object = False
                    gesture.set_state(Gtk.EventSequenceState.DENIED)
                self.pdf_view.queue_draw()
                return

            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_form_field_rect = (unrot_px, unrot_py, unrot_px, unrot_py)
            self.selected_form_field = None
            self._update_form_builder_controls_for_selected()
            self.pdf_view.queue_draw()
            return
        elif self.tool_mode == "calibrate":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            self.temp_calibration_line = (unrot_px, unrot_py, unrot_px, unrot_py)
            self.pdf_view.queue_draw()
            return
        elif self.tool_mode in ("measure_distance", "measure_area"):
            clicked_m = self._find_measurement_at_pos(page_x, page_y)
            if clicked_m:
                is_already_selected = (
                    self.selected_measurement is clicked_m and
                    getattr(self, '_can_drag_object', None) is not False
                )
                self.select_object(clicked_m)
                self.temp_polygon_vertices = []
                self.temp_measurement_line = None
                self.temp_measurement_rect = None
                self.last_mouse_page_pos = None
                if is_already_selected:
                    self.dragged_object = clicked_m
                    self.drag_threshold_passed = False
                    gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                    self.drag_start_pos = (start_x, start_y)
                    self.drag_begin_state = snapshot_object_state(clicked_m)
                else:
                    self.dragged_object = None
                    self._can_drag_object = False
                    gesture.set_state(Gtk.EventSequenceState.DENIED)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return

            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.dragging_to_create = True
            self.drag_start_page_pos = (unrot_px, unrot_py)
            if self.tool_mode == "measure_distance":
                self.temp_measurement_line = (unrot_px, unrot_py, unrot_px, unrot_py)
            else:
                self.temp_measurement_rect = (unrot_px, unrot_py, unrot_px, unrot_py)
            self.pdf_view.queue_draw()
            return

        if self.tool_mode in ("drag", "select"):
            self._close_active_form_field_editor()
            curr_selected = self.get_selected_object() if hasattr(self, 'get_selected_object') else (
                getattr(self, 'selected_text', None) or 
                getattr(self, 'selected_image', None) or 
                getattr(self, 'selected_shape', None) or 
                getattr(self, 'selected_stroke', None) or
                getattr(self, 'selected_form_field', None) or
                getattr(self, 'selected_measurement', None)
            )
            target_obj = None
            if curr_selected and hasattr(curr_selected, 'bbox') and curr_selected.bbox:
                bx1, by1, bx2, by2 = curr_selected.bbox
                padding = 4.0 / max(self.zoom_level, 0.001)
                rot = getattr(curr_selected, 'rotation', 0.0) % 360.0
                unrot_x, unrot_y = page_x, page_y
                if rot != 0.0:
                    cx = (bx1 + bx2) / 2.0
                    cy = (by1 + by2) / 2.0
                    unrot_x, unrot_y = pdf_handler.rotate_point(page_x, page_y, cx, cy, -rot)
                if (min(bx1, bx2) - padding) <= unrot_x <= (max(bx1, bx2) + padding) and (min(by1, by2) - padding) <= unrot_y <= (max(by1, by2) + padding):
                    target_obj = curr_selected

            if target_obj is not None:
                can_drag = (getattr(self, '_can_drag_object', None) is not False)
                if not can_drag:
                    self.dragged_object = None
                    gesture.set_state(Gtk.EventSequenceState.DENIED)
                    return
                self.dragged_object = target_obj
            else:
                hit_obj = self._find_any_object_at_pos(page_x, page_y) if hasattr(self, '_find_any_object_at_pos') else (
                    (self._find_text_at_pos(page_x, page_y) if hasattr(self, '_find_text_at_pos') else None) or
                    (self._find_image_at_pos(page_x, page_y) if hasattr(self, '_find_image_at_pos') else None) or
                    (self._find_shape_at_pos(page_x, page_y) if hasattr(self, '_find_shape_at_pos') else None) or
                    (self._find_stroke_at_pos(page_x, page_y) if hasattr(self, '_find_stroke_at_pos') else None) or
                    (self._find_form_field_at_pos(page_x, page_y) if hasattr(self, '_find_form_field_at_pos') else None) or
                    (self._find_measurement_at_pos(page_x, page_y) if hasattr(self, '_find_measurement_at_pos') else None)
                )
                if hit_obj:
                    # First click selects the object, movement is disabled
                    if hasattr(self, 'select_object'):
                        self.select_object(hit_obj)
                    else:
                        self.selected_text = hit_obj if isinstance(hit_obj, EditableText) else None
                        self.selected_image = hit_obj if isinstance(hit_obj, EditableImage) else None
                        self.selected_shape = hit_obj if isinstance(hit_obj, EditableShape) else None
                        self.selected_stroke = hit_obj if isinstance(hit_obj, EditableStroke) else None
                        self.selected_form_field = hit_obj if isinstance(hit_obj, AcroFormField) else None
                    self.dragged_object = None
                    self._can_drag_object = False
                    gesture.set_state(Gtk.EventSequenceState.DENIED)
                    return
                else:
                    self.dragged_object = None
                    gesture.set_state(Gtk.EventSequenceState.DENIED)
                    return
        else:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return

        if self.dragged_object:
            self.drag_threshold_passed = False
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.drag_start_pos = (start_x, start_y)
            orig_lt = getattr(self.dragged_object, 'linked_text', None)
            orig_lp = getattr(self.dragged_object, 'linked_patch', None)
            self.drag_begin_state = snapshot_object_state(self.dragged_object)
            if orig_lt is not None:
                self.drag_begin_state['linked_text'] = orig_lt
            if orig_lp is not None:
                self.drag_begin_state['linked_patch'] = orig_lp
            if orig_lt is not None:
                lt = orig_lt
                orig_lt_patch = getattr(lt, 'linked_patch', None)
                self.linked_drag_begin_state = snapshot_object_state(lt)
                if orig_lt_patch is not None:
                    self.linked_drag_begin_state['linked_patch'] = orig_lt_patch
                self.linked_drag_start_pos = (lt.x, lt.y)
                if not hasattr(lt, 'original_bbox') or not lt.original_bbox:
                    lt.original_bbox = lt.bbox
                if not hasattr(lt, 'original_baseline') or lt.original_baseline is None:
                    lt.original_baseline = getattr(lt, 'baseline', None)

        if self.dragged_object:
            if not hasattr(self.dragged_object, 'original_bbox') or not self.dragged_object.original_bbox:
                self.dragged_object.original_bbox = self.dragged_object.bbox
            if not hasattr(self.dragged_object, 'original_baseline') or self.dragged_object.original_baseline is None:
                self.dragged_object.original_baseline = getattr(self.dragged_object, 'baseline', None)

            x1, y1, _, _ = self.dragged_object.bbox
            self.drag_object_start_pos = (x1, y1)
        else:
            gesture.set_state(Gtk.EventSequenceState.DENIED)

    def on_drag_update(self, gesture, offset_x, offset_y):
        """Update canvas interaction during drag (move/resize objects, text select, or draw strokes)."""
        if self.view_mode:
            if getattr(self, 'dragged_sticky_note', None) and getattr(self, 'sticky_note_start_coords', None):
                dx, dy = self._visual_to_unrotated_delta(offset_x / self.zoom_level, offset_y / self.zoom_level)
                sx, sy = self.sticky_note_start_coords
                self.dragged_sticky_note.x = max(0, sx + dx)
                self.dragged_sticky_note.y = max(0, sy + dy)
                self.pdf_view.queue_draw()
                return

            if self.view_sel_start and self.view_drag_active:
                sx, sy = self.view_sel_start
                dx = offset_x / self.zoom_level
                dy = offset_y / self.zoom_level
                cx = sx + dx
                cy = sy + dy
                self.view_sel_rect = (min(sx, cx), min(sy, cy), max(sx, cx), max(sy, cy))
                self.pdf_view.queue_draw()
            return

        if self.inline_editor_widget is not None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
            
        if self.dragging_to_create:
            delta_x, delta_y = self._visual_to_unrotated_delta(offset_x / self.zoom_level, offset_y / self.zoom_level)
            if getattr(self, 'temp_stroke', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                self.temp_stroke.add_point(current_x, current_y)
                self.pdf_view.queue_draw()
                return
            if self.temp_image_bbox is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                
                if x2 - x1 < 20:
                    x2 = x1 + 20
                if y2 - y1 < 20:
                    y2 = y1 + 20
                    
                self.temp_image_bbox = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_stamp_bbox', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                if x2 - x1 < 10:
                    x2 = x1 + 10
                if y2 - y1 < 10:
                    y2 = y1 + 10
                self.temp_stamp_bbox = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_sig_bbox', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                if x2 - x1 < 10:
                    x2 = x1 + 10
                if y2 - y1 < 10:
                    y2 = y1 + 10
                self.temp_sig_bbox = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_clone_patch_bbox', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                self.temp_clone_patch_bbox = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_redact_bbox', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                self.temp_redact_bbox = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if self.temp_shape:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                
                if x2 - x1 < 10:
                    x2 = x1 + 10
                if y2 - y1 < 10:
                    y2 = y1 + 10
                    
                self.temp_shape.bbox = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_form_field_rect', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y
                if getattr(self, 'form_builder_field_type', 'text') == 'checkbox':
                    side = max(abs(delta_x), abs(delta_y))
                    if side < 16.0:
                        side = 20.0
                    current_x = start_x + (side if delta_x >= 0 else -side)
                    current_y = start_y + (side if delta_y >= 0 else -side)
                
                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)
                
                self.temp_form_field_rect = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_calibration_line', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y

                shift_pressed = False
                try:
                    state = gesture.get_current_event_state()
                    shift_pressed = bool(state & Gdk.ModifierType.SHIFT_MASK)
                except Exception:
                    pass

                if shift_pressed and (abs(delta_x) > 2 or abs(delta_y) > 2):
                    angle = math.atan2(delta_y, delta_x)
                    snap_angle = round(angle / (math.pi / 4)) * (math.pi / 4)
                    dist = math.hypot(delta_x, delta_y)
                    current_x = start_x + dist * math.cos(snap_angle)
                    current_y = start_y + dist * math.sin(snap_angle)

                self.temp_calibration_line = (start_x, start_y, current_x, current_y)
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_measurement_line', None) is not None:
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y

                shift_pressed = False
                try:
                    state = gesture.get_current_event_state()
                    shift_pressed = bool(state & Gdk.ModifierType.SHIFT_MASK)
                except Exception:
                    pass

                if shift_pressed and (abs(delta_x) > 2 or abs(delta_y) > 2):
                    angle = math.atan2(delta_y, delta_x)
                    snap_angle = round(angle / (math.pi / 4)) * (math.pi / 4)
                    dist = math.hypot(delta_x, delta_y)
                    current_x = start_x + dist * math.cos(snap_angle)
                    current_y = start_y + dist * math.sin(snap_angle)

                self.temp_measurement_line = (start_x, start_y, current_x, current_y)
                if abs(delta_x) >= 3.0 or abs(delta_y) >= 3.0:
                    self.temp_polygon_vertices = []
                    self.last_mouse_page_pos = None
                self.pdf_view.queue_draw()
                return
            if getattr(self, 'temp_measurement_rect', None) is not None:
                if abs(delta_x) >= 3.0 or abs(delta_y) >= 3.0:
                    self.temp_polygon_vertices = []
                    self.last_mouse_page_pos = None
                start_x, start_y = self.drag_start_page_pos
                current_x = start_x + delta_x
                current_y = start_y + delta_y

                x1 = min(start_x, current_x)
                y1 = min(start_y, current_y)
                x2 = max(start_x, current_x)
                y2 = max(start_y, current_y)

                self.temp_measurement_rect = (x1, y1, x2, y2)
                self.pdf_view.queue_draw()
                return
            return
        
        if not self.dragged_object:
            return

        if self.resize_handle:
            if self.resize_handle == "rotate":
                self._handle_rotate_update(gesture, offset_x, offset_y)
            else:
                self._handle_resize_update(offset_x, offset_y, gesture=gesture)
            return
        if self.tool_mode not in ("drag", "form_builder", "select"):
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return

        # Drag threshold / deadspace: ignore slight jitter to avoid accidental moves during click or double-click
        if not getattr(self, 'drag_threshold_passed', False):
            if math.hypot(offset_x, offset_y) < 5.0:
                return
            self.drag_threshold_passed = True
            
        delta_x, delta_y = self._visual_to_unrotated_delta(offset_x / self.zoom_level, offset_y / self.zoom_level)

        start_obj_x, start_obj_y = self.drag_object_start_pos
        new_x = start_obj_x + delta_x
        new_y = start_obj_y + delta_y

        orig_bbox = getattr(self.dragged_object, 'original_bbox', self.dragged_object.bbox)
        w = orig_bbox[2] - orig_bbox[0]
        h = orig_bbox[3] - orig_bbox[1]
        
        if isinstance(self.dragged_object, AcroFormField):
            self.dragged_object.rect = (new_x, new_y, new_x + w, new_y + h)
            self._update_form_field_overlay_positions()
            self.selected_form_field = self.dragged_object
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.pdf_view.queue_draw()
            return
        
        self.dragged_object.x = new_x
        self.dragged_object.y = new_y
        self.dragged_object.bbox = (new_x, new_y, new_x + w, new_y + h)
        
        if isinstance(self.dragged_object, EditableText):
            self.dragged_object.baseline = new_y + getattr(self.dragged_object, 'baseline_offset', self.dragged_object.font_size * 0.9)
            self.dragged_object.sync_char_boxes_to_bbox()

            self.selected_text = self.dragged_object
            self.selected_image = None
            self.selected_shape = None
        
        elif isinstance(self.dragged_object, EditableImage):
            self.selected_image = self.dragged_object
            self.selected_text = None
            self.selected_shape = None
            if getattr(self.dragged_object, 'linked_text', None) is not None and hasattr(self, 'linked_drag_start_pos'):
                lt = self.dragged_object.linked_text
                lt_start_x, lt_start_y = self.linked_drag_start_pos
                lt_new_x = lt_start_x + delta_x
                lt_new_y = lt_start_y + delta_y
                lt_orig_bbox = getattr(lt, 'original_bbox', lt.bbox)
                lt_w = lt_orig_bbox[2] - lt_orig_bbox[0]
                lt_h = lt_orig_bbox[3] - lt_orig_bbox[1]
                lt.x = lt_new_x
                lt.y = lt_new_y
                lt.bbox = (lt_new_x, lt_new_y, lt_new_x + lt_w, lt_new_y + lt_h)
                lt.baseline = lt_new_y + getattr(lt, 'baseline_offset', lt.font_size * 0.9)
                lt.sync_char_boxes_to_bbox()
            
        elif isinstance(self.dragged_object, EditableShape):
            self.selected_shape = self.dragged_object
            self.selected_image = None
            self.selected_text = None
            self.selected_stroke = None

        elif isinstance(self.dragged_object, EditableStroke):
            start_points = self.drag_begin_state.get('points', [])
            self.dragged_object.points = [(p[0] + delta_x, p[1] + delta_y) for p in start_points]
            self.dragged_object.recalculate_bbox()
            self.selected_stroke = self.dragged_object
            self.selected_shape = None
            self.selected_image = None
            self.selected_text = None

        elif isinstance(self.dragged_object, MeasurementObject):
            self.dragged_object.set_position(new_x, new_y)
            self.selected_measurement = self.dragged_object
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.selected_form_field = None

        elif isinstance(self.dragged_object, RedactionMark):
            self.dragged_object.set_position(new_x, new_y)
            self.selected_redaction_mark = self.dragged_object
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.selected_form_field = None
            self.selected_measurement = None

        self.pdf_view.queue_draw()

    def _handle_rotate_update(self, gesture, offset_x, offset_y):
        """Handle dynamic rotation update while dragging the stalk rotation handle."""
        if not self.dragged_object or not hasattr(self, 'rotate_center') or not hasattr(self, 'rotate_pointer_start_angle'):
            return

        current_x = self.drag_start_pos[0] + offset_x
        current_y = self.drag_start_pos[1] + offset_y
        cx, cy = self.rotate_center

        cur_dx = current_x - cx
        cur_dy = current_y - cy

        if math.hypot(cur_dx, cur_dy) < 2.0:
            return

        cur_pointer_angle = math.degrees(math.atan2(cur_dy, cur_dx))
        angle_delta = cur_pointer_angle - self.rotate_pointer_start_angle
        new_rot = (self.rotate_start_angle + angle_delta) % 360.0

        # Check Shift key modifier for 15-degree increment snapping
        shift_pressed = False
        try:
            state = gesture.get_current_event_state()
            shift_pressed = bool(state & Gdk.ModifierType.SHIFT_MASK)
        except Exception:
            pass

        if shift_pressed:
            new_rot = round(new_rot / 15.0) * 15.0 % 360.0
        else:
            new_rot = round(new_rot, 1) % 360.0

        if hasattr(self.dragged_object, 'set_rotation'):
            self.dragged_object.set_rotation(new_rot)
        else:
            self.dragged_object.rotation = new_rot

        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("status_object_rotation", f"{new_rot:.1f}°"))

        if hasattr(self, '_update_rotation_controls'):
            self._update_rotation_controls(self.dragged_object)

        self.pdf_view.queue_draw()

    def _handle_resize_update(self, offset_x, offset_y, gesture=None):
        """Handle resize update."""
        if not self.resize_handle or not self.resize_start_bbox or not self.dragged_object:
            return

        shift_pressed = False
        if gesture is not None:
            try:
                state = gesture.get_current_event_state()
                shift_pressed = bool(state & Gdk.ModifierType.SHIFT_MASK)
            except Exception:
                pass
        if not shift_pressed and getattr(self, '_shift_pressed', False):
            shift_pressed = True

        delta_x, delta_y = self._visual_to_unrotated_delta(offset_x / self.zoom_level, offset_y / self.zoom_level)

        calc_geom = getattr(self, 'calculate_resize_geometry', None)
        if calc_geom is not None:
            new_x1, new_y1, new_x2, new_y2 = calc_geom(
                start_bbox=self.resize_start_bbox,
                handle_name=self.resize_handle,
                delta_x=delta_x,
                delta_y=delta_y,
                shift_pressed=shift_pressed,
                min_size=10.0
            )
        else:
            new_x1, new_y1, new_x2, new_y2 = PdfEditorWindow.calculate_resize_geometry(
                self,
                start_bbox=self.resize_start_bbox,
                handle_name=self.resize_handle,
                delta_x=delta_x,
                delta_y=delta_y,
                shift_pressed=shift_pressed,
                min_size=10.0
            )

        if isinstance(self.dragged_object, EditableStroke):
            start_points = self.drag_begin_state.get('points', self.dragged_object.points)
            self.dragged_object.scale_to_bbox((new_x1, new_y1, new_x2, new_y2), self.resize_start_bbox, start_points)
        elif isinstance(self.dragged_object, AcroFormField):
            if getattr(self.dragged_object, 'field_type', None) in ("checkbox", "radio"):
                w = new_x2 - new_x1
                h = new_y2 - new_y1
                side = max(w, h, 16.0)
                if "w" in self.resize_handle:
                    new_x1 = new_x2 - side
                else:
                    new_x2 = new_x1 + side
                if "n" in self.resize_handle:
                    new_y1 = new_y2 - side
                else:
                    new_y2 = new_y1 + side
            self.dragged_object.rect = (new_x1, new_y1, new_x2, new_y2)
            self._update_form_field_overlay_positions()
        else:
            self.dragged_object.bbox = (new_x1, new_y1, new_x2, new_y2)
            self.dragged_object.x = new_x1
            self.dragged_object.y = new_y1

        self.pdf_view.queue_draw()

    def on_drag_end(self, gesture, offset_x, offset_y):
        """Finalize canvas drag interaction, committing created or modified objects to undo history."""
        self._can_drag_object = None
        if self.view_mode:
            if getattr(self, 'dragged_sticky_note', None):
                note = self.dragged_sticky_note
                start_coords = self.sticky_note_start_coords
                self.dragged_sticky_note = None
                self.sticky_note_start_coords = None
                if start_coords and (note.x != start_coords[0] or note.y != start_coords[1]):
                    command = MoveStickyNoteCommand(self, note, start_coords, (note.x, note.y))
                    self.undo_manager.add_command(command)
                    self.document_modified = True
                    self._update_ui_state()
                    self.pdf_view.queue_draw()
                return

            self.view_drag_active = False
            if self.view_sel_rect:
                x1, y1, x2, y2 = self.view_sel_rect
                if (x2 - x1) > 2 and (y2 - y1) > 2:
                    self.view_selected_text = pdf_handler.get_text_in_rect(
                        self.doc, self.current_page_index, (x1, y1, x2, y2))
                else:
                    self.view_sel_rect = None
                    self.view_selected_text = ""
            self._update_ui_state()
            self.pdf_view.queue_draw()
            return

        if self.dragging_to_create:
            self.dragging_to_create = False
            if getattr(self, 'temp_stroke', None) is not None:
                stroke_to_add = self.temp_stroke
                self.temp_stroke = None
                if stroke_to_add.points:
                    rdp_tol = min(0.5, 0.5 / max(getattr(self, 'zoom_level', 1.0), 1.0))
                    stroke_to_add.simplify(tolerance=rdp_tol)
                    stroke_to_add.recalculate_bbox()
                    stroke_to_add.original_bbox = stroke_to_add.bbox
                    self.selected_stroke = stroke_to_add
                    self.selected_text = None
                    self.selected_image = None
                    self.selected_shape = None

                    command = AddObjectCommand(self, stroke_to_add)
                    command.execute()
                    self.undo_manager.add_command(command)
                    self.document_modified = True
                    self._refresh_thumbnail(self.current_page_index)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return

            if self.temp_shape:
                x1, y1, x2, y2 = self.temp_shape.bbox
                if (x2 - x1) < 10 or (y2 - y1) < 10:
                    if self.temp_shape.shape_type in (EditableShape.SHAPE_CHECKMARK, EditableShape.SHAPE_CROSS):
                        cx, cy = self.drag_start_page_pos
                        size = 24.0
                        self.temp_shape.bbox = (cx - size / 2.0, cy - size / 2.0, cx + size / 2.0, cy + size / 2.0)
                        self.temp_shape.x = self.temp_shape.bbox[0]
                        self.temp_shape.y = self.temp_shape.bbox[1]
                    else:
                        self.temp_shape = None
                        self.pdf_view.queue_draw()
                        return
                
                self.temp_shape.original_bbox = self.temp_shape.bbox
                self.selected_shape = self.temp_shape
                self.selected_text = None
                self.selected_image = None
                self.selected_stroke = None
                
                command = AddObjectCommand(self, self.temp_shape)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                
                self.temp_shape.is_baked = True
                self.temp_shape = None
                self._refresh_thumbnail(self.current_page_index)
                
                self.pdf_view.queue_draw()
                self._update_ui_state()
            elif self.temp_image_bbox:
                x1, y1, x2, y2 = self.temp_image_bbox
                self.temp_image_bbox = None
                drag_w = abs(x2 - x1)
                drag_h = abs(y2 - y1)
                min_x = min(x1, x2)
                min_y = min(y1, y2)

                if drag_w < 12 or drag_h < 12:
                    self.pdf_view.queue_draw()
                    if getattr(self, '_image_dialog_open', False) is not True:
                        cx, cy = self.drag_start_page_pos if getattr(self, 'drag_start_page_pos', None) else (min_x, min_y)
                        self._handle_add_image_click(cx, cy, page_index=self.current_page_index)
                    return

                filter_img = Gtk.FileFilter(name=_("image_filter_label"))
                for mime in ["image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif", "image/tiff"]:
                    filter_img.add_mime_type(mime)
                for pat in ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp", "*.gif", "*.tiff", "*.PNG", "*.JPG", "*.JPEG"]:
                    filter_img.add_pattern(pat)

                def on_image_selected(file):
                    self._image_dialog_open = False
                    if file:
                        try:
                            with open(file.get_path(), 'rb') as f:
                                image_bytes = f.read()

                            if not image_bytes:
                                return

                            img_w, img_h = pdf_handler.get_image_pixel_dimensions(image_bytes)
                            aspect_ratio = float(img_w) / float(img_h) if img_h > 0 else 1.0

                            box_w = max(1.0, float(drag_w))
                            box_h = max(1.0, float(drag_h))

                            if (box_w / box_h) > aspect_ratio:
                                fit_h = box_h
                                fit_w = fit_h * aspect_ratio
                            else:
                                fit_w = box_w
                                fit_h = fit_w / aspect_ratio

                            fx0 = min_x + (box_w - fit_w) / 2.0
                            fy0 = min_y + (box_h - fit_h) / 2.0
                            final_bbox = (round(fx0, 2), round(fy0, 2), round(fx0 + fit_w, 2), round(fy0 + fit_h, 2))

                            image_obj = EditableImage(
                                bbox=final_bbox,
                                page_number=self.current_page_index,
                                xref=None,
                                image_bytes=image_bytes,
                                is_new=True
                            )

                            self.selected_image = image_obj
                            self.selected_text = None
                            self.selected_shape = None
                            self.selected_stroke = None
                            self.selected_form_field = None
                            self.selected_measurement = None
                            self.tool_mode = "select"

                            command = AddObjectCommand(self, image_obj)
                            command.execute()
                            self.undo_manager.add_command(command)
                            self.document_modified = True
                            self._refresh_thumbnail(self.current_page_index)
                            self.pdf_view.queue_draw()
                            self._update_ui_state()
                        except Exception as e:
                            show_error_dialog(self, _("image_add_error", e), _("image_error_title"))

                    self.pdf_view.queue_draw()

                self._image_dialog_open = True
                show_open_file_dialog(
                    self,
                    _("image_select_title"),
                    filters=[filter_img],
                    callback=on_image_selected
                )
            elif getattr(self, 'temp_stamp_bbox', None) is not None:
                x1, y1, x2, y2 = self.temp_stamp_bbox
                self.temp_stamp_bbox = None
                active_stamp = getattr(self, 'active_stamp', None)
                if not active_stamp and hasattr(self, 'stamp_library') and self.stamp_library:
                    active_stamp = self.stamp_library.get_active_stamp()

                if active_stamp and active_stamp.image_bytes:
                    if (x2 - x1) < 12 or (y2 - y1) < 12:
                        cx, cy = self.drag_start_page_pos
                        w = getattr(active_stamp, 'default_width', 160.0)
                        h = getattr(active_stamp, 'default_height', 54.0)
                        final_bbox = (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)
                    else:
                        final_bbox = (x1, y1, x2, y2)

                    def do_place_stamp():
                        stamp_obj = EditableImage(
                            bbox=final_bbox,
                            page_number=self.current_page_index,
                            xref=None,
                            image_bytes=active_stamp.image_bytes,
                            is_new=True,
                            is_stamp=True,
                            stamp_name=active_stamp.name,
                        )

                        self.selected_image = stamp_obj
                        self.selected_text = None
                        self.selected_shape = None
                        self.selected_stroke = None

                        command = AddObjectCommand(self, stamp_obj)
                        command.execute()
                        self.undo_manager.add_command(command)
                        self.document_modified = True
                        self._refresh_thumbnail(self.current_page_index)
                        if hasattr(self, 'status_label') and self.status_label:
                            self.status_label.set_text(_("stamp_placed_status").format(active_stamp.name))
                        self._update_ui_state()
                        self.pdf_view.queue_draw()

                    if active_stamp.has_password():
                        verify_dlg = StampVerificationDialog(
                            self,
                            active_stamp,
                            on_verified_callback=do_place_stamp,
                            on_cancelled_callback=lambda: self.pdf_view.queue_draw()
                        )
                        verify_dlg.present()
                    else:
                        do_place_stamp()

                self.pdf_view.queue_draw()
                return
            elif getattr(self, 'temp_sig_bbox', None) is not None:
                x1, y1, x2, y2 = self.temp_sig_bbox
                self.temp_sig_bbox = None
                w = x2 - x1
                h = y2 - y1
                if w < 10 or h < 10:
                    w, h = 180.0, 50.0
                    x2 = x1 + w
                    y2 = y1 + h
                initial_box = (x1, y1, w, h)
                self.tool_mode = "select"
                self._update_ui_state()
                self.pdf_view.queue_draw()

                from .signature_dialog import DigitalSignatureDialog
                if getattr(self, "_digital_sig_dialog", None) is not None:
                    try:
                        self._digital_sig_dialog.destroy()
                    except Exception:
                        pass
                self._digital_sig_dialog = DigitalSignatureDialog(
                    parent_window=self,
                    page_count=self.doc.page_count,
                    current_page=self.current_page_index,
                    initial_box=initial_box,
                    on_sign_callback=self._execute_sign_from_dialog,
                    on_draw_canvas_requested=self._on_draw_signature_on_canvas_requested,
                )
                self._digital_sig_dialog.connect("close-request", self._on_digital_sig_dialog_closed)
                self._digital_sig_dialog.present()
                return
            elif getattr(self, 'temp_clone_patch_bbox', None) is not None:
                x1, y1, x2, y2 = self.temp_clone_patch_bbox
                self.temp_clone_patch_bbox = None
                w = abs(x2 - x1)
                h = abs(y2 - y1)
                min_x = min(x1, x2)
                min_y = min(y1, y2)
                max_x = max(x1, x2)
                max_y = max(y1, y2)
                if w >= 4.0 and h >= 4.0 and self.doc:
                    target_page = getattr(self, 'drag_start_page_index', self.current_page_index)
                    patch_bytes = pdf_handler.extract_page_region_patch(
                        self.doc,
                        target_page,
                        (min_x, min_y, max_x, max_y),
                        dpi=300
                    )
                    if patch_bytes:
                        self.last_captured_patch = {
                            "image_bytes": patch_bytes,
                            "bbox": (min_x, min_y, max_x, max_y),
                            "page_number": target_page,
                            "dpi": 300,
                        }
                        patch_obj = PatchObject(
                            bbox=(min_x, min_y, max_x, max_y),
                            page_number=target_page,
                            image_bytes=patch_bytes,
                            is_new=True,
                            opacity=1.0,
                        )
                        command = AddObjectCommand(self, patch_obj)
                        command.execute()
                        if getattr(self, 'undo_manager', None):
                            self.undo_manager.add_command(command)

                        self.selected_image = patch_obj
                        self.selected_text = None
                        self.selected_shape = None
                        self.selected_stroke = None
                        self.selected_form_field = None
                        self.selected_measurement = None

                        self.tool_mode = "select"
                        self.document_modified = True
                        if hasattr(self, '_refresh_thumbnail'):
                            self._refresh_thumbnail(target_page)
                        if hasattr(self, 'status_label') and self.status_label:
                            self.status_label.set_text(_("patch_placed_status"))
                    else:
                        if hasattr(self, 'status_label') and self.status_label:
                            self.status_label.set_text(_("patch_capture_failed"))
                elif getattr(self, 'last_captured_patch', None) and (w < 4.0 or h < 4.0) and self.doc:
                    target_page = getattr(self, 'drag_start_page_index', self.current_page_index)
                    cx, cy = getattr(self, 'drag_start_page_pos', (min_x, min_y))
                    patch_data = self.last_captured_patch
                    orig_b = patch_data["bbox"]
                    pw = orig_b[2] - orig_b[0]
                    ph = orig_b[3] - orig_b[1]
                    stamp_bbox = (cx - pw / 2.0, cy - ph / 2.0, cx + pw / 2.0, cy + ph / 2.0)
                    patch_obj = PatchObject(
                        bbox=stamp_bbox,
                        page_number=target_page,
                        image_bytes=patch_data["image_bytes"],
                        is_new=True,
                        opacity=1.0,
                    )
                    command = AddObjectCommand(self, patch_obj)
                    command.execute()
                    if getattr(self, 'undo_manager', None):
                        self.undo_manager.add_command(command)

                    self.selected_image = patch_obj
                    self.selected_text = None
                    self.selected_shape = None
                    self.selected_stroke = None
                    self.selected_form_field = None
                    self.selected_measurement = None

                    self.tool_mode = "select"
                    self.document_modified = True
                    if hasattr(self, '_refresh_thumbnail'):
                        self._refresh_thumbnail(target_page)
                    if hasattr(self, 'status_label') and self.status_label:
                        self.status_label.set_text(_("patch_pasted_status"))
                self.pdf_view.queue_draw()
                self._update_ui_state()
                return
            elif getattr(self, 'temp_redact_bbox', None) is not None:
                x1, y1, x2, y2 = self.temp_redact_bbox
                self.temp_redact_bbox = None
                w = abs(x2 - x1)
                h = abs(y2 - y1)
                min_x = min(x1, x2)
                min_y = min(y1, y2)
                max_x = max(x1, x2)
                max_y = max(y1, y2)
                if w >= 4.0 and h >= 4.0 and self.doc:
                    target_page = getattr(self, 'drag_start_page_index', self.current_page_index)
                    fill_c = getattr(self, 'redact_default_fill', (0.0, 0.0, 0.0))
                    text_c = getattr(self, 'redact_default_text_color', (1.0, 1.0, 1.0))
                    overlay_t = getattr(self, 'redact_default_overlay', "[REDACTED]")
                    mark = RedactionMark(
                        page_number=target_page,
                        bbox=(min_x, min_y, max_x, max_y),
                        fill_color=fill_c,
                        overlay_text=overlay_t,
                        text_color=text_c,
                    )
                    from .undo_manager import AddRedactionCommand
                    cmd = AddRedactionCommand(self, mark)
                    cmd.execute()
                    if self.undo_manager:
                        self.undo_manager.record(cmd)
                    self.selected_redaction_mark = mark
                    self.tool_mode = "select"
                    self._update_ui_state()
                    self.pdf_view.queue_draw()
                    self._open_redaction_popover(mark)
                    return
                self.pdf_view.queue_draw()
                return
            elif getattr(self, 'temp_form_field_rect', None) is not None:
                x1, y1, x2, y2 = self.temp_form_field_rect
                self.temp_form_field_rect = None
                w = x2 - x1
                h = y2 - y1
                if w < 10 or h < 10:
                    if getattr(self, 'form_builder_field_type', 'text') == 'checkbox':
                        w, h = 20.0, 20.0
                    else:
                        w, h = 140.0, 26.0
                    x2 = x1 + w
                    y2 = y1 + h
                elif getattr(self, 'form_builder_field_type', 'text') == 'checkbox':
                    side = max(w, h)
                    w, h = side, side
                    x2 = x1 + w
                    y2 = y1 + h

                rect = (x1, y1, x2, y2)
                self._create_new_form_field(rect)
                self.pdf_view.queue_draw()
                self._update_ui_state()
            elif getattr(self, 'temp_calibration_line', None) is not None:
                line = self.temp_calibration_line
                sx, sy, ex, ey = line
                measured_len = math.hypot(ex - sx, ey - sy)
                if measured_len < 5.0:
                    self.temp_calibration_line = None
                else:
                    active_calib = self.get_scale_calibration(self.current_page_index) if hasattr(self, 'get_scale_calibration') else None
                    mm_len = (measured_len * 25.4) / 72.0
                    status_text = f"{measured_len:.1f} pt ({mm_len:.1f} mm)"
                    if active_calib and active_calib.points_per_unit > 0:
                        status_text += f" | {active_calib.format_distance(measured_len)}"
                    if hasattr(self, 'status_label') and self.status_label:
                        self.status_label.set_text(status_text)
                self.pdf_view.queue_draw()
                self._update_ui_state()
            elif getattr(self, 'temp_measurement_line', None) is not None:
                line = self.temp_measurement_line
                self.temp_measurement_line = None
                self.temp_polygon_vertices = []
                self.last_mouse_page_pos = None
                sx, sy, ex, ey = line
                measured_len = math.hypot(ex - sx, ey - sy)
                if measured_len >= 5.0:
                    meas = MeasurementObject(
                        measurement_type=MeasurementObject.TYPE_DISTANCE,
                        points=[(sx, sy), (ex, ey)],
                        page_number=self.current_page_index
                    )
                    cmd = AddMeasurementCommand(self, meas)
                    cmd.execute()
                    self.undo_manager.add_command(cmd)
                self.pdf_view.queue_draw()
                self._update_ui_state()
            elif getattr(self, 'temp_measurement_rect', None) is not None:
                rect = self.temp_measurement_rect
                self.temp_measurement_rect = None
                self.temp_polygon_vertices = []
                self.last_mouse_page_pos = None
                x1, y1, x2, y2 = rect
                w = abs(x2 - x1)
                h = abs(y2 - y1)
                if w >= 5.0 and h >= 5.0:
                    min_x, max_x = min(x1, x2), max(x1, x2)
                    min_y, max_y = min(y1, y2), max(y1, y2)
                    vertices = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
                    meas = MeasurementObject(
                        measurement_type=MeasurementObject.TYPE_AREA,
                        points=vertices,
                        page_number=self.current_page_index
                    )
                    cmd = AddMeasurementCommand(self, meas)
                    cmd.execute()
                    self.undo_manager.add_command(cmd)
                self.pdf_view.queue_draw()
                self._update_ui_state()
            return
        
        if not self.dragged_object or not hasattr(self, 'drag_begin_state'):
            if self.dragged_object:
                self.dragged_object = None
            self._can_drag_object = None
            self.resize_handle = None
            self.resize_start_bbox = None
            if hasattr(self, 'rotate_center'):
                del self.rotate_center
            if hasattr(self, 'rotate_start_angle'):
                del self.rotate_start_angle
            if hasattr(self, 'rotate_pointer_start_angle'):
                del self.rotate_pointer_start_angle
            self.drag_threshold_passed = False
            self.pdf_view.queue_draw()
            return

        self.commit_pending_format_change()

        old_properties = self.drag_begin_state
        
        if isinstance(self.dragged_object, EditableText):
            self.dragged_object.sync_char_boxes_to_bbox()
        new_properties = snapshot_object_state(self.dragged_object)

        dragged_obj_ref = self.dragged_object
        self.dragged_object = None
        self._can_drag_object = None
        self.resize_handle = None
        self.resize_start_bbox = None
        del self.drag_begin_state
        if hasattr(self, 'rotate_center'):
            del self.rotate_center
        if hasattr(self, 'rotate_start_angle'):
            del self.rotate_start_angle
        if hasattr(self, 'rotate_pointer_start_angle'):
            del self.rotate_pointer_start_angle

        if isinstance(dragged_obj_ref, AcroFormField):
            if not getattr(self, 'resize_handle', None) and not getattr(self, 'drag_threshold_passed', False):
                self.drag_threshold_passed = False
                self.selected_form_field = dragged_obj_ref
                self._update_ui_state()
                self.pdf_view.queue_draw()
                return
            old_rect = old_properties.get('rect', getattr(dragged_obj_ref, 'rect', None))
            new_rect = getattr(dragged_obj_ref, 'rect', None)
            if old_rect and new_rect and old_rect != new_rect:
                command = MoveResizeFormFieldCommand(self, dragged_obj_ref, old_rect, new_rect)
                command.execute()
                self.undo_manager.add_command(command)
            self.selected_form_field = dragged_obj_ref
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self._update_form_builder_controls_for_selected()
            self._update_ui_state()
            self.pdf_view.queue_draw()
            return

        if isinstance(dragged_obj_ref, RedactionMark):
            if old_properties != new_properties:
                from .undo_manager import EditRedactionCommand
                command = EditRedactionCommand(self, dragged_obj_ref, old_properties, new_properties)
                self.undo_manager.add_command(command)
                self.document_modified = True
            self.selected_redaction_mark = dragged_obj_ref
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.selected_form_field = None
            self.selected_measurement = None
            self._update_ui_state()
            self.pdf_view.queue_draw()
            return
        
        rot_changed = (old_properties.get('rotation', 0.0) != new_properties.get('rotation', 0.0))
        is_rotating = hasattr(self, 'rotate_center') or rot_changed
        if not getattr(self, 'resize_handle', None) and not is_rotating and not getattr(self, 'drag_threshold_passed', False):
            for k, v in old_properties.items():
                setattr(dragged_obj_ref, k, v)
            if hasattr(dragged_obj_ref, 'sync_char_boxes_to_bbox'):
                dragged_obj_ref.sync_char_boxes_to_bbox()
            self.drag_threshold_passed = False
            self.pdf_view.queue_draw()
            return

        if abs(offset_x) < 1 and abs(offset_y) < 1 and not rot_changed:
            self.pdf_view.queue_draw()
            return

        if rot_changed:
            old_rot = old_properties.get('rotation', 0.0)
            new_rot = new_properties.get('rotation', 0.0)
            command = RotateObjectCommand(self, dragged_obj_ref, old_rot, new_rot)
            command.execute()
            self.undo_manager.add_command(command)
        else:
            print(_("dbg_creating_drag_command"))
            cmd1 = EditObjectCommand(self, dragged_obj_ref, old_properties, new_properties)
            lt = getattr(dragged_obj_ref, 'linked_text', None)
            lt_old_props = getattr(self, 'linked_drag_begin_state', None)
            if hasattr(self, 'linked_drag_begin_state'):
                del self.linked_drag_begin_state
            if hasattr(self, 'linked_drag_start_pos'):
                del self.linked_drag_start_pos

            if lt and lt_old_props and lt in getattr(self, 'editable_texts', []):
                cmd2 = EditObjectCommand(self, lt, lt_old_props, snapshot_object_state(lt))
                command = CompositeCommand(self, [cmd1, cmd2])
            else:
                command = cmd1
            command.execute()
            self.undo_manager.add_command(command)

        if isinstance(dragged_obj_ref, EditableText):
            self.selected_text = dragged_obj_ref
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.pending_format_change_obj = self.selected_text
            self.before_format_change_state = snapshot_object_state(self.selected_text)
            self._update_text_format_controls(self.selected_text)
        elif isinstance(dragged_obj_ref, EditableImage):
            self.selected_image = dragged_obj_ref
            self.selected_text = None
            self.selected_shape = None
            self.selected_stroke = None
        elif isinstance(dragged_obj_ref, EditableShape):
            self.selected_shape = dragged_obj_ref
            self.selected_text = None
            self.selected_image = None
            self.selected_stroke = None
        elif isinstance(dragged_obj_ref, EditableStroke):
            self.selected_stroke = dragged_obj_ref
            self.selected_shape = None
            self.selected_text = None
            self.selected_image = None

        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(self.current_page_index)
        self.drag_threshold_passed = False
        self._update_ui_state()
        self.pdf_view.queue_draw()

    def insert_symbol_or_emoji(self, symbol, is_emoji=False):
        """Insert symbol into active text block or create full-color emoji stamp on document."""
        if getattr(self, 'inline_editor_widget', None) is not None and getattr(self, 'inline_text_view', None) is not None:
            buf = self.inline_text_view.get_buffer()
            buf.insert_at_cursor(symbol)
            self.inline_text_view.grab_focus()
            return

        if is_emoji and self.doc and self.current_pdf_page_width > 0:
            try:
                png_bytes = render_emoji_to_png_bytes(symbol, size=96)
                page_w_unzoomed = self.current_pdf_page_width / self.zoom_level
                page_h_unzoomed = self.current_pdf_page_height / self.zoom_level
                stamp_size = 32.0
                stamp_x = max(20.0, (page_w_unzoomed - stamp_size) / 2.0)
                stamp_y = max(20.0, (page_h_unzoomed - stamp_size) / 2.0)

                emoji_obj = EditableImage(
                    bbox=(stamp_x, stamp_y, stamp_x + stamp_size, stamp_y + stamp_size),
                    page_number=self.current_page_index,
                    xref=None,
                    image_bytes=png_bytes,
                    is_new=True
                )
                self.selected_image = emoji_obj
                self.selected_text = None
                self.selected_shape = None
                if hasattr(self, 'selected_stroke'):
                    self.selected_stroke = None

                command = AddObjectCommand(self, emoji_obj)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self._refresh_thumbnail(self.current_page_index)
                self.pdf_view.queue_draw()
                self._update_ui_state()
                self.status_label.set_text(f"Added emoji stamp: {symbol}")
                return
            except Exception as e:
                print(f"Error creating emoji stamp: {e}")

        display = Gdk.Display.get_default()
        if display:
            clipboard = display.get_clipboard()
            clipboard.set(symbol)

        self.status_label.set_text(_("symbol_copied", symbol))

    def _on_quick_guide_activated(self, action, param):
        """Display the interactive quick user guide dialog."""
        dialog = QuickGuideDialog(self)
        dialog.present()

    def _update_undo_redo_buttons(self, *args):
        """Sync undo/redo toolbar button sensitivity with UndoManager stacks."""
        has_doc = self.doc is not None
        can_undo = has_doc and bool(getattr(self.undo_manager, "undo_stack", []))
        can_redo = has_doc and bool(getattr(self.undo_manager, "redo_stack", []))
        if hasattr(self, 'undo_button') and self.undo_button:
            self.undo_button.set_sensitive(can_undo)
        if hasattr(self, 'redo_button') and self.redo_button:
            self.redo_button.set_sensitive(can_redo)
        if self.lookup_action("undo"):
            self.lookup_action("undo").set_enabled(can_undo)
        if self.lookup_action("redo"):
            self.lookup_action("redo").set_enabled(can_redo)

    def _refresh_thumbnail(self, page_index):
        """Regenerate and replace the thumbnail pixbuf for a modified page.
        
        Unsaved in-memory changes are rendered for immediate UI preview without
        corrupting or overwriting the clean on-disk thumbnail cache.
        """
        if not self.doc or not (0 <= page_index < pdf_handler.get_page_count(self.doc)):
            return
        try:
            gen_id = getattr(self, '_thumb_generation_id', None)
            if gen_id is not None:
                pdf_handler.cancel_thumbnail_async(gen_id, page_index)

            thumb_w = 100 if getattr(self, 'is_eco_mode', False) else 150
            thumb = pdf_handler.generate_thumbnail(
                self.doc, page_index, target_width=thumb_w,
                filepath=getattr(self._active_session, 'pdf_path', None),
                save_to_disk=False
            )
            if thumb and self.pages_model:
                n = self.pages_model.get_n_items()
                if page_index < n:
                    item = self.pages_model.get_item(page_index)
                    if item and getattr(item, 'index', None) == page_index:
                        item.thumbnail = thumb
                        GLib.idle_add(self._sync_thumbnail_selection)
                        return
                for i in range(n):
                    item = self.pages_model.get_item(i)
                    if item and getattr(item, 'index', None) == page_index:
                        item.thumbnail = thumb
                        GLib.idle_add(self._sync_thumbnail_selection)
                        break
        except Exception as e:
            print(f"Warning: Could not refresh thumbnail for page {page_index + 1}: {e}")
    
    def commit_pending_format_change(self):
        """Record pending text/shape style modifications into undo history."""
        if hasattr(self, '_commit_pending_form_field_edit'):
            self._commit_pending_form_field_edit()

        target_obj = getattr(self, 'pending_format_change_obj', None)
        before_state = getattr(self, 'before_format_change_state', None)
        self.pending_format_change_obj = None
        self.before_format_change_state = None

        if not target_obj or not before_state:
            return

        # An object that has been deleted or is not part of the active page collections
        # must never trigger an EditObjectCommand.
        active = False
        for attr in ('editable_texts', 'editable_shapes', 'editable_images', 'editable_strokes'):
            coll = getattr(self, attr, None)
            if coll and target_obj in coll:
                active = True
                break
        if not active:
            return

        current_state = snapshot_object_state(target_obj)

        # Ignore internal runtime/render state flags that do not represent user formatting changes
        ignore_keys = {
            '_ghost_redacted', 'is_baked', 'selected', 'editing', 'dragging',
            '_cached_layout', '_orig_page_text', 'drag_start_x', 'drag_start_y',
            'is_new', 'modified'
        }

        has_changed = False
        all_keys = set(before_state.keys()).union(current_state.keys())
        for k in all_keys:
            if k in ignore_keys or k.startswith('_'):
                continue
            if before_state.get(k) != current_state.get(k):
                has_changed = True
                break

        if has_changed:
            print(_("dbg_format_change_saved"))
            command = EditObjectCommand(self, target_obj, before_state, current_state)
            command.execute()
            self.undo_manager.add_command(command)

    def on_new_clicked(self, widget=None):
        """Prompt user for dimensions and initialize a new empty PDF document in a tab."""
        def on_create(width_pt, height_pt, num_pages):
            doc, error_msg = pdf_handler.create_new_pdf(width=width_pt, height=height_pt, num_pages=num_pages)

            if error_msg:
                show_error_dialog(self, error_msg)
                return

            if doc:
                if self._active_session is not None and self._active_session.doc is not None:
                    sess = self.create_session()
                    self.add_session(sess, switch_to=True)
                else:
                    sess = self._active_session or self.create_session()
                    if sess not in self.sessions:
                        self.add_session(sess, switch_to=True)
                    else:
                        sess.close()

                sess.doc = doc
                sess.pdf_path = None
                sess.original_file_path = None
                sess.current_page_index = 0
                sess.is_modified = True
                sess.page_objects_cache.clear()
                sess.editable_texts.clear()
                sess.editable_shapes.clear()
                sess.editable_images.clear()
                sess.editable_strokes.clear()
                sess.form_fields.clear()
                if sess.undo_manager:
                    sess.undo_manager.clear()

                self.set_active_session(sess)
                self.set_title(f"{constants.APP_NAME} - {sess.display_title}")
                self._update_tab_title(sess)
                if hasattr(self, 'stack') and self.stack:
                    self.stack.set_visible_child_name("editor")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_visible(True)

                self._load_thumbnails(sess)
                self._load_page(0, reload_objects=True)
                self.status_label.set_text(_("status_new_doc_created"))
                self._update_ui_state()

        show_new_document_dialog(self, on_create)

    def request_language_change(self, target_code: str):
        """Unified language change handler with multi-tab unsaved changes guard and restart confirmation."""
        current_lang = get_language()
        if target_code == current_lang:
            return

        modified_sessions = [s for s in self.sessions if s and s.is_modified and s.doc is not None]
        if modified_sessions:
            from .ui_components import show_confirm_dialog
            if not show_confirm_dialog(
                self,
                _("unsaved_changes"),
                _("unsaved_title"),
                destructive=False,
            ):
                if hasattr(self, 'action_change_language'):
                    self.action_change_language.set_state(GLib.Variant.new_string(current_lang))
                self._sync_welcome_view_language(current_lang)
                return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=_("lang_restart_title") + "\n\n" + _("lang_restart_msg"),
        )

        def on_response(d, response_id):
            d.destroy()
            if response_id == Gtk.ResponseType.OK:
                if hasattr(self, 'action_change_language'):
                    self.action_change_language.set_state(GLib.Variant.new_string(target_code))
                self._sync_welcome_view_language(target_code)
                set_language(target_code)
            else:
                if hasattr(self, 'action_change_language'):
                    self.action_change_language.set_state(GLib.Variant.new_string(current_lang))
                self._sync_welcome_view_language(current_lang)

        dialog.connect("response", on_response)
        dialog.present()

    def _sync_welcome_view_language(self, lang_code: str):
        if hasattr(self, 'stack') and self.stack:
            welcome_view = self.stack.get_child_by_name("welcome")
            if welcome_view and hasattr(welcome_view, "update_language_display"):
                welcome_view.update_language_display(lang_code)

    def do_close_request(self):
        """Prompt to save unsaved changes in all open tabs before closing the window."""
        if getattr(self, 'is_saving', False) is True:
            self.wait_for_save()

        if getattr(self, '_zoom_debounce_timer', None) is not None:
            try:
                GLib.source_remove(self._zoom_debounce_timer)
            except Exception:
                pass
            self._zoom_debounce_timer = None

        if getattr(self, "_merge_dialog", None) is not None:
            try:
                self._merge_dialog.cleanup()
                self._merge_dialog.close()
            except Exception:
                pass
            self._merge_dialog = None

        modified_sessions = [s for s in self.sessions if s and s.is_modified and s.doc is not None]
        for s in modified_sessions:
            if self.check_unsaved_changes(s):
                return True
        self._is_closing = True
        for s in list(self.sessions):
            self.remove_session(s)
        return False

    def on_stroke_width_scroll(self, controller, dx, dy):
        """Adjust stroke width of selected shape using mouse wheel scroll."""
        if not self.selected_shape:
            return False
        
        dy_abs = abs(dy)
        increment = 0.5 if dy > 0 else -0.5
        
        new_width = max(0.5, self.selected_shape.stroke_width + increment)
        self.selected_shape.stroke_width = round(new_width, 1)
        
        self.pdf_view.queue_draw()
        return True

    def _toggle_view_edit_mode(self, button=None):
        """Toggle between read-only text-selection mode and interactive object edit mode."""
        if hasattr(self, 'stack') and self.stack and self.stack.get_visible_child_name() == "welcome":
            if any(s.doc is not None for s in self.sessions):
                self.stack.set_visible_child_name("editor")
                if hasattr(self, 'tab_bar') and self.tab_bar:
                    self.tab_bar.set_autohide(False)
                    self.tab_bar.set_visible(True)
                if self._active_session and self._active_session.doc is not None:
                    self.set_title(f"{constants.APP_NAME} - {self._active_session.display_title}")
        self.view_mode = not self.view_mode
        self._close_active_form_field_editor()
        if self.view_mode:
            self._apply_and_hide_editor()
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_form_field = None
            self.tool_mode = "select"
        else:
            self.view_sel_start = None
            self.view_sel_rect = None
            self.view_selected_text = ""
            self.selected_form_field = None
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(self.current_page_index)
        self.drag_threshold_passed = False
        self._update_ui_state()
        self.pdf_view.queue_draw()

    def on_highlight_clicked(self, button):
        """Add a highlight annotation over selected text or canvas selection rectangle."""
        rgba = self.highlight_color_button.get_rgba()
        color = (rgba.red, rgba.green, rgba.blue)
        
        target_rect = None
        is_visual = False
        rot = 0.0
        if self.view_mode and self.view_sel_rect:
            target_rect = self.view_sel_rect
            is_visual = True
        elif not self.view_mode and self.selected_text and self.selected_text.bbox:
            if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char'):
                target_rect = self.get_selected_word_bbox() or self.selected_text.bbox
            else:
                target_rect = self.selected_text.bbox
            is_visual = False
            rot = getattr(self.selected_text, 'rotation', 0.0)
            
        if not target_rect:
            return
            
        x1, y1, x2, y2 = target_rect
        success, err = pdf_handler.add_highlight_annotation(
            self.doc, self.current_page_index, (x1, y1, x2, y2), color=color, is_visual=is_visual, rotation=rot
        )
        if success:
            pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
            self.document_modified = True
            self.view_sel_start = None
            self.view_sel_rect = None
            self.view_selected_text = ""
            self._refresh_thumbnail(self.current_page_index)
            self._update_ui_state()
            self.pdf_view.queue_draw()
        else:
            from .ui_components import show_error_dialog
            show_error_dialog(self, _("highlight_failed", err))

    def on_remove_highlight_clicked(self, button):
        """Remove highlight annotations overlapping current selection."""
        target_rect = None
        is_visual = False
        if self.view_mode and self.view_sel_rect:
            target_rect = self.view_sel_rect
            is_visual = True
        elif not self.view_mode and self.selected_text and self.selected_text.bbox:
            if getattr(self, 'word_selection_mode', False) and hasattr(self, 'selected_word_start_char'):
                target_rect = self.get_selected_word_bbox() or self.selected_text.bbox
            else:
                target_rect = self.selected_text.bbox
            is_visual = False
            
        if not target_rect:
            return
            
        self._remove_highlight_at_region(target_rect, is_visual=is_visual)

    def on_view_sticky_note_toggled(self, button):
        """Toggle sticky note placement mode in View Mode."""
        if button.get_active():
            self.view_tool_mode = "add_sticky_note"
            if hasattr(self, 'pdf_view'):
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        else:
            if getattr(self, 'view_tool_mode', None) == "add_sticky_note":
                self.view_tool_mode = None
            if hasattr(self, 'pdf_view'):
                self.pdf_view.set_cursor(Gdk.Cursor.new_from_name("text"))

    def on_view_sticky_note_clicked(self, button=None):
        """Toggle sticky note placement mode when clicked."""
        if hasattr(self, 'view_sticky_note_btn') and isinstance(self.view_sticky_note_btn, Gtk.ToggleButton):
            self.view_sticky_note_btn.set_active(not self.view_sticky_note_btn.get_active())
        else:
            self.view_tool_mode = "add_sticky_note" if getattr(self, 'view_tool_mode', None) != "add_sticky_note" else None

    def _find_sticky_note_at_pos(self, page_x, page_y):
        """Find interactive sticky note at unrotated coordinates."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        if not self._active_session:
            return None
        notes = self._active_session.sticky_notes.get(self.current_page_index, [])
        for note in reversed(notes):
            if note.contains_point(page_x, page_y):
                return note
        return None

    def _create_sticky_note_at(self, page_x, page_y):
        """Create new sticky note at coordinates and open editor popover."""
        if not self.doc or not self._active_session:
            return
        unrot_x, unrot_y = self._visual_to_unrotated_page_coords(page_x, page_y)
        note = StickyNoteObject(
            page_number=self.current_page_index,
            x=unrot_x,
            y=unrot_y,
            content="",
            author=_("author_user"),
            color=(1.0, 0.86, 0.24),
            icon_type="Comment",
            is_new=True,
        )
        from .undo_manager import AddStickyNoteCommand
        cmd = AddStickyNoteCommand(self, note)
        cmd.execute()
        if self.undo_manager:
            self.undo_manager.record(cmd)
        self._open_sticky_note_popover(note)

    def _open_sticky_note_popover(self, note):
        """Open floating comment editor popover attached to sticky note."""
        if not note:
            return
        self.selected_sticky_note = note

        p_idx = getattr(note, 'page_number', self.current_page_index)
        obj_rect = self.get_object_canvas_rect(note, page_index=p_idx)
        rect, pos = self.calculate_smart_popover_placement(obj_rect, estimated_size=(280, 260))

        popover = StickyNotePopover(editor_window=self, note=note)
        popover.set_pointing_to(rect)
        popover.set_position(pos)
        popover.popup()

    def delete_sticky_note(self, note):
        """Delete sticky note with undo support."""
        if not note:
            return
        from .undo_manager import DeleteStickyNoteCommand
        cmd = DeleteStickyNoteCommand(self, note)
        cmd.execute()
        if self.undo_manager:
            self.undo_manager.record(cmd)

    def _delete_sticky_note(self, note):
        """Delete sticky note alias."""
        self.delete_sticky_note(note)

    def _add_sticky_note_to_session(self, note, session=None):
        """Add sticky note to active session and trigger canvas/sidebar refresh."""
        sess = session or self._active_session
        if not sess:
            return
        p = note.page_number
        if p not in sess.sticky_notes:
            sess.sticky_notes[p] = []
        if note not in sess.sticky_notes[p]:
            sess.sticky_notes[p].append(note)
        if sess is self._active_session:
            self.selected_sticky_note = note
        self.document_modified = True
        if hasattr(self, 'annotations_sidebar'):
            self.annotations_sidebar.refresh()
            if sess is self._active_session:
                self.annotations_sidebar.sync_selection(note)
        self.pdf_view.queue_draw()

    def _remove_sticky_note_from_session(self, note, session=None):
        """Remove sticky note from active session."""
        sess = session or self._active_session
        if not sess:
            return
        p = note.page_number
        if p in sess.sticky_notes and note in sess.sticky_notes[p]:
            sess.sticky_notes[p].remove(note)
        if sess is self._active_session and self.selected_sticky_note == note:
            self.selected_sticky_note = None
        self.document_modified = True
        if hasattr(self, 'annotations_sidebar'):
            self.annotations_sidebar.refresh()
        self.pdf_view.queue_draw()

    def _apply_sticky_note_state(self, note, state, session=None):
        """Apply state dictionary to sticky note."""
        sess = session or self._active_session
        if not note or not state:
            return
        note.content = state.get("content", note.content)
        note.author = state.get("author", note.author)
        note.color = state.get("color", note.color)
        note.icon_type = state.get("icon_type", note.icon_type)
        if "modified_at" in state:
            note.modified_at = state["modified_at"]
        note.modified = True
        self.document_modified = True
        if hasattr(self, 'annotations_sidebar'):
            self.annotations_sidebar.refresh()
        self.pdf_view.queue_draw()

    def _set_sticky_note_pos(self, note, new_x, new_y, session=None):
        """Reposition sticky note."""
        if not note:
            return
        note.x = float(new_x)
        note.y = float(new_y)
        note.modified = True
        self.document_modified = True
        if hasattr(self, 'annotations_sidebar'):
            self.annotations_sidebar.refresh()
        self.pdf_view.queue_draw()

    def _find_redaction_mark_at_pos(self, page_x, page_y):
        """Find interactive visual redaction mark at coordinates."""
        try:
            coords = self._visual_to_unrotated_page_coords(page_x, page_y)
            if isinstance(coords, (tuple, list)) and len(coords) == 2:
                page_x, page_y = coords
        except Exception:
            pass
        if not self._active_session:
            return None
        marks = self._active_session.redaction_marks.get(self.current_page_index, [])
        for mark in reversed(marks):
            if getattr(mark, 'is_applied', False):
                continue
            if mark.contains_point(page_x, page_y):
                return mark
        return None

    def _open_redaction_popover(self, mark):
        """Open floating inspector popover for the specified redaction mark."""
        if not mark:
            return
        self.selected_redaction_mark = mark
        p_idx = getattr(mark, 'page_number', self.current_page_index)
        obj_rect = self.get_object_canvas_rect(mark, page_index=p_idx)
        rect, pos = self.calculate_smart_popover_placement(obj_rect, estimated_size=(280, 240))

        popover = RedactionInspectorPopover(editor_window=self, mark=mark)
        popover.set_pointing_to(rect)
        popover.set_position(pos)
        popover.popup()

    def delete_redaction_mark(self, mark):
        """Delete visual redaction mark with undo support."""
        if not mark:
            return
        from .undo_manager import DeleteRedactionCommand
        cmd = DeleteRedactionCommand(self, mark)
        cmd.execute()
        if self.undo_manager:
            self.undo_manager.record(cmd)
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("status_redaction_removed"))

    def _delete_redaction_mark(self, mark):
        """Delete visual redaction mark alias."""
        self.delete_redaction_mark(mark)

    def _add_redaction_mark_to_session(self, mark, session=None):
        """Add visual redaction mark to active session and trigger canvas/sidebar refresh."""
        sess = session or self._active_session
        if not sess:
            return
        p = mark.page_number
        if p not in sess.redaction_marks:
            sess.redaction_marks[p] = []
        if mark not in sess.redaction_marks[p]:
            sess.redaction_marks[p].append(mark)
        if sess is self._active_session:
            self.selected_redaction_mark = mark
        self.document_modified = True
        if hasattr(self, 'annotations_sidebar'):
            self.annotations_sidebar.refresh()
            if sess is self._active_session:
                self.annotations_sidebar.sync_selection(mark)
        self._update_redaction_controls()
        self.pdf_view.queue_draw()

    def _remove_redaction_mark_from_session(self, mark, session=None):
        """Remove visual redaction mark from active session."""
        sess = session or self._active_session
        if not sess:
            return
        p = mark.page_number
        if p in sess.redaction_marks and mark in sess.redaction_marks[p]:
            sess.redaction_marks[p].remove(mark)
        if sess is self._active_session and self.selected_redaction_mark == mark:
            self.selected_redaction_mark = None
        self.document_modified = True
        if hasattr(self, 'annotations_sidebar'):
            self.annotations_sidebar.refresh()
        self._update_redaction_controls()
        self.pdf_view.queue_draw()

    def _apply_redaction_mark_state(self, mark, state, session=None):
        """Apply state dictionary to visual redaction mark."""
        sess = session or self._active_session
        if not mark or not state:
            return
        if "bbox" in state:
            mark.update_bbox(*state["bbox"])
        if "fill_color" in state:
            mark.fill_color = tuple(state["fill_color"])
        if "overlay_text" in state:
            mark.overlay_text = state["overlay_text"]
        if "text_color" in state:
            mark.text_color = tuple(state["text_color"])
        if "font_size" in state:
            mark.font_size = float(state["font_size"])
        self.document_modified = True
        if hasattr(self, 'annotations_sidebar'):
            self.annotations_sidebar.refresh()
        self.pdf_view.queue_draw()

    def mark_object_for_redaction(self, target_object, page_index=None, bbox=None):
        """Mark specified editable object (text, shape, image) for visual redaction."""
        if not self.doc or not self._active_session or not target_object:
            return None
        target_bbox = bbox if (isinstance(bbox, (tuple, list)) and len(bbox) == 4) else getattr(target_object, 'bbox', None)
        if not target_bbox or not isinstance(target_bbox, (tuple, list)) or len(target_bbox) != 4:
            return None
        p = page_index if page_index is not None else getattr(target_object, 'page_number', self.current_page_index)
        fill_c = getattr(self, 'redact_default_fill', (0.0, 0.0, 0.0))
        text_c = getattr(self, 'redact_default_text_color', (1.0, 1.0, 1.0))
        overlay_t = getattr(self, 'redact_default_overlay', "[REDACTED]")
        mark = RedactionMark(
            page_number=p,
            bbox=tuple(target_bbox),
            fill_color=fill_c,
            overlay_text=overlay_t,
            text_color=text_c,
        )
        from .undo_manager import AddRedactionCommand
        cmd = AddRedactionCommand(self, mark)
        cmd.execute()
        if self.undo_manager:
            self.undo_manager.record(cmd)
        self._open_redaction_popover(mark)
        return mark

    def mark_selection_for_redaction(self):
        """Mark currently selected text or object for visual redaction."""
        if not self.doc or not self._active_session:
            return
        # 1. Selected editable text, shape, or image object
        if getattr(self, 'selected_text', None) and getattr(self.selected_text, 'bbox', None):
            if getattr(self, 'word_selection_mode', False) and getattr(self, 'selected_word', None):
                word_bbox = None
                if hasattr(self, 'get_selected_word_bbox') and callable(self.get_selected_word_bbox):
                    wb = self.get_selected_word_bbox()
                    if isinstance(wb, (tuple, list)) and len(wb) == 4:
                        word_bbox = wb
                if not word_bbox:
                    word_bbox = getattr(self, 'selected_word_bbox', None)
                if not isinstance(word_bbox, (tuple, list)) or len(word_bbox) != 4:
                    text = self.selected_text.text
                    start_c = getattr(self, 'selected_word_start_char', 0)
                    end_c = getattr(self, 'selected_word_end_char', len(text))
                    from .models import measure_text_width
                    tx0, ty0, tx1, ty1 = self.selected_text.bbox
                    total_w = max(1.0, float(tx1 - tx0))
                    w_pre = measure_text_width(text[:start_c], self.selected_text.font_family_base, self.selected_text.font_size, self.selected_text.is_bold, self.selected_text.is_italic, self.selected_text)
                    w_word = measure_text_width(text[start_c:end_c], self.selected_text.font_family_base, self.selected_text.font_size, self.selected_text.is_bold, self.selected_text.is_italic, self.selected_text)
                    w_total = measure_text_width(text, self.selected_text.font_family_base, self.selected_text.font_size, self.selected_text.is_bold, self.selected_text.is_italic, self.selected_text)
                    scale = (total_w / w_total) if w_total > 0 else 1.0
                    word_bbox = (tx0 + (w_pre * scale), ty0, tx0 + ((w_pre + w_word) * scale), ty1)
                return self.mark_object_for_redaction(self.selected_text, bbox=word_bbox)
            return self.mark_object_for_redaction(self.selected_text)
        elif getattr(self, 'selected_shape', None) and getattr(self.selected_shape, 'bbox', None):
            return self.mark_object_for_redaction(self.selected_shape)
        elif getattr(self, 'selected_image', None) and getattr(self.selected_image, 'bbox', None):
            return self.mark_object_for_redaction(self.selected_image)

        # 2. View mode text selection rectangle
        if getattr(self, 'view_sel_rect', None):
            vx0, vy0, vx1, vy1 = self.view_sel_rect
            if abs(vx1 - vx0) >= 2.0 and abs(vy1 - vy0) >= 2.0:
                p = self.current_page_index
                fill_c = getattr(self, 'redact_default_fill', (0.0, 0.0, 0.0))
                text_c = getattr(self, 'redact_default_text_color', (1.0, 1.0, 1.0))
                overlay_t = getattr(self, 'redact_default_overlay', "[REDACTED]")
                mark = RedactionMark(
                    page_number=p,
                    bbox=(min(vx0, vx1), min(vy0, vy1), max(vx0, vx1), max(vy0, vy1)),
                    fill_color=fill_c,
                    overlay_text=overlay_t,
                    text_color=text_c,
                )
                from .undo_manager import AddRedactionCommand
                cmd = AddRedactionCommand(self, mark)
                cmd.execute()
                if self.undo_manager:
                    self.undo_manager.record(cmd)
                self.view_sel_rect = None
                self.view_selected_text = ""
                self._open_redaction_popover(mark)
                return mark

    def _delete_selected_word_from_text(self, text_obj):
        """Delete currently selected word from editable text with full undo/redo reversibility."""
        if not text_obj or not getattr(self, 'selected_word', None):
            return
        word = self.selected_word
        full_text = text_obj.text
        start_idx = getattr(self, 'selected_word_start_char', -1)
        end_idx = getattr(self, 'selected_word_end_char', -1)
        if start_idx == -1 or end_idx == -1:
            start_idx = full_text.find(word)
            end_idx = start_idx + len(word) if start_idx != -1 else -1
        if start_idx == -1:
            return

        before = full_text[:start_idx]
        after = full_text[end_idx:]
        if before.endswith(" ") and after.startswith(" "):
            after = after[1:]
        new_text = (before + after).strip()
        if not new_text:
            self._handle_delete_with_confirmation(text_obj, "delete_text_confirm")
            return

        old_state = snapshot_object_state(text_obj)
        new_state = snapshot_object_state(text_obj)
        new_state['text'] = new_text

        new_w = measure_text_width(new_text, text_obj.font_family_base, text_obj.font_size, text_obj.is_bold, text_obj.is_italic, text_obj)
        x0, y0, x1, y1 = text_obj.bbox
        new_state['bbox'] = (x0, y0, x0 + new_w, y1)

        if text_obj.char_boxes:
            remaining_cbs = []
            for idx, cb in enumerate(text_obj.char_boxes):
                if idx < start_idx or idx >= end_idx:
                    remaining_cbs.append(dict(cb))
            for i, cb in enumerate(remaining_cbs):
                cb["index"] = i
            new_state['char_boxes'] = remaining_cbs

        cmd = EditObjectCommand(self, text_obj, old_state, new_state)
        cmd.execute()
        if self.undo_manager:
            self.undo_manager.record(cmd)
        self.word_selection_mode = False
        self.selected_word = None
        self.selected_word_bbox = None
        self.selected_word_start_char = -1
        self.selected_word_end_char = -1
        self.document_modified = True
        if self.doc and self.current_page_index is not None:
            pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
        self.pdf_view.queue_draw()

    def _update_redaction_controls(self):
        """Update live count badge and sensitivity for redaction controls."""
        if not hasattr(self, 'redaction_apply_button') or not self.redaction_apply_button:
            return
        redacts = getattr(self._active_session, 'redaction_marks', {}) if self._active_session else {}
        total = sum(len(marks) for marks in redacts.values())
        if total > 0:
            self.redaction_apply_button.set_label(_("redaction_btn_apply_count", total))
            self.redaction_apply_button.set_sensitive(True)
        else:
            self.redaction_apply_button.set_label(_("redaction_btn_apply"))
            self.redaction_apply_button.set_sensitive(False)

    def apply_all_redactions(self, prompt_warning: bool = True):
        """Burn all staged visual redaction marks permanently into the active PDF document."""
        if not self.doc or not self._active_session:
            return False
        redacts = getattr(self._active_session, 'redaction_marks', {})
        total_marks = sum(len(marks) for marks in redacts.values())
        if total_marks == 0:
            return False

        if prompt_warning:
            confirmed = show_confirm_dialog(
                self,
                _("redaction_warning_msg", total_marks),
                _("redaction_warning_title"),
                destructive=True
            )
            if not confirmed:
                return False

        affected_pages = list(redacts.keys())
        applied = pdf_handler.apply_redaction_marks(self.doc, redacts)
        if applied:
            redacts.clear()
            self.selected_redaction_mark = None
            self.document_modified = True

            # Invalidate page snapshots, Cairo cache & cached editable objects for affected pages
            for pno in affected_pages:
                if 0 <= pno < self.doc.page_count:
                    pdf_handler.invalidate_page_cache(self.doc, pno)
                    pdf_handler.save_page_snapshot(self.doc, pno, force=True)
                    if hasattr(self, '_page_objects_cache') and pno in self._page_objects_cache:
                        del self._page_objects_cache[pno]
                    self._refresh_thumbnail(pno)

            # Clean any TOC bookmark pointing to redacted pages
            try:
                pdf_handler.sanitize_document(
                    self.doc,
                    strip_metadata=False,
                    purge_xmp=False,
                    purge_attachments=False,
                    purge_comments=False,
                    purge_hidden_layers=False,
                    purge_orphaned_toc=True,
                    redacted_pages=set(affected_pages)
                )
            except Exception:
                pass

            # Reload active page objects if active page was affected or to ensure clean canvas
            if self.current_page_index in affected_pages:
                self._load_page(self.current_page_index, reload_objects=True)
            else:
                self.pdf_view.queue_draw()

            if hasattr(self, 'annotations_sidebar') and self.annotations_sidebar.get_visible():
                self.annotations_sidebar.refresh()
            self._update_ui_state()
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.set_text(_("status_redactions_applied"))
        return applied

    def stage_redactions_for_matches(self, matches, overlay_text: str = "[REDACTED]", fill_color=(0.0, 0.0, 0.0), text_color=(1.0, 1.0, 1.0)) -> int:
        """Stage visual redaction marks for search matches using CompositeCommand."""
        if not self.doc or not self._active_session or not matches:
            return 0
        from .models import RedactionMark
        from .undo_manager import AddRedactionCommand, CompositeCommand

        cmds = []
        for m in matches:
            page_idx = getattr(m, 'page_index', getattr(m, 'page', None))
            bbox = getattr(m, 'bbox', getattr(m, 'rect', None))
            if page_idx is None or bbox is None:
                continue
            mark = RedactionMark(
                page_number=page_idx,
                bbox=tuple(bbox),
                fill_color=tuple(fill_color),
                overlay_text=overlay_text,
                text_color=tuple(text_color),
            )
            cmds.append(AddRedactionCommand(self, mark))

        if not cmds:
            return 0

        composite = CompositeCommand(self, cmds)
        composite.execute()
        if self.undo_manager:
            self.undo_manager.record(composite)

        self._update_redaction_controls()
        self.pdf_view.queue_draw()
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("status_redactions_staged_count", len(cmds)))
        return len(cmds)

    def _create_search_redact_options_popover(self) -> Gtk.Popover:
        popover = Gtk.Popover()
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pop_box.set_margin_start(12)
        pop_box.set_margin_end(12)
        pop_box.set_margin_top(12)
        pop_box.set_margin_bottom(12)
        pop_box.set_size_request(260, -1)

        # Title
        title_lbl = Gtk.Label(label=_("search_redact_options_title"))
        title_lbl.add_css_class("heading")
        title_lbl.set_halign(Gtk.Align.START)
        pop_box.append(title_lbl)

        # PII Pattern Presets dropdown
        preset_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        preset_lbl = Gtk.Label(label=_("search_redact_pattern_label"))
        preset_lbl.add_css_class("dim-label")
        preset_lbl.set_halign(Gtk.Align.START)
        preset_box.append(preset_lbl)

        presets = [
            ("none", _("search_redact_mode_text")),
            ("email", _("pii_pattern_email")),
            ("phone", _("pii_pattern_phone")),
            ("credit_card", _("pii_pattern_credit_card")),
            ("ssn", _("pii_pattern_ssn")),
            ("date", _("pii_pattern_date")),
        ]
        preset_strings = [p[1] for p in presets]
        preset_dropdown = Gtk.DropDown.new_from_strings(preset_strings)
        def _on_preset_changed(dd, ps):
            idx = dd.get_selected()
            key, _label = presets[idx]
            if key == "none":
                self._search_pii_key = None
            else:
                self._search_pii_key = key
                from .search_engine import PII_PATTERNS
                pat = PII_PATTERNS.get(key, {})
                if pat and hasattr(self, 'search_entry') and self.search_entry:
                    self.search_entry.set_text(pat.get("regex", ""))
            if hasattr(self, 'search_entry') and self.search_entry:
                self._on_search_query_changed(self.search_entry, immediate=True)

        preset_dropdown.connect("notify::selected", _on_preset_changed)
        preset_box.append(preset_dropdown)
        pop_box.append(preset_box)

        pop_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Scope (Entire Document vs Current Page)
        scope_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scope_lbl = Gtk.Label(label=_("search_redact_scope_label"))
        scope_lbl.add_css_class("dim-label")
        scope_lbl.set_halign(Gtk.Align.START)
        scope_box.append(scope_lbl)

        curr_page_num = (self.current_page_index + 1) if getattr(self, 'current_page_index', None) is not None else 1
        scope_dd = Gtk.DropDown.new_from_strings([
            _("search_redact_scope_doc"),
            _("search_redact_scope_page", curr_page_num)
        ])
        def _on_scope_changed(dd, ps):
            self._search_scope_current_page = (dd.get_selected() == 1)
            if hasattr(self, 'search_entry') and self.search_entry:
                self._on_search_query_changed(self.search_entry, immediate=True)
        scope_dd.connect("notify::selected", _on_scope_changed)
        scope_box.append(scope_dd)
        pop_box.append(scope_box)

        pop_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Overlay text
        overlay_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        overlay_lbl = Gtk.Label(label=_("redaction_overlay_text"))
        overlay_lbl.add_css_class("dim-label")
        overlay_lbl.set_halign(Gtk.Align.START)
        overlay_box.append(overlay_lbl)

        self.search_redact_overlay_entry = Gtk.Entry()
        self.search_redact_overlay_entry.set_text(getattr(self, 'redact_default_overlay', "[REDACTED]"))
        def _on_overlay_changed(entry):
            self.redact_default_overlay = entry.get_text()
        self.search_redact_overlay_entry.connect("changed", _on_overlay_changed)
        overlay_box.append(self.search_redact_overlay_entry)
        pop_box.append(overlay_box)

        popover.set_child(pop_box)
        return popover

    def _redact_current_search_match(self):
        """Redact the currently highlighted search match and navigate to next."""
        if not hasattr(self, 'search_engine') or not self.search_engine or not self.search_engine.matches:
            return
        m = self.search_engine.get_current_match()
        if not m:
            return
        overlay = getattr(self, 'search_redact_overlay_entry', None)
        overlay_text = overlay.get_text() if overlay else getattr(self, 'redact_default_overlay', "[REDACTED]")
        fill_color = getattr(self, 'redact_default_fill', (0.0, 0.0, 0.0))
        text_color = getattr(self, 'redact_default_text_color', (1.0, 1.0, 1.0))

        self.stage_redactions_for_matches(
            matches=[m],
            overlay_text=overlay_text,
            fill_color=fill_color,
            text_color=text_color,
        )
        self._search_navigate_next()

    def _redact_all_search_matches(self):
        """Stage redaction marks for all current search matches at once."""
        if not hasattr(self, 'search_engine') or not self.search_engine or not self.search_engine.matches:
            return
        matches = list(self.search_engine.matches)
        overlay = getattr(self, 'search_redact_overlay_entry', None)
        overlay_text = overlay.get_text() if overlay else getattr(self, 'redact_default_overlay', "[REDACTED]")
        fill_color = getattr(self, 'redact_default_fill', (0.0, 0.0, 0.0))
        text_color = getattr(self, 'redact_default_text_color', (1.0, 1.0, 1.0))

        count = self.stage_redactions_for_matches(
            matches=matches,
            overlay_text=overlay_text,
            fill_color=fill_color,
            text_color=text_color,
        )
        if hasattr(self, 'toast_overlay') and self.toast_overlay:
            toast = Adw.Toast(title=_("status_redactions_staged_count", count))
            toast.set_timeout(2)
            self.toast_overlay.add_toast(toast)

    def on_find_and_redact(self, initial_query: str = ""):
        """Open docked Find & Redact bar above canvas (non-modal)."""
        if not self.doc or not self._active_session:
            return
        if hasattr(self, 'search_bar') and self.search_bar and not self.search_bar.get_search_mode():
            self.search_bar.set_search_mode(True)
        if hasattr(self, 'search_button') and self.search_button:
            self.search_button.set_active(True)
        if hasattr(self, 'search_redact_btn') and self.search_redact_btn:
            self.search_redact_btn.set_active(True)
        if hasattr(self, 'search_redact_box') and self.search_redact_box:
            self.search_redact_box.set_visible(True)
        if initial_query and hasattr(self, 'search_entry') and self.search_entry:
            self.search_entry.set_text(initial_query)
        if hasattr(self, 'search_entry') and self.search_entry:
            self.search_entry.grab_focus()
            self._on_search_query_changed(self.search_entry, immediate=True)

    def get_selected_word_bbox(self) -> Optional[Tuple[float, float, float, float]]:
        """Compute the sub-pixel exact bounding box of the currently selected word."""
        if not getattr(self, 'word_selection_mode', False) or not self.selected_text:
            return getattr(self, 'selected_word_bbox', None)
        text_obj = self.selected_text
        if hasattr(text_obj, 'sync_char_boxes_to_bbox'):
            text_obj.sync_char_boxes_to_bbox()
        start_c = getattr(self, 'selected_word_start_char', -1)
        end_c = getattr(self, 'selected_word_end_char', -1)
        if start_c == -1 or end_c == -1 or start_c >= end_c:
            return getattr(self, 'selected_word_bbox', None)

        if getattr(text_obj, 'char_boxes', None) and len(text_obj.char_boxes) >= end_c:
            cbs = text_obj.char_boxes[start_c:end_c]
            if cbs:
                x0 = min(cb['bbox'][0] for cb in cbs)
                y0 = min(cb['bbox'][1] for cb in cbs)
                x1 = max(cb['bbox'][2] for cb in cbs)
                y1 = max(cb['bbox'][3] for cb in cbs)
                return (x0, y0, x1, y1)

        if text_obj.bbox:
            tx0, ty0, tx1, ty1 = text_obj.bbox
            total_w = max(1.0, float(tx1 - tx0))
            from .models import measure_text_width
            w_pre = measure_text_width(text_obj.text[:start_c], text_obj.font_family_base, text_obj.font_size, text_obj.is_bold, text_obj.is_italic, text_obj)
            w_word = measure_text_width(text_obj.text[start_c:end_c], text_obj.font_family_base, text_obj.font_size, text_obj.is_bold, text_obj.is_italic, text_obj)
            w_total = measure_text_width(text_obj.text, text_obj.font_family_base, text_obj.font_size, text_obj.is_bold, text_obj.is_italic, text_obj)
            scale = (total_w / w_total) if w_total > 0 else 1.0
            x_start = tx0 + (w_pre * scale)
            x_end = tx0 + ((w_pre + w_word) * scale)
            return (x_start, ty0, x_end, ty1)

        return getattr(self, 'selected_word_bbox', None)

    def _isolate_selected_word_span(self):
        """If in word_selection_mode and the selected word is part of a larger paragraph,
        split the paragraph into [pre, mid, post] and select mid as an independent EditableText."""
        if not getattr(self, 'word_selection_mode', False) or not self.selected_text:
            return self.selected_text
        start_c = getattr(self, 'selected_word_start_char', -1)
        end_c = getattr(self, 'selected_word_end_char', -1)
        text_obj = self.selected_text
        if start_c == -1 or end_c == -1 or start_c >= end_c:
            return text_obj
        if start_c == 0 and end_c == len(text_obj.text):
            return text_obj

        # Clear pending format change tracking for text_obj to prevent duplicate/ghost edit commands
        if getattr(self, 'pending_format_change_obj', None) is text_obj:
            self.pending_format_change_obj = None
            self.before_format_change_state = None

        spans = text_obj.split_at_range(start_c, end_c, compensate_rotation=True)
        if len(spans) > 1:
            mid_index = 0 if start_c == 0 else 1
            mid_span = spans[mid_index]
            target_page_num = getattr(text_obj, 'page_number', self.current_page_index)
            commands = [DeleteObjectCommand(self, text_obj)]
            for s in spans:
                s.is_new = True
                s.is_baked = True
                s.page_number = target_page_num
                commands.append(AddObjectCommand(self, s))
            batch_cmd = CompositeCommand(self, commands)
            batch_cmd.execute()
            if self.undo_manager:
                self.undo_manager.record(batch_cmd)

            self.selected_text = mid_span
            self.pending_format_change_obj = mid_span
            self.before_format_change_state = snapshot_object_state(mid_span)
            self.selected_word_start_char = 0
            self.selected_word_end_char = len(mid_span.text)
            self.selected_word_bbox = mid_span.bbox
            self.word_selection_mode = False
            if hasattr(self, '_update_rotation_controls'):
                self._update_rotation_controls(mid_span)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(mid_span)
            return mid_span
        return text_obj

    def _toggle_word_style(self, text_obj, style_name: str):
        """Toggle typography formatting (bold, italic, underline, strikethrough) for selected word."""
        if not text_obj or not getattr(self, 'word_selection_mode', False):
            return
        start_char = getattr(self, 'selected_word_start_char', -1)
        end_char = getattr(self, 'selected_word_end_char', -1)
        if start_char == -1 or end_char == -1 or start_char >= end_char:
            return

        # Clear pending format change tracking for text_obj to prevent duplicate/ghost edit commands
        if getattr(self, 'pending_format_change_obj', None) is text_obj:
            self.pending_format_change_obj = None
            self.before_format_change_state = None

        if start_char == 0 and end_char == len(text_obj.text):
            old_props = snapshot_object_state(text_obj)
            new_props = snapshot_object_state(text_obj)
            if style_name == "bold":
                new_props['is_bold'] = not text_obj.is_bold
            elif style_name == "italic":
                new_props['is_italic'] = not text_obj.is_italic
            elif style_name == "underline":
                new_props['is_underline'] = not getattr(text_obj, 'is_underline', False)
            elif style_name == "strikethrough":
                new_props['is_strikethrough'] = not getattr(text_obj, 'is_strikethrough', False)

            new_w = measure_text_width(
                text_obj.text, text_obj.font_family_base, text_obj.font_size,
                new_props['is_bold'], new_props['is_italic'], text_obj
            )
            x0, y0, x1, y1 = text_obj.bbox
            dw = new_w - (x1 - x0)
            rot = getattr(text_obj, 'rotation', 0.0) % 360.0
            if rot != 0.0 and abs(dw) > 0.001:
                dc_x, dc_y = dw / 2.0, 0.0
                rad = math.radians(rot)
                rdx = dc_x * math.cos(rad) - dc_y * math.sin(rad)
                rdy = dc_x * math.sin(rad) + dc_y * math.cos(rad)
                d_x = rdx - dc_x
                d_y = rdy - dc_y
            else:
                d_x, d_y = 0.0, 0.0

            new_props['bbox'] = (x0 + d_x, y0 + d_y, x0 + new_w + d_x, y1 + d_y)
            new_props['x'] = new_props['bbox'][0]
            new_props['y'] = new_props['bbox'][1]
            if 'baseline' in new_props and new_props['baseline'] is not None:
                new_props['baseline'] += d_y
            dx = (x0 + new_w) - x1

            orig_w = max(0.1, float(x1 - x0))
            if text_obj.char_boxes and orig_w > 0:
                scale_x = new_w / orig_w
                new_cbs = []
                for cb in text_obj.char_boxes:
                    ncb = dict(cb)
                    cbx0, cby0, cbx1, cby1 = ncb["bbox"]
                    ncb["bbox"] = (x0 + d_x + (cbx0 - x0) * scale_x, cby0 + d_y, x0 + d_x + (cbx1 - x0) * scale_x, cby1 + d_y)
                    if "visual_bbox" in ncb:
                        ncb["visual_bbox"] = ncb["bbox"]
                    if "origin" in ncb:
                        ncb["origin"] = (x0 + d_x + (ncb["origin"][0] - x0) * scale_x, ncb["origin"][1] + d_y)
                    new_cbs.append(ncb)
                new_props['char_boxes'] = new_cbs

            commands = [EditObjectCommand(self, text_obj, old_props, new_props)]

            if abs(dx) > 0.001:
                t_base = getattr(text_obj, 'baseline', y1)
                t_page = getattr(text_obj, 'page_number', self.current_page_index)
                for other in getattr(self, 'editable_texts', []):
                    if other is text_obj or getattr(other, 'page_number', None) != t_page:
                        continue
                    o_base = getattr(other, 'baseline', other.bbox[3] if other.bbox else other.y)
                    if abs(o_base - t_base) < 2.5 and other.bbox and other.bbox[0] >= x1 - 0.5:
                        o_old = {'bbox': other.bbox}
                        ox0, oy0, ox1, oy1 = other.bbox
                        o_new = {'bbox': (ox0 + dx, oy0, ox1 + dx, oy1)}
                        if getattr(other, 'char_boxes', None):
                            o_old['char_boxes'] = [dict(cb) for cb in other.char_boxes]
                            shifted_cbs = []
                            for cb in other.char_boxes:
                                ncb = dict(cb)
                                cbx0, cby0, cbx1, cby1 = ncb["bbox"]
                                ncb["bbox"] = (cbx0 + dx, cby0, cbx1 + dx, cby1)
                                if "visual_bbox" in ncb:
                                    ncb["visual_bbox"] = ncb["bbox"]
                                if "origin" in ncb:
                                    ncb["origin"] = (ncb["origin"][0] + dx, ncb["origin"][1])
                                shifted_cbs.append(ncb)
                            o_new['char_boxes'] = shifted_cbs
                        commands.append(EditObjectCommand(self, other, o_old, o_new))

            if len(commands) == 1:
                cmd = commands[0]
                cmd.execute()
                if self.undo_manager:
                    self.undo_manager.record(cmd)
            else:
                batch_cmd = CompositeCommand(self, commands)
                batch_cmd.execute()
                if self.undo_manager:
                    self.undo_manager.record(batch_cmd)

            self.pending_format_change_obj = text_obj
            self.before_format_change_state = snapshot_object_state(text_obj)
            self.selected_word_bbox = text_obj.bbox
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            if self.doc and self.current_page_index is not None:
                pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
            self.pdf_view.queue_draw()
            self._update_ui_state()
            return

        spans = text_obj.split_at_range(start_char, end_char, compensate_rotation=False)
        if len(spans) > 1:
            mid_index = 0 if start_char == 0 else 1
            mid_span = spans[mid_index]
            if style_name == "bold":
                mid_span.is_bold = not getattr(text_obj, 'is_bold', False)
            elif style_name == "italic":
                mid_span.is_italic = not getattr(text_obj, 'is_italic', False)
            elif style_name == "underline":
                mid_span.is_underline = not getattr(text_obj, 'is_underline', False)
            elif style_name == "strikethrough":
                mid_span.is_strikethrough = not getattr(text_obj, 'is_strikethrough', False)

            new_mid_w = measure_text_width(
                mid_span.text, mid_span.font_family_base, mid_span.font_size,
                mid_span.is_bold, mid_span.is_italic, mid_span
            )
            mx0, my0, mx1, my1 = mid_span.bbox
            orig_mid_w = max(0.1, float(mx1 - mx0))
            mid_span.bbox = (mx0, my0, mx0 + new_mid_w, my1)
            mid_span.original_bbox = mid_span.bbox
            dx = (mx0 + new_mid_w) - mx1

            if mid_span.char_boxes and orig_mid_w > 0:
                scale_x = new_mid_w / orig_mid_w
                for cb in mid_span.char_boxes:
                    cbx0, cby0, cbx1, cby1 = cb["bbox"]
                    cb["bbox"] = (mx0 + (cbx0 - mx0) * scale_x, cby0, mx0 + (cbx1 - mx0) * scale_x, cby1)
                    if "visual_bbox" in cb:
                        cb["visual_bbox"] = cb["bbox"]
                    if "origin" in cb:
                        cb["origin"] = (mx0 + (cb["origin"][0] - mx0) * scale_x, cb["origin"][1])

            for s_idx in range(mid_index + 1, len(spans)):
                post_span = spans[s_idx]
                px0, py0, px1, py1 = post_span.bbox
                post_span.bbox = (px0 + dx, py0, px1 + dx, py1)
                post_span.original_bbox = post_span.bbox
                post_span.x = post_span.bbox[0]
                if post_span.char_boxes:
                    for cb in post_span.char_boxes:
                        cbx0, cby0, cbx1, cby1 = cb["bbox"]
                        cb["bbox"] = (cbx0 + dx, cby0, cbx1 + dx, cby1)
                        if "visual_bbox" in cb:
                            cb["visual_bbox"] = cb["bbox"]
                        if "origin" in cb:
                            cb["origin"] = (cb["origin"][0] + dx, cb["origin"][1])

            rot = getattr(text_obj, 'rotation', 0.0) % 360.0
            if rot != 0.0 and text_obj.bbox:
                p_cx = (text_obj.bbox[0] + text_obj.bbox[2]) / 2.0
                p_cy = (text_obj.bbox[1] + text_obj.bbox[3]) / 2.0
                for s in spans:
                    s.compensate_for_rotation((p_cx, p_cy), rot)

            target_page_num = getattr(text_obj, 'page_number', self.current_page_index)
            commands = [DeleteObjectCommand(self, text_obj)]
            for s in spans:
                s.is_new = True
                s.is_baked = True
                s.page_number = target_page_num
                commands.append(AddObjectCommand(self, s))
            batch_cmd = CompositeCommand(self, commands)
            batch_cmd.execute()
            if self.undo_manager:
                self.undo_manager.record(batch_cmd)

            self.pending_format_change_obj = None
            self.before_format_change_state = None
            self.selected_text = mid_span
            self.pending_format_change_obj = mid_span
            self.before_format_change_state = snapshot_object_state(mid_span)
            self.selected_word_start_char = 0
            self.selected_word_end_char = len(mid_span.text)
            self.selected_word_bbox = mid_span.bbox
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(mid_span)
            if self.doc and self.current_page_index is not None:
                pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
            self.pdf_view.queue_draw()
            self._update_ui_state()

    def _extract_word_at_position(self, text, click_pos_in_text):
        """Extract contiguous non-whitespace word and its character indices at cursor."""
        if not text or click_pos_in_text < 0 or click_pos_in_text > len(text):
            return None, 0, 0
        
        start = click_pos_in_text
        end = click_pos_in_text
        
        while start > 0 and text[start - 1] not in ' \t\n':
            start -= 1
        
        while end < len(text) and text[end] not in ' \t\n':
            end += 1
        
        return text[start:end], start, end

    def _on_middle_click(self, gesture, n_press, x, y):
        """Handle middle-click gesture to quickly select words or jump to links."""
        if not self.doc:
            return
        
        target_page, page_x, page_y = self.canvas_to_page_coords(x, y)
        is_on_page = self.is_canvas_point_on_page(x, y, target_page)
        if is_on_page and target_page != self.current_page_index:
            self._switch_active_page(target_page)
        
        if self.view_mode:
            clicked_word = pdf_handler.get_word_at_pos(self.doc, self.current_page_index, (page_x, page_y))
            if clicked_word:
                self.selected_word = clicked_word['text']
                self.view_sel_rect = clicked_word['bbox']
                self.word_selection_mode = True
                self.pdf_view.queue_draw()
                self._update_ui_state()
        else:
            clicked_text = self._find_text_at_pos(page_x, page_y)
            if clicked_text:
                self.selected_text = clicked_text
                if hasattr(clicked_text, 'sync_char_boxes_to_bbox'):
                    clicked_text.sync_char_boxes_to_bbox()
                unrot_x, unrot_y = self._visual_to_unrotated_page_coords(page_x, page_y)
                
                rot = getattr(clicked_text, 'rotation', 0.0) % 360.0
                if rot != 0.0 and clicked_text.bbox:
                    cx = (clicked_text.bbox[0] + clicked_text.bbox[2]) / 2.0
                    cy = (clicked_text.bbox[1] + clicked_text.bbox[3]) / 2.0
                    obj_unrot_x, obj_unrot_y = pdf_handler.rotate_point(unrot_x, unrot_y, cx, cy, -rot)
                else:
                    obj_unrot_x, obj_unrot_y = unrot_x, unrot_y
                
                # Stage 1: Hit-test exact character boxes
                char_hit = clicked_text.hit_test_char(unrot_x, unrot_y, tolerance=3.0)
                if char_hit and "index" in char_hit and 0 <= char_hit["index"] < len(clicked_text.text):
                    char_idx = char_hit["index"]
                    word, s_pos, e_pos = self._extract_word_at_position(clicked_text.text, char_idx)
                    if word:
                        self.selected_word = word
                        self.selected_word_start_char = s_pos
                        self.selected_word_end_char = e_pos
                        self.selected_word_bbox = self.get_selected_word_bbox()
                        self.word_selection_mode = True
                        self.pending_format_change_obj = clicked_text
                        self.before_format_change_state = snapshot_object_state(clicked_text)
                        self.pdf_view.queue_draw()
                        self._update_ui_state()
                        return

                # Stage 2: Fallback with PyMuPDF get_word_at_pos and closest occurrence matching
                pdf_word = pdf_handler.get_word_at_pos(self.doc, self.current_page_index, (page_x, page_y))
                if pdf_word and pdf_word.get('text'):
                    w_text = pdf_word['text']
                    best_start = -1
                    best_dist = float('inf')
                    search_pos = 0
                    while search_pos < len(clicked_text.text):
                        found_idx = clicked_text.text.find(w_text, search_pos)
                        if found_idx == -1:
                            break
                        if clicked_text.char_boxes and len(clicked_text.char_boxes) >= (found_idx + len(w_text)):
                            cbs = clicked_text.char_boxes[found_idx:found_idx + len(w_text)]
                            cx = sum((cb["bbox"][0] + cb["bbox"][2]) / 2.0 for cb in cbs) / max(len(cbs), 1)
                        else:
                            from .models import measure_text_width
                            pre_w = measure_text_width(clicked_text.text[:found_idx], clicked_text.font_family_base, clicked_text.font_size, clicked_text.is_bold, clicked_text.is_italic, clicked_text)
                            word_w = measure_text_width(w_text, clicked_text.font_family_base, clicked_text.font_size, clicked_text.is_bold, clicked_text.is_italic, clicked_text)
                            cx = (clicked_text.bbox[0] if clicked_text.bbox else clicked_text.x) + pre_w + word_w / 2.0
                        dist = abs(obj_unrot_x - cx)
                        if dist < best_dist:
                            best_dist = dist
                            best_start = found_idx
                        search_pos = found_idx + 1

                    if best_start != -1:
                        self.selected_word = w_text
                        self.selected_word_start_char = best_start
                        self.selected_word_end_char = best_start + len(w_text)
                        self.selected_word_bbox = self.get_selected_word_bbox()
                        self.word_selection_mode = True
                        self.pending_format_change_obj = clicked_text
                        self.before_format_change_state = snapshot_object_state(clicked_text)
                        self.pdf_view.queue_draw()
                        self._update_ui_state()
                        return

                # Stage 3: Caret index projection fallback
                caret_idx = clicked_text.get_caret_index_at_pos(obj_unrot_x, obj_unrot_y)
                word, s_pos, e_pos = self._extract_word_at_position(clicked_text.text, caret_idx)
                if word:
                    self.selected_word = word
                    self.selected_word_start_char = s_pos
                    self.selected_word_end_char = e_pos
                    self.selected_word_bbox = self.get_selected_word_bbox()
                    self.word_selection_mode = True
                    self.pending_format_change_obj = clicked_text
                    self.before_format_change_state = snapshot_object_state(clicked_text)
                    self.pdf_view.queue_draw()
                    self._update_ui_state()

    def _on_right_click(self, gesture, n_press, x, y):
        """Display context popover menu tailored to clicked text, shape, image, or empty area."""
        if not self.doc:
            return
        
        if getattr(self, 'temp_polygon_vertices', None):
            self.temp_polygon_vertices = []
            self.last_mouse_page_pos = None
            self.pdf_view.queue_draw()
            return
        
        target_page, page_x, page_y = self.canvas_to_page_coords(x, y)
        is_on_page = self.is_canvas_point_on_page(x, y, target_page)
        if is_on_page and target_page != self.current_page_index:
            self._switch_active_page(target_page)
        
        modifiers = Gtk.EventController.get_current_event_state(gesture)
        ctrl_pressed = bool(modifiers & Gdk.ModifierType.CONTROL_MASK)

        if self.view_mode:
            unrot_px, unrot_py = self._visual_to_unrotated_page_coords(page_x, page_y)
            clicked_note = self._find_sticky_note_at_pos(unrot_px, unrot_py) if hasattr(self, '_find_sticky_note_at_pos') else None
            if clicked_note:
                self.selected_sticky_note = clicked_note
                self.pdf_view.queue_draw()
                popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                popover_box.set_margin_start(6); popover_box.set_margin_end(6)
                popover_box.set_margin_top(6); popover_box.set_margin_bottom(6)
                
                btn_edit = Gtk.Button(label=_("edit_sticky_note"))
                btn_edit.connect("clicked", lambda b: (self.context_popover.popdown() if hasattr(self, 'context_popover') else None, self._open_sticky_note_popover(clicked_note)))
                popover_box.append(btn_edit)
                
                btn_del = Gtk.Button(label=_("delete_sticky_note"))
                btn_del.add_css_class("destructive-action")
                btn_del.connect("clicked", lambda b: (self.context_popover.popdown() if hasattr(self, 'context_popover') else None, self._delete_sticky_note(clicked_note)))
                popover_box.append(btn_del)
                
                if hasattr(self, 'context_popover') and self.context_popover:
                    try:
                        self.context_popover.popdown()
                        self.context_popover.unparent()
                    except Exception:
                        pass
                self.context_popover = Gtk.Popover(autohide=True, has_arrow=True)
                self.context_popover.set_child(popover_box)
                self.context_popover.set_parent(self.pdf_view)
                note_rect = self.get_object_canvas_rect(clicked_note, page_index=getattr(clicked_note, 'page_number', target_page))
                rect, pos = self.calculate_smart_popover_placement(note_rect, click_pos=(x, y))
                self.context_popover.set_pointing_to(rect)
                self.context_popover.set_position(pos)
                self.context_popover.popup()
                return

            if not self.view_sel_rect or not (self.view_sel_rect[0] <= page_x <= self.view_sel_rect[2] and self.view_sel_rect[1] <= page_y <= self.view_sel_rect[3]):
                clicked_word = pdf_handler.get_word_at_pos(self.doc, self.current_page_index, (page_x, page_y))
                if clicked_word:
                    self.view_sel_rect = clicked_word['bbox']
                    self.view_selected_text = clicked_word['text']
                    self.pdf_view.queue_draw()

            if ctrl_pressed and self.view_selected_text:
                import webbrowser
                import re
                match = re.search(r'https?://[^\s]+', self.view_selected_text)
                if match:
                    webbrowser.open(match.group(0))
                return

            popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            popover_box.set_margin_start(6); popover_box.set_margin_end(6)
            popover_box.set_margin_top(6); popover_box.set_margin_bottom(6)

            if self.view_selected_text:
                btn_copy = Gtk.Button(label=_("btn_copy_text"))
                btn_copy.connect("clicked", lambda b: self._handle_context_action("copy_view", None, x, y))
                popover_box.append(btn_copy)

                btn_edit = Gtk.Button(label=_("menu_edit_text"))
                btn_edit.connect("clicked", lambda b: self._handle_context_action("edit_view_text", None, x, y))
                popover_box.append(btn_edit)

                btn_hl = Gtk.Button(label=_("menu_highlight"))
                btn_hl.connect("clicked", lambda b: self._handle_context_action("highlight_view", None, x, y))
                popover_box.append(btn_hl)

            btn_add_note = Gtk.Button(label=_("menu_add_sticky_note"))
            btn_add_note.connect("clicked", lambda b: (self.context_popover.popdown() if hasattr(self, 'context_popover') else None, self._create_sticky_note_at(page_x, page_y)))
            popover_box.append(btn_add_note)

            if hasattr(self, 'context_popover') and self.context_popover:
                try:
                    self.context_popover.popdown()
                    self.context_popover.unparent()
                except Exception:
                    pass
            self.context_popover = Gtk.Popover(autohide=True, has_arrow=True)
            self.context_popover.set_child(popover_box)
            self.context_popover.set_parent(self.pdf_view)
            sel_rect = self.get_object_canvas_rect(self.view_sel_rect, page_index=self.current_page_index, is_visual_coords=True) if self.view_sel_rect else None
            rect, pos = self.calculate_smart_popover_placement(sel_rect, click_pos=(x, y))
            self.context_popover.set_pointing_to(rect)
            self.context_popover.set_position(pos)
            self.context_popover.popup()
            return

        clicked_text = self._find_text_at_pos(page_x, page_y)
        clicked_shape = self._find_shape_at_pos(page_x, page_y)
        clicked_image = self._find_image_at_pos(page_x, page_y)
        if hasattr(self, '_keep_topmost_hit'):
            clicked_text, clicked_image, clicked_shape = self._keep_topmost_hit(
                clicked_text, clicked_image, clicked_shape)
        clicked_measurement = self._find_measurement_at_pos(page_x, page_y)
        
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        popover_box.set_margin_start(6); popover_box.set_margin_end(6)
        popover_box.set_margin_top(6); popover_box.set_margin_bottom(6)
        
        is_word_mode = False
        if clicked_text:
            self.selected_text = clicked_text
            self.selected_shape = None
            self.selected_image = None
            
            is_word_mode = bool(
                getattr(self, 'word_selection_mode', False) and
                getattr(self, 'selected_word', None) and
                hasattr(self, 'selected_word_start_char') and
                hasattr(self, 'selected_word_end_char')
            )

            if is_word_mode:
                popover_box.set_size_request(210, -1)
                word_str = self.selected_word
                word_bbox = self.get_selected_word_bbox() or clicked_text.bbox

                # Word preview header
                preview_str = word_str if len(word_str) <= 20 else f"{word_str[:17]}…"
                lbl_header = Gtk.Label(label=f"“{preview_str}”")
                lbl_header.add_css_class("heading")
                lbl_header.set_halign(Gtk.Align.CENTER)
                lbl_header.set_ellipsize(Pango.EllipsizeMode.END)
                lbl_header.set_max_width_chars(22)
                popover_box.append(lbl_header)

                # Clipboard actions row (Cut / Copy)
                clip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2, homogeneous=True)
                clip_box.add_css_class("linked")

                btn_cut_w = Gtk.Button.new_from_icon_name("edit-cut-symbolic")
                btn_cut_w.set_tooltip_text(_("btn_cut"))
                def on_cut_word_click(b):
                    self.get_clipboard().set(word_str)
                    if hasattr(self, 'context_popover') and self.context_popover:
                        self.context_popover.popdown()
                    self._delete_selected_word_from_text(clicked_text)
                btn_cut_w.connect("clicked", on_cut_word_click)
                clip_box.append(btn_cut_w)

                btn_copy_w = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
                btn_copy_w.set_tooltip_text(_("btn_copy"))
                btn_copy_w.connect("clicked", lambda b: (
                    self.get_clipboard().set(word_str),
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None
                ))
                clip_box.append(btn_copy_w)
                popover_box.append(clip_box)

                # Typography row: [B] [I] [U] [S] using compact symbolic icons and tooltips
                typo_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2, homogeneous=True)
                typo_box.add_css_class("linked")

                btn_b = Gtk.Button.new_from_icon_name("format-text-bold-symbolic")
                btn_b.set_tooltip_text(_("bold_tip"))
                btn_b.connect("clicked", lambda b: (
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None,
                    self._toggle_word_style(clicked_text, "bold")
                ))
                typo_box.append(btn_b)

                btn_i = Gtk.Button.new_from_icon_name("format-text-italic-symbolic")
                btn_i.set_tooltip_text(_("italic_tip"))
                btn_i.connect("clicked", lambda b: (
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None,
                    self._toggle_word_style(clicked_text, "italic")
                ))
                typo_box.append(btn_i)

                btn_u = Gtk.Button.new_from_icon_name("format-text-underline-symbolic")
                btn_u.set_tooltip_text(_("underline_tip"))
                btn_u.connect("clicked", lambda b: (
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None,
                    self._toggle_word_style(clicked_text, "underline")
                ))
                typo_box.append(btn_u)

                btn_s = Gtk.Button.new_from_icon_name("format-text-strikethrough-symbolic")
                btn_s.set_tooltip_text(_("strikethrough_tip"))
                btn_s.connect("clicked", lambda b: (
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None,
                    self._toggle_word_style(clicked_text, "strikethrough")
                ))
                typo_box.append(btn_s)
                popover_box.append(typo_box)

                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

                # Word actions
                btn_hl = Gtk.Button(label=_("menu_highlight"))
                btn_hl.connect("clicked", lambda b: (
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None,
                    self.on_highlight_clicked(None)
                ))
                popover_box.append(btn_hl)

                btn_link_w = Gtk.Button(label=_("menu_insert_edit_link"))
                def on_link_word_click(b):
                    if hasattr(self, 'context_popover') and self.context_popover:
                        self.context_popover.popdown()
                    start_c = getattr(self, 'selected_word_start_char', 0)
                    end_c = getattr(self, 'selected_word_end_char', len(clicked_text.text))
                    if start_c == 0 and end_c == len(clicked_text.text):
                        self.show_link_popover(clicked_text, parent_widget=self.pdf_view)
                    else:
                        spans = clicked_text.split_at_range(start_c, end_c)
                        if len(spans) > 1:
                            mid_index = 0 if start_c == 0 else 1
                            mid_span = spans[mid_index]
                            from .undo_manager import DeleteObjectCommand, AddObjectCommand, CompositeCommand
                            target_page_num = getattr(clicked_text, 'page_number', self.current_page_index)
                            commands = [DeleteObjectCommand(self, clicked_text)]
                            for s in spans:
                                s.is_new = True
                                s.is_baked = True
                                s.page_number = target_page_num
                                commands.append(AddObjectCommand(self, s))
                            batch_cmd = CompositeCommand(self, commands)
                            batch_cmd.execute()
                            if self.undo_manager:
                                self.undo_manager.record(batch_cmd)
                            self.selected_text = mid_span
                            self.word_selection_mode = False
                            self.show_link_popover(mid_span, parent_widget=self.pdf_view)
                btn_link_w.connect("clicked", on_link_word_click)
                popover_box.append(btn_link_w)

                btn_redact_w = Gtk.Button(label=_("menu_mark_for_redaction"))
                def on_redact_word_click(b):
                    if hasattr(self, 'context_popover') and self.context_popover:
                        self.context_popover.popdown()
                    w_box = self.get_selected_word_bbox() or word_bbox
                    self.mark_object_for_redaction(clicked_text, page_index=target_page, bbox=w_box)
                btn_redact_w.connect("clicked", on_redact_word_click)
                popover_box.append(btn_redact_w)

                btn_del_w = Gtk.Button(label=_("btn_delete_word"))
                btn_del_w.add_css_class("destructive-action")
                def on_del_word_click(b):
                    if hasattr(self, 'context_popover') and self.context_popover:
                        self.context_popover.popdown()
                    self._delete_selected_word_from_text(clicked_text)
                btn_del_w.connect("clicked", on_del_word_click)
                popover_box.append(btn_del_w)

                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

                btn_edit = Gtk.Button(label=_("menu_edit_text"))
                btn_edit.connect("clicked", lambda b: self._handle_context_action("edit_text", clicked_text, x, y))
                popover_box.append(btn_edit)

                btn_redact_p = Gtk.Button(label=_("menu_mark_paragraph_for_redaction"))
                btn_redact_p.connect("clicked", lambda b: (
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None,
                    self.mark_object_for_redaction(clicked_text, page_index=target_page, bbox=clicked_text.bbox)
                ))
                popover_box.append(btn_redact_p)

                btn_del_p = Gtk.Button(label=_("btn_delete_paragraph"))
                btn_del_p.add_css_class("destructive-action")
                btn_del_p.connect("clicked", lambda b: (
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None,
                    self._handle_delete_with_confirmation(clicked_text, "delete_text_confirm")
                ))
                popover_box.append(btn_del_p)
            else:
                btn_copy = Gtk.Button(label=_("btn_copy"))
                def on_copy_clicked(b):
                    self.get_clipboard().set(clicked_text.text)
                    if hasattr(self, 'context_popover') and self.context_popover:
                        self.context_popover.popdown()
                btn_copy.connect("clicked", on_copy_clicked)
                popover_box.append(btn_copy)
                
                btn_paste = Gtk.Button(label=_("btn_paste"))
                btn_paste.set_sensitive(False)
                popover_box.append(btn_paste)
                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
                
                btn_bold = Gtk.Button(label=_("bold_tip"))
                btn_italic = Gtk.Button(label=_("italic_tip"))
                btn_underline = Gtk.Button(label=_("underline_tip"))
                btn_strikethrough = Gtk.Button(label=_("strikethrough_tip"))
                def on_bold_clicked(b):
                    self._toggle_text_bold(clicked_text)
                def on_italic_clicked(b):
                    self._toggle_text_italic(clicked_text)
                def on_underline_clicked(b):
                    self._toggle_text_underline(clicked_text)
                def on_strikethrough_clicked(b):
                    self._toggle_text_strikethrough(clicked_text)
                btn_bold.connect("clicked", on_bold_clicked)
                btn_italic.connect("clicked", on_italic_clicked)
                btn_underline.connect("clicked", on_underline_clicked)
                btn_strikethrough.connect("clicked", on_strikethrough_clicked)
                popover_box.append(btn_bold)
                popover_box.append(btn_italic)
                popover_box.append(btn_underline)
                popover_box.append(btn_strikethrough)
                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

                align_popover_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                align_popover_box.add_css_class("linked")
                btn_al_l = Gtk.Button(icon_name="format-justify-left-symbolic")
                btn_al_l.set_tooltip_text(_("align_left_tip"))
                btn_al_l.connect("clicked", lambda b: self._set_text_alignment(clicked_text, "left"))
                align_popover_box.append(btn_al_l)

                btn_al_c = Gtk.Button(icon_name="format-justify-center-symbolic")
                btn_al_c.set_tooltip_text(_("align_center_tip"))
                btn_al_c.connect("clicked", lambda b: self._set_text_alignment(clicked_text, "center"))
                align_popover_box.append(btn_al_c)

                btn_al_r = Gtk.Button(icon_name="format-justify-right-symbolic")
                btn_al_r.set_tooltip_text(_("align_right_tip"))
                btn_al_r.connect("clicked", lambda b: self._set_text_alignment(clicked_text, "right"))
                align_popover_box.append(btn_al_r)

                btn_al_j = Gtk.Button(icon_name="format-justify-fill-symbolic")
                btn_al_j.set_tooltip_text(_("align_justify_tip"))
                btn_al_j.connect("clicked", lambda b: self._set_text_alignment(clicked_text, "justify"))
                align_popover_box.append(btn_al_j)
                popover_box.append(align_popover_box)
                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
                
                btn_hl = Gtk.Button(label=_("menu_highlight"))
                btn_hl.connect("clicked", lambda b: self._handle_context_action("highlight_edit", clicked_text, x, y))
                popover_box.append(btn_hl)
                
                btn_rm_hl = Gtk.Button(label=_("menu_remove_highlight"))
                btn_rm_hl.connect("clicked", lambda b: self._handle_context_action("remove_highlight", clicked_text, x, y))
                popover_box.append(btn_rm_hl)
                
                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
                btn_edit = Gtk.Button(label=_("menu_edit_text"))
                btn_edit.connect("clicked", lambda b: self._handle_context_action("edit_text", clicked_text, x, y))
                popover_box.append(btn_edit)

                btn_link = Gtk.Button(label=_("menu_insert_edit_link"))
                def on_link_ctx(b):
                    if hasattr(self, 'context_popover') and self.context_popover:
                        self.context_popover.popdown()
                    self.show_link_popover(clicked_text, parent_widget=self.pdf_view)
                btn_link.connect("clicked", on_link_ctx)
                popover_box.append(btn_link)

                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
                layer_box_t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                btn_front_t = Gtk.Button(label=_("action_bring_to_front"))
                btn_front_t.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("front")))
                layer_box_t.append(btn_front_t)
                btn_fwd_t = Gtk.Button(label=_("action_bring_forward"))
                btn_fwd_t.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("forward")))
                layer_box_t.append(btn_fwd_t)
                btn_back_t = Gtk.Button(label=_("action_send_backward"))
                btn_back_t.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("backward")))
                layer_box_t.append(btn_back_t)
                btn_bottom_t = Gtk.Button(label=_("action_send_to_back"))
                btn_bottom_t.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("back")))
                layer_box_t.append(btn_bottom_t)
                popover_box.append(layer_box_t)
                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

                btn_redact_t = Gtk.Button(label=_("menu_mark_for_redaction"))
                def on_redact_text(b):
                    if hasattr(self, 'context_popover') and self.context_popover:
                        self.context_popover.popdown()
                    self.mark_object_for_redaction(clicked_text, page_index=target_page)
                btn_redact_t.connect("clicked", on_redact_text)
                popover_box.append(btn_redact_t)
                
                btn_del = Gtk.Button(label=_("delete_confirm"))
                btn_del.add_css_class("destructive-action")
                def on_delete_text(b):
                    self._handle_delete_with_confirmation(clicked_text, "delete_text_confirm")
                btn_del.connect("clicked", on_delete_text)
                popover_box.append(btn_del)
            
        elif clicked_shape:
            self.selected_shape = clicked_shape
            self.selected_text = None
            self.selected_image = None

            layer_box_s = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            btn_front_s = Gtk.Button(label=_("action_bring_to_front"))
            btn_front_s.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("front")))
            layer_box_s.append(btn_front_s)
            btn_fwd_s = Gtk.Button(label=_("action_bring_forward"))
            btn_fwd_s.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("forward")))
            layer_box_s.append(btn_fwd_s)
            btn_back_s = Gtk.Button(label=_("action_send_backward"))
            btn_back_s.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("backward")))
            layer_box_s.append(btn_back_s)
            btn_bottom_s = Gtk.Button(label=_("action_send_to_back"))
            btn_bottom_s.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("back")))
            layer_box_s.append(btn_bottom_s)
            popover_box.append(layer_box_s)
            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            btn_redact_s = Gtk.Button(label=_("menu_mark_for_redaction"))
            def on_redact_shape(b):
                if hasattr(self, 'context_popover') and self.context_popover:
                    self.context_popover.popdown()
                self.mark_object_for_redaction(clicked_shape, page_index=target_page)
            btn_redact_s.connect("clicked", on_redact_shape)
            popover_box.append(btn_redact_s)
            
            btn_del = Gtk.Button(label=_("menu_delete_shape"))
            btn_del.add_css_class("destructive-action")
            def on_delete_shape(b):
                self._handle_delete_with_confirmation(clicked_shape, "delete_shape_confirm")
            btn_del.connect("clicked", on_delete_shape)
            popover_box.append(btn_del)
            
        elif clicked_image:
            self.selected_image = clicked_image
            self.selected_text = None
            self.selected_shape = None

            if getattr(clicked_image, 'is_patch', False):
                btn_type_patch = Gtk.Button(label=_("menu_type_over_patch"))
                btn_type_patch.set_tooltip_text(_("patch_type_tooltip"))
                btn_type_patch.connect("clicked", lambda b: (
                    self.context_popover.popdown() if hasattr(self, 'context_popover') and self.context_popover else None,
                    self.initiate_text_over_patch(clicked_image)
                ))
                popover_box.append(btn_type_patch)
                popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            btn_extract = Gtk.Button(label=_("menu_extract_image"))
            btn_extract.connect("clicked", lambda b: self._handle_context_action("extract_image", clicked_image, x, y))
            popover_box.append(btn_extract)

            btn_replace = Gtk.Button(label=_("menu_replace_image"))
            btn_replace.connect("clicked", lambda b: self._handle_context_action("replace_image", clicked_image, x, y))
            popover_box.append(btn_replace)

            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            layer_box_i = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            btn_front_i = Gtk.Button(label=_("action_bring_to_front"))
            btn_front_i.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("front")))
            layer_box_i.append(btn_front_i)
            btn_fwd_i = Gtk.Button(label=_("action_bring_forward"))
            btn_fwd_i.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("forward")))
            layer_box_i.append(btn_fwd_i)
            btn_back_i = Gtk.Button(label=_("action_send_backward"))
            btn_back_i.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("backward")))
            layer_box_i.append(btn_back_i)
            btn_bottom_i = Gtk.Button(label=_("action_send_to_back"))
            btn_bottom_i.connect("clicked", lambda b: (self.context_popover.popdown(), self.reorder_selected_object("back")))
            layer_box_i.append(btn_bottom_i)
            popover_box.append(layer_box_i)
            popover_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            btn_redact_i = Gtk.Button(label=_("menu_mark_for_redaction"))
            def on_redact_image(b):
                if hasattr(self, 'context_popover') and self.context_popover:
                    self.context_popover.popdown()
                self.mark_object_for_redaction(clicked_image, page_index=target_page)
            btn_redact_i.connect("clicked", on_redact_image)
            popover_box.append(btn_redact_i)

            btn_del = Gtk.Button(label=_("menu_delete_image"))
            btn_del.add_css_class("destructive-action")
            def on_delete_image(b):
                self._handle_delete_with_confirmation(clicked_image, "delete_image_confirm")
            btn_del.connect("clicked", on_delete_image)
            popover_box.append(btn_del)
            
        elif clicked_measurement:
            self.selected_measurement = clicked_measurement
            self.selected_text = None
            self.selected_shape = None
            self.selected_image = None
            
            btn_del = Gtk.Button(label=_("delete_confirm"))
            btn_del.add_css_class("destructive-action")
            def on_delete_meas(b):
                if hasattr(self, 'context_popover') and self.context_popover:
                    self.context_popover.popdown()
                self._handle_delete_with_confirmation(clicked_measurement, "delete_shape_confirm")
            btn_del.connect("clicked", on_delete_meas)
            popover_box.append(btn_del)

        else:
            popover_box_empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            popover_box_empty.set_margin_start(6); popover_box_empty.set_margin_end(6)
            popover_box_empty.set_margin_top(6); popover_box_empty.set_margin_bottom(6)
            
            btn_paste_new = Gtk.Button(label=_("btn_paste_new"))
            btn_paste_new.connect("clicked", lambda b: self._handle_context_action("paste_new_text", (page_x, page_y), x, y))
            popover_box_empty.append(btn_paste_new)

            if getattr(self, 'last_captured_patch', None):
                btn_paste_patch = Gtk.Button(label=_("btn_paste_patch"))
                btn_paste_patch.connect("clicked", lambda b: self._handle_context_action("paste_clone_patch", (page_x, page_y), x, y))
                popover_box_empty.append(btn_paste_patch)
            
            if hasattr(self, 'context_popover') and self.context_popover:
                try:
                    self.context_popover.popdown()
                    self.context_popover.unparent()
                except Exception:
                    pass
                
            self.context_popover = Gtk.Popover(autohide=True, has_arrow=True)
            self.context_popover.set_child(popover_box_empty)
            self.context_popover.set_parent(self.pdf_view)
            rect, pos = self.calculate_smart_popover_placement(None, click_pos=(x, y))
            self.context_popover.set_pointing_to(rect)
            self.context_popover.set_position(pos)
            self.context_popover.popup()
            return
            
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(self.current_page_index)
        self.drag_threshold_passed = False
        self._update_ui_state()
        self.pdf_view.queue_draw()
        
        if hasattr(self, 'context_popover') and self.context_popover:
            try:
                self.context_popover.popdown()
                self.context_popover.unparent()
            except Exception:
                pass

        self.context_popover = Gtk.Popover(autohide=True, has_arrow=True)
        self.context_popover.set_child(popover_box)
        self.context_popover.set_parent(self.pdf_view)
        clicked_obj = clicked_text or clicked_shape or clicked_image or clicked_measurement
        if is_word_mode:
            w_bbox = self.get_selected_word_bbox()
            obj_rect = self.get_object_canvas_rect(w_bbox, page_index=target_page, is_visual_coords=False) if w_bbox else self.get_object_canvas_rect(clicked_obj, page_index=target_page)
        else:
            obj_rect = self.get_object_canvas_rect(clicked_obj, page_index=target_page)
        rect, pos = self.calculate_smart_popover_placement(obj_rect, click_pos=(x, y))
        self.context_popover.set_pointing_to(rect)
        self.context_popover.set_position(pos)
        self.context_popover.popup()

    def _handle_context_action(self, action, obj, x, y):
        """Execute actions dispatched from context menu popovers."""
        if hasattr(self, 'context_popover'):
            self.context_popover.popdown()
            
        if action == "edit_text":
            self._show_inline_editor(obj, click_x=x, click_y=y)
        elif action == "delete":
            self.selected_text = obj if type(obj).__name__ == 'EditableText' else None
            self.selected_shape = obj if type(obj).__name__ == 'EditableShape' else None
            if self.selected_text or self.selected_shape:
                obj_to_delete = self.selected_text or self.selected_shape
                command = DeleteObjectCommand(self, obj_to_delete)
                command.execute()
                self.undo_manager.add_command(command)
                self.selected_text = None
                self.selected_shape = None
                self._update_ui_state()
                self.pdf_view.queue_draw()
        elif action == "copy_view":
            if self.view_selected_text:
                self.get_clipboard().set(self.view_selected_text)
        elif action == "edit_view_text":
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()
            saved_rect = self.view_sel_rect
            saved_text = self.view_selected_text or getattr(self, 'selected_word', '')
            if self.view_mode:
                self._toggle_view_edit_mode()
            if saved_rect and saved_text:
                x1, y1, x2, y2 = saved_rect
                new_obj = EditableText(x1, y1, saved_text, is_new=False)
                new_obj.bbox = (x1, y1, x2, y2)
                new_obj.page_number = self.current_page_index
                command = AddObjectCommand(self, new_obj)
                command.execute()
                self.undo_manager.add_command(command)
                self.selected_text = new_obj
                self._show_inline_editor(new_obj, click_x=x, click_y=y, target_rect=new_obj.bbox)
            elif self.selected_text:
                self._show_inline_editor(self.selected_text, click_x=x, click_y=y, target_rect=self.selected_text.bbox)
        elif action == "highlight_view":
            self.on_highlight_clicked(None)
        elif action == "highlight_edit":
            self.on_highlight_clicked(None)
        elif action == "remove_highlight":
            if obj and hasattr(obj, 'bbox'):
                self._remove_highlight_at_region(obj.bbox)
        elif action == "paste_new_text":
            page_x, page_y = obj
            clipboard = self.get_clipboard()
            def _on_paste_finished(cb, task):
                try:
                    text = cb.read_text_finish(task)
                    if text and text.strip():
                        self._create_text_from_paste(page_x, page_y, text)
                except Exception:
                    pass
            clipboard.read_text_async(None, _on_paste_finished)
        elif action == "paste_clone_patch":
            page_x, page_y = obj
            self.paste_clone_patch(center_pos=(page_x, page_y))
        elif action == "toggle_bold":
            if self.view_mode:
                self._convert_view_selection_to_editable()
            if self.selected_text:
                self._toggle_text_bold(self.selected_text)
        elif action == "toggle_italic":
            if self.view_mode:
                self._convert_view_selection_to_editable()
            if self.selected_text:
                self._toggle_text_italic(self.selected_text)
        elif action == "toggle_underline":
            if self.view_mode:
                self._convert_view_selection_to_editable()
            if self.selected_text:
                self._toggle_text_underline(self.selected_text)
        elif action == "toggle_strikethrough":
            if self.view_mode:
                self._convert_view_selection_to_editable()
            if self.selected_text:
                self._toggle_text_strikethrough(self.selected_text)
        elif action == "extract_image":
            self._extract_image(obj)
        elif action == "replace_image":
            self._replace_image(obj)

    def _extract_image(self, image_obj):
        """Export an embedded or active image to disk."""
        if not image_obj:
            return

        img_bytes, ext = pdf_handler.extract_image_data(self.doc, image_obj)
        if not img_bytes:
            show_error_dialog(self, _("err_extract_image"), _("err_title"))
            return

        page_num = getattr(image_obj, 'page_number', self.current_page_index) or 0
        xref_part = getattr(image_obj, 'xref', None) or 'extracted'
        default_name = f"image_p{page_num + 1}_{xref_part}.{ext}"

        filter_img = Gtk.FileFilter(name=_("image_filter_label"))
        filter_img.add_pattern(f"*.{ext}")
        filter_all = Gtk.FileFilter(name=_("filter_all_files"))
        filter_all.add_pattern("*")

        def on_save_finish(file):
            if file:
                save_path = file.get_path()
                try:
                    with open(save_path, "wb") as f:
                        f.write(img_bytes)
                    self.status_label.set_text(_("image_extracted_success", os.path.basename(save_path)))
                except Exception as err:
                    show_error_dialog(self, str(err), _("err_title"))

        show_save_file_dialog(
            self,
            _("menu_extract_image"),
            initial_name=default_name,
            filters=[filter_img, filter_all],
            callback=on_save_finish
        )

    def _replace_image(self, image_obj):
        """Prompt user for a replacement image file and replace using page.replace_image()."""
        if not image_obj:
            return

        filter_img = Gtk.FileFilter(name=_("image_filter_label"))
        for mime in ["image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"]:
            filter_img.add_mime_type(mime)

        def on_open_finish(file):
            if file:
                image_path = file.get_path()
                try:
                    with open(image_path, "rb") as f:
                        new_raw_bytes = f.read()
                    if not new_raw_bytes:
                        return

                    command = ReplaceImageCommand(self, image_obj, new_raw_bytes)
                    if command.execute():
                        self.undo_manager.add_command(command)
                except Exception as err:
                    show_error_dialog(self, _("image_add_error", err), _("image_error_title"))

        show_open_file_dialog(
            self,
            _("menu_replace_image"),
            filters=[filter_img],
            callback=on_open_finish
        )

    def _convert_view_selection_to_editable(self):
        """Convert view selection to editable."""
        if not self.view_sel_rect or not self.view_selected_text:
            return
            
        from .models import EditableText
        from .undo_manager import AddObjectCommand
        
        x1, y1, x2, y2 = self.view_sel_rect
        new_obj = EditableText(x1, y1, self.view_selected_text, is_new=False)
        new_obj.bbox = (x1, y1, x2, y2)
        new_obj.page_number = self.current_page_index
        
        command = AddObjectCommand(self, new_obj)
        command.execute()
        self.undo_manager.add_command(command)
        self.selected_text = new_obj
        self.view_sel_rect = None
        self.view_selected_text = None
        self.word_selection_mode = False
        self.pdf_view.queue_draw()

    def _toggle_text_bold(self, text_obj):
        """Toggle text bold."""
        if text_obj:
            self.selected_text = text_obj
            old_properties = {'is_bold': text_obj.is_bold, 'bbox': text_obj.bbox}
            new_properties = {'is_bold': not text_obj.is_bold, 'bbox': text_obj.bbox}
            command = EditObjectCommand(self, text_obj, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            self.document_modified = True
            self.pdf_view.queue_draw()
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def _toggle_text_italic(self, text_obj):
        """Toggle text italic."""
        if text_obj:
            self.selected_text = text_obj
            old_properties = {'is_italic': text_obj.is_italic, 'bbox': text_obj.bbox}
            new_properties = {'is_italic': not text_obj.is_italic, 'bbox': text_obj.bbox}
            command = EditObjectCommand(self, text_obj, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            self.document_modified = True
            self.pdf_view.queue_draw()
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def _toggle_text_underline(self, text_obj):
        """Toggle text underline."""
        if text_obj:
            self.selected_text = text_obj
            old_val = getattr(text_obj, 'is_underline', False)
            old_properties = {'is_underline': old_val, 'bbox': text_obj.bbox}
            new_properties = {'is_underline': not old_val, 'bbox': text_obj.bbox}
            command = EditObjectCommand(self, text_obj, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            self.document_modified = True
            self.pdf_view.queue_draw()
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def _toggle_text_strikethrough(self, text_obj):
        """Toggle text strikethrough."""
        if text_obj:
            self.selected_text = text_obj
            old_val = getattr(text_obj, 'is_strikethrough', False)
            old_properties = {'is_strikethrough': old_val, 'bbox': text_obj.bbox}
            new_properties = {'is_strikethrough': not old_val, 'bbox': text_obj.bbox}
            command = EditObjectCommand(self, text_obj, old_properties, new_properties)
            command.execute()
            self.undo_manager.add_command(command)
            if hasattr(self, '_update_text_format_controls'):
                self._update_text_format_controls(text_obj)
            self.document_modified = True
            self.pdf_view.queue_draw()
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def _set_text_alignment(self, text_obj, new_align):
        """Set text alignment with undo/redo."""
        if text_obj:
            self.selected_text = text_obj
            old_val = getattr(text_obj, 'alignment', 'left')
            if old_val != new_align:
                old_properties = {'alignment': old_val, 'bbox': text_obj.bbox}
                new_properties = {'alignment': new_align, 'bbox': text_obj.bbox}
                command = EditObjectCommand(self, text_obj, old_properties, new_properties)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self.pdf_view.queue_draw()
                if hasattr(self, '_update_text_format_controls'):
                    self._update_text_format_controls(text_obj)
            if hasattr(self, 'context_popover') and self.context_popover:
                self.context_popover.popdown()

    def on_insert_edit_link_clicked(self, button=None):
        """Handle toolbar Insert/Edit link button click."""
        target = self.selected_text
        if not target:
            return
        anchor = getattr(self, 'link_button', self.pdf_view)
        self.show_link_popover(target, parent_widget=anchor)

    def show_link_popover(self, text_obj, parent_widget=None, point_rect=None):
        """Display popover dialog allowing user to insert, edit, or remove hyperlink for text_obj."""
        if not text_obj:
            return

        if hasattr(self, '_link_popover') and self._link_popover:
            try:
                self._link_popover.popdown()
                self._link_popover.unparent()
            except Exception:
                pass
            self._link_popover = None

        popover = Gtk.Popover(autohide=True, has_arrow=True)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)

        title_lbl = Gtk.Label(label=_("dialog_link_title"))
        title_lbl.add_css_class("heading")
        title_lbl.set_halign(Gtk.Align.START)
        content_box.append(title_lbl)

        url_lbl = Gtk.Label(label=_("link_url_label"))
        url_lbl.set_halign(Gtk.Align.START)
        url_lbl.add_css_class("dim-label")
        content_box.append(url_lbl)

        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("https://example.com")
        url_entry.set_width_chars(32)

        initial_url = getattr(text_obj, 'link_url', None) or ""
        if not initial_url and hasattr(text_obj, 'get_link_url'):
            initial_url = text_obj.get_link_url() or ""
        url_entry.set_text(initial_url)
        content_box.append(url_entry)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_halign(Gtk.Align.END)

        def apply_link(b=None):
            target_url = url_entry.get_text().strip()
            popover.popdown()
            if target_url:
                self._apply_text_link(text_obj, target_url)
            else:
                self._remove_text_link(text_obj)

        def remove_link(b=None):
            popover.popdown()
            self._remove_text_link(text_obj)

        def cancel_link(b=None):
            popover.popdown()

        btn_cancel = Gtk.Button(label=_("btn_cancel"))
        btn_cancel.connect("clicked", cancel_link)
        btn_box.append(btn_cancel)

        if getattr(text_obj, 'link_url', None) or getattr(text_obj, 'is_link', False):
            btn_remove = Gtk.Button(label=_("btn_remove_link"))
            btn_remove.add_css_class("destructive-action")
            btn_remove.connect("clicked", remove_link)
            btn_box.append(btn_remove)

        btn_apply = Gtk.Button(label=_("btn_apply"))
        btn_apply.add_css_class("suggested-action")
        btn_apply.connect("clicked", apply_link)
        url_entry.connect("activate", apply_link)
        btn_box.append(btn_apply)

        content_box.append(btn_box)
        popover.set_child(content_box)

        anchor = parent_widget or getattr(self, 'link_button', self.pdf_view)
        popover.set_parent(anchor)
        if point_rect:
            popover.set_pointing_to(point_rect)
        elif text_obj and anchor == self.pdf_view:
            obj_rect = self.get_object_canvas_rect(text_obj)
            if obj_rect:
                p_rect, pos = self.calculate_smart_popover_placement(obj_rect, estimated_size=(280, 200))
                popover.set_pointing_to(p_rect)
                popover.set_position(pos)
        self._link_popover = popover
        popover.popup()

    def _apply_text_link(self, text_obj, url: str):
        """Apply hyperlink URL and blue underlined styling to text_obj."""
        if not text_obj or not url:
            return
        if not url.startswith(("http://", "https://", "mailto:")):
            url = "https://" + url
        self.selected_text = text_obj
        old_props = {
            'link_url': getattr(text_obj, 'link_url', None),
            'color': getattr(text_obj, 'color', (0.0, 0.0, 0.0)),
            'is_underline': getattr(text_obj, 'is_underline', False),
            'bbox': text_obj.bbox
        }
        # Hyperlink styling: blue #0000ee and underline
        new_props = {
            'link_url': url,
            'color': (0.0, 0.0, 238.0 / 255.0),
            'is_underline': True,
            'bbox': text_obj.bbox
        }
        cmd = EditObjectCommand(self, text_obj, old_props, new_props)
        cmd.execute()
        self.undo_manager.add_command(cmd)
        self._update_text_format_controls(text_obj)
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("link_applied_success"))
        self.document_modified = True
        self.pdf_view.queue_draw()

    def _remove_text_link(self, text_obj):
        """Remove hyperlink URL from text_obj and restore original properties."""
        if not text_obj:
            return
        self.selected_text = text_obj
        old_props = {
            'link_url': getattr(text_obj, 'link_url', None),
            'color': getattr(text_obj, 'color', (0.0, 0.0, 0.0)),
            'is_underline': getattr(text_obj, 'is_underline', False),
            'bbox': text_obj.bbox
        }
        orig_color = getattr(text_obj, 'original_color', (0.0, 0.0, 0.0))
        if orig_color == (0.0, 0.0, 238.0 / 255.0):
            orig_color = (0.0, 0.0, 0.0)
        new_props = {
            'link_url': None,
            'color': orig_color,
            'is_underline': False,
            'bbox': text_obj.bbox
        }
        cmd = EditObjectCommand(self, text_obj, old_props, new_props)
        cmd.execute()
        self.undo_manager.add_command(cmd)
        self._update_text_format_controls(text_obj)
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("link_removed_success"))
        self.document_modified = True
        self.pdf_view.queue_draw()

    def _get_link_url_at_pos(self, page_x, page_y):
        """Find destination URL at page coordinates from editable texts or PDF link annotations."""
        if hasattr(self, '_get_page_spatial_index') and hasattr(self, '_spatial_indices') and isinstance(getattr(self, '_spatial_indices', None), dict):
            grid = self._get_page_spatial_index(self.current_page_index, "text")
            candidates = grid.query_point(page_x, page_y)
        else:
            candidates = getattr(self, 'editable_texts', [])
        for t in candidates:
            if getattr(t, 'page_number', None) != self.current_page_index:
                continue
            if getattr(t, 'bbox', None):
                bx1, by1, bx2, by2 = t.bbox
                if min(bx1, bx2) <= page_x <= max(bx1, bx2) and min(by1, by2) <= page_y <= max(by1, by2):
                    if getattr(t, 'is_link', False):
                        url = t.get_link_url() if hasattr(t, 'get_link_url') else getattr(t, 'link_url', None)
                        if url:
                            return url
        if getattr(self, 'doc', None) and 0 <= self.current_page_index < len(self.doc):
            try:
                if not hasattr(self, '_cached_page_links'):
                    self._cached_page_links = {}
                cache_key = (id(self.doc), self.current_page_index)
                links = self._cached_page_links.get(cache_key)
                if links is None:
                    page = self.doc[self.current_page_index]
                    links = list(page.get_links())
                    self._cached_page_links[cache_key] = links
                pt = fitz.Point(page_x, page_y)
                for link in links:
                    if link.get('kind') == fitz.LINK_URI and link.get('uri'):
                        rect = link.get('from')
                        if rect and rect.contains(pt):
                            return link.get('uri')
            except Exception:
                pass
        return None

    def _open_url(self, url: str):
        """Open web link in the system default browser."""
        if not url:
            return
        if not url.startswith(("http://", "https://", "mailto:")):
            url = "https://" + url
        try:
            from gi.repository import Gtk, Gdk
            Gtk.show_uri(self, url, Gdk.CURRENT_TIME)
        except Exception:
            try:
                from gi.repository import Gio
                Gio.AppInfo.launch_default_for_uri(url, None)
            except Exception:
                try:
                    import webbrowser
                    webbrowser.open(url)
                except Exception as e:
                    print(f"Warning: could not open URL {url}: {e}")

    def _update_confirm_delete_menu_state(self, val: bool):
        """Update the confirm delete menu action state."""
        if hasattr(self, 'action_confirm_delete'):
            self.action_confirm_delete.set_state(GLib.Variant.new_boolean(val))

    def _handle_delete_with_confirmation(self, obj, confirmation_key):
        """Handle delete with confirmation."""
        from .ui_components import show_confirm_dialog
        
        if isinstance(obj, EditableText):
            confirm_text = _("delete_text_confirm").format(f"{obj.text[:50]}...")
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, EditableShape):
            confirm_text = _("delete_shape_confirm")
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, EditableImage):
            confirm_text = _("delete_image_confirm")
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, EditableStroke):
            confirm_text = _("delete_shape_confirm")
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, AcroFormField):
            fname = getattr(obj, 'field_name', '') or 'field'
            confirm_text = _("delete_form_field_confirm").format(fname)
            confirm_title = _("delete_confirm_title")
        elif isinstance(obj, MeasurementObject):
            confirm_text = _("delete_shape_confirm")
            confirm_title = _("delete_confirm_title")
        else:
            return

        confirm_needed = get_setting("confirm_delete_objects", True)
        confirmed = True
        if confirm_needed:
            confirmed, do_not_ask = show_confirm_dialog(
                self, confirm_text, confirm_title, destructive=True,
                checkbox_label=_("do_not_ask_again")
            )
            if confirmed and do_not_ask:
                set_setting("confirm_delete_objects", False)
                self._update_confirm_delete_menu_state(False)
            
        if confirmed:
            if isinstance(obj, MeasurementObject):
                self.selected_measurement = None
                command = DeleteMeasurementCommand(self, obj)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self._update_tab_dirty_state()
                self._update_ui_state()
                self.pdf_view.queue_draw()
                self.status_label.set_text(_("object_deleted"))
                return
            if isinstance(obj, AcroFormField):
                if getattr(self, '_active_editing_form_field', None) == obj:
                    self._close_active_form_field_editor()
                self.selected_form_field = None
                command = DeleteFormFieldCommand(self, obj)
                command.execute()
                self.undo_manager.add_command(command)
                self.document_modified = True
                self._update_tab_dirty_state()
                self._update_form_builder_controls_for_selected()
                self._update_ui_state()
                self.pdf_view.queue_draw()
                self.status_label.set_text(_("object_deleted"))
                return
            if getattr(obj, 'linked_text', None) and obj.linked_text in getattr(self, 'editable_texts', []):
                cmd1 = DeleteObjectCommand(self, obj)
                cmd2 = DeleteObjectCommand(self, obj.linked_text)
                command = CompositeCommand(self, [cmd1, cmd2])
            elif getattr(obj, 'linked_patch', None) and obj.linked_patch in getattr(self, 'editable_images', []):
                obj.linked_patch.linked_text = None
                command = DeleteObjectCommand(self, obj)
            else:
                command = DeleteObjectCommand(self, obj)
            command.execute()
            self.undo_manager.add_command(command)
            self.selected_text = None
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.selected_measurement = None
            self._update_ui_state()
            self.pdf_view.queue_draw()
            self.status_label.set_text(_("object_deleted"))

    def _remove_highlight_at_region(self, bbox, is_visual=False):
        """Remove highlight at region."""
        if not self.doc:
            return
        try:
            success, removed_count = pdf_handler.remove_highlight_annotations(
                self.doc, self.current_page_index, bbox, is_visual=is_visual
            )
            if success and removed_count > 0:
                pdf_handler.invalidate_page_cache(self.doc, self.current_page_index)
                self.document_modified = True
                self._refresh_thumbnail(self.current_page_index)
                self._update_ui_state()
                self.pdf_view.queue_draw()
        except Exception as e:
            print(f"Error removing highlight: {e}")

    def _create_text_from_paste(self, page_x, page_y, text):
        """Create text from paste."""
        if not self.doc or not text or not text.strip():
            return
        
        try:
            font_family = self._last_font_family or "Liberation Sans"
            font_size = self._last_font_size or 11.0
            is_bold = self._last_is_bold or False
            is_italic = self._last_is_italic or False
            is_strikethrough = getattr(self, '_last_is_strikethrough', False)
            alignment = getattr(self, '_last_alignment', 'left')
            color = self._last_color or (0.0, 0.0, 0.0)
            
            new_text = EditableText(
                x=page_x,
                y=page_y,
                text=text.strip(),
                font_size=font_size,
                font_family=font_family,
                color=color,
                is_new=True,
                baseline=page_y + (font_size * 0.85),
                alignment=alignment
            )
            new_text.is_bold = is_bold
            new_text.is_italic = is_italic
            new_text.is_strikethrough = is_strikethrough
            new_text.page_number = self.current_page_index
            
            command = AddObjectCommand(self, new_text)
            command.execute()
            self.undo_manager.add_command(command)
            
            self.selected_text = new_text
            self._update_text_format_controls(new_text)
            self.document_modified = True
            self._refresh_thumbnail(self.current_page_index)
            self._update_ui_state()
            self.pdf_view.queue_draw()
            
        except Exception as e:
            print(f"Error creating text from paste: {e}")

    def paste_clone_patch(self, center_pos=None):
        """Paste a copy of the last captured clone patch onto current page."""
        if not getattr(self, 'last_captured_patch', None) or not self.doc:
            return False
        patch_data = self.last_captured_patch
        orig_bbox = patch_data["bbox"]
        pw = orig_bbox[2] - orig_bbox[0]
        ph = orig_bbox[3] - orig_bbox[1]

        page_num = self.current_page_index
        try:
            page = self.doc.load_page(page_num)
            p_width, p_height = page.rect.width, page.rect.height
        except Exception:
            p_width, p_height = 595.0, 842.0

        if center_pos:
            cx, cy = center_pos
        elif getattr(self, 'last_mouse_page_pos', None):
            cx, cy = self.last_mouse_page_pos
        elif getattr(self, '_last_pointer_pos', None):
            try:
                screen_x, screen_y = self._last_pointer_pos
                p_idx, px, py = self.find_page_at_point(screen_x, screen_y)
                if p_idx == page_num and px is not None:
                    cx, cy = px, py
                else:
                    cx, cy = p_width / 2.0, p_height / 2.0
            except Exception:
                cx, cy = p_width / 2.0, p_height / 2.0
        else:
            cx, cy = p_width / 2.0, p_height / 2.0

        x1 = cx - pw / 2.0
        y1 = cy - ph / 2.0
        x2 = cx + pw / 2.0
        y2 = cy + ph / 2.0

        if x1 < 0:
            x2 += -x1
            x1 = 0.0
        if y1 < 0:
            y2 += -y1
            y1 = 0.0
        if x2 > p_width:
            shift = x2 - p_width
            x1 = max(0.0, x1 - shift)
            x2 = p_width
        if y2 > p_height:
            shift = y2 - p_height
            y1 = max(0.0, y1 - shift)
            y2 = p_height

        new_patch = PatchObject(
            bbox=(x1, y1, x2, y2),
            page_number=page_num,
            image_bytes=patch_data["image_bytes"],
            is_new=True,
            opacity=1.0,
        )
        command = AddObjectCommand(self, new_patch)
        command.execute()
        if getattr(self, 'undo_manager', None):
            self.undo_manager.add_command(command)

        self.selected_image = new_patch
        self.selected_text = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None

        self.tool_mode = "select"
        self.document_modified = True
        if hasattr(self, '_refresh_thumbnail'):
            self._refresh_thumbnail(page_num)
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("patch_pasted_status"))
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(self.current_page_index)
        self.drag_threshold_passed = False
        self._update_ui_state()
        self.pdf_view.queue_draw()
        return True

    def initiate_text_over_patch(self, patch_obj):
        """Initiate immediate text correction layered over a texture patch object."""
        if not patch_obj or not getattr(patch_obj, 'bbox', None) or not self.doc:
            return None

        target_page = getattr(patch_obj, 'page_number', self.current_page_index)
        if target_page != self.current_page_index:
            self._switch_active_page(target_page)

        linked = getattr(patch_obj, 'linked_text', None)
        if linked and linked in getattr(self, 'editable_texts', []):
            self.selected_text = linked
            self.selected_image = None
            self.selected_shape = None
            self.selected_stroke = None
            self.selected_form_field = None
            self.selected_measurement = None
            self._update_text_format_controls(linked)
            self._show_inline_editor(linked, target_rect=patch_obj.bbox)
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.set_text(_("status_patch_text_added"))
            self.pdf_view.queue_draw()
            self._update_ui_state()
            return linked

        x1, y1, x2, y2 = patch_obj.bbox
        patch_h = abs(y2 - y1)
        font_size = getattr(self, 'font_size', 12)
        if hasattr(self, 'font_size_spin') and self.font_size_spin:
            try:
                toolbar_size = self.font_size_spin.get_value()
                if toolbar_size > 0:
                    font_size = toolbar_size
            except Exception:
                pass
        elif 8.0 <= patch_h * 0.7 <= 48.0:
            font_size = round(patch_h * 0.7, 1)

        color = getattr(self, 'font_color', (0.0, 0.0, 0.0))
        target_family_key = getattr(self, 'font_family', "Liberation Sans") or "Liberation Sans"
        target_base14 = "Helvetica"
        if hasattr(self, 'font_combo') and self.font_combo:
            c_iter = self.font_combo.get_active_iter()
            if c_iter and hasattr(self, 'font_store') and self.font_store:
                import re
                model_key = self.font_store[c_iter][1]
                normalized_for_base14 = re.sub(r'[^a-zA-Z0-9]', '', model_key).lower()
                for name_key, base14_val in BASE14_FALLBACK_MAP.items():
                    if name_key in normalized_for_base14:
                        target_base14 = base14_val
                        break

        unrot_x = x1 + 2.0
        unrot_y = y1 + 1.0
        baseline = y1 + font_size * 0.85

        new_text_obj = EditableText(
            x=unrot_x,
            y=unrot_y,
            text="",
            font_size=font_size,
            color=color,
            is_new=True,
            baseline=baseline,
            page_number=target_page
        )
        new_text_obj.bbox = (unrot_x, unrot_y, x2, y2)
        new_text_obj.original_bbox = (unrot_x, unrot_y, x2, y2)
        new_text_obj.font_family_base = target_family_key
        new_text_obj.font_family_original = _("font_user_added", target_family_key)
        new_text_obj.pdf_fontname_base14 = target_base14
        new_text_obj.linked_patch = patch_obj
        patch_obj.linked_text = new_text_obj

        self.editable_texts.append(new_text_obj)
        self.selected_text = new_text_obj
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.selected_measurement = None

        self._update_text_format_controls(new_text_obj)
        self._show_inline_editor(new_text_obj, target_rect=patch_obj.bbox)
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(_("status_patch_text_added"))
        if hasattr(self, '_invalidate_spatial_index'):
            self._invalidate_spatial_index(self.current_page_index)
        self.drag_threshold_passed = False
        self._update_ui_state()
        self.pdf_view.queue_draw()
        return new_text_obj

    def reorder_selected_object(self, direction):
        """Move selected canvas object in the unified per-page z-order."""
        selected_obj = (self.selected_text or self.selected_image or self.selected_shape or
                        getattr(self, 'selected_stroke', None) or
                        getattr(self, 'selected_measurement', None))
        if not selected_obj:
            return False

        page_no = getattr(selected_obj, 'page_number', self.current_page_index)
        page_objs = []
        for coll in (getattr(self, 'editable_images', []), self.editable_shapes,
                     getattr(self, 'editable_strokes', []), self.editable_texts,
                     getattr(self, 'measurements', []), getattr(self, 'sticky_notes', [])):
            for o in coll:
                if getattr(o, 'page_number', None) == page_no and o not in page_objs:
                    page_objs.append(o)

        if selected_obj not in page_objs or len(page_objs) <= 1:
            return False

        ordered = pdf_handler.sort_by_layer(page_objs)
        old_idx = ordered.index(selected_obj)
        last = len(ordered) - 1
        if direction == "front":
            new_idx = last
            msg = _("status_reordered_front")
        elif direction == "back":
            new_idx = 0
            msg = _("status_reordered_back")
        elif direction == "forward":
            new_idx = min(last, old_idx + 1)
            msg = _("status_reordered_forward")
        elif direction == "backward":
            new_idx = max(0, old_idx - 1)
            msg = _("status_reordered_backward")
        else:
            return False

        if old_idx == new_idx:
            return False

        new_order = list(ordered)
        new_order.remove(selected_obj)
        new_order.insert(new_idx, selected_obj)
        z_changes = [(o, getattr(o, 'z_index', None), i) for i, o in enumerate(new_order)]

        command = ReorderObjectCommand(self, selected_obj, old_idx, new_idx, z_changes=z_changes)
        command.execute()
        if getattr(self, 'undo_manager', None):
            self.undo_manager.add_command(command)
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.set_text(msg)
        return True

    def toggle_annotations_sidebar(self, visible: Optional[bool] = None):
        """Toggle or explicitly set visibility of the annotations sidebar."""
        if not hasattr(self, 'annotations_sidebar') or self.annotations_sidebar is None:
            return
        new_vis = not self.annotations_sidebar.get_visible() if visible is None else visible
        self.annotations_sidebar.set_visible(new_vis)
        if hasattr(self, 'toggle_annotations_button') and self.toggle_annotations_button:
            if self.toggle_annotations_button.get_active() != new_vis:
                self.toggle_annotations_button.set_active(new_vis)
        if new_vis:
            self.annotations_sidebar.refresh()

    def refresh_annotations_list(self):
        """Refresh the annotations sidebar list store if it is currently visible."""
        if hasattr(self, 'annotations_sidebar') and self.annotations_sidebar:
            if self.annotations_sidebar.get_visible():
                self.annotations_sidebar.refresh()

    def select_and_scroll_to_annotation(self, item):
        """Select the target object or annotation and scroll the canvas viewport to center it."""
        if not item:
            return

        page_index = item.page_number
        if self.doc and 0 <= page_index < len(self.doc):
            if page_index != self.current_page_index:
                self._load_page(page_index, preserve_scroll=True)

        # Clear canvas selections
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        if hasattr(self, 'selected_stroke'):
            self.selected_stroke = None
        if hasattr(self, 'selected_form_field'):
            self.selected_form_field = None
        if hasattr(self, 'selected_measurement'):
            self.selected_measurement = None
        if hasattr(self, 'selected_sticky_note'):
            self.selected_sticky_note = None
        self.highlighted_native_annot = None

        target = getattr(item, 'target_obj', None)
        if target is not None:
            if isinstance(target, EditableText):
                self.selected_text = target
            elif isinstance(target, EditableImage):
                self.selected_image = target
            elif isinstance(target, EditableShape):
                self.selected_shape = target
            elif isinstance(target, EditableStroke):
                self.selected_stroke = target
            elif isinstance(target, AcroFormField):
                self.selected_form_field = target
            elif isinstance(target, MeasurementObject):
                self.selected_measurement = target
            elif isinstance(target, StickyNoteObject):
                self.selected_sticky_note = target
            else:
                self.highlighted_native_annot = {
                    'bbox': item.bbox,
                    'page': page_index,
                    'type': item.item_type,
                    'title': item.title,
                }
        else:
            matched = False
            if item.item_type == "image" and hasattr(self, 'editable_images'):
                for img in self.editable_images:
                    ib = getattr(img, 'bbox', None)
                    if ib and item.bbox and abs(ib[0] - item.bbox[0]) < 2.0 and abs(ib[1] - item.bbox[1]) < 2.0:
                        self.selected_image = img
                        matched = True
                        break
            if not matched:
                self.highlighted_native_annot = {
                    'bbox': item.bbox,
                    'page': page_index,
                    'type': item.item_type,
                    'title': item.title,
                }

        bbox = getattr(item, 'bbox', None)
        if bbox and any(c != 0.0 for c in bbox):
            self.scroll_to_object_rect(page_index, bbox)

        self.pdf_view.queue_draw()
        self._update_ui_state()

    def scroll_to_object_rect(self, page_index: int, bbox: Tuple[float, float, float, float]):
        """Scroll the canvas viewport to center the specified object bounding box."""
        if not self.doc or page_index >= len(self.doc):
            return

        if page_index != self.current_page_index:
            self._load_page(page_index, preserve_scroll=True)

        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0

        vis_cx, vis_cy = self._unrotated_to_visual_page_coords(cx, cy, page_index=page_index)
        target_canvas_x, target_canvas_y = self.page_to_canvas_coords(page_index, vis_cx, vis_cy)

        h_adj = self.pdf_scroll.get_hadjustment()
        v_adj = self.pdf_scroll.get_vadjustment()

        def do_scroll():
            self._is_programmatic_scrolling = True
            try:
                if h_adj:
                    vp_w = h_adj.get_page_size()
                    if vp_w > 0:
                        target_h = max(0.0, target_canvas_x - vp_w / 2.0)
                        max_h = max(0.0, h_adj.get_upper() - vp_w)
                        h_adj.set_value(min(target_h, max_h))

                if v_adj:
                    vp_h = v_adj.get_page_size()
                    if vp_h > 0:
                        target_v = max(0.0, target_canvas_y - vp_h / 2.0)
                        max_v = max(0.0, v_adj.get_upper() - vp_h)
                        v_adj.set_value(min(target_v, max_v))
            finally:
                self._is_programmatic_scrolling = False
            self.pdf_view.queue_draw()

        GLib.idle_add(do_scroll)
