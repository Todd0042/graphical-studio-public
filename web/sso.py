"""Verify dev sign-in tickets minted by the configured SSO provider.

A ticket is `<base64url json>.<hmac-sha256 hex>` over {u: GitHub login, aud: site id, exp, n: nonce},
signed with the shared secret in DEV_SSO_SECRET. It is accepted once, only for this site,
only before it expires, and only for the allowed GitHub user.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from pathlib import Path


class TicketError(ValueError):
    pass


class TicketVerifier:
    def __init__(self, secret_path: Path, audience: str, allowed_user: str) -> None:
        self.secret_path = secret_path
        self.audience = audience
        self.allowed_user = allowed_user.lower()
        self._seen: dict[str, float] = {}  # nonce -> expiry (replay protection)
        self._lock = threading.Lock()

    def _secret(self) -> bytes:
        try:
            return self.secret_path.read_bytes().strip()
        except OSError as exc:
            raise TicketError("Dev sign-in is not configured on this host") from exc

    def verify(self, ticket: str) -> str:
        """Return the GitHub login the ticket vouches for, or raise TicketError."""
        body, _, sig = (ticket or "").partition(".")
        if not body or len(sig) != 64:
            raise TicketError("Malformed ticket")
        expected = hmac.new(self._secret(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise TicketError("Bad signature")
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            user, aud, exp, nonce = str(data["u"]).lower(), str(data["aud"]), int(data["exp"]), str(data["n"])
        except (ValueError, KeyError, TypeError) as exc:
            raise TicketError("Malformed ticket") from exc
        now = time.time()
        if aud != self.audience:
            raise TicketError("Ticket is for another site")
        if exp < now:
            raise TicketError("Ticket expired")
        if user != self.allowed_user:
            raise TicketError("User not allowed")
        with self._lock:
            for n, e in [(n, e) for n, e in self._seen.items() if e < now]:
                self._seen.pop(n, None)
            if nonce in self._seen:
                raise TicketError("Ticket already used")
            self._seen[nonce] = exp
        return user
