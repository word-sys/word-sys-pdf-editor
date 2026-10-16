# word-sys-pdf-editor - Digital Signature Management Module
# PAdES-compliant PKCS#7 digital signature generation, verification, and tamper detection.

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any, Tuple, List, Dict, Optional

# Suppress loud certvalidator tracebacks on self-signed / untrusted certificates
logging.getLogger("pyhanko_certvalidator").setLevel(logging.CRITICAL)
logging.getLogger("pyhanko.sign.validation").setLevel(logging.CRITICAL)

try:
    import pyhanko
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.images import PdfImage
    from pyhanko.sign import fields, signers, validation
    from pyhanko.sign.signers import SimpleSigner, PdfSignatureMetadata, PdfSigner
    from pyhanko.stamp import TextStampStyle
    PYHANKO_AVAILABLE = True
except ImportError:
    PYHANKO_AVAILABLE = False


def is_pyhanko_available() -> bool:
    """Return True if pyHanko is available in the current environment."""
    return PYHANKO_AVAILABLE


def load_pkcs12_certificate(
    pfx_data_or_path: bytes | str,
    passphrase: str | bytes | None = None,
) -> Tuple[Optional[Any], Optional[Dict[str, Any]], Optional[str]]:
    """
    Load a PKCS#12 (.p12 / .pfx) software certificate and private key.

    Returns:
        (signer, cert_info, error_message)
    """
    if not PYHANKO_AVAILABLE:
        return None, None, "pyHanko library is required for digital signatures"

    passphrase_bytes: Optional[bytes] = None
    if passphrase is not None:
        if isinstance(passphrase, str):
            passphrase_bytes = passphrase.encode("utf-8")
        else:
            passphrase_bytes = passphrase

    try:
        if isinstance(pfx_data_or_path, (bytes, bytearray)):
            signer = SimpleSigner.load_pkcs12_data(
                pfx_data_or_path,
                other_certs=(),
                passphrase=passphrase_bytes,
            )
        else:
            with open(pfx_data_or_path, "rb") as f:
                data = f.read()
            signer = SimpleSigner.load_pkcs12_data(
                data,
                other_certs=(),
                passphrase=passphrase_bytes,
            )
    except Exception as exc:
        err_msg = str(exc)
        if "passphrase" in err_msg.lower() or "mac" in err_msg.lower() or "password" in err_msg.lower():
            return None, None, "Invalid passphrase or password-protected certificate"
        return None, None, f"Failed to load certificate: {err_msg}"

    if signer is None or signer.signing_cert is None:
        return None, None, "Certificate could not be loaded from archive"

    cert = signer.signing_cert
    cert_info: Dict[str, Any] = {}

    try:
        subject_dict = cert.subject.native if hasattr(cert.subject, "native") else {}
        cert_info["subject_cn"] = subject_dict.get("common_name", signer.subject_name or "Unknown")
        cert_info["subject_org"] = subject_dict.get("organization_name", "")
        cert_info["subject_friendly"] = cert.subject.human_friendly if hasattr(cert.subject, "human_friendly") else str(cert.subject)
    except Exception:
        cert_info["subject_cn"] = signer.subject_name or "Unknown"
        cert_info["subject_org"] = ""
        cert_info["subject_friendly"] = cert_info["subject_cn"]

    try:
        issuer_dict = cert.issuer.native if hasattr(cert.issuer, "native") else {}
        cert_info["issuer_cn"] = issuer_dict.get("common_name", "")
        cert_info["issuer_org"] = issuer_dict.get("organization_name", "")
        cert_info["issuer_friendly"] = cert.issuer.human_friendly if hasattr(cert.issuer, "human_friendly") else str(cert.issuer)
    except Exception:
        cert_info["issuer_cn"] = ""
        cert_info["issuer_org"] = ""
        cert_info["issuer_friendly"] = ""

    try:
        tbs = cert["tbs_certificate"]
        validity = tbs["validity"]
        not_before = validity["not_before"].native
        not_after = validity["not_after"].native
        cert_info["not_before"] = not_before
        cert_info["not_after"] = not_after
        now = datetime.now(timezone.utc)
        if not_before.tzinfo is None:
            not_before = not_before.replace(tzinfo=timezone.utc)
        if not_after.tzinfo is None:
            not_after = not_after.replace(tzinfo=timezone.utc)
        cert_info["is_expired"] = now > not_after or now < not_before
    except Exception:
        cert_info["not_before"] = None
        cert_info["not_after"] = None
        cert_info["is_expired"] = False

    try:
        cert_info["serial_number"] = str(cert.serial_number)
    except Exception:
        cert_info["serial_number"] = ""

    try:
        cert_info["sha256_fingerprint"] = cert.sha256.hex()
    except Exception:
        cert_info["sha256_fingerprint"] = ""

    return signer, cert_info, None


