"""
JWT token management for backend session management.
Handles encoding and decoding of JWT tokens issued by the backend.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from uuid import UUID

from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger


class JWTService:
    """Service to handle JWT token creation and verification."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes

    def create_access_token(
        self,
        subject: str,  # user_id as string
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        org_id: Optional[str] = None,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """
        Create a JWT access token.
        
        Args:
            subject: User ID (UUID as string)
            user_email: User email address
            user_role: User role (admin, recruiter, candidate)
            org_id: Organization ID (optional)
            expires_delta: Custom expiration time (if None, uses default)
        
        Returns:
            Encoded JWT token
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.access_token_expire_minutes)

        expire = datetime.now(timezone.utc) + expires_delta
        
        payload = {
            "sub": subject,  # subject (user_id)
            "email": user_email,
            "role": user_role,
            "org_id": org_id,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        
        try:
            encoded_jwt = jwt.encode(
                payload, self.secret_key, algorithm=self.algorithm
            )
            logger.info(f"JWT token created for user {subject}")
            return encoded_jwt
        except Exception as e:
            logger.error(f"Error creating JWT token: {e}")
            raise

    def verify_access_token(self, token: str) -> dict:
        """
        Verify and decode a JWT access token.
        
        Args:
            token: JWT token string
        
        Returns:
            Decoded token payload
        
        Raises:
            jwt.InvalidTokenError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token, self.secret_key, algorithms=[self.algorithm]
            )
            
            # Verify token type
            if payload.get("type") != "access":
                raise jwt.InvalidTokenError("Invalid token type")
            
            logger.debug(f"JWT token verified for user {payload.get('sub')}")
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token has expired")
            raise
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            raise

    def get_user_id_from_token(self, token: str) -> str:
        """
        Extract user ID from token without full verification (for logging, etc).
        
        Args:
            token: JWT token string
        
        Returns:
            User ID string
        """
        try:
            payload = jwt.decode(
                token, self.secret_key, algorithms=[self.algorithm]
            )
            return payload.get("sub")
        except Exception:
            return None


def get_jwt_service() -> JWTService:
    """Factory function to create JWT service with config values."""
    return JWTService(
        secret_key=AppConfig.APP_SECRET_KEY,
        algorithm=AppConfig.ALGORITHM,
        access_token_expire_minutes=AppConfig.ACCESS_TOKEN_EXPIRE_MINUTES,
    )
