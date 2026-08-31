import json

from sqlalchemy.orm import Session

from backend.app.db.models import PaymentDB, WebhookEventDB
from backend.app.schemas.payment import PaymentStatus
from backend.app.schemas.protocol import (
    PaymentProvider,
    ProviderPaymentResult,
)
from backend.app.schemas.purchase import ProposedPurchase
from backend.app.schemas.razorpay import (
    RazorpayCheckoutOptions,
    RazorpayCheckoutVerificationResponse,
    RazorpayCheckoutVerificationRequest,
    RazorpayOrderEntity,
    RazorpayOrderVerification,
    RazorpayProviderOutcome,
    RazorpayReconciliationResponse,
    RazorpayWebhookResponse,
)
from backend.app.services.audit_service import create_audit_log
from backend.app.services.payment_service import (
    create_payment,
    find_payment_by_id,
    payment_protocol_details,
    payment_to_dict,
    reconcile_payment,
    update_payment_status,
)
from backend.app.services.protocol_service import (
    build_provider_payment_command,
    verify_provider_result,
)
from backend.app.services.razorpay_adapter import (
    RazorpayTestClient,
    build_razorpay_order_request,
    build_razorpay_receipt_from_values,
    verify_checkout_signature,
    verify_webhook_signature,
)
from backend.app.services.webhook_service import process_payment_webhook


def verify_razorpay_order(
    command,
    order_request,
    order: RazorpayOrderEntity,
) -> RazorpayOrderVerification:
    violations = []

    if order.amount != order_request.amount:
        violations.append({
            "code": "RAZORPAY_ORDER_AMOUNT_MISMATCH",
            "message": "Razorpay order amount does not match authorization.",
        })
    if order.currency != order_request.currency:
        violations.append({
            "code": "RAZORPAY_ORDER_CURRENCY_MISMATCH",
            "message": "Razorpay order currency does not match authorization.",
        })
    if order.receipt != order_request.receipt:
        violations.append({
            "code": "RAZORPAY_ORDER_RECEIPT_MISMATCH",
            "message": "Razorpay order receipt does not match the command.",
        })
    if order.amount != command.authorized_amount * 100:
        violations.append({
            "code": "RAZORPAY_SUBUNIT_CONVERSION_MISMATCH",
            "message": "Razorpay paise amount does not match the rupee mandate.",
        })

    return RazorpayOrderVerification(
        verified=not violations,
        violations=violations,
    )


def provider_result_from_order(command, order: RazorpayOrderEntity):
    status = (
        PaymentStatus.CAPTURED
        if order.status == "paid"
        else PaymentStatus.PENDING
    )
    return ProviderPaymentResult(
        context=command.context,
        provider=PaymentProvider.RAZORPAY_TEST,
        provider_reference=order.id,
        product_id=command.purchase.product_id,
        amount=command.authorized_amount,
        status=status,
    )


