import os
from typing import Annotated
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from sqlalchemy.exc import IntegrityError
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

from backend.app.schemas.intent import (
    DEFAULT_MERCHANT_ID,
    IntentMandate,
    IntentSelectionRequest,
)
from backend.app.schemas.buyer_agent import (
    BuyerAgentEvaluationResult,
    BuyerAgentResult,
)
from backend.app.schemas.merchant import (
    MerchantCapabilities,
    MerchantCatalog,
    MerchantContract,
)
from backend.app.schemas.purchase import PurchaseVerificationRequest
from backend.app.schemas.protocol import (
    CommerceContext,
    PaymentExecutionBoundaryResponse,
    ProtocolManifest,
)
from backend.app.schemas.demo import DemoScenarioList, DemoScenarioRun
from backend.app.schemas.evaluation import (
    EvaluationDatasetResponse,
    EvaluationReport,
)
from backend.app.schemas.orchestration import EndToEndOrchestrationResult
from backend.app.schemas.safety import SafetyManifest
from backend.app.schemas.razorpay import (
    RazorpayCheckoutVerificationRequest,
    RazorpayCheckoutVerificationResponse,
    RazorpayConfigurationStatus,
    RazorpayPaymentExecutionResponse,
    RazorpayReconciliationResponse,
    RazorpayWebhookResponse,
)
from backend.app.schemas.visual_intent import (
    VisualAnalyzerConfiguration,
    VisualIntentAnalysisResponse,
    VisualIntentConfirmationRequest,
    VisualIntentConfirmationResponse,
    VisualIntentRequest,
)
from backend.app.schemas.chat import (
    ProductAssistantChatRequest,
    ProductAssistantChatResponse,
)
from backend.app.schemas.merchant_approval import (
    MerchantApproval,
    MerchantApprovalDecisionResponse,
    MerchantApprovalListResponse,
    MerchantApprovalReviewRequest,
)


from backend.app.services.product_filter import filter_products
from backend.app.services.buyer_agent import run_buyer_agent
from backend.app.services.budget_stretch import find_budget_stretch_candidates
from backend.app.services.preference_engine import rank_products
from backend.app.services.tradeoff_engine import evaluate_tradeoff
from backend.app.services.intent_verifier import verify_purchase
from backend.app.services.decision_engine import make_decision
from backend.app.services.merchant_policy_engine import evaluate_merchant_policy
from backend.app.services.merchant_usage_service import (
    get_today_usage,
    record_autonomous_transaction,
)
from backend.app.services.merchant_service import (
    check_merchant_access,
    find_catalog_product,
    find_merchant_contract,
    list_merchant_contracts,
    list_merchant_dashboard_products,
    merchant_id_is_taken,
    register_merchant_profile,
    set_merchant_product_active_state,
    upsert_merchant_product,
)
from backend.app.services.merchant_auth_service import (
    authenticate_merchant,
    clear_session_cookie,
    create_merchant_credential,
    create_password_reset_token,
    require_active_merchant,
    reset_password_with_token,
    set_session_cookie,
)
from backend.app.services.merchant_approval_service import (
    create_merchant_approval_request,
    decide_merchant_approval,
    find_latest_matching_approval,
    find_merchant_approval,
    list_merchant_approvals,
    merchant_approval_to_dict,
)
from backend.app.services.security_service import (
    PASSWORD_RESET_TTL_SECONDS,
    validate_security_configuration,
)
from backend.app.schemas.merchant_auth import (
    MerchantCatalogEntry,
    MerchantDashboardCatalog,
    MerchantForgotPasswordRequest,
    MerchantForgotPasswordResponse,
    MerchantLoginRequest,
    MerchantRegisterRequest,
    MerchantResetPasswordRequest,
    MerchantResetPasswordResponse,
    MerchantSessionInfo,
)
from backend.app.schemas.product import Product
from backend.app.data.categories import CATEGORIES, canonicalize_category
from backend.app.services.trust_gate import evaluate_trust_gate
from backend.app.services.protocol_service import (
    build_commerce_context,
    build_internal_provider_result,
    build_protocol_manifest,
    build_provider_payment_command,
    verify_provider_result,
)
from backend.app.data.demo_scenarios import demo_scenarios
from backend.app.data.evaluation_cases import (
    DATASET_NAME,
    DATASET_VERSION,
    evaluation_cases,
)
from backend.app.services.demo_service import DEMO_MODE, run_demo_scenario
from backend.app.services.evaluation_service import run_evaluation_suite
from backend.app.services.orchestration_service import (
    build_stage_trace,
    evaluate_intent_pipeline,
    next_action_for_evaluation,
)
from backend.app.services.safety_service import build_safety_manifest
from backend.app.services.razorpay_adapter import (
    RazorpayTestClient,
    RazorpayTestCredentials,
    get_razorpay_configuration_status,
)
from backend.app.services.razorpay_service import (
    execute_razorpay_test_order,
    process_razorpay_webhook,
    reconcile_razorpay_payment,
    verify_razorpay_checkout_response,
)
from backend.app.services.visual_intent_service import (
    build_visual_analysis,
    get_configured_visual_analyzer,
    get_visual_analyzer_configuration,
)
from backend.app.services.chat_service import build_product_assistant_chat
from backend.app.services.openai_error_service import describe_openai_error
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
    audit_log_to_dict,
    create_audit_log,
    create_buyer_agent_audit_logs,
)
from backend.app.db.models import AuditLogDB, MerchantProfileDB
from backend.app.schemas.merchant_policy import (
    MerchantPolicy,
    MerchantPolicySettingsUpdate,
)
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

# Keep local Test Mode frictionless, but fail at startup rather than waiting
# for the first merchant login when a staging/production deployment is missing
# its signing secret.
validate_security_configuration()

FRONTEND_DIRECTORY = Path(__file__).resolve().parents[2] / "frontend"
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIRECTORY),
    name="frontend-assets",
)


@app.get("/", include_in_schema=False)
def get_demo_interface():
    return FileResponse(FRONTEND_DIRECTORY / "index.html")


@app.get("/chat", include_in_schema=False)
def get_chat_interface():
    return FileResponse(FRONTEND_DIRECTORY / "chat.html")


@app.get("/catalog", include_in_schema=False)
def get_catalog_browser_interface():
    return FileResponse(FRONTEND_DIRECTORY / "catalog.html")


