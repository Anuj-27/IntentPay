"""Conversation-state / intent-update engine for the chat assistant.

`/assistant/chat` is stateless at the transport layer -- the client
resends the whole message history each turn -- but "stateless transport"
does not mean "no conversation state." Before this module existed, the
chat service concatenated every user message in the thread into one text
blob and re-ran category/budget detection over the *whole* thing, so a
later "compare laptops under 65000" turn would still lose to an earlier
"smartphone under 50000" turn (longest alias wins ties; the first budget
number in the blob wins the regex search). That is the bug this module
fixes.

The fix: replay the conversation's prior user turns *in order*, folding
each one into an evolving `TurnIntent` using a small, fixed set of
operations (never a per-product keyword patch), then classify the new
turn against that accumulated state -- including resolving references
like "the second one" against whatever was actually shown last, which
the backend tracks itself rather than trusting the LLM/user text to name
a product_id.
"""

import logging
import re
from dataclasses import dataclass, field

from backend.app.services.intent_extractor import (
    autonomous_selection_is_explicitly_allowed,
    detect_priority,
    extract_budget_from_text,
    preference_level,
    subscription_is_explicitly_allowed,
)
from backend.app.services.product_search_service import (
    ProductMatch,
    SearchContext,
    resolve_search_context,
    search_catalog,
)
from backend.app.services.query_normalizer import extract_feature_phrases, tokenize


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- ops --

NEW_SEARCH = "NEW_SEARCH"
REFINE_SEARCH = "REFINE_SEARCH"
CORRECT_INTENT = "CORRECT_INTENT"
CLARIFICATION_RESPONSE = "CLARIFICATION_RESPONSE"
PRODUCT_REFERENCE = "PRODUCT_REFERENCE"
COMPARE_PRODUCTS = "COMPARE_PRODUCTS"
PURCHASE_REQUEST = "PURCHASE_REQUEST"
GENERAL_QUESTION = "GENERAL_QUESTION"

SEARCH_OPERATIONS = {NEW_SEARCH, REFINE_SEARCH, CORRECT_INTENT, CLARIFICATION_RESPONSE}
REFERENCE_OPERATIONS = {PRODUCT_REFERENCE, COMPARE_PRODUCTS, PURCHASE_REQUEST}


@dataclass(frozen=True)
class TurnIntent:
    category: str | None = None
    brand: str | None = None
    color: str | None = None
    max_budget: int | None = None
    quantity: int = 1
    preferred_features: tuple[str, ...] = ()
    brand_preference: str = "ANY"
    color_preference: str = "ANY"
    priority: str = "BEST_VALUE"
    subscription_allowed: bool = False
    autonomous_selection_allowed: bool = False

    def is_empty(self) -> bool:
        return self.category is None and self.brand is None and self.max_budget is None


@dataclass(frozen=True)
class ConversationState:
    """The state as of just before the turn currently being answered."""

    intent: TurnIntent = field(default_factory=TurnIntent)
    matches: tuple[ProductMatch, ...] = ()
    selected_product_id: str | None = None


@dataclass(frozen=True)
class TurnClassification:
    operation: str
    intent: TurnIntent
    reference_matches: tuple[ProductMatch, ...] = ()
    """Resolved products for PRODUCT_REFERENCE / COMPARE_PRODUCTS /
    PURCHASE_REQUEST -- always drawn from the prior candidate set (never
    invented from the message text)."""
    unresolved_reference: bool = False
    """True when the turn read as a reference ("the second one") but
    there was nothing in the prior candidate set to resolve it against."""


# ---- turn-level signal detection --------------------------------------

ORDINAL_WORDS = {
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4,
}
COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "both": 2}
SUPERLATIVE_BEST_WORDS = {"best", "top", "recommended"}
SUPERLATIVE_CHEAPEST_WORDS = {"cheapest", "lowest"}
PURCHASE_VERBS = {"buy", "purchase", "order", "checkout", "take"}
COMPARE_MARKERS = {"compare", "versus", "vs"}
BARE_REFERENCE_WORDS = {"it", "that", "this"}
ALL_WORDS = {"all", "every"}
_DIGIT_PATTERN = re.compile(r"\b(\d+)\b")


def _find_ordinal_index(tokens: list[str]) -> int | None:
    for token in tokens:
        if token in ORDINAL_WORDS:
            return ORDINAL_WORDS[token]
    return None


