try:
    import pymupdf as fitz
except ImportError:
    import fitz
import numpy as np
import cairo
import io
import os
from pathlib import Path
import math
import subprocess
import shutil
import tempfile
import traceback
import re
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, Gdk, Pango, PangoCairo
from .models import EditableText, FLAG_BOLD, FLAG_ITALIC, EditableImage, EditableShape, EditableStroke
from .utils import find_specific_font_variant, get_default_unicode_font_path
from .i18n import _

_cairo_page_cache = {}

def invalidate_page_cache(doc=None, page_index=None):
    """Invalidate cached Cairo page surfaces."""
    global _cairo_page_cache
    if doc is None:
        _cairo_page_cache.clear()
        return
    doc_id = id(doc)
    if page_index is None:
        keys_to_del = [k for k in _cairo_page_cache if k[0] == doc_id]
    else:
        keys_to_del = [k for k in _cairo_page_cache if k[0] == doc_id and k[1] == page_index]
    for k in keys_to_del:
        _cairo_page_cache.pop(k, None)

def rotate_point(x, y, cx, cy, angle_degrees):
    """Rotate point (x, y) around pivot (cx, cy) by angle_degrees clockwise."""
    if angle_degrees == 0:
        return x, y
    rad = math.radians(angle_degrees)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    nx = cx + (x - cx) * cos_a - (y - cy) * sin_a
    ny = cy + (x - cx) * sin_a + (y - cy) * cos_a
    return nx, ny

def get_rotation_matrix(cx, cy, angle_degrees):
    """Return fitz.Matrix rotating around (cx, cy) by angle_degrees."""
    t1 = fitz.Matrix(1, 0, 0, 1, -cx, -cy)
    rot = fitz.Matrix(angle_degrees)
    t2 = fitz.Matrix(1, 0, 0, 1, cx, cy)
    return t1 * rot * t2

def transform_point_page_rot(x: float, y: float, w: float, h: float, angle_delta: int):
    """Transform a point (x, y) on a page of dimensions (w, h) when rotated by angle_delta degrees."""
    delta = angle_delta % 360
    if delta == 90:
        return h - y, x
    elif delta == 180:
        return w - x, h - y
    elif delta == 270:
        return y, w - x
    return x, y

def transform_bbox_page_rot(bbox, w: float, h: float, angle_delta: int):
    """Transform bounding box (x1, y1, x2, y2) on a page of dimensions (w, h) when rotated by angle_delta degrees."""
    if not bbox:
        return bbox
    x1, y1, x2, y2 = bbox
    delta = angle_delta % 360
    if delta == 90:
        return (h - y2, x1, h - y1, x2)
    elif delta == 180:
        return (w - x2, h - y2, w - x1, h - y1)
    elif delta == 270:
        return (y1, w - x2, y2, w - x1)
    return (x1, y1, x2, y2)

def get_page_cairo_surface(doc, page_index, zoom_level):
    """Get or render cached Cairo ImageSurface for the given page and zoom level."""
    global _cairo_page_cache
    if not doc or not (0 <= page_index < doc.page_count):
        return None

    cache_key = (id(doc), page_index, round(float(zoom_level), 4))
    if cache_key in _cairo_page_cache:
        return _cairo_page_cache[cache_key]

    try:
        page = doc.load_page(page_index)
        zoom_matrix = fitz.Matrix(zoom_level, zoom_level)
        pix = page.get_pixmap(matrix=zoom_matrix, alpha=False)
        samples_bytes = bytes(pix.samples)

        pixbuf = GdkPixbuf.Pixbuf.new_from_data(
            samples_bytes, GdkPixbuf.Colorspace.RGB, False, 8,
            pix.width, pix.height, pix.stride
        )

        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, pix.width, pix.height)
        cr_surf = cairo.Context(surf)
        cr_surf.set_source_rgb(1.0, 1.0, 1.0)
        cr_surf.paint()
        if pixbuf:
            Gdk.cairo_set_source_pixbuf(cr_surf, pixbuf, 0, 0)
            cr_surf.paint()

        # Limit cache size to 6 surfaces to conserve memory
        if len(_cairo_page_cache) >= 6:
            oldest_key = next(iter(_cairo_page_cache))
            _cairo_page_cache.pop(oldest_key, None)

        _cairo_page_cache[cache_key] = surf
        return surf
    except Exception as e:
        print(f"Error creating cached page surface for page {page_index}: {e}")
        return None

def _get_font_args_for_pymupdf(text_obj):
    """Get the font args for pymupdf."""
    font_arg = {}
    font_to_embed_path = find_specific_font_variant(
        text_obj.font_family_base,
        text_obj.is_bold,
        text_obj.is_italic
    )

    if font_to_embed_path:
        try:
            test_f = fitz.Font(fontfile=font_to_embed_path)
            non_ascii_chars = [c for c in text_obj.text if ord(c) > 127]
            missing = [c for c in non_ascii_chars if not test_f.has_glyph(ord(c))]
            if missing:
                fb_path = find_specific_font_variant("DejaVu Sans", text_obj.is_bold, text_obj.is_italic)
                if fb_path and fb_path != font_to_embed_path:
                    fb_f = fitz.Font(fontfile=fb_path)
                    if all(fb_f.has_glyph(ord(c)) for c in missing if ord(c) < 0x10000):
                        font_to_embed_path = fb_path
                        print(f"DEBUG (FontHelper): Fallback to DejaVu Sans for symbols: {missing}")
        except Exception as e:
            print(f"DEBUG (FontHelper): Glyph check warning: {e}")

        style_suffix = ""
        if text_obj.is_bold: style_suffix += "Bold"
        if text_obj.is_italic: style_suffix += "Italic"
        if not style_suffix: style_suffix = "Regular"

        safe_family_name = re.sub(r'\W+', '', text_obj.font_family_base or "UnknownFont")
        internal_font_name = f"word-sys_{safe_family_name}_{style_suffix}"
        
        font_arg = {"fontfile": font_to_embed_path, "fontname": internal_font_name}
        print(f"DEBUG (FontHelper): Using TTF: {font_to_embed_path} as '{internal_font_name}'")
        return font_arg, None
    else:
        generic_unicode_font = get_default_unicode_font_path()
        if generic_unicode_font:
            internal_font_name = "word-sysEditFont_GenericUnicode"
            font_arg = {"fontfile": generic_unicode_font, "fontname": internal_font_name}
            print(f"DEBUG (FontHelper): WARNING: Could not find specific TTF. Using generic fallback: {generic_unicode_font}")
            return font_arg, None
        else:
            base14_name = text_obj.pdf_fontname_base14
            if text_obj.is_bold and text_obj.is_italic: base14_name += "bo"
            elif text_obj.is_bold: base14_name += "b"
            elif text_obj.is_italic: base14_name += "i"
            font_arg = {"fontname": base14_name}
            print(f"DEBUG (FontHelper): CRITICAL WARNING: No TTF found. Falling back to Base 14 font: '{base14_name}'.")
            if any(ord(c) > 127 for c in text_obj.text):
                 return None, "Cannot save non-ASCII text: No suitable Unicode font found."
            return font_arg, None

def load_pdf_document(filepath):
    """Load PDF document."""
    try:
        doc = fitz.open(filepath)
        if doc.needs_pass:
            doc.close()
            return None, "Password protected PDFs are not supported yet."
        return doc, None
    except Exception as e:
        return None, f"Error opening PDF: {e}\nPath: {filepath}"

def close_pdf_document(doc):
    """Close PDF document."""
    if doc:
        try:
            invalidate_page_cache(doc)
            doc.close()
        except Exception as e:
            print(f"Error closing PDF document: {e}")

def get_page_count(doc):
    """Get the page count."""
    return doc.page_count if doc else 0

def generate_thumbnail(doc, page_index, target_width=150):
    """Generate thumbnail."""
    if not doc or not (0 <= page_index < doc.page_count):
        return None
    try:
        page = doc.load_page(page_index)
        
        page_w = page.rect.width
        if page_w == 0: 
            page_w = 1 
            
        zoom_factor = target_width / page_w
        matrix = fitz.Matrix(zoom_factor, zoom_factor)

        pix = page.get_pixmap(matrix=matrix, alpha=False)
        gdk_pixbuf = GdkPixbuf.Pixbuf.new_from_data(
            pix.samples, GdkPixbuf.Colorspace.RGB, False, 8,
            pix.width, pix.height, pix.stride
        )
        return gdk_pixbuf
    except Exception as thumb_error:
        print(f"Warning: Could not generate thumbnail for page {page_index+1}: {thumb_error}")
        placeholder_pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, target_width, int(target_width * 1.414))
        placeholder_pixbuf.fill(0xaaaaaaFF)
        return placeholder_pixbuf

