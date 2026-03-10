"""
OAuth verification service for validating third-party OAuth provider tokens.
Handles Firebase token verification and extraction of user identity information.
"""

from typing import Optional, Dict, Any
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from src.truefit_core.common.utils import logger


class OAuthProvider:
    """Base class for OAuth providers."""
    
    async def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify OAuth token with the provider.
        
        Args:
            token: OAuth token from the provider
        
        Returns:
            User claims dictionary with at least 'sub', 'email', 'name'
        
        Raises:
            ValueError: If token is invalid or verification fails
        """
        raise NotImplementedError


class FirebaseOAuthProvider(OAuthProvider):
    """OAuth provider for Firebase authentication."""
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        # Firebase public certificate URL (Google manages these)
        self.certs_url = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
        self.issuer_template = "https://securetoken.google.com/{}"
    
    async def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify Firebase ID token.
        
        Args:
            token: Firebase ID token from frontend
        
        Returns:
            Claims dictionary with user information
        
        Raises:
            ValueError: If token is invalid or verification fails
        """
        try:
            # Use Google's library to verify Firebase tokens
            # This validates signature, expiration, and audience
            claims = id_token.verify_oauth2_token(
                token, 
                Request(), 
                self.project_id
            )
            
            # Verify the token is from Firebase (issuer check)
            expected_issuer = self.issuer_template.format(self.project_id)
            if claims.get("iss") != expected_issuer:
                raise ValueError(f"Unexpected issuer: {claims.get('iss')}")
            
            logger.debug(f"Firebase token verified for user {claims.get('sub')}")
            return claims
        except Exception as e:
            logger.error(f"Firebase token verification failed: {e}")
            raise ValueError(f"Invalid Firebase token: {str(e)}")


class GoogleOAuthProvider(OAuthProvider):
    """OAuth provider for Google OAuth 2.0 tokens."""
    
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.token_endpoint = "https://oauth2.googleapis.com/tokeninfo"
    
    async def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify Google OAuth token by calling Google's tokeninfo endpoint.
        
        Args:
            token: Google access token or ID token
        
        Returns:
            Claims dictionary with user information
        
        Raises:
            ValueError: If token is invalid
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.token_endpoint,
                    params={"access_token": token}
                )
                
                if response.status_code != 200:
                    raise ValueError(f"Token validation failed: {response.text}")
                
                data = response.json()
                
                # Verify the token is for our app
                if data.get("aud") != self.client_id:
                    raise ValueError(f"Token not for this app: {data.get('aud')}")
                
                logger.debug(f"Google token verified for user {data.get('sub')}")
                return data
        except Exception as e:
            logger.error(f"Google token verification failed: {e}")
            raise ValueError(f"Invalid Google token: {str(e)}")


class OAuthService:
    """Service to handle OAuth verification and user identity extraction."""
    
    def __init__(self, provider: OAuthProvider):
        self.provider = provider
    
    async def verify_and_extract_identity(
        self, 
        token: str
    ) -> Dict[str, str]:
        """
        Verify OAuth token and extract user identity information.
        
        Args:
            token: OAuth token from frontend
        
        Returns:
            Dictionary with keys: 'provider_subject', 'email', 'name'
        
        Raises:
            ValueError: If token verification fails
        """
        try:
            # Verify token with provider
            claims = await self.provider.verify_token(token)
            
            # Extract standard OIDC claims
            identity = {
                "provider_subject": claims.get("sub"),  # Provider's unique user ID
                "email": claims.get("email"),
                "name": claims.get("name") or "",
                "picture": claims.get("picture") or "",
            }
            
            # Validate required fields
            if not identity["provider_subject"]:
                raise ValueError("Token missing 'sub' claim")
            if not identity["email"]:
                raise ValueError("Token missing 'email' claim")
            
            logger.info(f"Identity extracted from OAuth token for {identity['email']}")
            return identity
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error extracting identity from OAuth token: {e}")
            raise ValueError(f"Failed to extract user identity: {str(e)}")


def get_oauth_service(
    provider_type: str,
    project_id: Optional[str] = None,
    client_id: Optional[str] = None,
) -> OAuthService:
    """
    Factory function to create OAuth service based on provider type.
    
    Args:
        provider_type: Type of OAuth provider ('firebase', 'google')
        project_id: Firebase project ID (required for firebase provider)
        client_id: Google client ID (required for google provider)
    
    Returns:
        OAuthService instance
    """
    if provider_type.lower() == "firebase":
        if not project_id:
            raise ValueError("project_id required for Firebase provider")
        provider = FirebaseOAuthProvider(project_id)
    elif provider_type.lower() == "google":
        if not client_id:
            raise ValueError("client_id required for Google provider")
        provider = GoogleOAuthProvider(client_id)
    else:
        raise ValueError(f"Unknown OAuth provider: {provider_type}")
    
    return OAuthService(provider)
