import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw, GLib
from .i18n import _

GUIDE_CSS = b"""
.keycap {
    background-color: alpha(currentColor, 0.08);
    border: 1px solid alpha(currentColor, 0.16);
    border-radius: 6px;
    padding: 3px 8px;
    font-family: monospace;
    font-weight: 600;
    font-size: 0.85em;
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
    """Modern Libadwaita interactive user guide and shortcut manual."""

    def __init__(self, parent_window):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("guide_dialog_title"))
        self.set_default_size(720, 600)
        self.set_resizable(True)

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

        main_box.append(header)
        main_box.append(self.view_stack)

        self._build_tools_page()
        self._build_canvas_page()
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

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Allow closing the guide with the Escape key."""
        if keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False

    def _build_tools_page(self):
        """Page 1: Tools & Editing features."""
        page = Adw.PreferencesPage()

        # Group 1: Selection & Typography
        grp_text = Adw.PreferencesGroup()
        grp_text.set_title(_esc(_("guide_grp_selection_text")))

        row_sel = Adw.ActionRow()
        row_sel.set_title(_esc(_("guide_tool_select_title")))
        row_sel.set_subtitle(_esc(_("guide_tool_select_desc")))
        row_sel.set_subtitle_lines(0)
        row_sel.add_prefix(Gtk.Image.new_from_icon_name("input-mouse-symbolic"))
        row_sel.add_suffix(make_keycap("S"))
        grp_text.add(row_sel)

        row_txt = Adw.ActionRow()
        row_txt.set_title(_esc(_("guide_tool_text_title")))
        row_txt.set_subtitle(_esc(_("guide_tool_text_desc")))
        row_txt.set_subtitle_lines(0)
        row_txt.add_prefix(Gtk.Image.new_from_icon_name("insert-text-symbolic"))
        row_txt.add_suffix(make_keycap("T"))
        grp_text.add(row_txt)

        row_drag = Adw.ActionRow()
        row_drag.set_title(_esc(_("guide_tool_drag_title")))
        row_drag.set_subtitle(_esc(_("guide_tool_drag_desc")))
        row_drag.set_subtitle_lines(0)
        row_drag.add_prefix(Gtk.Image.new_from_icon_name("drag-handle-symbolic"))
        row_drag.add_suffix(make_keycap("M"))
        grp_text.add(row_drag)

        page.add(grp_text)

        # Group 2: Freehand Drawing & Vector Shapes
        grp_shapes = Adw.PreferencesGroup()
        grp_shapes.set_title(_esc(_("guide_grp_drawing_shapes")))

        row_pen = Adw.ActionRow()
        row_pen.set_title(_esc(_("guide_tool_pen_title")))
        row_pen.set_subtitle(_esc(_("guide_tool_pen_desc")))
        row_pen.set_subtitle_lines(0)
        row_pen.add_prefix(Gtk.Image.new_from_icon_name("document-edit-symbolic"))
        row_pen.add_suffix(make_keycap("P"))
        grp_shapes.add(row_pen)

        row_hl = Adw.ActionRow()
        row_hl.set_title(_esc(_("guide_tool_highlighter_title")))
        row_hl.set_subtitle(_esc(_("guide_tool_highlighter_desc")))
        row_hl.set_subtitle_lines(0)
        row_hl.add_prefix(Gtk.Image.new_from_icon_name("marker-symbolic"))
        row_hl.add_suffix(make_keycap("H"))
        grp_shapes.add(row_hl)

        row_shapes = Adw.ActionRow()
        row_shapes.set_title(_esc(_("guide_tool_shapes_title")))
        row_shapes.set_subtitle(_esc(_("guide_tool_shapes_desc")))
        row_shapes.set_subtitle_lines(0)
        row_shapes.add_prefix(Gtk.Image.new_from_icon_name("checkbox-symbolic"))
        row_shapes.add_suffix(make_keycap_box("R", "C"))
        grp_shapes.add(row_shapes)

        row_mark = Adw.ActionRow()
        row_mark.set_title(_esc(_("guide_tool_markers_title")))
        row_mark.set_subtitle(_esc(_("guide_tool_markers_desc")))
        row_mark.set_subtitle_lines(0)
        row_mark.add_prefix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
        row_mark.add_suffix(make_keycap_box("V", "X"))
        grp_shapes.add(row_mark)

        row_img = Adw.ActionRow()
        row_img.set_title(_esc(_("guide_tool_image_title")))
        row_img.set_subtitle(_esc(_("guide_tool_image_desc")))
        row_img.set_subtitle_lines(0)
        row_img.add_prefix(Gtk.Image.new_from_icon_name("insert-image-symbolic"))
        row_img.add_suffix(make_keycap("I"))
        grp_shapes.add(row_img)

        page.add(grp_shapes)

        stack_page = self.view_stack.add_titled(page, "tools", _("guide_tab_tools"))
        stack_page.set_icon_name("document-edit-symbolic")

    def _build_canvas_page(self):
        """Page 2: Canvas Navigation & Page Management."""
        page = Adw.PreferencesPage()

        # Group 1: Navigation & History
        grp_nav = Adw.PreferencesGroup()
        grp_nav.set_title(_esc(_("guide_grp_navigation")))

        row_zoom = Adw.ActionRow()
        row_zoom.set_title(_esc(_("guide_nav_focal_zoom_title")))
        row_zoom.set_subtitle(_esc(_("guide_nav_focal_zoom_desc")))
        row_zoom.set_subtitle_lines(0)
        row_zoom.add_prefix(Gtk.Image.new_from_icon_name("zoom-in-symbolic"))
        row_zoom.add_suffix(make_keycap("Ctrl + Scroll"))
        grp_nav.add(row_zoom)

        row_undo = Adw.ActionRow()
        row_undo.set_title(_esc(_("guide_nav_undo_title")))
        row_undo.set_subtitle(_esc(_("guide_nav_undo_desc")))
        row_undo.set_subtitle_lines(0)
        row_undo.add_prefix(Gtk.Image.new_from_icon_name("edit-undo-symbolic"))
        row_undo.add_suffix(make_keycap_box("Ctrl + Z", "Ctrl + Y"))
        grp_nav.add(row_undo)

        page.add(grp_nav)

        # Group 2: Page Operations & Setup
        grp_pages = Adw.PreferencesGroup()
        grp_pages.set_title(_esc(_("guide_grp_pages")))

        row_sidebar = Adw.ActionRow()
        row_sidebar.set_title(_esc(_("guide_pages_sidebar_title")))
        row_sidebar.set_subtitle(_esc(_("guide_pages_sidebar_desc")))
        row_sidebar.set_subtitle_lines(0)
        row_sidebar.add_prefix(Gtk.Image.new_from_icon_name("view-grid-symbolic"))
        grp_pages.add(row_sidebar)

        row_actions = Adw.ActionRow()
        row_actions.set_title(_esc(_("guide_pages_actions_title")))
        row_actions.set_subtitle(_esc(_("guide_pages_actions_desc")))
        row_actions.set_subtitle_lines(0)
        row_actions.add_prefix(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        grp_pages.add(row_actions)

        row_new_doc = Adw.ActionRow()
        row_new_doc.set_title(_esc(_("guide_pages_new_doc_title")))
        row_new_doc.set_subtitle(_esc(_("guide_pages_new_doc_desc")))
        row_new_doc.set_subtitle_lines(0)
        row_new_doc.add_prefix(Gtk.Image.new_from_icon_name("document-new-symbolic"))
        row_new_doc.add_suffix(make_keycap("Ctrl + N"))
        grp_pages.add(row_new_doc)

        page.add(grp_pages)

        stack_page = self.view_stack.add_titled(page, "canvas", _("guide_tab_canvas"))
        stack_page.set_icon_name("view-paged-symbolic")

    def _build_shortcuts_page(self):
        """Page 3: Keyboard Shortcuts Cheatsheet."""
        page = Adw.PreferencesPage()

        def add_shortcut_row(group, title_text, *keys):
            row = Adw.ActionRow()
            row.set_title(_esc(title_text))
            row.add_suffix(make_keycap_box(*keys))
            group.add(row)

        # Group 1: File & Document
        grp_doc = Adw.PreferencesGroup()
        grp_doc.set_title(_esc(_("guide_grp_shortcuts_doc")))
        add_shortcut_row(grp_doc, _("guide_sc_new"), "Ctrl + N")
        add_shortcut_row(grp_doc, _("guide_sc_open"), "Ctrl + O")
        add_shortcut_row(grp_doc, _("guide_sc_save"), "Ctrl + S")
        add_shortcut_row(grp_doc, _("guide_sc_save_as"), "Ctrl + Shift + S")
        add_shortcut_row(grp_doc, _("guide_sc_print"), "Ctrl + P")
        add_shortcut_row(grp_doc, _("guide_sc_quit"), "Ctrl + Q")
        page.add(grp_doc)

        # Group 2: Editing & Canvas
        grp_edit = Adw.PreferencesGroup()
        grp_edit.set_title(_esc(_("guide_grp_shortcuts_edit")))
        add_shortcut_row(grp_edit, _("guide_sc_undo"), "Ctrl + Z")
        add_shortcut_row(grp_edit, _("guide_sc_redo"), "Ctrl + Y", "Ctrl + Shift + Z")
        add_shortcut_row(grp_edit, _("guide_sc_zoom_in"), "Ctrl + +")
        add_shortcut_row(grp_edit, _("guide_sc_zoom_out"), "Ctrl + -")
        add_shortcut_row(grp_edit, _("guide_sc_zoom_reset"), "Ctrl + 0")
        add_shortcut_row(grp_edit, _("guide_sc_zoom_scroll"), "Ctrl + Scroll")
        add_shortcut_row(grp_edit, _("guide_sc_delete"), "Delete")
        add_shortcut_row(grp_edit, _("guide_sc_deselect"), "Esc")
        add_shortcut_row(grp_edit, _("guide_sc_nudge"), "Arrow Keys")
        add_shortcut_row(grp_edit, _("guide_sc_nudge_fast"), "Shift + Arrow Keys")
        page.add(grp_edit)

        # Group 3: Tool Hotkeys
        grp_tools = Adw.PreferencesGroup()
        grp_tools.set_title(_esc(_("guide_grp_shortcuts_tools")))
        add_shortcut_row(grp_tools, _("guide_sc_tool_select"), "S")
        add_shortcut_row(grp_tools, _("guide_sc_tool_text"), "T")
        add_shortcut_row(grp_tools, _("guide_sc_tool_pen"), "P")
        add_shortcut_row(grp_tools, _("guide_sc_tool_highlighter"), "H")
        add_shortcut_row(grp_tools, _("guide_sc_tool_rect"), "R")
        add_shortcut_row(grp_tools, _("guide_sc_tool_ellipse"), "C")
        add_shortcut_row(grp_tools, _("guide_sc_tool_check"), "V")
        add_shortcut_row(grp_tools, _("guide_sc_tool_cross"), "X")
        add_shortcut_row(grp_tools, _("guide_sc_tool_image"), "I")
        add_shortcut_row(grp_tools, _("guide_sc_tool_drag"), "M")
        page.add(grp_tools)

        stack_page = self.view_stack.add_titled(page, "shortcuts", _("guide_tab_shortcuts"))
        stack_page.set_icon_name("input-keyboard-symbolic")
