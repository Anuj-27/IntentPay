def test_demo_interface_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Verified Visual Purchase Intent" in response.text
    assert "Screenshot is discovery, not authority" in response.text


def test_demo_interface_assets_are_served(client):
    stylesheet = client.get("/assets/styles.css")
    application = client.get("/assets/app.js")

    assert stylesheet.status_code == 200
    assert "--green" in stylesheet.text
    assert application.status_code == 200
    assert 'api("/visual-intents/analyze"' in application.text
    assert 'api("/visual-intents/confirm"' in application.text
