import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GObject, GdkPixbuf, Gio
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import os
import uuid
import math
import collections
from .utils import normalize_color
import re
import copy

FLAG_SUPERSCRIPT = 1       # bit 0
FLAG_ITALIC = 1 << 1       # bit 1
FLAG_SERIF = 1 << 2        # bit 2
FLAG_MONOSPACED = 1 << 3   # bit 3
FLAG_BOLD = 1 << 4         # bit 4

BASE14_FALLBACK_MAP = {
    'helvetica': 'helv', 'arial': 'helv', 'sans': 'helv', 'verdana': 'helv', 'tahoma': 'helv',
    'liberation sans': 'helv', 'liberationsans': 'helv', 'dejavusans': 'helv', 'notosans': 'helv',
    'carlito': 'helv', 'cantarell': 'helv', 'ubuntu': 'helv', 'aptos': 'helv', 'aptosdisplay': 'helv',
    'times': 'timr', 'timesnewroman': 'timr', 'serif': 'timr', 'georgia': 'timr',
    'liberation serif': 'timr', 'liberationserif': 'timr', 'dejavuserif': 'timr', 'notoserif': 'timr',
    'caladea': 'timr', 'roman': 'timr',
    'courier': 'cour', 'couriernew': 'cour', 'mono': 'cour', 'monospace': 'cour',
    'consolas': 'cour', 'liberation mono': 'cour', 'liberationmono': 'cour',
    'dejavusansmono': 'cour', 'notosansmono': 'cour', 'fixed': 'cour'
}


def get_base14_font_variant(base_code: str, is_bold: bool, is_italic: bool) -> str:
    """Get the standard Base14 font variant name."""
    mapping = {'helv': 'Helvetica', 'timr': 'Times', 'cour': 'Courier'}
    pdf_base = mapping.get(base_code, 'Helvetica')
    if is_bold and is_italic:
        if pdf_base == 'Helvetica': return 'Helvetica-BoldOblique'
        if pdf_base == 'Times': return 'Times-BoldItalic'
        if pdf_base == 'Courier': return 'Courier-BoldOblique'
    elif is_bold:
        if pdf_base == 'Helvetica': return 'Helvetica-Bold'
        if pdf_base == 'Times': return 'Times-Bold'
        if pdf_base == 'Courier': return 'Courier-Bold'
    elif is_italic:
        if pdf_base == 'Helvetica': return 'Helvetica-Oblique'
        if pdf_base == 'Times': return 'Times-Italic'
        if pdf_base == 'Courier': return 'Courier-Oblique'
    else:
        if pdf_base == 'Helvetica': return 'Helvetica'
        if pdf_base == 'Times': return 'Times-Roman'
        if pdf_base == 'Courier': return 'Courier'
    return pdf_base


def decompose_font_name(font_name: str, flags: int = 0) -> Dict[str, Any]:
    """Decompose a PDF font name and flags into constituent family, style, and Base14 properties.
    
    Handles subset prefixes (e.g. 'BAAAAA+LiberationSans-Bold'), PostScript suffixes
    (e.g. 'TimesNewRomanPSMT'), style indicators (Bold, Italic, Oblique, Kursiv),
    font flags, and matches to standard Base14 fonts and clean family names.
    """
    raw_name = font_name or "Helvetica"
    
    # 1. Detect and strip 6-letter subset prefix like 'ABCDEF+'
    subset_prefix = None
    name_clean = raw_name
    prefix_match = re.match(r'^([A-Z]{6}\+)(.*)$', raw_name)
    if prefix_match:
        subset_prefix = prefix_match.group(1)
        name_clean = prefix_match.group(2)
        
    if ',' in name_clean:
        name_clean = name_clean.split(',')[0]
        
    # 2. Check flags
    is_bold = bool(flags & FLAG_BOLD)
    is_italic = bool(flags & FLAG_ITALIC)
    is_serif = bool(flags & FLAG_SERIF)
    is_monospace = bool(flags & FLAG_MONOSPACED)
    
    # 3. Strip trailing PostScript identifiers
    potential_family_name = re.sub(r'[-_ ]?(PSMT|PS|MT)$', '', name_clean, flags=re.IGNORECASE).strip('-_ ')
    if not potential_family_name:
        potential_family_name = name_clean
        
    # 4. Detect style tokens
    style_patterns = [
        (r"(BoldItalic|BoldOblique|BdI|Z|BI)$", "BoldItalic"),
        (r"(Bold|Bd|Heavy|Black|DemiBold|SmBd|SemiBold)$", "Bold"),
        (r"(Italic|It|Oblique|Kursiv|I|Obl)$", "Italic"),
        (r"(Regular|Roman|Normal|Medium|Book|Rg|Text)$", "Regular")
    ]
    
    temp_name = potential_family_name
    for pattern, style_tag in style_patterns:
        m = re.search(r"([-_ ]?" + pattern + r")$", temp_name, re.IGNORECASE)
        if m:
            matched_str = m.group(0).lower()
            if "roman" in matched_str and ("times" in temp_name.lower()):
                pass
            else:
                if style_tag == "BoldItalic":
                    is_bold = True
                    is_italic = True
                elif style_tag == "Bold":
                    is_bold = True
                elif style_tag == "Italic":
                    is_italic = True
                temp_name = temp_name[:m.start()].strip("-_ ")
                
    cleaned_family_name = temp_name if temp_name else name_clean
    cleaned_family_name = re.sub(r'[-_ ]?(PSMT|PS|MT)$', '', cleaned_family_name, flags=re.IGNORECASE).strip('-_ ')
    
    cleaned_family_name_spaced = re.sub(r"(\w)([A-Z])", r"\1 \2", cleaned_family_name)
    base_name = ' '.join(word.capitalize() for word in cleaned_family_name_spaced.replace('-', ' ').replace('_', ' ').split())
    base_name = base_name.replace("Deja Vu", "DejaVu")
    
    if base_name in ("Times New", "Times"):
        base_name = "Times New Roman"
        
    lower_orig = raw_name.lower()
    if any(kw in lower_orig for kw in ('mono', 'typewriter', 'courier', 'console', 'consolas', 'fixed')):
        is_monospace = True
    if any(kw in lower_orig for kw in ('serif', 'times', 'roman', 'georgia', 'cambria', 'garamond', 'minion')):
        is_serif = True
        
    lower_base = base_name.lower().replace(" ", "")
    sans_aliases = ("arial", "helvetica", "calibri", "aptos", "aptosdisplay")
    serif_aliases = ("times", "timesnew", "timesnewroman")
    mono_aliases = ("courier", "couriernew")
    
    matched_family = base_name
    if lower_base in sans_aliases:
        matched_family = "Liberation Sans"
    elif lower_base in serif_aliases:
        matched_family = "Liberation Serif"
    elif lower_base in mono_aliases:
        matched_family = "Liberation Mono"
        
    if not matched_family or matched_family == "Unknown":
        matched_family = "Liberation Sans"
        
    normalized_for_base14 = re.sub(r'[^a-zA-Z0-9]', '', matched_family).lower()
    matched_base14 = None
    for name_key in sorted(BASE14_FALLBACK_MAP.keys(), key=len, reverse=True):
        if name_key.replace(" ", "") in normalized_for_base14:
            matched_base14 = BASE14_FALLBACK_MAP[name_key]
            break
            
    if not matched_base14:
        if is_monospace:
            matched_base14 = 'cour'
        elif is_serif:
            matched_base14 = 'timr'
        else:
            matched_base14 = 'helv'
            
    base14_code = matched_base14
    base14_name_map = {'helv': 'Helvetica', 'timr': 'Times', 'cour': 'Courier'}
    base14_name = base14_name_map.get(base14_code, 'Helvetica')
    base14_variant = get_base14_font_variant(base14_code, is_bold, is_italic)
    
    font_weight = 700 if is_bold else 400
    font_slant = "italic" if is_italic else "normal"
    
    return {
        "raw_name": raw_name,
        "subset_prefix": subset_prefix,
        "name_without_prefix": name_clean,
        "clean_family": cleaned_family_name,
        "clean_family_spaced": cleaned_family_name_spaced,
        "base_family": base_name,
        "matched_family": matched_family,
        "is_bold": is_bold,
        "is_italic": is_italic,
        "is_serif": is_serif,
        "is_monospace": is_monospace,
        "font_weight": font_weight,
        "font_slant": font_slant,
        "base14_code": base14_code,
        "base14_name": base14_name,
        "base14_variant": base14_variant
    }


