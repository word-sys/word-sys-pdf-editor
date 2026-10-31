from __future__ import annotations

import io
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import fitz
import numpy as np
from PIL import Image, ImageEnhance

SUPPORTED_LANGUAGES = {
    "eng": {"name": "English", "native": "English", "size_mb": 4.1},
    "tur": {"name": "Turkish", "native": "Türkçe", "size_mb": 2.2},
    "deu": {"name": "German", "native": "Deutsch", "size_mb": 2.5},
    "fra": {"name": "French", "native": "Français", "size_mb": 1.5},
    "spa": {"name": "Spanish", "native": "Español", "size_mb": 1.2},
    "ita": {"name": "Italian", "native": "Italiano", "size_mb": 1.6},
    "rus": {"name": "Russian", "native": "Русский", "size_mb": 3.5},
}

DEFAULT_TESSDATA_REPO_URL = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main"
)

@dataclass
class ScannedPageAnalysis:
    page_number: int
    is_scanned: bool
    text_char_count: int
    image_count: int
    image_coverage_ratio: float
    has_selectable_text: bool
    details: dict = field(default_factory=dict)


def get_tessdata_user_dir() -> Path:
    """Return the user profile data directory for storing downloaded OCR models.

    Adheres strictly to the XDG Base Directory Specification ($XDG_DATA_HOME).
    Works universally inside Flatpak sandboxes (~/.var/app/.../data),
    AppImage runs, and standard system installs (~/.local/share/...).
    """
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        base_dir = Path(xdg_data)
    else:
        base_dir = Path.home() / ".local" / "share"

    target = base_dir / "word-sys-pdf-editor" / "tessdata"
    return target


def get_tessdata_search_dirs() -> list[Path]:
    """Return an ordered list of search directories for Tesseract language models.

    Search priority:
    1. User Profile Directory ($XDG_DATA_HOME/word-sys-pdf-editor/tessdata)
    2. Application Bundle Paths (Flatpak /app/share/tessdata, AppImage APPDIR/usr/share/tessdata, Package root)
    3. System paths ($TESSDATA_PREFIX, /usr/share/tesseract-ocr/..., /usr/share/tessdata)
    """
    dirs: list[Path] = []

    user_dir = get_tessdata_user_dir()
    dirs.append(user_dir)

    appdir = os.environ.get("APPDIR")
    if appdir:
        dirs.append(Path(appdir) / "usr" / "share" / "tessdata")
        dirs.append(Path(appdir) / "usr" / "share" / "tesseract-ocr" / "tessdata")

    flatpak_dir = Path("/app/share/tessdata")
    if flatpak_dir.is_dir():
        dirs.append(flatpak_dir)

    pkg_dir = Path(__file__).resolve().parent / "tessdata"
    if pkg_dir.is_dir():
        dirs.append(pkg_dir)

    env_prefix = os.environ.get("TESSDATA_PREFIX")
    if env_prefix:
        p = Path(env_prefix)
        if (p / "tessdata").is_dir():
            dirs.append(p / "tessdata")
        dirs.append(p)

    system_candidates = [
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tesseract-ocr/tessdata"),
        Path("/usr/share/tessdata"),
        Path("/usr/local/share/tessdata"),
    ]
    for cand in system_candidates:
        if cand.is_dir() and cand not in dirs:
            dirs.append(cand)

    return dirs


def get_available_languages() -> dict[str, dict]:
    """Scan all search paths and return installed and supported OCR languages.

    Returns a dict mapping language codes to their metadata, installation status,
    source location, and absolute file path.
    """
    user_dir = get_tessdata_user_dir()
    search_dirs = get_tessdata_search_dirs()

    # Pre-populate known supported languages
    result: dict[str, dict] = {}
    for code, meta in SUPPORTED_LANGUAGES.items():
        result[code] = {
            "code": code,
            "name": meta["name"],
            "native": meta["native"],
            "size_mb": meta["size_mb"],
            "is_installed": False,
            "source": None,
            "path": None,
        }

    for s_dir in search_dirs:
        try:
            if not s_dir.is_dir():
                continue
            for model_file in s_dir.glob("*.traineddata"):
                code = model_file.stem
                if code == "osd":
                    continue

                is_user = s_dir.resolve() == user_dir.resolve()
                is_bundle = (
                    "app" in s_dir.parts or "APPDIR" in str(s_dir)
                )

                if is_user:
                    source = "user"
                elif is_bundle:
                    source = "bundle"
                else:
                    source = "system"

                if code in result:
                    if not result[code]["is_installed"]:
                        result[code]["is_installed"] = True
                        result[code]["source"] = source
                        result[code]["path"] = str(model_file)
                else:
                    # Discovered non-standard language model on system
                    result[code] = {
                        "code": code,
                        "name": code.upper(),
                        "native": code,
                        "size_mb": round(model_file.stat().st_size / (1024 * 1024), 1),
                        "is_installed": True,
                        "source": source,
                        "path": str(model_file),
                    }
        except Exception:
            continue

    return result


