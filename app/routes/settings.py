import asyncio
import html
import json

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pywebpush import webpush
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PushSubscription, Settings
from app.notifications.gotify import GotifyNotifier
from app.notifications.telegram import TelegramNotifier
from app.notifications.webpush import VAPID_CLAIMS_SUB
from app.plex.client import PlexClient

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _check_result(ok: bool, message: str) -> str:
    color = "var(--pico-ins-color)" if ok else "var(--pico-del-color)"
    mark = "✓" if ok else "✗"
    return f'<span style="color: {color}">{mark} {html.escape(message)}</span>'


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    s = db.get(Settings, 1)
    return templates.TemplateResponse(request, "settings.html", {"s": s, "saved": False})


@router.post("/settings", response_class=HTMLResponse)
def save_settings(
    request: Request,
    db: Session = Depends(get_db),
    plex_base_url: str = Form(...),
    plex_token: str = Form(...),
    break_target_pct: float = Form(...),
    break_skip_start_pct: float = Form(...),
    break_skip_end_pct: float = Form(...),
    break_lead_time_s: int = Form(...),
    webpush_enabled: bool = Form(False),
    gotify_enabled: bool = Form(False),
    gotify_url: str = Form(""),
    gotify_token: str = Form(""),
    telegram_enabled: bool = Form(False),
    telegram_bot_token: str = Form(""),
    telegram_chat_id: str = Form(""),
):
    s = db.get(Settings, 1)
    s.plex_base_url = plex_base_url.rstrip("/")
    s.plex_token = plex_token
    s.break_target_pct = break_target_pct
    s.break_skip_start_pct = break_skip_start_pct
    s.break_skip_end_pct = break_skip_end_pct
    s.break_lead_time_s = break_lead_time_s
    s.webpush_enabled = webpush_enabled
    s.gotify_enabled = gotify_enabled
    s.gotify_url = gotify_url.rstrip("/")
    s.gotify_token = gotify_token
    s.telegram_enabled = telegram_enabled
    s.telegram_bot_token = telegram_bot_token
    s.telegram_chat_id = telegram_chat_id
    db.commit()
    db.refresh(s)
    return templates.TemplateResponse(request, "settings.html", {"s": s, "saved": True})


@router.post("/settings/check/plex", response_class=HTMLResponse)
async def check_plex(
    plex_base_url: str = Form(...),
    plex_token: str = Form(...),
):
    client = PlexClient(plex_base_url, plex_token)
    try:
        sessions = await client.get_sessions()
    except httpx.HTTPStatusError as exc:
        return _check_result(False, f"Plex responded with HTTP {exc.response.status_code}.")
    except httpx.RequestError as exc:
        return _check_result(False, f"Could not reach Plex: {exc}")
    finally:
        await client.aclose()
    return _check_result(True, f"Connected. {len(sessions)} active session(s).")


@router.post("/settings/check/gotify", response_class=HTMLResponse)
async def check_gotify(
    gotify_url: str = Form(...),
    gotify_token: str = Form(...),
):
    notifier = GotifyNotifier(gotify_url, gotify_token)
    try:
        await notifier.send("Entracte test", "This is a test notification from Entracte settings.")
    except httpx.HTTPStatusError as exc:
        return _check_result(False, f"Gotify responded with HTTP {exc.response.status_code}.")
    except httpx.RequestError as exc:
        return _check_result(False, f"Could not reach Gotify: {exc}")
    return _check_result(True, "Test notification sent.")


@router.post("/settings/check/telegram", response_class=HTMLResponse)
async def check_telegram(
    telegram_bot_token: str = Form(...),
    telegram_chat_id: str = Form(...),
):
    notifier = TelegramNotifier(telegram_bot_token, telegram_chat_id)
    try:
        await notifier.send("Entracte test", "This is a test notification from Entracte settings.")
    except httpx.HTTPStatusError as exc:
        return _check_result(False, f"Telegram responded with HTTP {exc.response.status_code}.")
    except httpx.RequestError as exc:
        return _check_result(False, f"Could not reach Telegram: {exc}")
    return _check_result(True, "Test message sent.")


@router.post("/settings/check/webpush", response_class=HTMLResponse)
async def check_webpush(db: Session = Depends(get_db)):
    s = db.get(Settings, 1)
    subscriptions = db.query(PushSubscription).all()
    if not subscriptions:
        return _check_result(
            False, "No browser is subscribed yet. Click 'Enable push in this browser' first."
        )

    payload = json.dumps(
        {"title": "Entracte test", "body": "This is a test notification from Entracte settings."}
    )

    async def _send_one(sub: PushSubscription) -> None:
        await asyncio.to_thread(
            webpush,
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=payload,
            vapid_private_key=s.vapid_private_key,
            vapid_claims={"sub": VAPID_CLAIMS_SUB},
        )

    results = await asyncio.gather(*(_send_one(sub) for sub in subscriptions), return_exceptions=True)
    failures = [r for r in results if isinstance(r, Exception)]
    if failures:
        return _check_result(
            False, f"{len(failures)} of {len(subscriptions)} push attempt(s) failed: {failures[0]}"
        )
    return _check_result(True, f"Test push sent to {len(subscriptions)} subscription(s).")
