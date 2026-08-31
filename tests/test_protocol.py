from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.schemas.payment import PaymentStatus
from backend.app.schemas.protocol import (
    CommerceContext,
    ExternalProtocolStatus,
    ProviderPaymentCommand,
    ProviderPaymentResult,
)
from backend.app.schemas.purchase import ProposedPurchase
from backend.app.services.protocol_service import (
    build_commerce_context,
    build_protocol_manifest,
    build_provider_payment_command,
    verify_provider_result,
)


def build_intent_record():
    return SimpleNamespace(
        intent_id=str(uuid4()),
        correlation_id=str(uuid4()),
        protocol_version="1.0",
        mandate={
            "merchant_id": "MERCHANT-001",
            "product_category": "headphones",
            "max_budget": 5000,
        },
    )


def build_purchase() -> ProposedPurchase:
    return ProposedPurchase(
        product_id="PROD-001",
        quantity=1,
        unit_price=3200,
        total_amount=3200,
        subscription=False,
    )


def test_protocol_manifest_does_not_claim_external_conformance():
    manifest = build_protocol_manifest()
    declarations = {
        declaration.protocol.value: declaration
        for declaration in manifest.external_protocols
    }

    assert set(declarations) == {"UCP", "AP2", "ACP", "X402"}
    assert "UAP" not in declarations
    assert all(
        declaration.status == ExternalProtocolStatus.NOT_IMPLEMENTED
        for declaration in declarations.values()
    )
    assert manifest.supported_payment_providers == [
        "INTERNAL_LEDGER",
        "RAZORPAY_TEST",
    ]


def test_commerce_context_is_built_from_persisted_intent():
    intent_record = build_intent_record()

    context = build_commerce_context(intent_record)

    assert str(context.correlation_id) == intent_record.correlation_id
    assert context.intent_id == intent_record.intent_id
    assert context.merchant_id == "MERCHANT-001"
    assert context.protocol_version == "1.0"


def test_provider_command_uses_trusted_purchase_boundary():
    intent_record = build_intent_record()
    purchase = build_purchase()

    command = build_provider_payment_command(
        intent_record,
        purchase,
        "protocol-test-key",
    )

    assert command.authorized_amount == 3200
    assert command.purchase == purchase
    assert command.provider.value == "INTERNAL_LEDGER"


def test_provider_command_rejects_amount_mismatch():
    with pytest.raises(
        ValidationError,
        match="amount must match",
    ):
        ProviderPaymentCommand(
            context=build_commerce_context(build_intent_record()),
            idempotency_key="protocol-test-key",
            authorized_amount=9999,
            purchase=build_purchase(),
        )


def test_matching_provider_result_is_verified():
    command = build_provider_payment_command(
        build_intent_record(),
        build_purchase(),
        "protocol-test-key",
    )
    result = ProviderPaymentResult(
        context=command.context,
        provider=command.provider,
        provider_reference="PAYMENT-001",
        product_id=command.purchase.product_id,
        amount=command.authorized_amount,
        status=PaymentStatus.CREATED,
    )

    verification = verify_provider_result(command, result)

    assert verification.verified is True
    assert verification.violations == []


def test_tampered_provider_result_is_rejected():
    command = build_provider_payment_command(
        build_intent_record(),
        build_purchase(),
        "protocol-test-key",
    )
    wrong_context = CommerceContext(
        protocol_version=command.context.protocol_version,
        correlation_id=uuid4(),
        intent_id=command.context.intent_id,
        merchant_id=command.context.merchant_id,
    )
    result = ProviderPaymentResult(
        context=wrong_context,
        provider=command.provider,
        provider_reference="PAYMENT-001",
        product_id="PROD-002",
        amount=4800,
        status=PaymentStatus.CREATED,
    )

    verification = verify_provider_result(command, result)
    violation_codes = {
        violation.code
        for violation in verification.violations
    }

    assert verification.verified is False
    assert violation_codes == {
        "CORRELATION_ID_MISMATCH",
        "PROVIDER_AMOUNT_MISMATCH",
        "PROVIDER_PRODUCT_MISMATCH",
    }
