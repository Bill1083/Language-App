"""Web push reminders. VAPID keys come from `.env` or are generated on first
boot and kept in app_settings, so push works with zero configuration."""

import asyncio
import base64
import json
import logging
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AppSetting, PushSubscription

log = logging.getLogger("parlo.push")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _generate() -> dict[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64(key.public_key().public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint))
    return {"public": public, "private": private}


async def vapid_keys(db: AsyncSession) -> dict[str, str]:
    env = get_settings()
    if env.vapid_public_key and env.vapid_private_key:
        return {"public": env.vapid_public_key, "private": env.vapid_private_key}
    row = await db.get(AppSetting, "_vapid")
    if row is None:
        row = AppSetting(key="_vapid", value_json=_generate())
        db.add(row)
        await db.commit()
    return row.value_json


async def send_push(db: AsyncSession, sub: PushSubscription, payload: dict[str, Any]) -> bool:
    from pywebpush import WebPushException, webpush

    keys = await vapid_keys(db)
    env = get_settings()
    subject = env.vapid_subject or f"https://{env.domain}"

    def _send() -> None:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload),
            vapid_private_key=keys["private"],
            vapid_claims={"sub": subject},
            ttl=3600,
        )

    try:
        await asyncio.to_thread(_send)
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):  # subscription expired
            await db.delete(sub)
        log.warning("push failed (%s): %s", status, e)
        return False


async def user_subscriptions(db: AsyncSession, user_id: int) -> list[PushSubscription]:
    return list(await db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)))
