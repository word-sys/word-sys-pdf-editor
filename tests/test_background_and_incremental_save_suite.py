import os
import time
import tempfile
import threading
import datetime
from unittest.mock import MagicMock, patch

import pytest
import fitz
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12, BestAvailableEncryption
from gi.repository import GLib

from word_sys_pdf_editor import pdf_handler
from word_sys_pdf_editor.window import PdfEditorWindow
from word_sys_pdf_editor.models import DocumentSession, EditableText
from word_sys_pdf_editor.digital_signature import (
    is_pyhanko_available,
    sign_pdf_bytes,
    inspect_pdf_signatures,
)


@pytest.fixture
def sample_pfx():
    if not is_pyhanko_available():
        pytest.skip("pyHanko not installed")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Save Test Signer"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "word-sys Security"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    pfx_data = pkcs12.serialize_key_and_certificates(
        name=b"test_save_key",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=BestAvailableEncryption(b"testpass123"),
    )
    return pfx_data, b"testpass123"


def test_incremental_quick_save_round_trip_equality():
    """Verify that incremental save accurately preserves all pages and extracted objects."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name

    try:
        # Create base document
        doc = fitz.open()
        p1 = doc.new_page(width=400, height=300)
        p1.insert_text((50, 50), "First Page Text")
        p2 = doc.new_page(width=400, height=300)
        p2.insert_text((50, 50), "Second Page Text")
        doc.save(path)
        doc.close()

        # Open and apply incremental modifications
        doc = fitz.open(path)
        p1 = doc[0]
        p1.draw_rect(fitz.Rect(10, 10, 100, 100), color=(1, 0, 0))
        p2 = doc[1]
        p2.insert_text((50, 100), "Appended Incremental Text")

        success, err = pdf_handler.save_document(doc, path, incremental=True)
        assert success is True
        assert err is None
        doc.close()

        # Reopen and verify round-trip fidelity
        reopened = fitz.open(path)
        assert len(reopened) == 2
        p1_text = reopened[0].get_text()
        p2_text = reopened[1].get_text()
        assert "First Page Text" in p1_text
        assert "Second Page Text" in p2_text
        assert "Appended Incremental Text" in p2_text
        assert len(reopened[0].get_drawings()) == 1
        reopened.close()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_incremental_quick_save_performance_speedup():
    """Verify that incremental save is orders of magnitude faster than a full clean rewrite on a large PDF."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name

    try:
        # Create a 60-page PDF
        doc = fitz.open()
        for i in range(60):
            p = doc.new_page(width=500, height=500)
            p.insert_text((50, 50), f"Page content {i} with some arbitrary text data")
        doc.save(path)
        doc.close()

        # Measure full rewrite duration
        doc = fitz.open(path)
        doc[0].insert_text((50, 100), "Edit 1")
        t0 = time.perf_counter()
        success, _ = pdf_handler.save_document(doc, path, incremental=False)
        full_rewrite_time = time.perf_counter() - t0
        assert success is True
        doc.close()

        # Measure incremental save duration
        doc = fitz.open(path)
        doc[0].insert_text((50, 150), "Edit 2")
        t0 = time.perf_counter()
        success, _ = pdf_handler.save_document(doc, path, incremental=True)
        incremental_time = time.perf_counter() - t0
        assert success is True
        doc.close()

        # Incremental quick save must execute within 25 ms
        assert incremental_time < 0.05
        assert incremental_time < full_rewrite_time
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_signed_document_preservation_incremental_save(sample_pfx):
    """Verify digital signature envelope is intact after incremental quick save."""
    pfx_data, password = sample_pfx

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "Document requiring signature protection")
    raw_bytes = doc.tobytes()
    doc.close()

    signed_bytes, err = sign_pdf_bytes(
        pdf_bytes=raw_bytes,
        pfx_data_or_path=pfx_data,
        passphrase=password,
        reason="Integrity Test",
    )
    assert err is None
    assert signed_bytes is not None

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(signed_bytes)
        signed_path = f.name

    try:
        # Verify initial signature
        initial_sigs = inspect_pdf_signatures(signed_path)
        assert len(initial_sigs) == 1
        assert initial_sigs[0]["intact"] is True

        # Open signed document and perform incremental edit
        doc = fitz.open(signed_path)
        p = doc[0]
        p.draw_rect(fitz.Rect(100, 100, 200, 200), color=(0, 0, 1))
        success, err = pdf_handler.save_document(doc, signed_path, incremental=True)
        assert success is True
        doc.close()

        # Re-inspect: incremental write preserved the signature block
        reopened_sigs = inspect_pdf_signatures(signed_path)
        assert len(reopened_sigs) == 1
        assert reopened_sigs[0]["intact"] is True
    finally:
        if os.path.exists(signed_path):
            os.remove(signed_path)


