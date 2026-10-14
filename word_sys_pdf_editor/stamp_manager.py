import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cairo
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

from .i18n import _, _CONFIG_DIR


class CustomStamp:
    """Data model representing a rubber stamp or custom image stamp."""

    def __init__(
        self,
        stamp_id: str,
        name: str,
        category: str = "Standard",
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        default_width: float = 160.0,
        default_height: float = 60.0,
        created_at: Optional[str] = None,
        is_builtin: bool = False,
        is_password_protected: bool = False,
        password_hash: Optional[str] = None,
    ):
        self.id = stamp_id
        self.name = name
        self.category = category
        self.image_path = image_path
        self.image_bytes = image_bytes or b""
        self.default_width = float(default_width)
        self.default_height = float(default_height)
        self.created_at = created_at or datetime.now().isoformat()
        self.is_builtin = is_builtin
        self.is_password_protected = is_password_protected
        self.password_hash = password_hash
        self._pixbuf = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "image_filename": Path(self.image_path).name if self.image_path else f"{self.id}.png",
            "default_width": self.default_width,
            "default_height": self.default_height,
            "created_at": self.created_at,
            "is_builtin": self.is_builtin,
            "is_password_protected": self.is_password_protected,
            "password_hash": self.password_hash,
        }

    @classmethod
    def from_dict(cls, data: dict, stamps_dir: Path) -> "CustomStamp":
        filename = data.get("image_filename") or f"{data['id']}.png"
        img_path = stamps_dir / filename
        img_bytes = b""
        if img_path.exists():
            try:
                with open(img_path, "rb") as f:
                    img_bytes = f.read()
            except Exception as e:
                print(f"Warning loading stamp {data.get('id')}: {e}")

        return cls(
            stamp_id=data["id"],
            name=data.get("name", "Stamp"),
            category=data.get("category", "Standard"),
            image_path=str(img_path),
            image_bytes=img_bytes,
            default_width=data.get("default_width", 160.0),
            default_height=data.get("default_height", 60.0),
            created_at=data.get("created_at"),
            is_builtin=data.get("is_builtin", False),
            is_password_protected=data.get("is_password_protected", False),
            password_hash=data.get("password_hash"),
        )

    def get_pixbuf(self) -> Optional[GdkPixbuf.Pixbuf]:
        """Get or load GdkPixbuf for thumbnail rendering."""
        if self._pixbuf:
            return self._pixbuf
        if self.image_bytes:
            try:
                loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                loader.write(self.image_bytes)
                loader.close()
                self._pixbuf = loader.get_pixbuf()
                return self._pixbuf
            except Exception:
                pass
        if self.image_path and os.path.exists(self.image_path):
            try:
                self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.image_path)
                return self._pixbuf
            except Exception:
                pass
        return None

    def get_paintable(self) -> Optional[Gdk.Paintable]:
        """Convert pixbuf to GTK4 paintable for Gtk.Picture."""
        pixbuf = self.get_pixbuf()
        if pixbuf:
            try:
                return Gdk.Texture.new_for_pixbuf(pixbuf)
            except Exception as e:
                print(f"Error creating texture for stamp: {e}")
        return None


