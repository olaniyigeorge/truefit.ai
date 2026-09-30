# TrueFit API Reference

Reference for the FastAPI backend in `apps/backend`: authentication, REST endpoints, the interview WebSocket, error format and environment variables. Everything here was checked against the code under `apps/backend/src`.

For system design see [architecture.md](architecture.md). For where the project is heading (the `soro` voice SDK) see [voice-infra-pivot.md](voice-infra-pivot.md).

## Overview

| Item | Value |
|------|-------|
| Local base URL | `http://localhost:8000` |
| REST prefix | `/api/v1` (every router is mounted with this prefix) |
| WebSocket | `ws://localhost:8000/api/v1/ws/interview/{job_id}/{candidate_id}` |
| Swagger UI | `/api/docs` |
| OpenAPI schema | `/api/openapi.json` |
| Body format | JSON (except the resume upload, which is `multipart/form-data`) |

Run locally from `apps/backend` (the app reads `.env`, see [Environment variables](#environment-variables)):

```bash
python run.py        # or: uvicorn src.truefit_api.main:app --reload --port 8000
```

CORS is an allow-list hardcoded in `src/truefit_api/main.py` (localhost ports 3000, 5173, 5174, plus one production IP). The `CORS_ORIGINS` setting is not read.

## Authentication

### Flow

1. The frontend signs the user in with Firebase and gets a Firebase ID token.
2. It calls `POST /api/v1/auth/oauth/token` with that token.
3. The backend verifies the token against Firebase (public certs, checked against `FIREBASE_PROJECT_ID`), gets or creates the user, and returns a backend-signed JWT.
4. The frontend sends `Authorization: Bearer <jwt>` on later requests. The frontend stores the JWT in a `jwt` cookie (`apps/frontend/src/helpers/api.interceptors.ts`) and, on any 401, clears the cookie, signs out of Firebase and redirects to `/auth`.

### Exchange a token

`POST /api/v1/auth/oauth/token` (public)

```bash
curl -X POST http://localhost:8000/api/v1/auth/oauth/token \
  -H "Content-Type: application/json" \
  -d '{"token": "<FIREBASE_ID_TOKEN>", "provider": "firebase"}'
```

| Field | Type | Notes |
|-------|------|-------|
| `token` | string | Required, at least 10 characters |
| `provider` | string | `firebase` (default) or `google` |

Response (HTTP 200):

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 3600,
  "is_new_user": false,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "display_name": "Jane Doe",
    "role": "candidate",
    "org_id": null,
    "is_active": true
  }
}
```

Notes:

- `expires_in` is `ACCESS_TOKEN_EXPIRE_MINUTES * 60` seconds, matching the token's `exp` claim.
- `provider: "google"` needs `GOOGLE_CLIENT_ID` to be set. Without it the endpoint returns `400` "Google sign-in is not configured on this server". The frontend uses `firebase`.
- `is_new_user` is true when the call created the user.
- An inactive user gets 403 "User account is inactive".

### The backend JWT

Signed with `APP_SECRET_KEY` using `ALGORITHM` (HS256 in `env.example`). Claims:

| Claim | Meaning |
|-------|---------|
| `sub` | User ID (UUID string) |
| `email` | User email |
| `role` | `admin`, `recruiter` or `candidate` |
| `org_id` | Organization ID, or null |
| `iat`, `exp` | Issued at and expiry |
| `type` | Always `access`; any other value is rejected |

There are no refresh tokens. `POST /auth/refresh` re-issues a fresh JWT for a caller who still holds a valid one, using current data from the database.

### Auth endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/oauth/token` | none | Exchange a Firebase token for a backend JWT |
| GET | `/auth/me` | JWT | Current user from the database (adds `created_at`, `updated_at`) |
| POST | `/auth/refresh` | JWT | Issue a new JWT with fresh user data |
| POST | `/auth/logout` | JWT | Logs the event and returns `{"detail": "Successfully logged out"}`. Tokens are stateless, so there is no server-side revocation; the client must discard the token |

### How endpoints are guarded

Protection is opt-in per route. A route is protected only if it declares the `get_current_user` dependency (`src/truefit_infra/auth/middleware.py`), which:

1. Reads the `Authorization` header (401 "Missing authorization header" if absent).
2. Requires the form `Bearer <token>` (401 "Invalid authorization header format...").
3. Verifies signature, expiry and `type` (401 "Token has expired" or "Invalid authentication token").
4. Returns a `TokenPayload` with `user_id`, `email`, `role`, `org_id`.