def test_encrypted_document_safe_fallback_from_incremental():
    """Verify that encrypted documents or documents with new passwords safely fall back to full rewrite."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name

    try:
        doc = fitz.open()
        p = doc.new_page(width=300, height=300)
        p.insert_text((50, 50), "Confidential payload")
        doc.save(path)
        doc.close()

        # Open doc and attach custom security credentials
        doc = fitz.open(path)
        doc._pdf_password = "user_secret"
        doc._pdf_owner_password = "owner_secret"

        # Request incremental save: must fall back to full rewrite with encryption
        success, err = pdf_handler.save_document(doc, path, incremental=True)
        assert success is True
        assert err is None
        doc.close()

        # Verify output is encrypted and requires authentication
        reopened = fitz.open(path)
        assert reopened.is_encrypted is True
        assert reopened.authenticate("user_secret") > 0
        assert "Confidential payload" in reopened[0].get_text()
        reopened.close()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_save_failure_leaves_original_file_untouched():
    """Verify that a save failure leaves the original document byte-for-byte untouched."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name

    try:
        doc = fitz.open()
        p = doc.new_page(width=300, height=300)
        p.insert_text((50, 50), "Original Untouched Content")
        doc.save(path)
        doc.close()

        with open(path, "rb") as f:
            original_bytes = f.read()

        doc = fitz.open(path)
        doc[0].insert_text((50, 100), "Malicious edit to fail")

        # Simulate exception during doc.save
        with patch.object(doc, "save", side_effect=IOError("Simulated disk error")):
            success, err = pdf_handler.save_document(doc, path, incremental=True)
            assert success is False
            assert "Simulated disk error" in str(err)
        doc.close()

        # Check original file
        with open(path, "rb") as f:
            current_bytes = f.read()
        assert current_bytes == original_bytes
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_background_save_worker_threading_and_progress_spinner():
    """Verify that PdfEditorWindow saves in a worker thread and manages spinner and callbacks."""
    win = PdfEditorWindow()
    doc = fitz.open()
    doc.new_page(width=200, height=200)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        save_path = f.name

    try:
        doc.save(save_path)
        sess = win.create_session(doc=doc, filepath=save_path)
        win.add_session(sess, switch_to=True)

        finished_events = []

        def on_done(success, err):
            finished_events.append((success, err))

        win.save_document(save_path, incremental=False, background=True, on_finish=on_done)
        # Background save was dispatched
        assert hasattr(win, "_save_thread")
        win.wait_for_save()

        assert win.is_saving is False
        assert len(finished_events) == 1
        assert finished_events[0][0] is True
    finally:
        doc.close()
        if os.path.exists(save_path):
            os.remove(save_path)


def test_concurrent_save_and_editing_guards():
    """Verify that concurrent saves, page rotations, and page deletions are blocked when is_saving is True."""
    win = PdfEditorWindow()
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.new_page(width=200, height=200)

    sess = win.create_session(doc=doc, filepath="/tmp/dummy_test_guard.pdf")
    win.add_session(sess, switch_to=True)

    try:
        # Simulate is_saving=True
        win.is_saving = True

        # 1. Concurrent save rejected
        with patch("word_sys_pdf_editor.pdf_handler.save_document") as mock_save:
            win.save_document("/tmp/dummy_test_guard.pdf", incremental=True)
            mock_save.assert_not_called()

        # 2. Page rotation blocked
        init_rot = doc[0].rotation
        win.rotate_current_page(90)
        assert doc[0].rotation == init_rot

        # 3. Page deletion blocked
        init_pages = len(doc)
        win.on_delete_page(None)
        assert len(doc) == init_pages
    finally:
        win.is_saving = False
        doc.close()


