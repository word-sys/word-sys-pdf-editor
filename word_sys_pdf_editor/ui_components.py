import gi
import io
import cairo
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, GdkPixbuf, Adw, GLib, GObject, Gio, Pango, PangoCairo
from .i18n import _


_PLACEHOLDER_TEXTURE = None

def get_thumbnail_placeholder_texture():
    """Return a cached singleton neutral document placeholder texture for unrendered pages."""
    global _PLACEHOLDER_TEXTURE
    if _PLACEHOLDER_TEXTURE is not None:
        return _PLACEHOLDER_TEXTURE
    try:
        width, height = 150, 200
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
        cr = cairo.Context(surface)
        
        cr.set_source_rgb(0.95, 0.95, 0.96)
        cr.paint()
        
        cr.set_source_rgb(0.98, 0.98, 0.99)
        cr.rectangle(12, 12, width - 24, height - 24)
        cr.fill()
        
        cr.set_source_rgb(0.85, 0.85, 0.88)
        cr.set_line_width(1.0)
        cr.rectangle(12.5, 12.5, width - 25, height - 25)
        cr.stroke()
        
        cr.set_source_rgb(0.88, 0.88, 0.91)
        for y in range(40, height - 40, 18):
            cr.rectangle(24, y, width - 48, 4)
            cr.fill()
            
        cr.set_source_rgb(0.80, 0.80, 0.83)
        cr.rectangle(0.5, 0.5, width - 1, height - 1)
        cr.stroke()
        
        pix = GdkPixbuf.Pixbuf.new_from_data(
            surface.get_data(), GdkPixbuf.Colorspace.RGB, False, 8,
            surface.get_width(), surface.get_height(), surface.get_stride()
        )
        _PLACEHOLDER_TEXTURE = Gdk.Texture.new_for_pixbuf(pix)
        return _PLACEHOLDER_TEXTURE
    except Exception:
        return None