def pixmap_to_cairo_surface(pix):
    """Pixmap to cairo surface."""
    data = None
    fmt = None
    stride = 0
    data_ref = None

    try:
        if pix.alpha:
            if pix.n != 4: return None, None
            fmt = cairo.FORMAT_ARGB32
            samples_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 4))
            bgra_data = np.zeros_like(samples_np)
            bgra_data[..., 0] = samples_np[..., 2] # B
            bgra_data[..., 1] = samples_np[..., 1] # G
            bgra_data[..., 2] = samples_np[..., 0] # R
            bgra_data[..., 3] = samples_np[..., 3] # A
            data = bytearray(bgra_data.tobytes())
            stride = pix.stride
            data_ref = data

        else:
            if pix.n != 3: return None, None
            bgra_data = np.zeros((pix.height, pix.width, 4), dtype=np.uint8)
            try:
                 rgb_view = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 3))
            except ValueError:
                 rgb_view = np.frombuffer(pix.samples, dtype=np.uint8).copy().reshape((pix.height, pix.width, 3))

            bgra_data[:, :, 0] = rgb_view[:, :, 2]  # Blue
            bgra_data[:, :, 1] = rgb_view[:, :, 1]  # Green
            bgra_data[:, :, 2] = rgb_view[:, :, 0]  # Red
            bgra_data[:, :, 3] = 255                # Alpha
            data = bgra_data.data 
            fmt = cairo.FORMAT_ARGB32
            stride = pix.width * 4 
            data_ref = bgra_data 

        if data is None: return None, None

        surface = cairo.ImageSurface.create_for_data(data, fmt, pix.width, pix.height, stride)
        return surface, data_ref

    except Exception as e:
        print(f"Error creating Cairo surface from pixmap: {e}")
        return None, None


def draw_page_to_cairo(cr, doc, page_index, zoom_level):
    """Draw page to cairo using the cached surface."""
    surf = get_page_cairo_surface(doc, page_index, zoom_level)
    if surf:
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.paint()
        cr.set_source_surface(surf, 0, 0)
        cr.paint()
        return True, None
    else:
        cr.set_source_rgb(0.7, 0.7, 0.7)
        cr.paint()
        return False, "Failed to render page."


def _get_page_text_baselines(page):
    """Get list of (x0, x1, baseline) for all text lines on page."""
    baselines = []
    try:
        text_dict = page.get_text("dict", flags=0)
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if spans:
                        tx0 = min(s["bbox"][0] for s in spans)
                        tx1 = max(s["bbox"][2] for s in spans)
                        baseline = spans[0].get("origin", (0, line.get("bbox", [0, 0, 0, 0])[3]))[1]
                        baselines.append((tx0, tx1, baseline))
    except Exception:
        pass
    return baselines


def _get_page_text_strikelines(page):
    """Get list of (x0, x1, baseline, font_size) for all text lines on page."""
    strikelines = []
    try:
        text_dict = page.get_text("dict", flags=0)
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if spans:
                        tx0 = min(s["bbox"][0] for s in spans)
                        tx1 = max(s["bbox"][2] for s in spans)
                        baseline = spans[0].get("origin", (0, line.get("bbox", [0, 0, 0, 0])[3]))[1]
                        font_size = spans[0].get("size", 11.0)
                        strikelines.append((tx0, tx1, baseline, font_size))
    except Exception:
        pass
    return strikelines


def _is_underline_drawing(drawing, baselines):
    """Check if a drawing is an underline coincident with a text baseline."""
    if not baselines:
        return False
    try:
        items = drawing.get('items', [])
        rect = drawing.get('rect')
        line_y = None
        line_x0 = None
        line_x1 = None
        if len(items) == 1 and items[0][0] == 'l':
            p1, p2 = items[0][1], items[0][2]
            if abs(p1.y - p2.y) <= 1.0 and abs(p1.x - p2.x) >= 4.0:
                line_y = (p1.y + p2.y) / 2.0
                line_x0, line_x1 = min(p1.x, p2.x), max(p1.x, p2.x)
        elif rect and rect.height <= 3.5 and rect.width >= 4.0:
            line_y = (rect.y0 + rect.y1) / 2.0
            line_x0, line_x1 = rect.x0, rect.x1

        if line_y is None or line_x0 is None or line_x1 is None:
            return False

        for tx0, tx1, baseline in baselines:
            if abs(line_y - (baseline + 1.5)) <= 2.5:
                overlap = min(line_x1, tx1) - max(line_x0, tx0)
                text_width = max(0.1, tx1 - tx0)
                if overlap >= min(4.0, text_width * 0.4):
                    return True
    except Exception:
        pass
    return False


def _is_strikethrough_drawing(drawing, strikelines):
    """Check if a drawing is a strikethrough line across text midpoint."""
    if not strikelines:
        return False
    try:
        items = drawing.get('items', [])
        rect = drawing.get('rect')
        line_y = None
        line_x0 = None
        line_x1 = None
        if len(items) == 1 and items[0][0] == 'l':
            p1, p2 = items[0][1], items[0][2]
            if abs(p1.y - p2.y) <= 1.0 and abs(p1.x - p2.x) >= 4.0:
                line_y = (p1.y + p2.y) / 2.0
                line_x0, line_x1 = min(p1.x, p2.x), max(p1.x, p2.x)
        elif rect and rect.height <= 3.5 and rect.width >= 4.0:
            line_y = (rect.y0 + rect.y1) / 2.0
            line_x0, line_x1 = rect.x0, rect.x1

        if line_y is None or line_x0 is None or line_x1 is None:
            return False

        for tx0, tx1, baseline, font_sz in strikelines:
            target_strike_y = baseline - (font_sz * 0.3)
            tolerance = max(2.5, font_sz * 0.2)
            if abs(line_y - target_strike_y) <= tolerance:
                overlap = min(line_x1, tx1) - max(line_x0, tx0)
                text_width = max(0.1, tx1 - tx0)
                if overlap >= min(4.0, text_width * 0.4):
                    return True
    except Exception:
        pass
    return False


def _get_span_style_signature(span):
    """Compute a normalized tuple signature for style comparison."""
    color = span.get("color", 0)
    if isinstance(color, (list, tuple)):
        norm_color = tuple(round(float(c), 3) for c in color[:3])
    else:
        norm_color = int(color)
    font = span.get("font", "")
    flags = span.get("flags", 0)
    size = round(float(span.get("size", 11.0)), 1)
    return (norm_color, font, flags, size)


def extract_editable_text(doc, page_index):
    """Extract editable text."""
    editable_texts = []
    if not doc or not (0 <= page_index < doc.page_count):
        return [], "Invalid document or page index for text extraction."
    try:
        page = doc.load_page(page_index)
        text_dict = page.get_text("rawdict", flags=0)

        page_drawings = None
        try:
            page_drawings = page.get_drawings()
        except Exception:
            page_drawings = []

        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    
                    # Group adjacent spans in line sharing identical style signature
                    runs = []
                    current_run = []
                    current_sig = None
                    
                    for span in spans:
                        text = "".join(c["c"] for c in span.get("chars", [])) if span.get("chars") else span.get("text", "")
                        if not text:
                            continue
                        
                        sig = _get_span_style_signature(span)
                        
                        # If span is purely whitespace, attach to current active run
                        if not text.strip() and current_run:
                            current_run.append(span)
                            continue
                            
                        if current_sig is None:
                            current_sig = sig
                            current_run = [span]
                        elif sig == current_sig:
                            current_run.append(span)
                        else:
                            if current_run:
                                runs.append(current_run)
                            current_sig = sig
                            current_run = [span]
                            
                    if current_run:
                        runs.append(current_run)
                        
                    for run in runs:
                        all_chars = []
                        for s in run:
                            if s.get("chars"):
                                all_chars.extend(s["chars"])
                        if all_chars:
                            non_space = [c for c in all_chars if not c["c"].isspace()]
                            if not non_space:
                                continue
                            combined_text = "".join(c["c"] for c in all_chars).strip()
                            min_x = min(c["bbox"][0] for c in non_space)
                            min_y = min(c["bbox"][1] for c in non_space)
                            max_x = max(c["bbox"][2] for c in non_space)
                            max_y = max(c["bbox"][3] for c in non_space)
                        else:
                            combined_text = "".join(s.get("text", "") for s in run).strip()
                            if not combined_text:
                                continue
                            min_x = min(s.get("bbox", (0, 0, 0, 0))[0] for s in run)
                            min_y = min(s.get("bbox", (0, 0, 0, 0))[1] for s in run)
                            max_x = max(s.get("bbox", (0, 0, 0, 0))[2] for s in run)
                            max_y = max(s.get("bbox", (0, 0, 0, 0))[3] for s in run)
                            
                        bbox = [min_x, min_y, max_x, max_y]
                        
                        first_span = run[0]
                        span_data = first_span.copy()
                        span_data["bbox"] = tuple(bbox)
                        span_data["text"] = combined_text

                        orig_origin = first_span.get("origin", (0, bbox[3]))
                        
                        line_dir = line.get("dir", (1.0, 0.0))
                        line_rot = 0.0
                        if line_dir and (abs(line_dir[0] - 1.0) > 1e-3 or abs(line_dir[1]) > 1e-3):
                            line_rot = round(math.degrees(math.atan2(line_dir[1], line_dir[0])), 1) % 360.0

                        editable = EditableText(
                            x=bbox[0], y=bbox[1], text=combined_text,
                            font_size=first_span.get("size", 11) if first_span else 11,
                            font_family=first_span.get("font", "Liberation Sans") if first_span else "Liberation Sans",
                            color=first_span.get("color", 0) if first_span else 0,
                            span_data=span_data,
                            baseline=orig_origin[1],
                            rotation=line_rot
                        )
                        editable.bbox = tuple(bbox)
                        editable.original_bbox = editable.bbox
                        editable.original_baseline = editable.baseline
                        editable.page_number = page_index
                        if page_drawings:
                            for d in page_drawings:
                                if _is_underline_drawing(d, [(bbox[0], bbox[2], orig_origin[1])]):
                                    editable.is_underline = True
                                    break
                            for d in page_drawings:
                                if _is_strikethrough_drawing(d, [(bbox[0], bbox[2], orig_origin[1], editable.font_size)]):
                                    editable.is_strikethrough = True
                                    break
                        editable_texts.append(editable)
                        print(f"DEBUG: Extracted text segment: '{combined_text}' font='{editable.font_family_base}' color={editable.color} bbox={editable.bbox}")
        
        print(f"DEBUG: Total text objects extracted from page {page_index}: {len(editable_texts)}")
        return editable_texts, None
    except Exception as e:
        error_msg = f"Error extracting text from page {page_index}: {e}"
        print(error_msg)
        traceback.print_exc()
        return [], error_msg