def generate_cairo_stamp_png(
    text: str,
    color_rgb: Tuple[float, float, float],
    width: int = 240,
    height: int = 80,
    border_radius: float = 8.0,
) -> bytes:
    """Render a clean, high-resolution rubber stamp with double-border and bold text to PNG bytes."""
    import io

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)

    # Clean transparent background
    cr.set_operator(cairo.OPERATOR_CLEAR)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)

    r, g, b = color_rgb
    margin = 4.0
    line_w = 3.5

    x0 = margin + line_w / 2.0
    y0 = margin + line_w / 2.0
    w0 = width - 2.0 * margin - line_w
    h0 = height - 2.0 * margin - line_w

    # Outer rounded rectangle
    cr.set_source_rgba(r, g, b, 0.95)
    cr.set_line_width(line_w)

    def _draw_rounded_rect(ctx, x, y, w, h, rad):
        ctx.new_sub_path()
        ctx.arc(x + w - rad, y + rad, rad, -1.570796, 0)
        ctx.arc(x + w - rad, y + h - rad, rad, 0, 1.570796)
        ctx.arc(x + rad, y + h - rad, rad, 1.570796, 3.141592)
        ctx.arc(x + rad, y + rad, rad, 3.141592, 4.712388)
        ctx.close_path()

    _draw_rounded_rect(cr, x0, y0, w0, h0, border_radius)
    cr.stroke()

    # Inner decorative thin border
    inner_gap = 4.0
    xi = x0 + inner_gap
    yi = y0 + inner_gap
    wi = w0 - 2.0 * inner_gap
    hi = h0 - 2.0 * inner_gap
    radiusi = max(2.0, border_radius - inner_gap)

    cr.set_line_width(1.5)
    _draw_rounded_rect(cr, xi, yi, wi, hi, radiusi)
    cr.stroke()

    # Centered bold uppercase typography
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    font_size = 28.0
    cr.set_font_size(font_size)

    # Dynamically scale font down if text exceeds available width
    extents = cr.text_extents(text)
    available_w = wi - 16.0
    if extents.width > available_w and extents.width > 0:
        scale = available_w / extents.width
        font_size = max(14.0, font_size * scale)
        cr.set_font_size(font_size)
        extents = cr.text_extents(text)

    tx = (width - extents.width) / 2.0 - extents.x_bearing
    ty = (height - extents.height) / 2.0 - extents.y_bearing
    cr.set_source_rgba(r, g, b, 0.95)
    cr.move_to(tx, ty)
    cr.show_text(text)

    buf = io.BytesIO()
    surface.write_to_png(buf)
    return buf.getvalue()


