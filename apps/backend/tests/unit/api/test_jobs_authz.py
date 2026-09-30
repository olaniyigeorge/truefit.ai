"""Authorization rules for the jobs router, run against in-memory fakes."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.truefit_api.api.v1.http import jobs
from src.truefit_core.domain.job import ExperienceLevel, Job, JobRequirements, SkillRequirement
from src.truefit_infra.auth.middleware import TokenPayload, get_current_user

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


class FakeJobRepo:
    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, Job] = {}

    async def save(self, job: Job) -> None:
        self.jobs[job.id] = job

    async def get_by_id(self, job_id):
        return self.jobs.get(job_id)

    async def delete(self, job_id) -> None:
        self.jobs.pop(job_id, None)

    async def list_all_active(self, *, limit, offset):
        return []

    async def get_by_company(self, org_id, *, limit, offset):
        return [j for j in self.jobs.values() if j.org_id == org_id]


def make_job(org_id) -> Job:
    return Job(
        org_id=org_id,
        created_by=uuid.uuid4(),
        title="Engineer",
        description="A long enough description",
        requirements=JobRequirements(experience_level=ExperienceLevel.MID),
        skills=[SkillRequirement(name="python")],
    )


def user(role: str, org_id=None) -> TokenPayload:
    return TokenPayload(str(uuid.uuid4()), f"{role}@x.io", role, str(org_id) if org_id else None)


@pytest.fixture
def repo() -> FakeJobRepo:
    return FakeJobRepo()


@pytest.fixture
def make_client(repo):
    def _make(caller: TokenPayload) -> TestClient:
        app = FastAPI()
        app.include_router(jobs.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: caller
        app.dependency_overrides[jobs.get_job_repo] = lambda: repo
        return TestClient(app)

    return _make


def create_body(org_id, created_by=None) -> dict:
    return {
        "org_id": str(org_id),
        "created_by": str(created_by or uuid.uuid4()),
        "title": "Backend Engineer",
        "description": "Build and run services",
        "requirements": {"experience_level": "mid"},
        "skills": [{"name": "python"}],
    }


# Reads


@pytest.mark.parametrize("role", ["candidate", "recruiter", "admin"])
def test_any_authenticated_user_can_read(make_client, repo, role):
    job = make_job(ORG_A)
    repo.jobs[job.id] = job
    client = make_client(user(role, ORG_B))
    assert client.get(f"/api/v1/jobs/{job.id}").status_code == 200
    assert client.get("/api/v1/jobs/active").status_code == 200
    assert client.get(f"/api/v1/jobs?org_id={ORG_A}").status_code == 200


# Create


def test_candidate_cannot_create(make_client):
    r = make_client(user("candidate", ORG_A)).post("/api/v1/jobs", json=create_body(ORG_A))
    assert r.status_code == 403


def test_recruiter_creates_in_own_org_and_created_by_is_forced(make_client, repo):
    caller = user("recruiter", ORG_A)
    r = make_client(caller).post("/api/v1/jobs", json=create_body(ORG_A))
    assert r.status_code == 201
    assert r.json()["created_by"] == caller.user_id
    assert len(repo.jobs) == 1


def test_recruiter_cannot_create_in_other_org(make_client, repo):
    r = make_client(user("recruiter", ORG_A)).post("/api/v1/jobs", json=create_body(ORG_B))
    assert r.status_code == 403
    assert not repo.jobs


def test_admin_creates_in_any_org(make_client):
    caller = user("admin")
    r = make_client(caller).post("/api/v1/jobs", json=create_body(ORG_B))
    assert r.status_code == 201
    assert r.json()["created_by"] == caller.user_id


# Mutations

MUTATIONS = [
    ("patch", "/api/v1/jobs/{id}", {"description": "An updated description"}),
    ("post", "/api/v1/jobs/{id}/activate", None),
    ("post", "/api/v1/jobs/{id}/pause", None),
    ("post", "/api/v1/jobs/{id}/close", None),
    ("delete", "/api/v1/jobs/{id}", None),
]


def call(client, method, url, body):
    return getattr(client, method)(url, **({"json": body} if body else {}))


@pytest.mark.parametrize("method,url,body", MUTATIONS)
def test_candidate_and_foreign_recruiter_denied(make_client, repo, method, url, body):
    job = make_job(ORG_A)
    repo.jobs[job.id] = job
    for caller in (user("candidate", ORG_A), user("recruiter", ORG_B), user("recruiter")):
        r = call(make_client(caller), method, url.format(id=job.id), body)
        assert r.status_code == 403
    assert job.id in repo.jobs


@pytest.mark.parametrize("method,url,body", MUTATIONS)
def test_org_recruiter_and_admin_pass_authorization(make_client, repo, method, url, body):
    for caller in (user("recruiter", ORG_A), user("admin")):
        job = make_job(ORG_A)
        repo.jobs[job.id] = job
        r = call(make_client(caller), method, url.format(id=job.id), body)
        # 400 is a state-machine rejection (e.g. pausing a DRAFT), i.e. authorized.
        assert r.status_code in (200, 204, 400)


@pytest.mark.parametrize("method,url,body", MUTATIONS)
def test_missing_job_is_404(make_client, method, url, body):
    r = call(make_client(user("recruiter", ORG_A)), method, url.format(id=uuid.uuid4()), body)
    assert r.status_code == 404
