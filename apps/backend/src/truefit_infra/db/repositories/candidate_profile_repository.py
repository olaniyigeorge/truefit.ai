"""
SQLAlchemy implementation of CandidateProfileRepository against candidate_profiles.

Matches the "users + candidate_profiles" model.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.truefit_core.application.ports import CandidateProfileRepository
from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import CandidateProfile as CandidateProfileModel


class SQLAlchemyCandidateProfileRepository(CandidateProfileRepository):
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def create_for_user(
        self,
        *,
        user_id: uuid.UUID,
        headline: str | None = None,
        bio: str | None = None,
        location: str | None = None,
        years_experience: int | None = None,
        skills: list[str] | None = None,
    ) -> dict:
        """
        Upsert by unique constraint candidate_profiles.user_id.
        """
        values = {
            "user_id": user_id,
            "headline": headline,
            "bio": bio,
            "location": location,
            "years_experience": years_experience,
            "skills": skills or [],
        }

        stmt = (
            pg_insert(CandidateProfileModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "headline": values["headline"],
                    "bio": values["bio"],
                    "location": values["location"],
                    "years_experience": values["years_experience"],
                    "skills": values["skills"],
                },
            )
            .returning(CandidateProfileModel)
        )

        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one()

        return self._to_dict(row)

    async def get_by_user_id(self, user_id: uuid.UUID) -> Optional[dict]:
        stmt = select(CandidateProfileModel).where(CandidateProfileModel.user_id == user_id)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
        return self._to_dict(row) if row else None

    async def get_by_id(self, candidate_profile_id: uuid.UUID) -> Optional[dict]:
        stmt = select(CandidateProfileModel).where(CandidateProfileModel.id == candidate_profile_id)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
        return self._to_dict(row) if row else None

    async def delete(self, candidate_profile_id: uuid.UUID) -> None:
        stmt = delete(CandidateProfileModel).where(CandidateProfileModel.id == candidate_profile_id)
        async with self._db.get_session() as session:
            await session.execute(stmt)

    @staticmethod
    def _to_dict(row: CandidateProfileModel) -> dict:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "headline": row.headline,
            "bio": row.bio,
            "location": row.location,
            "years_experience": row.years_experience,
            "skills": row.skills or [],
            "resume_asset_id": row.resume_asset_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }