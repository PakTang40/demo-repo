"""Finding the one address the phones are allowed to use.

`--host 0.0.0.0` listens on *every* network the PC happens to be attached to. On
the building's own Wi-Fi that is what ADR-0004 assumed. Carry the laptop to a
cafe and it means every stranger on that Wi-Fi can read tenant national ID
numbers by typing an IP address -- no password, because there isn't one.

So the phone mode binds to exactly one interface: the Tailscale one. Devices on
the tailnet reach it from anywhere in the world; the cafe's network cannot see
the socket at all, because nothing is listening on that interface.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
from pathlib import Path

# Tailscale allocates every device an address out of the CGNAT range. Membership
# of this range is what makes an address "the tailnet one" rather than the LAN's.
TAILNET = ipaddress.ip_network("100.64.0.0/10")

_WINDOWS_INSTALL = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"


def in_tailnet(value: str) -> bool:
    try:
        return ipaddress.ip_address(value) in TAILNET
    except ValueError:
        return False


def _tailscale_exe() -> str | None:
    """The CLI is not on PATH in the session that installed it."""
    found = shutil.which("tailscale")
    if found:
        return found
    return str(_WINDOWS_INSTALL) if _WINDOWS_INSTALL.exists() else None


def _from_cli() -> str | None:
    exe = _tailscale_exe()
    if exe is None:
        return None
    try:
        result = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        candidate = line.strip()
        if in_tailnet(candidate):
            return candidate
    return None


def _from_interfaces() -> str | None:
    """Fallback for a machine where the CLI is missing but the interface is up."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return None
    for info in infos:
        address = info[4][0]
        if in_tailnet(address):
            return address
    return None


def tailscale_ip() -> str | None:
    """This machine's tailnet address, or None if Tailscale is not usable yet.

    None covers every "not ready" case the owner can actually hit -- not
    installed, installed but signed out, or the service stopped -- because the
    fix printed on screen is the same for all of them: open Tailscale and sign in.
    """
    return _from_cli() or _from_interfaces()


NOT_READY = """
  ยังเปิดให้มือถือเข้าใช้ไม่ได้ เพราะยังไม่พบที่อยู่ Tailscale ของเครื่องนี้

  วิธีแก้:
    1. เปิดโปรแกรม Tailscale (มุมขวาล่างข้างนาฬิกา)
    2. ล็อกอินด้วยบัญชีเดียวกับที่ใช้ในมือถือ
    3. ให้ไอคอนขึ้นว่า Connected แล้วกด เปิดระบบ.bat /phone อีกครั้ง

  ถ้ายังไม่ได้ติดตั้ง Tailscale ในมือถือ: โหลดจาก App Store / Play Store
  แล้วล็อกอินด้วยบัญชีเดียวกัน

  ระหว่างนี้ยังใช้งานบนคอมเครื่องนี้ได้ตามปกติ ด้วยการดับเบิลคลิก เปิดระบบ.bat
"""
