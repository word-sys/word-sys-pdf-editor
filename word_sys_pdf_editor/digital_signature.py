from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any, Tuple, List, Dict, Optional

logging.getLogger("pyhanko_certvalidator").setLevel(logging.CRITICAL)
logging.getLogger("pyhanko.sign.validation").setLevel(logging.CRITICAL)

try:
    import pyhanko
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.images import PdfImage
    from pyhanko.sign import fields, signers, validation
    from pyhanko.sign.signers import SimpleSigner, PdfSignatureMetadata, PdfSigner
    from pyhanko.sign.validation import DocumentSecurityStore, read_certification_data, KeyUsageConstraints
    from pyhanko.stamp import TextStampStyle
    from pyhanko.pdf_utils.text import TextBoxStyle
    PYHANKO_AVAILABLE = True
except ImportError:
    PYHANKO_AVAILABLE = False

from .trust_manager import build_validation_context, is_trust_manager_available
from .docmdp_guard import can_counter_sign, get_docmdp_perm_enum, inspect_docmdp_permissions, get_acrobat_diff_policy
from .tsa_client import TSAConfig, create_timestamper
from .pades_signer import (
    PAdESSigningConfig,
    prepare_pades_signature_meta,
    detect_pades_profile,
    PADES_B_B,
    PADES_B_T,
    PADES_B_LT,
    PADES_B_LTA,
)
from .pkcs11_manager import create_pkcs11_signer, is_pkcs11_engine_available
from .stamp_renderer import create_opentype_stamp_style, is_stamp_renderer_available


def is_pyhanko_available() -> bool:
    """Return True if pyHanko is available in the current environment."""
    return PYHANKO_AVAILABLE


def extract_cert_info_from_asn1(cert: Any, default_cn: str = "Signer") -> Dict[str, Any]:
    """Extract standard metadata dictionary from an asn1crypto.x509.Certificate object."""
    cert_info: Dict[str, Any] = {}

    try:
        subject_dict = cert.subject.native if hasattr(cert.subject, "native") else {}
        cert_info["subject_cn"] = subject_dict.get("common_name", default_cn)
        cert_info["subject_org"] = subject_dict.get("organization_name", "")
        cert_info["subject_friendly"] = cert.subject.human_friendly if hasattr(cert.subject, "human_friendly") else str(cert.subject)
    except Exception:
        cert_info["subject_cn"] = default_cn
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

    return cert_info


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

    cert_info = extract_cert_info_from_asn1(signer.signing_cert, default_cn=signer.subject_name or "Unknown")
    return signer, cert_info, None


