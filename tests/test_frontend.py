def test_demo_interface_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Shop with intent" in response.text
    assert "Pay with certainty" in response.text
    assert "Screenshot is discovery, not authority" in response.text
    assert '/assets/razorpay_checkout.js' in response.text


def test_demo_interface_assets_are_served(client):
    tokens_stylesheet = client.get("/assets/tokens.css")
    site_script = client.get("/assets/site.js")
    home_stylesheet = client.get("/assets/home.css")
    razorpay_checkout = client.get("/assets/razorpay_checkout.js")
    chat_stylesheet = client.get("/assets/chat.css")
    assistant_stylesheet = client.get("/assets/assistant.css")
    assistant_script = client.get("/assets/assistant.js")

    assert tokens_stylesheet.status_code == 200
    assert "--brand" in tokens_stylesheet.text
    assert site_script.status_code == 200
    assert home_stylesheet.status_code == 200
    assert razorpay_checkout.status_code == 200
    assert 'fetch("/payments/razorpay-test/orders"' in razorpay_checkout.text
    assert "verify-checkout" in razorpay_checkout.text
    assert "razorpay-test/reconcile" in razorpay_checkout.text
    assert chat_stylesheet.status_code == 200
    assert assistant_stylesheet.status_code == 200
    assert assistant_script.status_code == 200
    assert 'fetch("/assistant/chat"' in assistant_script.text
    assert 'fetch("/visual-intents/confirm"' in assistant_script.text
    assert "Open Razorpay Checkout" in assistant_script.text


def test_home_flow_does_not_require_an_image(client):
    response = client.get("/")
    assistant_script = client.get("/assets/assistant.js")

    # The old visible form is gone; the AI assistant widget (mounted by
    # assistant.js at runtime) is the only image-upload entry point on `/`
    # now, and it never marks the file input required.
    assert response.status_code == 200
    assert 'id="ipLauncher"' in response.text
    assert "device-frame" in response.text
    assert assistant_script.status_code == 200
    assert 'data-image-input' in assistant_script.text
    assert 'required' not in assistant_script.text.split("data-image-input")[1].split(">")[0]


def test_home_motion_styles_include_accessible_reduced_motion_fallback(client):
    stylesheet = client.get("/assets/home.css")

    assert stylesheet.status_code == 200
    assert "@keyframes gridDrift" in stylesheet.text
    assert "prefers-reduced-motion" in stylesheet.text
    assert ".demo-video-frame video { display: none; }" in stylesheet.text


def test_new_pages_are_served(client):
    catalog_page = client.get("/catalog")
    merchant_login_page = client.get("/merchant")
    merchant_dashboard_page = client.get("/merchant/dashboard")

    assert catalog_page.status_code == 200
    assert "Browse by category" in catalog_page.text
    assert merchant_login_page.status_code == 200
    assert "Merchant login" in merchant_login_page.text
    assert merchant_dashboard_page.status_code == 200
    assert "Add product" in merchant_dashboard_page.text
    assert "Pending purchase approvals" in merchant_dashboard_page.text


def test_approval_frontend_assets_are_served(client):
    dashboard_script = client.get("/assets/merchant-dashboard.js")
    dashboard_stylesheet = client.get("/assets/merchant.css")

    assert dashboard_script.status_code == 200
    assert "/merchant/approvals" in dashboard_script.text
    assert "Approve purchase" in dashboard_script.text
    assert dashboard_stylesheet.status_code == 200
    assert ".approval-card" in dashboard_stylesheet.text


def test_hero_media_assets_are_served(client):
    screenshot = client.get("/assets/media/hero-app-screenshot.png")
    video = client.get("/assets/media/demo-flow.webm")

    assert screenshot.status_code == 200
    assert screenshot.headers["content-type"] == "image/png"
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/webm"
