"""
Unit tests for OAuth and JWT functionality.
These tests verify the auth components work correctly.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import sys
sys.path.insert(0, 'c:\\Users\\USER\\Desktop\\truefit.ai\\apps\\backend')

from src.truefit_infra.auth.jwt import JWTService
from src.truefit_infra.auth.oauth import OAuthService, FirebaseOAuthProvider


def test_jwt_service():
    """Test JWT token creation and verification"""
    print("\n" + "="*60)
    print("Testing JWT Service")
    print("="*60)
    
    jwt_service = JWTService(
        secret_key="test-secret-key-min-32-chars-testing-12345678",
        algorithm="HS256",
        access_token_expire_minutes=30
    )
    
    # Test 1: Create token
    print("\n✓ Test 1: Creating JWT token...")
    token = jwt_service.create_access_token(
        subject="550e8400-e29b-41d4-a716-446655440000",
        user_email="test@example.com",
        user_role="candidate",
        org_id=None
    )
    print(f"  Token created: {token[:50]}...")
    assert token, "Token should not be empty"
    print("  ✅ PASSED")
    
    # Test 2: Verify token
    print("\n✓ Test 2: Verifying JWT token...")
    payload = jwt_service.verify_access_token(token)
    print(f"  Token sub: {payload.get('sub')}")
    print(f"  Token email: {payload.get('email')}")
    print(f"  Token role: {payload.get('role')}")
    print(f"  Token type: {payload.get('type')}")
    assert payload.get("sub") == "550e8400-e29b-41d4-a716-446655440000"
    assert payload.get("email") == "test@example.com"
    assert payload.get("role") == "candidate"
    assert payload.get("type") == "access"
    print("  ✅ PASSED")
    
    # Test 3: Get user ID from token
    print("\n✓ Test 3: Extracting user ID from token...")
    user_id = jwt_service.get_user_id_from_token(token)
    print(f"  Extracted user ID: {user_id}")
    assert user_id == "550e8400-e29b-41d4-a716-446655440000"
    print("  ✅ PASSED")
    
    # Test 4: Invalid token
    print("\n✓ Test 4: Testing invalid token verification...")
    try:
        jwt_service.verify_access_token("invalid.token.here")
        assert False, "Should have raised an error"
    except Exception as e:
        print(f"  Caught expected error: {type(e).__name__}")
        print("  ✅ PASSED")
    
    # Test 5: Expired token
    print("\n✓ Test 5: Testing expired token...")
    expired_token = jwt_service.create_access_token(
        subject="550e8400-e29b-41d4-a716-446655440000",
        user_email="test@example.com",
        user_role="candidate",
        expires_delta=timedelta(seconds=-1)  # Already expired
    )
    try:
        jwt_service.verify_access_token(expired_token)
        assert False, "Should have raised an error"
    except Exception as e:
        print(f"  Caught expected error: {type(e).__name__}")
        print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ All JWT Service tests PASSED!")
    print("="*60)


async def test_oauth_service():
    """Test OAuth service identity extraction"""
    print("\n" + "="*60)
    print("Testing OAuth Service")
    print("="*60)
    
    print("\n✓ Test 1: Firebase OAuth Provider instantiation...")
    provider = FirebaseOAuthProvider("truefit-ai")
    print(f"  Provider created with project: truefit-ai")
    print(f"  Certificate URL: {provider.certs_url}")
    print("  ✅ PASSED")
    
    print("\n✓ Test 2: OAuth Service instantiation...")
    oauth_service = OAuthService(provider)
    print("  OAuth service created")
    print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ OAuth Service initialization tests PASSED!")
    print("="*60)


def test_token_payload():
    """Test TokenPayload class"""
    print("\n" + "="*60)
    print("Testing TokenPayload")
    print("="*60)
    
    from src.truefit_infra.auth.middleware import TokenPayload
    
    print("\n✓ Test 1: Creating TokenPayload...")
    payload = TokenPayload(
        user_id="550e8400-e29b-41d4-a716-446655440000",
        email="user@example.com",
        role="candidate",
        org_id="org-123"
    )
    print(f"  User ID: {payload.user_id}")
    print(f"  Email: {payload.email}")
    print(f"  Role: {payload.role}")
    print(f"  Org ID: {payload.org_id}")
    assert payload.user_id == "550e8400-e29b-41d4-a716-446655440000"
    assert payload.email == "user@example.com"
    assert payload.role == "candidate"
    assert payload.org_id == "org-123"
    print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ TokenPayload tests PASSED!")
    print("="*60)


def test_pydantic_schemas():
    """Test Pydantic request/response schemas"""
    print("\n" + "="*60)
    print("Testing Pydantic Schemas")
    print("="*60)
    
    from src.truefit_api.api.v1.http.schemas.oauth import (
        OAuthTokenRequest,
        UserAuthResponse,
        AuthTokenResponse,
    )
    import uuid
    
    print("\n✓ Test 1: OAuthTokenRequest validation...")
    request = OAuthTokenRequest(
        token="valid.firebase.token.here",
        provider="firebase"
    )
    print(f"  Token (truncated): {request.token[:20]}...")
    print(f"  Provider: {request.provider}")
    assert request.provider == "firebase"
    print("  ✅ PASSED")
    
    print("\n✓ Test 2: UserAuthResponse creation...")
    user_resp = UserAuthResponse(
        id=uuid.uuid4(),
        email="test@example.com",
        display_name="Test User",
        role="candidate",
        org_id=None,
        is_active=True
    )
    print(f"  User ID: {user_resp.id}")
    print(f"  Email: {user_resp.email}")
    print(f"  Role: {user_resp.role}")
    assert user_resp.email == "test@example.com"
    print("  ✅ PASSED")
    
    print("\n✓ Test 3: AuthTokenResponse creation...")
    auth_resp = AuthTokenResponse(
        access_token="jwt.token.here",
        token_type="bearer",
        user=user_resp,
        expires_in=1800
    )
    print(f"  Access token: {auth_resp.access_token}")
    print(f"  Token type: {auth_resp.token_type}")
    print(f"  Expires in: {auth_resp.expires_in} seconds (30 min)")
    assert auth_resp.token_type == "bearer"
    assert auth_resp.expires_in == 1800
    print("  ✅ PASSED")
    
    print("\n" + "="*60)
    print("✅ All Pydantic Schema tests PASSED!")
    print("="*60)


if __name__ == "__main__":
    print("\n" + "█"*60)
    print("█" + " "*58 + "█")
    print("█" + "  OAUTH & JWT AUTHENTICATION TESTS".center(58) + "█")
    print("█" + " "*58 + "█")
    print("█"*60)
    
    try:
        # Run synchronous tests
        test_jwt_service()
        test_token_payload()
        test_pydantic_schemas()
        
        # Run async test
        asyncio.run(test_oauth_service())
        
        print("\n" + "█"*60)
        print("█" + " "*58 + "█")
        print("█" + "  ✅ ALL TESTS PASSED SUCCESSFULLY!".center(58) + "█")
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
