"""HMAC-signed session cookies for the web wrapper (sign-in tickets are verified by web/sso.py)."""

from __future__ import annotations

import hashlib
import hmac
import time

SESSION_COOKIE_NAME = "gs_session"


def create_session_token(username: str, secret: str, ttl_seconds: int) -> str:
    payload = f"{username}.{int(time.time()) + ttl_seconds}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: str | None, secret: str, expected_user: str) -> str | None:
    if not token or not secret:
        return None
    parts = token.rsplit(".", 2)
    if len(parts) != 3:
        return None
    username, expires, sig = parts
    try:
        if int(expires) <= int(time.time()):
            return None
    except ValueError:
        return None
    expected_sig = hmac.new(secret.encode(), f"{username}.{expires}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig) or not hmac.compare_digest(username, expected_user):
        return None
    return username


def safe_next_path(next_path: str | None) -> str:
    """Only local relative redirects (no open redirect)."""
    cleaned = (next_path or "").strip()
    if not cleaned.startswith("/") or cleaned.startswith("//") or "\\" in cleaned:
        return "/"
    return cleaned
