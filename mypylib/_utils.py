from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from ._colors import Colors
from ._types import ByteUnit, Dict


def get_hash_md5(file_name: str | Path) -> str:
    """Compute the MD5 hex digest of a file.

    :param file_name: Path to the file.
    :return: Hex digest string.
    """
    hasher = hashlib.md5()  # noqa: S324
    with Path(file_name).open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse(
    text: str | None,
    search: str | None,
    search2: str | None = None,
) -> str | None:
    """Extract a substring between two markers.

    :param text: Source string.
    :param search: Left boundary (excluded from result).
    :param search2: Optional right boundary (excluded from result).
    :return: Extracted substring, or ``None`` if *search* is not found.
    """
    if text is None or search is None:
        return None
    start = text.find(search)
    if start == -1:
        return None
    tail = text[start + len(search) :]
    if search2 is None:
        return tail
    end = tail.find(search2)
    return tail if end == -1 else tail[:end]


def ensure_dir_slash(input_dir: str) -> str:
    """Ensure a directory path ends with ``/``.

    :param input_dir: Directory path.
    :return: Path guaranteed to end with a trailing slash.
    """
    if not input_dir.endswith("/"):
        input_dir += "/"
    return input_dir


def convert_bytes(value: float, unit: ByteUnit, ndigits: int = 2) -> float:
    """Convert bytes to the requested unit rounded to ``ndigits`` decimals.

    Accepts both ``int`` byte counts and ``float`` per-second rates (PEP 484
    numeric promotion — ``int`` is assignable to ``float``).

    :param value: Value in bytes (int) or bytes-per-unit-of-time (float).
    :param unit: Target unit (``ByteUnit.B`` to ``ByteUnit.TB``).
    :param ndigits: Decimal places to round to.
    :return: Value in requested unit.
    """
    return round(value / 1024**unit.value, ndigits)


def run_subprocess(
    args: list[str] | str,
    timeout: float,
    cwd: str | Path | None = None,
) -> str:
    """Run a subprocess and return stdout; raise ``RuntimeError`` on non-zero exit.

    :param args: Command as a list, or a shell string.
    :param timeout: Seconds to wait before aborting.
    :param cwd: Working directory for the command.
    :return: Decoded stdout.
    :raises RuntimeError: If the process exits with a non-zero status.
    """
    is_shell = isinstance(args, str)
    process = subprocess.run(
        args,
        stdin=subprocess.PIPE,
        capture_output=True,
        timeout=timeout,
        shell=is_shell,
        cwd=cwd,
        check=False,
    )
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8")
        raise RuntimeError(f"run_subprocess error: {stderr}")
    return process.stdout.decode("utf-8")


def search_file_in_dir(path: str | Path, file_name: str) -> str | None:
    """Recursively search for a file by name, skipping hidden dirs.

    :param path: Root directory to search.
    :param file_name: Target file name (exact match).
    :return: Full path to the file, or ``None`` if not found.
    """
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_file() and entry.name == file_name:
                return entry.path
            if entry.is_dir():
                found = search_file_in_dir(entry.path, file_name)
                if found is not None:
                    return found
    return None


def search_dir_in_dir(path: str | Path, dir_name: str) -> str | None:
    """Recursively search for a directory by name, skipping hidden dirs.

    :param path: Root directory to search.
    :param dir_name: Target directory name (exact match).
    :return: Full path to the directory, or ``None`` if not found.
    """
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if not entry.is_dir():
                continue
            if entry.name == dir_name:
                return entry.path
            found = search_dir_in_dir(entry.path, dir_name)
            if found is not None:
                return found
    return None


def get_dir_from_path(path: str) -> str:
    """Return the directory portion of a UNIX path.

    :param path: File path.
    :return: Everything up to and including the last ``/``.
    """
    return path[: path.rfind("/") + 1]


def get_full_name_from_path(path: str | Path) -> str:
    """Return the file name (with extension) from a path.

    :param path: File path.
    :return: File name portion after the last separator.
    """
    return Path(path).name


def print_table(arr: list[list[Any]]) -> None:
    """Print a list of rows as a formatted table.

    The first row is treated as a header and printed in bold blue.

    :param arr: List of rows, each row is a list of column values.
    """
    if not arr:
        return
    col_widths = [max(len(str(row[i])) for row in arr) + 2 for i in range(len(arr[0]))]
    for row_idx, row in enumerate(arr):
        for i, value in enumerate(row):
            cell = str(value).ljust(col_widths[i])
            if row_idx == 0:
                cell = Colors.bold_text(Colors.blue_text(cell))
            print(cell, end="")
        print()


def thr_sleep() -> None:
    """Block the current thread indefinitely (sleep loop)."""
    while True:
        time.sleep(10)


def dec2hex(dec: int) -> str:
    """Convert an integer to a zero-padded hex string.

    :param dec: Integer value.
    :return: Hex string with even number of characters.
    """
    h = hex(dec)[2:]
    if len(h) % 2 > 0:
        h = "0" + h
    return h


def hex2dec(h: str) -> int:
    """Convert a hex string to an integer.

    :param h: Hex string (without ``0x`` prefix).
    :return: Integer value.
    """
    return int(h, base=16)


def get_username() -> str | None:
    """Return the current OS username from the ``USER`` environment variable.

    :return: Username string, or ``None`` if not set.
    """
    return os.getenv("USER")


def read_config_from_file(config_path: str) -> Dict:
    """Read a JSON config file and return it as a :class:`Dict`.

    :param config_path: Path to the JSON file.
    :return: Parsed configuration.
    """
    with open(config_path) as file:
        text = file.read()
    return Dict(json.loads(text))


def write_config_to_file(config_path: str, data: dict[str, Any]) -> None:
    """Write a dictionary to a JSON config file.

    :param config_path: Destination file path.
    :param data: Configuration data to serialize.
    """
    text = json.dumps(data, indent=4)
    with open(config_path, "w") as file:
        file.write(text)


def get_load_avg() -> list[float]:
    """Return the system load averages (1, 5, 15 minutes).

    Uses :func:`os.getloadavg` (Linux, BSD, macOS); returns zeros on
    platforms without it (e.g. Windows).

    :return: List of three float values, rounded to two decimals.
    """
    try:
        return [round(v, 2) for v in os.getloadavg()]
    except (OSError, AttributeError):
        return [0.0, 0.0, 0.0]
