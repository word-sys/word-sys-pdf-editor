"""Pure-Python SyncTeX parser, coordinate mapper, and CLI fallback engine.

Supports:
- Automatic discovery of `.synctex.gz` and `.synctex` files for a given PDF path.
- Full SyncTeX Version 1 parsing:
  - Preamble (`Input:<tag>:<path>`, `Magnification`, `Unit`, `X Offset`, `Y Offset`)
  - Dynamic `Input:` entries inside `Content:`
  - Page blocks (`{<page>` ... `}<page>`)
  - Hierarchical vertical/horizontal boxes (`[`/`]`, `(`/`)`) and void/leaf records
    (`v`, `h`, `x`, `k`, `g`, `$`)
- Conversion from SyncTeX scaled points (`1 bp = 65781.76 sp`) to PDF top-left-origin
  PostScript points (matching PyMuPDF `fitz.Page` and Cairo canvas coordinates).
- Forward search: `(tex_file, line, column) -> list[SyncTeXHighlight]`
- Backward search: `(page_index, pdf_x, pdf_y) -> Optional[SyncTeXLocation]`
- Optional cross-check / fallback via the system `synctex` CLI (`synctex view` / `synctex edit`)
  whenever installed.
- Utility helpers for `--synctex-forward` argument parsing and external editor command formatting.
"""

from __future__ import annotations

import gzip
import math
import os
import re
import shlex
import shutil
import subprocess
import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

# Exact conversion factor from TeX scaled points (sp) to PDF PostScript points (bp):
# 1 inch = 72.27 TeX pt = 72.0 PDF bp; 1 TeX pt = 65536 sp => 65536 * 72.27 / 72.0 = 65781.76 sp/bp.
SYNCTEX_SP_PER_BP: float = 65781.76

# Record kind classification
_BOX_KINDS = frozenset({"vbox", "hbox", "void_vbox", "void_hbox"})
_HBOX_KINDS = frozenset({"hbox", "void_hbox"})
_VBOX_KINDS = frozenset({"vbox", "void_vbox"})
_LEAF_KINDS = frozenset({"current", "kern", "glue", "math"})


@dataclass
class SyncTeXHighlight:
    """A resolved PDF highlight box produced by SyncTeX forward search."""

    page_index: int  # 0-based page index
    x0: float
    y0: float
    x1: float
    y1: float
    tex_path: str = ""
    line: int = 0
    column: int = 0

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def to_dict(self) -> Dict[str, object]:
        return {
            "page_index": self.page_index,
            "bbox": self.bbox,
            "tex_path": self.tex_path,
            "line": self.line,
            "column": self.column,
        }


@dataclass
class SyncTeXLocation:
    """A resolved TeX source location produced by SyncTeX backward search."""

    tex_path: str
    line: int
    column: int = 0
    page_index: int = 0
    bbox: Optional[Tuple[float, float, float, float]] = None

    def as_tuple(self) -> Tuple[str, int, int]:
        return (self.tex_path, self.line, self.column)


@dataclass
class SyncTeXRecord:
    """Internal parsed SyncTeX node record in PDF point coordinates (top-left origin)."""

    kind: str  # "vbox", "hbox", "void_vbox", "void_hbox", "current", "kern", "glue", "math"
    tag: int
    line: int
    column: int
    page_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    depth: int = 0
    has_explicit_box: bool = True
    parent_hbox_bbox: Optional[Tuple[float, float, float, float]] = None

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


def _normalize_fs_path(path: str, base_dir: str = "") -> str:
    """Normalize a filesystem path or `file://` URI against an optional base directory."""
    if not path:
        return ""
    text = str(path).strip()
    if text.startswith("file://"):
        parsed = urlparse(text)
        text = unquote(parsed.path)
    if base_dir and not os.path.isabs(text):
        text = os.path.join(base_dir, text)
    return os.path.normpath(text)


def _canonical_path_key(path: str, base_dir: str = "") -> str:
    """Return a canonical path key suitable for comparing TeX file paths."""
    norm = _normalize_fs_path(path, base_dir=base_dir)
    if not norm:
        return ""
    try:
        if os.path.exists(norm):
            return os.path.realpath(norm)
    except OSError:
        pass
    return norm


def find_synctex_file(pdf_path: Optional[str]) -> Optional[str]:
    """Locate the `.synctex.gz` or `.synctex` file associated with `pdf_path`."""
    if not pdf_path:
        return None
    norm_pdf = _normalize_fs_path(pdf_path)
    if not norm_pdf:
        return None

    root, ext = os.path.splitext(norm_pdf)
    candidates: List[str] = []
    if ext.lower() == ".pdf":
        candidates.extend([f"{root}.synctex.gz", f"{root}.synctex"])
    candidates.extend([f"{norm_pdf}.synctex.gz", f"{norm_pdf}.synctex"])

    seen = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        if os.path.isfile(cand):
            return cand
    return None


def is_synctex_cli_available() -> bool:
    """Return True if the system `synctex` CLI executable is available on PATH."""
    return shutil.which("synctex") is not None


