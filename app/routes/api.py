from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.plex import watcher

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/api/session/current", response_class=HTMLResponse)
async def session_current(request: Request):
    session = await watcher.store.get()
    return templates.TemplateResponse(request, "_chapter_timeline.html", {"session": session})