def _measure_text_pango(text_str: str, font_family: str, font_size: float, is_bold: bool = False, is_italic: bool = False) -> float:
    """Measure exact rendered pixel width of a text string using Pango and Cairo."""
    if not text_str:
        return 0.0
    try:
        import cairo
        from gi.repository import Pango, PangoCairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        cr = cairo.Context(surf)
        layout = PangoCairo.create_layout(cr)
        font_desc_str = f"{font_family or 'Liberation Sans'} {font_size}"
        if is_bold:
            font_desc_str += " Bold"
        if is_italic:
            font_desc_str += " Italic"
        fd = Pango.FontDescription.from_string(font_desc_str)
        fd.set_absolute_size(int(font_size * Pango.SCALE))
        layout.set_font_description(fd)
        layout.set_text(text_str, -1)
        pw, _ = layout.get_pixel_size()
        return max(1.0, float(pw))
    except Exception:
        return max(1.0, len(text_str) * font_size * 0.55)


def measure_text_width(
    text_str: str,
    font_family: str,
    font_size: float,
    is_bold: bool = False,
    is_italic: bool = False,
    text_obj: Optional['EditableText'] = None
) -> float:
    """Measure exact sub-pixel rendered width of text matching PDF page stream insertion."""
    if not text_str:
        return 0.0
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        from . import pdf_handler
        base_family = font_family or (text_obj.font_family_base if text_obj else "Liberation Sans")
        font_to_embed = pdf_handler.find_specific_font_variant(base_family, is_bold, is_italic)
        if font_to_embed:
            try:
                f = fitz.Font(fontfile=font_to_embed)
                return max(0.5, float(f.text_length(text_str, fontsize=font_size)))
            except Exception:
                pass

        base_name = getattr(text_obj, 'pdf_fontname_base14', 'helv') if text_obj else 'helv'
        calc_font = pdf_handler._get_base14_font_variant(base_name, is_bold, is_italic)
        return max(0.5, float(fitz.get_text_length(text_str, fontname=calc_font, fontsize=font_size)))
    except Exception:
        pass

    try:
        return _measure_text_pango(text_str, font_family, font_size, is_bold, is_italic)
    except Exception:
        return max(0.5, len(text_str) * font_size * 0.55)


def extract_font_properties(font_name: str, flags: int = 0) -> Dict[str, Any]:
    """Extract and decompose font properties from a PDF font name and flags."""
    return decompose_font_name(font_name, flags)


