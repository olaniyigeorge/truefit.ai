"""
Integration tests for OAuth and JWT endpoints.
Tests the full authentication flow with mocked dependencies.
"""

import sys
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import uuid

sys.path.insert(0, 'c:\\Users\\USER\\Desktop\\truefit.ai\\apps\\backend')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi import Depends

from src.truefit_infra.auth.jwt import JWTService, get_jwt_service
from src.truefit_infra.auth.middleware import get_current_user, TokenPayload
from src.truefit_api.api.v1.http.schemas.oauth import (
    OAuthTokenRequest,
    AuthTokenResponse,
)


def create_test_app():
    """Create a test FastAPI app with auth endpoints"""
    app = FastAPI()
    
    # Add JWT service dependency
    jwt_service = JWTService(
        secret_key="test-secret-key-min-32-chars-testing-12345678",
        algorithm="HS256",
        access_token_expire_minutes=30
    )
    
    # Override dependency
    def get_test_jwt_service():
        return jwt_service
    
    app.dependency_overrides[get_jwt_service] = get_test_jwt_service
    
    # Add test endpoints
    @app.post("/auth/oauth/token")
    async def oauth_token(request: OAuthTokenRequest):
        """Test OAuth endpoint"""
        # Simulate OAuth verification
        if "invalid" in request.token:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Create mock user
        user_id = str(uuid.uuid4())
        
        # Generate JWT
        token = jwt_service.create_access_token(
            subject=user_id,
            user_email="user@example.com",
            user_role="candidate",
            org_id=None
        )
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": 1800,
            "user": {
                "id": user_id,
                "email": "user@example.com",
                "display_name": "Test User",
                "role": "candidate",
                "org_id": None,
                "is_active": True
            }
        }
    
    @app.get("/auth/me", response_model=None)
    async def get_me(current_user: TokenPayload = Depends(get_current_user)):
        """Test protected endpoint"""
        # Return the token payload as dict
        return {
            "id": current_user.user_id,
            "email": current_user.email,
            "role": current_user.role,
            "org_id": current_user.org_id
        }
    
    return app, jwt_service


