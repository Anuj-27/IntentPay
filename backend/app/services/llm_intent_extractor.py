import os

from dotenv import load_dotenv
from openai import OpenAI

from backend.app.schemas.intent import (
    IntentMandate,
)
from backend.app.data.categories import canonicalize_category
from backend.app.services.intent_extractor import (
    autonomous_selection_is_explicitly_allowed,
    extract_budget_from_text,
    extract_quantity_from_text,
    subscription_is_explicitly_allowed,
)
from backend.app.services.merchant_service import (
    find_merchant_contracts_for_category,
)


load_dotenv()

DEFAULT_INTENT_MODEL = "gpt-5.6-luna"

SYSTEM_PROMPT = """
You are the IntentPay Intent Agent.

Convert a user's shopping request into a structured IntentMandate.

Rules:
1. Never invent a budget, quantity, subscription permission, or selection permission.
2. Never treat the maximum budget as a spending target.
3. Use EXACT for a brand or color explicitly requested as a requirement.
4. Use PREFERRED only when the user permits alternatives.
5. Use ANY when the user expresses no brand or color constraint.
6. autonomous_selection_allowed can be true only when the user explicitly
   delegates selection, such as "choose for me" or "you decide".
7. subscription_allowed can be true only when explicitly authorized.
8. Preserve the user's semantic intent.
9. You only extract intent. You do not authorize or execute payments.
10. Product categories may include headphones, smartphones, laptops,
    smartwatches, and cameras. Merchant selection is performed by trusted
    application code, not by you.
"""


def extract_intent_with_llm(
    message: str,
    client: OpenAI | None = None,
) -> IntentMandate:
    explicit_budget = extract_budget_from_text(message)
    explicit_quantity = extract_quantity_from_text(message)

    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        client = OpenAI()

    response = client.responses.parse(
        model=os.getenv("OPENAI_INTENT_MODEL") or DEFAULT_INTENT_MODEL,
        input=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": message,
            },
        ],
        text_format=IntentMandate,
    )

    intent = response.output_parsed
    if intent is None:
        raise ValueError("The LLM could not produce a valid IntentMandate.")

    canonical_category = canonicalize_category(intent.product_category)
    if canonical_category is None:
        raise ValueError("The extracted product category is not supported.")
    matching_merchants = find_merchant_contracts_for_category(canonical_category)
    if not matching_merchants:
        raise ValueError("No approved merchant supports the extracted category.")
    intent = intent.model_copy(
        update={
            "product_category": canonical_category,
            "merchant_id": matching_merchants[0].merchant.merchant_id,
        }
    )

    if intent.max_budget != explicit_budget:
        raise ValueError("The extracted budget does not match the user's text.")
    if intent.quantity != explicit_quantity:
        raise ValueError("The extracted quantity does not match the user's text.")
    if (
        intent.subscription_allowed
        and not subscription_is_explicitly_allowed(message)
    ):
        raise ValueError("The LLM inferred subscription permission that was not explicit.")
    if (
        intent.autonomous_selection_allowed
        and not autonomous_selection_is_explicitly_allowed(message)
    ):
        raise ValueError("The LLM inferred selection permission that was not explicit.")

    return intent
