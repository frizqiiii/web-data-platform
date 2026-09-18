"""Password hashing (Decision B: Argon2id) and secure random token
generation for sessions/CSRF.

RULE: plaintext passwords never appear in logs, audit records, error
messages, or API responses — this module only ever receives a
plaintext password as a function argument to hash/verify it, and
never returns or logs it. Callers must not log the password argument
either (see apps/api/tests/unit/test_security.py for the enforcement
test).
"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Argon2id (argon2-cffi's default `PasswordHasher` uses type=ID)
# with library-recommended parameters — no custom tuning without a
# measured reason, per Section 1.6 (no unjustified complexity).
_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain_password)
    except VerifyMismatchError:
        return False


def generate_token() -> str:
    """Cryptographically secure random token for session/refresh/CSRF
    tokens. 256 bits of entropy, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 of a session/refresh token, used as the Redis key
    (Decision H: hash tokens at rest so a Redis dump alone doesn't
    hand out usable session tokens — the attacker would still need
    the original plaintext token to compute this hash and look up
    the session)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
