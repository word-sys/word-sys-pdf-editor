from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from .i18n import _
from .search_engine import DocumentSearchEngine, SearchMatch, PII_PATTERNS


def _safe_markup(text: str) -> str:
    """Escape string for safe Pango markup rendering in Adwaita rows."""
    return GLib.markup_escape_text(text) if text else ""


class SearchRedactDialog(Adw.Window):
    """Modern Libadwaita modal dialog for finding text or PII patterns and staging batch redactions."""

    def __init__(
        self,
        parent_window,
        doc,
        current_page_num: int = 0,
        initial_query: str = "",
        default_overlay: str = "[REDACTED]",
        default_fill: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        on_confirm_callback: Optional[Callable[[List[SearchMatch], str, Tuple[float, float, float], Tuple[float, float, float]], None]] = None,
    ):
        super().__init__()
        self.parent_window = parent_window
        self.doc = doc
        self.current_page_num = current_page_num
        self.on_confirm_callback = on_confirm_callback
        self.search_engine = DocumentSearchEngine(doc)
        self.current_matches: List[SearchMatch] = []

        self.selected_fill = default_fill
        self.selected_text_color = (1.0, 1.0, 1.0) if default_fill == (0.0, 0.0, 0.0) else (0.0, 0.0, 0.0)

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("search_redact_dialog_title"))
        self.set_default_size(520, 620)
        self.set_resizable(True)
        self.connect("close-request", self._on_close_request)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header Bar
        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", lambda b: (self._clear_canvas_preview(), self.destroy()))
        header.pack_start(self.cancel_btn)

        self.confirm_btn = Gtk.Button(label=_("search_redact_btn_stage"))
        self.confirm_btn.add_css_class("suggested-action")
        self.confirm_btn.set_sensitive(False)
        self.confirm_btn.connect("clicked", self._on_confirm_clicked)
        header.pack_end(self.confirm_btn)
        main_box.append(header)

        # Scrolled container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=480)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(content_box)

        # Info Header
        info_group = Adw.PreferencesGroup()
        info_row = Adw.ActionRow()
        info_row.set_title(_safe_markup(_("search_redact_dialog_title")))
        info_row.set_subtitle(_safe_markup(_("search_redact_dialog_desc")))
        info_row.set_subtitle_lines(0)
        info_icon = Gtk.Image.new_from_icon_name("edit-clear-symbolic")
        info_row.add_prefix(info_icon)
        info_group.add(info_row)
        content_box.append(info_group)

        # Search Criteria Group
        criteria_group = Adw.PreferencesGroup()
        criteria_group.set_title(_safe_markup(_("search_redact_options_title")))
        content_box.append(criteria_group)

        # Mode Selector: Text vs Pattern (PII)
        mode_strings = [
            _("search_redact_mode_text"),
            _("search_redact_mode_pattern"),
        ]
        self.mode_dropdown = Gtk.DropDown.new_from_strings(mode_strings)
        self.mode_dropdown.set_valign(Gtk.Align.CENTER)
        self.mode_dropdown.connect("notify::selected", self._on_mode_changed)
        mode_row = Adw.ActionRow(title=_safe_markup(_("search_redact_mode_label")))
        mode_row.add_suffix(self.mode_dropdown)
        mode_row.set_activatable_widget(self.mode_dropdown)
        criteria_group.add(mode_row)

        # Text Query Entry Row
        self.query_entry = Gtk.Entry()
        self.query_entry.set_valign(Gtk.Align.CENTER)
        self.query_entry.set_hexpand(True)
        if initial_query:
            self.query_entry.set_text(initial_query)
        self.query_entry.connect("changed", lambda e: self._update_matches())
        self.query_entry.connect("activate", lambda e: self._on_next_match_clicked(None))
        self.query_row = Adw.ActionRow(title=_safe_markup(_("search_placeholder")))
        self.query_row.add_suffix(self.query_entry)
        self.query_row.set_activatable_widget(self.query_entry)
        criteria_group.add(self.query_row)

        # Pattern Preset Dropdown Row
        self.pii_keys = list(PII_PATTERNS.keys())
        pattern_labels = [_(PII_PATTERNS[k]["label_key"]) for k in self.pii_keys]
        self.pattern_dropdown = Gtk.DropDown.new_from_strings(pattern_labels)
        self.pattern_dropdown.set_valign(Gtk.Align.CENTER)
        self.pattern_dropdown.connect("notify::selected", lambda d, p: self._update_matches())
        self.pattern_row = Adw.ActionRow(title=_safe_markup(_("search_redact_pattern_label")))
        self.pattern_row.add_suffix(self.pattern_dropdown)
        self.pattern_row.set_activatable_widget(self.pattern_dropdown)
        self.pattern_row.set_visible(False)
        criteria_group.add(self.pattern_row)

        # Case Sensitivity Switch
        self.case_switch = Gtk.Switch()
        self.case_switch.set_valign(Gtk.Align.CENTER)
        self.case_switch.connect("notify::active", lambda s, p: self._update_matches())
        self.case_row = Adw.ActionRow(title=_safe_markup(_("search_case_sensitive")))
        self.case_row.add_suffix(self.case_switch)
        self.case_row.set_activatable_widget(self.case_switch)
        criteria_group.add(self.case_row)

        # Whole Word Switch
        self.whole_word_switch = Gtk.Switch()
        self.whole_word_switch.set_valign(Gtk.Align.CENTER)
        self.whole_word_switch.connect("notify::active", lambda s, p: self._update_matches())
        self.whole_word_row = Adw.ActionRow(title=_safe_markup(_("search_whole_word")))
        self.whole_word_row.add_suffix(self.whole_word_switch)
        self.whole_word_row.set_activatable_widget(self.whole_word_switch)
        criteria_group.add(self.whole_word_row)

        # Scope Group
        scope_group = Adw.PreferencesGroup()
        scope_group.set_title(_safe_markup(_("search_redact_scope_title")))
        content_box.append(scope_group)

        scope_strings = [
            _("search_redact_scope_doc"),
            _("search_redact_scope_page", current_page_num + 1),
        ]
        self.scope_dropdown = Gtk.DropDown.new_from_strings(scope_strings)
        self.scope_dropdown.set_valign(Gtk.Align.CENTER)
        self.scope_dropdown.connect("notify::selected", lambda d, p: self._update_matches())
        scope_row = Adw.ActionRow(title=_safe_markup(_("search_redact_scope_label")))
        scope_row.add_suffix(self.scope_dropdown)
        scope_row.set_activatable_widget(self.scope_dropdown)
        scope_group.add(scope_row)

        # Redaction Appearance Group
        appearance_group = Adw.PreferencesGroup()
        appearance_group.set_title(_safe_markup(_("redaction_mark_title")))
        content_box.append(appearance_group)

        # Overlay text entry
        self.overlay_entry = Gtk.Entry()
        self.overlay_entry.set_valign(Gtk.Align.CENTER)
        self.overlay_entry.set_text(default_overlay)
        overlay_row = Adw.ActionRow(title=_safe_markup(_("redaction_overlay_text")))
        overlay_row.add_suffix(self.overlay_entry)
        overlay_row.set_activatable_widget(self.overlay_entry)
        appearance_group.add(overlay_row)

        # Fill color selector: Black vs White
        fill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        fill_box.set_valign(Gtk.Align.CENTER)
        self.btn_black = Gtk.Button(label=_("color_black"))
        self.btn_black.add_css_class("flat")
        self.btn_white = Gtk.Button(label=_("color_white"))
        self.btn_white.add_css_class("flat")

        if self.selected_fill == (1.0, 1.0, 1.0):
            self.btn_white.add_css_class("suggested-action")
        else:
            self.btn_black.add_css_class("suggested-action")

        def set_fill(col):
            self.selected_fill = col
            if col == (0.0, 0.0, 0.0):
                self.selected_text_color = (1.0, 1.0, 1.0)
                self.btn_black.add_css_class("suggested-action")
                self.btn_white.remove_css_class("suggested-action")
            else:
                self.selected_text_color = (0.0, 0.0, 0.0)
                self.btn_white.add_css_class("suggested-action")
                self.btn_black.remove_css_class("suggested-action")

        self.btn_black.connect("clicked", lambda b: set_fill((0.0, 0.0, 0.0)))
        self.btn_white.connect("clicked", lambda b: set_fill((1.0, 1.0, 1.0)))
        fill_box.append(self.btn_black)
        fill_box.append(self.btn_white)

        fill_row = Adw.ActionRow(title=_safe_markup(_("redaction_fill_color")))
        fill_row.add_suffix(fill_box)
        appearance_group.add(fill_row)

        # Results & Preview Row
        results_group = Adw.PreferencesGroup()
        content_box.append(results_group)

        self.results_row = Adw.ActionRow()
        self.results_row.set_title(_safe_markup(_("search_redact_no_matches")))

        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        nav_box.set_valign(Gtk.Align.CENTER)

        self.prev_match_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
        self.prev_match_btn.set_tooltip_text(f"{_('search_prev')} (Shift+F3)")
        self.prev_match_btn.set_sensitive(False)
        self.prev_match_btn.connect("clicked", self._on_prev_match_clicked)
        nav_box.append(self.prev_match_btn)

        self.next_match_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
        self.next_match_btn.set_tooltip_text(f"{_('search_next')} (F3 / Enter)")
        self.next_match_btn.set_sensitive(False)
        self.next_match_btn.connect("clicked", self._on_next_match_clicked)
        nav_box.append(self.next_match_btn)

        self.preview_btn = Gtk.Button(label=_("search_redact_btn_preview"))
        self.preview_btn.set_valign(Gtk.Align.CENTER)
        self.preview_btn.add_css_class("flat")
        self.preview_btn.connect("clicked", self._on_preview_clicked)
        nav_box.append(self.preview_btn)

        self.results_row.add_suffix(nav_box)
        results_group.add(self.results_row)

        if initial_query:
            self._update_matches()

    def _on_close_request(self, window):
        self._clear_canvas_preview()
        return False

    def _clear_canvas_preview(self):
        if self.parent_window and hasattr(self.parent_window, 'search_engine') and self.parent_window.search_engine:
            self.parent_window.search_engine.clear()
            if hasattr(self.parent_window, 'pdf_view') and self.parent_window.pdf_view:
                self.parent_window.pdf_view.queue_draw()

    def _on_prev_match_clicked(self, _button):
        if self.parent_window and hasattr(self.parent_window, '_search_navigate_prev'):
            self.parent_window._search_navigate_prev()
            self._update_results_ui()

    def _on_next_match_clicked(self, _button):
        if self.parent_window and hasattr(self.parent_window, '_search_navigate_next'):
            self.parent_window._search_navigate_next()
            self._update_results_ui()

    def _on_mode_changed(self, dropdown, param):
        is_pattern = (dropdown.get_selected() == 1)
        self.query_row.set_visible(not is_pattern)
        self.pattern_row.set_visible(is_pattern)
        self.case_row.set_visible(not is_pattern)
        self.whole_word_row.set_visible(not is_pattern)
        self._update_matches()

    def _on_preview_clicked(self, _button):
        self._update_matches()

    def _update_matches(self):
        if not self.doc or len(self.doc) == 0:
            self.current_matches = []
            self._clear_canvas_preview()
            self._update_results_ui()
            return

        is_pattern = (self.mode_dropdown.get_selected() == 1)
        is_current_page_only = (self.scope_dropdown.get_selected() == 1)
        target_pages = [self.current_page_num] if is_current_page_only else list(range(len(self.doc)))

        if is_pattern:
            idx = self.pattern_dropdown.get_selected()
            if 0 <= idx < len(self.pii_keys):
                pattern_key = self.pii_keys[idx]
                self.current_matches = self.search_engine.search_pii(
                    self.doc, pattern_key=pattern_key, page_indices=target_pages
                )
            else:
                self.current_matches = []
        else:
            query = self.query_entry.get_text().strip()
            if not query:
                self.current_matches = []
            else:
                case_sensitive = self.case_switch.get_active()
                whole_word = self.whole_word_switch.get_active()
                all_hits = self.search_engine.search(
                    self.doc, query=query, case_sensitive=case_sensitive, whole_word=whole_word
                )
                if is_current_page_only:
                    self.current_matches = [m for m in all_hits if m.page_index == self.current_page_num]
                else:
                    self.current_matches = list(all_hits)

        self._update_results_ui()

        # Synchronize live search preview highlights on parent canvas
        if self.parent_window and hasattr(self.parent_window, 'search_engine') and self.parent_window.search_engine:
            self.parent_window.search_engine.doc = self.doc
            self.parent_window.search_engine.matches = list(self.current_matches)
            if self.current_matches:
                self.parent_window.search_engine.find_nearest_match(self.current_page_num)
                if hasattr(self.parent_window, '_jump_to_current_search_match'):
                    self.parent_window._jump_to_current_search_match()
            else:
                self.parent_window.search_engine.clear()
            if hasattr(self.parent_window, 'pdf_view') and self.parent_window.pdf_view:
                self.parent_window.pdf_view.queue_draw()

    def _update_results_ui(self):
        count = len(self.current_matches)
        if count > 0:
            curr_idx = -1
            if self.parent_window and hasattr(self.parent_window, 'search_engine') and self.parent_window.search_engine:
                curr_idx = self.parent_window.search_engine.current_index
            pages = len(set(m.page_index for m in self.current_matches))
            msg = _("search_redact_matches_found", count, pages)
            if curr_idx >= 0:
                msg += f" • [{curr_idx + 1}/{count}]"
            self.results_row.set_title(_safe_markup(msg))
            self.confirm_btn.set_sensitive(True)
            if hasattr(self, 'prev_match_btn'):
                self.prev_match_btn.set_sensitive(count > 1)
            if hasattr(self, 'next_match_btn'):
                self.next_match_btn.set_sensitive(count > 1)
        else:
            self.results_row.set_title(_safe_markup(_("search_redact_no_matches")))
            self.confirm_btn.set_sensitive(False)
            if hasattr(self, 'prev_match_btn'):
                self.prev_match_btn.set_sensitive(False)
            if hasattr(self, 'next_match_btn'):
                self.next_match_btn.set_sensitive(False)

    def _on_confirm_clicked(self, _button):
        if not self.current_matches:
            return
        overlay_text = self.overlay_entry.get_text().strip()
        matches = list(self.current_matches)
        fill_col = self.selected_fill
        text_col = self.selected_text_color
        self._clear_canvas_preview()

        if self.on_confirm_callback:
            self.on_confirm_callback(matches, overlay_text, fill_col, text_col)
        self.destroy()
