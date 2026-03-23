# /truefit_infra/realtime/webrtc_client.py
"""
WebRTCClient — server-side peer connection.

Owns the RTCPeerConnection. On track events:
  - audio  → AudioBridge
  - video  → FrameSampler (camera or screen share, detected by track label/id)
  - datachannel → DataChannelManager

Holds session context (job_id, candidate_id) so downstream components
always have the right scope. Does NOT know about Gemini or domain logic.
"""
from __future__ import annotations

import uuid
from typing import Optional

from aiortc import RTCPeerConnection, MediaStreamTrack
from aiortc.mediastreams import AudioStreamTrack

from src.truefit_infra.realtime.session_context import SessionContext

from .audio_bridge import AudioBridge
from .frame_sampler import FrameSampler
from .data_channel import DataChannelManager
from src.truefit_core.common.utils import logger


class WebRTCClient:
    """
    Server-side WebRTC peer.
    Created once per signaling handshake, lives until the session ends.
    """

    def __init__(
        self,
        *,
        pc: RTCPeerConnection,
        session_id: str,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        frame_interval_camera: float = 5.0,
        frame_interval_screen: float = 2.0,
        on_ice_candidate=None
    ) -> None:
        self.pc = pc
        self.context = SessionContext(
            session_id=session_id,
            job_id=job_id,
            candidate_id=candidate_id,
        )

        # Infra components — created here, started lazily on first track/channel
        self.audio_bridge = AudioBridge(context=self.context)
        self.frame_sampler = FrameSampler(
            context=self.context,
            camera_interval=frame_interval_camera,
            screen_interval=frame_interval_screen,
        )
        self.data_channel = DataChannelManager(context=self.context)
        self.on_ice_candidate = on_ice_candidate 

        self._closed = False

    # ── Setup ───

    def setup_handlers(self) -> None:
        """
        Register aiortc event handlers.
        Must be called before setRemoteDescription so no events are missed.
        """
        @self.pc.on("icecandidate")
        async def on_ice_candidate(candidate) -> None:
            if candidate and self.on_ice_candidate:
                await self.on_ice_candidate(candidate)

        @self.pc.on("track")
        async def on_track(track: MediaStreamTrack) -> None:
            logger.info(
                f"[{self.context.session_id}] Received track: "
                f"kind={track.kind} id={track.id}"
            )

            if track.kind == "audio":
                await self.audio_bridge.attach_inbound_track(track)

            elif track.kind == "video":
                # Distinguish camera vs screen share by track label convention.
                # Browser should set track.label = "screen" for getDisplayMedia tracks.
                is_screen = _is_screen_track(track)
                await self.frame_sampler.attach_track(track, is_screen=is_screen)

            @track.on("ended")
            async def on_ended() -> None:
                logger.info(f"[{self.context.session_id}] Track ended: {track.id}")

        @self.pc.on("datachannel")
        def on_datachannel(channel) -> None:
            logger.info(
                f"[{self.context.session_id}] DataChannel opened: {channel.label}"
            )
            self.data_channel.attach(channel)

        @self.pc.on("connectionstatechange")
        async def on_state_change() -> None:
            state = self.pc.connectionState
            logger.info(f"[{self.context.session_id}] Connection state: {state}")
            if state in ("failed", "closed"):
                await self.close()

    # ── Outbound audio (Gemini → browser) ──

    def add_outbound_audio_track(self, track: AudioStreamTrack) -> None:
        """
        Called by the agent/audio_bridge to add an outbound audio track.
        The track streams Gemini's synthesized audio back to the browser.
        """
        self.pc.addTrack(track)

    # ── Teardown ──

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.frame_sampler.stop()
        await self.audio_bridge.close()
        await self.pc.close()
        logger.info(f"[{self.context.session_id}] WebRTCClient closed")


# ── Helpers ──

def _is_screen_track(track: MediaStreamTrack) -> bool:
    """
    Heuristic: browsers set label to 'screen', 'window', or 'tab'
    for getDisplayMedia() tracks. Falls back to False (camera).
    """
    label = getattr(track, "label", "") or ""
    return any(kw in label.lower() for kw in ("screen", "window", "tab", "display"))


# ── Registry ──

class WebRTCClientRegistry:
    """
    Simple in-process registry mapping session_id → WebRTCClient.
    Replace with Redis-backed registry for multi-process deployments.
    """
    _store: dict[str, WebRTCClient] = {}

    @classmethod
    def register(cls, session_id: str, client: WebRTCClient) -> None:
        cls._store[session_id] = client

    @classmethod
    def get(cls, session_id: str) -> Optional[WebRTCClient]:
        return cls._store.get(session_id)

    @classmethod
    def unregister(cls, session_id: str) -> None:
        cls._store.pop(session_id, None)