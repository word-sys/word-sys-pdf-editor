from __future__ import annotations

import io
import math
import os
import threading
from typing import Optional, Callable, Dict, Tuple

import cairo
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GdkPixbuf
import pymupdf as fitz

from .i18n import _
from .compressor import (
    PRESET_BALANCED,
    PRESET_MAXIMUM,
    PRESET_HIGH_QUALITY,
    PRESET_LOSSLESS,
    PRESET_MAX_BW,
    CompressionOptions,
    CompressionResult,
    get_preset_options,
    compress_pdf_bytes,
    format_bytes,
)
from .ui_components import show_save_file_dialog


class CompressionCompareDialog(Adw.Window):
    def __init__(
        self,
        parent_window,
        pdf_bytes: bytes,
        initial_filename: Optional[str] = None,
        initial_preset: str = PRESET_BALANCED,
        initial_grayscale: bool = False,
        on_saved_callback: Optional[Callable[[str], None]] = None,
    ):
        super().__init__()
        self.parent_window = parent_window
        self.pdf_bytes = pdf_bytes
        self.initial_filename = initial_filename or "document.pdf"
        self.active_preset = initial_preset
        self.grayscale_enabled = initial_grayscale
        self.on_saved_callback = on_saved_callback

        self.set_title(_("compress_compare_title"))
        self.set_default_size(840, 620)
        if parent_window:
            self.set_transient_for(parent_window)
            self.set_modal(True)

        self.orig_doc = fitz.open(stream=self.pdf_bytes, filetype="pdf")
        self.total_pages = max(1, len(self.orig_doc))
        self.current_page = 0
        self.zoom_level = 1.0
        self.split_pos = 0.5
        self.view_mode = "side"

        self.compressed_doc: Optional[fitz.Document] = None
        self.compressed_result: Optional[CompressionResult] = None
        self._calc_token = 0
        self._pixbuf_cache: Dict[Tuple, GdkPixbuf.Pixbuf] = {}

        self._build_ui()
        self._setup_key_controller()
        self.stack.set_visible_child_name("side")
        self._update_views()
        self.connect("map", lambda w: GLib.idle_add(self._fit_to_window))
        self._trigger_recompression()

    def _build_ui(self):
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root_box)

        # HeaderBar
        header = Adw.HeaderBar()
        root_box.append(header)

        # Left Header items: Close & Page Navigation
        close_btn = Gtk.Button(label=_("btn_cancel"))
        close_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(close_btn)

        page_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.prev_page_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.prev_page_btn.set_tooltip_text(_("compress_compare_prev_page"))
        self.prev_page_btn.set_sensitive(False)
        self.prev_page_btn.connect("clicked", lambda b: self._change_page(-1))
        page_box.append(self.prev_page_btn)

        self.page_label = Gtk.Label(label=_("compress_compare_page_info", 1, self.total_pages))
        self.page_label.add_css_class("dim-label")
        page_box.append(self.page_label)

        self.next_page_btn = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_page_btn.set_tooltip_text(_("compress_compare_next_page"))
        self.next_page_btn.set_sensitive(self.total_pages > 1)
        self.next_page_btn.connect("clicked", lambda b: self._change_page(1))
        page_box.append(self.next_page_btn)
        header.pack_start(page_box)

        # Center Header: View Mode Switcher
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        mode_box.add_css_class("linked")
        self.btn_mode_side = Gtk.ToggleButton(label=_("compress_compare_view_side"))
        self.btn_mode_side.set_active(True)
        self.btn_mode_side.connect("toggled", self._on_mode_toggled)
        mode_box.append(self.btn_mode_side)

        self.btn_mode_split = Gtk.ToggleButton(label=_("compress_compare_view_split"))
        self.btn_mode_split.set_group(self.btn_mode_side)
        mode_box.append(self.btn_mode_split)
        header.set_title_widget(mode_box)

        # Right Header: Zoom Controls & Save
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        zoom_out_btn = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        zoom_out_btn.connect("clicked", lambda b: self._adjust_zoom(-0.25))
        zoom_box.append(zoom_out_btn)

        self.zoom_label = Gtk.Label(label="100%")
        self.zoom_label.set_width_chars(5)
        zoom_box.append(self.zoom_label)

        zoom_in_btn = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        zoom_in_btn.connect("clicked", lambda b: self._adjust_zoom(0.25))
        zoom_box.append(zoom_in_btn)

        fit_btn = Gtk.Button.new_from_icon_name("zoom-fit-best-symbolic")
        fit_btn.set_tooltip_text(_("compress_compare_zoom_fit"))
        fit_btn.connect("clicked", lambda b: self._fit_to_window())
        zoom_box.append(fit_btn)
        header.pack_end(zoom_box)

        self.save_btn = Gtk.Button(label=_("btn_save"))
        self.save_btn.set_tooltip_text(_("compress_compare_save_btn"))
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(self.save_btn)

        # Viewport Stack (Side-by-Side vs Wipe) - Full Width & Height
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        root_box.append(self.stack)

        # View 1: Side by Side
        side_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
        side_box.set_margin_start(8)
        side_box.set_margin_end(8)
        side_box.set_margin_top(8)
        side_box.set_margin_bottom(8)

        # Left Column: Original
        col_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.lbl_orig = Gtk.Label(label=_("compress_compare_orig_badge"))
        self.lbl_orig.add_css_class("heading")
        col_left.append(self.lbl_orig)

        self.scrolled_orig = Gtk.ScrolledWindow()
        self.scrolled_orig.set_hexpand(True)
        self.scrolled_orig.set_vexpand(True)
        self.pic_orig = Gtk.Picture()
        self.pic_orig.set_halign(Gtk.Align.CENTER)
        self.pic_orig.set_valign(Gtk.Align.CENTER)
        self.scrolled_orig.set_child(self.pic_orig)
        col_left.append(self.scrolled_orig)
        side_box.append(col_left)

        # Right Column: Compressed
        col_right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.lbl_comp = Gtk.Label(label=_("compress_compare_comp_badge"))
        self.lbl_comp.add_css_class("heading")
        col_right.append(self.lbl_comp)

        self.scrolled_comp = Gtk.ScrolledWindow()
        self.scrolled_comp.set_hexpand(True)
        self.scrolled_comp.set_vexpand(True)
        self.pic_comp = Gtk.Picture()
        self.pic_comp.set_halign(Gtk.Align.CENTER)
        self.pic_comp.set_valign(Gtk.Align.CENTER)
        self.scrolled_comp.set_child(self.pic_comp)
        col_right.append(self.scrolled_comp)
        side_box.append(col_right)

        # Synchronize Viewports in lockstep
        self.scrolled_comp.set_hadjustment(self.scrolled_orig.get_hadjustment())
        self.scrolled_comp.set_vadjustment(self.scrolled_orig.get_vadjustment())

        self.stack.add_named(side_box, "side")

        # View 2: Split Wipe Slider Canvas
        wipe_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        wipe_box.set_margin_start(8)
        wipe_box.set_margin_end(8)
        wipe_box.set_margin_top(8)
        wipe_box.set_margin_bottom(8)

        wipe_badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl_wipe_orig = Gtk.Label(label=_("compress_compare_orig_badge"))
        lbl_wipe_orig.add_css_class("heading")
        wipe_badge_box.append(lbl_wipe_orig)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        wipe_badge_box.append(spacer)

        self.lbl_wipe_comp = Gtk.Label(label=_("compress_compare_comp_badge"))
        self.lbl_wipe_comp.add_css_class("heading")
        wipe_badge_box.append(self.lbl_wipe_comp)
        wipe_box.append(wipe_badge_box)

        self.scrolled_wipe = Gtk.ScrolledWindow()
        self.scrolled_wipe.set_hexpand(True)
        self.scrolled_wipe.set_vexpand(True)

        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_halign(Gtk.Align.CENTER)
        self.drawing_area.set_valign(Gtk.Align.CENTER)
        self.drawing_area.set_draw_func(self._on_draw_wipe, None)

        drag_gesture = Gtk.GestureDrag()
        drag_gesture.connect("drag-begin", self._on_drag_begin)
        drag_gesture.connect("drag-update", self._on_drag_update)
        self.drawing_area.add_controller(drag_gesture)

        self.scrolled_wipe.set_child(self.drawing_area)
        wipe_box.append(self.scrolled_wipe)

        self.stack.add_named(wipe_box, "wipe")

        # Bottom Controls Toolbar - Clean 2-Row Compact Layout
        root_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bottom_box.set_margin_start(16)
        bottom_box.set_margin_end(16)
        bottom_box.set_margin_top(6)
        bottom_box.set_margin_bottom(6)
        root_box.append(bottom_box)

        # Row 1: Linked Presets Centered
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row1.set_halign(Gtk.Align.CENTER)
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        preset_box.add_css_class("linked")

        self.btn_bal = Gtk.ToggleButton(label=_("compress_preset_balanced_short"))
        self.btn_bal.set_tooltip_text(_("compress_preset_balanced_title") + " (150 DPI) - " + _("compress_preset_balanced_desc"))
        preset_box.append(self.btn_bal)

        self.btn_max = Gtk.ToggleButton(label=_("compress_preset_maximum_short"))
        self.btn_max.set_group(self.btn_bal)
        self.btn_max.set_tooltip_text(_("compress_preset_maximum_title") + " (72 DPI) - " + _("compress_preset_maximum_desc"))
        preset_box.append(self.btn_max)

        self.btn_max_bw = Gtk.ToggleButton(label=_("compress_preset_max_bw_short"))
        self.btn_max_bw.set_group(self.btn_bal)
        self.btn_max_bw.set_tooltip_text(_("compress_preset_max_bw_title") + " - " + _("compress_preset_max_bw_desc"))
        preset_box.append(self.btn_max_bw)

        self.btn_high = Gtk.ToggleButton(label=_("compress_preset_high_short"))
        self.btn_high.set_group(self.btn_bal)
        self.btn_high.set_tooltip_text(_("compress_preset_high_title") + " (300 DPI) - " + _("compress_preset_high_desc"))
        preset_box.append(self.btn_high)

        self.btn_lossless = Gtk.ToggleButton(label=_("compress_preset_lossless_short"))
        self.btn_lossless.set_group(self.btn_bal)
        self.btn_lossless.set_tooltip_text(_("compress_preset_lossless_title") + " - " + _("compress_preset_lossless_desc"))
        preset_box.append(self.btn_lossless)
        row1.append(preset_box)
        bottom_box.append(row1)

        # Aliases for backward compatibility
        self.radio_bal = self.btn_bal
        self.radio_max = self.btn_max
        self.radio_max_bw = self.btn_max_bw
        self.radio_high = self.btn_high
        self.radio_lossless = self.btn_lossless

        # Row 2: Grayscale toggle (left) and Stats summary (right)
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row2.set_halign(Gtk.Align.FILL)

        gray_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        gray_box.set_valign(Gtk.Align.CENTER)
        lbl_gray = Gtk.Label(label=_("compress_grayscale_title"))
        lbl_gray.add_css_class("dim-label")
        gray_box.append(lbl_gray)

        self.gray_switch = Gtk.Switch()
        self.gray_switch.set_valign(Gtk.Align.CENTER)
        self.gray_switch.set_active(self.grayscale_enabled)
        self.gray_switch.connect("notify::active", lambda s, p: self._on_grayscale_changed())
        gray_box.append(self.gray_switch)
        row2.append(gray_box)

        spacer_b = Gtk.Box()
        spacer_b.set_hexpand(True)
        row2.append(spacer_b)

        stats_pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        stats_pill.add_css_class("card")
        stats_pill.set_valign(Gtk.Align.CENTER)

        self.stats_icon = Gtk.Image.new_from_icon_name("document-save-symbolic")
        self.stats_icon.set_margin_start(8)
        stats_pill.append(self.stats_icon)

        self.stats_spinner = Gtk.Spinner()
        self.stats_spinner.start()
        stats_pill.append(self.stats_spinner)
        self.spinner = self.stats_spinner

        orig_str = format_bytes(len(self.pdf_bytes))
        self.stats_label = Gtk.Label(label=f"{orig_str} - {_('compress_calculating')}")
        self.stats_label.add_css_class("heading")
        self.stats_label.set_margin_end(10)
        self.stats_label.set_margin_top(3)
        self.stats_label.set_margin_bottom(3)
        stats_pill.append(self.stats_label)
        row2.append(stats_pill)
        bottom_box.append(row2)

        class _StatsRowCompat:
            def __init__(self, label, spinner, icon):
                self._label = label
                self._spinner = spinner
                self._icon = icon
            def set_title(self, text):
                pass
            def set_subtitle(self, text):
                self._label.set_text(text)
        self.stats_row = _StatsRowCompat(self.stats_label, self.stats_spinner, self.stats_icon)

        # Match initial preset
        if self.active_preset == PRESET_MAX_BW:
            self.btn_max_bw.set_active(True)
            self.gray_switch.set_sensitive(False)
        elif self.active_preset == PRESET_MAXIMUM:
            self.btn_max.set_active(True)
        elif self.active_preset == PRESET_HIGH_QUALITY:
            self.btn_high.set_active(True)
        elif self.active_preset == PRESET_LOSSLESS:
            self.btn_lossless.set_active(True)
        else:
            self.btn_bal.set_active(True)

        self.btn_bal.connect("toggled", self._on_preset_changed)
        self.btn_max.connect("toggled", self._on_preset_changed)
        self.btn_max_bw.connect("toggled", self._on_preset_changed)
        self.btn_high.connect("toggled", self._on_preset_changed)
        self.btn_lossless.connect("toggled", self._on_preset_changed)

    def _setup_key_controller(self):
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up):
            self._change_page(-1)
            return True
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Page_Down):
            self._change_page(1)
            return True
        elif keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self._adjust_zoom(0.25)
            return True
        elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self._adjust_zoom(-0.25)
            return True
        elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0) and (state & Gdk.ModifierType.CONTROL_MASK):
            self._fit_to_window()
            return True
        elif keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False

    def _on_mode_toggled(self, button):
        if self.btn_mode_side.get_active():
            self.view_mode = "side"
            self.stack.set_visible_child_name("side")
        else:
            self.view_mode = "wipe"
            self.stack.set_visible_child_name("wipe")
        self._update_views()

    def _get_active_preset(self) -> str:
        if self.btn_max_bw.get_active():
            return PRESET_MAX_BW
        elif self.btn_max.get_active():
            return PRESET_MAXIMUM
        elif self.btn_high.get_active():
            return PRESET_HIGH_QUALITY
        elif self.btn_lossless.get_active():
            return PRESET_LOSSLESS
        else:
            return PRESET_BALANCED

    def _on_preset_changed(self, button):
        if not button.get_active():
            return
        self.active_preset = self._get_active_preset()
        is_bw = (self.active_preset == PRESET_MAX_BW)
        self.gray_switch.set_sensitive(not is_bw)
        self._trigger_recompression()

    def _on_grayscale_changed(self):
        self.grayscale_enabled = self.gray_switch.get_active()
        self._trigger_recompression()

    def _change_page(self, delta: int):
        target = self.current_page + delta
        if 0 <= target < self.total_pages:
            self.current_page = target
            self.page_label.set_text(_("compress_compare_page_info", self.current_page + 1, self.total_pages))
            self.prev_page_btn.set_sensitive(self.current_page > 0)
            self.next_page_btn.set_sensitive(self.current_page < self.total_pages - 1)
            self._update_views()

    def _adjust_zoom(self, delta: float):
        new_zoom = max(0.5, min(4.0, round(self.zoom_level + delta, 2)))
        if new_zoom != self.zoom_level:
            self.zoom_level = new_zoom
            self.zoom_label.set_text(f"{int(round(self.zoom_level * 100))}%")
            self._update_views()

    def _fit_to_window(self):
        page = self.orig_doc[self.current_page]
        alloc = self.get_allocation()
        alloc_w = alloc.width if alloc.width > 1 else 840
        alloc_h = alloc.height if alloc.height > 1 else 620

        avail_w = max(200, (alloc_w - 48) // (2 if self.view_mode == "side" else 1))
        avail_h = max(200, alloc_h - 180)
        fit_w = avail_w / page.rect.width
        fit_h = avail_h / page.rect.height
        best = min(fit_w, fit_h)
        self.zoom_level = max(0.25, min(3.0, round(best, 2)))
        self.zoom_label.set_text(f"{int(round(self.zoom_level * 100))}%")
        self._update_views()

    def _trigger_recompression(self):
        self._calc_token += 1
        cur_token = self._calc_token

        self.stats_spinner.set_visible(True)
        self.stats_spinner.start()
        self.stats_label.set_text(_("compress_calculating"))

        opts = get_preset_options(self.active_preset)
        if self.active_preset != PRESET_MAX_BW:
            opts.grayscale = self.grayscale_enabled

        thread = threading.Thread(
            target=self._worker_compress,
            args=(cur_token, opts),
            daemon=True,
        )
        thread.start()

    def _worker_compress(self, token: int, opts: CompressionOptions):
        try:
            res = compress_pdf_bytes(self.pdf_bytes, options=opts)
            c_doc = fitz.open(stream=res.pdf_bytes, filetype="pdf")
        except Exception as exc:
            res = CompressionResult(
                pdf_bytes=self.pdf_bytes,
                original_size=len(self.pdf_bytes),
                compressed_size=len(self.pdf_bytes),
                savings_bytes=0,
                savings_percent=0.0,
                message=str(exc),
            )
            c_doc = fitz.open(stream=self.pdf_bytes, filetype="pdf")

        GLib.idle_add(self._on_compression_finished, token, res, c_doc)

    def _on_compression_finished(self, token: int, res: CompressionResult, c_doc: fitz.Document):
        if token != self._calc_token:
            c_doc.close()
            return

        if self.compressed_doc:
            self.compressed_doc.close()

        self.compressed_doc = c_doc
        self.compressed_result = res
        self._pixbuf_cache.clear()
        self.stats_spinner.stop()
        self.stats_spinner.set_visible(False)

        orig_str = format_bytes(res.original_size)
        comp_str = format_bytes(res.compressed_size)
        stats_text = f"{orig_str} → {comp_str} (-{res.savings_percent}%)"
        self.stats_row.set_subtitle(stats_text)

        orig_badge = f"{_('compress_compare_orig_badge')} ({orig_str})"
        comp_badge = f"{_('compress_compare_comp_badge')} ({comp_str})"
        self.lbl_orig.set_text(orig_badge)
        self.lbl_comp.set_text(comp_badge)
        self.lbl_wipe_comp.set_text(comp_badge)

        self._update_views()

    def _render_page_pixbuf(self, doc: fitz.Document, page_idx: int) -> Optional[GdkPixbuf.Pixbuf]:
        if not doc or page_idx >= len(doc):
            return None

        cache_key = (id(doc), page_idx, int(round(self.zoom_level * 100)))
        if cache_key in self._pixbuf_cache:
            return self._pixbuf_cache[cache_key]

        try:
            page = doc[page_idx]
            mat = fitz.Matrix(self.zoom_level, self.zoom_level)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pb = GdkPixbuf.Pixbuf.new_from_data(
                pix.samples,
                GdkPixbuf.Colorspace.RGB,
                False,
                8,
                pix.width,
                pix.height,
                pix.stride,
            )
            self._pixbuf_cache[cache_key] = pb
            return pb
        except Exception:
            return None

    def _update_views(self):
        pb_orig = self._render_page_pixbuf(self.orig_doc, self.current_page)
        pb_comp = self._render_page_pixbuf(self.compressed_doc, self.current_page) if self.compressed_doc else pb_orig

        if pb_orig:
            w, h = pb_orig.get_width(), pb_orig.get_height()
            self.pic_orig.set_size_request(w, h)
            self.pic_orig.set_paintable(Gdk.Texture.new_for_pixbuf(pb_orig))
            self.pic_orig.queue_draw()
            self.drawing_area.set_size_request(w, h)
            self.drawing_area.queue_draw()

        if pb_comp:
            w_c, h_c = pb_comp.get_width(), pb_comp.get_height()
            self.pic_comp.set_size_request(w_c, h_c)
            self.pic_comp.set_paintable(Gdk.Texture.new_for_pixbuf(pb_comp))
            self.pic_comp.queue_draw()

    def _on_draw_wipe(self, area, cr: cairo.Context, width: int, height: int, user_data):
        pb_orig = self._render_page_pixbuf(self.orig_doc, self.current_page)
        pb_comp = self._render_page_pixbuf(self.compressed_doc, self.current_page) if self.compressed_doc else pb_orig

        if not pb_orig:
            return

        w = pb_orig.get_width()
        h = pb_orig.get_height()
        split_x = max(0, min(w, int(round(w * self.split_pos))))

        # Draw left half: Original
        cr.save()
        cr.rectangle(0, 0, split_x, h)
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, pb_orig, 0, 0)
        cr.paint()
        cr.restore()

        # Draw right half: Compressed
        if pb_comp:
            cr.save()
            cr.rectangle(split_x, 0, w - split_x, h)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, pb_comp, 0, 0)
            cr.paint()
            cr.restore()

        # Vertical divider line
        cr.save()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
        cr.set_line_width(2.0)
        cr.move_to(split_x, 0)
        cr.line_to(split_x, h)
        cr.stroke()

        # Handle Circle
        center_y = h / 2.0
        cr.arc(split_x, center_y, 16.0, 0, 2 * math.pi)
        cr.set_source_rgba(0.15, 0.15, 0.15, 0.85)
        cr.fill_preserve()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
        cr.set_line_width(2.0)
        cr.stroke()

        # Inner arrows < | >
        cr.set_line_width(1.5)
        cr.move_to(split_x - 6, center_y)
        cr.line_to(split_x - 2, center_y - 4)
        cr.move_to(split_x - 6, center_y)
        cr.line_to(split_x - 2, center_y + 4)

        cr.move_to(split_x + 6, center_y)
        cr.line_to(split_x + 2, center_y - 4)
        cr.move_to(split_x + 6, center_y)
        cr.line_to(split_x + 2, center_y + 4)
        cr.stroke()
        cr.restore()

    def _on_drag_begin(self, gesture, start_x: float, start_y: float):
        self._update_split_from_x(start_x)

    def _on_drag_update(self, gesture, offset_x: float, offset_y: float):
        start_x, _ = gesture.get_start_point()
        self._update_split_from_x(start_x + offset_x)

    def _update_split_from_x(self, cur_x: float):
        pb = self._render_page_pixbuf(self.orig_doc, self.current_page)
        if not pb:
            return
        w = pb.get_width()
        if w > 0:
            self.split_pos = max(0.0, min(1.0, cur_x / float(w)))
            self.drawing_area.queue_draw()

    def _on_save_clicked(self, button):
        if not self.compressed_result or not self.compressed_result.pdf_bytes:
            return

        base_name = os.path.splitext(self.initial_filename)[0]
        suggested_name = f"{base_name}_compressed.pdf"

        filter_pdf = Gtk.FileFilter()
        filter_pdf.set_name("PDF Documents (*.pdf)")
        filter_pdf.add_mime_type("application/pdf")
        filter_pdf.add_pattern("*.pdf")

        def _do_save(gfile, _unused_filter=None):
            if not gfile:
                return
            dest_path = gfile.get_path() if hasattr(gfile, "get_path") else str(gfile)
            if not dest_path:
                return
            if not dest_path.lower().endswith(".pdf"):
                dest_path += ".pdf"
            try:
                with open(dest_path, "wb") as f:
                    f.write(self.compressed_result.pdf_bytes)

                if hasattr(self.parent_window, "toast_overlay") and self.parent_window.toast_overlay:
                    orig_str = format_bytes(self.compressed_result.original_size)
                    comp_str = format_bytes(self.compressed_result.compressed_size)
                    toast_msg = _(
                        "compress_success",
                        orig_str,
                        comp_str,
                        f"{self.compressed_result.savings_percent:.1f}",
                    )
                    self.parent_window.toast_overlay.add_toast(Adw.Toast(title=toast_msg))

                if self.on_saved_callback:
                    self.on_saved_callback(dest_path)
                self.destroy()
            except Exception as err:
                if hasattr(self.parent_window, "toast_overlay") and self.parent_window.toast_overlay:
                    self.parent_window.toast_overlay.add_toast(
                        Adw.Toast(title=_("compress_error", str(err)))
                    )

        show_save_file_dialog(
            self,
            _("compress_title"),
            initial_name=suggested_name,
            filters=[filter_pdf],
            default_filter=filter_pdf,
            callback=_do_save,
        )

    def do_destroy(self):
        if self.compressed_doc:
            try:
                self.compressed_doc.close()
            except Exception:
                pass
        if self.orig_doc:
            try:
                self.orig_doc.close()
            except Exception:
                pass
        self._pixbuf_cache.clear()
        Adw.Window.do_destroy(self)
