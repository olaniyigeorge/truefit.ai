

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from src.truefit_infra.config import AppConfig
from src.truefit_infra.auth.middleware import get_current_user, TokenPayload


router = APIRouter(prefix="/turn", tags=["turn"])



class TurnCredentials(BaseModel):
    ice_servers: list[dict]


@router.get("/credentials", response_model=TurnCredentials)
async def get_turn_credentials(
    current_user: TokenPayload = Depends(get_current_user),
) -> TurnCredentials:
    """
    Return ICE server config including STUN + TURN
    Requires authentication so credentials aren't publicly exposed
    """

    ice_servers = [
        {"urls": "stun:stun.l.google.com:19302"},
    ]

    if AppConfig.TURN_SERVER_URL:
        ice_servers.append({
            "urls": AppConfig.TURN_SERVER_URL,
            "username": AppConfig.TURN_USERNAME,
            "credential": AppConfig.TURN_CREDENTIAL,
        })
    return TurnCredentials(ice_servers=ice_servers)
