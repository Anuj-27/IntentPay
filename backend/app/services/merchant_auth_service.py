from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.db.models import MerchantCredentialDB, MerchantPasswordResetDB
from backend.app.services.merchant_service import find_merchant_contract
from backend.app.services.security_service import (
    PASSWORD_RESET_TTL_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    _is_secure_environment,
    create_session_token,
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    verify_password,
    verify_session_token,
    validate_security_configuration,
)


def create_merchant_credential(
    db: Session,
    merchant_id: str,
    password: str,
    *,
    commit: bool = True,
) -> None:
    password_hash, password_salt = hash_password(password)
    db.add(
        MerchantCredentialDB(
            merchant_id=merchant_id,
            password_hash=password_hash,
            password_salt=password_salt,
        )
    )
    if commit:
        db.commit()
    else:
        db.flush()


def authenticate_merchant(db: Session, merchant_id: str, password: str) -> bool:
    credential = (
        db.query(MerchantCredentialDB)
        .filter(MerchantCredentialDB.merchant_id == merchant_id)
        .first()
    )
    if credential is None:
        return False
    return verify_password(password, credential.password_hash, credential.password_salt)


def create_password_reset_token(db: Session, merchant_id: str) -> str | None:
    """Issues a one-time reset token when the merchant has credentials on
    file, or None otherwise. IntentPay has no email/SMS transport
    configured, so (matching the project's existing Test Mode / demo-
    credential transparency) the raw token is returned to the caller
    directly -- only its hash is ever persisted, and it expires quickly
    and can only be redeemed once."""

    credential = (
        db.query(MerchantCredentialDB)
        .filter(MerchantCredentialDB.merchant_id == merchant_id)
        .first()
    )
    if credential is None:
        return None

    token = generate_password_reset_token()
    db.add(
        MerchantPasswordResetDB(
            token_hash=hash_password_reset_token(token),
            merchant_id=merchant_id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=PASSWORD_RESET_TTL_SECONDS),
        )
    )
    db.commit()
    return token


def reset_password_with_token(db: Session, token: str, new_password: str) -> bool:
    token_hash = hash_password_reset_token(token)
    reset_record = (
        db.query(MerchantPasswordResetDB)
        .filter(MerchantPasswordResetDB.token_hash == token_hash)
        # PostgreSQL serializes two simultaneous reset attempts for the same
        # token. SQLite ignores this clause, while the test suite still
        # verifies the normal one-time path.
        .with_for_update()
        .first()
    )
    if reset_record is None or reset_record.used:
        return False

    expires_at = reset_record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return False

    credential = (
        db.query(MerchantCredentialDB)
        .filter(MerchantCredentialDB.merchant_id == reset_record.merchant_id)
        .first()
    )
    if credential is None:
        return False

    password_hash, password_salt = hash_password(new_password)
    credential.password_hash = password_hash
    credential.password_salt = password_salt
    reset_record.used = True
    db.commit()
    return True


def set_session_cookie(response: Response, merchant_id: str) -> None:
    validate_security_configuration()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(merchant_id),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_is_secure_environment(),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME)


def get_current_merchant_id(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> str:
    merchant_id = (
        verify_session_token(session_token) if session_token else None
    )
    if merchant_id is None:
        raise HTTPException(
            status_code=401,
            detail={
                "reason_code": "MERCHANT_SESSION_REQUIRED",
                "message": "Log in as a merchant to manage this catalog.",
            },
        )
    return merchant_id


def require_active_merchant(
    merchant_id: str = Depends(get_current_merchant_id),
    db: Session = Depends(get_db),
) -> str:
    contract = find_merchant_contract(merchant_id, db=db)
    if contract is None or not contract.merchant.active:
        raise HTTPException(
            status_code=401,
            detail={
                "reason_code": "MERCHANT_SESSION_INVALID",
                "message": "This merchant session is no longer valid.",
            },
        )
    return merchant_id
