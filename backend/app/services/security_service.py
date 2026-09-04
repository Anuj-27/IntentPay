import base64
import hashlib
import hmac
import json
import os
import secrets
import time


PBKDF2_ITERATIONS = 200_000
SESSION_COOKIE_NAME = "intentpay_merchant_session"
SESSION_TTL_SECONDS = 60 * 60 * 12
PASSWORD_RESET_TTL_SECONDS = 15 * 60
DEFAULT_SESSION_SECRET = "dev-only-insecure-secret-change-me"
SECURE_ENVIRONMENTS = {"production", "prod", "staging"}


def _is_secure_environment() -> bool:
    return os.getenv("APP_ENV", "development").strip().casefold() in SECURE_ENVIRONMENTS


def validate_security_configuration() -> None:
    """Fail fast when a deployment is marked non-local but still uses the
    development session secret.

    Local Test Mode keeps the deterministic fallback so a new learner can run
    the project immediately. Staging/production must provide a long,
    deployment-specific secret instead of silently issuing forgeable cookies.
    """

    configured = os.getenv("MERCHANT_SESSION_SECRET", "").strip()
    if not _is_secure_environment():
        return
    if not configured or configured == DEFAULT_SESSION_SECRET:
        raise RuntimeError(
            "MERCHANT_SESSION_SECRET must be set to a unique secret before "
            "starting a staging or production deployment."
        )
    if len(configured) < 32:
        raise RuntimeError(
            "MERCHANT_SESSION_SECRET must contain at least 32 characters."
        )


def _session_secret() -> bytes:
    validate_security_configuration()
    configured = os.getenv("MERCHANT_SESSION_SECRET", "").strip()
    return (configured or DEFAULT_SESSION_SECRET).encode("utf-8")


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    candidate_hash, _ = hash_password(password, bytes.fromhex(password_salt))
    return hmac.compare_digest(candidate_hash, password_hash)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_session_token(merchant_id: str) -> str:
    payload = json.dumps(
        {"merchant_id": merchant_id, "expires_at": time.time() + SESSION_TTL_SECONDS}
    ).encode("utf-8")
    signature = hmac.new(_session_secret(), payload, hashlib.sha256).digest()
    return f"{_b64encode(payload)}.{_b64encode(signature)}"


def verify_session_token(token: str) -> str | None:
    try:
        payload_part, signature_part = token.split(".", 1)
        payload = _b64decode(payload_part)
        signature = _b64decode(signature_part)
    except ValueError:
        return None

    expected_signature = hmac.new(_session_secret(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        data = json.loads(payload)
    except ValueError:
        return None

    if data.get("expires_at", 0) < time.time():
        return None

    merchant_id = data.get("merchant_id")
    return merchant_id if isinstance(merchant_id, str) else None


def generate_password_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_password_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
