from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import time

import psutil

from ._utils import parse, run_subprocess


def run_as_root(args: list[str]) -> int:
    """Execute a command with root privileges.

    Uses ``sudo`` on Linux (or falls back to ``su`` if sudo is missing),
    and ``doas`` on OpenBSD. If already running as root, the command is
    executed directly.

    :param args: Command and arguments to execute.
    :return: Exit code of the subprocess.
    :raises RuntimeError: If the platform is unsupported.
    """
    if os.geteuid() == 0:
        return subprocess.run(args, check=False).returncode

    psys = platform.system()
    if psys == "Linux":
        if shutil.which("sudo"):
            cmd = ["sudo", "-s", *args]
        else:
            print("Enter root password")
            cmd = ["su", "-c", shlex.join(args)]
    elif psys == "OpenBSD":
        cmd = ["doas", *args]
    else:
        raise RuntimeError(f"run_as_root: unsupported platform: {psys}")

    return subprocess.run(cmd, check=False).returncode


def add2systemd(
    *,
    name: str,
    start: str,
    pre: str | None = None,
    post: str = "/bin/echo service down",
    user: str = "root",
    group: str | None = None,
    workdir: str | None = None,
    force: bool = False,
) -> None:
    """Create and enable a systemd unit (or rc.d script on OpenBSD).

    :param name: Service name (required).
    :param start: ``ExecStart`` command (required).
    :param pre: ``ExecStartPre`` command.
    :param post: ``ExecStopPost`` command.
    :param user: Run-as user.
    :param group: Run-as group (defaults to *user* if not specified).
    :param workdir: Working directory.
    :param force: Overwrite an existing unit file.
    """
    if group is None:
        group = user
    pversion = platform.version()
    psys = platform.system()
    path = f"/etc/systemd/system/{name}.service"

    if psys == "OpenBSD":
        path = f"/etc/rc.d/{name}"
    if os.path.isfile(path):
        if force:
            print("Unit exist, force rewrite")
        else:
            print("Unit exist.")
            return

    text = f"""
[Unit]
Description = {name} service. Created by https://github.com/igroman787/mypylib.
After = network.target

[Service]
Type = simple
Restart = always
RestartSec = 30
ExecStart = {start}
{f"ExecStartPre = {pre}" if pre else "# ExecStartPre not set"}
ExecStopPost = {post}
User = {user}
Group = {group}
{f"WorkingDirectory = {workdir}" if workdir else "# WorkingDirectory not set"}
LimitNOFILE = infinity
LimitNPROC = infinity
LimitMEMLOCK = infinity

[Install]
WantedBy = multi-user.target
"""

    if psys == "OpenBSD" and "APRENDIENDODEJESUS" in pversion:
        text = f"""
#!/bin/ksh
servicio="{start}"
servicio_user="{user}"
servicio_timeout="3"

. /etc/rc.d/rc.subr

rc_cmd $1
"""

    with open(path, "w") as file:
        file.write(text)

    commands: list[list[str]] = [
        ["chmod", "664", path],
        ["chmod", "+x", path],
    ]
    if psys == "OpenBSD":
        commands.append(["rcctl", "enable", name])
    else:
        commands.append(["systemctl", "daemon-reload"])
        commands.append(["systemctl", "enable", name])

    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8").strip()
            raise RuntimeError(f"{cmd[0]} failed: {stderr}")


def get_service_status(name: str) -> bool:
    """Check whether a system service is currently active.

    :param name: Service name.
    :return: ``True`` if active, ``False`` otherwise.
    """
    cmd = ["rcctl", "check", name] if platform.system() == "OpenBSD" else ["systemctl", "is-active", "--quiet", name]
    return (
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def get_service_uptime(name: str) -> int | None:
    """Return the uptime of a systemd service in seconds.

    :param name: Service name.
    :return: Uptime in seconds, or ``None`` on error or if the service
        is not running.
    """
    prop = "ExecMainStartTimestampMonotonic"
    try:
        output = run_subprocess(
            ["systemctl", "show", name, f"--property={prop}"],
            timeout=3,
        )
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return None
    raw = parse(output, f"{prop}=", "\n")
    if not raw or raw == "0":
        return None
    start_monotonic = int(raw) / 10**6
    uptime = time.time() - (psutil.boot_time() + start_monotonic)
    return int(uptime)


def get_service_pid(name: str) -> int | None:
    """Return the main PID of a systemd service.

    :param name: Service name.
    :return: PID integer, or ``None`` on error.
    """
    prop = "MainPID"
    try:
        output = run_subprocess(
            ["systemctl", "show", name, f"--property={prop}"],
            timeout=3,
        )
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return None
    raw = parse(output, f"{prop}=", "\n")
    if raw is None:
        return None
    return int(raw)