def _get_base14_font_variant(base_name, is_bold, is_italic):
    """Get the base14 font variant."""
    mapping = {'helv': 'Helvetica', 'timr': 'Times', 'cour': 'Courier'}
    pdf_base = mapping.get(base_name, 'Helvetica')
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

def apply_text_edit(doc, text_obj: EditableText, new_text: str):
    """Apply text edit."""
    if not doc or text_obj.page_number is None:
        return False, "Invalid document or page number."

    font_arg, error_msg = _get_font_args_for_pymupdf(text_obj)
    if error_msg:
        return False, error_msg

    try:
        page = doc.load_page(text_obj.page_number)
        
        print(f"DEBUG apply_text_edit: is_new={text_obj.is_new}, new_text='{new_text}'")
        print(f"DEBUG: text_obj bbox: {text_obj.bbox}")
        
        if new_text.strip():
            text_color = (0, 0, 0)
            if text_obj.color:
                if isinstance(text_obj.color, (tuple, list)) and len(text_obj.color) >= 3:
                    text_color = tuple(float(c) for c in text_obj.color[:3])
                elif isinstance(text_obj.color, int):
                    blue = (text_obj.color & 255) / 255.0
                    green = ((text_obj.color >> 8) & 255) / 255.0
                    red = ((text_obj.color >> 16) & 255) / 255.0
                    text_color = (red, green, blue)
            
            print(f"DEBUG: Inserting updated text '{new_text}' at point ({text_obj.x}, {text_obj.baseline})")
            
            line_point = fitz.Point(text_obj.x, text_obj.baseline)
            rc = page.insert_text(
                line_point,
                new_text,
                fontsize=text_obj.font_size,
                color=text_color,
                overlay=True,
                **font_arg
            )
            print(f"DEBUG: insert_text returned: {rc}")
            if rc < 0:
                print(f"ERROR: insert_text failed with rc={rc}")
                return False, f"PyMuPDF insert_text error: {rc}"

        return True, None
    except Exception as e:
        print(f"ERROR applying text edit: {e}")
        traceback.print_exc()
        return False, f"Error during text application: {e}"

def save_document(doc, save_path, incremental=False):
    """Save document."""
    if not doc:
        return False, "Kaydedilecek belge yok."

    temp_path = f"{save_path}.tmp_save"

    try:
        doc.save(
            temp_path,
            garbage=4,
            deflate=True,
            incremental=False,  
            encryption=fitz.PDF_ENCRYPT_NONE
        )

        os.replace(temp_path, save_path)
        return True, None

    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        
        return False, _("err_pdf_save", e)
    
def _is_flatpak_sandbox():
    """Check whether the app is running inside a Flatpak sandbox."""
    return os.path.exists('/.flatpak-info')

