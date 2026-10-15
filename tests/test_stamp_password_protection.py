import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk

from word_sys_pdf_editor.stamp_manager import (
    CustomStamp,
    StampLibrary,
    StampPasswordDialog,
    StampVerificationDialog,
    generate_cairo_stamp_png,
    hash_stamp_password,
    verify_stamp_password,
)
from word_sys_pdf_editor.models import EditableImage
from word_sys_pdf_editor.undo_manager import UndoManager, AddObjectCommand


@pytest.fixture
def temp_stamps_dir():
    temp_dir = tempfile.mkdtemp(prefix="test_stamp_pwd_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_password_hashing_and_verification():
    raw_pass = "SecurePass#2026"
    stored_hash = hash_stamp_password(raw_pass)

    assert stored_hash is not None
    assert stored_hash.startswith("pbkdf2:sha256:100000:")
    parts = stored_hash.split(":")
    assert len(parts) == 5

    # Correct password succeeds
    assert verify_stamp_password(raw_pass, stored_hash) is True
    # Incorrect password fails
    assert verify_stamp_password("WrongPassword", stored_hash) is False
    assert verify_stamp_password("", stored_hash) is False
    assert verify_stamp_password(raw_pass, None) is False
    assert verify_stamp_password(raw_pass, "invalid:format") is False

    # Empty raw password raises ValueError
    with pytest.raises(ValueError):
        hash_stamp_password("")
    with pytest.raises(ValueError):
        hash_stamp_password("   ")


def test_custom_stamp_password_protection_lifecycle(temp_stamps_dir):
    png_bytes = generate_cairo_stamp_png("APPROVED", (0.0, 0.5, 0.0), width=120, height=40)
    img_path = temp_stamps_dir / "approved.png"
    img_path.write_bytes(png_bytes)

    stamp = CustomStamp(
        stamp_id="stamp_sec_1",
        name="Official Seal",
        category="Legal",
        image_path=str(img_path),
        image_bytes=png_bytes,
        default_width=140.0,
        default_height=50.0,
        is_builtin=False,
    )

    # Initial state: unprotected
    assert stamp.has_password() is False
    assert stamp.is_password_protected is False
    assert stamp.password_hash is None
    assert stamp.verify_password("any_or_no_password") is True

    # Set password
    stamp.set_password("ManagerPIN#9988")
    assert stamp.has_password() is True
    assert stamp.is_password_protected is True
    assert stamp.password_hash.startswith("pbkdf2:sha256:")

    # Verification
    assert stamp.verify_password("ManagerPIN#9988") is True
    assert stamp.verify_password("WrongPIN") is False

    # Serialization and deserialization
    data = stamp.to_dict()
    assert data["is_password_protected"] is True
    assert data["password_hash"] == stamp.password_hash

    restored = CustomStamp.from_dict(data, temp_stamps_dir)
    assert restored.has_password() is True
    assert restored.is_password_protected is True
    assert restored.password_hash == stamp.password_hash
    assert restored.verify_password("ManagerPIN#9988") is True
    assert restored.verify_password("WrongPIN") is False

    # Remove password
    restored.remove_password()
    assert restored.has_password() is False
    assert restored.is_password_protected is False
    assert restored.password_hash is None
    assert restored.verify_password("ManagerPIN#9988") is True


def test_stamp_password_dialog_set_new_password(temp_stamps_dir):
    stamp = CustomStamp(
        stamp_id="test_dlg_1",
        name="Contract Stamp",
        image_bytes=b"dummy_bytes",
    )

    success_called = []
    dlg = StampPasswordDialog(
        parent_window=None,
        stamp=stamp,
        on_success_callback=lambda s: success_called.append(s),
    )

    # Mismatch passwords
    dlg.new_entry.set_text("Alpha123")
    dlg.confirm_entry.set_text("Alpha456")
    dlg._on_save_clicked(None)

    assert len(success_called) == 0
    assert stamp.has_password() is False
    assert dlg.error_label.get_visible() is True

    # Empty password
    dlg.new_entry.set_text("")
    dlg.confirm_entry.set_text("")
    dlg._on_save_clicked(None)
    assert len(success_called) == 0
    assert stamp.has_password() is False

    # Matching password
    dlg.new_entry.set_text("Alpha123")
    dlg.confirm_entry.set_text("Alpha123")
    dlg._on_save_clicked(None)

    assert len(success_called) == 1
    assert stamp.has_password() is True
    assert stamp.verify_password("Alpha123") is True


def test_stamp_password_dialog_change_and_remove(temp_stamps_dir):
    stamp = CustomStamp(
        stamp_id="test_dlg_2",
        name="Secret Stamp",
        image_bytes=b"dummy_bytes",
    )
    stamp.set_password("CurrentSecret123")

    success_called = []
    dlg = StampPasswordDialog(
        parent_window=None,
        stamp=stamp,
        on_success_callback=lambda s: success_called.append(s),
    )

    assert dlg.curr_entry is not None

    # Try removing with wrong current password
    dlg.curr_entry.set_text("WrongOldSecret")
    dlg._on_remove_clicked(None)
    assert len(success_called) == 0
    assert stamp.has_password() is True
    assert dlg.error_label.get_visible() is True

    # Remove with correct current password
    dlg.curr_entry.set_text("CurrentSecret123")
    dlg._on_remove_clicked(None)
    assert len(success_called) == 1
    assert stamp.has_password() is False


def test_stamp_verification_dialog():
    stamp = CustomStamp(
        stamp_id="test_ver_1",
        name="Confidential Stamp",
        image_bytes=b"dummy_bytes",
    )
    stamp.set_password("OpenSesame42")

    verified_calls = []
    cancelled_calls = []

    dlg = StampVerificationDialog(
        parent_window=None,
        stamp=stamp,
        on_verified_callback=lambda: verified_calls.append(True),
        on_cancelled_callback=lambda: cancelled_calls.append(True),
    )

    # Wrong password attempt
    dlg.password_entry.set_text("WrongCode")
    dlg._on_unlock_clicked(None)

    assert len(verified_calls) == 0
    assert dlg.error_label.get_visible() is True

    # Correct password attempt
    dlg.password_entry.set_text("OpenSesame42")
    dlg._on_unlock_clicked(None)

    assert len(verified_calls) == 1
    assert len(cancelled_calls) == 0


def test_stamp_verification_dialog_cancellation():
    stamp = CustomStamp(
        stamp_id="test_ver_2",
        name="Confidential Stamp 2",
        image_bytes=b"dummy_bytes",
    )
    stamp.set_password("OpenSesame42")

    verified_calls = []
    cancelled_calls = []

    dlg = StampVerificationDialog(
        parent_window=None,
        stamp=stamp,
        on_verified_callback=lambda: verified_calls.append(True),
        on_cancelled_callback=lambda: cancelled_calls.append(True),
    )

    # User clicks cancel
    dlg._on_cancel_clicked(None)
    dlg._on_window_destroyed(None)

    assert len(verified_calls) == 0
    assert len(cancelled_calls) == 1
