from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Index
from sqlalchemy.orm import sessionmaker
import os

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://domain_user:domain_pass@localhost/domain_extractor")

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=True,
    future=True,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Sync session for migrations
from sqlalchemy import create_engine
sync_engine = create_engine(
    DATABASE_URL.replace("+asyncpg", ""),
    echo=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
)

# Base model
Base = declarative_base()

# Dependency to get DB session
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()