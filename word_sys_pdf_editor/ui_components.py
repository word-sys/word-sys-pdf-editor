import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, GdkPixbuf, Adw, GLib, GObject, Gio
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
        _("btn_cancel") if _("btn_cancel") != "btn_cancel" else "Cancel", Gtk.ResponseType.CANCEL,
        _("btn_confirm") if _("btn_confirm") != "btn_confirm" else "Confirm", Gtk.ResponseType.ACCEPT
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
        _("btn_cancel") if _("btn_cancel") != "btn_cancel" else "İptal", Gtk.ResponseType.CANCEL,
        _("btn_dont_save") if _("btn_dont_save") != "btn_dont_save" else "Kaydetme", Gtk.ResponseType.REJECT,
        _("btn_save") if _("btn_save") != "btn_save" else "Kaydet", Gtk.ResponseType.ACCEPT
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