from __future__ import annotations

import os
import threading
from typing import Optional, Callable

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio

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


class CompressionDialog(Adw.Window):
    def __init__(
        self,
        parent_window,
        pdf_bytes: bytes,
        initial_filename: Optional[str] = None,
        on_saved_callback: Optional[Callable[[str], None]] = None,
    ):
        super().__init__()
        self.parent_window = parent_window
        self.pdf_bytes = pdf_bytes
        self.initial_filename = initial_filename or "document.pdf"
        self.on_saved_callback = on_saved_callback

        self.compressed_result: Optional[CompressionResult] = None
        self._calc_token = 0
        self._pending_save = False

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("compress_title"))
        self.set_default_size(580, 640)
        self.set_resizable(False)

        self._build_ui()
        self._trigger_recalculation()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(self.cancel_btn)

        self.save_btn = Gtk.Button(label=_("compress_btn_save"))
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(self.save_btn)
        self.compare_btn = Gtk.Button.new_from_icon_name("view-dual-symbolic")
        self.compare_btn.set_tooltip_text(_("compress_btn_compare"))
        self.compare_btn.connect("clicked", self._on_compare_clicked)
        header.pack_end(self.compare_btn)
        main_box.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=540)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(content_box)

        # File Overview Card
        doc_group = Adw.PreferencesGroup()
        self.doc_row = Adw.ActionRow()
        self.doc_row.set_title(os.path.basename(self.initial_filename))
        orig_str = format_bytes(len(self.pdf_bytes))
        self.doc_row.set_subtitle(_("compress_orig_size_label", orig_str))
        doc_icon = Gtk.Image.new_from_icon_name("document-save-symbolic")
        self.doc_row.add_prefix(doc_icon)
        doc_group.add(self.doc_row)
        content_box.append(doc_group)

        # Output / Live Calculation Status Card
        status_group = Adw.PreferencesGroup()
        self.status_row = Adw.ActionRow()
        self.status_row.set_title(_("compress_output_size_title"))
        self.status_row.set_subtitle(_("compress_calculating"))
        self.status_icon = Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        self.status_row.add_prefix(self.status_icon)

        self.spinner = Gtk.Spinner()
        self.spinner.set_valign(Gtk.Align.CENTER)
        self.spinner.start()
        self.status_row.add_suffix(self.spinner)

        self.size_badge = Gtk.Label()
        self.size_badge.set_valign(Gtk.Align.CENTER)
        self.size_badge.add_css_class("heading")
        self.status_row.add_suffix(self.size_badge)

        self.compare_row = Adw.ActionRow(
            title=_("compress_btn_compare"),
            subtitle=_("compress_compare_title"),
        )
        self.compare_row.add_prefix(Gtk.Image.new_from_icon_name("view-dual-symbolic"))
        self.compare_row.set_activatable(True)
        compare_arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        self.compare_row.add_suffix(compare_arrow)
        self.compare_row.connect("activated", lambda r: self._on_compare_clicked(None))

        status_group.add(self.status_row)
        status_group.add(self.compare_row)
        content_box.append(status_group)

        # Presets Group with Radio Rows
        presets_group = Adw.PreferencesGroup()
        presets_group.set_title(_("compress_presets_title"))
        content_box.append(presets_group)

        self.radio_bal = Gtk.CheckButton()
        self.row_bal = Adw.ActionRow()
        self.row_bal.set_title(GLib.markup_escape_text(_("compress_preset_balanced_title")))
        self.row_bal.set_subtitle(GLib.markup_escape_text(_("compress_preset_balanced_desc")))
        self.row_bal.add_prefix(self.radio_bal)
        self.row_bal.set_activatable_widget(self.radio_bal)
        presets_group.add(self.row_bal)

        self.radio_max = Gtk.CheckButton()
        self.radio_max.set_group(self.radio_bal)
        self.row_max = Adw.ActionRow()
        self.row_max.set_title(GLib.markup_escape_text(_("compress_preset_maximum_title")))
        self.row_max.set_subtitle(GLib.markup_escape_text(_("compress_preset_maximum_desc")))
        self.row_max.add_prefix(self.radio_max)
        self.row_max.set_activatable_widget(self.radio_max)
        presets_group.add(self.row_max)

        self.radio_max_bw = Gtk.CheckButton()
        self.radio_max_bw.set_group(self.radio_bal)
        self.row_max_bw = Adw.ActionRow()
        self.row_max_bw.set_title(GLib.markup_escape_text(_("compress_preset_max_bw_title")))
        self.row_max_bw.set_subtitle(GLib.markup_escape_text(_("compress_preset_max_bw_desc")))
        self.row_max_bw.add_prefix(self.radio_max_bw)
        self.row_max_bw.set_activatable_widget(self.radio_max_bw)
        presets_group.add(self.row_max_bw)

        self.radio_high = Gtk.CheckButton()
        self.radio_high.set_group(self.radio_bal)
        self.row_high = Adw.ActionRow()
        self.row_high.set_title(GLib.markup_escape_text(_("compress_preset_high_title")))
        self.row_high.set_subtitle(GLib.markup_escape_text(_("compress_preset_high_desc")))
        self.row_high.add_prefix(self.radio_high)
        self.row_high.set_activatable_widget(self.radio_high)
        presets_group.add(self.row_high)

        self.radio_lossless = Gtk.CheckButton()
        self.radio_lossless.set_group(self.radio_bal)
        self.row_lossless = Adw.ActionRow()
        self.row_lossless.set_title(GLib.markup_escape_text(_("compress_preset_lossless_title")))
        self.row_lossless.set_subtitle(GLib.markup_escape_text(_("compress_preset_lossless_desc")))
        self.row_lossless.add_prefix(self.radio_lossless)
        self.row_lossless.set_activatable_widget(self.radio_lossless)
        presets_group.add(self.row_lossless)

        # Grayscale Conversion Group
        options_group = Adw.PreferencesGroup()
        content_box.append(options_group)

        self.grayscale_switch = Gtk.Switch()
        self.grayscale_switch.set_valign(Gtk.Align.CENTER)
        self.grayscale_switch.set_active(False)
        self.grayscale_switch.connect("notify::active", lambda s, p: self._trigger_recalculation())
        self.grayscale_row = Adw.ActionRow()
        self.grayscale_row.set_title(GLib.markup_escape_text(_("compress_grayscale_title")))
        self.grayscale_row.set_subtitle(GLib.markup_escape_text(_("compress_grayscale_desc")))
        self.grayscale_row.add_suffix(self.grayscale_switch)
        self.grayscale_row.set_activatable_widget(self.grayscale_switch)
        options_group.add(self.grayscale_row)

        # Connect Radio Toggles
        self.radio_bal.connect("toggled", self._on_preset_toggled)
        self.radio_max.connect("toggled", self._on_preset_toggled)
        self.radio_max_bw.connect("toggled", self._on_preset_toggled)
        self.radio_high.connect("toggled", self._on_preset_toggled)
        self.radio_lossless.connect("toggled", self._on_preset_toggled)

        # Default selection: Balanced
        self.radio_bal.set_active(True)

    def _get_active_preset(self) -> str:
        if self.radio_max_bw.get_active():
            return PRESET_MAX_BW
        elif self.radio_max.get_active():
            return PRESET_MAXIMUM
        elif self.radio_high.get_active():
            return PRESET_HIGH_QUALITY
        elif self.radio_lossless.get_active():
            return PRESET_LOSSLESS
        else:
            return PRESET_BALANCED

    def _on_preset_toggled(self, button):
        if not button.get_active():
            return
        is_bw = self.radio_max_bw.get_active()
        self.grayscale_switch.set_sensitive(not is_bw)
        self._trigger_recalculation()

    def _trigger_recalculation(self):
        self._calc_token += 1
        current_token = self._calc_token

        self.spinner.start()
        self.spinner.set_visible(True)
        self.status_icon.set_from_icon_name("emblem-synchronizing-symbolic")
        self.status_row.set_subtitle(_("compress_calculating"))
        self.size_badge.set_text("")

        preset = self._get_active_preset()
        grayscale = self.grayscale_switch.get_active() if hasattr(self, 'grayscale_switch') else False

        thread = threading.Thread(
            target=self._worker_calculate,
            args=(current_token, preset, grayscale),
            daemon=True,
        )
        thread.start()

    def _worker_calculate(self, token: int, preset: str, grayscale: bool):
        try:
            opts = get_preset_options(preset)
            opts.grayscale = grayscale
            res = compress_pdf_bytes(self.pdf_bytes, options=opts)
        except Exception as exc:
            res = CompressionResult(
                pdf_bytes=self.pdf_bytes,
                original_size=len(self.pdf_bytes),
                compressed_size=len(self.pdf_bytes),
                savings_bytes=0,
                savings_percent=0.0,
                achieved_target=False,
                message=str(exc),
            )

        GLib.idle_add(self._on_calculation_finished, token, res)

    def _on_calculation_finished(self, token: int, res: CompressionResult):
        if token != self._calc_token:
            return

        self.spinner.stop()
        self.spinner.set_visible(False)
        self.compressed_result = res

        orig_str = format_bytes(res.original_size)
        comp_str = format_bytes(res.compressed_size)

        self.size_badge.set_text(comp_str)

        if res.savings_bytes > 0:
            self.status_icon.set_from_icon_name("emblem-ok-symbolic")
            sub_text = f"{orig_str} → {comp_str} ({res.savings_percent:.1f}% reduction)"
            self.status_row.set_subtitle(sub_text)
        else:
            self.status_icon.set_from_icon_name("dialog-information-symbolic")
            self.status_row.set_subtitle(_("compress_already_optimal"))

        if self._pending_save:
            self._pending_save = False
            self._open_save_dialog()

    def _on_save_clicked(self, button):
        if self.spinner.get_visible() or not self.compressed_result:
            self._pending_save = True
            return
        self._open_save_dialog()

    def _on_compare_clicked(self, _button):
        from .compress_compare_dialog import CompressionCompareDialog
        preset = self._get_active_preset()
        grayscale = self.grayscale_switch.get_active() if hasattr(self, 'grayscale_switch') else False

        dlg = CompressionCompareDialog(
            parent_window=self.parent_window,
            pdf_bytes=self.pdf_bytes,
            initial_filename=self.initial_filename,
            initial_preset=preset,
            initial_grayscale=grayscale,
            on_saved_callback=self._on_saved_from_compare,
        )
        dlg.present()

    def _on_saved_from_compare(self, path: str):
        if self.on_saved_callback:
            self.on_saved_callback(path)
        self.destroy()

    def _open_save_dialog(self):
        if not self.compressed_result or not self.compressed_result.pdf_bytes:
            return

        stem, ext = os.path.splitext(os.path.basename(self.initial_filename))
        out_name = f"{stem}_compressed{ext or '.pdf'}"

        filter_pdf = Gtk.FileFilter(name=_("filter_pdf"))
        filter_pdf.add_pattern("*.pdf")
        filter_pdf.add_mime_type("application/pdf")

        def _on_saved(file):
            if not file:
                return
            dest_path = file.get_path()
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
            initial_name=out_name,
            filters=[filter_pdf],
            default_filter=filter_pdf,
            callback=_on_saved,
        )