class EditableText:
    """Data model representing extracted or newly added editable text on a PDF page."""
    def __init__(self, x, y, text, font_size=11, font_family="Liberation Sans",
                 color=(0, 0, 0), span_data=None, is_new=False, baseline=None, rotation=0.0, page_number=None, alignment="left", link_url=None):
        self.x = x
        self.y = y
        self.text = text
        self.original_text = text if not is_new else ""
        self.font_size = float(font_size)
        self.is_new = is_new
        self.rotation = float(rotation) % 360.0
        self.original_rotation = self.rotation
        self.link_url = link_url
        self.original_link_url = link_url

        self.original_bbox = span_data.get("bbox") if span_data else None

        pdf_font_name_original = font_family or "Liberation Sans"
        flags = 0
        
        if span_data:
            pdf_font_name_original = span_data.get('font', pdf_font_name_original)
            flags = span_data.get('flags', 0)

        font_info = decompose_font_name(pdf_font_name_original, flags)
        self.font_properties = font_info
        self.font_family_original = font_info["raw_name"]
        self.is_bold = font_info["is_bold"]
        self.is_italic = font_info["is_italic"]
        self.is_serif = font_info["is_serif"]
        self.is_monospace = font_info["is_monospace"]
        self.is_underline = False
        self.is_strikethrough = False
        self.alignment = alignment or "left"
        self.font_family_base = font_info["matched_family"]
        self.pdf_fontname_base14 = font_info["base14_code"]
        self.font_fallback_used = False
        self.original_is_bold = self.is_bold
        self.original_is_italic = self.is_italic

        pdf_color = color
        if span_data and 'color' in span_data:
            pdf_color = span_data['color']

        self.color = normalize_color(pdf_color)
        self.original_color = self.color

        self.selected = False
        self.editing = False
        self.span_data = span_data
        self.modified = is_new 
        self.char_boxes: List[Dict[str, Any]] = []

        if span_data and "bbox" in span_data:
            self.bbox = span_data["bbox"]
        else: 
            estimated_width = len(self.text) * self.font_size * 0.6 
            self.bbox = (self.x, self.y, self.x + estimated_width, self.y + self.font_size)

        if baseline is not None:
            self.baseline = float(baseline)
        elif span_data and "origin" in span_data:
            self.baseline = float(span_data["origin"][1])
        elif self.bbox: 
            self.baseline = float(self.bbox[3] - (self.font_size * 0.1)) 
        else: 
            self.baseline = float(self.y + (self.font_size * 0.9))

        self.original_baseline = self.baseline
        self.page_number = page_number
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        
        self.text_spans = []
        self.linked_patch = None
        
    def set_rotation(self, angle):
        """Set rotation in degrees (0-360)."""
        self.rotation = float(angle) % 360.0

    def sync_char_boxes_to_bbox(self):
        """Synchronize character bounding boxes with self.bbox if the object has moved."""
        if not self.char_boxes or not self.bbox:
            return
        cb_min_x = min(cb["bbox"][0] for cb in self.char_boxes)
        cb_min_y = min(cb["bbox"][1] for cb in self.char_boxes)
        dx = self.bbox[0] - cb_min_x
        dy = self.bbox[1] - cb_min_y
        if abs(dx) > 1e-4 or abs(dy) > 1e-4:
            for cb in self.char_boxes:
                b = cb["bbox"]
                cb["bbox"] = (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)
                if "visual_bbox" in cb:
                    vb = cb["visual_bbox"]
                    cb["visual_bbox"] = (vb[0] + dx, vb[1] + dy, vb[2] + dx, vb[3] + dy)
                if "origin" in cb:
                    orig = cb["origin"]
                    cb["origin"] = (orig[0] + dx, orig[1] + dy)

    def compensate_for_rotation(self, parent_center: Tuple[float, float], parent_rotation: float):
        """Compensate bounding box and character boxes so span rotates around its own center
        while aligning exactly with the parent rotated text."""
        rot = float(parent_rotation) % 360.0
        if rot == 0.0 or not self.bbox:
            return
        sc_x = (self.bbox[0] + self.bbox[2]) / 2.0
        sc_y = (self.bbox[1] + self.bbox[3]) / 2.0
        dc_x = parent_center[0] - sc_x
        dc_y = parent_center[1] - sc_y
        rad = math.radians(rot)
        rdx = dc_x * math.cos(rad) - dc_y * math.sin(rad)
        rdy = dc_x * math.sin(rad) + dc_y * math.cos(rad)
        sh_x = dc_x - rdx
        sh_y = dc_y - rdy

        if abs(sh_x) > 1e-4 or abs(sh_y) > 1e-4:
            self.bbox = (self.bbox[0] + sh_x, self.bbox[1] + sh_y, self.bbox[2] + sh_x, self.bbox[3] + sh_y)
            self.original_bbox = self.bbox
            self.x = self.bbox[0]
            self.y = self.bbox[1]
            if hasattr(self, 'baseline') and self.baseline is not None:
                self.baseline += sh_y
                self.original_baseline = self.baseline
            if self.char_boxes:
                for cb in self.char_boxes:
                    b = cb["bbox"]
                    cb["bbox"] = (b[0] + sh_x, b[1] + sh_y, b[2] + sh_x, b[3] + sh_y)
                    if "visual_bbox" in cb:
                        vb = cb["visual_bbox"]
                        cb["visual_bbox"] = (vb[0] + sh_x, vb[1] + sh_y, vb[2] + sh_x, vb[3] + sh_y)
                    if "origin" in cb:
                        orig = cb["origin"]
                        cb["origin"] = (orig[0] + sh_x, orig[1] + sh_y)

    def hit_test_char(self, x: float, y: float, tolerance: float = 2.0) -> Optional[Dict[str, Any]]:
        """Hit-test a point against the character bounding boxes in this EditableText object.
        
        Returns the closest matching character dict with keys 'char', 'bbox', 'origin', 'index'
        if within tolerance, else None.
        """
        self.sync_char_boxes_to_bbox()
        if not self.char_boxes:
            return None
            
        rot = getattr(self, 'rotation', 0.0) % 360.0
        px, py = x, y
        if rot != 0.0 and self.bbox:
            cx = (self.bbox[0] + self.bbox[2]) / 2.0
            cy = (self.bbox[1] + self.bbox[3]) / 2.0
            rad = math.radians(-rot)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            px = cx + (x - cx) * cos_a - (y - cy) * sin_a
            py = cy + (x - cx) * sin_a + (y - cy) * cos_a
            
        candidates = []
        for idx, cb in enumerate(self.char_boxes):
            bbox = cb["bbox"]
            if (bbox[0] - tolerance) <= px <= (bbox[2] + tolerance) and \
               (bbox[1] - tolerance) <= py <= (bbox[3] + tolerance):
                cx_c = (bbox[0] + bbox[2]) / 2.0
                cy_c = (bbox[1] + bbox[3]) / 2.0
                dist_sq = (px - cx_c) ** 2 + (py - cy_c) ** 2
                candidates.append((dist_sq, idx, cb))
                
        if not candidates:
            return None
            
        candidates.sort(key=lambda item: item[0])
        best_idx, best_box = candidates[0][1], candidates[0][2]
        res = dict(best_box)
        res["index"] = best_idx
        return res

    def get_caret_index_at_pos(self, x: float, y: Optional[float] = None) -> int:
        """Find the nearest caret insertion index (0 to len(text)) for a given x coordinate."""
        self.sync_char_boxes_to_bbox()
        if not self.text:
            return 0
        rot = getattr(self, 'rotation', 0.0) % 360.0
        if rot != 0.0 and self.bbox and y is not None:
            cx = (self.bbox[0] + self.bbox[2]) / 2.0
            cy = (self.bbox[1] + self.bbox[3]) / 2.0
            rad = math.radians(-rot)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            x = cx + (x - cx) * cos_a - (y - cy) * sin_a
        if not self.char_boxes:
            if not self.bbox or (self.bbox[2] - self.bbox[0]) <= 0:
                return len(self.text)
            ratio = (x - self.bbox[0]) / (self.bbox[2] - self.bbox[0])
            idx = int(round(ratio * len(self.text)))
            return max(0, min(idx, len(self.text)))
            
        first_box = self.char_boxes[0]["bbox"]
        if x <= first_box[0]:
            return 0
            
        last_box = self.char_boxes[-1]["bbox"]
        if x >= last_box[2]:
            return len(self.char_boxes)
            
        for idx, cb in enumerate(self.char_boxes):
            bbox = cb["bbox"]
            mid_x = (bbox[0] + bbox[2]) / 2.0
            if x < mid_x:
                return idx
            elif x <= bbox[2]:
                return idx + 1
                
        return len(self.char_boxes)

    @property
    def width(self) -> float:
        """Return the bounding box width."""
        if self.bbox and len(self.bbox) >= 4:
            return max(0.0, float(self.bbox[2] - self.bbox[0]))
        return 0.0

    @width.setter
    def width(self, val: float):
        """Set the bounding box width."""
        val = max(0.0, float(val))
        if self.bbox and len(self.bbox) >= 4:
            self.bbox = (self.bbox[0], self.bbox[1], self.bbox[0] + val, self.bbox[3])
        else:
            self.bbox = (self.x, self.y, self.x + val, self.y + self.font_size)

    @property
    def height(self) -> float:
        """Return the bounding box height."""
        if self.bbox and len(self.bbox) >= 4:
            return max(0.0, float(self.bbox[3] - self.bbox[1]))
        return 0.0

    @height.setter
    def height(self, val: float):
        """Set the bounding box height."""
        val = max(0.0, float(val))
        if self.bbox and len(self.bbox) >= 4:
            self.bbox = (self.bbox[0], self.bbox[1], self.bbox[2], self.bbox[1] + val)
        else:
            self.bbox = (self.x, self.y, self.x + len(self.text) * self.font_size * 0.6, self.y + val)

    @property
    def is_link(self):
        """Return True if text has a link URL or contains a web URL."""
        return bool(self.link_url or (self.text and re.search(r'https?://', self.text)))

    def get_link_url(self) -> Optional[str]:
        """Return effective link URL (explicit link_url or URL matched in text)."""
        if self.link_url:
            return self.link_url
        if self.text:
            match = re.search(r'https?://[^\s]+', self.text)
            if match:
                return match.group(0)
        return None

    def split_at_range(self, start_char: int, end_char: int, compensate_rotation: bool = True) -> List['EditableText']:
        """Split text into segments before, inside, and after a character selection range.
        
        Calculates sub-pixel accurate bounding boxes using exact char_boxes when available,
        or Pango layout font metrics as fallback.
        """
        self.sync_char_boxes_to_bbox()
        text = self.text
        if start_char < 0:
            start_char = 0
        if end_char > len(text):
            end_char = len(text)
        if start_char >= end_char:
            return [self]

        parts = []
        has_cbs = bool(self.char_boxes and len(self.char_boxes) >= len(text))

        def _make_part(p_text: str, p_cbs: List[Dict[str, Any]], fallback_x0: float, fallback_w: float) -> 'EditableText':
            part = copy.deepcopy(self)
            part.text = p_text
            part.original_text = p_text
            part.is_new = True
            part.is_baked = True
            part.page_number = getattr(self, 'page_number', None)
            part.original_rotation = getattr(self, 'rotation', 0.0)
            part.char_boxes = [dict(cb) for cb in p_cbs]
            for idx, cb in enumerate(part.char_boxes):
                cb["index"] = idx

            y0 = self.bbox[1] if self.bbox else self.y
            y1 = self.bbox[3] if self.bbox else (self.y + self.font_size)

            if part.char_boxes:
                bx0 = min(cb["bbox"][0] for cb in part.char_boxes)
                by0 = min(cb["bbox"][1] for cb in part.char_boxes)
                bx1 = max(cb["bbox"][2] for cb in part.char_boxes)
                by1 = max(cb["bbox"][3] for cb in part.char_boxes)
                part.bbox = (bx0, by0, bx1, by1)
            else:
                part.bbox = (fallback_x0, y0, fallback_x0 + fallback_w, y1)

            part.original_bbox = part.bbox
            part.x, part.y = part.bbox[0], part.bbox[1]
            return part

        orig_x0 = self.bbox[0] if self.bbox else self.x
        pre_w = measure_text_width(text[:start_char], self.font_family_base, self.font_size, self.is_bold, self.is_italic, self) if start_char > 0 else 0.0
        mid_w = measure_text_width(text[start_char:end_char], self.font_family_base, self.font_size, self.is_bold, self.is_italic, self)
        post_w = measure_text_width(text[end_char:], self.font_family_base, self.font_size, self.is_bold, self.is_italic, self) if end_char < len(text) else 0.0

        if start_char > 0:
            cbs = self.char_boxes[:start_char] if has_cbs else []
            pre = _make_part(text[:start_char], cbs, orig_x0, pre_w)
            parts.append(pre)

        mid_cbs = self.char_boxes[start_char:end_char] if has_cbs else []
        mid_x0 = orig_x0 + pre_w if not has_cbs else (min(cb["bbox"][0] for cb in mid_cbs) if mid_cbs else orig_x0)
        mid = _make_part(text[start_char:end_char], mid_cbs, mid_x0, mid_w)
        parts.append(mid)

        if end_char < len(text):
            post_cbs = self.char_boxes[end_char:] if has_cbs else []
            post_x0 = orig_x0 + pre_w + mid_w if not has_cbs else (min(cb["bbox"][0] for cb in post_cbs) if post_cbs else orig_x0 + mid_w)
            post = _make_part(text[end_char:], post_cbs, post_x0, post_w)
            parts.append(post)

        rot = getattr(self, 'rotation', 0.0) % 360.0
        if compensate_rotation and rot != 0.0 and self.bbox:
            p_cx = (self.bbox[0] + self.bbox[2]) / 2.0
            p_cy = (self.bbox[1] + self.bbox[3]) / 2.0
            for part in parts:
                part.compensate_for_rotation((p_cx, p_cy), rot)

        return parts

