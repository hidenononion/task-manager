"""security.py - helper an toan dung chung cho app.

Tap trung cac kiem tra nho, de test duoc doc lap:
  - SlidingWindowLimiter: gioi han so lan thu (chong brute-force)
  - is_public_http_url: chan SSRF khi goi webhook ra ngoai
  - safe_display_filename / file_signature_ok: chong path traversal + upload gia mao
  - csv_safe: chong CSV/Formula injection khi export
  - is_safe_link_url: chan link javascript:/data: trong attachment/avatar
"""

from __future__ import annotations

import ipaddress
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime
from urllib.parse import urlsplit

ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "doc", "docx"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_MAGIC_PREFIXES = {
    "pdf": (b"%PDF-",),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "docx": (b"PK\x03\x04", b"PK\x05\x06"),
}

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "metadata.google.internal.",
    "instance-data",
}


class SlidingWindowLimiter:
    """Bo dem theo cua so truot, an toan khi dung tu nhieu thread.

    Moi key giu danh sach thoi diem cac lan "hit" trong window_seconds.
    hit() tra ve 0 neu duoc phep, hoac so giay phai cho (>=1) neu bi chan.
    """

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))
        self._events: dict[str, deque] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(str(key), deque())
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.max_attempts:
                return max(1, int(events[0] + self.window_seconds - now) + 1)
            events.append(now)
            return 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(str(key), None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def _is_public_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_public_http_url(url: str, *, resolve_dns: bool = True) -> bool:
    """True neu URL la http(s) tro toi host cong khai (khong phai noi bo).

    resolve_dns=False chi kiem tra hinh thuc URL (dung o buoc gui lai webhook,
    tranh moi request deu phai phan giai DNS).
    """
    if not isinstance(url, str) or not url or len(url) > 2048:
        return False
    if any(ch in url for ch in ("\r", "\n", "\t", "\x00")):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if not parts.hostname or parts.username or parts.password:
        return False
    host = parts.hostname.strip().lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTNAMES or host.endswith(".local"):
        return False
    try:
        host.encode("idna")
    except UnicodeError:
        return False
    # Neu host la IP literal, kiem tra truc tiep.
    try:
        ipaddress.ip_address(host)
        return _is_public_ip(host)
    except ValueError:
        pass
    if not resolve_dns:
        return True
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError, UnicodeError):
        return False
    if not infos:
        return False
    # Moi dia chi phan giai duoc deu phai cong khai (chan DNS rebinding co ban).
    return all(_is_public_ip(info[4][0]) for info in infos)


def is_safe_link_url(url: str) -> bool:
    """Cho phep link http(s) hoac duong dan noi bo /... (khong cho //host)."""
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url or len(url) > 2048:
        return False
    if any(ord(ch) < 32 for ch in url):
        return False
    if url.startswith("//"):
        return False
    if url.startswith("/"):
        return True
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def safe_filename(filename: str, *, max_length: int = 120) -> str:
    """Lay ten file an toan: bo duong dan, ky tu dieu khien va '..'."""
    name = (filename or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32 and ch not in '<>:"|?*')
    name = name.strip().strip(".").replace("\x00", "")
    if not name:
        name = "file"
    stem, ext = os.path.splitext(name)
    ext = ext[:10]
    stem = stem[: max(1, max_length - len(ext))]
    return (stem or "file") + ext


def file_signature_ok(ext: str, head: bytes) -> bool:
    """Kiem tra magic bytes co khop voi phan mo rong duoc phep khong."""
    prefixes = _MAGIC_PREFIXES.get((ext or "").lower())
    if not prefixes:
        return False
    return any(head.startswith(prefix) for prefix in prefixes)


def csv_safe(value):
    """Chong formula injection: chi xu ly chuoi, giu nguyen so."""
    if not isinstance(value, str):
        return value
    # Bo qua khoang trang dau dong truoc khi kiem tra ky tu nguy hiem.
    if value.lstrip(" \t\r\n")[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
