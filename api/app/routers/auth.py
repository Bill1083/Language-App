from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from ..config import get_settings
from ..deps import CurrentUser, Db, client_ip, rate_limit
from ..models import Enrolment, Invite, Recording, User
from ..models import Session as DbSession
from ..security import (
    SESSION_COOKIE,
    clear_session_cookies,
    hash_password,
    new_token,
    session_expiry,
    set_session_cookies,
    token_hash,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

DEFAULT_USER_SETTINGS: dict[str, Any] = {
    "theme": "dark", "sound": True, "daily_goal_type": "xp", "daily_goal_value": 30, "new_cards_per_day": 15,
    "voice_gender": "female", "speech_speed": 1.0, "furigana": "always", "romaji": "auto", "strictness": "normal",
    "gender_colors": True, "reminders": False, "reminder_hour": 19, "timezone": "UTC", "active_language": None,
    "onboarded": False, "voice_notice_seen": False,
}


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"


class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)
    invite: str | None = None
    timezone: str | None = None


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    password: str = Field(max_length=200)


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=8, max_length=200)


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    settings: dict[str, Any] | None = None


async def user_json(db, user: User) -> dict[str, Any]:
    enrolments = list(await db.scalars(select(Enrolment).where(Enrolment.user_id == user.id)
                                       .order_by(Enrolment.created_at)))
    return {
        "id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role,
        "settings": {**DEFAULT_USER_SETTINGS, **(user.settings_json or {})},
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "enrolments": [{"language_code": e.language_code, "current_level": e.current_level,
                        "settings": e.settings_json or {}, "placement": e.placement_result} for e in enrolments],
    }


async def start_session(db, request: Request, response: Response, user: User) -> None:
    token = new_token()
    db.add(DbSession(id=token_hash(token), user_id=user.id, expires_at=session_expiry(),
                     user_agent=(request.headers.get("user-agent") or "")[:300]))
    user.last_seen_at = datetime.now(UTC)
    await db.commit()
    set_session_cookies(request, response, token)


@router.get("/status")
async def status(db: Db, invite: str | None = None) -> dict[str, Any]:
    users = await db.scalar(select(func.count()).select_from(User)) or 0
    invite_ok = None
    if invite:
        inv = await db.scalar(select(Invite).where(Invite.token == invite))
        invite_ok = bool(inv and inv.used_by is None and inv.expires_at > datetime.now(UTC))
    return {"needs_setup": users == 0, "registration_mode": get_settings().registration_mode, "invite_valid": invite_ok}


@router.post("/register")
async def register(body: RegisterIn, request: Request, response: Response, db: Db) -> dict[str, Any]:
    await rate_limit(f"register:{client_ip(request)}", 10)
    first_user = (await db.scalar(select(func.count()).select_from(User)) or 0) == 0
    mode = get_settings().registration_mode
    invite: Invite | None = None
    if not first_user:
        if body.invite:
            invite = await db.scalar(select(Invite).where(Invite.token == body.invite).with_for_update())
            if not invite or invite.used_by is not None or invite.expires_at < datetime.now(UTC):
                raise HTTPException(400, "This invite link is invalid or has expired")
        elif mode != "open":
            raise HTTPException(403, "Registration is invite-only. Ask the admin for an invite link."
                                if mode == "invite" else "Registration is closed on this server.")
    email = body.email.lower().strip()
    if await db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    settings = dict(DEFAULT_USER_SETTINGS)
    if body.timezone:
        settings["timezone"] = body.timezone
    user = User(email=email, password_hash=hash_password(body.password), display_name=body.display_name.strip(),
                role="admin" if first_user else "user", settings_json=settings)
    db.add(user)
    await db.flush()
    if invite:
        invite.used_by, invite.used_at = user.id, datetime.now(UTC)
    await start_session(db, request, response, user)
    return await user_json(db, user)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: Db) -> dict[str, Any]:
    await rate_limit(f"login:{client_ip(request)}", 10)
    user = await db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if not user or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, "Wrong email or password")
    if not user.is_active:
        raise HTTPException(403, "This account has been disabled")
    await start_session(db, request, response, user)
    return await user_json(db, user)


@router.post("/logout")
async def logout(request: Request, response: Response, db: Db) -> dict[str, bool]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.execute(delete(DbSession).where(DbSession.id == token_hash(token)))
        await db.commit()
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser, db: Db) -> dict[str, Any]:
    return await user_json(db, user)


@router.patch("/me")
async def update_me(body: MeUpdate, user: CurrentUser, db: Db) -> dict[str, Any]:
    if body.display_name is not None and body.display_name.strip():
        user.display_name = body.display_name.strip()
    if body.settings:
        allowed = {k: v for k, v in body.settings.items() if k in DEFAULT_USER_SETTINGS}
        user.settings_json = {**(user.settings_json or {}), **allowed}
    await db.commit()
    return await user_json(db, user)


@router.post("/me/password")
async def change_password(body: PasswordIn, user: CurrentUser, db: Db, request: Request) -> dict[str, bool]:
    if not verify_password(user.password_hash, body.current):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(body.new)
    current = token_hash(request.cookies.get(SESSION_COOKIE, ""))
    await db.execute(delete(DbSession).where(DbSession.user_id == user.id, DbSession.id != current))
    await db.commit()
    return {"ok": True}


@router.delete("/me/recordings")
async def delete_my_recordings(user: CurrentUser, db: Db) -> dict[str, int]:
    from pathlib import Path

    rows = list(await db.scalars(select(Recording).where(Recording.user_id == user.id, Recording.path.is_not(None))))
    for rec in rows:
        Path(rec.path).unlink(missing_ok=True)  # type: ignore[arg-type]
        rec.path = None
    await db.commit()
    return {"deleted": len(rows)}
