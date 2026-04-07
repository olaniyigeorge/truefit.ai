"""
tests/fixtures/seed_data.py

Seeds resources in dependency order (FULLY SELF-CONTAINED):
  1) Users (admin + recruiter)      -> required for orgs.created_by and jobs.created_by
  2) Orgs                           -> requires created_by user
  3) Candidates (as users + profiles) -> aligns to the DB model: users + candidate_profiles
  4) Jobs                           -> requires org_id + created_by
  5) Applications                   -> requires job + candidate_profile
  6) Interview Sessions (+ optional turns) -> requires application

USAGE

  uvicorn src.truefit_api.main:app --reload --port 8000
  python -m tests.fixtures.seed_data
  python -m tests.fixtures.seed_data --curl
  python -m tests.fixtures.seed_data --no-activate
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_URL = "http://localhost:8000/api/v1"

# If you have auth, set a token here and add headers in client.
DEFAULT_HEADERS = {"Content-Type": "application/json"}


# ── Users ─
# We create these first, then use returned ids for orgs/jobs.
USER_PAYLOADS: list[dict[str, Any]] = [
    {
        "email": "seed.admin@truefit.ai",
        "display_name": "Seed Admin",
        "role": "admin",
        "auth_provider": "seed",
        "provider_subject": "seed-admin",
    },
    {
        "email": "seed.recruiter@truefit.ai",
        "display_name": "Seed Recruiter",
        "role": "recruiter",
        "auth_provider": "seed",
        "provider_subject": "seed-recruiter",
    },
]


# ── Orgs
def make_org_payloads(created_by: str) -> list[dict[str, Any]]:
    return [
        {
            "name": "Truefit Labs",
            "slug": "truefit-labs",
            "created_by": created_by,
            "contact": {
                "email": "hiring@truefit.ai",
                "phone": "+1-415-000-0001",
                "website": "https://truefit.ai",
            },
            "description": "AI-powered hiring platform automating technical interviews.",
            "industry": "Technology",
            "headcount": "11-50",
            "billing": {
                "plan": "growth",
                "max_active_jobs": 20,
                "max_interviews_per_month": 500,
            },
        },
        {
            "name": "Acme Recruiting",
            "slug": "acme-recruiting",
            "created_by": created_by,
            "contact": {
                "email": "ops@acme-recruiting.com",
                "website": "https://acme-recruiting.com",
            },
            "description": "Full-service technical recruiting agency.",
            "industry": "Staffing & Recruiting",
            "headcount": "51-200",
            "billing": {
                "plan": "starter",
                "max_active_jobs": 5,
                "max_interviews_per_month": 100,
            },
        },
    ]


# ── Jobs (org_id injected at runtime) ─
def make_job_payloads(org_id: str, created_by: str) -> list[dict[str, Any]]:
    return [
        {
            "org_id": org_id,
            "created_by": created_by,
            "title": "Senior Backend Engineer",
            "description": (
                "We are looking for a Senior Backend Engineer to join our platform team. "
                "You will design and build the APIs powering Truefit's AI interview engine, "
                "working with Python, FastAPI, PostgreSQL, and Redis at scale."
            ),
            "requirements": {
                "experience_level": "senior",
                "min_total_years": 5,
                "education": "Bachelor's in Computer Science or equivalent",
                "certifications": [],
                "location": "Remote - Global",
                "work_arrangement": "remote",
            },
            "skills": [
                {"name": "Python", "required": True, "weight": 1.0, "min_years": 4},
                {"name": "FastAPI", "required": True, "weight": 0.9, "min_years": 2},
                {"name": "PostgreSQL", "required": True, "weight": 0.8, "min_years": 3},
                {"name": "Redis", "required": True, "weight": 0.7, "min_years": 2},
                {
                    "name": "System Design",
                    "required": True,
                    "weight": 1.0,
                    "min_years": 3,
                },
                {"name": "Docker", "required": False, "weight": 0.6},
                {"name": "Kubernetes", "required": False, "weight": 0.5},
            ],
            "interview_config": {
                "max_questions": 8,
                "max_duration_minutes": 25,
                "topics": ["system design", "python", "databases", "behavioural"],
                "custom_instructions": (
                    "Focus on distributed systems and async Python. "
                    "Ask at least one question about handling high-concurrency workloads."
                ),
            },
        },
        {
            "org_id": org_id,
            "created_by": created_by,
            "title": "ML Engineer - Inference",
            "description": (
                "Join our AI team to build and optimise the inference pipelines "
                "powering Truefit's real-time interview agent."
            ),
            "requirements": {
                "experience_level": "mid",
                "min_total_years": 3,
                "education": "Master's or PhD in ML/AI preferred",
                "certifications": ["Google Cloud Professional ML Engineer"],
                "location": "Remote - US/EU",
                "work_arrangement": "hybrid",
            },
            "skills": [
                {"name": "Python", "required": True, "weight": 1.0, "min_years": 3},
                {"name": "PyTorch", "required": True, "weight": 0.9, "min_years": 2},
                {
                    "name": "LLM Prompting",
                    "required": True,
                    "weight": 1.0,
                    "min_years": 1,
                },
                {"name": "Vertex AI", "required": False, "weight": 0.8},
            ],
            "interview_config": {
                "max_questions": 10,
                "max_duration_minutes": 30,
                "topics": [
                    "ML fundamentals",
                    "LLM architecture",
                    "inference",
                    "behavioural",
                ],
            },
        },
        {
            "org_id": org_id,
            "created_by": created_by,
            "title": "Junior Frontend Engineer",
            "description": "Build the candidate-facing interview UI using React and TypeScript.",
            "requirements": {
                "experience_level": "junior",
                "min_total_years": 1,
                "location": "Remote",
                "work_arrangement": "remote",
            },
            "skills": [
                {"name": "React", "required": True, "weight": 1.0, "min_years": 1},
                {"name": "TypeScript", "required": True, "weight": 0.9, "min_years": 1},
                {"name": "WebRTC", "required": False, "weight": 0.8},
            ],
            "interview_config": {
                "max_questions": 6,
                "max_duration_minutes": 20,
                "topics": ["react", "typescript", "behavioural"],
                "custom_instructions": "Keep questions approachable - this is a junior role.",
            },
        },
    ]


# ── Candidates (align to the DB: users + candidate_profiles) ───
CANDIDATE_USER_PAYLOADS: list[dict[str, Any]] = [
    {
        "email": "amara.nwosu@example.com",
        "display_name": "Amara Nwosu",
        "role": "candidate",
        "auth_provider": "seed",
        "provider_subject": "seed-candidate-amara",
    },
    {
        "email": "david.chen@example.com",
        "display_name": "David Chen",
        "role": "candidate",
        "auth_provider": "seed",
        "provider_subject": "seed-candidate-david",
    },
    {
        "email": "sofia.martinez@example.com",
        "display_name": "Sofia Martínez",
        "role": "candidate",
        "auth_provider": "seed",
        "provider_subject": "seed-candidate-sofia",
    },
]

CANDIDATE_PROFILE_PAYLOADS_BY_EMAIL: dict[str, dict[str, Any]] = {
    "amara.nwosu@example.com": {
        "headline": "Backend Engineer",
        "bio": "API + distributed systems engineer.",
        "location": "Lagos, NG",
        "years_experience": 5,
        "skills": ["Python", "FastAPI", "PostgreSQL", "Redis"],
    },
    "david.chen@example.com": {
        "headline": "ML Engineer",
        "bio": "Inference + LLM systems.",
        "location": "San Francisco, US",
        "years_experience": 4,
        "skills": ["Python", "PyTorch", "LLMs"],
    },
    "sofia.martinez@example.com": {
        "headline": "Frontend Engineer",
        "bio": "React + TypeScript UI.",
        "location": "Madrid, ES",
        "years_experience": 2,
        "skills": ["React", "TypeScript"],
    },
}


# ── Helpers ─────
@dataclass
class SeededResources:
    users: list[dict] = field(default_factory=list)
    orgs: list[dict] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    candidate_users: list[dict] = field(default_factory=list)
    candidate_profiles: list[dict] = field(default_factory=list)
    applications: list[dict] = field(default_factory=list)
    interviews: list[dict] = field(default_factory=list)


async def _health(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get("/health")
        print(f"Server: OK (status {r.status_code})\n")
        return r.status_code == 200
    except httpx.ConnectError:
        print(
            "\n❌  Cannot connect to server.\n"
            f"    Is the FastAPI app running at {BASE_URL}?\n\n"
            "    Start it with:\n"
            "      uvicorn src.truefit_api.main:app --reload --port 8000\n"
        )
        return False


async def _ensure_user(client: httpx.AsyncClient, payload: dict[str, Any]) -> dict:
    """
    Creates a user, or fetches it by email if it already exists.
    Requires:
      POST /users
      GET  /users/by-email/{email}
    """
    r = await client.post("/users", json=payload)
    if r.status_code in (200, 201):
        return r.json()

    # If API uses 409 conflict on duplicate email:
    if r.status_code == 409:
        r2 = await client.get(f"/users/by-email/{payload['email']}")
        r2.raise_for_status()
        return r2.json()

    # If API uses 422 validation, surface it clearly.
    if r.status_code == 422:
        raise RuntimeError(f"User validation error: {r.json().get('detail')}")

    raise RuntimeError(f"User create failed ({r.status_code}): {r.text}")


async def _ensure_org(client: httpx.AsyncClient, payload: dict[str, Any]) -> dict:
    r = await client.post("/orgs", json=payload)
    if r.status_code in (200, 201):
        return r.json()

    if r.status_code == 409:
        r2 = await client.get(f"/orgs/slug/{payload['slug']}")
        r2.raise_for_status()
        return r2.json()

    if r.status_code == 422:
        raise RuntimeError(f"Org validation error: {r.json().get('detail')}")

    raise RuntimeError(f"Org create failed ({r.status_code}): {r.text}")


async def _create_job(client: httpx.AsyncClient, payload: dict[str, Any]) -> dict:
    r = await client.post("/jobs", json=payload)
    if r.status_code in (200, 201):
        return r.json()
    if r.status_code == 422:
        raise RuntimeError(f"Job validation error: {r.json().get('detail')}")
    raise RuntimeError(f"Job create failed ({r.status_code}): {r.text}")


async def _activate_job(client: httpx.AsyncClient, job_id: str) -> dict:
    r = await client.post(f"/jobs/{job_id}/activate")
    if r.status_code == 200:
        return r.json()
    # keep non-fatal
    return {"id": job_id, "status": "draft", "activation_error": r.text}


async def _ensure_candidate_profile(
    client: httpx.AsyncClient,
    user_id: str,
    email: str,
) -> dict:
    """
    Creates candidate profile for a given user_id.
    Requires:
      POST /candidate-profiles
      GET  /candidate-profiles/by-user/{user_id}
    Adjust endpoints to match the API.
    """
    payload = {"user_id": user_id, **CANDIDATE_PROFILE_PAYLOADS_BY_EMAIL[email]}
    r = await client.post("/candidate-profiles", json=payload)
    if r.status_code in (200, 201):
        return r.json()

    if r.status_code == 409:
        r2 = await client.get(f"/candidate-profiles/by-user/{user_id}")
        r2.raise_for_status()
        return r2.json()

    if r.status_code == 422:
        raise RuntimeError(
            f"CandidateProfile validation error: {r.json().get('detail')}"
        )

    raise RuntimeError(f"CandidateProfile create failed ({r.status_code}): {r.text}")


async def _ensure_application(
    client: httpx.AsyncClient, job_id: str, candidate_profile_id: str
) -> dict:
    """
    Requires:
      POST /applications
      GET  /applications?job_id=...&candidate_id=... (or a dedicated endpoint)
    """
    payload = {
        "job_id": job_id,
        "candidate_id": candidate_profile_id,
        "source": "applied",
    }
    r = await client.post("/applications", json=payload)
    if r.status_code in (200, 201):
        return r.json()

    if r.status_code == 409:
        r2 = await client.get(
            f"/applications?job_id={job_id}&candidate_id={candidate_profile_id}"
        )
        r2.raise_for_status()
        # assume list
        data = r2.json()
        return data[0] if isinstance(data, list) and data else data

    if r.status_code == 422:
        raise RuntimeError(f"Application validation error: {r.json().get('detail')}")

    raise RuntimeError(f"Application create failed ({r.status_code}): {r.text}")


async def _start_interview(
    client: httpx.AsyncClient, job_id: str, candidate_profile_id: str
) -> dict:
    # existing endpoint
    r = await client.post(
        "/interviews", json={"job_id": job_id, "candidate_id": candidate_profile_id}
    )
    if r.status_code in (200, 201):
        return r.json()
    raise RuntimeError(f"Interview start failed ({r.status_code}): {r.text}")


# ── Seeder
async def seed(activate_jobs: bool = True) -> SeededResources:
    resources = SeededResources()
    print(f"\nConnecting to {BASE_URL} ...")

    async with httpx.AsyncClient(
        base_url=BASE_URL, timeout=20.0, headers=DEFAULT_HEADERS
    ) as client:
        if not await _health(client):
            return resources

        # 1) Users
        print("── Step 1: Users ─")
        for p in USER_PAYLOADS:
            u = await _ensure_user(client, p)
            print(f"  ✓  User: {u['id']}  {u.get('email')}  role={u.get('role')}")
            resources.users.append(u)

        admin_user = next(u for u in resources.users if u.get("role") == "admin")
        recruiter_user = next(
            u for u in resources.users if u.get("role") == "recruiter"
        )

        # 2) Orgs (created_by = admin)
        print("\n── Step 2: Orgs ──")
        for payload in make_org_payloads(created_by=admin_user["id"]):
            org = await _ensure_org(client, payload)
            print(f"  ✓  Org: {org['id']}  [{org['name']}]  slug={org['slug']}")
            resources.orgs.append(org)

        primary_org = resources.orgs[0]

        # 3) Candidate users + profiles
        print("\n── Step 3: Candidates (users + profiles) ")
        for p in CANDIDATE_USER_PAYLOADS:
            u = await _ensure_user(client, p)
            resources.candidate_users.append(u)
            print(f"  ✓  Candidate user: {u['id']}  {u.get('email')}")

            prof = await _ensure_candidate_profile(
                client, user_id=u["id"], email=u["email"]
            )
            resources.candidate_profiles.append(prof)
            print(f"     -> Profile: {prof['id']}  user_id={prof['user_id']}")

        # 4) Jobs (created_by = recruiter; org_id = primary org)
        print("\n── Step 4: Jobs ──")
        for payload in make_job_payloads(
            primary_org["id"], created_by=recruiter_user["id"]
        ):
            job = await _create_job(client, payload)
            print(f"  ✓  Job: {job['id']}  [{job['title']}]  status={job['status']}")

            if activate_jobs:
                job2 = await _activate_job(client, job["id"])
                if job2.get("status") == "active":
                    job = job2
                    print(f"     -> Activated  status={job['status']}")
                else:
                    print(
                        f"     ⚠  Could not activate ({job2.get('activation_error', 'unknown')})"
                    )

            resources.jobs.append(job)

        # 5) Applications + 6) Interviews
        print("\n── Step 5/6: Applications + Interviews ─")
        active_jobs = [j for j in resources.jobs if j.get("status") == "active"]
        if not active_jobs:
            print("  ⚠  No active jobs - skipping applications/interviews")
            return resources

        first_job = active_jobs[0]
        for prof in resources.candidate_profiles[:2]:
            app = await _ensure_application(
                client, job_id=first_job["id"], candidate_profile_id=prof["id"]
            )
            resources.applications.append(app)
            print(
                f"  ✓  Application: {app.get('id')}  job={first_job['id']} candidate={prof['id']}"
            )

            interview = await _start_interview(
                client, job_id=first_job["id"], candidate_profile_id=prof["id"]
            )
            resources.interviews.append(interview)
            print(f"     -> Interview: {interview['id']}")

    # Summary
    print(f"""