def _resolve_libreoffice_command():
    """Resolve the command used to invoke LibreOffice, reaching onto the host if sandboxed."""
    for name in ('libreoffice', 'soffice'):
        path = shutil.which(name)
        if path:
            return [path]

    if not _is_flatpak_sandbox():
        return None

    try:
        for name in ('libreoffice', 'soffice'):
            result = subprocess.run(
                ['flatpak-spawn', '--host', 'which', name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return ['flatpak-spawn', '--host', result.stdout.strip()]

        result = subprocess.run(
            ['flatpak-spawn', '--host', 'flatpak', 'info', 'org.libreoffice.LibreOffice'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return ['flatpak-spawn', '--host', 'flatpak', 'run', 'org.libreoffice.LibreOffice']
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None

def _export_via_libreoffice(doc, source_pdf_path, output_path, target_format):
    """Export via libreoffice."""
    libreoffice_command = _resolve_libreoffice_command()
    if not libreoffice_command:
        return False, f"LibreOffice Not Found. Install 'libreoffice-writer' to enable {target_format.upper()} export."
    print(f"DEBUG [{target_format.upper()} Export]: Using LibreOffice command: {libreoffice_command}")

    final_output_dir = Path(output_path).parent
    final_output_dir.mkdir(parents=True, exist_ok=True)

    if libreoffice_command[0] == 'flatpak-spawn':
        # LibreOffice runs in its own separate Flatpak sandbox and can't see
        # our document-portal mounts, our app-private ~/.var/app dir, or our
        # sandbox's private /tmp. It needs a plain real directory under $HOME
        # (outside both of those) that both sandboxes can see; we then move
        # the converted result into the real destination afterwards.
        work_dir = Path(os.path.expanduser('~/.word-sys-pdf-editor-libreoffice-cache'))
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        work_dir = final_output_dir

    temp_pdf_path = None
    try:
        fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf", prefix="word-sys_export_", dir=str(work_dir))
        os.close(fd)
        print(f"DEBUG [{target_format.upper()} Export]: Saving document state to temporary file: {temp_pdf_path}")

        try:
            pdf_bytes = doc.tobytes(garbage=4, clean=True, deflate=True)
            with open(temp_pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            save_success = True
            save_msg = ""
        except Exception as e:
            save_success, save_msg = save_document(doc, temp_pdf_path, incremental=False)

        if not save_success:
            if os.path.exists(temp_pdf_path): os.unlink(temp_pdf_path)
            return False, f"Failed to save temporary PDF for export: {save_msg}"
        
        if not os.path.exists(temp_pdf_path) or os.path.getsize(temp_pdf_path) == 0:
            print(f"ERROR [{target_format.upper()} Export]: Temporary PDF '{temp_pdf_path}' was not created or is empty.")
            if os.path.exists(temp_pdf_path): os.unlink(temp_pdf_path)
            return False, "Failed to create a valid temporary PDF for export."

        print(f"DEBUG [{target_format.upper()} Export]: Temp PDF Path = {temp_pdf_path} (Size: {os.path.getsize(temp_pdf_path)} bytes)")
        temp_pdf_path_obj = Path(temp_pdf_path)
        temp_pdf_name_no_ext = temp_pdf_path_obj.stem

        print(f"DEBUG [{target_format.upper()} Export]: Final {target_format.upper()} Output Dir = {final_output_dir}")
        print(f"DEBUG [{target_format.upper()} Export]: Desired Final {target_format.upper()} Path = {output_path}")

        python_cwd = Path(os.getcwd())
        expected_output_in_python_cwd = python_cwd / f"{temp_pdf_name_no_ext}.{target_format}"
        print(f"DEBUG [{target_format.upper()} Export]: Python's Current Working Directory (for output): {python_cwd}")
        print(f"DEBUG [{target_format.upper()} Export]: Expected {target_format.upper()} in Python CWD: {expected_output_in_python_cwd}")
        
        if os.path.exists(expected_output_in_python_cwd):
            print(f"DEBUG [{target_format.upper()} Export]: Removing leftover in CWD: {expected_output_in_python_cwd}")
            os.remove(expected_output_in_python_cwd)
        if os.path.exists(output_path):
            print(f"DEBUG [{target_format.upper()} Export]: Removing leftover final target: {output_path}")
            os.remove(output_path)

        if target_format == 'odt':
            convert_format = 'odt'
        elif target_format == 'docx':
            convert_format = 'docx'  
        else:
            convert_format = target_format

        infilter = 'writer_pdf_import'
        if target_format in ('pptx', 'odp'):
            infilter = 'impress_pdf_import'

        command = libreoffice_command + [
            '--headless',
            '--invisible',
            '--nologo',
            f'--infilter={infilter}',
            '--convert-to', convert_format,
            '--outdir', str(temp_pdf_path_obj.parent),
            str(temp_pdf_path)
        ]

        expected_output_location = temp_pdf_path_obj.parent / f"{temp_pdf_name_no_ext}.{target_format}"

        print(f"DEBUG [{target_format.upper()} Export]: Expected {target_format.upper()} at: {expected_output_location}")
        if os.path.exists(expected_output_location):
            print(f"DEBUG [{target_format.upper()} Export]: Removing leftover: {expected_output_location}")
            os.remove(expected_output_location)

        print(f"DEBUG [{target_format.upper()} Export]: Running command: {' '.join(command)}")

        current_env = os.environ.copy()
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env=current_env,
            stdin=subprocess.DEVNULL
        )

        print(f"DEBUG [{target_format.upper()} Export]: LibreOffice Return Code: {process.returncode}")
        if process.stdout:
            print(f"DEBUG [{target_format.upper()} Export]: LibreOffice stdout:\n---\n{process.stdout.strip()}\n---")
        if process.stderr:
            print(f"DEBUG [{target_format.upper()} Export]: LibreOffice stderr:\n---\n{process.stderr.strip()}\n---")

        if "0xc10" in process.stderr or "SfxBaseModel::impl_store" in process.stderr:
            error_msg = f"LibreOffice I/O Write Error during conversion. Stderr: {process.stderr.strip()}"
            if "no export filter" in process.stderr.lower():
                 error_msg += " (Also saw 'no export filter' - check LO installation and write permissions)"
            print(f"ERROR [{target_format.upper()} Export]: {error_msg}")
            return False, error_msg
        
        if ("no export filter" in process.stderr.lower() or "no export filter" in process.stdout.lower()) and process.returncode != 0 :
            error_msg = f"LibreOffice reported: No export filter for {target_format.upper()} found. Ensure 'libreoffice-writer' is fully installed."
            print(f"ERROR [{target_format.upper()} Export]: {error_msg}")
            return False, error_msg
            
        if process.returncode != 0:
            error_msg = f"LibreOffice conversion failed (code {process.returncode}).\nError:\n{process.stderr or process.stdout}"
            print(f"ERROR [{target_format.upper()} Export]: {error_msg}")
            return False, error_msg

        if os.path.exists(expected_output_location):
            print(f"DEBUG [{target_format.upper()} Export]: Found {target_format.upper()} at: {expected_output_location}")
            try:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(expected_output_location), str(output_path))
                print(f"DEBUG [{target_format.upper()} Export]: Moved {target_format.upper()} to final destination: {output_path}")
                return True, None
            except Exception as move_e:
                error_msg = f"Found converted {target_format.upper()} ({expected_output_location}) but failed to move to {output_path}: {move_e}"
                print(f"ERROR [{target_format.upper()} Export]: {error_msg}")
                return False, error_msg
        else:
            error_msg = f"LibreOffice conversion seemed to finish, but the output {target_format.upper()} ({expected_output_location}) could not be located."
            print(f"ERROR [{target_format.upper()} Export]: {error_msg}")
            return False, error_msg

    except subprocess.TimeoutExpired:
        return False, "LibreOffice conversion timed out (took longer than 120 seconds)."
    except Exception as e:
        print(f"ERROR [{target_format.upper()} Export]: General exception during {target_format.upper()} export process: {e}")
        return False, f"Error during {target_format.upper()} export process: {e}"
    finally:
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            try:
                os.unlink(temp_pdf_path)
                print(f"DEBUG [{target_format.upper()} Export]: Cleaned up temp PDF: {temp_pdf_path}")
            except Exception as unlink_e:
                print(f"Warning: Could not delete temporary file {temp_pdf_path}: {unlink_e}")

def export_pdf_as_odt(doc, source_pdf_path, output_odt_path):
    """Export PDF as odt."""
    if not output_odt_path.lower().endswith('.odt'):
        output_odt_path += '.odt'
    return _export_via_libreoffice(doc, source_pdf_path, output_odt_path, 'odt')

def export_pdf_as_docx(doc, source_pdf_path, output_docx_path):
    """Export PDF as docx."""
    if not output_docx_path.lower().endswith('.docx'):
        output_docx_path += '.docx'
    return _export_via_libreoffice(doc, source_pdf_path, output_docx_path, 'docx')

def export_pdf_as_pptx(doc, source_pdf_path, output_pptx_path):
    """Export PDF as pptx."""
    if not output_pptx_path.lower().endswith('.pptx'):
        output_pptx_path += '.pptx'
    return _export_via_libreoffice(doc, source_pdf_path, output_pptx_path, 'pptx')

def export_pdf_as_odp(doc, source_pdf_path, output_odp_path):
    """Export PDF as odp."""
    if not output_odp_path.lower().endswith('.odp'):
        output_odp_path += '.odp'
    return _export_via_libreoffice(doc, source_pdf_path, output_odp_path, 'odp')


def export_pdf_as_odt_alias(doc, source_pdf_path, output_odt_path):
    """Export PDF as odt alias."""
    return export_pdf_as_odt(doc, source_pdf_path, output_odt_path)


def _export_pdf_via_libreoffice(doc, output_path, target_format, format_label):
    """Export PDF via libreoffice."""
    if target_format == 'docx':
        return export_pdf_as_docx(doc, None, output_path)
    elif target_format == 'odt':
        return export_pdf_as_odt(doc, None, output_path)
    return False, f"Unsupported format: {target_format}"


def export_pdf_as_text(doc, output_txt_path):
    """Export PDF as text."""
    if not doc:
        return False, "No document to export."
    try:
        with open(output_txt_path, 'w', encoding='utf-8') as txt_file:
            for page_num in range(doc.page_count):
                page = doc.load_page(page_num)
                text = page.get_text("text", sort=True)
                txt_file.write(f"--- Page {page_num + 1} ---\n\n")
                txt_file.write(text)
                txt_file.write("\n\n")
        return True, None
    except Exception as e:
        return False, f"Error exporting as text: {e}"

def get_image_rgba_bytes(doc, xref):
    """Extract image as RGBA PNG bytes, compositing alpha/smask if present."""
    try:
        image_data = doc.extract_image(xref)
        if not image_data or 'image' not in image_data:
            return None

        smask_xref = image_data.get('smask', 0)
        if not smask_xref:
            try:
                smask_val = doc.xref_get_key(xref, "SMask")
                if smask_val and smask_val[0] == "xref":
                    smask_xref = int(smask_val[1].split()[0])
            except Exception:
                pass

        base_pix = fitz.Pixmap(doc, xref)

        # If soft mask (alpha transparency) is present
        if smask_xref and smask_xref > 0:
            try:
                mask_pix = fitz.Pixmap(doc, smask_xref)
                if base_pix.n != 3:
                    base_pix = fitz.Pixmap(fitz.csRGB, base_pix)
                if mask_pix.n != 1:
                    mask_pix = fitz.Pixmap(fitz.csGRAY, mask_pix)
                if base_pix.width == mask_pix.width and base_pix.height == mask_pix.height:
                    rgba_pix = fitz.Pixmap(base_pix, mask_pix)
                    return rgba_pix.tobytes("png")
                else:
                    from PIL import Image
                    import io
                    base_img = Image.open(io.BytesIO(base_pix.tobytes("png"))).convert("RGB")
                    mask_img = Image.open(io.BytesIO(mask_pix.tobytes("png"))).convert("L")
                    mask_img = mask_img.resize(base_img.size, Image.Resampling.LANCZOS)
                    base_img.putalpha(mask_img)
                    out_buf = io.BytesIO()
                    base_img.save(out_buf, format="PNG")
                    return out_buf.getvalue()
            except Exception as mask_err:
                print(f"Warning: smask compositing failed for xref {xref}: {mask_err}")

        # If base pixmap itself has alpha channel
        if base_pix.alpha:
            if base_pix.n != 4:
                base_pix = fitz.Pixmap(fitz.csRGB, base_pix)
            return base_pix.tobytes("png")

        # If CMYK without alpha, convert to standard RGB PNG
        if base_pix.n >= 4:
            rgb_pix = fitz.Pixmap(fitz.csRGB, base_pix)
            return rgb_pix.tobytes("png")

        # Standard image (JPEG, non-transparent PNG, etc.)
        return image_data["image"]
    except Exception as e:
        print(f"Warning: get_image_rgba_bytes failed for xref {xref}: {e}")
        try:
            return doc.extract_image(xref).get("image")
        except Exception:
            return None

def extract_editable_images(doc, page_index):
    """Extract editable images."""
    editable_images = []
    if not doc or not (0 <= page_index < doc.page_count):
        return [], _("err_invalid_doc_page_extract")
    
    try:
        page = doc.load_page(page_index)
        image_info_list = page.get_image_info(xrefs=True)
        
        if not image_info_list:
            print(f"DEBUG: No images found via get_image_info on page {page_index}. Trying alternative method...")
            image_info_list = []
        
        for img_info in image_info_list:
            try:
                bbox = img_info.get('bbox')
                xref = img_info.get('xref')
                
                if not bbox or not xref:
                    continue
 
                rect = fitz.Rect(bbox)
                if rect.is_empty or not rect.is_valid:
                    continue
 
                try:
                    image_bytes = get_image_rgba_bytes(doc, xref)
                    if not image_bytes:
                        print(f"DEBUG: Could not extract image data for xref {xref}")
                        continue
                    
                    image_obj = EditableImage(
                        bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                        page_number=page_index,
                        xref=xref,
                        image_bytes=image_bytes,
                        rotation=0.0
                    )
                    editable_images.append(image_obj)
                except Exception as extract_error:
                    print(f"DEBUG: Error extracting image bytes for xref {xref}: {extract_error}")
                    continue
                    
            except (ValueError, TypeError) as e:
                print(_("warn_image_skipped", page_index+1, img_info.get('xref'), e))
                continue
        
        print(f"DEBUG: Extracted {len(editable_images)} images from page {page_index}")
        return editable_images, None
    except Exception as e:
        error_msg = _("err_image_extract_page", page_index+1, e)
        print(error_msg)
        traceback.print_exc()
        return [], error_msg

def add_image_to_page(doc, page_number, image_path, rect):
    """Add image to page."""
    if not doc or page_number is None:
        return False, _("err_invalid_doc_page_add_image")
    try:
        page = doc.load_page(page_number)
        page.insert_image(rect, filename=image_path)
        return True, None
    except FileNotFoundError:
        return False, _("err_image_file_not_found", image_path)
    except Exception as e:
        print(_("err_placing_image", e))
        traceback.print_exc()
        return False, _("err_placing_image", e)

def delete_image_from_page(doc, image_obj: EditableImage):
    """Delete image from page."""
    if not doc or image_obj.page_number is None:
        return False, _("err_invalid_doc_page_delete_image")
    try:
        page = doc.load_page(image_obj.page_number)

        redact_rect = fitz.Rect(image_obj.bbox)
        if not redact_rect.is_empty and redact_rect.is_valid:
            page.add_redact_annot(redact_rect)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=0, text=1)
            except TypeError:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
            doc.load_page(image_obj.page_number)
            invalidate_page_cache(doc, image_obj.page_number)
            return True, None
        else:
            return False, _("err_invalid_image_bbox")
    except Exception as e:
        print(_("err_deleting_image", e))
        traceback.print_exc()
        return False, _("err_deleting_image", e)

def delete_shape_from_page(doc, shape_obj: EditableShape):
    """Delete shape from page."""
    if not doc or shape_obj.page_number is None:
        return False, _("err_invalid_doc_page_delete_shape")
    try:
        page = doc.load_page(shape_obj.page_number)

        x0, y0, x1, y1 = shape_obj.bbox
        pad = max(getattr(shape_obj, 'stroke_width', 2.0) / 2.0 + 1.5, 2.0)
        redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        if not redact_rect.is_empty and redact_rect.is_valid:
            page.add_redact_annot(redact_rect)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
            except TypeError:
                try:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=True)
                except Exception:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            doc.load_page(shape_obj.page_number)
            invalidate_page_cache(doc, shape_obj.page_number)
            return True, None
        else:
            return False, _("err_invalid_shape_bbox")
    except Exception as e:
        print(_("err_deleting_shape", e))
        traceback.print_exc()
        return False, _("err_deleting_shape", e)

def delete_stroke_from_page(doc, stroke_obj: EditableStroke):
    """Delete stroke from page."""
    if not doc or stroke_obj.page_number is None:
        return False, "Invalid document or page number."
    try:
        page = doc.load_page(stroke_obj.page_number)
        x0, y0, x1, y1 = stroke_obj.bbox
        pad = max(getattr(stroke_obj, 'stroke_width', 2.0) / 2.0 + 1.5, 2.0)
        redact_rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        if not redact_rect.is_empty and redact_rect.is_valid:
            page.add_redact_annot(redact_rect)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=2, text=1)
            except TypeError:
                try:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=True)
                except Exception:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            doc.load_page(stroke_obj.page_number)
            invalidate_page_cache(doc, stroke_obj.page_number)
            return True, None
        return False, "Invalid stroke bounding box."
    except Exception as e:
        print(f"Error deleting stroke: {e}")
        traceback.print_exc()
        return False, str(e)



