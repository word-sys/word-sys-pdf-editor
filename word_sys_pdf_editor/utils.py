import os
import platform
from pathlib import Path
import re
import subprocess
import threading
import json
import shutil
from gi.repository import GLib
from .i18n import _, get_setting, set_setting

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

def get_font_cache_path():
    """Retrieve the persistent font cache file path."""
    cache_base = os.environ.get("XDG_CACHE_HOME")
    if cache_base:
        base = Path(cache_base)
    else:
        base = Path.home() / ".cache"
    cache_dir = base / "word-sys-pdf-editor"
    return cache_dir / "font_cache.json"

def load_persistent_font_cache(cache_path=None):
    """Load system font mappings from persistent disk cache if directory mtimes are unchanged.
    Returns True if successfully loaded from cache, False otherwise.
    """
    global SYSTEM_FONTS, FONT_FAMILY_LIST_SORTED, FONT_SCAN_COMPLETED
    if cache_path is None:
        cache_path = get_font_cache_path()

    if not cache_path.is_file():
        return False

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        if not isinstance(cache_data, dict) or cache_data.get("version") != 1:
            return False

        cached_mtimes = cache_data.get("dir_mtimes", {})
        font_dirs = _get_font_dirs()
        current_existing_dirs = {str(d): d for d in font_dirs if d.is_dir()}

        # Verify that all tracked directories exist and their mtimes match
        if set(cached_mtimes.keys()) != set(current_existing_dirs.keys()):
            return False

        for d_str, d_path in current_existing_dirs.items():
            current_mtime = d_path.stat().st_mtime
            if abs(current_mtime - float(cached_mtimes.get(d_str, 0.0))) > 0.001:
                return False

        SYSTEM_FONTS = cache_data.get("system_fonts", {})
        FONT_FAMILY_LIST_SORTED = cache_data.get("family_list", [])
        if not FONT_FAMILY_LIST_SORTED and SYSTEM_FONTS:
            FONT_FAMILY_LIST_SORTED = sorted(SYSTEM_FONTS.keys())

        if FONT_FAMILY_LIST_SORTED:
            FONT_SCAN_COMPLETED.set()
            return True
        return False

    except Exception as e:
        print(f"DEBUG: Could not load persistent font cache ({cache_path}): {e}")
        return False

def save_persistent_font_cache(fonts_data, family_list, font_dirs, cache_path=None):
    """Persist font mappings and directory mtimes atomically to disk."""
    if cache_path is None:
        cache_path = get_font_cache_path()

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        dir_mtimes = {}
        for d in font_dirs:
            if d.is_dir():
                try:
                    dir_mtimes[str(d)] = d.stat().st_mtime
                except OSError:
                    pass

        payload = {
            "version": 1,
            "dir_mtimes": dir_mtimes,
            "system_fonts": fonts_data,
            "family_list": family_list
        }

        temp_path = cache_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(temp_path, cache_path)
        return True
    except Exception as e:
        print(f"DEBUG: Failed to save persistent font cache ({cache_path}): {e}")
        return False

