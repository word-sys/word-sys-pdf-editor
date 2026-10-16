from __future__ import annotations

import io
import os
import logging
from typing import Optional, Dict, Any, Tuple, Union

try:
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.fields import MDPPerm
    from pyhanko.sign.validation import read_certification_data
    DOCMDP_AVAILABLE = True
except ImportError:
    DOCMDP_AVAILABLE = False
    MDPPerm = None

logger = logging.getLogger(__name__)


def is_docmdp_available() -> bool:
    """Return True if DocMDP inspection dependencies are available."""
    return DOCMDP_AVAILABLE


def get_docmdp_perm_enum(val: Optional[int]) -> Optional[Any]:
    """Convert integer permission level (1, 2, 3) to MDPPerm enum."""
    if not DOCMDP_AVAILABLE or val is None or MDPPerm is None:
        return None
    try:
        return MDPPerm(int(val))
    except (ValueError, TypeError):
        return None


def _get_pdf_reader(doc_or_bytes_or_path: Union[bytes, bytearray, str, Any]) -> Optional[PdfFileReader]:
    """Obtain a pyHanko PdfFileReader from bytes, file path, or existing reader."""
    if not DOCMDP_AVAILABLE:
        return None

    if isinstance(doc_or_bytes_or_path, PdfFileReader):
        return doc_or_bytes_or_path

    try:
        if isinstance(doc_or_bytes_or_path, (bytes, bytearray)):
            stream = io.BytesIO(doc_or_bytes_or_path)
            return PdfFileReader(stream)
        elif isinstance(doc_or_bytes_or_path, str) and os.path.exists(doc_or_bytes_or_path):
            with open(doc_or_bytes_or_path, "rb") as f:
                stream = io.BytesIO(f.read())
            return PdfFileReader(stream)
        elif hasattr(doc_or_bytes_or_path, "tobytes"):
            stream = io.BytesIO(doc_or_bytes_or_path.tobytes())
            return PdfFileReader(stream)
    except Exception as exc:
        logger.debug(f"Failed to initialize PdfFileReader: {exc}")

    return None


_ACROBAT_DIFF_POLICY: Optional[Any] = None


def get_acrobat_diff_policy() -> Optional[Any]:
    """
    Construct or return cached StandardDiffPolicy matching Adobe Acrobat Pro behavior,
    allowing visible counter-signatures on certified documents where DocMDP permits.
    """
    global _ACROBAT_DIFF_POLICY
    if _ACROBAT_DIFF_POLICY is not None:
        return _ACROBAT_DIFF_POLICY

    try:
        from pyhanko.sign.diff_analysis import (
            DEFAULT_DIFF_POLICY,
            StandardDiffPolicy,
            FormUpdatingRule,
            SigFieldCreationRule,
        )
        field_rules = [
            SigFieldCreationRule(allow_new_visible_after_certify=True),
        ]
        if hasattr(DEFAULT_DIFF_POLICY, "form_rule") and DEFAULT_DIFF_POLICY.form_rule:
            orig_rules = getattr(DEFAULT_DIFF_POLICY.form_rule, "field_rules", [])
            for r in orig_rules[1:]:
                field_rules.append(r)
        form_rule = FormUpdatingRule(field_rules=field_rules)
        _ACROBAT_DIFF_POLICY = StandardDiffPolicy(
            global_rules=DEFAULT_DIFF_POLICY.global_rules,
            form_rule=form_rule,
        )
        return _ACROBAT_DIFF_POLICY
    except Exception as exc:
        logger.debug(f"Could not build Acrobat diff policy: {exc}")
        return None


def is_document_signed(doc_or_bytes_or_path: Union[bytes, bytearray, str, Any]) -> bool:
    """Return True if the document contains any embedded digital signatures."""
    reader = _get_pdf_reader(doc_or_bytes_or_path)
    if not reader:
        return False
    try:
        embedded = getattr(reader, "embedded_signatures", [])
        return len(embedded) > 0
    except Exception:
        return False


def inspect_docmdp_permissions(doc_or_bytes_or_path: Union[bytes, bytearray, str, Any]) -> Dict[str, Any]:
    """
    Inspect DocMDP document certification permissions.

    Returns:
        Dictionary containing certification status, permission level, and allowed actions.
    """
    info: Dict[str, Any] = {
        "is_certified": False,
        "permission": None,
        "permission_name": None,
        "allows_counter_signing": True,
        "allows_form_filling": True,
        "allows_annotations": True,
        "author_signature_field": None,
        "has_signatures": False,
        "signature_count": 0,
        "summary": "Document is not certified.",
    }

    if not DOCMDP_AVAILABLE:
        return info

    reader = _get_pdf_reader(doc_or_bytes_or_path)
    if not reader:
        return info

    try:
        embedded = getattr(reader, "embedded_signatures", [])
        info["signature_count"] = len(embedded)
        info["has_signatures"] = len(embedded) > 0

        cert_data = read_certification_data(reader)
        if cert_data is not None:
            info["is_certified"] = True
            perm = cert_data.permission
            perm_val = int(perm.value if hasattr(perm, "value") else perm)
            info["permission"] = perm_val
            info["permission_name"] = getattr(perm, "name", str(perm))
            if getattr(cert_data, "author_sig", None):
                for sig in embedded:
                    if getattr(sig, "sig_object", None) == cert_data.author_sig:
                        info["author_signature_field"] = getattr(sig, "field_name", None)
                        break

            if perm_val == 1:
                # Level 1: NO_CHANGES
                info["allows_counter_signing"] = False
                info["allows_form_filling"] = False
                info["allows_annotations"] = False
                info["summary"] = "Certified (Level 1: No changes permitted)."
            elif perm_val == 2:
                # Level 2: FILL_FORMS
                info["allows_counter_signing"] = True
                info["allows_form_filling"] = True
                info["allows_annotations"] = False
                info["summary"] = "Certified (Level 2: Form filling and signing permitted)."
            elif perm_val == 3:
                # Level 3: ANNOTATE
                info["allows_counter_signing"] = True
                info["allows_form_filling"] = True
                info["allows_annotations"] = True
                info["summary"] = "Certified (Level 3: Annotations, form filling, and signing permitted)."
            else:
                info["summary"] = f"Certified (Permission level {perm_val})."

        elif info["has_signatures"]:
            info["summary"] = f"Document contains {info['signature_count']} digital signature(s)."

    except Exception as exc:
        logger.debug(f"Error inspecting DocMDP permissions: {exc}")

    return info


def can_counter_sign(doc_or_bytes_or_path: Union[bytes, bytearray, str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Check if additional digital signatures or counter-signatures may be added to the document.

    Returns:
        (allowed, error_reason)
    """
    mdp_info = inspect_docmdp_permissions(doc_or_bytes_or_path)
    if mdp_info["is_certified"] and not mdp_info["allows_counter_signing"]:
        return (
            False,
            "Document is certified with Level 1 (NO_CHANGES). Additional signatures are prohibited.",
        )
    return True, None


def can_modify_content(doc_or_bytes_or_path: Union[bytes, bytearray, str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Check if direct content stream modifications (e.g. text or shape editing) are permitted.

    Returns:
        (allowed, reason)
    """
    mdp_info = inspect_docmdp_permissions(doc_or_bytes_or_path)
    if mdp_info["is_certified"] and mdp_info["permission"] == 1:
        return (
            False,
            "Document is certified with Level 1 (NO_CHANGES). Content modifications are locked.",
        )
    if mdp_info["has_signatures"]:
        return (
            False,
            "Document contains digital signatures. Direct content stream modifications are locked to preserve signature integrity.",
        )
    return True, None
