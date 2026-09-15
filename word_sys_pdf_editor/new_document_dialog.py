import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw, GLib
from .i18n import _

PRESET_SPECS = [
    ("preset_a4", 595.28, 841.89),         # A4 (210 x 297 mm)
    ("preset_a3", 841.89, 1190.55),        # A3 (297 x 420 mm)
    ("preset_a5", 419.53, 595.28),         # A5 (148 x 210 mm)
    ("preset_a6", 297.64, 419.53),         # A6 (105 x 148 mm)
    ("preset_a2", 1190.55, 1683.78),       # A2 (420 x 594 mm)
    ("preset_a1", 1683.78, 2383.94),       # A1 (594 x 841 mm)
    ("preset_a0", 2383.94, 3370.39),       # A0 (841 x 1189 mm)
    ("preset_b4", 708.66, 1000.63),        # B4 (250 x 353 mm)
    ("preset_b5", 498.90, 708.66),         # B5 (176 x 250 mm)
    ("preset_letter", 612.0, 792.0),       # US Letter (8.5 x 11 in)
    ("preset_legal", 612.0, 1008.0),       # US Legal (8.5 x 14 in)
    ("preset_executive", 522.0, 756.0),    # US Executive (7.25 x 10.5 in)
    ("preset_tabloid", 792.0, 1224.0),     # Tabloid / Ledger (11 x 17 in)
    ("preset_slide_16_9", 1920.0, 1080.0), # Slide 16:9
    ("preset_slide_16_10", 1920.0, 1200.0),# Slide 16:10
    ("preset_slide_4_3", 1024.0, 768.0),   # Slide 4:3
    ("preset_square", 1080.0, 1080.0),     # Square (1:1)
    ("preset_custom", None, None),         # Custom...
]

CUSTOM_PRESET_INDEX = len(PRESET_SPECS) - 1

UNITS = [
    {"id": "mm", "key": "new_doc_unit_mm", "factor": 72.0 / 25.4, "digits": 1, "step": 1.0, "min": 10.0, "max": 5000.0},
    {"id": "cm", "key": "new_doc_unit_cm", "factor": 72.0 / 2.54, "digits": 2, "step": 0.5, "min": 1.0, "max": 500.0},
    {"id": "in", "key": "new_doc_unit_in", "factor": 72.0, "digits": 2, "step": 0.25, "min": 0.5, "max": 200.0},
    {"id": "pt", "key": "new_doc_unit_pt", "factor": 1.0, "digits": 1, "step": 1.0, "min": 20.0, "max": 14400.0},
    {"id": "px", "key": "new_doc_unit_px", "factor": 1.0, "digits": 0, "step": 1.0, "min": 20.0, "max": 14400.0},
]


