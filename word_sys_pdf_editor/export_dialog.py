import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
from .i18n import _

FORMAT_ITEMS = [
    ("DOCX", "export_format_docx"),
    ("PPTX", "export_format_pptx"),
    ("ODT", "export_format_odt"),
    ("ODP", "export_format_odp"),
    ("TXT", "export_format_txt"),
]


class ExportDialog(Adw.Window):
    """Modern Libadwaita modal dialog for document export options."""

    def __init__(self, parent_window, initial_format="DOCX", initial_mode="canvas", on_confirm_callback=None):
        super().__init__()
        self.parent_window = parent_window
        self.on_confirm_callback = on_confirm_callback

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("export_dialog_title"))
        self.set_default_size(500, 440)
        self.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(self.cancel_btn)

        self.export_btn = Gtk.Button(label=_("export_btn_choose"))
        self.export_btn.add_css_class("suggested-action")
        self.export_btn.connect("clicked", self._on_export_clicked)
        header.pack_end(self.export_btn)
        main_box.append(header)

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

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(content_box)

        # Target Format Group
        group_format = Adw.PreferencesGroup()
        group_format.set_title(_("export_format_title"))
        content_box.append(group_format)

        fmt_labels = [_(item[1]) for item in FORMAT_ITEMS]
        self.format_model = Gtk.StringList.new(fmt_labels)
        self.format_row = Adw.ComboRow()
        self.format_row.set_title(_("export_format_title"))
        self.format_row.set_model(self.format_model)
        self.format_row.connect("notify::selected", self._on_format_changed)
        group_format.add(self.format_row)

        # Layout Mode Group
        self.layout_group = Adw.PreferencesGroup()
        self.layout_group.set_title(_("export_layout_mode_title"))
        content_box.append(self.layout_group)

        # Canvas mode row
        self.canvas_row = Adw.ActionRow()
        self.canvas_row.set_title(GLib.markup_escape_text(_("export_mode_canvas")))
        self.canvas_row.set_subtitle(GLib.markup_escape_text(_("export_mode_canvas_desc")))

        self.canvas_radio = Gtk.CheckButton()
        self.canvas_radio.set_valign(Gtk.Align.CENTER)
        self.canvas_row.add_prefix(self.canvas_radio)
        self.canvas_row.set_activatable_widget(self.canvas_radio)
        self.layout_group.add(self.canvas_row)

        # Flow mode row
        self.flow_row = Adw.ActionRow()
        self.flow_row.set_title(GLib.markup_escape_text(_("export_mode_flow")))
        self.flow_row.set_subtitle(GLib.markup_escape_text(_("export_mode_flow_desc")))

        self.flow_radio = Gtk.CheckButton()
        self.flow_radio.set_valign(Gtk.Align.CENTER)
        self.flow_radio.set_group(self.canvas_radio)
        self.flow_row.add_prefix(self.flow_radio)
        self.flow_row.set_activatable_widget(self.flow_radio)
        self.layout_group.add(self.flow_row)

        # Set initial values
        initial_fmt_upper = str(initial_format).upper().strip()
        matched_fmt = False
        for idx, (fmt_key, item_label_key) in enumerate(FORMAT_ITEMS):
            if fmt_key == initial_fmt_upper:
                self.format_row.set_selected(idx)
                matched_fmt = True
                break
        if not matched_fmt:
            self.format_row.set_selected(0)

        if str(initial_mode).lower().strip() == "flow":
            self.flow_radio.set_active(True)
        else:
            self.canvas_radio.set_active(True)

        self._update_layout_sensitivity()

    def _on_format_changed(self, row, pspec):
        self._update_layout_sensitivity()

    def _update_layout_sensitivity(self):
        is_txt = (self.get_selected_format() == "TXT")
        self.layout_group.set_sensitive(not is_txt)

    def get_selected_format(self) -> str:
        """Return selected format string (e.g. 'DOCX', 'PPTX', 'ODT', 'ODP', 'TXT')."""
        idx = self.format_row.get_selected()
        if 0 <= idx < len(FORMAT_ITEMS):
            return FORMAT_ITEMS[idx][0]
        return "DOCX"

    def get_selected_mode(self) -> str:
        """Return selected layout mode ('canvas' or 'flow')."""
        if self.get_selected_format() == "TXT":
            return "canvas"
        return "flow" if self.flow_radio.get_active() else "canvas"

    def _on_export_clicked(self, button):
        selected_format = self.get_selected_format()
        selected_mode = self.get_selected_mode()
        callback = self.on_confirm_callback
        self.destroy()
        if callback and callable(callback):
            callback(selected_format, selected_mode)
