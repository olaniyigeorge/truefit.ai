"""
Pydantic models for OAuth authentication flow.
Defines request/response schemas for OAuth endpoints.
"""

from typing import Optional
import uuid
from pydantic import BaseModel, Field


class OAuthTokenRequest(BaseModel):
    """Request body for OAuth token exchange."""

    token: str = Field(
        ...,
        description="OAuth provider token (e.g., Firebase ID token)",
        min_length=10,
    )
    provider: str = Field(
        default="firebase",
        description="OAuth provider type (firebase, google)",
        pattern="^(firebase|google)$",
    )


class AuthTokenResponse(BaseModel):
    """Response containing backend JWT access token and user info."""

    access_token: str = Field(..., description="Backend JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    user: "UserAuthResponse" = Field(..., description="Authenticated user info")
    expires_in: int = Field(
        default=1800,
        description="Token expiration time in seconds",
    )
    is_new_user: bool = Field(
        default=False, description="True if this is the user's first sign-in"
    )


class UserAuthResponse(BaseModel):
    """User information returned after successful authentication."""

    id: uuid.UUID = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    display_name: Optional[str] = Field(None, description="User display name")
    role: str = Field(..., description="User role (admin, recruiter, candidate)")
    org_id: Optional[uuid.UUID] = Field(None, description="Organization ID if member")
    is_active: bool = Field(..., description="Whether user account is active")


class OAuthErrorResponse(BaseModel):
    """Error response for OAuth operations."""

    detail: str = Field(..., description="Error message")
    code: str = Field(..., description="Error code")


class RefreshTokenRequest(BaseModel):
    """Request to refresh an expired JWT token."""

    refresh_token: Optional[str] = Field(
        None,
        description="Refresh token (optional for now, for future enhancement)",
    )


class CurrentUserResponse(BaseModel):
    """Response for getting current authenticated user info."""

    id: uuid.UUID = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    display_name: Optional[str] = Field(None, description="User display name")
    role: str = Field(..., description="User role")
    org_id: Optional[uuid.UUID] = Field(None, description="Organization ID")
    is_active: bool = Field(..., description="Account active status")
    created_at: str = Field(..., description="Account creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
