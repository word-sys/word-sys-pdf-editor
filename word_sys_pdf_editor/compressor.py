from __future__ import annotations

import io
import math
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List, Callable, Any

import pymupdf as fitz
from PIL import Image

PRESET_MAXIMUM = "maximum"      # 72 DPI, 50% quality
PRESET_BALANCED = "balanced"    # 150 DPI, 75% quality
PRESET_HIGH_QUALITY = "high"    # 300 DPI, 85% quality
PRESET_LOSSLESS = "lossless"    # Structure deflate and dead xref purge without re-encoding
PRESET_TARGET = "target"        # Binary search target size solver


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


@dataclass
class CompressionOptions:
    target_dpi: Optional[int] = 150
    jpeg_quality: int = 75
    compress_images: bool = True
    grayscale: bool = False
    deflate: bool = True
    clean: bool = True
    garbage: int = 4


@dataclass
class CompressionResult:
    pdf_bytes: bytes
    original_size: int
    compressed_size: int
    savings_bytes: int
    savings_percent: float
    achieved_target: bool = True
    options_used: Optional[CompressionOptions] = None
    iterations_count: int = 1
    message: Optional[str] = None


def get_preset_options(preset_name: str) -> CompressionOptions:
    name = (preset_name or "").lower().strip()
    if name == PRESET_MAXIMUM:
        return CompressionOptions(target_dpi=72, jpeg_quality=50, compress_images=True, grayscale=False)
    elif name == PRESET_HIGH_QUALITY:
        return CompressionOptions(target_dpi=300, jpeg_quality=85, compress_images=True, grayscale=False)
    elif name == PRESET_LOSSLESS:
        return CompressionOptions(target_dpi=None, jpeg_quality=95, compress_images=False, grayscale=False)
    else:
        return CompressionOptions(target_dpi=150, jpeg_quality=75, compress_images=True, grayscale=False)


