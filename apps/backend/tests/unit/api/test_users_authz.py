import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.truefit_api.api.v1.http import users as users_mod
from src.truefit_infra.auth.middleware import TokenPayload, get_current_user

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


def make_user(org_id=None, role="candidate"):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(), email="t@example.com", display_name="T", role=role,
        org_id=org_id, is_active=True, created_at=now, updated_at=now,
    )


def actor(role, user_id=None, org_id=None):
    return TokenPayload(str(user_id or uuid.uuid4()), "a@example.com", role,
                        str(org_id) if org_id else None)


@pytest.fixture
def ctx():
    svc = AsyncMock()
    org_repo = AsyncMock()
    app = FastAPI()
    app.include_router(users_mod.router, prefix="/api/v1")
    app.dependency_overrides[users_mod.get_user_service] = lambda: svc
    app.dependency_overrides[users_mod.get_org_repo] = lambda: org_repo

    def as_user(payload):
        app.dependency_overrides[get_current_user] = lambda: payload

    return SimpleNamespace(svc=svc, org_repo=org_repo, as_user=as_user,
                           client=TestClient(app))


CREATE_BODY = {"email": "n@example.com", "provider_subject": "sub"}


def test_create_user_admin_only(ctx):
    ctx.svc.create_user.return_value = {
        "user": make_user(), "org": None, "candidate_profile": None}
    ctx.as_user(actor("recruiter", org_id=ORG_A))
    assert ctx.client.post("/api/v1/users", json=CREATE_BODY).status_code == 403
    ctx.as_user(actor("candidate"))
    assert ctx.client.post("/api/v1/users", json=CREATE_BODY).status_code == 403
    ctx.svc.create_user.assert_not_awaited()
    ctx.as_user(actor("admin"))
    assert ctx.client.post("/api/v1/users", json=CREATE_BODY).status_code == 201


@pytest.mark.parametrize("who,expected", [
    ("self", 200), ("admin", 200), ("same_org_recruiter", 200),
    ("other_org_recruiter", 403), ("other_candidate", 403),
    ("same_org_candidate", 403),
])
def test_get_user_and_by_email(ctx, who, expected):
    target = make_user(org_id=ORG_A)
    ctx.svc.get_user.return_value = target
    ctx.svc.get_user_by_email.return_value = target
    payloads = {
        "self": actor("candidate", target.id, ORG_A),
        "admin": actor("admin"),
        "same_org_recruiter": actor("recruiter", org_id=ORG_A),
        "other_org_recruiter": actor("recruiter", org_id=ORG_B),
        "other_candidate": actor("candidate"),
        "same_org_candidate": actor("candidate", org_id=ORG_A),
    }
    ctx.as_user(payloads[who])
    r1 = ctx.client.get(f"/api/v1/users/{target.id}")
    r2 = ctx.client.get("/api/v1/users/by-email/t@example.com")
    assert r1.status_code == expected
    assert r2.status_code == expected
    if expected == 403:
        assert "t@example.com" not in r1.text + r2.text


def test_get_user_404(ctx):
    ctx.svc.get_user.return_value = None
    ctx.svc.get_user_by_email.return_value = None
    ctx.as_user(actor("candidate"))
    assert ctx.client.get(f"/api/v1/users/{uuid.uuid4()}").status_code == 404
    assert ctx.client.get("/api/v1/users/by-email/x@example.com").status_code == 404


def test_patch_self_display_name_ok(ctx):
    me = make_user()
    ctx.svc.update_user.return_value = me
    ctx.as_user(actor("candidate", me.id))
    r = ctx.client.patch(f"/api/v1/users/{me.id}", json={"display_name": "New"})
    assert r.status_code == 200


@pytest.mark.parametrize("body", [
    {"is_active": False}, {"org_id": str(uuid.uuid4())},
])
def test_patch_self_privileged_denied(ctx, body):
    me = make_user()
    ctx.svc.update_user.return_value = me
    ctx.org_repo.get_by_id.return_value = None  # not an org they founded
    ctx.as_user(actor("candidate", me.id))
    r = ctx.client.patch(f"/api/v1/users/{me.id}", json=body)
    assert r.status_code == 403
    ctx.svc.update_user.assert_not_awaited()


