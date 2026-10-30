"""Consolidated Signatures and Security Test Suite for word-sys-pdf-editor.

This suite merges digital signatures, PAdES signing, PKCS#11 token management,
TSA timestamp clients, trust store certificate management, DocMDP permissions guard,
sandboxed licensing, and signature UI dialog tests.
"""
from __future__ import annotations


# ============================================================================
# SECTION: test_digital_signature.py
# ============================================================================
# Unit and integration tests for PAdES PKCS#7 Digital Signatures and Bug Fixes

import datetime
import io
import os
import pytest
import fitz

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12, BestAvailableEncryption

from word_sys_pdf_editor.digital_signature import (
    is_pyhanko_available,
    load_pkcs12_certificate,
    sign_pdf_bytes,
    inspect_pdf_signatures,
)
from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.i18n import _STRINGS
from word_sys_pdf_editor.locales import (
    STRINGS_FR,
    STRINGS_DE,
    STRINGS_ES,
    STRINGS_IT,
    STRINGS_RU,
)


@pytest.fixture(scope="module")
def pfx_cert_and_password():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Test Author"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "word-sys Security"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
    ).sign(key, hashes.SHA256())

    pfx_data = pkcs12.serialize_key_and_certificates(
        name=b"test_key",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=BestAvailableEncryption(b"test_pass123"),
    )
    return pfx_data, "test_pass123"


def test_certificate_loading(pfx_cert_and_password):
    if not is_pyhanko_available():
        pytest.skip("pyHanko not installed")
    pfx_data, password = pfx_cert_and_password

    signer, cert_info, err = load_pkcs12_certificate(pfx_data, passphrase=password)
    assert err is None
    assert signer is not None
    assert cert_info is not None
    assert cert_info["subject_cn"] == "Test Author"
    assert cert_info["subject_org"] == "word-sys Security"

    bad_signer, bad_info, bad_err = load_pkcs12_certificate(pfx_data, passphrase="wrong_password")
    assert bad_signer is None
    assert bad_err is not None


def test_visible_signature_default_box(pfx_cert_and_password):
    if not is_pyhanko_available():
        pytest.skip("pyHanko not installed")
    pfx_data, password = pfx_cert_and_password

    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    pdf_bytes = doc.tobytes()

    signed_bytes, err = sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pfx_data_or_path=pfx_data,
        passphrase=password,
        page_index=0,
        box=None,
        visual_stamp=True,
        signer_name="Test Author",
        reason="Document Approval",
    )
    assert err is None
    assert signed_bytes is not None

    signed_doc = fitz.open(stream=signed_bytes, filetype="pdf")
    assert len(signed_doc) == 1
    widgets = list(signed_doc[0].widgets())
    assert len(widgets) >= 1

    sig_w = widgets[0]
    assert sig_w.field_type_string == "Signature"
    rect = sig_w.rect
    assert 150.0 <= rect.width <= 260.0
    assert 40.0 <= rect.height <= 60.0
    assert rect.x0 > 300.0
    assert rect.y0 > 700.0

    page_text = signed_doc[0].get_text()
    assert "Test Author" in page_text
    assert "Document Approval" in page_text


def test_signature_positions(pfx_cert_and_password):
    if not is_pyhanko_available():
        pytest.skip("pyHanko not installed")
    pfx_data, password = pfx_cert_and_password

    doc = fitz.open()
    doc.new_page(width=600.0, height=800.0)
    pdf_bytes = doc.tobytes()

    # Bottom Left
    box_bl = (40.0, 800.0 - 65.0 - 50.0, 220.0, 65.0)
    signed_bl, _ = sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pfx_data_or_path=pfx_data,
        passphrase=password,
        box=box_bl,
        page_height=800.0,
        page_width=600.0,
        visual_stamp=True,
    )
    doc_bl = fitz.open(stream=signed_bl, filetype="pdf")
    rect_bl = list(doc_bl[0].widgets())[0].rect
    assert rect_bl.x0 == 40.0

    # Top Right
    box_tr = (600.0 - 220.0 - 40.0, 40.0, 220.0, 65.0)
    signed_tr, _ = sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pfx_data_or_path=pfx_data,
        passphrase=password,
        box=box_tr,
        page_height=800.0,
        page_width=600.0,
        visual_stamp=True,
    )
    doc_tr = fitz.open(stream=signed_tr, filetype="pdf")
    rect_tr = list(doc_tr[0].widgets())[0].rect
    assert rect_tr.x0 == 340.0
    assert rect_tr.y0 == 40.0


def test_invisible_signature(pfx_cert_and_password):
    if not is_pyhanko_available():
        pytest.skip("pyHanko not installed")
    pfx_data, password = pfx_cert_and_password

    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    pdf_bytes = doc.tobytes()

    signed_bytes, err = sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pfx_data_or_path=pfx_data,
        passphrase=password,
        visual_stamp=False,
    )
    assert err is None
    assert signed_bytes is not None

    signed_doc = fitz.open(stream=signed_bytes, filetype="pdf")
    widgets = list(signed_doc[0].widgets())
    assert len(widgets) == 1
    rect = widgets[0].rect
    assert rect.width == 0.0 or rect.height == 0.0


def test_inspect_document_signatures(pfx_cert_and_password):
    if not is_pyhanko_available():
        pytest.skip("pyHanko not installed")
    pfx_data, password = pfx_cert_and_password

    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    pdf_bytes = doc.tobytes()

    signed_bytes, _ = sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pfx_data_or_path=pfx_data,
        passphrase=password,
        signer_name="Valid Signer",
    )

    sigs = inspect_pdf_signatures(signed_bytes)
    assert len(sigs) == 1
    assert sigs[0]["intact"] is True
    assert sigs[0]["signer_cn"] == "Test Author" or sigs[0]["signer_friendly"] != ""

    tampered_bytes = bytearray(signed_bytes)
    idx = tampered_bytes.find(b"/ByteRange")
    if idx != -1:
        tampered_bytes[idx + 2] = ord("X")
    tampered_sigs = inspect_pdf_signatures(bytes(tampered_bytes))
    if tampered_sigs:
        assert tampered_sigs[0]["intact"] is False


def test_localization_keys_presence():
    keys = [
        "sig_select_cert_title",
        "sig_position",
        "sig_pos_bottom_right",
        "sig_pos_bottom_left",
        "sig_pos_top_right",
        "sig_pos_top_left",
    ]
    all_dicts = [
        ("en", _STRINGS["en"]),
        ("tr", _STRINGS["tr"]),
        ("fr", STRINGS_FR),
        ("de", STRINGS_DE),
        ("es", STRINGS_ES),
        ("it", STRINGS_IT),
        ("ru", STRINGS_RU),
    ]

    for lang_code, d in all_dicts:
        for k in keys:
            assert k in d, f"Missing key {k} in language {lang_code}"