def compress_pdf_bytes(
    pdf_bytes: bytes,
    options: Optional[CompressionOptions] = None,
) -> CompressionResult:
    if options is None:
        options = get_preset_options(PRESET_BALANCED)

    orig_len = len(pdf_bytes)
    if not pdf_bytes:
        return CompressionResult(
            pdf_bytes=b"",
            original_size=0,
            compressed_size=0,
            savings_bytes=0,
            savings_percent=0.0,
            achieved_target=True,
            options_used=options,
        )

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logging.error("Failed to parse PDF for compression: %s", e)
        return CompressionResult(
            pdf_bytes=pdf_bytes,
            original_size=orig_len,
            compressed_size=orig_len,
            savings_bytes=0,
            savings_percent=0.0,
            achieved_target=False,
            options_used=options,
            message=f"Invalid PDF stream: {e}",
        )

    try:
        if options.compress_images:
            mask_xrefs = set()
            for xref in range(1, doc.xref_length()):
                try:
                    sm = doc.xref_get_key(xref, "SMask")
                    if sm[0] == "xref":
                        mask_xrefs.add(int(sm[1].split()[0]))
                    mk = doc.xref_get_key(xref, "Mask")
                    if mk[0] == "xref":
                        mask_xrefs.add(int(mk[1].split()[0]))
                except Exception:
                    pass

            rect_map: Dict[int, Tuple[float, float]] = {}
            for page in doc:
                try:
                    page_images = page.get_images()
                except Exception:
                    continue
                for img_tuple in page_images:
                    xref = img_tuple[0]
                    if xref <= 0 or xref in mask_xrefs:
                        continue
                    rects = page.get_image_rects(xref)
                    w_pt = max((r.width for r in rects), default=0.0)
                    h_pt = max((r.height for r in rects), default=0.0)
                    if xref not in rect_map:
                        rect_map[xref] = (w_pt, h_pt)
                    else:
                        cur_w, cur_h = rect_map[xref]
                        if w_pt > cur_w or h_pt > cur_h:
                            rect_map[xref] = (max(cur_w, w_pt), max(cur_h, h_pt))

            all_image_xrefs: Dict[int, Tuple[float, float]] = {}
            for xref in range(1, doc.xref_length()):
                if xref in mask_xrefs:
                    continue
                try:
                    sub = doc.xref_get_key(xref, "Subtype")
                    if sub[0] == "name" and sub[1] == "/Image":
                        all_image_xrefs[xref] = rect_map.get(xref, (0.0, 0.0))
                except Exception:
                    continue

            if not all_image_xrefs and rect_map:
                all_image_xrefs = rect_map

            for xref, (disp_w_pt, disp_h_pt) in all_image_xrefs.items():
                try:
                    img_dict = doc.extract_image(xref)
                    if not img_dict or "image" not in img_dict:
                        continue
                    raw_bytes = img_dict["image"]
                    orig_img_len = len(raw_bytes)
                    if orig_img_len < 512:
                        continue

                    smask_xref = img_dict.get("smask", 0)
                    if smask_xref > 0:
                        try:
                            base_pix = fitz.Pixmap(doc, xref)
                            mask_pix = fitz.Pixmap(doc, smask_xref)
                            combined_pix = fitz.Pixmap(base_pix, mask_pix)
                            pil_img = Image.frombytes("RGBA", (combined_pix.width, combined_pix.height), combined_pix.samples)
                        except Exception:
                            pil_img = Image.open(io.BytesIO(raw_bytes))
                    else:
                        pil_img = Image.open(io.BytesIO(raw_bytes))

                    orig_w, orig_h = pil_img.size

                    target_w, target_h = orig_w, orig_h
                    if options.target_dpi:
                        if disp_w_pt > 0 and disp_h_pt > 0:
                            req_w = int(round(disp_w_pt / 72.0 * options.target_dpi))
                            req_h = int(round(disp_h_pt / 72.0 * options.target_dpi))
                        else:
                            if options.target_dpi <= 72:
                                max_dim = 1000
                            elif options.target_dpi <= 150:
                                max_dim = 1800
                            else:
                                max_dim = 3200
                            scale_cap = min(max_dim / orig_w, max_dim / orig_h) if (orig_w > max_dim or orig_h > max_dim) else 1.0
                            req_w = int(round(orig_w * scale_cap))
                            req_h = int(round(orig_h * scale_cap))

                        if req_w > 0 and req_h > 0 and (req_w < orig_w or req_h < orig_h):
                            scale = min(req_w / orig_w, req_h / orig_h)
                            if scale < 0.95:
                                target_w = max(1, int(round(orig_w * scale)))
                                target_h = max(1, int(round(orig_h * scale)))

                    if target_w != orig_w or target_h != orig_h:
                        pil_img = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

                    if options.grayscale and pil_img.mode not in ("1", "L"):
                        pil_img = pil_img.convert("L")

                    has_alpha = pil_img.mode in ("RGBA", "LA") or ("transparency" in pil_img.info)
                    candidates = []

                    if has_alpha:
                        buf_png = io.BytesIO()
                        pil_img.save(buf_png, format="PNG", optimize=True)
                        candidates.append(buf_png.getvalue())
                    else:
                        im_rgb = pil_img if pil_img.mode in ("L", "RGB") else pil_img.convert("RGB")
                        buf_jpg = io.BytesIO()
                        im_rgb.save(
                            buf_jpg,
                            format="JPEG",
                            quality=max(10, min(95, options.jpeg_quality)),
                            optimize=True,
                            progressive=False,
                        )
                        candidates.append(buf_jpg.getvalue())

                        buf_png = io.BytesIO()
                        pil_img.save(buf_png, format="PNG", optimize=True)
                        candidates.append(buf_png.getvalue())

                    if candidates:
                        best_bytes = min(candidates, key=len)
                        if len(best_bytes) < orig_img_len:
                            doc[0].replace_image(xref, stream=best_bytes)

                except Exception as img_exc:
                    logging.debug("Could not recompress image xref %s: %s", xref, img_exc)

        out_c = doc.tobytes(
            deflate=options.deflate,
            garbage=options.garbage,
            clean=True,
            deflate_images=True,
            deflate_fonts=True,
        )
        out_nc = doc.tobytes(
            deflate=options.deflate,
            garbage=options.garbage,
            clean=False,
            deflate_images=True,
            deflate_fonts=True,
        )
        compressed_bytes = out_c if len(out_c) < len(out_nc) else out_nc

    finally:
        doc.close()

    comp_len = len(compressed_bytes)
    if comp_len >= orig_len:
        compressed_bytes = pdf_bytes
        comp_len = orig_len

    savings_bytes = max(0, orig_len - comp_len)
    savings_pct = round((savings_bytes / orig_len * 100.0), 1) if orig_len > 0 else 0.0

    return CompressionResult(
        pdf_bytes=compressed_bytes,
        original_size=orig_len,
        compressed_size=comp_len,
        savings_bytes=savings_bytes,
        savings_percent=savings_pct,
        achieved_target=True,
        options_used=options,
        iterations_count=1,
    )


