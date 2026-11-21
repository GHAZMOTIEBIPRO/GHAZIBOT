"""Password hashing, opaque tokens and time helpers (standard library only)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

# scrypt parameters: N=2^15, r=8, p=1 (OWASP minimum for scrypt), 32-byte key.
_N, _R, _P, _DKLEN = 2**15, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD_LENGTH = 10


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def in_hours(hours: float) -> str:
    return iso(utcnow() + timedelta(hours=hours))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM)
    enc = base64.urlsafe_b64encode
    return f"scrypt${_N}${_R}${_P}${enc(salt).decode()}${enc(key).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, key_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(key_b64)
        key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
                             dklen=len(expected), maxmem=_MAXMEM)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key, expected)


# A fixed hash used to spend the same time on unknown e-mails (anti-enumeration).
_DUMMY_HASH: str | None = None


def dummy_verify(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")
    verify_password(password, _DUMMY_HASH)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Only the SHA-256 of a session / one-time token is stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_problem(password: str) -> str | None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return f"كلمة المرور يجب ألا تقل عن {MIN_PASSWORD_LENGTH} أحرف."
    if len(password) > 256:
        return "كلمة المرور أطول من المسموح."
    if password.isdigit() or password.isalpha():
        return "استخدم حروفًا وأرقامًا معًا."
    return None


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def signature_ok(secret: str, body: bytes, given: str) -> bool:
    if not secret or not given:
        return False
    return hmac.compare_digest(sign(secret, body), given.strip())