@app.get("/merchant", include_in_schema=False)
def get_merchant_login_interface():
    return FileResponse(FRONTEND_DIRECTORY / "merchant-login.html")


@app.get("/merchant/dashboard", include_in_schema=False)
def get_merchant_dashboard_interface():
    return FileResponse(FRONTEND_DIRECTORY / "merchant-dashboard.html")


@app.middleware("http")
async def add_safe_response_headers(request: Request, call_next):
    # Browser-based merchant mutations must originate from this application.
    # CLI clients and the local demo may omit Origin; secure deployments must
    # send either Origin or Referer so a cross-site form cannot reuse a
    # merchant's session cookie.
    merchant_mutation = (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and (
            request.url.path.startswith("/merchant/catalog")
            or request.url.path == "/merchant/session/logout"
        )
    )
    if merchant_mutation:
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        configured_origin = os.getenv("APP_ORIGIN", "").strip()
        expected_origin = configured_origin or (
            f"{request.url.scheme}://{request.headers.get('host', '')}"
        )

        def origin_only(value: str) -> str:
            parsed = urlsplit(value)
            return (
                f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
                if parsed.scheme and parsed.netloc
                else ""
            )

        expected_origin = origin_only(expected_origin)
        supplied_origin = origin_only(origin or referer or "")
        if origin and origin_only(origin) != expected_origin:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": {
                        "reason_code": "CROSS_ORIGIN_MUTATION",
                        "message": "Merchant catalog changes must come from the IntentPay application.",
                    }
                },
            )
        if not origin and referer and supplied_origin != expected_origin:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": {
                        "reason_code": "CROSS_ORIGIN_MUTATION",
                        "message": "Merchant catalog changes must come from the IntentPay application.",
                    }
                },
            )
        if not origin and not referer and os.getenv("APP_ENV", "development").strip().casefold() in {"production", "prod", "staging"}:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": {
                        "reason_code": "ORIGIN_REQUIRED",
                        "message": "A same-origin request header is required for merchant catalog changes.",
                    }
                },
            )

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def get_razorpay_test_client() -> RazorpayTestClient | None:
    try:
        credentials = RazorpayTestCredentials.from_environment()
    except ValueError:
        return None
    return RazorpayTestClient(credentials)


def require_razorpay_test_client(
    client: RazorpayTestClient | None,
) -> RazorpayTestClient:
    if client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "RAZORPAY_TEST_NOT_CONFIGURED",
                "message": get_razorpay_configuration_status().message,
            },
        )
    return client


def get_visual_intent_analyzer():
    return get_configured_visual_analyzer()


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


def get_merchant_or_404(
    merchant_id: str,
    db: Session | None = None,
    apply_overlay: bool = True,
) -> MerchantContract:
    merchant_contract = find_merchant_contract(
        merchant_id, db=db, apply_overlay=apply_overlay
    )

    if merchant_contract is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "MERCHANT_NOT_FOUND",
                "message": f"Merchant '{merchant_id}' was not found.",
            },
        )

    return merchant_contract


def require_merchant_access(
    merchant_contract: MerchantContract,
    required_capabilities=(),
):
    access_result = check_merchant_access(
        merchant_contract,
        required_capabilities=required_capabilities,
    )

    if not access_result["available"]:
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": access_result["reason_code"],
                "message": access_result["message"],
            },
        )


def evaluate_purchase_request(
    intent_record,
    purchase,
    db: Session | None = None,
    merchant_approval: dict | None = None,
):
    intent = mandate_from_record(intent_record)
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)
    merchant_access_result = check_merchant_access(
        merchant_contract,
        required_capabilities=(
            "inventory_check",
            "checkout",
        ),
    )
    selected_product_id = (
        intent_record.selected_product_id
        if intent_record.selection_confirmed
        else None
    )
    verification_result = verify_purchase(
        intent,
        purchase,
        merchant_contract.catalog.products,
        selected_product_id=selected_product_id,
    )
    intent_decision = make_decision(verification_result)
    autonomous_usage_today = (
        get_today_usage(db, merchant_contract.merchant.merchant_id)
        if db is not None
        else (0, 0)
    )
    policy_result = evaluate_merchant_policy(
        verification_result,
        merchant_contract.merchant.policy,
        merchant_access_result=merchant_access_result,
        autonomous_usage_today=autonomous_usage_today,
    )
    if (
        merchant_approval is None
        and db is not None
        and verification_result["verified"]
        and verification_result.get("expected_total") is not None
    ):
        # Must see the approval regardless of its status -- a REJECTED or
        # EXPIRED approval is exactly what tells the Trust Gate to return
        # BLOCK instead of re-escalating a purchase the merchant already
        # turned down. Filtering to APPROVED-only here (the earlier bug)
        # made a rejected purchase look identical to one nobody had
        # reviewed yet.
        approval_record = find_latest_matching_approval(
            db,
            intent_id=intent_record.intent_id,
            merchant_id=intent.merchant_id,
            product_id=purchase.product_id,
            amount=verification_result["expected_total"],
        )
        if approval_record is not None:
            merchant_approval = merchant_approval_to_dict(approval_record)
    final_decision = evaluate_trust_gate(
        intent_decision,
        policy_result,
        merchant_approval=merchant_approval,
    )
    return verification_result, intent_decision, policy_result, final_decision