```python
@router.get("/me")
async def me(current_user: TokenPayload = Depends(get_current_user)):
    ...
```

### Access rules

Every route except `GET /health`, `GET /` and `POST /auth/oauth/token` requires a valid JWT. A test (`tests/unit/auth/test_routes_require_auth.py`) fails if a new route is added without one. Beyond being signed in, each route checks the caller's `role` and ownership (`src/truefit_infra/auth/authorization.py`). A denied request gets `403`.

| Term | Meaning |
|------|---------|
| admin | `role` is `admin`. Passes every check |
| self | The `user_id` in the JWT is the user in the path |
| owner / owning candidate | The candidate profile's `user_id` is the caller |
| org recruiter | `role` is `recruiter` and the JWT `org_id` is the org that owns the resource (for applications and interviews, the org of the job) |
| same-org recruiter | A recruiter in the same org as the target user |
| founder | The user who created the org (`orgs.created_by`) |

Notes:

- Lists are filtered by role. A candidate only ever sees their own applications and interviews, a recruiter only those for jobs in their org, and asking for another org's job is a `403`.
- `PATCH /users/{user_id}`: a non-admin may set their own `role` to `candidate` or `recruiter` (onboarding), and may set `org_id` only to an org they founded. `is_active` is admin only. Nobody can grant `admin` through the API.
- `POST /orgs` ignores any `created_by` the client sends and records the caller.
- `POST /candidates` by a candidate must be for their own account (body `email` and optional `user_id` must match the JWT). An admin must pass `user_id`.
- Joining an org you did not found is admin-only until an invite flow exists.
- The `role` and `org_id` claims are fixed when the token is issued. After a role or org change, call `POST /auth/refresh` to get a token that reflects it.

## REST endpoints