def get_best_tessdata_dir_for_lang(lang_code: str) -> str:
    """Find and return the directory containing the requested language model(s).

    Supports single languages (e.g. "eng") and compound bilingual/multilingual
    languages (e.g. "eng+tur", "deu+fra+eng").
    If models reside in different search paths, unifies them seamlessly into a
    composite directory so PyMuPDF's C-engine can load all models simultaneously.

    Raises FileNotFoundError if any requested language model is not installed.
    """
    clean = lang_code.strip().lower()
    codes = [c.strip() for c in clean.split("+") if c.strip()]
    if not codes:
        codes = ["eng"]

    all_langs = get_available_languages()
    missing = [c for c in codes if not all_langs.get(c, {}).get("is_installed")]
    if missing:
        missing_str = ", ".join(f"'{m}.traineddata'" for m in missing)
        raise FileNotFoundError(
            f"Language model(s) {missing_str} not found in any search path. "
            f"Please download via the OCR Language Manager."
        )

    # Collect directory for each code
    dirs: list[Path] = []
    for c in codes:
        p = all_langs[c]["path"]
        dirs.append(Path(p).parent)

    # If all models live in the exact same directory, return it directly
    if all(d.resolve() == dirs[0].resolve() for d in dirs):
        return str(dirs[0])

    # Models are distributed across different search paths (e.g. system + user profile).
    # Create a composite directory linking all requested models so Tesseract C-engine
    # finds all models in a single location.
    user_tess = get_tessdata_user_dir()
    user_tess.mkdir(parents=True, exist_ok=True)
    composite_dir = user_tess / "_composite"
    composite_dir.mkdir(parents=True, exist_ok=True)

    for c in codes:
        src = Path(all_langs[c]["path"])
        dst = composite_dir / f"{c}.traineddata"
        if not dst.exists() or dst.resolve() != src.resolve():
            try:
                if dst.is_symlink() or dst.exists():
                    dst.unlink()
                dst.symlink_to(src)
            except Exception:
                shutil.copy2(src, dst)

    return str(composite_dir)


def resolve_compound_language_model_dirs(lang_code: str) -> list[Path]:
    """Return a deduplicated list of directory Paths containing the models for the specified language code(s)."""
    clean = lang_code.strip().lower()
    codes = [c.strip() for c in clean.split("+") if c.strip()]
    if not codes:
        codes = ["eng"]

    all_langs = get_available_languages()
    dirs: list[Path] = []
    seen: set[Path] = set()
    for c in codes:
        info = all_langs.get(c, {})
        p = info.get("path")
        if p:
            parent = Path(p).parent.resolve()
            if parent not in seen:
                seen.add(parent)
                dirs.append(Path(p).parent)
    return dirs



def validate_language_code(lang_code: str) -> tuple[bool, str, list[str]]:
    """Validate a single or compound language code against installed models.

    Returns:
        (is_valid, normalized_code, missing_languages)
    """
    clean = lang_code.strip().lower()
    codes = [c.strip() for c in clean.split("+") if c.strip()]
    if not codes:
        codes = ["eng"]

    all_langs = get_available_languages()
    missing = [c for c in codes if not all_langs.get(c, {}).get("is_installed")]
    normalized = "+".join(codes)
    return (len(missing) == 0, normalized, missing)


def get_language_display_name(lang_code: str) -> str:
    """Return a human-friendly display name for a single or compound language string."""
    clean = lang_code.strip().lower()
    codes = [c.strip() for c in clean.split("+") if c.strip()]
    if not codes:
        return "English"

    all_langs = get_available_languages()
    names = []
    for c in codes:
        meta = all_langs.get(c)
        if meta:
            names.append(meta.get("name") or c.upper())
        else:
            names.append(c.upper())

    if len(names) == 1:
        return names[0]
    return " + ".join(names)


def download_language_model(
    lang_code: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    repo_url: str = DEFAULT_TESSDATA_REPO_URL,
) -> Path:
    clean_code = lang_code.strip().lower()
    filename = f"{clean_code}.traineddata"
    url = f"{repo_url}/{filename}"

    dest_dir = get_tessdata_user_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_file = dest_dir / filename
    temp_file = dest_dir / f"{filename}.tmp_{os.getpid()}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "word-sys-pdf-editor/1.11.2 (X11; Linux)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            total_size_header = resp.headers.get("Content-Length")
            total_size = int(total_size_header) if total_size_header else 0

            downloaded = 0
            chunk_size = 64 * 1024  # 64 KB

            with open(temp_file, "wb") as out_f:
                while True:
                    if cancel_check and cancel_check():
                        raise InterruptedError("Download cancelled by user.")

                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break

                    out_f.write(chunk)
                    downloaded += len(chunk)

                    if progress_callback:
                        progress_callback(downloaded, total_size)

        os.replace(temp_file, target_file)
        return target_file

    except Exception:
        if temp_file.is_file():
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise


