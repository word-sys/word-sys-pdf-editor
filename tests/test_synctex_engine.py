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

    def test_all_synctex_editor_presets_expand_unicode_and_spaced_paths(self):
        from word_sys_pdf_editor.settings_manager import SYNCTEX_EDITOR_PRESETS

        tricky_path = "/home/user/My Thesis (Draft)/chápter 1.tex"
        for preset_name, template in SYNCTEX_EDITOR_PRESETS.items():
            argv = format_editor_command(template, tricky_path, 128, 9)
            assert len(argv) >= 2, f"Preset {preset_name!r} produced empty argv"
            joined = " ".join(argv)
            assert tricky_path in joined, f"Preset {preset_name!r} lost tex path: {argv}"
            assert "128" in joined, f"Preset {preset_name!r} lost line number: {argv}"
            assert "%f" not in joined and "%l" not in joined and "%c" not in joined

    def test_forward_then_backward_search_roundtrip_consistency(self, tmp_path):
        payload = _build_sample_synctex(str(tmp_path))
        gz = tmp_path / "roundtrip.synctex.gz"
        with gzip.open(gz, "wb") as fh:
            fh.write(payload.encode("utf-8"))
        pdf = tmp_path / "roundtrip.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        doc = SyncTeXDocument.from_pdf(str(pdf), use_cli_fallback=False)
        assert doc is not None
        cases = [
            (os.path.normpath(str(tmp_path / "main.tex")), 10, 0),
            (os.path.normpath(str(tmp_path / "main.tex")), 14, 0),
            (os.path.normpath(str(tmp_path / "chapters" / "intro.tex")), 25, 1),
            (os.path.normpath(str(tmp_path / "chapters" / "intro.tex")), 30, 1),
        ]
        for tex_path, line_num, expected_page in cases:
            highlights = doc.forward_search(tex_path, line_num)
            assert len(highlights) >= 1
            hl = highlights[0]
            assert hl.page_index == expected_page
            cx = (hl.x0 + hl.x1) / 2.0
            cy = (hl.y0 + hl.y1) / 2.0
            loc = doc.backward_search(hl.page_index, cx, cy)
            assert loc is not None
            assert loc.tex_path == tex_path
            assert loc.line == line_num


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


