import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw, GLib
from .i18n import _

GUIDE_CSS = b"""
.keycap {
    background-color: alpha(currentColor, 0.08);
    border: 1px solid alpha(currentColor, 0.18);
    border-bottom-width: 2px;
    border-radius: 6px;
    padding: 3px 8px;
    font-family: monospace;
    font-weight: 700;
    font-size: 0.85em;
}
.guide-search-bar {
    padding: 6px 12px;
}
"""


def _esc(text: str) -> str:
    """Safely escape text for Pango markup used in Adw titles and subtitles."""
    return GLib.markup_escape_text(text) if text else ""


def make_keycap(text: str) -> Gtk.Widget:
    """Create a styled keyboard shortcut badge."""
    lbl = Gtk.Label(label=text)
    lbl.add_css_class("keycap")
    lbl.set_valign(Gtk.Align.CENTER)
    return lbl


def make_keycap_box(*keys: str) -> Gtk.Widget:
    """Create a horizontal container with multiple shortcut badges."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.set_halign(Gtk.Align.END)
    box.set_valign(Gtk.Align.CENTER)
    for k in keys:
        box.append(make_keycap(k))
    return box


class QuickGuideDialog(Adw.Window):
    """Modern Libadwaita interactive user guide, feature reference, and shortcut manual."""

    def __init__(self, parent_window):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("guide_dialog_title"))
        self.set_default_size(860, 660)
        self.set_resizable(True)

        self._filter_records: list[dict] = []
        self._tab_groups: dict[str, list[tuple[Adw.PreferencesGroup, list[dict]]]] = {
            "tools": [],
            "canvas": [],
            "security_ocr": [],
            "shortcuts": [],
        }

        self._setup_css()

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)

        header = Adw.HeaderBar()
        view_switcher = Adw.ViewSwitcher()
        view_switcher.set_stack(self.view_stack)
        view_switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(view_switcher)

        self.search_toggle_btn = Gtk.ToggleButton()
        self.search_toggle_btn.set_icon_name("system-search-symbolic")
        self.search_toggle_btn.set_tooltip_text(_("guide_search_tooltip"))
        header.pack_end(self.search_toggle_btn)

        self.search_bar = Gtk.SearchBar()
        self.search_bar.set_key_capture_widget(self)
        self.search_entry = Gtk.SearchEntry(placeholder_text=_("guide_search_placeholder"))
        self.search_entry.set_hexpand(True)
        self.search_entry.set_width_chars(38)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_bar.set_child(self.search_entry)
        self.search_bar.connect_entry(self.search_entry)

        self.search_toggle_btn.connect("toggled", self._on_search_btn_toggled)
        self.search_bar.connect("notify::search-mode-enabled", self._on_search_mode_changed)

        main_box.append(header)
        main_box.append(self.search_bar)
        main_box.append(self.view_stack)

        self._build_tools_page()
        self._build_canvas_page()
        self._build_security_ocr_page()
        self._build_shortcuts_page()

    def _setup_css(self):
        """Register CSS styling for keycaps and guide badges."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(GUIDE_CSS)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _on_search_btn_toggled(self, btn: Gtk.ToggleButton):
        active = btn.get_active()
        if self.search_bar.get_search_mode() != active:
            self.search_bar.set_search_mode(active)
        if active:
            self.search_entry.grab_focus()
        else:
            self.search_entry.set_text("")

    def _on_search_mode_changed(self, search_bar, _pspec):
        enabled = search_bar.get_search_mode()
        if self.search_toggle_btn.get_active() != enabled:
            self.search_toggle_btn.set_active(enabled)
        if not enabled and self.search_entry.get_text():
            self.search_entry.set_text("")

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle Ctrl+F to focus search and Escape to clear search or close the guide."""
        ctrl_mask = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl_mask and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.search_bar.set_search_mode(True)
            self.search_entry.grab_focus()
            return True
        if keyval == Gdk.KEY_Escape:
            if self.search_bar.get_search_mode() and self.search_entry.get_text():
                self.search_entry.set_text("")
                self.search_bar.set_search_mode(False)
                return True
            self.destroy()
            return True
        return False

    def _add_feature_row(
        self,
        tab_id: str,
        group: Adw.PreferencesGroup,
        group_rows: list[dict],
        title_key: str,
        desc_key: str,
        icon_name: str,
        *keys: str,
    ) -> Adw.ActionRow:
        title_text = _(title_key)
        desc_text = _(desc_key)
        row = Adw.ActionRow()
        row.set_title(_esc(title_text))
        row.set_subtitle(_esc(desc_text))
        row.set_subtitle_lines(0)
        if icon_name:
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
        if keys:
            if len(keys) == 1:
                row.add_suffix(make_keycap(keys[0]))
            else:
                row.add_suffix(make_keycap_box(*keys))
        group.add(row)

        search_blob = f"{title_text} {desc_text} {' '.join(keys)}".lower()
        rec = {"row": row, "tab": tab_id, "blob": search_blob}
        group_rows.append(rec)
        self._filter_records.append(rec)
        return row

    def _add_shortcut_row(
        self,
        tab_id: str,
        group: Adw.PreferencesGroup,
        group_rows: list[dict],
        title_text: str,
        *keys: str,
    ) -> Adw.ActionRow:
        row = Adw.ActionRow()
        row.set_title(_esc(title_text))
        row.add_suffix(make_keycap_box(*keys))
        group.add(row)

        search_blob = f"{title_text} {' '.join(keys)}".lower()
        rec = {"row": row, "tab": tab_id, "blob": search_blob}
        group_rows.append(rec)
        self._filter_records.append(rec)
        return row

    def _on_search_changed(self, entry: Gtk.SearchEntry):
        query = (entry.get_text() or "").strip().lower()
        tab_match_counts: dict[str, int] = {t: 0 for t in self._tab_groups}

        for tab_id, groups in self._tab_groups.items():
            for group_widget, rows in groups:
                visible_in_group = 0
                for rec in rows:
                    matched = (not query) or (query in rec["blob"])
                    rec["row"].set_visible(matched)
                    if matched:
                        visible_in_group += 1
                        tab_match_counts[tab_id] += 1
                group_widget.set_visible(visible_in_group > 0)

        if query:
            current_tab = self.view_stack.get_visible_child_name()
            if current_tab and tab_match_counts.get(current_tab, 0) == 0:
                for tab_id in ("tools", "canvas", "security_ocr", "shortcuts"):
                    if tab_match_counts.get(tab_id, 0) > 0:
                        self.view_stack.set_visible_child_name(tab_id)
                        break

    def _build_tools_page(self):
        """Page 1: Tools, Editing, Annotations, Measurements & Forms."""
        page = Adw.PreferencesPage()
        tab_id = "tools"

        # Group 1: Selection & Typography
        grp_text = Adw.PreferencesGroup()
        grp_text.set_title(_esc(_("guide_grp_selection_text")))
        rows_text: list[dict] = []

        self._add_feature_row(
            tab_id, grp_text, rows_text,
            "guide_tool_select_title", "guide_tool_select_desc",
            "input-mouse-symbolic", "S",
        )
        self._add_feature_row(
            tab_id, grp_text, rows_text,
            "guide_tool_text_title", "guide_tool_text_desc",
            "insert-text-symbolic", "T",
        )
        self._add_feature_row(
            tab_id, grp_text, rows_text,
            "guide_tool_clone_title", "guide_tool_clone_desc",
            "edit-cut-symbolic", "C",
        )
        self._add_feature_row(
            tab_id, grp_text, rows_text,
            "guide_tool_drag_title", "guide_tool_drag_desc",
            "drag-handle-symbolic", "M",
        )
        page.add(grp_text)
        self._tab_groups[tab_id].append((grp_text, rows_text))

        # Group 2: Freehand Drawing & Vector Shapes
        grp_shapes = Adw.PreferencesGroup()
        grp_shapes.set_title(_esc(_("guide_grp_drawing_shapes")))
        rows_shapes: list[dict] = []

        self._add_feature_row(
            tab_id, grp_shapes, rows_shapes,
            "guide_tool_pen_title", "guide_tool_pen_desc",
            "document-edit-symbolic", "P",
        )
        self._add_feature_row(
            tab_id, grp_shapes, rows_shapes,
            "guide_tool_highlighter_title", "guide_tool_highlighter_desc",
            "marker-symbolic", "H",
        )
        self._add_feature_row(
            tab_id, grp_shapes, rows_shapes,
            "guide_tool_shapes_title", "guide_tool_shapes_desc",
            "checkbox-symbolic", "R", "E",
        )
        self._add_feature_row(
            tab_id, grp_shapes, rows_shapes,
            "guide_tool_markers_title", "guide_tool_markers_desc",
            "emblem-ok-symbolic", "V", "X",
        )
        self._add_feature_row(
            tab_id, grp_shapes, rows_shapes,
            "guide_tool_image_title", "guide_tool_image_desc",
            "insert-image-symbolic", "I",
        )
        page.add(grp_shapes)
        self._tab_groups[tab_id].append((grp_shapes, rows_shapes))

        # Group 3: Annotations, Stamps, Measurements & Forms
        grp_annot = Adw.PreferencesGroup()
        grp_annot.set_title(_esc(_("guide_grp_annotations_forms")))
        rows_annot: list[dict] = []

        self._add_feature_row(
            tab_id, grp_annot, rows_annot,
            "guide_tool_notes_title", "guide_tool_notes_desc",
            "user-available-symbolic", "N",
        )
        self._add_feature_row(
            tab_id, grp_annot, rows_annot,
            "guide_tool_stamps_title", "guide_tool_stamps_desc",
            "starred-symbolic", "K",
        )
        self._add_feature_row(
            tab_id, grp_annot, rows_annot,
            "guide_tool_measure_title", "guide_tool_measure_desc",
            "accessories-calculator-symbolic", "U", "A",
        )
        self._add_feature_row(
            tab_id, grp_annot, rows_annot,
            "guide_tool_forms_title", "guide_tool_forms_desc",
            "view-list-symbolic", "B",
        )
        page.add(grp_annot)
        self._tab_groups[tab_id].append((grp_annot, rows_annot))

        stack_page = self.view_stack.add_titled(page, tab_id, _("guide_tab_tools"))
        stack_page.set_icon_name("document-edit-symbolic")

    def _build_canvas_page(self):
        """Page 2: Canvas Navigation, Continuous Scroll & Page Management."""
        page = Adw.PreferencesPage()
        tab_id = "canvas"

        # Group 1: Navigation & History
        grp_nav = Adw.PreferencesGroup()
        grp_nav.set_title(_esc(_("guide_grp_navigation")))
        rows_nav: list[dict] = []

        self._add_feature_row(
            tab_id, grp_nav, rows_nav,
            "guide_nav_focal_zoom_title", "guide_nav_focal_zoom_desc",
            "zoom-in-symbolic", "Ctrl + Scroll",
        )
        self._add_feature_row(
            tab_id, grp_nav, rows_nav,
            "guide_nav_continuous_title", "guide_nav_continuous_desc",
            "view-continuous-symbolic",
        )
        self._add_feature_row(
            tab_id, grp_nav, rows_nav,
            "guide_nav_search_title", "guide_nav_search_desc",
            "edit-find-symbolic", "Ctrl + F", "Ctrl + H",
        )
        self._add_feature_row(
            tab_id, grp_nav, rows_nav,
            "guide_nav_undo_title", "guide_nav_undo_desc",
            "edit-undo-symbolic", "Ctrl + Z", "Ctrl + Y",
        )
        page.add(grp_nav)
        self._tab_groups[tab_id].append((grp_nav, rows_nav))

        # Group 2: Page Operations & Setup
        grp_pages = Adw.PreferencesGroup()
        grp_pages.set_title(_esc(_("guide_grp_pages")))
        rows_pages: list[dict] = []

        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_pages_sidebar_title", "guide_pages_sidebar_desc",
            "view-grid-symbolic",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_pages_actions_title", "guide_pages_actions_desc",
            "view-refresh-symbolic",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_pages_new_doc_title", "guide_pages_new_doc_desc",
            "document-new-symbolic", "Ctrl + N",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_rotate_title", "guide_rotate_desc",
            "object-rotate-right-symbolic", "Ctrl + Shift + R", "Ctrl + Shift + L",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_tabs_title", "guide_tabs_desc",
            "tab-new-symbolic", "Ctrl + W", "Ctrl + Tab",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_merge_title", "guide_merge_desc",
            "edit-copy-symbolic", "Ctrl + Shift + M",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_split_title", "guide_split_desc",
            "edit-cut-symbolic",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_compress_title", "guide_compress_desc",
            "package-x-generic-symbolic",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_headers_watermarks_title", "guide_headers_watermarks_desc",
            "view-paged-symbolic",
        )
        self._add_feature_row(
            tab_id, grp_pages, rows_pages,
            "guide_export_title", "guide_export_desc",
            "document-save-as-symbolic",
        )
        page.add(grp_pages)
        self._tab_groups[tab_id].append((grp_pages, rows_pages))

        stack_page = self.view_stack.add_titled(page, tab_id, _("guide_tab_canvas"))
        stack_page.set_icon_name("view-paged-symbolic")

    def _build_security_ocr_page(self):
        """Page 3: OCR Text Recognition, Digital Signatures, Redaction & Encryption."""
        page = Adw.PreferencesPage()
        tab_id = "security_ocr"

        # Group 1: Optical Character Recognition (OCR)
        grp_ocr = Adw.PreferencesGroup()
        grp_ocr.set_title(_esc(_("guide_grp_ocr")))
        rows_ocr: list[dict] = []

        self._add_feature_row(
            tab_id, grp_ocr, rows_ocr,
            "guide_ocr_streaming_title", "guide_ocr_streaming_desc",
            "document-properties-symbolic", "Ctrl + Shift + O",
        )
        self._add_feature_row(
            tab_id, grp_ocr, rows_ocr,
            "guide_ocr_region_title", "guide_ocr_region_desc",
            "edit-select-all-symbolic", "O", "Ctrl + Alt + O",
        )
        self._add_feature_row(
            tab_id, grp_ocr, rows_ocr,
            "guide_ocr_languages_title", "guide_ocr_languages_desc",
            "preferences-desktop-locale-symbolic",
        )
        page.add(grp_ocr)
        self._tab_groups[tab_id].append((grp_ocr, rows_ocr))

        # Group 2: Digital Signatures, Redaction & Encryption
        grp_sec = Adw.PreferencesGroup()
        grp_sec.set_title(_esc(_("guide_grp_security")))
        rows_sec: list[dict] = []

        self._add_feature_row(
            tab_id, grp_sec, rows_sec,
            "guide_sec_signatures_title", "guide_sec_signatures_desc",
            "security-high-symbolic", "G",
        )
        self._add_feature_row(
            tab_id, grp_sec, rows_sec,
            "guide_sec_redaction_title", "guide_sec_redaction_desc",
            "edit-clear-all-symbolic", "Shift + R",
        )
        self._add_feature_row(
            tab_id, grp_sec, rows_sec,
            "guide_sec_encryption_title", "guide_sec_encryption_desc",
            "dialog-password-symbolic",
        )
        page.add(grp_sec)
        self._tab_groups[tab_id].append((grp_sec, rows_sec))

        stack_page = self.view_stack.add_titled(page, tab_id, _("guide_tab_security_ocr"))
        stack_page.set_icon_name("security-high-symbolic")

    def _build_shortcuts_page(self):
        """Page 4: Keyboard Shortcuts Cheatsheet."""
        page = Adw.PreferencesPage()
        tab_id = "shortcuts"

        # Group 1: File & Document
        grp_doc = Adw.PreferencesGroup()
        grp_doc.set_title(_esc(_("guide_grp_shortcuts_doc")))
        rows_doc: list[dict] = []
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_new"), "Ctrl + N")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_open"), "Ctrl + O")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_save"), "Ctrl + S")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_save_as"), "Ctrl + Shift + S")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_print"), "Ctrl + P")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_find"), "Ctrl + F")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_replace"), "Ctrl + H")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_ocr"), "Ctrl + Shift + O")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_merge"), "Ctrl + Shift + M")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_close_tab"), "Ctrl + W")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_next_tab"), "Ctrl + Tab", "Ctrl + PgDn")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_prev_tab"), "Ctrl + Shift + Tab", "Ctrl + PgUp")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_quick_guide"), "F1")
        self._add_shortcut_row(tab_id, grp_doc, rows_doc, _("guide_sc_quit"), "Ctrl + Q")
        page.add(grp_doc)
        self._tab_groups[tab_id].append((grp_doc, rows_doc))

        # Group 2: Editing & Canvas
        grp_edit = Adw.PreferencesGroup()
        grp_edit.set_title(_esc(_("guide_grp_shortcuts_edit")))
        rows_edit: list[dict] = []
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_undo"), "Ctrl + Z")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_redo"), "Ctrl + Y", "Ctrl + Shift + Z")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_copy_paste_dup"), "Ctrl + C", "Ctrl + V", "Ctrl + D")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_rotate_cw"), "Ctrl + Shift + R")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_rotate_ccw"), "Ctrl + Shift + L")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_zoom_in"), "Ctrl + +")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_zoom_out"), "Ctrl + -")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_zoom_reset"), "Ctrl + 0")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_zoom_scroll"), "Ctrl + Scroll")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_delete"), "Delete")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_deselect"), "Esc")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_type_over_patch"), "Enter", "T")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_layer_front"), "Ctrl + Shift + ]")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_layer_forward"), "Ctrl + ]")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_layer_backward"), "Ctrl + [")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_layer_back"), "Ctrl + Shift + [")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_nudge"), "Arrow Keys")
        self._add_shortcut_row(tab_id, grp_edit, rows_edit, _("guide_sc_nudge_fast"), "Shift + Arrow Keys")
        page.add(grp_edit)
        self._tab_groups[tab_id].append((grp_edit, rows_edit))

        # Group 3: Tool Hotkeys
        grp_tools = Adw.PreferencesGroup()
        grp_tools.set_title(_esc(_("guide_grp_shortcuts_tools")))
        rows_tools: list[dict] = []
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_select"), "S")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_text"), "T")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_pen"), "P")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_highlighter"), "H")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_rect"), "R")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_ellipse"), "E")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_clone_patch"), "C")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_redact"), "Shift + R")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_check"), "V")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_cross"), "X")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_image"), "I")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_stamp"), "K")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_note"), "N")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_ruler"), "U")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_area"), "A")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_signature"), "G")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_ocr_region"), "O")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_form_builder"), "B")
        self._add_shortcut_row(tab_id, grp_tools, rows_tools, _("guide_sc_tool_drag"), "M")
        page.add(grp_tools)
        self._tab_groups[tab_id].append((grp_tools, rows_tools))

        stack_page = self.view_stack.add_titled(page, tab_id, _("guide_tab_shortcuts"))
        stack_page.set_icon_name("input-keyboard-symbolic")