class StampLibrary:
    """Persistent catalog and manager for built-in and user-imported custom stamps."""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = Path(storage_dir) if storage_dir else (_CONFIG_DIR / "stamps")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_file = self.storage_dir / "stamps.json"
        self.stamps: List[CustomStamp] = []
        self.active_stamp_id: Optional[str] = None
        self.load()

    def load(self):
        """Load stamps from disk, or initialize defaults if missing."""
        self.stamps = []
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.active_stamp_id = data.get("active_stamp_id")
                    for stamp_dict in data.get("stamps", []):
                        stamp = CustomStamp.from_dict(stamp_dict, self.storage_dir)
                        if stamp.image_bytes:
                            self.stamps.append(stamp)
            except Exception as e:
                print(f"Warning reading stamp manifest: {e}")

        # If library has no stamps or builtins are missing, generate built-ins
        existing_ids = {s.id for s in self.stamps}
        if not self.stamps or not any(s.is_builtin for s in self.stamps):
            self._generate_builtin_stamps(existing_ids)
            self.save()

        if not self.active_stamp_id and self.stamps:
            self.active_stamp_id = self.stamps[0].id

    def save(self):
        """Save stamp metadata and active stamp to stamps.json."""
        try:
            payload = {
                "active_stamp_id": self.active_stamp_id,
                "stamps": [s.to_dict() for s in self.stamps],
            }
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            print(f"Warning saving stamp manifest: {e}")

    def _generate_builtin_stamps(self, existing_ids: set):
        """Create standard out-of-the-box stamps."""
        builtins_spec = [
            ("builtin_approved", _("stamp_builtin_approved"), (0.15, 0.65, 0.25), "Standard", 160.0, 54.0),
            ("builtin_confidential", _("stamp_builtin_confidential"), (0.85, 0.15, 0.15), "Standard", 170.0, 54.0),
            ("builtin_draft", _("stamp_builtin_draft"), (0.1, 0.45, 0.85), "Standard", 150.0, 54.0),
            ("builtin_rejected", _("stamp_builtin_rejected"), (0.75, 0.1, 0.1), "Review", 160.0, 54.0),
            ("builtin_final", _("stamp_builtin_final"), (0.05, 0.5, 0.45), "Standard", 150.0, 54.0),
            ("builtin_void", _("stamp_builtin_void"), (0.35, 0.35, 0.35), "Review", 150.0, 54.0),
        ]

        for s_id, name, color, category, width, height in builtins_spec:
            if s_id in existing_ids:
                continue
            img_bytes = generate_cairo_stamp_png(name, color, width=int(width * 1.5), height=int(height * 1.5))
            img_path = self.storage_dir / f"{s_id}.png"
            try:
                with open(img_path, "wb") as f:
                    f.write(img_bytes)
            except Exception as e:
                print(f"Error saving builtin stamp {s_id}: {e}")

            stamp = CustomStamp(
                stamp_id=s_id,
                name=name,
                category=category,
                image_path=str(img_path),
                image_bytes=img_bytes,
                default_width=width,
                default_height=height,
                is_builtin=True,
            )
            self.stamps.append(stamp)

    def import_stamp_from_file(
        self,
        source_path: str,
        name: Optional[str] = None,
        category: str = "Custom",
        target_width: float = 160.0,
    ) -> Optional[CustomStamp]:
        """Import an external image file into the persistent library normalized to PNG."""
        src = Path(source_path)
        if not src.exists() or not src.is_file():
            return None

        stamp_name = (name or src.stem).strip()
        stamp_id = f"stamp_{uuid.uuid4().hex[:10]}"

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(src))
            orig_w = pixbuf.get_width()
            orig_h = pixbuf.get_height()

            # Normalize to PNG bytes
            ok, img_bytes = pixbuf.save_to_bufferv("png", [], [])
            if not ok or not img_bytes:
                return None

            # Calculate appropriate default dimension preserving aspect ratio
            aspect = float(orig_h) / float(orig_w) if orig_w > 0 else 0.5
            calc_w = target_width
            calc_h = max(24.0, round(calc_w * aspect, 1))

            dest_path = self.storage_dir / f"{stamp_id}.png"
            with open(dest_path, "wb") as f:
                f.write(img_bytes)

            stamp = CustomStamp(
                stamp_id=stamp_id,
                name=stamp_name,
                category=category,
                image_path=str(dest_path),
                image_bytes=img_bytes,
                default_width=calc_w,
                default_height=calc_h,
                is_builtin=False,
            )
            self.stamps.append(stamp)
            self.active_stamp_id = stamp.id
            self.save()
            return stamp
        except Exception as e:
            print(f"Error importing stamp from {source_path}: {e}")
            return None

    def delete_stamp(self, stamp_id: str) -> bool:
        """Delete custom stamp from library (built-ins are protected)."""
        target = self.get_stamp(stamp_id)
        if not target or target.is_builtin:
            return False

        if target.image_path and os.path.exists(target.image_path):
            try:
                os.remove(target.image_path)
            except OSError:
                pass

        self.stamps = [s for s in self.stamps if s.id != stamp_id]
        if self.active_stamp_id == stamp_id:
            self.active_stamp_id = self.stamps[0].id if self.stamps else None
        self.save()
        return True

    def get_stamp(self, stamp_id: str) -> Optional[CustomStamp]:
        for s in self.stamps:
            if s.id == stamp_id:
                return s
        return None

    def get_active_stamp(self) -> Optional[CustomStamp]:
        if self.active_stamp_id:
            stamp = self.get_stamp(self.active_stamp_id)
            if stamp:
                return stamp
        return self.stamps[0] if self.stamps else None

    def set_active_stamp(self, stamp_id: str):
        if self.get_stamp(stamp_id):
            self.active_stamp_id = stamp_id
            self.save()

    def get_categories(self) -> List[str]:
        cats = []
        for s in self.stamps:
            if s.category not in cats:
                cats.append(s.category)
        return cats


