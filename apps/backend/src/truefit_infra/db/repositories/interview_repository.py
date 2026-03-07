from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

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

# Notes on mapping:
# - InterviewSession.id                 -> Interview.interview_id
# - InterviewSession.application_id     -> join Application for job_id + candidate_id
# - Application.job_id                  -> Interview.job_id
# - Application.candidate_id            -> Interview.candidate_id
# - JobListing.org_id                   -> Interview.company_id
# - InterviewTurn rows                  -> Interview.turns (Turn(question, answer))
#
# This repo treats "one Interview" == "one InterviewSession".


class SQLAlchemyInterviewRepository(InterviewRepository):
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def save(self, interview: Interview) -> None:
        """
        Upsert-ish behavior:
        - If session exists, update status/timestamps and replace turns (simple + safe).
        - If it doesn't, create session, then insert turns.
        """
        async with self._db.get_session() as session:
            # 1) Load existing session (and its turns)
            existing = await session.execute(
                select(InterviewSession)
                .where(InterviewSession.id == interview.id)  # or interview.interview_id depending on your domain
                .options(selectinload(InterviewSession.turns))
            )
            session_row = existing.scalar_one_or_none()

            # 2) Create or update the InterviewSession row
            if session_row is None:
                # We need application_id to create a session.
                # Domain interview must carry application_id OR we must find it by (job_id, candidate_id).
                # Here we resolve application_id by job_id + candidate_id.
                app_res = await session.execute(
                    select(Application)
                    .where(
                        Application.job_id == interview.job_id,
                        Application.candidate_id == interview.candidate_id,
                    )
                )
                app = app_res.scalar_one_or_none()
                if app is None:
                    raise ValueError("Application not found for job_id + candidate_id; cannot create InterviewSession.")

                session_row = InterviewSession(
                    id=interview.id,  # or interview.interview_id
                    application_id=app.id,
                    round=1,
                    status=interview.status.value,
                    started_at=interview.started_at,
                    ended_at=interview.ended_at,
                    # realtime/context_snapshot can stay defaults
                )
                session.add(session_row)
                await session.flush()  # ensures session_row exists for FK inserts

            else:
                session_row.status = interview.status.value
                session_row.started_at = interview.started_at
                session_row.ended_at = interview.ended_at

            # 3) Replace turns (simple approach; ok for hackathon scale)
            # Delete existing turns then insert fresh sequence
            if session_row.turns:
                for t in session_row.turns:
                    await session.delete(t)
                await session.flush()

            # Insert new turns with sequential numbering
            for i, turn in enumerate(interview.turns, start=1):
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

                # Store as a single "turn" row.
                # If you want Q and A as separate rows, we can split it.
                session.add(
                    InterviewTurn(
                        session_id=session_row.id,
                        seq=i,
                        speaker="agent",        # question asked by agent (adjust if your domain differs)
                        modality="text",        # adjust if you use audio/video
                        turn_text=q.text,       # optional
                        payload=payload,
                        started_at=q.asked_at,
                        ended_at=a.answered_at if a else None,
                    )
                )

                # If candidate answered, add another row (optional, but more truthful)
                if a and a.text:
                    i += 1
                    session.add(
                        InterviewTurn(
                            session_id=session_row.id,
                            seq=i,
                            speaker="candidate",
                            modality="text",
                            turn_text=a.text,
                            payload=payload,
                            started_at=a.answered_at,
                            ended_at=a.answered_at,
                        )
                    )

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
            job_res = await session.execute(select(JobListing).where(JobListing.id == app.job_id))
            job = job_res.scalar_one()

            return self._to_domain(session_row=s, job=job)

    async def list_by_candidate(self, candidate_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .join(Application, InterviewSession.application_id == Application.id)
                .where(Application.candidate_id == candidate_id)
                .order_by(InterviewSession.created_at.desc())
                .limit(limit)
                .offset(offset)
                .options(selectinload(InterviewSession.turns), selectinload(InterviewSession.application))
            )
            sessions = res.scalars().all()

            # batch load jobs for org_id mapping
            job_ids = {s.application.job_id for s in sessions}
            jobs_res = await session.execute(select(JobListing).where(JobListing.id.in_(job_ids)))
            jobs = {j.id: j for j in jobs_res.scalars().all()}

            return [self._to_domain(s, jobs[s.application.job_id]) for s in sessions]

    async def list_by_job(self, job_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .join(Application, InterviewSession.application_id == Application.id)
                .where(Application.job_id == job_id)
                .order_by(InterviewSession.created_at.desc())
                .limit(limit)
                .offset(offset)
                .options(selectinload(InterviewSession.turns), selectinload(InterviewSession.application))
            )
            sessions = res.scalars().all()

            job_res = await session.execute(select(JobListing).where(JobListing.id == job_id))
            job = job_res.scalar_one()

            return [self._to_domain(s, job) for s in sessions]

    async def get_active_for_candidate_and_job(self, candidate_id: uuid.UUID, job_id: uuid.UUID) -> Optional[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .join(Application, InterviewSession.application_id == Application.id)
                .where(
                    Application.candidate_id == candidate_id,
                    Application.job_id == job_id,
                    InterviewSession.status == InterviewStatus.ACTIVE.value,
                )
                .options(selectinload(InterviewSession.turns), selectinload(InterviewSession.application))
            )
            s = res.scalar_one_or_none()
            if not s:
                return None

            job_res = await session.execute(select(JobListing).where(JobListing.id == job_id))
            job = job_res.scalar_one()

            return self._to_domain(s, job)

    async def list_by_status(self, status: InterviewStatus, *, limit: int = 50, offset: int = 0) -> list[Interview]:
        async with self._db.get_session() as session:
            res = await session.execute(
                select(InterviewSession)
                .where(InterviewSession.status == status.value)
                .order_by(InterviewSession.created_at.desc())
                .limit(limit)
                .offset(offset)
                .options(selectinload(InterviewSession.turns), selectinload(InterviewSession.application))
            )
            sessions = res.scalars().all()

            job_ids = {s.application.job_id for s in sessions}
            jobs_res = await session.execute(select(JobListing).where(JobListing.id.in_(job_ids)))
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
            await session.execute(delete(InterviewSession).where(InterviewSession.id == interview_id))
            await session.commit()

    # -----------------------
    # Mapping helpers
    # -----------------------

    @staticmethod
    def _to_domain(session_row: InterviewSession, job: JobListing) -> Interview:
        app = session_row.application

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
                    follow_up_of=(uuid.UUID(payload["follow_up_of"]) if payload.get("follow_up_of") else None),
                    asked_at=datetime.fromisoformat(payload["asked_at"]) if payload.get("asked_at") else (t.started_at or session_row.created_at),
                )

                answer = None
                if payload.get("answer_text"):
                    answered_at = payload.get("answered_at")
                    answer = Answer(
                        question_id=uuid.UUID(payload["question_id"]),
                        text=payload["answer_text"],
                        answered_at=datetime.fromisoformat(answered_at) if answered_at else (t.ended_at or session_row.updated_at),
                        duration_seconds=payload.get("duration_seconds"),
                    )

                turns.append(Turn(question=question, answer=answer))

        return Interview(
            interview_id=session_row.id,
            job_id=app.job_id,
            candidate_id=app.candidate_id,
            company_id=job.org_id,
            status=InterviewStatus(session_row.status),
            max_questions=session_row.realtime.get("max_questions", 10) if hasattr(session_row, "realtime") else 10,
            max_duration_minutes=session_row.realtime.get("max_duration_minutes", 30) if hasattr(session_row, "realtime") else 30,
            turns=turns,
            started_at=session_row.started_at,
            ended_at=session_row.ended_at,
            created_at=session_row.created_at,
            updated_at=session_row.updated_at,
        )