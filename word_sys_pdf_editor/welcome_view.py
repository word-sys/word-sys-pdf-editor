import gi
import random
import os
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
        overlay = Gtk.Overlay()
        self.set_child(overlay)

        clamp = Adw.Clamp(maximum_size=800, tightening_threshold=300)
        overlay.set_child(clamp)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        main_box.set_vexpand(True)
        main_box.set_valign(Gtk.Align.CENTER)
        clamp.set_child(main_box)
        main_box.set_margin_bottom(40)

        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top_bar.set_halign(Gtk.Align.END)
        top_bar.set_valign(Gtk.Align.START)
        top_bar.set_margin_top(16)
        top_bar.set_margin_end(20)

        self._languages = get_supported_languages()
        cur_lang = get_language()
        cur_name = dict(self._languages).get(cur_lang, "English")

        self.lang_menu_btn = Gtk.MenuButton()
        self.lang_menu_btn.add_css_class("pill")
        self.lang_menu_btn.add_css_class("flat")
        self.lang_menu_btn.set_tooltip_text(_("lang_label"))

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lang_icon = Gtk.Image.new_from_icon_name("preferences-desktop-locale-symbolic")
        self.lang_btn_label = Gtk.Label(label=cur_name)
        chevron = Gtk.Image.new_from_icon_name("pan-down-symbolic")
        btn_box.append(lang_icon)
        btn_box.append(self.lang_btn_label)
        btn_box.append(chevron)
        self.lang_menu_btn.set_child(btn_box)

        lang_menu = Gio.Menu()
        for code, name in self._languages:
            lang_item = Gio.MenuItem.new(name, f"win.change_language('{code}')")
            lang_menu.append_item(lang_item)
        self.lang_menu_btn.set_menu_model(lang_menu)
        self._lang_dropdown = self.lang_menu_btn

        top_bar.append(self.lang_menu_btn)
        overlay.add_overlay(top_bar)

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

        button_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER
        )
        button_box.set_margin_top(16)
        main_box.append(button_box)

        has_open_docs = bool(
            hasattr(self.parent_window, 'sessions') and
            any(s.doc is not None for s in self.parent_window.sessions)
        )
        if has_open_docs:
            return_button = Gtk.Button(label=_("btn_return_to_workspace"))
            return_button.connect("clicked", lambda b: self.parent_window.go_to_welcome())
            button_box.append(return_button)

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

    def update_language_display(self, lang_code: str):
        """Update the language pill button label when language changes."""
        cur_name = dict(self._languages).get(lang_code, "English")
        if hasattr(self, "lang_btn_label"):
            self.lang_btn_label.set_text(cur_name)

    def _set_dropdown_lang_code(self, lang_code: str):
        self.update_language_display(lang_code)

    def _confirm_language_switch(self, lang_code: str):
        if hasattr(self.parent_window, "request_language_change"):
            self.parent_window.request_language_change(lang_code)
        else:
            set_language(lang_code)

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
            try:
                from .pdf_handler import get_disk_thumbnail_cache
                get_disk_thumbnail_cache().prune_orphaned_thumbnails()
            except Exception:
                pass

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
        path = None
        if hasattr(row, '_file_path') and row._file_path:
            path = row._file_path
        elif hasattr(row, '_uri') and row._uri:
            gfile = Gio.File.new_for_uri(row._uri)
            path = gfile.get_path()
        if path:
            if not os.path.isfile(path):
                self._populate_recent_files()
                return
            self.parent_window.load_document(path)