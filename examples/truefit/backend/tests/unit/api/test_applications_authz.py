"""Authorization rules for the applications router, run against in-memory fakes."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.truefit_api.api.v1.http import applications
from src.truefit_core.domain.application import Application
from src.truefit_infra.auth.middleware import TokenPayload, get_current_user

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
JOB_A = uuid.uuid4()
JOB_B = uuid.uuid4()


class FakeAppRepo:
    def __init__(self) -> None:
        self.apps: dict[uuid.UUID, Application] = {}

    async def save(self, a):
        self.apps[a.id] = a

    async def get_by_id(self, application_id):
        return self.apps.get(application_id)

    async def get_by_job_and_candidate(self, job_id, candidate_id):
        return next(
            (a for a in self.apps.values() if a.job_id == job_id and a.candidate_id == candidate_id),
            None,
        )

    async def list_by_job(self, job_id, *, status=None, limit, offset):
        return [a for a in self.apps.values() if a.job_id == job_id]

    async def list_by_candidate(self, candidate_id, *, limit, offset):
        return [a for a in self.apps.values() if a.candidate_id == candidate_id]


class FakeJobRepo:
    async def get_by_id(self, job_id):
        org = {JOB_A: ORG_A, JOB_B: ORG_B}.get(job_id)
        return SimpleNamespace(org_id=org) if org else None


class FakeOwnership:
    def __init__(self) -> None:
        self.profiles: dict[uuid.UUID, uuid.UUID] = {}  # profile id -> user id

    async def owner_user_id(self, candidate_id):
        return self.profiles.get(candidate_id)

    async def profile_id_for_user(self, user_id):
        return next((p for p, u in self.profiles.items() if str(u) == str(user_id)), None)


def user(role: str, org_id=None, user_id=None) -> TokenPayload:
    return TokenPayload(
        str(user_id or uuid.uuid4()), f"{role}@x.io", role, str(org_id) if org_id else None
    )


@pytest.fixture
def world():
    repo, ownership = FakeAppRepo(), FakeOwnership()
    alice_user, bob_user = uuid.uuid4(), uuid.uuid4()
    alice_profile, bob_profile = uuid.uuid4(), uuid.uuid4()
    ownership.profiles[alice_profile] = alice_user
    ownership.profiles[bob_profile] = bob_user
    app_a = Application(job_id=JOB_A, candidate_id=alice_profile)
    app_b = Application(job_id=JOB_B, candidate_id=bob_profile)
    repo.apps = {app_a.id: app_a, app_b.id: app_b}
    return SimpleNamespace(
        repo=repo, ownership=ownership, alice=alice_user, bob=bob_user,
        alice_profile=alice_profile, bob_profile=bob_profile, app_a=app_a, app_b=app_b,
    )


@pytest.fixture
def make_client(world):
    def _make(caller: TokenPayload) -> TestClient:
        app = FastAPI()
        app.include_router(applications.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: caller
        app.dependency_overrides[applications.get_application_repo] = lambda: world.repo
        app.dependency_overrides[applications.get_job_repo] = lambda: FakeJobRepo()
        app.dependency_overrides[applications.get_candidate_ownership] = lambda: world.ownership
        return TestClient(app)

    return _make


# Create


def create_body(job_id, candidate_id):
    return {"job_id": str(job_id), "candidate_id": str(candidate_id)}


def test_candidate_creates_own_application(make_client, world):
    c = make_client(user("candidate", user_id=world.alice))
    r = c.post("/api/v1/applications", json=create_body(JOB_B, world.alice_profile))
    assert r.status_code == 201


def test_candidate_cannot_create_for_someone_else(make_client, world):
    c = make_client(user("candidate", user_id=world.alice))
    r = c.post("/api/v1/applications", json=create_body(JOB_B, world.bob_profile))
    assert r.status_code == 403


def test_recruiter_cannot_create(make_client, world):
    c = make_client(user("recruiter", ORG_A))
    r = c.post("/api/v1/applications", json=create_body(JOB_A, world.bob_profile))
    assert r.status_code == 403


def test_admin_can_create(make_client, world):
    r = make_client(user("admin")).post(
        "/api/v1/applications", json=create_body(JOB_B, world.alice_profile)
    )
    assert r.status_code == 201


# Get


def test_get_allowed_callers(make_client, world):
    url = f"/api/v1/applications/{world.app_a.id}"
    for caller in (user("admin"), user("candidate", user_id=world.alice), user("recruiter", ORG_A)):
        assert make_client(caller).get(url).status_code == 200


def test_get_denied_callers(make_client, world):
    url = f"/api/v1/applications/{world.app_a.id}"
    for caller in (user("candidate", user_id=world.bob), user("recruiter", ORG_B), user("recruiter")):
        assert make_client(caller).get(url).status_code == 403


def test_get_missing_is_404(make_client):
    assert make_client(user("admin")).get(f"/api/v1/applications/{uuid.uuid4()}").status_code == 404


# List


def ids(r):
    return {a["id"] for a in r.json()}


def test_admin_list_unrestricted(make_client, world):
    r = make_client(user("admin")).get(f"/api/v1/applications?job_id={JOB_B}")
    assert r.status_code == 200 and ids(r) == {str(world.app_b.id)}


def test_candidate_list_forced_to_own(make_client, world):
    c = make_client(user("candidate", user_id=world.alice))
    assert ids(c.get(f"/api/v1/applications?job_id={JOB_B}")) == set()
    assert ids(c.get("/api/v1/applications")) == {str(world.app_a.id)}
    assert ids(c.get(f"/api/v1/applications?candidate_id={world.alice_profile}")) == {str(world.app_a.id)}


def test_candidate_list_other_candidate_is_403(make_client, world):
    c = make_client(user("candidate", user_id=world.alice))
    assert c.get(f"/api/v1/applications?candidate_id={world.bob_profile}").status_code == 403


def test_recruiter_list_own_org_job(make_client, world):
    r = make_client(user("recruiter", ORG_A)).get(f"/api/v1/applications?job_id={JOB_A}")
    assert r.status_code == 200 and ids(r) == {str(world.app_a.id)}


def test_recruiter_list_other_org_job_is_403(make_client):
    r = make_client(user("recruiter", ORG_A)).get(f"/api/v1/applications?job_id={JOB_B}")
    assert r.status_code == 403


def test_recruiter_list_by_candidate_is_filtered_to_org(make_client, world):
    extra = Application(job_id=JOB_B, candidate_id=world.alice_profile)
    world.repo.apps[extra.id] = extra
    r = make_client(user("recruiter", ORG_A)).get(
        f"/api/v1/applications?candidate_id={world.alice_profile}"
    )
    assert ids(r) == {str(world.app_a.id)}


# Status and delete


def status_call(c, app):
    return c.patch(f"/api/v1/applications/{app.id}/status", json={"status": "shortlisted"})


def test_status_update_rules(make_client, world):
    assert status_call(make_client(user("recruiter", ORG_A)), world.app_a).status_code == 200
    assert status_call(make_client(user("admin")), world.app_b).status_code == 200
    for caller in (user("recruiter", ORG_B), user("candidate", user_id=world.alice)):
        assert status_call(make_client(caller), world.app_a).status_code == 403


@pytest.mark.parametrize(
    "caller_factory",
    [
        lambda w: user("admin"),
        lambda w: user("candidate", user_id=w.alice),
        lambda w: user("recruiter", ORG_A),
    ],
)
def test_delete_allowed(make_client, world, caller_factory):
    r = make_client(caller_factory(world)).delete(f"/api/v1/applications/{world.app_a.id}")
    assert r.status_code == 204


@pytest.mark.parametrize(
    "caller_factory",
    [lambda w: user("candidate", user_id=w.bob), lambda w: user("recruiter", ORG_B)],
)
def test_delete_denied(make_client, world, caller_factory):
    r = make_client(caller_factory(world)).delete(f"/api/v1/applications/{world.app_a.id}")
    assert r.status_code == 403
