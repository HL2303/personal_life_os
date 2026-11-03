import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

password_hasher = PasswordHasher()
_DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for_session(session_token: str) -> str:
    return hmac.new(
        session_token.encode("utf-8"),
        b"personal-life-os-csrf-v1",
        hashlib.sha256,
    ).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def dummy_password_hash() -> str:
    return _DUMMY_PASSWORD_HASH
