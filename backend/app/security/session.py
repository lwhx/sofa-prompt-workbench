from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionPayload:
    session_id: str
    user_id: str
    expires_at: int
    csrf_token: str


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session_token(
    user_id: str, secret: str, ttl_seconds: int, *, session_id: str | None = None
) -> tuple[str, str]:
    csrf_token = secrets.token_urlsafe(32)
    payload = {
        "uid": user_id,
        "sid": session_id or secrets.token_urlsafe(24),
        "exp": int(time.time()) + ttl_seconds,
        "csrf": csrf_token,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _encode(hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}", csrf_token


def decode_session_token(token: str, secret: str) -> SessionPayload | None:
    try:
        encoded, signature = token.split(".", 1)
        expected = _encode(hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_decode(encoded))
        if not isinstance(data, dict) or int(data["exp"]) < int(time.time()):
            return None
        return SessionPayload(
            session_id=str(data["sid"]),
            user_id=str(data["uid"]),
            expires_at=int(data["exp"]),
            csrf_token=str(data["csrf"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