def persist_buyer_agent_audit_logs(
    db: Session,
    intent_record,
    buyer_result: BuyerAgentResult,
    verification_result: dict | None = None,
    policy_result: dict | None = None,
    final_decision: dict | None = None,
    intent: IntentMandate | None = None,
    merchant_contract: MerchantContract | None = None,
):
    try:
        create_buyer_agent_audit_logs(
            db=db,
            intent_id=intent_record.intent_id,
            correlation_id=intent_record.correlation_id,
            protocol_version=intent_record.protocol_version,
            buyer_result=buyer_result,
            verification_result=verification_result,
            policy_result=policy_result,
            final_decision=final_decision,
            user_authorized_amount=(
                intent.max_budget if intent is not None else None
            ),
            autonomous_transaction_limit=(
                merchant_contract.merchant.policy.autonomous_transaction_limit
                if merchant_contract is not None
                else None
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def evaluate_persisted_intent(
    intent_record,
    merchant_contract: MerchantContract,
    db: Session,
):
    """Evaluate an intent and apply only its exact current approval.

    The first pass determines whether merchant human review is required. If
    so, a matching approval may be supplied to a second full evaluation. A
    matching rejected or expired approval is also applied, so a rejection
    cannot silently turn back into an escalation on the next request.
    """

    intent = mandate_from_record(intent_record)
    confirmed_product_id = (
        intent_record.selected_product_id
        if intent_record.selection_confirmed
        else None
    )
    evaluation = evaluate_intent_pipeline(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=confirmed_product_id,
        db=db,
    )

    proposed_purchase = evaluation.buyer_agent.proposed_purchase
    expected_total = (
        evaluation.verification.expected_total
        if evaluation.verification is not None
        else None
    )
    if (
        evaluation.final_decision.decision == DecisionType.ESCALATE
        and proposed_purchase is not None
        and expected_total is not None
    ):
        approval = find_latest_matching_approval(
            db,
            intent_id=intent_record.intent_id,
            merchant_id=intent.merchant_id,
            product_id=proposed_purchase.product_id,
            amount=expected_total,
        )
        if approval is not None:
            evaluation = evaluate_intent_pipeline(
                intent=intent,
                merchant_contract=merchant_contract,
                confirmed_product_id=confirmed_product_id,
                merchant_approval=merchant_approval_to_dict(approval),
                db=db,
            )

    return evaluation


@app.post(
    "/intents/{intent_id}/merchant-approval",
    response_model=MerchantApproval,
    status_code=201,
)
def request_merchant_approval(
    intent_id: str,
    db: Session = Depends(get_db),
):
    """Create a review request only when the current Trust Gate escalates."""

    intent_record = get_intent_or_404(db, intent_id)
    intent = mandate_from_record(intent_record)
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)
    confirmed_product_id = (
        intent_record.selected_product_id
        if intent_record.selection_confirmed
        else None
    )
    evaluation = evaluate_intent_pipeline(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=confirmed_product_id,
        db=db,
    )

    if evaluation.final_decision.decision != DecisionType.ESCALATE:
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "APPROVAL_NOT_REQUIRED",
                "message": (
                    "A merchant approval can be requested only when the "
                    "current Trust Gate decision is ESCALATE."
                ),
                "final_decision": evaluation.final_decision.model_dump(
                    mode="json"
                ),
            },
        )

    proposed_purchase = evaluation.buyer_agent.proposed_purchase
    expected_total = (
        evaluation.verification.expected_total
        if evaluation.verification is not None
        else None
    )
    if proposed_purchase is None or expected_total is None:
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "APPROVAL_PROPOSAL_MISSING",
                "message": "The escalated evaluation has no verified purchase proposal.",
            },
        )

    try:
        approval, _ = create_merchant_approval_request(
            db,
            intent_id=intent_record.intent_id,
            merchant_id=intent.merchant_id,
            product_id=proposed_purchase.product_id,
            amount=expected_total,
            reason_code=evaluation.final_decision.reason_code,
            message=evaluation.final_decision.message,
            priority=(
                "HIGH"
                if merchant_contract.merchant.policy.autonomous_transaction_limit is not None
                and expected_total > merchant_contract.merchant.policy.autonomous_transaction_limit * 2
                else "NORMAL"
            ),
        )
        persist_buyer_agent_audit_logs(
            db=db,
            intent_record=intent_record,
            buyer_result=evaluation.buyer_agent,
            verification_result=(
                evaluation.verification.model_dump()
                if evaluation.verification is not None
                else None
            ),
            policy_result=(
                evaluation.merchant_policy.model_dump()
                if evaluation.merchant_policy is not None
                else None
            ),
            final_decision=evaluation.final_decision.model_dump(),
            intent=intent,
            merchant_contract=merchant_contract,
        )
    except Exception:
        db.rollback()
        raise

    return merchant_approval_to_dict(approval)


@app.get(
    "/merchant/approvals",
    response_model=MerchantApprovalListResponse,
)
def get_merchant_approvals(
    include_resolved: bool = Query(default=False),
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    return MerchantApprovalListResponse(
        merchant_id=merchant_id,
        approvals=[
            MerchantApproval.model_validate(approval)
            for approval in list_merchant_approvals(
                db,
                merchant_id,
                pending_only=not include_resolved,
            )
        ],
    )


@app.get(
    "/merchant/approvals/{approval_id}",
    response_model=MerchantApproval,
)
def get_merchant_approval(
    approval_id: str,
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    approval = find_merchant_approval(db, approval_id)
    if approval is None or approval.merchant_id != merchant_id:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "MERCHANT_APPROVAL_NOT_FOUND",
                "message": "That approval request was not found.",
            },
        )
    return merchant_approval_to_dict(approval)


