"""Who is asking: nobody, a player, or the DM - and which characters this browser has claimed.

No passwords set   -> the site is open; the machine running the server is the DM.
table_password set -> players sign in once (cookie); needed before exposing the site.
dm_password set    -> that password signs in as DM from any device; the loopback
                      shortcut switches off so a tunnel can't impersonate the DM.

Each character carries its own password: the first person to open the sheet sets
one, after that the browser keeps an unlock cookie and everyone else needs the
password. The DM opens everything. Cookies are signed with a random secret kept
next to the database, so they cannot be forged.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path

from fastapi import Request

from .config import Settings

COOKIE = "am_auth"
CHAR_COOKIE = "am_chars"
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
_PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for", "x-real-ip")


def load_secret(settings: Settings) -> bytes:
    """A random signing key, created on first run and kept beside the database."""
    path = Path(settings.db_path).parent / "secret.key"
    if path.exists():
        return bytes.fromhex(path.read_text().strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_text(key.hex())
    return key


def _sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode(), "sha256").hexdigest()


# ------------------------------------------------------------------ roles
def token_for(role: str, secret: bytes) -> str:
    return f"{role}.{_sign(secret, 'role:' + role)}"


def role_from_cookie(request: Request, secret: bytes) -> str | None:
    raw = request.cookies.get(COOKIE, "")
    role, _, sig = raw.partition(".")
    if role in ("player", "dm") and hmac.compare_digest(token_for(role, secret), f"{role}.{sig}"):
        return role
    return None


def _is_local(request: Request) -> bool:
    if any(h in request.headers for h in _PROXY_HEADERS):
        return False
    host = request.client.host if request.client else ""
    return host in _LOOPBACK


def role_for(request: Request, settings: Settings, secret: bytes) -> str | None:
    """The effective role, or None when a sign-in is required first."""
    role = role_from_cookie(request, secret)
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


# ------------------------------------------------------------------ character passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 50_000).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 50_000).hex()
    return hmac.compare_digest(candidate, digest)


def unlocked_from_cookie(request: Request, secret: bytes) -> set[int]:
    raw = request.cookies.get(CHAR_COOKIE, "")
    ids, _, sig = raw.partition(".")
    if not ids or not hmac.compare_digest(_sign(secret, "chars:" + ids), sig):
        return set()
    return {int(x) for x in ids.split(",") if x.isdigit()}


def unlock_cookie_value(ids: set[int], secret: bytes) -> str:
    joined = ",".join(str(i) for i in sorted(ids))
    return f"{joined}.{_sign(secret, 'chars:' + joined)}"


class Locked(Exception):
    """Raised when a sheet needs its character password first."""

    def __init__(self, cid: int):
        super().__init__(f"character {cid} is locked")
        self.cid = cid
