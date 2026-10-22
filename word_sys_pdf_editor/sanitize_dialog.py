import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
from .i18n import _


def _safe_markup(text: str) -> str:
    """Escapes string for safe Pango markup rendering in Adwaita ActionRows and PreferencesGroups."""
    return GLib.markup_escape_text(text) if text else ""


class SanitizeDialog(Adw.Window):
    """Modern Libadwaita modal dialog for document sanitization options."""

    def __init__(self, parent_window, on_confirm_callback=None):
        super().__init__()
        self.parent_window = parent_window
        self.on_confirm_callback = on_confirm_callback

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_safe_markup(_("sanitize_dialog_title")))
        self.set_default_size(520, 560)
        self.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header Bar
        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(self.cancel_btn)

        self.confirm_btn = Gtk.Button(label=_("sanitize_btn_confirm"))
        self.confirm_btn.add_css_class("destructive-action")
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

        # Informational Description Card
        info_group = Adw.PreferencesGroup()
        info_row = Adw.ActionRow()
        info_row.set_title(_safe_markup(_("sanitize_dialog_title")))
        info_row.set_subtitle(_safe_markup(_("sanitize_intro")))
        info_row.set_subtitle_lines(0)
        info_icon = Gtk.Image.new_from_icon_name("security-high-symbolic")
        info_row.add_prefix(info_icon)
        info_group.add(info_row)
        content_box.append(info_group)

        # Sanitization Options Group
        options_group = Adw.PreferencesGroup()
        options_group.set_title(_safe_markup(_("sanitize_options_title")))
        content_box.append(options_group)

        # 1. Metadata switch
        self.metadata_switch = Gtk.Switch()
        self.metadata_switch.set_valign(Gtk.Align.CENTER)
        self.metadata_switch.set_active(True)
        self.metadata_row = Adw.ActionRow(
            title=_safe_markup(_("sanitize_opt_metadata")),
            subtitle=_safe_markup(_("sanitize_opt_metadata_desc")),
        )
        self.metadata_row.add_suffix(self.metadata_switch)
        self.metadata_row.set_activatable_widget(self.metadata_switch)
        options_group.add(self.metadata_row)

        # 2. XMP switch
        self.xmp_switch = Gtk.Switch()
        self.xmp_switch.set_valign(Gtk.Align.CENTER)
        self.xmp_switch.set_active(True)
        self.xmp_row = Adw.ActionRow(
            title=_safe_markup(_("sanitize_opt_xmp")),
            subtitle=_safe_markup(_("sanitize_opt_xmp_desc")),
        )
        self.xmp_row.add_suffix(self.xmp_switch)
        self.xmp_row.set_activatable_widget(self.xmp_switch)
        options_group.add(self.xmp_row)

        # 3. Attachments switch
        self.attachments_switch = Gtk.Switch()
        self.attachments_switch.set_valign(Gtk.Align.CENTER)
        self.attachments_switch.set_active(True)
        self.attachments_row = Adw.ActionRow(
            title=_safe_markup(_("sanitize_opt_attachments")),
            subtitle=_safe_markup(_("sanitize_opt_attachments_desc")),
        )
        self.attachments_row.add_suffix(self.attachments_switch)
        self.attachments_row.set_activatable_widget(self.attachments_switch)
        options_group.add(self.attachments_row)

        # 4. Hidden Layers switch
        self.hidden_layers_switch = Gtk.Switch()
        self.hidden_layers_switch.set_valign(Gtk.Align.CENTER)
        self.hidden_layers_switch.set_active(True)
        self.hidden_layers_row = Adw.ActionRow(
            title=_safe_markup(_("sanitize_opt_hidden_layers")),
            subtitle=_safe_markup(_("sanitize_opt_hidden_layers_desc")),
        )
        self.hidden_layers_row.add_suffix(self.hidden_layers_switch)
        self.hidden_layers_row.set_activatable_widget(self.hidden_layers_switch)
        options_group.add(self.hidden_layers_row)

        # 5. Comments & Markup switch
        self.comments_switch = Gtk.Switch()
        self.comments_switch.set_valign(Gtk.Align.CENTER)
        self.comments_switch.set_active(True)
        self.comments_row = Adw.ActionRow(
            title=_safe_markup(_("sanitize_opt_comments")),
            subtitle=_safe_markup(_("sanitize_opt_comments_desc")),
        )
        self.comments_row.add_suffix(self.comments_switch)
        self.comments_row.set_activatable_widget(self.comments_switch)
        options_group.add(self.comments_row)

        # 6. Orphaned / Redacted Bookmarks switch
        self.orphaned_toc_switch = Gtk.Switch()
        self.orphaned_toc_switch.set_valign(Gtk.Align.CENTER)
        self.orphaned_toc_switch.set_active(True)
        self.orphaned_toc_row = Adw.ActionRow(
            title=_safe_markup(_("sanitize_opt_orphaned_toc")),
            subtitle=_safe_markup(_("sanitize_opt_orphaned_toc_desc")),
        )
        self.orphaned_toc_row.add_suffix(self.orphaned_toc_switch)
        self.orphaned_toc_row.set_activatable_widget(self.orphaned_toc_switch)
        options_group.add(self.orphaned_toc_row)

        # 7. Strip all bookmarks switch
        self.strip_bookmarks_switch = Gtk.Switch()
        self.strip_bookmarks_switch.set_valign(Gtk.Align.CENTER)
        self.strip_bookmarks_switch.set_active(False)
        self.strip_bookmarks_row = Adw.ActionRow(
            title=_safe_markup(_("sanitize_opt_strip_bookmarks")),
            subtitle=_safe_markup(_("sanitize_opt_strip_bookmarks_desc")),
        )
        self.strip_bookmarks_row.add_suffix(self.strip_bookmarks_switch)
        self.strip_bookmarks_row.set_activatable_widget(self.strip_bookmarks_switch)
        options_group.add(self.strip_bookmarks_row)

    def _on_confirm_clicked(self, _button):
        options = {
            "strip_metadata": bool(self.metadata_switch.get_active()),
            "purge_xmp": bool(self.xmp_switch.get_active()),
            "purge_attachments": bool(self.attachments_switch.get_active()),
            "purge_hidden_layers": bool(self.hidden_layers_switch.get_active()),
            "purge_comments": bool(self.comments_switch.get_active()),
            "purge_orphaned_toc": bool(self.orphaned_toc_switch.get_active()),
            "strip_bookmarks": bool(self.strip_bookmarks_switch.get_active()),
        }
        if self.on_confirm_callback:
            self.on_confirm_callback(options)
        self.destroy()
