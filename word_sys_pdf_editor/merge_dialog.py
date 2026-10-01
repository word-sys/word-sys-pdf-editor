from pathlib import Path
import gi
try:
    import pymupdf as fitz
except ImportError:
    import fitz

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Adw, Gio, GLib, Pango

from .i18n import _
from . import pdf_handler
from .ui_components import show_open_file_dialog, show_error_dialog


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

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_start(8)
        header_box.set_margin_end(8)
        header_box.set_margin_top(6)

        page_lbl = Gtk.Label(label=f"{page_index + 1}")
        page_lbl.add_css_class("heading")
        header_box.append(page_lbl)

        dim_text = f"{int(page_width)} × {int(page_height)}"
        dim_lbl = Gtk.Label(label=dim_text, hexpand=True, xalign=0.0)
        dim_lbl.add_css_class("dim-label")
        dim_lbl.add_css_class("caption")
        header_box.append(dim_lbl)

        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.set_tooltip_text(_("merge_add_page"))
        add_btn.connect("clicked", self._on_add_clicked)
        header_box.append(add_btn)

        self.append(header_box)

        pic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER)
        pic_box.set_margin_top(4)
        pic_box.set_margin_bottom(8)
        pic_box.set_margin_start(8)
        pic_box.set_margin_end(8)

        self.picture = Gtk.Picture()
        self.picture.set_size_request(120, 160)
        self.picture.set_can_shrink(True)
        self.picture.set_keep_aspect_ratio(True)
        pic_box.append(self.picture)

        self.append(pic_box)

        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.set_button(1)
        click_ctrl.connect("pressed", self._on_gesture_pressed)
        self.add_controller(click_ctrl)

    def set_thumbnail(self, pixbuf):
        self.pixbuf = pixbuf
        if pixbuf:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.picture.set_paintable(texture)

    def _on_add_clicked(self, _button):
        self._add_to_target()

    def _on_gesture_pressed(self, _gesture, n_press, _x, _y):
        if n_press == 2:
            self._add_to_target()

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

        self.choose_btn = Gtk.Button.new_from_icon_name("document-open-symbolic")
        self.choose_btn.set_tooltip_text(_("merge_btn_choose_pdf"))
        self.choose_btn.add_css_class("flat")
        self.choose_btn.connect("clicked", self.on_choose_clicked)
        top_row.append(self.choose_btn)

        self.add_all_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        self.add_all_btn.set_tooltip_text(_("merge_add_all_tip"))
        self.add_all_btn.add_css_class("flat")
        self.add_all_btn.set_sensitive(False)
        self.add_all_btn.connect("clicked", self.on_add_all_clicked)
        top_row.append(self.add_all_btn)

        self.clear_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        self.clear_btn.set_tooltip_text(_("merge_clear_tip"))
        self.clear_btn.add_css_class("flat")
        self.clear_btn.set_sensitive(False)
        self.clear_btn.connect("clicked", lambda b: self.clear())
        top_row.append(self.clear_btn)

        header_card.append(top_row)

        self.file_lbl = Gtk.Label(label="", xalign=0.0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.file_lbl.add_css_class("dim-label")
        self.file_lbl.add_css_class("caption")
        self.file_lbl.set_margin_start(10)
        self.file_lbl.set_margin_end(10)
        self.file_lbl.set_margin_bottom(8)
        header_card.append(self.file_lbl)

        self.append(header_card)

        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, vexpand=True)
        self.empty_box.set_margin_start(20)
        self.empty_box.set_margin_end(20)

        empty_icon = Gtk.Image.new_from_icon_name("document-open-symbolic")
        empty_icon.set_pixel_size(48)
        empty_icon.add_css_class("dim-label")
        self.empty_box.append(empty_icon)

        empty_title = Gtk.Label(label=_("merge_empty_source_title"))
        empty_title.add_css_class("heading")
        self.empty_box.append(empty_title)

        empty_desc = Gtk.Label(label=_("merge_empty_source_desc"), wrap=True, justify=Gtk.Justification.CENTER)
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
            pixbuf = pdf_handler.generate_thumbnail(self.doc, index, target_width=140)
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


class TargetPageCard(Gtk.Box):
    def __init__(self, target_panel, target_idx: int, page_entry: dict):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.target_panel = target_panel
        self.target_idx = target_idx
        self.page_entry = page_entry

        self.add_css_class("card")
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_start(8)
        header_box.set_margin_end(8)
        header_box.set_margin_top(6)

        idx_lbl = Gtk.Label(label=f"#{target_idx + 1}")
        idx_lbl.add_css_class("heading")
        header_box.append(idx_lbl)

        role_str = "A" if page_entry.get("source_role") == "source_a" else "B"
        src_page = page_entry.get("page_index", 0) + 1
        src_badge = Gtk.Label(label=f"Doc {role_str} : p.{src_page}", hexpand=True, xalign=0.0)
        src_badge.add_css_class("dim-label")
        src_badge.add_css_class("caption")
        header_box.append(src_badge)

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

        pic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER)
        pic_box.set_margin_top(4)
        pic_box.set_margin_bottom(8)
        pic_box.set_margin_start(8)
        pic_box.set_margin_end(8)

        self.picture = Gtk.Picture()
        self.picture.set_size_request(120, 160)
        self.picture.set_can_shrink(True)
        self.picture.set_keep_aspect_ratio(True)

        pixbuf = page_entry.get("thumbnail_pixbuf")
        if pixbuf:
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.picture.set_paintable(texture)

        pic_box.append(self.picture)
        self.append(pic_box)

    def update_position(self, target_idx: int, total_pages: int):
        self.target_idx = target_idx
        first_child = self.get_first_child()
        if first_child:
            idx_lbl = first_child.get_first_child()
            if isinstance(idx_lbl, Gtk.Label):
                idx_lbl.set_text(f"#{target_idx + 1}")
        self.up_btn.set_sensitive(target_idx > 0)
        self.down_btn.set_sensitive(target_idx < total_pages - 1)