def delete_user_language_model(lang_code: str) -> bool:
    """Remove a downloaded language model from the user profile directory.

    Only deletes files inside the user's data directory; system/bundle models are untouched.
    """
    clean_code = lang_code.strip().lower()
    user_file = get_tessdata_user_dir() / f"{clean_code}.traineddata"
    if user_file.is_file():
        user_file.unlink()
        return True
    return False


def is_scanned_page(
    page: fitz.Page,
    min_text_chars: int = 25,
    min_image_area_ratio: float = 0.35,
) -> ScannedPageAnalysis:
    """Analyze a page to determine if it is a scanned document lacking selectable text.

    Heuristics:
    1. Extract all text on the page (`page.get_text().strip()`).
    2. Check for raster image objects (`page.get_images()`).
    3. Measure the cumulative surface area covered by raster images.
    4. If text length < min_text_chars and image area ratio >= min_image_area_ratio,
       the page is classified as a scanned image page.
    """
    page_num = page.number
    text = page.get_text().strip()
    char_count = len(text)
    images = page.get_images()

    page_rect = page.rect
    page_area = max(page_rect.width * page_rect.height, 1.0)

    total_image_area = 0.0
    for img in images:
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
            for r in rects:
                intersect = r & page_rect
                if not intersect.is_empty:
                    total_image_area += intersect.width * intersect.height
        except Exception:
            continue

    coverage_ratio = min(total_image_area / page_area, 1.0)
    has_text = char_count >= min_text_chars

    is_scanned = (not has_text) and (len(images) > 0) and (coverage_ratio >= min_image_area_ratio)

    return ScannedPageAnalysis(
        page_number=page_num,
        is_scanned=is_scanned,
        text_char_count=char_count,
        image_count=len(images),
        image_coverage_ratio=coverage_ratio,
        has_selectable_text=has_text,
        details={
            "page_width": page_rect.width,
            "page_height": page_rect.height,
            "images": len(images),
        },
    )


def analyze_document_scans(doc: fitz.Document) -> dict:
    """Analyze all pages in a document and return scan statistics."""
    pages_analysis = []
    scanned_pages = []

    for i in range(len(doc)):
        analysis = is_scanned_page(doc[i])
        pages_analysis.append(analysis)
        if analysis.is_scanned:
            scanned_pages.append(i)

    return {
        "total_pages": len(doc),
        "scanned_count": len(scanned_pages),
        "scanned_pages": scanned_pages,
        "analyses": pages_analysis,
    }


def estimate_word_confidence(text: str) -> float:
    """Estimate OCR word recognition confidence based on lexical and typographic characteristics.
    
    Used when reading preexisting PDF text layers or as a fast sandbox fallback.
    Returns a score between 0.0 and 1.0.
    """
    t = str(text).strip()
    if not t:
        return 0.0
    bad_chars = set("~|`^_{}[]<>\\#%*")
    num_bad = sum(1 for c in t if c in bad_chars)
    if num_bad > 0:
        return max(0.10, 0.45 - 0.12 * num_bad)

    if not any(c.isalnum() for c in t):
        return 0.30

    letters = sum(1 for c in t if c.isalpha())
    digits = sum(1 for c in t if c.isdigit())
    if letters > 0 and digits > 0 and len(t) <= 4:
        return 0.55
    if t.isdigit() or t.replace(".", "").replace(",", "").isdigit():
        return 0.90
    if len(t) == 1:
        return 0.65
    if t.isupper() or t.istitle() or t.islower():
        return 0.92
    return 0.78


