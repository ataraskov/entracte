from __future__ import annotations

import asyncio
import json
import logging

from pywebpush import WebPushException, webpush

from app.db import SessionLocal
from app.models import PushSubscription

logger = logging.getLogger(__name__)

VAPID_CLAIMS_SUB = "mailto:entracte@localhost"


class WebPushNotifier:
    def __init__(self, vapid_private_key: str):
        self._vapid_private_key = vapid_private_key

    async def send(self, title: str, body: str) -> None:
        with SessionLocal() as db:
            subscriptions = db.query(PushSubscription).all()

        if not subscriptions:
            return

        results = await asyncio.gather(
            *(self._send_one(sub, title, body) for sub in subscriptions),
            return_exceptions=True,
        )
        for sub, result in zip(subscriptions, results):
            if isinstance(result, Exception):
                logger.error("Web push to subscription %s failed: %s", sub.id, result)

    async def _send_one(self, sub: PushSubscription, title: str, body: str) -> None:
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        }
        payload = json.dumps({"title": title, "body": body})
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=self._vapid_private_key,
                vapid_claims={"sub": VAPID_CLAIMS_SUB},
            )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                # Subscription no longer valid (browser unsubscribed/expired).
                with SessionLocal() as db:
                    db.query(PushSubscription).filter_by(id=sub.id).delete()
                    db.commit()
            else:
                raise
