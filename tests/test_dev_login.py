from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from portal.app import create_app
from portal.config import Settings


class LoginInputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") in {"username", "password"}:
            self.values[attrs["name"]] = attrs.get("value", "")


@pytest.mark.parametrize(
    "enabled,public_url,secure,expected",
    [
        (False, "http://127.0.0.1:8080", False, False),
        (True, "http://127.0.0.1:8080", False, True),
        (True, "http://localhost:8080", False, True),
        (True, "https://127.0.0.1:8080", True, False),
        (True, "https://pacs.example.com", True, False),
        (True, "http://pacs.example.com", False, False),
    ],
)
def test_development_credentials_are_only_shown_on_opted_in_local_login(
    monkeypatch, tmp_path, enabled, public_url, secure, expected
):
    monkeypatch.setenv("APP_SECRET", "test-secret-" * 6)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "portal.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("PUBLIC_URL", public_url)
    monkeypatch.setenv("SECURE_COOKIES", str(secure).lower())
    monkeypatch.setenv("DEV_LOGIN_USERNAME", "admin" if enabled else "")
    monkeypatch.setenv("DEV_LOGIN_PASSWORD", "Asd@12345" if enabled else "")
    with TestClient(create_app(Settings.from_env()), base_url=public_url) as client:
        response = client.get("/portal/login")
    assert response.status_code == 200
    inputs = LoginInputs(response.text).values
    assert inputs == {"username": "admin" if expected else "", "password": "Asd@12345" if expected else ""}
    assert ("Asd@12345" in response.text) == expected