class NewDocumentDialog(Adw.Window):
    """Modern Libadwaita modal dialog for creating documents with custom dimensions."""

    def __init__(self, parent_window, on_create_callback):
        super().__init__()
        self.parent_window = parent_window
        self.on_create_callback = on_create_callback
        self._is_updating = False
        self._current_unit_idx = 0

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("new_doc_dialog_title"))
        self.set_default_size(470, 560)
        self.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("new_doc_cancel"))
        self.cancel_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(self.cancel_btn)

        self.create_btn = Gtk.Button(label=_("new_doc_create"))
        self.create_btn.add_css_class("suggested-action")
        self.create_btn.connect("clicked", self._on_create_clicked)
        header.pack_end(self.create_btn)
        main_box.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=430)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(content_box)

        group_setup = Adw.PreferencesGroup()
        group_setup.set_title(_("new_doc_page_setup"))
        content_box.append(group_setup)

        preset_names = [_(spec[0]) for spec in PRESET_SPECS]
        self.preset_model = Gtk.StringList.new(preset_names)
        self.preset_row = Adw.ComboRow()
        self.preset_row.set_title(_("new_doc_template"))
        self.preset_row.set_model(self.preset_model)
        self.preset_row.set_selected(0)
        self.preset_row.connect("notify::selected", self._on_preset_changed)
        group_setup.add(self.preset_row)

        self.orient_row = Adw.ActionRow()
        self.orient_row.set_title(_("new_doc_orientation"))

        orient_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        orient_box.add_css_class("linked")
        orient_box.set_valign(Gtk.Align.CENTER)

        self.portrait_btn = Gtk.ToggleButton()
        port_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        port_box.append(Gtk.Image.new_from_icon_name("document-page-setup-symbolic"))
        port_box.append(Gtk.Label(label=_("new_doc_portrait")))
        self.portrait_btn.set_child(port_box)
        self.portrait_btn.set_tooltip_text(_("new_doc_portrait"))

        self.landscape_btn = Gtk.ToggleButton()
        land_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        land_box.append(Gtk.Image.new_from_icon_name("object-flip-horizontal-symbolic"))
        land_box.append(Gtk.Label(label=_("new_doc_landscape")))
        self.landscape_btn.set_child(land_box)
        self.landscape_btn.set_tooltip_text(_("new_doc_landscape"))

        self.landscape_btn.set_group(self.portrait_btn)
        self.portrait_btn.set_active(True)

        self.portrait_btn.connect("toggled", self._on_orientation_toggled)
        self.landscape_btn.connect("toggled", self._on_orientation_toggled)

        orient_box.append(self.portrait_btn)
        orient_box.append(self.landscape_btn)
        self.orient_row.add_suffix(orient_box)
        group_setup.add(self.orient_row)

        group_dim = Adw.PreferencesGroup()
        group_dim.set_title(_("new_doc_dimensions"))
        content_box.append(group_dim)

        unit_names = [_(u["key"]) for u in UNITS]
        self.unit_model = Gtk.StringList.new(unit_names)
        self.unit_row = Adw.ComboRow()
        self.unit_row.set_title(_("new_doc_unit"))
        self.unit_row.set_model(self.unit_model)
        self.unit_row.set_selected(0)
        self.unit_row.connect("notify::selected", self._on_unit_changed)
        group_dim.add(self.unit_row)

        self.width_row = Adw.ActionRow()
        self.width_row.set_title(_("new_doc_width"))
        self.width_spin = Gtk.SpinButton.new_with_range(10.0, 5000.0, 1.0)
        self.width_spin.set_digits(1)
        self.width_spin.set_valign(Gtk.Align.CENTER)
        self.width_spin.set_value(210.0)
        self.width_spin.connect("value-changed", self._on_dim_spin_changed)
        self.width_row.add_suffix(self.width_spin)
        group_dim.add(self.width_row)

        self.height_row = Adw.ActionRow()
        self.height_row.set_title(_("new_doc_height"))
        self.height_spin = Gtk.SpinButton.new_with_range(10.0, 5000.0, 1.0)
        self.height_spin.set_digits(1)
        self.height_spin.set_valign(Gtk.Align.CENTER)
        self.height_spin.set_value(297.0)
        self.height_spin.connect("value-changed", self._on_dim_spin_changed)
        self.height_row.add_suffix(self.height_spin)
        group_dim.add(self.height_row)

        group_doc = Adw.PreferencesGroup()
        group_doc.set_title(_("new_doc_document"))
        content_box.append(group_doc)

        self.pages_row = Adw.ActionRow()
        self.pages_row.set_title(_("new_doc_num_pages"))
        self.pages_row.set_subtitle(_("new_doc_pages_desc"))
        self.pages_spin = Gtk.SpinButton.new_with_range(1, 500, 1)
        self.pages_spin.set_digits(0)
        self.pages_spin.set_valign(Gtk.Align.CENTER)
        self.pages_spin.set_value(1)
        self.pages_spin.connect("value-changed", lambda s: self._update_summary_info())
        self.pages_row.add_suffix(self.pages_spin)
        group_doc.add(self.pages_row)

        self.summary_label = Gtk.Label()
        self.summary_label.add_css_class("dim-label")
        self.summary_label.set_wrap(True)
        self.summary_label.set_justify(Gtk.Justification.CENTER)
        self.summary_label.set_margin_top(4)
        content_box.append(self.summary_label)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        self._update_summary_info()

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._on_create_clicked(None)
            return True
        return False

    def _on_preset_changed(self, combo, param):
        if self._is_updating:
            return
        idx = combo.get_selected()
        if idx >= len(PRESET_SPECS) or idx == CUSTOM_PRESET_INDEX:
            return

        base_w_pt, base_h_pt = PRESET_SPECS[idx][1], PRESET_SPECS[idx][2]
        if base_w_pt is None or base_h_pt is None:
            return

        is_landscape = self.landscape_btn.get_active()
        if is_landscape:
            w_pt = max(base_w_pt, base_h_pt)
            h_pt = min(base_w_pt, base_h_pt)
        else:
            w_pt = min(base_w_pt, base_h_pt)
            h_pt = max(base_w_pt, base_h_pt)

        unit = UNITS[self._current_unit_idx]
        w_val = w_pt / unit["factor"]
        h_val = h_pt / unit["factor"]

        self._is_updating = True
        self.width_spin.set_value(round(w_val, unit["digits"]))
        self.height_spin.set_value(round(h_val, unit["digits"]))
        self._is_updating = False
        self._update_summary_info()

    def _on_orientation_toggled(self, button):
        if self._is_updating or not button.get_active():
            return

        is_landscape = self.landscape_btn.get_active()
        w = self.width_spin.get_value()
        h = self.height_spin.get_value()

        if is_landscape and w < h:
            self._is_updating = True
            self.width_spin.set_value(h)
            self.height_spin.set_value(w)
            self._is_updating = False
        elif not is_landscape and w > h:
            self._is_updating = True
            self.width_spin.set_value(h)
            self.height_spin.set_value(w)
            self._is_updating = False

        self._update_summary_info()

    def _on_unit_changed(self, combo, param):
        if self._is_updating:
            return
        new_idx = combo.get_selected()
        if new_idx == self._current_unit_idx or new_idx >= len(UNITS):
            return

        old_unit = UNITS[self._current_unit_idx]
        new_unit = UNITS[new_idx]

        w_pt = self.width_spin.get_value() * old_unit["factor"]
        h_pt = self.height_spin.get_value() * old_unit["factor"]

        new_w = w_pt / new_unit["factor"]
        new_h = h_pt / new_unit["factor"]

        self._is_updating = True
        self._current_unit_idx = new_idx

        self.width_spin.set_range(new_unit["min"], new_unit["max"])
        self.width_spin.set_increments(new_unit["step"], new_unit["step"] * 10)
        self.width_spin.set_digits(new_unit["digits"])
        self.width_spin.set_value(round(new_w, new_unit["digits"]))

        self.height_spin.set_range(new_unit["min"], new_unit["max"])
        self.height_spin.set_increments(new_unit["step"], new_unit["step"] * 10)
        self.height_spin.set_digits(new_unit["digits"])
        self.height_spin.set_value(round(new_h, new_unit["digits"]))

        self._is_updating = False
        self._update_summary_info()

    def _on_dim_spin_changed(self, spin):
        if self._is_updating:
            return

        w = self.width_spin.get_value()
        h = self.height_spin.get_value()

        is_landscape = w > h
        self._is_updating = True
        if is_landscape and not self.landscape_btn.get_active():
            self.landscape_btn.set_active(True)
        elif not is_landscape and not self.portrait_btn.get_active():
            self.portrait_btn.set_active(True)

        unit = UNITS[self._current_unit_idx]
        curr_w_pt = w * unit["factor"]
        curr_h_pt = h * unit["factor"]

        matched_idx = CUSTOM_PRESET_INDEX
        for i in range(len(PRESET_SPECS) - 1):
            spec_w, spec_h = PRESET_SPECS[i][1], PRESET_SPECS[i][2]
            target_w = max(spec_w, spec_h) if is_landscape else min(spec_w, spec_h)
            target_h = min(spec_w, spec_h) if is_landscape else max(spec_w, spec_h)
            if abs(curr_w_pt - target_w) <= 1.0 and abs(curr_h_pt - target_h) <= 1.0:
                matched_idx = i
                break

        if self.preset_row.get_selected() != matched_idx:
            self.preset_row.set_selected(matched_idx)

        self._is_updating = False
        self._update_summary_info()

    def _update_summary_info(self):
        unit = UNITS[self._current_unit_idx]
        w_val = self.width_spin.get_value()
        h_val = self.height_spin.get_value()
        w_pt = w_val * unit["factor"]
        h_pt = h_val * unit["factor"]
        orient_str = _("new_doc_landscape") if w_val > h_val else _("new_doc_portrait")
        pages = int(self.pages_spin.get_value())
        pages_str = f"{pages} {'Page' if pages == 1 else 'Pages'}"

        text = f"{w_val:.1f} × {h_val:.1f} {unit['id']} ({w_pt:.0f} × {h_pt:.0f} pt) • {orient_str} • {pages_str}"
        self.summary_label.set_text(text)

    def _on_create_clicked(self, button):
        unit = UNITS[self._current_unit_idx]
        w_pt = self.width_spin.get_value() * unit["factor"]
        h_pt = self.height_spin.get_value() * unit["factor"]
        pages = int(self.pages_spin.get_value())

        self.destroy()
        if self.on_create_callback:
            self.on_create_callback(w_pt, h_pt, pages)


def show_new_document_dialog(parent_window, on_create_callback):
    """Present the new document dialog."""
    dialog = NewDocumentDialog(parent_window, on_create_callback)
    dialog.present()
