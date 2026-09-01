from typing import Annotated
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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


from backend.app.services.product_filter import filter_products
from backend.app.services.buyer_agent import run_buyer_agent
from backend.app.services.budget_stretch import find_budget_stretch_candidates
from backend.app.services.preference_engine import rank_products
from backend.app.services.tradeoff_engine import evaluate_tradeoff
from backend.app.services.intent_verifier import verify_purchase
from backend.app.services.decision_engine import make_decision
from backend.app.services.merchant_policy_engine import evaluate_merchant_policy
from backend.app.services.merchant_service import (
    check_merchant_access,
    find_catalog_product,
    find_merchant_contract,
    list_merchant_contracts,
)
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

FRONTEND_DIRECTORY = Path(__file__).resolve().parents[2] / "frontend"
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIRECTORY),
    name="frontend-assets",
)


@app.get("/", include_in_schema=False)
def get_demo_interface():
    return FileResponse(FRONTEND_DIRECTORY / "index.html")


@app.middleware("http")
async def add_safe_response_headers(request: Request, call_next):
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


def get_merchant_or_404(merchant_id: str) -> MerchantContract:
    merchant_contract = find_merchant_contract(merchant_id)

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


def evaluate_purchase_request(intent_record, purchase):
    intent = mandate_from_record(intent_record)
    merchant_contract = get_merchant_or_404(intent.merchant_id)
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
    policy_result = evaluate_merchant_policy(
        verification_result,
        merchant_contract.merchant.policy,
        merchant_access_result=merchant_access_result,
    )
    final_decision = evaluate_trust_gate(
        intent_decision,
        policy_result,
    )
    return verification_result, intent_decision, policy_result, final_decision


def persist_buyer_agent_audit_logs(
    db: Session,
    intent_record,
    buyer_result: BuyerAgentResult,
    verification_result: dict | None = None,
    policy_result: dict | None = None,
    final_decision: dict | None = None,
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
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


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
def get_merchants():
    contracts = list_merchant_contracts()

    return {
        "count": len(contracts),
        "merchants": [
            contract.merchant
            for contract in contracts
        ],
    }


@app.get("/categories")
def get_categories():
    contracts = list_merchant_contracts()
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
    merchant_contract = get_merchant_or_404(request.merchant_id)
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
            "Submit razorpay_test_request to POST "
            "/payments/razorpay-test/orders. The user must still complete "
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
def get_merchant_contract(merchant_id: str):
    merchant_contract = get_merchant_or_404(merchant_id)
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
def get_merchant_capabilities(merchant_id: str):
    return get_merchant_or_404(merchant_id).merchant.capabilities


@app.get(
    "/merchants/{merchant_id}/catalog",
    response_model=MerchantCatalog,
)
def get_merchant_catalog(merchant_id: str):
    merchant_contract = get_merchant_or_404(merchant_id)
    require_merchant_access(
        merchant_contract,
        required_capabilities=(
            "catalog_search",
            "inventory_check",
        ),
    )
    return merchant_contract.catalog


@app.post("/intents", status_code=201)
def create_intent(
    intent: IntentMandate,
    db: Session = Depends(get_db),
):
    merchant_contract = get_merchant_or_404(intent.merchant_id)
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
    merchant_contract = get_merchant_or_404(intent.merchant_id)
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
    return intent_to_dict(updated_record)


@app.get("/products")
def get_products(
    merchant_id: str = Query(default=DEFAULT_MERCHANT_ID),
    category: str | None = Query(default=None),
):
    merchant_contract = get_merchant_or_404(merchant_id)
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
def get_allowed_products(intent: IntentMandate):
    merchant_contract = get_merchant_or_404(intent.merchant_id)
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
    ) = evaluate_purchase_request(intent_record, request.purchase)

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
    merchant_contract = get_merchant_or_404(intent.merchant_id)

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

    intent = mandate_from_record(
        intent_record
    )
    merchant_contract = get_merchant_or_404(intent.merchant_id)

    confirmed_product_id = (
        intent_record.selected_product_id
        if intent_record.selection_confirmed
        else None
    )

    evaluation = evaluate_intent_pipeline(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=confirmed_product_id,
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
    merchant_contract = get_merchant_or_404(intent.merchant_id)
    confirmed_product_id = (
        intent_record.selected_product_id
        if intent_record.selection_confirmed
        else None
    )
    evaluation = evaluate_intent_pipeline(
        intent=intent,
        merchant_contract=merchant_contract,
        confirmed_product_id=confirmed_product_id,
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
    )
    return {
        "protocol_context": build_commerce_context(intent_record),
        "evaluation": evaluation,
        "stage_trace": build_stage_trace(evaluation),
        "next_action": next_action_for_evaluation(evaluation),
        "payment_executed": False,
    }
