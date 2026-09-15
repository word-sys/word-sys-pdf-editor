import os
import platform
from pathlib import Path
import re
import subprocess
import threading
from gi.repository import GLib
from .i18n import _

FONT_SCAN_COMPLETED = threading.Event()
SYSTEM_FONTS = {}
FONT_FAMILY_LIST_SORTED = []
FONT_MATCH_CACHE = {}

def _get_embedded_font_dir():
    """Retrieve the embedded fonts directory within the package."""
    try:
        base_dir = Path(__file__).resolve().parent
        fonts_dir = base_dir / "fonts"
        if fonts_dir.is_dir():
            print(_("dbg_embedded_font_found", fonts_dir))
            return fonts_dir
    except Exception as e:
        print(_("err_embedded_font_not_found", e))
    return None

def _get_font_dirs():
    """Get all potential directory paths that contain system fonts."""
    font_dirs = []

    embedded_dir = _get_embedded_font_dir()
    if embedded_dir:
        font_dirs.append(embedded_dir)

    system = platform.system()
    if system == "Linux":
        system_font_paths = [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.local/share/fonts"),
            os.path.expanduser("~/.fonts"),
            "/run/host/fonts",
            "/run/host/user-fonts",
        ]
    elif system == "Windows":
        system_font_paths = [os.path.join(os.environ.get('SYSTEMROOT', 'C:\\Windows'), 'Fonts')]
    elif system == "Darwin":
        system_font_paths = ["/System/Library/Fonts/", "/Library/Fonts/", os.path.expanduser("~/Library/Fonts")]
    else:
        system_font_paths = []

    for d_str in system_font_paths:
        if d_str:
            d_path = Path(d_str)
            if d_path.is_dir() and d_path not in font_dirs:
                font_dirs.append(d_path)

    return font_dirs

def parse_font_name(filename):
    """Parse font name and extract family name and weight/slant style."""
    name_part = filename.stem

    styles_map = {
        "BoldItalic": [r"BoldItalic", r"BoldOblique", r"BdI", r"Z", r"BI"],
        "Bold":       [r"Bold", r"Bd", r"Heavy", r"Black", r"DemiBold", r"SmBd", r"S_B"],
        "Italic":     [r"Italic", r"It", r"Oblique", r"Kursiv", r"I", r"Obl"],
        "Regular":    [r"Regular", r"Roman", r"Normal", r"Medium", r"Book", r"Rg", r"W4", r"W5", r"Text"]
    }

    detected_style_key = "Regular"
    cleaned_name = name_part

    for style_key, patterns in styles_map.items():
        for pattern in patterns:
            match = re.search(r"([_ -]?" + pattern + r")$", cleaned_name, re.IGNORECASE)
            if match:
                detected_style_key = style_key
                cleaned_name = cleaned_name[:match.start()]
                break
        if detected_style_key != "Regular" and style_key != "Regular":
            break

    family_name_candidate = re.sub(r"[ _-]+$", "", cleaned_name)
    if not family_name_candidate:
        family_name_candidate = name_part

    family_name_candidate = re.sub(r'(PSMT|PS|MT)$', '', family_name_candidate, flags=re.IGNORECASE).strip()

    family_name_candidate = re.sub(r"([a-z])([A-Z])", r"\1 \2", family_name_candidate)
    display_family_name = ' '.join(word.capitalize() for word in family_name_candidate.replace('-', ' ').replace('_', ' ').split())

    if not display_family_name:
        return None, None

    return display_family_name, detected_style_key

def scan_system_fonts_async(callback_on_done=None):
    """Scan system fonts async."""
    def _scan():
        """Scan."""
        global SYSTEM_FONTS, FONT_FAMILY_LIST_SORTED, FONT_SCAN_COMPLETED
        print("Scanning system and embedded fonts...")
        font_dirs = _get_font_dirs()
        temp_fonts_data = {}

        for directory in font_dirs:
            try:
                for item in list(directory.rglob('*.ttf')) + list(directory.rglob('*.otf')):
                    if item.is_file():
                        family_name, style_key = parse_font_name(item)
                        if family_name and style_key:
                            if family_name not in temp_fonts_data:
                                temp_fonts_data[family_name] = {}
                            if style_key not in temp_fonts_data[family_name]:
                                temp_fonts_data[family_name][style_key] = str(item)
            except Exception as e:
                print(_("warn_scanning_dir", directory, e))

        SYSTEM_FONTS = temp_fonts_data
        FONT_FAMILY_LIST_SORTED = sorted(SYSTEM_FONTS.keys())
        FONT_SCAN_COMPLETED.set()
        print(_("font_scan_completed", len(FONT_FAMILY_LIST_SORTED)))

        if callback_on_done:
            GLib.idle_add(callback_on_done)

    thread = threading.Thread(target=_scan, daemon=True)
    thread.start()

