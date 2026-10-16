from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

try:
    import pkcs11
    from pkcs11 import Attribute, ObjectClass
    from pkcs11.exceptions import PinIncorrect, PinLocked, DeviceRemoved, PKCS11Error
    PKCS11_AVAILABLE = True
except ImportError:
    pkcs11 = None
    Attribute = None
    ObjectClass = None
    PinIncorrect = Exception
    PinLocked = Exception
    DeviceRemoved = Exception
    PKCS11Error = Exception
    PKCS11_AVAILABLE = False

try:
    import pyhanko.sign.pkcs11 as p11_signer
    from pyhanko.config.pkcs11 import TokenCriteria
    PYHANKO_PKCS11_AVAILABLE = True
except ImportError:
    p11_signer = None
    TokenCriteria = None
    PYHANKO_PKCS11_AVAILABLE = False

try:
    import asn1crypto.x509
    ASN1CRYPTO_AVAILABLE = True
except ImportError:
    asn1crypto = None
    ASN1CRYPTO_AVAILABLE = False


KNOWN_PKCS11_MODULES: List[Tuple[str, str]] = [
    # Universal p11-kit Proxy
    ("p11-kit Proxy (Debian/Ubuntu)", "/usr/lib/x86_64-linux-gnu/p11-kit-proxy.so"),
    ("p11-kit Proxy (Standard)", "/usr/lib/p11-kit-proxy.so"),
    ("p11-kit Proxy (Lib64)", "/usr/lib64/p11-kit-proxy.so"),

    # OpenSC
    ("OpenSC (Debian/Ubuntu)", "/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so"),
    ("OpenSC (Standard)", "/usr/lib/opensc-pkcs11.so"),
    ("OpenSC (Lib64)", "/usr/lib64/opensc-pkcs11.so"),
    ("OpenSC (Flatpak)", "/app/lib/opensc-pkcs11.so"),

    # TÜBİTAK Kamu SM (AKİS)
    ("AKİS (TÜBİTAK Kamu SM)", "/usr/lib/libakisp11.so"),
    ("AKİS (TÜBİTAK Kamu SM /lib)", "/lib/libakisp11.so"),

    # SafeNet / Thales / Gemalto
    ("SafeNet / Thales eToken", "/usr/lib/libeTPkcs11.so"),
    ("SafeNet / Thales eToken (Lib64)", "/usr/lib64/libeTPkcs11.so"),
    ("Thales / Gemalto IDPrime", "/usr/lib/libIDPrimePKCS11.so"),
    ("Thales / Gemalto IDPrime (Lib64)", "/usr/lib64/libIDPrimePKCS11.so"),

    # AET SafeSign (Türktrüst)
    ("SafeSign / Türktrüst", "/usr/lib/libaetpkss.so"),
    ("SafeSign / Türktrüst (.so.3)", "/usr/lib/libaetpkss.so.3"),

    # SoftHSM2 (Development / Testing)
    ("SoftHSM2 (Standard)", "/usr/lib/softhsm/libsofthsm2.so"),
    ("SoftHSM2 (Debian/Ubuntu)", "/usr/lib/x86_64-linux-gnu/softhsm/libsofthsm2.so"),
    ("SoftHSM2 (Fedora/RHEL)", "/usr/lib64/pkcs11/libsofthsm2.so"),
]


def is_pkcs11_engine_available() -> bool:
    return PKCS11_AVAILABLE and PYHANKO_PKCS11_AVAILABLE and ASN1CRYPTO_AVAILABLE


def find_available_pkcs11_drivers(custom_path: Optional[str] = None) -> List[Dict[str, str]]:
    drivers: List[Dict[str, str]] = []
    seen_paths = set()

    if custom_path and os.path.isfile(custom_path):
        resolved = os.path.realpath(custom_path)
        drivers.append({"name": "Custom Driver", "path": resolved})
        seen_paths.add(resolved)

    for name, path in KNOWN_PKCS11_MODULES:
        if os.path.isfile(path):
            resolved = os.path.realpath(path)
            if resolved not in seen_paths:
                drivers.append({"name": name, "path": resolved})
                seen_paths.add(resolved)

    return drivers


