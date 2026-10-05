import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.truefit_api.api.v1.http import orgs as orgs_mod
from src.truefit_core.domain.org import Org, OrgContact, OrgStatus
from src.truefit_infra.auth.middleware import TokenPayload, get_current_user

FOUNDER = uuid.uuid4()


class FakeOrgRepo:
    def __init__(self):
        self.orgs = {}

    async def exists_by_slug(self, slug):
        return any(o.slug == slug for o in self.orgs.values())

    async def save(self, org):
        self.orgs[org.id] = org

    async def get_by_id(self, org_id):
        return self.orgs.get(org_id)

    async def get_by_slug(self, slug):
        return next((o for o in self.orgs.values() if o.slug == slug), None)

    async def list_all(self, limit=20, offset=0):
        return list(self.orgs.values())

    async def list_by_status(self, s, limit=20, offset=0):
        return [o for o in self.orgs.values() if o.status == s]

    async def delete(self, org_id):
        self.orgs.pop(org_id, None)


def make_org(slug="acme", status=OrgStatus.ACTIVE):
    return Org(name="Acme", slug=slug, contact=OrgContact(email="a@acme.com"),
               created_by=FOUNDER, status=status)


def actor(role, org_id=None, user_id=None):
    return TokenPayload(str(user_id or uuid.uuid4()), "a@example.com", role,
                        str(org_id) if org_id else None)


@pytest.fixture
def ctx():
    repo = FakeOrgRepo()
    org = make_org()
    repo.orgs[org.id] = org
    app = FastAPI()
    app.include_router(orgs_mod.router, prefix="/api/v1")
    app.dependency_overrides[orgs_mod.get_org_repo] = lambda: repo

    class C:
        pass

    c = C()
    c.repo, c.org, c.client = repo, org, TestClient(app)
    c.as_user = lambda p: app.dependency_overrides.__setitem__(get_current_user, lambda: p)
    return c


CREATE = {"name": "New Co", "slug": "new-co", "contact": {"email": "n@co.com"}}


@pytest.mark.parametrize("role,expected", [
    ("candidate", 403), ("recruiter", 201), ("admin", 201)])
def test_create_roles(ctx, role, expected):
    ctx.as_user(actor(role))
    assert ctx.client.post("/api/v1/orgs", json=CREATE).status_code == expected


def test_create_forces_created_by(ctx):
    me = uuid.uuid4()
    ctx.as_user(actor("recruiter", user_id=me))
    r = ctx.client.post("/api/v1/orgs", json={**CREATE, "created_by": str(uuid.uuid4())})
    assert r.status_code == 201
    assert r.json()["created_by"] == str(me)
    # and created_by may be omitted entirely
    r = ctx.client.post("/api/v1/orgs", json={**CREATE, "slug": "other-co"})
    assert r.json()["created_by"] == str(me)


@pytest.mark.parametrize("role", ["candidate", "recruiter", "admin"])
def test_reads_open_to_any_authenticated_user(ctx, role):
    ctx.as_user(actor(role))
    assert ctx.client.get(f"/api/v1/orgs/{ctx.org.id}").status_code == 200
    assert ctx.client.get("/api/v1/orgs/slug/acme").status_code == 200
    assert ctx.client.get("/api/v1/orgs").status_code == 200


def mutations(org_id):
    return [
        ("patch", f"/api/v1/orgs/{org_id}", {"name": "Renamed"}),
        ("patch", f"/api/v1/orgs/{org_id}/billing", {"plan": "free"}),
        ("post", f"/api/v1/orgs/{org_id}/suspend", None),
        ("post", f"/api/v1/orgs/{org_id}/reactivate", None),
        ("post", f"/api/v1/orgs/{org_id}/deactivate", None),
        ("delete", f"/api/v1/orgs/{org_id}", None),
    ]


@pytest.mark.parametrize("idx", range(6))
def test_mutations_denied_for_outsiders(ctx, idx):
    method, url, body = mutations(ctx.org.id)[idx]
    for p in (actor("candidate", ctx.org.id),
              actor("recruiter", uuid.uuid4()),
              actor("recruiter")):
        ctx.as_user(p)
        r = getattr(ctx.client, method)(url, **({"json": body} if body else {}))
        assert r.status_code == 403, (method, url, p.role)
    assert ctx.org.name == "Acme" and ctx.org.status == OrgStatus.ACTIVE
    assert ctx.org.id in ctx.repo.orgs


@pytest.mark.parametrize("role_is_admin", [True, False])
def test_mutations_allowed_for_admin_and_own_recruiter(ctx, role_is_admin):
    p = actor("admin") if role_is_admin else actor("recruiter", ctx.org.id)
    ctx.as_user(p)
    c, oid = ctx.client, ctx.org.id
    assert c.patch(f"/api/v1/orgs/{oid}", json={"name": "Renamed"}).status_code == 200
    assert c.patch(f"/api/v1/orgs/{oid}/billing", json={"plan": "free"}).status_code == 200
    assert c.post(f"/api/v1/orgs/{oid}/suspend").status_code == 200
    assert c.post(f"/api/v1/orgs/{oid}/reactivate").status_code == 200
    assert c.post(f"/api/v1/orgs/{oid}/deactivate").status_code == 200
    assert c.delete(f"/api/v1/orgs/{oid}").status_code == 204


def test_denied_does_not_leak_existence(ctx):
    ctx.as_user(actor("recruiter", uuid.uuid4()))
    r = ctx.client.delete(f"/api/v1/orgs/{uuid.uuid4()}")
    assert r.status_code == 403