def test_signature_dialog_ui_headless():
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk, Adw
    from word_sys_pdf_editor.signature_dialog import DigitalSignatureDialog, SignatureDetailsDialog

    dlg = DigitalSignatureDialog(parent_window=None, page_count=3, current_page=1)
    assert hasattr(dlg, "position_combo")
    assert hasattr(dlg, "position_row")
    assert dlg.position_combo.get_model().get_n_items() == 4

    dlg.visible_switch.set_active(False)
    assert dlg.position_row.get_sensitive() is False
    assert dlg.page_row.get_sensitive() is False
    dlg.visible_switch.set_active(True)
    assert dlg.position_row.get_sensitive() is True
    assert dlg.page_row.get_sensitive() is True
    dlg.destroy()

    details_dlg = SignatureDetailsDialog(parent_window=None, signatures=[])
    assert not hasattr(details_dlg, "close_btn")
    details_dlg.destroy()


def test_signature_contact_and_unicode_location(pfx_cert_and_password):
    if not is_pyhanko_available():
        pytest.skip("pyHanko not installed")
    pfx_data, password = pfx_cert_and_password

    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    pdf_bytes = doc.tobytes()
    doc.close()

    loc = "Muğla, Muğla, Republic Of Turkey"
    contact = "barin@example.com"

    signed_bytes, err = sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pfx_data_or_path=pfx_data,
        passphrase=password,
        signer_name="Barin Guzeldemirci",
        reason="I am the author of this document",
        location=loc,
        contact_info=contact,
        visual_stamp=True,
    )
    assert err is None, err
    assert signed_bytes is not None

    doc2 = fitz.open("pdf", signed_bytes)
    page_text = doc2[0].get_text()
    doc2.close()

    assert "Contact: barin@example.com" in page_text
    assert "þÿ" not in page_text
    assert "Location: Mugla, Mugla, Republic Of Turkey" in page_text

    sigs = inspect_pdf_signatures(signed_bytes)
    assert len(sigs) == 1
    assert sigs[0]["intact"] is True
    assert sigs[0]["location"] == loc
    assert sigs[0]["contact_info"] == contact

    from word_sys_pdf_editor.signature_dialog import SignatureDetailsDialog
    details_dlg = SignatureDetailsDialog(parent_window=None, signatures=sigs)
    assert details_dlg is not None
    details_dlg.destroy()


# ============================================================================
# SECTION: test_enterprise_signing.py
# ============================================================================

import os
import shutil
import tempfile
import unittest
import datetime
import subprocess

import pymupdf
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12, BestAvailableEncryption, Encoding
import asn1crypto.x509
import asn1crypto.keys
from pyhanko.sign.timestamps import DummyTimeStamper

from word_sys_pdf_editor.digital_signature import sign_pdf_bytes, inspect_pdf_signatures
from word_sys_pdf_editor.pades_signer import PADES_B_B, PADES_B_T, PADES_B_LT
from word_sys_pdf_editor.docmdp_guard import (
    can_counter_sign,
    can_modify_content,
    inspect_docmdp_permissions,
)
from word_sys_pdf_editor.pkcs11_manager import list_tokens, list_token_certificates


def generate_test_p12(common_name: str, password: bytes) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"test",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=BestAvailableEncryption(password),
    )


