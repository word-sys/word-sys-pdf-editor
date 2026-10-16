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
