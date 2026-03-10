# OAuth Authentication Flow Integration Guide

## Overview

This document explains the OAuth authentication flow implemented in the TrueFit backend. The system uses OAuth providers (primarily Firebase with Google OAuth) for identity verification, then issues backend JWT tokens for session management.

## Architecture

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   Frontend  │         │   Backend    │         │   OAuth     │
│   (React)   │         │   (FastAPI)  │         │   Provider  │
└─────────────┘         └──────────────┘         │  (Firebase) │
      │                         │                 └─────────────┘
      │─ User clicks "Sign in"  │
      │─ Firebase popup         │
      │─ User authenticates     │
      │◄─ Firebase ID token     │
      │                         │
      │─ POST /api/v1/auth/oauth/token
      │─ { token: "...", provider: "firebase" }
      │                         │
      │                         │─ Verify token with Firebase
      │                         │◄─ Valid ✓
      │                         │
      │                         │─ Get or create user in DB
      │                         │
      │                         │─ Generate backend JWT
      │                         │
      │◄─ { access_token: "...", user: {...} }
      │
      │─ Store JWT in localStorage/sessionStorage
      │
      │─ GET /api/v1/auth/me
      │─ Header: "Authorization: Bearer <jwt>"
      │                         │
      │                         │─ Verify JWT
      │                         │
      │◄─ { id, email, role, ... }
```

## Components

### 1. JWT Service (`src/truefit_infra/auth/jwt.py`)

Manages creation and verification of backend JWT tokens.

**Key Methods:**
- `create_access_token()` - Create JWT with user claims
- `verify_access_token()` - Verify and decode JWT
- `get_user_id_from_token()` - Extract user ID without full verification

**Features:**
- Uses HS256 algorithm (HMAC with SHA-256)
- Configurable expiration (default: 30 minutes)
- Includes user claims: id, email, role, org_id
- Token type verification (access vs other types)

### 2. OAuth Service (`src/truefit_infra/auth/oauth.py`)

Handles OAuth provider token verification and identity extraction.

**Key Providers:**
- `FirebaseOAuthProvider` - Verifies Firebase ID tokens
- `GoogleOAuthProvider` - Verifies Google OAuth tokens

**Key Methods:**
- `verify_token()` - Verify with OAuth provider
- `verify_and_extract_identity()` - Verify and extract user info

**Extracted Identity:**
```json
{
  "provider_subject": "112345678901234567890",  // Provider's unique ID
  "email": "user@example.com",
  "name": "John Doe",
  "picture": "https://..."
}
```

### 3. Auth Middleware (`src/truefit_infra/auth/middleware.py`)

Validates JWT tokens in requests and provides authentication context.

**Key Functions:**
- `extract_token_from_header()` - Parse "Bearer <token>" format
- `verify_jwt_token()` - Verify JWT signature and claims
- `get_current_user()` - FastAPI dependency for protected endpoints

**Usage Pattern:**
```python
from src.truefit_infra.auth.middleware import get_current_user, TokenPayload

@router.get("/me")
async def get_me(current_user: TokenPayload = Depends(get_current_user)):
    return {
        "user_id": current_user.user_id,
        "email": current_user.email,
        "role": current_user.role
    }
