# Using OAuth Authentication in Existing Endpoints

## Overview

This document shows how to protect existing endpoints with JWT authentication and how OAuth flows through your application.

## Authentication Flow Architecture

```
Frontend                Backend
┌─────────────┐        ┌──────────────────────────────┐
│ React App   │        │ FastAPI Application          │
└─────────────┘        └──────────────────────────────┘
       │                          │
       │──(1) Sign in Google──────>│
       │<─(2) Firebase ID Token───│
       │
       │──(3) POST /auth/oauth/token
       │     { token, provider }──>│
       │                          │
       │                     (Verify OAuth Token)
       │                     (Create/Get User)
       │                     (Generate JWT)
       │                          │
       │<─(4) Access Token────────│
       │     { access_token, user }
       │
       │─(5) GET /api/protected
       │     Authorization: Bearer token───>│
       │                          │
       │                     (Verify JWT)
       │                     (Get user from token)
       │                          │
       │<─(6) Protected Data─────│
```

## Step 1: Authenticate User

### Endpoint: `POST /api/v1/auth/oauth/token`

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "token": "Firebase_ID_Token_Here",
    "provider": "firebase"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1NTBlODQwMC1lMjliLTQxZDQtYTcxNi00NDY2NTU0NDAwMDAiLCJlbWFpbCI6InVzZXJAZXhhbXBsZS5jb20iLCJyb2xlIjoiY2FuZGlkYXRlIiwib3JnX2lkIjpudWxsLCJleHAiOjE3MzYzNDU5MzcsImlhdCI6MTczNjM0NDEzNywidHlwZSI6ImFjY2VzcyJ9.kVEq-RtI5Yd9h0jK8l2_XrZvPqO-4mNs3uYwZxAaBc8",
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

**Store this token:** `localStorage.setItem('authToken', response.access_token)`

## Step 2: Protect Existing Endpoints with JWT

### Example: Protect the Users Endpoint

**Before (Unprotected):**
```python
# src/truefit_api/api/v1/http/users.py

@router.get("")
async def list_users(svc: UserService = Depends(get_user_service)):
    """Anyone can access this endpoint"""
    users = await svc.list_users()
    return users
```

**After (Protected with JWT):**
```python
from src.truefit_infra.auth.middleware import get_current_user, TokenPayload
from fastapi import Depends

@router.get("")
async def list_users(
    current_user: TokenPayload = Depends(get_current_user),
    svc: UserService = Depends(get_user_service)
):
    """Only authenticated users can access"""
    # current_user contains: user_id, email, role, org_id
    users = await svc.list_users()
    return users
```

**Frontend Usage:**
```typescript
const token = localStorage.getItem('authToken')
const response = await fetch('http://localhost:8000/api/v1/users', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
})
```

## Step 3: Use Current User Information in Endpoints

### Example 1: Get Current User's Data

```python
@router.get("/me")
async def get_my_profile(
    current_user: TokenPayload = Depends(get_current_user),
    svc: UserService = Depends(get_user_service)
):
    """Get current user's profile"""
    user = await svc.get_user(user_id=current_user.user_id)
    return {
        "id": user.id,
        "email": current_user.email,
        "role": current_user.role,
        "org_id": current_user.org_id,
    }
```

### Example 2: Create Resource with User Ownership

```python
@router.post("/jobs")
async def create_job(
    job_data: JobCreateRequest,
    current_user: TokenPayload = Depends(get_current_user),
    svc: JobService = Depends(get_job_service)
):
    """Create a job listing (current user becomes owner)"""
    job = await svc.create_job(
        title=job_data.title,
        description=job_data.description,
        created_by_user_id=current_user.user_id,  # Use current user
        org_id=current_user.org_id
    )
    return job
```

### Example 3: Role-Based Access Control

```python
@router.post("/rubrics")
async def create_rubric(
    rubric_data: RubricCreateRequest,
    current_user: TokenPayload = Depends(get_current_user),
    svc: RubricService = Depends(get_rubric_service)
):
    """Only recruiters can create rubrics"""
    if current_user.role not in ["recruiter", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only recruiters can create rubrics"
        )
    
    rubric = await svc.create_rubric(
        name=rubric_data.name,
        org_id=current_user.org_id,
        created_by_id=current_user.user_id
    )
    return rubric
```

## Step 4: Implement Protection Middleware

### Optional: Require Authentication for All Endpoints

Create a global middleware for specific route prefixes:

```python
# src/truefit_api/middlewares.py

from fastapi import Request
from src.truefit_infra.auth.middleware import get_current_user
from src.truefit_infra.auth.jwt import get_jwt_service

async def auth_required_middleware(request: Request, call_next):
    """Middleware to ensure /api/v1/protected/* endpoints require auth"""
    
    # Skip auth check for public endpoints
    public_paths = ["/api/v1/auth/oauth/token", "/api/v1/health"]
    if any(request.url.path.startswith(path) for path in public_paths):
        return await call_next(request)
    
    # Check for Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authorization header missing"}
        )
    
    return await call_next(request)
```

## Protected Endpoints Pattern

### Pattern 1: Required User Authentication

```python
@router.get("/interviews/{interview_id}")
async def get_interview(
    interview_id: str,
    current_user: TokenPayload = Depends(get_current_user),  # Required
    svc: InterviewService = Depends(get_interview_service)
):
    """Get interview details - authentication required"""
    interview = await svc.get_interview(interview_id)
    
    # Authorization check
    if interview.created_by_id != current_user.user_id:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not authorized")
    
    return interview
```

### Pattern 2: Optional User Context