def sign_pdf_bytes(
    pdf_bytes: bytes,
    pfx_data_or_path: bytes | str,
    passphrase: str | bytes | None = None,
    field_name: Optional[str] = None,
    reason: Optional[str] = None,
    location: Optional[str] = None,
    contact_info: Optional[str] = None,
    signer_name: Optional[str] = None,
    page_index: int = 0,
    box: Optional[Tuple[float, float, float, float]] = None,
    page_height: Optional[float] = None,
    page_width: Optional[float] = None,
    visual_stamp: bool = True,
    signature_image_bytes: Optional[bytes] = None,
    custom_stamp_text: Optional[str] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Digitally sign a PDF document using pyHanko (PAdES / PKCS#7 incremental signing).

    Parameters:
        pdf_bytes: Raw bytes of the document to sign.
        pfx_data_or_path: PKCS#12 certificate file path or raw bytes.
        passphrase: Password to decrypt private key.
        field_name: Name of signature field (e.g. Signature_1).
        reason: Stated reason for signature.
        location: Stated signing location.
        contact_info: Contact information.
        signer_name: Name to render on stamp (defaults to cert Common Name).
        page_index: 0-indexed page number for visible stamp.
        box: (x, y, width, height) in canvas/screen top-left coordinates.
        page_height: Height of target page in points (needed for coordinate conversion).
        page_width: Width of target page in points (needed for default position layout).
        visual_stamp: If True, render visible cryptographic stamp on target page.
        signature_image_bytes: Optional PNG/JPEG image bytes for handwritten signature.
        custom_stamp_text: Optional override for stamp text format string.

    Returns:
        (signed_pdf_bytes, error_message)
    """
    if not PYHANKO_AVAILABLE:
        return None, "pyHanko library is required for digital signatures"

    signer, cert_info, err = load_pkcs12_certificate(pfx_data_or_path, passphrase=passphrase)
    if err or signer is None or cert_info is None:
        return None, err or "Failed to load signing certificate"

    if not field_name:
        field_name = f"Signature_{int(datetime.now().timestamp())}"

    display_name = signer_name or cert_info.get("subject_cn") or "Signer"
    display_reason = reason or "I approve this document"
    display_location = location or ""
    display_contact = contact_info or ""

    try:
        in_stream = io.BytesIO(pdf_bytes)
        writer = IncrementalPdfFileWriter(in_stream)

        meta = PdfSignatureMetadata(
            field_name=field_name,
            reason=display_reason,
            location=display_location if display_location else None,
            contact_info=display_contact if display_contact else None,
            name=display_name,
            subfilter=fields.SigSeedSubFilter.PADES,
        )

        stamp_style = None
        new_field_spec = None

        if visual_stamp:
            if page_height is None or page_width is None:
                try:
                    import pymupdf
                    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as tmp_doc:
                        if 0 <= page_index < len(tmp_doc):
                            page_rect = tmp_doc[page_index].rect
                            if page_height is None:
                                page_height = page_rect.height
                            if page_width is None:
                                page_width = page_rect.width
                except Exception:
                    pass
            if page_height is None:
                page_height = 842.0
            if page_width is None:
                page_width = 595.0

            if box is None:
                stamp_w = 220.0
                stamp_h = 65.0
                stamp_x = max(20.0, page_width - stamp_w - 40.0)
                stamp_y = max(20.0, page_height - stamp_h - 50.0)
                box = (stamp_x, stamp_y, stamp_w, stamp_h)

            bx, by, bw, bh = box
            # Convert screen top-left coordinates to PDF user-space bottom-left coordinates
            pdf_x0 = int(bx)
            pdf_y0 = int(page_height - (by + bh))
            pdf_x1 = int(bx + bw)
            pdf_y1 = int(page_height - by)

            # Ensure valid non-inverted box bounds
            if pdf_x1 <= pdf_x0:
                pdf_x1 = pdf_x0 + 150
            if pdf_y1 <= pdf_y0:
                pdf_y1 = pdf_y0 + 50

            pdf_box = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            new_field_spec = fields.SigFieldSpec(
                sig_field_name=field_name,
                on_page=page_index,
                box=pdf_box,
            )

            # Build visual text stamp appearance
            if custom_stamp_text:
                stamp_text = custom_stamp_text
            else:
                stamp_text = "Digitally signed by: %(signer)s\nDate: %(ts)s\nReason: %(reason)s"
                if display_location:
                    stamp_text += "\nLocation: %(location)s"

            # Optional handwritten background image
            bg_image = None
            if signature_image_bytes:
                try:
                    from PIL import Image
                    pil_img = Image.open(io.BytesIO(signature_image_bytes))
                    bg_image = PdfImage(image=pil_img)
                except Exception as img_exc:
                    logging.warning(f"Failed to load signature image: {img_exc}")

            stamp_style = TextStampStyle(
                stamp_text=stamp_text,
                border_width=1,
                background=bg_image,
                background_opacity=0.35 if bg_image else 1.0,
            )
        else:
            # Invisible signature
            new_field_spec = fields.SigFieldSpec(
                sig_field_name=field_name,
                on_page=page_index,
                box=None,
            )

        pdf_signer = PdfSigner(
            signature_meta=meta,
            signer=signer,
            stamp_style=stamp_style,
            new_field_spec=new_field_spec,
        )

        out_stream = io.BytesIO()
        appearance_params = {
            "signer": display_name,
            "reason": display_reason,
            "location": display_location,
        }

        pdf_signer.sign_pdf(
            writer,
            output=out_stream,
            appearance_text_params=appearance_params,
        )

        signed_bytes = out_stream.getvalue()
        if not signed_bytes:
            return None, "Signature processing produced empty document stream"

        return signed_bytes, None

    except Exception as exc:
        return None, f"Digital signing failed: {exc}"


def inspect_pdf_signatures(pdf_bytes_or_path: bytes | str) -> List[Dict[str, Any]]:
    """
    Inspect all digital signatures in a PDF and determine cryptographic integrity.

    Returns:
        List of signature metadata dictionaries with integrity and validation details.
    """
    if not PYHANKO_AVAILABLE:
        return []

    results: List[Dict[str, Any]] = []

    try:
        if isinstance(pdf_bytes_or_path, (bytes, bytearray)):
            stream = io.BytesIO(pdf_bytes_or_path)
        else:
            with open(pdf_bytes_or_path, "rb") as f:
                stream = io.BytesIO(f.read())

        reader = PdfFileReader(stream)
        embedded_sigs = getattr(reader, "embedded_signatures", [])
        if not embedded_sigs:
            return []

        for sig in embedded_sigs:
            info: Dict[str, Any] = {
                "field_name": getattr(sig, "field_name", "Signature"),
                "intact": False,
                "valid": False,
                "coverage": "UNKNOWN",
                "signing_time": None,
                "signer_cn": "Unknown",
                "signer_org": "",
                "signer_friendly": "Unknown",
                "issuer_cn": "",
                "issuer_org": "",
                "issuer_friendly": "",
                "not_before": None,
                "not_after": None,
                "serial_number": "",
                "sha256_fingerprint": "",
                "reason": "",
                "location": "",
                "contact_info": "",
            }

            try:
                status = validation.validate_pdf_signature(sig)
                info["intact"] = getattr(status, "intact", False)
                info["valid"] = getattr(status, "valid", False)
                coverage = getattr(status, "coverage", None)
                if coverage:
                    info["coverage"] = getattr(coverage, "name", str(coverage))
            except Exception as val_exc:
                logging.debug(f"Signature validation error: {val_exc}")
                info["intact"] = False
                info["valid"] = False

            # Extract signature dictionary metadata
            try:
                sig_obj = getattr(sig, "sig_object", {})
                if sig_obj:
                    info["reason"] = str(sig_obj.get("/Reason", "") or "")
                    info["location"] = str(sig_obj.get("/Location", "") or "")
                    info["contact_info"] = str(sig_obj.get("/ContactInfo", "") or "")
            except Exception:
                pass

            try:
                info["signing_time"] = getattr(sig, "self_reported_timestamp", None)
            except Exception:
                pass

            # Extract certificate details
            try:
                cert = getattr(sig, "signer_cert", None)
                if cert:
                    subj = cert.subject.native if hasattr(cert.subject, "native") else {}
                    info["signer_cn"] = subj.get("common_name", getattr(cert.subject, "human_friendly", "Signer"))
                    info["signer_org"] = subj.get("organization_name", "")
                    info["signer_friendly"] = getattr(cert.subject, "human_friendly", info["signer_cn"])

                    iss = cert.issuer.native if hasattr(cert.issuer, "native") else {}
                    info["issuer_cn"] = iss.get("common_name", getattr(cert.issuer, "human_friendly", ""))
                    info["issuer_org"] = iss.get("organization_name", "")
                    info["issuer_friendly"] = getattr(cert.issuer, "human_friendly", info["issuer_cn"])

                    tbs = cert["tbs_certificate"]
                    validity = tbs["validity"]
                    info["not_before"] = validity["not_before"].native
                    info["not_after"] = validity["not_after"].native
                    info["serial_number"] = str(cert.serial_number)
                    info["sha256_fingerprint"] = cert.sha256.hex()
            except Exception:
                pass

            results.append(info)

    except Exception as exc:
        logging.debug(f"Failed to inspect PDF signatures: {exc}")

    return results
