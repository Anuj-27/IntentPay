import pytest

from backend.app.db.models import MerchantCredentialDB
from backend.app.services.security_service import hash_password


MERCHANT_ID = "MERCHANT-001"
PASSWORD = "test-only-password-123"


def seed_credential(db_session):
    password_hash, password_salt = hash_password(PASSWORD)
    db_session.add(
        MerchantCredentialDB(
            merchant_id=MERCHANT_ID,
            password_hash=password_hash,
            password_salt=password_salt,
        )
    )
    db_session.commit()


def login(client):
    return client.post(
        "/merchant/session/login",
        json={"merchant_id": MERCHANT_ID, "password": PASSWORD},
    )


def create_escalated_intent(client):
    response = client.post(
        "/intents",
        json={
            "product_category": "headphones",
            "max_budget": 10000,
            "quantity": 2,
            "brand": "Sony",
            "brand_preference": "EXACT",
            "preferred_features": ["ANC", "fast charging"],
            "autonomous_selection_allowed": True,
        },
    )
    assert response.status_code == 201
    return response.json()["intent_id"]


def test_reask_cannot_create_merchant_approval(client):
    intent_id = client.post(
        "/intents",
        json={
            "product_category": "headphones",
            "max_budget": 5000,
            "autonomous_selection_allowed": False,
        },
    ).json()["intent_id"]

    response = client.post(f"/intents/{intent_id}/merchant-approval")

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "APPROVAL_NOT_REQUIRED"


def test_escalation_can_be_approved_and_payment_re_evaluates(client, db_session):
    seed_credential(db_session)
    intent_id = create_escalated_intent(client)

    evaluation = client.post(f"/intents/{intent_id}/orchestrate").json()
    assert evaluation["evaluation"]["final_decision"]["decision"] == "ESCALATE"

    request_response = client.post(
        f"/intents/{intent_id}/merchant-approval"
    )
    assert request_response.status_code == 201
    approval = request_response.json()
    assert approval["status"] == "PENDING"
    assert approval["amount"] == 9600

    assert login(client).status_code == 200
    pending = client.get("/merchant/approvals").json()
    assert [item["approval_id"] for item in pending["approvals"]] == [
        approval["approval_id"]
    ]

    decision_response = client.post(
        f"/merchant/approvals/{approval['approval_id']}/decision",
        json={"decision": "APPROVE", "reason": "Verified for this customer."},
    )
    assert decision_response.status_code == 200
    decision_body = decision_response.json()
    assert decision_body["approval"]["status"] == "APPROVED"
    assert decision_body["evaluation"]["final_decision"]["decision"] == "ALLOW"
    assert decision_body["ready_for_payment"] is True

    purchase = decision_body["evaluation"]["buyer_agent"]["proposed_purchase"]
    payment_response = client.post(
        "/payments/create",
        json={
            "intent_id": intent_id,
            "purchase": purchase,
            "idempotency_key": "approval-payment-001",
        },
    )
    assert payment_response.status_code == 200
    assert payment_response.json()["payment_created"] is True
    assert payment_response.json()["final_decision"]["decision"] == "ALLOW"


def test_escalation_rejection_becomes_block_and_cannot_pay(client, db_session):
    seed_credential(db_session)
    intent_id = create_escalated_intent(client)
    approval = client.post(
        f"/intents/{intent_id}/merchant-approval"
    ).json()
    assert login(client).status_code == 200

    decision_response = client.post(
        f"/merchant/approvals/{approval['approval_id']}/decision",
        json={"decision": "REJECT", "reason": "Inventory is reserved."},
    )
    assert decision_response.status_code == 200
    body = decision_response.json()
    assert body["approval"]["status"] == "REJECTED"
    assert body["evaluation"]["final_decision"]["decision"] == "BLOCK"
    assert body["evaluation"]["final_decision"]["reason_code"] == (
        "MERCHANT_APPROVAL_REJECTED"
    )
    assert body["ready_for_payment"] is False

    purchase = body["evaluation"]["buyer_agent"]["proposed_purchase"]
    payment_response = client.post(
        "/payments/create",
        json={
            "intent_id": intent_id,
            "purchase": purchase,
            "idempotency_key": "rejected-approval-payment-001",
        },
    )
    assert payment_response.status_code == 200
    assert payment_response.json()["payment_created"] is False
    assert payment_response.json()["final_decision"]["decision"] == "BLOCK"


