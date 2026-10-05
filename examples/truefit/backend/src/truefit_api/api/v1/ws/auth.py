"""
WebSocket authentication for the interview socket.

Browsers cannot set an Authorization header on a WebSocket, so the client sends
the same backend JWT it uses for REST as a `token` query parameter:

    ws://host/api/v1/ws/interview/{job_id}/{candidate_id}?token=<jwt>

The connection is rejected during the handshake unless the token is valid and
belongs to the candidate being interviewed (or an admin).
"""

from __future__ import annotations

import uuid
from typing import Optional

import jwt
from starlette.websockets import WebSocket

from src.truefit_core.application.ports import CandidateRepository
from src.truefit_core.common.utils import logger
from src.truefit_infra.auth.authorization import ADMIN
from src.truefit_infra.auth.jwt import JWTService
from src.truefit_infra.auth.middleware import TokenPayload

WS_UNAUTHORIZED = 4401  # missing, invalid or expired token
WS_FORBIDDEN = 4403  # valid token, but not allowed to join this interview


async def authenticate_interview_socket(
    websocket: WebSocket,
    *,
    candidate_id: uuid.UUID,
    candidate_repo: CandidateRepository,
    jwt_service: JWTService,
) -> Optional[TokenPayload]:
    """
    Returns the caller's TokenPayload, or None after closing the socket with a
    4401 or 4403 code. Call before websocket.accept().
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=WS_UNAUTHORIZED, reason="Missing token")
        return None

    try:
        claims = jwt_service.verify_access_token(token)
    except jwt.InvalidTokenError as e:
        logger.warning(f"Interview socket rejected: invalid token ({e})")
        await websocket.close(code=WS_UNAUTHORIZED, reason="Invalid or expired token")
        return None

    user = TokenPayload(
        user_id=claims.get("sub"),
        email=claims.get("email"),
        role=claims.get("role"),
        org_id=claims.get("org_id"),
    )

    candidate = await candidate_repo.get_by_id(candidate_id)
    owns_profile = candidate is not None and str(candidate.user_id) == str(user.user_id)
    if not (user.role == ADMIN or owns_profile):
        # Same answer whether the candidate exists or not, so ids cannot be probed.
        logger.warning(f"Interview socket rejected: {user.user_id} may not join {candidate_id}")
        await websocket.close(code=WS_FORBIDDEN, reason="Forbidden")
        return None

    return user