def generate_mock_tsa() -> DummyTimeStamper:
    tsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tsa_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mock RFC 3161 TSA Authority")])
    tsa_cert = (
        x509.CertificateBuilder()
        .subject_name(tsa_name)
        .issuer_name(tsa_name)
        .public_key(tsa_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(tsa_key, hashes.SHA256())
    )
    tsa_cert_asn1 = asn1crypto.x509.Certificate.load(tsa_cert.public_bytes(Encoding.DER))
    from cryptography.hazmat.primitives.serialization import PrivateFormat, NoEncryption
    key_der = tsa_key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    tsa_key_asn1 = asn1crypto.keys.PrivateKeyInfo.load(key_der)
    return DummyTimeStamper(tsa_cert=tsa_cert_asn1, tsa_key=tsa_key_asn1)


def create_sample_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595.0, height=842.0)
    page.insert_text((50, 100), "Enterprise Legal Document Verification")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class TestEnterpriseSigning(unittest.TestCase):
    def test_pades_b_b_signing_and_verification(self):
        pdf_bytes = create_sample_pdf()
        p12_data = generate_test_p12("Alice Corporate Officer", b"secure_pass")

        signed_pdf, err = sign_pdf_bytes(
            pdf_bytes=pdf_bytes,
            pfx_data_or_path=p12_data,
            passphrase="secure_pass",
            field_name="Signature_Alice",
            reason="Commercial Contract Approval",
            location="Berlin, DE",
            pades_profile=PADES_B_B,
        )
        self.assertIsNone(err)
        self.assertIsNotNone(signed_pdf)
        self.assertGreater(len(signed_pdf), len(pdf_bytes))

        signatures = inspect_pdf_signatures(signed_pdf)
        self.assertEqual(len(signatures), 1)
        sig = signatures[0]
        self.assertEqual(sig["field_name"], "Signature_Alice")
        self.assertEqual(sig["signer_cn"], "Alice Corporate Officer")
        self.assertEqual(sig["reason"], "Commercial Contract Approval")
        self.assertEqual(sig["location"], "Berlin, DE")
        self.assertTrue(sig["intact"])
        self.assertTrue(sig["valid"])
        self.assertEqual(sig["pades_profile"], "B-B")
        self.assertIsNotNone(sig["cert_der"])
        self.assertIsNotNone(sig["cert_pem"])

    def test_pades_b_t_timestamp_embedding(self):
        pdf_bytes = create_sample_pdf()
        p12_data = generate_test_p12("Bob Legal Signer", b"pass123")
        dummy_tsa = generate_mock_tsa()

        signed_pdf, err = sign_pdf_bytes(
            pdf_bytes=pdf_bytes,
            pfx_data_or_path=p12_data,
            passphrase="pass123",
            field_name="Signature_Bob_TSA",
            pades_profile=PADES_B_T,
            timestamper=dummy_tsa,
        )
        self.assertIsNone(err)
        self.assertIsNotNone(signed_pdf)

        signatures = inspect_pdf_signatures(signed_pdf)
        self.assertEqual(len(signatures), 1)
        sig = signatures[0]
        self.assertEqual(sig["pades_profile"], "B-T")
        self.assertTrue(sig["intact"])
        self.assertTrue(sig["valid"])
        self.assertIsNotNone(sig["tsa_timestamp"])
        self.assertTrue(sig["tsa_valid"])
        self.assertEqual(sig["tsa_cn"], "Mock RFC 3161 TSA Authority")

    def test_incremental_co_signing(self):
        pdf_bytes = create_sample_pdf()
        p12_primary = generate_test_p12("Primary Signer", b"pass1")
        p12_secondary = generate_test_p12("Secondary Signer", b"pass2")

        signed_first, err1 = sign_pdf_bytes(
            pdf_bytes=pdf_bytes,
            pfx_data_or_path=p12_primary,
            passphrase="pass1",
            field_name="Sig_Primary",
        )
        self.assertIsNone(err1)

        signed_second, err2 = sign_pdf_bytes(
            pdf_bytes=signed_first,
            pfx_data_or_path=p12_secondary,
            passphrase="pass2",
            field_name="Sig_Secondary",
        )
        self.assertIsNone(err2)

        signatures = inspect_pdf_signatures(signed_second)
        self.assertEqual(len(signatures), 2)

        sig1 = next(s for s in signatures if s["field_name"] == "Sig_Primary")
        sig2 = next(s for s in signatures if s["field_name"] == "Sig_Secondary")

        self.assertTrue(sig1["intact"])
        self.assertTrue(sig1["valid"])
        self.assertEqual(sig1["signer_cn"], "Primary Signer")

        self.assertTrue(sig2["intact"])
        self.assertTrue(sig2["valid"])
        self.assertEqual(sig2["signer_cn"], "Secondary Signer")

    def test_tamper_detection_byte_range_integrity(self):
        pdf_bytes = create_sample_pdf()
        p12_data = generate_test_p12("Tamper Signer", b"pass")

        signed_pdf, err = sign_pdf_bytes(
            pdf_bytes=pdf_bytes,
            pfx_data_or_path=p12_data,
            passphrase="pass",
            field_name="Sig_Tamper",
        )
        self.assertIsNone(err)

        corrupted = bytearray(signed_pdf)
        corrupted[100] = corrupted[100] ^ 0xFF

        signatures = inspect_pdf_signatures(bytes(corrupted))
        self.assertEqual(len(signatures), 1)
        self.assertFalse(signatures[0]["intact"])

    def test_docmdp_certification_level_1_lock(self):
        pdf_bytes = create_sample_pdf()
        p12_data = generate_test_p12("Author Certifier", b"pass")

        signed_pdf, err = sign_pdf_bytes(
            pdf_bytes=pdf_bytes,
            pfx_data_or_path=p12_data,
            passphrase="pass",
            field_name="AuthorSeal",
            certify=True,
            docmdp_permissions=1,
        )
        self.assertIsNone(err)

        mdp_info = inspect_docmdp_permissions(signed_pdf)
        self.assertTrue(mdp_info["is_certified"])
        self.assertEqual(mdp_info["permission"], 1)
        self.assertFalse(mdp_info["allows_counter_signing"])
        self.assertFalse(mdp_info["allows_form_filling"])
        self.assertFalse(mdp_info["allows_annotations"])

        can_sign, blocked_msg = can_counter_sign(signed_pdf)
        self.assertFalse(can_sign)
        self.assertIn("NO_CHANGES", blocked_msg)

        can_mod, mod_msg = can_modify_content(signed_pdf)
        self.assertFalse(can_mod)
        self.assertIn("NO_CHANGES", mod_msg)

        p12_second = generate_test_p12("Second Party", b"pass")
        _, rejected_err = sign_pdf_bytes(
            pdf_bytes=signed_pdf,
            pfx_data_or_path=p12_second,
            passphrase="pass",
            field_name="Sig_Blocked",
        )
        self.assertIsNotNone(rejected_err)
        self.assertIn("NO_CHANGES", rejected_err)

    def test_docmdp_certification_level_2_counter_signing(self):
        pdf_bytes = create_sample_pdf()
        p12_data = generate_test_p12("Author Certifier Level 2", b"pass")

        signed_pdf, err = sign_pdf_bytes(
            pdf_bytes=pdf_bytes,
            pfx_data_or_path=p12_data,
            passphrase="pass",
            field_name="AuthorSealL2",
            certify=True,
            docmdp_permissions=2,
        )
        self.assertIsNone(err)

        mdp_info = inspect_docmdp_permissions(signed_pdf)
        self.assertTrue(mdp_info["is_certified"])
        self.assertEqual(mdp_info["permission"], 2)
        self.assertTrue(mdp_info["allows_counter_signing"])
        self.assertTrue(mdp_info["allows_form_filling"])
        self.assertFalse(mdp_info["allows_annotations"])

        can_sign, _ = can_counter_sign(signed_pdf)
        self.assertTrue(can_sign)

    def test_pkcs11_hardware_signer_dispatch(self):
        from unittest.mock import MagicMock, patch
        pdf_bytes = create_sample_pdf()

        mock_signer = MagicMock()
        mock_signer.signing_cert = None
        mock_session = MagicMock()

        with patch("word_sys_pdf_editor.digital_signature.create_pkcs11_signer", return_value=(mock_signer, mock_session, None)) as mock_create:
            with patch("pyhanko.pdf_utils.incremental_writer.IncrementalPdfFileWriter"):
                with patch("pyhanko.sign.signers.PdfSigner.async_sign_pdf"):
                    sign_pdf_bytes(
                        pdf_bytes=pdf_bytes,
                        pkcs11_driver="/usr/lib/libopensc.so",
                        pkcs11_slot_id=2,
                        pkcs11_token_label="CorporateToken",
                        pkcs11_pin="123456",
                        pkcs11_cert_label="NonRepudiationCert",
                    )
            mock_create.assert_called_once_with(
                module_path="/usr/lib/libopensc.so",
                slot_id=2,
                token_label="CorporateToken",
                user_pin="123456",
                cert_label="NonRepudiationCert",
                cert_id=None,
            )
            mock_session.close.assert_called_once()

    def test_certificate_export_der_and_pem_roundtrip(self):
        pdf_bytes = create_sample_pdf()
        p12_data = generate_test_p12("Export Signer", b"pass")

        signed_pdf, err = sign_pdf_bytes(
            pdf_bytes=pdf_bytes,
            pfx_data_or_path=p12_data,
            passphrase="pass",
            field_name="Sig_Export",
        )
        self.assertIsNone(err)

        signatures = inspect_pdf_signatures(signed_pdf)
        self.assertEqual(len(signatures), 1)
        sig = signatures[0]

        der_bytes = sig.get("cert_der")
        pem_str = sig.get("cert_pem")
        self.assertIsNotNone(der_bytes)
        self.assertIsNotNone(pem_str)

        cert_from_der = x509.load_der_x509_certificate(der_bytes)
        cert_from_pem = x509.load_pem_x509_certificate(pem_str.encode("utf-8"))

        self.assertEqual(cert_from_der.serial_number, cert_from_pem.serial_number)
        cn = cert_from_der.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        self.assertEqual(cn, "Export Signer")


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_pades_signer.py
# ============================================================================
# word-sys-pdf-editor - PAdES Baseline Profiles Tests

import io
import datetime
import pytest
import pymupdf
import asn1crypto.x509
import asn1crypto.keys
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from cryptography.x509.oid import NameOID
from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper
from pyhanko_certvalidator import ValidationContext

from word_sys_pdf_editor.pades_signer import (
    PAdESSigningConfig,
    prepare_pades_signature_meta,
    detect_pades_profile,
    PADES_B_B,
    PADES_B_T,
    PADES_B_LT,
    PADES_B_LTA,
)
from word_sys_pdf_editor.digital_signature import sign_pdf_bytes, inspect_pdf_signatures