class TargetDocumentPanel(Gtk.Box):
    def __init__(self, dialog, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.dialog = dialog
        self.title_str = title
        self.pages = []
        self.page_cards = []

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

        self.clear_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        self.clear_btn.set_tooltip_text(_("merge_clear_target_tip"))
        self.clear_btn.add_css_class("flat")
        self.clear_btn.set_sensitive(False)
        self.clear_btn.connect("clicked", lambda b: self.clear())
        top_row.append(self.clear_btn)

        header_card.append(top_row)

        desc_lbl = Gtk.Label(label=_("merge_workspace_subtitle"), xalign=0.0)
        desc_lbl.add_css_class("dim-label")
        desc_lbl.add_css_class("caption")
        desc_lbl.set_margin_start(10)
        desc_lbl.set_margin_end(10)
        desc_lbl.set_margin_bottom(8)
        header_card.append(desc_lbl)

        self.append(header_card)

        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, vexpand=True)
        self.empty_box.set_margin_start(20)
        self.empty_box.set_margin_end(20)

        empty_icon = Gtk.Image.new_from_icon_name("edit-copy-symbolic")
        empty_icon.set_pixel_size(48)
        empty_icon.add_css_class("dim-label")
        self.empty_box.append(empty_icon)

        empty_title = Gtk.Label(label=_("merge_empty_target_title"))
        empty_title.add_css_class("heading")
        self.empty_box.append(empty_title)

        empty_desc = Gtk.Label(label=_("merge_empty_target_desc"), wrap=True, justify=Gtk.Justification.CENTER)
        empty_desc.add_css_class("dim-label")
        empty_desc.add_css_class("caption")
        self.empty_box.append(empty_desc)

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

    def add_page(self, source_role: str, source_path: str, source_doc, page_index: int,
                 thumbnail_pixbuf, page_width: float, page_height: float):
        entry = {
            "source_role": source_role,
            "source_path": source_path,
            "source_doc": source_doc,
            "page_index": page_index,
            "thumbnail_pixbuf": thumbnail_pixbuf,
            "page_width": page_width,
            "page_height": page_height,
        }
        self.pages.append(entry)
        idx = len(self.pages) - 1

        card = TargetPageCard(self, target_idx=idx, page_entry=entry)
        self.page_cards.append(card)
        self.ribbon_box.append(card)

        self._refresh_state()

    def remove_page(self, target_idx: int):
        if 0 <= target_idx < len(self.pages):
            self.pages.pop(target_idx)
            card = self.page_cards.pop(target_idx)
            self.ribbon_box.remove(card)
            self._refresh_state()

    def move_page(self, from_idx: int, to_idx: int):
        if 0 <= from_idx < len(self.pages) and 0 <= to_idx < len(self.pages) and from_idx != to_idx:
            item = self.pages.pop(from_idx)
            self.pages.insert(to_idx, item)

            child = self.ribbon_box.get_first_child()
            while child:
                self.ribbon_box.remove(child)
                child = self.ribbon_box.get_first_child()

            self.page_cards.clear()
            for idx, entry in enumerate(self.pages):
                card = TargetPageCard(self, target_idx=idx, page_entry=entry)
                self.page_cards.append(card)
                self.ribbon_box.append(card)

            self._refresh_state()

    def clear(self):
        self.pages.clear()
        self.page_cards.clear()
        child = self.ribbon_box.get_first_child()
        while child:
            self.ribbon_box.remove(child)
            child = self.ribbon_box.get_first_child()
        self._refresh_state()

    def _refresh_state(self):
        count = len(self.pages)
        self.page_badge.set_text(_("merge_page_count", count))
        self.clear_btn.set_sensitive(count > 0)
        self.empty_box.set_visible(count == 0)
        self.scroll.set_visible(count > 0)

        for idx, card in enumerate(self.page_cards):
            card.update_position(idx, count)

        if self.dialog:
            self.dialog._on_target_pages_changed()


class MergeDialog(Adw.Window):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window

        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("merge_workspace_title"))
        self.set_default_size(820, 520)
        self.set_size_request(680, 420)
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

        main_box.append(header)

        panels_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0, vexpand=True, homogeneous=True)

        self.panel_a = SourceDocumentPanel(self, role="source_a", title=_("merge_source_a"))
        panels_box.append(self.panel_a)

        panels_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.target_panel = TargetDocumentPanel(self, title=_("merge_target_doc"))
        panels_box.append(self.target_panel)

        panels_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.panel_b = SourceDocumentPanel(self, role="source_b", title=_("merge_source_b"))
        panels_box.append(self.panel_b)

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

    def _on_save_clicked(self, _button):
        pass

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
