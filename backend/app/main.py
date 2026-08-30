from fastapi import FastAPI, Depends, HTTPException
from openai import OpenAIError
from sqlalchemy.orm import Session

from backend.app.db.database import get_db

from backend.app.schemas.ai_intent import (
    NaturalLanguageIntentRequest,
)

from backend.app.services.intent_extractor import (
    extract_intent_from_text,
)
from backend.app.services.llm_intent_extractor import (
    extract_intent_with_llm,
)

from backend.app.schemas.intent import IntentMandate, IntentSelectionRequest
from backend.app.schemas.purchase import PurchaseVerificationRequest
from backend.app.data.products import products


from backend.app.services.product_filter import filter_products
from backend.app.services.budget_stretch import find_budget_stretch_candidates
from backend.app.services.preference_engine import rank_products
from backend.app.services.tradeoff_engine import evaluate_tradeoff
from backend.app.services.intent_verifier import verify_purchase
from backend.app.services.decision_engine import make_decision
from backend.app.data.merchant_policies import merchant_policy
from backend.app.services.merchant_policy_engine import evaluate_merchant_policy
from backend.app.services.trust_gate import evaluate_trust_gate
from backend.app.schemas.decision import DecisionType
from backend.app.schemas.payment import (
    PaymentExecutionRequest,
    PaymentStatusUpdateRequest,
    PaymentReconciliationRequest,
    PaymentWebhookRequest
)
from backend.app.services.payment_service import (
    create_payment,
    update_payment_status,
    reconcile_payment
)
from backend.app.services.webhook_service import (
    process_payment_webhook
)
from backend.app.services.audit_service import (
    create_audit_log,
    audit_log_to_dict,
)
from backend.app.db.models import AuditLogDB
from backend.app.services.intent_service import (
    confirm_product_selection,
    create_intent_record,
    find_intent_by_id,
    intent_to_dict,
    mandate_from_record,
)



app = FastAPI(
    title="IntentPay API",
    version="0.1.0"
)


def get_intent_or_404(db: Session, intent_id: str):
    intent_record = find_intent_by_id(db, intent_id)
    if intent_record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "INTENT_NOT_FOUND",
                "message": f"Intent '{intent_id}' was not found.",
            },
        )
    return intent_record


def evaluate_purchase_request(intent_record, purchase):
    intent = mandate_from_record(intent_record)
    selected_product_id = (
        intent_record.selected_product_id
        if intent_record.selection_confirmed
        else None
    )
    verification_result = verify_purchase(
        intent,
        purchase,
        products,
        selected_product_id=selected_product_id,
    )
    intent_decision = make_decision(verification_result)
    policy_result = evaluate_merchant_policy(
        verification_result,
        merchant_policy,
    )
    final_decision = evaluate_trust_gate(
        intent_decision,
        policy_result,
    )
    return verification_result, intent_decision, policy_result, final_decision


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "IntentPay API"
    }


@app.post("/intents", status_code=201)
def create_intent(
    intent: IntentMandate,
    db: Session = Depends(get_db),
):
    intent_record = create_intent_record(db, intent)
    return intent_to_dict(intent_record)


@app.get("/intents/{intent_id}")
def get_intent(
    intent_id: str,
    db: Session = Depends(get_db),
):
    return intent_to_dict(get_intent_or_404(db, intent_id))


@app.post("/intents/{intent_id}/selection")
def select_intent_product(
    intent_id: str,
    request: IntentSelectionRequest,
    db: Session = Depends(get_db),
):
    intent_record = get_intent_or_404(db, intent_id)
    intent = mandate_from_record(intent_record)
    product = next(
        (
            catalog_product
            for catalog_product in products
            if catalog_product.product_id == request.product_id
        ),
        None,
    )

    if product is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "PRODUCT_NOT_FOUND",
                "message": f"Product '{request.product_id}' was not found.",
            },
        )

    allowed_products, rejected_products = filter_products(intent, [product])
    if not allowed_products:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "PRODUCT_SELECTION_NOT_ALLOWED",
                "message": "The selected product does not satisfy the intent.",
                "violations": rejected_products[0]["reasons"],
            },
        )

    updated_record = confirm_product_selection(
        db,
        intent_record,
        request.product_id,
    )
    return intent_to_dict(updated_record)


@app.get("/products")
def get_products():
    return {
        "count": len(products),
        "products": products
    }


@app.post("/products/filter")
def get_allowed_products(intent: IntentMandate):
    allowed_products, rejected_products = filter_products(
        intent,
        products
    )

    ranked_products = rank_products(
        intent,
        allowed_products
    )

    tradeoff_decision = evaluate_tradeoff(
        intent,
        ranked_products
    )

    stretch_candidates = find_budget_stretch_candidates(
        intent,
        allowed_products,
        rejected_products
    )

    return {
        "allowed_count": len(allowed_products),
        "rejected_count": len(rejected_products),
        "allowed_products": allowed_products,
        "ranked_products": ranked_products,
        "rejected_products": rejected_products,
        "stretch_candidates": stretch_candidates,
        "tradeoff_decision": tradeoff_decision
    }


