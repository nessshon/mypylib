import ipaddress
import json
import platform
import socket
import struct
import subprocess
from urllib.request import urlopen

import requests

from ._utils import run_subprocess


def ping(hostname: str) -> bool:
    """Send a single ICMP ping to *hostname*.

    :param hostname: Target host or IP address.
    :return: ``True`` if the host responded, ``False`` otherwise.
    """
    result = subprocess.run(
        ["ping", "-c", "1", "-w", "3", hostname],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def get_ping(host: str, count: int = 3, timeout: float = 5) -> float | None:
    """Return average ping latency to *host* in ms, or ``None`` if unreachable.

    :param host: Target host or IP address.
    :param count: Number of pings to send.
    :param timeout: Per-ping timeout in seconds.
    :return: Average round-trip time in ms, or ``None`` on failure.
    """
    try:
        result = run_subprocess(
            ["ping", "-c", str(count), "-W", str(timeout), host],
            timeout=timeout + 1,
        )
    except (subprocess.SubprocessError, RuntimeError):
        return None

    try:
        avg_str = result.split("\n")[-2].split("=")[1].split("/")[1]
        return float(avg_str)
    except (IndexError, ValueError):
        return None


def get_pings(hosts: tuple[str, ...]) -> dict[str, float | None]:
    """Return mapping ``host -> avg ping latency (ms)`` or ``None`` if unreachable.

    :param hosts: Hosts to measure.
    :return: Dictionary of host to average ping latency (or ``None``).
    """
    return {host: get_ping(host) for host in hosts}


def get_request(url: str, timeout: float = 30) -> str:
    """Perform an HTTP GET and return the response body as a string.

    :param url: URL to fetch (must start with ``http://`` or ``https://``).
    :param timeout: Request timeout in seconds.
    :return: Response body decoded as UTF-8.
    :raises ValueError: If the URL scheme is unsupported.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Unsupported URL scheme: {url}")
    with urlopen(url, timeout=timeout) as response:  # noqa: S310
        body: bytes = response.read()
    return body.decode("utf-8")


def get_internet_interface_name() -> str:
    """Return the name of the default network interface.

    :return: Interface name (e.g. ``"eth0"``).
    """
    if platform.system() == "OpenBSD":
        text = subprocess.getoutput("ifconfig egress")
        return text.split("\n", 1)[0].split(" ", 1)[0][:-1]

    text = subprocess.getoutput("ip --json route")
    try:
        routes: list[dict[str, str]] = json.loads(text)
        return routes[0]["dev"]
    except (json.JSONDecodeError, IndexError, KeyError):
        items = text.split("\n", 1)[0].split(" ")
        return items[items.index("dev") + 1]


def ip2int(addr: str) -> int:
    """Convert a dotted-quad IPv4 address to a signed 32-bit integer.

    :param addr: IPv4 address string (e.g. ``"192.168.1.1"``).
    :return: Integer representation.
    """
    result: int = struct.unpack("!i", socket.inet_aton(addr))[0]
    return result


def int2ip(dec: int) -> str:
    """Convert a signed 32-bit integer back to a dotted-quad IPv4 string.

    :param dec: Integer representation of an IPv4 address.
    :return: Dotted-quad string.
    """
    return socket.inet_ntoa(struct.pack("!i", dec))


def get_own_ip() -> str:
    """Determine the public IPv4 address of this machine.

    Queries external services and returns the first valid IPv4 response.

    :return: Public IPv4 address string.
    :raises RuntimeError: If no service returned a valid IPv4 address.
    """
    services = ("https://ifconfig.me/ip", "https://ipinfo.io/ip")
    for url in services:
        try:
            ip = requests.get(url, timeout=30).text.strip()
            ipaddress.IPv4Address(ip)
        except (requests.RequestException, ValueError):
            continue
        return ip
    raise RuntimeError("Cannot get own IP address")