def _sanitize_visual_stamp_text(text: str) -> str:
    """Sanitize text for standard Type-1 PDF font rendering to prevent UTF-16 byte corruption."""
    if not text:
        return ""
    replacements = {
        "ğ": "g", "Ğ": "G",
        "ı": "i", "İ": "I",
        "ş": "s", "Ş": "S",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    import unicodedata
    normalized = unicodedata.normalize("NFKD", text)
    safe = "".join(c for c in normalized if not unicodedata.combining(c))
    try:
        return safe.encode("latin-1").decode("latin-1")
    except UnicodeEncodeError:
        return safe.encode("ascii", errors="replace").decode("ascii")


def _wrap_stamp_field(prefix: str, val: str, max_chars: int = 42) -> Tuple[str, int]:
    """Wrap a stamp field across multiple lines if it exceeds max_chars."""
    if not val:
        return "", 0
    full = f"{prefix}: {val}"
    if len(full) <= max_chars:
        return val, 1
    import textwrap
    avail = max(18, max_chars - len(prefix) - 2)
    wrapped = textwrap.wrap(val, width=avail)
    if len(wrapped) <= 1:
        return val, 1
    indent = "  "
    multi = wrapped[0] + "\n" + "\n".join(indent + w for w in wrapped[1:])
    return multi, len(wrapped)


def sign_pdf_bytes(
    pdf_bytes: bytes,
    pfx_data_or_path: Optional[bytes | str] = None,
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
    certify: bool = False,
    docmdp_permissions: Optional[int] = None,
    validation_context: Optional[Any] = None,
    pades_profile: str = PADES_B_B,
    tsa_config: Optional[TSAConfig] = None,
    timestamper: Optional[Any] = None,
    signer: Optional[Any] = None,
    pkcs11_driver: Optional[str] = None,
    pkcs11_slot_id: Optional[int] = None,
    pkcs11_token_label: Optional[str] = None,
    pkcs11_pin: Optional[str] = None,
    pkcs11_cert_label: Optional[str] = None,
    pkcs11_cert_id: Optional[bytes] = None,
    use_opentype_stamp: bool = False,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Digitally sign a PDF document using pyHanko supporting PAdES B-B/T/LT/LTA,
    software PKCS#12, or hardware smart cards / tokens via PKCS#11.
    """
    if not PYHANKO_AVAILABLE:
        return None, "pyHanko library is required for digital signatures"

    can_sign, blocked_reason = can_counter_sign(pdf_bytes)
    if not can_sign:
        return None, blocked_reason

    session_to_close = None
    cert_info: Dict[str, Any] = {}

    if signer is not None:
        if hasattr(signer, "signing_cert") and signer.signing_cert:
            cert_info = extract_cert_info_from_asn1(signer.signing_cert, default_cn=signer_name or "Signer")
    elif pkcs11_driver:
        p11_cid = pkcs11_cert_id if (pkcs11_cert_id is not None and len(pkcs11_cert_id) > 0) else None
        p11_clbl = str(pkcs11_cert_label).strip() if (pkcs11_cert_label is not None and str(pkcs11_cert_label).strip()) else None

        hw_signer, hw_session, hw_err = create_pkcs11_signer(
            module_path=pkcs11_driver,
            slot_id=pkcs11_slot_id,
            token_label=pkcs11_token_label,
            user_pin=pkcs11_pin,
            cert_label=p11_clbl,
            cert_id=p11_cid,
        )
        if hw_err or hw_signer is None:
            return None, hw_err or "Failed to initialize PKCS#11 hardware signer"
        signer = hw_signer
        session_to_close = hw_session
        try:
            if hasattr(signer, "signing_cert") and signer.signing_cert:
                cert_info = extract_cert_info_from_asn1(signer.signing_cert, default_cn=signer_name or "Hardware Signer")
        except Exception as cert_read_exc:
            logging.warning("Could not extract certificate info from hardware signer: %s", cert_read_exc)
    elif pfx_data_or_path:
        sw_signer, sw_cert_info, sw_err = load_pkcs12_certificate(pfx_data_or_path, passphrase=passphrase)
        if sw_err or sw_signer is None or sw_cert_info is None:
            return None, sw_err or "Failed to load signing certificate"
        signer = sw_signer
        cert_info = sw_cert_info
    else:
        return None, "No signing certificate or hardware token provided"

    try:
        if not field_name:
            field_name = f"Signature_{int(datetime.now().timestamp())}"

        display_name = signer_name or cert_info.get("subject_cn") or "Signer"
        display_reason = reason or "I approve this document"
        display_location = location or ""
        display_contact = contact_info or ""

        # Sanitize visual appearance texts to prevent Type-1 UTF-16 BOM (\xfe\xff) corruption
        stamp_signer = _sanitize_visual_stamp_text(display_name)
        stamp_reason, _lines_r = _wrap_stamp_field("Reason", _sanitize_visual_stamp_text(display_reason))
        stamp_location, _lines_l = _wrap_stamp_field("Location", _sanitize_visual_stamp_text(display_location))
        stamp_contact, _lines_c = _wrap_stamp_field("Contact", _sanitize_visual_stamp_text(display_contact))

        in_stream = io.BytesIO(pdf_bytes)
        writer = IncrementalPdfFileWriter(in_stream)

        pades_cfg = PAdESSigningConfig(
            profile=pades_profile,
            tsa_config=tsa_config,
            timestamper=timestamper,
            certify=certify,
            docmdp_permissions=docmdp_permissions,
            validation_context=validation_context,
        )
        meta, active_timestamper, meta_err = prepare_pades_signature_meta(
            field_name=field_name,
            reason=display_reason,
            location=display_location if display_location else None,
            contact_info=display_contact if display_contact else None,
            signer_name=display_name,
            pades_config=pades_cfg,
        )
        if meta_err or meta is None:
            return None, meta_err

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

            rendered_lines = [
                f"Digitally signed by: {stamp_signer}",
                "Date: YYYY-MM-DD HH:MM:SS +00",
            ]
            rendered_lines.extend(f"Reason: {stamp_reason}".split("\n"))
            if display_location:
                rendered_lines.extend(f"Location: {stamp_location}".split("\n"))
            if display_contact:
                rendered_lines.extend(f"Contact: {stamp_contact}".split("\n"))

            if box is None:
                max_chars = max(len(l) for l in rendered_lines)
                max_w = min(260.0, float(page_width - 30.0))
                if max_chars <= 34:
                    stamp_w = 175.0
                else:
                    stamp_w = min(max_chars * 4.3 + 12.0, max_w)
                stamp_h = max(42.0, 8.0 + len(rendered_lines) * 8.6)
                stamp_x = max(15.0, page_width - stamp_w - 25.0)
                stamp_y = max(15.0, page_height - stamp_h - 30.0)
                box = (stamp_x, stamp_y, stamp_w, stamp_h)

            bx, by, bw, bh = box
            # Convert screen top-left coordinates to PDF user-space bottom-left coordinates
            pdf_x0 = int(bx)
            pdf_y0 = int(page_height - (by + bh))
            pdf_x1 = int(bx + bw)
            pdf_y1 = int(page_height - by)

            # Ensure valid non-inverted box bounds
            if pdf_x1 <= pdf_x0:
                pdf_x1 = pdf_x0 + 140
            if pdf_y1 <= pdf_y0:
                pdf_y1 = pdf_y0 + 42

            pdf_box = (pdf_x0, pdf_y0, pdf_x1, pdf_y1)

            new_field_spec = fields.SigFieldSpec(
                sig_field_name=field_name,
                on_page=page_index,
                box=pdf_box,
            )

            stamp_style = None
            if use_opentype_stamp and not custom_stamp_text and is_stamp_renderer_available():
                now_str = datetime.now().strftime("%Y.%m.%d %H:%M:%S %z")
                verif_text = f"Verification: PAdES-{pades_profile}"
                if pades_profile == PADES_B_LT:
                    verif_text += " (LTV Enabled)"
                stamp_style = create_opentype_stamp_style(
                    signer_name=display_name,
                    date_str=now_str,
                    reason=display_reason,
                    location=display_location if display_location else None,
                    contact=display_contact if display_contact else None,
                    organization=cert_info.get("subject_org"),
                    verification_text=verif_text,
                    handwritten_bytes=signature_image_bytes,
                    width_pt=bw,
                    height_pt=bh,
                )

            if stamp_style is None:
                # Fallback to standard TextStampStyle
                if custom_stamp_text:
                    stamp_text = custom_stamp_text
                else:
                    stamp_text = "Digitally signed by: %(signer)s\nDate: %(ts)s\nReason: %(reason)s"
                    if display_location:
                        stamp_text += "\nLocation: %(location)s"
                    if display_contact:
                        stamp_text += "\nContact: %(contact)s"

                bg_image = None
                if signature_image_bytes:
                    try:
                        from PIL import Image
                        pil_img = Image.open(io.BytesIO(signature_image_bytes))
                        bg_image = PdfImage(image=pil_img)
                    except Exception as img_exc:
                        logging.warning("Failed to load signature image: %s", img_exc)

                stamp_style = TextStampStyle(
                    stamp_text=stamp_text,
                    border_width=1,
                    background=bg_image,
                    background_opacity=0.35 if bg_image else 1.0,
                    text_box_style=TextBoxStyle(font_size=7),
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
            timestamper=active_timestamper,
            stamp_style=stamp_style,
            new_field_spec=new_field_spec,
        )

        out_stream = io.BytesIO()
        appearance_params = {
            "signer": stamp_signer,
            "reason": stamp_reason,
            "location": stamp_location,
            "contact": stamp_contact,
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
    finally:
        if session_to_close is not None:
            try:
                session_to_close.close()
            except Exception:
                pass


def inspect_pdf_signatures(pdf_bytes_or_path: bytes | str) -> List[Dict[str, Any]]:
    """
    Inspect all digital signatures in a PDF and determine cryptographic integrity,
    trust status against universal roots (certifi + OS CA bundle + custom roots),
    DocMDP compliance, PAdES profile (B-B/T/LT/LTA), RFC 3161 timestamps, and Adobe LTV status.
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

        vc = build_validation_context() if is_trust_manager_available() else None
        key_usage_constraints = KeyUsageConstraints(
            key_usage={"digital_signature", "non_repudiation"}
        )

        # Check for Document Security Store (/DSS) and LTV presence
        has_dss = False
        has_ltv = False
        try:
            dss = DocumentSecurityStore.read_dss(reader)
            if dss is not None:
                has_dss = True
                root_dict = getattr(reader, "root", {})
                dss_dict = root_dict.get("/DSS") if hasattr(root_dict, "get") else None
                if dss_dict and ("/OCSPs" in dss_dict or "/CRLs" in dss_dict):
                    has_ltv = True
        except Exception:
            pass

        # Inspect certification data if present
        cert_data = None
        try:
            cert_data = read_certification_data(reader)
        except Exception:
            pass

        for sig in embedded_sigs:
            sig_field_name = getattr(sig, "field_name", "Signature")
            info: Dict[str, Any] = {
                "field_name": sig_field_name,
                "intact": False,
                "valid": False,
                "trusted": False,
                "docmdp_ok": None,
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
                "is_certification": False,
                "docmdp_permission": None,
                "docmdp_permission_name": None,
                "has_dss": has_dss,
                "has_ltv": has_ltv,
                "validation_error": None,
                "pades_profile": PADES_B_B,
                "is_document_timestamp": False,
                "tsa_timestamp": None,
                "tsa_valid": None,
                "tsa_intact": None,
                "tsa_trusted": None,
                "tsa_cn": "",
            }

            active_status = None
            diff_policy = get_acrobat_diff_policy()
            try:
                status = validation.validate_pdf_signature(
                    sig,
                    signer_validation_context=vc,
                    key_usage_settings=key_usage_constraints,
                    diff_policy=diff_policy,
                )
                active_status = status
                info["intact"] = getattr(status, "intact", False)
                info["valid"] = getattr(status, "valid", False)
                info["trusted"] = getattr(status, "trusted", False)
                info["docmdp_ok"] = getattr(status, "docmdp_ok", None)
                coverage = getattr(status, "coverage", None)
                if coverage:
                    info["coverage"] = getattr(coverage, "name", str(coverage))
            except Exception as val_exc:
                logging.debug("Signature validation error for %s: %s", sig_field_name, val_exc)
                # Fallback to basic validation without validation context if trust building failed
                try:
                    fallback_status = validation.validate_pdf_signature(sig, diff_policy=diff_policy)
                    active_status = fallback_status
                    info["intact"] = getattr(fallback_status, "intact", False)
                    info["valid"] = getattr(fallback_status, "valid", False)
                    info["trusted"] = False
                    f_cov = getattr(fallback_status, "coverage", None)
                    if f_cov:
                        info["coverage"] = getattr(f_cov, "name", str(f_cov))
                except Exception:
                    info["intact"] = False
                    info["valid"] = False
                    info["trusted"] = False
                info["validation_error"] = str(val_exc)

            # Check if this signature is a DocTimeStamp (PAdES B-LTA)
            is_doc_ts = False
            try:
                sig_type = str(sig.sig_object.get("/Type", ""))
                subfilter = str(sig.sig_object.get("/SubFilter", ""))
                if "/DocTimeStamp" in sig_type or "/ETSI.RFC3161" in subfilter:
                    is_doc_ts = True
            except Exception:
                pass
            info["is_document_timestamp"] = is_doc_ts

            # Detect PAdES Profile
            info["pades_profile"] = detect_pades_profile(
                status=active_status,
                has_dss=has_dss,
                has_ltv=has_ltv,
                is_document_timestamp=is_doc_ts,
            )

            # Extract TSA timestamp details
            if active_status is not None:
                ts_val = getattr(active_status, "timestamp_validity", None)
                if ts_val is not None:
                    info["tsa_timestamp"] = getattr(ts_val, "timestamp", None)
                    info["tsa_valid"] = getattr(ts_val, "valid", None)
                    info["tsa_intact"] = getattr(ts_val, "intact", None)
                    info["tsa_trusted"] = getattr(ts_val, "trusted", None)
                    try:
                        tsa_cert = getattr(ts_val, "signing_cert", None)
                        if tsa_cert:
                            tsa_subj = tsa_cert.subject.native if hasattr(tsa_cert.subject, "native") else {}
                            info["tsa_cn"] = tsa_subj.get("common_name", getattr(tsa_cert.subject, "human_friendly", "TSA"))
                    except Exception:
                        pass

            # Check if this signature is the author certification signature
            if cert_data and getattr(cert_data, "author_sig", None):
                if getattr(sig, "sig_object", None) == cert_data.author_sig:
                    info["is_certification"] = True
                    perm = cert_data.permission
                    info["docmdp_permission"] = int(perm.value if hasattr(perm, "value") else perm)
                    info["docmdp_permission_name"] = getattr(perm, "name", str(perm))

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
                    if not info["contact_info"]:
                        email = subj.get("email_address") or subj.get("email")
                        if email:
                            info["contact_info"] = str(email)

                    try:
                        raw_der = cert.dump()
                        info["cert_der"] = raw_der
                        import base64
                        b64 = base64.encodebytes(raw_der).decode("ascii")
                        info["cert_pem"] = f"-----BEGIN CERTIFICATE-----\n{b64}-----END CERTIFICATE-----\n"
                    except Exception:
                        pass
            except Exception:
                pass

            results.append(info)

    except Exception as exc:
        logging.debug("Failed to inspect PDF signatures: %s", exc)

    return results