```python
from typing import Optional

@router.get("/jobs")
async def list_jobs(
    auth_header: Optional[str] = Header(None),
    jwt_svc: JWTService = Depends(get_jwt_service),
    svc: JobService = Depends(get_job_service)
):
    """List jobs - optional authentication for personalized results"""
    current_user = None
    
    if auth_header:
        try:
            from src.truefit_infra.auth.middleware import verify_jwt_token
            current_user = await verify_jwt_token(jwt_svc, auth_header)
        except:
            pass  # User not authenticated, return public results
    
    jobs = await svc.list_jobs()
    
    if current_user:
        # Add personalized fields
        for job in jobs:
            job.applied_by_me = current_user.user_id in job.applicant_ids
    
    return jobs
```

## Token Lifecycle Management

### Check Token Expiration

```python
from datetime import datetime

def is_token_expired(token: str) -> bool:
    """Check if token is expired without verifying signature"""
    try:
        import json
        import base64
        
        # JWT format: header.payload.signature
        payload = token.split('.')[1]
        # Add padding if needed
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        
        exp = claims.get('exp')
        return datetime.fromtimestamp(exp) < datetime.utcnow()
    except:
        return True
```

### Frontend: Handle Token Expiration

```typescript
// src/helpers/auth.ts

export const getValidToken = async (): Promise<string | null> => {
  let token = localStorage.getItem('authToken');
  
  if (!token) return null;
  
  // Check if expired
  const payload = JSON.parse(
    atob(token.split('.')[1])
  );
  
  const isExpired = payload.exp * 1000 < Date.now();
  
  if (isExpired) {
    // Token expired - clear and redirect to login
    localStorage.removeItem('authToken');
    localStorage.removeItem('user');
    window.location.href = '/login';
    return null;
  }
  
  return token;
};

// Use in API calls
const response = await fetch(url, {
  headers: {
    'Authorization': `Bearer ${await getValidToken()}`
  }
});
```

## API Call Helper with Auto-Auth

```typescript
// src/helpers/api.ts

export class ApiClient {
  private getToken = () => localStorage.getItem('authToken');
  
  async request(
    url: string,
    options: RequestInit = {}
  ): Promise<Response> {
    const token = this.getToken();
    
    if (!token) {
      throw new Error('Not authenticated');
    }
    
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
        'Authorization': `Bearer ${token}`
      }
    });
    
    // Handle 401 - redirect to login
    if (response.status === 401) {
      localStorage.removeItem('authToken');
      window.location.href = '/login';
      throw new Error('Session expired');
    }
    
    return response;
  }
  
  get(url: string) {
    return this.request(url, { method: 'GET' });
  }
  
  post(url: string, data: any) {
    return this.request(url, {
      method: 'POST',
      body: JSON.stringify(data)
    });
  }
  
  put(url: string, data: any) {
    return this.request(url, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  }
  
  delete(url: string) {
    return this.request(url, { method: 'DELETE' });
  }
}

export const api = new ApiClient();

// Usage:
const interviews = await api.get('/api/v1/interviews');
const newJob = await api.post('/api/v1/jobs', { title: '...' });
```

## Complete Example: Interview Endpoints

```python
from fastapi import APIRouter, Depends
from src.truefit_infra.auth.middleware import get_current_user, TokenPayload

router = APIRouter(prefix="/interviews", tags=["interviews"])

@router.post("")
async def create_interview(
    data: InterviewCreateRequest,
    current_user: TokenPayload = Depends(get_current_user),  # Required
    svc: InterviewService = Depends(get_interview_service)
):
    """Create interview - only authenticated users"""
    interview = await svc.create_interview(
        title=data.title,
        job_id=data.job_id,
        created_by_id=current_user.user_id,
        org_id=current_user.org_id
    )
    return interview


@router.get("/{interview_id}")
async def get_interview(
    interview_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    svc: InterviewService = Depends(get_interview_service)
):
    """Get interview details"""
    interview = await svc.get_interview(interview_id)
    
    # Check access: owner, job creator, or admin
    if interview.created_by_id != current_user.user_id:
        job = await svc.get_job(interview.job_id)
        if job.created_by_id != current_user.user_id:
            if current_user.role != "admin":
                raise HTTPException(
                    status_code=403,
                    detail="Not authorized to view this interview"
                )
    
    return interview


@router.get("")
async def list_my_interviews(
    current_user: TokenPayload = Depends(get_current_user),
    svc: InterviewService = Depends(get_interview_service)
):
    """List current user's interviews"""
    interviews = await svc.list_interviews_for_user(
        user_id=current_user.user_id
    )
    return interviews
```

## Testing Protected Endpoints

### Using cURL

```bash
# Get token first
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/oauth/token \
  -H "Content-Type: application/json" \
  -d '{"token":"FIREBASE_TOKEN","provider":"firebase"}' | jq -r '.access_token')

# Use token in requests
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"

curl -X GET http://localhost:8000/api/v1/interviews \
  -H "Authorization: Bearer $TOKEN"
```

### Using Tests

```python
# tests/integration/test_auth_protected_endpoints.py

import pytest
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(client: TestClient):
    """Protected endpoints should return 401 without auth"""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_with_valid_token(
    client: TestClient,
    valid_jwt_token: str
):
    """Protected endpoints work with valid token"""
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {valid_jwt_token}"}
    )
    assert response.status_code == 200
```

## Summary

1. **All new endpoints**: Add `current_user: TokenPayload = Depends(get_current_user)` parameter
2. **Use current user info**: Access `current_user.user_id`, `current_user.email`, `current_user.role`
3. **Authorization checks**: Compare user ID or check role before returning data
4. **Frontend**: Add `Authorization: Bearer <token>` header to all requests
5. **Handle expiration**: Check token expiration and redirect to login if needed
