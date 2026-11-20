"""Unit tests for the pure-Python SyncTeX parser, coordinate mapper, and CLI fallback."""

import gzip
import os
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from word_sys_pdf_editor.synctex_engine import (
    SYNCTEX_SP_PER_BP,
    SyncTeXDocument,
    SyncTeXHighlight,
    SyncTeXLocation,
    find_synctex_file,
    format_editor_command,
    parse_synctex_forward_arg,
)


def _sp(bp: float) -> int:
    """Helper to convert PDF points (bp) into SyncTeX scaled points (sp)."""
    return int(round(bp * SYNCTEX_SP_PER_BP))


def _build_sample_synctex(project_dir: str) -> str:
    """Build a realistic two-page SyncTeX Version 1 payload with multiple inputs and record types."""
    main_tex = os.path.join(project_dir, "main.tex")
    # Page 1: outer vbox (line 1) containing two hbox lines (lines 10 and 14) + a leaf-only math line (line 18)
    # Page 2: dynamic Input:2 for ./chapters/intro.tex with void_hbox (line 25) and columned hboxes (line 30)
    lines = [
        "SyncTeX Version:1",
        f"Input:1:{main_tex}",
        "Output:main.pdf",
        "Magnification:1000",
        "Unit:1",
        "X Offset:0",
        "Y Offset:0",
        "Content:",
        "!128",
        "{1",
        f"[1,1:{_sp(72)},{_sp(720)}:{_sp(450)},{_sp(648)},{_sp(0)}",
        f"(1,10:{_sp(72)},{_sp(120)}:{_sp(300)},{_sp(10)},{_sp(2)}",
        f"x1,10:{_sp(72)},{_sp(120)}",
        f"k1,10:{_sp(120)},{_sp(120)}:{_sp(12)}",
        f"g1,10:{_sp(150)},{_sp(120)}",
        ")",
        f"(1,14:{_sp(72)},{_sp(140)}:{_sp(320)},{_sp(10)},{_sp(2)}",
        f"h1,14:{_sp(72)},{_sp(140)}:{_sp(150)},{_sp(10)},{_sp(2)}",
        f"h1,14:{_sp(225)},{_sp(140)}:{_sp(167)},{_sp(10)},{_sp(2)}",
        ")",
        f"(1,17:{_sp(72)},{_sp(170)}:{_sp(200)},{_sp(11)},{_sp(3)}",
        f"$1,18:{_sp(100)},{_sp(170)}",
        f"k1,18:{_sp(140)},{_sp(170)}:{_sp(10)}",
        ")",
        f"v1,20:{_sp(72)},{_sp(220)}:{_sp(180)},{_sp(20)},{_sp(0)}",
        "]",
        "}1",
        "Input:2:./chapters/intro.tex",
        "{2",
        f"[2,1:{_sp(72)},{_sp(700)}:{_sp(450)},{_sp(620)},{_sp(0)}",
        f"h2,25:{_sp(72)},{_sp(100)}:{_sp(280)},{_sp(12)},{_sp(3)}",
        f"(2,30,4:{_sp(72)},{_sp(130)}:{_sp(80)},{_sp(10)},{_sp(2)}",
        ")",
        f"(2,30,22:{_sp(180)},{_sp(130)}:{_sp(95)},{_sp(10)},{_sp(2)}",
        ")",
        "]",
        "}2",
        "Postamble:",
        "Count:18",
        "Post scriptum:",
    ]
    return "\n".join(lines) + "\n"


