from pathlib import Path
import gi
try:
    import pymupdf as fitz
except ImportError:
    import fitz

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, Adw, Gio, GLib, Pango, GdkPixbuf

from .i18n import _
from . import pdf_handler
from .ui_components import show_open_file_dialog, show_error_dialog


class PagePreviewDialog(Adw.Window):
    def __init__(self, parent_window, doc, page_index: int, source_role: str = "", file_path: str = "", on_add_callback=None):
        super().__init__()
        self.parent_window = parent_window
        self.doc = doc
        self.current_page_idx = page_index
        self.source_role = source_role
        self.file_path = file_path
        self.on_add_callback = on_add_callback
        self.zoom_level = 1.0

        self.set_transient_for(parent_window)
        self.set_modal(True)
        title_name = Path(file_path).name if file_path else _("merge_preview_page")
        self.set_title(f"{title_name} - {_('merge_preview_page')}")
        self.set_default_size(840, 780)
        self.set_size_request(440, 400)
        self.set_resizable(True)

        self._build_ui()
        self._render_current_page()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        close_btn = Gtk.Button(label=_("btn_cancel"))
        close_btn.connect("clicked", lambda b: self.close())
        header.pack_start(close_btn)

        self.prev_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.prev_btn.set_tooltip_text(_("prev_page_tip"))
        self.prev_btn.add_css_class("flat")
        self.prev_btn.connect("clicked", lambda b: self._go_page(self.current_page_idx - 1))
        header.pack_start(self.prev_btn)

        self.page_info_lbl = Gtk.Label(label="")
        self.page_info_lbl.add_css_class("heading")
        header.pack_start(self.page_info_lbl)

        self.next_btn = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_btn.set_tooltip_text(_("next_page_tip"))
        self.next_btn.add_css_class("flat")
        self.next_btn.connect("clicked", lambda b: self._go_page(self.current_page_idx + 1))
        header.pack_start(self.next_btn)

        if self.on_add_callback:
            add_btn = Gtk.Button(label=_("merge_add_page"))
            add_btn.add_css_class("suggested-action")
            add_btn.connect("clicked", self._on_add_clicked)
            header.pack_end(add_btn)

        zoom_fit_btn = Gtk.Button.new_from_icon_name("zoom-fit-best-symbolic")
        zoom_fit_btn.set_tooltip_text(_("merge_zoom_fit"))
        zoom_fit_btn.add_css_class("flat")
        zoom_fit_btn.connect("clicked", lambda b: self._zoom_fit())
        header.pack_end(zoom_fit_btn)

        zoom_in_btn = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        zoom_in_btn.set_tooltip_text(_("merge_zoom_in"))
        zoom_in_btn.add_css_class("flat")
        zoom_in_btn.connect("clicked", lambda b: self._set_zoom(self.zoom_level + 0.25))
        header.pack_end(zoom_in_btn)

        self.zoom_lbl = Gtk.Label(label="100%")
        self.zoom_lbl.add_css_class("caption")
        self.zoom_lbl.add_css_class("dim-label")
        header.pack_end(self.zoom_lbl)

        zoom_out_btn = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        zoom_out_btn.set_tooltip_text(_("merge_zoom_out"))
        zoom_out_btn.add_css_class("flat")
        zoom_out_btn.connect("clicked", lambda b: self._set_zoom(self.zoom_level - 0.25))
        header.pack_end(zoom_out_btn)

        main_box.append(header)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.set_hexpand(True)

        self.pic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.pic_box.set_margin_top(16)
        self.pic_box.set_margin_bottom(16)
        self.pic_box.set_margin_start(16)
        self.pic_box.set_margin_end(16)

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_keep_aspect_ratio(True)
        self.pic_box.append(self.picture)

        self.scroll.set_child(self.pic_box)
        main_box.append(self.scroll)

        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _on_add_clicked(self, _button=None):
        if self.on_add_callback:
            self.on_add_callback(self.current_page_idx)
        self.close()

    def _zoom_fit(self):
        if not self.doc or self.doc.is_closed or not (0 <= self.current_page_idx < self.doc.page_count):
            self._set_zoom(1.0)
            return
        sw_w = self.scroll.get_allocated_width() - 48
        sw_h = self.scroll.get_allocated_height() - 48
        page = self.doc.load_page(self.current_page_idx)
        pw = page.rect.width
        ph = page.rect.height
        if sw_w > 100 and sw_h > 100 and pw > 0 and ph > 0:
            fit_zoom = min(sw_w / pw, sw_h / ph)
            fit_zoom = max(0.5, min(3.0, round(fit_zoom, 2)))
            self._set_zoom(fit_zoom)
        else:
            self._set_zoom(1.0)

    def _set_zoom(self, zoom: float):
        zoom = max(0.5, min(3.0, zoom))
        self.zoom_level = zoom
        self.zoom_lbl.set_text(f"{int(zoom * 100)}%")
        self._render_current_page()

    def _go_page(self, new_idx: int):
        if self.doc and 0 <= new_idx < self.doc.page_count:
            self.current_page_idx = new_idx
            self._render_current_page()

    def _render_current_page(self):
        if not self.doc or self.doc.is_closed or not (0 <= self.current_page_idx < self.doc.page_count):
            return
        try:
            page = self.doc.load_page(self.current_page_idx)
            disp_w = max(50, int(page.rect.width * self.zoom_level))
            disp_h = max(50, int(page.rect.height * self.zoom_level))
            self.picture.set_size_request(disp_w, disp_h)

            scale = min(4.0, max(1.5, 1.5 * self.zoom_level))
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            gdk_pixbuf = GdkPixbuf.Pixbuf.new_from_data(
                pix.samples, GdkPixbuf.Colorspace.RGB, False, 8,
                pix.width, pix.height, pix.stride
            )
            self.picture.set_paintable(Gdk.Texture.new_for_pixbuf(gdk_pixbuf))

            total = self.doc.page_count
            self.page_info_lbl.set_text(_("merge_preview_page_info", self.current_page_idx + 1, total))
            self.prev_btn.set_sensitive(self.current_page_idx > 0)
            self.next_btn.set_sensitive(self.current_page_idx < total - 1)
        except Exception as e:
            print(f"Error previewing page: {e}")

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up):
            self._go_page(self.current_page_idx - 1)
            return True
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Page_Down, Gdk.KEY_space):
            self._go_page(self.current_page_idx + 1)
            return True
        elif keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