def _find_compare_count(tokens: list[str], available: int) -> int | None:
    text = " ".join(tokens)
    if not any(marker in tokens for marker in COMPARE_MARKERS) and not (
        "first" in tokens or "top" in tokens
    ):
        return None

    if any(word in tokens for word in ALL_WORDS):
        return available

    for token in tokens:
        if token in COUNT_WORDS:
            return min(COUNT_WORDS[token], available)

    digit_match = _DIGIT_PATTERN.search(text)
    if digit_match:
        return min(int(digit_match.group(1)), available)

    # "compare X and Y" with no explicit count still means "compare the
    # current candidates" -- default to the top two.
    if any(marker in tokens for marker in COMPARE_MARKERS):
        return min(2, available)

    return None


def _is_purchase_request(tokens: list[str]) -> bool:
    return any(verb in tokens for verb in PURCHASE_VERBS)


def _is_bare_reference(tokens: list[str]) -> bool:
    return any(word in tokens for word in BARE_REFERENCE_WORDS)


def _resolve_superlative_index(tokens: list[str]) -> int | None:
    if any(word in tokens for word in SUPERLATIVE_BEST_WORDS):
        return 0  # matches are already ranked best-first
    return None


# ---- folding prior turns into an accumulated intent --------------------


def _extract_turn_intent_delta(
    db,
    message_text: str,
    *,
    merchant_id: str | None,
) -> tuple[str | None, str | None, str | None, int | None, list[str]]:
    """What THIS message alone (never the whole thread) appears to be
    asking for: category, brand, color, budget, feature phrases."""

    context: SearchContext = resolve_search_context(db, message_text, merchant_id=merchant_id)
    try:
        budget = extract_budget_from_text(message_text)
    except ValueError:
        budget = None
    features = extract_feature_phrases(message_text)
    return context.category, context.brand, context.color, budget, features


def _extract_preference_delta(
    message_text: str,
    *,
    brand: str | None,
    color: str | None,
) -> tuple[str | None, str | None, str | None, bool | None, bool | None]:
    """Settings-style signals THIS message alone appears to carry: brand/
    color preference strength (only meaningful when that turn also named a
    brand/color), purchase priority, and explicit subscription/autonomous-
    selection allowances. None means "no signal this turn" -- the caller
    carries the prior value forward, exactly like budget/brand/color."""

    brand_preference = preference_level(message_text.casefold(), brand.casefold()) if brand is not None else None
    color_preference = preference_level(message_text.casefold(), color) if color is not None else None
    priority = detect_priority(message_text)
    subscription_allowed = True if subscription_is_explicitly_allowed(message_text) else None
    autonomous_selection_allowed = True if autonomous_selection_is_explicitly_allowed(message_text) else None
    return brand_preference, color_preference, priority, subscription_allowed, autonomous_selection_allowed


def _run_search_for_intent(
    db,
    intent: TurnIntent,
    *,
    merchant_id: str | None,
    limit: int,
) -> tuple[ProductMatch, ...]:
    if intent.category is None:
        return ()

    context = SearchContext(
        normalized_text="",
        search_tokens=(),
        corrected_tokens=(),
        correction_applied=False,
        category=intent.category,
        brand=intent.brand,
        color=intent.color,
    )
    return tuple(
        search_catalog(
            db,
            context=context,
            budget=intent.max_budget,
            quantity=intent.quantity,
            merchant_id=merchant_id,
            requested_features=list(intent.preferred_features),
            limit=limit,
        )
    )


def _apply_classification(
    db,
    state: ConversationState,
    classification: TurnClassification,
    *,
    merchant_id: str | None,
    limit: int,
) -> ConversationState:
    """Folds one classified turn into the running conversation state --
    the same transition used both to replay history and to build the
    response to the turn currently being answered."""

    if classification.operation in SEARCH_OPERATIONS:
        matches = _run_search_for_intent(
            db, classification.intent, merchant_id=merchant_id, limit=limit
        )
        # A fresh/refined search supersedes whatever was individually
        # selected before -- that selection may no longer even be in the
        # new candidate set.
        return ConversationState(intent=classification.intent, matches=matches, selected_product_id=None)

    if (
        classification.operation in (PRODUCT_REFERENCE, PURCHASE_REQUEST)
        and classification.reference_matches
    ):
        return ConversationState(
            intent=state.intent,
            matches=state.matches,
            selected_product_id=classification.reference_matches[0].product.product_id,
        )

    # COMPARE_PRODUCTS, GENERAL_QUESTION, and unresolved references don't
    # change what's on the table.
    return state