def extract_editable_shapes(doc, page_index):
    """Extract editable geometric shapes (rectangles, ellipses)."""
    editable_shapes = []
    if not doc or not (0 <= page_index < doc.page_count):
        return [], "Invalid document or page index for shape extraction."
    try:
        page = doc.load_page(page_index)
        drawings = page.get_drawings()
        baselines = _get_page_text_baselines(page)
        strikelines = _get_page_text_strikelines(page)
        for drawing in drawings:
            try:
                if _is_underline_drawing(drawing, baselines) or _is_strikethrough_drawing(drawing, strikelines):
                    continue
                items = drawing.get('items', [])
                if not items:
                    continue

                raw_fill = drawing.get('fill')
                raw_stroke = drawing.get('color')
                raw_width = drawing.get('width', 1.0)
                is_transparent = (raw_fill is None)
                fill_color = raw_fill if raw_fill else (1.0, 1.0, 1.0)
                stroke_color = raw_stroke if raw_stroke else (0.0, 0.0, 0.0)
                stroke_width = float(raw_width) if raw_width else 1.0

                # Check if rectangle:
                if len(items) == 1 and items[0][0] == 're':
                    r = fitz.Rect(items[0][1])
                    if r.width >= 2 and r.height >= 2:
                        shape_obj = EditableShape(
                            shape_type=EditableShape.SHAPE_RECTANGLE,
                            bbox=(r.x0, r.y0, r.x1, r.y1),
                            fill_color=fill_color,
                            stroke_color=stroke_color,
                            stroke_width=stroke_width,
                            page_number=page_index,
                            is_new=False,
                            is_transparent=is_transparent,
                            rotation=0.0
                        )
                        shape_obj.is_baked = True
                        editable_shapes.append(shape_obj)
                    continue

                # Check if ellipse:
                if len(items) == 4 and all(it[0] == 'c' for it in items):
                    rect = drawing.get('rect')
                    if rect:
                        r = fitz.Rect(rect)
                        if r.width >= 2 and r.height >= 2:
                            shape_obj = EditableShape(
                                shape_type=EditableShape.SHAPE_ELLIPSE,
                                bbox=(r.x0, r.y0, r.x1, r.y1),
                                fill_color=fill_color,
                                stroke_color=stroke_color,
                                stroke_width=stroke_width,
                                page_number=page_index,
                                is_new=False,
                                is_transparent=is_transparent,
                                rotation=0.0
                            )
                            shape_obj.is_baked = True
                            editable_shapes.append(shape_obj)
                    continue

                # If drawing is filled, treat as rectangle shape by bounding box
                if raw_fill is not None:
                    rect = drawing.get('rect')
                    if rect:
                        r = fitz.Rect(rect)
                        if r.width >= 2 and r.height >= 2:
                            shape_obj = EditableShape(
                                shape_type=EditableShape.SHAPE_RECTANGLE,
                                bbox=(r.x0, r.y0, r.x1, r.y1),
                                fill_color=fill_color,
                                stroke_color=stroke_color,
                                stroke_width=stroke_width,
                                page_number=page_index,
                                is_new=False,
                                is_transparent=False,
                                rotation=0.0
                            )
                            shape_obj.is_baked = True
                            editable_shapes.append(shape_obj)
            except Exception as item_err:
                print(f"Warning: skipping shape drawing item: {item_err}")
                continue

        print(f"DEBUG: Extracted {len(editable_shapes)} shapes from page {page_index}")
        return editable_shapes, None
    except Exception as e:
        error_msg = f"Error extracting shapes from page {page_index}: {e}"
        print(error_msg)
        return [], error_msg


def extract_editable_strokes(doc, page_index):
    """Extract editable freehand and highlighter strokes."""
    editable_strokes = []
    if not doc or not (0 <= page_index < doc.page_count):
        return [], "Invalid document or page index for stroke extraction."
    try:
        page = doc.load_page(page_index)
        drawings = page.get_drawings()
        baselines = _get_page_text_baselines(page)
        strikelines = _get_page_text_strikelines(page)
        for drawing in drawings:
            try:
                if _is_underline_drawing(drawing, baselines) or _is_strikethrough_drawing(drawing, strikelines):
                    continue
                items = drawing.get('items', [])
                if not items:
                    continue

                # Skip pure shapes (handled by extract_editable_shapes)
                if len(items) == 1 and items[0][0] == 're':
                    continue
                if len(items) == 4 and all(it[0] == 'c' for it in items):
                    continue
                if drawing.get('fill') is not None:
                    continue

                raw_stroke = drawing.get('color')
                raw_width = drawing.get('width', 1.0)
                raw_opacity = drawing.get('opacity')

                subpaths = []
                current_subpath = []
                for it in items:
                    if it[0] == 'l':
                        p1, p2 = (it[1].x, it[1].y), (it[2].x, it[2].y)
                        if current_subpath and current_subpath[-1] != p1:
                            subpaths.append(current_subpath)
                            current_subpath = [p1, p2]
                        else:
                            if not current_subpath:
                                current_subpath.append(p1)
                            current_subpath.append(p2)
                    elif it[0] == 'c':
                        p1, p4 = (it[1].x, it[1].y), (it[4].x, it[4].y)
                        if current_subpath and current_subpath[-1] != p1:
                            subpaths.append(current_subpath)
                            current_subpath = [p1, p4]
                        else:
                            if not current_subpath:
                                current_subpath.append(p1)
                            current_subpath.append(p4)
                if current_subpath:
                    subpaths.append(current_subpath)

                stroke_width = float(raw_width) if raw_width else 2.0
                is_hl = (stroke_width >= 8.0) or (raw_opacity is not None and raw_opacity < 0.9)
                tool_type = EditableStroke.TOOL_HIGHLIGHTER if is_hl else EditableStroke.TOOL_PEN
                opacity = float(raw_opacity) if raw_opacity is not None else (0.35 if is_hl else 1.0)
                stroke_color = raw_stroke if raw_stroke else (0.0, 0.0, 0.0)

                for sp in subpaths:
                    if sp and len(sp) >= 1:
                        stroke_obj = EditableStroke(
                            points=sp,
                            stroke_color=stroke_color,
                            stroke_width=stroke_width,
                            opacity=opacity,
                            tool_type=tool_type,
                            page_number=page_index,
                            is_new=False,
                            rotation=0.0
                        )
                        stroke_obj.is_baked = True
                        editable_strokes.append(stroke_obj)
            except Exception as item_err:
                print(f"Warning: skipping stroke drawing item: {item_err}")
                continue

        print(f"DEBUG: Extracted {len(editable_strokes)} strokes from page {page_index}")
        return editable_strokes, None
    except Exception as e:
        error_msg = f"Error extracting strokes from page {page_index}: {e}"
        print(error_msg)
        return [], error_msg

_page_snapshots: dict = {}
_page_original_links: dict = {}

def save_page_snapshot(doc, page_num: int, force: bool = False):
    """Save page snapshot."""
    key = (id(doc), page_num)
    if key in _page_snapshots and not force:
        return  
    try:
        page = doc.load_page(page_num)
        page.clean_contents()
        xrefs = page.get_contents()
        content = b""
        for xref in xrefs:
            raw = doc.xref_stream(xref)
            if raw:
                content += raw
        _page_snapshots[key] = content
        _page_original_links[key] = page.get_links()
    except Exception as e:
        print(f"Warning: could not save snapshot for page {page_num}: {e}")