class TestSyncTeXFileDiscoveryAndLoading:
    """Verify discovery, plain/gzip loading, corrupt file safety, and mtime reloading."""

    def test_find_synctex_file_prefers_gz_and_supports_plain_and_uri(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        assert find_synctex_file(str(pdf)) is None

        plain = tmp_path / "paper.synctex"
        plain.write_text("SyncTeX Version:1\n", encoding="utf-8")
        assert find_synctex_file(str(pdf)) == str(plain)

        gz = tmp_path / "paper.synctex.gz"
        with gzip.open(gz, "wb") as f:
            f.write(b"SyncTeX Version:1\n")
        # Prefers .synctex.gz when both exist
        assert find_synctex_file(str(pdf)) == str(gz)
        assert find_synctex_file(f"file://{pdf}") == str(gz)

    def test_load_plain_and_gzip_synctex_documents(self, tmp_path):
        pdf = tmp_path / "main.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        payload = _build_sample_synctex(str(tmp_path))

        # 1. Plain .synctex
        plain = tmp_path / "main.synctex"
        plain.write_text(payload, encoding="utf-8")
        doc_plain = SyncTeXDocument.from_pdf(str(pdf), use_cli_fallback=False)
        assert doc_plain is not None
        assert doc_plain.is_loaded is True
        assert doc_plain.page_count == 2
        assert 1 in doc_plain.input_files
        assert 2 in doc_plain.input_files
        assert doc_plain.input_files[2] == os.path.normpath(str(tmp_path / "chapters" / "intro.tex"))

        # 2. Gzip .synctex.gz
        plain.unlink()
        gz = tmp_path / "main.synctex.gz"
        with gzip.open(gz, "wb") as f:
            f.write(payload.encode("utf-8"))
        doc_gz = SyncTeXDocument.from_pdf(str(pdf), use_cli_fallback=False)
        assert doc_gz is not None
        assert doc_gz.is_loaded is True
        assert doc_gz.page_count == 2

    def test_corrupt_gzip_returns_none_gracefully(self, tmp_path):
        pdf = tmp_path / "broken.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        gz = tmp_path / "broken.synctex.gz"
        gz.write_bytes(b"\x1f\x8bnot-actually-valid-gzip-stream")

        doc = SyncTeXDocument.from_pdf(str(pdf), use_cli_fallback=False)
        assert doc is None

    def test_reload_if_changed_picks_up_updated_synctex(self, tmp_path):
        pdf = tmp_path / "live.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        st = tmp_path / "live.synctex"
        main_tex = str(tmp_path / "main.tex")

        v1 = (
            f"SyncTeX Version:1\nInput:1:{main_tex}\nOutput:live.pdf\n"
            f"Magnification:1000\nUnit:1\nX Offset:0\nY Offset:0\nContent:\n"
            f"{{1\n(1,5:{_sp(72)},{_sp(100)}:{_sp(100)},{_sp(10)},{_sp(2)}\n)\n}}1\nPostamble:\n"
        )
        st.write_text(v1, encoding="utf-8")
        doc = SyncTeXDocument.from_pdf(str(pdf), use_cli_fallback=False)
        assert doc is not None
        assert doc.reload_if_changed() is False
        assert len(doc.forward_search(main_tex, 5)) == 1
        assert doc.forward_search(main_tex, 5)[0].line == 5

        # Write updated version with future mtime
        v2 = (
            f"SyncTeX Version:1\nInput:1:{main_tex}\nOutput:live.pdf\n"
            f"Magnification:1000\nUnit:1\nX Offset:0\nY Offset:0\nContent:\n"
            f"{{1\n(1,42:{_sp(90)},{_sp(200)}:{_sp(150)},{_sp(12)},{_sp(2)}\n)\n}}1\nPostamble:\n"
        )
        st.write_text(v2, encoding="utf-8")
        future = time.time() + 5.0
        os.utime(st, (future, future))

        assert doc.reload_if_changed() is True
        res = doc.forward_search(main_tex, 42)
        assert len(res) == 1
        assert res[0].line == 42
        assert abs(res[0].x0 - 90.0) < 0.5


class TestSyncTeXCoordinateMappingAndSearch:
    """Verify coordinate scaling, forward search, and backward search accuracy."""

    def test_custom_magnification_unit_offsets_and_equals_shorthand(self):
        # Magnification 2000 + Unit 1 => scale is 2x normal
        # X Offset = _sp(10) -> shifted by 20bp when magnified 2x
        text = (
            "SyncTeX Version:1\n"
            "Input:1:/proj/doc.tex\n"
            "Output:doc.pdf\n"
            "Magnification:2000\n"
            "Unit:1\n"
            f"X Offset:{_sp(10)}\n"
            f"Y Offset:{_sp(5)}\n"
            "Content:\n"
            "{1\n"
            f"(1,8:{_sp(40)},{_sp(50)}:{_sp(100)},{_sp(6)},{_sp(2)}\n"
            f"h1,9:=,=:{_sp(50)},{_sp(6)},{_sp(2)}\n"
            ")\n"
            "}1\n"
            "Postamble:\n"
        )
        doc = SyncTeXDocument.from_string(text, base_dir="/proj")
        res8 = doc.forward_search("/proj/doc.tex", 8)
        assert len(res8) == 1
        h8 = res8[0]
        # (40 + 10) * 2 = 100, width = 100 * 2 = 200 -> x1 = 300
        # (50 + 5) * 2 = 110, H = 6 * 2 = 12, D = 2 * 2 = 4 -> y0 = 98, y1 = 114
        assert abs(h8.x0 - 100.0) < 0.2
        assert abs(h8.x1 - 300.0) < 0.2
        assert abs(h8.y0 - 98.0) < 0.2
        assert abs(h8.y1 - 114.0) < 0.2

        # `=` shorthand on line 9 reused last h and v -> x0 = 100, y0 = 98
        res9 = doc.forward_search("/proj/doc.tex", 9)
        assert len(res9) == 1
        assert abs(res9[0].x0 - 100.0) < 0.2
        assert abs(res9[0].x1 - 200.0) < 0.2

    def test_forward_search_exact_merged_nearest_and_path_variants(self, tmp_path):
        payload = _build_sample_synctex(str(tmp_path))
        doc = SyncTeXDocument.from_string(payload, base_dir=str(tmp_path))
        main_tex = str(tmp_path / "main.tex")

        # Exact hbox match on page 0, line 10
        res10 = doc.forward_search(main_tex, 10)
        assert len(res10) == 1
        h = res10[0]
        assert h.page_index == 0
        assert abs(h.x0 - 72.0) < 0.2
        assert abs(h.x1 - 372.0) < 0.2
        assert abs(h.y0 - 110.0) < 0.2
        assert abs(h.y1 - 122.0) < 0.2

        # Line 14 has parent hbox + two adjacent void_hboxes merged cleanly into one band
        res14 = doc.forward_search("main.tex", 14)
        assert len(res14) == 1
        assert abs(res14[0].x0 - 72.0) < 0.2
        assert abs(res14[0].x1 - 392.0) < 0.2

        # Line 13 (blank/comment) snaps to nearest line 14
        res13 = doc.forward_search(main_tex, 13)
        assert len(res13) == 1
        assert res13[0].line == 14

        # Line 18 (leaf-only math + kern inside enclosing hbox at y0=159, y1=173)
        res18 = doc.forward_search(main_tex, 18)
        assert len(res18) == 1
        assert res18[0].page_index == 0
        assert abs(res18[0].x0 - 100.0) < 0.5
        assert abs(res18[0].x1 - 140.0) < 0.5
        assert abs(res18[0].y0 - 159.0) < 0.5
        assert abs(res18[0].y1 - 173.0) < 0.5

        # Line 25 in dynamic Input:2 (./chapters/intro.tex) on page index 1
        for query in (
            str(tmp_path / "chapters" / "intro.tex"),
            "chapters/intro.tex",
            "intro.tex",
            "intro",
        ):
            res25 = doc.forward_search(query, 25)
            assert len(res25) == 1
            assert res25[0].page_index == 1
            assert abs(res25[0].x0 - 72.0) < 0.2
            assert abs(res25[0].y0 - 88.0) < 0.2

        # Column disambiguation on line 30 (col 4 vs col 22)
        res30_left = doc.forward_search("chapters/intro.tex", 30, column=5)
        res30_right = doc.forward_search("chapters/intro.tex", 30, column=20)
        assert len(res30_left) == 1 and abs(res30_left[0].x0 - 72.0) < 0.2
        assert len(res30_right) == 1 and abs(res30_right[0].x0 - 180.0) < 0.2

    def test_backward_search_containment_margin_snap_and_multifile(self, tmp_path):
        payload = _build_sample_synctex(str(tmp_path))
        doc = SyncTeXDocument.from_string(payload, base_dir=str(tmp_path))
        main_tex = os.path.normpath(str(tmp_path / "main.tex"))
        intro_tex = os.path.normpath(str(tmp_path / "chapters" / "intro.tex"))

        # Click inside line 10 hbox (overlaps outer page vbox line 1 -> must pick tight line 10!)
        loc10 = doc.backward_search(0, 115.0, 115.0)
        assert loc10 is not None
        assert loc10.tex_path == main_tex
        assert loc10.line == 10

        # Click inside math/kern line 18 (nested inside hbox line 17 -> must pick innermost line 18!)
        loc18 = doc.backward_search(0, 135.0, 166.0)
        assert loc18 is not None
        assert loc18.tex_path == main_tex
        assert loc18.line == 18

        # Click in left margin horizontally aligned with line 14 (x=30, y=135) -> snaps to line 14, not line 10 or 17
        loc_margin = doc.backward_search(0, 30.0, 135.0)
        assert loc_margin is not None
        assert loc_margin.line == 14

        # Click on page 2 inside second columned hbox (line 30, col 22)
        loc_p2 = doc.backward_search(1, 210.0, 125.0)
        assert loc_p2 is not None
        assert loc_p2.tex_path == intro_tex
        assert loc_p2.line == 30
        assert loc_p2.column == 22

        # Out-of-range page returns None
        assert doc.backward_search(9, 100.0, 100.0) is None


class TestSyncTeXCliFallbackAndHelpers:
    """Verify system `synctex` CLI parsing/fallback and CLI argument/editor template helpers."""

    def test_cli_view_and_edit_fallback_parsing(self):
        view_stdout = (
            "This is SyncTeX command line utility, version 1.5\n"
            "SyncTeX result begin\n"
            "Output:paper.pdf\n"
            "Page:2\n"
            "x:100.0\n"
            "y:200.0\n"
            "h:100.0\n"
            "v:200.0\n"
            "W:240.0\n"
            "H:11.0\n"
            "before:\n"
            "SyncTeX result end\n"
        )
        edit_stdout = (
            "This is SyncTeX command line utility, version 1.5\n"
            "SyncTeX result begin\n"
            "Output:paper.pdf\n"
            "Input:/work/thesis/./sec1.tex\n"
            "Line:88\n"
            "Column:-1\n"
            "Offset:0\n"
            "SyncTeX result end\n"
        )

        doc = SyncTeXDocument(pdf_path="/work/thesis/paper.pdf", auto_load=False, use_cli_fallback=True)
        with patch("word_sys_pdf_editor.synctex_engine.is_synctex_cli_available", return_value=True):
            mock_view = MagicMock(returncode=0, stdout=view_stdout)
            with patch("subprocess.run", return_value=mock_view) as run_mock:
                hl = doc.forward_search("/work/thesis/sec1.tex", 88, 3)
                assert run_mock.called
                assert len(hl) == 1
                assert hl[0].page_index == 1
                assert abs(hl[0].x0 - 100.0) < 0.1
                assert abs(hl[0].x1 - 340.0) < 0.1
                assert abs(hl[0].y0 - 189.0) < 0.1
                assert abs(hl[0].y1 - 200.0) < 0.1

            mock_edit = MagicMock(returncode=0, stdout=edit_stdout)
            with patch("subprocess.run", return_value=mock_edit) as run_mock:
                loc = doc.backward_search(1, 150.0, 195.0)
                assert run_mock.called
                assert loc is not None
                assert loc.tex_path == "/work/thesis/sec1.tex"
                assert loc.line == 88
                assert loc.column == 0  # -1 clamped to 0

            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="synctex", timeout=3.0)):
                assert doc.forward_search("/work/thesis/sec1.tex", 88) == []
                assert doc.backward_search(1, 150.0, 195.0) is None

    def test_parse_synctex_forward_arg_and_format_editor_command(self):
        assert parse_synctex_forward_arg("42:7:/home/user/paper.tex") == (42, 7, "/home/user/paper.tex")
        assert parse_synctex_forward_arg("42:/home/user/paper.tex") == (42, 0, "/home/user/paper.tex")
        assert parse_synctex_forward_arg("12:0:/tmp/my thesis/ch 1.tex") == (12, 0, "/tmp/my thesis/ch 1.tex")
        assert parse_synctex_forward_arg("invalid") is None
        assert parse_synctex_forward_arg("") is None

        # Spaces & metacharacters stay inside single argv element (no shell injection)
        argv_vscode = format_editor_command("code --goto %f:%l:%c", "/tmp/my paper; rm -rf.tex", 55, 4)
        assert argv_vscode == ["code", "--goto", "/tmp/my paper; rm -rf.tex:55:4"]

        argv_texstudio = format_editor_command("texstudio --line %l %f", "/tmp/my thesis/main.tex", 10, 0)
        assert argv_texstudio == ["texstudio", "--line", "10", "/tmp/my thesis/main.tex"]

        argv_emacs = format_editor_command("emacsclient -n +%l:%c %f", "/tmp/doc.tex", 23, 8)
        assert argv_emacs == ["emacsclient", "-n", "+23:8", "/tmp/doc.tex"]

        assert format_editor_command("", "/tmp/doc.tex", 1, 0) == []