def parse_synctex_forward_arg(spec: str) -> Optional[Tuple[int, int, str]]:
    """Parse a `--synctex-forward` specification string into `(line, column, tex_path)`.

    Supported formats:
    - `LINE:COL:TEX_PATH` (standard TeXstudio / VS Code LaTeX Workshop / Okular / Evince syntax)
    - `LINE:TEX_PATH` (column defaults to 0)
    """
    if not spec or not isinstance(spec, str):
        return None
    raw = spec.strip()
    if not raw:
        return None

    parts = raw.split(":", 2)
    if len(parts) < 2:
        return None

    try:
        line = int(parts[0].strip())
    except ValueError:
        return None
    if line < 1:
        line = 1

    if len(parts) == 3:
        col_str = parts[1].strip()
        if col_str == "" or re.fullmatch(r"-?\d+", col_str):
            col = max(0, int(col_str)) if col_str else 0
            tex_path = parts[2].strip()
            return (line, col, tex_path) if tex_path else None
        # Second segment was not a number (e.g. Windows drive letter `LINE:C:\...`)
        tex_path = f"{parts[1]}:{parts[2]}".strip()
        return (line, 0, tex_path) if tex_path else None

    tex_path = parts[1].strip()
    return (line, 0, tex_path) if tex_path else None


def format_editor_command(
    template: str,
    tex_path: str,
    line: int,
    column: int = 0,
) -> List[str]:
    """Expand `%f`, `%l`, `%c` placeholders in an editor command template into an argv list.

    Uses token-level replacement after `shlex.split` so paths containing spaces or
    shell metacharacters are passed safely without shell interpolation.
    """
    if not template or not isinstance(template, str):
        return []
    raw = template.strip()
    if not raw:
        return []

    safe_line = str(max(1, int(line)))
    safe_col = str(max(0, int(column)))
    safe_file = str(tex_path or "")

    # Protect placeholders inside tokens before shlex splitting
    f_tok = "__SYNCTEX_FILE_PLACEHOLDER__"
    l_tok = "__SYNCTEX_LINE_PLACEHOLDER__"
    c_tok = "__SYNCTEX_COL_PLACEHOLDER__"
    protected = raw.replace("%f", f_tok).replace("%l", l_tok).replace("%c", c_tok)
    try:
        tokens = shlex.split(protected)
    except ValueError:
        tokens = protected.split()

    result: List[str] = []
    for tok in tokens:
        expanded = tok.replace(f_tok, safe_file).replace(l_tok, safe_line).replace(c_tok, safe_col)
        result.append(expanded)
    return result


def _parse_int_or_prev(token: str, prev_value: int) -> Optional[int]:
    """Parse a SyncTeX integer coordinate or `=` shorthand referring to `prev_value`."""
    t = token.strip()
    if t == "=":
        return prev_value
    try:
        return int(t)
    except ValueError:
        return None


def _parse_link(link_str: str) -> Optional[Tuple[int, int, int]]:
    """Parse SyncTeX `<tag>,<line>[,<col>]` link tuple."""
    parts = link_str.split(",")
    if len(parts) < 2:
        return None
    try:
        tag = int(parts[0])
        line = int(parts[1])
        col = int(parts[2]) if len(parts) >= 3 and parts[2] != "" else 0
        return (tag, line, max(0, col))
    except ValueError:
        return None


def _merge_line_highlights(
    highlights: Sequence[SyncTeXHighlight],
    y_overlap_tol: float = 2.0,
    x_gap_tol: float = 24.0,
) -> List[SyncTeXHighlight]:
    """Merge overlapping or horizontally adjacent highlight rectangles on the same line."""
    if not highlights:
        return []

    sorted_hl = sorted(highlights, key=lambda h: (h.page_index, round(h.y0, 1), h.x0))
    merged: List[SyncTeXHighlight] = []

    for h in sorted_hl:
        if not merged:
            merged.append(
                SyncTeXHighlight(
                    page_index=h.page_index,
                    x0=h.x0,
                    y0=h.y0,
                    x1=h.x1,
                    y1=h.y1,
                    tex_path=h.tex_path,
                    line=h.line,
                    column=h.column,
                )
            )
            continue

        prev = merged[-1]
        same_page = prev.page_index == h.page_index
        # Check vertical overlap or close line baseline alignment
        v_overlap = min(prev.y1, h.y1) - max(prev.y0, h.y0)
        min_h = max(1.0, min(prev.height, h.height))
        same_band = v_overlap >= (-y_overlap_tol) and (
            v_overlap >= 0.35 * min_h or abs(prev.y0 - h.y0) <= 3.5
        )
        close_x = h.x0 <= prev.x1 + x_gap_tol and prev.x0 <= h.x1 + x_gap_tol

        if same_page and same_band and close_x:
            prev.x0 = min(prev.x0, h.x0)
            prev.y0 = min(prev.y0, h.y0)
            prev.x1 = max(prev.x1, h.x1)
            prev.y1 = max(prev.y1, h.y1)
        else:
            merged.append(
                SyncTeXHighlight(
                    page_index=h.page_index,
                    x0=h.x0,
                    y0=h.y0,
                    x1=h.x1,
                    y1=h.y1,
                    tex_path=h.tex_path,
                    line=h.line,
                    column=h.column,
                )
            )
    return merged