@app.post(
    "/merchant/approvals/{approval_id}/decision",
    response_model=MerchantApprovalDecisionResponse,
)
def decide_merchant_approval_request(
    approval_id: str,
    request: MerchantApprovalReviewRequest,
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    """Approve or reject, then re-run the complete Trust Gate pipeline."""

    approval = find_merchant_approval(db, approval_id)
    if approval is None or approval.merchant_id != merchant_id:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "MERCHANT_APPROVAL_NOT_FOUND",
                "message": "That approval request was not found.",
            },
        )

    intent_record = get_intent_or_404(db, approval.intent_id)
    intent = mandate_from_record(intent_record)
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)
    confirmed_product_id = (
        intent_record.selected_product_id
        if intent_record.selection_confirmed
        else None
    )
    current_evaluation = evaluate_intent_pipeline(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=confirmed_product_id,
        db=db,
    )
    current_purchase = current_evaluation.buyer_agent.proposed_purchase
    current_total = (
        current_evaluation.verification.expected_total
        if current_evaluation.verification is not None
        else None
    )

    if (
        current_evaluation.final_decision.decision != DecisionType.ESCALATE
        or current_purchase is None
        or current_total != approval.amount
        or current_purchase.product_id != approval.product_id
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "MERCHANT_APPROVAL_STALE",
                "message": (
                    "The purchase changed or no longer requires the same "
                    "merchant approval. Run a fresh evaluation."
                ),
                "final_decision": current_evaluation.final_decision.model_dump(
                    mode="json"
                ),
            },
        )

    try:
        approval = decide_merchant_approval(
            db,
            approval_id=approval_id,
            reviewer_merchant_id=merchant_id,
            decision=request.decision,
            reason=request.reason,
        )
    except PermissionError as error:
        db.rollback()
        raise HTTPException(
            status_code=403,
            detail={
                "reason_code": "MERCHANT_APPROVAL_FORBIDDEN",
                "message": str(error),
            },
        ) from error
    except ValueError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "MERCHANT_APPROVAL_NOT_PENDING",
                "message": str(error),
            },
        ) from error

    evaluation = evaluate_intent_pipeline(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=confirmed_product_id,
        merchant_approval=merchant_approval_to_dict(approval),
        db=db,
    )
    persist_buyer_agent_audit_logs(
        db=db,
        intent_record=intent_record,
        buyer_result=evaluation.buyer_agent,
        verification_result=(
            evaluation.verification.model_dump()
            if evaluation.verification is not None
            else None
        ),
        policy_result=(
            evaluation.merchant_policy.model_dump()
            if evaluation.merchant_policy is not None
            else None
        ),
        final_decision=evaluation.final_decision.model_dump(),
        intent=intent,
        merchant_contract=merchant_contract,
    )

    razorpay_test_request = None
    if (
        evaluation.final_decision.decision == DecisionType.ALLOW
        and evaluation.buyer_agent.proposed_purchase is not None
    ):
        razorpay_test_request = {
            "intent_id": intent_record.intent_id,
            "purchase": evaluation.buyer_agent.proposed_purchase.model_dump(
                mode="json"
            ),
            "idempotency_key": f"approval-{approval.approval_id}",
        }

    return MerchantApprovalDecisionResponse(
        approval=MerchantApproval.model_validate(
            merchant_approval_to_dict(approval)
        ),
        evaluation=evaluation,
        next_action=next_action_for_evaluation(evaluation),
        ready_for_payment=evaluation.ready_for_payment,
        razorpay_test_request=razorpay_test_request,
    )


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "IntentPay API"
    }


@app.get(
    "/protocol/manifest",
    response_model=ProtocolManifest,
)
def get_protocol_manifest():
    return build_protocol_manifest()


@app.get(
    "/safety/manifest",
    response_model=SafetyManifest,
)
def get_safety_manifest():
    return build_safety_manifest()


@app.get(
    "/payments/razorpay-test/configuration",
    response_model=RazorpayConfigurationStatus,
)
def get_razorpay_test_configuration():
    return get_razorpay_configuration_status()


@app.get(
    "/evaluations/cases",
    response_model=EvaluationDatasetResponse,
)
def get_evaluation_cases(
    limit: int = Query(default=20, ge=1, le=500),
):
    returned_cases = evaluation_cases[:limit]
    return {
        "dataset_name": DATASET_NAME,
        "dataset_version": DATASET_VERSION,
        "total_cases": len(evaluation_cases),
        "returned_cases": len(returned_cases),
        "cases": returned_cases,
    }


@app.post(
    "/evaluations/run",
    response_model=EvaluationReport,
)
def execute_evaluation_suite(
    include_case_results: bool = Query(default=False),
):
    return run_evaluation_suite(
        include_case_results=include_case_results,
    )


@app.get(
    "/demo/scenarios",
    response_model=DemoScenarioList,
)
def get_demo_scenarios():
    return {
        "mode": DEMO_MODE,
        "real_money_moved": False,
        "scenarios": demo_scenarios,
    }


@app.post(
    "/demo/scenarios/{scenario_id}/run",
    response_model=DemoScenarioRun,
)
def execute_demo_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
):
    try:
        return run_demo_scenario(db, scenario_id)
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "DEMO_SCENARIO_NOT_FOUND",
                "message": str(error),
            },
        ) from error


@app.get("/merchants")
def get_merchants(db: Session = Depends(get_db)):
    contracts = list_merchant_contracts(db=db)

    return {
        "count": len(contracts),
        "merchants": [
            contract.merchant
            for contract in contracts
        ],
    }


@app.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    contracts = list_merchant_contracts(db=db)
    return {
        "count": len(CATEGORIES),
        "categories": [
            {
                "category_id": category.category_id,
                "display_name": category.display_name,
                "aliases": category.aliases,
                "common_attributes": category.common_attributes,
                "merchant_ids": [
                    contract.merchant.merchant_id
                    for contract in contracts
                    if any(
                        product.category == category.category_id
                        for product in contract.catalog.products
                    )
                ],
            }
            for category in CATEGORIES
        ],
    }


@app.post(
    "/visual-intents/analyze",
    response_model=VisualIntentAnalysisResponse,
)
def analyze_visual_intent(
    request: VisualIntentRequest,
    analyzer=Depends(get_visual_intent_analyzer),
):
    try:
        return build_visual_analysis(request, analyzer)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "VISUAL_INTENT_INVALID",
                "message": str(error),
            },
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "VISUAL_MODEL_NOT_CONFIGURED",
                "message": str(error),
            },
        ) from error
    except OpenAIError as error:
        provider_error = describe_openai_error(
            error,
            default_reason_code="VISUAL_MODEL_PROVIDER_ERROR",
            default_message="The visual product model request failed.",
        )
        raise HTTPException(
            status_code=provider_error.http_status,
            detail={
                "reason_code": provider_error.reason_code,
                "message": provider_error.message,
            },
        ) from error


@app.post(
    "/assistant/chat",
    response_model=ProductAssistantChatResponse,
)
def product_assistant_chat(
    request: ProductAssistantChatRequest,
    db: Session = Depends(get_db),
):
    try:
        return build_product_assistant_chat(request, db)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "CHAT_REQUEST_INVALID",
                "message": str(error),
            },
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "CHAT_ANALYZER_UNAVAILABLE",
                "message": str(error),
            },
        ) from error


@app.get(
    "/visual-intents/configuration",
    response_model=VisualAnalyzerConfiguration,
)
def get_visual_configuration():
    return get_visual_analyzer_configuration()


