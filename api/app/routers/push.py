from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from ..deps import CurrentUser, Db
from ..models import PushSubscription
from ..services.push import send_push, user_subscriptions, vapid_keys

router = APIRouter(prefix="/push", tags=["push"])


class Keys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: Keys


class Unsubscribe(BaseModel):
    endpoint: str


@router.get("/key")
async def public_key(user: CurrentUser, db: Db) -> dict[str, str]:
    return {"public_key": (await vapid_keys(db))["public"]}


@router.post("/subscribe")
async def subscribe(body: SubscriptionIn, user: CurrentUser, db: Db) -> dict[str, bool]:
    existing = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing:
        existing.user_id, existing.p256dh, existing.auth = user.id, body.keys.p256dh, body.keys.auth
    else:
        db.add(PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth))
    await db.commit()
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(body: Unsubscribe, user: CurrentUser, db: Db) -> dict[str, bool]:
    await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint,
                                                    PushSubscription.user_id == user.id))
    await db.commit()
    return {"ok": True}


@router.post("/test")
async def test_push(user: CurrentUser, db: Db) -> dict[str, Any]:
    subs = await user_subscriptions(db, user.id)
    if not subs:
        raise HTTPException(400, "This device isn't subscribed to reminders yet")
    sent = 0
    for sub in subs:
        sent += await send_push(db, sub, {"title": "Parlo reminders are on 🎉",
                                          "body": "You'll get a nudge at your reminder time.", "url": "/"})
    await db.commit()
    return {"sent": sent}