class TestSyncTeXBackwardSearchAndPreferences:
    """Verify Ctrl+Click backward search, context menu jump action, editor launcher, and Preferences SyncTeX UI."""

    def test_ctrl_click_backward_search_hyperlink_priority_and_context_menu(self, tmp_path):
        import fitz
        from gi.repository import Adw, Gdk, Gtk
        from word_sys_pdf_editor.settings_manager import SettingsManager
        from word_sys_pdf_editor.window import PdfEditorWindow

        main_pdf_path = tmp_path / "main.pdf"
        d_main = fitz.open()
        d_main.new_page(width=595, height=842)
        d_main.new_page(width=595, height=842)
        d_main.save(str(main_pdf_path))
        d_main.close()

        gz_path = tmp_path / "main.synctex.gz"
        with gzip.open(gz_path, "wb") as gz:
            gz.write(_build_sample_synctex(str(tmp_path)).encode("utf-8"))

        plain_pdf_path = tmp_path / "no_synctex.pdf"
        d_plain = fitz.open()
        d_plain.new_page(width=595, height=842)
        d_plain.save(str(plain_pdf_path))
        d_plain.close()

        temp_mgr = SettingsManager(config_file=tmp_path / "settings.json")
        temp_mgr.set("synctex_enabled", True)
        temp_mgr.set("synctex_editor_preset", "vscode")

        with patch("word_sys_pdf_editor.i18n._save_settings"), \
             patch("word_sys_pdf_editor.settings_manager.get_settings_manager", return_value=temp_mgr):
            try:
                app = Adw.Application(application_id="org.word_sys.test_synctex_backward")
            except Exception:
                app = None
            win = PdfEditorWindow(application=app)
            try:
                win.font_scan_in_progress = False
                doc_main = fitz.open(str(main_pdf_path))
                sess_main = win.create_session(doc=doc_main, filepath=str(main_pdf_path))
                win.add_session(sess_main, switch_to=True)
                win.current_pdf_page_width = 595
                win.current_pdf_page_height = 842
                win.zoom_level = 1.0

                main_tex_expected = os.path.normpath(str(tmp_path / "main.tex"))

                # 1. Ctrl+Click on line 10 (not over a web hyperlink) launches VS Code at main.tex:10
                gesture = Gtk.GestureClick.new()
                with patch.object(Gtk.EventController, "get_current_event_state", return_value=Gdk.ModifierType.CONTROL_MASK), \
                     patch.object(win, "canvas_to_page_coords", return_value=(0, 115.0, 115.0)), \
                     patch.object(win, "is_canvas_point_on_page", return_value=True), \
                     patch.object(win, "_get_link_url_at_pos", return_value=None), \
                     patch("subprocess.Popen") as popen_mock:
                    win.on_pdf_view_pressed(gesture, 1, 115.0, 115.0)
                    assert popen_mock.call_count == 1
                    argv = popen_mock.call_args[0][0]
                    assert argv == ["code", "-g", f"{main_tex_expected}:10"]

                # 2. Ctrl+Click over a web hyperlink opens URL and does NOT launch LaTeX editor
                with patch.object(Gtk.EventController, "get_current_event_state", return_value=Gdk.ModifierType.CONTROL_MASK), \
                     patch.object(win, "canvas_to_page_coords", return_value=(0, 115.0, 115.0)), \
                     patch.object(win, "is_canvas_point_on_page", return_value=True), \
                     patch.object(win, "_get_link_url_at_pos", return_value="https://example.org"), \
                     patch.object(win, "_open_url") as open_url_mock, \
                     patch("subprocess.Popen") as popen_mock:
                    win.on_pdf_view_pressed(gesture, 1, 115.0, 115.0)
                    open_url_mock.assert_called_once_with("https://example.org")
                    assert popen_mock.call_count == 0

                # 3. Context menu adds 'Jump to LaTeX Source (.tex)' and clicking it invokes backward search
                pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                pop_box.append(Gtk.Button(label="Existing Action"))
                added = win._append_synctex_context_item(pop_box, 0, 115.0, 115.0)
                assert added is True
                children = []
                child = pop_box.get_first_child()
                while child is not None:
                    children.append(child)
                    child = child.get_next_sibling()
                jump_btn = children[-1]
                assert isinstance(jump_btn, Gtk.Button)
                assert ".tex" in (jump_btn.get_label() or "")

                with patch("subprocess.Popen") as popen_mock:
                    jump_btn.emit("clicked")
                    assert popen_mock.call_count == 1
                    assert popen_mock.call_args[0][0] == ["code", "-g", f"{main_tex_expected}:10"]

                # 4. FileNotFoundError during editor launch is handled gracefully without raising
                with patch("subprocess.Popen", side_effect=FileNotFoundError("no such binary")):
                    assert win.launch_external_latex_editor(main_tex_expected, 10, 0) is False

                # 5. Disabling synctex_enabled suppresses both Ctrl+Click and context menu item
                temp_mgr.set("synctex_enabled", False)
                assert win._has_synctex_for_active_session() is False
                pop_box_disabled = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                assert win._append_synctex_context_item(pop_box_disabled, 0, 115.0, 115.0) is False
                assert win.handle_synctex_backward_search(0, 115.0, 115.0) is None

                # 6. Document without .synctex/.synctex.gz does not add context menu item
                temp_mgr.set("synctex_enabled", True)
                doc_plain = fitz.open(str(plain_pdf_path))
                sess_plain = win.create_session(doc=doc_plain, filepath=str(plain_pdf_path))
                win.add_session(sess_plain, switch_to=True)
                assert win._has_synctex_for_active_session() is False
                pop_box_plain = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                assert win._append_synctex_context_item(pop_box_plain, 0, 100.0, 100.0) is False
            finally:
                win.clear_synctex_highlight_pulse()
                for s in list(win.sessions):
                    try:
                        s.close()
                    except Exception:
                        pass
                win.destroy()

    def test_preferences_window_synctex_presets_and_custom_command(self, tmp_path):
        from word_sys_pdf_editor.preferences_dialog import PreferencesWindow
        from word_sys_pdf_editor.settings_manager import (
            SYNCTEX_EDITOR_PRESETS,
            VALID_SYNCTEX_PRESETS,
            SettingsManager,
        )

        mgr = SettingsManager(config_file=tmp_path / "prefs_synctex.json")
        prefs = PreferencesWindow(editor_window=None, settings_manager=mgr)
        try:
            assert hasattr(prefs, "synctex_group")
            assert prefs.synctex_enabled_switch.get_active() is True
            assert prefs._synctex_preset_codes == list(VALID_SYNCTEX_PRESETS)
            assert prefs.synctex_command_entry.get_text() == SYNCTEX_EDITOR_PRESETS["vscode"]

            # Select TeXstudio preset -> command entry and SettingsManager update automatically
            ts_idx = prefs._synctex_preset_codes.index("texstudio")
            prefs.synctex_preset_dropdown.set_selected(ts_idx)
            assert mgr.get("synctex_editor_preset") == "texstudio"
            assert mgr.get("synctex_editor_command") == SYNCTEX_EDITOR_PRESETS["texstudio"]
            assert prefs.synctex_command_entry.get_text() == SYNCTEX_EDITOR_PRESETS["texstudio"]

            # Select Kate, Sublime, Emacs presets
            for code in ("kate", "sublime", "emacs", "vim", "neovim", "gedit"):
                idx = prefs._synctex_preset_codes.index(code)
                prefs.synctex_preset_dropdown.set_selected(idx)
                assert mgr.get("synctex_editor_preset") == code
                assert mgr.get("synctex_editor_command") == SYNCTEX_EDITOR_PRESETS[code]

            # Typing a custom command switches preset to "custom" and saves the template
            custom_cmd = 'my-tex-ide --file "%f" --line %l --col %c'
            prefs.synctex_command_entry.set_text(custom_cmd)
            assert mgr.get("synctex_editor_command") == custom_cmd
            assert mgr.get("synctex_editor_preset") == "custom"
            assert prefs.synctex_preset_dropdown.get_selected() == prefs._synctex_preset_codes.index("custom")

            # Disabling SyncTeX disables preset and command rows
            prefs.synctex_enabled_switch.set_active(False)
            assert mgr.get("synctex_enabled") is False
            assert prefs.synctex_preset_row.get_sensitive() is False
            assert prefs.synctex_command_row.get_sensitive() is False
        finally:
            prefs.close()
            prefs.destroy()


