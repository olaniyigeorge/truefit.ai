import asyncio
from datetime import datetime, timedelta, timezone

from src.truefit_core.common.utils import logger
from src.truefit_core.application.ports import InterviewRepository
from src.truefit_core.domain.interview import InterviewStatus

STALE_THRESHOLD_MINUTES = 45
SWEEP_INTERVAL_SECONDS = 60


class InterviewSweeper:
    """
    Background task that finds and abandons active interview sessions
    that have exceeded the max duration or gone stale (server crash,
    unclean disconnect, etc.).

    Lifecycle:
        start()  — called once at app startup via asyncio.create_task()
        stop()   — called at app shutdown to set the exit flag;
                   the task itself is cancelled by the lifespan finally block
                   which interrupts the sleep immediately without waiting 60s
    """

    def __init__(self, interviews: InterviewRepository, orchestration) -> None:
        self._interviews = interviews
        self._orchestration = orchestration
        self._running = False

    async def start(self) -> None:
        if self._running:
            logger.warning("[Sweeper] Already running, ignoring duplicate start()")
            return

        self._running = True
        logger.info("[Sweeper] Interview sweeper started")

        while self._running:
            try:
                await self._sweep()
            except Exception as e:
                logger.error(f"[Sweeper] Sweep error: {e}", exc_info=True)
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)

    def stop(self) -> None:
        """
        Sets the exit flag. Does NOT interrupt the current sleep —
        the lifespan finally block cancels the task directly, which
        breaks out of asyncio.sleep() immediately.
        """
        self._running = False
        logger.info("[Sweeper] Interview sweeper stopped")

    def _normalise_dt(self, dt: datetime) -> datetime:
        """
        Ensures datetime is timezone-aware (UTC).
        Guards against naive datetimes returned by some DB drivers.
        """
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    async def _sweep(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MINUTES)

        active_sessions = await self._interviews.list_by_status(
            InterviewStatus.ACTIVE, limit=200
        )

        if len(active_sessions) >= 200:
            logger.warning(
                "[Sweeper] Active session count hit query limit (200) — "
                "some sessions may not be swept this cycle"
            )

        stale = [
            s for s in active_sessions
            if s.started_at and self._normalise_dt(s.started_at) < cutoff
        ]

        logger.debug(
            f"[Sweeper] Sweep complete — "
            f"{len(active_sessions)} active, {len(stale)} stale"
        )

        if not stale:
            return

        logger.info(f"[Sweeper] Found {len(stale)} stale session(s) to abandon")

        for interview in stale:
            try:
                await self._orchestration.abandon_interview(
                    interview.id,
                    reason="sweeper:timeout_exceeded",
                )
                logger.info(f"[Sweeper] Abandoned stale session {interview.id}")
            except Exception as e:
                logger.error(
                    f"[Sweeper] Failed to abandon {interview.id}: {e}",
                    exc_info=True,
                )