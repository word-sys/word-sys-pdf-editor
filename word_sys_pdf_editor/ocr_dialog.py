from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

import fitz
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .i18n import _
from .ocr_engine import (
    SUPPORTED_LANGUAGES,
    analyze_document_scans,
    delete_user_language_model,
    download_language_model,
    get_available_languages,
    get_best_tessdata_dir_for_lang,
    get_tessdata_user_dir,
    perform_ocr_on_page,
)


class OCRDialog(Adw.Window):
    """Modern Libadwaita dialog for executing OCR and managing language models."""

    def __init__(
        self,
        parent_window,
        doc: fitz.Document,
        current_page_num: int = 0,
        on_completed_callback: Optional[Callable[[list[int], dict], None]] = None,
    ):
        super().__init__()
        self.parent_window = parent_window
        self.doc = doc
        self.current_page_num = current_page_num
        self.on_completed_callback = on_completed_callback

        self._active_downloads: set[str] = set()
        self._cancel_ocr_flag = False
        self._is_ocr_running = False

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("ocr_dialog_title"))
        self.set_default_size(560, 640)
        self.set_resizable(False)

        # Analyze document for scanned pages
        self.scan_stats = analyze_document_scans(self.doc)

        self._build_ui()
        self._refresh_languages()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header Bar
        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", self._on_cancel_clicked)
        header.pack_start(self.cancel_btn)

        self.start_btn = Gtk.Button(label=_("ocr_btn_start"))
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.connect("clicked", self._on_start_ocr_clicked)
        header.pack_end(self.start_btn)
        main_box.append(header)

        # View Switcher Bar
        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        view_switcher_title = Adw.ViewSwitcherTitle()
        view_switcher_title.set_stack(self.view_stack)
        header.set_title_widget(view_switcher_title)
        main_box.append(self.view_stack)


        run_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        run_scrolled = Gtk.ScrolledWindow()
        run_scrolled.set_vexpand(True)
        run_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        run_clamp = Adw.Clamp(maximum_size=500)
        run_clamp.set_margin_top(16)
        run_clamp.set_margin_bottom(16)
        run_clamp.set_margin_start(16)
        run_clamp.set_margin_end(16)
        run_clamp.set_child(run_box)
        run_scrolled.set_child(run_clamp)

        # Scan Analysis Card
        analysis_group = Adw.PreferencesGroup()
        analysis_group.set_title(_("ocr_scan_analysis_title"))
        run_box.append(analysis_group)

        self.analysis_row = Adw.ActionRow()
        scanned_count = self.scan_stats["scanned_count"]
        if scanned_count > 0:
            scanned_pages_str = ", ".join(
                str(p + 1) for p in self.scan_stats["scanned_pages"]
            )
            self.analysis_row.set_title(
                _("ocr_scans_detected", scanned_count, scanned_pages_str)
            )
            self.analysis_row.add_css_class("accent")
            icon_name = "scanner-symbolic"
        else:
            self.analysis_row.set_title(_("ocr_no_scans_detected"))
            icon_name = "document-properties-symbolic"

        self.analysis_icon = Gtk.Image.new_from_icon_name(icon_name)
        self.analysis_row.add_prefix(self.analysis_icon)
        analysis_group.add(self.analysis_row)

        run_box.append(Gtk.Box(spacing=12))

        # OCR Settings Group
        settings_group = Adw.PreferencesGroup()
        settings_group.set_title(_("ocr_dialog_title"))
        run_box.append(settings_group)

        # Language Selector ComboRow
        self.lang_model = Gtk.StringList()
        self.lang_row = Adw.ComboRow(
            title=_("ocr_lang_label"),
            model=self.lang_model,
        )
        self.installed_lang_codes: list[str] = []
        settings_group.add(self.lang_row)

        # Scope / Page Range ComboRow
        self.scope_model = Gtk.StringList()
        self.scope_options: list[str] = []

        # Current page
        curr_label = _("ocr_pages_current", self.current_page_num + 1)
        self.scope_model.append(curr_label)
        self.scope_options.append("current")

        # Scanned pages only (if any exist)
        if scanned_count > 0:
            scanned_label = _("ocr_pages_scanned_only", scanned_count)
            self.scope_model.append(scanned_label)
            self.scope_options.append("scanned_only")

        # All pages
        all_label = _("ocr_pages_all", len(self.doc))
        self.scope_model.append(all_label)
        self.scope_options.append("all")

        self.scope_row = Adw.ComboRow(
            title=_("ocr_pages_label"),
            model=self.scope_model,
        )
        self.scope_row.set_selected(0)  # Default to current page
        settings_group.add(self.scope_row)

        # Quality / DPI ComboRow
        self.dpi_model = Gtk.StringList()
        self.dpi_model.append(_("ocr_dpi_fast"))
        self.dpi_model.append(_("ocr_dpi_medium"))
        self.dpi_model.append(_("ocr_dpi_high"))
        self.dpi_values = [150, 200, 300]

        self.dpi_row = Adw.ComboRow(
            title=_("ocr_dpi_label"),
            model=self.dpi_model,
        )
        self.dpi_row.set_selected(0)  # 150 DPI recommended default
        settings_group.add(self.dpi_row)

        # Progress Section
        self.progress_group = Adw.PreferencesGroup()
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_fraction(0.0)

        self.progress_status_label = Gtk.Label(label="")
        self.progress_status_label.set_wrap(True)
        self.progress_status_label.set_justify(Gtk.Justification.CENTER)

        prog_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        prog_box.set_margin_top(16)
        prog_box.append(self.progress_bar)
        prog_box.append(self.progress_status_label)
        self.progress_group.add(prog_box)
        self.progress_group.set_visible(False)
        run_box.append(self.progress_group)

        p1 = self.view_stack.add_titled(
            run_scrolled,
            "recognize",
            _("ocr_tab_process"),
        )
        p1.set_icon_name("scanner-symbolic")

        models_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        models_scrolled = Gtk.ScrolledWindow()
        models_scrolled.set_vexpand(True)
        models_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        models_clamp = Adw.Clamp(maximum_size=500)
        models_clamp.set_margin_top(16)
        models_clamp.set_margin_bottom(16)
        models_clamp.set_margin_start(16)
        models_clamp.set_margin_end(16)
        models_clamp.set_child(models_box)
        models_scrolled.set_child(models_clamp)

        # Storage & Transparency Info Group
        storage_group = Adw.PreferencesGroup()
        storage_group.set_title(_("ocr_storage_info_title"))

        storage_row = Adw.ActionRow()
        user_path_str = str(get_tessdata_user_dir())
        storage_row.set_title(_("ocr_storage_path_label", user_path_str))

        open_folder_btn = Gtk.Button.new_from_icon_name("folder-open-symbolic")
        open_folder_btn.set_tooltip_text(_("ocr_open_folder"))
        open_folder_btn.set_valign(Gtk.Align.CENTER)
        open_folder_btn.connect("clicked", self._on_open_storage_folder)
        storage_row.add_suffix(open_folder_btn)
        storage_group.add(storage_row)
        models_box.append(storage_group)

        # Models List Group
        self.models_list_group = Adw.PreferencesGroup()
        self.models_list_group.set_title(_("ocr_tab_models"))
        models_box.append(self.models_list_group)

        p2 = self.view_stack.add_titled(
            models_scrolled,
            "models",
            _("ocr_tab_models"),
        )
        p2.set_icon_name("preferences-desktop-locale-symbolic")

    def _refresh_languages(self):
        """Scan system and user profile for installed language models and update UI."""
        all_langs = get_available_languages()

        # Update Recognize Tab dropdown
        self.installed_lang_codes.clear()
        # Clear existing items in StringList
        while self.lang_model.get_n_items() > 0:
            self.lang_model.remove(0)

        for code, info in all_langs.items():
            if info["is_installed"]:
                self.installed_lang_codes.append(code)
                display_name = f"{info['name']} ({info['native']})"
                self.lang_model.append(display_name)

        if not self.installed_lang_codes:
            self.start_btn.set_sensitive(False)
            self.lang_row.set_subtitle(_("ocr_err_no_model"))
        else:
            self.start_btn.set_sensitive(True)
            self.lang_row.set_subtitle("")
            self.lang_row.set_selected(0)

        # Clear old rows from models_list_group
        if not hasattr(self, "_model_rows"):
            self._model_rows = []
        for r in self._model_rows:
            self.models_list_group.remove(r)
        self._model_rows.clear()

        for code, meta in SUPPORTED_LANGUAGES.items():
            info = all_langs.get(code, {})
            is_installed = info.get("is_installed", False)
            source = info.get("source")
            size_mb = meta["size_mb"]

            row = Adw.ActionRow()
            row.set_title(f"{meta['name']} ({meta['native']})")

            if is_installed:
                if source == "system":
                    status_text = _("ocr_status_installed_system")
                elif source == "bundle":
                    status_text = _("ocr_status_installed_bundle")
                else:
                    status_text = _("ocr_status_installed_user")

                row.set_subtitle(status_text)
                check_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                check_icon.add_css_class("success")
                row.add_prefix(check_icon)

                # If installed in user storage, allow deleting to free disk space
                if source == "user":
                    del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
                    del_btn.set_tooltip_text(_("ocr_btn_delete"))
                    del_btn.set_valign(Gtk.Align.CENTER)
                    del_btn.add_css_class("flat")
                    del_btn.connect("clicked", self._make_delete_handler(code))
                    row.add_suffix(del_btn)
            else:
                row.set_subtitle(_("ocr_status_available", size_mb))
                avail_icon = Gtk.Image.new_from_icon_name("cloud-download-symbolic")
                row.add_prefix(avail_icon)

                down_btn = Gtk.Button(label=_("ocr_btn_download"))
                down_btn.set_valign(Gtk.Align.CENTER)
                down_btn.add_css_class("suggested-action")
                down_btn.connect("clicked", self._make_download_handler(code, row, down_btn))
                row.add_suffix(down_btn)

            self.models_list_group.add(row)
            self._model_rows.append(row)

    def _make_download_handler(self, code: str, row: Adw.ActionRow, button: Gtk.Button):
        def _on_download(_btn):
            if code in self._active_downloads:
                return
            self._active_downloads.add(code)
            button.set_sensitive(False)

            # Create in-row mini progress bar
            prog_bar = Gtk.ProgressBar()
            prog_bar.set_valign(Gtk.Align.CENTER)
            prog_bar.set_hexpand(False)
            prog_bar.set_fraction(0.0)

            row.remove(button)
            row.add_suffix(prog_bar)

            def _progress_cb(curr: int, total: int):
                if total > 0:
                    fraction = min(curr / total, 1.0)
                    percent = int(fraction * 100)
                    GLib.idle_add(prog_bar.set_fraction, fraction)
                    GLib.idle_add(row.set_subtitle, _("ocr_status_downloading", percent))

            def _worker():
                try:
                    download_language_model(code, progress_callback=_progress_cb)
                    # Instant activation - no restart required!
                    GLib.idle_add(self._on_download_complete, code, None)
                except Exception as e:
                    GLib.idle_add(self._on_download_complete, code, str(e))

            threading.Thread(target=_worker, daemon=True).start()

        return _on_download

    def _on_download_complete(self, code: str, error: Optional[str]):
        if code in self._active_downloads:
            self._active_downloads.remove(code)

        self._refresh_languages()

        if error:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading=_("ocr_dialog_title"),
                body=f"Download failed: {error}",
            )
            dialog.add_response("ok", _("btn_confirm"))
            dialog.present()

    def _make_delete_handler(self, code: str):
        def _on_delete(_btn):
            delete_user_language_model(code)
            self._refresh_languages()

        return _on_delete

    def _on_open_storage_folder(self, _btn):
        target = get_tessdata_user_dir()
        target.mkdir(parents=True, exist_ok=True)
        try:
            Gio.AppInfo.launch_default_for_uri(f"file://{target.resolve()}", None)
        except Exception:
            try:
                import subprocess
                subprocess.Popen(["xdg-open", str(target.resolve())])
            except Exception:
                pass

    def do_close_request(self) -> bool:
        """Handle window close request cleanly, stopping any running OCR process."""
        self._cancel_ocr_flag = True
        self._is_ocr_running = False
        return False  # Return False to allow window closing

    def _on_cancel_clicked(self, _btn):
        if self._is_ocr_running:
            self._cancel_ocr_flag = True
            self.progress_status_label.set_text("Cancelling...")
            self.cancel_btn.set_sensitive(False)
        else:
            self.close()

    def _on_start_ocr_clicked(self, _btn):
        if not self.installed_lang_codes:
            return

        selected_idx = self.lang_row.get_selected()
        if selected_idx < 0 or selected_idx >= len(self.installed_lang_codes):
            return
        lang_code = self.installed_lang_codes[selected_idx]

        scope_idx = self.scope_row.get_selected()
        scope_type = self.scope_options[scope_idx]

        dpi_idx = self.dpi_row.get_selected()
        dpi = self.dpi_values[dpi_idx]

        # Determine target pages
        if scope_type == "current":
            target_pages = [self.current_page_num]
        elif scope_type == "scanned_only":
            target_pages = list(self.scan_stats["scanned_pages"])
            if not target_pages:
                target_pages = [self.current_page_num]
        else:
            target_pages = list(range(len(self.doc)))

        # Update UI state for processing
        self._is_ocr_running = True
        self._cancel_ocr_flag = False
        if hasattr(self.parent_window, "_ocr_cancel_requested"):
            self.parent_window._ocr_cancel_requested = False
        self.start_btn.set_sensitive(False)
        self.cancel_btn.set_sensitive(True)
        self.lang_row.set_sensitive(False)
        self.scope_row.set_sensitive(False)
        self.dpi_row.set_sensitive(False)
        self.progress_group.set_visible(True)

        total_pages = len(target_pages)
        if hasattr(self.parent_window, "show_ocr_banner"):
            self.parent_window.show_ocr_banner(total_pages)

        def _worker():
            results = {}
            total = len(target_pages)
            try:
                tessdata_dir = get_best_tessdata_dir_for_lang(lang_code)

                for idx, p_num in enumerate(target_pages):
                    if self._cancel_ocr_flag or getattr(self.parent_window, "_ocr_cancel_requested", False):
                        break

                    curr_msg = _("ocr_msg_processing", idx + 1, total)
                    fraction = idx / max(total, 1)
                    GLib.idle_add(self.progress_bar.set_fraction, fraction)
                    GLib.idle_add(self.progress_status_label.set_text, curr_msg)
                    if hasattr(self.parent_window, "update_ocr_banner"):
                        GLib.idle_add(self.parent_window.update_ocr_banner, idx + 1, total, fraction)

                    try:
                        ocr_doc = perform_ocr_on_page(
                            self.doc,
                            page_num=p_num,
                            language=lang_code,
                            dpi=dpi,
                            tessdata_dir=tessdata_dir,
                        )
                        results[p_num] = ocr_doc
                    except Exception as err:
                        print(f"Error executing OCR on page {p_num}: {err}")
            except Exception as e:
                print(f"OCR execution setup error: {e}")
            finally:
                GLib.idle_add(self._on_ocr_finished, target_pages, results)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_ocr_finished(self, target_pages: list[int], results: dict):
        self._is_ocr_running = False
        self.start_btn.set_sensitive(True)
        self.cancel_btn.set_sensitive(True)
        self.lang_row.set_sensitive(True)
        self.scope_row.set_sensitive(True)
        self.dpi_row.set_sensitive(True)

        is_cancelled = self._cancel_ocr_flag or getattr(self.parent_window, "_ocr_cancel_requested", False)

        if is_cancelled:
            if hasattr(self.parent_window, "hide_ocr_banner"):
                self.parent_window.hide_ocr_banner(cancelled=True)
            self.close()
            return

        self.progress_bar.set_fraction(1.0)
        self.progress_status_label.set_text(
            _("ocr_msg_completed", len(results))
        )
        if hasattr(self.parent_window, "hide_ocr_banner"):
            self.parent_window.hide_ocr_banner(cancelled=False, completed_count=len(results))

        if self.on_completed_callback:
            try:
                self.on_completed_callback(target_pages, results)
            except Exception as e:
                print(f"Error in OCR completion callback: {e}")

        self.close()
