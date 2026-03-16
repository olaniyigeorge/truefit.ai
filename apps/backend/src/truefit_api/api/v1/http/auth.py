"""
OAuth authentication endpoints.
Handles OAuth token verification and backend JWT issuance.
"""

from typing import Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from src.truefit_infra.auth.jwt import JWTService, get_jwt_service
from src.truefit_infra.auth.oauth import get_oauth_service
from src.truefit_infra.auth.middleware import get_current_user, TokenPayload
from src.truefit_infra.db.database import db_manager
from src.truefit_infra.db.repositories.user_repository import SQLAlchemyUserRepository
from src.truefit_infra.db.repositories.org_repository import SQLAlchemyOrgRepository
from src.truefit_infra.db.repositories.candidate_profile_repository import (
    SQLAlchemyCandidateProfileRepository,
)

from src.truefit_core.application.services.user_service import UserService
from src.truefit_core.common.utils import logger

from src.truefit_api.api.v1.http.schemas.oauth import (
    OAuthTokenRequest,
    AuthTokenResponse,
    UserAuthResponse,
    CurrentUserResponse,
)
from src.truefit_infra.config import AppConfig

router = APIRouter(prefix="/auth", tags=["authentication"])


def get_user_service() -> UserService:
    """Dependency to get UserService instance."""
    return UserService(
        user_repo=SQLAlchemyUserRepository(db_manager),
        org_repo=SQLAlchemyOrgRepository(db_manager),
        candidate_profile_repo=SQLAlchemyCandidateProfileRepository(db_manager),
    )


@router.post("/oauth/token", response_model=AuthTokenResponse)
async def oauth_authenticate(
    request: OAuthTokenRequest,
    jwt_svc: JWTService = Depends(get_jwt_service),
    user_svc: UserService = Depends(get_user_service),
) -> AuthTokenResponse:
    """
    Authenticate user with OAuth provider and issue backend JWT.
    
    Flow:
    1. Receive OAuth provider token from frontend
    2. Verify token with OAuth provider
    3. Extract user identity (email, name, provider_subject)
    4. Create or get user from database
    5. Generate backend JWT token
    6. Return JWT and user info to frontend
    
    Args:
        request: OAuth token request with provider token and type
        jwt_svc: JWT service for token generation
        user_svc: User service for database operations
    
    Returns:
        AuthTokenResponse with JWT access token and user info
    
    Raises:
        HTTPException: If OAuth verification fails or user creation fails
    """
    try:
        # Step 1: Get OAuth service for the specified provider
        oauth_svc = get_oauth_service(
            provider_type=request.provider,
            project_id=AppConfig.FIREBASE_PROJECT_ID
        )
        
        # Step 2: Verify OAuth token with provider
        identity = await oauth_svc.verify_and_extract_identity(request.token)
        
        logger.info(f"OAuth token verified for {identity['email']}")
        
        # Step 3: Get or create user in database
        user, is_new_user = await user_svc.get_or_create_oauth_user(
            email=identity["email"],
            provider=request.provider,
            provider_subject=identity["provider_subject"],
            display_name=identity.get("name"),
        )
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to authenticate user",
            )
        
        # Step 4: Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        
        # Step 5: Generate backend JWT token
        access_token = jwt_svc.create_access_token(
            subject=str(user.id),
            user_email=user.email,
            user_role=user.role.value if hasattr(user.role, "value") else str(user.role),
            org_id=str(user.org_id) if user.org_id else None,
        )
        
        logger.info(f"JWT token issued for user {user.email}")
        
        # Step 6: Return response
        return AuthTokenResponse(
            access_token=access_token,
            is_new_user=is_new_user,
            user=UserAuthResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=user.role.value if hasattr(user.role, "value") else str(user.role),
                org_id=user.org_id,
                is_active=user.is_active,
            ),
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"OAuth verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OAuth token",
        )
    except ValidationError as e:
        logger.error(f"Validation error in OAuth flow: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request parameters",
        )
    except Exception as e:
        logger.error(f"Unexpected error in OAuth flow: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed",
        )


@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user_info(
    current_user: TokenPayload = Depends(get_current_user),
    user_svc: UserService = Depends(get_user_service),
) -> CurrentUserResponse:
    """
    Get current authenticated user information.
    
    Requires: Valid JWT in Authorization header (Bearer token)
    
    Args:
        current_user: Current user from JWT token
        user_svc: User service for database operations
    
    Returns:
        CurrentUserResponse with user details
    
    Raises:
        HTTPException: If user not found or not authenticated
    """
    try:
        # Get fresh user data from database
        user = await user_svc.get_user(user_id=current_user.user_id)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        
        return CurrentUserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            org_id=user.org_id,
            is_active=user.is_active,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user information",
        )

@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh_token(
    current_user: TokenPayload = Depends(get_current_user),
    jwt_svc: JWTService = Depends(get_jwt_service),
    user_svc: UserService = Depends(get_user_service),
) -> AuthTokenResponse:
    """Issue a fresh JWT with latest user data from DB."""
    user = await user_svc.get_user(uuid.UUID(current_user.user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    access_token = jwt_svc.create_access_token(
        subject=str(user.id),
        user_email=user.email,
        user_role=user.role.value if hasattr(user.role, "value") else str(user.role),
        org_id=str(user.org_id) if user.org_id else None,
    )

    return AuthTokenResponse(
        access_token=access_token,
        is_new_user=False,
        user=UserAuthResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            org_id=user.org_id,
            is_active=user.is_active,
        ),
    )



@router.post("/logout")
async def logout(
    current_user: TokenPayload = Depends(get_current_user),
):
    """
    Logout endpoint (marks token as invalid on frontend).
    
    Note: JWT tokens are stateless, so logout is handled by removing
    the token from the frontend. This endpoint can be extended to
    implement token blacklisting if needed.
    
    Args:
        current_user: Current authenticated user
    
    Returns:
        Success message
    """
    logger.info(f"User {current_user.email} logged out")
    return {"detail": "Successfully logged out"}