@app.post(
    "/visual-intents/confirm",
    response_model=VisualIntentConfirmationResponse,
    status_code=201,
)
def confirm_visual_intent(
    request: VisualIntentConfirmationRequest,
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(request.merchant_id, db=db)
    require_merchant_access(
        merchant_contract,
        required_capabilities=("catalog_search", "inventory_check", "checkout"),
    )
    product = find_catalog_product(merchant_contract, request.product_id)
    if product is None or not product.in_stock:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "VERIFIED_PRODUCT_NOT_AVAILABLE",
                "message": "The confirmed product is not available in the merchant catalog.",
            },
        )

    verified_total = product.price * request.quantity
    if verified_total > request.max_budget:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "BUDGET_EXCEEDED",
                "message": (
                    f"The verified total is ₹{verified_total}, which exceeds "
                    f"the maximum budget of ₹{request.max_budget}."
                ),
            },
        )

    intent = IntentMandate(
        merchant_id=request.merchant_id,
        product_category=product.category,
        max_budget=request.max_budget,
        quantity=request.quantity,
        brand=product.brand,
        brand_preference="EXACT",
        subscription_allowed=False,
        autonomous_selection_allowed=False,
    )
    intent_record = create_intent_record(db, intent)
    intent_record = confirm_product_selection(
        db,
        intent_record,
        product.product_id,
    )
    evaluation = evaluate_intent_pipeline(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=product.product_id,
        db=db,
    )
    persist_buyer_agent_audit_logs(
        db=db,
        intent_record=intent_record,
        buyer_result=evaluation.buyer_agent,
        verification_result=(
            evaluation.verification.model_dump()
            if evaluation.verification is not None
            else None
        ),
        policy_result=(
            evaluation.merchant_policy.model_dump()
            if evaluation.merchant_policy is not None
            else None
        ),
        final_decision=evaluation.final_decision.model_dump(),
        intent=intent,
        merchant_contract=merchant_contract,
    )

    razorpay_test_request = None
    next_step = "Resolve the Trust Gate decision before payment."
    if (
        evaluation.final_decision.decision == DecisionType.ALLOW
        and evaluation.buyer_agent.proposed_purchase is not None
    ):
        razorpay_test_request = {
            "intent_id": intent_record.intent_id,
            "purchase": evaluation.buyer_agent.proposed_purchase.model_dump(mode="json"),
            "idempotency_key": f"visual-{intent_record.intent_id}",
        }
        next_step = (
            "Use the confirmation screen's Open Razorpay Checkout button. "
            "API clients may submit razorpay_test_request to POST "
            "/payments/razorpay-test/orders; the user must still complete "
            "Razorpay Checkout."
        )

    return {
        "intent_id": intent_record.intent_id,
        "intent": intent_to_dict(intent_record),
        "merchant_id": request.merchant_id,
        "product": product,
        "evaluation": evaluation.model_dump(mode="json"),
        "razorpay_test_request": razorpay_test_request,
        "next_step": next_step,
    }


@app.get(
    "/merchants/{merchant_id}",
    response_model=MerchantContract,
)
def get_merchant_contract(merchant_id: str, db: Session = Depends(get_db)):
    merchant_contract = get_merchant_or_404(merchant_id, db=db)
    require_merchant_access(
        merchant_contract,
        required_capabilities=(
            "catalog_search",
            "inventory_check",
        ),
    )
    return merchant_contract


@app.get(
    "/merchants/{merchant_id}/capabilities",
    response_model=MerchantCapabilities,
)
def get_merchant_capabilities(merchant_id: str, db: Session = Depends(get_db)):
    return get_merchant_or_404(merchant_id, db=db).merchant.capabilities


@app.get(
    "/merchants/{merchant_id}/catalog",
    response_model=MerchantCatalog,
)
def get_merchant_catalog(merchant_id: str, db: Session = Depends(get_db)):
    merchant_contract = get_merchant_or_404(merchant_id, db=db)
    require_merchant_access(
        merchant_contract,
        required_capabilities=(
            "catalog_search",
            "inventory_check",
        ),
    )
    return merchant_contract.catalog


@app.post(
    "/merchant/register",
    response_model=MerchantSessionInfo,
    status_code=201,
)
def register_merchant(
    request: MerchantRegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if merchant_id_is_taken(db, request.merchant_id):
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "MERCHANT_ID_TAKEN",
                "message": f"Merchant ID '{request.merchant_id}' is already registered.",
            },
        )

    # Profile and credential must be committed together. Otherwise a
    # duplicate/racing registration could leave an account with a profile but
    # no usable credential.
    try:
        register_merchant_profile(
            db,
            request.merchant_id,
            request.display_name,
            commit=False,
        )
        create_merchant_credential(
            db,
            request.merchant_id,
            request.password,
            commit=False,
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "MERCHANT_ID_TAKEN",
                "message": f"Merchant ID '{request.merchant_id}' is already registered.",
            },
        ) from error

    set_session_cookie(response, request.merchant_id)
    return MerchantSessionInfo(
        merchant_id=request.merchant_id,
        display_name=request.display_name,
    )


@app.post(
    "/merchant/session/login",
    response_model=MerchantSessionInfo,
)
def merchant_login(
    request: MerchantLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if not authenticate_merchant(db, request.merchant_id, request.password):
        raise HTTPException(
            status_code=401,
            detail={
                "reason_code": "MERCHANT_CREDENTIALS_INVALID",
                "message": "That merchant ID and password do not match.",
            },
        )

    merchant_contract = get_merchant_or_404(request.merchant_id, db=db)
    if not merchant_contract.merchant.active:
        raise HTTPException(
            status_code=403,
            detail={
                "reason_code": "MERCHANT_INACTIVE",
                "message": "This merchant is not active for agent commerce.",
            },
        )

    set_session_cookie(response, request.merchant_id)
    return MerchantSessionInfo(
        merchant_id=merchant_contract.merchant.merchant_id,
        display_name=merchant_contract.merchant.display_name,
    )


@app.post(
    "/merchant/password/forgot",
    response_model=MerchantForgotPasswordResponse,
)
def forgot_merchant_password(
    request: MerchantForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    token = create_password_reset_token(db, request.merchant_id)
    if token is None:
        return MerchantForgotPasswordResponse(
            message=(
                "If that merchant ID has an account, a password reset "
                "token has been generated."
            ),
        )

    return MerchantForgotPasswordResponse(
        message=(
            "Test Mode: IntentPay does not send email. Use this one-time "
            "reset token to set a new password before it expires."
        ),
        reset_token=token,
        expires_in_seconds=PASSWORD_RESET_TTL_SECONDS,
    )


@app.post(
    "/merchant/password/reset",
    response_model=MerchantResetPasswordResponse,
)
def reset_merchant_password(
    request: MerchantResetPasswordRequest,
    db: Session = Depends(get_db),
):
    success = reset_password_with_token(db, request.reset_token, request.new_password)
    if not success:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "RESET_TOKEN_INVALID",
                "message": (
                    "That reset token is invalid, already used, or expired. "
                    "Request a new one."
                ),
            },
        )
    return MerchantResetPasswordResponse(reset=True)