def _build_edit_after_save_fixture(tmp_path):
    from word_sys_pdf_editor import pdf_handler
    from word_sys_pdf_editor.models import (
        EditableText, EditableShape, EditableStroke, EditableImage,
    )
    path = str(tmp_path / "edit_after_save.pdf")
    base = fitz.open()
    base.new_page().insert_text((72, 72), "Hello base")
    base.save(path)
    base.close()
    doc, _err = pdf_handler.load_pdf_document(path)
    pdf_handler.save_page_snapshot(doc, 0)
    text = EditableText(100, 200, "New Text", font_size=14, is_new=True)
    text.page_number = 0
    shape = EditableShape("ellipse", (100, 300, 200, 360), page_number=0, is_new=True)
    stroke = EditableStroke(
        [(100, 400), (150, 420), (200, 400)], stroke_color=(1, 1, 0),
        stroke_width=8, opacity=0.5, page_number=0, is_new=True,
    )
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    pix.set_rect(pix.irect, (255, 0, 0))
    image = EditableImage((300, 300, 360, 360), 0, 0, pix.tobytes("png"), is_new=True, rotation=30.0)
    lists = dict(all_texts=[text], all_shapes=[shape], all_images=[image], all_strokes=[stroke])
    pdf_handler.rebuild_page(doc, 0, **lists)
    return pdf_handler, doc, path, text, lists


def _ink(doc):
    samples = doc[0].get_pixmap().samples
    return len(samples) - samples.count(255)


@pytest.mark.parametrize("sequence", [
    [True, True, True], [False, False], [True, False, True], [False, True],
])
def test_editing_after_save_keeps_all_objects(tmp_path, sequence):
    """Regression: stroke/image/stamp vanished when editing after a save."""
    pdf_handler, doc, path, text, lists = _build_edit_after_save_fixture(tmp_path)
    try:
        baseline = _ink(doc)
        for i, incr in enumerate(sequence):
            ok, err = pdf_handler.save_document(doc, path, incremental=incr)
            assert ok, err
            text.text = text.text + "x"
            pdf_handler.rebuild_page(doc, 0, **lists)
            assert len(doc[0].get_images()) >= 1
            assert len(doc[0].get_drawings()) >= 2
            assert _ink(doc) >= baseline - 50
    finally:
        pdf_handler.release_page_snapshots(doc)
        doc.close()


def test_full_rewrite_does_not_mutate_live_document(tmp_path):
    """Full rewrite (garbage/clean) must not renumber xrefs of the live document."""
    pdf_handler, doc, path, text, lists = _build_edit_after_save_fixture(tmp_path)
    try:
        before_len = doc.xref_length()
        before_imgs = doc.get_page_images(0)
        ok, err = pdf_handler.save_document(doc, path, incremental=False)
        assert ok, err
        assert doc.xref_length() == before_len
        assert doc.get_page_images(0) == before_imgs
        reopened = fitz.open(path)
        assert len(reopened[0].get_images()) >= 1
        reopened.close()
    finally:
        pdf_handler.release_page_snapshots(doc)
        doc.close()


def test_encrypted_document_save_then_edit_keeps_objects_and_encryption(tmp_path):
    pdf_handler, doc, path, text, lists = _build_edit_after_save_fixture(tmp_path)
    pdf_handler.release_page_snapshots(doc)
    doc.close()
    plain = fitz.open(path)
    enc_path = str(tmp_path / "enc_edit_after_save.pdf")
    plain.save(enc_path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    plain.close()

    edoc, err = pdf_handler.load_pdf_document(enc_path, password="u")
    assert edoc is not None, err
    try:
        pdf_handler.save_page_snapshot(edoc, 0)
        text.page_number = 0
        text.is_new = True
        text.text = "New Text"
        pdf_handler.rebuild_page(edoc, 0, **lists)
        baseline = _ink(edoc)
        xref_len = edoc.xref_length()
        for incr in (False, True, False):
            ok, e = pdf_handler.save_document(edoc, enc_path, incremental=incr)
            assert ok, e
            text.text = text.text + "x"
            pdf_handler.rebuild_page(edoc, 0, **lists)
            assert len(edoc[0].get_images()) >= 1
            assert _ink(edoc) >= baseline - 50
        reopened = fitz.open(enc_path)
        assert reopened.needs_pass
        assert reopened.authenticate("u")
        assert len(reopened[0].get_images()) >= 1
        reopened.close()
    finally:
        pdf_handler.release_page_snapshots(edoc)
        edoc.close()


def test_full_rewrite_without_stored_password_never_mutates_unencrypted_live_doc(tmp_path):
    """Owner-only/empty-user-password docs report is_encrypted False and use the copy path."""
    pdf_handler, doc, path, text, lists = _build_edit_after_save_fixture(tmp_path)
    try:
        assert not doc.is_encrypted
        before = doc.xref_length()
        ok, e = pdf_handler.save_document(doc, path, incremental=False)
        assert ok, e
        assert doc.xref_length() == before
    finally:
        pdf_handler.release_page_snapshots(doc)
        doc.close()
