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
