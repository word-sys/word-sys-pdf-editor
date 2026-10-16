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

