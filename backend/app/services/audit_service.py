from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.db.models import AuditLogDB
from backend.app.schemas.buyer_agent import BuyerAgentResult
from backend.app.schemas.decision import DecisionType
from backend.app.services.privacy_service import redact_sensitive_data


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
        details=redact_sensitive_data(details),
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


def create_buyer_agent_audit_logs(
    db: Session,
    intent_id: str,
    correlation_id: str,
    protocol_version: str,
    buyer_result: BuyerAgentResult,
    verification_result: dict | None = None,
    policy_result: dict | None = None,
    final_decision: dict | None = None,
):
    proposed_purchase = buyer_result.proposed_purchase

    amount = (
        proposed_purchase.total_amount
        if proposed_purchase is not None
        else None
    )

    recommended_product_id = (
        buyer_result.recommended_product.product_id
        if buyer_result.recommended_product is not None
        else None
    )

    # --------------------------------------------------------
    # Record what the Buyer Agent decided
    # --------------------------------------------------------

    create_audit_log(
        db=db,
        event_type="BUYER_AGENT_DECISION",
        component="BUYER_AGENT",
        message=buyer_result.message,
        entity_type="INTENT",
        entity_id=intent_id,
        decision=buyer_result.decision.value,
        reason_code=buyer_result.reason_code,
        amount=amount,
        details={
            "protocol_version": protocol_version,
            "correlation_id": correlation_id,
            "merchant_id": buyer_result.merchant_id,
            "recommended_product_id": (
                recommended_product_id
            ),
            "proposed_product_id": (
                proposed_purchase.product_id
                if proposed_purchase is not None
                else None
            ),
            "allowed_product_count": len(
                buyer_result.ranked_products
            ),
            "rejected_product_count": len(
                buyer_result.rejected_products
            ),
            "stretch_candidate_count": len(
                buyer_result.stretch_candidates
            ),
            "proposal_created": (
                proposed_purchase is not None
            ),
        },
    )

    # No Trust Gate event exists when the Buyer Agent
    # did not create a ProposedPurchase.
    if final_decision is None:
        return

    final_decision_value = DecisionType(
        final_decision["decision"]
    ).value

    # --------------------------------------------------------
    # Record the Trust Gate preview decision
    # --------------------------------------------------------

    create_audit_log(
        db=db,
        event_type="TRUST_GATE_PREVIEW_DECISION",
        component="TRUST_GATE",
        message=final_decision["message"],
        entity_type="INTENT",
        entity_id=intent_id,
        decision=final_decision_value,
        reason_code=final_decision["reason_code"],
        amount=amount,
        details={
            "protocol_version": protocol_version,
            "correlation_id": correlation_id,
            "buyer_agent_decision": (
                buyer_result.decision.value
            ),
            "buyer_agent_reason_code": (
                buyer_result.reason_code
            ),
            "verified": (
                verification_result.get("verified")
                if verification_result is not None
                else None
            ),
            "expected_total": (
                verification_result.get("expected_total")
                if verification_result is not None
                else None
            ),
            "merchant_policy_status": (
                policy_result.get("status")
                if policy_result is not None
                else None
            ),
            "merchant_policy_reason": (
                policy_result.get("reason_code")
                if policy_result is not None
                else None
            ),
            "ready_for_payment": (
                final_decision_value
                == DecisionType.ALLOW.value
            ),
        },
    )
