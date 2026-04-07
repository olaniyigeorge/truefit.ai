"""
WebRTC signaling logic - no HTTP endpoints.
Called directly by InterviewConnection over the WebSocket.
"""

from __future__ import annotations

from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceCandidate,
    RTCConfiguration,
    RTCIceServer,
)
from aiortc.sdp import candidate_from_sdp

from .webrtc_client import WebRTCClient, WebRTCClientRegistry
from src.truefit_core.common.utils import logger


class WebRTCSignaling:
    """
    Handles the WebRTC handshake for one session.
    Instantiated by InterviewConnection and called as messages arrive over WS.
    No HTTP, no routers - pure async methods.
    """

    def __init__(self, *, session_id: str, job_id, candidate_id) -> None:
        self._session_id = session_id
        self._job_id = job_id
        self._candidate_id = candidate_id
        self._client: WebRTCClient | None = None

    # ── Step 1: browser sends offer ─

    async def handle_offer(
        self,
        sdp: str,
        sdp_type: str,
        frame_interval_camera: float = 5.0,
        frame_interval_screen: float = 2.0,
    ) -> str:
        logger.info(f"[{self._session_id}] Creating RTCPeerConnection")
        configuration = RTCConfiguration(
            iceServers=[
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
                RTCIceServer(
                    urls=["turn:openrelay.metered.ca:80"],
                    username="openrelayproject",
                    credential="openrelayproject",
                ),
                RTCIceServer(
                    urls=["turn:openrelay.metered.ca:443"],
                    username="openrelayproject",
                    credential="openrelayproject",
                ),
            ]
        )
        pc = RTCPeerConnection(configuration=configuration)

        logger.info(f"[{self._session_id}] Creating WebRTCClient")
        self._client = WebRTCClient(
            pc=pc,
            session_id=self._session_id,
            job_id=self._job_id,
            candidate_id=self._candidate_id,
            frame_interval_camera=frame_interval_camera,
            frame_interval_screen=frame_interval_screen,
        )

        logger.info(f"[{self._session_id}] Calling setup_handlers")
        self._client.setup_handlers()

        logger.info(f"[{self._session_id}] setRemoteDescription")
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=sdp_type))

        # ← Add outbound audio track BEFORE createAnswer so it's negotiated
        outbound_track = self._client.audio_bridge.create_outbound_track()
        self._client.add_outbound_audio_track(outbound_track)

        logger.info(f"[{self._session_id}] createAnswer")
        answer = await pc.createAnswer()

        logger.info(f"[{self._session_id}] setLocalDescription")
        await pc.setLocalDescription(answer)

        WebRTCClientRegistry.register(self._session_id, self._client)
        logger.info(f"[{self._session_id}] WebRTC offer handled, answer ready")
        return pc.localDescription.sdp

    # ── Step 2: trickle ICE candidates ─────

    async def handle_ice_candidate(
        self,
        candidate: str,
        sdp_mid: str | None,
        sdp_mline_index: int | None,
    ) -> None:
        """Add a trickle ICE candidate from the browser."""
        if not self._client:
            logger.warning(
                f"[{self._session_id}] ICE candidate before offer - dropping"
            )
            return

        if not candidate:
            return  # browser sends an empty string as the end-of-candidates signal

        # ice = RTCIceCandidate(
        #     candidate=candidate,
        #     sdpMid=sdp_mid,
        #     sdpMLineIndex=sdp_mline_index,
        # )
        try:
            # Strip the "candidate:" prefix that browsers include
            sdp_line = candidate
            if sdp_line.startswith("candidate:"):
                sdp_line = sdp_line[len("candidate:") :]

            ice = candidate_from_sdp(sdp_line)
            ice.sdpMid = sdp_mid
            ice.sdpMLineIndex = sdp_mline_index
            await self._client.pc.addIceCandidate(ice)
        except Exception as e:
            logger.warning(f"[{self._session_id}] Failed to add ICE candidate: {e}")

    # Accessors 

    @property
    def client(self) -> WebRTCClient | None:
        return self._client

    # Teardown

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            WebRTCClientRegistry.unregister(self._session_id)
