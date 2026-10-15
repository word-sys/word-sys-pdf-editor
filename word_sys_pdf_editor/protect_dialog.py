import os
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
from typing import Optional, Callable, Dict, Any

from .i18n import _


class DocumentUnlockDialog(Adw.Window):
    """Libadwaita modal dialog for entering password to unlock protected PDFs or word-sys Vaults."""

    def __init__(
        self,
        parent_window,
        filepath: str,
        is_vault: bool = False,
        on_unlock_callback: Optional[Callable[[str], None]] = None,
        on_cancel_callback: Optional[Callable[[], None]] = None
    ):
        super().__init__()
        self.parent_window = parent_window
        self.filepath = filepath
        self.is_vault = is_vault
        self.on_unlock_callback = on_unlock_callback
        self.on_cancel_callback = on_cancel_callback

        if parent_window:
            self.set_transient_for(parent_window)
            self.set_modal(True)

        title = _("unlock_vault_title") if is_vault else _("unlock_doc_title")
        self.set_title(title)
        self.set_default_size(440, 320)
        self.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # HeaderBar
        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", self._on_cancel_clicked)
        header.pack_start(self.cancel_btn)

        self.unlock_btn = Gtk.Button(label=_("unlock_btn"))
        self.unlock_btn.add_css_class("suggested-action")
        self.unlock_btn.connect("clicked", self._on_unlock_clicked)
        header.pack_end(self.unlock_btn)
        main_box.append(header)

        # Scrolled content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=400)
        clamp.set_margin_top(18)
        clamp.set_margin_bottom(18)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        clamp.set_child(content_box)

        # Info card
        info_group = Adw.PreferencesGroup()
        info_row = Adw.ActionRow()
        info_row.set_title(os.path.basename(filepath))
        desc = _("unlock_vault_desc") if is_vault else _("unlock_doc_desc")
        info_row.set_subtitle(desc)
        info_row.set_subtitle_lines(0)

        icon = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        icon.set_pixel_size(28)
        icon.add_css_class("accent")
        info_row.add_prefix(icon)
        info_group.add(info_row)
        content_box.append(info_group)

        # Input card
        input_group = Adw.PreferencesGroup()
        content_box.append(input_group)

        pw_row = Adw.ActionRow()
        pw_row.set_title(_("protect_user_pw"))
        self.pw_entry = Gtk.PasswordEntry()
        self.pw_entry.set_show_peek_icon(True)
        self.pw_entry.set_valign(Gtk.Align.CENTER)
        self.pw_entry.set_hexpand(True)
        self.pw_entry.connect("activate", lambda e: self._on_unlock_clicked(None))
        pw_row.add_suffix(self.pw_entry)
        input_group.add(pw_row)

        # Error label
        self.error_label = Gtk.Label()
        self.error_label.add_css_class("error")
        self.error_label.set_wrap(True)
        self.error_label.set_visible(False)
        content_box.append(self.error_label)

    def show_error(self, message: Optional[str] = None):
        """Display error feedback in the dialog."""
        msg = message or _("unlock_err_invalid")
        self.error_label.set_text(msg)
        self.error_label.set_visible(True)
        self.pw_entry.set_text("")
        self.pw_entry.grab_focus()

    def _on_unlock_clicked(self, btn):
        password = self.pw_entry.get_text()
        if not password:
            self.show_error(_("protect_pw_empty"))
            return
        if self.on_unlock_callback:
            self.on_unlock_callback(password)

    def _on_cancel_clicked(self, btn):
        if self.on_cancel_callback:
            self.on_cancel_callback()
        self.destroy()


