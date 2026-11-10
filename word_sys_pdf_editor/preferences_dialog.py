"""Dedicated GNOME / Libadwaita Preferences Window for Word-Sys PDF Editor."""

from __future__ import annotations

from typing import Any, List, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from . import utils
from .i18n import _, get_language, get_setting, get_supported_languages
from .settings_manager import SettingsManager, get_settings_manager


class PreferencesWindow(Adw.PreferencesWindow):
    """Application Preferences Window providing General, Workflow, Menu, and Toolbar pages."""

    def __init__(
        self,
        editor_window: Optional[Any] = None,
        settings_manager: Optional[SettingsManager] = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.editor_window = editor_window
        self.settings: SettingsManager = settings_manager or get_settings_manager()
        self._syncing_ui: bool = False

        self.set_title(_("prefs_window_title"))
        self.set_default_size(680, 560)
        self.set_search_enabled(True)
        self.set_modal(False)
        if editor_window is not None and isinstance(editor_window, Gtk.Window):
            self.set_transient_for(editor_window)

        self._build_general_page()
        self._build_workflow_page()

        self._unsub_settings = self.settings.subscribe(self._on_setting_changed)
        self.connect("close-request", self._on_close_request)

    # ------------------------------------------------------------------
    # Page 1: General & Appearance
    # ------------------------------------------------------------------
    def _build_general_page(self) -> None:
        self.general_page = Adw.PreferencesPage(
            title=_("prefs_page_general"),
            icon_name="preferences-system-symbolic",
        )
        self.general_page.set_name("general")

        # Group 1: Language & Viewing
        self.appearance_group = Adw.PreferencesGroup(
            title=_("prefs_group_appearance"),
            description=_("prefs_group_appearance_desc"),
        )

        # 1. Application Language selector
        self.language_row = Adw.ActionRow(
            title=_("prefs_lang_title"),
            subtitle=_("prefs_lang_subtitle"),
        )
        supported = get_supported_languages()
        self._lang_codes: List[str] = [code for code, _name in supported]
        lang_names: List[str] = [name for _code, name in supported]
        self.language_dropdown = Gtk.DropDown.new_from_strings(lang_names)
        self.language_dropdown.set_valign(Gtk.Align.CENTER)
        current_lang = get_language()
        if current_lang in self._lang_codes:
            self.language_dropdown.set_selected(self._lang_codes.index(current_lang))
        self.language_dropdown.connect("notify::selected", self._on_language_dropdown_changed)
        self.language_row.add_suffix(self.language_dropdown)
        self.language_row.set_activatable_widget(self.language_dropdown)
        self.appearance_group.add(self.language_row)

        # 2. Continuous Vertical Scrolling switch
        self.continuous_scroll_row = Adw.ActionRow(
            title=_("prefs_continuous_scroll_title"),
            subtitle=_("prefs_continuous_scroll_subtitle"),
        )
        self.continuous_scroll_switch = Gtk.Switch()
        self.continuous_scroll_switch.set_valign(Gtk.Align.CENTER)
        init_cont = (
            bool(getattr(self.editor_window, "continuous_scroll", False))
            if self.editor_window is not None and hasattr(self.editor_window, "continuous_scroll")
            else bool(self.settings.get("continuous_scroll", True))
        )
        self.continuous_scroll_switch.set_active(init_cont)
        self.continuous_scroll_switch.connect("notify::active", self._on_continuous_scroll_toggled)
        self.continuous_scroll_row.add_suffix(self.continuous_scroll_switch)
        self.continuous_scroll_row.set_activatable_widget(self.continuous_scroll_switch)
        self.appearance_group.add(self.continuous_scroll_row)

        # 3. Eco / Low-Hardware Performance Mode switch
        self.eco_mode_row = Adw.ActionRow(
            title=_("prefs_eco_mode_title"),
            subtitle=_("prefs_eco_mode_subtitle"),
        )
        self.eco_mode_switch = Gtk.Switch()
        self.eco_mode_switch.set_valign(Gtk.Align.CENTER)
        init_eco = (
            bool(getattr(self.editor_window, "is_eco_mode", False))
            if self.editor_window is not None and hasattr(self.editor_window, "is_eco_mode")
            else bool(self.settings.get("is_eco_mode", False))
        )
        self.eco_mode_switch.set_active(init_eco)
        self.eco_mode_switch.connect("notify::active", self._on_eco_mode_toggled)
        self.eco_mode_row.add_suffix(self.eco_mode_switch)
        self.eco_mode_row.set_activatable_widget(self.eco_mode_switch)
        self.appearance_group.add(self.eco_mode_row)

        self.general_page.add(self.appearance_group)

        # Group 2: Document & Editing Safeguards
        self.behavior_group = Adw.PreferencesGroup(
            title=_("prefs_group_behavior"),
        )

        # 4. Confirm Before Deleting Objects switch
        self.confirm_delete_row = Adw.ActionRow(
            title=_("prefs_confirm_delete_title"),
            subtitle=_("prefs_confirm_delete_subtitle"),
        )
        self.confirm_delete_switch = Gtk.Switch()
        self.confirm_delete_switch.set_valign(Gtk.Align.CENTER)
        init_confirm = bool(get_setting("confirm_delete_objects", self.settings.get("confirm_delete", False)))
        self.confirm_delete_switch.set_active(init_confirm)
        self.confirm_delete_switch.connect("notify::active", self._on_confirm_delete_toggled)
        self.confirm_delete_row.add_suffix(self.confirm_delete_switch)
        self.confirm_delete_row.set_activatable_widget(self.confirm_delete_switch)
        self.behavior_group.add(self.confirm_delete_row)

        # 5. Reveal OCR Text Confidence Layer switch
        self.ocr_overlay_row = Adw.ActionRow(
            title=_("prefs_ocr_overlay_title"),
            subtitle=_("prefs_ocr_overlay_subtitle"),
        )
        self.ocr_overlay_switch = Gtk.Switch()
        self.ocr_overlay_switch.set_valign(Gtk.Align.CENTER)
        init_ocr = (
            bool(getattr(self.editor_window, "show_ocr_overlay", False))
            if self.editor_window is not None and hasattr(self.editor_window, "show_ocr_overlay")
            else bool(self.settings.get("show_ocr_overlay", False))
        )
        self.ocr_overlay_switch.set_active(init_ocr)
        self.ocr_overlay_switch.connect("notify::active", self._on_ocr_overlay_toggled)
        self.ocr_overlay_row.add_suffix(self.ocr_overlay_switch)
        self.ocr_overlay_row.set_activatable_widget(self.ocr_overlay_switch)
        self.behavior_group.add(self.ocr_overlay_row)

        # 6. Auto-Reload PDF When Modified on Disk switch
        self.auto_reload_row = Adw.ActionRow(
            title=_("prefs_auto_reload_title"),
            subtitle=_("prefs_auto_reload_subtitle"),
        )
        self.auto_reload_switch = Gtk.Switch()
        self.auto_reload_switch.set_valign(Gtk.Align.CENTER)
        init_auto_reload = bool(self.settings.get("auto_reload_modified_pdf", True))
        self.auto_reload_switch.set_active(init_auto_reload)
        self.auto_reload_switch.connect("notify::active", self._on_auto_reload_toggled)
        self.auto_reload_row.add_suffix(self.auto_reload_switch)
        self.auto_reload_row.set_activatable_widget(self.auto_reload_switch)
        self.behavior_group.add(self.auto_reload_row)

        self.general_page.add(self.behavior_group)
        self.add(self.general_page)

    # ------------------------------------------------------------------
    # Page 2: Tools & Workflow
    # ------------------------------------------------------------------
    def _build_workflow_page(self) -> None:
        self.workflow_page = Adw.PreferencesPage(
            title=_("prefs_page_workflow"),
            icon_name="applications-graphics-symbolic",
        )
        self.workflow_page.set_name("workflow")

        # Group 1: Tool Switching Behavior
        self.tool_switching_group = Adw.PreferencesGroup(
            title=_("prefs_group_tool_switching"),
            description=_("prefs_group_tool_switching_desc"),
        )

        # 1. Automatically switch to Selection tool after creating or editing an object
        self.auto_switch_row = Adw.ActionRow(
            title=_("prefs_auto_switch_select_title"),
            subtitle=_("prefs_auto_switch_select_subtitle"),
        )
        self.auto_switch_switch = Gtk.Switch()
        self.auto_switch_switch.set_valign(Gtk.Align.CENTER)
        self.auto_switch_switch.set_active(bool(self.settings.get("auto_switch_to_select", True)))
        self.auto_switch_switch.connect("notify::active", self._on_auto_switch_toggled)
        self.auto_switch_row.add_suffix(self.auto_switch_switch)
        self.auto_switch_row.set_activatable_widget(self.auto_switch_switch)
        self.tool_switching_group.add(self.auto_switch_row)

        # 2. Keep Pen and Highlighter active across multiple strokes
        self.keep_drawing_row = Adw.ActionRow(
            title=_("prefs_keep_drawing_active_title"),
            subtitle=_("prefs_keep_drawing_active_subtitle"),
        )
        self.keep_drawing_switch = Gtk.Switch()
        self.keep_drawing_switch.set_valign(Gtk.Align.CENTER)
        self.keep_drawing_switch.set_active(bool(self.settings.get("keep_drawing_tools_active", True)))
        self.keep_drawing_switch.connect("notify::active", self._on_keep_drawing_toggled)
        self.keep_drawing_row.add_suffix(self.keep_drawing_switch)
        self.keep_drawing_row.set_activatable_widget(self.keep_drawing_switch)
        self.tool_switching_group.add(self.keep_drawing_row)

        self.workflow_page.add(self.tool_switching_group)

        # Group 2: Default Text Formatting
        self.text_defaults_group = Adw.PreferencesGroup(
            title=_("prefs_group_text_defaults"),
            description=_("prefs_group_text_defaults_desc"),
        )

        # 3. Default Font Family selector
        self.default_font_row = Adw.ActionRow(
            title=_("prefs_default_font_family_title"),
            subtitle=_("prefs_default_font_family_subtitle"),
        )
        self._font_families: List[str] = self._collect_available_font_families()
        self.default_font_dropdown = Gtk.DropDown.new_from_strings(self._font_families)
        self.default_font_dropdown.set_valign(Gtk.Align.CENTER)
        saved_font = str(self.settings.get("default_font_family", "Liberation Sans") or "Liberation Sans")
        if saved_font in self._font_families:
            self.default_font_dropdown.set_selected(self._font_families.index(saved_font))
        self.default_font_dropdown.connect("notify::selected", self._on_default_font_changed)
        self.default_font_row.add_suffix(self.default_font_dropdown)
        self.default_font_row.set_activatable_widget(self.default_font_dropdown)
        self.text_defaults_group.add(self.default_font_row)

        # 4. Default Font Size spin button
        self.default_font_size_row = Adw.ActionRow(
            title=_("prefs_default_font_size_title"),
            subtitle=_("prefs_default_font_size_subtitle"),
        )
        self.default_font_size_spin = Gtk.SpinButton.new_with_range(4.0, 144.0, 0.5)
        self.default_font_size_spin.set_digits(1)
        self.default_font_size_spin.set_valign(Gtk.Align.CENTER)
        self.default_font_size_spin.set_value(float(self.settings.get("default_font_size", 11.0)))
        self.default_font_size_spin.connect("value-changed", self._on_default_font_size_changed)
        self.default_font_size_row.add_suffix(self.default_font_size_spin)
        self.default_font_size_row.set_activatable_widget(self.default_font_size_spin)
        self.text_defaults_group.add(self.default_font_size_row)

        self.workflow_page.add(self.text_defaults_group)
        self.add(self.workflow_page)

    @staticmethod
    def _collect_available_font_families() -> List[str]:
        base_families = [
            "Liberation Sans",
            "Liberation Serif",
            "Liberation Mono",
            "DejaVu Sans",
            "DejaVu Serif",
            "DejaVu Sans Mono",
            "Helvetica",
            "Times-Roman",
            "Courier",
        ]
        discovered = list(getattr(utils, "FONT_FAMILY_LIST_SORTED", []) or [])
        combined: List[str] = []
        seen = set()
        for fam in base_families + discovered:
            if fam and fam not in seen:
                combined.append(fam)
                seen.add(fam)
        return combined

    # ------------------------------------------------------------------
    # Signal Handlers
    # ------------------------------------------------------------------
    def _on_language_dropdown_changed(self, dropdown: Gtk.DropDown, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        idx = int(dropdown.get_selected())
        if 0 <= idx < len(self._lang_codes):
            target_code = self._lang_codes[idx]
            if self.editor_window is not None and hasattr(self.editor_window, "request_language_change"):
                self.editor_window.request_language_change(target_code)
            else:
                self.settings.set("language", target_code)

    def _on_continuous_scroll_toggled(self, switch: Gtk.Switch, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        active = bool(switch.get_active())
        self.settings.set("continuous_scroll", active)
        if self.editor_window is not None and hasattr(self.editor_window, "set_continuous_scroll_mode"):
            self.editor_window.set_continuous_scroll_mode(active)

    def _on_eco_mode_toggled(self, switch: Gtk.Switch, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        active = bool(switch.get_active())
        self.settings.set("is_eco_mode", active)
        if self.editor_window is not None and hasattr(self.editor_window, "set_eco_mode"):
            self.editor_window.set_eco_mode(active)

    def _on_confirm_delete_toggled(self, switch: Gtk.Switch, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        active = bool(switch.get_active())
        self.settings.set("confirm_delete", active)
        if self.editor_window is not None and hasattr(self.editor_window, "_update_confirm_delete_menu_state"):
            self.editor_window._update_confirm_delete_menu_state(active)

    def _on_ocr_overlay_toggled(self, switch: Gtk.Switch, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        active = bool(switch.get_active())
        self.settings.set("show_ocr_overlay", active)
        if self.editor_window is not None and hasattr(self.editor_window, "set_ocr_overlay_mode"):
            self.editor_window.set_ocr_overlay_mode(active)

    def _on_auto_reload_toggled(self, switch: Gtk.Switch, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        active = bool(switch.get_active())
        self.settings.set("auto_reload_modified_pdf", active)

    def _on_auto_switch_toggled(self, switch: Gtk.Switch, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        active = bool(switch.get_active())
        self.settings.set("auto_switch_to_select", active)
        if self.editor_window is not None and hasattr(self.editor_window, "_update_auto_switch_select_menu_state"):
            self.editor_window._update_auto_switch_select_menu_state(active)

    def _on_keep_drawing_toggled(self, switch: Gtk.Switch, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        active = bool(switch.get_active())
        self.settings.set("keep_drawing_tools_active", active)

    def _on_default_font_changed(self, dropdown: Gtk.DropDown, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        idx = int(dropdown.get_selected())
        if 0 <= idx < len(self._font_families):
            family = self._font_families[idx]
            self.settings.set("default_font_family", family)
            if self.editor_window is not None:
                self.editor_window._last_font_family = family

    def _on_default_font_size_changed(self, spin: Gtk.SpinButton) -> None:
        if self._syncing_ui:
            return
        val = round(float(spin.get_value()), 1)
        self.settings.set("default_font_size", val)
        if self.editor_window is not None:
            self.editor_window._last_font_size = val

    def _on_setting_changed(self, key: str, value: Any) -> None:
        """Synchronize UI switches if settings are changed externally while PreferencesWindow is open."""
        self._syncing_ui = True
        try:
            if key in ("continuous_scroll", "view_mode"):
                bval = (value == "continuous") if key == "view_mode" else bool(value)
                if self.continuous_scroll_switch.get_active() != bval:
                    self.continuous_scroll_switch.set_active(bval)
            elif key in ("is_eco_mode", "eco_mode") and value is not None:
                bval = bool(value)
                if self.eco_mode_switch.get_active() != bval:
                    self.eco_mode_switch.set_active(bval)
            elif key in ("confirm_delete", "confirm_delete_objects"):
                bval = bool(value)
                if self.confirm_delete_switch.get_active() != bval:
                    self.confirm_delete_switch.set_active(bval)
            elif key == "show_ocr_overlay":
                bval = bool(value)
                if self.ocr_overlay_switch.get_active() != bval:
                    self.ocr_overlay_switch.set_active(bval)
            elif key == "auto_reload_modified_pdf":
                bval = bool(value)
                if self.auto_reload_switch.get_active() != bval:
                    self.auto_reload_switch.set_active(bval)
            elif key == "auto_switch_to_select":
                bval = bool(value)
                if self.auto_switch_switch.get_active() != bval:
                    self.auto_switch_switch.set_active(bval)
            elif key == "keep_drawing_tools_active":
                bval = bool(value)
                if self.keep_drawing_switch.get_active() != bval:
                    self.keep_drawing_switch.set_active(bval)
            elif key == "default_font_family" and isinstance(value, str):
                if value in self._font_families:
                    idx = self._font_families.index(value)
                    if self.default_font_dropdown.get_selected() != idx:
                        self.default_font_dropdown.set_selected(idx)
            elif key == "default_font_size":
                try:
                    fval = float(value)
                    if abs(self.default_font_size_spin.get_value() - fval) > 0.01:
                        self.default_font_size_spin.set_value(fval)
                except (TypeError, ValueError):
                    pass
        finally:
            self._syncing_ui = False

    def _on_close_request(self, _win: Gtk.Window) -> bool:
        if getattr(self, "_unsub_settings", None):
            try:
                self._unsub_settings()
            except Exception:
                pass
            self._unsub_settings = None
        if self.editor_window is not None and getattr(self.editor_window, "_preferences_window", None) is self:
            self.editor_window._preferences_window = None
        return False
