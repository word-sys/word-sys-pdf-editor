from __future__ import annotations

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
