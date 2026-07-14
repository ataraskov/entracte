from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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