def list_tokens(module_path: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not PKCS11_AVAILABLE:
        return [], "PKCS#11 subsystem is not installed or available"

    if not module_path or not os.path.isfile(module_path):
        return [], f"PKCS#11 driver not found: {module_path}"

    try:
        lib = pkcs11.lib(module_path)
        slots = lib.get_slots(token_present=True)
        tokens_info: List[Dict[str, Any]] = []

        for slot in slots:
            try:
                tok = slot.get_token()
                label = str(tok.label).strip()
                manufacturer = str(tok.manufacturer_id).strip()
                model = str(tok.model).strip()
                serial_val = getattr(tok, "serial", None)
                serial = str(serial_val).strip() if serial_val is not None else ""
                tokens_info.append({
                    "slot_id": int(slot.slot_id),
                    "token_label": label or f"Slot {slot.slot_id}",
                    "manufacturer": manufacturer,
                    "model": model,
                    "serial_number": serial,
                })
            except Exception as slot_exc:
                logging.debug("Failed reading token in slot %s: %s", slot, slot_exc)

        return tokens_info, None
    except Exception as exc:
        logging.error("Failed to enumerate PKCS#11 tokens in %s: %s", module_path, exc)
        return [], f"Failed to access PKCS#11 driver: {exc}"


def list_token_certificates(
    module_path: str,
    slot_id: Optional[int] = None,
    token_label: Optional[str] = None,
    user_pin: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not is_pkcs11_engine_available():
        return [], "PKCS#11 or ASN.1 cryptographic parser is not available"

    if not module_path or not os.path.isfile(module_path):
        return [], f"PKCS#11 driver not found: {module_path}"

    try:
        lib = pkcs11.lib(module_path)
        token = None
        if slot_id is not None:
            slot = lib.get_slot(slot_id)
            token = slot.get_token()
        elif token_label:
            target_label = token_label.strip()
            for s in lib.get_slots(token_present=True):
                try:
                    tok = s.get_token()
                    if str(tok.label).strip() == target_label:
                        token = tok
                        break
                except Exception:
                    continue
            if token is None:
                return [], f"Token '{token_label}' not found"
        else:
            slots = lib.get_slots(token_present=True)
            if not slots:
                return [], "No active smart card or hardware token detected"
            token = slots[0].get_token()

        certs: List[Dict[str, Any]] = []
        with token.open(user_pin=user_pin) as session:
            for obj in session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}):
                try:
                    raw_der = bytes(obj[Attribute.VALUE])
                    asn1_cert = asn1crypto.x509.Certificate.load(raw_der)
                    try:
                        label = str(obj[Attribute.LABEL] or "")
                    except Exception:
                        label = ""
                    try:
                        cert_id_raw = obj[Attribute.ID]
                        cert_id_bytes = bytes(cert_id_raw) if cert_id_raw else b""
                    except Exception:
                        cert_id_bytes = b""

                    subj = asn1_cert.subject.native if hasattr(asn1_cert.subject, "native") else {}
                    subject_cn = subj.get("common_name", getattr(asn1_cert.subject, "human_friendly", "Hardware Certificate"))
                    subject_org = subj.get("organization_name", "")
                    subject_friendly = getattr(asn1_cert.subject, "human_friendly", subject_cn)

                    iss = asn1_cert.issuer.native if hasattr(asn1_cert.issuer, "native") else {}
                    issuer_cn = iss.get("common_name", getattr(asn1_cert.issuer, "human_friendly", ""))
                    issuer_org = iss.get("organization_name", "")
                    issuer_friendly = getattr(asn1_cert.issuer, "human_friendly", issuer_cn)

                    tbs = asn1_cert["tbs_certificate"]
                    validity = tbs["validity"]
                    not_before = validity["not_before"].native
                    not_after = validity["not_after"].native
                    now = datetime.now(timezone.utc)
                    if not_before.tzinfo is None:
                        not_before = not_before.replace(tzinfo=timezone.utc)
                    if not_after.tzinfo is None:
                        not_after = not_after.replace(tzinfo=timezone.utc)
                    is_expired = now > not_after or now < not_before

                    key_usage = set()
                    if asn1_cert.key_usage_value:
                        key_usage = asn1_cert.key_usage_value.native or set()

                    is_signing = "digital_signature" in key_usage or "non_repudiation" in key_usage
                    is_qualified = "non_repudiation" in key_usage

                    badge = "[Qualified Signing / Non-Repudiation]" if is_qualified else (
                        "[Digital Signature]" if is_signing else "[Authentication Only]"
                    )

                    certs.append({
                        "label": label or subject_cn,
                        "cert_id_hex": cert_id_bytes.hex(),
                        "cert_id_bytes": cert_id_bytes,
                        "subject_cn": subject_cn,
                        "subject_org": subject_org,
                        "subject_friendly": subject_friendly,
                        "issuer_cn": issuer_cn,
                        "issuer_org": issuer_org,
                        "issuer_friendly": issuer_friendly,
                        "not_before": not_before,
                        "not_after": not_after,
                        "is_expired": is_expired,
                        "serial_number": str(asn1_cert.serial_number),
                        "sha256_fingerprint": asn1_cert.sha256.hex(),
                        "key_usage": list(key_usage),
                        "is_signing": is_signing,
                        "is_qualified": is_qualified,
                        "badge": badge,
                    })
                except Exception as cert_parse_exc:
                    logging.debug("Skipping unparseable certificate: %s", cert_parse_exc)

        # Prioritize qualified signing certificates, then standard signing certificates
        certs.sort(key=lambda c: (c["is_qualified"], c["is_signing"]), reverse=True)
        return certs, None

    except PinIncorrect:
        return [], "Incorrect PIN for hardware token"
    except PinLocked:
        return [], "Hardware token PIN is locked. PUK unblock required"
    except DeviceRemoved:
        return [], "Smart card or hardware token was removed"
    except Exception as exc:
        logging.error("Failed to list certificates from PKCS#11 token: %s", exc)
        return [], f"Failed to read certificates: {exc}"


