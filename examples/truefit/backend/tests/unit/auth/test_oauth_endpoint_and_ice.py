import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.truefit_api.api.v1.http import auth as auth_module
from src.truefit_api.api.v1.http.schemas.oauth import AuthTokenResponse
from src.truefit_infra.realtime import ice

pytestmark = pytest.mark.unit


def _app():
    app = FastAPI()
    app.include_router(auth_module.router, prefix="/api/v1")
    return TestClient(app)


def test_google_sign_in_reports_not_configured_instead_of_401(monkeypatch):
    monkeypatch.setattr(auth_module.AppConfig, "GOOGLE_CLIENT_ID", None, raising=False)
    r = _app().post("/api/v1/auth/oauth/token", json={"token": "x" * 20, "provider": "google"})
    assert r.status_code == 400
    assert "not configured" in r.json()["detail"]


def test_google_provider_gets_the_configured_client_id(monkeypatch):
    seen = {}

    def fake_get_oauth_service(**kwargs):
        seen.update(kwargs)
        raise ValueError("stop here")

    monkeypatch.setattr(auth_module.AppConfig, "GOOGLE_CLIENT_ID", "client-123", raising=False)
    monkeypatch.setattr(auth_module, "get_oauth_service", fake_get_oauth_service)
    r = _app().post("/api/v1/auth/oauth/token", json={"token": "x" * 20, "provider": "google"})
    assert seen["client_id"] == "client-123"
    assert r.status_code == 401  # the fake rejects the token


def test_expires_in_is_required_not_defaulted():
    with pytest.raises(ValidationError):
        AuthTokenResponse(
            access_token="t",
            user={"id": "00000000-0000-0000-0000-000000000000", "email": "a@b.c", "role": "candidate", "is_active": True},
        )


def test_ice_servers_are_stun_only_without_turn_config(monkeypatch):
    monkeypatch.setattr(ice.AppConfig, "TURN_SERVER_URL", "", raising=False)
    assert ice.build_ice_servers() == [{"urls": ice.STUN_URL}]


def test_ice_servers_include_configured_turn_credentials(monkeypatch):
    monkeypatch.setattr(ice.AppConfig, "TURN_SERVER_URL", "turn:turn.example.com:3478", raising=False)
    monkeypatch.setattr(ice.AppConfig, "TURN_USERNAME", "user", raising=False)
    monkeypatch.setattr(ice.AppConfig, "TURN_CREDENTIAL", "secret", raising=False)
    servers = ice.build_ice_servers()
    assert servers[1] == {"urls": "turn:turn.example.com:3478", "username": "user", "credential": "secret"}


def test_no_turn_credentials_are_hard_coded_in_signaling():
    import inspect

    from src.truefit_infra.realtime import signaling

    source = inspect.getsource(signaling)
    assert "openrelayproject" not in source