class EditableImage:
    """Data model representing an extracted or inserted image, rubber stamp, or texture clone patch on a PDF page."""
    def __init__(self, bbox, page_number, xref, image_bytes, is_new=False, rotation=0.0,
                 opacity=1.0, is_stamp=False, stamp_name=None, is_patch=False):
        self.bbox = bbox
        self.original_bbox = bbox
        self.x = bbox[0] if bbox else 0.0
        self.y = bbox[1] if bbox else 0.0
        self.page_number = page_number
        self.xref = xref
        self.image_bytes = image_bytes
        self.is_new = is_new
        self.selected = False
        self.modified = False
        self.rotation = float(rotation) % 360.0
        self.original_rotation = self.rotation
        self.opacity = float(opacity)
        self.is_stamp = bool(is_stamp)
        self.stamp_name = stamp_name
        self.is_patch = bool(is_patch)

    def set_rotation(self, angle):
        """Set rotation in degrees (0-360)."""
        self.rotation = float(angle) % 360.0

class PatchObject(EditableImage):
    """Specialized EditableImage representing a background texture clone patch."""
    def __init__(self, bbox, page_number, image_bytes, is_new=True, rotation=0.0, opacity=1.0, purge_underlying_text=True):
        super().__init__(
            bbox=bbox,
            page_number=page_number,
            xref=None,
            image_bytes=image_bytes,
            is_new=is_new,
            rotation=rotation,
            opacity=opacity,
            is_stamp=False,
            is_patch=True
        )
        self.linked_text = None
        self.purge_underlying_text = bool(purge_underlying_text)

class EditableShape:
    """Data model representing vector shapes such as rectangle, ellipse, checkmark, cross."""
    SHAPE_RECTANGLE = "rectangle"
    SHAPE_ELLIPSE = "ellipse"
    SHAPE_POLYGON = "polygon"
    SHAPE_CHECKMARK = "checkmark"
    SHAPE_CROSS = "cross"
    
    def __init__(self, shape_type, bbox, fill_color=(255, 255, 255), 
                 stroke_color=(0, 0, 0), stroke_width=2.0, page_number=None, is_new=False, is_transparent=True, rotation=0.0):
        self.shape_type = shape_type
        self.bbox = bbox
        self.original_bbox = bbox
        
        self.fill_color = normalize_color(fill_color)
        self.stroke_color = normalize_color(stroke_color)
        self.original_fill_color = self.fill_color
        self.original_stroke_color = self.stroke_color
        
        self.stroke_width = float(stroke_width)
        self.original_stroke_width = self.stroke_width
        self.is_transparent = is_transparent
        self.rotation = float(rotation) % 360.0
        self.original_rotation = self.rotation
        
        self.page_number = page_number
        self.is_new = is_new
        self.selected = False
        self.modified = is_new
        
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        
        self.x = bbox[0]
        self.y = bbox[1]
    
    def get_width(self):
        """Get the width."""
        return self.bbox[2] - self.bbox[0]
    
    def get_height(self):
        """Get the height."""
        return self.bbox[3] - self.bbox[1]
    
    def set_size(self, width, height):
        """Set the size."""
        x1, y1, _, _ = self.bbox
        self.bbox = (x1, y1, x1 + width, y1 + height)
    
    def set_position(self, x, y):
        """Set the position."""
        width = self.get_width()
        height = self.get_height()
        self.bbox = (x, y, x + width, y + height)
        self.x = x
        self.y = y

    def set_rotation(self, angle):
        """Set rotation in degrees (0-360)."""
        self.rotation = float(angle) % 360.0

    def get_checkmark_points(self):
        """Calculate vector vertex points for checkmark shape within its bounding box."""
        x1, y1, x2, y2 = self.bbox
        w = max(x2 - x1, 1.0)
        h = max(y2 - y1, 1.0)
        return [
            (x1 + 0.15 * w, y1 + 0.50 * h),
            (x1 + 0.38 * w, y1 + 0.85 * h),
            (x1 + 0.85 * w, y1 + 0.18 * h)
        ]

    def get_cross_lines(self):
        """Calculate vector line segments for cross shape within its bounding box."""
        x1, y1, x2, y2 = self.bbox
        w = max(x2 - x1, 1.0)
        h = max(y2 - y1, 1.0)
        return [
            ((x1 + 0.18 * w, y1 + 0.18 * h), (x2 - 0.18 * w, y2 - 0.18 * h)),
            ((x2 - 0.18 * w, y1 + 0.18 * h), (x1 + 0.18 * w, y2 - 0.18 * h))
        ]

class EditableStroke:
    """Data model representing freehand pen and highlighter vector drawings."""
    TOOL_PEN = "pen"
    TOOL_HIGHLIGHTER = "highlighter"

    def __init__(self, points=None, stroke_color=(0, 0, 0), stroke_width=2.0,
                 opacity=1.0, tool_type="pen", page_number=None, is_new=True, rotation=0.0):
        self.points = list(points) if points else []
        self.stroke_color = normalize_color(stroke_color)
        self.original_stroke_color = self.stroke_color
        self.stroke_width = float(stroke_width)
        self.original_stroke_width = self.stroke_width
        self.opacity = float(opacity)
        self.tool_type = tool_type
        self.page_number = page_number
        self.is_new = is_new
        self.selected = False
        self.modified = is_new
        self.rotation = float(rotation) % 360.0
        self.original_rotation = self.rotation
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.x = 0
        self.y = 0
        self.bbox = (0, 0, 0, 0)
        self.original_bbox = (0, 0, 0, 0)
        if self.points:
            self.recalculate_bbox()

    def add_point(self, x, y):
        """Add point to stroke and recalculate bbox."""
        self.points.append((float(x), float(y)))
        self.recalculate_bbox()

    def recalculate_bbox(self):
        """Recalculate bounding box from points with stroke width padding."""
        if not self.points:
            self.bbox = (0, 0, 0, 0)
            self.original_bbox = self.bbox
            self.x, self.y = 0, 0
            return
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        pad = max(self.stroke_width / 2.0, 2.0)
        min_x, max_x = min(xs) - pad, max(xs) + pad
        min_y, max_y = min(ys) - pad, max(ys) + pad
        self.bbox = (min_x, min_y, max_x, max_y)
        self.original_bbox = self.bbox
        self.x = min_x
        self.y = min_y

    def get_width(self):
        """Get the width."""
        return self.bbox[2] - self.bbox[0]

    def get_height(self):
        """Get the height."""
        return self.bbox[3] - self.bbox[1]

    def scale_to_bbox(self, new_bbox, orig_bbox, orig_points=None):
        """Scale stroke points proportionally to match new bounding box."""
        if not self.points:
            self.bbox = new_bbox
            self.x, self.y = new_bbox[0], new_bbox[1]
            return
        pts_to_scale = orig_points if orig_points else self.points
        ox1, oy1, ox2, oy2 = orig_bbox
        nx1, ny1, nx2, ny2 = new_bbox
        ow = max(ox2 - ox1, 1e-3)
        oh = max(oy2 - oy1, 1e-3)
        nw = max(nx2 - nx1, 1e-3)
        nh = max(ny2 - ny1, 1e-3)
        new_pts = []
        for px, py in pts_to_scale:
            rx = (px - ox1) / ow
            ry = (py - oy1) / oh
            new_pts.append((nx1 + rx * nw, ny1 + ry * nh))
        self.points = new_pts
        self.recalculate_bbox()
        self.bbox = new_bbox
        self.x = new_bbox[0]
        self.y = new_bbox[1]

    def set_position(self, new_x, new_y):
        """Shift all points to a new (x, y) origin."""
        dx = new_x - self.x
        dy = new_y - self.y
        self.points = [(px + dx, py + dy) for px, py in self.points]
        self.recalculate_bbox()

    def set_rotation(self, angle):
        """Set rotation in degrees (0-360)."""
        self.rotation = float(angle) % 360.0


