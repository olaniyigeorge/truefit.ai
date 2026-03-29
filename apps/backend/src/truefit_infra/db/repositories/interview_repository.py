from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from src.truefit_core.common.utils import logger
from src.truefit_core.application.ports import InterviewRepository
from src.truefit_core.domain.interview import (
    Answer,
    Interview,
    InterviewStatus,
    Question,
    Turn,
)
from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import (
    InterviewSession,
    InterviewTurn,
    Application,
    JobListing,
)

class SQLAlchemyInterviewRepository(InterviewRepository):
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def save(self, interview: Interview) -> None:
        async with self._db.get_session() as session:

            # 1) Load existing session WITH turns eagerly
            result = await session.execute(
                select(InterviewSession)
                .where(InterviewSession.id == interview.id)
                .options(selectinload(InterviewSession.turns))  # ← must be here
            )
            session_row = result.scalar_one_or_none()

            # 2) Create or update InterviewSession row
            if session_row is None:
                app_result = await session.execute(
                    select(Application).where(
                        Application.job_id == interview.job_id,
                        Application.candidate_id == interview.candidate_id,
                    )
                )
                app = app_result.scalar_one_or_none()
                if app is None:
                    raise ValueError(
                        "Application not found for job_id + candidate_id; "
                        "create an application before starting an interview."
                    )

                session_row = InterviewSession(
                    id=interview.id,
                    application_id=app.id,
                    round=1,
                    status=interview.status.value,
                    started_at=interview.started_at,
                    ended_at=interview.ended_at,
                )
                session.add(session_row)
                await session.flush()
                existing_turns = [] 

            else:
                session_row.status = interview.status.value
                session_row.started_at = interview.started_at
                session_row.ended_at = interview.ended_at
                existing_turns = list(session_row.turns)

            # 3) Delete existing turns synchronously within the session
            for t in existing_turns:
                await session.delete(t)
            if existing_turns:
                await session.flush()

            # 4) Insert new turns
            seq = 1
            for turn in interview.turns:
                q = turn.question
                a = turn.answer

                payload = {
                    "question_id": str(q.id),
                    "question_text": q.text,
                    "topic": q.topic,
                    "follow_up_of": str(q.follow_up_of) if q.follow_up_of else None,
                    "asked_at": q.asked_at.isoformat(),
                    "answer_text": a.text if a else None,
                    "answered_at": a.answered_at.isoformat() if a else None,
                    "duration_seconds": a.duration_seconds if a else None,
                }

                session.add(
                    InterviewTurn(
                        session_id=session_row.id,
                        seq=seq,
                        speaker="agent",
                        modality="text",
                        turn_text=q.text,
                        payload=payload,
                        started_at=q.asked_at,
                        ended_at=a.answered_at if a else None,
                    )
                )
                seq += 1

                if a and a.text:
                    session.add(
                        InterviewTurn(
                            session_id=session_row.id,
                            seq=seq,
                            speaker="candidate",
                            modality="text",
                            turn_text=a.text,
                            payload=payload,
                            started_at=a.answered_at,
                            ended_at=a.answered_at,
                        )
                    )
                    seq += 1

            await session.commit()

    async def get_by_id(self, interview_id: uuid.UUID) -> Optional[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .where(InterviewSession.id == interview_id)
                .options(
                    selectinload(InterviewSession.turns),
                    selectinload(InterviewSession.application),
                )
            )
            s = res.scalar_one_or_none()
            if not s:
                return None

            # load job listing to get org_id
            app = s.application
            job_res = await session.execute(
                select(JobListing).where(JobListing.id == app.job_id)
            )
            job = job_res.scalar_one()

            return self._to_domain(session_row=s, job=job)

    async def list_by_candidate(
        self, candidate_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .join(Application, InterviewSession.application_id == Application.id)
                .where(Application.candidate_id == candidate_id)
                .order_by(InterviewSession.created_at.desc())
                .limit(limit)
                .offset(offset)
                .options(
                    selectinload(InterviewSession.turns),
                    selectinload(InterviewSession.application),
                )
            )
            sessions = res.scalars().all()

            # batch load jobs for org_id mapping
            job_ids = {s.application.job_id for s in sessions}
            jobs_res = await session.execute(
                select(JobListing).where(JobListing.id.in_(job_ids))
            )
            jobs = {j.id: j for j in jobs_res.scalars().all()}

            return [self._to_domain(s, jobs[s.application.job_id]) for s in sessions]

    async def list_by_job(
        self, job_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .join(Application, InterviewSession.application_id == Application.id)
                .where(Application.job_id == job_id)
                .order_by(InterviewSession.created_at.desc())
                .limit(limit)
                .offset(offset)
                .options(
                    selectinload(InterviewSession.turns),
                    selectinload(InterviewSession.application),
                )
            )
            sessions = res.scalars().all()

            job_res = await session.execute(
                select(JobListing).where(JobListing.id == job_id)
            )
            job = job_res.scalar_one()

            return [self._to_domain(s, job) for s in sessions]

    async def get_active_for_job_and_candidate(
        self,
        *,
        job_id: uuid.UUID,
        candidate_id: uuid.UUID,
    ) -> Optional[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .join(Application, InterviewSession.application_id == Application.id)
                .where(
                    Application.candidate_id == candidate_id,
                    Application.job_id == job_id,
                    InterviewSession.status == InterviewStatus.ACTIVE.value,
                )
                .order_by(InterviewSession.started_at.desc())
                .limit(1)
                .options(
                    selectinload(InterviewSession.turns),
                    selectinload(InterviewSession.application),
                )
            )
            s = res.scalar_one_or_none()
            if not s:
                return None

            job_res = await session.execute(
                select(JobListing).where(JobListing.id == job_id)
            )
            job = job_res.scalar_one()

            return self._to_domain(s, job)

    async def close_dangling_questions(self, interview_id: uuid.UUID) -> int:
        interview = await self.get_by_id(interview_id)
        if interview is None:
            logger.warning(
                f"[InterviewRepo] close_dangling_questions: "
                f"interview {interview_id} not found"
            )
            return 0

        count = interview.void_open_questions()
        if count:
            await self.save(interview)
            logger.info(
                f"[InterviewRepo] Voided {count} dangling question(s) "
                f"for interview {interview_id}"
            )
        return count

    async def list_by_status(
        self, status: InterviewStatus, *, limit: int = 50, offset: int = 0
    ) -> list[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .where(InterviewSession.status == status.value)
                .order_by(InterviewSession.created_at.desc())
                .limit(limit)
                .offset(offset)
                .options(
                    selectinload(InterviewSession.turns),
                    selectinload(InterviewSession.application),
                )
            )
            sessions = res.scalars().all()

            job_ids = {s.application.job_id for s in sessions}
            jobs_res = await session.execute(
                select(JobListing).where(JobListing.id.in_(job_ids))
            )
            jobs = {j.id: j for j in jobs_res.scalars().all()}

            return [self._to_domain(s, jobs[s.application.job_id]) for s in sessions]

    async def count_by_job(self, job_id: uuid.UUID) -> int:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(func.count())
                .select_from(InterviewSession)
                .join(Application, InterviewSession.application_id == Application.id)
                .where(Application.job_id == job_id)
            )
            return int(res.scalar_one())

    async def delete(self, interview_id: uuid.UUID) -> None:
        async with self._db.get_session() as session:
            await session.execute(
                delete(InterviewSession).where(InterviewSession.id == interview_id)
            )
            await session.commit()

    # Mapping helpers

    @staticmethod
    def _to_domain(session_row: InterviewSession, job: JobListing) -> Interview:
        app = session_row.application

        def _ensure_tz(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        # rebuild Turn[] from InterviewTurn rows
        turns: list[Turn] = []
        for t in sorted(session_row.turns, key=lambda x: x.seq):
            payload = t.payload or {}
            # only map turns that look like question turns; you can refine this
            if payload.get("question_id") and payload.get("question_text"):
                question = Question(
                    id=uuid.UUID(payload["question_id"]),
                    text=payload["question_text"],
                    topic=payload.get("topic"),
                    follow_up_of=(
                        uuid.UUID(payload["follow_up_of"])
                        if payload.get("follow_up_of")
                        else None
                    ),
                    asked_at=(
                        datetime.fromisoformat(payload["asked_at"])
                        if payload.get("asked_at")
                        else (t.started_at or session_row.created_at)
                    ),
                )

                answer = None
                if payload.get("answer_text"):
                    answered_at = payload.get("answered_at")
                    answer = Answer(
                        question_id=uuid.UUID(payload["question_id"]),
                        text=payload["answer_text"],
                        answered_at=(
                            datetime.fromisoformat(answered_at)
                            if answered_at
                            else (t.ended_at or session_row.updated_at)
                        ),
                        duration_seconds=payload.get("duration_seconds"),
                    )

                turns.append(Turn(question=question, answer=answer))

        return Interview(
            interview_id=session_row.id,
            job_id=app.job_id,
            candidate_id=app.candidate_id,
            org_id=job.org_id,
            status=InterviewStatus(session_row.status),
            max_questions=(
                session_row.realtime.get("max_questions", 10)
                if session_row.realtime
                else 10
            ),
            max_duration_minutes=(
                session_row.realtime.get("max_duration_minutes", 30)
                if session_row.realtime
                else 30
            ),
            turns=turns,
            started_at=_ensure_tz(session_row.started_at),
            ended_at=_ensure_tz(session_row.ended_at),
            created_at=_ensure_tz(session_row.created_at),
            updated_at=_ensure_tz(session_row.updated_at),
        )
