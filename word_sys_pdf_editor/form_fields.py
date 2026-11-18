"""AcroForm field data model and Adobe XFA/XHTML Rich Text (/RV + /DS) parser and serializer."""

from __future__ import annotations

import copy
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .utils import normalize_color

# PDF ISO 32000-1 Table 228 — Field flags (/Ff) for text fields (1-indexed bit positions in spec)
FIELD_FLAG_READ_ONLY: int = 1 << 0        # Bit 1
FIELD_FLAG_REQUIRED: int = 1 << 1         # Bit 2
FIELD_FLAG_NO_EXPORT: int = 1 << 2        # Bit 3
FIELD_FLAG_MULTILINE: int = 1 << 12       # Bit 13 (4096)
FIELD_FLAG_PASSWORD: int = 1 << 13        # Bit 14 (8192)
FIELD_FLAG_FILE_SELECT: int = 1 << 20     # Bit 21
FIELD_FLAG_DO_NOT_SPELL_CHECK: int = 1 << 22  # Bit 23
FIELD_FLAG_DO_NOT_SCROLL: int = 1 << 23   # Bit 24
FIELD_FLAG_COMB: int = 1 << 24            # Bit 25 (16777216)
FIELD_FLAG_RICH_TEXT: int = 1 << 25       # Bit 26 (33554432)

XHTML_NS = "http://www.w3.org/1999/xhtml"
XFA_NS = "http://www.xfa.org/schema/xfa-data/1.0/"

_NAMED_CSS_COLORS: Dict[str, Tuple[float, float, float]] = {
    "black": (0.0, 0.0, 0.0),
    "white": (1.0, 1.0, 1.0),
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 0.5, 0.0),
    "lime": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "cyan": (0.0, 1.0, 1.0),
    "magenta": (1.0, 0.0, 1.0),
    "gray": (0.5, 0.5, 0.5),
    "grey": (0.5, 0.5, 0.5),
    "darkgray": (0.33, 0.33, 0.33),
    "darkgrey": (0.33, 0.33, 0.33),
    "lightgray": (0.83, 0.83, 0.83),
    "lightgrey": (0.83, 0.83, 0.83),
    "navy": (0.0, 0.0, 0.5),
    "maroon": (0.5, 0.0, 0.0),
    "purple": (0.5, 0.0, 0.5),
    "teal": (0.0, 0.5, 0.5),
    "olive": (0.5, 0.5, 0.0),
    "orange": (1.0, 0.65, 0.0),
    "brown": (0.65, 0.16, 0.16),
}


def color_tuple_to_hex(color: Optional[Sequence[float]], default: str = "#000000") -> str:
    """Convert an RGB tuple (0..1 floats or 0..255 ints) to a ``#rrggbb`` hex string."""
    if not color or len(color) < 3:
        return default
    norm = normalize_color(tuple(color[:3]))
    r = max(0, min(255, int(round(norm[0] * 255.0))))
    g = max(0, min(255, int(round(norm[1] * 255.0))))
    b = max(0, min(255, int(round(norm[2] * 255.0))))
    return f"#{r:02x}{g:02x}{b:02x}"


def parse_css_color(color_str: Optional[str]) -> Optional[Tuple[float, float, float]]:
    """Parse a CSS color value (``#rgb``, ``#rrggbb``, ``rgb(...)``, or named color) into normalized ``(r, g, b)``."""
    if not color_str:
        return None
    raw = str(color_str).strip().lower()
    if not raw or raw in ("inherit", "initial", "transparent", "none"):
        return None
    if raw in _NAMED_CSS_COLORS:
        return _NAMED_CSS_COLORS[raw]
    if raw.startswith("#"):
        hex_part = raw[1:].strip()
        if len(hex_part) == 3:
            try:
                r = int(hex_part[0] * 2, 16) / 255.0
                g = int(hex_part[1] * 2, 16) / 255.0
                b = int(hex_part[2] * 2, 16) / 255.0
                return (round(r, 4), round(g, 4), round(b, 4))
            except ValueError:
                return None
        if len(hex_part) >= 6:
            try:
                r = int(hex_part[0:2], 16) / 255.0
                g = int(hex_part[2:4], 16) / 255.0
                b = int(hex_part[4:6], 16) / 255.0
                return (round(r, 4), round(g, 4), round(b, 4))
            except ValueError:
                return None
    m_rgb = re.match(r"rgba?\(\s*([^)]+)\s*\)", raw)
    if m_rgb:
        parts = [p.strip() for p in m_rgb.group(1).split(",")]
        if len(parts) >= 3:
            try:
                vals: List[float] = []
                for p in parts[:3]:
                    if p.endswith("%"):
                        vals.append(max(0.0, min(1.0, float(p[:-1].strip()) / 100.0)))
                    else:
                        v = float(p)
                        vals.append(max(0.0, min(1.0, v / 255.0 if v > 1.0 else v)))
                return (round(vals[0], 4), round(vals[1], 4), round(vals[2], 4))
            except ValueError:
                return None
    return None


