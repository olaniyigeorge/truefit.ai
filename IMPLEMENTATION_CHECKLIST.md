# OAuth Implementation - Implementation Checklist

## ✅ Backend Implementation Complete

### Core Authentication Components
- [x] **JWT Service** (`src/truefit_infra/auth/jwt.py`)
  - JWT token creation with user claims
  - Token verification and validation
  - Secure signature validation (HS256)

- [x] **OAuth Service** (`src/truefit_infra/auth/oauth.py`)
  - Firebase token verification
  - Google OAuth token verification
  - User identity extraction
  - Provider-agnostic architecture

- [x] **Auth Middleware** (`src/truefit_infra/auth/middleware.py`)
  - JWT extraction from Authorization header
  - Token validation on protected routes
  - Current user dependency injection

- [x] **Auth Endpoints** (`src/truefit_api/api/v1/http/auth.py`)
  - `POST /api/v1/auth/oauth/token` - OAuth token exchange
  - `GET /api/v1/auth/me` - Get current user
  - `POST /api/v1/auth/logout` - Logout endpoint

- [x] **Schemas** (`src/truefit_api/api/v1/http/schemas/oauth.py`)
  - Request/response validation
  - Type hints and documentation

- [x] **UserService Enhancement** (`src/truefit_core/application/services/user_service.py`)
  - OAuth user creation/retrieval
  - Automatic candidate profile creation
  - Provider consistency checking

### Framework Integration
- [x] Main app updated with auth router
- [x] Dependencies exposed for injection
- [x] Requirements.txt updated with:
  - PyJWT==2.10.1
  - google-auth-httplib2==0.2.0

## 📋 Next Steps - Frontend Implementation

### 1. Install Dependencies
```bash
# No additional npm packages needed - Firebase already included
# Verify in frontend/package.json that firebase is present
```

### 2. Update Sign-In Component
**File:** `apps/frontend/src/pages/auth/Signin.tsx`

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
      'http://localhost:8000/api/v1/auth/oauth/token',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: idToken,
          provider: 'firebase'
        })
      }
    )
    
    if (!response.ok) throw new Error(await response.text())
    
    const data = await response.json()
    
    // Store JWT and user info
    localStorage.setItem('authToken', data.access_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    
    // Navigate to dashboard
    navigate('/dashboard', { replace: true })
  } catch (error) {
    form.setError('root', { 
      message: error.message || 'Sign in failed' 
    })
  }
}
```

### 3. Create Auth Context Hook
**File:** `apps/frontend/src/hooks/useAuth.tsx` (replace existing)

```typescript
import { useContext } from 'react'
import { AuthContext } from '@/context/authContext'

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
```

### 4. Create API Helper with JWT
**File:** `apps/frontend/src/helpers/api.ts`

```typescript
const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000'

export const apiCall = async (
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> => {
  const token = localStorage.getItem('authToken')
  
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  }
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  })
  
  // Handle token expiration
  if (response.status === 401) {
    localStorage.removeItem('authToken')
    localStorage.removeItem('user')
    window.location.href = '/signin'
    throw new Error('Session expired')
  }
  
  return response
}

// Convenience methods
export const api = {
  get: (endpoint: string) => apiCall(endpoint, { method: 'GET' }),
  post: (endpoint: string, data?: any) => apiCall(endpoint, {
    method: 'POST',
    body: data ? JSON.stringify(data) : undefined,
  }),
  put: (endpoint: string, data?: any) => apiCall(endpoint, {
    method: 'PUT',
    body: data ? JSON.stringify(data) : undefined,
  }),
  delete: (endpoint: string) => apiCall(endpoint, { method: 'DELETE' }),
}
```

### 5. Update Protected Components
Update components that need authentication:

```typescript
import { useAuth } from '@/hooks/useAuth'
import { useEffect } from 'react'
import { useNavigate } from 'react-router'

export const ProtectedComponent = () => {
  const { user, loading } = useAuth()
  const navigate = useNavigate()
  
  useEffect(() => {
    if (!loading && !user) {
      navigate('/signin')
    }
  }, [loading, user, navigate])
  
  if (loading) return <LoadingSpinner />
  if (!user) return null
  
  return <div>{/* Component content */}</div>
}
```

## 🔧 Backend Configuration

### 1. Update Environment Variables
**File:** `apps/backend/.env`

```env
# JWT Configuration (Choose ONE approach)

# APPROACH 1: Simple HS256 (Good for development/testing)
APP_SECRET_KEY="your-secret-key-min-32-chars-random-string"

# APPROACH 2: Use Python to generate
# python -c "import secrets; print(secrets.token_urlsafe(32))"

ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES="30"

