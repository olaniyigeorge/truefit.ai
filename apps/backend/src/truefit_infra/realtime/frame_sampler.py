"""
FrameSampler - periodic video frame extraction.

Runs two independent async loops:
  - camera loop   (default: every 5s)
  - screen loop   (default: every 2s for technical interviews)

Each loop pulls a frame from its aiortc track, encodes it as JPEG,
and puts a FrameEvent on a shared queue the agent consumes.
"""

from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import av
from aiortc import MediaStreamTrack
from PIL import Image

from src.truefit_core.common.utils import logger
from src.truefit_infra.realtime.session_context import SessionContext


class FrameSource(str, Enum):
    CAMERA = "camera"
    SCREEN = "screen"


@dataclass
class FrameEvent:
    source: FrameSource
    jpeg_bytes: bytes
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""


class FrameSampler:
    """
    Attach video tracks and consume sampled frames from frame_queue.
    frame_queue items are FrameEvent instances.
    """

    def __init__(
        self,
        *,
        context: SessionContext,
        camera_interval: float = 5.0,
        screen_interval: float = 2.0,
        jpeg_quality: int = 75,
        max_dimension: int = 1280,
    ) -> None:
        self._ctx = context
        self._camera_interval = camera_interval
        self._screen_interval = screen_interval
        self._jpeg_quality = jpeg_quality
        self._max_dimension = max_dimension

        self.frame_queue: asyncio.Queue[FrameEvent] = asyncio.Queue(maxsize=50)

        self._camera_task: Optional[asyncio.Task] = None
        self._screen_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # ── Attach tracks ─

    async def attach_track(self, track: MediaStreamTrack, *, is_screen: bool) -> None:
        source = FrameSource.SCREEN if is_screen else FrameSource.CAMERA
        interval = self._screen_interval if is_screen else self._camera_interval

        task = asyncio.create_task(
            self._sample_loop(track, source=source, interval=interval),
            name=f"frame-{source.value}-{self._ctx.session_id}",
        )

        if is_screen:
            self._screen_task = task
        else:
            self._camera_task = task

        logger.info(
            f"[{self._ctx.session_id}] FrameSampler attached "
            f"{source.value} track (interval={interval}s)"
        )

    # ── Sample loop ───

    async def _sample_loop(
        self,
        track: MediaStreamTrack,
        *,
        source: FrameSource,
        interval: float,
    ) -> None:
        """
        Pull frames at `interval` seconds. Skips frames between intervals
        so we don't accumulate a backlog.
        """
        next_sample_at = time.monotonic()

        try:
            while not self._stop_event.is_set():
                now = time.monotonic()

                if now < next_sample_at:
                    # Drain the track without processing (keep buffer clear)
                    try:
                        await asyncio.wait_for(
                            track.recv(), timeout=next_sample_at - now
                        )
                    except (asyncio.TimeoutError, Exception):
                        pass
                    continue

                # Time to capture a frame
                try:
                    frame: av.VideoFrame = await asyncio.wait_for(
                        track.recv(), timeout=2.0
                    )
                except asyncio.TimeoutError:
                    logger.debug(
                        f"[{self._ctx.session_id}] {source.value} frame timeout"
                    )
                    next_sample_at = time.monotonic() + interval
                    continue
                except Exception as e:
                    logger.warning(
                        f"[{self._ctx.session_id}] {source.value} track error: {e}"
                    )
                    break

                jpeg_bytes = await asyncio.get_event_loop().run_in_executor(
                    None, self._encode_frame, frame
                )

                event = FrameEvent(
                    source=source,
                    jpeg_bytes=jpeg_bytes,
                    session_id=self._ctx.session_id,
                )

                try:
                    self.frame_queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Drop oldest frame - freshness matters more than completeness
                    try:
                        self.frame_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self.frame_queue.put_nowait(event)

                next_sample_at = time.monotonic() + interval

        except asyncio.CancelledError:
            pass

    # ── Frame encoding

    def _encode_frame(self, frame: av.VideoFrame) -> bytes:
        """Convert av.VideoFrame -> JPEG bytes. Runs in thread executor."""
        img: Image.Image = frame.to_image()

        # Resize if too large
        w, h = img.size
        if max(w, h) > self._max_dimension:
            scale = self._max_dimension / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self._jpeg_quality, optimize=True)
        return buf.getvalue()

    # ── Teardown

    def stop(self) -> None:
        self._stop_event.set()
        for task in (self._camera_task, self._screen_task):
            if task:
                task.cancel()
