from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("SECRET_KEY", "test-secret")

from app.config import Settings, override_settings
from app.database import Base, reset_engine
from app.main import create_app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        database_url=TEST_DB_URL,
        secret_key="test-secret",
        library_root=tmp_path / "library",
        slskd_url="",
        slskd_api_key="",
        prowlarr_url="",
        prowlarr_api_key="",
        sabnzbd_url="",
        sabnzbd_api_key="",
        naming_template="{album_artist}/{year} - {album}/{disc_track} - {title}.{ext}",
    )
    override_settings(settings)
    return settings


@pytest_asyncio.fixture
async def db_session(test_settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    reset_engine(TEST_DB_URL)
    app = create_app()
    engine = create_async_engine(TEST_DB_URL)

    import app.database as db_module

    db_module._engine = engine
    db_module._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