# Firebase Configuration
FIREBASE_PROJECT_ID="truefit-ai"
GOOGLE_APPLICATION_CREDENTIALS="path/to/firebase-key.json"
```

### 2. Update CORS for Production
**File:** `apps/backend/src/truefit_api/main.py`

For development:
```python
allow_origins=[
    "http://localhost:3000",
    "http://localhost:5173",
]
```

For production:
```python
allow_origins=[
    "https://yourdomain.com",
    "https://www.yourdomain.com",
]
```

### 3. Install Python Packages
```bash
cd apps/backend
pip install -r requirements.txt
```

New packages:
- PyJWT==2.10.1
- google-auth-httplib2==0.2.0

## 🧪 Testing Checklist

### Backend Tests
- [ ] Test OAuth token endpoint with valid Firebase token
- [ ] Test OAuth token endpoint with invalid token
- [ ] Test OAuth token endpoint with expired token
- [ ] Test /auth/me endpoint with valid JWT
- [ ] Test /auth/me endpoint without Authorization header
- [ ] Test /auth/me endpoint with invalid JWT
- [ ] Verify new user created in database after first login
- [ ] Verify user not duplicated on second login
- [ ] Test logout endpoint
- [ ] Verify JWT expiration (after 30 minutes by default)

### Frontend Tests
- [ ] Google sign-in button works
- [ ] Firebase authentication popup appears
- [ ] Token received and stored in localStorage
- [ ] Redirected to dashboard after sign-in
- [ ] API calls include Authorization header
- [ ] 401 errors redirect to sign-in
- [ ] User info displays correctly
- [ ] Sign-out clears token and user data
- [ ] Protected routes redirect to sign-in when not authenticated

### Integration Tests
- [ ] Full flow: Click Google → Sign in → Redirect → API call works
- [ ] Token persists across page refreshes
- [ ] Expired token triggers re-login
- [ ] User can sign in with same email multiple times

## 📚 Documentation Files

Created documentation in project root:

1. **OAUTH_INTEGRATION_GUIDE.md** - Comprehensive technical guide
   - Architecture overview
   - Component descriptions
   - Database schema
   - Security considerations
   - Full API documentation
   - Troubleshooting guide

2. **OAUTH_SETUP_GUIDE.md** - Quick start guide
   - Installation steps
   - Environment configuration
   - Testing with cURL
   - Frontend integration examples
   - Security checklist

3. **OAUTH_USAGE_EXAMPLES.md** - Practical examples
   - How to protect endpoints
   - Use current user in endpoints
   - Role-based access control
   - Token lifecycle management
   - Complete working examples

4. **IMPLEMENTATION_CHECKLIST.md** - This file
   - Backend completion status
   - Frontend tasks
   - Testing checklist
   - Documentation reference

## 🔒 Security Reminders

- [ ] Never commit `.env` file with real secrets
- [ ] Use strong random `APP_SECRET_KEY` (min 32 chars)
- [ ] Enable HTTPS in production
- [ ] Keep `GOOGLE_APPLICATION_CREDENTIALS` secure
- [ ] Restrict CORS to actual frontend domain
- [ ] Implement rate limiting on auth endpoints
- [ ] Log authentication events
- [ ] Monitor for suspicious login patterns

## 🚀 Production Deployment

Before going live:

1. [ ] Generate strong `APP_SECRET_KEY` in production
2. [ ] Update CORS origins to match frontend domain
3. [ ] Use environment-specific configuration (dev/staging/prod)
4. [ ] Set up HTTPS/SSL certificates
5. [ ] Configure Firebase production project
6. [ ] Update frontend API base URL to production backend
7. [ ] Test complete authentication flow
8. [ ] Set up error monitoring (Sentry, etc.)
9. [ ] Configure database backups
10. [ ] Set up audit logging

## 🆘 Support & Troubleshooting

### Common Issues

**Issue:** "Invalid Firebase token"
- Solution: Verify Firebase project ID, check certificate
- See: `OAUTH_INTEGRATION_GUIDE.md` → Troubleshooting

**Issue:** "User already exists with different provider"
- Solution: Current system doesn't support multiple OAuth providers per email
- Future: Implement OAuth federation

**Issue:** CORS errors in frontend
- Solution: Update `allow_origins` in main.py to include frontend URL
- See: `OAUTH_SETUP_GUIDE.md` → Troubleshooting

**Issue:** 401 Unauthorized on protected endpoints
- Solution: Check JWT is in Authorization header with "Bearer" prefix
- See: `OAUTH_USAGE_EXAMPLES.md` → Testing Protected Endpoints

### For More Help

- Full technical guide: `OAUTH_INTEGRATION_GUIDE.md`
- API documentation: `http://localhost:8000/api/docs` (Swagger UI)
- Examples and patterns: `OAUTH_USAGE_EXAMPLES.md`

## 📝 Summary

✅ **Completed by Backend:**
- JWT service implementation
- OAuth verification service  
- Auth middleware for JWT validation
- Three auth endpoints (oauth/token, /me, /logout)
- User service OAuth integration
- Framework integration

📋 **You Need to Complete:**
- Frontend: Update sign-in component with backend OAuth flow
- Frontend: Create API helper with JWT support
- Frontend: Update protected components
- Configuration: Set environment variables
- Testing: Run through complete authentication flow

## ⏱️ Estimated Time

**Backend Setup (Already Done):** 2-3 hours
**Frontend Integration:** 1-2 hours
**Testing:** 1-2 hours
**Total:** 4-7 hours

## 🎯 Success Criteria

- User can sign in with Google OAuth
- Backend JWT issued and stored
- JWT accepted on protected endpoints
- User info persists across page refresh
- 401 errors handled gracefully
- New users created in database
- Existing users updated on re-login

## 📞 Questions?

Refer to:
1. `OAUTH_INTEGRATION_GUIDE.md` - Technical architecture
2. `OAUTH_SETUP_GUIDE.md` - Setup and configuration
3. `OAUTH_USAGE_EXAMPLES.md` - Code examples and patterns
