# word-sys-pdf-editor - Digital Signature Dialogs
# Modal interfaces for configuring digital signatures and viewing signature validation status.

from __future__ import annotations

import os
from typing import Optional, Callable, Dict, Any, List, Tuple
from datetime import datetime

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio

from .i18n import _
from .ui_components import show_open_file_dialog
from .digital_signature import load_pkcs12_certificate, is_pyhanko_available


class DigitalSignatureDialog(Adw.Window):
    """Libadwaita modal dialog for configuring and applying a cryptographic digital signature."""

    def __init__(
        self,
        parent_window,
        page_count: int = 1,
        current_page: int = 0,
        initial_box: Optional[Tuple[float, float, float, float]] = None,
        on_sign_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        super().__init__()
        self.parent_window = parent_window
        self.page_count = max(1, page_count)
        self.current_page = max(0, min(current_page, self.page_count - 1))
        self.initial_box = initial_box
        self.on_sign_callback = on_sign_callback

        self.cert_path: str = ""
        self.cert_data: bytes = b""
        self.passphrase: str = ""
        self.cert_info: Optional[Dict[str, Any]] = None
        self.signer = None

        self.image_path: str = ""
        self.image_bytes: Optional[bytes] = None

        if parent_window:
            self.set_transient_for(parent_window)
            self.set_modal(True)

        self.set_title(_("sig_dialog_title"))
        self.set_default_size(520, 680)
        self.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # HeaderBar
        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(self.cancel_btn)

        self.sign_btn = Gtk.Button(label=_("sig_btn_sign"))
        self.sign_btn.add_css_class("suggested-action")
        self.sign_btn.set_sensitive(False)
        self.sign_btn.connect("clicked", self._on_sign_clicked)
        header.pack_end(self.sign_btn)
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

        # --- Group 1: Certificate Selection ---
        cert_group = Adw.PreferencesGroup()
        cert_group.set_title(_("sig_group_cert"))
        cert_group.set_description(_("sig_group_cert_desc"))
        content_box.append(cert_group)

        # Cert file row
        self.cert_file_row = Adw.ActionRow()
        self.cert_file_row.set_title(_("sig_cert_file"))
        self.cert_file_row.set_subtitle(_("sig_cert_none_selected"))
        self.cert_file_row.set_subtitle_lines(0)

        browse_cert_btn = Gtk.Button(label=_("sig_btn_browse"))
        browse_cert_btn.set_valign(Gtk.Align.CENTER)
        browse_cert_btn.connect("clicked", self._on_browse_cert_clicked)
        self.cert_file_row.add_suffix(browse_cert_btn)
        cert_group.add(self.cert_file_row)

        # Password row
        self.pw_row = Adw.ActionRow()
        self.pw_row.set_title(_("sig_cert_password"))
        self.pw_entry = Gtk.PasswordEntry()
        self.pw_entry.set_valign(Gtk.Align.CENTER)
        self.pw_entry.set_hexpand(True)
        self.pw_entry.connect("changed", self._on_credentials_changed)
        self.pw_entry.connect("activate", lambda e: self._on_credentials_changed(e))
        self.pw_row.add_suffix(self.pw_entry)
        cert_group.add(self.pw_row)

        # Status row
        self.status_row = Adw.ActionRow()
        self.status_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        self.status_row.add_prefix(self.status_icon)
        self.status_row.set_title(_("sig_cert_status_title"))
        self.status_row.set_subtitle(_("sig_cert_status_prompt"))
        self.status_row.set_subtitle_lines(0)
        cert_group.add(self.status_row)

        # --- Group 2: Signature Details ---
        details_group = Adw.PreferencesGroup()
        details_group.set_title(_("sig_group_details"))
        content_box.append(details_group)

        # Reason row
        reason_row = Adw.ActionRow()
        reason_row.set_title(_("sig_reason"))
        self.reason_combo = Gtk.ComboBoxText()
        self.reason_combo.set_valign(Gtk.Align.CENTER)
        self.reason_combo.append_text(_("sig_reason_approve"))
        self.reason_combo.append_text(_("sig_reason_author"))
        self.reason_combo.append_text(_("sig_reason_reviewed"))
        self.reason_combo.append_text(_("sig_reason_custom"))
        self.reason_combo.set_active(0)
        self.reason_combo.connect("changed", self._on_reason_combo_changed)
        reason_row.add_suffix(self.reason_combo)
        details_group.add(reason_row)

        self.custom_reason_row = Adw.ActionRow()
        self.custom_reason_row.set_title(_("sig_reason_custom_label"))
        self.custom_reason_entry = Gtk.Entry()
        self.custom_reason_entry.set_valign(Gtk.Align.CENTER)
        self.custom_reason_entry.set_hexpand(True)
        self.custom_reason_row.add_suffix(self.custom_reason_entry)
        self.custom_reason_row.set_visible(False)
        details_group.add(self.custom_reason_row)

        # Location row
        loc_row = Adw.ActionRow()
        loc_row.set_title(_("sig_location"))
        self.loc_entry = Gtk.Entry()
        self.loc_entry.set_valign(Gtk.Align.CENTER)
        self.loc_entry.set_hexpand(True)
        self.loc_entry.set_placeholder_text(_("sig_location_placeholder"))
        loc_row.add_suffix(self.loc_entry)
        details_group.add(loc_row)

        # Contact row
        contact_row = Adw.ActionRow()
        contact_row.set_title(_("sig_contact"))
        self.contact_entry = Gtk.Entry()
        self.contact_entry.set_valign(Gtk.Align.CENTER)
        self.contact_entry.set_hexpand(True)
        self.contact_entry.set_placeholder_text(_("sig_contact_placeholder"))
        contact_row.add_suffix(self.contact_entry)
        details_group.add(contact_row)

        # --- Group 3: Visual Appearance ---
        appearance_group = Adw.PreferencesGroup()
        appearance_group.set_title(_("sig_group_appearance"))
        content_box.append(appearance_group)

        # Visible switch row
        self.visible_row = Adw.ActionRow()
        self.visible_row.set_title(_("sig_visible_stamp"))
        self.visible_row.set_subtitle(_("sig_visible_stamp_desc"))
        self.visible_row.set_subtitle_lines(0)
        self.visible_switch = Gtk.Switch()
        self.visible_switch.set_valign(Gtk.Align.CENTER)
        self.visible_switch.set_active(True)
        self.visible_switch.connect("notify::active", self._on_visible_toggled)
        self.visible_row.add_suffix(self.visible_switch)
        appearance_group.add(self.visible_row)

        # Page spin row
        self.page_row = Adw.ActionRow()
        self.page_row.set_title(_("sig_target_page"))
        self.page_spin = Gtk.SpinButton.new_with_range(1, self.page_count, 1)
        self.page_spin.set_valign(Gtk.Align.CENTER)
        self.page_spin.set_value(self.current_page + 1)
        self.page_row.add_suffix(self.page_spin)
        appearance_group.add(self.page_row)

        # Position row
        self.position_row = Adw.ActionRow()
        self.position_row.set_title(_("sig_position"))
        self._positions = [
            ("bottom_right", _("sig_pos_bottom_right")),
            ("bottom_left", _("sig_pos_bottom_left")),
            ("top_right", _("sig_pos_top_right")),
            ("top_left", _("sig_pos_top_left")),
        ]
        self.position_combo = Gtk.DropDown.new_from_strings([label for _, label in self._positions])
        self.position_combo.set_valign(Gtk.Align.CENTER)
        self.position_row.add_suffix(self.position_combo)
        appearance_group.add(self.position_row)

        # Handwritten image row
        self.image_row = Adw.ActionRow()
        self.image_row.set_title(_("sig_image_optional"))
        self.image_row.set_subtitle(_("sig_image_none"))
        self.image_row.set_subtitle_lines(0)

        image_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.browse_image_btn = Gtk.Button(label=_("sig_btn_browse"))
        self.browse_image_btn.set_valign(Gtk.Align.CENTER)
        self.browse_image_btn.connect("clicked", self._on_browse_image_clicked)
        image_btn_box.append(self.browse_image_btn)

        self.clear_image_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        self.clear_image_btn.set_valign(Gtk.Align.CENTER)
        self.clear_image_btn.set_tooltip_text(_("sig_image_clear"))
        self.clear_image_btn.set_sensitive(False)
        self.clear_image_btn.connect("clicked", self._on_clear_image_clicked)
        image_btn_box.append(self.clear_image_btn)

        self.image_row.add_suffix(image_btn_box)
        appearance_group.add(self.image_row)

    def _on_reason_combo_changed(self, combo):
        is_custom = combo.get_active() == 3
        self.custom_reason_row.set_visible(is_custom)

    def _on_visible_toggled(self, switch, gparam):
        active = switch.get_active()
        self.page_row.set_sensitive(active)
        self.position_row.set_sensitive(active)
        self.image_row.set_sensitive(active)

    def _on_browse_cert_clicked(self, button):
        f_cert = Gtk.FileFilter()
        f_cert.set_name(_("sig_filter_certs"))
        f_cert.add_pattern("*.p12")
        f_cert.add_pattern("*.pfx")
        f_cert.add_mime_type("application/x-pkcs12")

        f_all = Gtk.FileFilter()
        f_all.set_name(_("filter_all_files"))
        f_all.add_pattern("*")

        def on_cert_selected(gfile):
            if not gfile:
                return
            path = gfile.get_path()
            if not path or not os.path.exists(path):
                return
            self.cert_path = path
            try:
                with open(path, "rb") as f:
                    self.cert_data = f.read()
                filename = os.path.basename(path)
                self.cert_file_row.set_subtitle(filename)
                self._verify_credentials()
            except Exception as e:
                self.cert_file_row.set_subtitle(f"Error reading file: {e}")

        show_open_file_dialog(
            self,
            _("sig_select_cert_title"),
            filters=[f_cert, f_all],
            default_filter=f_cert,
            callback=on_cert_selected,
        )

    def _on_browse_image_clicked(self, button):
        f_img = Gtk.FileFilter()
        f_img.set_name(_("image_filter_label"))
        f_img.add_pixbuf_formats()

        def on_image_selected(gfile):
            if not gfile:
                return
            path = gfile.get_path()
            if not path or not os.path.exists(path):
                return
            try:
                with open(path, "rb") as f:
                    self.image_bytes = f.read()
                self.image_path = path
                self.image_row.set_subtitle(os.path.basename(path))
                self.clear_image_btn.set_sensitive(True)
            except Exception as e:
                self.image_row.set_subtitle(f"Error: {e}")

        show_open_file_dialog(
            self,
            _("image_select_title"),
            filters=[f_img],
            callback=on_image_selected,
        )

    def _on_clear_image_clicked(self, button):
        self.image_path = ""
        self.image_bytes = None
        self.image_row.set_subtitle(_("sig_image_none"))
        self.clear_image_btn.set_sensitive(False)

    def _on_credentials_changed(self, entry):
        self.passphrase = self.pw_entry.get_text()
        self._verify_credentials()

    def _verify_credentials(self):
        if not self.cert_data:
            self.status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.status_row.set_title(_("sig_cert_status_title"))
            self.status_row.set_subtitle(_("sig_cert_status_prompt"))
            self.sign_btn.set_sensitive(False)
            return

        signer, info, err = load_pkcs12_certificate(self.cert_data, passphrase=self.passphrase)
        if err or signer is None or info is None:
            self.status_icon.set_from_icon_name("dialog-error-symbolic")
            self.status_row.set_title(_("sig_cert_locked"))
            self.status_row.set_subtitle(err or _("sig_cert_invalid_pass"))
            self.sign_btn.set_sensitive(False)
            self.signer = None
            self.cert_info = None
        else:
            self.signer = signer
            self.cert_info = info
            self.status_icon.set_from_icon_name("emblem-ok-symbolic")
            signer_name = info.get("subject_cn") or "Signer"
            issuer_name = info.get("issuer_cn") or info.get("issuer_friendly") or "CA"
            expiry = info.get("not_after")
            expiry_str = expiry.strftime("%Y-%m-%d") if expiry else ""
            status_text = f"Issuer: {issuer_name}"
            if expiry_str:
                status_text += f" | Valid to: {expiry_str}"
            self.status_row.set_title(signer_name)
            self.status_row.set_subtitle(status_text)
            self.sign_btn.set_sensitive(True)

    def _get_reason(self) -> str:
        idx = self.reason_combo.get_active()
        if idx == 0:
            return _("sig_reason_approve")
        elif idx == 1:
            return _("sig_reason_author")
        elif idx == 2:
            return _("sig_reason_reviewed")
        else:
            txt = self.custom_reason_entry.get_text().strip()
            return txt or _("sig_reason_approve")

    def _on_sign_clicked(self, button):
        if not self.signer or not self.cert_info:
            return

        target_page = int(self.page_spin.get_value()) - 1
        pos_idx = self.position_combo.get_selected()
        pos_key = self._positions[pos_idx][0] if 0 <= pos_idx < len(self._positions) else "bottom_right"
        options = {
            "cert_path": self.cert_path,
            "cert_data": self.cert_data,
            "passphrase": self.passphrase,
            "signer_name": self.cert_info.get("subject_cn", ""),
            "reason": self._get_reason(),
            "location": self.loc_entry.get_text().strip(),
            "contact_info": self.contact_entry.get_text().strip(),
            "visual_stamp": self.visible_switch.get_active(),
            "page_index": target_page,
            "position": pos_key,
            "box": self.initial_box,
            "signature_image_bytes": self.image_bytes,
        }

        self.destroy()
        if self.on_sign_callback:
            self.on_sign_callback(options)


class SignatureDetailsDialog(Adw.Window):
    """Libadwaita modal dialog listing all digital signatures and cryptographic verification statuses."""

    def __init__(self, parent_window, signatures: List[Dict[str, Any]]):
        super().__init__()
        self.parent_window = parent_window
        self.signatures = signatures

        if parent_window:
            self.set_transient_for(parent_window)
            self.set_modal(True)

        self.set_title(_("sig_details_title"))
        self.set_default_size(560, 580)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # HeaderBar with native window controls
        header = Adw.HeaderBar()
        main_box.append(header)

        # Scrolled container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=520)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        if not signatures:
            status_page = Adw.StatusPage()
            status_page.set_icon_name("security-high-symbolic")
            status_page.set_title(_("sig_none_found_title"))
            status_page.set_description(_("sig_none_found_desc"))
            clamp.set_child(status_page)
            return

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(content_box)

        for idx, sig in enumerate(signatures, 1):
            group = Adw.PreferencesGroup()
            field_name = sig.get("field_name") or f"Signature {idx}"
            group.set_title(f"{_('sig_header_signature')} #{idx}: {field_name}")
            content_box.append(group)

            # Integrity / Validity Status Row
            status_row = Adw.ActionRow()
            is_intact = sig.get("intact", False)
            if is_intact:
                icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                icon.add_css_class("success")
                status_row.add_prefix(icon)
                status_row.set_title(_("sig_status_valid"))
                status_row.set_subtitle(_("sig_status_valid_desc"))
            else:
                icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
                icon.add_css_class("error")
                status_row.add_prefix(icon)
                status_row.set_title(_("sig_status_invalid"))
                status_row.set_subtitle(_("sig_status_invalid_desc"))
            status_row.set_subtitle_lines(0)
            group.add(status_row)

            # Signer Details
            signer_row = Adw.ActionRow()
            signer_row.set_title(_("sig_detail_signer"))
            signer_text = sig.get("signer_cn") or "Unknown"
            org = sig.get("signer_org")
            if org:
                signer_text += f" ({org})"
            signer_row.set_subtitle(signer_text)
            group.add(signer_row)

            # Issuer Details
            issuer_row = Adw.ActionRow()
            issuer_row.set_title(_("sig_detail_issuer"))
            issuer_text = sig.get("issuer_cn") or sig.get("issuer_friendly") or "Unknown"
            issuer_row.set_subtitle(issuer_text)
            group.add(issuer_row)

            # Date / Timestamp
            ts = sig.get("signing_time")
            if ts:
                date_row = Adw.ActionRow()
                date_row.set_title(_("sig_detail_date"))
                date_str = ts.strftime("%Y-%m-%d %H:%M:%S %Z") if hasattr(ts, "strftime") else str(ts)
                date_row.set_subtitle(date_str)
                group.add(date_row)

            # Reason
            reason = sig.get("reason")
            if reason:
                reason_row = Adw.ActionRow()
                reason_row.set_title(_("sig_reason"))
                reason_row.set_subtitle(reason)
                group.add(reason_row)

            # Location
            location = sig.get("location")
            if location:
                loc_row = Adw.ActionRow()
                loc_row.set_title(_("sig_location"))
                loc_row.set_subtitle(location)
                group.add(loc_row)

            # Scope / Coverage
            cov_row = Adw.ActionRow()
            cov_row.set_title(_("sig_detail_coverage"))
            coverage = sig.get("coverage", "UNKNOWN")
            if "ENTIRE_FILE" in coverage:
                cov_desc = _("sig_coverage_entire")
            else:
                cov_desc = _("sig_coverage_revision")
            cov_row.set_subtitle(cov_desc)
            group.add(cov_row)

            # Validity Range
            not_before = sig.get("not_before")
            not_after = sig.get("not_after")
            if not_before and not_after:
                validity_row = Adw.ActionRow()
                validity_row.set_title(_("sig_detail_cert_validity"))
                nb_str = not_before.strftime("%Y-%m-%d") if hasattr(not_before, "strftime") else str(not_before)
                na_str = not_after.strftime("%Y-%m-%d") if hasattr(not_after, "strftime") else str(not_after)
                validity_row.set_subtitle(f"{nb_str} -> {na_str}")
                group.add(validity_row)

            # SHA-256 Fingerprint
            fp = sig.get("sha256_fingerprint")
            if fp:
                fp_row = Adw.ActionRow()
                fp_row.set_title(_("sig_detail_fingerprint"))
                formatted_fp = ":".join(fp[i:i+2] for i in range(0, len(fp), 2))
                fp_row.set_subtitle(formatted_fp)
                fp_row.set_subtitle_lines(0)
                group.add(fp_row)