def _match_fontconfig(family_name, is_bold=False, is_italic=False):
    """Resolve a font family and style using Linux fontconfig (fc-match) directly."""
    if not family_name:
        return None

    clean_family = str(family_name).strip()
    cache_key = (clean_family, bool(is_bold), bool(is_italic))
    if cache_key in FONT_MATCH_CACHE:
        return FONT_MATCH_CACHE[cache_key]

    if platform.system() != "Linux":
        return None

    style_parts = []
    if is_bold:
        style_parts.append("bold")
    if is_italic:
        style_parts.append("italic")
    if not style_parts:
        style_parts.append("regular")

    pattern = f"{clean_family}:{':'.join(style_parts)}"
    try:
        res = subprocess.run(
            ["fc-match", "-f", "%{file}\n", pattern],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1.0,
            check=False
        )
        if res.returncode == 0 and res.stdout.strip():
            font_path = res.stdout.strip().split("\n")[0].strip()
            if font_path and os.path.isfile(font_path):
                FONT_MATCH_CACHE[cache_key] = font_path
                return font_path
    except Exception as e:
        print(f"DEBUG: fc-match failed for '{pattern}': {e}")

    FONT_MATCH_CACHE[cache_key] = None
    return None

def find_specific_font_variant(family_name, is_bold=False, is_italic=False):
    """Find specific font variant using cache, SYSTEM_FONTS, and fontconfig."""
    if not family_name:
        return None

    cache_key = (str(family_name).strip(), bool(is_bold), bool(is_italic))
    if cache_key in FONT_MATCH_CACHE and FONT_MATCH_CACHE[cache_key]:
        return FONT_MATCH_CACHE[cache_key]

    normalized_family_name = family_name.replace(" ", "").lower()
    
    sans_prefixes = ("arial", "helvetica", "calibri")
    serif_prefixes = ("times", "timesnewroman")
    mono_prefixes = ("courier", "couriernew")
    matched_alias = None
    for prefix in sans_prefixes:
        if normalized_family_name.startswith(prefix):
            matched_alias = "liberationsans"
            break
    if not matched_alias:
        for prefix in serif_prefixes:
            if normalized_family_name.startswith(prefix):
                matched_alias = "liberationserif"
                break
    if not matched_alias:
        for prefix in mono_prefixes:
            if normalized_family_name.startswith(prefix):
                matched_alias = "liberationmono"
                break
    if matched_alias:
        print(f"DEBUG: Mapping proprietary font '{family_name}' to '{matched_alias}'")
        normalized_family_name = matched_alias

    # 1. Try SYSTEM_FONTS if font scan has already completed
    if FONT_SCAN_COMPLETED.is_set():
        found_family_key = None
        if family_name in SYSTEM_FONTS:
            found_family_key = family_name
        else:
            for key in SYSTEM_FONTS:
                if key.replace(" ", "").lower() == normalized_family_name:
                    found_family_key = key
                    break

        if found_family_key:
            family_variants = SYSTEM_FONTS[found_family_key]
            if is_bold and is_italic and "BoldItalic" in family_variants:
                path = family_variants["BoldItalic"]
            elif is_bold and "Bold" in family_variants:
                path = family_variants["Bold"]
            elif is_italic and "Italic" in family_variants:
                path = family_variants["Italic"]
            elif "Regular" in family_variants:
                path = family_variants["Regular"]
            elif family_variants:
                path = next(iter(family_variants.values()))
            else:
                path = None

            if path and os.path.isfile(path):
                FONT_MATCH_CACHE[cache_key] = path
                return path

    # 2. Try fast Linux fontconfig match
    fc_path = _match_fontconfig(family_name, is_bold, is_italic)
    if fc_path and os.path.isfile(fc_path):
        FONT_MATCH_CACHE[cache_key] = fc_path
        return fc_path

    # 3. If font scan hasn't completed and fc-match didn't succeed, wait up to 2 seconds
    if not FONT_SCAN_COMPLETED.is_set():
        FONT_SCAN_COMPLETED.wait(timeout=2.0)
        if FONT_SCAN_COMPLETED.is_set():
            for key in SYSTEM_FONTS:
                if key.replace(" ", "").lower() == normalized_family_name:
                    family_variants = SYSTEM_FONTS[key]
                    if is_bold and is_italic and "BoldItalic" in family_variants:
                        path = family_variants["BoldItalic"]
                    elif is_bold and "Bold" in family_variants:
                        path = family_variants["Bold"]
                    elif is_italic and "Italic" in family_variants:
                        path = family_variants["Italic"]
                    elif "Regular" in family_variants:
                        path = family_variants["Regular"]
                    else:
                        path = next(iter(family_variants.values())) if family_variants else None
                    if path and os.path.isfile(path):
                        FONT_MATCH_CACHE[cache_key] = path
                        return path

    print(f"WARNING: Could not find any font file for family '{family_name}' (normalized: '{normalized_family_name}')")
    return None