class ProtectDocumentDialog(Adw.Window):
    """Modern Libadwaita modal dialog for applying Standard AES-256 PDF encryption or word-sys Exclusive Vault (.wspdf)."""

    def __init__(
        self,
        parent_window,
        on_protect_callback: Callable[[str, Dict[str, Any]], None]
    ):
        super().__init__()
        self.parent_window = parent_window
        self.on_protect_callback = on_protect_callback

        if parent_window:
            self.set_transient_for(parent_window)
            self.set_modal(True)

        self.set_title(_("protect_doc_title"))
        self.set_default_size(520, 600)
        self.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # HeaderBar
        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(self.cancel_btn)

        self.apply_btn = Gtk.Button(label=_("protect_apply_btn"))
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self._on_apply_clicked)
        header.pack_end(self.apply_btn)
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

        # Mode Selection
        mode_group = Adw.PreferencesGroup()
        content_box.append(mode_group)

        # Radio buttons for mode selection
        self.standard_radio = Gtk.CheckButton(label=_("protect_mode_standard"))
        self.standard_radio.set_active(True)
        self.standard_radio.connect("toggled", self._on_mode_toggled)

        self.vault_radio = Gtk.CheckButton(label=_("protect_mode_vault"))
        self.vault_radio.set_group(self.standard_radio)
        self.vault_radio.connect("toggled", self._on_mode_toggled)

        mode_row_std = Adw.ActionRow()
        mode_row_std.set_title(_("protect_mode_standard"))
        mode_row_std.set_subtitle(_("protect_mode_standard_desc"))
        mode_row_std.set_subtitle_lines(0)
        mode_row_std.add_prefix(self.standard_radio)
        mode_row_std.set_activatable_widget(self.standard_radio)
        mode_group.add(mode_row_std)

        mode_row_vault = Adw.ActionRow()
        mode_row_vault.set_title(_("protect_mode_vault"))
        mode_row_vault.set_subtitle(_("protect_mode_vault_desc"))
        mode_row_vault.set_subtitle_lines(0)
        mode_row_vault.add_prefix(self.vault_radio)
        mode_row_vault.set_activatable_widget(self.vault_radio)
        mode_group.add(mode_row_vault)

        # Stack for Mode Views
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        content_box.append(self.stack)

        # --- Standard Mode View ---
        std_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.stack.add_named(std_box, "standard")

        std_pw_group = Adw.PreferencesGroup()
        std_box.append(std_pw_group)

        std_user_row = Adw.ActionRow()
        std_user_row.set_title(_("protect_user_pw"))
        self.std_user_entry = Gtk.PasswordEntry()
        self.std_user_entry.set_show_peek_icon(True)
        self.std_user_entry.set_valign(Gtk.Align.CENTER)
        self.std_user_entry.set_hexpand(True)
        std_user_row.add_suffix(self.std_user_entry)
        std_pw_group.add(std_user_row)

        std_confirm_row = Adw.ActionRow()
        std_confirm_row.set_title(_("protect_confirm_pw"))
        self.std_confirm_entry = Gtk.PasswordEntry()
        self.std_confirm_entry.set_show_peek_icon(True)
        self.std_confirm_entry.set_valign(Gtk.Align.CENTER)
        self.std_confirm_entry.set_hexpand(True)
        std_confirm_row.add_suffix(self.std_confirm_entry)
        std_pw_group.add(std_confirm_row)

        std_owner_row = Adw.ActionRow()
        std_owner_row.set_title(_("protect_owner_pw"))
        self.std_owner_entry = Gtk.PasswordEntry()
        self.std_owner_entry.set_show_peek_icon(True)
        self.std_owner_entry.set_valign(Gtk.Align.CENTER)
        self.std_owner_entry.set_hexpand(True)
        std_owner_row.add_suffix(self.std_owner_entry)
        std_pw_group.add(std_owner_row)

        # Permissions Group
        perm_group = Adw.PreferencesGroup(title=_("protect_perm_header"))
        std_box.append(perm_group)

        self.perm_print_row = self._create_switch_row(_("protect_perm_print"), True)
        perm_group.add(self.perm_print_row)

        self.perm_copy_row = self._create_switch_row(_("protect_perm_copy"), False)
        perm_group.add(self.perm_copy_row)

        self.perm_annotate_row = self._create_switch_row(_("protect_perm_annotate"), True)
        perm_group.add(self.perm_annotate_row)

        self.perm_modify_row = self._create_switch_row(_("protect_perm_modify"), False)
        perm_group.add(self.perm_modify_row)

        self.perm_form_row = self._create_switch_row(_("protect_perm_form"), True)
        perm_group.add(self.perm_form_row)

        # --- Vault Mode View ---
        vault_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.stack.add_named(vault_box, "vault")

        vault_pw_group = Adw.PreferencesGroup()
        vault_box.append(vault_pw_group)

        vault_user_row = Adw.ActionRow()
        vault_user_row.set_title(_("protect_user_pw"))
        self.vault_entry = Gtk.PasswordEntry()
        self.vault_entry.set_show_peek_icon(True)
        self.vault_entry.set_valign(Gtk.Align.CENTER)
        self.vault_entry.set_hexpand(True)
        vault_user_row.add_suffix(self.vault_entry)
        vault_pw_group.add(vault_user_row)

        vault_confirm_row = Adw.ActionRow()
        vault_confirm_row.set_title(_("protect_confirm_pw"))
        self.vault_confirm_entry = Gtk.PasswordEntry()
        self.vault_confirm_entry.set_show_peek_icon(True)
        self.vault_confirm_entry.set_valign(Gtk.Align.CENTER)
        self.vault_confirm_entry.set_hexpand(True)
        vault_confirm_row.add_suffix(self.vault_confirm_entry)
        vault_pw_group.add(vault_confirm_row)

        # Error label
        self.error_label = Gtk.Label()
        self.error_label.add_css_class("error")
        self.error_label.set_wrap(True)
        self.error_label.set_visible(False)
        content_box.append(self.error_label)

    def _on_mode_toggled(self, btn):
        if self.standard_radio.get_active():
            self.stack.set_visible_child_name("standard")
        else:
            self.stack.set_visible_child_name("vault")
        self.error_label.set_visible(False)

    def _create_switch_row(self, title: str, default_active: bool = True):
        row = Adw.ActionRow(title=title)
        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        switch.set_active(default_active)
        row.add_suffix(switch)
        row.set_activatable_widget(switch)
        row.get_active = switch.get_active
        row.set_active = switch.set_active
        return row

    def _show_error(self, message: str):
        self.error_label.set_text(message)
        self.error_label.set_visible(True)

    def _on_apply_clicked(self, btn):
        is_standard = self.standard_radio.get_active()

        if is_standard:
            user_pw = self.std_user_entry.get_text()
            confirm_pw = self.std_confirm_entry.get_text()
            owner_pw = self.std_owner_entry.get_text()

            if not user_pw:
                self._show_error(_("protect_pw_empty"))
                return
            if len(user_pw) < 4:
                self._show_error(_("protect_pw_too_short"))
                return
            if user_pw != confirm_pw:
                self._show_error(_("protect_pw_mismatch"))
                return

            settings = {
                "user_pw": user_pw,
                "owner_pw": owner_pw or user_pw,
                "allow_print": self.perm_print_row.get_active(),
                "allow_copy": self.perm_copy_row.get_active(),
                "allow_annotate": self.perm_annotate_row.get_active(),
                "allow_modify": self.perm_modify_row.get_active(),
                "allow_form_fill": self.perm_form_row.get_active(),
            }
            mode = "standard"
        else:
            vault_pw = self.vault_entry.get_text()
            vault_confirm = self.vault_confirm_entry.get_text()

            if not vault_pw:
                self._show_error(_("protect_pw_empty"))
                return
            if len(vault_pw) < 4:
                self._show_error(_("protect_pw_too_short"))
                return
            if vault_pw != vault_confirm:
                self._show_error(_("protect_pw_mismatch"))
                return

            settings = {
                "password": vault_pw,
            }
            mode = "vault"

        self.destroy()
        if self.on_protect_callback:
            self.on_protect_callback(mode, settings)