@app.post("/merchant/session/logout")
def merchant_logout(response: Response):
    clear_session_cookie(response)
    return {"logged_out": True}


@app.get(
    "/merchant/session",
    response_model=MerchantSessionInfo,
)
def get_merchant_session(
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(merchant_id, db=db)
    return MerchantSessionInfo(
        merchant_id=merchant_contract.merchant.merchant_id,
        display_name=merchant_contract.merchant.display_name,
    )


@app.get(
    "/merchant/policy",
    response_model=MerchantPolicy,
)
def get_merchant_policy(
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(merchant_id, db=db)
    return merchant_contract.merchant.policy


@app.patch(
    "/merchant/policy",
    response_model=MerchantPolicy,
)
def update_merchant_policy(
    update: MerchantPolicySettingsUpdate,
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    """Only self-registered merchants (MerchantProfileDB) can edit their
    own policy -- the three built-in demo merchants (MERCHANT-001/002/003)
    are fixed baseline configuration for the reproducible demo/benchmark
    scenarios, not live-editable accounts."""

    profile = (
        db.query(MerchantProfileDB)
        .filter(MerchantProfileDB.merchant_id == merchant_id)
        .first()
    )
    if profile is None:
        raise HTTPException(
            status_code=400,
            detail={
                "reason_code": "MERCHANT_POLICY_NOT_EDITABLE",
                "message": (
                    "This merchant's policy is fixed baseline demo "
                    "configuration and cannot be edited."
                ),
            },
        )

    if (
        profile.max_transaction_amount is not None
        and update.autonomous_transaction_limit > profile.max_transaction_amount
    ):
        # The same rule MerchantPolicy's own validator enforces on read --
        # checked here too so an invalid combination is rejected instead
        # of being written to the row and only failing the next time
        # anything tries to read this merchant's contract back out.
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "AUTONOMOUS_LIMIT_EXCEEDS_HARD_CEILING",
                "message": (
                    f"The autonomous transaction limit (₹{update.autonomous_transaction_limit}) "
                    f"cannot exceed this merchant's hard transaction limit "
                    f"(₹{profile.max_transaction_amount})."
                ),
            },
        )

    previous_limit = profile.autonomous_transaction_limit
    profile.autonomous_transaction_limit = update.autonomous_transaction_limit
    create_audit_log(
        db=db,
        event_type="MERCHANT_POLICY_UPDATED",
        component="MERCHANT_POLICY",
        message=(
            f"Autonomous transaction limit changed from "
            f"₹{previous_limit} to ₹{update.autonomous_transaction_limit}."
        ),
        entity_type="MERCHANT",
        entity_id=merchant_id,
        details={
            "previous_autonomous_transaction_limit": previous_limit,
            "new_autonomous_transaction_limit": update.autonomous_transaction_limit,
        },
    )
    db.commit()

    merchant_contract = get_merchant_or_404(merchant_id, db=db)
    return merchant_contract.merchant.policy


@app.get(
    "/merchant/catalog",
    response_model=MerchantDashboardCatalog,
)
def get_merchant_dashboard_catalog(
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(merchant_id, db=db, apply_overlay=False)
    entries = list_merchant_dashboard_products(merchant_contract, db)
    return MerchantDashboardCatalog(
        merchant_id=merchant_contract.merchant.merchant_id,
        display_name=merchant_contract.merchant.display_name,
        count=len(entries),
        products=[MerchantCatalogEntry(**entry) for entry in entries],
    )


@app.post(
    "/merchant/catalog/products",
    response_model=MerchantCatalogEntry,
    status_code=201,
)
def create_merchant_product(
    product: Product,
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(merchant_id, db=db, apply_overlay=False)
    override = upsert_merchant_product(db, merchant_contract, product)
    return MerchantCatalogEntry(
        product=product,
        is_custom=not any(
            p.product_id == product.product_id
            for p in merchant_contract.catalog.products
        ),
        is_active=override.is_active,
    )


@app.put(
    "/merchant/catalog/products/{product_id}",
    response_model=MerchantCatalogEntry,
)
def update_merchant_product(
    product_id: str,
    product: Product,
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    if product.product_id != product_id:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "PRODUCT_ID_MISMATCH",
                "message": "The product ID in the URL and body must match.",
            },
        )

    merchant_contract = get_merchant_or_404(merchant_id, db=db, apply_overlay=False)
    override = upsert_merchant_product(db, merchant_contract, product)
    return MerchantCatalogEntry(
        product=product,
        is_custom=not any(
            p.product_id == product.product_id
            for p in merchant_contract.catalog.products
        ),
        is_active=override.is_active,
    )


def _set_merchant_product_active(
    product_id: str,
    is_active: bool,
    merchant_id: str,
    db: Session,
) -> dict:
    merchant_contract = get_merchant_or_404(merchant_id, db=db, apply_overlay=False)
    override = set_merchant_product_active_state(
        db, merchant_contract, product_id, is_active
    )
    if override is None:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "PRODUCT_NOT_FOUND",
                "message": f"Product '{product_id}' was not found in your catalog.",
            },
        )
    return {"product_id": product_id, "is_active": override.is_active}


