from backend.app.db.models import IntentDB
from backend.app.schemas.intent import IntentMandate
from backend.app.schemas.protocol import (
    CommerceArtifactType,
    CommerceContext,
    ExternalProtocolDeclaration,
    ExternalProtocolName,
    ExternalProtocolStatus,
    PaymentProvider,
    ProtocolManifest,
    ProviderPaymentCommand,
    ProviderPaymentResult,
    ProviderResultVerification,
)
from backend.app.schemas.purchase import ProposedPurchase


def build_protocol_manifest() -> ProtocolManifest:
    not_implemented = ExternalProtocolStatus.NOT_IMPLEMENTED

    return ProtocolManifest(
        supported_artifacts=list(CommerceArtifactType),
        supported_payment_providers=[
            PaymentProvider.INTERNAL_LEDGER.value,
            PaymentProvider.RAZORPAY_TEST.value,
        ],
        external_protocols=[
            ExternalProtocolDeclaration(
                protocol=ExternalProtocolName.UCP,
                status=not_implemented,
                inspiration=[
                    "merchant capability discovery",
                    "typed checkout boundaries",
                ],
                disclaimer=(
                    "IntentPay does not implement or claim UCP "
                    "conformance."
                ),
            ),
            ExternalProtocolDeclaration(
                protocol=ExternalProtocolName.AP2,
                status=not_implemented,
                inspiration=[
                    "intent-bound payment authorization",
                    "deterministic mandate verification",
                    "auditable payment evidence",
                ],
                disclaimer=(
                    "IntentPay mandates are not AP2 mandates and are "
                    "not cryptographically signed."
                ),
            ),
            ExternalProtocolDeclaration(
                protocol=ExternalProtocolName.ACP,
                status=not_implemented,
                inspiration=[
                    "agent-to-merchant checkout lifecycle",
                    "provider-independent payment handoff",
                ],
                disclaimer=(
                    "IntentPay does not expose an ACP checkout "
                    "implementation."
                ),
            ),
            ExternalProtocolDeclaration(
                protocol=ExternalProtocolName.X402,
                status=not_implemented,
                inspiration=[
                    "versioned payment artifacts",
                    "provider result verification",
                ],
                disclaimer=(
                    "IntentPay does not implement HTTP 402 payment "
                    "requirements or on-chain settlement."
                ),
            ),
        ],
        disclaimer=(
            "This manifest describes IntentPay's internal protocol-neutral "
            "boundary. External protocols are design references only."
        ),
    )


def build_commerce_context(
    intent_record: IntentDB,
) -> CommerceContext:
    intent = IntentMandate.model_validate(intent_record.mandate)

    return CommerceContext(
        protocol_version=intent_record.protocol_version,
        correlation_id=intent_record.correlation_id,
        intent_id=intent_record.intent_id,
        merchant_id=intent.merchant_id,
    )


def build_provider_payment_command(
    intent_record: IntentDB,
    purchase: ProposedPurchase,
    idempotency_key: str,
    provider: PaymentProvider = PaymentProvider.INTERNAL_LEDGER,
) -> ProviderPaymentCommand:
    return ProviderPaymentCommand(
        context=build_commerce_context(intent_record),
        idempotency_key=idempotency_key,
        provider=provider,
        authorized_amount=purchase.total_amount,
        purchase=purchase,
    )


def build_internal_provider_result(
    command: ProviderPaymentCommand,
    payment_result: dict,
) -> ProviderPaymentResult:
    payment = payment_result["payment"]

    return ProviderPaymentResult(
        context=command.context,
        provider=command.provider,
        provider_reference=payment["payment_id"],
        product_id=payment["product_id"],
        amount=payment["amount"],
        status=payment["status"],
    )


def verify_provider_result(
    command: ProviderPaymentCommand,
    result: ProviderPaymentResult,
) -> ProviderResultVerification:
    violations = []

    if result.context.correlation_id != command.context.correlation_id:
        violations.append({
            "code": "CORRELATION_ID_MISMATCH",
            "message": "Provider result correlation ID does not match.",
        })

    if result.context.intent_id != command.context.intent_id:
        violations.append({
            "code": "INTENT_ID_MISMATCH",
            "message": "Provider result intent ID does not match.",
        })

    if result.context.merchant_id != command.context.merchant_id:
        violations.append({
            "code": "MERCHANT_ID_MISMATCH",
            "message": "Provider result merchant ID does not match.",
        })

    if result.context.protocol_version != command.context.protocol_version:
        violations.append({
            "code": "PROTOCOL_VERSION_MISMATCH",
            "message": "Provider result protocol version does not match.",
        })

    if result.provider != command.provider:
        violations.append({
            "code": "PAYMENT_PROVIDER_MISMATCH",
            "message": "Provider result came from an unexpected provider.",
        })

    if result.amount != command.authorized_amount:
        violations.append({
            "code": "PROVIDER_AMOUNT_MISMATCH",
            "message": "Provider result amount does not match authorization.",
        })

    if result.product_id != command.purchase.product_id:
        violations.append({
            "code": "PROVIDER_PRODUCT_MISMATCH",
            "message": "Provider result product does not match authorization.",
        })

    if result.currency != command.currency:
        violations.append({
            "code": "PROVIDER_CURRENCY_MISMATCH",
            "message": "Provider result currency does not match authorization.",
        })

    return ProviderResultVerification(
        verified=not violations,
        violations=violations,
    )