class MeasurementObject:
    """Data model representing a linear distance or polygon area measurement on a PDF page."""
    TYPE_DISTANCE = "distance"
    TYPE_AREA = "area"

    def __init__(self, measurement_type: str, points: List[Tuple[float, float]],
                 page_number: int, color: Tuple[float, float, float] = (0.0, 0.55, 0.95),
                 fill_color: Tuple[float, float, float, float] = (0.0, 0.55, 0.95, 0.22),
                 stroke_width: float = 1.5, unit: Optional[str] = None,
                 is_new: bool = True, rotation: float = 0.0,
                 label: Optional[str] = None):
        self.measurement_type = measurement_type  # "distance" or "area"
        self.points = [tuple(p) for p in points]
        self.page_number = page_number
        self.color = normalize_color(color)
        self.fill_color = fill_color
        self.stroke_width = float(stroke_width)
        self.unit = unit
        self.is_new = is_new
        self.selected = False
        self.modified = is_new
        self.rotation = float(rotation) % 360.0
        self.label = label
        self.original_points = list(self.points)
        self.recalculate_bbox()

    def recalculate_bbox(self):
        """Update bounding box covering vertices, leader lines, and badge margin."""
        if not self.points:
            self.bbox = (0.0, 0.0, 0.0, 0.0)
            self.x, self.y = 0.0, 0.0
            return
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        pad = max(self.stroke_width * 2.0, 16.0)
        self.bbox = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
        self.x, self.y = self.bbox[0], self.bbox[1]

    def calculate_length(self) -> float:
        """Calculate linear distance in points between the first two vertices."""
        if len(self.points) < 2:
            return 0.0
        p0, p1 = self.points[0], self.points[1]
        return math.hypot(p1[0] - p0[0], p1[1] - p0[1])

    def compute_raw_value(self) -> float:
        """Return length or area in points depending on measurement type."""
        if self.measurement_type == self.TYPE_DISTANCE:
            return self.calculate_length()
        return self.calculate_area()

    def calculate_perimeter(self) -> float:
        """Calculate polygon perimeter in points."""
        if len(self.points) < 2:
            return 0.0
        total = 0.0
        n = len(self.points)
        for i in range(n):
            p0 = self.points[i]
            p1 = self.points[(i + 1) % n]
            total += math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        return total

    def calculate_area(self) -> float:
        """Calculate polygon area in points squared using the Shoelace formula."""
        if len(self.points) < 3:
            return 0.0
        area = 0.0
        n = len(self.points)
        for i in range(n):
            j = (i + 1) % n
            area += self.points[i][0] * self.points[j][1]
            area -= self.points[j][0] * self.points[i][1]
        return abs(area) / 2.0

    def get_centroid(self) -> Tuple[float, float]:
        """Calculate center point for readout pill placement."""
        if not self.points:
            return (0.0, 0.0)
        if self.measurement_type == self.TYPE_DISTANCE or len(self.points) == 2:
            p0, p1 = self.points[0], self.points[1]
            return ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def format_measurement(self, scale_calib: Optional['ScaleCalibration'] = None) -> str:
        """Return formatted measurement string based on active scale calibration."""
        if self.label:
            return self.label
        if self.measurement_type == self.TYPE_DISTANCE:
            pt_len = self.calculate_length()
            if scale_calib and scale_calib.points_per_unit > 0:
                return scale_calib.format_distance(pt_len)
            else:
                mm_len = (pt_len * 25.4) / 72.0
                return f"{pt_len:.1f} pt ({mm_len:.1f} mm)"
        else:
            pt_area = self.calculate_area()
            if scale_calib and scale_calib.points_per_unit > 0:
                return scale_calib.format_area(pt_area)
            else:
                return f"{pt_area:.1f} pt²"

    def set_position(self, new_x, new_y):
        """Translate all vertices by (dx, dy)."""
        dx = new_x - self.x
        dy = new_y - self.y
        self.points = [(px + dx, py + dy) for px, py in self.points]
        self.recalculate_bbox()

    def to_dict(self) -> dict:
        return {
            "type": self.measurement_type,
            "points": self.points,
            "page_number": self.page_number,
            "color": self.color,
            "fill_color": self.fill_color,
            "stroke_width": self.stroke_width,
            "unit": self.unit,
            "rotation": self.rotation,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'MeasurementObject':
        return cls(
            measurement_type=data.get("type", cls.TYPE_DISTANCE),
            points=[tuple(p) for p in data.get("points", [])],
            page_number=data.get("page_number", 0),
            color=tuple(data.get("color", (0.0, 0.55, 0.95))),
            fill_color=tuple(data.get("fill_color", (0.0, 0.55, 0.95, 0.22))),
            stroke_width=data.get("stroke_width", 1.5),
            unit=data.get("unit"),
            is_new=False,
            rotation=data.get("rotation", 0.0),
            label=data.get("label")
        )


@dataclass
class AcroFormField:
    """Data model representing an interactive AcroForm field."""
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

    def set_value(self, new_val: Any):
        self.value = new_val
        self.is_modified = True

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
        }


# Precision Drawing Units & Scales
POINTS_PER_INCH = 72.0
POINTS_PER_MM = 72.0 / 25.4
POINTS_PER_CM = 720.0 / 25.4
POINTS_PER_M = 72000.0 / 25.4
POINTS_PER_FT = 72.0 * 12.0
POINTS_PER_YD = 72.0 * 36.0
POINTS_PER_PT = 1.0

UNIT_FACTORS_TO_POINTS = {
    "pt": POINTS_PER_PT,
    "m": POINTS_PER_M,
    "cm": POINTS_PER_CM,
    "mm": POINTS_PER_MM,
    "in": POINTS_PER_INCH,
    "ft": POINTS_PER_FT,
    "yd": POINTS_PER_YD,
}

