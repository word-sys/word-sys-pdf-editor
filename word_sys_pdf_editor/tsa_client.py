from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

try:
    import pyhanko
    from pyhanko.sign.timestamps import HTTPTimeStamper, TimeStamper
    PYHANKO_TSA_AVAILABLE = True
except ImportError:
    HTTPTimeStamper = None
    TimeStamper = None
    PYHANKO_TSA_AVAILABLE = False


PRESET_TSAS: Dict[str, str] = {
    "DigiCert": "http://timestamp.digicert.com",
    "FreeTSA": "https://freetsa.org/tsr",
    "Sectigo": "http://timestamp.sectigo.com",
}


@dataclass
class TSAConfig:
    url: str = PRESET_TSAS["DigiCert"]
    auth_user: Optional[str] = None
    auth_password: Optional[str] = None
    timeout: int = 15

    def is_valid(self) -> bool:
        if not self.url or not isinstance(self.url, str):
            return False
        clean = self.url.strip().lower()
        return clean.startswith("http://") or clean.startswith("https://")


def is_tsa_client_available() -> bool:
    return PYHANKO_TSA_AVAILABLE


def create_timestamper(tsa_config: Optional[TSAConfig] = None) -> Optional[Any]:
    if not PYHANKO_TSA_AVAILABLE or tsa_config is None or not tsa_config.is_valid():
        return None

    auth = None
    if tsa_config.auth_user and tsa_config.auth_password:
        auth = (tsa_config.auth_user, tsa_config.auth_password)

    try:
        return HTTPTimeStamper(
            url=tsa_config.url.strip(),
            timeout=tsa_config.timeout,
            auth=auth,
        )
    except Exception as exc:
        logging.warning("Failed to initialize HTTPTimeStamper: %s", exc)
        return None
