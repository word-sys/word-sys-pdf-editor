from __future__ import annotations

import os
from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from .i18n import _
from .ui_components import show_open_file_dialog, show_confirm_dialog
from .trust_manager import (
    is_trust_manager_available,
    list_custom_trusted_roots,
    import_trusted_root,
    remove_custom_trusted_root,
    get_all_trust_roots,
)


class TrustStoreDialog(Adw.Window):
    """Libadwaita dialog for managing custom enterprise and national root certificates."""

    def __init__(self, parent_window=None):
        super().__init__()
        self.parent_window = parent_window

        if parent_window:
            self.set_transient_for(parent_window)
            self.set_modal(True)

        self.set_title(_("trust_dialog_title") if "_" in dir() else "Certificate Trust Store")
        self.set_default_size(580, 620)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # HeaderBar
        header = Adw.HeaderBar()
        import_btn = Gtk.Button(label=_("trust_btn_import") if "_" in dir() else "Import Certificate")
        import_btn.add_css_class("suggested-action")
        import_btn.connect("clicked", self._on_import_clicked)
        header.pack_end(import_btn)
        main_box.append(header)

        # Scrolled Window
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

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(self.content_box)

        self._refresh_content()

    def _refresh_content(self):
        """Rebuild the content groups listing global and custom trusted roots."""
        # Clear previous children
        while child := self.content_box.get_first_child():
            self.content_box.remove(child)

        # 1. Global Trust Anchors Group
        global_group = Adw.PreferencesGroup()
        global_group.set_title(_("trust_group_global_title") if "_" in dir() else "Global Trust Anchors")
        global_group.set_description(
            _("trust_group_global_desc") if "_" in dir() else
            "Anchored to Mozilla / certifi bundle and OS system trust store (AATL & EUTL compatible)."
        )
        self.content_box.append(global_group)

        global_row = Adw.ActionRow()
        icon = Gtk.Image.new_from_icon_name("security-high-symbolic")
        icon.add_css_class("success")
        global_row.add_prefix(icon)
        all_roots = get_all_trust_roots() if is_trust_manager_available() else []
        custom_roots = list_custom_trusted_roots() if is_trust_manager_available() else []
        global_count = max(0, len(all_roots) - len(custom_roots))
        global_row.set_title(
            _("trust_global_status_title", global_count) if "_" in dir() else
            f"{global_count} Pre-installed Global Root Certificates Active"
        )
        global_row.set_subtitle(
            _("trust_global_status_subtitle") if "_" in dir() else
            "Commercial and qualified e-signatures (DigiCert, GlobalSign, Sectigo, etc.) validate automatically."
        )
        global_row.set_subtitle_lines(0)
        global_group.add(global_row)

        # 2. Custom Enterprise / National Roots Group
        custom_group = Adw.PreferencesGroup()
        custom_group.set_title(_("trust_group_custom_title") if "_" in dir() else "Custom Enterprise & National Roots")
        custom_group.set_description(
            _("trust_group_custom_desc") if "_" in dir() else
            "User-installed root CAs (TÜBİTAK Kamu SM, government PKIs, internal company authorities)."
        )
        self.content_box.append(custom_group)

        if not custom_roots:
            empty_row = Adw.ActionRow()
            empty_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
            empty_row.add_prefix(empty_icon)
            empty_row.set_title(_("trust_custom_empty_title") if "_" in dir() else "No Custom Roots Installed")
            empty_row.set_subtitle(
                _("trust_custom_empty_desc") if "_" in dir() else
                "Click 'Import Certificate' to add .crt, .cer, or .pem trust anchors."
            )
            empty_row.set_subtitle_lines(0)
            custom_group.add(empty_row)
            return

        for item in custom_roots:
            row = Adw.ActionRow()
            cert_icon = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
            row.add_prefix(cert_icon)

            cn = item.get("subject_cn") or item.get("filename") or "Certificate"
            org = item.get("subject_org")
            title_text = f"{cn} ({org})" if org else cn
            row.set_title(title_text)

            issuer = item.get("issuer_cn") or "Self-signed"
            fp = item.get("sha256_fingerprint", "")
            short_fp = f"{fp[:16]}..." if len(fp) >= 16 else fp
            sub_text = f"Issuer: {issuer} | SHA-256: {short_fp}"
            row.set_subtitle(sub_text)
            row.set_subtitle_lines(0)

            del_btn = Gtk.Button()
            del_btn.set_icon_name("user-trash-symbolic")
            del_btn.add_css_class("flat")
            del_btn.add_css_class("destructive-action")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.set_tooltip_text(_("trust_btn_remove") if "_" in dir() else "Remove Certificate")
            target_fn = item.get("filename") or ""
            del_btn.connect("clicked", lambda b, fn=target_fn: self._on_delete_clicked(fn))
            row.add_suffix(del_btn)

            custom_group.add(row)

    def _on_import_clicked(self, button):
        """Open file dialog to import .crt, .cer, or .pem certificate."""
        f_cert = Gtk.FileFilter()
        f_cert.set_name("X.509 Certificates (*.crt, *.cer, *.pem)")
        f_cert.add_pattern("*.crt")
        f_cert.add_pattern("*.cer")
        f_cert.add_pattern("*.pem")
        f_cert.add_pattern("*.der")

        f_all = Gtk.FileFilter()
        f_all.set_name("All Files (*)")
        f_all.add_pattern("*")

        def on_selected(gfile):
            if not gfile:
                return
            path = gfile.get_path()
            if not path or not os.path.exists(path):
                return
            success, err, summary = import_trusted_root(path)
            if success:
                self._refresh_content()
            else:
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.CLOSE,
                    text="Certificate Import Failed",
                    secondary_text=err or "Invalid certificate format.",
                )
                dialog.connect("response", lambda d, r: d.destroy())
                dialog.present()

        show_open_file_dialog(
            self,
            "Select Root Certificate to Trust",
            filters=[f_cert, f_all],
            default_filter=f_cert,
            callback=on_selected,
        )

    def _on_delete_clicked(self, filename: str):
        """Confirm and delete a custom trusted root certificate."""
        if not filename:
            return
        accepted = show_confirm_dialog(
            self,
            f"Are you sure you want to remove '{filename}' from trusted roots?",
            title="Remove Trusted Certificate",
            destructive=True,
        )
        if accepted:
            remove_custom_trusted_root(filename)
            self._refresh_content()