class SyncTeXDocument:
    """Parsed SyncTeX index supporting forward and backward search for a PDF document."""

    def __init__(
        self,
        pdf_path: Optional[str] = None,
        synctex_path: Optional[str] = None,
        auto_load: bool = True,
        use_cli_fallback: bool = True,
    ):
        self.pdf_path: Optional[str] = _normalize_fs_path(pdf_path) if pdf_path else None
        self.synctex_path: Optional[str] = (
            _normalize_fs_path(synctex_path) if synctex_path else find_synctex_file(self.pdf_path)
        )
        self.use_cli_fallback: bool = bool(use_cli_fallback)

        self.version: int = 1
        self.output_file: str = ""
        self.magnification: float = 1000.0
        self.unit: float = 1.0
        self.x_offset: int = 0
        self.y_offset: int = 0

        self.input_files: Dict[int, str] = {}
        self._raw_input_files: Dict[int, str] = {}
        self._canonical_input_files: Dict[int, str] = {}
        self._records_by_page: Dict[int, List[SyncTeXRecord]] = {}
        self._records_by_tag_line: Dict[Tuple[int, int], List[SyncTeXRecord]] = {}
        self._lines_by_tag: Dict[int, List[int]] = {}
        self._base_dir: str = ""
        self._loaded: bool = False
        self.mtime: float = 0.0

        if auto_load and self.synctex_path:
            self.load(self.synctex_path)

    @classmethod
    def from_pdf(
        cls,
        pdf_path: str,
        use_cli_fallback: bool = True,
    ) -> Optional["SyncTeXDocument"]:
        """Discover and load the SyncTeX data corresponding to `pdf_path`, or return None."""
        st_path = find_synctex_file(pdf_path)
        if not st_path:
            return None
        doc = cls(
            pdf_path=pdf_path,
            synctex_path=st_path,
            auto_load=True,
            use_cli_fallback=use_cli_fallback,
        )
        return doc if doc.is_loaded else None

    @classmethod
    def from_string(
        cls,
        content: str,
        base_dir: str = "",
        pdf_path: Optional[str] = None,
        use_cli_fallback: bool = False,
    ) -> "SyncTeXDocument":
        """Create and parse a `SyncTeXDocument` directly from raw SyncTeX text."""
        doc = cls(
            pdf_path=pdf_path,
            synctex_path=None,
            auto_load=False,
            use_cli_fallback=use_cli_fallback,
        )
        doc.parse_text(content, base_dir=base_dir)
        return doc

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def page_count(self) -> int:
        if not self._records_by_page:
            return 0
        return max(self._records_by_page.keys()) + 1

    @property
    def scale(self) -> float:
        """Multiplicative factor converting SyncTeX integer units into PDF PostScript points (bp)."""
        return (self.unit * (self.magnification / 1000.0)) / SYNCTEX_SP_PER_BP

    def _reset(self) -> None:
        self.version = 1
        self.output_file = ""
        self.magnification = 1000.0
        self.unit = 1.0
        self.x_offset = 0
        self.y_offset = 0
        self.input_files.clear()
        self._raw_input_files.clear()
        self._canonical_input_files.clear()
        self._records_by_page.clear()
        self._records_by_tag_line.clear()
        self._lines_by_tag.clear()
        self._loaded = False

    def load(self, synctex_path: Optional[str] = None) -> bool:
        """Read and parse `.synctex.gz` or `.synctex` from disk."""
        target = _normalize_fs_path(synctex_path) if synctex_path else self.synctex_path
        if not target and self.pdf_path:
            target = find_synctex_file(self.pdf_path)
        if not target or not os.path.isfile(target):
            self._reset()
            return False

        self.synctex_path = target
        base_dir = os.path.dirname(os.path.abspath(target))
        try:
            with open(target, "rb") as fh:
                magic = fh.read(2)
            is_gzip = target.lower().endswith(".gz") or magic == b"\x1f\x8b"
            if is_gzip:
                with gzip.open(target, "rb") as gz:
                    raw_bytes = gz.read()
            else:
                with open(target, "rb") as fh:
                    raw_bytes = fh.read()
            text = raw_bytes.decode("utf-8", errors="replace")
            self.mtime = os.path.getmtime(target)
        except (OSError, EOFError, zlib.error):
            self._reset()
            return False

        return self.parse_text(text, base_dir=base_dir)

    def reload_if_changed(self) -> bool:
        """Reload the SyncTeX file if it appeared or its mtime changed on disk."""
        target = self.synctex_path or find_synctex_file(self.pdf_path)
        if not target or not os.path.isfile(target):
            return False
        try:
            current_mtime = os.path.getmtime(target)
        except OSError:
            return False
        if (not self._loaded) or (target != self.synctex_path) or (current_mtime != self.mtime):
            return self.load(target)
        return False

    def _register_input(self, line_text: str, base_dir: str) -> None:
        # Format: Input:<tag>:<path>
        rest = line_text[6:]
        sep_idx = rest.find(":")
        if sep_idx <= 0:
            return
        try:
            tag = int(rest[:sep_idx].strip())
        except ValueError:
            return
        raw_path = rest[sep_idx + 1 :].strip()
        if not raw_path:
            return
        norm_path = _normalize_fs_path(raw_path, base_dir=base_dir)
        self._raw_input_files[tag] = raw_path
        self.input_files[tag] = norm_path
        self._canonical_input_files[tag] = _canonical_path_key(norm_path, base_dir=base_dir)

    def parse_text(self, content: str, base_dir: str = "") -> bool:
        """Parse SyncTeX Version 1 textual content into internal page and line indices."""
        self._reset()
        if not content:
            return False

        self._base_dir = base_dir or (
            os.path.dirname(os.path.abspath(self.pdf_path)) if self.pdf_path else ""
        )

        in_content = False
        current_page_index: Optional[int] = None
        box_stack: List[SyncTeXRecord] = []
        last_h = 0
        last_v = 0
        scale = self.scale

        for raw_line in content.splitlines():
            if not raw_line:
                continue
            line = raw_line.rstrip("\r\n")
            if not line:
                continue

            # Dynamic Input: lines can appear in both preamble and Content:
            if line.startswith("Input:"):
                self._register_input(line, self._base_dir)
                continue

            if not in_content:
                if line.startswith("SyncTeX Version:"):
                    try:
                        self.version = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif line.startswith("Output:"):
                    self.output_file = line.split(":", 1)[1].strip()
                elif line.startswith("Magnification:"):
                    try:
                        val = float(line.split(":", 1)[1].strip())
                        if val > 0:
                            self.magnification = val
                    except ValueError:
                        pass
                elif line.startswith("Unit:"):
                    try:
                        val = float(line.split(":", 1)[1].strip())
                        if val > 0:
                            self.unit = val
                    except ValueError:
                        pass
                elif line.startswith("X Offset:"):
                    try:
                        self.x_offset = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif line.startswith("Y Offset:"):
                    try:
                        self.y_offset = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif line.startswith("Content:"):
                    in_content = True
                    scale = self.scale
                continue

            # Inside Content:
            if line.startswith("Postamble:"):
                break

            first = line[0]
            if first == "!":
                # SyncTeX byte offset anchor line
                continue
            if first == "{":
                try:
                    page_num = int(line[1:].strip())
                    current_page_index = max(0, page_num - 1)
                    box_stack.clear()
                    self._records_by_page.setdefault(current_page_index, [])
                except ValueError:
                    pass
                continue
            if first == "}":
                current_page_index = None
                box_stack.clear()
                continue
            if first == "]" or first == ")":
                if box_stack:
                    box_stack.pop()
                continue
            if first == "<" or first == ">":
                # XObject form markers (SyncTeX >= 1.16)
                continue

            if current_page_index is None:
                continue

            if first in ("[", "(", "v", "h"):
                # Box record: <char><tag>,<line>[,<col>]:<h>,<v>:<W>,<H>,<D>
                colon1 = line.find(":", 1)
                if colon1 < 0:
                    continue
                colon2 = line.find(":", colon1 + 1)
                if colon2 < 0:
                    continue

                link = _parse_link(line[1:colon1])
                if link is None:
                    continue
                tag, src_line, src_col = link

                pos_parts = line[colon1 + 1 : colon2].split(",")
                dim_parts = line[colon2 + 1 :].split(",")
                if len(pos_parts) < 2 or len(dim_parts) < 3:
                    continue

                h_val = _parse_int_or_prev(pos_parts[0], last_h)
                v_val = _parse_int_or_prev(pos_parts[1], last_v)
                if h_val is None or v_val is None:
                    continue
                try:
                    w_val = int(dim_parts[0])
                    ht_val = int(dim_parts[1])
                    dp_val = int(dim_parts[2])
                except ValueError:
                    continue

                last_h, last_v = h_val, v_val
                x = (h_val + self.x_offset) * scale
                y = (v_val + self.y_offset) * scale
                w_pt = w_val * scale
                ht_pt = ht_val * scale
                dp_pt = dp_val * scale

                x0, x1 = (x, x + w_pt) if w_pt >= 0 else (x + w_pt, x)
                y0, y1 = min(y - ht_pt, y + dp_pt), max(y - ht_pt, y + dp_pt)

                kind_map = {
                    "[": "vbox",
                    "(": "hbox",
                    "v": "void_vbox",
                    "h": "void_hbox",
                }
                rec = SyncTeXRecord(
                    kind=kind_map[first],
                    tag=tag,
                    line=src_line,
                    column=src_col,
                    page_index=current_page_index,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    depth=len(box_stack),
                    has_explicit_box=True,
                )
                self._add_record(rec)
                if first in ("[", "("):
                    box_stack.append(rec)
                continue

            if first in ("x", "k", "g", "$"):
                # Leaf record:
                # k<tag>,<line>[,<col>]:<h>,<v>:<W>
                # x/g/$<tag>,<line>[,<col>]:<h>,<v>
                colon1 = line.find(":", 1)
                if colon1 < 0:
                    continue
                link = _parse_link(line[1:colon1])
                if link is None:
                    continue
                tag, src_line, src_col = link

                colon2 = line.find(":", colon1 + 1)
                if colon2 >= 0:
                    pos_str = line[colon1 + 1 : colon2]
                    extra_str = line[colon2 + 1 :]
                else:
                    pos_str = line[colon1 + 1 :]
                    extra_str = ""

                pos_parts = pos_str.split(",")
                if len(pos_parts) < 2:
                    continue
                h_val = _parse_int_or_prev(pos_parts[0], last_h)
                v_val = _parse_int_or_prev(pos_parts[1], last_v)
                if h_val is None or v_val is None:
                    continue
                last_h, last_v = h_val, v_val

                x = (h_val + self.x_offset) * scale
                y = (v_val + self.y_offset) * scale

                # Inherit vertical line band from innermost enclosing hbox when available
                parent_hbox_bbox: Optional[Tuple[float, float, float, float]] = None
                for ancestor in reversed(box_stack):
                    if ancestor.kind == "hbox" and (ancestor.y1 - ancestor.y0) > 0.5:
                        parent_hbox_bbox = (ancestor.x0, ancestor.y0, ancestor.x1, ancestor.y1)
                        break

                if parent_hbox_bbox is not None:
                    y0, y1 = parent_hbox_bbox[1], parent_hbox_bbox[3]
                else:
                    y0, y1 = y - 10.0, y + 2.5

                has_box = False
                if first == "k" and extra_str:
                    try:
                        w_pt = int(extra_str.split(",", 1)[0]) * scale
                        x0, x1 = min(x, x - w_pt), max(x, x - w_pt)
                        has_box = (x1 - x0) > 0.1
                    except ValueError:
                        x0 = x1 = x
                else:
                    x0 = x1 = x

                leaf_map = {
                    "x": "current",
                    "k": "kern",
                    "g": "glue",
                    "$": "math",
                }
                rec = SyncTeXRecord(
                    kind=leaf_map[first],
                    tag=tag,
                    line=src_line,
                    column=src_col,
                    page_index=current_page_index,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    depth=len(box_stack),
                    has_explicit_box=has_box,
                    parent_hbox_bbox=parent_hbox_bbox,
                )
                self._add_record(rec)

        # Build sorted line lists per tag for fast nearest-line lookup
        tag_lines: Dict[int, set] = {}
        for tag, line_num in self._records_by_tag_line.keys():
            if line_num > 0:
                tag_lines.setdefault(tag, set()).add(line_num)
        for tag, lines_set in tag_lines.items():
            self._lines_by_tag[tag] = sorted(lines_set)

        self._loaded = bool(self.input_files or self._records_by_page)
        return self._loaded

    def _add_record(self, rec: SyncTeXRecord) -> None:
        self._records_by_page.setdefault(rec.page_index, []).append(rec)
        if rec.line > 0:
            self._records_by_tag_line.setdefault((rec.tag, rec.line), []).append(rec)

    def _resolve_matching_tags(self, tex_file: str) -> List[int]:
        """Find all SyncTeX input tags corresponding to `tex_file`."""
        if not tex_file or not self.input_files:
            return []

        raw_query = str(tex_file).strip()
        if raw_query.startswith("file://"):
            raw_query = unquote(urlparse(raw_query).path)

        candidates_to_try = [raw_query]
        if not os.path.splitext(raw_query)[1]:
            candidates_to_try.append(f"{raw_query}.tex")

        for query in candidates_to_try:
            norm_q = _normalize_fs_path(query, base_dir=self._base_dir)
            canon_q = _canonical_path_key(query, base_dir=self._base_dir)

            # 1. Exact canonical or normalized match
            exact = [
                tag
                for tag in self.input_files
                if self._canonical_input_files.get(tag) == canon_q
                or self.input_files.get(tag) == norm_q
            ]
            if exact:
                return exact

            # 2. Case-insensitive canonical match
            canon_q_low = canon_q.lower()
            ci_exact = [
                tag
                for tag in self.input_files
                if self._canonical_input_files.get(tag, "").lower() == canon_q_low
            ]
            if ci_exact:
                return ci_exact

            # 3. Path suffix match (e.g. `chapters/intro.tex` matches `/proj/chapters/intro.tex`)
            q_parts = [p for p in os.path.normpath(query).replace("\\", "/").split("/") if p and p != "."]
            if q_parts:
                suffix_matches: List[int] = []
                for tag, stored_path in self.input_files.items():
                    s_parts = [p for p in stored_path.replace("\\", "/").split("/") if p and p != "."]
                    if len(s_parts) >= len(q_parts) and s_parts[-len(q_parts) :] == q_parts:
                        suffix_matches.append(tag)
                if suffix_matches:
                    return suffix_matches

            # 4. Basename fallback
            q_base = os.path.basename(query).lower()
            if q_base:
                base_matches = [
                    tag
                    for tag, stored_path in self.input_files.items()
                    if os.path.basename(stored_path).lower() == q_base
                ]
                if base_matches:
                    return base_matches

        return []

    def _records_to_highlights(
        self,
        records: Sequence[SyncTeXRecord],
        tex_path: str,
        line: int,
        column: int = 0,
    ) -> List[SyncTeXHighlight]:
        """Convert matched SyncTeX records for a line into clean highlight rectangles."""
        if not records:
            return []

        # Tier 1: hbox / void_hbox with non-trivial area
        hboxes = [r for r in records if r.kind in _HBOX_KINDS and (r.x1 - r.x0) > 0.5 and (r.y1 - r.y0) > 0.5]
        # Tier 2: leaf nodes (current, kern, glue, math)
        leaves = [r for r in records if r.kind in _LEAF_KINDS]
        # Tier 3: vbox / void_vbox
        vboxes = [r for r in records if r.kind in _VBOX_KINDS and (r.x1 - r.x0) > 0.5 and (r.y1 - r.y0) > 0.5]

        raw_highlights: List[SyncTeXHighlight] = []

        if hboxes:
            chosen = hboxes
            if column > 0:
                col_recs = [r for r in hboxes if r.column > 0]
                if col_recs:
                    min_dist = min(abs(r.column - column) for r in col_recs)
                    chosen = [r for r in col_recs if abs(r.column - column) == min_dist]
            for r in chosen:
                raw_highlights.append(
                    SyncTeXHighlight(
                        page_index=r.page_index,
                        x0=r.x0,
                        y0=r.y0,
                        x1=r.x1,
                        y1=r.y1,
                        tex_path=tex_path,
                        line=r.line,
                        column=r.column,
                    )
                )
        elif leaves:
            chosen = leaves
            if column > 0:
                col_recs = [r for r in leaves if r.column > 0]
                if col_recs:
                    min_dist = min(abs(r.column - column) for r in col_recs)
                    chosen = [r for r in col_recs if abs(r.column - column) == min_dist]

            # Group leaves by (page_index, parent_hbox_bbox or rounded baseline band)
            grouped: Dict[Tuple[int, int], List[SyncTeXRecord]] = {}
            for r in chosen:
                band_key = (r.page_index, int(round(r.y0 / 4.0)))
                grouped.setdefault(band_key, []).append(r)

            for (p_idx, _band), grp in grouped.items():
                gx0 = min(r.x0 for r in grp)
                gy0 = min(r.y0 for r in grp)
                gx1 = max(r.x1 for r in grp)
                gy1 = max(r.y1 for r in grp)

                # If leaves collapsed to a very narrow point, expand cleanly to parent hbox
                # or a visible marker width so the highlight is always legible.
                if (gx1 - gx0) < 6.0:
                    parent_boxes = [r.parent_hbox_bbox for r in grp if r.parent_hbox_bbox is not None]
                    if parent_boxes:
                        pb = parent_boxes[0]
                        if (pb[2] - pb[0]) > 4.0 and (pb[3] - pb[1]) <= 36.0:
                            gx0, gy0, gx1, gy1 = pb
                    if (gx1 - gx0) < 6.0:
                        gx0 = max(0.0, gx0 - 4.0)
                        gx1 = gx0 + 24.0
                if (gy1 - gy0) < 6.0:
                    gy0 = gy0 - 5.0
                    gy1 = gy1 + 5.0

                raw_highlights.append(
                    SyncTeXHighlight(
                        page_index=p_idx,
                        x0=gx0,
                        y0=gy0,
                        x1=gx1,
                        y1=gy1,
                        tex_path=tex_path,
                        line=grp[0].line,
                        column=grp[0].column,
                    )
                )
        elif vboxes:
            # Prefer tightest vboxes (highest depth / smallest area) rather than entire page body
            max_depth = max(r.depth for r in vboxes)
            deepest = [r for r in vboxes if r.depth == max_depth]
            for r in deepest:
                raw_highlights.append(
                    SyncTeXHighlight(
                        page_index=r.page_index,
                        x0=r.x0,
                        y0=r.y0,
                        x1=r.x1,
                        y1=r.y1,
                        tex_path=tex_path,
                        line=r.line,
                        column=r.column,
                    )
                )
        else:
            # Degenerate zero-size box fallback
            for r in records:
                x0 = r.x0
                x1 = max(r.x1, r.x0 + 24.0)
                y0 = r.y0
                y1 = max(r.y1, r.y0 + 12.0)
                raw_highlights.append(
                    SyncTeXHighlight(
                        page_index=r.page_index,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        tex_path=tex_path,
                        line=r.line,
                        column=r.column,
                    )
                )

        return _merge_line_highlights(raw_highlights)

    def forward_search(
        self,
        tex_file: str,
        line: int,
        column: int = 0,
        prefer_cli: bool = False,
    ) -> List[SyncTeXHighlight]:
        """Resolve `(tex_file, line, column)` to PDF highlight rectangles.

        Returns a list of `SyncTeXHighlight` objects with 0-based `page_index` and
        `(x0, y0, x1, y1)` PDF bounding boxes (top-left origin).
        """
        target_line = max(1, int(line))
        target_col = max(0, int(column))

        if prefer_cli and self.use_cli_fallback and self.pdf_path and is_synctex_cli_available():
            cli_res = self._cli_forward_search(tex_file, target_line, target_col)
            if cli_res:
                return cli_res

        tags = self._resolve_matching_tags(tex_file)
        if tags:
            # 1. Try exact line match across all matching tags
            exact_records: List[SyncTeXRecord] = []
            resolved_tex_path = self.input_files.get(tags[0], tex_file)
            for tag in tags:
                recs = self._records_by_tag_line.get((tag, target_line))
                if recs:
                    exact_records.extend(recs)
                    resolved_tex_path = self.input_files.get(tag, resolved_tex_path)
            if exact_records:
                return self._records_to_highlights(exact_records, resolved_tex_path, target_line, target_col)

            # 2. Nearest line fallback (cursor on blank line / comment / command line)
            best_pair: Optional[Tuple[int, int]] = None
            best_key: Optional[Tuple[int, int]] = None
            for tag in tags:
                for cand_line in self._lines_by_tag.get(tag, ()):
                    dist = abs(cand_line - target_line)
                    # Slight tie-break preference for lines >= target_line (forward into paragraph)
                    tie = 0 if cand_line >= target_line else 1
                    key = (dist, tie)
                    if best_key is None or key < best_key:
                        best_key = key
                        best_pair = (tag, cand_line)

            if best_pair is not None:
                best_tag, best_line = best_pair
                recs = self._records_by_tag_line.get((best_tag, best_line), [])
                resolved_tex_path = self.input_files.get(best_tag, tex_file)
                highlights = self._records_to_highlights(recs, resolved_tex_path, best_line, target_col)
                if highlights:
                    return highlights

        if self.use_cli_fallback and self.pdf_path and is_synctex_cli_available():
            return self._cli_forward_search(tex_file, target_line, target_col)

        return []

    def backward_search(
        self,
        page_index: int,
        pdf_x: float,
        pdf_y: float,
        prefer_cli: bool = False,
    ) -> Optional[SyncTeXLocation]:
        """Resolve a PDF point `(page_index, pdf_x, pdf_y)` to a TeX source location.

        `page_index` is 0-based and `(pdf_x, pdf_y)` are top-left-origin PDF points.
        """
        p_idx = int(page_index)
        px = float(pdf_x)
        py = float(pdf_y)

        if prefer_cli and self.use_cli_fallback and self.pdf_path and is_synctex_cli_available():
            cli_loc = self._cli_backward_search(p_idx, px, py)
            if cli_loc is not None:
                return cli_loc

        records = self._records_by_page.get(p_idx)
        if records:
            valid = [r for r in records if r.tag in self.input_files and r.line > 0]
            if valid:
                # 1. Containing records (with small 1.5 pt tolerance)
                tol = 1.5
                containing: List[SyncTeXRecord] = [
                    r
                    for r in valid
                    if (r.x0 - tol) <= px <= (r.x1 + tol) and (r.y0 - tol) <= py <= (r.y1 + tol)
                ]
                if containing:
                    def _contain_rank(r: SyncTeXRecord) -> Tuple[int, float, int]:
                        # Prefer leaf / hbox over outer vbox; then smallest area; then deepest nesting
                        if r.kind in _LEAF_KINDS:
                            tier = 0
                        elif r.kind in _HBOX_KINDS:
                            tier = 1
                        else:
                            tier = 2
                        # Use finite area even for point leaves
                        area = r.area if r.area > 0.0 else 0.0
                        return (tier, area, -r.depth)

                    best = min(containing, key=_contain_rank)
                    return SyncTeXLocation(
                        tex_path=self.input_files[best.tag],
                        line=best.line,
                        column=best.column,
                        page_index=p_idx,
                        bbox=(best.x0, best.y0, best.x1, best.y1),
                    )

                # 2. Nearest record on the same page (weight vertical distance higher than horizontal
                #    so margin clicks stay on the clicked visual line)
                def _dist_rank(r: SyncTeXRecord) -> Tuple[float, int, float]:
                    dx = 0.0 if r.x0 <= px <= r.x1 else min(abs(px - r.x0), abs(px - r.x1))
                    dy = 0.0 if r.y0 <= py <= r.y1 else min(abs(py - r.y0), abs(py - r.y1))
                    weighted_dist = math.hypot(dx, dy * 2.5)
                    tier = 0 if (r.kind in _LEAF_KINDS or r.kind in _HBOX_KINDS) else 1
                    return (weighted_dist, tier, r.area)

                nearest = min(valid, key=_dist_rank)
                return SyncTeXLocation(
                    tex_path=self.input_files[nearest.tag],
                    line=nearest.line,
                    column=nearest.column,
                    page_index=p_idx,
                    bbox=(nearest.x0, nearest.y0, nearest.x1, nearest.y1),
                )

        if self.use_cli_fallback and self.pdf_path and is_synctex_cli_available():
            return self._cli_backward_search(p_idx, px, py)

        return None

    def _cli_forward_search(
        self,
        tex_file: str,
        line: int,
        column: int = 0,
    ) -> List[SyncTeXHighlight]:
        """Run `synctex view -i <line>:<col>:<tex_file> -o <pdf_path>` as a CLI fallback."""
        if not self.pdf_path:
            return []
        try:
            proc = subprocess.run(
                ["synctex", "view", "-i", f"{line}:{column}:{tex_file}", "-o", self.pdf_path],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if proc.returncode != 0 or not proc.stdout:
                return []
            return self._parse_cli_view_output(proc.stdout, tex_path=tex_file, line=line, column=column)
        except (OSError, subprocess.SubprocessError):
            return []

    def _cli_backward_search(
        self,
        page_index: int,
        pdf_x: float,
        pdf_y: float,
    ) -> Optional[SyncTeXLocation]:
        """Run `synctex edit -o <page>:<x>:<y>:<pdf_path>` as a CLI fallback."""
        if not self.pdf_path:
            return None
        page_1based = max(1, int(page_index) + 1)
        try:
            proc = subprocess.run(
                ["synctex", "edit", "-o", f"{page_1based}:{pdf_x:.3f}:{pdf_y:.3f}:{self.pdf_path}"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if proc.returncode != 0 or not proc.stdout:
                return None
            return self._parse_cli_edit_output(proc.stdout, page_index=page_index)
        except (OSError, subprocess.SubprocessError):
            return None

    @staticmethod
    def _parse_cli_view_output(
        output: str,
        tex_path: str = "",
        line: int = 0,
        column: int = 0,
    ) -> List[SyncTeXHighlight]:
        """Parse stdout from `synctex view` into `SyncTeXHighlight` objects."""
        highlights: List[SyncTeXHighlight] = []
        in_result = False
        cur: Dict[str, float] = {}

        def _flush() -> None:
            if "Page" not in cur:
                return
            p_idx = max(0, int(cur["Page"]) - 1)
            h = cur.get("h", cur.get("x", 0.0))
            v = cur.get("v", cur.get("y", 0.0))
            w = cur.get("W", 0.0)
            ht = cur.get("H", 0.0)
            dp = cur.get("D", 0.0)
            x0 = h
            x1 = h + w if w > 0 else h + 24.0
            y0 = v - ht if ht > 0 else v - 10.0
            y1 = v + dp
            if y1 <= y0:
                y1 = y0 + 12.0
            highlights.append(
                SyncTeXHighlight(
                    page_index=p_idx,
                    x0=min(x0, x1),
                    y0=min(y0, y1),
                    x1=max(x0, x1),
                    y1=max(y0, y1),
                    tex_path=tex_path,
                    line=line,
                    column=column,
                )
            )

        for raw_line in output.splitlines():
            s = raw_line.strip()
            if s == "SyncTeX result begin":
                in_result = True
                continue
            if s == "SyncTeX result end":
                _flush()
                break
            if not in_result:
                continue
            if ":" not in s:
                continue
            key, val = s.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key == "Page":
                _flush()
                cur = {}
                try:
                    cur["Page"] = float(val)
                except ValueError:
                    pass
            elif key in ("x", "y", "h", "v", "W", "H", "D"):
                try:
                    cur[key] = float(val)
                except ValueError:
                    pass

        return _merge_line_highlights(highlights)

    @staticmethod
    def _parse_cli_edit_output(output: str, page_index: int = 0) -> Optional[SyncTeXLocation]:
        """Parse stdout from `synctex edit` into a `SyncTeXLocation`."""
        in_result = False
        tex_input = ""
        line_num = 0
        col_num = 0

        for raw_line in output.splitlines():
            s = raw_line.strip()
            if s == "SyncTeX result begin":
                in_result = True
                continue
            if s == "SyncTeX result end":
                break
            if not in_result or ":" not in s:
                continue
            key, val = s.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key == "Input" and not tex_input:
                tex_input = _normalize_fs_path(val)
            elif key == "Line" and not line_num:
                try:
                    line_num = int(val)
                except ValueError:
                    pass
            elif key == "Column":
                try:
                    col_num = max(0, int(val))
                except ValueError:
                    pass

        if tex_input and line_num > 0:
            return SyncTeXLocation(
                tex_path=tex_input,
                line=line_num,
                column=col_num,
                page_index=page_index,
            )
        return None
