from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from app.main import app
from app.settings import settings


def test_login_and_ctrader_config_are_reload_safe_and_never_return_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_username", "test-admin")
    monkeypatch.setattr(settings, "admin_password", "very-long-test-password")
    monkeypatch.setattr(settings, "session_secret", "a-long-test-session-signing-secret")
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "quantlab.sqlite3"))
    monkeypatch.setattr(settings, "cors_origins", ["https://owner.github.io"])

    origin = {"Origin": "https://owner.github.io"}
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={
            "username": "test-admin", "password": "very-long-test-password"
        }, headers=origin)
        assert login.status_code == 200
        token = login.json()["access_token"]
        auth = {**origin, "Authorization": f"Bearer {token}"}

        saved = client.put("/api/v1/integrations/ctrader/config", headers=auth, json={
            "client_id": "test-client-id",
            "client_secret": "DO_NOT_RETURN_THIS_SECRET",
            "redirect_uri": "https://api.example.test/api/v1/integrations/ctrader/callback",
            "environment": "demo",
        })
        assert saved.status_code == 200
        assert saved.json()["secret_saved"] is True
        assert "DO_NOT_RETURN_THIS_SECRET" not in saved.text

        # Simulates browser reload: the app re-reads public config using its tab session token.
        read_back = client.get("/api/v1/integrations/ctrader/config", headers={"Authorization": f"Bearer {token}"})
        assert read_back.status_code == 200
        assert read_back.json()["client_id"] == "test-client-id"
        assert read_back.json()["secret_saved"] is True
        assert "client_secret" not in read_back.json()

        assert client.get("/api/v1/integrations/ctrader/config").status_code == 401
        assert client.post("/api/v1/auth/login", json={
            "username": "test-admin", "password": "very-long-test-password"
        }, headers={"Origin": "https://evil.example"}).status_code == 403