@pytest.fixture(scope="module")
def crypto_fixtures():
    # 1. Signer key and cert
    priv_key = rsa.generate_private_key(65537, 2048)
    cert = x509.CertificateBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"PAdES Tester")])
    ).issuer_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"PAdES Tester")])
    ).public_key(priv_key.public_key()).serial_number(1001).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
    ).add_extension(
        x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True
    ).sign(priv_key, hashes.SHA256())

    p12_bytes = serialization.pkcs12.serialize_key_and_certificates(
        name=b"PAdES Tester",
        key=priv_key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(b"testpass"),
    )

    # 2. TSA key and cert
    tsa_key = rsa.generate_private_key(65537, 2048)
    tsa_cert = x509.CertificateBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"Local TSA Service")])
    ).issuer_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"Local TSA Service")])
    ).public_key(tsa_key.public_key()).serial_number(1002).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
    ).add_extension(
        x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.TIME_STAMPING]), critical=True
    ).sign(tsa_key, hashes.SHA256())

    asn1_tsa_cert = asn1crypto.x509.Certificate.load(tsa_cert.public_bytes(serialization.Encoding.DER))
    asn1_tsa_key = asn1crypto.keys.PrivateKeyInfo.load(tsa_key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    timestamper = DummyTimeStamper(tsa_cert=asn1_tsa_cert, tsa_key=asn1_tsa_key)

    return {
        "p12_bytes": p12_bytes,
        "passphrase": b"testpass",
        "timestamper": timestamper,
        "asn1_signer_cert": asn1crypto.x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
        "asn1_tsa_cert": asn1_tsa_cert,
    }


@pytest.fixture
def sample_pdf():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), "PAdES Test Document")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_prepare_pades_signature_meta_validation():
    # B-B does not require timestamper
    cfg_bb = PAdESSigningConfig(profile=PADES_B_B)
    meta, ts, err = prepare_pades_signature_meta("Sig1", pades_config=cfg_bb)
    assert err is None
    assert meta is not None
    assert meta.embed_validation_info is False
    assert meta.use_pades_lta is False
    assert ts is None

    # B-T without timestamper must fail
    cfg_bt_no_ts = PAdESSigningConfig(profile=PADES_B_T)
    meta, ts, err = prepare_pades_signature_meta("Sig1", pades_config=cfg_bt_no_ts)
    assert err is not None
    assert "requires a functional Time Stamp Authority" in err


def test_pades_b_b_signing(sample_pdf, crypto_fixtures):
    signed_bytes, err = sign_pdf_bytes(
        pdf_bytes=sample_pdf,
        pfx_data_or_path=crypto_fixtures["p12_bytes"],
        passphrase=crypto_fixtures["passphrase"],
        pades_profile=PADES_B_B,
        signer_name="PAdES Tester",
    )
    assert err is None
    assert signed_bytes is not None

    sigs = inspect_pdf_signatures(signed_bytes)
    assert len(sigs) == 1
    assert sigs[0]["intact"] is True
    assert sigs[0]["valid"] is True
    assert sigs[0]["pades_profile"] == PADES_B_B
    assert sigs[0]["tsa_timestamp"] is None


def test_pades_b_t_signing(sample_pdf, crypto_fixtures):
    signed_bytes, err = sign_pdf_bytes(
        pdf_bytes=sample_pdf,
        pfx_data_or_path=crypto_fixtures["p12_bytes"],
        passphrase=crypto_fixtures["passphrase"],
        pades_profile=PADES_B_T,
        timestamper=crypto_fixtures["timestamper"],
        signer_name="PAdES Tester",
    )
    assert err is None
    assert signed_bytes is not None

    sigs = inspect_pdf_signatures(signed_bytes)
    assert len(sigs) == 1
    assert sigs[0]["intact"] is True
    assert sigs[0]["valid"] is True
    assert sigs[0]["pades_profile"] == PADES_B_T
    assert sigs[0]["tsa_timestamp"] is not None
    assert sigs[0]["tsa_cn"] == "Local TSA Service"


def test_pades_b_lt_and_lta_signing(sample_pdf, crypto_fixtures):
    vc = ValidationContext(
        trust_roots=[crypto_fixtures["asn1_signer_cert"], crypto_fixtures["asn1_tsa_cert"]],
        allow_fetching=False,
    )

    # 1. PAdES B-LT
    lt_bytes, err = sign_pdf_bytes(
        pdf_bytes=sample_pdf,
        pfx_data_or_path=crypto_fixtures["p12_bytes"],
        passphrase=crypto_fixtures["passphrase"],
        pades_profile=PADES_B_LT,
        timestamper=crypto_fixtures["timestamper"],
        validation_context=vc,
        signer_name="PAdES Tester",
    )
    assert err is None
    assert lt_bytes is not None

    sigs_lt = inspect_pdf_signatures(lt_bytes)
    assert len(sigs_lt) == 1
    assert sigs_lt[0]["intact"] is True
    assert sigs_lt[0]["has_dss"] is True
    assert sigs_lt[0]["pades_profile"] in (PADES_B_LT, PADES_B_T)

    # 2. PAdES B-LTA
    lta_bytes, err = sign_pdf_bytes(
        pdf_bytes=sample_pdf,
        pfx_data_or_path=crypto_fixtures["p12_bytes"],
        passphrase=crypto_fixtures["passphrase"],
        pades_profile=PADES_B_LTA,
        timestamper=crypto_fixtures["timestamper"],
        validation_context=vc,
        signer_name="PAdES Tester",
    )
    assert err is None
    assert lta_bytes is not None

    sigs_lta = inspect_pdf_signatures(lta_bytes)
    # B-LTA creates the primary signature plus an archival document timestamp signature
    assert len(sigs_lta) >= 2
    assert sigs_lta[0]["intact"] is True
    assert any(s["is_document_timestamp"] or s["pades_profile"] == PADES_B_LTA for s in sigs_lta)


# ============================================================================
# SECTION: test_pkcs11_manager.py
# ============================================================================
# word-sys-pdf-editor - PKCS#11 Hardware Token & Smart Card Tests

import os
import shutil
import tempfile
import subprocess
import datetime
import pytest
import pymupdf
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from cryptography.x509.oid import NameOID

from word_sys_pdf_editor.pkcs11_manager import (
    find_available_pkcs11_drivers,
    list_tokens,
    list_token_certificates,
    create_pkcs11_signer,
    is_pkcs11_engine_available,
)
from word_sys_pdf_editor.digital_signature import sign_pdf_bytes, inspect_pdf_signatures


def test_pkcs11_engine_availability():
    assert is_pkcs11_engine_available() is True


def test_find_available_pkcs11_drivers():
    drivers = find_available_pkcs11_drivers()
    assert len(drivers) > 0
    # SoftHSM2 and/or OpenSC should be discovered
    driver_names = [d["name"] for d in drivers]
    driver_paths = [d["path"] for d in drivers]
    assert any("softhsm" in p.lower() or "opensc" in p.lower() for p in driver_paths)