def replay_conversation(
    db,
    prior_user_messages: list[str],
    *,
    merchant_id: str | None,
    limit: int = 5,
) -> ConversationState:
    """Rebuilds conversation state by classifying and folding every prior
    user turn, in order, using the exact same classifier as the turn
    being answered right now -- so a turn that reads as a reference this
    request either was one, consistently, if the conversation is replayed
    again on the next request."""

    state = ConversationState()
    for message_text in prior_user_messages:
        try:
            classification = classify_current_turn(
                db, prior_state=state, message_text=message_text, merchant_id=merchant_id
            )
        except Exception:
            logger.exception("conversation_state: failed to classify a prior turn during replay")
            continue
        state = _apply_classification(db, state, classification, merchant_id=merchant_id, limit=limit)

    return state


# ---- classifying the turn being answered right now ---------------------


def classify_current_turn(
    db,
    *,
    prior_state: ConversationState,
    message_text: str,
    merchant_id: str | None,
) -> TurnClassification:
    tokens = tokenize(message_text)
    prior_intent = prior_state.intent
    prior_matches = list(prior_state.matches)

    # 1. A genuine category switch always wins, even over words that would
    #    otherwise read as a reference to the existing candidates ("Compare
    #    laptops under 65000" contains "compare", but it is asking for a
    #    new category, not a comparison of the smartphones just shown).
    category, brand, color, budget, features = _extract_turn_intent_delta(
        db, message_text, merchant_id=merchant_id
    )
    (
        brand_preference,
        color_preference,
        priority,
        subscription_allowed,
        autonomous_selection_allowed,
    ) = _extract_preference_delta(message_text, brand=brand, color=color)
    category_changed = category is not None and category != prior_intent.category

    # 2. Reference-type operations take priority when there's something to
    #    reference and this turn isn't actually switching categories --
    #    these never trigger a new catalog search.
    if prior_matches and not category_changed:
        compare_count = _find_compare_count(tokens, available=len(prior_matches))
        ordinal_index = _find_ordinal_index(tokens)
        superlative_index = _resolve_superlative_index(tokens)
        is_purchase = _is_purchase_request(tokens)
        is_bare_ref = _is_bare_reference(tokens)

        if is_purchase:
            index = ordinal_index if ordinal_index is not None else superlative_index
            if index is None and (is_bare_ref or len(prior_matches) == 1):
                # "buy it" / "buy that one" -- resolve to whatever was
                # specifically selected last, else the single/top
                # candidate.
                if prior_state.selected_product_id is not None:
                    resolved = next(
                        (m for m in prior_matches if m.product.product_id == prior_state.selected_product_id),
                        None,
                    )
                    if resolved is not None:
                        return TurnClassification(
                            operation=PURCHASE_REQUEST,
                            intent=prior_intent,
                            reference_matches=(resolved,),
                        )
                index = 0
            if index is not None and 0 <= index < len(prior_matches):
                return TurnClassification(
                    operation=PURCHASE_REQUEST,
                    intent=prior_intent,
                    reference_matches=(prior_matches[index],),
                )
            return TurnClassification(
                operation=PURCHASE_REQUEST,
                intent=prior_intent,
                unresolved_reference=True,
            )

        if compare_count is not None:
            return TurnClassification(
                operation=COMPARE_PRODUCTS,
                intent=prior_intent,
                reference_matches=tuple(prior_matches[:compare_count]),
            )

        if ordinal_index is not None:
            if 0 <= ordinal_index < len(prior_matches):
                return TurnClassification(
                    operation=PRODUCT_REFERENCE,
                    intent=prior_intent,
                    reference_matches=(prior_matches[ordinal_index],),
                )
            return TurnClassification(
                operation=PRODUCT_REFERENCE,
                intent=prior_intent,
                unresolved_reference=True,
            )

        if superlative_index is not None:
            return TurnClassification(
                operation=PRODUCT_REFERENCE,
                intent=prior_intent,
                reference_matches=(prior_matches[superlative_index],),
            )

    # 3. No resolvable reference -- interpret this turn as shaping the
    #    search itself.
    has_signal = category is not None or brand is not None or color is not None or budget is not None or features

    if not has_signal:
        return TurnClassification(operation=GENERAL_QUESTION, intent=prior_intent)

    if category_changed:
        new_intent = TurnIntent(
            category=category,
            brand=brand,
            color=color,
            max_budget=budget,
            quantity=prior_intent.quantity,
            preferred_features=tuple(features),
            brand_preference=brand_preference or "ANY",
            color_preference=color_preference or "ANY",
            priority=priority or prior_intent.priority,
            subscription_allowed=subscription_allowed if subscription_allowed is not None else prior_intent.subscription_allowed,
            autonomous_selection_allowed=(
                autonomous_selection_allowed if autonomous_selection_allowed is not None else prior_intent.autonomous_selection_allowed
            ),
        )
        return TurnClassification(operation=NEW_SEARCH, intent=new_intent)

    if prior_intent.category is None:
        # First real search-shaping turn in the conversation.
        new_intent = TurnIntent(
            category=category,
            brand=brand,
            color=color,
            max_budget=budget,
            quantity=prior_intent.quantity,
            preferred_features=tuple(features),
            brand_preference=brand_preference or "ANY",
            color_preference=color_preference or "ANY",
            priority=priority or prior_intent.priority,
            subscription_allowed=subscription_allowed if subscription_allowed is not None else prior_intent.subscription_allowed,
            autonomous_selection_allowed=(
                autonomous_selection_allowed if autonomous_selection_allowed is not None else prior_intent.autonomous_selection_allowed
            ),
        )
        operation = CLARIFICATION_RESPONSE if prior_intent.is_empty() and category is None else NEW_SEARCH
        return TurnClassification(operation=operation, intent=new_intent)

    # Same category as before: figure out whether each signal replaces an
    # existing value (a correction) or adds a new one (a refinement).
    operation = REFINE_SEARCH
    next_brand = prior_intent.brand
    if brand is not None and brand != prior_intent.brand:
        next_brand = brand
        operation = CORRECT_INTENT if prior_intent.brand is not None else REFINE_SEARCH

    next_color = prior_intent.color
    if color is not None and color != prior_intent.color:
        next_color = color
        operation = CORRECT_INTENT if prior_intent.color is not None else operation

    next_budget = prior_intent.max_budget
    if budget is not None and budget != prior_intent.max_budget:
        next_budget = budget
        operation = CORRECT_INTENT if prior_intent.max_budget is not None else operation

    merged_features = list(prior_intent.preferred_features)
    for feature in features:
        if feature not in merged_features:
            merged_features.append(feature)

    new_intent = TurnIntent(
        category=prior_intent.category,
        brand=next_brand,
        color=next_color,
        max_budget=next_budget,
        quantity=prior_intent.quantity,
        preferred_features=tuple(merged_features),
        brand_preference=brand_preference if brand_preference is not None else prior_intent.brand_preference,
        color_preference=color_preference if color_preference is not None else prior_intent.color_preference,
        priority=priority if priority is not None else prior_intent.priority,
        subscription_allowed=subscription_allowed if subscription_allowed is not None else prior_intent.subscription_allowed,
        autonomous_selection_allowed=(
            autonomous_selection_allowed if autonomous_selection_allowed is not None else prior_intent.autonomous_selection_allowed
        ),
    )
    return TurnClassification(operation=operation, intent=new_intent)


def log_turn_debug_info(
    *,
    conversation_id: str,
    operation: str,
    previous_intent: TurnIntent,
    new_intent: TurnIntent,
    candidate_count_before: int,
    candidate_count_after: int,
) -> None:
    """Structured internal logging only -- never returned to the client."""

    logger.info(
        "chat_conversation_turn",
        extra={
            "conversation_id": conversation_id,
            "operation": operation,
            "previous_category": previous_intent.category,
            "new_category": new_intent.category,
            "previous_budget": previous_intent.max_budget,
            "new_budget": new_intent.max_budget,
            "previous_brand": previous_intent.brand,
            "new_brand": new_intent.brand,
            "candidate_count_before": candidate_count_before,
            "candidate_count_after": candidate_count_after,
        },
    )
