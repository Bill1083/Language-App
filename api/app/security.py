"""Password hashing, cookie sessions and CSRF.

Sessions: a random token in an HTTP-only cookie; only its SHA-256 is stored.
CSRF: double-submit. A readable `parlo_csrf` cookie is issued at login and the
frontend echoes it in `X-CSRF-Token` on every unsafe request.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Request, Response

from .config import get_settings

SESSION_COOKIE = "parlo_session"
CSRF_COOKIE = "parlo_csrf"
CSRF_HEADER = "x-csrf-token"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=get_settings().session_days)


def cookie_is_secure(request: Request) -> bool:
    mode = get_settings().cookie_secure
    if mode == "true":
        return True
    if mode == "false":
        return False
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def set_session_cookies(request: Request, response: Response, token: str) -> None:
    secure = cookie_is_secure(request)
    max_age = get_settings().session_days * 86400
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=secure, samesite="lax", path="/"
    )
    response.set_cookie(
        CSRF_COOKIE, new_token(18), max_age=max_age, httponly=False, secure=secure, samesite="lax", path="/"
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def csrf_ok(request: Request) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    return bool(cookie and header and hmac.compare_digest(cookie, header))


def allowed_ws_origin(request_origin: str | None, host: str | None, forwarded_host: str | None = None) -> bool:
    """CSRF check for the WebSocket handshake, which can't carry the CSRF header.

    The page's origin must be this site: the Host the request arrived with, the
    X-Forwarded-Host a proxy passed on, or the configured DOMAIN. The DOMAIN
    fallback matters behind proxies that rewrite Host (an Nginx location with
    its own proxy_set_header lines sends the upstream name instead).
    """
    if not request_origin:
        return False
    origin_host = request_origin.split("://", 1)[-1].rstrip("/").lower()
    allowed = {h.strip().lower() for h in (host, *(forwarded_host or "").split(",")) if h and h.strip()}
    domain = get_settings().domain.strip().lower()
    if domain:
        allowed.add(domain)
    return origin_host in allowed or origin_host.split(":")[0] == domain
