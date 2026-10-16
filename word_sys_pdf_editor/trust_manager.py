from __future__ import annotations

import os
import re
import base64
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    import certifi
    import asn1crypto.x509 as x509
    from pyhanko_certvalidator import ValidationContext
    TRUST_MANAGER_AVAILABLE = True
except ImportError:
    TRUST_MANAGER_AVAILABLE = False


logger = logging.getLogger(__name__)

# In-memory caches for fast sub-millisecond retrieval
_CACHED_GLOBAL_ROOTS: Optional[List[x509.Certificate]] = None
_CACHED_CUSTOM_ROOTS: Optional[List[x509.Certificate]] = None
_CACHED_VALIDATION_CONTEXT: Optional[ValidationContext] = None

PEM_CERT_PATTERN = re.compile(
    r"-----BEGIN CERTIFICATE-----\s*([A-Za-z0-9+/=\s]+?)\s*-----END CERTIFICATE-----"
)


def is_trust_manager_available() -> bool:
    """Return True if required trust validation dependencies are installed."""
    return TRUST_MANAGER_AVAILABLE


def get_trusted_roots_dir() -> Path:
    """Return path to user-managed custom trusted root certificates directory."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        base_dir = Path(xdg_config) / "word-sys-pdf-editor"
    else:
        base_dir = Path.home() / ".config" / "word-sys-pdf-editor"

    roots_dir = base_dir / "trusted_roots"
    roots_dir.mkdir(parents=True, exist_ok=True)
    return roots_dir


def _parse_certs_from_pem_text(pem_text: str) -> List[x509.Certificate]:
    """Parse all PEM-encoded certificates from string into asn1crypto Certificates."""
    certs: List[x509.Certificate] = []
    for b64_match in PEM_CERT_PATTERN.findall(pem_text):
        try:
            der_bytes = base64.b64decode("".join(b64_match.split()))
            certs.append(x509.Certificate.load(der_bytes))
        except Exception as exc:
            logger.debug(f"Failed to parse individual certificate block: {exc}")
    return certs


def _load_global_ca_roots() -> List[x509.Certificate]:
    """Load universal global trust roots from certifi and operating system bundles."""
    global _CACHED_GLOBAL_ROOTS
    if _CACHED_GLOBAL_ROOTS is not None:
        return _CACHED_GLOBAL_ROOTS

    if not TRUST_MANAGER_AVAILABLE:
        return []

    collected: Dict[str, x509.Certificate] = {}

    # 1. Load Mozilla CA bundle via certifi
    try:
        certifi_path = certifi.where()
        if os.path.isfile(certifi_path):
            with open(certifi_path, "r", encoding="utf-8", errors="ignore") as f:
                for cert in _parse_certs_from_pem_text(f.read()):
                    collected[cert.sha256.hex()] = cert
    except Exception as exc:
        logger.warning(f"Failed to load certifi trust bundle: {exc}")

    # 2. Check standard operating system CA paths
    os_ca_paths = [
        "/etc/ssl/certs/ca-certificates.crt",           # Debian, Ubuntu, Flatpak runtime
        "/etc/pki/tls/certs/ca-bundle.crt",             # Fedora, RHEL, CentOS
        "/etc/ssl/ca-bundle.pem",                       # OpenSUSE
        "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    ]
    for os_path in os_ca_paths:
        if os.path.isfile(os_path):
            try:
                with open(os_path, "r", encoding="utf-8", errors="ignore") as f:
                    for cert in _parse_certs_from_pem_text(f.read()):
                        collected[cert.sha256.hex()] = cert
                break  # Stop after first matching system bundle
            except Exception as exc:
                logger.debug(f"Failed reading OS bundle {os_path}: {exc}")

    _CACHED_GLOBAL_ROOTS = list(collected.values())
    return _CACHED_GLOBAL_ROOTS


def get_custom_trusted_roots(force_reload: bool = False) -> List[x509.Certificate]:
    """Load user-imported enterprise or national root certificates from storage."""
    global _CACHED_CUSTOM_ROOTS
    if _CACHED_CUSTOM_ROOTS is not None and not force_reload:
        return _CACHED_CUSTOM_ROOTS

    if not TRUST_MANAGER_AVAILABLE:
        return []

    roots_dir = get_trusted_roots_dir()
    custom_certs: Dict[str, x509.Certificate] = {}

    for file_path in roots_dir.iterdir():
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext not in (".crt", ".cer", ".pem", ".der"):
            continue

        try:
            raw_bytes = file_path.read_bytes()
            # Attempt PEM parsing first
            try:
                text_content = raw_bytes.decode("utf-8", errors="ignore")
                parsed_list = _parse_certs_from_pem_text(text_content)
                if parsed_list:
                    for c in parsed_list:
                        custom_certs[c.sha256.hex()] = c
                    continue
            except Exception:
                pass

            # Fallback to direct binary DER parsing
            cert = x509.Certificate.load(raw_bytes)
            custom_certs[cert.sha256.hex()] = cert
        except Exception as exc:
            logger.warning(f"Failed parsing custom certificate {file_path.name}: {exc}")

    _CACHED_CUSTOM_ROOTS = list(custom_certs.values())
    return _CACHED_CUSTOM_ROOTS


def get_all_trust_roots(force_reload: bool = False) -> List[x509.Certificate]:
    """Return combined, deduplicated list of global and custom trust anchors."""
    global_roots = _load_global_ca_roots()
    custom_roots = get_custom_trusted_roots(force_reload=force_reload)

    dedup: Dict[str, x509.Certificate] = {}
    for c in global_roots:
        dedup[c.sha256.hex()] = c
    for c in custom_roots:
        dedup[c.sha256.hex()] = c

    return list(dedup.values())


def invalidate_trust_cache() -> None:
    """Clear cached trust roots and validation context."""
    global _CACHED_CUSTOM_ROOTS, _CACHED_VALIDATION_CONTEXT
    _CACHED_CUSTOM_ROOTS = None
    _CACHED_VALIDATION_CONTEXT = None


def build_validation_context(
    revocation_mode: Optional[str] = None,
    allow_fetching: bool = True,
    force_reload: bool = False,
) -> Optional[ValidationContext]:
    """
    Construct a pyhanko-certvalidator ValidationContext anchored to universal roots.

    Parameters:
        revocation_mode: 'soft-fail' (default for desktop), 'hard-fail' (strict enterprise), or 'require-all'.
        allow_fetching: Enable dynamic AIA HTTP fetching for missing intermediate CAs.
        force_reload: Invalidate in-memory cached validation context.

    Returns:
        Configured ValidationContext instance or None if unavailable.
    """
    global _CACHED_VALIDATION_CONTEXT
    if not TRUST_MANAGER_AVAILABLE:
        return None

    if _CACHED_VALIDATION_CONTEXT is not None and not force_reload:
        return _CACHED_VALIDATION_CONTEXT

    roots = get_all_trust_roots(force_reload=force_reload)
    mode = revocation_mode or "soft-fail"

    try:
        vc = ValidationContext(
            trust_roots=roots,
            allow_fetching=allow_fetching,
            revocation_mode=mode,
        )
        _CACHED_VALIDATION_CONTEXT = vc
        return vc
    except Exception as exc:
        logger.error(f"Failed to build ValidationContext: {exc}")
        return None


def extract_certificate_summary(cert: x509.Certificate) -> Dict[str, Any]:
    """Extract human-readable metadata from an X.509 certificate."""
    info: Dict[str, Any] = {
        "subject_cn": "Unknown",
        "subject_org": "",
        "issuer_cn": "",
        "issuer_org": "",
        "serial_number": "",
        "sha256_fingerprint": "",
        "not_before": None,
        "not_after": None,
        "is_expired": False,
        "key_usage": [],
        "is_ca": False,
    }

    try:
        subj = cert.subject.native if hasattr(cert.subject, "native") else {}
        info["subject_cn"] = subj.get("common_name", getattr(cert.subject, "human_friendly", "Unknown"))
        info["subject_org"] = subj.get("organization_name", "")
    except Exception:
        pass

    try:
        iss = cert.issuer.native if hasattr(cert.issuer, "native") else {}
        info["issuer_cn"] = iss.get("common_name", getattr(cert.issuer, "human_friendly", ""))
        info["issuer_org"] = iss.get("organization_name", "")
    except Exception:
        pass

    try:
        info["serial_number"] = str(cert.serial_number)
        info["sha256_fingerprint"] = cert.sha256.hex()
    except Exception:
        pass

    try:
        tbs = cert["tbs_certificate"]
        val = tbs["validity"]
        nb = val["not_before"].native
        na = val["not_after"].native
        info["not_before"] = nb
        info["not_after"] = na
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if na.tzinfo is None:
            na = na.replace(tzinfo=timezone.utc)
        if nb.tzinfo is None:
            nb = nb.replace(tzinfo=timezone.utc)
        info["is_expired"] = now > na or now < nb
    except Exception:
        pass

    try:
        info["key_usage"] = list(cert.key_usage_value.native) if hasattr(cert, "key_usage_value") and cert.key_usage_value else []
    except Exception:
        pass

    try:
        info["is_ca"] = cert.ca
    except Exception:
        pass

    return info


def import_trusted_root(
    data_or_path: bytes | str,
    filename_hint: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Import a custom Root or Intermediate CA certificate into user trust store.

    Parameters:
        data_or_path: File path or raw bytes (.crt, .cer, .pem, .der).
        filename_hint: Optional original filename.

    Returns:
        (success, error_message, cert_summary)
    """
    if not TRUST_MANAGER_AVAILABLE:
        return False, "Cryptographic libraries unavailable", None

    try:
        if isinstance(data_or_path, str):
            with open(data_or_path, "rb") as f:
                raw_bytes = f.read()
            if not filename_hint:
                filename_hint = os.path.basename(data_or_path)
        else:
            raw_bytes = bytes(data_or_path)

        cert: Optional[x509.Certificate] = None

        # Check PEM text
        try:
            text = raw_bytes.decode("utf-8", errors="ignore")
            parsed = _parse_certs_from_pem_text(text)
            if parsed:
                cert = parsed[0]
        except Exception:
            pass

        # Fallback to DER
        if cert is None:
            cert = x509.Certificate.load(raw_bytes)

        if cert is None:
            return False, "Could not parse valid X.509 certificate", None

        summary = extract_certificate_summary(cert)
        fingerprint = summary["sha256_fingerprint"][:16]

        clean_hint = re.sub(r"[^A-Za-z0-9_\-\.]", "_", filename_hint or "custom_root.crt")
        target_name = f"{fingerprint}_{clean_hint}"
        if not target_name.endswith(".crt"):
            target_name += ".crt"

        dest_path = get_trusted_roots_dir() / target_name
        dest_path.write_bytes(cert.dump())

        invalidate_trust_cache()
        summary["saved_filename"] = target_name
        summary["saved_path"] = str(dest_path)

        return True, None, summary

    except Exception as exc:
        return False, f"Failed importing root certificate: {exc}", None