def restore_page_from_snapshot(doc, page_num: int) -> bool:
    """Restore page from snapshot."""
    key = (id(doc), page_num)
    if key not in _page_snapshots:
        return False
    try:
        content = _page_snapshots[key]
        page = doc.load_page(page_num)
        page.clean_contents()
        xrefs = page.get_contents()
        if xrefs:
            doc.update_stream(xrefs[0], content)
            for extra_xref in xrefs[1:]:
                try:
                    doc.xref_set_key(extra_xref, "Length", "0")
                    doc.update_stream(extra_xref, b"")
                except Exception:
                    pass
        else:
            xref = doc._newXref()
            doc.update_stream(xref, content)
            
        original_links = _page_original_links.get(key, [])
        original_signatures = set()
        for link in original_links:
            rect = link.get("from")
            rect_tuple = (rect.x0, rect.y0, rect.x1, rect.y1) if rect else (0, 0, 0, 0)
            sig = (link.get("kind"), rect_tuple, link.get("uri"))
            original_signatures.add(sig)
            
        current_links = page.get_links()
        for link in current_links:
            rect = link.get("from")
            rect_tuple = (rect.x0, rect.y0, rect.x1, rect.y1) if rect else (0, 0, 0, 0)
            sig = (link.get("kind"), rect_tuple, link.get("uri"))
            if sig not in original_signatures:
                page.delete_link(link)
                
        invalidate_page_cache(doc, page_num)
        return True
    except Exception as e:
        print(f"Warning: could not restore snapshot for page {page_num}: {e}")
        return False

def release_page_snapshots(doc):
    """Release page snapshots."""
    doc_id = id(doc)
    keys_to_remove = [k for k in _page_snapshots if k[0] == doc_id]
    for k in keys_to_remove:
        del _page_snapshots[k]
        if k in _page_original_links:
            del _page_original_links[k]

def _apply_single_object_to_page(doc, page, obj):
    """Apply single object to page."""
    rot = getattr(obj, "rotation", 0.0) % 360.0

    if isinstance(obj, EditableText):
        if obj.text:
            font_arg, error_msg = _get_font_args_for_pymupdf(obj)
            if error_msg:
                return False, error_msg
            lines = obj.text.split('\n')
            line_height = obj.font_size * 1.2
            
            base_name = getattr(obj, "pdf_fontname_base14", "helv")
            is_bold = getattr(obj, "is_bold", False)
            is_italic = getattr(obj, "is_italic", False)
            calc_font = _get_base14_font_variant(base_name, is_bold, is_italic)
            
            fontname = font_arg.get("fontname", "helv")
            fontfile = font_arg.get("fontfile", None)
            font_obj = None
            try:
                font_obj = fitz.Font(fontname=fontname, fontfile=fontfile)
            except Exception:
                pass

            cx = (obj.bbox[0] + obj.bbox[2]) / 2.0 if obj.bbox else obj.x
            cy = (obj.bbox[1] + obj.bbox[3]) / 2.0 if obj.bbox else obj.y
            morph = (fitz.Point(cx, cy), fitz.Matrix(-rot)) if rot != 0.0 else None
            mat = get_rotation_matrix(cx, cy, rot) if rot != 0.0 else None

            align = getattr(obj, 'alignment', 'left')
            box_w = (obj.bbox[2] - obj.bbox[0]) if obj.bbox and (obj.bbox[2] > obj.bbox[0]) else None

            for i, line in enumerate(lines):
                links = list(re.finditer(r'(https?://[^\s]+|www\.[^\s]+)', line))
                
                if font_obj:
                    try:
                        text_len = font_obj.text_length(line, fontsize=obj.font_size)
                    except Exception:
                        text_len = fitz.get_text_length(line, fontname=calc_font, fontsize=obj.font_size)
                else:
                    text_len = fitz.get_text_length(line, fontname=calc_font, fontsize=obj.font_size)

                w_avail = box_w if box_w and box_w > text_len else text_len
                if align == 'center':
                    line_start_x = obj.x + max(0.0, (w_avail - text_len) / 2.0)
                elif align == 'right':
                    line_start_x = obj.x + max(0.0, w_avail - text_len)
                else:
                    line_start_x = obj.x

                if not links:
                    is_justified = (align == 'justify' and box_w and box_w > text_len and i < len(lines) - 1)
                    words = line.split(' ') if is_justified else None
                    if is_justified and words and len(words) > 1:
                        word_lens = []
                        for w in words:
                            if font_obj:
                                try:
                                    wl = font_obj.text_length(w, fontsize=obj.font_size)
                                except Exception:
                                    wl = fitz.get_text_length(w, fontname=calc_font, fontsize=obj.font_size)
                            else:
                                wl = fitz.get_text_length(w, fontname=calc_font, fontsize=obj.font_size)
                            word_lens.append(wl)
                        total_w = sum(word_lens)
                        space_w = (box_w - total_w) / (len(words) - 1)
                        curr_wx = obj.x
                        for w, wl in zip(words, word_lens):
                            if w:
                                pos = fitz.Point(curr_wx, obj.baseline + (i * line_height))
                                page.insert_text(pos, w, fontsize=obj.font_size,
                                                 color=obj.color, overlay=True, morph=morph, **font_arg)
                            curr_wx += wl + space_w
                        line_draw_x = obj.x
                        draw_len = box_w
                    else:
                        pos = fitz.Point(line_start_x, obj.baseline + (i * line_height))
                        page.insert_text(pos, line, fontsize=obj.font_size,
                                         color=obj.color, overlay=True, morph=morph, **font_arg)
                        line_draw_x = line_start_x
                        draw_len = text_len
                    
                    if getattr(obj, 'is_underline', False):
                        p1 = fitz.Point(line_draw_x, obj.baseline + (i * line_height) + 1.5)
                        p2 = fitz.Point(line_draw_x + draw_len, obj.baseline + (i * line_height) + 1.5)
                        if mat:
                            p1 = p1 * mat
                            p2 = p2 * mat
                        page.draw_line(p1, p2, color=obj.color, width=0.8)

                    if getattr(obj, 'is_strikethrough', False):
                        sp1 = fitz.Point(line_draw_x, obj.baseline + (i * line_height) - (obj.font_size * 0.3))
                        sp2 = fitz.Point(line_draw_x + draw_len, obj.baseline + (i * line_height) - (obj.font_size * 0.3))
                        if mat:
                            sp1 = sp1 * mat
                            sp2 = sp2 * mat
                        page.draw_line(sp1, sp2, color=obj.color, width=0.8)
                else:
                    segments = []
                    last_idx = 0
                    for match in links:
                        start, end = match.start(), match.end()
                        if start > last_idx:
                            segments.append((line[last_idx:start], False))
                        segments.append((line[start:end], True))
                        last_idx = end
                    if last_idx < len(line):
                        segments.append((line[last_idx:], False))
                        
                    current_x = line_start_x
                    for seg_text, is_seg_link in segments:
                        if not seg_text:
                            continue
                        
                        seg_color = (0.0, 0.33, 0.8) if is_seg_link else obj.color
                        pos = fitz.Point(current_x, obj.baseline + (i * line_height))
                        page.insert_text(pos, seg_text, fontsize=obj.font_size,
                                         color=seg_color, overlay=True, morph=morph, **font_arg)
                        
                        if font_obj:
                            try:
                                seg_len = font_obj.text_length(seg_text, fontsize=obj.font_size)
                            except Exception:
                                seg_len = fitz.get_text_length(seg_text, fontname=calc_font, fontsize=obj.font_size)
                        else:
                            seg_len = fitz.get_text_length(seg_text, fontname=calc_font, fontsize=obj.font_size)
                        
                        if is_seg_link or getattr(obj, 'is_underline', False):
                            p1 = fitz.Point(current_x, obj.baseline + (i * line_height) + 1.5)
                            p2 = fitz.Point(current_x + seg_len, obj.baseline + (i * line_height) + 1.5)
                            if mat:
                                p1 = p1 * mat
                                p2 = p2 * mat
                            page.draw_line(p1, p2, color=seg_color, width=0.8)

                        if getattr(obj, 'is_strikethrough', False):
                            sp1 = fitz.Point(current_x, obj.baseline + (i * line_height) - (obj.font_size * 0.3))
                            sp2 = fitz.Point(current_x + seg_len, obj.baseline + (i * line_height) - (obj.font_size * 0.3))
                            if mat:
                                sp1 = sp1 * mat
                                sp2 = sp2 * mat
                            page.draw_line(sp1, sp2, color=seg_color, width=0.8)
                            
                        if is_seg_link:
                            y0 = obj.baseline + (i * line_height) - obj.font_size
                            y1 = obj.baseline + (i * line_height) + (obj.font_size * 0.2)
                            link_rect = fitz.Rect(current_x, y0, current_x + seg_len, y1)
                            
                            uri = seg_text
                            if not uri.startswith(("http://", "https://")):
                                uri = "https://" + uri
                                
                            link_from = link_rect.quad * mat if mat else link_rect.quad
                            rect = link_from.rect if hasattr(link_from, 'rect') else fitz.Rect(link_from)
                            link_data = {"kind": fitz.LINK_URI, "from": rect, "uri": uri}
                            page.insert_link(link_data)
                            
                        current_x += seg_len
                        
    elif isinstance(obj, EditableImage):
        rect = fitz.Rect(obj.bbox)
        if rot == 0.0:
            page.insert_image(rect, stream=obj.image_bytes, keep_proportion=False)
        elif rot % 90 == 0:
            page.insert_image(rect, stream=obj.image_bytes, rotate=int(rot), keep_proportion=False)
        else:
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(obj.image_bytes))
                rotated_im = im.rotate(-rot, expand=True, resample=Image.BICUBIC)
                buf = io.BytesIO()
                rotated_im.save(buf, format="PNG")
                stream = buf.getvalue()
                cx = (rect.x0 + rect.x1) / 2.0
                cy = (rect.y0 + rect.y1) / 2.0
                w = rect.x1 - rect.x0
                h = rect.y1 - rect.y0
                rad = math.radians(rot)
                nw = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
                nh = abs(w * math.sin(rad)) + abs(h * math.cos(rad))
                rot_rect = fitz.Rect(cx - nw / 2.0, cy - nh / 2.0, cx + nw / 2.0, cy + nh / 2.0)
                page.insert_image(rot_rect, stream=stream, keep_proportion=False)
            except Exception:
                page.insert_image(rect, stream=obj.image_bytes, keep_proportion=False)
    elif isinstance(obj, EditableShape):
        rect = fitz.Rect(obj.bbox)
        shape = page.new_shape()
        stroke = tuple(float(c) for c in obj.stroke_color)
        fill = tuple(float(c) for c in obj.fill_color) if not obj.is_transparent else None
        cx = (rect.x0 + rect.x1) / 2.0
        cy = (rect.y0 + rect.y1) / 2.0
        mat = get_rotation_matrix(cx, cy, rot) if rot != 0.0 else None

        if obj.shape_type == EditableShape.SHAPE_RECTANGLE:
            if mat:
                shape.draw_quad(rect.quad * mat)
            else:
                shape.draw_rect(rect)
            shape.finish(color=stroke, fill=fill, width=obj.stroke_width)
        elif obj.shape_type == EditableShape.SHAPE_ELLIPSE:
            if mat:
                k = 0.5522847498307935
                rx = (rect.x1 - rect.x0) / 2.0
                ry = (rect.y1 - rect.y0) / 2.0
                beziers = [
                    (fitz.Point(cx + rx, cy), fitz.Point(cx + rx, cy - k * ry), fitz.Point(cx + k * rx, cy - ry), fitz.Point(cx, cy - ry)),
                    (fitz.Point(cx, cy - ry), fitz.Point(cx - k * rx, cy - ry), fitz.Point(cx - rx, cy - k * ry), fitz.Point(cx - rx, cy)),
                    (fitz.Point(cx - rx, cy), fitz.Point(cx - rx, cy + k * ry), fitz.Point(cx - k * rx, cy + ry), fitz.Point(cx, cy + ry)),
                    (fitz.Point(cx, cy + ry), fitz.Point(cx + k * rx, cy + ry), fitz.Point(cx + rx, cy + k * ry), fitz.Point(cx + rx, cy))
                ]
                for p0, c1, c2, p1 in beziers:
                    shape.draw_bezier(p0 * mat, c1 * mat, c2 * mat, p1 * mat)
            else:
                shape.draw_oval(rect)
            shape.finish(color=stroke, fill=fill, width=obj.stroke_width)
        elif obj.shape_type == EditableShape.SHAPE_CHECKMARK:
            pts = obj.get_checkmark_points()
            fitz_pts = [fitz.Point(p[0], p[1]) * mat if mat else fitz.Point(p[0], p[1]) for p in pts]
            shape.draw_polyline(fitz_pts)
            shape.finish(color=stroke, fill=None, width=obj.stroke_width, lineCap=1, lineJoin=1, closePath=False)
        elif obj.shape_type == EditableShape.SHAPE_CROSS:
            lines = obj.get_cross_lines()
            for (p1, p2) in lines:
                pt1 = fitz.Point(p1[0], p1[1]) * mat if mat else fitz.Point(p1[0], p1[1])
                pt2 = fitz.Point(p2[0], p2[1]) * mat if mat else fitz.Point(p2[0], p2[1])
                shape.draw_line(pt1, pt2)
            shape.finish(color=stroke, fill=None, width=obj.stroke_width, lineCap=1, lineJoin=1, closePath=False)
        else:
            if mat:
                shape.draw_quad(rect.quad * mat)
            else:
                shape.draw_rect(rect)
            shape.finish(color=stroke, fill=fill, width=obj.stroke_width)
        shape.commit()
    elif isinstance(obj, EditableStroke):
        if obj.points and len(obj.points) >= 2:
            shape = page.new_shape()
            pts = [fitz.Point(p[0], p[1]) for p in obj.points]
            if rot != 0.0 and obj.bbox:
                cx = (obj.bbox[0] + obj.bbox[2]) / 2.0
                cy = (obj.bbox[1] + obj.bbox[3]) / 2.0
                mat = get_rotation_matrix(cx, cy, rot)
                pts = [p * mat for p in pts]
            shape.draw_polyline(pts)
            stroke = tuple(float(c) for c in obj.stroke_color)
            is_hl = getattr(obj, 'tool_type', None) in (EditableStroke.TOOL_HIGHLIGHTER, "highlighter") or obj.stroke_width >= 8.0
            cap = 2 if is_hl else 1
            join = 2 if is_hl else 1
            shape.finish(
                color=stroke,
                width=obj.stroke_width,
                stroke_opacity=getattr(obj, 'opacity', 1.0),
                lineCap=cap,
                lineJoin=join,
                closePath=False
            )
            shape.commit()
        elif obj.points and len(obj.points) == 1:
            p = fitz.Point(obj.points[0][0], obj.points[0][1])
            if rot != 0.0 and obj.bbox:
                cx = (obj.bbox[0] + obj.bbox[2]) / 2.0
                cy = (obj.bbox[1] + obj.bbox[3]) / 2.0
                nx, ny = rotate_point(p.x, p.y, cx, cy, rot)
                p = fitz.Point(nx, ny)
            r = max(obj.stroke_width / 2.0, 1.0)
            rect = fitz.Rect(p.x - r, p.y - r, p.x + r, p.y + r)
            shape = page.new_shape()
            is_hl = getattr(obj, 'tool_type', None) in (EditableStroke.TOOL_HIGHLIGHTER, "highlighter") or obj.stroke_width >= 8.0
            if is_hl:
                shape.draw_rect(rect)
            else:
                shape.draw_oval(rect)
            stroke = tuple(float(c) for c in obj.stroke_color)
            shape.finish(
                color=stroke,
                fill=stroke,
                fill_opacity=getattr(obj, 'opacity', 1.0),
                stroke_opacity=getattr(obj, 'opacity', 1.0)
            )
            shape.commit()
    return True, None