class PageThumbnailFactory(Gtk.SignalListItemFactory):
    """Factory class to create and bind page thumbnail widgets in the sidebar."""
    def __init__(self, editor_window=None):
        """Initialise the factory with setup, bind, unbind, and teardown signal handlers."""
        super().__init__()
        self.editor_window = editor_window
        self.connect("setup", self._on_setup)
        self.connect("bind", self._on_bind)
        self.connect("unbind", self._on_unbind)
        self.connect("teardown", self._on_teardown)

    @staticmethod
    def parse_drag_payload(value, editor_window=None):
        """Extract `(source_session_id, from_idx)` from a drag drop value or active window drag state."""
        source_session_id = None
        from_idx = None

        if isinstance(value, str):
            if ":" in value:
                sid_part, idx_part = value.rsplit(":", 1)
                source_session_id = sid_part if sid_part else None
                try:
                    from_idx = int(idx_part)
                except (TypeError, ValueError):
                    from_idx = None
            else:
                try:
                    from_idx = int(value)
                except (TypeError, ValueError):
                    from_idx = None
        elif isinstance(value, int) and not isinstance(value, bool):
            from_idx = int(value)

        if editor_window is not None:
            active_drag = getattr(editor_window, "_active_thumbnail_drag", None)
            if isinstance(active_drag, tuple) and len(active_drag) == 2:
                drag_sid, drag_idx = active_drag
                if from_idx is None:
                    from_idx = drag_idx
                if source_session_id is None and isinstance(drag_sid, str) and drag_sid:
                    source_session_id = drag_sid

        return source_session_id, from_idx

    def _ensure_controllers(self, box, list_item):
        """Attach drag, drop, and right-click controllers to the thumbnail box once."""
        if getattr(box, '_controllers_attached', False):
            return

        drag_source = Gtk.DragSource.new()
        drag_source.set_actions(Gdk.DragAction.MOVE | Gdk.DragAction.COPY)

        def on_prepare(source, x, y):
            if self.editor_window and getattr(self.editor_window, 'view_mode', False):
                return None
            pdf_pg = list_item.get_item()
            if not pdf_pg:
                return None

            source_session_id = None
            if self.editor_window is not None:
                active_sess = getattr(self.editor_window, '_active_session', None)
                sid = getattr(active_sess, 'session_id', None) if active_sess is not None else None
                if isinstance(sid, str) and sid:
                    source_session_id = sid
                self.editor_window._active_thumbnail_drag = (source_session_id, int(pdf_pg.index))

            int_val = GObject.Value(GObject.TYPE_INT, int(pdf_pg.index))
            int_provider = Gdk.ContentProvider.new_for_value(int_val)
            if source_session_id:
                str_val = GObject.Value(
                    GObject.TYPE_STRING,
                    f"{source_session_id}:{int(pdf_pg.index)}",
                )
                str_provider = Gdk.ContentProvider.new_for_value(str_val)
                if hasattr(Gdk.ContentProvider, "new_union"):
                    return Gdk.ContentProvider.new_union([str_provider, int_provider])
                return str_provider
            return int_provider

        def on_drag_begin(source, drag):
            pdf_pg = list_item.get_item()
            if pdf_pg and getattr(pdf_pg, 'thumbnail', None):
                tex = Gdk.Texture.new_for_pixbuf(pdf_pg.thumbnail)
                Gtk.DragSource.set_icon(source, tex, 0, 0)

        def on_drag_end(source, drag, delete_data):
            if self.editor_window is not None:
                self.editor_window._active_thumbnail_drag = None
                if hasattr(self.editor_window, "_cancel_tab_hover_switch_timer"):
                    self.editor_window._cancel_tab_hover_switch_timer()

        drag_source.connect("prepare", on_prepare)
        drag_source.connect("drag-begin", on_drag_begin)
        drag_source.connect("drag-end", on_drag_end)
        box.add_controller(drag_source)

        drop_target = Gtk.DropTarget.new(
            GObject.TYPE_INT,
            Gdk.DragAction.MOVE | Gdk.DragAction.COPY,
        )
        drop_target.set_gtypes([GObject.TYPE_INT, GObject.TYPE_STRING])

        def on_drop(target, value, x, y):
            source_session_id, from_idx = self.parse_drag_payload(value, self.editor_window)
            target_session_id = None
            if self.editor_window is not None:
                active_sess = getattr(self.editor_window, '_active_session', None)
                sid = getattr(active_sess, 'session_id', None) if active_sess is not None else None
                if isinstance(sid, str) and sid:
                    target_session_id = sid

            is_cross_tab = (
                source_session_id is not None
                and target_session_id is not None
                and source_session_id != target_session_id
            )

            if self.editor_window and getattr(self.editor_window, 'view_mode', False):
                if is_cross_tab:
                    self.editor_window.view_mode = False
                    if hasattr(self.editor_window, '_update_ui_state'):
                        self.editor_window._update_ui_state()
                else:
                    return False

            pdf_pg = list_item.get_item()
            if not pdf_pg or from_idx is None:
                return False

            to_idx = int(pdf_pg.index)
            if self.editor_window is not None:
                self.editor_window._active_thumbnail_drag = None

            is_copy_action = bool(
                getattr(self.editor_window, "_thumbnail_drag_copy_modifier", False)
            )
            current_drop = target.get_current_drop() if hasattr(target, "get_current_drop") else None
            if current_drop is not None and hasattr(current_drop, "get_actions"):
                try:
                    if current_drop.get_actions() == Gdk.DragAction.COPY:
                        is_copy_action = True
                except Exception:
                    pass

            if is_cross_tab or is_copy_action:
                if self.editor_window and hasattr(self.editor_window, 'copy_page_from_session'):
                    return bool(
                        self.editor_window.copy_page_from_session(
                            source_session_id,
                            from_idx,
                            to_idx,
                        )
                    )
                return False

            if from_idx == to_idx:
                return False
            if self.editor_window and hasattr(self.editor_window, 'on_page_reorder'):
                self.editor_window.on_page_reorder(from_idx, to_idx)
            return True

        drop_target.connect("drop", on_drop)
        box.add_controller(drop_target)

        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)

        def on_right_click(gesture, n_press, rx, ry):
            pdf_pg = list_item.get_item()
            if not pdf_pg:
                return
            if self.editor_window and hasattr(self.editor_window, 'show_thumbnail_context_menu'):
                self.editor_window.show_thumbnail_context_menu(box, rx, ry, pdf_pg.index)

        right_click.connect("pressed", on_right_click)
        box.add_controller(right_click)
        box._controllers_attached = True

    def _on_setup(self, factory, list_item):
        """Set up initial layout and controllers for the thumbnail list item."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6)
        
        image = Gtk.Picture()
        image.set_size_request(150, 200)
        image.set_can_shrink(False)
        placeholder = get_thumbnail_placeholder_texture()
        if placeholder:
            image.set_paintable(placeholder)

        label = Gtk.Label()
        label.set_halign(Gtk.Align.CENTER)
        
        box.append(image)
        box.append(label)
        list_item.set_child(box)
        self._ensure_controllers(box, list_item)

    def _on_bind(self, factory, list_item):
        """Bind a PDF page object and its thumbnail image to the list item."""
        box = list_item.get_child()
        if not box:
            return
        self._ensure_controllers(box, list_item)

        picture = box.get_first_child()
        label = box.get_last_child()
        pdf_page = list_item.get_item()
        if not pdf_page:
            return

        label.set_text(_("page_info").format(pdf_page.index + 1))
        self._cleanup_notification(box)

        is_eco = getattr(self.editor_window, 'is_eco_mode', False) if self.editor_window else False
        thumb_w = 100 if is_eco else 150
        thumb_h = 133 if is_eco else 200

        if getattr(pdf_page, 'thumbnail', None):
            picture.set_size_request(thumb_w, -1)
            texture = Gdk.Texture.new_for_pixbuf(pdf_page.thumbnail)
            picture.set_paintable(texture)
            picture.set_visible(True)
        else:
            picture.set_size_request(thumb_w, thumb_h)
            placeholder = get_thumbnail_placeholder_texture()
            picture.set_paintable(placeholder)
            picture.set_visible(True)
            if self.editor_window and hasattr(self.editor_window, 'request_thumbnail'):
                self.editor_window.request_thumbnail(pdf_page.index)

        def on_thumb_notify(obj, pspec):
            if list_item.get_item() == obj:
                cur_eco = getattr(self.editor_window, 'is_eco_mode', False) if self.editor_window else False
                w = 100 if cur_eco else 150
                h = 133 if cur_eco else 200
                if getattr(obj, 'thumbnail', None):
                    picture.set_size_request(w, -1)
                    texture = Gdk.Texture.new_for_pixbuf(obj.thumbnail)
                    picture.set_paintable(texture)
                    picture.set_visible(True)
                else:
                    picture.set_size_request(w, h)
                    placeholder = get_thumbnail_placeholder_texture()
                    picture.set_paintable(placeholder)
                    picture.set_visible(True)

        if isinstance(pdf_page, GObject.GObject):
            try:
                handler_id = pdf_page.connect("notify::thumbnail", on_thumb_notify)
                box._thumb_handler_id = handler_id
                box._thumb_page = pdf_page
            except Exception:
                pass

    def _cleanup_notification(self, box):
        """Disconnect thumbnail notify listener from the previously bound item."""
        if not box:
            return
        handler_id = getattr(box, '_thumb_handler_id', None)
        page = getattr(box, '_thumb_page', None)
        if handler_id and page:
            try:
                if isinstance(page, GObject.GObject) and page.handler_is_connected(handler_id):
                    page.disconnect(handler_id)
            except Exception:
                pass
        box._thumb_handler_id = None
        box._thumb_page = None

    def _on_unbind(self, factory, list_item):
        """Recycle row: disconnect notification, release texture, and cancel off-screen request."""
        box = list_item.get_child()
        if box:
            self._cleanup_notification(box)
            picture = box.get_first_child()
            if picture:
                picture.set_paintable(None)
        pdf_page = list_item.get_item()
        if pdf_page and getattr(pdf_page, 'thumbnail', None) is None:
            if self.editor_window and hasattr(self.editor_window, 'cancel_thumbnail_request'):
                self.editor_window.cancel_thumbnail_request(pdf_page.index)

    def _on_teardown(self, factory, list_item):
        """Clean up all references when widget is destroyed."""
        box = list_item.get_child()
        if box:
            self._cleanup_notification(box)
        list_item.set_child(None)


def show_error_dialog(parent_window, message, title="Error"):
    """Show a simple error modal dialog."""
    dialog = Gtk.MessageDialog(
        transient_for=parent_window,
        modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        text=title,
        secondary_text=message
    )

    dialog.connect("response", lambda d, response_id: d.destroy())
    dialog.present()


def show_info_dialog(parent_window, message, title="Information"):
    """Show an information modal dialog."""
    dialog = Gtk.MessageDialog(
        transient_for=parent_window,
        modal=True,
        message_type=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text=title,
        secondary_text=message
    )

    dialog.connect("response", lambda d, response_id: d.destroy())
    dialog.present()

def show_confirm_dialog(parent_window, message, title="Confirm", destructive=True, checkbox_label=None):
    """Show a confirmation dialog with Accept and Cancel options, and optional checkbox."""
    message_type = Gtk.MessageType.QUESTION
    if destructive:
        message_type = Gtk.MessageType.WARNING

    dialog = Gtk.MessageDialog(
        transient_for=parent_window,
        modal=True,
        message_type=message_type,
        buttons=Gtk.ButtonsType.NONE,
        text=title,
        secondary_text=message
    )

    checkbox = None
    if checkbox_label:
        checkbox = Gtk.CheckButton(label=checkbox_label)
        checkbox.set_margin_top(10)
        checkbox.set_halign(Gtk.Align.START)
        dialog.get_message_area().append(checkbox)

    dialog.add_buttons(
        _("btn_cancel"), Gtk.ResponseType.CANCEL,
        _("btn_confirm"), Gtk.ResponseType.ACCEPT
    )
    dialog.set_default_size(450, -1)
    dialog.set_default_response(Gtk.ResponseType.CANCEL)

    response = None
    def on_response(d, resp_id):
        nonlocal response
        response = resp_id
        d.destroy()

    dialog.connect("response", on_response)
    dialog.present()

    while response is None:
         context = GLib.MainContext.default()
         context.iteration(True)

    dialog.destroy()
    accepted = (response == Gtk.ResponseType.ACCEPT)
    if checkbox_label:
        return accepted, (checkbox.get_active() if checkbox else False)
    return accepted

def show_save_changes_dialog(parent_window):
    """Show a prompt to save or discard changes before closing/opening another file."""
    dialog = Gtk.MessageDialog(
        transient_for=parent_window,
        modal=True,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.NONE,
        text=_("unsaved_title"),
        secondary_text=_("unsaved_changes")
    )

    dialog.add_buttons(
        _("btn_cancel"), Gtk.ResponseType.CANCEL,
        _("btn_dont_save"), Gtk.ResponseType.REJECT,
        _("btn_save"), Gtk.ResponseType.ACCEPT
    )
    dialog.set_default_response(Gtk.ResponseType.ACCEPT)

    response = None
    def on_response(d, resp_id):
        nonlocal response
        response = resp_id
        d.destroy()

    dialog.connect("response", on_response)
    dialog.present()

    while response is None:
         context = GLib.MainContext.default()
         context.iteration(True)

    return response


def show_open_file_dialog(parent_window, title, filters=None, default_filter=None, callback=None):
    """
    Show an open file dialog using Gtk.FileDialog if available (GTK >= 4.10),
    otherwise falling back to Gtk.FileChooserDialog (GTK < 4.10).
    Callback receives (gfile) or (gfile, selected_filter).
    """
    if hasattr(Gtk, "FileDialog"):
        dialog = Gtk.FileDialog(title=title)
        if filters:
            store = Gio.ListStore.new(Gtk.FileFilter)
            for f in filters:
                store.append(f)
            dialog.set_filters(store)
        if default_filter:
            dialog.set_default_filter(default_filter)

        def on_open_finish(d, result):
            try:
                gfile = d.open_finish(result)
            except GLib.Error:
                gfile = None
            if callback:
                import inspect
                sig = inspect.signature(callback)
                if len(sig.parameters) >= 2:
                    callback(gfile, None)
                else:
                    callback(gfile)

        dialog.open(parent_window, None, on_open_finish)
    else:
        dialog = Gtk.FileChooserDialog(
            title=title,
            transient_for=parent_window,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            _("btn_cancel"), Gtk.ResponseType.CANCEL,
            _("btn_confirm"), Gtk.ResponseType.ACCEPT,
        )
        if parent_window:
            dialog.set_modal(True)
        if filters:
            for f in filters:
                dialog.add_filter(f)
        if default_filter:
            dialog.set_filter(default_filter)

        def on_response(d, response_id):
            gfile = None
            selected_filter = None
            if response_id == Gtk.ResponseType.ACCEPT:
                gfile = d.get_file()
                selected_filter = d.get_filter()
            d.destroy()
            if callback:
                import inspect
                sig = inspect.signature(callback)
                if len(sig.parameters) >= 2:
                    callback(gfile, selected_filter)
                else:
                    callback(gfile)

        dialog.connect("response", on_response)
        dialog.present()


def show_save_file_dialog(parent_window, title=_("dialog_save_as"), initial_name=None, filters=None, default_filter=None, callback=None, suggested_name=None):
    """
    Show a save file dialog using Gtk.FileDialog if available (GTK >= 4.10),
    otherwise falling back to Gtk.FileChooserDialog (GTK < 4.10).
    Callback receives (gfile) or (gfile, selected_filter).
    """
    if not initial_name and suggested_name:
        initial_name = suggested_name

    if hasattr(Gtk, "FileDialog"):
        dialog = Gtk.FileDialog(title=title)
        if initial_name:
            dialog.set_initial_name(initial_name)
        if filters:
            store = Gio.ListStore.new(Gtk.FileFilter)
            for f in filters:
                store.append(f)
            dialog.set_filters(store)
        if default_filter:
            dialog.set_default_filter(default_filter)

        def on_save_finish(d, result):
            try:
                gfile = d.save_finish(result)
            except GLib.Error:
                gfile = None
            if callback:
                import inspect
                sig = inspect.signature(callback)
                if len(sig.parameters) >= 2:
                    callback(gfile, None)
                else:
                    callback(gfile)

        dialog.save(parent_window, None, on_save_finish)
    else:
        dialog = Gtk.FileChooserDialog(
            title=title,
            transient_for=parent_window,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            _("btn_cancel"), Gtk.ResponseType.CANCEL,
            _("btn_save") if "_" in _("btn_save") else _("btn_confirm"), Gtk.ResponseType.ACCEPT,
        )
        if parent_window:
            dialog.set_modal(True)
        if initial_name:
            dialog.set_current_name(initial_name)
        if filters:
            for f in filters:
                dialog.add_filter(f)
        if default_filter:
            dialog.set_filter(default_filter)

        def on_response(d, response_id):
            gfile = None
            selected_filter = None
            if response_id == Gtk.ResponseType.ACCEPT:
                gfile = d.get_file()
                selected_filter = d.get_filter()
            d.destroy()
            if callback:
                import inspect
                sig = inspect.signature(callback)
                if len(sig.parameters) >= 2:
                    callback(gfile, selected_filter)
                else:
                    callback(gfile)

        dialog.connect("response", on_response)
        dialog.present()


def render_emoji_to_png_bytes(emoji_char, size=96):
    """Render an emoji character into crisp high-resolution PNG bytes using Cairo and Pango."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    layout = PangoCairo.create_layout(cr)
    font_desc = Pango.FontDescription("Noto Color Emoji, Apple Color Emoji, Segoe UI Emoji, sans-serif")
    font_desc.set_absolute_size(int(size * 0.72 * Pango.SCALE))
    layout.set_font_description(font_desc)
    layout.set_text(emoji_char, -1)

    ink_rect, logical_rect = layout.get_pixel_extents()
    x = (size - logical_rect.width) / 2.0
    y = (size - logical_rect.height) / 2.0
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)

    bio = io.BytesIO()
    surface.write_to_png(bio)
    return bio.getvalue()


