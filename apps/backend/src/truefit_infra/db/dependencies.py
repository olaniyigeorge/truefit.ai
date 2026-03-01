from typing import Annotated, AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager

from db.database import db_manager


async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with db_manager.get_session() as session:
        yield session


async_db_session_dependency = Annotated[AsyncSession, Depends(get_async_db_session)]