def rebuild_page(doc, page_num: int, all_texts, all_shapes, all_images,
                 exclude_obj=None, all_strokes=None):
    """Rebuild page."""
    if not restore_page_from_snapshot(doc, page_num):
        print(f"Warning: no snapshot for page {page_num}, skipping restore")
    try:
        page = doc.load_page(page_num)
        for obj in all_texts:
            if getattr(obj, 'page_number', None) == page_num and obj is not exclude_obj:
                if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                    _apply_single_object_to_page(doc, page, obj)
        for obj in all_images:
            if getattr(obj, 'page_number', None) == page_num and obj is not exclude_obj:
                if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                    _apply_single_object_to_page(doc, page, obj)
        for obj in all_shapes:
            if getattr(obj, 'page_number', None) == page_num and obj is not exclude_obj:
                if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                    _apply_single_object_to_page(doc, page, obj)
        if all_strokes:
            for obj in all_strokes:
                if getattr(obj, 'page_number', None) == page_num and obj is not exclude_obj:
                    if getattr(obj, 'is_new', False) or getattr(obj, '_ghost_redacted', False):
                        _apply_single_object_to_page(doc, page, obj)
        invalidate_page_cache(doc, page_num)
        return True, None
    except Exception as e:
        print(f"ERROR: rebuild_page failed for page {page_num}: {e}")
        traceback.print_exc()
        return False, str(e)

def apply_object_edit(doc, obj):
    """Apply object edit."""
    if not doc or not hasattr(obj, 'page_number') or obj.page_number is None:
        return False, "Invalid object or page number."
    try:
        page = doc.load_page(obj.page_number)
        res, err = _apply_single_object_to_page(doc, page, obj)
        invalidate_page_cache(doc, obj.page_number)
        return res, err
    except Exception as e:
        print(f"ERROR: An error occurred while applying object edit: {e}")
        traceback.print_exc()
        return False, f"Error while applying object edit: {e}"
    
def create_new_pdf(width=595, height=842, num_pages=1):
    """Create new PDF with customizable dimensions and page count."""
    try:
        doc = fitz.open()
        w = float(width) if width else 595.0
        h = float(height) if height else 842.0
        pages = max(1, int(num_pages)) if num_pages else 1
        for _ in range(pages):
            doc.new_page(width=w, height=h)
        return doc, None
    except Exception as e:
        return None, _("err_creating_new_pdf", e)