class MergedPreviewDialog(Adw.Window):
    def __init__(self, parent_window, doc=None, target_panel=None, merged_doc=None):
        super().__init__()
        self.parent_window = parent_window
        self.doc = doc if doc is not None else merged_doc
        self.target_panel = target_panel
        self.current_page_idx = 0
        self.zoom_level = 1.0

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("merge_full_preview_title"))
        self.set_default_size(880, 800)
        self.set_size_request(450, 400)
        self.set_resizable(True)

        self._build_ui()
        self._render_current_page()
        self.connect("close-request", self._on_close_request)

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        close_btn = Gtk.Button(label=_("btn_cancel"))
        close_btn.connect("clicked", lambda b: self.close())
        header.pack_start(close_btn)

        self.prev_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.prev_btn.set_tooltip_text(_("prev_page_tip"))
        self.prev_btn.add_css_class("flat")
        self.prev_btn.connect("clicked", lambda b: self._go_page(self.current_page_idx - 1))
        header.pack_start(self.prev_btn)

        self.page_info_lbl = Gtk.Label(label="")
        self.page_info_lbl.add_css_class("heading")
        header.pack_start(self.page_info_lbl)

        self.next_btn = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_btn.set_tooltip_text(_("next_page_tip"))
        self.next_btn.add_css_class("flat")
        self.next_btn.connect("clicked", lambda b: self._go_page(self.current_page_idx + 1))
        header.pack_start(self.next_btn)

        if self.parent_window and hasattr(self.parent_window, "_on_save_clicked"):
            save_btn = Gtk.Button(label=_("merge_btn_save"))
            save_btn.add_css_class("suggested-action")
            save_btn.connect("clicked", lambda b: self._on_save_clicked())
            header.pack_end(save_btn)

        zoom_fit_btn = Gtk.Button.new_from_icon_name("zoom-fit-best-symbolic")
        zoom_fit_btn.set_tooltip_text(_("merge_zoom_fit"))
        zoom_fit_btn.add_css_class("flat")
        zoom_fit_btn.connect("clicked", lambda b: self._zoom_fit())
        header.pack_end(zoom_fit_btn)

        zoom_in_btn = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        zoom_in_btn.set_tooltip_text(_("merge_zoom_in"))
        zoom_in_btn.add_css_class("flat")
        zoom_in_btn.connect("clicked", lambda b: self._set_zoom(self.zoom_level + 0.25))
        header.pack_end(zoom_in_btn)

        self.zoom_lbl = Gtk.Label(label="100%")
        self.zoom_lbl.add_css_class("caption")
        self.zoom_lbl.add_css_class("dim-label")
        header.pack_end(self.zoom_lbl)

        zoom_out_btn = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        zoom_out_btn.set_tooltip_text(_("merge_zoom_out"))
        zoom_out_btn.add_css_class("flat")
        zoom_out_btn.connect("clicked", lambda b: self._set_zoom(self.zoom_level - 0.25))
        header.pack_end(zoom_out_btn)

        main_box.append(header)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.set_hexpand(True)

        self.pic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.pic_box.set_margin_top(16)
        self.pic_box.set_margin_bottom(16)
        self.pic_box.set_margin_start(16)
        self.pic_box.set_margin_end(16)

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_keep_aspect_ratio(True)
        self.pic_box.append(self.picture)

        self.scroll.set_child(self.pic_box)
        main_box.append(self.scroll)

        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _on_save_clicked(self):
        if self.parent_window and hasattr(self.parent_window, "_on_save_clicked"):
            self.parent_window._on_save_clicked(None)

    def _zoom_fit(self):
        if not self.doc or self.doc.is_closed or not (0 <= self.current_page_idx < self.doc.page_count):
            self._set_zoom(1.0)
            return
        sw_w = self.scroll.get_allocated_width() - 48
        sw_h = self.scroll.get_allocated_height() - 48
        page = self.doc.load_page(self.current_page_idx)
        pw = page.rect.width
        ph = page.rect.height
        if sw_w > 100 and sw_h > 100 and pw > 0 and ph > 0:
            fit_zoom = min(sw_w / pw, sw_h / ph)
            fit_zoom = max(0.5, min(3.0, round(fit_zoom, 2)))
            self._set_zoom(fit_zoom)
        else:
            self._set_zoom(1.0)

    def _set_zoom(self, zoom: float):
        zoom = max(0.5, min(3.0, zoom))
        self.zoom_level = zoom
        self.zoom_lbl.set_text(f"{int(zoom * 100)}%")
        self._render_current_page()

    def _go_page(self, new_idx: int):
        if self.doc and 0 <= new_idx < self.doc.page_count:
            self.current_page_idx = new_idx
            self._render_current_page()

    def _render_current_page(self):
        if not self.doc or self.doc.is_closed or not (0 <= self.current_page_idx < self.doc.page_count):
            return
        try:
            page = self.doc.load_page(self.current_page_idx)
            disp_w = max(50, int(page.rect.width * self.zoom_level))
            disp_h = max(50, int(page.rect.height * self.zoom_level))
            self.picture.set_size_request(disp_w, disp_h)

            scale = min(4.0, max(1.5, 1.5 * self.zoom_level))
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            gdk_pixbuf = GdkPixbuf.Pixbuf.new_from_data(
                pix.samples, GdkPixbuf.Colorspace.RGB, False, 8,
                pix.width, pix.height, pix.stride
            )
            self.picture.set_paintable(Gdk.Texture.new_for_pixbuf(gdk_pixbuf))

            total = self.doc.page_count
            self.page_info_lbl.set_text(_("merge_preview_page_info", self.current_page_idx + 1, total))
            self.prev_btn.set_sensitive(self.current_page_idx > 0)
            self.next_btn.set_sensitive(self.current_page_idx < total - 1)
        except Exception as e:
            print(f"Error previewing merged page: {e}")

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up):
            self._go_page(self.current_page_idx - 1)
            return True
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Page_Down, Gdk.KEY_space):
            self._go_page(self.current_page_idx + 1)
            return True
        elif keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_close_request(self, _window):
        if self.doc and not self.doc.is_closed:
            try:
                self.doc.close()
            except Exception:
                pass
        return False