def preprocess_image_for_ocr(
    img: Image.Image,
    auto_invert: bool = True,
    enhance_contrast: bool = True,
    block_size: int = 64,
) -> Image.Image:
    """Preprocess PIL Image for maximum OCR recognition accuracy.
    
    1. Adaptive Dark-Background Inversion:
       Detects dark regions or inverted colors (e.g. white text on black background in
       flowcharts, diagrams, code blocks, night-mode documents) and adaptively inverts
       dark blocks to light background so Tesseract can recognize characters cleanly.
    2. Dynamic Contrast Enhancement:
       Sharpens character edges and widens dynamic range for fine diagram stems and text.
    """
    try:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        arr = np.array(img)
        h, w = arr.shape[:2]
        is_rgb = (len(arr.shape) == 3)

        if auto_invert:
            gray = np.array(img.convert("L"))
            bs = max(32, min(block_size, min(h, w)))
            for y in range(0, h, bs):
                for x in range(0, w, bs):
                    by1 = min(y + bs, h)
                    bx1 = min(x + bs, w)
                    block_gray = gray[y:by1, x:bx1]
                    if np.mean(block_gray) < 120:
                        if is_rgb:
                            arr[y:by1, x:bx1] = 255 - arr[y:by1, x:bx1]
                        else:
                            arr[y:by1, x:bx1] = 255 - block_gray

        res_img = Image.fromarray(arr)
        if enhance_contrast:
            enhancer = ImageEnhance.Contrast(res_img)
            res_img = enhancer.enhance(1.35)
        return res_img
    except Exception as e:
        print(f"Warning: preprocess_image_for_ocr failed: {e}")
        return img


def preprocess_pixmap_for_ocr(
    pix: fitz.Pixmap,
    auto_invert: bool = True,
    enhance_contrast: bool = True,
) -> fitz.Pixmap:
    """Preprocess a PyMuPDF pixmap for optimal OCR text recognition."""
    if not auto_invert and not enhance_contrast:
        return pix
    try:
        if getattr(pix, "alpha", 0):
            pix = fitz.Pixmap(pix, 0)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        preprocessed = preprocess_image_for_ocr(img, auto_invert=auto_invert, enhance_contrast=enhance_contrast)
        return fitz.Pixmap(fitz.csRGB, preprocessed.width, preprocessed.height, preprocessed.tobytes(), False)
    except Exception as e:
        print(f"Warning: preprocess_pixmap_for_ocr failed: {e}")
        return pix


def auto_invert_dark_background(pix: fitz.Pixmap, threshold: int = 120) -> fitz.Pixmap:
    """Invert dark backgrounds or inverted scans for optimal OCR text recognition."""
    return preprocess_pixmap_for_ocr(pix, auto_invert=True, enhance_contrast=False)


def perform_ocr_on_pixmap(
    pix: fitz.Pixmap,
    language: str = "eng",
    compress: bool = True,
    tessdata_dir: Optional[str] = None,
    auto_invert: bool = True,
    enhance_contrast: bool = True,
) -> bytes:
    """Execute in-process Tesseract OCR on a pixmap and return a 1-page searchable PDF in bytes.

    Uses PyMuPDF's statically built-in C-engine.
    """
    if getattr(pix, "alpha", 0):
        pix = fitz.Pixmap(pix, 0)

    if auto_invert or enhance_contrast:
        pix = preprocess_pixmap_for_ocr(pix, auto_invert=auto_invert, enhance_contrast=enhance_contrast)

    if tessdata_dir is None:
        tessdata_dir = get_best_tessdata_dir_for_lang(language)

    ocr_bytes = pix.pdfocr_tobytes(
        language=language,
        compress=compress,
        tessdata=tessdata_dir,
    )
    return ocr_bytes


def perform_ocr_on_page(
    doc: fitz.Document,
    page_num: int,
    language: str = "eng",
    dpi: int = 200,
    tessdata_dir: Optional[str] = None,
    auto_invert: bool = True,
    enhance_contrast: bool = True,
) -> fitz.Document:
    """Execute OCR on a specific page of a document and return a 1-page fitz.Document containing recognized text layer."""
    if page_num < 0 or page_num >= len(doc):
        raise IndexError(f"Page index {page_num} out of bounds (total: {len(doc)})")

    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    ocr_bytes = perform_ocr_on_pixmap(
        pix,
        language=language,
        compress=True,
        tessdata_dir=tessdata_dir,
        auto_invert=auto_invert,
        enhance_contrast=enhance_contrast,
    )
    return fitz.open(stream=ocr_bytes)


def find_tesseract_binary() -> Optional[str]:
    """Locate the tesseract CLI binary across system PATH, Flatpak (/app/bin), and AppImage ($APPDIR/usr/bin)."""
    found = shutil.which("tesseract")
    if found:
        return found

    appdir = os.environ.get("APPDIR")
    if appdir:
        cand = Path(appdir) / "usr" / "bin" / "tesseract"
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)

    flatpak_cand = Path("/app/bin/tesseract")
    if flatpak_cand.is_file() and os.access(flatpak_cand, os.X_OK):
        return str(flatpak_cand)

    return None


