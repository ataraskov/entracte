from __future__ import annotations

import asyncio
import logging

from app.db import SessionLocal
from app.models import Settings
from app.notifications.base import Notifier
from app.notifications.gotify import GotifyNotifier
from app.notifications.telegram import TelegramNotifier
from app.notifications.webpush import WebPushNotifier

logger = logging.getLogger(__name__)


def _build_notifiers(settings: Settings) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if settings.webpush_enabled and settings.vapid_private_key:
        notifiers.append(WebPushNotifier(settings.vapid_private_key))
    if settings.gotify_enabled and settings.gotify_url and settings.gotify_token:
        notifiers.append(GotifyNotifier(settings.gotify_url, settings.gotify_token))
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        notifiers.append(TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id))
    return notifiers


async def notify(title: str, body: str) -> None:
    with SessionLocal() as db:
        settings = db.get(Settings, 1)
        notifiers = _build_notifiers(settings)

    if not notifiers:
        logger.info("No notification channels enabled; skipping notify(%r)", title)
        return

    results = await asyncio.gather(
        *(n.send(title, body) for n in notifiers), return_exceptions=True
    )
    for notifier, result in zip(notifiers, results):
        if isinstance(result, Exception):
            logger.error("Notifier %s failed: %s", type(notifier).__name__, result)
