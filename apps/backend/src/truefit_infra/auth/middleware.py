"""
Authentication middleware for verifying JWT tokens in requests.
Extracts and validates JWT from Authorization header.
"""

from typing import Optional
import jwt
from fastapi import Depends, HTTPException, status
from starlette.requests import Request

from src.truefit_infra.auth.jwt import JWTService, get_jwt_service
from src.truefit_core.common.utils import logger


class TokenPayload:
    """Represents verified JWT token payload."""

    def __init__(
        self, user_id: str, email: str, role: str, org_id: Optional[str] = None
    ):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.org_id = org_id


def extract_token_from_header(authorization: str) -> str:
    """
    Extract JWT token from Authorization header.

    Expected format: "Bearer <token>"

    Args:
        authorization: Authorization header value

    Returns:
        JWT token string

    Raises:
        HTTPException: If header format is invalid
    """
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid authentication scheme")
        return token
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected: 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_jwt_token(
    jwt_service: JWTService,
    authorization: str,
) -> TokenPayload:
    """
    Verify JWT token and return token payload.

    Args:
        jwt_service: JWTService instance
        authorization: Authorization header value

    Returns:
        TokenPayload with verified user information

    Raises:
        HTTPException: If token is invalid or expired
    """
    token = extract_token_from_header(authorization)

    try:
        payload = jwt_service.verify_access_token(token)
        return TokenPayload(
            user_id=payload.get("sub"),
            email=payload.get("email"),
            role=payload.get("role"),
            org_id=payload.get("org_id"),
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error(f"Unexpected error verifying JWT: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    request: Request,
    jwt_service: JWTService = Depends(get_jwt_service),
) -> TokenPayload:
    """
    FastAPI dependency to get current authenticated user.

    Use this in endpoint route parameters:
    @router.get("/me")
    async def get_me(current_user: TokenPayload = Depends(get_current_user)):
        return {"user_id": current_user.user_id, "email": current_user.email}

    Args:
        request: FastAPI request
        jwt_service: JWTService instance

    Returns:
        TokenPayload with current user information

    Raises:
        HTTPException: If no valid token provided
    """
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await verify_jwt_token(jwt_service, authorization)
