def test_demo_interface_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Verified Visual Purchase Intent" in response.text
    assert "Screenshot is discovery, not authority" in response.text


def test_demo_interface_assets_are_served(client):
    stylesheet = client.get("/assets/styles.css")
    application = client.get("/assets/app.js")
    home_stylesheet = client.get("/assets/home.css")
    home_application = client.get("/assets/home.js")

    assert stylesheet.status_code == 200
    assert "--green" in stylesheet.text
    assert application.status_code == 200
    assert 'api("/visual-intents/analyze"' in application.text
    assert 'api("/visual-intents/confirm"' in application.text
    assert home_stylesheet.status_code == 200
    assert home_application.status_code == 200
    assert 'fetch("/assistant/chat"' in home_application.text


def test_home_flow_does_not_require_an_image(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "No image required" in response.text
    assert 'id="homeImageInput" type="file"' in response.text
    assert 'id="homeImageInput" type="file" required' not in response.text
    assert "orb-core" in response.text


def test_home_motion_styles_include_accessible_reduced_motion_fallback(client):
    stylesheet = client.get("/assets/home.css")

    assert stylesheet.status_code == 200
    assert "@keyframes orbFloat" in stylesheet.text
    assert "prefers-reduced-motion" in stylesheet.text
