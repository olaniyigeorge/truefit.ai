# /truefit_infra/realtime/signaling.py
"""
WebRTC signaling endpoint.
Handles SDP offer/answer and ICE candidate exchange.
No Gemini, no domain logic — pure WebRTC plumbing.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .webrtc_client import WebRTCClient, WebRTCClientRegistry

signaling_router = APIRouter(prefix="/webrtc", tags=["webrtc-signaling"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class SDPOffer(BaseModel):
    sdp: str
    type: str  # always "offer"
    # Session context passed from the frontend at connection time
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    # Optional per-session config
    frame_interval_camera: float = 5.0    # seconds between camera frames
    frame_interval_screen: float = 2.0   # seconds between screen frames


class SDPAnswer(BaseModel):
    sdp: str
    type: str  # always "answer"
    session_id: str


class ICECandidate(BaseModel):
    session_id: str
    candidate: str
    sdpMid: str | None = None
    sdpMLineIndex: int | None = None


class ICEAck(BaseModel):
    ok: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@signaling_router.post("/offer", response_model=SDPAnswer)
async def receive_offer(offer: SDPOffer) -> SDPAnswer:
    """
    1. Frontend POSTs its SDP offer + session context.
    2. We create a WebRTCClient (owns the RTCPeerConnection).
    3. We set the remote description, create an answer, return it.
    """
    from aiortc import RTCPeerConnection, RTCSessionDescription

    session_id = str(uuid.uuid4())

    pc = RTCPeerConnection()

    client = WebRTCClient(
        pc=pc,
        session_id=session_id,
        job_id=offer.job_id,
        candidate_id=offer.candidate_id,
        frame_interval_camera=offer.frame_interval_camera,
        frame_interval_screen=offer.frame_interval_screen,
    )

    # Wire up track/datachannel handlers before setting remote description
    client.setup_handlers()

    remote_desc = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    await pc.setRemoteDescription(remote_desc)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    # Register so ICE endpoint can find this client
    WebRTCClientRegistry.register(session_id, client)

    return SDPAnswer(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type,
        session_id=session_id,
    )


@signaling_router.post("/ice-candidate", response_model=ICEAck)
async def add_ice_candidate(payload: ICECandidate) -> ICEAck:
    """
    Trickle ICE: frontend sends candidates as they're discovered.
    """
    from aiortc import RTCIceCandidate

    client = WebRTCClientRegistry.get(payload.session_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Session not found")

    candidate = RTCIceCandidate(
        candidate=payload.candidate,
        sdpMid=payload.sdpMid,
        sdpMLineIndex=payload.sdpMLineIndex,
    )
    await client.pc.addIceCandidate(candidate)
    return ICEAck(ok=True)


@signaling_router.delete("/session/{session_id}")
async def close_session(session_id: str) -> dict[str, Any]:
    """Explicit teardown from frontend."""
    client = WebRTCClientRegistry.get(session_id)
    if client:
        await client.close()
        WebRTCClientRegistry.unregister(session_id)
    return {"closed": True}