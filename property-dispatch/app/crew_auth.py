"""Crew sign-in: personal codes for each crew member, a master code for the owner.

* Personal codes are stored only as salted PBKDF2 hashes.
* Signing in returns a signed session token (no server-side session table).
  The signing key is derived from CREW_ACCESS_TOKEN, so changing the owner's
  master code signs every phone out.
* Failed attempts are throttled per IP to slow down guessing.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass

PBKDF2_ROUNDS = 200_000
SESSION_DAYS = 30
MAX_FAILS = 8
FAIL_WINDOW_S = 15 * 60
OWNER = "owner"


@dataclass(frozen=True)
class CrewIdentity:
    member_id: str | None   # None for the owner's master-code session
    is_owner: bool


def hash_code(code: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def check_code(code: str, stored: str) -> bool:
    try:
        _, rounds, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt_hex), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def valid_code(code: str) -> bool:
    """Personal codes: 4-32 characters. Short PINs are fine; the IP throttle limits guessing."""
    return 4 <= len(code) <= 32 and not code.isspace()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "crew"


class SessionSigner:
    def __init__(self, master_code: str):
        self._key = hmac.new(master_code.encode(), b"crew-session-v1", hashlib.sha256).digest()

    def issue(self, subject: str, now: float | None = None) -> str:
        body = json.dumps({"sub": subject, "exp": int((now or time.time()) + SESSION_DAYS * 86400)},
                          separators=(",", ":")).encode()
        payload = base64.urlsafe_b64encode(body).decode().rstrip("=")
        sig = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
        return f"cs1.{payload}.{sig}"

    def read(self, token: str, now: float | None = None) -> str | None:
        try:
            prefix, payload, sig = token.split(".")
        except ValueError:
            return None
        if prefix != "cs1":
            return None
        expected = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except ValueError:
            return None
        if data.get("exp", 0) < (now or time.time()):
            return None
        return data.get("sub")


class LoginThrottle:
    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            recent = [t for t in self._fails.get(key, []) if now - t < FAIL_WINDOW_S]
            self._fails[key] = recent
            return len(recent) >= MAX_FAILS

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