class TestSyncTeXCliAndSingleInstanceForwardSearch:
    """Verify CLI argument parsing, single-instance command-line IPC, tab focus, and canvas highlight pulse."""

    def test_parse_cli_arguments_synctex_page_and_cwd_resolution(self, tmp_path):
        from word_sys_pdf_editor.main import parse_cli_arguments

        tex_file = tmp_path / "main.tex"
        tex_file.write_text("\\documentclass{article}\n", encoding="utf-8")

        parsed = parse_cli_arguments(
            ["--synctex-forward", "42:5:main.tex", "paper.pdf"],
            cwd=str(tmp_path),
        )
        assert parsed["synctex_forward"] == (42, 5, str(tex_file))
        assert parsed["files"] == [str(tmp_path / "paper.pdf")]
        assert parsed["page_index"] is None
        assert parsed["show_help"] is False
        assert parsed["show_version"] is False

        parsed_eq = parse_cli_arguments(
            ["--synctex-forward=14:chapters/intro.tex", f"file://{tmp_path}/doc.pdf", "--unknown-gtk-flag"],
            cwd=str(tmp_path),
        )
        assert parsed_eq["synctex_forward"] == (14, 0, "chapters/intro.tex")
        assert parsed_eq["files"] == [str(tmp_path / "doc.pdf")]

        parsed_page = parse_cli_arguments(["-p", "3", "paper.pdf"], cwd=str(tmp_path))
        assert parsed_page["page_index"] == 2
        assert parsed_page["files"] == [str(tmp_path / "paper.pdf")]

        parsed_page1 = parse_cli_arguments(["--page", "1", "paper.pdf"], cwd=str(tmp_path))
        assert parsed_page1["page_index"] == 0

        assert parse_cli_arguments(["--help"])["show_help"] is True
        assert parse_cli_arguments(["--version"])["show_version"] is True

    def test_application_handles_command_line_flag_and_dispatch(self, tmp_path):
        from gi.repository import Gio
        from word_sys_pdf_editor.main import PdfEditorApplication

        app = PdfEditorApplication(
            application_id="org.word_sys.test_synctex_cli_dispatch",
        )
        flags = app.get_flags()
        assert bool(flags & Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        assert bool(flags & Gio.ApplicationFlags.HANDLES_OPEN)

        # --version and --help return 0 without creating a window
        cmd_ver = MagicMock()
        cmd_ver.get_arguments.return_value = ["word-sys-pdf-editor", "--version"]
        cmd_ver.get_cwd.return_value = str(tmp_path)
        assert app.do_command_line(cmd_ver) == 0
        assert cmd_ver.print_literal.called
        assert app.window is None

        cmd_help = MagicMock()
        cmd_help.get_arguments.return_value = ["word-sys-pdf-editor", "--help"]
        cmd_help.get_cwd.return_value = str(tmp_path)
        assert app.do_command_line(cmd_help) == 0
        assert cmd_help.print_literal.called
        assert app.window is None

        # Secondary-instance --synctex-forward reuses existing window and dispatches forward search
        mock_win = MagicMock()
        app.window = mock_win
        parsed_fwd = {
            "files": [str(tmp_path / "paper.pdf")],
            "page_index": None,
            "synctex_forward": (25, 3, str(tmp_path / "chapters" / "intro.tex")),
            "show_help": False,
            "show_version": False,
        }
        assert app._dispatch_cli_request(parsed_fwd, immediate=True) is True
        mock_win.handle_synctex_forward_search.assert_called_once_with(
            str(tmp_path / "paper.pdf"),
            str(tmp_path / "chapters" / "intro.tex"),
            25,
            3,
        )

        # Secondary-instance -p 2 dispatches open_or_focus_document with 0-based page_index=1
        mock_win.reset_mock()
        parsed_pg = {
            "files": [str(tmp_path / "paper.pdf")],
            "page_index": 1,
            "synctex_forward": None,
            "show_help": False,
            "show_version": False,
        }
        assert app._dispatch_cli_request(parsed_pg, immediate=True) is True
        mock_win.open_or_focus_document.assert_called_once_with(str(tmp_path / "paper.pdf"), 1)

    def test_glib_application_run_accepts_synctex_and_version_args(self):
        from gi.repository import Gio
        from word_sys_pdf_editor.main import PdfEditorApplication

        app = PdfEditorApplication(
            application_id="org.word_sys.test_glib_cli_nonunique",
            flags=(
                Gio.ApplicationFlags.NON_UNIQUE
                | Gio.ApplicationFlags.HANDLES_OPEN
                | Gio.ApplicationFlags.HANDLES_COMMAND_LINE
            ),
        )
        # Verifies GApplication does not reject --version / --synctex-forward prior to do_command_line
        exit_code = app.run(["word-sys-pdf-editor", "--version"])
        assert exit_code == 0

    def test_window_forward_search_focuses_tab_scrolls_renders_and_pulses(self, tmp_path):
        import cairo
        import fitz
        from gi.repository import Adw
        from word_sys_pdf_editor.window import PdfEditorWindow

        # Create two PDFs + a matching .synctex.gz for main.pdf
        main_pdf_path = tmp_path / "main.pdf"
        d_main = fitz.open()
        d_main.new_page(width=595, height=842)
        d_main.new_page(width=595, height=842)
        d_main.save(str(main_pdf_path))
        d_main.close()

        other_pdf_path = tmp_path / "other.pdf"
        d_other = fitz.open()
        d_other.new_page(width=595, height=842)
        d_other.save(str(other_pdf_path))
        d_other.close()

        gz_path = tmp_path / "main.synctex.gz"
        with gzip.open(gz_path, "wb") as gz:
            gz.write(_build_sample_synctex(str(tmp_path)).encode("utf-8"))

        with patch("word_sys_pdf_editor.i18n._save_settings"):
            try:
                app = Adw.Application(application_id="org.word_sys.test_synctex_win_pulse")
            except Exception:
                app = None
            win = PdfEditorWindow(application=app)
            try:
                win.font_scan_in_progress = False
                doc_main = fitz.open(str(main_pdf_path))
                doc_other = fitz.open(str(other_pdf_path))

                sess_main = win.create_session(doc=doc_main, filepath=str(main_pdf_path))
                win.add_session(sess_main, switch_to=True)
                sess_other = win.create_session(doc=doc_other, filepath=str(other_pdf_path))
                win.add_session(sess_other, switch_to=True)
                assert win._active_session is sess_other

                # Forward search targeting main.pdf (currently background tab) line 25 in intro.tex (page 2)
                ok = win.handle_synctex_forward_search(str(main_pdf_path), "chapters/intro.tex", 25, 0)
                assert ok is True
                assert win._active_session is sess_main
                assert win.current_page_index == 1
                assert len(win.synctex_highlight_boxes) == 1
                assert win.synctex_highlight_boxes[0]["page_index"] == 1
                assert win._synctex_pulse_alpha > 0.0

                # Render SyncTeX highlight pulse onto a Cairo surface and confirm pixels were painted
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, 850)
                cr = cairo.Context(surf)
                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.paint()
                win._draw_synctex_highlights(cr, page_index=1, page_offset_x=0.0, page_offset_y=0.0)
                surf.flush()
                # Check pixel inside highlighted band (x=100, y=94) is no longer pure white
                raw_data = bytes(surf.get_data())
                stride = surf.get_stride()
                px_offset = 94 * stride + 100 * 4
                b, g, r, a = raw_data[px_offset : px_offset + 4]
                assert (r, g, b) != (255, 255, 255)

                # Advance pulse timer past mid-fade and past completion
                win._synctex_pulse_start_time = time.monotonic() - 1.5
                assert win._on_synctex_pulse_tick() is True
                assert 0.0 < win._synctex_pulse_alpha < 1.0

                win._synctex_pulse_start_time = time.monotonic() - 5.0
                assert win._on_synctex_pulse_tick() is False
                assert win.synctex_highlight_boxes == []
                assert win._synctex_pulse_alpha == 0.0

                # open_or_focus_document with target_page=0 switches back to page 0 even from page 1
                assert win.open_or_focus_document(str(main_pdf_path), target_page=0) is True
                assert win.current_page_index == 0

                # Deferred forward search executes automatically inside _finish_loading
                fresh_sess = win.create_session(filepath=str(main_pdf_path))
                canon_fp = os.path.realpath(str(main_pdf_path))
                win._pending_synctex_forward[canon_fp] = ("main.tex", 14, 0)
                doc_reopen = fitz.open(str(main_pdf_path))
                win._finish_loading(doc_reopen, None, str(main_pdf_path), target_page=0, target_session=fresh_sess)
                assert canon_fp not in win._pending_synctex_forward
                assert len(win.synctex_highlight_boxes) == 1
                assert win.synctex_highlight_boxes[0]["page_index"] == 0
                assert win.synctex_highlight_boxes[0]["line"] == 14
            finally:
                win.clear_synctex_highlight_pulse()
                for s in list(win.sessions):
                    try:
                        s.close()
                    except Exception:
                        pass
                win.destroy()

