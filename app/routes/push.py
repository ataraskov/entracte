from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PushSubscription, Settings

router = APIRouter()


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    endpoint: str
    keys: PushKeys


@router.get("/sw.js")
def service_worker() -> FileResponse:
    # Served at the origin root (not /static/sw.js) so its default scope
    # covers the whole app without needing a Service-Worker-Allowed header.
    return FileResponse("app/static/sw.js", media_type="application/javascript")


@router.get("/api/push/vapid-public-key")
def vapid_public_key(db: Session = Depends(get_db)) -> JSONResponse:
    settings = db.get(Settings, 1)
    return JSONResponse({"publicKey": settings.vapid_public_key})


@router.post("/api/push/subscribe")
def subscribe(payload: PushSubscribeRequest, db: Session = Depends(get_db)) -> JSONResponse:
    existing = db.query(PushSubscription).filter_by(endpoint=payload.endpoint).one_or_none()
    if existing is None:
        db.add(
            PushSubscription(
                endpoint=payload.endpoint,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
            )
        )
        db.commit()
    return JSONResponse({"status": "ok"})


@router.post("/api/push/unsubscribe")
def unsubscribe(payload: dict, db: Session = Depends(get_db)) -> JSONResponse:
    endpoint = payload.get("endpoint")
    if endpoint:
        db.query(PushSubscription).filter_by(endpoint=endpoint).delete()
        db.commit()
    return JSONResponse({"status": "ok"})