class SourcePageCard(Gtk.Box):
    def __init__(self, panel, page_index: int, page_width: float, page_height: float):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.panel = panel
        self.page_index = page_index
        self.page_width = page_width
        self.page_height = page_height
        self.pixbuf = None

        self.add_css_class("card")
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header_box.set_margin_start(8)
        header_box.set_margin_end(8)
        header_box.set_margin_top(6)

        page_lbl = Gtk.Label(label=f"{page_index + 1}")
        page_lbl.add_css_class("heading")
        header_box.append(page_lbl)

        dim_text = f"{int(page_width)} × {int(page_height)}"
        dim_lbl = Gtk.Label(label=dim_text, hexpand=True, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        dim_lbl.add_css_class("dim-label")
        dim_lbl.add_css_class("caption")
        header_box.append(dim_lbl)

        self.preview_btn = Gtk.Button.new_from_icon_name("view-reveal-symbolic")
        self.preview_btn.add_css_class("flat")
        self.preview_btn.set_tooltip_text(_("merge_preview_page"))
        self.preview_btn.connect("clicked", lambda b: self._preview_page())
        header_box.append(self.preview_btn)

        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.set_tooltip_text(_("merge_add_page"))
        add_btn.connect("clicked", self._on_add_clicked)
        header_box.append(add_btn)

        self.append(header_box)

        pic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.FILL, hexpand=True)
        pic_box.set_margin_top(4)
        pic_box.set_margin_bottom(8)
        pic_box.set_margin_start(8)
        pic_box.set_margin_end(8)

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_keep_aspect_ratio(True)
        self.picture.set_hexpand(True)
        self.picture.set_halign(Gtk.Align.FILL)
        self.picture.set_size_request(60, 85)
        pic_box.append(self.picture)

        self.append(pic_box)

        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.set_button(1)
        click_ctrl.connect("pressed", self._on_gesture_pressed)
        pic_box.add_controller(click_ctrl)

    def set_thumbnail(self, pixbuf):
        self.pixbuf = pixbuf
        if pixbuf:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.picture.set_paintable(texture)

    def _on_add_clicked(self, _button):
        self._add_to_target()

    def _on_gesture_pressed(self, _gesture, n_press, _x, _y):
        if n_press == 1:
            self._preview_page()
        elif n_press == 2:
            self._add_to_target()

    def _preview_page(self):
        if self.panel and self.panel.doc and not self.panel.doc.is_closed:
            dialog = self.panel.dialog
            preview_win = PagePreviewDialog(
                parent_window=dialog,
                doc=self.panel.doc,
                page_index=self.page_index,
                source_role=self.panel.role,
                file_path=self.panel.file_path or "",
                on_add_callback=lambda idx: self._add_to_target()
            )
            preview_win.present()

    def _add_to_target(self):
        if self.panel and self.panel.dialog and self.panel.dialog.target_panel:
            self.panel.dialog.target_panel.add_page(
                source_role=self.panel.role,
                source_path=self.panel.file_path,
                source_doc=self.panel.doc,
                page_index=self.page_index,
                thumbnail_pixbuf=self.pixbuf,
                page_width=self.page_width,
                page_height=self.page_height,
            )


class SourceDocumentPanel(Gtk.Box):
    def __init__(self, dialog, role: str, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.dialog = dialog
        self.role = role
        self.title_str = title
        self.doc = None
        self.file_path = None
        self.page_count = 0
        self.page_cards = []
        self._idle_loader_id = 0

        self._build_ui()
        self._setup_drop_target()

    def _build_ui(self):
        header_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_card.add_css_class("card")
        header_card.set_margin_start(8)
        header_card.set_margin_end(8)
        header_card.set_margin_top(8)
        header_card.set_margin_bottom(4)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        top_row.set_margin_start(10)
        top_row.set_margin_end(10)
        top_row.set_margin_top(8)

        self.title_lbl = Gtk.Label(label=self.title_str, hexpand=True, xalign=0.0)
        self.title_lbl.add_css_class("heading")
        top_row.append(self.title_lbl)

        self.page_badge = Gtk.Label(label="")
        self.page_badge.add_css_class("dim-label")
        self.page_badge.add_css_class("caption")
        top_row.append(self.page_badge)

        header_card.append(top_row)

        actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions_row.set_margin_start(10)
        actions_row.set_margin_end(10)
        actions_row.set_margin_bottom(6)

        self.file_lbl = Gtk.Label(label="", hexpand=True, xalign=0.0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.file_lbl.add_css_class("dim-label")
        self.file_lbl.add_css_class("caption")
        actions_row.append(self.file_lbl)

        self.choose_btn = Gtk.Button.new_from_icon_name("document-open-symbolic")
        self.choose_btn.set_tooltip_text(_("merge_btn_choose_pdf"))
        self.choose_btn.add_css_class("flat")
        self.choose_btn.connect("clicked", self.on_choose_clicked)
        actions_row.append(self.choose_btn)

        self.add_all_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        self.add_all_btn.set_tooltip_text(_("merge_add_all_tip"))
        self.add_all_btn.add_css_class("flat")
        self.add_all_btn.set_sensitive(False)
        self.add_all_btn.connect("clicked", self.on_add_all_clicked)
        actions_row.append(self.add_all_btn)

        self.clear_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        self.clear_btn.set_tooltip_text(_("merge_clear_tip"))
        self.clear_btn.add_css_class("flat")
        self.clear_btn.set_sensitive(False)
        self.clear_btn.connect("clicked", lambda b: self.clear())
        actions_row.append(self.clear_btn)

        header_card.append(actions_row)

        self.append(header_card)

        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, vexpand=True)
        self.empty_box.set_margin_start(16)
        self.empty_box.set_margin_end(16)

        empty_icon = Gtk.Image.new_from_icon_name("document-open-symbolic")
        empty_icon.set_pixel_size(48)
        empty_icon.add_css_class("dim-label")
        self.empty_box.append(empty_icon)

        empty_title = Gtk.Label(label=_("merge_empty_source_title"))
        empty_title.add_css_class("heading")
        self.empty_box.append(empty_title)

        empty_desc = Gtk.Label(label=_("merge_empty_source_desc"), wrap=True, justify=Gtk.Justification.CENTER)
        empty_desc.set_max_width_chars(28)
        empty_desc.add_css_class("dim-label")
        empty_desc.add_css_class("caption")
        self.empty_box.append(empty_desc)

        choose_action_btn = Gtk.Button(label=_("merge_btn_choose_pdf"))
        choose_action_btn.add_css_class("pill")
        choose_action_btn.connect("clicked", self.on_choose_clicked)
        self.empty_box.append(choose_action_btn)

        self.append(self.empty_box)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)

        self.ribbon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.ribbon_box.set_margin_start(8)
        self.ribbon_box.set_margin_end(8)
        self.ribbon_box.set_margin_top(4)
        self.ribbon_box.set_margin_bottom(12)
        self.scroll.set_child(self.ribbon_box)

        self.append(self.scroll)

        self.empty_box.set_visible(True)
        self.scroll.set_visible(False)

    def _setup_drop_target(self):
        target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        target.connect("drop", self._on_file_dropped)
        self.add_controller(target)

    def _on_file_dropped(self, _target, value, _x, _y):
        if isinstance(value, Gio.File):
            path = value.get_path()
            if path and path.lower().endswith(".pdf"):
                self.load_file(path)
                return True
        return False

    def load_file(self, file_path: str) -> bool:
        self.clear()
        if not file_path or not Path(file_path).is_file():
            return False

        try:
            doc = fitz.open(file_path)
            if doc.page_count == 0:
                doc.close()
                show_error_dialog(self.dialog, _("err_source_pdf_empty"), _("err_merge_title"))
                return False

            self.doc = doc
            self.file_path = str(file_path)
            self.page_count = doc.page_count

            filename = Path(file_path).name
            self.file_lbl.set_text(filename)
            self.page_badge.set_text(_("merge_page_count", self.page_count))

            self.add_all_btn.set_sensitive(True)
            self.clear_btn.set_sensitive(True)

            for i in range(self.page_count):
                page = doc.load_page(i)
                rect = page.rect
                card = SourcePageCard(self, page_index=i, page_width=rect.width, page_height=rect.height)
                self.page_cards.append(card)
                self.ribbon_box.append(card)

            self.empty_box.set_visible(False)
            self.scroll.set_visible(True)
            self._start_progressive_thumbnails()
            return True

        except Exception as e:
            show_error_dialog(self.dialog, str(e), _("err_merge_title"))
            return False

    def _start_progressive_thumbnails(self):
        if self._idle_loader_id:
            GLib.source_remove(self._idle_loader_id)
            self._idle_loader_id = 0
        if self.page_count > 0:
            self._idle_loader_id = GLib.idle_add(self._load_next_thumbnail, 0)

    def _load_next_thumbnail(self, index: int):
        if self.doc is None or self.doc.is_closed or index >= self.page_count:
            self._idle_loader_id = 0
            return False

        if not self.get_visible() or not self.dialog or not self.dialog.get_visible():
            self._idle_loader_id = 0
            return False

        try:
            pixbuf = pdf_handler.generate_thumbnail(self.doc, index, target_width=450)
            if index < len(self.page_cards):
                self.page_cards[index].set_thumbnail(pixbuf)
        except Exception:
            pass

        next_idx = index + 1
        if next_idx < self.page_count and self.doc is not None and not self.doc.is_closed:
            self._idle_loader_id = GLib.idle_add(self._load_next_thumbnail, next_idx)
        else:
            self._idle_loader_id = 0
        return False

    def clear(self):
        if self._idle_loader_id:
            GLib.source_remove(self._idle_loader_id)
            self._idle_loader_id = 0

        if self.doc is not None:
            target_uses_doc = False
            if self.dialog and self.dialog.target_panel:
                target_uses_doc = any(p.get("source_doc") is self.doc for p in self.dialog.target_panel.pages)
            if not target_uses_doc:
                try:
                    if not self.doc.is_closed:
                        self.doc.close()
                except Exception:
                    pass
            self.doc = None

        self.file_path = None
        self.page_count = 0
        self.page_cards.clear()

        child = self.ribbon_box.get_first_child()
        while child:
            self.ribbon_box.remove(child)
            child = self.ribbon_box.get_first_child()

        self.file_lbl.set_text("")
        self.page_badge.set_text("")
        self.add_all_btn.set_sensitive(False)
        self.clear_btn.set_sensitive(False)
        self.empty_box.set_visible(True)
        self.scroll.set_visible(False)

    def on_choose_clicked(self, _button):
        filter_pdf = Gtk.FileFilter(name=_("filter_pdf"))
        filter_pdf.add_pattern("*.pdf")
        filter_pdf.add_mime_type("application/pdf")
        filter_all = Gtk.FileFilter(name=_("filter_all"))
        filter_all.add_pattern("*")

        def on_open_finish(file):
            if file:
                def _do_load():
                    self.load_file(file.get_path())
                    return False
                GLib.idle_add(_do_load)

        show_open_file_dialog(
            self.dialog,
            _("open_pdf_title"),
            filters=[filter_pdf, filter_all],
            default_filter=filter_pdf,
            callback=on_open_finish
        )

    def on_add_all_clicked(self, _button):
        if self.doc is None or not self.dialog or not self.dialog.target_panel:
            return
        for card in self.page_cards:
            card._add_to_target()


