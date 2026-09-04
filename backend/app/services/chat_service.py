import hashlib
import json
import logging

from backend.app.data.categories import canonicalize_category
from backend.app.schemas.chat import (
    ChatIntentSummary,
    ChatProductSuggestion,
    ChatUpsellSuggestion,
    ProductAssistantChatRequest,
    ProductAssistantChatResponse,
)
from backend.app.schemas.visual_intent import VisualIntentRequest, VisualProductCandidate
from backend.app.services.conversation_state_service import (
    CORRECT_INTENT,
    COMPARE_PRODUCTS,
    GENERAL_QUESTION,
    NEW_SEARCH,
    PRODUCT_REFERENCE,
    PURCHASE_REQUEST,
    REFINE_SEARCH,
    SEARCH_OPERATIONS,
    ConversationState,
    TurnClassification,
    TurnIntent,
    classify_current_turn,
    log_turn_debug_info,
    replay_conversation,
)
from backend.app.services.intent_extractor import extract_quantity_from_text
from backend.app.services.product_search_service import (
    ProductMatch,
    SearchContext,
    UpsellMatch,
    find_upsell_candidates,
    resolve_search_context,
    search_catalog,
)
from backend.app.services.query_normalizer import extract_feature_phrases
from backend.app.services.visual_intent_service import get_configured_visual_analyzer


logger = logging.getLogger(__name__)


def _last_user_message(request: ProductAssistantChatRequest) -> str:
    return next(
        message.content
        for message in reversed(request.messages)
        if message.role == "user"
    )


def _prior_user_messages(request: ProductAssistantChatRequest) -> list[str]:
    """Every user turn *before* the one being answered right now -- used
    to replay conversation state. The current turn is handled separately
    (classify_current_turn) since, unlike earlier turns, it needs
    reference resolution against what was just shown."""

    user_messages = [m.content for m in request.messages if m.role == "user"]
    return user_messages[:-1]


