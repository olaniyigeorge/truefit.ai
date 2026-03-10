# OAuth Authentication Setup Guide

## Quick Start

### 1. Install Dependencies

```bash
cd apps/backend
pip install -r requirements.txt
```

This installs the newly added packages:
- **PyJWT==2.10.1** - For JWT token encoding/decoding
- **google-auth-httplib2==0.2.0** - For Firebase token verification

### 2. Update Environment Configuration

Add these to your `.env` file in the backend directory:

```env
# JWT Configuration
APP_SECRET_KEY="your-secret-key-min-32-chars-use-strong-random-string"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES="30"

# Firebase Configuration (if not already set)
FIREBASE_PROJECT_ID="truefit-ai"
```

**Generating a secure secret key:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Database Schema

No new database tables needed. The existing `users` table already has:
- `auth_provider` - Stores "firebase", "google", etc.
- `provider_subject` - Stores provider's unique user ID

### 4. Test the Implementation

#### Option A: Using cURL

```bash
# 1. Get a valid Firebase ID token (manual step from frontend)
# For testing: use Firebase Console or frontend sign-in

# 2. Test OAuth token endpoint
curl -X POST http://localhost:8000/api/v1/auth/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "token": "YOUR_FIREBASE_ID_TOKEN_HERE",
    "provider": "firebase"
  }'

# Expected response:
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

# 3. Test protected endpoint with JWT
JWT_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $JWT_TOKEN"

# Expected response:
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

#### Option B: Using Swagger UI

1. Start the backend:
```bash
cd apps/backend
python -m uvicorn src.truefit_api.main:app --reload
```

2. Open http://localhost:8000/api/docs

3. Find the OAuth endpoints:
   - `POST /api/v1/auth/oauth/token`
   - `GET /api/v1/auth/me`
   - `POST /api/v1/auth/logout`

4. Test the endpoints directly in Swagger UI

### 5. Frontend Integration

In your React frontend (e.g., `apps/frontend/src/pages/auth/Signin.tsx`):

```typescript
import { signInWithPopup, GoogleAuthProvider } from "firebase/auth"
import { auth } from "@/helpers/firebase"

const handleGoogleSignIn = async () => {
  try {
    const googleProvider = new GoogleAuthProvider()
    const result = await signInWithPopup(auth, googleProvider)
    
    // Get Firebase ID token
    const idToken = await result.user.getIdToken()
    
    // Exchange for backend JWT
    const response = await fetch(
      `${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/api/v1/auth/oauth/token`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: idToken,
          provider: 'firebase'
        })
      }
    )
    
    if (!response.ok) {
      throw new Error('Authentication failed')
    }
    
    const data = await response.json()
    
    // Store backend JWT
    localStorage.setItem('authToken', data.access_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    
    // Navigate to dashboard
    navigate('/dashboard', { replace: true })
  } catch (error: any) {
    console.error('Google sign-in failed:', error)
    // Show error to user
  }
}
```

### 6. Using JWT in API Calls

Create a utility function to automatically add JWT to requests:

```typescript
// src/helpers/api.ts
export const apiCall = (
  url: string,
  options: RequestInit = {}
): Promise<Response> => {
  const token = localStorage.getItem('authToken')
  
  return fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'Content-Type': 'application/json',
      ...(token && { 'Authorization': `Bearer ${token}` })
    }
  })
}

// Usage in components:
const response = await apiCall('http://localhost:8000/api/v1/auth/me')
const user = await response.json()
```

### 7. Verify User Created in Database

```bash
# Connect to your database
psql -U postgres -d your_database

# Query users table
SELECT id, email, auth_provider, provider_subject, created_at 
FROM users 
ORDER BY created_at DESC 
LIMIT 10;
```

You should see:
- New user with email from OAuth
- `auth_provider = "firebase"`
- `provider_subject = "Firebase's unique user ID"`
- `created_at = current timestamp`

## Troubleshooting

### Error: "Invalid Firebase token"

Check:
1. Is Firebase project ID correct? (currently hardcoded as "truefit-ai")
2. Is the token from the right Firebase project?
3. Are Firebase credentials (`GOOGLE_APPLICATION_CREDENTIALS`) set?

### Error: "User already exists with different provider"

This happens if a user tries to sign in with OAuth but already exists with a different auth method.

**Solution**: For now, use same OAuth provider. Future: implement provider federation.

### Error: "Token has expired"

Your backend JWT expired. The frontend should:
1. Clear the token: `localStorage.removeItem('authToken')`
2. Redirect to login: `window.location.href = '/signin'`

### Error: CORS issues

Ensure your frontend URL is in backend CORS config (`src/truefit_api/main.py`):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Your frontend URL
        "http://localhost:5173",
        # Add production URLs here
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Files Summary

| File | Purpose |
|------|---------|
| `auth/jwt.py` | JWT token creation/verification |
| `auth/oauth.py` | OAuth provider verification |
| `auth/middleware.py` | JWT validation for protected endpoints |
| `api/v1/http/auth.py` | OAuth and auth endpoints |
| `api/v1/http/schemas/oauth.py` | Request/response models |
| `core/application/services/user_service.py` | User creation from OAuth |

## Next Steps

1. ✅ Backend OAuth setup complete
2. 📋 Frontend integration (React signin component)
3. 🔧 Add JWT to existing API calls
4. 🧪 End-to-end testing
5. 🔐 Security review before production

## Documentation

Full integration guide: See `/OAUTH_INTEGRATION_GUIDE.md` in the project root.

For API documentation: http://localhost:8000/api/docs (Swagger UI)

## Security Checklist

- [ ] `APP_SECRET_KEY` is strong (32+ chars, random)
- [ ] Never commit `.env` with real secrets
- [ ] Firebase project ID matches your Firebase project
- [ ] Frontend CORS only allows your domain
- [ ] HTTPS enabled in production
- [ ] Token expiration set appropriately (30 min default)
- [ ] Never expose JWT in logs
- [ ] Test with expired and tampered tokens