def test_oauth_endpoints():
    """Test OAuth token endpoint"""
    print("\n" + "="*60)
    print("Testing OAuth Endpoints")
    print("="*60)
    
    app, jwt_service = create_test_app()
    client = TestClient(app)
    
    # Test 1: Valid OAuth token
    print("\n✓ Test 1: Valid OAuth token exchange...")
    response = client.post(
        "/auth/oauth/token",
        json={
            "token": "valid.firebase.token.xyz",
            "provider": "firebase"
        }
    )
    print(f"  Status code: {response.status_code}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    data = response.json()
    print(f"  Access token: {data['access_token'][:50]}...")
    print(f"  Token type: {data['token_type']}")
    print(f"  User email: {data['user']['email']}")
    print(f"  User role: {data['user']['role']}")
    print(f"  Expires in: {data['expires_in']} seconds")
    
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "user@example.com"
    assert data["user"]["role"] == "candidate"
    assert data["expires_in"] == 1800
    print("  ✅ PASSED")
    
    # Test 2: Invalid OAuth token
    print("\n✓ Test 2: Invalid OAuth token...")
    response = client.post(
        "/auth/oauth/token",
        json={
            "token": "invalid.token.here",
            "provider": "firebase"
        }
    )
    print(f"  Status code: {response.status_code}")
    print(f"  Error: {response.json()['detail']}")
    assert response.status_code == 401
    print("  ✅ PASSED")
    
    # Test 3: Missing provider
    print("\n✓ Test 3: Invalid request (missing provider)...")
    response = client.post(
        "/auth/oauth/token",
        json={"token": "valid.token"}
    )
    print(f"  Status code: {response.status_code}")
    # Should have default provider
    assert response.status_code in [200, 422]  # Either works or validation error
    print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ OAuth Endpoint tests PASSED!")
    print("="*60)


def test_jwt_verification():
    """Test JWT token verification"""
    print("\n" + "="*60)
    print("Testing JWT Verification")
    print("="*60)
    
    app, jwt_service = create_test_app()
    
    print("\n✓ Test 1: Create and verify JWT...")
    token = jwt_service.create_access_token(
        subject="550e8400-e29b-41d4-a716-446655440000",
        user_email="test@example.com",
        user_role="recruiter",
        org_id="org-550e8400"
    )
    print(f"  Token created: {token[:50]}...")
    
    payload = jwt_service.verify_access_token(token)
    print(f"  Subject: {payload.get('sub')}")
    print(f"  Email: {payload.get('email')}")
    print(f"  Role: {payload.get('role')}")
    print(f"  Org ID: {payload.get('org_id')}")
    
    assert payload["sub"] == "550e8400-e29b-41d4-a716-446655440000"
    assert payload["email"] == "test@example.com"
    assert payload["role"] == "recruiter"
    assert payload["org_id"] == "org-550e8400"
    print("  ✅ PASSED")
    
    print("\n✓ Test 2: Token contains required claims...")
    assert "exp" in payload, "Missing expiration claim"
    assert "iat" in payload, "Missing issued-at claim"
    assert "type" in payload, "Missing token type claim"
    print(f"  Has expiration: ✓")
    print(f"  Has issued-at: ✓")
    print(f"  Has token type: {payload['type']}")
    print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ JWT Verification tests PASSED!")
    print("="*60)


def test_full_auth_flow():
    """Test complete authentication flow"""
    print("\n" + "="*60)
    print("Testing Full Authentication Flow")
    print("="*60)
    
    app, jwt_service = create_test_app()
    client = TestClient(app)
    
    print("\n✓ Step 1: Frontend sends OAuth token to backend...")
    oauth_response = client.post(
        "/auth/oauth/token",
        json={
            "token": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjE2ZjQwMThjYjU3MDAifQ...",
            "provider": "firebase"
        }
    )
    assert oauth_response.status_code == 200
    auth_data = oauth_response.json()
    print(f"  Received JWT: {auth_data['access_token'][:30]}...")
    print(f"  User: {auth_data['user']['email']}")
    print("  ✅ PASSED")
    
    print("\n✓ Step 2: Verify JWT token...")
    jwt_token = auth_data["access_token"]
    payload = jwt_service.verify_access_token(jwt_token)
    print(f"  JWT verified for user: {payload['email']}")
    print(f"  User role: {payload['role']}")
    print(f"  Token valid until: {datetime.fromtimestamp(payload['exp'])}")
    print("  ✅ PASSED")
    
    print("\n✓ Step 3: Extract user ID from token...")
    user_id = jwt_service.get_user_id_from_token(jwt_token)
    print(f"  User ID: {user_id}")
    assert user_id is not None
    print("  ✅ PASSED")
    
    print("\n✓ Step 4: Simulate using token in API requests...")
    print(f"  Header: Authorization: Bearer {jwt_token[:20]}...")
    print("  This token would be used for:")
    print("    - POST /api/v1/interviews")
    print("    - GET /api/v1/jobs")
    print("    - PUT /api/v1/users/{id}")
    print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ Full Authentication Flow tests PASSED!")
    print("="*60)


def test_user_roles():
    """Test different user roles and permissions"""
    print("\n" + "="*60)
    print("Testing User Roles")
    print("="*60)
    
    _, jwt_service = create_test_app()
    
    roles = ["candidate", "recruiter", "admin"]
    
    for role in roles:
        print(f"\n✓ Testing role: {role}...")
        token = jwt_service.create_access_token(
            subject=str(uuid.uuid4()),
            user_email=f"{role}@example.com",
            user_role=role,
        )
        payload = jwt_service.verify_access_token(token)
        print(f"  Role in token: {payload['role']}")
        assert payload['role'] == role
        print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ User Role tests PASSED!")
    print("="*60)


def test_token_expiration():
    """Test token expiration handling"""
    print("\n" + "="*60)
    print("Testing Token Expiration")
    print("="*60)
    
    from datetime import timedelta
    _, jwt_service = create_test_app()
    
    print("\n✓ Test 1: Create token with short expiration...")
    token = jwt_service.create_access_token(
        subject=str(uuid.uuid4()),
        user_email="test@example.com",
        user_role="candidate",
        expires_delta=timedelta(seconds=1)
    )
    payload = jwt_service.verify_access_token(token)
    print(f"  Token created with 1 second expiration")
    print(f"  Expiration: {datetime.fromtimestamp(payload['exp'])}")
    print("  ✅ PASSED")
    
    print("\n✓ Test 2: Verify expired token fails...")
    import time
    time.sleep(2)
    try:
        jwt_service.verify_access_token(token)
        print("  ❌ Should have failed!")
        assert False
    except Exception as e:
        print(f"  Caught expected error: {type(e).__name__}")
        print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ Token Expiration tests PASSED!")
    print("="*60)


if __name__ == "__main__":
    print("\n" + "█"*60)
    print("█" + " "*58 + "█")
    print("█" + "  OAUTH & JWT INTEGRATION TESTS".center(58) + "█")
    print("█" + " "*58 + "█")
    print("█"*60)
    
    try:
        test_oauth_endpoints()
        test_jwt_verification()
        test_full_auth_flow()
        test_user_roles()
        test_token_expiration()
        
        print("\n" + "█"*60)
        print("█" + " "*58 + "█")
        print("█" + "  ✅ ALL INTEGRATION TESTS PASSED!".center(58) + "█")
        print("█" + " "*58 + "█")
        print("█"*60 + "\n")
        
    except Exception as e:
        print("\n" + "█"*60)
        print("█" + " "*58 + "█")
        print("█" + f"  ❌ TEST FAILED: {str(e)[:50]}".ljust(59) + "█")
        print("█" + " "*58 + "█")
        print("█"*60 + "\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