def _colors_equal(
    c1: Optional[Tuple[float, float, float]],
    c2: Optional[Tuple[float, float, float]],
    tol: float = 0.008,
) -> bool:
    if c1 is None and c2 is None:
        return True
    if c1 is None or c2 is None:
        return False
    n1 = normalize_color(c1)
    n2 = normalize_color(c2)
    return (
        abs(n1[0] - n2[0]) <= tol
        and abs(n1[1] - n2[1]) <= tol
        and abs(n1[2] - n2[2]) <= tol
    )


def _clean_font_family(raw_family: Optional[str], default: str = "Helvetica") -> str:
    if not raw_family:
        return default
    first = str(raw_family).split(",")[0].strip().strip("'\"")
    if not first or first.lower() in ("sans-serif", "serif", "monospace", "inherit"):
        return default
    return first


@dataclass
class RichTextRun:
    """Represents a contiguous styled span of text inside a Rich Text AcroForm field."""

    text: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    font_family: str = "Helvetica"
    font_size: Optional[float] = None
    color: Optional[Tuple[float, float, float]] = None

    def __post_init__(self):
        self.text = str(self.text or "")
        self.bold = bool(self.bold)
        self.italic = bool(self.italic)
        self.underline = bool(self.underline)
        self.strikethrough = bool(self.strikethrough)
        self.font_family = _clean_font_family(self.font_family, "Helvetica")
        if self.font_size is not None:
            try:
                fsize = float(self.font_size)
                self.font_size = round(fsize, 2) if fsize > 0 else None
            except (TypeError, ValueError):
                self.font_size = None
        if self.color is not None:
            if isinstance(self.color, str):
                self.color = parse_css_color(self.color)
            elif isinstance(self.color, (tuple, list)) and len(self.color) >= 3:
                norm = normalize_color(tuple(self.color[:3]))
                self.color = (round(norm[0], 4), round(norm[1], 4), round(norm[2], 4))
            else:
                self.color = None

    def same_style(self, other: "RichTextRun") -> bool:
        """Return True if this run and `other` share identical formatting properties."""
        if not isinstance(other, RichTextRun):
            return False
        size_same = (
            (self.font_size is None and other.font_size is None)
            or (
                self.font_size is not None
                and other.font_size is not None
                and abs(self.font_size - other.font_size) < 0.05
            )
        )
        return (
            self.bold == other.bold
            and self.italic == other.italic
            and self.underline == other.underline
            and self.strikethrough == other.strikethrough
            and self.font_family.lower() == other.font_family.lower()
            and size_same
            and _colors_equal(self.color, other.color)
        )

    def has_formatting(
        self,
        default_font: str = "Helvetica",
        default_size: Optional[float] = None,
        default_color: Optional[Tuple[float, float, float]] = (0.0, 0.0, 0.0),
    ) -> bool:
        """Return True if this run uses bold, italic, underline, strikethrough, or non-default font/size/color."""
        if self.bold or self.italic or self.underline or self.strikethrough:
            return True
        if default_font and self.font_family and self.font_family.lower() != _clean_font_family(default_font).lower():
            return True
        if (
            default_size is not None
            and default_size > 0
            and self.font_size is not None
            and abs(self.font_size - float(default_size)) >= 0.1
        ):
            return True
        if self.color is not None and default_color is not None and not _colors_equal(self.color, default_color):
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "strikethrough": self.strikethrough,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "color": list(self.color) if self.color is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RichTextRun":
        if isinstance(data, RichTextRun):
            return copy.deepcopy(data)
        col = data.get("color")
        return cls(
            text=data.get("text", ""),
            bold=bool(data.get("bold", False)),
            italic=bool(data.get("italic", False)),
            underline=bool(data.get("underline", False)),
            strikethrough=bool(data.get("strikethrough", False)),
            font_family=data.get("font_family", "Helvetica"),
            font_size=data.get("font_size"),
            color=tuple(col) if isinstance(col, (list, tuple)) and len(col) >= 3 else col,
        )