def _scan_system_fonts_direct(font_dirs):
    """Collect font file paths and parse family/style mappings using fast fontconfig query or fallback."""
    temp_fonts_data = {}
    found_files = []

    # Fast fontconfig listing path on Linux if fc-list is available
    if platform.system() == "Linux":
        fc_list_path = shutil.which("fc-list")
        if fc_list_path:
            try:
                res = subprocess.run(
                    [fc_list_path, "-f", "%{file}\n"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5.0,
                    check=False
                )
                if res.returncode == 0 and res.stdout:
                    for line in res.stdout.splitlines():
                        fpath = line.strip()
                        if fpath.lower().endswith((".ttf", ".otf")):
                            found_files.append(Path(fpath))
            except Exception as fc_err:
                print(f"DEBUG: fc-list scan failed, falling back to disk walk: {fc_err}")

    # Fallback to filesystem walk if fc-list produced no files or on non-Linux
    if not found_files:
        for directory in font_dirs:
            try:
                for item in list(directory.rglob('*.ttf')) + list(directory.rglob('*.otf')):
                    if item.is_file():
                        found_files.append(item)
            except Exception as e:
                print(_("warn_scanning_dir", directory, e))

    # Also include any embedded fonts directory if present
    embedded_dir = _get_embedded_font_dir()
    if embedded_dir and embedded_dir.is_dir():
        try:
            for item in list(embedded_dir.glob('*.ttf')) + list(embedded_dir.glob('*.otf')):
                if item.is_file() and item not in found_files:
                    found_files.append(item)
        except Exception:
            pass

    for item in found_files:
        try:
            family_name, style_key = parse_font_name(item)
            if family_name and style_key:
                if family_name not in temp_fonts_data:
                    temp_fonts_data[family_name] = {}
                if style_key not in temp_fonts_data[family_name]:
                    temp_fonts_data[family_name][style_key] = str(item)
        except Exception:
            pass

    return temp_fonts_data

def scan_system_fonts_async(callback_on_done=None, force_rescan=False, cache_path=None):
    """Scan system font directories or load from persistent cache."""
    font_dirs = _get_font_dirs()

    # Attempt instant cache load first (< 5ms) unless explicitly forced to re-scan
    if not force_rescan and load_persistent_font_cache(cache_path=cache_path):
        print(_("font_scan_completed", len(FONT_FAMILY_LIST_SORTED)))
        if callback_on_done:
            GLib.idle_add(callback_on_done)
        return

    def _scan():
        global SYSTEM_FONTS, FONT_FAMILY_LIST_SORTED, FONT_SCAN_COMPLETED
        print("Scanning system and embedded fonts...")
        temp_fonts_data = _scan_system_fonts_direct(font_dirs)

        SYSTEM_FONTS = temp_fonts_data
        FONT_FAMILY_LIST_SORTED = sorted(SYSTEM_FONTS.keys())
        FONT_SCAN_COMPLETED.set()
        save_persistent_font_cache(SYSTEM_FONTS, FONT_FAMILY_LIST_SORTED, font_dirs, cache_path=cache_path)
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
    """Resolve default Unicode fallback font path on system."""
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
    """Convert RGB tuple, int, or float representation into standard (0.0-1.0) RGB float tuple."""
    if color_val is None:
        return (0.0, 0.0, 0.0)

    if isinstance(color_val, str):
        c_str = color_val.strip().lstrip("#")
        if len(c_str) == 6:
            try:
                r = int(c_str[0:2], 16) / 255.0
                g = int(c_str[2:4], 16) / 255.0
                b = int(c_str[4:6], 16) / 255.0
                return (r, g, b)
            except ValueError:
                pass
        elif len(c_str) == 3:
            try:
                r = int(c_str[0] * 2, 16) / 255.0
                g = int(c_str[1] * 2, 16) / 255.0
                b = int(c_str[2] * 2, 16) / 255.0
                return (r, g, b)
            except ValueError:
                pass

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


def point_to_segment_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate the shortest Euclidean distance from a point to a 2D line segment."""
    import math
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def point_in_polygon(px: float, py: float, vertices: list) -> bool:
    """Check if point (px, py) lies inside the polygon defined by vertices."""
    n = len(vertices)
    if n < 3:
        return False
    inside = False
    p1x, p1y = vertices[0]
    for i in range(1, n + 1):
        p2x, p2y = vertices[i % n]
        if py > min(p1y, p2y):
            if py <= max(p1y, p2y):
                if px <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (py - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or px <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


class DecodedPixbufCache:
    """Bounded LRU cache of decoded, display-sized GdkPixbuf images.

    The canvas used to re-create a `GdkPixbuf.PixbufLoader` and re-decode the image bytes on
    every frame (a 4000x3000 JPEG costs ~237 ms per decode). The cache is keyed on the encoded
    `bytes` object itself: hashing a bytes object is cached by Python and an identical object
    matches by identity, so a hit costs microseconds, and new bytes (replace, rotate, undo/redo)
    can never see a stale pixbuf. Images larger than `max_dimension` on their longest side are
    downscaled once, which also bounds decoded memory for huge photos.
    """

    def __init__(self, max_bytes=96 * 1024 * 1024, max_entries=32, max_dimension=2560):
        from collections import OrderedDict
        self._entries = OrderedDict()   # encoded bytes -> (pixbuf or None, decoded_size)
        self._total = 0
        self._lock = threading.Lock()
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.max_dimension = max_dimension
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _decode(image_bytes, max_dimension):
        from gi.repository import GdkPixbuf
        loader = GdkPixbuf.PixbufLoader.new()
        try:
            loader.write(image_bytes)
        finally:
            loader.close()
        pixbuf = loader.get_pixbuf()
        if pixbuf is None:
            return None
        w, h = pixbuf.get_width(), pixbuf.get_height()
        longest = max(w, h)
        if max_dimension and longest > max_dimension:
            ratio = max_dimension / float(longest)
            pixbuf = pixbuf.scale_simple(
                max(1, int(w * ratio)), max(1, int(h * ratio)), GdkPixbuf.InterpType.BILINEAR
            ) or pixbuf
        return pixbuf

    def get(self, image_bytes):
        """Return the decoded pixbuf for encoded image bytes, or None if undecodable."""
        if not image_bytes:
            return None
        if not isinstance(image_bytes, bytes):
            try:
                return self._decode(bytes(image_bytes), self.max_dimension)
            except Exception:
                return None
        with self._lock:
            entry = self._entries.get(image_bytes)
            if entry is not None:
                self._entries.move_to_end(image_bytes)
                self.hits += 1
                return entry[0]
        self.misses += 1
        try:
            pixbuf = self._decode(image_bytes, self.max_dimension)
        except Exception:
            pixbuf = None
        size = pixbuf.get_byte_length() if pixbuf is not None else 0
        with self._lock:
            if image_bytes in self._entries:
                self._total -= self._entries[image_bytes][1]
            self._entries[image_bytes] = (pixbuf, size)
            self._entries.move_to_end(image_bytes)
            self._total += size
            while self._entries and (
                len(self._entries) > self.max_entries
                or (self._total > self.max_bytes and len(self._entries) > 1)
            ):
                _key, (_pb, sz) = self._entries.popitem(last=False)
                self._total -= sz
        return pixbuf

    def set_limits(self, max_bytes=None, max_entries=None, max_dimension=None):
        """Adjust budgets (used by Eco mode) and evict down to the new limits."""
        with self._lock:
            if max_bytes is not None:
                self.max_bytes = max_bytes
            if max_entries is not None:
                self.max_entries = max_entries
            if max_dimension is not None and max_dimension != self.max_dimension:
                self.max_dimension = max_dimension
                self._entries.clear()   # decoded sizes depend on max_dimension
                self._total = 0
            while self._entries and (
                len(self._entries) > self.max_entries
                or (self._total > self.max_bytes and len(self._entries) > 1)
            ):
                _key, (_pb, sz) = self._entries.popitem(last=False)
                self._total -= sz

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._total = 0

    @property
    def total_bytes(self):
        return self._total

    def __len__(self):
        return len(self._entries)


DECODED_PIXBUF_CACHE = DecodedPixbufCache()


def get_decoded_pixbuf(image_bytes):
    """Decode (or fetch from cache) a display-sized pixbuf for the canvas."""
    return DECODED_PIXBUF_CACHE.get(image_bytes)