@pytest.mark.parametrize("role", ["candidate", "recruiter"])
def test_patch_self_may_pick_candidate_or_recruiter_during_onboarding(ctx, role):
    me = make_user()
    ctx.svc.update_user.return_value = me
    ctx.as_user(actor("candidate", me.id))
    r = ctx.client.patch(f"/api/v1/users/{me.id}", json={"role": role})
    assert r.status_code == 200


def test_patch_self_cannot_self_grant_admin(ctx):
    me = make_user()
    ctx.as_user(actor("candidate", me.id))
    r = ctx.client.patch(f"/api/v1/users/{me.id}", json={"role": "admin"})
    assert r.status_code in (403, 422)
    ctx.svc.update_user.assert_not_awaited()


def test_patch_self_may_attach_to_an_org_they_founded(ctx):
    me = make_user()
    ctx.svc.update_user.return_value = me
    ctx.org_repo.get_by_id.return_value = SimpleNamespace(id=ORG_A, created_by=me.id)
    ctx.as_user(actor("recruiter", me.id))
    r = ctx.client.patch(f"/api/v1/users/{me.id}", json={"org_id": str(ORG_A)})
    assert r.status_code == 200


def test_patch_other_user_denied_even_for_recruiter(ctx):
    target = make_user(org_id=ORG_A)
    ctx.as_user(actor("recruiter", org_id=ORG_A))
    r = ctx.client.patch(f"/api/v1/users/{target.id}", json={"display_name": "x"})
    assert r.status_code == 403
    ctx.svc.update_user.assert_not_awaited()


def test_patch_admin_can_change_privileged(ctx):
    target = make_user()
    ctx.svc.update_user.return_value = target
    ctx.as_user(actor("admin"))
    r = ctx.client.patch(f"/api/v1/users/{target.id}",
                         json={"role": "recruiter", "is_active": True})
    assert r.status_code == 200


def org_with(created_by):
    return SimpleNamespace(id=ORG_A, created_by=created_by)


def test_join_org_founder_allowed(ctx):
    me = make_user()
    ctx.org_repo.get_by_id.return_value = org_with(me.id)
    ctx.svc.join_org.return_value = me
    ctx.as_user(actor("recruiter", me.id))
    r = ctx.client.post(f"/api/v1/users/{me.id}/join-org", json={"org_id": str(ORG_A)})
    assert r.status_code == 200


def test_join_org_non_founder_denied(ctx):
    me = make_user()
    ctx.org_repo.get_by_id.return_value = org_with(uuid.uuid4())
    ctx.as_user(actor("recruiter", me.id))
    r = ctx.client.post(f"/api/v1/users/{me.id}/join-org", json={"org_id": str(ORG_A)})
    assert r.status_code == 403
    ctx.svc.join_org.assert_not_awaited()


def test_join_org_unknown_org_denied_for_non_admin(ctx):
    me = make_user()
    ctx.org_repo.get_by_id.return_value = None
    ctx.as_user(actor("recruiter", me.id))
    r = ctx.client.post(f"/api/v1/users/{me.id}/join-org", json={"org_id": str(ORG_A)})
    assert r.status_code == 403


def test_join_org_for_someone_else_denied(ctx):
    victim = make_user()
    attacker = uuid.uuid4()
    ctx.org_repo.get_by_id.return_value = org_with(attacker)
    ctx.as_user(actor("recruiter", attacker, ORG_A))
    r = ctx.client.post(f"/api/v1/users/{victim.id}/join-org", json={"org_id": str(ORG_A)})
    assert r.status_code == 403
    ctx.svc.join_org.assert_not_awaited()


def test_join_org_admin_allowed(ctx):
    target = make_user()
    ctx.svc.join_org.return_value = target
    ctx.as_user(actor("admin"))
    r = ctx.client.post(f"/api/v1/users/{target.id}/join-org", json={"org_id": str(ORG_A)})
    assert r.status_code == 200