@app.post("/verify-purchase")
def verify_proposed_purchase(
    request: PurchaseVerificationRequest,
    db: Session = Depends(get_db),
):
    intent_record = get_intent_or_404(db, request.intent_id)
    (
        verification_result,
        decision_result,
        policy_result,
        final_decision,
    ) = evaluate_purchase_request(
        intent_record,
        request.purchase,
    )

    return {
        "intent_id": request.intent_id,
        "verification": verification_result,
        "intent_decision": decision_result,
        "merchant_policy": policy_result,
        "final_decision": final_decision
    }

@app.post("/payments/create")
def create_verified_payment(
    request: PaymentExecutionRequest,
    db: Session = Depends(get_db)
):
    intent_record = get_intent_or_404(db, request.intent_id)
    (
        verification_result,
        intent_decision,
        policy_result,
        final_decision,
    ) = evaluate_purchase_request(
        intent_record,
        request.purchase,
    )
    try:
        create_audit_log(
            db=db,
            event_type="TRUST_GATE_DECISION",
            component="TRUST_GATE",
            message=final_decision["message"],
            entity_type="INTENT",
            entity_id=request.intent_id,
            decision=final_decision["decision"],
            reason_code=final_decision["reason_code"],
            amount=verification_result.get("expected_total"),
            details={
                "product_id": request.purchase.product_id,

                "idempotency_key": request.idempotency_key,

                "requested_quantity": request.purchase.quantity,

                "requested_unit_price": request.purchase.unit_price,

                "requested_total_amount": request.purchase.total_amount,

                "verified": verification_result["verified"],

                "intent_decision": intent_decision["decision"],

                "intent_decision_reason": intent_decision["reason_code"],

                "merchant_policy_status": policy_result.get("status"),

                "merchant_policy_reason": policy_result.get("reason_code"),

                "verification_violations": verification_result.get(
                    "violations",
                    []
                ),
            },
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    if final_decision["decision"] != DecisionType.ALLOW:
        return {
            "payment_created": False,
            "final_decision": final_decision,
            "message": (
                "Payment was not created because "
                "the Trust Gate did not return ALLOW."
            )
        }

    trusted_amount =  verification_result[
        "expected_total"
    ]

    payment_result = create_payment(
        db=db,
        intent_id=request.intent_id,
        product_id=request.purchase.product_id,
        amount=trusted_amount,
        idempotency_key=request.idempotency_key
    )

    return {
        "payment_created": payment_result["created"],
        "final_decision": final_decision,
        "payment_result": payment_result
    }

@app.patch("/payments/{payment_id}/status")
def change_payment_status(
    payment_id: str,
    request: PaymentStatusUpdateRequest,
    db: Session = Depends(get_db),
):
    return update_payment_status(
        db=db,
        payment_id=payment_id,
        new_status=request.new_status,
    )

@app.post("/payments/{payment_id}/reconcile")
def reconcile_payment_endpoint(
    payment_id: str,
    request: PaymentReconciliationRequest,
    db: Session = Depends(get_db),
):
    return reconcile_payment(
        db=db,
        payment_id=payment_id,
        resolved_status=request.resolved_status,
    )

@app.post("/webhooks/payment")
def payment_webhook(
    request: PaymentWebhookRequest,
    db: Session = Depends(get_db),
):
    return process_payment_webhook(
        db=db,
        event_id=request.event_id,
        payment_id=request.payment_id,
        new_status=request.status,
    )

@app.get("/audit")
def get_audit_logs(
    db: Session = Depends(get_db),
):
    logs = (
        db.query(AuditLogDB)
        .order_by(
            AuditLogDB.created_at.desc()
        )
        .all()
    )

    return {
        "count": len(logs),
        "logs": [
            audit_log_to_dict(log)
            for log in logs
        ],
    }


@app.get("/audit/{entity_id}")
def get_entity_audit_logs(
    entity_id: str,
    db: Session = Depends(get_db),
):
    logs = (
        db.query(AuditLogDB)
        .filter(
            AuditLogDB.entity_id == entity_id
        )
        .order_by(
            AuditLogDB.created_at.asc()
        )
        .all()
    )

    return {
        "entity_id": entity_id,
        "count": len(logs),
        "logs": [
            audit_log_to_dict(log)
            for log in logs
        ],
    }

@app.post("/intents/parse")
def parse_natural_language_intent(
    request: NaturalLanguageIntentRequest
):
    try:
        intent = extract_intent_from_text(
            request.message
        )

        return {
            "status": "PARSED",
            "source": "DETERMINISTIC_PARSER",
            "original_message": request.message,
            "intent": intent,
        }

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "INTENT_EXTRACTION_FAILED",
                "message": str(error),
            },
        )


@app.post("/intents/parse/llm")
def parse_natural_language_intent_with_llm(
    request: NaturalLanguageIntentRequest,
):
    try:
        intent = extract_intent_with_llm(request.message)
        return {
            "status": "PARSED",
            "source": "OPENAI_STRUCTURED_OUTPUT",
            "original_message": request.message,
            "intent": intent,
        }
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "INTENT_EXTRACTION_FAILED",
                "message": str(error),
            },
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LLM_NOT_CONFIGURED",
                "message": str(error),
            },
        ) from error
    except OpenAIError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "reason_code": "LLM_PROVIDER_ERROR",
                "message": "The intent model request failed.",
            },
        ) from error
