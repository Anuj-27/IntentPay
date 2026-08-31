from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.db.models import IntentDB
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.protocol import PROTOCOL_VERSION
from backend.app.services.audit_service import create_audit_log


def intent_to_dict(intent_record: IntentDB):
    intent = IntentMandate.model_validate(intent_record.mandate)

    return {
        "intent_id": intent_record.intent_id,
        "protocol_context": {
            "protocol_version": intent_record.protocol_version,
            "correlation_id": intent_record.correlation_id,
            "intent_id": intent_record.intent_id,
            "merchant_id": intent.merchant_id,
        },
        "status": "ACTIVE",
        "intent": intent_record.mandate,
        "selected_product_id": intent_record.selected_product_id,
        "selection_confirmed": intent_record.selection_confirmed,
        "created_at": intent_record.created_at,
        "updated_at": intent_record.updated_at,
    }


def create_intent_record(
    db: Session,
    intent: IntentMandate,
):
    intent_id = str(uuid4())
    correlation_id = str(uuid4())

    intent_record = IntentDB(
        intent_id=intent_id,
        correlation_id=correlation_id,
        protocol_version=PROTOCOL_VERSION,
        mandate=intent.model_dump(mode="json"),
        selection_confirmed=False,
    )

    try:
        db.add(intent_record)
        db.flush()
        create_audit_log(
            db=db,
            event_type="INTENT_CREATED",
            component="INTENT_SERVICE",
            message="A validated intent mandate was persisted.",
            entity_type="INTENT",
            entity_id=intent_record.intent_id,
            reason_code="INTENT_CREATED",
            amount=intent.max_budget,
            details={
                "protocol_version": PROTOCOL_VERSION,
                "correlation_id": correlation_id,
                "merchant_id": intent.merchant_id,
                "product_category": intent.product_category,
                "quantity": intent.quantity,
                "autonomous_selection_allowed": (
                    intent.autonomous_selection_allowed
                ),
            },
        )
        db.commit()
        db.refresh(intent_record)
    except Exception:
        db.rollback()
        raise

    return intent_record


def find_intent_by_id(
    db: Session,
    intent_id: str,
):
    return (
        db.query(IntentDB)
        .filter(IntentDB.intent_id == intent_id)
        .first()
    )


def confirm_product_selection(
    db: Session,
    intent_record: IntentDB,
    product_id: str,
):
    previous_product_id = intent_record.selected_product_id
    intent_record.selected_product_id = product_id
    intent_record.selection_confirmed = True

    try:
        db.flush()
        create_audit_log(
            db=db,
            event_type="PRODUCT_SELECTION_CONFIRMED",
            component="INTENT_SERVICE",
            message="The user-confirmed product selection was persisted.",
            entity_type="INTENT",
            entity_id=intent_record.intent_id,
            reason_code="PRODUCT_SELECTION_CONFIRMED",
            details={
                "protocol_version": intent_record.protocol_version,
                "correlation_id": intent_record.correlation_id,
                "previous_product_id": previous_product_id,
                "selected_product_id": product_id,
            },
        )
        db.commit()
        db.refresh(intent_record)
    except Exception:
        db.rollback()
        raise

    return intent_record


def mandate_from_record(intent_record: IntentDB) -> IntentMandate:
    return IntentMandate.model_validate(intent_record.mandate)
