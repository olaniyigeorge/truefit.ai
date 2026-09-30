from fastapi import APIRouter, Depends
from pydantic import BaseModel
from src.truefit_infra.realtime.ice import build_ice_servers
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

    return TurnCredentials(ice_servers=build_ice_servers())
