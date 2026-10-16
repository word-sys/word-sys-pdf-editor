from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Any, Tuple

try:
    import pyhanko
    from pyhanko.sign import fields
    from pyhanko.sign.signers import PdfSignatureMetadata
    from pyhanko.sign.validation import DocumentSecurityStore
    PYHANKO_PADES_AVAILABLE = True
except ImportError:
    fields = None
    PdfSignatureMetadata = None
    DocumentSecurityStore = None
    PYHANKO_PADES_AVAILABLE = False

from .tsa_client import TSAConfig, create_timestamper
from .docmdp_guard import get_docmdp_perm_enum
from .trust_manager import build_validation_context


PADES_B_B = "B-B"
PADES_B_T = "B-T"
PADES_B_LT = "B-LT"
PADES_B_LTA = "B-LTA"

ALL_PADES_PROFILES = (PADES_B_B, PADES_B_T, PADES_B_LT, PADES_B_LTA)


@dataclass
class PAdESSigningConfig:
    profile: str = PADES_B_B
    tsa_config: Optional[TSAConfig] = None
    timestamper: Optional[Any] = None
    certify: bool = False
    docmdp_permissions: Optional[int] = None
    validation_context: Optional[Any] = None

    def normalized_profile(self) -> str:
        p = (self.profile or PADES_B_B).strip().upper()
        if p in ("B_B", "B-B", "BB"):
            return PADES_B_B
        if p in ("B_T", "B-T", "BT"):
            return PADES_B_T
        if p in ("B_LT", "B-LT", "BLT", "LTV"):
            return PADES_B_LT
        if p in ("B_LTA", "B-LTA", "BLTA"):
            return PADES_B_LTA
        return PADES_B_B


def is_pades_signer_available() -> bool:
    return PYHANKO_PADES_AVAILABLE


def prepare_pades_signature_meta(
    field_name: str,
    reason: Optional[str] = None,
    location: Optional[str] = None,
    contact_info: Optional[str] = None,
    signer_name: Optional[str] = None,
    pades_config: Optional[PAdESSigningConfig] = None,
) -> Tuple[Optional[Any], Optional[Any], Optional[str]]:
    """
    Prepare PdfSignatureMetadata and TimeStamper according to requested PAdES profile.

    Returns:
        (signature_meta, timestamper, error_message)
    """
    if not PYHANKO_PADES_AVAILABLE:
        return None, None, "pyHanko library is required for PAdES signatures"

    config = pades_config or PAdESSigningConfig()
    profile = config.normalized_profile()

    timestamper = config.timestamper
    if timestamper is None and config.tsa_config is not None:
        timestamper = create_timestamper(config.tsa_config)

    if profile in (PADES_B_T, PADES_B_LT, PADES_B_LTA) and timestamper is None:
        return None, None, f"PAdES {profile} profile requires a functional Time Stamp Authority (TSA)"

    perm_enum = None
    if config.docmdp_permissions is not None:
        perm_enum = get_docmdp_perm_enum(config.docmdp_permissions)
    is_certify = config.certify or (perm_enum is not None)

    vc = config.validation_context
    if (profile in (PADES_B_LT, PADES_B_LTA)) and vc is None:
        vc = build_validation_context()

    embed_validation_info = profile in (PADES_B_LT, PADES_B_LTA)
    use_pades_lta = profile == PADES_B_LTA

    try:
        meta = PdfSignatureMetadata(
            field_name=field_name,
            reason=reason or "I approve this document",
            location=location if location else None,
            contact_info=contact_info if contact_info else None,
            name=signer_name,
            subfilter=fields.SigSeedSubFilter.PADES,
            certify=is_certify,
            docmdp_permissions=perm_enum if is_certify else None,
            embed_validation_info=embed_validation_info,
            validation_context=vc if embed_validation_info else None,
            use_pades_lta=use_pades_lta,
        )
        return meta, timestamper, None
    except Exception as exc:
        logging.error("Failed to construct PdfSignatureMetadata for PAdES %s: %s", profile, exc)
        return None, None, f"Failed to configure PAdES {profile} signature: {exc}"


def detect_pades_profile(
    status: Optional[Any],
    has_dss: bool = False,
    has_ltv: bool = False,
    is_document_timestamp: bool = False,
    has_archival_timestamp: bool = False,
) -> str:
    """
    Detect the PAdES baseline profile of an embedded signature.
    """
    if is_document_timestamp or has_archival_timestamp:
        return PADES_B_LTA

    if has_ltv:
        return PADES_B_LT

    has_ts = False
    if status is not None:
        ts_status = getattr(status, "timestamp_validity", None)
        if ts_status is not None:
            has_ts = True

    if has_ts and has_dss:
        return PADES_B_LT
    if has_ts:
        return PADES_B_T

    return PADES_B_B