class StampManagerDialog(Adw.Window):
    """Modern Libadwaita modal dialog for browsing, importing, and managing custom stamps."""

    def __init__(self, parent_window, library: StampLibrary, on_stamp_selected_callback=None):
        super().__init__()
        self.parent_window = parent_window
        self.library = library
        self.on_stamp_selected_callback = on_stamp_selected_callback
        self.active_filter_category = "All"

        if parent_window:
            self.set_transient_for(parent_window)
            self.set_modal(True)
        self.set_title(_("stamp_manager_title"))
        self.set_default_size(680, 540)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # HeaderBar
        header = Adw.HeaderBar()
        self.import_btn = Gtk.Button(label=_("stamp_import_btn"))
        self.import_btn.add_css_class("suggested-action")
        self.import_btn.connect("clicked", self._on_import_clicked)
        header.pack_start(self.import_btn)

        self.done_btn = Gtk.Button(label=_("btn_confirm"))
        self.done_btn.connect("clicked", lambda b: self.destroy())
        header.pack_end(self.done_btn)
        main_box.append(header)

        # Category Filter Tabs
        self.filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.filter_box.set_margin_start(16)
        self.filter_box.set_margin_end(16)
        self.filter_box.set_margin_top(12)
        self.filter_box.set_margin_bottom(6)
        main_box.append(self.filter_box)

        self._build_category_filters()

        # Scrolled Grid View
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=640)
        clamp.set_margin_top(8)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        self.cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        clamp.set_child(self.cards_box)

        self._populate_stamps_view()

    def _build_category_filters(self):
        """Construct filter toggle buttons for categories."""
        while child := self.filter_box.get_first_child():
            self.filter_box.remove(child)

        all_cats = ["All"] + self.library.get_categories()
        first_btn = None
        for cat in all_cats:
            label = cat if cat != "All" else _("recent_header").replace("<b>", "").replace("</b>", "").strip() or "All"
            btn = Gtk.ToggleButton(label=cat)
            if not first_btn:
                first_btn = btn
            else:
                btn.set_group(first_btn)

            if cat == self.active_filter_category:
                btn.set_active(True)

            btn.connect("toggled", self._on_category_toggled, cat)
            self.filter_box.append(btn)

    def _on_category_toggled(self, button, category):
        if button.get_active():
            self.active_filter_category = category
            self._populate_stamps_view()

    def _populate_stamps_view(self):
        """Render stamps cards."""
        while child := self.cards_box.get_first_child():
            self.cards_box.remove(child)

        filtered = [
            s for s in self.library.stamps
            if self.active_filter_category == "All" or s.category == self.active_filter_category
        ]

        if not filtered:
            empty_status = Adw.StatusPage()
            empty_status.set_icon_name("tag-symbolic")
            empty_status.set_title(_("stamp_no_stamps"))
            self.cards_box.append(empty_status)
            return

        group = Adw.PreferencesGroup()
        self.cards_box.append(group)

        active_id = self.library.active_stamp_id

        for stamp in filtered:
            row = Adw.ActionRow()
            row.set_title(stamp.name)
            is_active = (stamp.id == active_id)

            subtitle = f"{stamp.category} • {int(stamp.default_width)} × {int(stamp.default_height)} pt"
            if stamp.is_builtin:
                subtitle += f" • {_('stamp_cat_standard')}"
            row.set_subtitle(subtitle)

            # Left thumbnail preview
            paintable = stamp.get_paintable()
            if paintable:
                pic = Gtk.Picture.new_for_paintable(paintable)
                pic.set_can_shrink(True)
                pic.set_size_request(90, 36)
                pic.set_margin_end(12)
                row.add_prefix(pic)
            else:
                icon = Gtk.Image.new_from_icon_name("tag-symbolic")
                icon.set_pixel_size(32)
                row.add_prefix(icon)

            # Active indicator / Select button
            if is_active:
                badge = Gtk.Button.new_from_icon_name("emblem-ok-symbolic")
                badge.add_css_class("flat")
                badge.add_css_class("accent")
                badge.set_tooltip_text(_("stamp_active_label"))
                row.add_suffix(badge)
            else:
                set_btn = Gtk.Button(label=_("stamp_set_active"))
                set_btn.add_css_class("flat")
                set_btn.connect("clicked", self._on_set_active_clicked, stamp.id)
                row.add_suffix(set_btn)

            # Delete button for custom imported stamps
            if not stamp.is_builtin:
                del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
                del_btn.add_css_class("flat")
                del_btn.add_css_class("destructive-action")
                del_btn.set_tooltip_text(_("stamp_delete_btn"))
                del_btn.connect("clicked", self._on_delete_clicked, stamp.id)
                row.add_suffix(del_btn)

            group.add(row)

    def _on_set_active_clicked(self, btn, stamp_id):
        self.library.set_active_stamp(stamp_id)
        self._populate_stamps_view()
        if self.on_stamp_selected_callback:
            self.on_stamp_selected_callback(self.library.get_stamp(stamp_id))

    def _on_delete_clicked(self, btn, stamp_id):
        self.library.delete_stamp(stamp_id)
        self._build_category_filters()
        self._populate_stamps_view()

    def _on_import_clicked(self, btn):
        """Open file dialog to pick an image for a new stamp."""
        filter_img = Gtk.FileFilter()
        filter_img.set_name(_("stamp_filter_image"))
        for mime in ["image/png", "image/jpeg", "image/svg+xml", "image/webp", "image/bmp"]:
            filter_img.add_mime_type(mime)

        dialog = Gtk.FileDialog()
        dialog.set_title(_("stamp_import_title"))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_img)
        dialog.set_filters(filters)

        def _on_file_opened(dlg, result):
            try:
                gfile = dlg.open_finish(result)
                if gfile:
                    file_path = gfile.get_path()
                    if file_path:
                        stamp = self.library.import_stamp_from_file(file_path)
                        if stamp:
                            self._build_category_filters()
                            self._populate_stamps_view()
                            if self.on_stamp_selected_callback:
                                self.on_stamp_selected_callback(stamp)
            except Exception as e:
                print(f"Error opening image file: {e}")

        dialog.open(self, None, _on_file_opened)