def persist_provider_order(
    db: Session,
    payment: PaymentDB,
    order: RazorpayOrderEntity,
    event_type: str,
    reason_code: str,
):
    payment.provider_order_id = order.id
    payment.provider_status = order.status

    try:
        db.flush()
        create_audit_log(
            db=db,
            event_type=event_type,
            component="RAZORPAY_TEST_ADAPTER",
            message="Razorpay Test Mode order metadata was persisted.",
            entity_type="PAYMENT",
            entity_id=payment.payment_id,
            reason_code=reason_code,
            amount=payment.amount,
            details={
                **payment_protocol_details(db, payment),
                "provider": payment.provider,
                "provider_order_id": order.id,
                "provider_status": order.status,
                "amount_subunits": order.amount,
                "currency": order.currency,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(payment)


def audit_provider_outcome(
    db: Session,
    payment: PaymentDB,
    event_type: str,
    reason_code: str,
    message: str,
):
    try:
        create_audit_log(
            db=db,
            event_type=event_type,
            component="RAZORPAY_TEST_ADAPTER",
            message=message,
            entity_type="PAYMENT",
            entity_id=payment.payment_id,
            reason_code=reason_code,
            amount=payment.amount,
            details={
                **payment_protocol_details(db, payment),
                "provider": payment.provider,
                "provider_order_id": payment.provider_order_id,
                "payment_status": payment.status,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def execute_razorpay_test_order(
    db: Session,
    intent_record,
    purchase: ProposedPurchase,
    idempotency_key: str,
    trusted_amount: int,
    client: RazorpayTestClient,
) -> dict:
    command = build_provider_payment_command(
        intent_record=intent_record,
        purchase=purchase,
        idempotency_key=idempotency_key,
        provider=PaymentProvider.RAZORPAY_TEST,
    )
    payment_result = create_payment(
        db=db,
        intent_id=intent_record.intent_id,
        correlation_id=intent_record.correlation_id,
        protocol_version=intent_record.protocol_version,
        product_id=purchase.product_id,
        amount=trusted_amount,
        idempotency_key=idempotency_key,
        provider=PaymentProvider.RAZORPAY_TEST.value,
        currency="INR",
    )
    payment = find_payment_by_id(
        db,
        payment_result["payment"]["payment_id"],
    )

    if payment is None:
        raise RuntimeError("The local Razorpay payment record was not found.")

    if not payment_result["success"]:
        return {
            "payment_created": False,
            "reason_code": payment_result["reason_code"],
            "message": payment_result["message"],
            "payment_command": command,
            "payment_result": payment_result,
        }

    if not payment_result["created"]:
        payment_result["payment"] = payment_to_dict(payment)

        if payment.provider_order_id:
            checkout_options = RazorpayCheckoutOptions(
                key=client.credentials.key_id,
                amount=payment.amount * 100,
                order_id=payment.provider_order_id,
                description=f"IntentPay purchase {payment.product_id}",
            )
            return {
                "payment_created": False,
                "reason_code": "RAZORPAY_ORDER_IDEMPOTENT_REPLAY",
                "message": (
                    "The existing Razorpay Test Mode order was returned; no "
                    "second provider request was sent."
                ),
                "payment_command": command,
                "checkout_options": checkout_options,
                "payment_result": payment_result,
            }

        return {
            "payment_created": False,
            "reason_code": "RAZORPAY_ORDER_REQUIRES_RECONCILIATION",
            "message": (
                "The logical payment already exists without a confirmed "
                "provider order ID. It was not blindly retried."
            ),
            "payment_command": command,
            "payment_result": payment_result,
        }

    pending_result = update_payment_status(
        db,
        payment.payment_id,
        PaymentStatus.PENDING,
    )
    order_request = build_razorpay_order_request(
        command,
        payment.payment_id,
    )
    provider_call = client.create_order(order_request)

    if provider_call.outcome == RazorpayProviderOutcome.UNCERTAIN:
        update_payment_status(
            db,
            payment.payment_id,
            PaymentStatus.UNKNOWN,
        )
        db.refresh(payment)
        audit_provider_outcome(
            db,
            payment,
            "RAZORPAY_ORDER_UNKNOWN",
            provider_call.reason_code,
            provider_call.message,
        )
        payment_result["payment"] = payment_to_dict(payment)
        return {
            "payment_created": True,
            "reason_code": provider_call.reason_code,
            "message": provider_call.message,
            "payment_command": command,
            "order_request": order_request,
            "payment_result": payment_result,
        }

    if provider_call.outcome == RazorpayProviderOutcome.REJECTED:
        update_payment_status(
            db,
            payment.payment_id,
            PaymentStatus.FAILED,
        )
        db.refresh(payment)
        audit_provider_outcome(
            db,
            payment,
            "RAZORPAY_ORDER_REJECTED",
            provider_call.reason_code,
            provider_call.message,
        )
        payment_result["payment"] = payment_to_dict(payment)
        return {
            "payment_created": True,
            "reason_code": provider_call.reason_code,
            "message": provider_call.message,
            "payment_command": command,
            "order_request": order_request,
            "payment_result": payment_result,
        }

    order = provider_call.order
    if order is None:
        raise RuntimeError("Successful Razorpay call did not contain an order.")

    order_verification = verify_razorpay_order(
        command,
        order_request,
        order,
    )
    persist_provider_order(
        db,
        payment,
        order,
        event_type=(
            "RAZORPAY_ORDER_CREATED"
            if order_verification.verified
            else "RAZORPAY_ORDER_VERIFICATION_FAILED"
        ),
        reason_code=(
            "RAZORPAY_TEST_ORDER_CREATED"
            if order_verification.verified
            else "RAZORPAY_ORDER_VERIFICATION_FAILED"
        ),
    )

    if not order_verification.verified:
        update_payment_status(
            db,
            payment.payment_id,
            PaymentStatus.UNKNOWN,
        )
        db.refresh(payment)
        payment_result["payment"] = payment_to_dict(payment)
        return {
            "payment_created": True,
            "reason_code": "RAZORPAY_ORDER_VERIFICATION_FAILED",
            "message": (
                "The provider order did not match the authorized command and "
                "was moved to UNKNOWN for reconciliation."
            ),
            "payment_command": command,
            "order_request": order_request,
            "provider_order": order,
            "order_verification": order_verification,
            "payment_result": payment_result,
        }

    provider_result = provider_result_from_order(command, order)
    provider_verification = verify_provider_result(command, provider_result)
    checkout_options = RazorpayCheckoutOptions(
        key=client.credentials.key_id,
        amount=order.amount,
        order_id=order.id,
        description=f"IntentPay purchase {purchase.product_id}",
    )
    payment_result["payment"] = payment_to_dict(payment)

    return {
        "payment_created": True,
        "reason_code": "RAZORPAY_TEST_ORDER_CREATED",
        "message": (
            "The verified Razorpay Test Mode order is ready for client-side "
            "Checkout. Payment is not complete until captured."
        ),
        "payment_command": command,
        "order_request": order_request,
        "provider_order": order,
        "provider_result": provider_result,
        "provider_verification": provider_verification,
        "order_verification": order_verification,
        "checkout_options": checkout_options,
        "payment_result": payment_result,
    }


def verify_razorpay_checkout_response(
    db: Session,
    local_payment_id: str,
    request: RazorpayCheckoutVerificationRequest,
    client: RazorpayTestClient,
) -> RazorpayCheckoutVerificationResponse:
    payment = find_payment_by_id(db, local_payment_id)

    if payment is None or payment.provider != PaymentProvider.RAZORPAY_TEST.value:
        return RazorpayCheckoutVerificationResponse(
            verified=False,
            reason_code="RAZORPAY_PAYMENT_NOT_FOUND",
            message="The Razorpay Test Mode payment was not found.",
            payment_id=local_payment_id,
        )

    if payment.provider_order_id != request.razorpay_order_id:
        return RazorpayCheckoutVerificationResponse(
            verified=False,
            reason_code="RAZORPAY_ORDER_ID_MISMATCH",
            message="Checkout order ID does not match the local payment.",
            payment_id=local_payment_id,
            provider_order_id=payment.provider_order_id,
        )

    verified = verify_checkout_signature(
        request.razorpay_order_id,
        request.razorpay_payment_id,
        request.razorpay_signature,
        client.credentials.key_secret,
    )

    if not verified:
        audit_provider_outcome(
            db,
            payment,
            "RAZORPAY_CHECKOUT_SIGNATURE_REJECTED",
            "RAZORPAY_CHECKOUT_SIGNATURE_INVALID",
            "Razorpay Checkout signature verification failed.",
        )
        return RazorpayCheckoutVerificationResponse(
            verified=False,
            reason_code="RAZORPAY_CHECKOUT_SIGNATURE_INVALID",
            message="Razorpay Checkout signature verification failed.",
            payment_id=local_payment_id,
            provider_order_id=payment.provider_order_id,
        )

    if (
        payment.provider_payment_id is not None
        and payment.provider_payment_id != request.razorpay_payment_id
    ):
        return RazorpayCheckoutVerificationResponse(
            verified=False,
            reason_code="RAZORPAY_PAYMENT_ID_MISMATCH",
            message="Checkout payment ID conflicts with the stored provider payment.",
            payment_id=local_payment_id,
            provider_order_id=payment.provider_order_id,
            provider_payment_id=payment.provider_payment_id,
        )

    payment.provider_payment_id = request.razorpay_payment_id
    payment.provider_status = "checkout_signature_verified"

    try:
        db.flush()
        create_audit_log(
            db=db,
            event_type="RAZORPAY_CHECKOUT_SIGNATURE_VERIFIED",
            component="RAZORPAY_TEST_ADAPTER",
            message=(
                "Razorpay Checkout signature was verified; captured status "
                "is still required before fulfillment."
            ),
            entity_type="PAYMENT",
            entity_id=payment.payment_id,
            reason_code="RAZORPAY_CHECKOUT_SIGNATURE_VERIFIED",
            amount=payment.amount,
            details={
                **payment_protocol_details(db, payment),
                "provider": payment.provider,
                "provider_order_id": payment.provider_order_id,
                "provider_payment_id": payment.provider_payment_id,
                "awaiting_captured_webhook": True,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return RazorpayCheckoutVerificationResponse(
        verified=True,
        reason_code="RAZORPAY_CHECKOUT_SIGNATURE_VERIFIED",
        message=(
            "Checkout signature is valid. Fulfillment must wait for captured "
            "status from a webhook or reconciliation."
        ),
        payment_id=local_payment_id,
        provider_order_id=payment.provider_order_id,
        provider_payment_id=payment.provider_payment_id,
        awaiting_captured_webhook=True,
    )


def audit_rejected_razorpay_webhook(
    db: Session,
    event_id: str,
    reason_code: str,
    message: str,
    signature_verified: bool,
    payment_id: str | None = None,
):
    try:
        create_audit_log(
            db=db,
            event_type="RAZORPAY_WEBHOOK_REJECTED",
            component="RAZORPAY_WEBHOOK",
            message=message,
            entity_type="PAYMENT" if payment_id else "WEBHOOK",
            entity_id=payment_id or event_id,
            reason_code=reason_code,
            details={
                "provider": PaymentProvider.RAZORPAY_TEST.value,
                "event_id": event_id,
                "signature_verified": signature_verified,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def process_razorpay_webhook(
    db: Session,
    raw_body: bytes,
    signature: str,
    event_id: str,
    client: RazorpayTestClient,
) -> RazorpayWebhookResponse:
    signature_valid = verify_webhook_signature(
        raw_body,
        signature,
        client.credentials.webhook_secret,
    )
    if not signature_valid:
        audit_rejected_razorpay_webhook(
            db,
            event_id,
            "RAZORPAY_WEBHOOK_SIGNATURE_INVALID",
            "Razorpay webhook signature verification failed.",
            signature_verified=False,
        )
        return RazorpayWebhookResponse(
            success=False,
            processed=False,
            signature_verified=False,
            reason_code="RAZORPAY_WEBHOOK_SIGNATURE_INVALID",
            message="Razorpay webhook signature verification failed.",
            event_id=event_id,
        )

    try:
        payload = json.loads(raw_body)
        event_type = payload["event"]
        payment_entity = payload["payload"]["payment"]["entity"]
        provider_order_id = payment_entity["order_id"]
        provider_payment_id = payment_entity["id"]
        amount_subunits = int(payment_entity["amount"])
        currency = payment_entity["currency"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        audit_rejected_razorpay_webhook(
            db,
            event_id,
            "RAZORPAY_WEBHOOK_PAYLOAD_INVALID",
            "Signed Razorpay webhook payload is malformed.",
            signature_verified=True,
        )
        return RazorpayWebhookResponse(
            success=False,
            processed=False,
            signature_verified=True,
            reason_code="RAZORPAY_WEBHOOK_PAYLOAD_INVALID",
            message="Signed Razorpay webhook payload is malformed.",
            event_id=event_id,
        )

    status_by_event = {
        "payment.authorized": PaymentStatus.AUTHORIZED,
        "payment.captured": PaymentStatus.CAPTURED,
        "payment.failed": PaymentStatus.FAILED,
    }
    new_status = status_by_event.get(event_type)
    if new_status is None:
        return RazorpayWebhookResponse(
            success=True,
            processed=False,
            signature_verified=True,
            reason_code="RAZORPAY_WEBHOOK_EVENT_IGNORED",
            message="The signed Razorpay event type is not subscribed by IntentPay.",
            event_id=event_id,
            event_type=event_type,
        )

    payment = (
        db.query(PaymentDB)
        .filter(PaymentDB.provider_order_id == provider_order_id)
        .first()
    )
    if payment is None:
        audit_rejected_razorpay_webhook(
            db,
            event_id,
            "RAZORPAY_ORDER_NOT_FOUND",
            "Webhook order ID does not match a local payment.",
            signature_verified=True,
        )
        return RazorpayWebhookResponse(
            success=False,
            processed=False,
            signature_verified=True,
            reason_code="RAZORPAY_ORDER_NOT_FOUND",
            message="Webhook order ID does not match a local payment.",
            event_id=event_id,
            event_type=event_type,
        )

    if amount_subunits != payment.amount * 100 or currency != payment.currency:
        audit_rejected_razorpay_webhook(
            db,
            event_id,
            "RAZORPAY_WEBHOOK_TRANSACTION_MISMATCH",
            "Webhook amount or currency does not match the local payment.",
            signature_verified=True,
            payment_id=payment.payment_id,
        )
        return RazorpayWebhookResponse(
            success=False,
            processed=False,
            signature_verified=True,
            reason_code="RAZORPAY_WEBHOOK_TRANSACTION_MISMATCH",
            message="Webhook amount or currency does not match the local payment.",
            event_id=event_id,
            event_type=event_type,
            payment_id=payment.payment_id,
        )

    if event_type == "payment.failed":
        existing_event = db.query(WebhookEventDB).filter(
            WebhookEventDB.event_id == event_id
        ).first()
        if existing_event is not None:
            return RazorpayWebhookResponse(
                success=True,
                processed=False,
                signature_verified=True,
                reason_code="DUPLICATE_WEBHOOK_EVENT",
                message="This Razorpay webhook event was already processed.",
                event_id=event_id,
                event_type=event_type,
                payment_id=payment.payment_id,
                payment=payment_to_dict(payment),
            )

        payment.provider_status = event_type
        db.add(WebhookEventDB(
            event_id=event_id,
            payment_id=payment.payment_id,
            status=PaymentStatus.FAILED.value,
            processed=True,
            provider=PaymentProvider.RAZORPAY_TEST.value,
            signature_verified=True,
        ))
        create_audit_log(
            db=db,
            event_type="RAZORPAY_PAYMENT_ATTEMPT_FAILED",
            component="RAZORPAY_WEBHOOK",
            message=(
                "A Razorpay payment attempt failed. The order remains open "
                "for a valid Checkout retry."
            ),
            entity_type="PAYMENT",
            entity_id=payment.payment_id,
            reason_code="RAZORPAY_PAYMENT_ATTEMPT_FAILED",
            amount=payment.amount,
            details={
                **payment_protocol_details(db, payment),
                "event_id": event_id,
                "provider_order_id": provider_order_id,
                "failed_provider_payment_id": provider_payment_id,
            },
        )
        db.commit()
        db.refresh(payment)
        return RazorpayWebhookResponse(
            success=True,
            processed=True,
            signature_verified=True,
            reason_code="RAZORPAY_PAYMENT_ATTEMPT_FAILED",
            message=(
                "The failed attempt was recorded without closing the "
                "Razorpay order."
            ),
            event_id=event_id,
            event_type=event_type,
            payment_id=payment.payment_id,
            payment=payment_to_dict(payment),
        )

    if (
        payment.provider_payment_id is not None
        and payment.provider_payment_id != provider_payment_id
    ):
        audit_rejected_razorpay_webhook(
            db,
            event_id,
            "RAZORPAY_PAYMENT_ID_MISMATCH",
            "Webhook payment ID conflicts with the local provider payment.",
            signature_verified=True,
            payment_id=payment.payment_id,
        )
        return RazorpayWebhookResponse(
            success=False,
            processed=False,
            signature_verified=True,
            reason_code="RAZORPAY_PAYMENT_ID_MISMATCH",
            message="Webhook payment ID conflicts with the local provider payment.",
            event_id=event_id,
            event_type=event_type,
            payment_id=payment.payment_id,
        )

    payment.provider_payment_id = provider_payment_id

    if (
        payment.status == PaymentStatus.CAPTURED.value
        and new_status == PaymentStatus.AUTHORIZED
    ):
        existing_event = db.query(WebhookEventDB).filter(
            WebhookEventDB.event_id == event_id
        ).first()
        if existing_event is None:
            db.add(WebhookEventDB(
                event_id=event_id,
                payment_id=payment.payment_id,
                status=new_status.value,
                processed=False,
                provider=PaymentProvider.RAZORPAY_TEST.value,
                signature_verified=True,
            ))
            create_audit_log(
                db=db,
                event_type="STALE_RAZORPAY_WEBHOOK_IGNORED",
                component="RAZORPAY_WEBHOOK",
                message="A late authorized event was ignored after capture.",
                entity_type="PAYMENT",
                entity_id=payment.payment_id,
                reason_code="STALE_PROVIDER_STATUS",
                amount=payment.amount,
                details={
                    **payment_protocol_details(db, payment),
                    "event_id": event_id,
                    "provider_order_id": provider_order_id,
                    "provider_payment_id": provider_payment_id,
                },
            )
            db.commit()
        return RazorpayWebhookResponse(
            success=True,
            processed=False,
            signature_verified=True,
            reason_code="STALE_PROVIDER_STATUS",
            message="Late authorized event was safely ignored after capture.",
            event_id=event_id,
            event_type=event_type,
            payment_id=payment.payment_id,
            payment=payment_to_dict(payment),
        )

    payment.provider_status = event_type
    result = process_payment_webhook(
        db=db,
        event_id=event_id,
        payment_id=payment.payment_id,
        new_status=new_status,
        provider=PaymentProvider.RAZORPAY_TEST.value,
        signature_verified=True,
    )
    db.refresh(payment)

    return RazorpayWebhookResponse(
        success=result["success"],
        processed=result.get("processed", False),
        signature_verified=True,
        reason_code=result.get("reason_code", "RAZORPAY_WEBHOOK_APPLIED"),
        message=result.get("message", "Razorpay webhook was processed."),
        event_id=event_id,
        event_type=event_type,
        payment_id=payment.payment_id,
        payment=payment_to_dict(payment),
    )


def reconcile_razorpay_payment(
    db: Session,
    local_payment_id: str,
    client: RazorpayTestClient,
) -> RazorpayReconciliationResponse:
    payment = find_payment_by_id(db, local_payment_id)
    if payment is None or payment.provider != PaymentProvider.RAZORPAY_TEST.value:
        return RazorpayReconciliationResponse(
            success=False,
            reason_code="RAZORPAY_PAYMENT_NOT_FOUND",
            message="The Razorpay Test Mode payment was not found.",
        )
    if payment.provider_order_id:
        provider_call = client.fetch_order(payment.provider_order_id)
    else:
        receipt = build_razorpay_receipt_from_values(
            intent_id=payment.intent_id,
            idempotency_key=payment.idempotency_key,
            authorized_amount=payment.amount,
        )
        provider_call = client.find_order_by_receipt(receipt)

    if provider_call.outcome != RazorpayProviderOutcome.SUCCESS:
        return RazorpayReconciliationResponse(
            success=False,
            reason_code=provider_call.reason_code,
            message=provider_call.message,
            payment=payment_to_dict(payment),
        )

    order = provider_call.order
    if order is None:
        raise RuntimeError("Successful Razorpay fetch did not contain an order.")

    if payment.provider_order_id is None:
        persist_provider_order(
            db,
            payment,
            order,
            event_type="RAZORPAY_ORDER_RECOVERED_BY_RECEIPT",
            reason_code="RAZORPAY_ORDER_FOUND_BY_RECEIPT",
        )

    expected_receipt = build_razorpay_receipt_from_values(
        intent_id=payment.intent_id,
        idempotency_key=payment.idempotency_key,
        authorized_amount=payment.amount,
    )
    violations = []
    if order.id != payment.provider_order_id:
        violations.append({
            "code": "RAZORPAY_ORDER_ID_MISMATCH",
            "message": "Fetched order ID does not match the local payment.",
        })
    if order.amount != payment.amount * 100:
        violations.append({
            "code": "RAZORPAY_ORDER_AMOUNT_MISMATCH",
            "message": "Fetched order amount does not match the local payment.",
        })
    if order.currency != payment.currency:
        violations.append({
            "code": "RAZORPAY_ORDER_CURRENCY_MISMATCH",
            "message": "Fetched order currency does not match the local payment.",
        })
    if order.receipt != expected_receipt:
        violations.append({
            "code": "RAZORPAY_ORDER_RECEIPT_MISMATCH",
            "message": "Fetched order receipt does not match the local payment.",
        })
    verification = RazorpayOrderVerification(
        verified=not violations,
        violations=violations,
    )
    if not verification.verified:
        return RazorpayReconciliationResponse(
            success=False,
            reason_code="RAZORPAY_RECONCILIATION_MISMATCH",
            message="Fetched Razorpay order failed deterministic verification.",
            payment=payment_to_dict(payment),
            provider_order=order,
            order_verification=verification,
        )

    payment.provider_status = order.status
    target_status = (
        PaymentStatus.CAPTURED
        if order.status == "paid"
        else PaymentStatus.PENDING
    )

    if payment.status == PaymentStatus.UNKNOWN.value:
        transition = reconcile_payment(
            db,
            payment.payment_id,
            target_status,
        )
    elif payment.status == PaymentStatus.CREATED.value:
        transition = update_payment_status(
            db,
            payment.payment_id,
            target_status,
        )
    elif (
        target_status == PaymentStatus.CAPTURED
        and payment.status in {
            PaymentStatus.PENDING.value,
            PaymentStatus.AUTHORIZED.value,
        }
    ):
        transition = update_payment_status(
            db,
            payment.payment_id,
            target_status,
        )
    else:
        db.commit()
        transition = {"success": True}

    db.refresh(payment)
    return RazorpayReconciliationResponse(
        success=transition["success"],
        reason_code=(
            "RAZORPAY_PAYMENT_RECONCILED"
            if transition["success"]
            else transition["reason_code"]
        ),
        message=(
            "Local payment state now reflects the verified Razorpay order."
            if transition["success"]
            else transition["message"]
        ),
        payment=payment_to_dict(payment),
        provider_order=order,
        order_verification=verification,
    )
