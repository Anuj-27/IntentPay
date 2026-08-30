from sqlalchemy.orm import Session

from backend.app.db.models import WebhookEventDB
from backend.app.schemas.payment import PaymentStatus

from backend.app.services.payment_service import (
    find_payment_by_id,
    update_payment_status,
    reconcile_payment,
    payment_to_dict,
)

from backend.app.services.audit_service import create_audit_log


def process_payment_webhook(
    db: Session,
    event_id: str,
    payment_id: str,
    new_status: PaymentStatus,
):
    # ========================================================
    # 1. Check webhook event idempotency
    # ========================================================

    existing_event = (
        db.query(WebhookEventDB)
        .filter(
            WebhookEventDB.event_id == event_id
        )
        .first()
    )

    if existing_event is not None:

        try:
            create_audit_log(
                db=db,
                event_type="DUPLICATE_WEBHOOK_IGNORED",
                component="WEBHOOK_SERVICE",
                message=(
                    "A duplicate webhook event was safely ignored."
                ),
                entity_type="PAYMENT",
                entity_id=payment_id,
                reason_code="DUPLICATE_WEBHOOK_EVENT",
                details={
                    "event_id": event_id,
                    "requested_status": new_status.value,
                },
            )

            db.commit()

        except Exception:
            db.rollback()
            raise

        return {
            "success": True,
            "processed": False,
            "reason_code": "DUPLICATE_WEBHOOK_EVENT",
            "message": (
                "This webhook event has already been processed."
            ),
            "event_id": event_id,
        }

    # ========================================================
    # 2. Find payment
    # ========================================================

    payment = find_payment_by_id(
        db=db,
        payment_id=payment_id,
    )

    if payment is None:

        try:
            create_audit_log(
                db=db,
                event_type="WEBHOOK_REJECTED",
                component="WEBHOOK_SERVICE",
                message=(
                    "Webhook could not be processed because "
                    "the payment was not found."
                ),
                entity_type="PAYMENT",
                entity_id=payment_id,
                reason_code="PAYMENT_NOT_FOUND",
                details={
                    "event_id": event_id,
                    "requested_status": new_status.value,
                },
            )

            db.commit()

        except Exception:
            db.rollback()
            raise

        return {
            "success": False,
            "processed": False,
            "reason_code": "PAYMENT_NOT_FOUND",
            "message": (
                f"Payment '{payment_id}' was not found."
            ),
            "event_id": event_id,
        }

    # ========================================================
    # 3. Payment already has the webhook status
    # ========================================================

    if payment.status == new_status.value:

        try:
            webhook_event = WebhookEventDB(
                event_id=event_id,
                payment_id=payment_id,
                status=new_status.value,
                processed=True,
            )

            db.add(webhook_event)
            db.flush()

            create_audit_log(
                db=db,
                event_type="WEBHOOK_STATUS_ALREADY_APPLIED",
                component="WEBHOOK_SERVICE",
                message=(
                    "Webhook was received, but the payment "
                    "already had the requested status."
                ),
                entity_type="PAYMENT",
                entity_id=payment_id,
                reason_code="PAYMENT_STATUS_ALREADY_APPLIED",
                amount=payment.amount,
                details={
                    "event_id": event_id,
                    "status": new_status.value,
                },
            )

            db.commit()

        except Exception:
            db.rollback()
            raise

        return {
            "success": True,
            "processed": False,
            "reason_code": "PAYMENT_STATUS_ALREADY_APPLIED",
            "message": (
                "Payment already has this status."
            ),
            "event_id": event_id,
            "payment": payment_to_dict(payment),
        }

    # ========================================================
    # 4. Apply payment state change
    # ========================================================

    if payment.status == PaymentStatus.UNKNOWN.value:

        result = reconcile_payment(
            db=db,
            payment_id=payment_id,
            resolved_status=new_status,
            commit=False,
        )

    else:

        result = update_payment_status(
            db=db,
            payment_id=payment_id,
            new_status=new_status,
            commit=False,
        )

    # ========================================================
    # 5. Successful webhook processing
    # ========================================================

    if result["success"]:

        try:
            webhook_event = WebhookEventDB(
                event_id=event_id,
                payment_id=payment_id,
                status=new_status.value,
                processed=True,
            )

            db.add(webhook_event)
            db.flush()

            create_audit_log(
                db=db,
                event_type="WEBHOOK_APPLIED",
                component="WEBHOOK_SERVICE",
                message=(
                    "Webhook event was successfully applied "
                    "to the payment."
                ),
                entity_type="PAYMENT",
                entity_id=payment_id,
                reason_code="WEBHOOK_APPLIED",
                amount=payment.amount,
                details={
                    "event_id": event_id,
                    "new_status": new_status.value,
                },
            )

            db.commit()

        except Exception:
            db.rollback()
            raise

        return {
            "success": True,
            "processed": True,
            "event_id": event_id,
            "result": result,
        }

    # ========================================================
    # 6. State transition rejected
    # ========================================================

    try:
        create_audit_log(
            db=db,
            event_type="WEBHOOK_REJECTED",
            component="WEBHOOK_SERVICE",
            message=(
                "Webhook payment state transition was rejected."
            ),
            entity_type="PAYMENT",
            entity_id=payment_id,
            reason_code="INVALID_PAYMENT_TRANSITION",
            amount=payment.amount,
            details={
                "event_id": event_id,
                "current_status": payment.status,
                "requested_status": new_status.value,
            },
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return {
        "success": False,
        "processed": False,
        "event_id": event_id,
        "result": result,
    }