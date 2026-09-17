"""Access boundary for deployment-wide administrative APIs.

AI-Research-OS intentionally has no user-account system.  Space keys isolate
ordinary research data, but they are not credentials and therefore must not
authorize deployment-wide operations such as backup restore or secret/config
updates.

Policy:
* genuinely local requests are allowed without a token, preserving the
  zero-login desktop workflow;
* non-local requests must present ``X-Admin-Token`` matching ``ADMIN_TOKEN``;
* proxy headers and browser Origin/Referer are considered so a LAN request
  forwarded through the Vite development proxy is not mistaken for localhost.
"""
from __future__ import annotations

import hmac
import ipaddress
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request, status

from . import config

ADMIN_HEADER = "X-Admin-Token"


def _is_loopback_host(value: str | None) -> bool:
    """Return whether a hostname/IP denotes this machine's loopback."""
    raw = (value or "").strip().lower().strip("[]")
    if not raw:
        return False
    if raw in {"localhost", "testclient"}:  # testclient is Starlette's in-process host.
        return True
    # Header values may contain a port.  Bracketed IPv6 was stripped above.
    if raw.count(":") == 1 and raw.rsplit(":", 1)[1].isdigit():
        raw = raw.rsplit(":", 1)[0]
    try:
        address = ipaddress.ip_address(raw)
        if address.is_loopback:
            return True
        mapped = getattr(address, "ipv4_mapped", None)
        return bool(mapped and mapped.is_loopback)
    except ValueError:
        return False


def _header_url_is_local(value: str | None) -> bool:
    """Validate a browser Origin/Referer; opaque or malformed values are remote."""
    if not value:
        return True
    try:
        return _is_loopback_host(urlsplit(value).hostname)
    except ValueError:
        return False


def request_is_local(request: Request) -> bool:
    """Conservatively decide whether the original caller is local.

    ``X-Forwarded-For`` wins over the socket peer.  This is important for the
    Vite proxy, which connects to FastAPI from loopback on behalf of a browser.
    A browser Origin/Referer, when present, must also be loopback.
    """
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    # Only trust forwarding metadata from a local reverse proxy. A direct
    # remote client must not be able to spoof X-Forwarded-For: 127.0.0.1.
    if forwarded and _is_loopback_host(peer):
        caller = forwarded.split(",", 1)[0].strip()
    else:
        caller = peer
    if not _is_loopback_host(caller):
        return False
    if not _header_url_is_local(request.headers.get("origin")):
        return False
    if not _header_url_is_local(request.headers.get("referer")):
        return False
    return True


def admin_token_matches(candidate: str | None) -> bool:
    expected = config.settings.admin_token.strip()
    supplied = (candidate or "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


async def require_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias=ADMIN_HEADER),
) -> None:
    """FastAPI dependency protecting deployment-wide sensitive operations."""
    if request_is_local(request) or admin_token_matches(x_admin_token):
        return
    configured = bool(config.settings.admin_token.strip())
    detail = (
        f"远程系统管理需要有效的 {ADMIN_HEADER}"
        if configured
        else f"远程系统管理已禁用；请在后端配置 ADMIN_TOKEN 后使用 {ADMIN_HEADER}"
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def startup_security_message() -> str:
    """Return a visible startup summary without ever exposing the token."""
    host = config.settings.app_host.strip()
    public_bind = host not in {"127.0.0.1", "::1", "localhost"}
    configured = bool(config.settings.admin_token.strip())
    if configured:
        strength = "" if len(config.settings.admin_token) >= 32 else " WARNING: token is shorter than 32 characters."
        return (
            "[security] admin APIs: localhost or X-Admin-Token; "
            f"remote administration enabled with ADMIN_TOKEN.{strength}"
        )
    if public_bind:
        return (
            "[security] WARNING: server is bound beyond loopback; remote admin APIs "
            "are blocked until ADMIN_TOKEN is configured."
        )
    return "[security] admin APIs are restricted to localhost."


__all__ = [
    "ADMIN_HEADER",
    "admin_token_matches",
    "request_is_local",
    "require_admin",
    "startup_security_message",
]