class StampPopover(Gtk.Popover):
    """Compact quick-picker popover attached to the stamp tool button."""

    def __init__(self, library: StampLibrary, on_stamp_chosen_callback=None, on_manage_clicked_callback=None):
        super().__init__()
        self.library = library
        self.on_stamp_chosen_callback = on_stamp_chosen_callback
        self.on_manage_clicked_callback = on_manage_clicked_callback

        self.set_has_arrow(True)
        self.set_size_request(240, -1)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        container.set_margin_top(8)
        container.set_margin_bottom(8)
        container.set_margin_start(8)
        container.set_margin_end(8)
        self.set_child(container)

        title_label = Gtk.Label(label=f"<b>{_('stamp_quick_menu')}</b>", use_markup=True, xalign=0.0)
        title_label.set_margin_bottom(4)
        container.append(title_label)

        self.list_box = Gtk.ListBox()
        self.list_box.add_css_class("boxed-list")
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        container.append(self.list_box)

        # Refresh stamp list
        self.refresh()

        # Separator & Manage Library button
        container.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=6, margin_bottom=4))

        manage_btn = Gtk.Button(label=_("menu_manage_stamps"))
        manage_btn.add_css_class("flat")
        manage_btn.connect("clicked", self._on_manage_clicked)
        container.append(manage_btn)

    def refresh(self):
        """Re-render items inside the popover."""
        while child := self.list_box.get_first_child():
            self.list_box.remove(child)

        active_id = self.library.active_stamp_id

        for stamp in self.library.stamps[:8]:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hbox.set_margin_top(4)
            hbox.set_margin_bottom(4)
            hbox.set_margin_start(6)
            hbox.set_margin_end(6)
            row.set_child(hbox)

            paintable = stamp.get_paintable()
            if paintable:
                pic = Gtk.Picture.new_for_paintable(paintable)
                pic.set_can_shrink(True)
                pic.set_size_request(60, 24)
                hbox.append(pic)
            else:
                icon = Gtk.Image.new_from_icon_name("tag-symbolic")
                icon.set_pixel_size(18)
                hbox.append(icon)

            lbl = Gtk.Label(label=stamp.name, xalign=0.0, hexpand=True)
            hbox.append(lbl)

            if stamp.id == active_id:
                check = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                check.add_css_class("accent")
                hbox.append(check)

            # Clicking row activates stamp
            click_gesture = Gtk.GestureClick()
            click_gesture.connect("released", self._on_row_clicked, stamp.id)
            row.add_controller(click_gesture)

            self.list_box.append(row)

    def _on_row_clicked(self, gesture, n_press, x, y, stamp_id):
        self.library.set_active_stamp(stamp_id)
        self.popdown()
        if self.on_stamp_chosen_callback:
            self.on_stamp_chosen_callback(self.library.get_stamp(stamp_id))

    def _on_manage_clicked(self, btn):
        self.popdown()
        if self.on_manage_clicked_callback:
            self.on_manage_clicked_callback()