@pytest.fixture(scope="module")
def softhsm_token():
    # Detect installed SoftHSM2 library
    softhsm_lib = None
    candidates = [
        "/usr/lib/softhsm/libsofthsm2.so",
        "/usr/lib/x86_64-linux-gnu/softhsm/libsofthsm2.so",
    ]
    for c in candidates:
        if os.path.isfile(c):
            softhsm_lib = c
            break

    if softhsm_lib is None or not shutil.which("softhsm2-util") or not shutil.which("pkcs11-tool"):
        pytest.skip("SoftHSM2 or pkcs11-tool is not installed")

    tmpdir = tempfile.mkdtemp(prefix="wordsys_softhsm_")
    tokens_dir = os.path.join(tmpdir, "tokens")
    os.makedirs(tokens_dir)
    conf_path = os.path.join(tmpdir, "softhsm2.conf")
    with open(conf_path, "w") as f:
        f.write(f"directories.tokendir = {tokens_dir}\nobjectstore.backend = file\nlog.level = ERROR\n")

    orig_conf = os.environ.get("SOFTHSM2_CONF")
    os.environ["SOFTHSM2_CONF"] = conf_path

    token_label = "WordSysHardware"
    user_pin = "1234"
    so_pin = "12345678"

    # 1. Initialize SoftHSM2 token
    subprocess.run([
        "softhsm2-util", "--init-token", "--free",
        "--label", token_label,
        "--so-pin", so_pin,
        "--pin", user_pin,
    ], capture_output=True, check=True)

    # 2. Generate RSA Key Pair
    key = rsa.generate_private_key(65537, 2048)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = os.path.join(tmpdir, "token_key.pem")
    with open(key_path, "wb") as f:
        f.write(key_pem)

    # 3. Import private key into token
    subprocess.run([
        "softhsm2-util", "--import", key_path,
        "--token", token_label,
        "--pin", user_pin,
        "--label", "HardwareSignerKey",
        "--id", "01",
    ], capture_output=True, check=True)

    # 4. Generate Qualified X.509 Certificate with non_repudiation and digital_signature
    cert = x509.CertificateBuilder().subject_name(
        x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"Jane Doe Qualified"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Kamu SM PKI"),
        ])
    ).issuer_name(
        x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"National Qualified Root CA"),
        ])
    ).public_key(key.public_key()).serial_number(777).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
    ).add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=True,  # non-repudiation
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    ).sign(key, hashes.SHA256())

    cert_path = os.path.join(tmpdir, "token_cert.der")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.DER))

    # 5. Import certificate into token using pkcs11-tool
    subprocess.run([
        "pkcs11-tool", "--module", softhsm_lib,
        "--token", token_label,
        "--login", "--pin", user_pin,
        "--write-object", cert_path,
        "--type", "cert",
        "--id", "01",
        "--label", "HardwareSignerKey",
    ], capture_output=True, check=True)

    yield {
        "lib_path": softhsm_lib,
        "token_label": token_label,
        "pin": user_pin,
        "cert_label": "HardwareSignerKey",
    }

    # Cleanup
    if orig_conf:
        os.environ["SOFTHSM2_CONF"] = orig_conf
    else:
        os.environ.pop("SOFTHSM2_CONF", None)
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_pkcs11_list_tokens(softhsm_token):
    tokens, err = list_tokens(softhsm_token["lib_path"])
    assert err is None
    assert len(tokens) >= 1
    found = any(t["token_label"] == softhsm_token["token_label"] for t in tokens)
    assert found is True


def test_pkcs11_list_certificates(softhsm_token):
    # Valid PIN
    certs, err = list_token_certificates(
        module_path=softhsm_token["lib_path"],
        token_label=softhsm_token["token_label"],
        user_pin=softhsm_token["pin"],
    )
    assert err is None
    assert len(certs) == 1
    c = certs[0]
    assert c["subject_cn"] == "Jane Doe Qualified"
    assert c["issuer_cn"] == "National Qualified Root CA"
    assert c["is_qualified"] is True
    assert c["is_signing"] is True
    assert "[Qualified Signing / Non-Repudiation]" in c["badge"]

    # Invalid PIN
    bad_certs, bad_err = list_token_certificates(
        module_path=softhsm_token["lib_path"],
        token_label=softhsm_token["token_label"],
        user_pin="9999",
    )
    assert len(bad_certs) == 0
    assert bad_err is not None
    assert "PIN" in bad_err.upper()


def test_pkcs11_hardware_signing(softhsm_token):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 100), "Signed via Hardware Smart Card")
    pdf_bytes = doc.tobytes()
    doc.close()

    # 1. Test signing with cert_label and empty cert_id (regression test for empty ID query bug)
    signed_bytes, err = sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pkcs11_driver=softhsm_token["lib_path"],
        pkcs11_token_label=softhsm_token["token_label"],
        pkcs11_pin=softhsm_token["pin"],
        pkcs11_cert_label=softhsm_token["cert_label"],
        pkcs11_cert_id=b"",
        signer_name="Jane Doe Qualified",
        reason="Official Approval via Hardware Token",
    )
    assert err is None
    assert signed_bytes is not None

    sigs = inspect_pdf_signatures(signed_bytes)
    assert len(sigs) == 1
    assert sigs[0]["intact"] is True
    assert sigs[0]["valid"] is True
    assert sigs[0]["signer_cn"] == "Jane Doe Qualified"
    assert sigs[0]["reason"] == "Official Approval via Hardware Token"

    # 2. Test signing with explicit byte cert_id
    signed_bytes_id, err_id = sign_pdf_bytes(
        pdf_bytes=pdf_bytes,
        pkcs11_driver=softhsm_token["lib_path"],
        pkcs11_token_label=softhsm_token["token_label"],
        pkcs11_pin=softhsm_token["pin"],
        pkcs11_cert_label=softhsm_token["cert_label"],
        pkcs11_cert_id=b"\x01",
        signer_name="Jane Doe Qualified",
    )
    assert err_id is None
    assert signed_bytes_id is not None

    # 3. Test candidate fallback when label is mismatched but cert_id matches
    signer, session, create_err = create_pkcs11_signer(
        module_path=softhsm_token["lib_path"],
        token_label=softhsm_token["token_label"],
        user_pin=softhsm_token["pin"],
        cert_label="NonExistentLabel",
        cert_id=b"\x01",
    )
    assert create_err is None
    assert signer is not None
    if session:
        session.close()



# ============================================================================
# SECTION: test_trust_manager.py
# ============================================================================
# word-sys-pdf-editor - Universal Global Trust Store Test Suite

import os
import shutil
import tempfile
import pytest
from datetime import timezone, timedelta
import datetime

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from cryptography.x509.oid import NameOID

from word_sys_pdf_editor.trust_manager import (
    is_trust_manager_available,
    get_trusted_roots_dir,
    get_all_trust_roots,
    import_trusted_root,
    list_custom_trusted_roots,
    remove_custom_trusted_root,
    build_validation_context,
    extract_certificate_summary,
    invalidate_trust_cache,
)


@pytest.fixture(autouse=True)
def isolated_trust_store(monkeypatch):
    temp_dir = tempfile.mkdtemp(prefix="wspdf_trust_test_")
    monkeypatch.setenv("XDG_CONFIG_HOME", temp_dir)
    invalidate_trust_cache()
    yield temp_dir
    invalidate_trust_cache()
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_trust_manager_availability():
    assert is_trust_manager_available() is True


