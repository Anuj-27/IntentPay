from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.db.models import PaymentDB
from backend.app.schemas.payment import PaymentStatus
from backend.app.services.payment_state_machine import (
    transition_payment_status,
)
from backend.app.services.audit_service import create_audit_log


# ============================================================
# Convert SQLAlchemy PaymentDB object into a normal dictionary
# ============================================================

def payment_to_dict(payment: PaymentDB):
    return {
        "payment_id": payment.payment_id,
        "intent_id": payment.intent_id,
        "product_id": payment.product_id,
        "amount": payment.amount,
        "status": payment.status,
        "idempotency_key": payment.idempotency_key,
        "created_at": payment.created_at,
        "updated_at": payment.updated_at,
    }


# ============================================================
# CREATE PAYMENT
# ============================================================

def create_payment(
    db: Session,
    intent_id: str,
    product_id: str,
    amount: int,
    idempotency_key: str,
):
    # --------------------------------------------------------
    # Check whether this idempotency key already exists
    # --------------------------------------------------------

    existing_payment = (
        db.query(PaymentDB)
        .filter(
            PaymentDB.idempotency_key == idempotency_key
        )
        .first()
    )

    # --------------------------------------------------------
    # Same idempotency key already exists
    # --------------------------------------------------------

    if existing_payment is not None:

        # Same logical payment request
        if (
            existing_payment.intent_id == intent_id
            and existing_payment.product_id == product_id
            and existing_payment.amount == amount
        ):
            return {
                "success": True,
                "created": False,
                "reason_code": "IDEMPOTENT_REPLAY",
                "message": (
                    "A payment already exists for this "
                    "idempotency key."
                ),
                "payment": payment_to_dict(
                    existing_payment
                ),
            }

        # Same key but different payment data
        return {
            "success": False,
            "created": False,
            "reason_code": "IDEMPOTENCY_KEY_CONFLICT",
            "message": (
                "The idempotency key was already used "
                "for a different payment."
            ),
            "payment": payment_to_dict(
                existing_payment
            ),
        }

    # --------------------------------------------------------
    # Create new persistent payment
    # --------------------------------------------------------

    payment = PaymentDB(
        payment_id=str(uuid4()),
        intent_id=intent_id,
        product_id=product_id,
        amount=amount,
        status=PaymentStatus.CREATED.value,
        idempotency_key=idempotency_key,
    )

    # --------------------------------------------------------
    # Atomic transaction:
    # payment + audit must succeed together
    # --------------------------------------------------------

    try:
        db.add(payment)

        # Send INSERT to PostgreSQL,
        # but do not permanently commit yet.
        db.flush()

        create_audit_log(
            db=db,
            event_type="PAYMENT_CREATED",
            component="PAYMENT_SERVICE",
            message=(
                "A new persistent payment record was created."
            ),
            entity_type="PAYMENT",
            entity_id=payment.payment_id,
            reason_code="PAYMENT_CREATED",
            amount=payment.amount,
            details={
                "intent_id": payment.intent_id,
                "product_id": payment.product_id,
                "idempotency_key": payment.idempotency_key,
                "status": payment.status,
            },
        )

        # Payment and audit log become permanent together.
        db.commit()

    except Exception:
        db.rollback()
        raise

    db.refresh(payment)

    return {
        "success": True,
        "created": True,
        "reason_code": "PAYMENT_CREATED",
        "message": (
            "A new persistent payment record was created."
        ),
        "payment": payment_to_dict(payment),
    }


# ============================================================
# FIND PAYMENT
# ============================================================

def find_payment_by_id(
    db: Session,
    payment_id: str,
):
    return (
        db.query(PaymentDB)
        .filter(
            PaymentDB.payment_id == payment_id
        )
        .first()
    )


# ============================================================
# UPDATE PAYMENT STATUS
# ============================================================