def _conversation_id(request: ProductAssistantChatRequest) -> str:
    """A stable-per-thread id for correlating debug log lines across the
    turns of one conversation. Nothing is persisted for this -- it is
    just a hash of the thread contents received so far, which is already
    exactly what the (stateless) client resends every turn."""

    payload = json.dumps(
        [{"role": m.role, "content": m.content} for m in request.messages],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _effective_search_text(text: str, visual_candidate: VisualProductCandidate | None) -> str:
    """Merges one turn's text with whatever a visual scan surfaced, so
    query normalization / typo correction / catalog matching all run over
    one combined signal. Deliberately scoped to a single turn, never the
    whole conversation -- concatenating every prior turn here was the
    root cause of a later "compare laptops" turn losing to an earlier
    "smartphone" turn."""

    return " ".join(
        value
        for value in (
            text,
            visual_candidate.product_name if visual_candidate else None,
            visual_candidate.model if visual_candidate else None,
            visual_candidate.variant if visual_candidate else None,
        )
        if value
    )


def _product_match_to_suggestion(match: ProductMatch) -> ChatProductSuggestion:
    return ChatProductSuggestion(
        merchant_id=match.merchant_id,
        merchant_name=match.merchant_name,
        product=match.product,
        score=match.score,
        reasons=match.reasons[:8],
        total_amount=match.total_amount,
        within_budget=match.within_budget,
    )


def _upsell_match_to_suggestion(match: UpsellMatch) -> ChatUpsellSuggestion:
    return ChatUpsellSuggestion(
        merchant_id=match.merchant_id,
        merchant_name=match.merchant_name,
        product=match.product,
        total_amount=match.total_amount,
        over_budget_amount=match.over_budget_amount,
        over_budget_percent=match.over_budget_percent,
        rating_gain=match.rating_gain,
        new_features=match.new_features,
        reasons=match.reasons[:8],
        status=match.status,
    )


def _intent_summary(intent: TurnIntent, *, quantity: int) -> ChatIntentSummary:
    return ChatIntentSummary(
        category=intent.category,
        brand=intent.brand,
        color=intent.color,
        max_budget=intent.max_budget,
        quantity=quantity,
        preferences=list(intent.preferred_features),
        brand_preference=intent.brand_preference,
        color_preference=intent.color_preference,
        priority=intent.priority,
        subscription_allowed=intent.subscription_allowed,
        autonomous_selection_allowed=intent.autonomous_selection_allowed,
    )


def build_product_assistant_chat(
    request: ProductAssistantChatRequest,
    db=None,
) -> ProductAssistantChatResponse:
    last_user_message = _last_user_message(request)
    conversation_id = _conversation_id(request)

    quantity = request.quantity
    try:
        parsed_quantity = extract_quantity_from_text(last_user_message)
        if request.quantity == 1 and parsed_quantity > 1:
            quantity = parsed_quantity
    except ValueError:
        pass

    visual_candidate = None
    visual_error = None
    if request.image_base64 is not None:
        visual_request = VisualIntentRequest(
            image_base64=request.image_base64,
            media_type=request.media_type,
            user_message=last_user_message,
            max_budget=request.max_budget,
            quantity=quantity,
            merchant_id=request.merchant_id,
        )
        try:
            visual_candidate = get_configured_visual_analyzer()(visual_request)
        except (RuntimeError, ValueError) as error:
            visual_error = str(error)

    # ---- Conversation state: replay every PRIOR turn (never the current
    # one) to find out what's actually still on the table, instead of
    # concatenating the whole thread into one blob. ----
    try:
        conversation_state = replay_conversation(
            db, _prior_user_messages(request), merchant_id=request.merchant_id
        )
    except Exception:
        logger.exception("conversation_state: failed to replay prior turns")
        conversation_state = ConversationState()

    effective_text = _effective_search_text(last_user_message, visual_candidate)
    try:
        turn = classify_current_turn(
            db,
            prior_state=conversation_state,
            message_text=effective_text,
            merchant_id=request.merchant_id,
        )
    except Exception:
        logger.exception("conversation_state: failed to classify current turn")
        turn = TurnClassification(operation=GENERAL_QUESTION, intent=conversation_state.intent)

    if turn.operation in SEARCH_OPERATIONS:
        return _handle_search_turn(
            request=request,
            db=db,
            turn=turn,
            effective_text=effective_text,
            visual_candidate=visual_candidate,
            visual_error=visual_error,
            quantity=quantity,
            conversation_id=conversation_id,
            candidate_count_before=len(conversation_state.matches),
        )

    if turn.operation in (PRODUCT_REFERENCE, COMPARE_PRODUCTS, PURCHASE_REQUEST):
        return _handle_reference_turn(
            turn=turn,
            quantity=quantity,
            visual_candidate=visual_candidate,
            conversation_id=conversation_id,
            candidate_count_before=len(conversation_state.matches),
        )

    return _handle_general_question(
        conversation_state=conversation_state,
        quantity=quantity,
        visual_candidate=visual_candidate,
        conversation_id=conversation_id,
    )


def _handle_search_turn(
    *,
    request: ProductAssistantChatRequest,
    db,
    turn: TurnClassification,
    effective_text: str,
    visual_candidate: VisualProductCandidate | None,
    visual_error: str | None,
    quantity: int,
    conversation_id: str,
    candidate_count_before: int,
) -> ProductAssistantChatResponse:
    intent = turn.intent

    visual_category = (
        canonicalize_category(visual_candidate.category)
        if visual_candidate and visual_candidate.confidence >= 0.70
        else None
    )
    category = visual_category or intent.category
    brand = (
        visual_candidate.brand
        if visual_candidate and visual_candidate.brand
        else intent.brand
    )

    budget = intent.max_budget
    if request.max_budget is not None:
        if budget is not None and request.max_budget != budget:
            raise ValueError("max_budget conflicts with the maximum amount in the chat.")
        budget = request.max_budget

    preferences = list(intent.preferred_features)
    for feature in extract_feature_phrases(effective_text):
        if feature not in preferences:
            preferences.append(feature)
    if visual_candidate:
        for feature in visual_candidate.visible_features:
            if feature not in preferences:
                preferences.append(feature)

    resolved_intent = TurnIntent(
        category=category,
        brand=brand,
        color=intent.color,
        max_budget=budget,
        quantity=quantity,
        preferred_features=tuple(preferences),
        brand_preference=intent.brand_preference,
        color_preference=intent.color_preference,
        priority=intent.priority,
        subscription_allowed=intent.subscription_allowed,
        autonomous_selection_allowed=intent.autonomous_selection_allowed,
    )
    intent_summary = _intent_summary(resolved_intent, quantity=quantity)

    if category is None:
        reply = (
            "Tell me what you want to buy, such as a smartphone, laptop, "
            "camera, smartwatch, or headphones. You can also drop a product "
            "image here."
        )
        if visual_candidate and visual_candidate.confidence < 0.70:
            reply = (
                "I received the image, but I cannot identify the product "
                "confidently yet. Add the model name or describe the category "
                "so I can search approved catalogs safely."
            )
        if visual_error:
            reply += " The image analyzer was unavailable, so a text description is needed."
        log_turn_debug_info(
            conversation_id=conversation_id,
            operation=turn.operation,
            previous_intent=turn.intent,
            new_intent=resolved_intent,
            candidate_count_before=candidate_count_before,
            candidate_count_after=0,
        )
        return ProductAssistantChatResponse(
            reply=reply,
            intent=intent_summary,
            visual_candidate=visual_candidate,
            next_action="PROVIDE_PRODUCT_HINT" if request.image_base64 else "PROVIDE_CATEGORY",
        )

    try:
        search_context: SearchContext = resolve_search_context(
            db, effective_text, merchant_id=request.merchant_id
        )
        search_context = SearchContext(
            normalized_text=search_context.normalized_text,
            search_tokens=search_context.search_tokens,
            corrected_tokens=search_context.corrected_tokens,
            correction_applied=search_context.correction_applied,
            category=category,
            brand=brand,
            color=intent.color,
        )
    except Exception:
        logger.exception("product_search: failed to resolve search context")
        search_context = SearchContext(
            normalized_text=effective_text,
            search_tokens=(),
            corrected_tokens=(),
            correction_applied=False,
            category=category,
            brand=brand,
            color=intent.color,
        )

    matches: list[ProductMatch] = []
    try:
        matches = search_catalog(
            db,
            context=search_context,
            budget=budget,
            quantity=quantity,
            merchant_id=request.merchant_id,
            requested_features=preferences,
            limit=5,
        )
    except Exception:
        logger.exception("product_search: catalog search failed for category=%s", category)

    suggestions = [_product_match_to_suggestion(match) for match in matches]
    match_type = "NONE"
    if suggestions:
        match_type = "IMAGE_MATCH" if visual_candidate is not None else "TEXT_MATCH"

    upsell_matches: list[UpsellMatch] = []
    if budget is not None:
        try:
            upsell_matches = find_upsell_candidates(
                db,
                category=category,
                budget=budget,
                quantity=quantity,
                merchant_id=request.merchant_id,
                limit=3,
            )
        except Exception:
            logger.exception("product_search: upsell lookup failed for category=%s", category)
    upsell_suggestions = [_upsell_match_to_suggestion(match) for match in upsell_matches]

    lead_in = ""
    if turn.operation == NEW_SEARCH and candidate_count_before:
        lead_in = "Starting a new search — the previous results no longer apply. "
    elif turn.operation in (REFINE_SEARCH, CORRECT_INTENT):
        lead_in = "Updated your search. "

    if budget is None:
        reply = (
            f"{lead_in}I found {len(suggestions)} approved {category} option(s). "
            "These are discovery suggestions only. Tell me your maximum "
            "budget before I prepare a bounded purchase intent."
        )
        next_action = "PROVIDE_BUDGET"
    elif not suggestions:
        reply = (
            f"{lead_in}I could not find an in-stock {category} product within "
            f"₹{budget} for quantity {quantity}. Increase the maximum budget "
            "or try another category."
        )
        next_action = "PROVIDE_BUDGET"
    else:
        reply = (
            f"{lead_in}I found {len(suggestions)} approved {category} option(s) "
            f"within your maximum of ₹{budget}. Compare the cards, then choose "
            "one to open the separate verification flow. Nothing is authorized "
            "from chat."
        )
        next_action = "CHOOSE_PRODUCT"

    if search_context.correction_applied and (suggestions or upsell_suggestions):
        reply = "I understood that as a search for your product below. " + reply

    if upsell_suggestions:
        reply += (
            f" I also found {len(upsell_suggestions)} premium option(s) above "
            "your budget with meaningfully more value, shown separately."
        )

    if visual_candidate:
        reply = (
            f"Visual candidate: {visual_candidate.product_name} "
            f"({round(visual_candidate.confidence * 100)}% confidence). "
            + reply
        )
    if visual_error:
        reply += " The local vision model was unavailable; OCR/text fallback was used."

    log_turn_debug_info(
        conversation_id=conversation_id,
        operation=turn.operation,
        previous_intent=turn.intent,
        new_intent=resolved_intent,
        candidate_count_before=candidate_count_before,
        candidate_count_after=len(suggestions),
    )

    return ProductAssistantChatResponse(
        reply=reply,
        suggestions=suggestions,
        upsell_candidates=upsell_suggestions,
        visual_candidate=visual_candidate,
        match_type=match_type,
        intent=intent_summary,
        next_action=next_action,
    )


def _handle_reference_turn(
    *,
    turn: TurnClassification,
    quantity: int,
    visual_candidate: VisualProductCandidate | None,
    conversation_id: str,
    candidate_count_before: int,
) -> ProductAssistantChatResponse:
    intent_summary = _intent_summary(turn.intent, quantity=quantity)

    log_turn_debug_info(
        conversation_id=conversation_id,
        operation=turn.operation,
        previous_intent=turn.intent,
        new_intent=turn.intent,
        candidate_count_before=candidate_count_before,
        candidate_count_after=len(turn.reference_matches),
    )

    if turn.unresolved_reference or not turn.reference_matches:
        reply = (
            "I don't have enough recent results to resolve that reference. "
            "Ask for a product category first, or name the product directly."
        )
        return ProductAssistantChatResponse(
            reply=reply,
            intent=intent_summary,
            visual_candidate=visual_candidate,
            next_action="PROVIDE_CATEGORY",
        )

    suggestions = [_product_match_to_suggestion(match) for match in turn.reference_matches]

    if turn.operation == COMPARE_PRODUCTS:
        reply = (
            f"Comparing {len(suggestions)} option(s) from your current results. "
            "Nothing is authorized from chat."
        )
        next_action = "CHOOSE_PRODUCT"
    elif turn.operation == PURCHASE_REQUEST:
        product = turn.reference_matches[0].product
        reply = (
            f"Got it — {product.name} at ₹{turn.reference_matches[0].total_amount}. "
            "Open the separate verification flow to confirm the exact product, "
            "quantity, and budget before anything is authorized."
        )
        next_action = "OPEN_VERIFICATION"
    else:
        product = turn.reference_matches[0].product
        reply = f"Here it is: {product.name} at ₹{turn.reference_matches[0].total_amount}."
        next_action = "CHOOSE_PRODUCT"

    return ProductAssistantChatResponse(
        reply=reply,
        suggestions=suggestions,
        visual_candidate=visual_candidate,
        intent=intent_summary,
        next_action=next_action,
    )


def _handle_general_question(
    *,
    conversation_state: ConversationState,
    quantity: int,
    visual_candidate: VisualProductCandidate | None,
    conversation_id: str,
) -> ProductAssistantChatResponse:
    intent_summary = _intent_summary(conversation_state.intent, quantity=quantity)

    log_turn_debug_info(
        conversation_id=conversation_id,
        operation=GENERAL_QUESTION,
        previous_intent=conversation_state.intent,
        new_intent=conversation_state.intent,
        candidate_count_before=len(conversation_state.matches),
        candidate_count_after=len(conversation_state.matches),
    )

    if not conversation_state.matches:
        return ProductAssistantChatResponse(
            reply=(
                "Tell me what you want to buy, such as a smartphone, laptop, "
                "camera, smartwatch, or headphones. You can also drop a product "
                "image here."
            ),
            intent=intent_summary,
            visual_candidate=visual_candidate,
            next_action="PROVIDE_CATEGORY",
        )

    suggestions = [_product_match_to_suggestion(match) for match in conversation_state.matches]
    return ProductAssistantChatResponse(
        reply="Here are your current results again — let me know how I can help further.",
        suggestions=suggestions,
        visual_candidate=visual_candidate,
        intent=intent_summary,
        next_action="CHOOSE_PRODUCT",
    )