def extract_ocr_words_with_confidence(
    pix: fitz.Pixmap,
    page_rect: Optional[fitz.Rect] = None,
    language: str = "eng",
    tessdata_dir: Optional[str] = None,
    auto_invert: bool = True,
    enhance_contrast: bool = True,
) -> list[dict]:
    """Extract recognized words with precise bounding boxes and confidence scores (0.0 - 1.0).
    
    If system tesseract binary is available, runs TSV extraction for 100% exact per-word confidence.
    Otherwise, performs in-process OCR via PyMuPDF and computes heuristic confidence.
    """
    if getattr(pix, "alpha", 0):
        pix = fitz.Pixmap(pix, 0)

    if auto_invert or enhance_contrast:
        pix = preprocess_pixmap_for_ocr(pix, auto_invert=auto_invert, enhance_contrast=enhance_contrast)

    if tessdata_dir is None:
        tessdata_dir = get_best_tessdata_dir_for_lang(language)

    pw = float(page_rect.width) if page_rect else float(pix.width)
    ph = float(page_rect.height) if page_rect else float(pix.height)
    sx = pw / max(float(pix.width), 1.0)
    sy = ph / max(float(pix.height), 1.0)

    tess_path = find_tesseract_binary()
    if tess_path:
        try:
            img_bytes = pix.tobytes("png")
            cmd = [tess_path, "stdin", "stdout", "-l", language, "tsv"]
            if tessdata_dir:
                cmd.extend(["--tessdata-dir", tessdata_dir])
            proc = subprocess.run(cmd, input=img_bytes, capture_output=True, timeout=25)
            if proc.returncode == 0 and proc.stdout:
                tsv_lines = proc.stdout.decode("utf-8", errors="ignore").splitlines()
                words_list: list[dict] = []
                for line in tsv_lines[1:]:
                    parts = line.split("\t")
                    if len(parts) >= 12 and parts[0] == "5":
                        raw_text = parts[11].strip()
                        if not raw_text:
                            continue
                        lx = float(parts[6]) * sx
                        ty = float(parts[7]) * sy
                        bw = float(parts[8]) * sx
                        bh = float(parts[9]) * sy
                        conf_val = max(0.0, min(1.0, float(parts[10]) / 100.0))
                        words_list.append({
                            "bbox": (lx, ty, lx + bw, ty + bh),
                            "text": raw_text,
                            "confidence": conf_val,
                        })
                if words_list:
                    return words_list
        except Exception as e:
            print(f"Notice: TSV extraction fallback to in-process OCR: {e}")

    ocr_bytes = pix.pdfocr_tobytes(
        language=language,
        compress=True,
        tessdata=tessdata_dir,
    )
    words_list = []
    try:
        temp_doc = fitz.open(stream=ocr_bytes)
        for w in temp_doc[0].get_text("words"):
            if len(w) >= 5 and str(w[4]).strip():
                text_str = str(w[4]).strip()
                wx0 = float(w[0]) * (pw / max(temp_doc[0].rect.width, 1.0))
                wy0 = float(w[1]) * (ph / max(temp_doc[0].rect.height, 1.0))
                wx1 = float(w[2]) * (pw / max(temp_doc[0].rect.width, 1.0))
                wy1 = float(w[3]) * (ph / max(temp_doc[0].rect.height, 1.0))
                words_list.append({
                    "bbox": (min(wx0, wx1), min(wy0, wy1), max(wx0, wx1), max(wy0, wy1)),
                    "text": text_str,
                    "confidence": estimate_word_confidence(text_str),
                })
        temp_doc.close()
    except Exception as e:
        print(f"Error extracting in-process OCR words: {e}")

    return words_list


def extract_ocr_text_from_page(
    doc: fitz.Document,
    page_num: int,
    language: str = "eng",
    dpi: int = 150,
    tessdata_dir: Optional[str] = None,
) -> str:
    """Perform OCR on a page and extract recognized text as a string."""
    ocr_doc = perform_ocr_on_page(
        doc,
        page_num=page_num,
        language=language,
        dpi=dpi,
        tessdata_dir=tessdata_dir,
    )
    try:
        return ocr_doc[0].get_text()
    finally:
        ocr_doc.close()


def check_ocr_support() -> tuple[bool, str]:
    """Verify that PyMuPDF supports OCR in the current runtime environment."""
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 10, 10), 1)
    if not hasattr(pix, "pdfocr_tobytes"):
        return False, "PyMuPDF was compiled without MuPDF Tesseract OCR support."

    installed_langs = [
        code for code, data in get_available_languages().items() if data["is_installed"]
    ]
    if not installed_langs:
        return True, "OCR engine ready, but no language models are installed."

    return True, f"OCR engine ready. Installed languages: {', '.join(installed_langs)}"


