import base64

from backend.app.schemas.visual_intent import VisualProductCandidate


PNG_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\nintentpay-test").decode()


def chat_request(message: str, **updates):
    body = {"messages": [{"role": "user", "content": message}]}
    body.update(updates)
    return body


def test_product_assistant_returns_budget_aware_catalog_suggestions(client):
    response = client.post(
        "/assistant/chat",
        json=chat_request("I need a smartphone under 50000 with 5G"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == {
        "category": "smartphones",
        "brand": None,
        "color": None,
        "max_budget": 50000,
        "quantity": 1,
        "preferences": ["5G"],
        "brand_preference": "ANY",
        "color_preference": "ANY",
        "priority": "BEST_VALUE",
        "subscription_allowed": False,
        "autonomous_selection_allowed": False,
    }
    assert body["next_action"] == "CHOOSE_PRODUCT"
    assert body["discovery_only"] is True
    assert body["suggestions"]
    assert all(item["within_budget"] is True for item in body["suggestions"])


def test_product_assistant_requires_budget_before_verification(client):
    response = client.post(
        "/assistant/chat",
        json=chat_request("Show me Samsung smartphones"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"]["category"] == "smartphones"
    assert body["intent"]["brand"] == "Samsung"
    assert body["intent"]["max_budget"] is None
    assert body["next_action"] == "PROVIDE_BUDGET"
    assert all(item["within_budget"] is None for item in body["suggestions"])


def test_product_assistant_extracts_preference_priority_and_permissions(client):
    response = client.post(
        "/assistant/chat",
        json=chat_request(
            "I prefer Samsung smartphones under 50000, cheapest option, subscription is okay"
        ),
    )

    assert response.status_code == 200
    intent = response.json()["intent"]
    assert intent["brand"] == "Samsung"
    assert intent["brand_preference"] == "PREFERRED"
    assert intent["priority"] == "CHEAPEST"
    assert intent["subscription_allowed"] is True
    assert intent["autonomous_selection_allowed"] is False


def test_product_assistant_persists_priority_and_permissions_across_turns(client):
    first = client.post(
        "/assistant/chat",
        json=chat_request("Samsung smartphones under 50000, cheapest option, subscription is okay"),
    )
    assert first.status_code == 200

    second = client.post(
        "/assistant/chat",
        json={
            "messages": [
                {"role": "user", "content": "Samsung smartphones under 50000, cheapest option, subscription is okay"},
                {"role": "assistant", "content": first.json()["reply"]},
                {"role": "user", "content": "actually under 60000"},
            ]
        },
    )

    assert second.status_code == 200
    intent = second.json()["intent"]
    assert intent["max_budget"] == 60000
    assert intent["priority"] == "CHEAPEST"
    assert intent["subscription_allowed"] is True
    assert intent["brand"] == "Samsung"


def test_product_assistant_accepts_image_and_returns_visual_candidate(client, monkeypatch):
    candidate = VisualProductCandidate(
        product_name="Galaxy A56 256GB",
        category="smartphones",
        brand="Samsung",
        model="Galaxy A56",
        variant="8GB/256GB",
        confidence=0.94,
        extraction_method="LOCAL_VISION",
    )
    monkeypatch.setattr(
        "backend.app.services.chat_service.get_configured_visual_analyzer",
        lambda: lambda request: candidate,
    )

    response = client.post(
        "/assistant/chat",
        json=chat_request(
            "Find this phone under 50000",
            image_base64=PNG_BASE64,
            media_type="image/png",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["visual_candidate"]["extraction_method"] == "LOCAL_VISION"
    assert body["visual_candidate"]["model"] == "Galaxy A56"
    assert body["suggestions"][0]["product"]["product_id"] == "TECH-PHONE-002"


def test_product_assistant_rejects_unpaired_image_metadata(client):
    response = client.post(
        "/assistant/chat",
        json=chat_request("Find me a phone", image_base64=PNG_BASE64),
    )

    assert response.status_code == 422


def test_chat_interface_and_navigation_are_served(client):
    chat_page = client.get("/chat")
    home_page = client.get("/")
    assistant_script = client.get("/assets/assistant.js")

    assert chat_page.status_code == 200
    assert 'id="assistantRoot"' in chat_page.text
    assert home_page.status_code == 200
    assert 'href="/chat"' in home_page.text
    assert assistant_script.status_code == 200
    assert 'fetch("/assistant/chat"' in assistant_script.text