@app.post("/merchant/catalog/products/{product_id}/deactivate")
def deactivate_merchant_product(
    product_id: str,
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    return _set_merchant_product_active(product_id, False, merchant_id, db)


@app.post("/merchant/catalog/products/{product_id}/activate")
def activate_merchant_product(
    product_id: str,
    merchant_id: str = Depends(require_active_merchant),
    db: Session = Depends(get_db),
):
    return _set_merchant_product_active(product_id, True, merchant_id, db)


@app.post("/intents", status_code=201)
def create_intent(
    intent: IntentMandate,
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)
    require_merchant_access(
        merchant_contract,
        required_capabilities=(
            "catalog_search",
            "inventory_check",
        ),
    )
    intent_record = create_intent_record(db, intent)
    return intent_to_dict(intent_record)


@app.get("/intents/{intent_id}")
def get_intent(
    intent_id: str,
    db: Session = Depends(get_db),
):
    return intent_to_dict(get_intent_or_404(db, intent_id))


@app.get(
    "/intents/{intent_id}/protocol-context",
    response_model=CommerceContext,
)
def get_intent_protocol_context(
    intent_id: str,
    db: Session = Depends(get_db),
):
    intent_record = get_intent_or_404(db, intent_id)
    return build_commerce_context(intent_record)


@app.post("/intents/{intent_id}/selection")
def select_intent_product(
    intent_id: str,
    request: IntentSelectionRequest,
    db: Session = Depends(get_db),
):
    intent_record = get_intent_or_404(db, intent_id)
    intent = mandate_from_record(intent_record)
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)
    require_merchant_access(
        merchant_contract,
        required_capabilities=(
            "catalog_search",
            "inventory_check",
        ),
    )
    product = find_catalog_product(
        merchant_contract,
        request.product_id,
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
    return {
        **intent_to_dict(updated_record),
        # The canonical catalog product (image included) for the
        # confirmed selection, so the frontend can keep showing the same
        # product card without re-deriving it from the LLM or a client-
        # side index.
        "product": product,
    }


@app.get("/products")
def get_products(
    merchant_id: str = Query(default=DEFAULT_MERCHANT_ID),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(merchant_id, db=db)
    require_merchant_access(
        merchant_contract,
        required_capabilities=(
            "catalog_search",
            "inventory_check",
        ),
    )
    products = merchant_contract.catalog.products
    if category is not None:
        canonical_category = canonicalize_category(category)
        if canonical_category is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason_code": "CATEGORY_NOT_SUPPORTED",
                    "message": f"Category '{category}' is not supported.",
                },
            )
        products = [
            product
            for product in products
            if product.category == canonical_category
        ]

    return {
        "merchant_id": merchant_contract.merchant.merchant_id,
        "count": len(products),
        "products": products
    }


@app.post("/products/filter")
def get_allowed_products(
    intent: IntentMandate,
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)
    require_merchant_access(
        merchant_contract,
        required_capabilities=(
            "catalog_search",
            "inventory_check",
        ),
    )
    products = merchant_contract.catalog.products

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
    protocol_context = build_commerce_context(intent_record)
    (
        verification_result,
        decision_result,
        policy_result,
        final_decision,
    ) = evaluate_purchase_request(
        intent_record,
        request.purchase,
        db=db,
    )

    return {
        "intent_id": request.intent_id,
        "protocol_context": protocol_context,
        "verification": verification_result,
        "intent_decision": decision_result,
        "merchant_policy": policy_result,
        "final_decision": final_decision
    }

@app.post(
    "/payments/create",
    response_model=PaymentExecutionBoundaryResponse,
)
def create_verified_payment(
    request: PaymentExecutionRequest,
    db: Session = Depends(get_db)
):
    intent_record = get_intent_or_404(db, request.intent_id)
    protocol_context = build_commerce_context(intent_record)
    (
        verification_result,
        intent_decision,
        policy_result,
        final_decision,
    ) = evaluate_purchase_request(
        intent_record,
        request.purchase,
        db=db,
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
                "protocol_version": intent_record.protocol_version,

                "correlation_id": intent_record.correlation_id,

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
            "protocol_context": protocol_context,
            "final_decision": final_decision,
            "message": (
                "Payment was not created because "
                "the Trust Gate did not return ALLOW."
            )
        }

    trusted_amount =  verification_result[
        "expected_total"
    ]

    provider_command = build_provider_payment_command(
        intent_record=intent_record,
        purchase=request.purchase,
        idempotency_key=request.idempotency_key,
    )

    payment_result = create_payment(
        db=db,
        intent_id=request.intent_id,
        correlation_id=intent_record.correlation_id,
        protocol_version=intent_record.protocol_version,
        product_id=request.purchase.product_id,
        amount=trusted_amount,
        idempotency_key=request.idempotency_key
    )

    if not payment_result["success"]:
        return {
            "payment_created": False,
            "protocol_context": protocol_context,
            "final_decision": final_decision,
            "payment_command": provider_command,
            "payment_result": payment_result,
            "message": payment_result["message"],
        }

    provider_result = build_internal_provider_result(
        provider_command,
        payment_result,
    )
    provider_verification = verify_provider_result(
        provider_command,
        provider_result,
    )

    return {
        "payment_created": payment_result["created"],
        "protocol_context": protocol_context,
        "final_decision": final_decision,
        "payment_command": provider_command,
        "provider_result": provider_result,
        "provider_verification": provider_verification,
        "payment_result": payment_result,
    }


@app.post(
    "/payments/razorpay-test/orders",
    response_model=RazorpayPaymentExecutionResponse,
)
def create_razorpay_test_order(
    request: PaymentExecutionRequest,
    db: Session = Depends(get_db),
    razorpay_client=Depends(get_razorpay_test_client),
):
    intent_record = get_intent_or_404(db, request.intent_id)
    protocol_context = build_commerce_context(intent_record)
    (
        verification_result,
        intent_decision,
        policy_result,
        final_decision,
    ) = evaluate_purchase_request(intent_record, request.purchase, db=db)

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
                "protocol_version": intent_record.protocol_version,
                "correlation_id": intent_record.correlation_id,
                "provider": "RAZORPAY_TEST",
                "product_id": request.purchase.product_id,
                "idempotency_key": request.idempotency_key,
                "verified": verification_result["verified"],
                "intent_decision": intent_decision["decision"],
                "merchant_policy_status": policy_result.get("status"),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    if final_decision["decision"] != DecisionType.ALLOW:
        return {
            "payment_created": False,
            "protocol_context": protocol_context,
            "final_decision": final_decision,
            "reason_code": final_decision["reason_code"],
            "message": (
                "No Razorpay order was created because the Trust Gate did "
                "not return ALLOW."
            ),
        }

    client = require_razorpay_test_client(razorpay_client)
    execution = execute_razorpay_test_order(
        db=db,
        intent_record=intent_record,
        purchase=request.purchase,
        idempotency_key=request.idempotency_key,
        trusted_amount=verification_result["expected_total"],
        client=client,
    )
    # Count this against the merchant's daily autonomous caps exactly
    # once: `payment_created` is only True the first time this
    # idempotency key creates a new local payment record, never on a
    # retried/replayed request, so a retry can never inflate the count.
    if execution.get("payment_created"):
        record_autonomous_transaction(
            db,
            mandate_from_record(intent_record).merchant_id,
            verification_result["expected_total"],
        )
    return {
        "protocol_context": protocol_context,
        "final_decision": final_decision,
        **execution,
    }