class SymbolsPopover(Gtk.Popover):
    """Popover palette for inserting special characters, form review symbols, and emojis."""
    SYMBOLS_REVIEW = [
        "✓", "✔", "✕", "✗", "🗹", "☒", "☐", "★", "☆", 
        "➜", "➔", "⬤", "◯", "▲", "▼", "■", "◆", "§",
        "©", "®", "™", "€", "$", "£", "¥", "°", "±",
        "≠", "≈", "≤", "≥", "∞", "‰", "•", "–", "—"
    ]
    
    EMOJIS_COMMON = [
        "👍", "👎", "⚠️", "✅", "❌", "📌", "📝", "💡",
        "🔒", "⭐", "🎯", "🚀", "🔥", "❤️", "ℹ️", "❓",
        "❗", "👏", "🎉", "👀", "✍️", "🔍", "📎", "📅"
    ]

    def __init__(self, editor_window=None, **kwargs):
        super().__init__(**kwargs)
        self.editor_window = editor_window
        self.set_autohide(True)
        self.set_size_request(280, 240)
        self._build_ui()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=8, margin_end=8, margin_top=8, margin_bottom=8)
        
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(stack)
        switcher.set_halign(Gtk.Align.CENTER)
        main_box.append(switcher)

        # Tab 1: Symbols
        symbols_flow = Gtk.FlowBox()
        symbols_flow.set_valign(Gtk.Align.START)
        symbols_flow.set_max_children_per_line(6)
        symbols_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        symbols_flow.set_row_spacing(4)
        symbols_flow.set_column_spacing(4)
        
        for sym in self.SYMBOLS_REVIEW:
            btn = Gtk.Button(label=sym)
            btn.add_css_class("flat")
            btn.set_size_request(36, 36)
            btn.connect("clicked", self._on_symbol_clicked, sym, False)
            symbols_flow.append(btn)
            
        sym_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        sym_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sym_scroll.set_child(symbols_flow)
        stack.add_titled(sym_scroll, "symbols", _("tab_symbols"))

        # Tab 2: Emojis
        emojis_flow = Gtk.FlowBox()
        emojis_flow.set_valign(Gtk.Align.START)
        emojis_flow.set_max_children_per_line(6)
        emojis_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        emojis_flow.set_row_spacing(4)
        emojis_flow.set_column_spacing(4)
        
        for em in self.EMOJIS_COMMON:
            btn = Gtk.Button(label=em)
            btn.add_css_class("flat")
            btn.set_size_request(36, 36)
            btn.connect("clicked", self._on_symbol_clicked, em, True)
            emojis_flow.append(btn)
            
        em_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        em_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        em_scroll.set_child(emojis_flow)
        stack.add_titled(em_scroll, "emojis", _("tab_emojis"))

        main_box.append(stack)
        self.set_child(main_box)

    def _on_symbol_clicked(self, button, symbol, is_emoji):
        self.popdown()
        if self.editor_window and hasattr(self.editor_window, 'insert_symbol_or_emoji'):
            self.editor_window.insert_symbol_or_emoji(symbol, is_emoji=is_emoji)