ZOOM_LEVELS = [0.7, 0.85, 1.0, 1.2, 1.4]

MERGE_CSS = b"""
.card-selected {
    outline: 2px solid @accent_color;
    outline-offset: -1px;
}
.insertion-marker-bar {
    min-height: 4px;
    border-radius: 2px;
    background-color: transparent;
}
.insertion-marker-bar.active {
    background-color: @accent_color;
    min-height: 6px;
}
"""

_merge_css_loaded = False


def _ensure_merge_css():
    global _merge_css_loaded
    if _merge_css_loaded:
        return
    display = Gdk.Display.get_default()
    if display is not None:
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(MERGE_CSS)
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            _merge_css_loaded = True
        except Exception:
            pass


class InsertionMarker(Gtk.Box):
    def __init__(self, target_panel, index: int):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.target_panel = target_panel
        self.index = index
        self.is_active = False

        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(2)
        self.set_margin_bottom(2)

        self.bar = Gtk.Box()
        self.bar.add_css_class("insertion-marker-bar")
        self.bar.set_size_request(-1, 4)
        self.append(self.bar)

        self.pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER, spacing=4)
        self.pill_box.set_visible(False)
        marker_icon = Gtk.Image.new_from_icon_name("pan-down-symbolic")
        marker_icon.set_pixel_size(12)
        marker_lbl = Gtk.Label(label=_("merge_insert_marker"))
        marker_lbl.add_css_class("caption")
        marker_lbl.add_css_class("dim-label")
        self.pill_box.append(marker_icon)
        self.pill_box.append(marker_lbl)
        self.append(self.pill_box)

        click = Gtk.GestureClick.new()
        click.set_button(1)
        click.connect("pressed", self._on_clicked)
        self.add_controller(click)

    def set_active(self, active: bool):
        self.is_active = active
        if active:
            self.bar.add_css_class("active")
            self.pill_box.set_visible(True)
        else:
            self.bar.remove_css_class("active")
            self.pill_box.set_visible(False)

    def _on_clicked(self, _gesture, _n, _x, _y):
        self.target_panel.set_insertion_index(self.index)