PRESET_SCALES = {
    "1:1": {"name": "1:1", "ratio": 1.0, "unit": "m"},
    "1:10": {"name": "1:10", "ratio": 10.0, "unit": "m"},
    "1:20": {"name": "1:20", "ratio": 20.0, "unit": "m"},
    "1:50": {"name": "1:50", "ratio": 50.0, "unit": "m"},
    "1:100": {"name": "1:100", "ratio": 100.0, "unit": "m"},
    "1:200": {"name": "1:200", "ratio": 200.0, "unit": "m"},
    "1:500": {"name": "1:500", "ratio": 500.0, "unit": "m"},
    "1:1000": {"name": "1:1000", "ratio": 1000.0, "unit": "m"},
    '1/8" = 1\'-0"': {"name": '1/8" = 1\'-0"', "ratio": 96.0, "unit": "ft"},
    '1/4" = 1\'-0"': {"name": '1/4" = 1\'-0"', "ratio": 48.0, "unit": "ft"},
    '1/2" = 1\'-0"': {"name": '1/2" = 1\'-0"', "ratio": 24.0, "unit": "ft"},
    '1" = 1\'-0"': {"name": '1" = 1\'-0"', "ratio": 12.0, "unit": "ft"},
    '1" = 10\'': {"name": '1" = 10\'', "ratio": 120.0, "unit": "ft"},
    '1" = 20\'': {"name": '1" = 20\'', "ratio": 240.0, "unit": "ft"},
}


