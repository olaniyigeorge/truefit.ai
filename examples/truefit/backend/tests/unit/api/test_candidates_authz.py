"""Authorization rules for /api/v1/candidates, using in-memory fakes."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.truefit_api.api.v1.http import candidates as mod
from src.truefit_core.domain.candidate import Candidate, ContactInfo
from src.truefit_infra.auth.middleware import TokenPayload, get_current_user

OWNER = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


class FakeRepo:
    def __init__(self, candidates):
        self.items = {c.id: c for c in candidates}

    async def get_by_id(self, cid):
        return self.items.get(cid)

    async def get_by_email(self, email):
        return next((c for c in self.items.values() if c.contact.email == email), None)

    async def list_all(self, *, limit=50, offset=0):
        return list(self.items.values())

    async def save(self, c):
        self.items[c.id] = c


def make_candidate(user_id=OWNER, with_resume=False):
    c = Candidate(
        full_name="Ada Lovelace",
        contact=ContactInfo(email="ada@example.com"),
        user_id=uuid.UUID(user_id),
    )
    if with_resume:
        from datetime import datetime, timezone

        from src.truefit_core.domain.candidate import ResumeRef

        c.attach_resume(
            ResumeRef("k/ada.pdf", "ada.pdf", datetime.now(timezone.utc))
        )
    return c


def user(role, uid=OTHER, email="x@example.com", org=None):
    return TokenPayload(user_id=uid, email=email, role=role, org_id=org)


@pytest.fixture
def cand():
    return make_candidate(with_resume=True)


@pytest.fixture
def repo(cand):
    return FakeRepo([cand])


def client_for(repo, caller):
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1")
    app.dependency_overrides[mod.get_candidate_repo] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: caller
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


ADMIN = user("admin")
RECRUITER = user("recruiter", org=str(uuid.uuid4()))
OWNER_U = user("candidate", uid=OWNER, email="ada@example.com")
STRANGER = user("candidate", uid=OTHER, email="eve@example.com")


@pytest.mark.parametrize(
    "caller,code",
    [(ADMIN, 200), (RECRUITER, 200), (OWNER_U, 200), (STRANGER, 403)],
)
async def test_get_and_resume_read(repo, cand, caller, code):
    async with client_for(repo, caller) as c:
        assert (await c.get(f"/api/v1/candidates/{cand.id}")).status_code == code
        assert (await c.get(f"/api/v1/candidates/{cand.id}/resume")).status_code == code


async def test_denied_get_leaks_nothing(repo, cand):
    async with client_for(repo, STRANGER) as c:
        r = await c.get(f"/api/v1/candidates/{cand.id}")
    assert "Ada" not in r.text and "ada@example.com" not in r.text


@pytest.mark.parametrize(
    "caller,code",
    [(ADMIN, 200), (RECRUITER, 200), (OWNER_U, 403), (STRANGER, 403)],
)
async def test_list(repo, caller, code):
    async with client_for(repo, caller) as c:
        assert (await c.get("/api/v1/candidates")).status_code == code


@pytest.mark.parametrize(
    "caller,code",
    [(ADMIN, 200), (OWNER_U, 200), (RECRUITER, 403), (STRANGER, 403)],
)
async def test_patch(repo, cand, caller, code):
    async with client_for(repo, caller) as c:
        r = await c.patch(f"/api/v1/candidates/{cand.id}", json={"full_name": "Ada L"})
    assert r.status_code == code


@pytest.mark.parametrize(
    "caller,code",
    [(ADMIN, 204), (OWNER_U, 204), (RECRUITER, 403), (STRANGER, 403)],
)
async def test_delete_resume(repo, cand, caller, code):
    async with client_for(repo, caller) as c:
        r = await c.delete(f"/api/v1/candidates/{cand.id}/resume")
    assert r.status_code == code


@pytest.mark.parametrize(
    "caller,code",
    [(ADMIN, 200), (OWNER_U, 200), (RECRUITER, 403), (STRANGER, 403)],
)
async def test_upload_resume(repo, cand, caller, code):
    files = {"file": ("cv.pdf", b"%PDF-1.4", "application/pdf")}
    async with client_for(repo, caller) as c:
        r = await c.post(f"/api/v1/candidates/{cand.id}/resume", files=files)
    assert r.status_code == code


def payload(**extra):
    return {"full_name": "Grace Hopper", "email": "grace@example.com", **extra}


async def test_create_admin_ok():
    repo = FakeRepo([])
    async with client_for(repo, ADMIN) as c:
        r = await c.post("/api/v1/candidates", json=payload(user_id=OTHER))
    assert r.status_code == 201


async def test_create_candidate_for_self_sets_owner():
    repo = FakeRepo([])
    me = user("candidate", uid=OWNER, email="Grace@Example.com")
    async with client_for(repo, me) as c:
        r = await c.post("/api/v1/candidates", json=payload())
    assert r.status_code == 201
    assert r.json()["user_id"] == OWNER


async def test_create_candidate_explicit_own_user_id_ok():
    me = user("candidate", uid=OWNER, email="grace@example.com")
    async with client_for(FakeRepo([]), me) as c:
        r = await c.post("/api/v1/candidates", json=payload(user_id=OWNER))
    assert r.status_code == 201


async def test_create_candidate_other_user_id_denied():
    me = user("candidate", uid=OWNER, email="grace@example.com")
    async with client_for(FakeRepo([]), me) as c:
        r = await c.post("/api/v1/candidates", json=payload(user_id=OTHER))
    assert r.status_code == 403


async def test_create_candidate_other_email_denied():
    me = user("candidate", uid=OWNER, email="someone@example.com")
    async with client_for(FakeRepo([]), me) as c:
        r = await c.post("/api/v1/candidates", json=payload())
    assert r.status_code == 403


async def test_create_recruiter_denied():
    async with client_for(FakeRepo([]), RECRUITER) as c:
        r = await c.post("/api/v1/candidates", json=payload())
    assert r.status_code == 403
