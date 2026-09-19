"""Who is asking: nobody, a player, or the DM.

No passwords set   -> everything open; the machine running the server is the DM.
table_password set -> players log in once (cookie); needed before exposing the site.
dm_password set    -> that password logs in as DM from any device; the loopback
                      shortcut switches off so a tunnel can't impersonate the DM.
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Request

from .config import Settings

COOKIE = "am_auth"
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
_PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for", "x-real-ip")


def _secret(settings: Settings) -> bytes:
    return hashlib.sha256(f"{settings.table_password}\0{settings.dm_password}\0artificers-manual".encode()).digest()


def token_for(role: str, settings: Settings) -> str:
    sig = hmac.new(_secret(settings), role.encode(), "sha256").hexdigest()
    return f"{role}.{sig}"


def role_from_cookie(request: Request, settings: Settings) -> str | None:
    raw = request.cookies.get(COOKIE, "")
    role, _, sig = raw.partition(".")
    if role in ("player", "dm") and hmac.compare_digest(token_for(role, settings), f"{role}.{sig}"):
        return role
    return None


def _is_local(request: Request) -> bool:
    if any(h in request.headers for h in _PROXY_HEADERS):
        return False
    host = request.client.host if request.client else ""
    return host in _LOOPBACK


def role_for(request: Request, settings: Settings) -> str | None:
    """The effective role, or None when a login is required first."""
    role = role_from_cookie(request, settings)
    if role:
        return role
    if not settings.dm_password and _is_local(request):
        return "dm"
    if not settings.table_password:
        return "player"
    return None


def login_role(password: str, settings: Settings) -> str | None:
    if settings.dm_password and hmac.compare_digest(password, settings.dm_password):
        return "dm"
    if settings.table_password and hmac.compare_digest(password, settings.table_password):
        return "player"
    return None