def solve_target_size(
    pdf_bytes: bytes,
    target_bytes: int,
    tolerance_ratio: float = 0.05,
    max_iterations: int = 7,
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
) -> CompressionResult:
    orig_len = len(pdf_bytes)
    if orig_len <= target_bytes:
        lossless_opts = get_preset_options(PRESET_LOSSLESS)
        res = compress_pdf_bytes(pdf_bytes, options=lossless_opts)
        res.achieved_target = True
        res.iterations_count = 1
        res.message = "Document is already smaller than the target size."
        return res

    lossless_opts = get_preset_options(PRESET_LOSSLESS)
    lossless_res = compress_pdf_bytes(pdf_bytes, options=lossless_opts)
    if lossless_res.compressed_size <= target_bytes:
        lossless_res.achieved_target = True
        lossless_res.iterations_count = 1
        lossless_res.message = "Target size achieved with lossless optimization."
        return lossless_res

    floor_opts = CompressionOptions(target_dpi=72, jpeg_quality=15, compress_images=True)
    floor_res = compress_pdf_bytes(pdf_bytes, options=floor_opts)
    if floor_res.compressed_size > target_bytes:
        floor_res.achieved_target = False
        floor_res.iterations_count = 2
        floor_res.message = (
            f"Target size of {target_bytes / (1024*1024):.2f} MB could not be reached. "
            f"Maximum achievable compression is {floor_res.compressed_size / (1024*1024):.2f} MB."
        )
        return floor_res

    chosen_dpi = 72
    for candidate_dpi in (300, 150, 72):
        test_opts = CompressionOptions(target_dpi=candidate_dpi, jpeg_quality=25, compress_images=True)
        test_res = compress_pdf_bytes(pdf_bytes, options=test_opts)
        if test_res.compressed_size <= target_bytes:
            chosen_dpi = candidate_dpi
            break

    low_q = 15
    high_q = 92
    best_res: Optional[CompressionResult] = floor_res
    best_opts = floor_opts
    iterations = 0

    while low_q <= high_q and iterations < max_iterations:
        iterations += 1
        mid_q = (low_q + high_q) // 2
        cur_opts = CompressionOptions(target_dpi=chosen_dpi, jpeg_quality=mid_q, compress_images=True)
        cur_res = compress_pdf_bytes(pdf_bytes, options=cur_opts)

        if progress_callback:
            try:
                progress_callback(iterations, max_iterations, cur_res.compressed_size)
            except Exception:
                pass

        if cur_res.compressed_size <= target_bytes:
            best_res = cur_res
            best_opts = cur_opts
            low_q = mid_q + 1
        else:
            high_q = mid_q - 1

    if best_res is not None:
        best_res.achieved_target = best_res.compressed_size <= target_bytes
        best_res.options_used = best_opts
        best_res.iterations_count = iterations
        best_res.message = (
            f"Target size met at {chosen_dpi} DPI with JPEG quality {best_opts.jpeg_quality}%."
        )
        return best_res

    return floor_res