def test_database_rejects_a_second_pending_approval_for_the_same_purchase(client, db_session):
    """The real concurrency guard: a partial unique index on
    (intent_id, product_id, amount) WHERE status='PENDING', not just an
    application-level check. Proven directly against the DB rather than
    trusting the service layer's own check-then-insert."""

    from datetime import datetime, timedelta, timezone

    from sqlalchemy.exc import IntegrityError

    from backend.app.db.models import MerchantApprovalDB

    now = datetime.now(timezone.utc)
    common = dict(
        intent_id=create_escalated_intent(client),
        merchant_id=MERCHANT_ID,
        product_id="PROD-002",
        amount=9600,
        status="PENDING",
        requested_reason_code="MERCHANT_HUMAN_APPROVAL_REQUIRED",
        requested_message="test",
        expires_at=now + timedelta(minutes=30),
    )
    db_session.add(MerchantApprovalDB(approval_id="approval-race-1", **common))
    db_session.commit()

    db_session.add(MerchantApprovalDB(approval_id="approval-race-2", **common))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_concurrent_creation_falls_back_to_the_winning_approval(client, db_session, monkeypatch):
    """Simulates the exact race the DB guard exists for: two requests both
    pass the application-level duplicate check (because neither has
    committed yet) before one of them wins the insert. The service layer
    must recover by returning the winner, not crash or create a second
    PENDING row."""

    from datetime import datetime, timedelta, timezone

    from backend.app.db.models import MerchantApprovalDB
    from backend.app.services import merchant_approval_service

    seed_credential(db_session)
    intent_id = create_escalated_intent(client)

    winner = MerchantApprovalDB(
        approval_id="approval-winner",
        intent_id=intent_id,
        merchant_id=MERCHANT_ID,
        product_id="PROD-002",
        amount=9600,
        status="PENDING",
        requested_reason_code="MERCHANT_HUMAN_APPROVAL_REQUIRED",
        requested_message="won the race",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db_session.add(winner)
    db_session.commit()

    original_lookup = merchant_approval_service.find_latest_matching_approval
    call_count = {"n": 0}

    def flaky_lookup(db, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Pretend this request's own duplicate check ran a moment
            # before "winner" committed -- exactly the race window the
            # database-level guard exists to close.
            return None
        return original_lookup(db, **kwargs)

    monkeypatch.setattr(merchant_approval_service, "find_latest_matching_approval", flaky_lookup)

    record, was_duplicate = merchant_approval_service.create_merchant_approval_request(
        db_session,
        intent_id=intent_id,
        merchant_id=MERCHANT_ID,
        product_id="PROD-002",
        amount=9600,
        reason_code="MERCHANT_HUMAN_APPROVAL_REQUIRED",
        message="race test",
    )

    assert was_duplicate is True
    assert record.approval_id == "approval-winner"

    all_pending = (
        db_session.query(MerchantApprovalDB)
        .filter(
            MerchantApprovalDB.intent_id == intent_id,
            MerchantApprovalDB.status == "PENDING",
        )
        .all()
    )
    assert len(all_pending) == 1


def test_stale_price_blocks_blind_approval(client, db_session):
    """TEST 9 from the spec: if the canonical price changes after the
    approval request was created, the merchant cannot blindly approve the
    old amount."""

    seed_credential(db_session)
    intent_id = create_escalated_intent(client)
    approval = client.post(f"/intents/{intent_id}/merchant-approval").json()
    assert approval["amount"] == 9600

    assert login(client).status_code == 200
    price_change = client.put(
        "/merchant/catalog/products/PROD-002",
        json={
            "product_id": "PROD-002",
            "name": "Sony Premium Wireless",
            "category": "headphones",
            "price": 5200,
            "brand": "Sony",
            "color": "black",
            "rating": 4.7,
            "features": ["40-hour battery", "ANC", "fast charging", "better microphone"],
            "in_stock": True,
        },
    )
    assert price_change.status_code == 200

    assert login(client).status_code == 200
    decision_response = client.post(
        f"/merchant/approvals/{approval['approval_id']}/decision",
        json={"decision": "APPROVE", "reason": "Approving without noticing the price moved."},
    )

    assert decision_response.status_code == 409
    assert decision_response.json()["detail"]["reason_code"] == "MERCHANT_APPROVAL_STALE"


def test_out_of_stock_blocks_blind_approval(client, db_session):
    """TEST 10 from the spec."""

    seed_credential(db_session)
    intent_id = create_escalated_intent(client)
    approval = client.post(f"/intents/{intent_id}/merchant-approval").json()

    assert login(client).status_code == 200
    stock_change = client.put(
        "/merchant/catalog/products/PROD-002",
        json={
            "product_id": "PROD-002",
            "name": "Sony Premium Wireless",
            "category": "headphones",
            "price": 4800,
            "brand": "Sony",
            "color": "black",
            "rating": 4.7,
            "features": ["40-hour battery", "ANC", "fast charging", "better microphone"],
            "in_stock": False,
        },
    )
    assert stock_change.status_code == 200

    assert login(client).status_code == 200
    decision_response = client.post(
        f"/merchant/approvals/{approval['approval_id']}/decision",
        json={"decision": "APPROVE"},
    )

    assert decision_response.status_code == 409
    assert decision_response.json()["detail"]["reason_code"] == "MERCHANT_APPROVAL_STALE"


def test_frontend_cannot_supply_price_or_amount(client, db_session):
    """TEST 11: the creation endpoint takes only an intent_id from the
    URL -- there is no request body field a client could use to smuggle
    in a price or amount at all."""

    import inspect

    from backend.app import main as main_module

    signature = inspect.signature(main_module.request_merchant_approval)
    body_params = [
        name
        for name, param in signature.parameters.items()
        if name not in ("intent_id", "db")
    ]
    assert body_params == []


def test_duplicate_click_returns_the_same_approval(client, db_session):
    """TEST 3: repeated clicks reuse the one active approval."""

    seed_credential(db_session)
    intent_id = create_escalated_intent(client)

    first = client.post(f"/intents/{intent_id}/merchant-approval").json()
    second = client.post(f"/intents/{intent_id}/merchant-approval").json()
    assert first["approval_id"] == second["approval_id"]

    assert login(client).status_code == 200
    pending = client.get("/merchant/approvals").json()["approvals"]
    matching = [a for a in pending if a["intent_id"] == intent_id]
    assert len(matching) == 1


def test_only_the_owning_merchant_can_review_approval(client, db_session):
    seed_credential(db_session)
    intent_id = create_escalated_intent(client)
    approval = client.post(
        f"/intents/{intent_id}/merchant-approval"
    ).json()

    response = client.post(
        f"/merchant/approvals/{approval['approval_id']}/decision",
        json={"decision": "APPROVE"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["reason_code"] == "MERCHANT_SESSION_REQUIRED"
