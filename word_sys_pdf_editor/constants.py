"""Application constants and metadata."""

import os
from pathlib import Path

APP_NAME = "word-sys PDF Editor"
APP_VERSION = "1.12.0"


def get_application_license_text() -> str:
    """Retrieve full GPL-3.0-or-later license text across dev, system, Flatpak, and AppImage environments."""
    search_paths = [
        # 1. Bundled inside the package directory (Flatpak/AppImage/wheels)
        Path(__file__).resolve().parent / "LICENSE",
        # 2. Workspace root during development / local repository clone
        Path(__file__).resolve().parent.parent / "LICENSE",
        # 3. Flatpak standard doc directory
        Path("/app/share/doc/word-sys-pdf-editor/LICENSE"),
        # 4. Standard Debian / Ubuntu common licenses directory
        Path("/usr/share/common-licenses/GPL-3"),
        # 5. Arch Linux common licenses directory
        Path("/usr/share/licenses/common/GPL3/license.txt"),
        # 6. Fedora / Red Hat licenses directory
        Path("/usr/share/licenses/GPL-3"),
    ]

    # 7. AppImage mounted directory if present
    appdir = os.environ.get("APPDIR")
    if appdir:
        search_paths.insert(0, Path(appdir) / "usr" / "share" / "doc" / "word-sys-pdf-editor" / "LICENSE")
        search_paths.insert(0, Path(appdir) / "LICENSE")

    for path in search_paths:
        try:
            if path and path.is_file():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
        except Exception:
            continue

    # 8. Guaranteed embedded fallback constant
    try:
        from .license_data import GPL_V3_FULL_TEXT
        return GPL_V3_FULL_TEXT.strip()
    except Exception:
        return "GNU General Public License v3.0 or later."
