from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.version import __version__

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["version"] = __version__


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {})
