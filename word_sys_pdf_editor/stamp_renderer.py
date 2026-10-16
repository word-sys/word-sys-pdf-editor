from __future__ import annotations

import io
import logging
from typing import Optional, Tuple

try:
    import cairo
    import gi
    gi.require_version('Pango', '1.0')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Pango, PangoCairo
    PANGO_AVAILABLE = True
except (ImportError, ValueError):
    PANGO_AVAILABLE = False

try:
    from PIL import Image
    from pyhanko.pdf_utils.images import PdfImage
    from pyhanko.stamp import StaticStampStyle
    PYHANKO_STAMP_AVAILABLE = True
except ImportError:
    Image = None
    PdfImage = None
    StaticStampStyle = None
    PYHANKO_STAMP_AVAILABLE = False


def is_stamp_renderer_available() -> bool:
    return PANGO_AVAILABLE and PYHANKO_STAMP_AVAILABLE


def render_stamp_pil_image(
    signer_name: str,
    date_str: str,
    reason: Optional[str] = None,
    location: Optional[str] = None,
    contact: Optional[str] = None,
    organization: Optional[str] = None,
    verification_text: Optional[str] = None,
    handwritten_bytes: Optional[bytes] = None,
    width_pt: float = 220.0,
    height_pt: float = 52.0,
    scale_factor: float = 2.5,
) -> Optional[Any]:
    """
    Render an Adobe Acrobat style multilingual digital signature stamp.

    Returns:
        PIL.Image instance or None if renderer unavailable.
    """
    if not is_stamp_renderer_available():
        return None

    px_w = int(max(100.0, width_pt) * scale_factor)
    px_h = int(max(30.0, height_pt) * scale_factor)

    try:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px_w, px_h)
        ctx = cairo.Context(surface)
        ctx.scale(scale_factor, scale_factor)

        w = float(width_pt)
        h = float(height_pt)

        # Background card
        ctx.set_source_rgba(0.98, 0.99, 1.0, 0.96)
        ctx.rectangle(0.5, 0.5, w - 1.0, h - 1.0)
        ctx.fill()

        # Border
        ctx.set_source_rgba(0.25, 0.45, 0.75, 0.65)
        ctx.set_line_width(0.8)
        ctx.rectangle(0.5, 0.5, w - 1.0, h - 1.0)
        ctx.stroke()

        text_x = 8.0
        text_avail_w = w - 16.0

        # Optional handwritten image on the left
        if handwritten_bytes:
            try:
                hw_pil = Image.open(io.BytesIO(handwritten_bytes)).convert("RGBA")
                hw_buf = io.BytesIO()
                hw_pil.save(hw_buf, format="PNG")
                hw_surf = cairo.ImageSurface.create_from_png(io.BytesIO(hw_buf.getvalue()))

                img_w = float(hw_surf.get_width())
                img_h = float(hw_surf.get_height())
                max_img_w = max(35.0, min(65.0, w * 0.28))
                max_img_h = h - 8.0

                scale = min(max_img_w / img_w, max_img_h / img_h)
                dest_w = img_w * scale
                dest_h = img_h * scale
                dest_x = 6.0
                dest_y = (h - dest_h) / 2.0

                ctx.save()
                ctx.translate(dest_x, dest_y)
                ctx.scale(scale, scale)
                ctx.set_source_surface(hw_surf, 0, 0)
                ctx.paint_with_alpha(0.85)
                ctx.restore()

                text_x = dest_x + dest_w + 8.0
                text_avail_w = w - text_x - 8.0
            except Exception as hw_exc:
                logging.debug("Could not render handwritten image on stamp: %s", hw_exc)

        # Render metadata with Pango
        layout = PangoCairo.create_layout(ctx)
        layout.set_width(int(text_avail_w * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)

        lines = [
            f"<b>Digitally signed by:</b> {signer_name or 'Signer'}",
            f"<b>Date:</b> {date_str}",
        ]
        if reason:
            lines.append(f"<b>Reason:</b> {reason}")
        if location:
            lines.append(f"<b>Location:</b> {location}")
        if contact:
            lines.append(f"<b>Contact:</b> {contact}")
        if verification_text:
            lines.append(f"<span foreground='#1a5fb4'>{verification_text}</span>")

        markup_text = "\n".join(lines)
        layout.set_markup(markup_text, -1)

        font_desc = Pango.font_description_from_string("Sans 6.5")
        layout.set_font_description(font_desc)

        ctx.set_source_rgb(0.12, 0.12, 0.12)
        ctx.move_to(text_x, 5.0)
        PangoCairo.show_layout(ctx, layout)

        out_buf = io.BytesIO()
        surface.write_to_png(out_buf)
        out_buf.seek(0)
        return Image.open(out_buf)

    except Exception as exc:
        logging.error("Failed to render stamp PIL image: %s", exc)
        return None


def create_opentype_stamp_style(
    signer_name: str,
    date_str: str,
    reason: Optional[str] = None,
    location: Optional[str] = None,
    contact: Optional[str] = None,
    organization: Optional[str] = None,
    verification_text: Optional[str] = None,
    handwritten_bytes: Optional[bytes] = None,
    width_pt: float = 220.0,
    height_pt: float = 52.0,
) -> Optional[Any]:
    """
    Create a pyHanko StaticStampStyle from an OpenType Pango-rendered stamp image.
    """
    if not is_stamp_renderer_available():
        return None

    pil_img = render_stamp_pil_image(
        signer_name=signer_name,
        date_str=date_str,
        reason=reason,
        location=location,
        contact=contact,
        organization=organization,
        verification_text=verification_text,
        handwritten_bytes=handwritten_bytes,
        width_pt=width_pt,
        height_pt=height_pt,
    )
    if pil_img is None:
        return None

    try:
        pdf_image = PdfImage(pil_img)
        return StaticStampStyle(background=pdf_image)
    except Exception as exc:
        logging.error("Failed to create StaticStampStyle: %s", exc)
        return None
