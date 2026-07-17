from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import get_db
from app.models.auth import AppUser, AuthSession, UserRole

_hasher = PasswordHasher()
_attempts: dict[str, deque[float]] = defaultdict(deque)
_WINDOW_SECONDS = 300
_MAX_FAILURES = 5


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except VerifyMismatchError:
        return False


def validate_password(password: str) -> None:
    if len(password) < 14 or password.isalpha() or password.isdigit():
        raise HTTPException(
            status_code=422,
            detail=(
                "Password needs 14 characters and must include letters and numbers or symbols"
            ),
        )


def login_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.casefold()}"


def check_login_allowed(key: str) -> None:
    now = time.monotonic()
    attempts = _attempts[key]
    while attempts and attempts[0] <= now - _WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")


def record_login_failure(key: str) -> None:
    _attempts[key].append(time.monotonic())


def clear_login_failures(key: str) -> None:
    _attempts.pop(key, None)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def setup_complete(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(func.count(AppUser.id))))


async def create_session(
    db: AsyncSession, user: AppUser, settings: Settings
) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        user_id=user.id,
        token_hash=_token_hash(token),
        csrf_token=secrets.token_urlsafe(24),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
    )
    db.add(session)
    await db.flush()
    return token, session


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AppUser:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    session = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == _token_hash(token))
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = await db.get(AppUser, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        await db.delete(session)
        raise HTTPException(status_code=401, detail="Session expired")
    request.state.auth_session = session
    return user


async def require_mutation(
    request: Request,
    user: Annotated[AppUser, Depends(get_current_user)],
) -> AppUser:
    session: AuthSession = request.state.auth_session
    supplied = request.headers.get("X-CSRF-Token")
    cookie = request.cookies.get("csrf")
    if (
        not supplied
        or not cookie
        or not secrets.compare_digest(supplied, session.csrf_token)
        or not secrets.compare_digest(cookie, session.csrf_token)
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    if user.role is UserRole.viewer:
        raise HTTPException(status_code=403, detail="Role cannot modify resources")
    return user


async def require_admin(
    user: Annotated[AppUser, Depends(require_mutation)],
) -> AppUser:
    if user.role not in {UserRole.owner, UserRole.admin}:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user
