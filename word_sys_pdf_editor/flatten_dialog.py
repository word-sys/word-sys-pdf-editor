import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw
from .i18n import _


class FlattenDialog(Adw.Window):
    """Modern Libadwaita modal dialog for annotation flattening options."""

    def __init__(self, parent_window, current_page: int = 0, total_pages: int = 1, on_confirm_callback=None):
        super().__init__()
        self.parent_window = parent_window
        self.current_page = current_page
        self.total_pages = total_pages
        self.on_confirm_callback = on_confirm_callback

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("flatten_dialog_title"))
        self.set_default_size(500, 440)
        self.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header Bar
        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(self.cancel_btn)

        self.confirm_btn = Gtk.Button(label=_("flatten_btn_confirm"))
        self.confirm_btn.add_css_class("suggested-action")
        self.confirm_btn.connect("clicked", self._on_confirm_clicked)
        header.pack_end(self.confirm_btn)
        main_box.append(header)

        # Scrolled container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=460)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(content_box)

        # Informational Description Card
        info_group = Adw.PreferencesGroup()
        info_row = Adw.ActionRow()
        info_row.set_title(_("flatten_dialog_title"))
        info_row.set_subtitle(_("flatten_intro"))
        info_row.set_subtitle_lines(0)
        info_icon = Gtk.Image.new_from_icon_name("document-edit-symbolic")
        info_row.add_prefix(info_icon)
        info_group.add(info_row)
        content_box.append(info_group)

        # Scope Group
        scope_group = Adw.PreferencesGroup()
        scope_group.set_title(_("flatten_scope_title"))
        content_box.append(scope_group)

        # Scope Radio Rows
        self.scope_page_check = Gtk.CheckButton()
        self.scope_page_row = Adw.ActionRow(title=_("flatten_scope_page"))
        self.scope_page_row.add_prefix(self.scope_page_check)
        self.scope_page_row.set_activatable_widget(self.scope_page_check)
        scope_group.add(self.scope_page_row)

        self.scope_all_check = Gtk.CheckButton()
        self.scope_all_check.set_group(self.scope_page_check)
        self.scope_all_row = Adw.ActionRow(title=_("flatten_scope_all"))
        self.scope_all_row.add_prefix(self.scope_all_check)
        self.scope_all_row.set_activatable_widget(self.scope_all_check)
        scope_group.add(self.scope_all_row)

        # Default scope: current page if multi-page, or all
        self.scope_page_check.set_active(True)

        # Options Group
        options_group = Adw.PreferencesGroup()
        options_group.set_title(_("flatten_options_title"))
        content_box.append(options_group)

        self.forms_switch = Gtk.Switch()
        self.forms_switch.set_valign(Gtk.Align.CENTER)
        self.forms_switch.set_active(False)

        self.forms_row = Adw.ActionRow(
            title=_("flatten_include_forms"),
            subtitle=_("flatten_include_forms_desc"),
        )
        self.forms_row.add_suffix(self.forms_switch)
        self.forms_row.set_activatable_widget(self.forms_switch)
        options_group.add(self.forms_row)

        # Sticky Notes Stay Live Notice Card
        notes_group = Adw.PreferencesGroup()
        notes_row = Adw.ActionRow()
        notes_row.set_subtitle(_("flatten_notes_stay_live"))
        notes_row.set_subtitle_lines(0)
        note_icon = Gtk.Image.new_from_icon_name("user-bookmarks-symbolic")
        notes_row.add_prefix(note_icon)
        notes_group.add(notes_row)
        content_box.append(notes_group)

    def _on_confirm_clicked(self, _button):
        scope = "all" if self.scope_all_check.get_active() else "page"
        include_forms = bool(self.forms_switch.get_active())
        if self.on_confirm_callback:
            self.on_confirm_callback(scope=scope, include_forms=include_forms)
        self.destroy()