── Seed complete ──
   Users:              {len(resources.users)}
   Orgs:               {len(resources.orgs)}
   Candidate users:    {len(resources.candidate_users)}
   Candidate profiles: {len(resources.candidate_profiles)}
   Jobs:               {len(resources.jobs)}
   Applications:       {len(resources.applications)}
   Interviews:         {len(resources.interviews)}
""")

    if (
        resources.orgs
        or resources.jobs
        or resources.candidate_profiles
        or resources.interviews
    ):
        print("── Resource IDs ──")
        for u in resources.users:
            print(f"   user       {u['id']}  {u.get('email')} [{u.get('role')}]")
        for o in resources.orgs:
            print(f"   org        {o['id']}  {o['name']}")
        for j in resources.jobs:
            print(f"   job        {j['id']}  {j['title']}  [{j.get('status')}]")
        for c in resources.candidate_profiles:
            print(f"   candidate  {c['id']}  user={c['user_id']}")
        for a in resources.applications:
            print(f"   app        {a.get('id')}")
        for i in resources.interviews:
            print(f"   interview  {i['id']}")
        print()

    return resources


# ── curl examples ─────
CURL_EXAMPLES = """
# NOTE: This seed script now creates users + candidates using API endpoints.
# You can still create resources manually with these examples if needed.

# Health
curl -s http://localhost:8000/api/v1/health | python -m json.tool

# Create user (admin)
curl -s -X POST http://localhost:8000/api/v1/users \\
  -H "Content-Type: application/json" \\
  -d '{
    "email": "seed.admin@truefit.ai",
    "display_name": "Seed Admin",
    "role": "admin",
    "auth_provider": "seed",
    "provider_subject": "seed-admin"
  }' | python -m json.tool

# Create org
curl -s -X POST http://localhost:8000/api/v1/orgs \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Truefit Labs",
    "slug": "truefit-labs",
    "created_by": "USER_ID",
    "contact": {"email": "hiring@truefit.ai"}
  }' | python -m json.tool
"""


if __name__ == "__main__":
    activate = "--no-activate" not in sys.argv

    if "--curl" in sys.argv:
        print(CURL_EXAMPLES)
    else:
        asyncio.run(seed(activate_jobs=activate))
