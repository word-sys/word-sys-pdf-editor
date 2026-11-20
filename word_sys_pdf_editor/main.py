import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import unquote, urlparse

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GLib, Adw

from .constants import APP_VERSION
from .synctex_engine import parse_synctex_forward_arg
from .window import PdfEditorWindow


CLI_HELP_TEXT = (
    "Usage: word-sys-pdf-editor [OPTIONS] [PDF_FILE...]\n"
    "\n"
    "Options:\n"
    "  --synctex-forward LINE:COL:TEX_PATH  Jump to SyncTeX location in PDF_FILE\n"
    "  -p, --page PAGE_NUM                  Open PDF_FILE at 1-based page PAGE_NUM\n"
    "  --version                            Print version and exit\n"
    "  -h, --help                           Show this help message and exit\n"
)


def _resolve_cli_path(raw_path: str, cwd: Optional[str] = None) -> str:
    """Resolve a CLI file path or `file://` URI relative to `cwd`."""
    text = str(raw_path or "").strip()
    if not text:
        return ""
    if text.startswith("file://"):
        text = unquote(urlparse(text).path)
    if cwd and not os.path.isabs(text):
        text = os.path.join(cwd, text)
    return os.path.normpath(text)


def parse_cli_arguments(
    argv: Sequence[str],
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse CLI arguments for single-instance activation and SyncTeX forward search.

    Accepts `argv` WITHOUT the executable name (i.e. `sys.argv[1:]`).
    Returns a dictionary containing:
      - `files`: list of resolved PDF file paths
      - `page_index`: optional 0-based page index (from 1-based `-p` / `--page`)
      - `synctex_forward`: optional `(line, column, tex_path)` tuple
      - `show_help`: bool
      - `show_version`: bool
    """
    parser = argparse.ArgumentParser(prog="word-sys-pdf-editor", add_help=False)
    parser.add_argument("-h", "--help", action="store_true", dest="show_help")
    parser.add_argument("--version", action="store_true", dest="show_version")
    parser.add_argument("--synctex-forward", dest="synctex_forward", default=None)
    parser.add_argument("-p", "--page", dest="page", default=None)
    parser.add_argument("files", nargs="*")

    ns, _unknown = parser.parse_known_args(list(argv))

    resolved_files: List[str] = []
    for f in ns.files or []:
        p = _resolve_cli_path(f, cwd=cwd)
        if p:
            resolved_files.append(p)

    page_index: Optional[int] = None
    if ns.page is not None:
        try:
            page_num = int(str(ns.page).strip())
            page_index = max(0, page_num - 1)
        except ValueError:
            page_index = None

    synctex_tuple = None
    if ns.synctex_forward:
        parsed_st = parse_synctex_forward_arg(ns.synctex_forward)
        if parsed_st is not None:
            st_line, st_col, st_tex = parsed_st
            if st_tex.startswith("file://"):
                st_tex = unquote(urlparse(st_tex).path)
            elif cwd and not os.path.isabs(st_tex):
                cand = os.path.normpath(os.path.join(cwd, st_tex))
                if os.path.exists(cand):
                    st_tex = cand
            synctex_tuple = (st_line, st_col, st_tex)

    return {
        "files": resolved_files,
        "page_index": page_index,
        "synctex_forward": synctex_tuple,
        "show_help": bool(ns.show_help),
        "show_version": bool(ns.show_version),
    }


class PdfEditorApplication(Adw.Application):
    """The main GTK4/libadwaita application class for the PDF Editor."""
    def __init__(self, **kwargs):
        """Initialise application and basic menu actions."""
        app_id = kwargs.pop('application_id', os.environ.get('FLATPAK_ID', 'org.word_sys.pdfeditor'))
        flags = kwargs.pop(
            'flags',
            Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
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
        """Handle opening PDF files passed via desktop file manager or D-Bus Open."""
        if not self.window:
            self.do_activate()

        for idx in range(min(n_files, len(files))):
            filepath = files[idx].get_path()
            if filepath:
                def _open_oneshot(p=filepath):
                    self.window.open_or_focus_document(p, None)
                    return False
                GLib.idle_add(_open_oneshot)

        self.window.present()

    def do_command_line(self, command_line):
        """Handle CLI invocations on both primary and D-Bus forwarded secondary instances."""
        try:
            raw_args = list(command_line.get_arguments())
        except Exception:
            raw_args = []
        try:
            cwd = command_line.get_cwd() or os.getcwd()
        except Exception:
            cwd = os.getcwd()

        parsed = parse_cli_arguments(raw_args[1:] if len(raw_args) > 1 else [], cwd=cwd)

        if parsed["show_help"]:
            try:
                command_line.print_literal(CLI_HELP_TEXT)
            except Exception:
                sys.stdout.write(CLI_HELP_TEXT)
            return 0

        if parsed["show_version"]:
            ver_line = f"word-sys-pdf-editor {APP_VERSION}\n"
            try:
                command_line.print_literal(ver_line)
            except Exception:
                sys.stdout.write(ver_line)
            return 0

        self.do_activate()
        self._dispatch_cli_request(parsed)
        return 0

    def _dispatch_cli_request(self, parsed: Dict[str, Any], immediate: bool = False) -> bool:
        """Dispatch a parsed CLI request to the main `PdfEditorWindow`."""
        if not self.window:
            return False

        def _invoke(fn, *args):
            if immediate:
                fn(*args)
            else:
                def _oneshot():
                    fn(*args)
                    return False
                GLib.idle_add(_oneshot)

        files = parsed.get("files") or []
        synctex_forward = parsed.get("synctex_forward")
        page_index = parsed.get("page_index")

        if synctex_forward is not None:
            st_line, st_col, st_tex = synctex_forward
            primary_pdf = files[0] if files else None
            _invoke(self.window.handle_synctex_forward_search, primary_pdf, st_tex, st_line, st_col)
            for extra_pdf in files[1:]:
                _invoke(self.window.open_or_focus_document, extra_pdf, None)
            return True

        if files:
            _invoke(self.window.open_or_focus_document, files[0], page_index)
            for extra_pdf in files[1:]:
                _invoke(self.window.open_or_focus_document, extra_pdf, None)
            return True

        if page_index is not None:
            def _jump_active(p_idx):
                if self.window and self.window.doc is not None:
                    total = len(self.window.doc)
                    if total > 0:
                        clamped = max(0, min(int(p_idx), total - 1))
                        if getattr(self.window, 'continuous_scroll', False):
                            self.window.scroll_to_page(clamped, smooth=True)
                        else:
                            self.window._load_page(clamped)
                return False
            _invoke(_jump_active, page_index)
            return True

        return False


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