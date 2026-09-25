import gi
import random
from pathlib import Path

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk, Pango

from . import constants
from .i18n import _, get_language, set_language, get_supported_languages, get_setting, set_setting


class WelcomeView(Adw.Bin):
    """The start screen view showing recent files, quick guide, and language settings."""
    def __init__(self, parent_window, **kwargs):
        """Initialise the WelcomeView and load recent files."""
        super().__init__(**kwargs)
        self.parent_window = parent_window

        self._build_ui()
        self._populate_recent_files()

    def _build_ui(self):
        """Build widgets for the welcome screen layout."""
        clamp = Adw.Clamp(maximum_size=800, tightening_threshold=300)
        self.set_child(clamp)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        main_box.set_vexpand(True)
        main_box.set_valign(Gtk.Align.CENTER)
        clamp.set_child(main_box)
        main_box.set_margin_bottom(40)

        try:
            app_icon = Gtk.Image.new_from_icon_name("f-pv1")
            app_icon.set_pixel_size(200)
            app_icon.set_valign(Gtk.Align.END)
            app_icon.set_halign(Gtk.Align.CENTER)
            app_icon.set_margin_bottom(20)
            main_box.append(app_icon)
        except Exception as e:
            print(f"Welcome screen icon could not be loaded: {e}")

        title = Gtk.Label(label=constants.APP_NAME)
        title.add_css_class("title-1")
        main_box.append(title)

        subtitle = Gtk.Label(label=_("app_subtitle"))
        subtitle.add_css_class("dim-label")
        main_box.append(subtitle)

        lang_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        lang_box.set_margin_top(4)

        lang_icon = Gtk.Image.new_from_icon_name("preferences-desktop-locale-symbolic")
        lang_box.append(lang_icon)

        lang_label = Gtk.Label(label=_("lang_label"))
        lang_label.add_css_class("dim-label")
        lang_box.append(lang_label)

        self._languages = get_supported_languages()
        lang_names = [name for _, name in self._languages]
        self._lang_dropdown = Gtk.DropDown.new_from_strings(lang_names)
        self._lang_dropdown.add_css_class("flat")

        cur_lang = get_language()
        cur_idx = 0
        for i, (code, lang_title) in enumerate(self._languages):
            if code == cur_lang:
                cur_idx = i
                break
        self._lang_dropdown.set_selected(cur_idx)
        self._lang_dropdown_handler_id = self._lang_dropdown.connect("notify::selected", self._on_lang_selected)
        lang_box.append(self._lang_dropdown)

        main_box.append(lang_box)

        button_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER
        )
        button_box.set_margin_top(16)
        main_box.append(button_box)

        new_button = Gtk.Button(label=_("btn_new"))
        new_button.set_tooltip_text(f"{_('btn_new')} (Ctrl+N)")
        new_button.set_action_name("win.new")
        button_box.append(new_button)

        open_button = Gtk.Button(label=_("btn_open"))
        open_button.get_style_context().add_class("suggested-action")
        open_button.set_tooltip_text(f"{_('btn_open')} (Ctrl+O)")
        open_button.set_action_name("win.open")
        button_box.append(open_button)

        guide_button = Gtk.Button(label=_("btn_guide"))
        guide_button.set_tooltip_text(f"{_('btn_guide')} (F1)")
        guide_button.set_action_name("win.quick_guide")
        button_box.append(guide_button)

        recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        recent_box.set_margin_top(30)
        main_box.append(recent_box)

        recent_label = Gtk.Label(label=_("recent_header"))
        recent_label.set_use_markup(True)
        recent_label.set_halign(Gtk.Align.START)
        recent_box.append(recent_label)

        self.recent_list_box = Gtk.ListBox()
        self.recent_list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.recent_list_box.add_css_class("boxed-list")
        self.recent_list_box.connect("row-activated", self._on_recent_row_activated)

        self.recent_scroll = Gtk.ScrolledWindow()
        self.recent_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.recent_scroll.set_max_content_height(180)
        self.recent_scroll.set_propagate_natural_height(True)
        self.recent_scroll.set_child(self.recent_list_box)
        
        recent_box.append(self.recent_scroll)
        self.recent_box = recent_box

        tips = _("tips")
        tip_text = random.choice(tips) if isinstance(tips, list) else str(tips)
        tip_label = Gtk.Label(label=tip_text)
        tip_label.add_css_class("dim-label")
        tip_label.set_halign(Gtk.Align.CENTER)
        tip_label.set_wrap(True)
        tip_label.set_margin_top(40)
        main_box.append(tip_label)

    def _on_lang_selected(self, dropdown, _param):
        """Handle language selection change from dropdown."""
        idx = dropdown.get_selected()
        if 0 <= idx < len(self._languages):
            lang_code = self._languages[idx][0]
            if lang_code != get_language():
                self._confirm_language_switch(lang_code)

    def _set_dropdown_lang_code(self, lang_code):
        """Revert or update dropdown selection without triggering signal callback."""
        target_idx = 0
        for i, (code, lang_title) in enumerate(self._languages):
            if code == lang_code:
                target_idx = i
                break
        if self._lang_dropdown.get_selected() != target_idx:
            self._lang_dropdown.handler_block(self._lang_dropdown_handler_id)
            self._lang_dropdown.set_selected(target_idx)
            self._lang_dropdown.handler_unblock(self._lang_dropdown_handler_id)

    def _confirm_language_switch(self, lang_code):
        """Confirm language switch."""
        from gi.repository import Gtk
        from .ui_components import show_confirm_dialog

        if self.parent_window.doc and self.parent_window.document_modified:
            if not show_confirm_dialog(
                self.parent_window,
                _("unsaved_changes"),
                _("unsaved_title"),
                destructive=False,
            ):
                self._set_dropdown_lang_code(get_language())
                return

        dialog = Gtk.MessageDialog(
            transient_for=self.parent_window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=_("lang_restart_title") + "\n\n" + _("lang_restart_msg"),
        )

        def on_response(d, response_id):
            """Handle the dialog response event."""
            d.destroy()
            if response_id == Gtk.ResponseType.OK:
                set_language(lang_code)
            else:
                self._set_dropdown_lang_code(get_language())

        dialog.connect("response", on_response)
        dialog.present()

    def refresh_recent_files(self):
        """Public helper to refresh the recent files list."""
        self._populate_recent_files()

    def _populate_recent_files(self, *args):
        """Populate the list of recently opened PDF files from settings."""
        child = self.recent_list_box.get_first_child()
        while child:
            self.recent_list_box.remove(child)
            child = self.recent_list_box.get_first_child()

        recent_files = get_setting("recent_opened_files", [])
        if not isinstance(recent_files, list):
            recent_files = []

        valid_files = []
        for file_path_str in recent_files:
            if not file_path_str or not isinstance(file_path_str, str):
                continue
            p = Path(file_path_str)
            if p.is_file():
                valid_files.append(file_path_str)

        if len(valid_files) != len(recent_files):
            set_setting("recent_opened_files", valid_files)

        displayed_count = 0
        for file_path_str in valid_files[:15]:
            row = self._create_recent_file_row(file_path_str)
            self.recent_list_box.append(row)
            displayed_count += 1

        self.recent_box.set_visible(displayed_count > 0)

    def _create_recent_file_row(self, file_path_str):
        """Create a list row widget for a recent file entry with universal document icon."""
        row = Gtk.ListBoxRow()
        row._file_path = str(file_path_str)
        try:
            row._uri = Path(file_path_str).as_uri()
        except Exception:
            row._uri = ""
        row.set_activatable(True)

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_start=12,
            margin_end=12,
            margin_top=8,
            margin_bottom=8,
        )

        icon = Gio.ThemedIcon.new_from_names([
            "application-pdf-symbolic",
            "x-office-document-symbolic",
            "text-x-generic-symbolic",
            "application-x-generic-symbolic",
            "document-symbolic",
        ])
        icon_img = Gtk.Image.new_from_gicon(icon)
        icon_img.set_pixel_size(28)
        icon_img.set_valign(Gtk.Align.CENTER)
        icon_img.add_css_class("accent")
        box.append(icon_img)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        file_path = Path(file_path_str)
        filename = file_path.name
        title_lbl = Gtk.Label(label=filename, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        title_lbl.add_css_class("heading")
        vbox.append(title_lbl)

        subtitle_text = str(file_path.parent)
        subtitle_lbl = Gtk.Label(label=subtitle_text, xalign=0.0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        subtitle_lbl.add_css_class("dim-label")
        subtitle_lbl.add_css_class("caption")
        vbox.append(subtitle_lbl)

        box.append(vbox)
        row.set_child(box)
        return row

    def on_open_clicked(self, button):
        """Handle open button clicks by delegating to parent window."""
        if self.parent_window:
            self.parent_window.on_open_clicked(button)

    def _on_recent_row_activated(self, list_box, row):
        """Handle recent file row activation."""
        if not self.parent_window:
            return
        if hasattr(row, '_file_path') and row._file_path:
            self.parent_window.load_document(row._file_path)
        elif hasattr(row, '_uri') and row._uri:
            gfile = Gio.File.new_for_uri(row._uri)
            self.parent_window.load_document(gfile.get_path())