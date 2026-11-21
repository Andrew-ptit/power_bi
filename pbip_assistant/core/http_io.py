"""HTTP request framing shared by the two local servers.

The coordinator (task pane) and the source-only UI are separate applications but
they answer the same browser, so they must agree on framing and loopback policy.
Keeping those two decisions here means a fix in one cannot drift from the other.

Nothing here holds handler state: callers pass the header mapping and the request
stream they already own, so this module stays import-light and unit-testable.
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import urlsplit

from .errors import InputError

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def host_header_is_loopback(host_header: str) -> bool:
    """True when a Host/X-Forwarded style header names a loopback host."""
    try:
        hostname = urlsplit(f"//{host_header}").hostname
    except ValueError:
        return False
    return hostname in LOOPBACK_HOSTS


def origin_is_loopback(origin: str, *, schemes: frozenset[str]) -> bool:
    """True when an Origin header is an absolute URL on a loopback host."""
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in schemes and parsed.hostname in LOOPBACK_HOSTS


def read_body(headers: Mapping[str, Any], rfile, maximum: int) -> bytes:
    """Read exactly Content-Length bytes, refusing anything above the limit."""
    value = headers.get("Content-Length")
    if value is None:
        raise ValueError("Content-Length is required")
    length = int(value)
    if length < 0 or length > maximum:
        raise InputError("REQUEST_LIMIT", "", f"Request exceeds {maximum} bytes")
    payload = rfile.read(length)
    if len(payload) != length:
        raise ValueError("Request body ended early")
    return payload


def read_json(headers: Mapping[str, Any], rfile, maximum: int) -> dict[str, Any]:
    """Read a bounded JSON object body."""
    value = json.loads(read_body(headers, rfile, maximum).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value