def detect_page_skew_angle(page: fitz.Page, dpi: int = 100, max_angle: float = 12.0) -> float:
    """Detect skew angle of text on a scanned page using horizontal projection profile variance.

    Returns the angle in degrees needed to straighten the page (positive or negative).
    If the detected skew is negligible (< 0.35 deg) or page lacks prominent text lines,
    returns 0.0 (indicating already straight).
    """
    try:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        w, h = img.size
        scale = min(1.0, 600.0 / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), resample=Image.Resampling.BILINEAR)

        arr = np.array(img)
        binary = (arr < 190).astype(np.float32)
        if np.sum(binary) < 50:
            return 0.0

        best_angle = 0.0
        max_score = -1.0

        # Coarse sweep: -max_angle to +max_angle in 1.0 deg steps
        for angle in np.arange(-max_angle, max_angle + 0.5, 1.0):
            rot = Image.fromarray((binary * 255).astype(np.uint8)).rotate(
                angle, resample=Image.Resampling.NEAREST, fillcolor=0
            )
            proj = np.sum(np.array(rot) > 0, axis=1)
            score = float(np.sum(np.diff(proj) ** 2))
            if score > max_score:
                max_score = score
                best_angle = angle

        # Fine sweep: +-1.0 deg around best_angle in 0.1 deg steps
        coarse_best = best_angle
        for angle in np.arange(coarse_best - 1.0, coarse_best + 1.05, 0.1):
            rot = Image.fromarray((binary * 255).astype(np.uint8)).rotate(
                angle, resample=Image.Resampling.NEAREST, fillcolor=0
            )
            proj = np.sum(np.array(rot) > 0, axis=1)
            score = float(np.sum(np.diff(proj) ** 2))
            if score > max_score:
                max_score = score
                best_angle = angle

        res = round(float(best_angle), 2)
        return res if abs(res) >= 0.35 else 0.0
    except Exception as e:
        print(f"Warning: skew detection failed: {e}")
        return 0.0


def deskew_scanned_page(doc: fitz.Document, page_num: int, angle: float, dpi: int = 150) -> bool:
    """Straighten a tilted scanned page by rotating the raster image by `angle` degrees."""
    if not doc or page_num < 0 or page_num >= len(doc):
        return False
    if abs(angle) < 0.2:
        return True
    try:
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        deskewed = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255), expand=False)
        out_buf = io.BytesIO()
        deskewed.save(out_buf, format="PNG")

        rect = page.rect
        page.clean_contents()
        page.add_redact_annot(rect)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=1, text=1)
        page.insert_image(rect, stream=out_buf.getvalue(), keep_proportion=False)
        return True
    except Exception as e:
        print(f"Warning: deskew_scanned_page failed on page {page_num}: {e}")
        return False


def detect_page_orientation(page: fitz.Page, dpi: int = 100, language: str = "eng", tessdata_dir: Optional[str] = None) -> int:
    """Detect coarse orientation (0, 90, 180, 270) needed to make page text upright."""
    try:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        img_std = img.resize((400, 400))
        arr = (np.array(img_std) < 180).astype(np.float32)
        if np.sum(arr) < 50:
            return 0

        h_var = float(np.var(np.diff(np.sum(arr, axis=1))))
        v_var = float(np.var(np.diff(np.sum(arr, axis=0))))

        is_vertical_lines = (v_var > h_var * 1.35)
        orientations = [90, 270] if is_vertical_lines else [0, 180]

        best_score = -9999
        best_orient = 0
        symbols = set("}{][|~\\/^_\"`")

        orig_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        for rot in orientations:
            rot_img = orig_img.rotate(rot, expand=True) if rot != 0 else orig_img
            px = fitz.Pixmap(fitz.csRGB, rot_img.width, rot_img.height, rot_img.tobytes(), False)
            try:
                ocr_bytes = perform_ocr_on_pixmap(px, language=language, compress=True, tessdata_dir=tessdata_dir)
                test_doc = fitz.open("pdf", ocr_bytes)
                words = [w[4] for w in test_doc[0].get_text("words")]
                test_doc.close()

                score = 0
                for w in words:
                    text = str(w).strip()
                    if not text:
                        continue
                    if any(c in symbols for c in text):
                        score -= 3
                        continue
                    if text.istitle() or text.islower() or text.isupper():
                        score += 2
                    else:
                        score -= 1

                if score > best_score:
                    best_score = score
                    best_orient = rot
            except Exception:
                pass

        return best_orient
    except Exception as e:
        print(f"Warning: detect_page_orientation failed: {e}")
        return 0


def format_ocr_eta(eta_seconds: Optional[float]) -> str:
    """Format remaining OCR time in seconds into a concise human-readable string (e.g. '~12s', '~1m 20s')."""
    if eta_seconds is None or eta_seconds < 0:
        return ""
    if eta_seconds == 0:
        return "0s"
    secs = max(1, int(round(float(eta_seconds))))
    if secs < 60:
        return f"~{secs}s"
    mins, rem = divmod(secs, 60)
    if rem > 0:
        return f"~{mins}m {rem}s"
    return f"~{mins}m"


