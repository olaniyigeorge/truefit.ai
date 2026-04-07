# /truefit_infra/realtime/webrtc_client.py
"""
WebRTCClient - server-side peer connection manager.

─────────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE DOES
─────────────────────────────────────────────────────────────────────────────
This module owns the RTCPeerConnection lifecycle and routes everything that
arrives through it to the right downstream component.

Think of WebRTCClient as a traffic controller sitting on top of the raw
aiortc peer connection. When media and data arrives from the browser, it
decides where it goes:

  Browser audio track  -> AudioBridge    (mic audio -> Gemini)
  Browser video track  -> FrameSampler   (camera/screen frames -> Gemini)
  DataChannel messages -> DataChannelManager (in-call events)

It also:
  - Adds the agent's outbound audio track so the browser can hear Gemini
  - Forwards ICE candidates both directions (browser ↔ server) for connectivity
  - Cleans up all resources when the session ends

WHAT IT DOES NOT KNOW ABOUT:
  - Gemini / the AI layer - it hands audio to AudioBridge and stops there
  - WebSockets - it calls on_ice_candidate (a callback), not ws.send_text()
  - Domain logic - it has job_id/candidate_id for scoping, not for decisions

─────────────────────────────────────────────────────────────────────────────
HOW IT FITS IN THE OVERALL FLOW
─────────────────────────────────────────────────────────────────────────────
  InterviewConnection
    -> WebRTCSignaling.handle_offer()
      -> creates WebRTCClient
        -> sets up RTCPeerConnection handlers (this file)
          -> AudioBridge    (audio_bridge.py)
          -> FrameSampler   (frame_sampler.py)
          -> DataChannelManager (data_channel.py)
    -> stores client reference as self._webrtc
    -> uses client.audio_bridge for all audio I/O
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
    Server-side WebRTC peer connection for one interview session.

    Created once per signaling handshake by WebRTCSignaling.handle_offer().
    Lives until the session ends (candidate disconnects, interview completes,
    or connection state transitions to "failed" or "closed").

    Owns three infrastructure components that it creates and manages:
      audio_bridge    - bidirectional audio between WebRTC and the agent
      frame_sampler   - samples video frames at intervals for Gemini
      data_channel    - handles structured in-call events from the browser

    After construction, call setup_handlers() before setRemoteDescription
    to ensure no aiortc events are missed.
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
        on_ice_candidate=None,
    ) -> None:
        """
        pc:
            The aiortc RTCPeerConnection instance. Created by WebRTCSignaling
            before instantiating this client. We take ownership of it here.

        session_id:
            The unique ID for this interview session (generated in InterviewConnection).
            Used for log scoping and as the key in WebRTCClientRegistry.

        job_id / candidate_id:
            Stored in SessionContext and passed to downstream components
            (AudioBridge, FrameSampler, DataChannelManager) so they always
            have the right scope for logging and any future domain calls.

        frame_interval_camera:
            How often (in seconds) to sample a frame from the candidate's camera.
            Default 5.0s - low frequency because camera frames are mainly for
            context (e.g., checking candidate is present), not continuous analysis.

        frame_interval_screen:
            How often (in seconds) to sample a frame from the screen share.
            Default 2.0s - higher frequency than camera because screen content
            (code, documents) changes more meaningfully and Gemini needs to
            read it to give relevant feedback.

        on_ice_candidate:
            Async callback called each time the server-side ICE agent discovers
            a new network candidate. In production this is set by
            InterviewConnection._handle_webrtc_offer() to a closure that
            sends the candidate over the WebSocket to the browser.
        """
        self.pc = pc
        # SessionContext is a lightweight dataclass that bundles session/job/candidate
        # IDs together. Passed to all downstream components for scoping.
        self.context = SessionContext(
            session_id=session_id,
            job_id=job_id,
            candidate_id=candidate_id,
        )

        # ── Infrastructure components ─────────────────────────────────────────
        # Created here at construction time, but activated lazily when the
        # corresponding track/channel arrives via aiortc events in setup_handlers().

        # Handles all audio I/O: browser mic -> Gemini, Gemini response -> browser
        self.audio_bridge = AudioBridge(context=self.context)

        # Samples video frames from camera and screen share at configured intervals
        self.frame_sampler = FrameSampler(
            context=self.context,
            camera_interval=frame_interval_camera,
            screen_interval=frame_interval_screen,
        )

        # Receives structured DataChannel messages from the browser
        # (screen_share_start/stop, clarification_request, etc.)
        self.data_channel = DataChannelManager(context=self.context)

        # ICE candidate forwarding callback - set after construction by
        # InterviewConnection._handle_webrtc_offer() via a closure
        self.on_ice_candidate = on_ice_candidate

        self._closed = False  # Guards against double-close

    # ─────────────────────────────────────────────────────────────────────────
    # SETUP
    # ─────────────────────────────────────────────────────────────────────────

    def setup_handlers(self) -> None:
        """
        Registers all aiortc event handlers on the RTCPeerConnection.

        CRITICAL: Must be called BEFORE setRemoteDescription (i.e., before
        the SDP offer is processed). aiortc fires track and datachannel events
        synchronously during SDP processing - if handlers aren't registered
        first, we miss those events and audio/video never flows.

        Called by WebRTCSignaling.handle_offer() immediately after constructing
        the WebRTCClient, before calling pc.setRemoteDescription().

        Registers four handlers:
          "icecandidate"        - server discovered a new ICE candidate
          "track"               - browser sent a media track (audio or video)
          "datachannel"         - browser opened a DataChannel
          "connectionstatechange" - peer connection state changed
        """

        @self.pc.on("icecandidate")
        async def on_ice_candidate(candidate) -> None:
            """
            Fires each time the server's ICE agent discovers a new network
            candidate (local IP/port combination it can receive data on).

            We forward it to the browser via on_ice_candidate callback -
            this is the "trickle ICE" pattern. Without trickle ICE, we'd
            have to wait for ALL candidates before sending the SDP answer,
            which significantly delays connection establishment.

            None candidates mean ICE gathering is complete - we skip those.
            """
            if candidate and self.on_ice_candidate:
                await self.on_ice_candidate(candidate)

        @self.pc.on("track")
        async def on_track(track: MediaStreamTrack) -> None:
            """
            Fires when the browser adds a media track to the peer connection.

            We expect up to three tracks:
              1. Audio track  - browser microphone (always present)
              2. Video track  - camera (optional, if candidate enabled it)
              3. Video track  - screen share (optional, if candidate shares screen)

            Track routing:
              audio -> AudioBridge.attach_inbound_track()
                      Starts the pump loop that resamples 48kHz -> 16kHz PCM
                      and feeds inbound_queue for the agent.

              video -> FrameSampler.attach_track(is_screen=...)
                      Starts sampling frames at the configured interval.
                      We distinguish camera vs screen by checking the track label
                      (browsers set label to "screen"/"window"/"tab" for getDisplayMedia).

            The "ended" sub-handler logs when a specific track stops - useful
            for detecting when a candidate stops their screen share mid-interview.
            """
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
            """
            Fires when the browser opens a WebRTC DataChannel.

            DataChannels are used for structured in-call events that don't
            fit the audio/video track model: screen share lifecycle signals,
            clarification requests, technical issue reports, etc.

            We pass the raw channel to DataChannelManager which sets up its
            own message handler and exposes on_inbound_event for InterviewConnection
            to wire to _on_datachannel_event().
            """
            logger.info(
                f"[{self.context.session_id}] DataChannel opened: {channel.label}"
            )
            self.data_channel.attach(channel)

        @self.pc.on("connectionstatechange")
        async def on_state_change() -> None:
            """
            Fires whenever the overall peer connection state changes.

            States: "new" -> "connecting" -> "connected" -> "disconnected"/"failed"/"closed"

            We only act on terminal states (failed, closed) - clean up all
            resources via close(). This handles abrupt disconnects (candidate
            closes browser tab, network drops) where we don't get a graceful
            WebSocket disconnect message.

            "disconnected" is intentionally NOT handled here - it's transient
            and can recover to "connected". Only "failed" and "closed" are final.
            """
            state = self.pc.connectionState
            logger.info(f"[{self.context.session_id}] Connection state: {state}")
            if state in ("failed", "closed"):
                await self.close()

    # ─────────────────────────────────────────────────────────────────────────
    # OUTBOUND AUDIO (Gemini -> browser)
    # ─────────────────────────────────────────────────────────────────────────

    def add_outbound_audio_track(self, track: AudioStreamTrack) -> None:
        """
        Adds the agent's audio track to the peer connection so the browser
        can receive Gemini's synthesised speech.

        Called during WebRTC setup (in WebRTCSignaling.handle_offer() after
        creating the WebRTCClient) before the SDP answer is generated.
        The track must be added before createAnswer() so it's included in
        the SDP - if added after, the browser won't know to expect it.

        The track is _AgentAudioTrack from AudioBridge - it pulls from
        outbound_queue, resamples 24kHz -> 48kHz, and delivers 20ms frames
        at the correct pace for the browser's audio renderer.
        """
        self.pc.addTrack(track)

    # ─────────────────────────────────────────────────────────────────────────
    # TEARDOWN
    # ─────────────────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """
        Shuts down all resources owned by this client.

        Called from two places:
          1. on_connectionstatechange when state is "failed" or "closed"
             (abrupt disconnect - browser tab closed, network failure)
          2. WebRTCSignaling.close() when the session ends normally

        Sequence:
          1. Stop FrameSampler - cancels the frame sampling tasks
          2. Close AudioBridge - cancels pump task, drains queues, puts sentinels
          3. Close RTCPeerConnection - tears down DTLS, ICE, and media streams

        The _closed guard prevents double-close (e.g., if connectionstatechange
        fires "failed" and then WebRTCSignaling.close() is also called).
        """
        if self._closed:
            return
        self._closed = True
        self.frame_sampler.stop()
        await self.audio_bridge.close()
        await self.pc.close()
        logger.info(f"[{self.context.session_id}] WebRTCClient closed")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _is_screen_track(track: MediaStreamTrack) -> bool:
    """
    Heuristic to distinguish a screen share track from a camera track.

    When a browser calls getDisplayMedia() (screen share), the resulting
    MediaStreamTrack's label is typically set to "screen", "window", "tab",
    or "display" depending on what the user chose to share.

    When a browser calls getUserMedia() (camera), the label is usually the
    device name (e.g., "FaceTime HD Camera") - it won't contain these keywords.

    This is a best-effort heuristic, not a guaranteed classification. If a
    camera is named "Screen Camera Pro" it would be misclassified - but that's
    an edge case we accept for now. A more robust approach would be for the
    frontend to explicitly label tracks before adding them to the peer connection.

    Returns True if the track is likely a screen share, False if camera.
    """
    label = getattr(track, "label", "") or ""
    return any(kw in label.lower() for kw in ("screen", "window", "tab", "display"))


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT REGISTRY
# ─────────────────────────────────────────────────────────────────────────────


class WebRTCClientRegistry:
    """
    In-process registry that maps session_id -> WebRTCClient.

    Used so that any part of the system that has a session_id can look up
    the corresponding WebRTCClient without passing it through function arguments
    all the way down the call stack.

    CURRENT LIMITATION:
      This is a simple class-level dictionary - it's in-memory and
      process-local. In a single-process deployment (which we currently run)
      this is fine. For a multi-process or multi-instance deployment, this
      would need to be replaced with a Redis-backed registry (or we'd use
      sticky sessions at the load balancer level).

    Usage:
      # Registration (done by WebRTCSignaling after creating the client)
      WebRTCClientRegistry.register(session_id, client)

      # Lookup (by any component that has the session_id)
      client = WebRTCClientRegistry.get(session_id)

      # Cleanup (called on session teardown)
      WebRTCClientRegistry.unregister(session_id)
    """

    # Class-level store - shared across all instances (effectively a singleton dict)
    _store: dict[str, WebRTCClient] = {}

    @classmethod
    def register(cls, session_id: str, client: WebRTCClient) -> None:
        """
        Adds a client to the registry under its session_id.
        Called by WebRTCSignaling after the client is fully constructed
        and handlers are registered.
        """
        cls._store[session_id] = client

    @classmethod
    def get(cls, session_id: str) -> Optional[WebRTCClient]:
        """
        Returns the WebRTCClient for the given session_id, or None if
        the session doesn't exist (already unregistered or never created).
        """
        return cls._store.get(session_id)

    @classmethod
    def unregister(cls, session_id: str) -> None:
        """
        Removes the client from the registry when the session ends.
        Safe to call even if the session_id was never registered (pop with default).
        Should be called during session teardown to prevent memory leaks
        - entries never self-expire in this in-memory implementation.
        """
        cls._store.pop(session_id, None)