def test_load_global_ca_roots():
    roots = get_all_trust_roots()
    assert len(roots) > 50, "Expected at least 50 global root certificates from certifi and system"


def test_import_and_list_custom_trusted_root():
    # Generate test root CA certificate
    key = rsa.generate_private_key(65537, 2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Test Enterprise Root CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme Corporation"),
    ])
    now = datetime.datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(9999)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem_bytes = cert.public_bytes(serialization.Encoding.PEM)

    success, err, summary = import_trusted_root(pem_bytes, filename_hint="acme_root.crt")
    assert success is True
    assert err is None
    assert summary is not None
    assert summary["subject_cn"] == "Test Enterprise Root CA"
    assert summary["subject_org"] == "Acme Corporation"
    assert summary["is_ca"] is True

    custom_list = list_custom_trusted_roots()
    assert len(custom_list) == 1
    assert custom_list[0]["subject_cn"] == "Test Enterprise Root CA"

    # Verify removal
    removed = remove_custom_trusted_root(summary["saved_filename"])
    assert removed is True
    assert len(list_custom_trusted_roots()) == 0


def test_build_validation_context():
    vc_soft = build_validation_context(revocation_mode="soft-fail", force_reload=True)
    assert vc_soft is not None

    vc_hard = build_validation_context(revocation_mode="hard-fail", force_reload=True)
    assert vc_hard is not None


# ============================================================================
# SECTION: test_tsa_client.py
# ============================================================================
# word-sys-pdf-editor - RFC 3161 TSA Client Tests

import pytest
from word_sys_pdf_editor.tsa_client import (
    TSAConfig,
    create_timestamper,
    is_tsa_client_available,
    PRESET_TSAS,
)


def test_tsa_client_availability():
    assert is_tsa_client_available() is True


def test_tsa_config_validation():
    cfg_default = TSAConfig()
    assert cfg_default.is_valid() is True
    assert cfg_default.url == PRESET_TSAS["DigiCert"]

    cfg_invalid = TSAConfig(url="not_a_valid_url")
    assert cfg_invalid.is_valid() is False

    cfg_empty = TSAConfig(url="")
    assert cfg_empty.is_valid() is False

    cfg_custom = TSAConfig(url="https://timestamp.example.com", timeout=20)
    assert cfg_custom.is_valid() is True
    assert cfg_custom.timeout == 20


def test_create_timestamper():
    cfg = TSAConfig(
        url="http://timestamp.digicert.com",
        timeout=10,
        auth_user="testuser",
        auth_password="testpassword",
    )
    timestamper = create_timestamper(cfg)
    assert timestamper is not None
    assert timestamper.url == "http://timestamp.digicert.com"
    assert timestamper.timeout == 10

    # Invalid config should return None
    assert create_timestamper(TSAConfig(url="invalid")) is None
    assert create_timestamper(None) is None


# ============================================================================
# SECTION: test_docmdp_guard.py
# ============================================================================
# word-sys-pdf-editor - DocMDP Document Certification & Permissions Test Suite

import io
import pymupdf
import pytest
from datetime import timezone, timedelta
import datetime

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
    now = datetime.datetime.now(timezone.utc)
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


