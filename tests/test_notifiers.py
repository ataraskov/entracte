import json

import httpx
import pytest
from pywebpush import WebPushException

from app.notifications.dispatcher import _build_notifiers
from app.notifications.gotify import GotifyNotifier
from app.notifications.telegram import TelegramNotifier
from app.notifications.webpush import WebPushNotifier
from app.models import Settings


def _mock_transport(monkeypatch, handler):
    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)


@pytest.mark.asyncio
async def test_gotify_sends_expected_payload(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["params"] = dict(request.url.params)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 1})

    _mock_transport(monkeypatch, handler)

    notifier = GotifyNotifier("http://gotify.local", "tok123")
    await notifier.send("Break time", "Chapter 6 at 50 min")

    assert captured["method"] == "POST"
    assert captured["params"]["token"] == "tok123"
    assert captured["json"]["title"] == "Break time"
    assert captured["json"]["message"] == "Chapter 6 at 50 min"


@pytest.mark.asyncio
async def test_telegram_sends_expected_payload(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    _mock_transport(monkeypatch, handler)

    notifier = TelegramNotifier("bot-token", "12345")
    await notifier.send("Break time", "Chapter 6 at 50 min")

    assert "bot-token" in captured["url"]
    assert captured["json"]["chat_id"] == "12345"
    assert "Break time" in captured["json"]["text"]
    assert "Chapter 6 at 50 min" in captured["json"]["text"]


def test_dispatcher_builds_only_enabled_channels_with_credentials():
    s = Settings(
        webpush_enabled=False,
        gotify_enabled=True,
        gotify_url="http://gotify.local",
        gotify_token="tok",
        telegram_enabled=True,
        telegram_bot_token="",  # missing credential -> should be skipped
        telegram_chat_id="123",
    )
    notifiers = _build_notifiers(s)
    assert len(notifiers) == 1
    assert isinstance(notifiers[0], GotifyNotifier)


@pytest.mark.asyncio
async def test_webpush_drops_subscription_on_410(monkeypatch):
    from app import db as db_module
    from app.models import PushSubscription

    with db_module.SessionLocal() as db:
        db.query(PushSubscription).delete()
        db.commit()
        db.add(PushSubscription(endpoint="https://push.example/1", p256dh="p", auth="a"))
        db.commit()

    def fake_webpush(*args, **kwargs):
        response = httpx.Response(410, request=httpx.Request("POST", "https://push.example/1"))
        raise WebPushException("gone", response=response)

    monkeypatch.setattr("app.notifications.webpush.webpush", fake_webpush)

    notifier = WebPushNotifier("fake-private-key")
    await notifier.send("Break time", "Chapter 6 at 50 min")

    with db_module.SessionLocal() as db:
        remaining = db.query(PushSubscription).filter_by(endpoint="https://push.example/1").all()
    assert remaining == []
