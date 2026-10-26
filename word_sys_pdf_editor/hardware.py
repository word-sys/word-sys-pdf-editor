"""Hardware auto-detection and adaptive system resource profiling."""

import os
from typing import Dict, Any, Optional
from .i18n import get_setting, set_setting


def detect_hardware_spec() -> Dict[str, Any]:
    """Detect system RAM and CPU core count, classifying low-spec vs high-performance hardware."""
    total_ram_bytes = 0
    cpu_cores = os.cpu_count() or 1

    # 1. Query POSIX system configuration
    try:
        pages = os.sysconf('SC_PHYS_PAGES')
        page_size = os.sysconf('SC_PAGE_SIZE')
        if pages > 0 and page_size > 0:
            total_ram_bytes = int(pages * page_size)
    except Exception:
        pass

    # 2. Linux /proc/meminfo fallback
    if total_ram_bytes <= 0 and os.path.exists('/proc/meminfo'):
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        parts = line.split()
                        # MemTotal is in kB
                        total_ram_bytes = int(parts[1]) * 1024
                        break
        except Exception:
            pass

    # 3. Default fallback assumption: 8 GB
    if total_ram_bytes <= 0:
        total_ram_bytes = 8 * 1024 * 1024 * 1024

    total_ram_mb = float(total_ram_bytes / (1024 * 1024))
    total_ram_gb = float(total_ram_mb / 1024.0)

    # Low-spec threshold: <= 4096 MB RAM or <= 2 CPU cores
    is_low_spec = (total_ram_mb <= 4096.0) or (cpu_cores <= 2)

    return {
        "total_ram_bytes": total_ram_bytes,
        "total_ram_mb": total_ram_mb,
        "total_ram_gb": total_ram_gb,
        "cpu_cores": cpu_cores,
        "is_low_spec_hardware": is_low_spec,
    }


def is_eco_mode_enabled() -> bool:
    """Return whether Eco / Low-Spec mode is currently enabled (user setting or auto-detected)."""
    val = get_setting("eco_mode", None)
    if val is not None:
        return bool(val)
    spec = detect_hardware_spec()
    return bool(spec.get("is_low_spec_hardware", False))


def set_eco_mode_enabled(enabled: Optional[bool]):
    """Persist user preference for Eco / Low-Spec mode."""
    if enabled is None:
        set_setting("eco_mode", None)
    else:
        set_setting("eco_mode", bool(enabled))
