from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import Session as DbSession
from .models import User
from .redis_client import get_redis
from .security import SESSION_COOKIE, csrf_ok, token_hash

Db = Annotated[AsyncSession, Depends(get_db)]

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LAST_SEEN_EVERY = timedelta(minutes=5)  # at most one write per user per interval


async def user_from_token(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    row = await db.execute(
        select(User, DbSession)
        .join(DbSession, DbSession.user_id == User.id)
        .where(DbSession.id == token_hash(token))
    )
    found = row.first()
    if not found:
        return None
    user, session = found
    if session.expires_at < datetime.now(UTC) or not user.is_active:
        return None
    return user


async def touch_last_seen(db: AsyncSession, user: User, now: datetime | None = None) -> bool:
    """Record that the user is active. Sessions last 30 days, so login alone would
    leave "last seen" stuck on the day they signed in."""
    now = now or datetime.now(UTC)
    if user.last_seen_at and now - user.last_seen_at < LAST_SEEN_EVERY:
        return False
    user.last_seen_at = now
    await db.commit()
    return True


async def current_user(request: Request, db: Db) -> User:
    user = await user_from_token(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "Not signed in")
    await touch_last_seen(db, user)
    if request.method in UNSAFE_METHODS and not csrf_ok(request):
        raise HTTPException(403, "CSRF check failed — reload the page and try again")
    return user


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(admin_user)]


async def rate_limit(key: str, limit: int, window_s: int = 60) -> None:
    redis = get_redis()
    bucket = f"rl:{key}:{int(datetime.now(UTC).timestamp()) // window_s}"
    count = await redis.incr(bucket)
    if count == 1:
        await redis.expire(bucket, window_s)
    if count > limit:
        raise HTTPException(429, "Too many requests — slow down a little and try again shortly")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