UNICODE_FONT_PATH = None

def get_default_unicode_font_path():
    """Get the default unicode font path."""
    global UNICODE_FONT_PATH
    if UNICODE_FONT_PATH and os.path.isfile(UNICODE_FONT_PATH):
        return UNICODE_FONT_PATH

    preferred_defaults = ["Liberation Sans", "DejaVu Sans", "Noto Sans", "sans-serif"]
    for family in preferred_defaults:
        fc_path = _match_fontconfig(family, False, False)
        if fc_path and os.path.isfile(fc_path):
            UNICODE_FONT_PATH = fc_path
            print(f"Default Unicode font set to: {UNICODE_FONT_PATH}")
            return UNICODE_FONT_PATH

    if not FONT_SCAN_COMPLETED.is_set():
        FONT_SCAN_COMPLETED.wait(timeout=2.0)

    for family in preferred_defaults:
        path = find_specific_font_variant(family, False, False)
        if path and os.path.isfile(path):
            UNICODE_FONT_PATH = path
            print(f"Default Unicode font set to: {UNICODE_FONT_PATH}")
            return UNICODE_FONT_PATH

    if FONT_FAMILY_LIST_SORTED and SYSTEM_FONTS:
        for family_name in FONT_FAMILY_LIST_SORTED:
            if "Regular" in SYSTEM_FONTS[family_name]:
                UNICODE_FONT_PATH = SYSTEM_FONTS[family_name]["Regular"]
                print(f"Default Unicode font (fallback) set to: {UNICODE_FONT_PATH}")
                return UNICODE_FONT_PATH
        if FONT_FAMILY_LIST_SORTED:
            first_family = FONT_FAMILY_LIST_SORTED[0]
            if SYSTEM_FONTS[first_family]:
                UNICODE_FONT_PATH = next(iter(SYSTEM_FONTS[first_family].values()))
                print(f"Default Unicode font (absolute fallback) set to: {UNICODE_FONT_PATH}")
                return UNICODE_FONT_PATH

    print("CRITICAL: No fallback Unicode font could be determined after scan.")
    return None


def normalize_color(color_val):
    """Normalize color."""
    if color_val is None:
        return (0.0, 0.0, 0.0)

    if isinstance(color_val, int):
        blue = (color_val & 255) / 255.0
        green = ((color_val >> 8) & 255) / 255.0
        red = ((color_val >> 16) & 255) / 255.0
        return (red, green, blue)
    elif isinstance(color_val, float):
        val = color_val / 255.0 if color_val > 1.0 else color_val
        val = max(0.0, min(1.0, val))
        return (val, val, val)

    elif isinstance(color_val, (list, tuple)) and len(color_val) >= 3:
        rgb = list(color_val[:3])
        for i in range(3):
            if isinstance(rgb[i], (int, float)):
                val = float(rgb[i])
                if val > 1.0:
                    val = val / 255.0
                rgb[i] = max(0.0, min(1.0, val))
            else:
                rgb[i] = 0.0
        return tuple(rgb)

    return (0.0, 0.0, 0.0)
