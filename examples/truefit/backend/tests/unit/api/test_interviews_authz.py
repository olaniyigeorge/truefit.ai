"""Authorization rules for /api/v1/interviews, using in-memory fakes."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.truefit_api.api.v1.http import interviews as mod
from src.truefit_core.domain.candidate import Candidate, ContactInfo
from src.truefit_core.domain.interview import Interview
from src.truefit_infra.auth.middleware import TokenPayload, get_current_user

ORG_A = str(uuid.uuid4())
ORG_B = str(uuid.uuid4())
U_OWNER = str(uuid.uuid4())
U_OTHER = str(uuid.uuid4())


class Repo:
    def __init__(self, items=()):
        self.items = {i.id: i for i in items}

    async def get_by_id(self, i):
        return self.items.get(i)

    async def save(self, x):
        self.items[x.id] = x


class InterviewRepo(Repo):
    async def list_by_candidate(self, cid, *, limit=50, offset=0):
        return [i for i in self.items.values() if i.candidate_id == cid]

    async def list_by_job(self, jid, *, limit=50, offset=0):
        return [i for i in self.items.values() if i.job_id == jid]


def mk_candidate(user_id):
    return Candidate(
        full_name="Ada",
        contact=ContactInfo(email="a@example.com"),
        user_id=uuid.UUID(user_id),
    )


def mk_interview(job_id, cand_id, org):
    return Interview(
        job_id=job_id,
        candidate_id=cand_id,
        org_id=uuid.UUID(org),
        max_questions=3,
        max_duration_minutes=10,
    )


class World:
    def __init__(self):
        self.cand = mk_candidate(U_OWNER)
        self.other_cand = mk_candidate(U_OTHER)
        self.job_a = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=uuid.UUID(ORG_A),
            interview_config=SimpleNamespace(max_questions=3, max_duration_minutes=10),
            assert_open_for_interviews=lambda: None,
        )
        self.job_b = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=uuid.UUID(ORG_B),
            interview_config=self.job_a.interview_config,
            assert_open_for_interviews=lambda: None,
        )
        self.mine = mk_interview(self.job_a.id, self.cand.id, ORG_A)
        self.mine_b = mk_interview(self.job_b.id, self.cand.id, ORG_B)
        self.theirs = mk_interview(self.job_a.id, self.other_cand.id, ORG_A)
        self.interviews = InterviewRepo([self.mine, self.mine_b, self.theirs])
        self.jobs = Repo([self.job_a, self.job_b])
        self.cands = Repo([self.cand, self.other_cand])

    def client(self, caller):
        app = FastAPI()
        app.include_router(mod.router, prefix="/api/v1")
        app.dependency_overrides[mod.get_interview_repo] = lambda: self.interviews
        app.dependency_overrides[mod.get_job_repo] = lambda: self.jobs
        app.dependency_overrides[mod.get_candidate_repo] = lambda: self.cands
        app.dependency_overrides[get_current_user] = lambda: caller
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def user(role, uid=None, org=None):
    return TokenPayload(
        user_id=uid or str(uuid.uuid4()), email="x@example.com", role=role, org_id=org
    )


ADMIN = user("admin")
OWNER = user("candidate", U_OWNER)
STRANGER = user("candidate", U_OTHER)
REC_A = user("recruiter", org=ORG_A)
REC_B = user("recruiter", org=ORG_B)


@pytest.fixture
def w():
    return World()


@pytest.mark.parametrize(
    "caller,code",
    [(ADMIN, 200), (OWNER, 200), (REC_A, 200), (REC_B, 403), (STRANGER, 403)],
)
async def test_get_and_transcript(w, caller, code):
    async with w.client(caller) as c:
        assert (await c.get(f"/api/v1/interviews/{w.mine.id}")).status_code == code
        r = await c.get(f"/api/v1/interviews/{w.mine.id}/transcript")
        assert r.status_code == code


@pytest.mark.parametrize(
    "caller,code",
    [(ADMIN, 200), (OWNER, 200), (REC_A, 403), (REC_B, 403), (STRANGER, 403)],
)
async def test_abandon(w, caller, code):
    async with w.client(caller) as c:
        r = await c.post(f"/api/v1/interviews/{w.mine.id}/abandon", json={})
    assert r.status_code == code


@pytest.mark.parametrize(
    "caller,code",
    [(ADMIN, 201), (OWNER, 201), (STRANGER, 403), (REC_A, 403)],
)
async def test_create(w, caller, code):
    body = {"job_id": str(w.job_a.id), "candidate_id": str(w.cand.id)}
    async with w.client(caller) as c:
        r = await c.post("/api/v1/interviews", json=body)
    assert r.status_code == code


def ids(r):
    return {row["id"] for row in r.json()}


async def test_list_admin_unrestricted(w):
    async with w.client(ADMIN) as c:
        r = await c.get(f"/api/v1/interviews?job_id={w.job_a.id}")
    assert ids(r) == {str(w.mine.id), str(w.theirs.id)}


async def test_list_candidate_own_ok(w):
    async with w.client(OWNER) as c:
        r = await c.get(f"/api/v1/interviews?candidate_id={w.cand.id}")
    assert r.status_code == 200
    assert ids(r) == {str(w.mine.id), str(w.mine_b.id)}


async def test_list_candidate_mismatching_param_denied(w):
    async with w.client(OWNER) as c:
        r = await c.get(f"/api/v1/interviews?candidate_id={w.other_cand.id}")
    assert r.status_code == 403


async def test_list_candidate_job_filter_only_returns_own(w):
    async with w.client(OWNER) as c:
        r = await c.get(f"/api/v1/interviews?job_id={w.job_a.id}")
    assert r.status_code == 200
    assert ids(r) == {str(w.mine.id)}


async def test_list_recruiter_own_org_job(w):
    async with w.client(REC_A) as c:
        r = await c.get(f"/api/v1/interviews?job_id={w.job_a.id}")
    assert ids(r) == {str(w.mine.id), str(w.theirs.id)}


async def test_list_recruiter_other_org_job_denied(w):
    async with w.client(REC_B) as c:
        r = await c.get(f"/api/v1/interviews?job_id={w.job_a.id}")
    assert r.status_code == 403


async def test_list_recruiter_by_candidate_filters_to_org(w):
    async with w.client(REC_A) as c:
        r = await c.get(f"/api/v1/interviews?candidate_id={w.cand.id}")
    assert ids(r) == {str(w.mine.id)}