def insert_blank_page(doc, page_index=None, width=None, height=None):
    """Insert blank page."""
    try:
        if width is None or height is None:
            if doc.page_count > 0:
                first_page = doc[0]
                default_width = first_page.rect.width
                default_height = first_page.rect.height
            else:
                default_width = 595
                default_height = 842
            
            if width is None:
                width = default_width
            if height is None:
                height = default_height
        
        doc_id = id(doc)
        global _page_snapshots, _page_original_links
        if page_index is not None and 0 <= page_index <= doc.page_count:
            target_pno = int(page_index)
            new_snapshots = {}
            for (did, pno), content in _page_snapshots.items():
                if did == doc_id and pno >= target_pno:
                    new_snapshots[(did, pno + 1)] = content
                else:
                    new_snapshots[(did, pno)] = content
            _page_snapshots = new_snapshots

            new_links = {}
            for (did, pno), links in _page_original_links.items():
                if did == doc_id and pno >= target_pno:
                    new_links[(did, pno + 1)] = links
                else:
                    new_links[(did, pno)] = links
            _page_original_links = new_links

            doc.new_page(pno=target_pno, width=width, height=height)
        else:
            doc.new_page(width=width, height=height)

        invalidate_page_cache(doc)
        return True, _("success_blank_page_added", doc.page_count)
    
    except Exception as e:
        return False, _("err_adding_page", e)

def merge_pdf_pages(target_doc, source_pdf_path, insert_position=None):
    """Merge PDF pages."""
    try:
        source_doc = fitz.open(source_pdf_path)
        source_page_count = source_doc.page_count
        
        if source_page_count == 0:
            return False, _("err_source_pdf_empty"), 0
        
        target_doc.insert_pdf(source_doc, from_page=0, to_page=source_page_count - 1)
        
        source_doc.close()
        invalidate_page_cache(target_doc)
        
        return True, _("success_merged_pages", source_page_count), source_page_count
    
    except Exception as e:
        return False, _("err_merging_pdf", e), 0

def move_page(doc, from_index, to_index):
    """Move page."""
    try:
        if from_index < 0 or from_index >= doc.page_count:
            return False, _("err_invalid_page_index")
        
        if to_index < 0 or to_index >= doc.page_count:
            return False, _("err_invalid_target_index")
        
        if from_index == to_index:
            return True, _("success_page_already_there")
        
        if from_index < to_index:
            fitz_target = -1 if to_index >= doc.page_count - 1 else to_index + 1
        else:
            fitz_target = to_index
        doc.move_page(from_index, fitz_target)
        
        doc_id = id(doc)
        global _page_snapshots, _page_original_links
        def _remap_index(p):
            if from_index < to_index:
                if p == from_index: return to_index
                if from_index < p <= to_index: return p - 1
            else:
                if p == from_index: return to_index
                if to_index <= p < from_index: return p + 1
            return p

        new_snapshots = {}
        for (did, pno), content in _page_snapshots.items():
            if did == doc_id:
                new_snapshots[(did, _remap_index(pno))] = content
            else:
                new_snapshots[(did, pno)] = content
        _page_snapshots = new_snapshots

        new_links = {}
        for (did, pno), links in _page_original_links.items():
            if did == doc_id:
                new_links[(did, _remap_index(pno))] = links
            else:
                new_links[(did, pno)] = links
        _page_original_links = new_links

        invalidate_page_cache(doc)
        
        return True, _("success_page_moved", from_index + 1, to_index + 1)
    
    except Exception as e:
        return False, _("err_moving_page", e)

def delete_page(doc, page_index):
    """Delete page."""
    try:
        if not doc:
            return False, _("err_no_doc_msg_alt")
        
        if doc.page_count <= 1:
            return False, _("err_cannot_delete_last_page")
        
        if page_index < 0 or page_index >= doc.page_count:
            return False, _("err_invalid_page_index_val", page_index + 1)
        
        doc.delete_page(page_index)
        
        doc_id = id(doc)
        global _page_snapshots, _page_original_links
        new_snapshots = {}
        for (did, pno), content in _page_snapshots.items():
            if did == doc_id:
                if pno == page_index:
                    continue
                elif pno > page_index:
                    new_snapshots[(did, pno - 1)] = content
                else:
                    new_snapshots[(did, pno)] = content
            else:
                new_snapshots[(did, pno)] = content
        _page_snapshots = new_snapshots

        new_links = {}
        for (did, pno), links in _page_original_links.items():
            if did == doc_id:
                if pno == page_index:
                    continue
                elif pno > page_index:
                    new_links[(did, pno - 1)] = links
                else:
                    new_links[(did, pno)] = links
            else:
                new_links[(did, pno)] = links
        _page_original_links = new_links

        invalidate_page_cache(doc)
        return True, _("success_page_deleted", page_index + 1)
    
    except Exception as e:
        return False, _("err_deleting_page", e)

def rotate_page(doc, page_index: int, angle_delta: int):
    """Rotate the specified page by angle_delta degrees (e.g. 90 or -90)."""
    if not doc or not (0 <= page_index < doc.page_count):
        return False, _("err_invalid_page_index")
    try:
        page = doc.load_page(page_index)
        cur_rot = getattr(page, 'rotation', 0) or 0
        new_rot = (cur_rot + angle_delta) % 360
        page.set_rotation(new_rot)
        invalidate_page_cache(doc, page_index)
        return True, new_rot
    except Exception as e:
        return False, str(e)

def get_page_rotation(doc, page_index: int) -> int:
    """Get the current rotation of the specified page in degrees."""
    if not doc or not (0 <= page_index < doc.page_count):
        return 0
    try:
        page = doc.load_page(page_index)
        return getattr(page, 'rotation', 0) or 0
    except Exception:
        return 0

def add_highlight_annotation(doc, page_index, rect_unzoomed, color=(1, 0.93, 0), is_visual=False, rotation=0.0):
    """Add highlight annotation."""
    if not doc or not (0 <= page_index < doc.page_count):
        return False, "Invalid document or page index."
    try:
        page = doc.load_page(page_index)
        r = fitz.Rect(*rect_unzoomed)
        if is_visual and page.rotation % 360 != 0:
            r = (r * (~page.rotation_matrix)).normalize()
        if r.is_empty or not r.is_valid:
            return False, "Empty or invalid rect."
        rot = float(rotation) % 360.0
        if rot != 0.0:
            cx = (r.x0 + r.x1) / 2.0
            cy = (r.y0 + r.y1) / 2.0
            mat = get_rotation_matrix(cx, cy, rot)
            annot = page.add_highlight_annot(quads=r.quad * mat)
        else:
            annot = page.add_highlight_annot(r)
        annot.set_colors(stroke=color)
        annot.update()
        invalidate_page_cache(doc, page_index)
        return True, None
    except Exception as e:
        traceback.print_exc()
        return False, f"Highlight annotation error: {e}"

def remove_highlight_annotations(doc, page_index, rect_unzoomed=None, is_visual=False):
    """Remove highlight annotations."""
    if not doc or not (0 <= page_index < doc.page_count):
        return False, "Invalid document or page index."
    try:
        page = doc.load_page(page_index)
        annots = page.annots()
        removed_count = 0
        
        if annots:
            target_rect = None
            if rect_unzoomed:
                target_rect = fitz.Rect(*rect_unzoomed)
                if is_visual and page.rotation % 360 != 0:
                    target_rect = (target_rect * (~page.rotation_matrix)).normalize()
            
            for annot in annots:
                annot_type = annot.type[0]
                if annot_type == 8:
                    if target_rect is None or target_rect.intersects(annot.rect):
                        page.delete_annot(annot)
                        removed_count += 1
        
        if removed_count > 0:
            invalidate_page_cache(doc, page_index)
        return True, removed_count
    except Exception as e:
        traceback.print_exc()
        return False, f"Error removing highlights: {e}"

def get_text_in_rect(doc, page_index, rect_unzoomed):
    """Get the text in rect."""
    if not doc or not (0 <= page_index < doc.page_count):
        return ""
    try:
        page = doc.load_page(page_index)
        r = fitz.Rect(*rect_unzoomed)
        if page.rotation % 360 != 0:
            r = (r * (~page.rotation_matrix)).normalize()
        words = page.get_text("words", clip=r, sort=True)
        return " ".join(w[4] for w in words)
    except Exception as e:
        print(f"get_text_in_rect error: {e}")
        return ""

def get_word_at_pos(doc, page_index, pos_unzoomed):
    """Get the word at pos."""
    if not doc or not (0 <= page_index < doc.page_count):
        return None
    try:
        page = doc.load_page(page_index)
        x, y = pos_unzoomed
        p = fitz.Point(x, y)
        rot_mat = page.rotation_matrix if page.rotation % 360 != 0 else None
        if rot_mat:
            p = p * (~rot_mat)
        words = page.get_text("words")
        for w in words:
            r = fitz.Rect(w[0], w[1], w[2], w[3])
            if r.contains(p):
                vis_r = (r * rot_mat).normalize() if rot_mat else r
                return {'bbox': (vis_r.x0, vis_r.y0, vis_r.x1, vis_r.y1), 'text': w[4]}
        return None
    except Exception as e:
        print(f"get_word_at_pos error: {e}")
        return None

def get_block_at_pos(doc, page_index, pos_unzoomed):
    """Get the block at pos."""
    if not doc or not (0 <= page_index < doc.page_count):
        return None
    try:
        page = doc.load_page(page_index)
        x, y = pos_unzoomed
        p = fitz.Point(x, y)
        rot_mat = page.rotation_matrix if page.rotation % 360 != 0 else None
        if rot_mat:
            p = p * (~rot_mat)
        
        text_dict = page.get_text("dict")
        for block in text_dict["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    r = fitz.Rect(line["bbox"])
                    if r.contains(p):
                        line_text = "".join(span["text"] for span in line["spans"])
                        vis_r = (r * rot_mat).normalize() if rot_mat else r
                        return {'bbox': (vis_r.x0, vis_r.y0, vis_r.x1, vis_r.y1), 'text': line_text}
        return None
    except Exception as e:
        print(f"get_block_at_pos error: {e}")
        return None