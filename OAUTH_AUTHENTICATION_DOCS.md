# OAuth Authentication — Consolidated Documentation

> **Project:** TrueFit  
> **Stack:** React (Frontend) · FastAPI (Backend) · Firebase / Google OAuth  
> **Status:** Backend complete · Frontend integration required

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Backend Components](#backend-components)
3. [API Reference](#api-reference)
4. [Database Schema](#database-schema)
5. [Environment Configuration](#environment-configuration)
6. [Frontend Integration](#frontend-integration)
7. [Protecting Endpoints](#protecting-endpoints)
8. [Token Lifecycle Management](#token-lifecycle-management)
9. [Security Considerations](#security-considerations)
10. [Testing](#testing)
11. [Troubleshooting](#troubleshooting)
12. [Implementation Checklist](#implementation-checklist)
13. [Next Steps & Roadmap](#next-steps--roadmap)

---

## Architecture Overview

```
Frontend                        Backend                        OAuth Provider
┌─────────────┐                ┌──────────────────┐           ┌─────────────┐
│  React App  │                │  FastAPI App     │           │  Firebase   │
└─────────────┘                └──────────────────┘           └─────────────┘
      │                                │                              │
      │── (1) User clicks "Sign in" ──>│                              │
      │── (2) Firebase popup ─────────────────────────────────────>  │
      │<─ (3) Firebase ID Token ──────────────────────────────────── │
      │                                │                              │
      │── (4) POST /auth/oauth/token ─>│                              │
      │       { token, provider }      │── (5) Verify token ──────>  │
      │                                │<─ Valid ✓ ────────────────── │
      │                                │                              │
      │                                │── Get or create user in DB   │
      │                                │── Generate backend JWT       │
      │                                │                              │
      │<─ (6) { access_token, user } ──│                              │
      │                                │                              │
      │── (7) GET /api/protected ─────>│                              │
      │       Authorization: Bearer … │── Verify JWT                 │
      │<─ (8) Protected Data ──────── │                              │
```

---

## Backend Components

### File Map

| File | Purpose |
|------|---------|
| `src/truefit_infra/auth/jwt.py` | JWT token creation and verification |
| `src/truefit_infra/auth/oauth.py` | OAuth provider verification (Firebase, Google) |
| `src/truefit_infra/auth/middleware.py` | JWT validation dependency for protected routes |
| `src/truefit_api/api/v1/http/auth.py` | Auth endpoints (`/oauth/token`, `/me`, `/logout`) |
| `src/truefit_api/api/v1/http/schemas/oauth.py` | Request / response Pydantic models |
| `src/truefit_core/application/services/user_service.py` | OAuth user creation and retrieval |

### JWT Service (`jwt.py`)

Manages creation and verification of backend JWT tokens.

**Key methods:**
- `create_access_token()` — Create a JWT with user claims
- `verify_access_token()` — Verify and decode a JWT
- `get_user_id_from_token()` — Extract user ID without full verification

**Features:**
- HS256 algorithm (HMAC-SHA256)
- Configurable expiration (default: 30 minutes)
- Claims: `user_id`, `email`, `role`, `org_id`, token `type`

### OAuth Service (`oauth.py`)

Handles provider token verification and identity extraction.

**Supported providers:**
- `FirebaseOAuthProvider` — Verifies Firebase ID tokens
- `GoogleOAuthProvider` — Verifies raw Google OAuth tokens

**Extracted identity shape:**
```json
{
  "provider_subject": "112345678901234567890",
  "email": "user@example.com",
  "name": "John Doe",
  "picture": "https://..."
}
```

### Auth Middleware (`middleware.py`)

Validates JWT tokens in incoming requests.

**Key functions:**
- `extract_token_from_header()` — Parses `Bearer <token>` format
- `verify_jwt_token()` — Verifies signature and claims
- `get_current_user()` — FastAPI dependency for protected endpoints

**Usage:**
```python
from src.truefit_infra.auth.middleware import get_current_user, TokenPayload

@router.get("/me")
async def get_me(current_user: TokenPayload = Depends(get_current_user)):
    return {
        "user_id": current_user.user_id,
        "email":   current_user.email,
        "role":    current_user.role,
    }
```

---

## API Reference

### `POST /api/v1/auth/oauth/token`

Exchange an OAuth provider token for a backend JWT.

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "token": "FIREBASE_ID_TOKEN",
    "provider": "firebase"
  }'
```

**Response `201 Created`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "display_name": "John Doe",
    "role": "candidate",
    "org_id": null,
    "is_active": true
  }
}
```

**Error codes:** `400` Invalid parameters · `401` Invalid OAuth token · `403` Inactive account · `500` Unexpected error

---

### `GET /api/v1/auth/me`

Return the currently authenticated user's profile.

**Headers:** `Authorization: Bearer <jwt>`

**Response `200 OK`:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "display_name": "John Doe",
  "role": "candidate",
  "org_id": null,
  "is_active": true,
  "created_at": "2024-01-15T10:30:00+00:00",
  "updated_at": "2024-01-20T15:45:00+00:00"
}
```

**Error codes:** `401` Missing / invalid JWT · `404` User not found · `500` Unexpected error

---

### `POST /api/v1/auth/logout`

Invalidate the current session (client-side token removal).

**Headers:** `Authorization: Bearer <jwt>`

**Response `200 OK`:**
```json
{ "detail": "Successfully logged out" }
```

---

## Database Schema

No new tables are required. The existing `users` table supports OAuth via two dedicated columns.

```sql
CREATE TABLE users (
    id                UUID         PRIMARY KEY,
    email             VARCHAR(320) NOT NULL UNIQUE,
    display_name      VARCHAR(255),
    role              VARCHAR(32)  NOT NULL,
    auth_provider     VARCHAR(64)  NOT NULL,      -- "firebase", "google", etc.
    provider_subject  VARCHAR(255) NOT NULL,       -- Provider's unique user ID
    org_id            UUID,
    is_active         BOOLEAN      DEFAULT TRUE,
    created_at        TIMESTAMP,
    updated_at        TIMESTAMP
);
```

### User Creation Flow

1. Verify Firebase token (signature + expiration)
2. Extract `sub`, `email`, and other claims
3. Look up user by email
4. **Create or update:**
   - Same provider → update `provider_subject` if changed
   - Different provider → reject (federation not yet implemented)
   - New user → create with `role = "candidate"`, create default candidate profile
5. Generate backend JWT with user claims

---

## Environment Configuration

Add the following to `apps/backend/.env`:

```env
# JWT
APP_SECRET_KEY="your-secret-key-min-32-chars-random-string"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES="30"

# Firebase
FIREBASE_PROJECT_ID="truefit-ai"
GOOGLE_APPLICATION_CREDENTIALS="path/to/firebase-service-account.json"
```

**Generate a secure secret key:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Install new Python packages:**
```bash
cd apps/backend
pip install -r requirements.txt
# Added: PyJWT==2.10.1 · google-auth-httplib2==0.2.0
```

---

## Frontend Integration

### 1. Sign-In Component (`apps/frontend/src/pages/auth/Signin.tsx`)

```typescript
import { signInWithPopup, GoogleAuthProvider } from "firebase/auth"
import { auth } from "@/helpers/firebase"

const handleGoogleSignIn = async () => {
  try {
    const result = await signInWithPopup(auth, new GoogleAuthProvider())
    const idToken = await result.user.getIdToken()

    const response = await fetch(
      `${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/api/v1/auth/oauth/token`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: idToken, provider: 'firebase' }),
      }
    )

    if (!response.ok) throw new Error(await response.text())

    const data = await response.json()
    localStorage.setItem('authToken', data.access_token)
    localStorage.setItem('user', JSON.stringify(data.user))

    navigate('/dashboard', { replace: true })
  } catch (error: any) {
    form.setError('root', { message: error.message || 'Sign in failed' })
  }
}
```

### 2. API Helper (`apps/frontend/src/helpers/api.ts`)

```typescript
const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000'

export class ApiClient {
  private getToken = () => localStorage.getItem('authToken')

  async request(url: string, options: RequestInit = {}): Promise<Response> {
    const token = this.getToken()
    if (!token) throw new Error('Not authenticated')

    const response = await fetch(`${API_BASE}${url}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
        'Authorization': `Bearer ${token}`,
      },
    })

    if (response.status === 401) {
      localStorage.removeItem('authToken')
      localStorage.removeItem('user')
      window.location.href = '/signin'
      throw new Error('Session expired')
    }

    return response
  }

  get    = (url: string)            => this.request(url, { method: 'GET' })
  post   = (url: string, data: any) => this.request(url, { method: 'POST',   body: JSON.stringify(data) })
  put    = (url: string, data: any) => this.request(url, { method: 'PUT',    body: JSON.stringify(data) })
  delete = (url: string)            => this.request(url, { method: 'DELETE' })
}

export const api = new ApiClient()
```

### 3. Auth Context Hook (`apps/frontend/src/hooks/useAuth.tsx`)

```typescript
import { useState } from 'react'

export const useAuth = () => {
  const [user, setUser]   = useState(() => JSON.parse(localStorage.getItem('user') || 'null'))
  const [token, setToken] = useState(() => localStorage.getItem('authToken'))

  const loginWithGoogle = async (idToken: string) => {
    const response = await fetch('/api/v1/auth/oauth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: idToken, provider: 'firebase' }),
    })
    const data = await response.json()
    localStorage.setItem('authToken', data.access_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    setToken(data.access_token)
    setUser(data.user)
  }

  const logout = () => {
    localStorage.removeItem('authToken')
    localStorage.removeItem('user')
    setToken(null)
    setUser(null)
  }

  return { user, token, loginWithGoogle, logout }
}
```

### 4. Protected Route Guard

```typescript
import { useAuth } from '@/hooks/useAuth'
import { useEffect } from 'react'
import { useNavigate } from 'react-router'

export const ProtectedComponent = () => {
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!loading && !user) navigate('/signin')
  }, [loading, user, navigate])

  if (loading) return <LoadingSpinner />
  if (!user)   return null

  return <div>{/* Component content */}</div>
}
```

---

## Protecting Endpoints

### Pattern 1 — Required Authentication

```python
from src.truefit_infra.auth.middleware import get_current_user, TokenPayload
from fastapi import Depends, HTTPException

# Before (unprotected):
@router.get("")
async def list_users(svc: UserService = Depends(get_user_service)):
    return await svc.list_users()

# After (protected):
@router.get("")
async def list_users(
    current_user: TokenPayload = Depends(get_current_user),
    svc: UserService = Depends(get_user_service),
):
    return await svc.list_users()
```

### Pattern 2 — Resource Ownership

```python
@router.post("/jobs")
async def create_job(
    job_data: JobCreateRequest,
    current_user: TokenPayload = Depends(get_current_user),
    svc: JobService = Depends(get_job_service),
):
    return await svc.create_job(
        title=job_data.title,
        description=job_data.description,
        created_by_user_id=current_user.user_id,
        org_id=current_user.org_id,
    )
```

### Pattern 3 — Role-Based Access Control

```python
@router.post("/rubrics")
async def create_rubric(
    rubric_data: RubricCreateRequest,
    current_user: TokenPayload = Depends(get_current_user),
    svc: RubricService = Depends(get_rubric_service),
):
    if current_user.role not in ["recruiter", "admin"]:
        raise HTTPException(status_code=403, detail="Only recruiters can create rubrics")

    return await svc.create_rubric(
        name=rubric_data.name,
        org_id=current_user.org_id,
        created_by_id=current_user.user_id,
    )
```

### Pattern 4 — Authorization Check by Ownership

```python
@router.get("/interviews/{interview_id}")
async def get_interview(
    interview_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    svc: InterviewService = Depends(get_interview_service),
):
    interview = await svc.get_interview(interview_id)

    if interview.created_by_id != current_user.user_id:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not authorized")

    return interview
```

### Pattern 5 — Optional Authentication

```python
from typing import Optional
from fastapi import Header

@router.get("/jobs")
async def list_jobs(
    auth_header: Optional[str] = Header(None),
    jwt_svc: JWTService = Depends(get_jwt_service),
    svc: JobService = Depends(get_job_service),
):
    current_user = None
    if auth_header:
        try:
            from src.truefit_infra.auth.middleware import verify_jwt_token
            current_user = await verify_jwt_token(jwt_svc, auth_header)
        except:
            pass

    jobs = await svc.list_jobs()

    if current_user:
        for job in jobs:
            job.applied_by_me = current_user.user_id in job.applicant_ids

    return jobs
```

---

## Token Lifecycle Management

### Check expiration (backend)

```python
from datetime import datetime
import json, base64

def is_token_expired(token: str) -> bool:
    try:
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return datetime.fromtimestamp(claims['exp']) < datetime.utcnow()
    except:
        return True
```

### Check expiration (frontend)

```typescript
export const getValidToken = async (): Promise<string | null> => {
  const token = localStorage.getItem('authToken')
  if (!token) return null

  const payload = JSON.parse(atob(token.split('.')[1]))
  if (payload.exp * 1000 < Date.now()) {
    localStorage.removeItem('authToken')
    localStorage.removeItem('user')
    window.location.href = '/signin'
    return null
  }

  return token
}
```

---

## Security Considerations

| Topic | Recommendation |
|-------|---------------|
| **Token storage** | Use HttpOnly + Secure + SameSite cookies in production; localStorage is vulnerable to XSS |
| **Secret key** | Minimum 32 characters, randomly generated, rotated periodically |
| **CORS** | Restrict `allow_origins` to actual frontend domain in production; require HTTPS |
| **OAuth validation** | Always verify signature, expiration, and audience with the provider |
| **Secrets in code** | Never hardcode secrets; use environment variables only |
| **Logs** | Never log JWT tokens |
| **Rate limiting** | Add rate limits to all auth endpoints before going to production |

### CORS Configuration

```python
# Development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Production — restrict to your domain
allow_origins=["https://yourdomain.com"]
```

### Security Checklist

- [ ] `APP_SECRET_KEY` is 32+ chars and randomly generated
- [ ] `.env` with real secrets is never committed
- [ ] Firebase project ID matches your actual project
- [ ] HTTPS is enabled in production
- [ ] CORS is restricted to the production frontend domain
- [ ] Token expiration is set appropriately (default: 30 min)
- [ ] Auth endpoints have rate limiting
- [ ] Authentication events are logged for auditing

---

## Testing

### cURL — Full Flow

```bash
# 1. Exchange Firebase token for backend JWT
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/oauth/token \
  -H "Content-Type: application/json" \
  -d '{"token":"FIREBASE_ID_TOKEN","provider":"firebase"}' | jq -r '.access_token')

# 2. Call a protected endpoint
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"

# 3. Test expired/invalid token (expect 401)
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer invalid.token.here"
```

### Swagger UI

1. Start the backend: `uvicorn src.truefit_api.main:app --reload`
2. Open [http://localhost:8000/api/docs](http://localhost:8000/api/docs)
3. Test endpoints directly in the UI

### Pytest

```python
# tests/integration/test_auth_protected_endpoints.py

@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_with_valid_token(client, valid_jwt_token):
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {valid_jwt_token}"},
    )
    assert response.status_code == 200
```

### Verify User in Database

```sql
SELECT id, email, auth_provider, provider_subject, created_at
FROM users
ORDER BY created_at DESC
LIMIT 10;
```

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid Firebase token` | Wrong project ID or credentials | Verify `FIREBASE_PROJECT_ID`; check `GOOGLE_APPLICATION_CREDENTIALS` |
| `Token has expired` | JWT past expiry | Clear localStorage and redirect to `/signin` |
| `Invalid authorization header format` | Missing `Bearer` prefix | Use `Authorization: Bearer <token>` |
| `Invalid authentication token` | Tampered JWT | Clear token, re-authenticate |
| `User account is inactive` | Account disabled | Contact support / admin |
| `User already exists with different provider` | Email registered via different OAuth provider | Provider federation not yet supported |
| CORS errors | Frontend origin not in `allow_origins` | Add frontend URL to CORS config in `main.py` |
| 401 on protected endpoints | Token missing, expired, or malformed | Verify header format; check token expiry; confirm `APP_SECRET_KEY` is consistent |

---

## Implementation Checklist

### ✅ Backend (Complete)

- [x] JWT Service — token creation, verification, HS256 signing
- [x] OAuth Service — Firebase and Google provider verification
- [x] Auth Middleware — JWT extraction and validation dependency
- [x] Auth Endpoints — `/oauth/token`, `/me`, `/logout`
- [x] Pydantic Schemas — request / response validation
- [x] UserService — OAuth user creation, candidate profile auto-creation
- [x] Main app updated — auth router registered
- [x] `requirements.txt` updated — `PyJWT==2.10.1`, `google-auth-httplib2==0.2.0`

### 📋 Frontend (To Do)

- [ ] Update `Signin.tsx` — exchange Firebase token for backend JWT
- [ ] Create `src/helpers/api.ts` — `ApiClient` with auto-auth headers
- [ ] Create / update `useAuth` hook — login, logout, token state
- [ ] Protect routes — redirect to `/signin` when unauthenticated
- [ ] Handle 401 responses — clear token and redirect globally

### 🧪 Testing (To Do)

**Backend:**
- [ ] OAuth token exchange with valid / invalid / expired Firebase token
- [ ] `/auth/me` with valid JWT, without header, with invalid JWT
- [ ] New user created in DB on first login; not duplicated on subsequent logins
- [ ] Logout endpoint; JWT expiration after 30 minutes

**Frontend:**
- [ ] Google sign-in popup appears and completes
- [ ] Token stored in localStorage after sign-in
- [ ] API calls include `Authorization` header
- [ ] 401 responses redirect to sign-in
- [ ] User info displays correctly
- [ ] Sign-out clears token and user data

**Integration:**
- [ ] Full flow: click Google → authenticate → redirect → API call succeeds
- [ ] Token persists across page refreshes
- [ ] Expired token triggers re-login

---

## Next Steps & Roadmap

| Priority | Feature |
|----------|---------|
| High | Frontend integration (sign-in component + API helper) |
| High | End-to-end testing |
| Medium | Token refresh / rotation for long-lived sessions |
| Medium | Rate limiting on auth endpoints |
| Medium | Audit logging for all authentication events |
| Low | OAuth provider federation (multiple providers per email) |
| Low | Token blacklisting on logout |
| Low | Two-factor authentication (optional) |
| Low | Active session management and revocation |

### Production Deployment Checklist

- [ ] Generate strong `APP_SECRET_KEY` (separate from dev)
- [ ] Update CORS origins to match production frontend domain
- [ ] Enable HTTPS / SSL
- [ ] Configure Firebase production project
- [ ] Update `REACT_APP_API_URL` to production backend URL
- [ ] Set up error monitoring (e.g. Sentry)
- [ ] Configure database backups
- [ ] Enable audit logging

---

*Full API docs available at [http://localhost:8000/api/docs](http://localhost:8000/api/docs) when the backend is running.*