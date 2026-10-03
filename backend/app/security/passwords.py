"""Password hashing with Argon2id (argon2-cffi defaults: 64 MiB memory, 3 passes, 4 lanes).

Passwords are hashed, never encrypted or stored. Verification of an unknown account still runs one
Argon2id verification against a fixed dummy hash, so response time does not reveal which emails exist.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()          # Argon2id is argon2-cffi's default type
_DUMMY_HASH = _hasher.hash("chakravyuh-dummy-password-for-timing")

MIN_LENGTH, MAX_LENGTH = 12, 128
# Values that have appeared in this project's docs or defaults, plus very common choices.
WEAK = {"change-me-admin", "changeme", "password", "password123", "chakravyuh", "admin", "administrator",
        "123456789012", "qwertyuiop12", "letmein12345"}


def policy_problem(password: str, email: str = "") -> str | None:
    """Return why the password is unacceptable, or None."""
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters"
    if len(password) > MAX_LENGTH:
        return f"Password must be at most {MAX_LENGTH} characters"
    low = password.lower()
    if low in WEAK or low.startswith("change-me"):
        return "Password is too common"
    if email and low == email.lower():
        return "Password must not be the email address"
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)
