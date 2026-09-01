from backend.app.services.visual_intent_service import (
    candidate_from_ocr_text,
    get_visual_analyzer_configuration,
)


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
        "backend.app.services.visual_intent_service.find_tesseract_executable",
        lambda: "tesseract",
    )

    configuration = get_visual_analyzer_configuration()

    assert configuration["mode"] == "LOCAL_OCR"
    assert configuration["local_ocr_available"] is True
    assert configuration["sends_images_to_external_provider"] is False