class CopyPagesToTabDialog(Adw.Window):
    """Modal Libadwaita dialog for copying a single page or multi-page range to an open tab or a new tab."""

    POSITION_KEYS = ("beginning", "before_current", "after_current", "end")
    SCOPE_KEYS = ("single", "range", "all")

    def __init__(self, parent_window, initial_page_index=None, on_confirm=None):
        super().__init__()
        self.parent_window = parent_window
        self.on_confirm = on_confirm
        self._is_updating = False

        doc = getattr(parent_window, "doc", None)
        self.total_pages = max(1, len(doc) if doc is not None else 1)
        raw_page = (
            initial_page_index
            if initial_page_index is not None
            else (getattr(parent_window, "current_page_index", 0) or 0)
        )
        self.initial_page_index = max(0, min(int(raw_page), self.total_pages - 1))

        if parent_window is not None:
            self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(_("copy_pages_dialog_title"))
        self.set_default_size(480, 470)
        self.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        self.cancel_btn = Gtk.Button(label=_("btn_cancel"))
        self.cancel_btn.connect("clicked", lambda b: self.destroy())
        header.pack_start(self.cancel_btn)

        self.copy_btn = Gtk.Button(label=_("copy_pages_btn_copy"))
        self.copy_btn.add_css_class("suggested-action")
        self.copy_btn.connect("clicked", self._on_copy_clicked)
        header.pack_end(self.copy_btn)
        main_box.append(header)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=440)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(16)
        clamp.set_margin_end(16)
        scrolled.set_child(clamp)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(content_box)

        # Group 1: Source Page Range
        group_source = Adw.PreferencesGroup()
        group_source.set_title(_("copy_pages_group_source"))
        group_source.set_description(_("copy_pages_group_source_desc"))
        content_box.append(group_source)

        scope_labels = [
            _("copy_pages_scope_single", self.initial_page_index + 1),
            _("copy_pages_scope_range"),
            _("copy_pages_scope_all", self.total_pages),
        ]
        self.scope_model = Gtk.StringList.new(scope_labels)
        self.scope_row = Adw.ComboRow()
        self.scope_row.set_title(_("copy_pages_scope_title"))
        self.scope_row.set_model(self.scope_model)
        self.scope_row.set_selected(0)
        self.scope_row.connect("notify::selected", self._on_scope_changed)
        group_source.add(self.scope_row)

        self.range_row = Adw.ActionRow()
        self.range_row.set_title(_("copy_pages_range_entry_title", self.total_pages))
        self.range_entry = Gtk.Entry(
            valign=Gtk.Align.CENTER,
            width_chars=16,
            placeholder_text="1-3, 5",
        )
        self.range_entry.set_text(str(self.initial_page_index + 1))
        self.range_entry.connect("changed", self._on_range_entry_changed)
        self.range_entry.connect("activate", lambda e: self._on_copy_clicked())
        self.range_row.add_suffix(self.range_entry)
        self.range_row.set_activatable_widget(self.range_entry)
        group_source.add(self.range_row)

        self.validation_label = Gtk.Label(xalign=0.0)
        self.validation_label.add_css_class("caption")
        self.validation_label.set_margin_start(4)
        content_box.append(self.validation_label)

        # Group 2: Target Tab & Insertion Position
        group_target = Adw.PreferencesGroup()
        group_target.set_title(_("copy_pages_group_target"))
        content_box.append(group_target)

        self.target_specs = []
        other_sessions = (
            parent_window.get_other_open_document_sessions()
            if parent_window is not None and hasattr(parent_window, "get_other_open_document_sessions")
            else []
        )
        for sess in other_sessions:
            title = getattr(sess, "display_title", None) or _("untitled_document")
            self.target_specs.append({"kind": "session", "session": sess, "label": title})

        self.target_specs.append(
            {"kind": "new_tab", "session": None, "label": _("copy_pages_target_new_tab")}
        )

        active_sess = getattr(parent_window, "_active_session", None) if parent_window is not None else None
        if active_sess is not None and getattr(active_sess, "doc", None) is not None:
            curr_title = getattr(active_sess, "display_title", None) or _("untitled_document")
            self.target_specs.append(
                {
                    "kind": "session",
                    "session": active_sess,
                    "label": _("copy_pages_target_current_fmt", curr_title),
                }
            )

        target_labels = [spec["label"] for spec in self.target_specs]
        self.target_model = Gtk.StringList.new(target_labels)
        self.target_row = Adw.ComboRow()
        self.target_row.set_title(_("copy_pages_target_tab_title"))
        self.target_row.set_model(self.target_model)
        self.target_row.set_selected(0)
        self.target_row.connect("notify::selected", self._on_target_changed)
        group_target.add(self.target_row)

        pos_labels = [
            _("copy_pages_pos_beginning"),
            _("copy_pages_pos_before_current"),
            _("copy_pages_pos_after_current"),
            _("copy_pages_pos_end"),
        ]
        self.position_model = Gtk.StringList.new(pos_labels)
        self.position_row = Adw.ComboRow()
        self.position_row.set_title(_("copy_pages_position_title"))
        self.position_row.set_model(self.position_model)
        self.position_row.set_selected(3)
        group_target.add(self.position_row)

        self.switch_tab_row = Adw.ActionRow()
        self.switch_tab_row.set_title(_("copy_pages_switch_tab_title"))
        self.switch_tab_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch_tab_row.add_suffix(self.switch_tab_switch)
        self.switch_tab_row.set_activatable_widget(self.switch_tab_switch)
        group_target.add(self.switch_tab_row)

        self._sync_target_dependent_controls()
        self._validate_current_range()

    def _on_scope_changed(self, row, pspec):
        if self._is_updating:
            return
        idx = int(self.scope_row.get_selected())
        self._is_updating = True
        try:
            if idx == 0:
                self.range_entry.set_text(str(self.initial_page_index + 1))
            elif idx == 2:
                all_str = f"1-{self.total_pages}" if self.total_pages > 1 else "1"
                self.range_entry.set_text(all_str)
        finally:
            self._is_updating = False
        self._validate_current_range()

    def _on_range_entry_changed(self, entry):
        if not self._is_updating:
            txt = (self.range_entry.get_text() or "").strip()
            single_str = str(self.initial_page_index + 1)
            all_str = f"1-{self.total_pages}" if self.total_pages > 1 else "1"
            self._is_updating = True
            try:
                if txt == single_str:
                    self.scope_row.set_selected(0)
                elif txt == all_str and self.total_pages > 1:
                    self.scope_row.set_selected(2)
                else:
                    self.scope_row.set_selected(1)
            finally:
                self._is_updating = False
        self._validate_current_range()

    def _on_target_changed(self, row, pspec):
        self._sync_target_dependent_controls()

    def _sync_target_dependent_controls(self):
        spec = self.get_selected_target_spec()
        is_new_tab = (spec.get("kind") == "new_tab")
        self.position_row.set_sensitive(not is_new_tab)
        if is_new_tab:
            self.switch_tab_switch.set_active(True)
            self.switch_tab_row.set_sensitive(False)
        else:
            active_sess = getattr(self.parent_window, "_active_session", None) if self.parent_window else None
            is_same_tab = (spec.get("session") is not None and spec.get("session") is active_sess)
            self.switch_tab_row.set_sensitive(not is_same_tab)
            if is_same_tab:
                self.switch_tab_switch.set_active(False)

    def get_selected_page_indices(self):
        from . import pdf_handler
        return pdf_handler.parse_page_range_string(self.range_entry.get_text(), self.total_pages)

    def get_selected_target_spec(self) -> dict:
        idx = int(self.target_row.get_selected())
        if 0 <= idx < len(self.target_specs):
            return self.target_specs[idx]
        return {"kind": "new_tab", "session": None, "label": _("copy_pages_target_new_tab")}

    def get_selected_position_key(self) -> str:
        idx = int(self.position_row.get_selected())
        if 0 <= idx < len(self.POSITION_KEYS):
            return self.POSITION_KEYS[idx]
        return "end"

    def select_target_new_tab(self) -> None:
        for i, spec in enumerate(self.target_specs):
            if spec.get("kind") == "new_tab":
                self.target_row.set_selected(i)
                return

    def select_target_session(self, session) -> None:
        for i, spec in enumerate(self.target_specs):
            if spec.get("session") is session:
                self.target_row.set_selected(i)
                return

    def select_position(self, position_key: str) -> None:
        key = str(position_key or "").strip().lower()
        if key in self.POSITION_KEYS:
            self.position_row.set_selected(self.POSITION_KEYS.index(key))

    def _validate_current_range(self) -> bool:
        is_valid, indices, err_msg = self.get_selected_page_indices()
        if is_valid:
            self.validation_label.set_text(_("copy_pages_valid_count", len(indices)))
            self.validation_label.remove_css_class("error")
            self.validation_label.add_css_class("dim-label")
            self.copy_btn.set_sensitive(True)
        else:
            self.validation_label.set_text(err_msg)
            self.validation_label.remove_css_class("dim-label")
            self.validation_label.add_css_class("error")
            self.copy_btn.set_sensitive(False)
        return is_valid

    def _on_copy_clicked(self, button=None) -> bool:
        is_valid, indices, _err = self.get_selected_page_indices()
        if not is_valid or not indices:
            return False

        spec = self.get_selected_target_spec()
        create_new_tab = (spec.get("kind") == "new_tab")
        target_session = spec.get("session")
        pos_key = self.get_selected_position_key()
        switch_to = bool(self.switch_tab_switch.get_active())

        ok = False
        if self.parent_window is not None and hasattr(self.parent_window, "copy_pages_from_session_to_target"):
            ok = bool(
                self.parent_window.copy_pages_from_session_to_target(
                    page_indices=indices,
                    target_session=target_session,
                    create_new_tab=create_new_tab,
                    position=pos_key,
                    switch_to_target=switch_to,
                )
            )
        if callable(self.on_confirm):
            self.on_confirm(indices, spec, pos_key, ok)
        self.destroy()
        return ok


from .new_document_dialog import show_new_document_dialog, NewDocumentDialog