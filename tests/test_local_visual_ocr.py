import base64

from backend.app.services.visual_intent_service import (
    LocalVisionUnavailable,
    analyze_product_screenshot_with_local_vision,
    analyze_product_screenshot_with_fallback,
    candidate_from_ocr_text,
    get_visual_analyzer_configuration,
)
from backend.app.schemas.visual_intent import VisualIntentRequest


PNG_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\nintentpay-test").decode()


def test_local_ocr_maps_visible_model_to_catalog_candidate():
    candidate = candidate_from_ocr_text(
        "DemoTech Google Pixel 9a 128GB 8GB/128GB INR 49,999 5G"
    )

    assert candidate.extraction_method == "LOCAL_OCR"
    assert candidate.product_name == "Pixel 9a 128GB"
    assert candidate.category == "smartphones"
    assert candidate.brand == "Google"
    assert candidate.model == "Pixel 9a"
    assert candidate.displayed_price == 49999
    assert candidate.confidence >= 0.90


def test_unclear_local_ocr_candidate_has_low_confidence():
    candidate = candidate_from_ocr_text("shopping page special offer")

    assert candidate.extraction_method == "LOCAL_OCR"
    assert candidate.confidence < 0.70
    assert candidate.category == "unknown"
    assert candidate.brand is None


def test_visual_configuration_defaults_to_private_local_mode(
    monkeypatch,
):
    monkeypatch.delenv("VISUAL_ANALYZER_MODE", raising=False)
    monkeypatch.setattr(
        "backend.app.services.visual_intent_service.local_vision_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "backend.app.services.visual_intent_service.find_tesseract_executable",
        lambda: "tesseract",
    )

    configuration = get_visual_analyzer_configuration()

    assert configuration["mode"] == "LOCAL_VISION"
    assert configuration["local_vision_available"] is False
    assert configuration["local_ocr_available"] is True
    assert configuration["sends_images_to_external_provider"] is False


def test_local_vision_parses_strict_ollama_json(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "message": {
                    "content": (
                        '{"product_name":"Google Pixel 9a 128GB",'
                        '"category":"smartphones","brand":"Google",'
                        '"model":"Pixel 9a","variant":"8GB/128GB",'
                        '"displayed_price":49999,"currency":"INR",'
                        '"merchant_name":null,"merchant_domain":null,'
                        '"visible_features":["5G"],"confidence":0.93}'
                    )
                }
            }

    def fake_get(url, timeout):
        return FakeResponse()

    def fake_post(url, json, timeout):
        assert url.endswith("/api/chat")
        assert json["model"] == "qwen2.5vl:3b"
        assert json["messages"][0]["images"]
        return FakeResponse()

    monkeypatch.setattr(
        "backend.app.services.visual_intent_service.httpx.get",
        lambda url, timeout: type(
            "TagsResponse", (), {"status_code": 200, "json": lambda self: {"models": [{"name": "qwen2.5vl:3b"}]}}
        )(),
    )
    monkeypatch.setattr(
        "backend.app.services.visual_intent_service.httpx.post", fake_post
    )

    candidate = analyze_product_screenshot_with_local_vision(
        VisualIntentRequest(image_base64=PNG_BASE64, media_type="image/png")
    )

    assert candidate.extraction_method == "LOCAL_VISION"
    assert candidate.model == "Pixel 9a"
    assert candidate.confidence == 0.93


def test_local_vision_falls_back_to_ocr_when_runtime_is_unavailable(monkeypatch):
    expected = candidate_from_ocr_text("Google Pixel 9a 128GB")

    def unavailable(request):
        raise LocalVisionUnavailable("Ollama is not running")

    monkeypatch.setattr(
        "backend.app.services.visual_intent_service.analyze_product_screenshot_with_local_vision",
        unavailable,
    )
    monkeypatch.setattr(
        "backend.app.services.visual_intent_service.analyze_product_screenshot_locally",
        lambda request: expected,
    )

    candidate = analyze_product_screenshot_with_fallback(
        VisualIntentRequest(image_base64=PNG_BASE64, media_type="image/png")
    )

    assert candidate is expected
    assert candidate.extraction_method == "LOCAL_OCR"