```

### 4. Auth Endpoints (`src/truefit_api/api/v1/http/auth.py`)

Three main endpoints:

#### a. OAuth Token Exchange
**Endpoint:** `POST /api/v1/auth/oauth/token`

**Request:**
```json
{
  "token": "eyJhbGc...",  // Firebase ID token from frontend
  "provider": "firebase"   // OAuth provider type
}
```

**Response (201 Created):**
```json
{
  "access_token": "eyJhbGc...",  // Backend JWT
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

**Errors:**
- `401 Unauthorized` - Invalid OAuth token
- `403 Forbidden` - User account inactive
- `400 Bad Request` - Invalid parameters
- `500 Internal Server Error` - Unexpected error

#### b. Get Current User
**Endpoint:** `GET /api/v1/auth/me`

**Headers (Required):**
```
Authorization: Bearer eyJhbGc...
```

**Response:**
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

**Errors:**
- `401 Unauthorized` - Missing or invalid JWT
- `404 Not Found` - User not found
- `500 Internal Server Error` - Unexpected error

#### c. Logout
**Endpoint:** `POST /api/v1/auth/logout`

**Headers (Required):**
```
Authorization: Bearer eyJhbGc...
```

**Response:**
```json
{
  "detail": "Successfully logged out"
}
```

## User Creation Flow

When a user authenticates via OAuth:

1. **Token Verification**: Verify Firebase token signature and expiration
2. **Identity Extraction**: Extract `sub`, `email`, and other claims
3. **User Lookup**: Check if user exists by email
4. **Create or Update**:
   - If exists with same provider: Update `provider_subject` if different
   - If exists with different provider: Reject (or allow with configuration)
   - If doesn't exist: Create new user with role="candidate"
5. **Candidate Profile**: Create default candidate profile for new users
6. **JWT Generation**: Create backend JWT with user claims

See [UserService.get_or_create_oauth_user()](#userserviceget_or_create_oauth_user) for details.

## Database Schema

### User Table
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(320) NOT NULL UNIQUE,
    display_name VARCHAR(255),
    role VARCHAR(32) NOT NULL,
    auth_provider VARCHAR(64) NOT NULL,      -- "firebase", "google", etc.
    provider_subject VARCHAR(255) NOT NULL,  -- Provider's unique ID
    org_id UUID,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Key Fields:**
- `auth_provider`: OAuth provider name (required for audit)
- `provider_subject`: Provider's unique user ID (maps provider account to DB user)
- Both together ensure we can handle multiple OAuth providers

## Configuration

### Required Environment Variables

```env
# JWT Configuration
APP_SECRET_KEY=your-secret-key-here  # Use strong random key
ALGORITHM=HS256                      # Algorithm for JWT
ACCESS_TOKEN_EXPIRE_MINUTES=30       # Token expiration

# Firebase Configuration
GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json  # Firebase service account

# OAuth Provider
FIREBASE_PROJECT_ID=your-firebase-project-id  # For token verification
```

**Important Security Notes:**
- `APP_SECRET_KEY` should be a strong random string (minimum 32 characters)
- Use environment variables, never hardcode secrets
- Rotate `APP_SECRET_KEY` periodically (invalidates all existing tokens)

## Frontend Integration

### 1. Send Firebase Token to Backend

```typescript
// After Firebase authentication
const signInWithGoogle = async () => {
  try {
    const result = await signInWithPopup(auth, googleProvider);
    
    // Get the ID token
    const idToken = await result.user.getIdToken();
    
    // Exchange for backend JWT
    const response = await fetch('http://localhost:8000/api/v1/auth/oauth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: idToken,
        provider: 'firebase'
      })
    });
    
    if (!response.ok) throw new Error('Auth failed');
    
    const data = await response.json();
    
    // Store backend JWT
    localStorage.setItem('authToken', data.access_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    
    return data;
  } catch (error) {
    console.error('Authentication error:', error);
    throw error;
  }
};
```

### 2. Use JWT in Requests

```typescript
// Add to all API requests
const apiCall = async (url: string, options: RequestInit = {}) => {
  const token = localStorage.getItem('authToken');
  
  return fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${token}`
    }
  });
};

// Usage
const user = await apiCall('http://localhost:8000/api/v1/auth/me');
```

### 3. Handle Token Expiration

```typescript
// Check if token is expired
const isTokenExpired = (token: string) => {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload.exp * 1000 < Date.now();
  } catch {
    return true;
  }
};

