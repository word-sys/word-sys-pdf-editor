"""Dedicated GNOME / Libadwaita Preferences Window"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GObject, Gtk

from . import utils
from .i18n import _, get_language, get_setting, get_supported_languages
from .settings_manager import (
    DEFAULT_TOOLBAR_TOOLS_ORDER,
    HAMBURGER_DOCUMENT_ACTION_KEYS,
    HAMBURGER_INLINE_TOGGLE_KEYS,
    HAMBURGER_ITEM_LABELS,
    TOOLBAR_LAYOUT_PRESETS,
    TOOLBAR_TOOL_METADATA,
    SettingsManager,
    get_settings_manager,
)


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
        self._build_hamburger_page()
        self._build_toolbar_page()

        self._unsub_settings = self.settings.subscribe(self._on_setting_changed)
        self.connect("close-request", self._on_close_request)

    def _build_general_page(self) -> None:
        self.general_page = Adw.PreferencesPage(
            title=_("prefs_page_general"),
            icon_name="preferences-system-symbolic",
        )
        self.general_page.set_name("general")

        self.appearance_group = Adw.PreferencesGroup(
            title=_("prefs_group_appearance"),
            description=_("prefs_group_appearance_desc"),
        )

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

        self.behavior_group = Adw.PreferencesGroup(
            title=_("prefs_group_behavior"),
        )

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


    def _build_workflow_page(self) -> None:
        self.workflow_page = Adw.PreferencesPage(
            title=_("prefs_page_workflow"),
            icon_name="applications-graphics-symbolic",
        )
        self.workflow_page.set_name("workflow")

        self.tool_switching_group = Adw.PreferencesGroup(
            title=_("prefs_group_tool_switching"),
            description=_("prefs_group_tool_switching_desc"),
        )

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

        self.text_defaults_group = Adw.PreferencesGroup(
            title=_("prefs_group_text_defaults"),
            description=_("prefs_group_text_defaults_desc"),
        )

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

    def _build_hamburger_page(self) -> None:
        self.hamburger_page = Adw.PreferencesPage(
            title=_("prefs_page_hamburger"),
            icon_name="open-menu-symbolic",
        )
        self.hamburger_page.set_name("hamburger")

        self.hamburger_preset_group = Adw.PreferencesGroup(
            title=_("prefs_group_hamburger_preset"),
            description=_("prefs_group_hamburger_preset_desc"),
        )

        self.hamburger_preset_row = Adw.ActionRow(
            title=_("prefs_hamburger_preset_title"),
            subtitle=_("prefs_hamburger_preset_subtitle"),
        )
        self._hamburger_preset_codes: List[str] = ["standard", "minimal", "full", "custom"]
        preset_labels: List[str] = [
            _("prefs_hamburger_preset_standard"),
            _("prefs_hamburger_preset_minimal"),
            _("prefs_hamburger_preset_full"),
            _("prefs_hamburger_preset_custom"),
        ]
        self.hamburger_preset_dropdown = Gtk.DropDown.new_from_strings(preset_labels)
        self.hamburger_preset_dropdown.set_valign(Gtk.Align.CENTER)
        current_preset = str(self.settings.get("hamburger_menu_preset", "standard"))
        if current_preset in self._hamburger_preset_codes:
            self.hamburger_preset_dropdown.set_selected(self._hamburger_preset_codes.index(current_preset))
        self.hamburger_preset_dropdown.connect("notify::selected", self._on_hamburger_preset_changed)
        self.hamburger_preset_row.add_suffix(self.hamburger_preset_dropdown)
        self.hamburger_preset_row.set_activatable_widget(self.hamburger_preset_dropdown)
        self.hamburger_preset_group.add(self.hamburger_preset_row)
        self.hamburger_page.add(self.hamburger_preset_group)

        self.hamburger_item_rows: Dict[str, Adw.ActionRow] = {}
        self.hamburger_item_switches: Dict[str, Gtk.Switch] = {}
        visible_items: Dict[str, bool] = dict(self.settings.get("hamburger_visible_items"))

        self.hamburger_doc_actions_group = Adw.PreferencesGroup(
            title=_("prefs_group_hamburger_doc_actions"),
            description=_("prefs_group_hamburger_doc_actions_desc"),
        )
        for item_key in HAMBURGER_DOCUMENT_ACTION_KEYS:
            label_key = HAMBURGER_ITEM_LABELS.get(item_key, item_key)
            row = Adw.ActionRow(title=_(label_key))
            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            sw.set_active(bool(visible_items.get(item_key, True)))
            sw.connect("notify::active", self._on_hamburger_item_toggled, item_key)
            row.add_suffix(sw)
            row.set_activatable_widget(sw)
            self.hamburger_doc_actions_group.add(row)
            self.hamburger_item_rows[item_key] = row
            self.hamburger_item_switches[item_key] = sw
        self.hamburger_page.add(self.hamburger_doc_actions_group)

        self.hamburger_inline_toggles_group = Adw.PreferencesGroup(
            title=_("prefs_group_hamburger_inline_toggles"),
            description=_("prefs_group_hamburger_inline_toggles_desc"),
        )
        for item_key in HAMBURGER_INLINE_TOGGLE_KEYS:
            label_key = HAMBURGER_ITEM_LABELS.get(item_key, item_key)
            row = Adw.ActionRow(title=_(label_key))
            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            sw.set_active(bool(visible_items.get(item_key, False)))
            sw.connect("notify::active", self._on_hamburger_item_toggled, item_key)
            row.add_suffix(sw)
            row.set_activatable_widget(sw)
            self.hamburger_inline_toggles_group.add(row)
            self.hamburger_item_rows[item_key] = row
            self.hamburger_item_switches[item_key] = sw
        self.hamburger_page.add(self.hamburger_inline_toggles_group)

        self.add(self.hamburger_page)

    def _build_toolbar_page(self) -> None:
        self.toolbar_page = Adw.PreferencesPage(
            title=_("prefs_page_toolbar"),
            icon_name="view-grid-symbolic",
        )
        self.toolbar_page.set_name("toolbar")

        self.toolbar_preset_group = Adw.PreferencesGroup(
            title=_("prefs_group_toolbar_presets"),
            description=_("prefs_group_toolbar_presets_desc"),
        )
        self.toolbar_preset_row = Adw.ActionRow(
            title=_("prefs_toolbar_preset_title"),
            subtitle=_("prefs_toolbar_preset_subtitle"),
        )
        self._toolbar_preset_codes: List[str] = [
            "default",
            "essential",
            "annotation",
            "forms_signing",
            "custom",
        ]
        preset_labels: List[str] = [
            _("prefs_toolbar_preset_default"),
            _("prefs_toolbar_preset_essential"),
            _("prefs_toolbar_preset_annotation"),
            _("prefs_toolbar_preset_forms"),
            _("prefs_toolbar_preset_custom"),
        ]
        self.toolbar_preset_dropdown = Gtk.DropDown.new_from_strings(preset_labels)
        self.toolbar_preset_dropdown.set_valign(Gtk.Align.CENTER)
        detected_preset = self._detect_current_toolbar_preset()
        if detected_preset in self._toolbar_preset_codes:
            self.toolbar_preset_dropdown.set_selected(self._toolbar_preset_codes.index(detected_preset))
        self.toolbar_preset_dropdown.connect("notify::selected", self._on_toolbar_preset_changed)

        self.toolbar_reset_button = Gtk.Button(label=_("prefs_toolbar_reset_btn"))
        self.toolbar_reset_button.set_valign(Gtk.Align.CENTER)
        self.toolbar_reset_button.set_tooltip_text(_("prefs_toolbar_reset_tip"))
        self.toolbar_reset_button.connect("clicked", self._on_toolbar_reset_clicked)

        self.toolbar_preset_row.add_suffix(self.toolbar_preset_dropdown)
        self.toolbar_preset_row.add_suffix(self.toolbar_reset_button)
        self.toolbar_preset_group.add(self.toolbar_preset_row)
        self.toolbar_page.add(self.toolbar_preset_group)

        self.toolbar_tools_group = Adw.PreferencesGroup(
            title=_("prefs_group_toolbar_tools"),
            description=_("prefs_group_toolbar_tools_desc"),
        )
        self.toolbar_tools_listbox = Gtk.ListBox()
        self.toolbar_tools_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.toolbar_tools_listbox.add_css_class("boxed-list")
        self.toolbar_tools_group.add(self.toolbar_tools_listbox)
        self.toolbar_page.add(self.toolbar_tools_group)

        self.toolbar_tool_rows: Dict[str, Adw.ActionRow] = {}
        self.toolbar_tool_switches: Dict[str, Gtk.Switch] = {}
        self.toolbar_move_up_buttons: Dict[str, Gtk.Button] = {}
        self.toolbar_move_down_buttons: Dict[str, Gtk.Button] = {}
        self._refresh_toolbar_rows()

        self.add(self.toolbar_page)

    def _detect_current_toolbar_preset(self) -> str:
        order = list(self.settings.get("toolbar_tools_order", DEFAULT_TOOLBAR_TOOLS_ORDER))
        visible = dict(self.settings.get("toolbar_visible_tools", {}))
        for preset_name, preset_data in TOOLBAR_LAYOUT_PRESETS.items():
            if order == list(preset_data["order"]) and visible == dict(preset_data["visible"]):
                return preset_name
        return "custom"

    def _refresh_toolbar_rows(self) -> None:
        was_syncing = self._syncing_ui
        self._syncing_ui = True
        try:
            child = self.toolbar_tools_listbox.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.toolbar_tools_listbox.remove(child)
                child = nxt

            self.toolbar_tool_rows.clear()
            self.toolbar_tool_switches.clear()
            self.toolbar_move_up_buttons.clear()
            self.toolbar_move_down_buttons.clear()

            order: List[str] = list(self.settings.get("toolbar_tools_order", DEFAULT_TOOLBAR_TOOLS_ORDER))
            visible: Dict[str, bool] = dict(self.settings.get("toolbar_visible_tools", {}))
            total = len(order)

            for idx, tool_id in enumerate(order):
                meta = TOOLBAR_TOOL_METADATA.get(tool_id, {})
                label_key = meta.get("label_key", tool_id)
                tip_key = meta.get("tip_key", "")
                icon_name = meta.get("icon", "applications-graphics-symbolic")
                shortcut = meta.get("shortcut", "")

                row = Adw.ActionRow(
                    title=_(label_key),
                    subtitle=_(tip_key) if tip_key else "",
                )

                prefix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                prefix_box.set_valign(Gtk.Align.CENTER)
                drag_icon = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
                drag_icon.add_css_class("dim-label")
                tool_icon = Gtk.Image.new_from_icon_name(icon_name)
                prefix_box.append(drag_icon)
                prefix_box.append(tool_icon)
                row.add_prefix(prefix_box)

                if shortcut:
                    sc_lbl = Gtk.Label(label=shortcut)
                    sc_lbl.set_valign(Gtk.Align.CENTER)
                    sc_lbl.add_css_class("dim-label")
                    sc_lbl.add_css_class("caption")
                    row.add_suffix(sc_lbl)

                up_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
                up_btn.add_css_class("flat")
                up_btn.set_valign(Gtk.Align.CENTER)
                up_btn.set_tooltip_text(_("prefs_tool_move_up_tip"))
                up_btn.set_sensitive(idx > 0)
                up_btn.connect("clicked", lambda _b, tid=tool_id: self.move_tool(tid, -1))
                row.add_suffix(up_btn)

                down_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
                down_btn.add_css_class("flat")
                down_btn.set_valign(Gtk.Align.CENTER)
                down_btn.set_tooltip_text(_("prefs_tool_move_down_tip"))
                down_btn.set_sensitive(idx < total - 1)
                down_btn.connect("clicked", lambda _b, tid=tool_id: self.move_tool(tid, 1))
                row.add_suffix(down_btn)

                sw = Gtk.Switch()
                sw.set_valign(Gtk.Align.CENTER)
                is_vis = True if tool_id == "select" else bool(visible.get(tool_id, True))
                sw.set_active(is_vis)
                if tool_id == "select":
                    sw.set_sensitive(False)
                    sw.set_tooltip_text(_("prefs_tool_select_always_visible_tip"))
                else:
                    sw.set_tooltip_text(_("prefs_tool_visible_tip"))
                    sw.connect(
                        "notify::active",
                        lambda s, _pspec, tid=tool_id: self._on_toolbar_tool_switch_toggled(s, tid),
                    )
                row.add_suffix(sw)

                try:
                    drag_source = Gtk.DragSource.new()
                    drag_source.set_actions(Gdk.DragAction.MOVE)
                    drag_source.connect(
                        "prepare",
                        lambda _src, _x, _y, tid=tool_id: Gdk.ContentProvider.new_for_value(tid),
                    )
                    row.add_controller(drag_source)

                    drop_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
                    drop_target.connect(
                        "drop",
                        lambda _tgt, val, _x, _y, target_idx=idx: self._on_tool_row_dropped(val, target_idx),
                    )
                    row.add_controller(drop_target)
                except Exception:
                    pass

                self.toolbar_tools_listbox.append(row)
                self.toolbar_tool_rows[tool_id] = row
                self.toolbar_tool_switches[tool_id] = sw
                self.toolbar_move_up_buttons[tool_id] = up_btn
                self.toolbar_move_down_buttons[tool_id] = down_btn

            detected = self._detect_current_toolbar_preset()
            if detected in self._toolbar_preset_codes:
                p_idx = self._toolbar_preset_codes.index(detected)
                if self.toolbar_preset_dropdown.get_selected() != p_idx:
                    self.toolbar_preset_dropdown.set_selected(p_idx)
        finally:
            self._syncing_ui = was_syncing

    def _on_tool_row_dropped(self, dragged_tool_id: Any, target_index: int) -> bool:
        if not isinstance(dragged_tool_id, str):
            return False
        self.move_tool_to_index(dragged_tool_id, target_index)
        return True

    def move_tool(self, tool_id: str, delta: int) -> List[str]:
        """Move `tool_id` by `delta` positions (-1 up, +1 down) in the toolbar ordering."""
        order = list(self.settings.get("toolbar_tools_order", DEFAULT_TOOLBAR_TOOLS_ORDER))
        if tool_id not in order:
            return order
        cur_idx = order.index(tool_id)
        new_idx = max(0, min(len(order) - 1, cur_idx + int(delta)))
        return self.move_tool_to_index(tool_id, new_idx)

    def move_tool_to_index(self, tool_id: str, new_index: int) -> List[str]:
        """Move `tool_id` to `new_index` in the toolbar ordering and rebuild live."""
        order = list(self.settings.get("toolbar_tools_order", DEFAULT_TOOLBAR_TOOLS_ORDER))
        if tool_id not in order:
            return order
        cur_idx = order.index(tool_id)
        clamped_idx = max(0, min(len(order) - 1, int(new_index)))
        if cur_idx == clamped_idx:
            return order
        order.pop(cur_idx)
        order.insert(clamped_idx, tool_id)
        self.settings.set("toolbar_tools_order", order)
        self._refresh_toolbar_rows()
        if self.editor_window is not None and hasattr(self.editor_window, "rebuild_tools_grid"):
            self.editor_window.rebuild_tools_grid()
        return order

    def set_tool_visibility(self, tool_id: str, is_visible: bool) -> Dict[str, bool]:
        """Set visibility of `tool_id` on the primary toolbar (keeping 'select' always visible)."""
        vis_map = dict(self.settings.get("toolbar_visible_tools", {}))
        vis_map[tool_id] = True if tool_id == "select" else bool(is_visible)
        vis_map["select"] = True
        self.settings.set("toolbar_visible_tools", vis_map)
        self._refresh_toolbar_rows()
        if self.editor_window is not None and hasattr(self.editor_window, "rebuild_tools_grid"):
            self.editor_window.rebuild_tools_grid()
        return vis_map

    def _on_toolbar_tool_switch_toggled(self, switch: Gtk.Switch, tool_id: str) -> None:
        if self._syncing_ui:
            return
        self.set_tool_visibility(tool_id, bool(switch.get_active()))

    def _on_toolbar_preset_changed(self, dropdown: Gtk.DropDown, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        idx = int(dropdown.get_selected())
        if 0 <= idx < len(self._toolbar_preset_codes):
            preset_code = self._toolbar_preset_codes[idx]
            if preset_code in TOOLBAR_LAYOUT_PRESETS:
                self.settings.apply_toolbar_preset(preset_code)
                self._refresh_toolbar_rows()
                if self.editor_window is not None and hasattr(self.editor_window, "rebuild_tools_grid"):
                    self.editor_window.rebuild_tools_grid()

    def _on_toolbar_reset_clicked(self, _button: Gtk.Button) -> None:
        self.settings.reset_toolbar_to_default()
        self._refresh_toolbar_rows()
        if self.editor_window is not None and hasattr(self.editor_window, "rebuild_tools_grid"):
            self.editor_window.rebuild_tools_grid()

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

    def _on_hamburger_preset_changed(self, dropdown: Gtk.DropDown, _pspec: Any) -> None:
        if self._syncing_ui:
            return
        idx = int(dropdown.get_selected())
        if 0 <= idx < len(self._hamburger_preset_codes):
            preset_code = self._hamburger_preset_codes[idx]
            self.settings.set("hamburger_menu_preset", preset_code)
            if self.editor_window is not None and hasattr(self.editor_window, "rebuild_hamburger_menu"):
                self.editor_window.rebuild_hamburger_menu()

    def _on_hamburger_item_toggled(self, switch: Gtk.Switch, _pspec: Any, item_key: str) -> None:
        if self._syncing_ui:
            return
        items = dict(self.settings.get("hamburger_visible_items"))
        items[item_key] = bool(switch.get_active())
        self.settings.set("hamburger_visible_items", items)
        if self.editor_window is not None and hasattr(self.editor_window, "rebuild_hamburger_menu"):
            self.editor_window.rebuild_hamburger_menu()

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
            elif key == "hamburger_menu_preset" and isinstance(value, str):
                if value in self._hamburger_preset_codes:
                    idx = self._hamburger_preset_codes.index(value)
                    if self.hamburger_preset_dropdown.get_selected() != idx:
                        self.hamburger_preset_dropdown.set_selected(idx)
            elif key == "hamburger_visible_items" and isinstance(value, dict):
                for item_key, sw in self.hamburger_item_switches.items():
                    bval = bool(value.get(item_key, False))
                    if sw.get_active() != bval:
                        sw.set_active(bval)
            elif key in ("toolbar_tools_order", "toolbar_visible_tools"):
                self._refresh_toolbar_rows()
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
