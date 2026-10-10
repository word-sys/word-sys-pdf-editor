import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GObject, GdkPixbuf, Gio
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import os
import uuid
import math
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
        
    def set_rotation(self, angle):
        """Set rotation in degrees (0-360)."""
        self.rotation = float(angle) % 360.0

    def hit_test_char(self, x: float, y: float, tolerance: float = 2.0) -> Optional[Dict[str, Any]]:
        """Hit-test a point against the character bounding boxes in this EditableText object.
        
        Returns the closest matching character dict with keys 'char', 'bbox', 'origin', 'index'
        if within tolerance, else None.
        """
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
        if not self.text:
            return 0
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

    def split_at_range(self, start_char, end_char):
        """Split text into segments before, inside, and after a character selection range."""
        text = self.text
        if start_char < 0: start_char = 0
        if end_char > len(text): end_char = len(text)
        if start_char >= end_char:
            return [self]
        parts = []
        if start_char > 0:
            pre = copy.deepcopy(self)
            pre.text = text[:start_char]
            pre.original_text = text[:start_char]
            pre.is_new = True
            x1, y1, x2, y2 = self.bbox
            ratio = start_char / max(len(text), 1)
            pre.bbox = (x1, y1, x1 + (x2 - x1) * ratio, y2)
            pre.original_bbox = pre.bbox
            pre.original_rotation = getattr(self, 'rotation', 0.0)
            pre.x, pre.y = pre.bbox[0], pre.bbox[1]
            parts.append(pre)
        mid = copy.deepcopy(self)
        mid.text = text[start_char:end_char]
        mid.original_text = text[start_char:end_char]
        mid.is_new = True
        x1, y1, x2, y2 = self.bbox
        r1 = start_char / max(len(text), 1)
        r2 = end_char / max(len(text), 1)
        mid.bbox = (x1 + (x2 - x1) * r1, y1, x1 + (x2 - x1) * r2, y2)
        mid.original_bbox = mid.bbox
        mid.original_rotation = getattr(self, 'rotation', 0.0)
        mid.x, mid.y = mid.bbox[0], mid.bbox[1]
        parts.append(mid)
        if end_char < len(text):
            post = copy.deepcopy(self)
            post.text = text[end_char:]
            post.original_text = text[end_char:]
            post.is_new = True
            x1, y1, x2, y2 = self.bbox
            ratio = end_char / max(len(text), 1)
            post.bbox = (x1 + (x2 - x1) * ratio, y1, x2, y2)
            post.original_bbox = post.bbox
            post.original_rotation = getattr(self, 'rotation', 0.0)
            post.x, post.y = post.bbox[0], post.bbox[1]
            parts.append(post)
        return parts

class EditableImage:
    """Data model representing an extracted or inserted image on a PDF page."""
    def __init__(self, bbox, page_number, xref, image_bytes, is_new=False, rotation=0.0):
        self.bbox = bbox
        self.original_bbox = bbox
        self.page_number = page_number
        self.xref = xref
        self.image_bytes = image_bytes
        self.is_new = is_new
        self.selected = False
        self.modified = False
        self.rotation = float(rotation) % 360.0
        self.original_rotation = self.rotation

    def set_rotation(self, angle):
        """Set rotation in degrees (0-360)."""
        self.rotation = float(angle) % 360.0

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

UNIT_FACTORS_TO_POINTS = {
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
        unit: Measurement unit string ('m', 'cm', 'mm', 'ft', 'in', 'yd').
        known_distance: Real-world reference length used for calibration.
        points_len: Measured length in PDF points of the reference line.
        reference_line: Optional (x1, y1, x2, y2) coordinates of reference line in PDF page space.
        preset_name: Optional preset identifier (e.g. '1:100', '1/4" = 1\'-0"').
        page_index: Page index if page-specific, or None for document-wide.
    """
    points_per_unit: float
    unit: str = "m"
    known_distance: float = 1.0
    points_len: float = 0.0
    reference_line: Optional[Tuple[float, float, float, float]] = None
    preset_name: Optional[str] = None
    page_index: Optional[int] = None

    @property
    def units_per_point(self) -> float:
        """Return the reciprocal factor: real-world units per PDF point."""
        return (1.0 / self.points_per_unit) if self.points_per_unit > 0 else 1.0

    def distance_in_units(self, points: float) -> float:
        """Convert a distance in PDF points to calibrated real-world units."""
        return (points / self.points_per_unit) if self.points_per_unit > 0 else points

    def points_from_distance(self, distance: float) -> float:
        """Convert a real-world distance into PDF points."""
        return distance * self.points_per_unit

    def area_in_units(self, points_sq: float) -> float:
        """Convert an area in square points to square real-world units."""
        factor = self.points_per_unit ** 2
        return (points_sq / factor) if factor > 0 else points_sq

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
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScaleCalibration":
        """Deserialize calibration state from dictionary."""
        ref_line = tuple(data["reference_line"]) if data.get("reference_line") else None
        return cls(
            points_per_unit=float(data["points_per_unit"]),
            unit=data.get("unit", "m"),
            known_distance=float(data.get("known_distance", 1.0)),
            points_len=float(data.get("points_len", 0.0)),
            reference_line=ref_line,
            preset_name=data.get("preset_name"),
            page_index=data.get("page_index"),
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


class PdfPage(GObject.GObject):
    """GObject model for PDF page index and thumbnail in sidebar list."""
    __gtype_name__ = 'PdfPage'
    index = GObject.Property(type=int)
    thumbnail = GObject.Property(type=GdkPixbuf.Pixbuf)

    def __init__(self, index, thumbnail):
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

    # Scale calibration
    scale_calibration: Optional[ScaleCalibration] = None
    scale_calibrations: Dict[int, ScaleCalibration] = field(default_factory=dict)

    # Tab integration
    tab_page: Any = None
    bin_widget: Any = None

    def __post_init__(self):
        """Ensure Gio.ListStore for pages_model if not provided."""
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
                self.doc.close()
            except Exception:
                pass
            self.doc = None
        self.page_cache.clear()
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
        self.scroll_x = 0.0
        self.scroll_y = 0.0


