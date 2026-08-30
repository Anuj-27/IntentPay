from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.db.models import AuditLogDB


def create_audit_log(
    db: Session,
    event_type: str,
    component: str,
    message: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    decision: str | None = None,
    reason_code: str | None = None,
    amount: int | None = None,
    details: dict | None = None,
):
    audit_log = AuditLogDB(
        audit_id=str(uuid4()),
        event_type=event_type,
        component=component,
        entity_type=entity_type,
        entity_id=entity_id,
        decision=decision,
        reason_code=reason_code,
        message=message,
        amount=amount,
        details=details,
    )

    db.add(audit_log)

    # Send SQL to PostgreSQL,
    # but DO NOT permanently commit yet.
    db.flush()

    return audit_log

def audit_log_to_dict(log):
    return {
        "audit_id": log.audit_id,
        "event_type": log.event_type,
        "component": log.component,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "decision": log.decision,
        "reason_code": log.reason_code,
        "message": log.message,
        "amount": log.amount,
        "details": log.details,
        "created_at": log.created_at,
    }