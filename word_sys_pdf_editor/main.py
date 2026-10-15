import os
import sys
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GLib, Adw

from .window import PdfEditorWindow

class PdfEditorApplication(Adw.Application):
    """The main GTK4/libadwaita application class for the PDF Editor."""
    def __init__(self, **kwargs):
        """Initialise application and basic menu actions."""
        app_id = kwargs.pop('application_id', os.environ.get('FLATPAK_ID', 'org.word_sys.pdfeditor'))
        flags = kwargs.pop('flags', Gio.ApplicationFlags.HANDLES_OPEN)
        super().__init__(application_id=app_id, flags=flags, **kwargs)
        self.window = None

        quit_action = Gio.SimpleAction.new('quit', None)
        quit_action.connect('activate', self.on_quit)
        self.add_action(quit_action)
        self.set_accels_for_action('app.quit', ['<Control>q'])

    def do_activate(self):
        """Activate the main application window."""
        if not self.window:
            self.window = PdfEditorWindow(application=self)
        self.window.present()

    def do_open(self, files, n_files, hint):
        """Handle opening PDF files passed via CLI or file manager."""
        if not self.window:
             self.activate()

        if n_files > 0:
            filepath = files[0].get_path()
            if filepath:
                GLib.idle_add(self.window.load_document, filepath)

        self.window.present()


    def on_quit(self, action, param):
        """Safely quit the application and prompt for unsaved changes."""
        if self.window:
             if self.window.check_unsaved_changes():
                  return
             self.window.close_document()

        print("Quitting application.")
        self.quit()

def _suppress_glib_noise():
    """Suppress harmless known upstream GLib/GIO file chooser warnings."""
    def _legacy_handler(log_domain, log_level, message, user_data=None):
        if message and ("is-backup" in message or "g_file_info_get_is_backup" in message):
            return
        GLib.log_default_handler(log_domain, log_level, message, user_data)

    for domain in ["GLib-GIO", "Gtk", "GLib"]:
        try:
            GLib.log_set_handler(
                domain,
                GLib.LogLevelFlags.LEVEL_CRITICAL | GLib.LogLevelFlags.LEVEL_WARNING,
                _legacy_handler,
                None
            )
        except Exception:
            pass

    def _writer_func(*args):
        try:
            if len(args) >= 2 and isinstance(args[1], (list, tuple)):
                for f in args[1]:
                    val = str(getattr(f, "value", ""))
                    if "is-backup" in val or "g_file_info_get_is_backup" in val:
                        return GLib.LogWriterOutput.HANDLED
        except Exception:
            pass
        return GLib.log_writer_default(*args)

    try:
        GLib.log_set_writer_func(_writer_func)
    except Exception:
        pass


def main():
    """Run the Adw application."""
    import os, locale
    from .i18n import get_language
    lang = get_language()
    if lang == "tr":
        os.environ["LANGUAGE"] = "tr_TR:tr"
        os.environ["LC_MESSAGES"] = "tr_TR.UTF-8"
        try:
            locale.setlocale(locale.LC_MESSAGES, "tr_TR.UTF-8")
        except Exception:
            try:
                locale.setlocale(locale.LC_MESSAGES, "tr")
            except Exception:
                pass

    from pathlib import Path
    app_id = os.environ.get('FLATPAK_ID', 'word-sys-pdf-editor')
    GLib.set_prgname(app_id)
    GLib.set_application_name("word-sys's PDF Editor")
    _suppress_glib_noise()
    Adw.init()

    try:
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        if display:
            theme = Gtk.IconTheme.get_for_display(display)
            icons_dir = Path(__file__).resolve().parent / "icons"
            if icons_dir.exists():
                theme.add_search_path(str(icons_dir))
    except Exception as e:
        print(f"Warning registering icon theme search path: {e}")

    Gtk.Window.set_default_icon_name("f-pv1")
    app = PdfEditorApplication()
    return app.run(sys.argv)