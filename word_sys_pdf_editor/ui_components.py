import gi
import io
import cairo
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, GdkPixbuf, Adw, GLib, GObject, Gio, Pango, PangoCairo
from .i18n import _


class PageThumbnailFactory(Gtk.SignalListItemFactory):
    """Factory class to create and bind page thumbnail widgets in the sidebar."""
    def __init__(self, editor_window=None):
        """Initialise the factory with setup and bind signal handlers."""
        super().__init__()
        self.editor_window = editor_window
        self.connect("setup", self._on_setup)
        self.connect("bind", self._on_bind)

    def _on_setup(self, factory, list_item):
        """Set up initial layout for the thumbnail list item."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6)
        
        image = Gtk.Picture()
        image.set_size_request(150, -1)
        image.set_can_shrink(False)

        label = Gtk.Label()
        label.set_halign(Gtk.Align.CENTER)
        
        box.append(image)
        box.append(label)
        list_item.set_child(box)

    def _on_bind(self, factory, list_item):
        """Bind a PDF page object and its thumbnail image to the list item."""
        box = list_item.get_child()
        picture = box.get_first_child()
        label = box.get_last_child()
        pdf_page = list_item.get_item()

        if pdf_page and pdf_page.thumbnail:
            texture = Gdk.Texture.new_for_pixbuf(pdf_page.thumbnail)
            picture.set_paintable(texture)
            picture.set_visible(True)
        else:
            picture.set_paintable(None)
            picture.set_visible(False)

        page_index = pdf_page.index
        label.set_text(_("page_info").format(page_index + 1))

        for ctrl in list(box.observe_controllers()):
            if isinstance(ctrl, Gtk.DragSource) or isinstance(ctrl, Gtk.DropTarget):
                box.remove_controller(ctrl)

        drag_source = Gtk.DragSource.new()
        drag_source.set_actions(Gdk.DragAction.MOVE)

        def on_prepare(source, x, y, idx=page_index):
            """Handle the prepare event."""
            val = GObject.Value(GObject.TYPE_INT, idx)
            return Gdk.ContentProvider.new_for_value(val)

        def on_drag_begin(source, drag, idx=page_index, pic=picture):
            """Handle the drag begin event."""
            pdf_pg = list_item.get_item()
            if pdf_pg and pdf_pg.thumbnail:
                tex = Gdk.Texture.new_for_pixbuf(pdf_pg.thumbnail)
                Gtk.DragSource.set_icon(source, tex, 0, 0)

        drag_source.connect("prepare", on_prepare)
        drag_source.connect("drag-begin", on_drag_begin)
        box.add_controller(drag_source)

        drop_target = Gtk.DropTarget.new(GObject.TYPE_INT, Gdk.DragAction.MOVE)

        def on_drop(target, value, x, y, to_idx=page_index):
            """Handle the drop event."""
            from_idx = value
            if from_idx == to_idx:
                return False
            if self.editor_window:
                self.editor_window.on_page_reorder(from_idx, to_idx)
            return True

        drop_target.connect("drop", on_drop)
        box.add_controller(drop_target)


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

def show_confirm_dialog(parent_window, message, title="Confirm", destructive=True):
    """Show a confirmation dialog with Accept and Cancel options."""
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

    dialog.add_buttons(
        _("btn_cancel"), Gtk.ResponseType.CANCEL,
        _("btn_confirm"), Gtk.ResponseType.ACCEPT
    )
    dialog.set_default_size(450, -1)
    dialog.set_default_response(Gtk.ResponseType.CANCEL)

    response = None
    def on_response(d, resp_id):
        """Handle the dialog response event."""
        nonlocal response
        response = resp_id
        d.destroy()

    dialog.connect("response", on_response)
    dialog.present()

    while response is None:
         context = GLib.MainContext.default()
         context.iteration(True)

    dialog.destroy()
    return response == Gtk.ResponseType.ACCEPT

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
        """Handle the dialog response event."""
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


def show_save_file_dialog(parent_window, title, initial_name=None, filters=None, default_filter=None, callback=None):
    """
    Show a save file dialog using Gtk.FileDialog if available (GTK >= 4.10),
    otherwise falling back to Gtk.FileChooserDialog (GTK < 4.10).
    Callback receives (gfile) or (gfile, selected_filter).
    """
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