from __future__ import annotations

import os
import shutil
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import fitz

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
    """Find and return the directory containing the requested language model.

    Raises FileNotFoundError if the language model is not installed.
    """
    # Multi-language strings (e.g. "eng+tur") check primary language first
    primary = lang_code.split("+")[0].strip()
    filename = f"{primary}.traineddata"

    for s_dir in get_tessdata_search_dirs():
        try:
            candidate = s_dir / filename
            if candidate.is_file() and candidate.stat().st_size > 0:
                return str(s_dir)
        except Exception:
            continue

    raise FileNotFoundError(
        f"Language model '{primary}.traineddata' not found in any search path. "
        f"Please download it via the OCR Language Manager."
    )


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
