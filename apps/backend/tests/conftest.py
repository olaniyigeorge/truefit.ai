"""
tests/conftest.py
────
Shared pytest fixtures for all test layers.

- async_db_session:  in-memory SQLite engine + session factory for integration tests.
  Uses aiosqlite so there is no Postgres dependency in CI.
  All models are created fresh at the start of each test function (function scope).
"""

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.truefit_infra.db.database import DatabaseManager
from src.truefit_infra.db.models import Base, Org, User, UserRole

# ─
# In-memory SQLite engine (integration tests only)
# ─

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def async_engine():
    """Creates a fresh in-memory SQLite engine for each test function."""
    engine = create_async_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yields one AsyncSession per test, rolled back after each test."""
    factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=True,
        autocommit=False,
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def db_manager(async_engine) -> DatabaseManager:
    """A DatabaseManager wired to the in-memory SQLite engine."""
    manager = DatabaseManager()
    manager.engine = async_engine
    manager.session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=True,
        autocommit=False,
    )
    manager._is_initialized = True
    return manager


# ─
# Seed data helpers
# ─


async def _create_org(session: AsyncSession, name: str = "Acme Corp") -> Org:
    org = Org(
        id=uuid.uuid4(),
        name=name,
        slug=name.lower().replace(" ", "-"),
    )
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def _create_user(
    session: AsyncSession,
    org: Org,
    email: str = "recruiter@acme.com",
    role: str = UserRole.recruiter.value,
    display_name: str = "Recruiter Bob",
) -> User:
    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        email=email,
        display_name=display_name,
        role=role,
        auth_provider="firebase",
        provider_subject=f"firebase|{uuid.uuid4().hex}",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def org(async_session: AsyncSession) -> Org:
    return await _create_org(async_session)


@pytest_asyncio.fixture()
async def recruiter_user(async_session: AsyncSession, org: Org) -> User:
    return await _create_user(async_session, org)


@pytest_asyncio.fixture()
async def candidate_user(async_session: AsyncSession, org: Org) -> User:
    return await _create_user(
        async_session,
        org,
        email="candidate@example.com",
        role=UserRole.candidate.value,
        display_name="Alice Smith",
    )