class StreamingOCRPipeline:
    """Streaming OCR worker that processes pages incrementally and publishes per-page results as soon as ready.

    Supports pause/resume, cancellation without corrupting already-completed pages, and live ETA tracking.
    """

    def __init__(
        self,
        doc: fitz.Document,
        target_pages: list[int],
        language: str = "eng",
        dpi: int = 200,
        tessdata_dir: Optional[str] = None,
        auto_deskew: bool = True,
        auto_rotate: bool = True,
        auto_invert: bool = True,
        enhance_contrast: bool = True,
        on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
        on_page_ready: Optional[Callable[[int, dict[str, Any], dict[str, Any]], None]] = None,
        on_finished: Optional[Callable[[dict[str, Any]], None]] = None,
        dispatch_callback: Optional[Callable[..., Any]] = None,
        external_cancel_check: Optional[Callable[[], bool]] = None,
    ):
        self.doc = doc
        self.target_pages = [int(p) for p in target_pages]
        self.language = language
        self.dpi = dpi
        self.tessdata_dir = tessdata_dir
        self.auto_deskew = auto_deskew
        self.auto_rotate = auto_rotate
        self.auto_invert = auto_invert
        self.enhance_contrast = enhance_contrast
        self.on_progress = on_progress
        self.on_page_ready = on_page_ready
        self.on_finished = on_finished
        self.dispatch_callback = dispatch_callback
        self.external_cancel_check = external_cancel_check

        self._cancel_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

        self.completed_pages: list[int] = []
        self.page_durations: list[float] = []
        self.eta_seconds: Optional[float] = None
        self.results: dict[int, Any] = {}
        self.ocr_words_by_page: dict[int, list[dict[str, Any]]] = {}

    @property
    def is_paused(self) -> bool:
        return not self._resume_event.is_set() and not self.is_cancelled

    @property
    def is_cancelled(self) -> bool:
        if self._cancel_event.is_set():
            return True
        if callable(self.external_cancel_check):
            try:
                if self.external_cancel_check():
                    self._cancel_event.set()
                    return True
            except Exception:
                pass
        return False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def pause(self) -> None:
        """Pause processing before the next page begins."""
        if not self._cancel_event.is_set():
            self._resume_event.clear()

    def resume(self) -> None:
        """Resume a paused OCR pipeline."""
        self._resume_event.set()

    def toggle_pause(self) -> bool:
        """Toggle pause state and return True if now paused, False if resumed."""
        if self.is_paused:
            self.resume()
            return False
        self.pause()
        return True

    def cancel(self) -> None:
        """Request cancellation and wake any paused worker thread."""
        self._cancel_event.set()
        self._resume_event.set()

    def _emit(self, callback: Optional[Callable[..., Any]], *args: Any) -> None:
        if not callable(callback):
            return
        if callable(self.dispatch_callback):
            def _wrapped():
                callback(*args)
                return False
            self.dispatch_callback(_wrapped)
        else:
            callback(*args)

    def _wait_if_paused(self) -> bool:
        """Block while paused; return True if cancelled while waiting."""
        while not self._resume_event.is_set():
            if self.is_cancelled:
                return True
            self._resume_event.wait(timeout=0.03)
        return self.is_cancelled

    def start(self, sync: bool = False) -> "StreamingOCRPipeline":
        """Start the streaming OCR pipeline on a daemon worker thread (or synchronously if sync=True)."""
        self._is_running = True
        if sync:
            self._run()
        else:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        from . import pdf_handler

        total = len(self.target_pages)
        tessdata_dir = self.tessdata_dir
        try:
            if tessdata_dir is None and total > 0 and not self.is_cancelled:
                try:
                    tessdata_dir = get_best_tessdata_dir_for_lang(self.language)
                except Exception as td_err:
                    print(f"OCR tessdata lookup notice: {td_err}")
                    tessdata_dir = None

            for idx, p_num in enumerate(self.target_pages):
                if self._wait_if_paused():
                    break
                if self.doc is None or getattr(self.doc, "is_closed", False):
                    break
                if p_num < 0 or p_num >= len(self.doc):
                    continue

                pre_progress = {
                    "current_index": idx + 1,
                    "total_pages": total,
                    "page_num": p_num,
                    "fraction": idx / max(total, 1),
                    "eta_seconds": self.eta_seconds,
                    "eta_text": format_ocr_eta(self.eta_seconds),
                    "paused": self.is_paused,
                }
                self._emit(self.on_progress, pre_progress)

                if self._wait_if_paused():
                    break

                t0 = time.perf_counter()
                pre_snapshot = None
                ocr_doc = None
                ocr_words: list[dict[str, Any]] = []
                page_mutated_by_prep = False

                try:
                    doc_lock = pdf_handler.get_doc_lock(self.doc)
                    if doc_lock is not None:
                        with doc_lock:
                            if getattr(self.doc, "is_closed", False):
                                break
                            pdf_handler.save_page_snapshot(self.doc, p_num, force=True)
                            pre_snapshot = pdf_handler._page_snapshots.get((id(self.doc), p_num))
                            p_obj = self.doc[p_num]

                            if self.auto_rotate and not self.is_cancelled:
                                try:
                                    rot_angle = detect_page_orientation(
                                        p_obj,
                                        dpi=100,
                                        language=self.language,
                                        tessdata_dir=tessdata_dir,
                                    )
                                    if rot_angle in (90, 180, 270):
                                        p_obj.set_rotation((p_obj.rotation + rot_angle) % 360)
                                        page_mutated_by_prep = True
                                except Exception as ro_err:
                                    print(f"Warning: auto-rotate failed on page {p_num}: {ro_err}")

                            if self.auto_deskew and not self.is_cancelled:
                                try:
                                    if is_scanned_page(p_obj).is_scanned:
                                        skew = detect_page_skew_angle(p_obj, dpi=100)
                                        if abs(skew) >= 0.35:
                                            deskew_scanned_page(self.doc, p_num, skew, dpi=self.dpi)
                                            page_mutated_by_prep = True
                                except Exception as sk_err:
                                    print(f"Warning: auto-deskew failed on page {p_num}: {sk_err}")
                    else:
                        pdf_handler.save_page_snapshot(self.doc, p_num, force=True)
                        pre_snapshot = pdf_handler._page_snapshots.get((id(self.doc), p_num))

                    if self.is_cancelled:
                        if page_mutated_by_prep and pre_snapshot is not None:
                            pdf_handler._page_snapshots[(id(self.doc), p_num)] = pre_snapshot
                            pdf_handler.restore_page_from_snapshot(self.doc, p_num)
                        break

                    ocr_doc = perform_ocr_on_page(
                        self.doc,
                        page_num=p_num,
                        language=self.language,
                        dpi=self.dpi,
                        tessdata_dir=tessdata_dir,
                        auto_invert=self.auto_invert,
                        enhance_contrast=self.enhance_contrast,
                    )

                    if self.is_cancelled:
                        if ocr_doc is not None and hasattr(ocr_doc, "close"):
                            try:
                                ocr_doc.close()
                            except Exception:
                                pass
                        if page_mutated_by_prep and pre_snapshot is not None:
                            pdf_handler._page_snapshots[(id(self.doc), p_num)] = pre_snapshot
                            pdf_handler.restore_page_from_snapshot(self.doc, p_num)
                        break

                    if doc_lock is not None:
                        with doc_lock:
                            if not getattr(self.doc, "is_closed", False):
                                ocr_words = pdf_handler.extract_ocr_words_for_page(self.doc[p_num], ocr_doc)
                    else:
                        ocr_words = pdf_handler.extract_ocr_words_for_page(self.doc[p_num], ocr_doc)

                    elapsed = max(0.0005, time.perf_counter() - t0)
                    self.page_durations.append(elapsed)
                    avg_dur = sum(self.page_durations) / len(self.page_durations)
                    remaining = max(0, total - (idx + 1))
                    self.eta_seconds = avg_dur * remaining

                    self.completed_pages.append(p_num)
                    self.results[p_num] = ocr_doc
                    self.ocr_words_by_page[p_num] = ocr_words

                    post_progress = {
                        "current_index": idx + 1,
                        "total_pages": total,
                        "page_num": p_num,
                        "fraction": (idx + 1) / max(total, 1),
                        "eta_seconds": self.eta_seconds,
                        "eta_text": format_ocr_eta(self.eta_seconds),
                        "paused": self.is_paused,
                    }
                    page_payload = {
                        "page_num": p_num,
                        "ocr_doc": ocr_doc,
                        "ocr_words": ocr_words,
                        "pre_snapshot": pre_snapshot,
                        "language": self.language,
                        "dpi": self.dpi,
                    }
                    self._emit(self.on_page_ready, p_num, page_payload, post_progress)
                except Exception as err:
                    print(f"Error executing streaming OCR on page {p_num}: {err}")
        finally:
            self._is_running = False
            summary = {
                "target_pages": list(self.target_pages),
                "completed_pages": list(self.completed_pages),
                "results": self.results,
                "ocr_words_by_page": self.ocr_words_by_page,
                "cancelled": self.is_cancelled,
                "eta_seconds": 0.0,
                "language": self.language,
                "dpi": self.dpi,
            }
            self._emit(self.on_finished, summary)

