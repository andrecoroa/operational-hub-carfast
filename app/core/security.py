import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 390_000
TOKEN_ALGORITHM = "carfast_token_v1"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected = password_hash.split("$", 3)
        iterations = int(iterations_text)
    except ValueError:
        return False

    if algorithm != PASSWORD_ALGORITHM:
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual, expected)


def create_access_token(subject: str, secret_key: str, expires_minutes: int = 480) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    expires_ts = str(int(expires_at.timestamp()))
    nonce = secrets.token_urlsafe(16)
    payload = f"{TOKEN_ALGORITHM}:{subject}:{expires_ts}:{nonce}"
    signature = hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_access_token(token: str, secret_key: str) -> str | None:
    try:
        algorithm, subject, expires_ts, nonce, signature = token.split(":", 4)
    except ValueError:
        return None

    if algorithm != TOKEN_ALGORITHM or not subject or not expires_ts or not nonce:
        return None

    payload = f"{algorithm}:{subject}:{expires_ts}:{nonce}"
    expected = hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    try:
        expires_at = datetime.fromtimestamp(int(expires_ts), tz=timezone.utc)
    except ValueError:
        return None

    if expires_at <= datetime.now(timezone.utc):
        return None
    return subject
