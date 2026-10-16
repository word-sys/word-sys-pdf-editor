# word-sys-pdf-editor - Universal Global Trust Store Test Suite

import os
import shutil
import tempfile
import pytest
from datetime import datetime, timezone, timedelta

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
    now = datetime.now(timezone.utc)
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