def coalesce_rich_text_runs(runs: Sequence[RichTextRun]) -> List[RichTextRun]:
    """Merge adjacent `RichTextRun` objects with identical styling and drop empty runs (unless single empty run)."""
    merged: List[RichTextRun] = []
    for run in runs or []:
        if not isinstance(run, RichTextRun):
            run = RichTextRun.from_dict(run) if isinstance(run, dict) else RichTextRun(text=str(run))
        if not run.text:
            continue
        if merged and merged[-1].same_style(run):
            merged[-1].text += run.text
        else:
            merged.append(copy.deepcopy(run))
    return merged


def _parse_css_declarations(style_str: str) -> Dict[str, str]:
    props: Dict[str, str] = {}
    if not style_str:
        return props
    for decl in str(style_str).split(";"):
        if ":" not in decl:
            continue
        k, v = decl.split(":", 1)
        key = k.strip().lower()
        val = v.strip()
        if key and val:
            props[key] = val
    return props


def _apply_css_to_style_state(style_str: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new style dictionary with CSS declarations from `style_str` applied over `state`."""
    new_state = dict(state)
    props = _parse_css_declarations(style_str)
    if not props:
        return new_state

    # Shorthand `font:` e.g. "font: italic bold 12.0pt 'Helvetica',sans-serif" or "font: Helvetica,sans-serif 12.0pt"
    if "font" in props:
        font_val = props["font"]
        low_font = font_val.lower()
        if re.search(r"\b(bold|700|800|900)\b", low_font):
            new_state["bold"] = True
        if re.search(r"\b(italic|oblique)\b", low_font):
            new_state["italic"] = True
        m_size = re.search(r"(\d+(?:\.\d+)?)\s*(?:pt|px|em)?", font_val, re.IGNORECASE)
        if m_size:
            try:
                new_state["font_size"] = float(m_size.group(1))
            except ValueError:
                pass
        # Remove size and style keywords to isolate font family
        fam_candidate = re.sub(
            r"\b(italic|oblique|bold|normal|regular|\d+(?:\.\d+)?\s*(?:pt|px|em)?)\b",
            " ",
            font_val,
            flags=re.IGNORECASE,
        ).strip()
        if fam_candidate:
            cleaned_fam = _clean_font_family(fam_candidate, default="")
            if cleaned_fam:
                new_state["font_family"] = cleaned_fam

    if "font-family" in props:
        cleaned_fam = _clean_font_family(props["font-family"], default="")
        if cleaned_fam:
            new_state["font_family"] = cleaned_fam

    if "font-size" in props:
        m_sz = re.search(r"(\d+(?:\.\d+)?)", props["font-size"])
        if m_sz:
            try:
                new_state["font_size"] = float(m_sz.group(1))
            except ValueError:
                pass

    if "font-weight" in props:
        fw = props["font-weight"].strip().lower()
        if fw in ("bold", "bolder", "600", "700", "800", "900"):
            new_state["bold"] = True
        elif fw in ("normal", "lighter", "400", "300"):
            new_state["bold"] = False

    if "font-style" in props:
        fs = props["font-style"].strip().lower()
        if fs in ("italic", "oblique"):
            new_state["italic"] = True
        elif fs == "normal":
            new_state["italic"] = False

    for td_key in ("text-decoration", "text-decoration-line"):
        if td_key in props:
            td = props[td_key].strip().lower()
            if "none" in td:
                new_state["underline"] = False
                new_state["strikethrough"] = False
            else:
                if "underline" in td:
                    new_state["underline"] = True
                if "line-through" in td or "strikethrough" in td:
                    new_state["strikethrough"] = True

    if "color" in props:
        parsed_col = parse_css_color(props["color"])
        if parsed_col is not None:
            new_state["color"] = parsed_col

    if "text-align" in props:
        ta = props["text-align"].strip().lower()
        align_map = {"left": 0, "center": 1, "right": 2, "justify": 3}
        if ta in align_map:
            new_state["align"] = align_map[ta]

    return new_state


def parse_default_style_css(default_style: str) -> Dict[str, Any]:
    """Parse an AcroForm `/DS` Default Style CSS string into style properties."""
    base: Dict[str, Any] = {
        "font_family": "Helvetica",
        "font_size": 12.0,
        "bold": False,
        "italic": False,
        "underline": False,
        "strikethrough": False,
        "color": (0.0, 0.0, 0.0),
        "align": 0,
    }
    if not default_style:
        return base
    return _apply_css_to_style_state(default_style, base)


def format_default_style_css(
    default_font: str = "Helvetica",
    default_size: float = 12.0,
    default_color: Optional[Tuple[float, float, float]] = (0.0, 0.0, 0.0),
    align: Union[int, str] = 0,
) -> str:
    """Format an Adobe Acrobat compliant `/DS` CSS string."""
    fam = _clean_font_family(default_font, "Helvetica")
    eff_size = float(default_size) if default_size and float(default_size) > 0 else 12.0
    hex_col = color_tuple_to_hex(default_color, default="#000000")
    if isinstance(align, str):
        align_str = align.strip().lower()
        if align_str not in ("left", "center", "right", "justify"):
            align_str = "left"
    else:
        align_str = {0: "left", 1: "center", 2: "right", 3: "justify"}.get(int(align or 0), "left")
    fam_css = f"'{fam}'" if " " in fam else fam
    return f"font: {fam_css},sans-serif {eff_size:.1f}pt; text-align:{align_str}; color:{hex_col}"


def _local_tag_name(tag: str) -> str:
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    if ":" in tag:
        return tag.split(":", 1)[1].lower()
    return tag.lower()


def parse_rv_xhtml_to_runs(rv_xhtml: str, default_style: str = "") -> List[RichTextRun]:
    """Parse an AcroForm `/RV` XHTML rich text string and optional `/DS` default style into `RichTextRun` spans."""
    if not rv_xhtml or not str(rv_xhtml).strip():
        return []

    raw = str(rv_xhtml).strip()
    ds_state = parse_default_style_css(default_style)

    # Wrap in a synthetic root if needed so fragments or multiple <p> elements parse cleanly
    xml_candidate = raw
    if not re.match(r"^\s*<(?:body|html|div)\b", xml_candidate, re.IGNORECASE):
        xml_candidate = f"<body>{xml_candidate}</body>"

    # Replace common HTML entities not predefined in XML
    xml_candidate = (
        xml_candidate.replace("&nbsp;", "\u00a0")
        .replace("<br>", "<br/>")
        .replace("<BR>", "<br/>")
    )

    try:
        root = ET.fromstring(xml_candidate)
    except ET.ParseError:
        # Fallback: strip malformed tags and return plain text run
        plain = html.unescape(re.sub(r"<[^>]+>", "", raw))
        if not plain:
            return []
        return [
            RichTextRun(
                text=plain,
                bold=ds_state["bold"],
                italic=ds_state["italic"],
                underline=ds_state["underline"],
                strikethrough=ds_state["strikethrough"],
                font_family=ds_state["font_family"],
                font_size=ds_state["font_size"],
                color=ds_state["color"],
            )
        ]

    runs: List[RichTextRun] = []

    def _emit_text(txt: Optional[str], st: Dict[str, Any]) -> None:
        if not txt:
            return
        runs.append(
            RichTextRun(
                text=txt,
                bold=bool(st.get("bold", False)),
                italic=bool(st.get("italic", False)),
                underline=bool(st.get("underline", False)),
                strikethrough=bool(st.get("strikethrough", False)),
                font_family=st.get("font_family", "Helvetica"),
                font_size=st.get("font_size"),
                color=st.get("color"),
            )
        )

    def _walk(elem: ET.Element, parent_state: Dict[str, Any]) -> None:
        tag = _local_tag_name(elem.tag)
        st = dict(parent_state)

        if tag in ("b", "strong"):
            st["bold"] = True
        elif tag in ("i", "em"):
            st["italic"] = True
        elif tag == "u":
            st["underline"] = True
        elif tag in ("s", "strike", "del"):
            st["strikethrough"] = True
        elif tag == "font":
            if elem.get("color"):
                c = parse_css_color(elem.get("color"))
                if c is not None:
                    st["color"] = c
            if elem.get("face"):
                st["font_family"] = _clean_font_family(elem.get("face"), st["font_family"])
            if elem.get("size"):
                m_sz = re.search(r"(\d+(?:\.\d+)?)", elem.get("size", ""))
                if m_sz:
                    try:
                        st["font_size"] = float(m_sz.group(1))
                    except ValueError:
                        pass

        style_attr = elem.get("style")
        if style_attr:
            st = _apply_css_to_style_state(style_attr, st)

        if tag == "br":
            _emit_text("\n", st)
            return

        if elem.text:
            _emit_text(elem.text, st)

        children = list(elem)
        for idx, child in enumerate(children):
            child_tag = _local_tag_name(child.tag)
            if child_tag in ("p", "div") and idx > 0:
                # Separate consecutive paragraph blocks with a newline
                if runs and not runs[-1].text.endswith("\n"):
                    _emit_text("\n", st)
            _walk(child, st)
            if child.tail:
                _emit_text(child.tail, st)

    _walk(root, ds_state)
    return coalesce_rich_text_runs(runs)


def serialize_runs_to_rv_xhtml(
    runs: Sequence[RichTextRun],
    default_font: str = "Helvetica",
    default_size: float = 12.0,
    default_color: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    align: Union[int, str] = 0,
) -> Tuple[str, str, str]:
    """Serialize `RichTextRun` spans into ``(plain_text_v, rv_xhtml, ds_style)`` per Adobe AcroForm Rich Text spec."""
    eff_font = _clean_font_family(default_font, "Helvetica")
    eff_size = float(default_size) if default_size and float(default_size) > 0 else 12.0
    eff_color = normalize_color(default_color) if default_color else (0.0, 0.0, 0.0)
    if isinstance(align, str):
        align_str = align.strip().lower()
        if align_str not in ("left", "center", "right", "justify"):
            align_str = "left"
    else:
        align_str = {0: "left", 1: "center", 2: "right", 3: "justify"}.get(int(align or 0), "left")

    ds_style = format_default_style_css(
        default_font=eff_font,
        default_size=eff_size,
        default_color=eff_color,
        align=align_str,
    )

    normalized_runs: List[RichTextRun] = []
    for r in runs or []:
        if isinstance(r, RichTextRun):
            normalized_runs.append(r)
        elif isinstance(r, dict):
            normalized_runs.append(RichTextRun.from_dict(r))
        else:
            normalized_runs.append(
                RichTextRun(
                    text=str(r),
                    font_family=eff_font,
                    font_size=eff_size,
                    color=eff_color,
                )
            )

    plain_text_v = "".join(r.text for r in normalized_runs)

    # Split runs into paragraphs separated by '\n'
    paragraphs: List[List[RichTextRun]] = [[]]
    for r in normalized_runs:
        parts = r.text.split("\n")
        for idx, part in enumerate(parts):
            if idx > 0:
                paragraphs.append([])
            if part:
                sub_run = copy.deepcopy(r)
                sub_run.text = part
                paragraphs[-1].append(sub_run)

    p_elements: List[str] = []
    for para_runs in paragraphs:
        if not para_runs:
            p_elements.append(
                f'<p dir="ltr" style="text-align:{align_str};margin-top:0pt;margin-bottom:0pt">&#160;</p>'
            )
            continue

        span_fragments: List[str] = []
        for r in para_runs:
            escaped_text = html.escape(r.text, quote=False)
            style_parts: List[str] = []

            r_fam = _clean_font_family(r.font_family, eff_font)
            if r_fam.lower() != eff_font.lower():
                fam_css = f"'{r_fam}'" if " " in r_fam else r_fam
                style_parts.append(f"font-family:{fam_css},sans-serif")

            if r.font_size is not None and r.font_size > 0 and abs(r.font_size - eff_size) >= 0.05:
                style_parts.append(f"font-size:{r.font_size:.1f}pt")

            if r.color is not None and not _colors_equal(r.color, eff_color):
                style_parts.append(f"color:{color_tuple_to_hex(r.color)}")

            if r.bold:
                style_parts.append("font-weight:bold")
            if r.italic:
                style_parts.append("font-style:italic")

            decorations: List[str] = []
            if r.underline:
                decorations.append("underline")
            if r.strikethrough:
                decorations.append("line-through")
            if decorations:
                style_parts.append(f"text-decoration:{' '.join(decorations)}")

            inner = escaped_text
            if r.underline:
                inner = f"<u>{inner}</u>"
            if r.strikethrough:
                inner = f"<s>{inner}</s>"
            if r.italic:
                inner = f"<i>{inner}</i>"
            if r.bold:
                inner = f"<b>{inner}</b>"

            if style_parts:
                inner = f'<span style="{";".join(style_parts)}">{inner}</span>'
            span_fragments.append(inner)

        p_elements.append(
            f'<p dir="ltr" style="text-align:{align_str};margin-top:0pt;margin-bottom:0pt">'
            f"{''.join(span_fragments)}</p>"
        )

    body_open = (
        f'<body xmlns="{XHTML_NS}" xmlns:xfa="{XFA_NS}" '
        f'xfa:APIVersion="Acroform:2.7.0.0" xfa:spec="2.1" '
        f'style="{ds_style}">'
    )
    rv_xhtml = f"{body_open}{''.join(p_elements)}</body>"
    return plain_text_v, rv_xhtml, ds_style


def runs_to_pango_markup(
    runs: Sequence[RichTextRun],
    default_font: str = "Helvetica",
    default_size: Optional[float] = None,
    default_color: Optional[Tuple[float, float, float]] = None,
) -> str:
    """Convert `RichTextRun` spans into Pango markup for Cairo/GTK canvas rendering."""
    if not runs:
        return ""
    fragments: List[str] = []
    for r in runs:
        if not r.text:
            continue
        escaped = html.escape(r.text, quote=True)
        span_attrs: List[str] = []
        if r.font_family and default_font and r.font_family.lower() != default_font.lower():
            span_attrs.append(f'face="{html.escape(r.font_family, quote=True)}"')
        if (
            r.font_size is not None
            and r.font_size > 0
            and (default_size is None or abs(r.font_size - default_size) >= 0.1)
        ):
            # Pango size attribute is in 1/1024ths of a point (Pango.SCALE = 1024)
            span_attrs.append(f'size="{int(round(r.font_size * 1024))}"')
        if r.color is not None and (default_color is None or not _colors_equal(r.color, default_color)):
            span_attrs.append(f'foreground="{color_tuple_to_hex(r.color)}"')

        inner = escaped
        if r.underline:
            inner = f"<u>{inner}</u>"
        if r.strikethrough:
            inner = f"<s>{inner}</s>"
        if r.italic:
            inner = f"<i>{inner}</i>"
        if r.bold:
            inner = f"<b>{inner}</b>"
        if span_attrs:
            inner = f"<span {' '.join(span_attrs)}>{inner}</span>"
        fragments.append(inner)
    return "".join(fragments)


@dataclass
class AcroFormField:
    """Data model representing an interactive AcroForm field with Rich Text (/RV + /DS) support."""

    FIELD_FLAG_RICH_TEXT = FIELD_FLAG_RICH_TEXT

    field_id: str
    xref: int
    page_number: int
    rect: Tuple[float, float, float, float]
    field_name: str
    field_label: str = ""
    field_type: str = "text"
    field_type_id: int = 0
    value: Any = ""
    default_value: Any = None
    choice_values: List[str] = field(default_factory=list)
    button_states: Optional[Dict[str, Any]] = None
    field_flags: int = 0
    is_read_only: bool = False
    is_required: bool = False
    is_no_export: bool = False
    is_multiline: bool = False
    is_password: bool = False
    is_comb: bool = False
    max_length: int = 0
    text_fontsize: float = 0.0
    text_color: Optional[Tuple[float, float, float]] = None
    fill_color: Optional[Tuple[float, float, float]] = None
    border_color: Optional[Tuple[float, float, float]] = None
    border_width: float = 1.0
    is_modified: bool = False
    text_align: int = 0
    font_family: str = "Helvetica"
    rich_text_enabled: bool = False
    rich_text_runs: List[RichTextRun] = field(default_factory=list)
    default_style: str = ""
    rv_xhtml: str = ""

    def __post_init__(self):
        if bool(self.field_flags & FIELD_FLAG_RICH_TEXT):
            self.rich_text_enabled = True
        if self.rich_text_enabled:
            self.field_flags = int(self.field_flags) | FIELD_FLAG_RICH_TEXT

        if self.rich_text_runs:
            normalized: List[RichTextRun] = []
            for r in self.rich_text_runs:
                if isinstance(r, RichTextRun):
                    normalized.append(r)
                elif isinstance(r, dict):
                    normalized.append(RichTextRun.from_dict(r))
            self.rich_text_runs = normalized
        elif self.rv_xhtml and str(self.rv_xhtml).strip():
            self.rich_text_runs = parse_rv_xhtml_to_runs(self.rv_xhtml, self.default_style)
            if self.rich_text_runs:
                self.rich_text_enabled = True
                self.field_flags = int(self.field_flags) | FIELD_FLAG_RICH_TEXT

        if self.default_style and not self.font_family:
            ds_info = parse_default_style_css(self.default_style)
            self.font_family = ds_info.get("font_family", "Helvetica")

    @property
    def x(self) -> float:
        return self.rect[0]

    @property
    def y(self) -> float:
        return self.rect[1]

    @property
    def width(self) -> float:
        return max(0.0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> float:
        return max(0.0, self.rect[3] - self.rect[1])

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return self.rect

    @property
    def is_checked(self) -> bool:
        if self.field_type in ("checkbox", "radio"):
            if isinstance(self.value, bool):
                return self.value
            val_str = str(self.value).strip().lower()
            return val_str not in ("off", "no", "false", "0", "", "none", "/off")
        return False

    def has_rich_formatting(self) -> bool:
        """Return True if any run in `rich_text_runs` has non-plain formatting."""
        eff_size = self.text_fontsize if self.text_fontsize and self.text_fontsize > 0 else 12.0
        eff_col = self.text_color if self.text_color is not None else (0.0, 0.0, 0.0)
        for r in self.rich_text_runs or []:
            if r.has_formatting(
                default_font=self.font_family or "Helvetica",
                default_size=eff_size,
                default_color=eff_col,
            ):
                return True
        return False

    def get_plain_text(self) -> str:
        """Return the plain-text string representation of this field's value."""
        if self.rich_text_runs:
            return "".join(r.text for r in self.rich_text_runs)
        return str(self.value or "")

    def set_value(self, new_val: Any):
        self.value = new_val
        if self.field_type == "text" and self.rich_text_enabled:
            eff_size = self.text_fontsize if self.text_fontsize and self.text_fontsize > 0 else 12.0
            eff_col = self.text_color if self.text_color is not None else (0.0, 0.0, 0.0)
            if not self.rich_text_runs or self.get_plain_text() != str(new_val or ""):
                if len(self.rich_text_runs) == 1:
                    base_run = copy.deepcopy(self.rich_text_runs[0])
                    base_run.text = str(new_val or "")
                    self.rich_text_runs = [base_run] if base_run.text else []
                else:
                    txt_val = str(new_val or "")
                    self.rich_text_runs = (
                        [
                            RichTextRun(
                                text=txt_val,
                                font_family=self.font_family or "Helvetica",
                                font_size=eff_size,
                                color=eff_col,
                            )
                        ]
                        if txt_val
                        else []
                    )
            plain_v, rv_str, ds_str = serialize_runs_to_rv_xhtml(
                self.rich_text_runs,
                default_font=self.font_family or "Helvetica",
                default_size=eff_size,
                default_color=eff_col,
                align=self.text_align,
            )
            self.value = plain_v
            self.rv_xhtml = rv_str
            if not self.default_style:
                self.default_style = ds_str
        self.is_modified = True

    def set_rich_text_runs(
        self,
        runs: Sequence[RichTextRun],
        auto_enable_rich_text: bool = True,
    ) -> None:
        """Update `rich_text_runs` and synchronize `value` (`/V`), `rv_xhtml` (`/RV`), and `default_style` (`/DS`)."""
        self.rich_text_runs = coalesce_rich_text_runs(runs)
        if auto_enable_rich_text and (self.rich_text_enabled or self.has_rich_formatting()):
            self.rich_text_enabled = True
            self.field_flags = int(self.field_flags) | FIELD_FLAG_RICH_TEXT

        eff_size = self.text_fontsize if self.text_fontsize and self.text_fontsize > 0 else 12.0
        eff_col = self.text_color if self.text_color is not None else (0.0, 0.0, 0.0)
        plain_v, rv_str, ds_str = serialize_runs_to_rv_xhtml(
            self.rich_text_runs,
            default_font=self.font_family or "Helvetica",
            default_size=eff_size,
            default_color=eff_col,
            align=self.text_align,
        )
        self.value = plain_v
        if self.rich_text_enabled or self.has_rich_formatting():
            self.rv_xhtml = rv_str
            self.default_style = ds_str
        else:
            self.rv_xhtml = ""
        self.is_modified = True

    def to_pango_markup(self) -> str:
        """Return Pango markup for rendering this field's text on a Cairo/Pango layout."""
        eff_size = self.text_fontsize if self.text_fontsize and self.text_fontsize > 0 else None
        eff_col = self.text_color if self.text_color is not None else (0.0, 0.0, 0.0)
        if self.rich_text_runs:
            return runs_to_pango_markup(
                self.rich_text_runs,
                default_font=self.font_family or "Helvetica",
                default_size=eff_size,
                default_color=eff_col,
            )
        return html.escape(str(self.value or ""), quote=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_id": self.field_id,
            "xref": self.xref,
            "page_number": self.page_number,
            "rect": self.rect,
            "field_name": self.field_name,
            "field_label": self.field_label,
            "field_type": self.field_type,
            "field_type_id": self.field_type_id,
            "value": self.value,
            "default_value": self.default_value,
            "choice_values": list(self.choice_values),
            "button_states": self.button_states,
            "field_flags": self.field_flags,
            "is_read_only": self.is_read_only,
            "is_required": self.is_required,
            "is_no_export": self.is_no_export,
            "is_multiline": self.is_multiline,
            "is_password": self.is_password,
            "is_comb": self.is_comb,
            "max_length": self.max_length,
            "text_fontsize": self.text_fontsize,
            "text_color": self.text_color,
            "fill_color": self.fill_color,
            "border_color": self.border_color,
            "border_width": self.border_width,
            "is_modified": self.is_modified,
            "text_align": self.text_align,
            "font_family": self.font_family,
            "rich_text_enabled": self.rich_text_enabled,
            "rich_text_runs": [r.to_dict() for r in self.rich_text_runs],
            "default_style": self.default_style,
            "rv_xhtml": self.rv_xhtml,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcroFormField":
        if isinstance(data, AcroFormField):
            return copy.deepcopy(data)
        runs_raw = data.get("rich_text_runs") or []
        runs = [RichTextRun.from_dict(r) for r in runs_raw]
        return cls(
            field_id=data.get("field_id", ""),
            xref=int(data.get("xref", 0) or 0),
            page_number=int(data.get("page_number", 0) or 0),
            rect=tuple(data.get("rect", (0.0, 0.0, 0.0, 0.0))),
            field_name=data.get("field_name", ""),
            field_label=data.get("field_label", ""),
            field_type=data.get("field_type", "text"),
            field_type_id=int(data.get("field_type_id", 0) or 0),
            value=data.get("value", ""),
            default_value=data.get("default_value"),
            choice_values=list(data.get("choice_values") or []),
            button_states=copy.deepcopy(data.get("button_states")),
            field_flags=int(data.get("field_flags", 0) or 0),
            is_read_only=bool(data.get("is_read_only", False)),
            is_required=bool(data.get("is_required", False)),
            is_no_export=bool(data.get("is_no_export", False)),
            is_multiline=bool(data.get("is_multiline", False)),
            is_password=bool(data.get("is_password", False)),
            is_comb=bool(data.get("is_comb", False)),
            max_length=int(data.get("max_length", 0) or 0),
            text_fontsize=float(data.get("text_fontsize", 0.0) or 0.0),
            text_color=tuple(data["text_color"]) if data.get("text_color") else None,
            fill_color=tuple(data["fill_color"]) if data.get("fill_color") else None,
            border_color=tuple(data["border_color"]) if data.get("border_color") else None,
            border_width=float(data.get("border_width", 1.0) or 1.0),
            is_modified=bool(data.get("is_modified", False)),
            text_align=int(data.get("text_align", 0) or 0),
            font_family=data.get("font_family", "Helvetica"),
            rich_text_enabled=bool(data.get("rich_text_enabled", False)),
            rich_text_runs=runs,
            default_style=data.get("default_style", ""),
            rv_xhtml=data.get("rv_xhtml", ""),
        )