// Redirect to login if expired
if (isTokenExpired(token)) {
  localStorage.removeItem('authToken');
  window.location.href = '/login';
}
```

### 4. Create Auth Context Hook

```typescript
// useAuthContext.tsx
export const useAuth = () => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('authToken'));
  
  const loginWithGoogle = async (idToken: string) => {
    const response = await fetch('/api/v1/auth/oauth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: idToken, provider: 'firebase' })
    });
    
    const data = await response.json();
    setToken(data.access_token);
    setUser(data.user);
    localStorage.setItem('authToken', data.access_token);
  };
  
  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('authToken');
  };
  
  return { user, token, loginWithGoogle, logout };
};
```

## Security Considerations

### 1. Token Storage
- **localStorage**: Persists across sessions, vulnerable to XSS
- **sessionStorage**: Cleared on browser close, still vulnerable to XSS
- **HttpOnly Cookie**: Secure, not accessible by JavaScript (recommended for production)

**Recommendation**: Use HttpOnly + Secure + SameSite cookies for production

### 2. CORS Configuration
Current CORS allows:
```python
allow_origins=[
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
```

**For Production**: Restrict to actual frontend domain and use HTTPS

### 3. OAuth Token Validation
- Always verify signature with OAuth provider's public keys
- Check token expiration before use
- Verify token is for correct application (audience)
- Never trust unverified tokens

### 4. Backend JWT Security
- Sign with strong secret key
- Set appropriate expiration time
- Include necessary claims but avoid sensitive data
- Validate all claims when verifying

### 5. HTTPS Required
- All OAuth tokens should only be transmitted over HTTPS
- Backend to OAuth provider communication must use HTTPS
- Set secure CORS policies

## Error Handling

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid authorization header format` | Missing "Bearer" prefix | Use `Authorization: Bearer <token>` |
| `Token has expired` | JWT expired | Implement token refresh or re-login |
| `Invalid authentication token` | Token tampered with | Clear token and re-authenticate |
| `Invalid Firebase token` | Bad Firebase ID token | Verify frontend sends correct token |
| `User account is inactive` | User disabled | Contact support/admin |
| `User already exists with different provider` | Email from different OAuth provider | Standard for now, may add federation |

## Testing

### 1. Test OAuth Token Endpoint

```bash
# 1. Get Firebase ID token from frontend (manual or via test)
FIREBASE_ID_TOKEN="eyJhbGc..."

# 2. Test OAuth token exchange
curl -X POST http://localhost:8000/api/v1/auth/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "token": "'$FIREBASE_ID_TOKEN'",
    "provider": "firebase"
  }'

# Expected response:
# {
#   "access_token": "eyJhbGc...",
#   "token_type": "bearer",
#   "expires_in": 1800,
#   "user": { ... }
# }
```

### 2. Test Protected Endpoint

```bash
JWT_TOKEN="eyJhbGc..."

curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $JWT_TOKEN"

# Expected response:
# {
#   "id": "550e8400...",
#   "email": "user@example.com",
#   ...
# }
```

### 3. Test with Expired Token

```bash
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer eyJhbGcOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjB9.xxx"

# Expected response (401):
# {
#   "detail": "Token has expired"
# }
```

## Related Files

- JWT Implementation: [jwt.py](./auth/jwt.py)
- OAuth Service: [oauth.py](./auth/oauth.py)
- Auth Middleware: [middleware.py](./auth/middleware.py)
- Auth Endpoints: [auth.py](./../../api/v1/http/auth.py)
- OAuth Schemas: [oauth.py](./../../api/v1/http/schemas/oauth.py)
- User Service: [user_service.py](./../../core/application/services/user_service.py)

## Troubleshooting

### Issue: "Invalid Firebase token"
1. Verify Firebase project ID matches config
2. Check Firebase service account credentials
3. Ensure token isn't expired

### Issue: "User with email already exists with different provider"
1. User already registered with different OAuth provider
2. Current: Multiple providers per email not supported
3. Future: Add provider federation logic

### Issue: Token not working in protected endpoints
1. Verify token is in Authorization header
2. Check format: `Authorization: Bearer <token>`
3. Ensure token hasn't expired
4. Verify APP_SECRET_KEY matches between requests

### Issue: CORS errors
1. Check frontend URL is in `allow_origins`
2. Verify request includes `Content-Type: application/json`
3. Ensure credentials are properly sent

## Next Steps

1. **Token Refresh**: Implement refresh token rotation for long-lived sessions
2. **OAuth Provider Federation**: Support multiple providers per user email
3. **Token Blacklisting**: Implement logout token invalidation
4. **Rate Limiting**: Add rate limits to auth endpoints
5. **Audit Logging**: Log all authentication events
6. **Two-Factor Authentication**: Add optional 2FA
7. **Session Management**: Track active sessions and allow revocation