Paths below are relative to `/api/v1`. "Auth" is who may call the route. `none` means public, `JWT` any signed-in user, and the roles are explained under [Access rules](#access-rules). List endpoints take `limit` (1 to 100) and `offset` (default 0) unless noted, and return bare JSON arrays with no pagination envelope.

### Health

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/health` | none | Checks database and Redis (LLM, queue and storage checks are stubbed as `skipped`). Returns `status` of `ok`, `degraded` or `down` with per-check detail. Always HTTP 200 in practice: 503 is only returned when every check is down, which cannot happen while three checks are stubbed. Hidden from Swagger |
| GET | `/` | none | Returns `{"status": "ok"}`. Hidden from Swagger |

### Users

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/users` | admin | Create a user (201). Body: `email`, `provider_subject` (required), `display_name`, `auth_provider` (default `seed`), `account_type` (default `candidate`), optional `candidate_profile` or `org`. Returns `{user, org, candidate_profile}` |
| GET | `/users/{user_id}` | self, admin, same-org recruiter | Get by ID |
| GET | `/users/by-email/{email}` | self, admin, same-org recruiter | Get by email |
| PATCH | `/users/{user_id}` | self, admin (see note) | Update `display_name`, `is_active`, `role` (`candidate` or `recruiter` only), `org_id` |
| POST | `/users/{user_id}/join-org` | admin, or the founder of the org | Body: `{"org_id": "<uuid>"}` |

User fields: `id`, `email`, `display_name`, `role`, `org_id`, `is_active`, `created_at`, `updated_at`. Sign-in via `/auth/oauth/token` is the normal way users are created.

### Organizations

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/orgs` | recruiter, admin | Create (201). Body: `name`, `created_by`, `contact` (`email` required, `phone`, `website`), optional `slug`, `description`, `logo_url`, `industry`, `headcount`, `billing`. 409 on slug conflict |
| GET | `/orgs` | JWT | List. Query: `status` (`active`, `suspended`, `deactivated`) |
| GET | `/orgs/{org_id}` | JWT | Get by ID |
| GET | `/orgs/slug/{slug}` | JWT | Get by slug |
| PATCH | `/orgs/{org_id}` | org recruiter, admin | Update profile fields. 400 if no field is given |
| PATCH | `/orgs/{org_id}/billing` | org recruiter, admin | Body: `plan` (default `free`), `max_active_jobs`, `max_interviews_per_month` |
| POST | `/orgs/{org_id}/suspend` | org recruiter, admin | Status transition |
| POST | `/orgs/{org_id}/reactivate` | org recruiter, admin | Status transition |
| POST | `/orgs/{org_id}/deactivate` | org recruiter, admin | Status transition (permanent) |
| DELETE | `/orgs/{org_id}` | org recruiter, admin | 204 |

### Jobs

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/jobs` | org recruiter, admin | Create (201). Body: `org_id`, `created_by`, `title`, `description` (min 10 chars), `requirements` (`experience_level` required), `skills` (at least one), optional `interview_config` |
| GET | `/jobs` | JWT | List for an org. Query: `org_id` (required), `status`, `experience_level`. Default `limit` 20 |
| GET | `/jobs/active` | JWT | Active jobs across orgs. Default `limit` 50 |
| GET | `/jobs/{job_id}` | JWT | Get by ID |
| PATCH | `/jobs/{job_id}` | org recruiter, admin | Update `description`, `requirements`, `interview_config`, `skills_add`, `skills_remove` (skill names) |
| POST | `/jobs/{job_id}/activate` | org recruiter, admin | Status transition |
| POST | `/jobs/{job_id}/pause` | org recruiter, admin | Status transition |
| POST | `/jobs/{job_id}/close` | org recruiter, admin | Status transition |
| DELETE | `/jobs/{job_id}` | org recruiter, admin | 204. Only `draft` jobs; otherwise 400 |

Job `status`: `draft`, `active`, `paused`, `closed`. `experience_level`: `intern`, `junior`, `mid`, `senior`, `staff`, `principal`. Each skill has `name`, `required` (default true), `weight` (0 to 1), `min_years`. `interview_config` defaults: `max_questions` 10 (1 to 50), `max_duration_minutes` 30 (5 to 120), plus `topics` and `custom_instructions`.

### Candidates

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/candidates` | the candidate themself, admin | Register (201). Body: `full_name`, `email`, optional `phone`, `linkedin_url` |
| GET | `/candidates` | recruiter, admin | List. Default `limit` 50 |
| GET | `/candidates/{candidate_id}` | owner, recruiter, admin | Get by ID |
| PATCH | `/candidates/{candidate_id}` | owner, admin | Update `full_name`, `phone`, `linkedin_url`. 400 if empty |
| POST | `/candidates/{candidate_id}/resume` | owner, admin | Upload `file` (multipart). PDF or Word only (400 otherwise), max 10 MB (413) |
| GET | `/candidates/{candidate_id}/resume` | owner, recruiter, admin | Returns a dict with the resume URL. 404 if none |
| DELETE | `/candidates/{candidate_id}/resume` | owner, admin | 204. 404 if none |

Candidate fields: `id`, `user_id`, `full_name`, `headline`, `bio`, `location`, `skills`, `contact` (`email`, `phone`, `linkedin_url`), `status` (`active`, `banned`, `withdrawn`), `resume` (`storage_key`, `filename`, `content_type`, `uploaded_at`), timestamps.

### Applications

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/applications` | owning candidate, admin | Create (201). Body: `job_id`, `candidate_id`, optional `source` (`applied` default, or `invited`), `meta`. 409 on conflict |
| GET | `/applications` | JWT, filtered by role | List. Query: `job_id` or `candidate_id` (one is required, else 400), optional `status` |
| GET | `/applications/{application_id}` | owner, org recruiter, admin | Get by ID |
| PATCH | `/applications/{application_id}/status` | org recruiter, admin | Body: `status`, optional `meta_updates` |
| DELETE | `/applications/{application_id}` | owner, org recruiter, admin | Withdraw (204) |

Application `status`: `new`, `interviewing`, `shortlisted`, `rejected`, `hired`.

### Interviews

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/interviews` | owning candidate, admin | Create and start an interview (201). Body: `job_id`, `candidate_id`. 404 if either is missing, 400 if the job is not open or the candidate is ineligible or already interviewing |
| GET | `/interviews` | JWT, filtered by role | List. Query: `candidate_id` or `job_id` (one is required, else 400). Default `limit` 20 |
| GET | `/interviews/{interview_id}` | owner, org recruiter, admin | Get by ID |
| POST | `/interviews/{interview_id}/abandon` | owning candidate, admin | Body (optional fields): `reason` (default `manual`), `initiated_by` (default `candidate`). 400 if already finished. Releases the candidate's active-interview lock |
| GET | `/interviews/{interview_id}/transcript` | owner, org recruiter, admin | `{interview_id, status, turns[]}`, each turn with `question_id`, `question_text`, `topic`, `answer_text`, `duration_seconds`, `asked_at`, `answered_at` |

Interview fields: `id`, `job_id`, `candidate_id`, `company_id`, `status`, `question_count`, `answered_count`, `max_questions`, `max_duration_minutes`, `elapsed_minutes`, `started_at`, `ended_at`, `created_at`. `status` is one of `scheduled`, `active`, `completed`, `abandoned`, `evaluated`.

Note that the WebSocket (below) also creates an interview when it connects. The browser flow uses the WebSocket, not `POST /interviews`.

### TURN credentials

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/turn/credentials` | JWT | Returns `{"ice_servers": [...]}`: a Google STUN server, plus a TURN entry (`urls`, `username`, `credential`) when `TURN_SERVER_URL` is set |

## Interview WebSocket

`/api/v1/ws/interview/{job_id}/{candidate_id}` (source: `src/truefit_api/api/v1/ws/interview_websocket.py`). Both path parameters are UUIDs. The connection is authenticated with the backend JWT in a `token` query parameter (browsers cannot set headers on a WebSocket): `ws://localhost:8000/api/v1/ws/interview/{job_id}/{candidate_id}?token=<jwt>`. The handshake is rejected with close code `4401` for a missing, invalid or expired token, and `4403` when the caller is not the interviewed candidate (and not an admin). The token ends up in the URL, so keep it short-lived and avoid logging query strings at your proxy.

The socket is a control and signaling channel only. Audio and video travel over a WebRTC peer connection negotiated through it, plus a WebRTC data channel for in-call events.

### Session sequence

1. Client connects. The server creates the interview, loads the job and candidate, and sends `session_started`.
2. Client sends `webrtc_offer`. The server replies with `webrtc_answer`. Both sides trickle `ice_candidate` messages.
3. If the offer is not received within 30 seconds, the server sends an `error` ("WebRTC setup timed out") and ends the session.
4. The live AI interviewer starts. Transcripts and interrupts stream back over the socket.
5. The session ends when the agent finishes, the client sends `end_session`, or the client disconnects. Disconnects and errors mark the interview `abandoned`.

The live model is chosen by `LLM_PRIMARY_PROVIDER` and `LLM_FALLBACK_PROVIDER` (Gemini Live or OpenAI Realtime, with optional fallback).

### Client to server

| `type` | Fields | Purpose |
|--------|--------|---------|
| `webrtc_offer` | `sdp`, `sdp_type` (default `offer`), `frame_interval_camera` (default 5.0), `frame_interval_screen` (default 2.0) | Start WebRTC negotiation |
| `ice_candidate` | `candidate`, `sdpMid`, `sdpMLineIndex` | Trickle ICE |
| `end_session` | `reason` (default `candidate_ended`) | Abandon the interview. Server replies `session_ended` and stops reading |
| `ping` | none | Keepalive, server replies `pong` |

Malformed JSON is logged and ignored.

### Server to client

| `type` | Fields | When |
|--------|--------|------|
| `session_started` | `interview_id`, `session_id`, `max_questions`, `max_duration_minutes` | Right after connect |
| `webrtc_answer` | `sdp`, `sdp_type` (`answer`) | Reply to `webrtc_offer` |
| `ice_candidate` | `candidate`, `sdpMid`, `sdpMLineIndex` | Server-side ICE candidates |
| `transcript` | `speaker` (`agent` or `candidate`), `text` | Live captions |
| `interrupt` | `interrupt_id`, `directive`, `type_detail` | The agent flagged a candidate interruption. `directive` defaults to `stop_and_listen` |
| `session_ended` | `status` (`abandoned`), `reason` | Reply to `end_session` only |
| `error` | `message` | Setup timeout or an unhandled error |
| `pong` | none | Reply to `ping` |

`session_ended` is only sent in response to `end_session`. When the interview completes on its own, or the agent session fails, the client should rely on the socket closing and on `GET /interviews/{id}` for the final status.

### Data channel

A WebRTC data channel carries JSON events shaped `{"type": ..., ...}`. The server handles `ping` (replies `pong`) and acts on or logs `screen_share_start`, `screen_share_stop` and `clarification_request` (the last is currently ignored).

### Background sweeper

On startup the app launches an `InterviewSweeper` task that runs every 60 seconds and abandons active interviews that exceeded their maximum duration or went stale (45 minute threshold). It is cancelled on shutdown. See [architecture.md](architecture.md).

## Error responses

`HTTPException` and unhandled exceptions are both returned in one envelope (`src/truefit_api/middlewares.py`):

```json
{
  "status": false,
  "error": "Job 3f2a... not found",
  "path": "http://localhost:8000/api/v1/jobs/3f2a..."
}
```

| Code | Meaning in this API |
|------|---------------------|
| 400 | Domain rule violation, missing required query filter, empty update body, invalid enum filter |
| 401 | Missing, malformed, expired or invalid JWT; failed provider token verification |
| 403 | Inactive user account (token exchange) |
| 404 | Entity not found |
| 409 | Conflict (duplicate org slug, duplicate application, duplicate user) |
| 413 | Resume larger than 10 MB |
| 422 | Request body or parameter validation failed (FastAPI's default validation body, not the envelope above) |
| 500 | Unhandled error. The `error` field contains the raw exception message |

Auth failures also carry a `WWW-Authenticate: Bearer` header.

## Environment variables

Settings are loaded by `src/truefit_infra/config.py` (pydantic-settings, from `.env`). Copy `apps/backend/env.example` to `.env`. Startup fails if a variable without a default is missing.

`env.example` lists every variable the settings class requires, including `FIREBASE_PROJECT_ID`. The `TURN_*` variables and `GOOGLE_CLIENT_ID` are optional. `ENV` accepts `dev`, `test` or `prod`.

### Used by the running code

| Variable | Purpose |
|----------|---------|
| `ENV` | `dev`, `prod` or `test`. Selects the config class |
| `PROJECT_NAME` | FastAPI app title |
| `APP_SECRET_KEY` | JWT signing secret. Change it in every non-local environment |
| `ALGORITHM` | JWT algorithm (`HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime. The `JWTService` fallback is 30, `env.example` sets 60 |
| `FIREBASE_PROJECT_ID` | Project ID used to verify Firebase ID tokens |
| `DATABASE_URL` | SQLAlchemy URL, for example `postgresql+asyncpg://user:pass@host:5432/db` (SQLite URLs are also handled). Tables are created on startup |
| `REDIS_URL` | Redis for cache and queue (interrupt signals and domain events) |
| `GEMINI_API_KEY` | Gemini key, required when Gemini is primary or fallback |
| `GEMINI_LIVE_MODEL` | Optional Live model override |
| `OPENAI_API_KEY` | Required when OpenAI is primary or fallback |
| `OPENAI_REALTIME_MODEL` | Optional Realtime model override |
| `LLM_PRIMARY_PROVIDER` | `gemini` (default) or `openai` |
| `LLM_FALLBACK_PROVIDER` | `gemini`, `openai` or `none` (default) |
| `TURN_SERVER_URL`, `TURN_USERNAME`, `TURN_CREDENTIAL` | Optional TURN relay. Used for both `/turn/credentials` and the server's own peer connection. STUN only when empty |
| `GOOGLE_CLIENT_ID` | Optional. Enables `provider: "google"` sign-in |

### Required by the settings class but not read by any code

These must be set for startup to succeed but currently have no effect: `API_VERSION`, `LOG_LEVEL`, `CLIENT_DOMAIN`, `BACKEND_DOMAIN`, `CORS_ORIGINS`, `AUTH_MODE`, `DB_ECHO`, `REDIS_PREFIX`, `GEMINI_MODEL`, `GEMINI_LIVE_ENABLED`, `STORAGE_PROVIDER`, `LOCAL_STORAGE_DIR`, `GCS_BUCKET`, `GOOGLE_APPLICATION_CREDENTIALS`, `REALTIME_ENABLED`, `WEBRTC_TOKEN_SECRET`, `WORKERS_ENABLED`, `SENTRY_DSN`.

### Frontend (`apps/frontend`)

`VITE_PUBLIC_API_URL`, `VITE_PUBLIC_WS_URL`, and the Firebase web config: `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_STORAGE_BUCKET`, `VITE_FIREBASE_MESSAGING_SENDER_ID`, `VITE_FIREBASE_APP_ID`.
