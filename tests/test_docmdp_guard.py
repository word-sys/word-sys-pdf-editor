# word-sys-pdf-editor - DocMDP Document Certification & Permissions Test Suite

import io
import pymupdf
import pytest
from datetime import datetime, timezone, timedelta

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509
from cryptography.x509.oid import NameOID

from word_sys_pdf_editor.docmdp_guard import (
    is_docmdp_available,
    inspect_docmdp_permissions,
    can_counter_sign,
    can_modify_content,
    is_document_signed,
)
from word_sys_pdf_editor.digital_signature import sign_pdf_bytes, inspect_pdf_signatures


def _generate_test_pfx(cn: str = "Test Signer") -> bytes:
    key = rsa.generate_private_key(65537, 2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"cert", key, cert, None, serialization.NoEncryption()
    )


def _create_blank_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    b = doc.tobytes()
    doc.close()
    return b


def test_unsigned_pdf():
    pdf = _create_blank_pdf()
    assert is_document_signed(pdf) is False

    info = inspect_docmdp_permissions(pdf)
    assert info["is_certified"] is False
    assert info["has_signatures"] is False
    assert info["allows_counter_signing"] is True
    assert info["allows_form_filling"] is True
    assert info["allows_annotations"] is True

    allowed, err = can_counter_sign(pdf)
    assert allowed is True
    assert err is None

    can_mod, _ = can_modify_content(pdf)
    assert can_mod is True


def test_certify_level_1_no_changes():
    pdf = _create_blank_pdf()
    pfx = _generate_test_pfx("Author Certifier")

    # Sign as Level 1: NO_CHANGES
    signed_bytes, err = sign_pdf_bytes(
        pdf_bytes=pdf,
        pfx_data_or_path=pfx,
        field_name="CertificationSig",
        certify=True,
        docmdp_permissions=1,
    )
    assert err is None
    assert signed_bytes is not None

    assert is_document_signed(signed_bytes) is True
    info = inspect_docmdp_permissions(signed_bytes)
    assert info["is_certified"] is True
    assert info["permission"] == 1
    assert info["permission_name"] == "NO_CHANGES"
    assert info["allows_counter_signing"] is False
    assert info["allows_form_filling"] is False
    assert info["allows_annotations"] is False

    # Check can_counter_sign returns False
    can_counter, block_err = can_counter_sign(signed_bytes)
    assert can_counter is False
    assert "NO_CHANGES" in block_err

    # Check can_modify_content returns False
    can_mod, mod_err = can_modify_content(signed_bytes)
    assert can_mod is False
    assert "NO_CHANGES" in mod_err

    # Attempting to sign again must be rejected
    pfx2 = _generate_test_pfx("Second Signer")
    counter_bytes, err2 = sign_pdf_bytes(
        pdf_bytes=signed_bytes,
        pfx_data_or_path=pfx2,
        field_name="SecondSig",
    )
    assert counter_bytes is None
    assert "NO_CHANGES" in err2


def test_certify_level_2_counter_signing_and_byte_range_integrity():
    pdf = _create_blank_pdf()
    pfx1 = _generate_test_pfx("First Author")

    # 1. Sign as Level 2: FILL_FORMS
    signed_1, err1 = sign_pdf_bytes(
        pdf_bytes=pdf,
        pfx_data_or_path=pfx1,
        field_name="Sig1",
        certify=True,
        docmdp_permissions=2,
    )
    assert err1 is None
    assert signed_1 is not None

    info1 = inspect_docmdp_permissions(signed_1)
    assert info1["is_certified"] is True
    assert info1["permission"] == 2
    assert info1["allows_counter_signing"] is True
    assert info1["allows_form_filling"] is True
    assert info1["allows_annotations"] is False

    can_counter, _ = can_counter_sign(signed_1)
    assert can_counter is True

    # 2. Counter-sign with Signer 2
    pfx2 = _generate_test_pfx("Second Approver")
    signed_2, err2 = sign_pdf_bytes(
        pdf_bytes=signed_1,
        pfx_data_or_path=pfx2,
        field_name="Sig2",
    )
    assert err2 is None
    assert signed_2 is not None

    # Inspect signatures on the counter-signed document
    sigs = inspect_pdf_signatures(signed_2)
    assert len(sigs) == 2

    sig1_info = next(s for s in sigs if s["field_name"] == "Sig1")
    sig2_info = next(s for s in sigs if s["field_name"] == "Sig2")

    # Sig1 must be intact, valid, certified, and docmdp_ok
    assert sig1_info["intact"] is True
    assert sig1_info["valid"] is True
    assert sig1_info["is_certification"] is True
    assert sig1_info["docmdp_permission"] == 2
    assert sig1_info["docmdp_ok"] is True
    assert "REVISION" in sig1_info["coverage"]

    # Sig2 must be intact, valid, and docmdp_ok
    assert sig2_info["intact"] is True
    assert sig2_info["valid"] is True
    assert sig2_info["is_certification"] is False
    assert sig2_info["docmdp_ok"] is True
    assert "ENTIRE_FILE" in sig2_info["coverage"]
