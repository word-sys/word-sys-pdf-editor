from __future__ import annotations

import os
from typing import Optional, Callable, Dict, Any, List, Tuple
from datetime import datetime

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio

from .i18n import _
from .ui_components import show_open_file_dialog, show_save_file_dialog
from .digital_signature import load_pkcs12_certificate, is_pyhanko_available
from .pkcs11_manager import (
    find_available_pkcs11_drivers,
    list_tokens,
    list_token_certificates,
    is_pkcs11_engine_available,
)
from .tsa_client import (
    TSAConfig,
    PRESET_TSAS,
)
from .pades_signer import (
    PADES_B_B,
    PADES_B_T,
    PADES_B_LT,
    PADES_B_LTA,
)


class DigitalSignatureDialog(Adw.Window):
    """Libadwaita modal dialog for configuring and applying a cryptographic digital signature."""

    def __init__(
        self,
        parent_window,
        page_count: int = 1,
        current_page: int = 0,
        initial_box: Optional[Tuple[float, float, float, float]] = None,
        on_sign_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_draw_canvas_requested: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self.parent_window = parent_window
        self.page_count = max(1, page_count)
        self.current_page = max(0, min(current_page, self.page_count - 1))
        self.initial_box = initial_box
        self.on_sign_callback = on_sign_callback
        self.on_draw_canvas_requested = on_draw_canvas_requested

        # Certificate source: "software" or "hardware"
        self.cert_source: str = "software"

        # Software certificate state
        self.cert_path: str = ""
        self.cert_data: bytes = b""
        self.passphrase: str = ""
        self.cert_info: Optional[Dict[str, Any]] = None
        self.signer = None

        # Hardware token state
        self.hw_driver_path: str = ""
        self.hw_token_label: str = ""
        self.hw_token_slot_id: Optional[int] = None
        self.hw_pin: str = ""
        self.hw_cert_label: Optional[str] = None
        self.hw_cert_id: Optional[bytes] = None
        self.hw_cert_info: Optional[Dict[str, Any]] = None
        self.available_drivers: List[Dict[str, str]] = []
        self.available_tokens: List[Dict[str, Any]] = []
        self.available_certs: List[Dict[str, Any]] = []

        self.image_path: str = ""
        self.image_bytes: Optional[bytes] = None

        if parent_window:
            self.set_transient_for(parent_window)
            self.set_modal(True)

        self.set_title(_("sig_dialog_title"))
        self.set_default_size(540, 720)
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

        clamp = Adw.Clamp(maximum_size=490)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(content_box)

        # --- Source Selector ---
        source_group = Adw.PreferencesGroup()
        source_group.set_title(_("sig_group_source"))
        content_box.append(source_group)

        self.source_row = Adw.ActionRow()
        self.source_row.set_title(_("sig_group_source"))
        self.source_combo = Gtk.DropDown.new_from_strings([
            _("sig_source_software"),
            _("sig_source_hardware"),
        ])
        self.source_combo.set_valign(Gtk.Align.CENTER)
        self.source_combo.connect("notify::selected", self._on_source_changed)
        self.source_row.add_suffix(self.source_combo)
        source_group.add(self.source_row)

        # --- Group 1: Software Certificate Selection ---
        self.sw_cert_group = Adw.PreferencesGroup()
        self.sw_cert_group.set_title(_("sig_group_cert"))
        self.sw_cert_group.set_description(_("sig_group_cert_desc"))
        content_box.append(self.sw_cert_group)

        # Cert file row
        self.cert_file_row = Adw.ActionRow()
        self.cert_file_row.set_title(_("sig_cert_file"))
        self.cert_file_row.set_subtitle(_("sig_cert_none_selected"))
        self.cert_file_row.set_subtitle_lines(0)

        browse_cert_btn = Gtk.Button(label=_("sig_btn_browse"))
        browse_cert_btn.set_valign(Gtk.Align.CENTER)
        browse_cert_btn.connect("clicked", self._on_browse_cert_clicked)
        self.cert_file_row.add_suffix(browse_cert_btn)
        self.sw_cert_group.add(self.cert_file_row)

        # Password row
        self.pw_row = Adw.ActionRow()
        self.pw_row.set_title(_("sig_cert_password"))
        self.pw_entry = Gtk.PasswordEntry()
        self.pw_entry.set_valign(Gtk.Align.CENTER)
        self.pw_entry.set_hexpand(True)
        self.pw_entry.connect("changed", self._on_credentials_changed)
        self.pw_entry.connect("activate", lambda e: self._on_credentials_changed(e))
        self.pw_row.add_suffix(self.pw_entry)
        self.sw_cert_group.add(self.pw_row)

        # Software status row
        self.status_row = Adw.ActionRow()
        self.status_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        self.status_row.add_prefix(self.status_icon)
        self.status_row.set_title(_("sig_cert_status_title"))
        self.status_row.set_subtitle(_("sig_cert_status_prompt"))
        self.status_row.set_subtitle_lines(0)
        self.sw_cert_group.add(self.status_row)

        # --- Group 2: Hardware Token Group ---
        self.hw_token_group = Adw.PreferencesGroup()
        self.hw_token_group.set_title(_("sig_source_hardware"))
        self.hw_token_group.set_description(_("sig_source_hardware_desc"))
        self.hw_token_group.set_visible(False)
        content_box.append(self.hw_token_group)

        # Driver row
        self.hw_driver_row = Adw.ActionRow()
        self.hw_driver_row.set_title(_("sig_hw_driver"))

        driver_controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        driver_controls_box.set_valign(Gtk.Align.CENTER)
        driver_controls_box.set_halign(Gtk.Align.END)
        driver_controls_box.set_margin_top(4)
        driver_controls_box.set_margin_bottom(4)

        self.hw_driver_combo = Gtk.DropDown.new_from_strings([_("sig_hw_no_drivers")])
        self.hw_driver_combo.set_valign(Gtk.Align.CENTER)
        self.hw_driver_combo.connect("notify::selected", self._on_hw_driver_changed)
        driver_controls_box.append(self.hw_driver_combo)

        hw_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hw_btn_box.set_halign(Gtk.Align.FILL)

        browse_driver_btn = Gtk.Button(label=_("sig_hw_browse_driver"))
        browse_driver_btn.set_hexpand(True)
        browse_driver_btn.set_valign(Gtk.Align.CENTER)
        browse_driver_btn.connect("clicked", self._on_browse_driver_clicked)
        hw_btn_box.append(browse_driver_btn)

        rescan_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        rescan_btn.set_tooltip_text(_("sig_hw_rescan"))
        rescan_btn.set_valign(Gtk.Align.CENTER)
        rescan_btn.connect("clicked", lambda b: self._rescan_pkcs11_drivers())
        hw_btn_box.append(rescan_btn)

        driver_controls_box.append(hw_btn_box)

        self.hw_driver_row.add_suffix(driver_controls_box)
        self.hw_token_group.add(self.hw_driver_row)

        # Token row
        self.hw_token_row = Adw.ActionRow()
        self.hw_token_row.set_title(_("sig_hw_token"))
        self.hw_token_combo = Gtk.DropDown.new_from_strings([_("sig_hw_no_tokens")])
        self.hw_token_combo.set_valign(Gtk.Align.CENTER)
        self.hw_token_combo.connect("notify::selected", self._on_hw_token_changed)
        self.hw_token_row.add_suffix(self.hw_token_combo)
        self.hw_token_group.add(self.hw_token_row)

        # PIN row
        self.hw_pin_row = Adw.ActionRow()
        self.hw_pin_row.set_title(_("sig_hw_pin"))
        self.hw_pin_entry = Gtk.PasswordEntry()
        self.hw_pin_entry.set_valign(Gtk.Align.CENTER)
        self.hw_pin_entry.set_hexpand(True)
        self.hw_pin_entry.connect("changed", self._on_hw_pin_changed)
        self.hw_pin_entry.connect("activate", lambda e: self._on_hw_pin_changed(e))
        self.hw_pin_row.add_suffix(self.hw_pin_entry)
        self.hw_token_group.add(self.hw_pin_row)

        # Certificate row
        self.hw_cert_row = Adw.ActionRow()
        self.hw_cert_row.set_title(_("sig_hw_cert"))
        self.hw_cert_combo = Gtk.DropDown.new_from_strings([_("sig_hw_no_certs")])
        self.hw_cert_combo.set_valign(Gtk.Align.CENTER)
        self.hw_cert_combo.connect("notify::selected", self._on_hw_cert_changed)
        self.hw_cert_row.add_suffix(self.hw_cert_combo)
        self.hw_token_group.add(self.hw_cert_row)

        # Hardware status row
        self.hw_status_row = Adw.ActionRow()
        self.hw_status_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        self.hw_status_row.add_prefix(self.hw_status_icon)
        self.hw_status_row.set_title(_("sig_cert_status_title"))
        self.hw_status_row.set_subtitle(_("sig_hw_no_certs"))
        self.hw_status_row.set_subtitle_lines(0)
        self.hw_token_group.add(self.hw_status_row)

        # --- Group 3: PAdES Profile & Timestamping ---
        pades_group = Adw.PreferencesGroup()
        pades_group.set_title(_("sig_group_pades"))
        content_box.append(pades_group)

        self.pades_profile_row = Adw.ActionRow()
        self.pades_profile_row.set_title(_("sig_pades_profile"))
        self._pades_profiles = [
            (PADES_B_B, "PAdES B-B (Basic Cryptographic Signature)"),
            (PADES_B_T, "PAdES B-T (Includes RFC 3161 Trusted Timestamp)"),
            (PADES_B_LT, "PAdES B-LT (Long-Term Validation with /DSS)"),
            (PADES_B_LTA, "PAdES B-LTA (Long-Term Archive with DocTimeStamp)"),
        ]
        self.pades_combo = Gtk.DropDown.new_from_strings([label for _, label in self._pades_profiles])
        self.pades_combo.set_valign(Gtk.Align.CENTER)
        self.pades_combo.connect("notify::selected", self._on_pades_profile_changed)
        self.pades_profile_row.add_suffix(self.pades_combo)
        pades_group.add(self.pades_profile_row)

        # TSA Server preset row
        self.tsa_row = Adw.ActionRow()
        self.tsa_row.set_title(_("sig_tsa_server"))
        self._tsa_presets = [
            ("digicert", "DigiCert TSA (http://timestamp.digicert.com)"),
            ("freetsa", "FreeTSA (https://freetsa.org/tsr)"),
            ("sectigo", "Sectigo TSA (http://timestamp.sectigo.com)"),
            ("custom", _("preset_custom")),
        ]
        self.tsa_combo = Gtk.DropDown.new_from_strings([label for _, label in self._tsa_presets])
        self.tsa_combo.set_valign(Gtk.Align.CENTER)
        self.tsa_combo.connect("notify::selected", self._on_tsa_preset_changed)
        self.tsa_row.add_suffix(self.tsa_combo)
        self.tsa_row.set_visible(False)
        pades_group.add(self.tsa_row)

        # Custom TSA URL row
        self.custom_tsa_row = Adw.ActionRow()
        self.custom_tsa_row.set_title(_("sig_tsa_custom_url"))
        self.custom_tsa_entry = Gtk.Entry()
        self.custom_tsa_entry.set_valign(Gtk.Align.CENTER)
        self.custom_tsa_entry.set_hexpand(True)
        self.custom_tsa_entry.set_placeholder_text("https://...")
        self.custom_tsa_row.add_suffix(self.custom_tsa_entry)
        self.custom_tsa_row.set_visible(False)
        pades_group.add(self.custom_tsa_row)

        # Optional TSA Auth row
        self.tsa_auth_row = Adw.ActionRow()
        self.tsa_auth_row.set_title(_("sig_tsa_auth_optional"))
        tsa_auth_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.tsa_user_entry = Gtk.Entry()
        self.tsa_user_entry.set_placeholder_text(_("sig_tsa_user"))
        self.tsa_user_entry.set_valign(Gtk.Align.CENTER)
        tsa_auth_box.append(self.tsa_user_entry)
        self.tsa_pass_entry = Gtk.PasswordEntry()
        self.tsa_pass_entry.set_valign(Gtk.Align.CENTER)
        tsa_auth_box.append(self.tsa_pass_entry)
        self.tsa_auth_row.add_suffix(tsa_auth_box)
        self.tsa_auth_row.set_visible(False)
        pades_group.add(self.tsa_auth_row)

        # --- Group 4: Signature Details ---
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

        # Certify Document (DocMDP) row
        self.certify_row = Adw.ActionRow()
        self.certify_row.set_title("Certify Document (DocMDP)")
        self.certify_row.set_subtitle("Apply as primary author certification restricting future document modifications.")
        self.certify_row.set_subtitle_lines(0)
        self.certify_switch = Gtk.Switch()
        self.certify_switch.set_valign(Gtk.Align.CENTER)
        self.certify_switch.set_active(False)
        self.certify_switch.connect("notify::active", self._on_certify_toggled)
        self.certify_row.add_suffix(self.certify_switch)
        details_group.add(self.certify_row)

        # DocMDP permissions dropdown row
        self.docmdp_row = Adw.ActionRow()
        self.docmdp_row.set_title("Permitted Changes")
        self.docmdp_combo = Gtk.DropDown.new_from_strings([
            "Level 1: No Changes Permitted (Document Sealed)",
            "Level 2: Form Filling & Signing Permitted",
            "Level 3: Annotations, Form Filling & Signing Permitted",
        ])
        self.docmdp_combo.set_selected(1)
        self.docmdp_combo.set_valign(Gtk.Align.CENTER)
        self.docmdp_row.add_suffix(self.docmdp_combo)
        self.docmdp_row.set_visible(False)
        details_group.add(self.docmdp_row)

        # --- Group 5: Visual Appearance ---
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
        if self.initial_box:
            self._positions.insert(0, ("drawn_box", _("sig_pos_drawn_box")))

        pos_controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pos_controls_box.set_valign(Gtk.Align.CENTER)
        pos_controls_box.set_halign(Gtk.Align.END)
        pos_controls_box.set_margin_top(4)
        pos_controls_box.set_margin_bottom(4)

        self.position_combo = Gtk.DropDown.new_from_strings([label for _, label in self._positions])
        self.position_combo.set_valign(Gtk.Align.CENTER)
        if self.initial_box:
            self.position_combo.set_selected(0)
        pos_controls_box.append(self.position_combo)

        self.draw_canvas_btn = Gtk.Button(label=_("sig_btn_draw_canvas"))
        self.draw_canvas_btn.set_valign(Gtk.Align.CENTER)
        self.draw_canvas_btn.connect("clicked", self._on_draw_canvas_clicked)
        pos_controls_box.append(self.draw_canvas_btn)

        self.position_row.add_suffix(pos_controls_box)

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

    def _on_source_changed(self, combo, _param):
        idx = combo.get_selected()
        if idx == 0:
            self.cert_source = "software"
            self.sw_cert_group.set_visible(True)
            self.hw_token_group.set_visible(False)
        else:
            self.cert_source = "hardware"
            self.sw_cert_group.set_visible(False)
            self.hw_token_group.set_visible(True)
            if not self.available_drivers:
                self._rescan_pkcs11_drivers()
        self._verify_credentials()

    def _rescan_pkcs11_drivers(self):
        try:
            self.available_drivers = find_available_pkcs11_drivers()
        except Exception:
            self.available_drivers = []

        if not self.available_drivers:
            self.hw_driver_combo.set_model(Gtk.StringList.new([_("sig_hw_no_drivers")]))
            self.hw_token_combo.set_model(Gtk.StringList.new([_("sig_hw_no_tokens")]))
            self.hw_cert_combo.set_model(Gtk.StringList.new([_("sig_hw_no_certs")]))
            self.hw_driver_path = ""
            self.hw_token_label = ""
            self.hw_token_slot_id = None
            self.hw_status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.hw_status_row.set_title(_("sig_cert_status_title"))
            self.hw_status_row.set_subtitle(_("sig_hw_no_drivers"))
            return

        driver_names = [d["name"] for d in self.available_drivers]
        self.hw_driver_combo.set_model(Gtk.StringList.new(driver_names))
        self.hw_driver_combo.set_selected(0)
        self._on_hw_driver_changed(self.hw_driver_combo, None)

    def _on_browse_driver_clicked(self, button):
        f_so = Gtk.FileFilter()
        f_so.set_name(_("sig_hw_select_driver_title"))
        f_so.add_pattern("*.so")
        f_so.add_pattern("*.so.*")

        f_all = Gtk.FileFilter()
        f_all.set_name(_("filter_all_files"))
        f_all.add_pattern("*")

        def on_driver_selected(gfile):
            if not gfile:
                return
            path = gfile.get_path()
            if not path or not os.path.exists(path):
                return
            custom_driver = {"name": f"Custom: {os.path.basename(path)}", "path": path}
            self.available_drivers.insert(0, custom_driver)
            driver_names = [d["name"] for d in self.available_drivers]
            self.hw_driver_combo.set_model(Gtk.StringList.new(driver_names))
            self.hw_driver_combo.set_selected(0)
            self._on_hw_driver_changed(self.hw_driver_combo, None)

        show_open_file_dialog(
            self,
            _("sig_hw_select_driver_title"),
            filters=[f_so, f_all],
            default_filter=f_so,
            callback=on_driver_selected,
        )

    def _on_hw_driver_changed(self, combo, _param):
        idx = combo.get_selected()
        if 0 <= idx < len(self.available_drivers):
            self.hw_driver_path = self.available_drivers[idx]["path"]
            tokens, err = list_tokens(self.hw_driver_path)
            self.available_tokens = tokens or []
            if tokens:
                labels = [f"{t.get('token_label', 'Token')} ({t.get('manufacturer', '')})" for t in tokens]
                self.hw_token_combo.set_model(Gtk.StringList.new(labels))
                self.hw_token_combo.set_selected(0)
                self._on_hw_token_changed(self.hw_token_combo, None)
            else:
                self.hw_token_combo.set_model(Gtk.StringList.new([_("sig_hw_no_tokens")]))
                self.hw_token_label = ""
                self.hw_token_slot_id = None
                self._update_hw_certificates([])
        else:
            self.hw_driver_path = ""
            self.hw_token_combo.set_model(Gtk.StringList.new([_("sig_hw_no_tokens")]))
            self.hw_token_label = ""
            self.hw_token_slot_id = None
            self._update_hw_certificates([])

    def _on_hw_token_changed(self, combo, _param):
        idx = combo.get_selected()
        if 0 <= idx < len(self.available_tokens):
            tok = self.available_tokens[idx]
            self.hw_token_label = tok.get("token_label", "")
            self.hw_token_slot_id = tok.get("slot_id")
        else:
            self.hw_token_label = ""
            self.hw_token_slot_id = None
        self._refresh_hw_certificates()

    def _on_hw_pin_changed(self, entry):
        self.hw_pin = entry.get_text()
        self._refresh_hw_certificates()

    def _refresh_hw_certificates(self):
        if not self.hw_driver_path or not self.hw_token_label:
            self._update_hw_certificates([])
            return

        certs, err = list_token_certificates(
            module_path=self.hw_driver_path,
            slot_id=self.hw_token_slot_id,
            token_label=self.hw_token_label,
            user_pin=self.hw_pin or None,
        )
        if err or not certs:
            self._update_hw_certificates([], error_msg=err)
        else:
            self._update_hw_certificates(certs)

    def _update_hw_certificates(self, certs: List[Dict[str, Any]], error_msg: Optional[str] = None):
        self.available_certs = certs
        if certs:
            labels = []
            for c in certs:
                lbl = c.get("subject_cn") or c.get("label") or "Certificate"
                if c.get("is_qualified"):
                    lbl += " [Qualified Signing]"
                labels.append(lbl)
            self.hw_cert_combo.set_model(Gtk.StringList.new(labels))
            self.hw_cert_combo.set_selected(0)
            self._on_hw_cert_changed(self.hw_cert_combo, None)
        else:
            self.hw_cert_combo.set_model(Gtk.StringList.new([_("sig_hw_no_certs")]))
            self.hw_cert_label = None
            self.hw_cert_id = None
            self.hw_cert_info = None
            self.hw_status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.hw_status_row.set_title(_("sig_cert_status_title"))
            self.hw_status_row.set_subtitle(error_msg or _("sig_hw_no_certs"))
            self._verify_credentials()

    def _on_hw_cert_changed(self, combo, _param):
        idx = combo.get_selected()
        if 0 <= idx < len(self.available_certs):
            c = self.available_certs[idx]
            self.hw_cert_label = c.get("raw_label") or c.get("label") or None
            self.hw_cert_id = c.get("cert_id_bytes") or c.get("id") or None
            self.hw_cert_info = c
            self.hw_status_icon.set_from_icon_name("emblem-ok-symbolic")
            name = c.get("subject_cn") or "Hardware Signer"
            if c.get("is_qualified"):
                name += " [Qualified Signing / Non-Repudiation]"
            sub = f"Issuer: {c.get('issuer_cn', 'CA')}"
            expiry = c.get("not_after")
            if expiry:
                sub += f" | Valid to: {expiry.strftime('%Y-%m-%d') if hasattr(expiry, 'strftime') else expiry}"
            self.hw_status_row.set_title(name)
            self.hw_status_row.set_subtitle(sub)
        else:
            self.hw_cert_label = None
            self.hw_cert_id = None
            self.hw_cert_info = None
        self._verify_credentials()

    def _on_pades_profile_changed(self, combo, _param):
        idx = combo.get_selected()
        code, _ = self._pades_profiles[idx]
        needs_tsa = code in (PADES_B_T, PADES_B_LT, PADES_B_LTA)
        self.tsa_row.set_visible(needs_tsa)
        if needs_tsa:
            self._on_tsa_preset_changed(self.tsa_combo, None)
        else:
            self.custom_tsa_row.set_visible(False)
            self.tsa_auth_row.set_visible(False)

    def _on_tsa_preset_changed(self, combo, _param):
        idx = combo.get_selected()
        code, _ = self._tsa_presets[idx]
        is_custom = code == "custom"
        self.custom_tsa_row.set_visible(is_custom)
        self.tsa_auth_row.set_visible(is_custom)

    def _on_draw_canvas_clicked(self, button):
        self.destroy()
        if self.on_draw_canvas_requested:
            self.on_draw_canvas_requested()

    def _on_reason_combo_changed(self, combo):
        is_custom = combo.get_active() == 3
        self.custom_reason_row.set_visible(is_custom)

    def _on_certify_toggled(self, switch, _param):
        self.docmdp_row.set_visible(switch.get_active())

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
        if self.cert_source == "software":
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
        else:
            if self.hw_cert_info is not None:
                self.sign_btn.set_sensitive(True)
            else:
                self.sign_btn.set_sensitive(False)

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
        if self.cert_source == "software" and (not self.signer or not self.cert_info):
            return
        if self.cert_source == "hardware" and not self.hw_cert_info:
            return

        target_page = int(self.page_spin.get_value()) - 1
        pos_idx = self.position_combo.get_selected()
        pos_key = self._positions[pos_idx][0] if 0 <= pos_idx < len(self._positions) else "bottom_right"
        is_certify = self.certify_switch.get_active()
        docmdp_perm = (self.docmdp_combo.get_selected() + 1) if is_certify else None

        pades_idx = self.pades_combo.get_selected()
        pades_profile_code = self._pades_profiles[pades_idx][0]

        tsa_cfg = None
        if pades_profile_code in (PADES_B_T, PADES_B_LT, PADES_B_LTA):
            tsa_idx = self.tsa_combo.get_selected()
            tsa_preset_code = self._tsa_presets[tsa_idx][0]
            if tsa_preset_code == "digicert":
                tsa_cfg = TSAConfig(url=PRESET_TSAS["DigiCert"])
            elif tsa_preset_code == "freetsa":
                tsa_cfg = TSAConfig(url=PRESET_TSAS["FreeTSA"])
            elif tsa_preset_code == "sectigo":
                tsa_cfg = TSAConfig(url=PRESET_TSAS["Sectigo"])
            else:
                c_url = self.custom_tsa_entry.get_text().strip()
                u = self.tsa_user_entry.get_text().strip() or None
                p = self.tsa_pass_entry.get_text() or None
                if c_url:
                    tsa_cfg = TSAConfig(url=c_url, auth_user=u, auth_password=p)

        signer_cn = ""
        if self.cert_source == "software" and self.cert_info:
            signer_cn = self.cert_info.get("subject_cn", "")
        elif self.cert_source == "hardware" and self.hw_cert_info:
            signer_cn = self.hw_cert_info.get("subject_cn", "")

        options = {
            "cert_source": self.cert_source,
            "cert_path": self.cert_path,
            "cert_data": self.cert_data,
            "passphrase": self.passphrase,
            "signer": self.signer,
            "signer_name": signer_cn,
            "reason": self._get_reason(),
            "location": self.loc_entry.get_text().strip(),
            "contact_info": self.contact_entry.get_text().strip(),
            "visual_stamp": self.visible_switch.get_active(),
            "page_index": target_page,
            "position": pos_key,
            "box": self.initial_box if pos_key == "drawn_box" else None,
            "signature_image_bytes": self.image_bytes,
            "certify": is_certify,
            "docmdp_permissions": docmdp_perm,
            "pades_profile": pades_profile_code,
            "tsa_config": tsa_cfg,
            "pkcs11_driver": self.hw_driver_path if self.cert_source == "hardware" else None,
            "pkcs11_token_label": self.hw_token_label if self.cert_source == "hardware" else None,
            "pkcs11_slot_id": self.hw_token_slot_id if self.cert_source == "hardware" else None,
            "pkcs11_pin": self.hw_pin if self.cert_source == "hardware" else None,
            "pkcs11_cert_label": self.hw_cert_label if self.cert_source == "hardware" and self.hw_cert_label else None,
            "pkcs11_cert_id": self.hw_cert_id if self.cert_source == "hardware" and self.hw_cert_id else None,
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
        self.set_default_size(580, 620)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # HeaderBar with native window controls and Trust Store button
        header = Adw.HeaderBar()
        trust_btn = Gtk.Button()
        trust_btn.set_icon_name("channel-secure-symbolic")
        trust_btn.set_tooltip_text(_("trust_dialog_title"))
        trust_btn.connect("clicked", self._open_trust_store)
        header.pack_end(trust_btn)
        main_box.append(header)

        # Scrolled container
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
            is_valid = sig.get("valid", False)
            is_trusted = sig.get("trusted", False)

            if is_intact and is_valid:
                if is_trusted:
                    icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                    icon.add_css_class("success")
                    status_row.add_prefix(icon)
                    status_row.set_title(_("sig_status_valid"))
                    status_row.set_subtitle("Cryptographically intact and verified against trusted roots.")
                else:
                    icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
                    status_row.add_prefix(icon)
                    status_row.set_title("Cryptographically Valid (Untrusted Root)")
                    status_row.set_subtitle("Signature is intact, but the certificate authority is not in the trusted store.")
            else:
                icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
                icon.add_css_class("error")
                status_row.add_prefix(icon)
                status_row.set_title(_("sig_status_invalid"))
                status_row.set_subtitle(_("sig_status_invalid_desc"))
            status_row.set_subtitle_lines(0)
            group.add(status_row)

            # PAdES Profile Row
            profile = sig.get("pades_profile")
            if profile:
                prof_row = Adw.ActionRow()
                prof_row.set_title(_("sig_pades_profile"))
                prof_row.set_subtitle(str(profile))
                group.add(prof_row)

            # RFC 3161 TSA Timestamp Row
            if sig.get("tsa_timestamp") or sig.get("tsa_valid") is not None:
                tsa_row = Adw.ActionRow()
                tsa_row.set_title(_("sig_tsa_server"))
                ts_time = sig.get("tsa_timestamp")
                ts_str = ts_time.strftime("%Y-%m-%d %H:%M:%S %Z") if hasattr(ts_time, "strftime") else str(ts_time or "")
                tsa_cn = sig.get("tsa_cn") or "TSA"
                valid_txt = " (Cryptographically Intact)" if sig.get("tsa_valid") else ""
                tsa_row.set_subtitle(f"{tsa_cn}: {ts_str}{valid_txt}")
                group.add(tsa_row)

            # Certification / DocMDP Row
            if sig.get("is_certification", False):
                cert_row = Adw.ActionRow()
                cert_row.set_title("Document Certification (DocMDP)")
                perm_name = sig.get("docmdp_permission_name") or "NO_CHANGES"
                perm_level = sig.get("docmdp_permission") or 1
                cert_row.set_subtitle(f"Level {perm_level}: {perm_name}")
                group.add(cert_row)

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

            # Contact / Email
            contact = sig.get("contact_info")
            if contact:
                contact_row = Adw.ActionRow()
                contact_row.set_title(_("sig_contact"))
                contact_row.set_subtitle(contact)
                group.add(contact_row)

            # Adobe LTV Status
            ltv_row = Adw.ActionRow()
            ltv_row.set_title("Long-Term Validation (LTV)")
            if sig.get("has_ltv", False):
                ltv_row.set_subtitle("Enabled (Embedded revocation information in /DSS)")
            elif sig.get("has_dss", False):
                ltv_row.set_subtitle("Present in Document Security Store (/DSS)")
            else:
                ltv_row.set_subtitle("Not embedded (Document valid at time of signing)")
            group.add(ltv_row)

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

            # Export Public Certificate Row
            if sig.get("cert_der") or sig.get("cert_pem"):
                export_row = Adw.ActionRow()
                export_row.set_title(_("sig_export_cert_title"))
                export_btn = Gtk.Button(label=_("sig_btn_export_cert"))
                export_btn.set_valign(Gtk.Align.CENTER)
                export_btn.connect("clicked", lambda b, s=sig: self._export_certificate(s))
                export_row.add_suffix(export_btn)
                group.add(export_row)

    def _export_certificate(self, sig: Dict[str, Any]):
        signer = sig.get("signer_cn") or "certificate"
        clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in signer).strip("_")
        initial_name = f"{clean_name or 'certificate'}.cer"

        f_cer = Gtk.FileFilter()
        f_cer.set_name("DER Encoded Certificate (*.cer, *.crt)")
        f_cer.add_pattern("*.cer")
        f_cer.add_pattern("*.crt")

        f_pem = Gtk.FileFilter()
        f_pem.set_name("PEM Certificate (*.pem)")
        f_pem.add_pattern("*.pem")

        f_all = Gtk.FileFilter()
        f_all.set_name(_("filter_all_files"))
        f_all.add_pattern("*")

        def on_save_finish(gfile, chosen_filter=None):
            if not gfile:
                return
            save_path = gfile.get_path()
            if not save_path:
                return

            is_pem = save_path.lower().endswith(".pem") or (chosen_filter and chosen_filter.get_name() == f_pem.get_name())
            try:
                if is_pem and sig.get("cert_pem"):
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(sig["cert_pem"])
                elif sig.get("cert_der"):
                    with open(save_path, "wb") as f:
                        f.write(sig["cert_der"])
                elif sig.get("cert_pem"):
                    with open(save_path, "w", encoding="utf-8") as f:
                        f.write(sig["cert_pem"])

                if hasattr(self.parent_window, "toast_overlay") and self.parent_window.toast_overlay:
                    self.parent_window.toast_overlay.add_toast(Adw.Toast(title=_("sig_export_cert_success")))
            except Exception:
                pass

        show_save_file_dialog(
            self,
            _("sig_export_cert_title"),
            initial_name=initial_name,
            filters=[f_cer, f_pem, f_all],
            default_filter=f_cer,
            callback=on_save_finish,
        )

    def _open_trust_store(self, _button):
        """Open the Certificate Trust Store dialog."""
        from .trust_dialog import TrustStoreDialog
        dlg = TrustStoreDialog(parent_window=self)
        dlg.present()
