from __future__ import annotations

import io
import os
import shutil
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import fitz
import numpy as np
from PIL import Image

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


def perform_ocr_on_pixmap(
    pix: fitz.Pixmap,
    language: str = "eng",
    compress: bool = True,
    tessdata_dir: Optional[str] = None,
) -> bytes:
    """Execute in-process Tesseract OCR on a pixmap and return a 1-page searchable PDF in bytes.

    Uses PyMuPDF's statically built-in C-engine.
    """
    # PDFOCR cannot accept pixmaps with an alpha channel; safely drop alpha if present
    if getattr(pix, "alpha", 0):
        pix = fitz.Pixmap(pix, 0)

    if tessdata_dir is None:
        tessdata_dir = get_best_tessdata_dir_for_lang(language)

    # pix.pdfocr_tobytes runs the C-engine directly
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
    dpi: int = 150,
    tessdata_dir: Optional[str] = None,
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
    )
    return fitz.open(stream=ocr_bytes)


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
