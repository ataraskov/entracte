import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import config
from app.db import init_db
from app.plex import watcher
from app.routes import api, dashboard, push, settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # alembic's fileConfig() (run above, as part of the migration) resets the
    # root logger per alembic.ini's [logger_root] (level=WARNING), clobbering
    # the level set below. Re-assert it here so app-level INFO logs survive.
    logging.basicConfig(level=logging.INFO, force=True)
    watcher_task = asyncio.create_task(watcher.run_forever(config.poll_interval_s))
    yield
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Entracte", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(api.router)
app.include_router(push.router)
