from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.models import MerchantApprovalDB
from backend.app.schemas.decision import DecisionType
from backend.app.services.audit_service import create_audit_log


APPROVAL_TTL = timedelta(minutes=30)
ACTIVE_APPROVAL_STATUSES = ("PENDING", "APPROVED", "REJECTED", "EXPIRED")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _effective_status(record: MerchantApprovalDB, now: datetime | None = None) -> str:
    now = now or _utc_now()
    if record.status in {"PENDING", "APPROVED"} and _as_utc(record.expires_at) <= now:
        return "EXPIRED"
    return record.status


def merchant_approval_to_dict(record: MerchantApprovalDB) -> dict:
    return {
        "approval_id": record.approval_id,
        "intent_id": record.intent_id,
        "merchant_id": record.merchant_id,
        "product_id": record.product_id,
        "amount": record.amount,
        "status": _effective_status(record),
        "requested_reason_code": record.requested_reason_code,
        "requested_message": record.requested_message,
        "priority": record.priority,
        "reviewer_merchant_id": record.reviewer_merchant_id,
        "decision_reason": record.decision_reason,
        "expires_at": record.expires_at,
        "created_at": record.created_at,
        "decided_at": record.decided_at,
    }


def find_merchant_approval(
    db: Session,
    approval_id: str,
) -> MerchantApprovalDB | None:
    return (
        db.query(MerchantApprovalDB)
        .filter(MerchantApprovalDB.approval_id == approval_id)
        .first()
    )


def find_latest_matching_approval(
    db: Session,
    *,
    intent_id: str,
    merchant_id: str,
    product_id: str,
    amount: int,
) -> MerchantApprovalDB | None:
    return (
        db.query(MerchantApprovalDB)
        .filter(
            MerchantApprovalDB.intent_id == intent_id,
            MerchantApprovalDB.merchant_id == merchant_id,
            MerchantApprovalDB.product_id == product_id,
            MerchantApprovalDB.amount == amount,
            MerchantApprovalDB.status.in_(ACTIVE_APPROVAL_STATUSES),
        )
        .order_by(MerchantApprovalDB.created_at.desc())
        .first()
    )


def list_merchant_approvals(
    db: Session,
    merchant_id: str,
    *,
    pending_only: bool = True,
) -> list[dict]:
    query = db.query(MerchantApprovalDB).filter(
        MerchantApprovalDB.merchant_id == merchant_id
    )
    if pending_only:
        query = query.filter(MerchantApprovalDB.status == "PENDING")

    records = query.order_by(MerchantApprovalDB.created_at.desc()).all()
    approvals = []
    for record in records:
        approval = merchant_approval_to_dict(record)
        if pending_only and approval["status"] != "PENDING":
            continue
        approvals.append(approval)
    return approvals


def create_merchant_approval_request(
    db: Session,
    *,
    intent_id: str,
    merchant_id: str,
    product_id: str,
    amount: int,
    reason_code: str,
    message: str,
    priority: str = "NORMAL",
) -> tuple[MerchantApprovalDB, bool]:
    """Create an escalation request, or return the active duplicate.

    The boolean is true when an existing pending request was reused. This
    makes repeated browser/API retries safe without creating review spam.
    """

    existing = find_latest_matching_approval(
        db,
        intent_id=intent_id,
        merchant_id=merchant_id,
        product_id=product_id,
        amount=amount,
    )
    if existing is not None:
        effective_status = _effective_status(existing)
        if effective_status in {"PENDING", "APPROVED"}:
            return existing, True

    now = _utc_now()
    record = MerchantApprovalDB(
        approval_id=str(uuid4()),
        intent_id=intent_id,
        merchant_id=merchant_id,
        product_id=product_id,
        amount=amount,
        status="PENDING",
        requested_reason_code=reason_code,
        requested_message=message,
        priority=priority,
        expires_at=now + APPROVAL_TTL,
    )
    db.add(record)
    try:
        # Flushing (not just adding) sends the INSERT now, inside this
        # transaction, so the database's partial unique index -- the real
        # concurrency guard -- can reject it immediately if a concurrent
        # request already committed a PENDING row for this exact intent/
        # product/amount. The `find_latest_matching_approval` check above
        # only prevents duplicates when requests don't race; this catches
        # the case where they do.
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = find_latest_matching_approval(
            db,
            intent_id=intent_id,
            merchant_id=merchant_id,
            product_id=product_id,
            amount=amount,
        )
        if winner is not None:
            return winner, True
        raise

    create_audit_log(
        db=db,
        event_type="MERCHANT_APPROVAL_REQUESTED",
        component="MERCHANT_APPROVAL",
        message="Merchant human approval was requested for an escalated purchase.",
        entity_type="INTENT",
        entity_id=intent_id,
        decision=DecisionType.ESCALATE.value,
        reason_code="MERCHANT_HUMAN_APPROVAL_REQUIRED",
        amount=amount,
        details={
            "approval_id": record.approval_id,
            "merchant_id": merchant_id,
            "product_id": product_id,
            "expires_at": record.expires_at.isoformat(),
        },
    )
    db.commit()
    db.refresh(record)
    return record, False


def decide_merchant_approval(
    db: Session,
    *,
    approval_id: str,
    reviewer_merchant_id: str,
    decision: str,
    reason: str | None,
) -> MerchantApprovalDB:
    record = (
        db.query(MerchantApprovalDB)
        .filter(MerchantApprovalDB.approval_id == approval_id)
        .with_for_update()
        .first()
    )
    if record is None:
        raise ValueError("Merchant approval request was not found.")
    if record.merchant_id != reviewer_merchant_id:
        raise PermissionError("This approval belongs to another merchant.")

    status = _effective_status(record)
    if status != "PENDING":
        raise ValueError(
            f"Merchant approval is no longer pending (status: {status})."
        )

    now = _utc_now()
    approved = decision == "APPROVE"
    record.status = "APPROVED" if approved else "REJECTED"
    record.reviewer_merchant_id = reviewer_merchant_id
    record.decision_reason = reason
    record.decided_at = now

    create_audit_log(
        db=db,
        event_type="MERCHANT_APPROVAL_DECISION",
        component="MERCHANT_APPROVAL",
        message=(
            "Merchant approved the escalated purchase."
            if approved
            else "Merchant rejected the escalated purchase."
        ),
        entity_type="INTENT",
        entity_id=record.intent_id,
        decision=(
            DecisionType.ALLOW.value
            if approved
            else DecisionType.BLOCK.value
        ),
        reason_code=(
            "MERCHANT_APPROVAL_GRANTED"
            if approved
            else "MERCHANT_APPROVAL_REJECTED"
        ),
        amount=record.amount,
        details={
            "approval_id": record.approval_id,
            "merchant_id": record.merchant_id,
            "reviewer_merchant_id": reviewer_merchant_id,
            "decision": decision,
            "decision_reason": reason,
            "product_id": record.product_id,
        },
    )
    db.commit()
    db.refresh(record)
    return record