class TestLiveFileMonitorAndAutoReload:
    """Verify Gio.FileMonitor attachment, 400 ms debounce, PDF trailer checks, seamless auto-reload, and unsaved-edit banner."""

    def test_auto_reload_preserves_page_scroll_zoom_and_reloads_synctex(self, tmp_path):
        import fitz
        from gi.repository import Adw, Gio
        from word_sys_pdf_editor.settings_manager import SettingsManager
        from word_sys_pdf_editor.window import PdfEditorWindow

        pdf_path = tmp_path / "thesis.pdf"
        st_path = tmp_path / "thesis.synctex.gz"
        tex_path = str(tmp_path / "thesis.tex")

        def _write_pdf(marker: str, pages: int = 3):
            d = fitz.open()
            for idx in range(pages):
                p = d.new_page(width=595, height=842)
                p.insert_text((72, 120), f"{marker} Page {idx + 1}", fontsize=12)
            d.save(str(pdf_path))
            d.close()

        def _write_synctex(line_num: int):
            payload = (
                f"SyncTeX Version:1\nInput:1:{tex_path}\nOutput:thesis.pdf\n"
                f"Magnification:1000\nUnit:1\nX Offset:0\nY Offset:0\nContent:\n"
                f"{{1\n(1,{line_num}:{_sp(72)},{_sp(120)}:{_sp(200)},{_sp(12)},{_sp(2)}\n)\n}}1\nPostamble:\n"
            )
            with gzip.open(st_path, "wb") as gz:
                gz.write(payload.encode("utf-8"))

        _write_pdf("Initial LaTeX v1", pages=3)
        _write_synctex(12)

        temp_mgr = SettingsManager(config_file=tmp_path / "auto_reload_settings.json")
        temp_mgr.set("auto_reload_modified_pdf", True)

        with patch("word_sys_pdf_editor.i18n._save_settings"), \
             patch("word_sys_pdf_editor.settings_manager.get_settings_manager", return_value=temp_mgr):
            try:
                app = Adw.Application(application_id="org.word_sys.test_auto_reload_clean")
            except Exception:
                app = None
            win = PdfEditorWindow(application=app)
            try:
                win.font_scan_in_progress = False
                doc = fitz.open(str(pdf_path))
                sess = win.create_session(doc=doc, filepath=str(pdf_path))
                win.add_session(sess, switch_to=True)

                # FileMonitor attached cleanly
                assert sess.file_monitor is not None
                assert isinstance(sess.file_monitor, Gio.FileMonitor)
                assert win._is_pdf_file_ready_for_reload(str(pdf_path)) is True

                # Configure active viewport: page index 1, zoom 1.45, continuous scroll, scroll offset (35, 420)
                win.continuous_scroll = True
                sess.continuous_scroll = True
                win.zoom_level = 1.45
                sess.zoom_level = 1.45
                win._load_page(1, reload_objects=True)
                win.current_page_index = 1
                sess.current_page_index = 1
                h_adj = win.pdf_scroll.get_hadjustment()
                v_adj = win.pdf_scroll.get_vadjustment()
                h_adj.set_upper(2000.0)
                h_adj.set_page_size(500.0)
                h_adj.set_value(35.0)
                v_adj.set_upper(4000.0)
                v_adj.set_page_size(600.0)
                v_adj.set_value(420.0)
                sess.scroll_x = 35.0
                sess.scroll_y = 420.0

                # Burst of CHANGED events debounces cleanly into a single 400 ms timer
                with patch("gi.repository.GLib.timeout_add", side_effect=[101, 102]) as timeout_mock, \
                     patch("gi.repository.GLib.source_remove") as remove_mock:
                    win._on_session_file_monitor_changed(
                        sess.file_monitor, None, None, Gio.FileMonitorEvent.CHANGED, sess
                    )
                    win._on_session_file_monitor_changed(
                        sess.file_monitor, None, None, Gio.FileMonitorEvent.CHANGES_DONE_HINT, sess
                    )
                    assert timeout_mock.call_count == 2
                    assert timeout_mock.call_args_list[0][0][0] == 400
                    remove_mock.assert_called_once_with(101)
                    sess.file_monitor_debounce_id = None

                # Simulate LaTeX recompilation writing v2 PDF + updated .synctex.gz (line 77)
                _write_pdf("Recompiled LaTeX v2", pages=3)
                _write_synctex(77)

                assert win._on_file_monitor_debounce_fired(sess) is False
                assert "Recompiled LaTeX v2 Page 2" in sess.doc[1].get_text()
                assert win.current_page_index == 1
                assert abs(win.zoom_level - 1.45) < 1e-6
                assert abs(sess.scroll_x - 35.0) < 0.5
                assert abs(sess.scroll_y - 420.0) < 0.5
                assert win.external_reload_banner.get_visible() is False

                # SyncTeX index was refreshed in place and resolves new line 77
                assert sess.synctex_doc is not None
                hl = sess.synctex_doc.forward_search(tex_path, 77)
                assert len(hl) == 1 and hl[0].line == 77

                # Self-save suppression ignores file monitor events completely
                sess.suppress_file_monitor_until = time.monotonic() + 5.0
                with patch("gi.repository.GLib.timeout_add") as timeout_mock:
                    win._on_session_file_monitor_changed(
                        sess.file_monitor, None, None, Gio.FileMonitorEvent.CHANGED, sess
                    )
                    assert timeout_mock.call_count == 0
                sess.suppress_file_monitor_until = 0.0

                # Incomplete PDF without %%EOF trailer does NOT clobber open doc and schedules retry
                pdf_path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Incomplete true >>\n")
                assert win._is_pdf_file_ready_for_reload(str(pdf_path)) is False
                with patch("gi.repository.GLib.timeout_add", return_value=205) as retry_mock:
                    win._on_file_monitor_debounce_fired(sess)
                    assert retry_mock.call_count == 1
                    assert sess._file_monitor_retry_count == 1
                    assert "Recompiled LaTeX v2 Page 2" in sess.doc[1].get_text()
                    sess.file_monitor_debounce_id = None
            finally:
                for s in list(win.sessions):
                    try:
                        s.close()
                    except Exception:
                        pass
                assert sess.file_monitor is None
                win.destroy()

    def test_unsaved_edits_show_reload_banner_and_respects_auto_reload_setting(self, tmp_path):
        import fitz
        from gi.repository import Adw
        from word_sys_pdf_editor.settings_manager import SettingsManager
        from word_sys_pdf_editor.window import PdfEditorWindow

        pdf_a = tmp_path / "doc_a.pdf"
        pdf_b = tmp_path / "doc_b.pdf"

        def _save_text_pdf(path, text):
            d = fitz.open()
            p = d.new_page(width=595, height=842)
            p.insert_text((72, 120), text, fontsize=12)
            d.save(str(path))
            d.close()

        _save_text_pdf(pdf_a, "Version A1")
        _save_text_pdf(pdf_b, "Doc B")

        temp_mgr = SettingsManager(config_file=tmp_path / "banner_settings.json")
        temp_mgr.set("auto_reload_modified_pdf", True)

        with patch("word_sys_pdf_editor.i18n._save_settings"), \
             patch("word_sys_pdf_editor.settings_manager.get_settings_manager", return_value=temp_mgr):
            try:
                app = Adw.Application(application_id="org.word_sys.test_auto_reload_banner")
            except Exception:
                app = None
            win = PdfEditorWindow(application=app)
            try:
                win.font_scan_in_progress = False
                sess_a = win.create_session(doc=fitz.open(str(pdf_a)), filepath=str(pdf_a))
                win.add_session(sess_a, switch_to=True)
                sess_b = win.create_session(doc=fitz.open(str(pdf_b)), filepath=str(pdf_b))
                win.add_session(sess_b, switch_to=False)

                # Mark session A as having unsaved edits
                sess_a.is_modified = True
                win.document_modified = True

                # External update on disk -> must NOT auto-reload; must show non-intrusive banner
                _save_text_pdf(pdf_a, "Version A2 From LaTeX")
                win._on_file_monitor_debounce_fired(sess_a)
                assert "Version A1" in sess_a.doc[0].get_text()
                assert sess_a.external_change_pending is True
                assert win.external_reload_banner.get_visible() is True

                # Switching to clean tab B hides banner; switching back to tab A shows it again
                win.set_active_session(sess_b)
                assert win.external_reload_banner.get_visible() is False
                win.set_active_session(sess_a)
                assert win.external_reload_banner.get_visible() is True

                # Clicking Reload button discards unsaved edits, loads Version A2, and hides banner
                win.external_reload_banner_btn.emit("clicked")
                assert "Version A2 From LaTeX" in sess_a.doc[0].get_text()
                assert sess_a.is_modified is False
                assert sess_a.external_change_pending is False
                assert win.external_reload_banner.get_visible() is False

                # When auto_reload_modified_pdf is False, external changes are ignored
                temp_mgr.set("auto_reload_modified_pdf", False)
                _save_text_pdf(pdf_a, "Version A3 Ignored")
                win._on_file_monitor_debounce_fired(sess_a)
                assert "Version A2 From LaTeX" in sess_a.doc[0].get_text()
                assert win.external_reload_banner.get_visible() is False
            finally:
                for s in list(win.sessions):
                    try:
                        s.close()
                    except Exception:
                        pass
                win.destroy()



