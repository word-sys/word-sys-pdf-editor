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
