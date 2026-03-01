from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from contextlib import asynccontextmanager
from typing import AsyncGenerator


from src.truefit_core.common.utils import logger

Base = declarative_base()


class DatabaseManager:
    def __init__(self):
        self.engine = None
        self.session_factory = None
        self._is_initialized = False

    def initialize(self, database_url: str, **engine_kwargs):
        """Initialize database engine and session factory"""
        if self._is_initialized:
            logger.warning("Database already initialized")
            return

        self.engine = create_async_engine(database_url, future=True, **engine_kwargs)

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=True,
            autocommit=False,
        )

        self._is_initialized = True
        logger.info(f"Database initialized with URL: {database_url}")

    async def create_tables(self):
        """Create all database tables"""
        logger.info("\n creating tables...\n")
        if not self.engine:
            raise RuntimeError("Database not initialized")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully")

    async def close(self):
        """Close database connections"""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connections closed")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session with automatic cleanup"""
        if not self.session_factory:
            raise RuntimeError("Database not initialized")

        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


# Global database manager instance
db_manager = DatabaseManager()