def create_pkcs11_signer(
    module_path: str,
    slot_id: Optional[int] = None,
    token_label: Optional[str] = None,
    user_pin: Optional[str] = None,
    cert_label: Optional[str] = None,
    cert_id: Optional[bytes] = None,
) -> Tuple[Optional[Any], Optional[Any], Optional[str]]:
    """
    Open an active PKCS#11 session and instantiate a pyHanko PKCS11Signer.

    Returns:
        (signer, session, error_message)
    """
    if not is_pkcs11_engine_available():
        return None, None, "PKCS#11 signing engine is not available"

    if not module_path or not os.path.isfile(module_path):
        return None, None, f"PKCS#11 driver not found: {module_path}"

    token_criteria = None
    if token_label:
        token_criteria = TokenCriteria(label=token_label.strip())

    try:
        session = p11_signer.open_pkcs11_session(
            lib_location=module_path,
            slot_no=slot_id,
            token_criteria=token_criteria,
            user_pin=user_pin,
        )

        signer = p11_signer.PKCS11Signer(
            pkcs11_session=session,
            cert_label=cert_label,
            cert_id=cert_id,
            key_label=cert_label,
            key_id=cert_id,
        )

        return signer, session, None

    except PinIncorrect:
        return None, None, "Incorrect PIN for hardware token"
    except PinLocked:
        return None, None, "Hardware token PIN is locked. PUK unblock required"
    except DeviceRemoved:
        return None, None, "Smart card or hardware token was removed"
    except PKCS11Error as pk_err:
        return None, None, f"PKCS#11 hardware token error: {pk_err}"
    except Exception as exc:
        logging.error("Failed to initialize PKCS#11 signer: %s", exc)
        return None, None, f"Hardware signer initialization failed: {exc}"
