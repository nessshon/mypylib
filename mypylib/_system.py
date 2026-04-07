from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Final

import psutil

from ._types import ByteUnit, DiskSpace, MemoryInfo, UnameInfo
from ._utils import convert_bytes, run_subprocess

_VIRTUAL_MARKERS: Final[tuple[str, ...]] = ("virtual", "kvm", "qemu", "vmware")


def get_cpu_name() -> str | None:
    """Return CPU model name from ``/proc/cpuinfo``, or ``None`` if unavailable."""
    try:
        with Path("/proc/cpuinfo").open() as file:
            for line in file:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except FileNotFoundError:
        return None
    return None


def get_cpu_count(logical: bool = True) -> int:
    """Return CPU core count (logical by default, physical if ``logical=False``)."""
    return psutil.cpu_count(logical=logical) or 1


def get_hardware_name() -> str | None:
    """Return DMI product name, lowercased, or ``None`` if unavailable."""
    try:
        return Path("/sys/class/dmi/id/product_name").read_text().strip().lower()
    except FileNotFoundError:
        return None


def is_hardware_virtualized() -> bool | None:
    """Detect if running on a virtualized host.

    :return: ``True``/``False``, or ``None`` if hardware name unavailable.
    """
    hardware_name = get_hardware_name()
    if hardware_name is None:
        return None
    return any(marker in hardware_name for marker in _VIRTUAL_MARKERS)


def get_ram_info() -> MemoryInfo:
    """Return RAM usage (total/used in binary GB) and percent."""
    data = psutil.virtual_memory()
    return MemoryInfo(
        total=convert_bytes(data.total, ByteUnit.GB),
        used=convert_bytes(data.used, ByteUnit.GB),
        percent=data.percent,
    )


def get_swap_info() -> MemoryInfo:
    """Return swap usage (total/used in binary GB) and percent."""
    data = psutil.swap_memory()
    return MemoryInfo(
        total=convert_bytes(data.total, ByteUnit.GB),
        used=convert_bytes(data.used, ByteUnit.GB),
        percent=data.percent,
    )


def get_uname() -> UnameInfo:
    """Return system uname fields (nodename excluded for privacy)."""
    data = os.uname()
    return UnameInfo(
        sysname=data.sysname,
        release=data.release,
        version=data.version,
        machine=data.machine,
    )


def get_disk_space(
    path: Path | str,
    unit: ByteUnit = ByteUnit.GB,
    ndigits: int = 2,
) -> DiskSpace:
    """Return disk total/used/free at *path* in the requested unit."""
    total, used, free = shutil.disk_usage(path)
    return DiskSpace(
        total=convert_bytes(total, unit, ndigits),
        used=convert_bytes(used, unit, ndigits),
        free=convert_bytes(free, unit, ndigits),
    )


def get_disk_device(path: Path | str) -> str | None:
    """Return device name backing the filesystem at *path*, or ``None`` on failure."""
    try:
        result = run_subprocess(["df", str(path)], timeout=3)
    except (subprocess.SubprocessError, RuntimeError):
        return None

    lines = result.strip().split("\n")
    if len(lines) < 2:
        return None
    return lines[1].split()[0]