def list_custom_trusted_roots() -> List[Dict[str, Any]]:
    """List all installed custom enterprise/national root certificates with metadata."""
    if not TRUST_MANAGER_AVAILABLE:
        return []

    roots_dir = get_trusted_roots_dir()
    results: List[Dict[str, Any]] = []

    for file_path in sorted(roots_dir.iterdir()):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext not in (".crt", ".cer", ".pem", ".der"):
            continue

        try:
            raw_bytes = file_path.read_bytes()
            cert: Optional[x509.Certificate] = None
            try:
                text = raw_bytes.decode("utf-8", errors="ignore")
                parsed = _parse_certs_from_pem_text(text)
                if parsed:
                    cert = parsed[0]
            except Exception:
                pass

            if cert is None:
                cert = x509.Certificate.load(raw_bytes)

            summary = extract_certificate_summary(cert)
            summary["filename"] = file_path.name
            summary["path"] = str(file_path)
            results.append(summary)
        except Exception as exc:
            logger.debug(f"Failed reading certificate {file_path.name}: {exc}")

    return results


def remove_custom_trusted_root(filename_or_path: str) -> bool:
    """Remove a certificate from the custom trusted roots directory."""
    target_name = os.path.basename(filename_or_path)
    dest_path = get_trusted_roots_dir() / target_name
    if dest_path.is_file():
        try:
            dest_path.unlink()
            invalidate_trust_cache()
            return True
        except Exception as exc:
            logger.warning(f"Failed deleting certificate {target_name}: {exc}")
            return False
    return False