@dataclass
class ScaleCalibration:
    """Document scale calibration for architectural, engineering, and precision drawings.

    Attributes:
        points_per_unit: Number of PDF points per real-world unit (e.g. 28.35 points per meter).
        unit: Measurement unit string ('m', 'cm', 'mm', 'ft', 'in', 'yd', 'pt').
        known_distance: Real-world reference length used for calibration.
        points_len: Measured length in PDF points of the reference line.
        reference_line: Optional (x1, y1, x2, y2) coordinates of reference line in PDF page space.
        preset_name: Optional preset identifier (e.g. '1:100', '1/4" = 1\'-0"').
        page_index: Page index if page-specific, or None for document-wide.
        ratio_value: Scale ratio factor (e.g. 1.0 for 1:1, 50.0 for 1:50).
    """
    points_per_unit: float = 1.0
    unit: str = "pt"
    known_distance: float = 1.0
    points_len: float = 0.0
    reference_line: Optional[Tuple[float, float, float, float]] = None
    preset_name: Optional[str] = None
    page_index: Optional[int] = None
    ratio_value: float = 1.0

    @property
    def units_per_point(self) -> float:
        """Return the reciprocal factor: real-world units per PDF point."""
        return (1.0 / self.points_per_unit) if self.points_per_unit > 0 else 1.0

    def distance_in_units(self, points: float) -> float:
        """Convert a distance in PDF points to calibrated real-world units."""
        return (points / self.points_per_unit) if self.points_per_unit > 0 else points

    def convert_distance(self, points: float) -> float:
        """Alias for distance_in_units."""
        return self.distance_in_units(points)

    def points_from_distance(self, distance: float) -> float:
        """Convert a real-world distance into PDF points."""
        return distance * self.points_per_unit

    def area_in_units(self, points_sq: float) -> float:
        """Convert an area in square points to square real-world units."""
        factor = self.points_per_unit ** 2
        return (points_sq / factor) if factor > 0 else points_sq

    def convert_area(self, points_sq: float) -> float:
        """Alias for area_in_units."""
        return self.area_in_units(points_sq)

    @staticmethod
    def convert_points_to_unit(points: float, unit: str) -> float:
        """Convert raw points to specified unit length."""
        factor = UNIT_FACTORS_TO_POINTS.get(unit, 1.0)
        return points / factor if factor > 0 else points

    def calibrate_from_points(self, points: List[Tuple[float, float]], real_world_dist: float, unit: str = "m"):
        """Calibrate scale in-place using two line endpoints and real world distance."""
        if len(points) >= 2:
            p0, p1 = points[0], points[1]
            dist_pt = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            self.reference_line = (p0[0], p0[1], p1[0], p1[1])
        else:
            dist_pt = 0.0
        safe_dist = max(float(real_world_dist), 1e-9)
        self.points_per_unit = dist_pt / safe_dist
        self.unit = unit
        self.known_distance = safe_dist
        self.points_len = dist_pt

    def format_distance(self, points: float, precision: int = 2) -> str:
        """Return human-readable distance with unit suffix."""
        val = self.distance_in_units(points)
        return f"{val:.{precision}f} {self.unit}"

    def format_area(self, points_sq: float, precision: int = 2) -> str:
        """Return human-readable area with unit squared suffix."""
        val = self.area_in_units(points_sq)
        return f"{val:.{precision}f} {self.unit}\u00b2"

    def format_scale_ratio(self) -> str:
        """Return summary of the scale ratio."""
        if self.preset_name:
            return f"{self.preset_name} (1 {self.unit} = {self.points_per_unit:.2f} pt)"
        return f"1 {self.unit} = {self.points_per_unit:.2f} pt"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize calibration state to dictionary."""
        return {
            "points_per_unit": float(self.points_per_unit),
            "unit": self.unit,
            "known_distance": float(self.known_distance),
            "points_len": float(self.points_len),
            "reference_line": list(self.reference_line) if self.reference_line else None,
            "preset_name": self.preset_name,
            "page_index": self.page_index,
            "ratio_value": float(self.ratio_value),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScaleCalibration":
        """Deserialize calibration state from dictionary."""
        ref_line = tuple(data["reference_line"]) if data.get("reference_line") else None
        return cls(
            points_per_unit=float(data.get("points_per_unit", 1.0)),
            unit=data.get("unit", "pt"),
            known_distance=float(data.get("known_distance", 1.0)),
            points_len=float(data.get("points_len", 0.0)),
            reference_line=ref_line,
            preset_name=data.get("preset_name"),
            page_index=data.get("page_index"),
            ratio_value=float(data.get("ratio_value", 1.0)),
        )

    @classmethod
    def from_reference_line(cls, x1: float, y1: float, x2: float, y2: float,
                            known_distance: float, unit: str = "m",
                            page_index: Optional[int] = None) -> "ScaleCalibration":
        """Compute calibration from reference line coordinates and known real-world distance."""
        dist_pt = math.hypot(x2 - x1, y2 - y1)
        safe_dist = max(float(known_distance), 1e-9)
        ppu = dist_pt / safe_dist
        return cls(
            points_per_unit=ppu,
            unit=unit,
            known_distance=safe_dist,
            points_len=dist_pt,
            reference_line=(x1, y1, x2, y2),
            page_index=page_index,
        )

    @classmethod
    def from_preset(cls, preset_key: str, page_index: Optional[int] = None) -> "ScaleCalibration":
        """Generate calibration from standard preset scale name."""
        preset = PRESET_SCALES.get(preset_key)
        if not preset:
            raise ValueError(f"Unknown preset scale: {preset_key}")
        unit = preset["unit"]
        ratio = preset["ratio"]
        base_ppu = UNIT_FACTORS_TO_POINTS.get(unit, POINTS_PER_M)
        ppu = base_ppu / ratio
        return cls(
            points_per_unit=ppu,
            unit=unit,
            known_distance=1.0,
            points_len=ppu,
            preset_name=preset_key,
            page_index=page_index,
        )


class StickyNoteObject:
    """Data model representing an interactive PDF Sticky Note / Text Comment annotation."""
    ICON_COMMENT = "Comment"
    ICON_NOTE = "Note"
    ICON_HELP = "Help"
    ICON_KEY = "Key"
    ICON_NEW_PARAGRAPH = "NewParagraph"

    COLOR_YELLOW = (1.0, 0.86, 0.24)
    COLOR_BLUE = (0.25, 0.60, 1.0)
    COLOR_GREEN = (0.30, 0.82, 0.45)
    COLOR_PINK = (1.0, 0.42, 0.62)
    COLOR_PURPLE = (0.68, 0.45, 0.98)

    COLOR_MAP = {
        "yellow": COLOR_YELLOW,
        "blue": COLOR_BLUE,
        "green": COLOR_GREEN,
        "pink": COLOR_PINK,
        "purple": COLOR_PURPLE,
    }

    def __init__(self, page_number: int = 0, x: float = 0.0, y: float = 0.0,
                 content: str = "", author: str = "",
                 color: Any = (1.0, 0.86, 0.24),
                 icon_type: str = "Comment",
                 created_at: Optional[str] = None,
                 modified_at: Optional[str] = None,
                 width: float = 24.0, height: float = 24.0,
                 is_new: bool = True, note_id: Optional[str] = None,
                 native_annot: Any = None,
                 color_hex: Optional[str] = None,
                 icon_name: Optional[str] = None):
        import datetime
        self.id = note_id or str(uuid.uuid4())[:8]
        self.page_number = int(page_number)
        self.x = float(x)
        self.y = float(y)
        self.width = float(width)
        self.height = float(height)
        self.content = str(content or "")
        self.author = str(author or "")
        actual_color = color_hex if color_hex else color
        self.color = normalize_color(actual_color) if actual_color else self.COLOR_YELLOW
        eff_icon = icon_name if icon_name else icon_type
        self.icon_type = eff_icon if eff_icon in (self.ICON_COMMENT, self.ICON_NOTE, self.ICON_HELP, self.ICON_KEY, self.ICON_NEW_PARAGRAPH) else self.ICON_COMMENT
        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.created_at = created_at or now_iso
        self.modified_at = modified_at or self.created_at
        self.is_new = is_new
        self.selected = False
        self.modified = is_new
        self.native_annot = native_annot

    @property
    def icon_name(self) -> str:
        return self.icon_type

    @icon_name.setter
    def icon_name(self, val: str):
        self.icon_type = val

    @property
    def rgba_tuple(self) -> Tuple[float, float, float, float]:
        r, g, b = self.color[:3]
        return (r, g, b, 1.0)

    @property
    def color_hex(self) -> str:
        r, g, b = self.color[:3]
        return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"

    @color_hex.setter
    def color_hex(self, hex_val: str):
        self.color = normalize_color(hex_val)

    def contains_point(self, px: float, py: float, padding: float = 4.0) -> bool:
        """Check if point (px, py) lies within note icon or hit padding."""
        x0, y0, x1, y1 = self.bbox
        return (x0 - padding <= px <= x1 + padding) and (y0 - padding <= py <= y1 + padding)

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        """Return (x0, y0, x1, y1) bounding box in PDF points."""
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize sticky note to dictionary."""
        return {
            "id": self.id,
            "page_number": self.page_number,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "content": self.content,
            "author": self.author,
            "color": list(self.color),
            "icon_type": self.icon_type,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StickyNoteObject":
        """Reconstruct sticky note from serialized dictionary."""
        return cls(
            page_number=data.get("page_number", 0),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            content=data.get("content", ""),
            author=data.get("author", ""),
            color=tuple(data.get("color", cls.COLOR_YELLOW)),
            icon_type=data.get("icon_type", cls.ICON_COMMENT),
            created_at=data.get("created_at"),
            modified_at=data.get("modified_at"),
            width=data.get("width", 24.0),
            height=data.get("height", 24.0),
            is_new=False,
            note_id=data.get("id"),
        )

class RedactionMark:
    """Data model representing a visual staged redaction mark on a PDF page."""
    DEFAULT_FILL_BLACK = (0.0, 0.0, 0.0)
    DEFAULT_FILL_WHITE = (1.0, 1.0, 1.0)
    DEFAULT_TEXT_COLOR_WHITE = (1.0, 1.0, 1.0)
    DEFAULT_TEXT_COLOR_BLACK = (0.0, 0.0, 0.0)
    DEFAULT_BORDER_COLOR = (0.85, 0.15, 0.15, 0.95)

    def __init__(self, page_number: int = 0,
                 bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
                 fill_color: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                 overlay_text: str = "[REDACTED]",
                 text_color: Tuple[float, float, float] = (1.0, 1.0, 1.0),
                 font_size: float = 10.0,
                 font_name: str = "helv",
                 border_color: Tuple[float, float, float, float] = (0.85, 0.15, 0.15, 0.95),
                 mark_id: Optional[str] = None,
                 is_applied: bool = False,
                 z_index: int = 0):
        self.id = mark_id or str(uuid.uuid4())[:8]
        self.page_number = int(page_number)
        self.fill_color = tuple(fill_color) if fill_color else self.DEFAULT_FILL_BLACK
        self.overlay_text = overlay_text or ""
        self.text_color = tuple(text_color) if text_color else self.DEFAULT_TEXT_COLOR_WHITE
        self.font_size = float(font_size)
        self.font_name = font_name
        self.border_color = tuple(border_color) if border_color else self.DEFAULT_BORDER_COLOR
        self.is_applied = bool(is_applied)
        self.selected = False
        self.z_index = int(z_index)
        self.rotation = 0.0
        self.update_bbox(*bbox)

    def update_bbox(self, x0: float, y0: float, x1: float, y1: float):
        """Update and normalize bounding box coordinates."""
        min_x = min(float(x0), float(x1))
        max_x = max(float(x0), float(x1))
        min_y = min(float(y0), float(y1))
        max_y = max(float(y0), float(y1))
        self.bbox = (min_x, min_y, max_x, max_y)
        self.x = min_x
        self.y = min_y
        self.width = max_x - min_x
        self.height = max_y - min_y

    def contains_point(self, px: float, py: float, tolerance: float = 2.0) -> bool:
        """Hit test checking whether (px, py) falls within or on the border of this redaction mark."""
        x0, y0, x1, y1 = self.bbox
        return (x0 - tolerance <= px <= x1 + tolerance and
                y0 - tolerance <= py <= y1 + tolerance)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize redaction mark to dictionary."""
        return {
            "id": self.id,
            "page_number": self.page_number,
            "bbox": list(self.bbox),
            "fill_color": list(self.fill_color),
            "overlay_text": self.overlay_text,
            "text_color": list(self.text_color),
            "font_size": self.font_size,
            "font_name": self.font_name,
            "border_color": list(self.border_color),
            "is_applied": self.is_applied,
            "z_index": self.z_index,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RedactionMark":
        """Reconstruct redaction mark from serialized dictionary."""
        return cls(
            page_number=data.get("page_number", 0),
            bbox=tuple(data.get("bbox", (0.0, 0.0, 0.0, 0.0))),
            fill_color=tuple(data.get("fill_color", cls.DEFAULT_FILL_BLACK)),
            overlay_text=data.get("overlay_text", "[REDACTED]"),
            text_color=tuple(data.get("text_color", cls.DEFAULT_TEXT_COLOR_WHITE)),
            font_size=data.get("font_size", 10.0),
            font_name=data.get("font_name", "helv"),
            border_color=tuple(data.get("border_color", cls.DEFAULT_BORDER_COLOR)),
            mark_id=data.get("id"),
            is_applied=data.get("is_applied", False),
            z_index=data.get("z_index", 0),
        )


class SpatialGridIndex:
    """Lightweight 2D spatial hash grid for accelerating canvas hit-testing."""

    def __init__(self, cell_size: float = 64.0):
        self.cell_size = float(max(16.0, cell_size))
        self.cells: Dict[Tuple[int, int], List[Any]] = collections.defaultdict(list)
        self.all_items: List[Any] = []

    def clear(self):
        """Reset all cells and indexed items."""
        self.cells.clear()
        self.all_items.clear()

    def insert(self, obj: Any, bbox: Optional[Tuple[float, float, float, float]] = None):
        """Insert object into the spatial grid cells matching its bounding box."""
        if bbox is None:
            bbox = getattr(obj, "bbox", None)
        if not bbox or len(bbox) != 4:
            self.all_items.append(obj)
            return

        x0, y0, x1, y1 = bbox
        min_x = min(x0, x1)
        max_x = max(x0, x1)
        min_y = min(y0, y1)
        max_y = max(y0, y1)

        c_x0 = int(math.floor(min_x / self.cell_size))
        c_x1 = int(math.floor(max_x / self.cell_size))
        c_y0 = int(math.floor(min_y / self.cell_size))
        c_y1 = int(math.floor(max_y / self.cell_size))

        self.all_items.append(obj)
        for cx in range(c_x0, c_x1 + 1):
            for cy in range(c_y0, c_y1 + 1):
                self.cells[(cx, cy)].append(obj)

    def query_point(self, x: float, y: float, tolerance: float = 0.0) -> List[Any]:
        """Return unique candidate objects in cells intersecting (x, y) with optional tolerance."""
        if not self.cells:
            return list(self.all_items)

        if tolerance <= 0.0:
            cx = int(math.floor(x / self.cell_size))
            cy = int(math.floor(y / self.cell_size))
            return list(self.cells.get((cx, cy), []))

        c_x0 = int(math.floor((x - tolerance) / self.cell_size))
        c_x1 = int(math.floor((x + tolerance) / self.cell_size))
        c_y0 = int(math.floor((y - tolerance) / self.cell_size))
        c_y1 = int(math.floor((y + tolerance) / self.cell_size))

        if c_x0 == c_x1 and c_y0 == c_y1:
            return list(self.cells.get((c_x0, c_y0), []))

        seen = set()
        candidates = []
        for cx in range(c_x0, c_x1 + 1):
            for cy in range(c_y0, c_y1 + 1):
                cell_objs = self.cells.get((cx, cy))
                if cell_objs:
                    for obj in cell_objs:
                        obj_id = id(obj)
                        if obj_id not in seen:
                            seen.add(obj_id)
                            candidates.append(obj)
        return candidates

    def query_rect(self, rect: Tuple[float, float, float, float]) -> List[Any]:
        """Return unique candidate objects intersecting given bounding box."""
        if not self.cells:
            return list(self.all_items)

        x0, y0, x1, y1 = rect
        c_x0 = int(math.floor(min(x0, x1) / self.cell_size))
        c_x1 = int(math.floor(max(x0, x1) / self.cell_size))
        c_y0 = int(math.floor(min(y0, y1) / self.cell_size))
        c_y1 = int(math.floor(max(y0, y1) / self.cell_size))

        if c_x0 == c_x1 and c_y0 == c_y1:
            return list(self.cells.get((c_x0, c_y0), []))

        seen = set()
        candidates = []
        for cx in range(c_x0, c_x1 + 1):
            for cy in range(c_y0, c_y1 + 1):
                cell_objs = self.cells.get((cx, cy))
                if cell_objs:
                    for obj in cell_objs:
                        obj_id = id(obj)
                        if obj_id not in seen:
                            seen.add(obj_id)
                            candidates.append(obj)
        return candidates


class PdfPage(GObject.GObject):
    """GObject model for PDF page index and thumbnail in sidebar list."""
    __gtype_name__ = 'PdfPage'
    index = GObject.Property(type=int)
    thumbnail = GObject.Property(type=GdkPixbuf.Pixbuf)

    def __init__(self, index, thumbnail=None):
        super().__init__(index=index, thumbnail=thumbnail)


@dataclass
class DocumentSession:
    """Encapsulates the state of an open PDF document session.

    Manages the document object, file paths, undo history, navigation,
    zoom level, edit mode, and page object collections.
    """
    doc: Any = None
    pdf_path: Optional[str] = None
    original_file_path: Optional[str] = None
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Navigation & View
    current_page_index: int = 0
    zoom_level: float = 1.0
    view_mode: bool = True
    continuous_scroll: bool = False
    show_ocr_overlay: bool = False
    scroll_x: float = 0.0
    scroll_y: float = 0.0

    # Modification & Undo
    is_modified: bool = False
    allow_incremental_save: bool = True
    is_repaired_file: bool = False
    undo_manager: Any = None

    # Page models & Object collections
    pages_model: Any = None
    editable_texts: List[Any] = field(default_factory=list)
    editable_images: List[Any] = field(default_factory=list)
    editable_shapes: List[Any] = field(default_factory=list)
    editable_strokes: List[Any] = field(default_factory=list)
    form_fields: List[AcroFormField] = field(default_factory=list)

    # Selected objects
    selected_text: Any = None
    selected_image: Any = None
    selected_shape: Any = None
    selected_stroke: Any = None
    selected_form_field: Optional[Any] = None

    # View mode text selection
    view_sel_start: Optional[Tuple[float, float]] = None
    view_sel_rect: Optional[Tuple[float, float, float, float]] = None
    view_selected_text: str = ""
    view_drag_active: bool = False

    # Word selection mode
    selected_word: Optional[str] = None
    selected_word_start_char: Optional[int] = None
    selected_word_end_char: Optional[int] = None
    word_selection_mode: bool = False

    # Page render caches
    page_cache: Dict[int, Any] = field(default_factory=dict)
    page_objects_cache: Dict[int, Any] = field(default_factory=dict)

    # Scale calibration
    scale_calibration: Optional[ScaleCalibration] = None
    scale_calibrations: Dict[int, ScaleCalibration] = field(default_factory=dict)

    # Measurements (Distance & Area)
    measurements: Dict[int, List[MeasurementObject]] = field(default_factory=dict)
    selected_measurement: Optional[Any] = None

    # Sticky Notes & Comments
    sticky_notes: Dict[int, List[StickyNoteObject]] = field(default_factory=dict)
    selected_sticky_note: Optional[Any] = None

    # Redactions (Staged visual marks)
    redaction_marks: Dict[int, List[RedactionMark]] = field(default_factory=dict)
    selected_redaction_mark: Optional[Any] = None

    # Tab integration
    tab_page: Any = None
    bin_widget: Any = None

    # Security and Vault
    is_vault: bool = False
    vault_password: Optional[str] = None
    pdf_password: Optional[str] = None
    digital_signatures: Optional[List[Dict[str, Any]]] = None

    def __post_init__(self):
        """Ensure Gio.ListStore for pages_model if not provided and apply view mode settings."""
        if self.pages_model is None:
            try:
                self.pages_model = Gio.ListStore(item_type=PdfPage)
            except Exception:
                self.pages_model = None

    @property
    def acroform_fields(self) -> List[Any]:
        return self.form_fields

    @acroform_fields.setter
    def acroform_fields(self, val: List[Any]):
        self.form_fields = val

    @property
    def title(self) -> str:
        """Return the document filename or 'Untitled Document'."""
        if self.pdf_path:
            return os.path.basename(self.pdf_path)
        return "Untitled Document"

    @property
    def display_title(self) -> str:
        """Return title prefixed with '*' if document has unsaved modifications."""
        t = self.title
        return f"*{t}" if self.is_modified else t

    @property
    def page_count(self) -> int:
        """Return the number of pages in the open document."""
        if self.doc:
            try:
                return len(self.doc)
            except Exception:
                return 0
        return 0

    def close(self):
        """Cleanly close the underlying document and free session resources."""
        if self.doc is not None:
            try:
                from . import pdf_handler
                pdf_handler.release_page_snapshots(self.doc)
                pdf_handler.invalidate_page_cache(self.doc)
            except Exception:
                pass
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None
        self.page_cache.clear()
        self.page_objects_cache.clear()
        self.editable_texts.clear()
        self.editable_images.clear()
        self.editable_shapes.clear()
        self.editable_strokes.clear()
        self.form_fields.clear()
        self.selected_text = None
        self.selected_image = None
        self.selected_shape = None
        self.selected_stroke = None
        self.selected_form_field = None
        self.scale_calibration = None
        self.scale_calibrations.clear()
        self.measurements.clear()
        self.selected_measurement = None
        self.sticky_notes.clear()
        self.selected_sticky_note = None
        self.scroll_x = 0.0
        self.scroll_y = 0.0