# ============================================================================
# SECTION: test_sandboxed_license.py
# ============================================================================
# -*- coding: utf-8 -*-
"""Comprehensive test suite for Sandboxed License Asset Embedding.

Verifies:
- get_application_license_text() returns the complete, official GNU General Public License v3 text.
- Resilience in sandboxed Flatpak and AppImage environments where /usr/share/common-licenses does not exist.
- Embedded fallback constant GPL_V3_FULL_TEXT is valid and used when all filesystem paths are missing.
- Package data inclusion in pyproject.toml and installation directives in Flatpak manifests.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from word_sys_pdf_editor import constants
from word_sys_pdf_editor.license_data import GPL_V3_FULL_TEXT


class TestSandboxedLicenseEmbedding(unittest.TestCase):
    """Test license loading and fallback mechanisms across sandboxed runtimes."""

    def test_get_application_license_text_returns_full_gpl3(self):
        text = constants.get_application_license_text()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 10000)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
        self.assertIn("Version 3, 29 June 2007", text)
        self.assertIn("Preamble", text)
        self.assertNotIn("Full text could not be loaded", text)

    def test_embedded_license_data_constant_validity(self):
        self.assertIsInstance(GPL_V3_FULL_TEXT, str)
        self.assertGreater(len(GPL_V3_FULL_TEXT), 30000)
        self.assertIn("Free Software Foundation, Inc.", GPL_V3_FULL_TEXT)

    def test_fallback_when_all_filesystem_paths_absent(self):
        # Simulate environment where no search paths exist (sandboxed container without mounted files)
        with patch.object(Path, "is_file", return_value=False):
            text = constants.get_application_license_text()
            self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
            self.assertGreater(len(text), 10000)
            self.assertNotIn("Full text could not be loaded", text)

    def test_appdir_environment_variable_precedence(self):
        # In AppImage, APPDIR environment variable points to mounted squashfs image
        fake_appdir = "/tmp/.mount_appimage_test"
        with patch.dict(os.environ, {"APPDIR": fake_appdir}):
            text = constants.get_application_license_text()
            self.assertIsInstance(text, str)
            self.assertIn("GNU GENERAL PUBLIC LICENSE", text)

    def test_package_license_file_exists(self):
        pkg_license = Path(__file__).resolve().parent.parent / "word_sys_pdf_editor" / "LICENSE"
        self.assertTrue(pkg_license.is_file(), "Bundled word_sys_pdf_editor/LICENSE must exist for wheel/pip installation")
        content = pkg_license.read_text(encoding="utf-8")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", content)

    def test_third_party_licenses_file_and_debian_copyright(self):
        root_dir = Path(__file__).resolve().parent.parent
        third_party = root_dir / "THIRD_PARTY_LICENSES.md"
        self.assertTrue(third_party.is_file(), "THIRD_PARTY_LICENSES.md must exist in root directory")
        tp_text = third_party.read_text(encoding="utf-8")
        for pkg in ["pyHanko", "cryptography", "certifi", "anyconvert", "NumPy", "PyMuPDF", "Pillow"]:
            self.assertIn(pkg, tp_text, f"Missing attribution for {pkg} in THIRD_PARTY_LICENSES.md")

        deb_copyright = root_dir / "debian" / "copyright"
        self.assertTrue(deb_copyright.is_file(), "debian/copyright must exist")
        deb_text = deb_copyright.read_text(encoding="utf-8")
        self.assertIn("Format:", deb_text)
        self.assertIn("GPL-3.0-or-later", deb_text)
        self.assertIn("pyHanko", deb_text)

    def test_about_credit_libraries_localization(self):
        from word_sys_pdf_editor.i18n import _STRINGS
        from word_sys_pdf_editor.locales import STRINGS_FR, STRINGS_DE, STRINGS_ES, STRINGS_IT, STRINGS_RU
        dicts = [
            ("en", _STRINGS["en"]),
            ("tr", _STRINGS["tr"]),
            ("fr", STRINGS_FR),
            ("de", STRINGS_DE),
            ("es", STRINGS_ES),
            ("it", STRINGS_IT),
            ("ru", STRINGS_RU),
        ]
        for lang, d in dicts:
            self.assertIn("about_credit_libraries", d, f"Missing about_credit_libraries key in language {lang}")


if __name__ == "__main__":
    unittest.main()


# ============================================================================
# SECTION: test_signature_ui.py
# ============================================================================

import unittest
from unittest.mock import MagicMock, patch
from datetime import timezone
import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

from word_sys_pdf_editor.signature_dialog import DigitalSignatureDialog, SignatureDetailsDialog
from word_sys_pdf_editor.pades_signer import PADES_B_B, PADES_B_T, PADES_B_LT, PADES_B_LTA
from word_sys_pdf_editor.tsa_client import PRESET_TSAS, TSAConfig


class TestSignatureUI(unittest.TestCase):
    def test_digital_signature_dialog_initial_box(self):
        dlg_without_box = DigitalSignatureDialog(parent_window=None, page_count=2, current_page=0)
        self.assertEqual(dlg_without_box.position_combo.get_model().get_n_items(), 4)
        dlg_without_box.destroy()

        box = (45.0, 75.0, 190.0, 55.0)
        dlg_with_box = DigitalSignatureDialog(parent_window=None, page_count=2, current_page=0, initial_box=box)
        self.assertEqual(dlg_with_box.position_combo.get_model().get_n_items(), 5)
        self.assertEqual(dlg_with_box.position_combo.get_selected(), 0)
        dlg_with_box.destroy()

    def test_digital_signature_dialog_source_switching(self):
        dlg = DigitalSignatureDialog(parent_window=None, page_count=1, current_page=0)
        self.assertEqual(dlg.cert_source, "software")
        self.assertTrue(dlg.sw_cert_group.get_visible())
        self.assertFalse(dlg.hw_token_group.get_visible())

        with patch("word_sys_pdf_editor.signature_dialog.find_available_pkcs11_drivers", return_value=[{"name": "Mock OpenSC", "path": "/usr/lib/opensc.so"}]):
            dlg.source_combo.set_selected(1)
            self.assertEqual(dlg.cert_source, "hardware")
            self.assertFalse(dlg.sw_cert_group.get_visible())
            self.assertTrue(dlg.hw_token_group.get_visible())

        dlg.source_combo.set_selected(0)
        self.assertEqual(dlg.cert_source, "software")
        self.assertTrue(dlg.sw_cert_group.get_visible())
        self.assertFalse(dlg.hw_token_group.get_visible())
        dlg.destroy()

    def test_digital_signature_dialog_pades_and_tsa(self):
        dlg = DigitalSignatureDialog(parent_window=None, page_count=1, current_page=0)
        self.assertFalse(dlg.tsa_row.get_visible())
        self.assertFalse(dlg.custom_tsa_row.get_visible())
        self.assertFalse(dlg.tsa_auth_row.get_visible())

        dlg.pades_combo.set_selected(1)
        self.assertTrue(dlg.tsa_row.get_visible())
        self.assertFalse(dlg.custom_tsa_row.get_visible())

        dlg.tsa_combo.set_selected(3)
        self.assertTrue(dlg.custom_tsa_row.get_visible())
        self.assertTrue(dlg.tsa_auth_row.get_visible())

        dlg.pades_combo.set_selected(0)
        self.assertFalse(dlg.tsa_row.get_visible())
        self.assertFalse(dlg.custom_tsa_row.get_visible())
        self.assertFalse(dlg.tsa_auth_row.get_visible())
        dlg.destroy()

    def test_digital_signature_dialog_draw_canvas_request(self):
        draw_requested = False

        def on_draw():
            nonlocal draw_requested
            draw_requested = True

        dlg = DigitalSignatureDialog(
            parent_window=None,
            page_count=1,
            current_page=0,
            on_draw_canvas_requested=on_draw,
        )
        dlg._on_draw_canvas_clicked(None)
        self.assertTrue(draw_requested)

    def test_signature_details_dialog_presentation_and_export(self):
        dummy_sig = {
            "field_name": "TestSignature_1",
            "intact": True,
            "valid": True,
            "trusted": True,
            "signer_cn": "Jane Doe",
            "signer_org": "Acme Corp",
            "issuer_cn": "Acme Root CA",
            "pades_profile": PADES_B_LT,
            "tsa_timestamp": datetime.datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
            "tsa_valid": True,
            "tsa_cn": "DigiCert TSA",
            "has_ltv": True,
            "has_dss": True,
            "cert_der": b"\x30\x82\x01\x0a",
            "cert_pem": "-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----\n",
            "sha256_fingerprint": "aabbccddeeff",
            "coverage": "ENTIRE_FILE",
        }

        dlg = SignatureDetailsDialog(parent_window=None, signatures=[dummy_sig])
        self.assertIsNotNone(dlg)

        with patch("word_sys_pdf_editor.signature_dialog.show_save_file_dialog") as mock_save:
            dlg._export_certificate(dummy_sig)
            mock_save.assert_called_once()
            args, kwargs = mock_save.call_args
            self.assertEqual(kwargs.get("initial_name"), "Jane_Doe.cer")

        dlg.destroy()

    def test_window_interactive_canvas_signature_placement(self):
        from word_sys_pdf_editor.window import PdfEditorWindow
        import fitz

        win = PdfEditorWindow()
        doc = fitz.open()
        doc.new_page(width=595.0, height=842.0)
        win.doc = doc
        win.current_pdf_page_width = 595.0
        win.current_pdf_page_height = 842.0
        win.zoom_level = 1.0
        win.view_mode = False
        win.get_page_canvas_rect = MagicMock(return_value=(0.0, 0.0, 595.0, 842.0))

        win.on_tool_selected(None, "place_signature")
        self.assertEqual(win.tool_mode, "place_signature")

        mock_gesture = MagicMock()

        win.on_drag_begin(mock_gesture, 100.0, 200.0)
        self.assertTrue(win.dragging_to_create)
        self.assertIsNotNone(win.temp_sig_bbox)
        self.assertEqual(win.temp_sig_bbox, (100.0, 200.0, 100.0, 200.0))

        win.on_drag_update(mock_gesture, 120.0, 45.0)
        self.assertEqual(win.temp_sig_bbox, (100.0, 200.0, 220.0, 245.0))

        with patch.object(DigitalSignatureDialog, "present") as mock_present:
            win.on_drag_end(mock_gesture, 120.0, 45.0)
            self.assertFalse(win.dragging_to_create)
            self.assertIsNone(win.temp_sig_bbox)
            self.assertEqual(win.tool_mode, "select")
            self.assertIsNotNone(win._digital_sig_dialog)
            self.assertEqual(win._digital_sig_dialog.initial_box, (100.0, 200.0, 120.0, 45.0))
            mock_present.assert_called_once()
            win._digital_sig_dialog.destroy()

        doc.close()
        win.destroy()

    def test_non_blocking_signature_inspection_on_document_open_and_banner_update(self):
        """Verify signed document opens without blocking, shows verifying banner, and updates on completion."""
        import threading
        from gi.repository import GLib
        from word_sys_pdf_editor.window import PdfEditorWindow
        from word_sys_pdf_editor.i18n import _ as tr

        win = PdfEditorWindow()
        doc = fitz.open()
        doc.new_page(width=595.0, height=842.0)

        worker_started = threading.Event()
        release_worker = threading.Event()
        scheduled_callbacks = []

        fake_sigs = [
            {
                "field_name": "Sig1",
                "intact": True,
                "valid": True,
                "trusted": True,
                "signer_cn": "Alice Verified",
            }
        ]

        def slow_inspect(_doc):
            worker_started.set()
            release_worker.wait(timeout=5.0)
            return fake_sigs

        orig_idle_add = GLib.idle_add

        def capture_idle_add(func, *args, **kwargs):
            if getattr(func, "__name__", "") == "_apply_signature_inspection_result":
                scheduled_callbacks.append((func, args))
                return 1
            return orig_idle_add(func, *args, **kwargs)

        try:
            with patch("word_sys_pdf_editor.pdf_handler.inspect_document_signatures", side_effect=slow_inspect), \
                 patch.object(win, "_load_thumbnails"), \
                 patch.object(win, "_load_page"), \
                 patch("gi.repository.GLib.idle_add", side_effect=capture_idle_add):
                sess = win._active_session
                win._finish_loading(doc, None, "signed_test.pdf", 0, sess)

                # _finish_loading returned before slow_inspect finished
                self.assertTrue(worker_started.wait(timeout=2.0))
                self.assertTrue(sess.sig_inspection_in_progress)
                self.assertIsNone(sess.digital_signatures)

                # Banner shows lightweight verifying state
                self.assertTrue(win.signature_banner.get_visible())
                self.assertEqual(win.signature_banner_label.get_text(), tr("sig_banner_verifying"))
                self.assertFalse(win.signature_banner_btn.get_visible())

                # Let worker complete and run main-thread callback
                release_worker.set()
                for _idx in range(50):
                    if scheduled_callbacks:
                        break
                    threading.Event().wait(0.02)

                self.assertEqual(len(scheduled_callbacks), 1)
                cb_func, cb_args = scheduled_callbacks[0]
                cb_func(*cb_args)

                self.assertFalse(sess.sig_inspection_in_progress)
                self.assertEqual(sess.digital_signatures, fake_sigs)
                self.assertTrue(win.signature_banner.get_visible())
                self.assertEqual(
                    win.signature_banner_label.get_text(),
                    tr("sig_banner_single_valid", "Alice Verified"),
                )
                self.assertTrue(win.signature_banner_btn.get_visible())
        finally:
            release_worker.set()
            if not doc.is_closed:
                doc.close()
            win.destroy()

    def test_signature_inspection_discards_closed_tab_or_stale_document_result(self):
        """Verify background signature inspection results are ignored if the tab closed or document changed."""
        from word_sys_pdf_editor.window import PdfEditorWindow

        win = PdfEditorWindow()
        doc1 = fitz.open()
        doc1.new_page(width=595.0, height=842.0)
        doc2 = fitz.open()
        doc2.new_page(width=595.0, height=842.0)

        fake_sigs = [
            {
                "field_name": "Sig1",
                "intact": True,
                "valid": True,
                "trusted": True,
                "signer_cn": "Stale Signer",
            }
        ]

        try:
            sess = win._active_session
            sess.doc = doc1
            sess.sig_inspection_token = 7
            sess.sig_inspection_in_progress = True

            # Case 1: Document in session changed to doc2 before doc1 inspection completed
            sess.doc = doc2
            win._update_signature_banner(None)
            win._apply_signature_inspection_result(sess, doc1, 7, fake_sigs)
            self.assertIsNone(sess.digital_signatures)
            self.assertFalse(win.signature_banner.get_visible())

            # Case 2: Session was removed (tab closed) before inspection completed
            closed_sess = win.create_session()
            closed_sess.doc = doc1
            closed_sess.sig_inspection_token = 1
            closed_sess.sig_inspection_in_progress = True
            if closed_sess in win.sessions:
                win.sessions.remove(closed_sess)
            win._apply_signature_inspection_result(closed_sess, doc1, 1, fake_sigs)
            self.assertIsNone(closed_sess.digital_signatures)
            self.assertTrue(closed_sess.sig_inspection_in_progress)

            # Case 3: Document was closed via session.close() before callback ran
            sess.doc = doc1
            sess.sig_inspection_token = 10
            sess.sig_inspection_in_progress = True
            sess.close()
            win._apply_signature_inspection_result(sess, doc1, 10, fake_sigs)
            self.assertIsNone(sess.digital_signatures)
            self.assertFalse(win.signature_banner.get_visible())
        finally:
            if not doc1.is_closed:
                doc1.close()
            if not doc2.is_closed:
                doc2.close()
            win.destroy()

    def test_on_inspect_digital_signatures_non_blocking_when_uninspected(self):
        """Verify on_inspect_digital_signatures triggers async inspection when signatures are not yet cached."""
        from word_sys_pdf_editor.window import PdfEditorWindow

        win = PdfEditorWindow()
        doc = fitz.open()
        doc.new_page(width=595.0, height=842.0)

        fake_sigs = [
            {
                "field_name": "Sig1",
                "intact": True,
                "valid": True,
                "trusted": True,
                "signer_cn": "Async Inspector",
            }
        ]

        try:
            sess = win._active_session
            sess.doc = doc
            sess.digital_signatures = None

            def fake_start(target_sess, target_doc, on_complete=None):
                target_sess.sig_inspection_token = 1
                target_sess.sig_inspection_in_progress = True
                target_sess._sig_inspection_on_complete = on_complete
                win._apply_signature_inspection_result(target_sess, target_doc, 1, fake_sigs)

            with patch.object(win, "_start_signature_inspection", side_effect=fake_start) as mock_start, \
                 patch.object(SignatureDetailsDialog, "present") as mock_present:
                win.on_inspect_digital_signatures()
                mock_start.assert_called_once()
                self.assertEqual(sess.digital_signatures, fake_sigs)
                mock_present.assert_called_once()
        finally:
            if not doc.is_closed:
                doc.close()
            win.destroy()

    def test_sig_banner_verifying_localization(self):
        """Ensure sig_banner_verifying key exists across all supported locales."""
        dicts = [
            ("en", _STRINGS["en"]),
            ("tr", _STRINGS["tr"]),
            ("fr", STRINGS_FR),
            ("de", STRINGS_DE),
            ("es", STRINGS_ES),
            ("it", STRINGS_IT),
            ("ru", STRINGS_RU),
        ]
        for lang, d in dicts:
            self.assertIn("sig_banner_verifying", d, f"Missing sig_banner_verifying in {lang}")
            self.assertTrue(len(d["sig_banner_verifying"]) > 0)


if __name__ == "__main__":
    unittest.main()