def update_payment_status(
    db: Session,
    payment_id: str,
    new_status: PaymentStatus,
    commit: bool = True,
):
    # --------------------------------------------------------
    # Find payment
    # --------------------------------------------------------

    payment = find_payment_by_id(
        db=db,
        payment_id=payment_id,
    )

    if payment is None:
        return {
            "success": False,
            "reason_code": "PAYMENT_NOT_FOUND",
            "message": (
                f"Payment '{payment_id}' was not found."
            ),
        }

    # Convert stored string to PaymentStatus enum
    current_status = PaymentStatus(
        payment.status
    )

    # --------------------------------------------------------
    # Validate state-machine transition
    # --------------------------------------------------------

    transition_result = transition_payment_status(
        current_status,
        new_status,
    )

    if not transition_result["success"]:
        return {
            "success": False,
            "reason_code": "INVALID_PAYMENT_TRANSITION",
            "message": (
                f"Payment cannot move from "
                f"{current_status.value} to {new_status.value}."
            ),
            "payment": payment_to_dict(payment),
            "transition": transition_result,
        }

    previous_status = payment.status

    payment.status = new_status.value

    # --------------------------------------------------------
    # Atomic status update + audit event
    # --------------------------------------------------------

    try:
        db.flush()

        create_audit_log(
            db=db,
            event_type="PAYMENT_STATUS_CHANGED",
            component="PAYMENT_SERVICE",
            message=(
                f"Payment status changed from "
                f"{previous_status} to {new_status.value}."
            ),
            entity_type="PAYMENT",
            entity_id=payment.payment_id,
            reason_code="PAYMENT_STATUS_CHANGED",
            amount=payment.amount,
            details={
                "previous_status": previous_status,
                "new_status": new_status.value,
            },
        )

        if commit:
            db.commit()

    except Exception:
        db.rollback()
        raise

    if commit:
        db.refresh(payment)

    return {
        "success": True,
        "reason_code": "PAYMENT_STATUS_CHANGED",
        "payment_id": payment.payment_id,
        "previous_status": previous_status,
        "new_status": payment.status,
        "payment": payment_to_dict(payment),
    }


# ============================================================
# RECONCILE UNKNOWN PAYMENT
# ============================================================

def reconcile_payment(
    db: Session,
    payment_id: str,
    resolved_status: PaymentStatus,
    commit: bool = True,
):
    # --------------------------------------------------------
    # Find payment
    # --------------------------------------------------------

    payment = find_payment_by_id(
        db=db,
        payment_id=payment_id,
    )

    if payment is None:
        return {
            "success": False,
            "reason_code": "PAYMENT_NOT_FOUND",
            "message": (
                f"Payment '{payment_id}' was not found."
            ),
        }

    # --------------------------------------------------------
    # Reconciliation is only valid from UNKNOWN
    # --------------------------------------------------------

    if payment.status != PaymentStatus.UNKNOWN.value:
        return {
            "success": False,
            "reason_code": "PAYMENT_NOT_UNKNOWN",
            "message": (
                "Reconciliation can only be performed "
                "for payments in UNKNOWN status."
            ),
            "payment": payment_to_dict(payment),
        }

    # --------------------------------------------------------
    # Validate UNKNOWN -> resolved state
    # --------------------------------------------------------

    transition_result = transition_payment_status(
        PaymentStatus.UNKNOWN,
        resolved_status,
    )

    if not transition_result["success"]:
        return {
            "success": False,
            "reason_code": "INVALID_RECONCILIATION_STATE",
            "message": (
                f"UNKNOWN payment cannot be reconciled "
                f"to {resolved_status.value}."
            ),
            "transition": transition_result,
            "payment": payment_to_dict(payment),
        }

    previous_status = payment.status

    payment.status = resolved_status.value

    # --------------------------------------------------------
    # Atomic reconciliation + audit event
    # --------------------------------------------------------

    try:
        db.flush()

        create_audit_log(
            db=db,
            event_type="PAYMENT_RECONCILED",
            component="PAYMENT_SERVICE",
            message=(
                f"Payment was reconciled from "
                f"{previous_status} to {resolved_status.value}."
            ),
            entity_type="PAYMENT",
            entity_id=payment.payment_id,
            reason_code="PAYMENT_RECONCILED",
            amount=payment.amount,
            details={
                "previous_status": previous_status,
                "resolved_status": resolved_status.value,
            },
        )

        if commit:
            db.commit()

    except Exception:
        db.rollback()
        raise

    if commit:
        db.refresh(payment)

    return {
        "success": True,
        "reason_code": "PAYMENT_RECONCILED",
        "previous_status": previous_status,
        "new_status": payment.status,
        "payment": payment_to_dict(payment),
    }
