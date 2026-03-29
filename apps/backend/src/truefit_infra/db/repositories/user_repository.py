"""
SQLAlchemy implementation of UserRepository against the users table.

- Upsert with pg_insert + on_conflict_do_update
- Mapping functions _to_row/_to_domain
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.truefit_core.application.ports import UserRepository
from src.truefit_core.domain.user import User, UserRole
from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import User as UserModel


class SQLAlchemyUserRepository(UserRepository):
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def save(self, user: User) -> None:
        data = self._to_row(user)

        stmt = (
            pg_insert(UserModel)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "org_id": data["org_id"],
                    "display_name": data["display_name"],
                    "role": data["role"],
                    "auth_provider": data["auth_provider"],
                    "provider_subject": data["provider_subject"],
                    "is_active": data["is_active"],
                    "updated_at": data["updated_at"],
                },
            )
        )

        async with self._db.get_session() as session:
            await session.execute(stmt)

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        stmt = select(UserModel).where(UserModel.id == user_id)
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_email(self, email: str) -> Optional[User]:
        stmt = select(UserModel).where(UserModel.email == email.lower().strip())
        async with self._db.get_session() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def delete(self, user_id: uuid.UUID) -> None:
        stmt = delete(UserModel).where(UserModel.id == user_id)
        async with self._db.get_session() as session:
            await session.execute(stmt)

    @staticmethod
    def _to_row(user: User) -> dict:
        return {
            "id": user.id,
            "org_id": user.org_id,
            "email": user.email.lower(),
            "display_name": user.display_name,
            "role": user.role.value,
            "auth_provider": user.auth_provider,
            "provider_subject": user.provider_subject,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }

    @staticmethod
    def _to_domain(row: UserModel) -> User:
        return User(
            id=row.id,
            org_id=row.org_id,
            email=row.email,
            display_name=row.display_name,
            role=UserRole(row.role),
            auth_provider=row.auth_provider,
            provider_subject=row.provider_subject,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