class TargetPageCard(Gtk.Box):
    def __init__(self, target_panel, target_idx: int, page_entry: dict, zoom_level: float = 1.0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.target_panel = target_panel
        self.target_idx = target_idx
        self.page_entry = page_entry
        self.zoom_level = zoom_level
        self.is_selected = False

        self.add_css_class("card")
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header_box.set_margin_start(8)
        header_box.set_margin_end(8)
        header_box.set_margin_top(6)

        idx_lbl = Gtk.Label(label=f"#{target_idx + 1}")
        idx_lbl.add_css_class("heading")
        header_box.append(idx_lbl)

        role_str = "A" if page_entry.get("source_role") == "source_a" else "B"
        src_page = page_entry.get("page_index", 0) + 1
        src_badge = Gtk.Label(label=f"Doc {role_str} : p.{src_page}", hexpand=True, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        src_badge.add_css_class("dim-label")
        src_badge.add_css_class("caption")
        header_box.append(src_badge)

        self.preview_btn = Gtk.Button.new_from_icon_name("view-reveal-symbolic")
        self.preview_btn.add_css_class("flat")
        self.preview_btn.set_tooltip_text(_("merge_preview_page"))
        self.preview_btn.connect("clicked", lambda b: self._preview_page())
        header_box.append(self.preview_btn)

        self.insert_marker_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        self.insert_marker_btn.add_css_class("flat")
        self.insert_marker_btn.set_tooltip_text(_("merge_insert_after", target_idx + 1))
        self.insert_marker_btn.connect("clicked", self._on_insert_here_clicked)
        header_box.append(self.insert_marker_btn)

        self.up_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
        self.up_btn.add_css_class("flat")
        self.up_btn.set_tooltip_text(_("merge_move_up_tip"))
        self.up_btn.connect("clicked", lambda b: self.target_panel.move_page(self.target_idx, self.target_idx - 1))
        header_box.append(self.up_btn)

        self.down_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
        self.down_btn.add_css_class("flat")
        self.down_btn.set_tooltip_text(_("merge_move_down_tip"))
        self.down_btn.connect("clicked", lambda b: self.target_panel.move_page(self.target_idx, self.target_idx + 1))
        header_box.append(self.down_btn)

        del_btn = Gtk.Button.new_from_icon_name("edit-delete-symbolic")
        del_btn.add_css_class("flat")
        del_btn.set_tooltip_text(_("merge_remove_page_tip"))
        del_btn.connect("clicked", lambda b: self.target_panel.remove_page(self.target_idx))
        header_box.append(del_btn)

        self.append(header_box)

        pic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.FILL, hexpand=True)
        pic_box.set_margin_top(4)
        pic_box.set_margin_bottom(8)
        pic_box.set_margin_start(8)
        pic_box.set_margin_end(8)

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_keep_aspect_ratio(True)
        self.picture.set_hexpand(True)
        self.picture.set_halign(Gtk.Align.FILL)
        self.picture.set_size_request(60, 85)

        pixbuf = page_entry.get("thumbnail_pixbuf")
        if pixbuf:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.picture.set_paintable(texture)

        pic_box.append(self.picture)
        self.append(pic_box)

        self.set_zoom(self.zoom_level)

        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.set_button(1)
        click_ctrl.connect("pressed", self._on_card_pressed)
        pic_box.add_controller(click_ctrl)

    def set_zoom(self, zoom_level: float):
        self.zoom_level = zoom_level
        if abs(zoom_level - 1.0) < 0.05:
            self.picture.set_hexpand(True)
            self.picture.set_halign(Gtk.Align.FILL)
            self.picture.set_size_request(60, 85)
        elif zoom_level < 1.0:
            w = max(60, int(180 * zoom_level))
            h = max(85, int(250 * zoom_level))
            self.picture.set_hexpand(False)
            self.picture.set_halign(Gtk.Align.CENTER)
            self.picture.set_size_request(w, h)
        else:
            w = int(240 * zoom_level)
            h = int(340 * zoom_level)
            self.picture.set_hexpand(True)
            self.picture.set_halign(Gtk.Align.FILL)
            self.picture.set_size_request(w, h)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        if selected:
            self.add_css_class("card-selected")
        else:
            self.remove_css_class("card-selected")

    def _on_insert_here_clicked(self, _button):
        self.target_panel.set_insertion_index(self.target_idx + 1)
        self.target_panel.select_page(self.target_idx)

    def _on_card_pressed(self, _gesture, n_press, _x, _y):
        if n_press == 1:
            if self.target_panel.selected_idx == self.target_idx:
                self.target_panel.select_page(None)
            else:
                self.target_panel.select_page(self.target_idx)
        elif n_press == 2:
            self._preview_page()

    def _preview_page(self):
        src_doc = self.page_entry.get("source_doc")
        src_page = self.page_entry.get("page_index", 0)
        src_path = self.page_entry.get("source_path", "")
        if src_doc and not src_doc.is_closed:
            dialog = self.target_panel.dialog
            preview_win = PagePreviewDialog(
                parent_window=dialog,
                doc=src_doc,
                page_index=src_page,
                source_role=self.page_entry.get("source_role", ""),
                file_path=src_path,
                on_add_callback=None
            )
            preview_win.present()

    def update_position(self, target_idx: int, total_pages: int):
        self.target_idx = target_idx
        first_child = self.get_first_child()
        if first_child:
            idx_lbl = first_child.get_first_child()
            if isinstance(idx_lbl, Gtk.Label):
                idx_lbl.set_text(f"#{target_idx + 1}")
        self.up_btn.set_sensitive(target_idx > 0)
        self.down_btn.set_sensitive(target_idx < total_pages - 1)
        self.insert_marker_btn.set_tooltip_text(_("merge_insert_after", target_idx + 1))


class TargetDocumentPanel(Gtk.Box):
    def __init__(self, dialog, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.dialog = dialog
        self.title_str = title
        self.pages = []
        self.page_cards = []
        self.markers = []
        self.selected_idx = None
        self.insertion_index = None
        self.zoom_index = 2
        self.zoom_level = ZOOM_LEVELS[self.zoom_index]

        _ensure_merge_css()
        self._build_ui()

    def _build_ui(self):
        header_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_card.add_css_class("card")
        header_card.set_margin_start(8)
        header_card.set_margin_end(8)
        header_card.set_margin_top(8)
        header_card.set_margin_bottom(4)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        top_row.set_margin_start(10)
        top_row.set_margin_end(10)
        top_row.set_margin_top(8)

        title_lbl = Gtk.Label(label=self.title_str, hexpand=True, xalign=0.0)
        title_lbl.add_css_class("heading")
        top_row.append(title_lbl)

        self.page_badge = Gtk.Label(label=_("merge_page_count", 0))
        self.page_badge.add_css_class("dim-label")
        self.page_badge.add_css_class("caption")
        top_row.append(self.page_badge)

        header_card.append(top_row)

        insertion_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        insertion_row.set_margin_start(10)
        insertion_row.set_margin_end(10)

        self.insertion_btn = Gtk.Button(label=_("merge_insert_at_end"))
        self.insertion_btn.add_css_class("flat")
        self.insertion_btn.set_hexpand(True)
        self.insertion_btn.set_sensitive(False)
        self.insertion_btn.connect("clicked", self.on_insertion_btn_clicked)
        btn_child = self.insertion_btn.get_child()
        if isinstance(btn_child, Gtk.Label):
            btn_child.set_ellipsize(Pango.EllipsizeMode.END)
            btn_child.set_xalign(0.0)
        insertion_row.append(self.insertion_btn)

        self.clear_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        self.clear_btn.set_tooltip_text(_("merge_clear_target_tip"))
        self.clear_btn.add_css_class("flat")
        self.clear_btn.set_sensitive(False)
        self.clear_btn.connect("clicked", lambda b: self.clear())
        insertion_row.append(self.clear_btn)

        header_card.append(insertion_row)

        preview_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        preview_toolbar.set_margin_start(10)
        preview_toolbar.set_margin_end(10)
        preview_toolbar.set_margin_bottom(6)

        desc_lbl = Gtk.Label(label=_("merge_workspace_subtitle"), hexpand=True, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        desc_lbl.add_css_class("dim-label")
        desc_lbl.add_css_class("caption")
        preview_toolbar.append(desc_lbl)

        self.zoom_out_btn = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        self.zoom_out_btn.add_css_class("flat")
        self.zoom_out_btn.set_tooltip_text(_("merge_zoom_out"))
        self.zoom_out_btn.set_sensitive(False)
        self.zoom_out_btn.connect("clicked", lambda b: self.zoom_out())
        preview_toolbar.append(self.zoom_out_btn)

        self.zoom_lbl = Gtk.Label(label="100%")
        self.zoom_lbl.add_css_class("caption")
        self.zoom_lbl.add_css_class("dim-label")
        preview_toolbar.append(self.zoom_lbl)

        self.zoom_in_btn = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        self.zoom_in_btn.add_css_class("flat")
        self.zoom_in_btn.set_tooltip_text(_("merge_zoom_in"))
        self.zoom_in_btn.set_sensitive(False)
        self.zoom_in_btn.connect("clicked", lambda b: self.zoom_in())
        preview_toolbar.append(self.zoom_in_btn)

        self.zoom_fit_btn = Gtk.Button.new_from_icon_name("zoom-fit-best-symbolic")
        self.zoom_fit_btn.add_css_class("flat")
        self.zoom_fit_btn.set_tooltip_text(_("merge_zoom_fit"))
        self.zoom_fit_btn.set_sensitive(False)
        self.zoom_fit_btn.connect("clicked", lambda b: self.zoom_fit())
        preview_toolbar.append(self.zoom_fit_btn)

        self.preview_btn = Gtk.Button.new_from_icon_name("document-print-preview-symbolic")
        self.preview_btn.add_css_class("flat")
        self.preview_btn.set_tooltip_text(_("merge_btn_preview"))
        self.preview_btn.set_sensitive(False)
        self.preview_btn.connect("clicked", lambda b: self.dialog._on_preview_merged_clicked(b) if self.dialog else None)
        preview_toolbar.append(self.preview_btn)

        header_card.append(preview_toolbar)

        self.append(header_card)

        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, vexpand=True)
        self.empty_box.set_margin_start(16)
        self.empty_box.set_margin_end(16)

        empty_icon = Gtk.Image.new_from_icon_name("edit-copy-symbolic")
        empty_icon.set_pixel_size(48)
        empty_icon.add_css_class("dim-label")
        self.empty_box.append(empty_icon)

        empty_title = Gtk.Label(label=_("merge_empty_target_title"))
        empty_title.add_css_class("heading")
        self.empty_box.append(empty_title)

        empty_desc = Gtk.Label(label=_("merge_empty_target_desc"), wrap=True, justify=Gtk.Justification.CENTER)
        empty_desc.set_max_width_chars(28)
        empty_desc.add_css_class("dim-label")
        empty_desc.add_css_class("caption")
        self.empty_box.append(empty_desc)

        self.append(self.empty_box)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)

        self.ribbon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.ribbon_box.set_margin_start(8)
        self.ribbon_box.set_margin_end(8)
        self.ribbon_box.set_margin_top(4)
        self.ribbon_box.set_margin_bottom(12)
        self.scroll.set_child(self.ribbon_box)

        self.append(self.scroll)

        self.inspector_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.inspector_card.add_css_class("card")
        self.inspector_card.set_margin_start(8)
        self.inspector_card.set_margin_end(8)
        self.inspector_card.set_margin_top(4)
        self.inspector_card.set_margin_bottom(8)

        insp_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        insp_hdr.set_margin_start(8)
        insp_hdr.set_margin_end(8)
        insp_hdr.set_margin_top(6)

        insp_title = Gtk.Label(label=_("merge_inspector_title"), hexpand=True, xalign=0.0)
        insp_title.add_css_class("heading")
        insp_title.add_css_class("caption")
        insp_hdr.append(insp_title)

        self.insp_pos_lbl = Gtk.Label(label="")
        self.insp_pos_lbl.add_css_class("dim-label")
        self.insp_pos_lbl.add_css_class("caption")
        insp_hdr.append(self.insp_pos_lbl)

        self.insp_preview_btn = Gtk.Button.new_from_icon_name("view-reveal-symbolic")
        self.insp_preview_btn.add_css_class("flat")
        self.insp_preview_btn.set_tooltip_text(_("merge_preview_page"))
        self.insp_preview_btn.connect("clicked", lambda b: self._preview_selected_page())
        insp_hdr.append(self.insp_preview_btn)

        self.inspector_close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        self.inspector_close_btn.add_css_class("flat")
        self.inspector_close_btn.connect("clicked", lambda b: self.select_page(None))
        insp_hdr.append(self.inspector_close_btn)
        self.inspector_card.append(insp_hdr)

        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row1.set_margin_start(8)
        row1.set_margin_end(8)
        self.insp_source_lbl = Gtk.Label(label="", hexpand=True, xalign=0.0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.insp_source_lbl.add_css_class("caption")
        self.insp_source_lbl.add_css_class("dim-label")
        row1.append(self.insp_source_lbl)

        self.insp_page_lbl = Gtk.Label(label="")
        self.insp_page_lbl.add_css_class("caption")
        self.insp_page_lbl.add_css_class("dim-label")
        row1.append(self.insp_page_lbl)
        self.inspector_card.append(row1)

        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row2.set_margin_start(8)
        row2.set_margin_end(8)
        row2.set_margin_bottom(6)

        self.insp_size_lbl = Gtk.Label(label="", hexpand=True, xalign=0.0)
        self.insp_size_lbl.add_css_class("caption")
        self.insp_size_lbl.add_css_class("dim-label")
        row2.append(self.insp_size_lbl)

        self.insp_orient_lbl = Gtk.Label(label="")
        self.insp_orient_lbl.add_css_class("caption")
        self.insp_orient_lbl.add_css_class("dim-label")
        row2.append(self.insp_orient_lbl)
        self.inspector_card.append(row2)

        self.append(self.inspector_card)

        self.empty_box.set_visible(True)
        self.scroll.set_visible(False)
        self.inspector_card.set_visible(False)

    def zoom_in(self):
        if self.zoom_index < len(ZOOM_LEVELS) - 1:
            self.zoom_index += 1
            self._apply_zoom()

    def zoom_out(self):
        if self.zoom_index > 0:
            self.zoom_index -= 1
            self._apply_zoom()

    def zoom_fit(self):
        self.zoom_index = 2
        self._apply_zoom()

    def _apply_zoom(self):
        self.zoom_level = ZOOM_LEVELS[self.zoom_index]
        self.zoom_lbl.set_text(f"{int(self.zoom_level * 100)}%")
        count = len(self.pages)
        self.zoom_out_btn.set_sensitive(count > 0 and self.zoom_index > 0)
        self.zoom_in_btn.set_sensitive(count > 0 and self.zoom_index < len(ZOOM_LEVELS) - 1)
        self.zoom_fit_btn.set_sensitive(count > 0)
        for card in self.page_cards:
            card.set_zoom(self.zoom_level)

    def on_insertion_btn_clicked(self, _button):
        if self.insertion_index is not None:
            self.set_insertion_index(None)
        else:
            if len(self.pages) > 0:
                self.set_insertion_index(len(self.pages))

    def set_insertion_index(self, index: int | None):
        if index is not None and index >= len(self.pages):
            self.insertion_index = None
        else:
            self.insertion_index = index
        self._update_insertion_ui()

    def _update_insertion_ui(self):
        count = len(self.pages)
        if count == 0:
            self.insertion_btn.set_label(_("merge_insert_at_end"))
            self.insertion_btn.set_sensitive(False)
            return

        self.insertion_btn.set_sensitive(True)
        if self.insertion_index is None or self.insertion_index >= count:
            self.insertion_btn.set_label(_("merge_insert_at_end"))
        elif self.insertion_index == 0:
            self.insertion_btn.set_label(_("merge_insert_marker"))
        else:
            self.insertion_btn.set_label(_("merge_insert_after", self.insertion_index))

        btn_child = self.insertion_btn.get_child()
        if isinstance(btn_child, Gtk.Label):
            btn_child.set_ellipsize(Pango.EllipsizeMode.END)
            btn_child.set_xalign(0.0)

        for m in self.markers:
            is_active = (self.insertion_index is not None and m.index == self.insertion_index)
            m.set_active(is_active)

    def select_page(self, target_idx: int | None):
        if target_idx is not None and not (0 <= target_idx < len(self.pages)):
            target_idx = None
        self.selected_idx = target_idx
        for idx, card in enumerate(self.page_cards):
            card.set_selected(idx == target_idx)
        if target_idx is not None:
            self.set_insertion_index(target_idx + 1)
        self._update_inspector_ui()

    def _update_inspector_ui(self):
        if self.selected_idx is None or self.selected_idx >= len(self.pages):
            self.inspector_card.set_visible(False)
            return

        entry = self.pages[self.selected_idx]
        role_code = entry.get("source_role")
        role_label = _("merge_source_a") if role_code == "source_a" else _("merge_source_b")
        src_path = entry.get("source_path")
        filename = Path(src_path).name if src_path else role_label

        self.insp_source_lbl.set_text(_("merge_inspector_source", f"{role_label} ({filename})"))
        orig_page = entry.get("page_index", 0) + 1
        self.insp_page_lbl.set_text(_("merge_inspector_page", orig_page))

        w = float(entry.get("page_width", 0.0))
        h = float(entry.get("page_height", 0.0))
        self.insp_size_lbl.set_text(_("merge_inspector_size", int(w), int(h)))

        is_portrait = h >= w
        self.insp_orient_lbl.set_text(_("merge_inspector_portrait") if is_portrait else _("merge_inspector_landscape"))
        self.insp_pos_lbl.set_text(f"#{self.selected_idx + 1} / {len(self.pages)}")
        self.inspector_card.set_visible(True)

    def _preview_selected_page(self):
        if self.selected_idx is None or not (0 <= self.selected_idx < len(self.pages)):
            return
        entry = self.pages[self.selected_idx]
        src_doc = entry.get("source_doc")
        src_page = entry.get("page_index", 0)
        src_path = entry.get("source_path", "")
        if src_doc and not src_doc.is_closed:
            preview_win = PagePreviewDialog(
                parent_window=self.dialog,
                doc=src_doc,
                page_index=src_page,
                source_role=entry.get("source_role", ""),
                file_path=src_path,
                on_add_callback=None
            )
            preview_win.present()

    def add_page(self, source_role: str, source_path: str, source_doc, page_index: int,
                 thumbnail_pixbuf, page_width: float, page_height: float, insert_at: int | None = None):
        entry = {
            "source_role": source_role,
            "source_path": source_path,
            "source_doc": source_doc,
            "page_index": page_index,
            "thumbnail_pixbuf": thumbnail_pixbuf,
            "page_width": page_width,
            "page_height": page_height,
        }

        pos = insert_at if insert_at is not None else self.insertion_index
        if pos is None or pos >= len(self.pages):
            self.pages.append(entry)
            target_idx = len(self.pages) - 1
            if self.insertion_index is not None:
                self.insertion_index = len(self.pages)
        else:
            self.pages.insert(pos, entry)
            target_idx = pos
            self.insertion_index = pos + 1

        self._rebuild_ribbon()
        self.select_page(target_idx)

    def remove_page(self, target_idx: int):
        if 0 <= target_idx < len(self.pages):
            self.pages.pop(target_idx)
            if self.selected_idx == target_idx:
                self.selected_idx = None
            elif self.selected_idx is not None and self.selected_idx > target_idx:
                self.selected_idx -= 1

            if self.insertion_index is not None:
                if self.insertion_index > len(self.pages):
                    self.insertion_index = len(self.pages)
                elif self.insertion_index > target_idx:
                    self.insertion_index -= 1

            self._rebuild_ribbon()

    def move_page(self, from_idx: int, to_idx: int):
        if 0 <= from_idx < len(self.pages) and 0 <= to_idx < len(self.pages) and from_idx != to_idx:
            item = self.pages.pop(from_idx)
            self.pages.insert(to_idx, item)
            if self.selected_idx == from_idx:
                self.selected_idx = to_idx
            self._rebuild_ribbon()

    def clear(self):
        self.pages.clear()
        self.selected_idx = None
        self.insertion_index = None
        self._rebuild_ribbon()

    def _rebuild_ribbon(self):
        child = self.ribbon_box.get_first_child()
        while child:
            self.ribbon_box.remove(child)
            child = self.ribbon_box.get_first_child()

        self.page_cards.clear()
        self.markers.clear()

        count = len(self.pages)
        if count > 0:
            m0 = InsertionMarker(self, 0)
            self.markers.append(m0)
            self.ribbon_box.append(m0)

            for idx, entry in enumerate(self.pages):
                card = TargetPageCard(self, target_idx=idx, page_entry=entry, zoom_level=self.zoom_level)
                if idx == self.selected_idx:
                    card.set_selected(True)
                self.page_cards.append(card)
                self.ribbon_box.append(card)

                m = InsertionMarker(self, idx + 1)
                self.markers.append(m)
                self.ribbon_box.append(m)

        self._refresh_state()

    def _refresh_state(self):
        count = len(self.pages)
        self.page_badge.set_text(_("merge_page_count", count))
        self.clear_btn.set_sensitive(count > 0)
        self.insertion_btn.set_sensitive(count > 0)
        self.zoom_out_btn.set_sensitive(count > 0 and self.zoom_index > 0)
        self.zoom_in_btn.set_sensitive(count > 0 and self.zoom_index < len(ZOOM_LEVELS) - 1)
        self.zoom_fit_btn.set_sensitive(count > 0)
        self.preview_btn.set_sensitive(count > 0)
        self.empty_box.set_visible(count == 0)
        self.scroll.set_visible(count > 0)

        for idx, card in enumerate(self.page_cards):
            card.update_position(idx, count)

        self._update_insertion_ui()
        self._update_inspector_ui()

        if self.dialog:
            self.dialog._on_target_pages_changed()


class MergeDialog(Adw.Window):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("merge_workspace_title"))
        self.set_default_size(700, 520)
        self.set_size_request(480, 380)
        self.set_resizable(True)

        self._build_ui()
        self._prepopulate_from_parent()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        close_btn = Gtk.Button(label=_("btn_cancel"))
        close_btn.connect("clicked", lambda b: self.close())
        header.pack_start(close_btn)

        self.save_btn = Gtk.Button(label=_("merge_btn_save"))
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.set_sensitive(False)
        self.save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(self.save_btn)

        self.preview_merged_btn = Gtk.Button.new_from_icon_name("document-print-preview-symbolic")
        self.preview_merged_btn.add_css_class("flat")
        self.preview_merged_btn.set_tooltip_text(_("merge_btn_preview"))
        self.preview_merged_btn.set_sensitive(False)
        self.preview_merged_btn.connect("clicked", self._on_preview_merged_clicked)
        header.pack_end(self.preview_merged_btn)

        main_box.append(header)

        panels_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0, vexpand=True, hexpand=True)

        self.panel_a = SourceDocumentPanel(self, role="source_a", title=_("merge_source_a"))
        self.panel_a.set_hexpand(True)
        panels_box.append(self.panel_a)

        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep1.set_hexpand(False)
        panels_box.append(sep1)

        self.target_panel = TargetDocumentPanel(self, title=_("merge_target_doc"))
        self.target_panel.set_hexpand(True)
        panels_box.append(self.target_panel)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.set_hexpand(False)
        panels_box.append(sep2)

        self.panel_b = SourceDocumentPanel(self, role="source_b", title=_("merge_source_b"))
        self.panel_b.set_hexpand(True)
        panels_box.append(self.panel_b)

        panel_size_group = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)
        panel_size_group.add_widget(self.panel_a)
        panel_size_group.add_widget(self.target_panel)
        panel_size_group.add_widget(self.panel_b)

        main_box.append(panels_box)

        self.connect("close-request", self._on_close_request)

    def _prepopulate_from_parent(self):
        if self.parent_window:
            cur_path = getattr(self.parent_window, "current_file_path", None)
            if cur_path and Path(cur_path).is_file():
                self.panel_a.load_file(cur_path)

    def _on_target_pages_changed(self):
        count = len(self.target_panel.pages)
        self.save_btn.set_sensitive(count > 0)
        self.preview_merged_btn.set_sensitive(count > 0)

    def _on_preview_merged_clicked(self, _button):
        if not self.target_panel.pages:
            return
        merged_doc = fitz.open()
        for entry in self.target_panel.pages:
            src_doc = entry.get("source_doc")
            p_idx = entry.get("page_index", 0)
            if src_doc and not src_doc.is_closed:
                merged_doc.insert_pdf(src_doc, from_page=p_idx, to_page=p_idx)
        if merged_doc.page_count == 0:
            merged_doc.close()
            return
        preview_win = MergedPreviewDialog(parent_window=self, merged_doc=merged_doc)
        preview_win.present()

    def _on_save_clicked(self, _button):
        if not self.target_panel.pages:
            return
        from .ui_components import show_save_file_dialog
        filter_pdf = Gtk.FileFilter(name=_("filter_pdf"))
        filter_pdf.add_pattern("*.pdf")
        filter_pdf.add_mime_type("application/pdf")

        def on_save_finish(file, _filter=None):
            if file:
                path = file.get_path()
                if not path:
                    return
                if not path.lower().endswith(".pdf"):
                    path += ".pdf"
                try:
                    merged_doc = fitz.open()
                    for entry in self.target_panel.pages:
                        src_doc = entry.get("source_doc")
                        p_idx = entry.get("page_index", 0)
                        if src_doc and not src_doc.is_closed:
                            merged_doc.insert_pdf(src_doc, from_page=p_idx, to_page=p_idx)
                    merged_doc.save(path)
                    merged_doc.close()
                    if self.parent_window and hasattr(self.parent_window, "load_document"):
                        self.parent_window.load_document(path)
                    self.close()
                except Exception:
                    pass

        show_save_file_dialog(
            parent_window=self,
            title=_("merge_btn_save"),
            initial_name="merged.pdf",
            filters=[filter_pdf],
            default_filter=filter_pdf,
            callback=on_save_finish
        )

    def _on_close_request(self, _window):
        self.cleanup()
        return False

    def cleanup(self):
        if hasattr(self, "panel_a") and self.panel_a:
            self.panel_a.clear()
        if hasattr(self, "panel_b") and self.panel_b:
            self.panel_b.clear()
        if hasattr(self, "target_panel") and self.target_panel:
            closed_docs = set()
            for page in self.target_panel.pages:
                doc = page.get("source_doc")
                if doc is not None and id(doc) not in closed_docs:
                    closed_docs.add(id(doc))
                    try:
                        if not doc.is_closed:
                            doc.close()
                    except Exception:
                        pass
            self.target_panel.clear()