@app.post(
    "/payments/{payment_id}/razorpay-test/verify-checkout",
    response_model=RazorpayCheckoutVerificationResponse,
)
def verify_razorpay_checkout(
    payment_id: str,
    request: RazorpayCheckoutVerificationRequest,
    db: Session = Depends(get_db),
    razorpay_client=Depends(get_razorpay_test_client),
):
    client = require_razorpay_test_client(razorpay_client)
    return verify_razorpay_checkout_response(
        db,
        payment_id,
        request,
        client,
    )


@app.post(
    "/payments/{payment_id}/razorpay-test/reconcile",
    response_model=RazorpayReconciliationResponse,
)
def reconcile_razorpay_test_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    razorpay_client=Depends(get_razorpay_test_client),
):
    client = require_razorpay_test_client(razorpay_client)
    return reconcile_razorpay_payment(
        db,
        payment_id,
        client,
    )

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


@app.post(
    "/webhooks/razorpay",
    response_model=RazorpayWebhookResponse,
)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Annotated[
        str,
        Header(alias="X-Razorpay-Signature"),
    ],
    x_razorpay_event_id: Annotated[
        str,
        Header(alias="X-Razorpay-Event-Id"),
    ],
    db: Session = Depends(get_db),
    razorpay_client=Depends(get_razorpay_test_client),
):
    client = require_razorpay_test_client(razorpay_client)
    raw_body = await request.body()
    result = process_razorpay_webhook(
        db=db,
        raw_body=raw_body,
        signature=x_razorpay_signature,
        event_id=x_razorpay_event_id,
        client=client,
    )

    if result.reason_code == "RAZORPAY_WEBHOOK_SIGNATURE_INVALID":
        raise HTTPException(
            status_code=401,
            detail=result.model_dump(mode="json"),
        )
    if result.reason_code == "RAZORPAY_WEBHOOK_PAYLOAD_INVALID":
        raise HTTPException(
            status_code=400,
            detail=result.model_dump(mode="json"),
        )
    if not result.success:
        raise HTTPException(
            status_code=409,
            detail=result.model_dump(mode="json"),
        )
    return result

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
        provider_error = describe_openai_error(
            error,
            default_reason_code="LLM_PROVIDER_ERROR",
            default_message="The intent model request failed.",
        )
        raise HTTPException(
            status_code=provider_error.http_status,
            detail={
                "reason_code": provider_error.reason_code,
                "message": provider_error.message,
            },
        ) from error


@app.post(
    "/intents/{intent_id}/buyer-agent",
    response_model=BuyerAgentResult,
)
def execute_buyer_agent(
    intent_id: str,
    db: Session = Depends(get_db),
):
    # --------------------------------------------------------
    # 1. Load the trusted persisted intent
    # --------------------------------------------------------

    intent_record = get_intent_or_404(
        db,
        intent_id,
    )

    intent = mandate_from_record(
        intent_record
    )
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)

    # --------------------------------------------------------
    # 2. Load user-confirmed selection when it exists
    # --------------------------------------------------------

    confirmed_product_id = (
        intent_record.selected_product_id
        if intent_record.selection_confirmed
        else None
    )

    # --------------------------------------------------------
    # 3. Run the Buyer Agent
    # --------------------------------------------------------

    buyer_result = run_buyer_agent(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=confirmed_product_id,
    )

    persist_buyer_agent_audit_logs(
        db=db,
        intent_record=intent_record,
        buyer_result=buyer_result,
        intent=intent,
        merchant_contract=merchant_contract,
    )

    return buyer_result


@app.post(
    "/intents/{intent_id}/buyer-agent/evaluate",
    response_model=BuyerAgentEvaluationResult,
)
def evaluate_buyer_agent_proposal(
    intent_id: str,
    db: Session = Depends(get_db),
):
    # --------------------------------------------------------
    # 1. Load the trusted persisted intent
    # --------------------------------------------------------

    intent_record = get_intent_or_404(
        db,
        intent_id,
    )

    intent = mandate_from_record(intent_record)
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)
    evaluation = evaluate_persisted_intent(
        intent_record,
        merchant_contract,
        db,
    )
    persist_buyer_agent_audit_logs(
        db=db,
        intent_record=intent_record,
        buyer_result=evaluation.buyer_agent,
        verification_result=(
            evaluation.verification.model_dump()
            if evaluation.verification is not None
            else None
        ),
        policy_result=(
            evaluation.merchant_policy.model_dump()
            if evaluation.merchant_policy is not None
            else None
        ),
        final_decision=(
            evaluation.final_decision.model_dump()
            if evaluation.buyer_agent.proposed_purchase is not None
            else None
        ),
        intent=intent,
        merchant_contract=merchant_contract,
    )
    return evaluation


@app.post(
    "/intents/{intent_id}/orchestrate",
    response_model=EndToEndOrchestrationResult,
)
def orchestrate_intent(
    intent_id: str,
    db: Session = Depends(get_db),
):
    intent_record = get_intent_or_404(db, intent_id)
    intent = mandate_from_record(intent_record)
    merchant_contract = get_merchant_or_404(intent.merchant_id, db=db)
    evaluation = evaluate_persisted_intent(
        intent_record,
        merchant_contract,
        db,
    )
    persist_buyer_agent_audit_logs(
        db=db,
        intent_record=intent_record,
        buyer_result=evaluation.buyer_agent,
        verification_result=(
            evaluation.verification.model_dump()
            if evaluation.verification is not None
            else None
        ),
        policy_result=(
            evaluation.merchant_policy.model_dump()
            if evaluation.merchant_policy is not None
            else None
        ),
        final_decision=(
            evaluation.final_decision.model_dump()
            if evaluation.buyer_agent.proposed_purchase is not None
            else None
        ),
        intent=intent,
        merchant_contract=merchant_contract,
    )
    return {
        "protocol_context": build_commerce_context(intent_record),
        "evaluation": evaluation,
        "stage_trace": build_stage_trace(evaluation),
        "next_action": next_action_for_evaluation(evaluation),
        "payment_executed": False,
    }
