# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Entracte watches what's currently playing on a Plex server, reads the title's embedded chapter markers, picks a good moment to take a break, and notifies the user shortly before that point via Web Push, Gotify, and/or Telegram. FastAPI + htmx + server-rendered Jinja templates (Pico CSS), SQLite via SQLAlchemy, no build step or frontend framework.

## Commands

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload      # run locally, http://localhost:8000
pytest                              # run all tests
pytest tests/test_watcher_notify.py -k some_test  # run a single test
docker compose up -d --build        # run via Docker instead
```

There is no lint/format command configured in this repo.

Config is env-driven (`ENTRACTE_*` vars, see `.env.example` and `app/config.py`); secrets (Plex token, notifier credentials) are entered via the `/settings` page and stored in the DB, never via env/CLI.

## Architecture

**Single-row settings, not multi-user.** `Settings` (`app/models.py`) is a single DB row (`id=1`) holding every user-editable config value — Plex URL/token, break heuristic parameters, and per-channel notification settings/credentials. There is no concept of multiple users or profiles. VAPID keypair for Web Push is generated once in `init_db()` (`app/db.py`) and persisted on that same row.

**Background polling loop drives everything.** `app/plex/watcher.py::run_forever` is started as an asyncio task in the FastAPI `lifespan` (`app/main.py`) and is the only place that reads Plex state and decides when to notify:
- Polls `/status/sessions` on `poll_interval_s` (configurable), plus a best-effort websocket listener (`_websocket_loop`) to Plex's undocumented notifications endpoint that wakes the poll loop early on "playing" events — the websocket is purely a "poll now" trigger, never a data source, since it's unstable/undocumented.
- On a new session, fetches chapters and calls `app/breaks/heuristic.py::suggest_break` to pick the chapter boundary closest to a configurable target percent of runtime, skipping a head/tail window (`break_skip_start_pct`/`break_skip_end_pct`).
- `SessionStore` (in-process, in-memory) holds the current session + chapters for the dashboard to read; `SessionState` (DB-persisted) holds only what's needed for notify-once dedup (`notified_at`) so restarts/reconnects can't double-send.
- `_maybe_notify` fires once per session when playback position enters `[suggested_offset - lead_time, suggested_offset]`, via `app.notifications.dispatcher.notify(...)` as a fire-and-forget task (tasks are kept in `_background_tasks` so asyncio's weak references don't GC them mid-flight).

**Notifiers share a `Notifier` protocol** (`app/notifications/base.py`: just an async `send(title, body)`). `dispatcher._build_notifiers` reads the `Settings` row and instantiates whichever of `WebPushNotifier`/`GotifyNotifier`/`TelegramNotifier` are enabled+configured; `notify()` fans out to all of them with `asyncio.gather(..., return_exceptions=True)` and only logs failures — a broken notifier never breaks the others or the poll loop. Note `WebPushNotifier.send` swallows/logs errors per-subscription itself (and auto-deletes subscriptions that 404/410), so code that needs to *observe* a push failure (e.g. a "test notification" check) must bypass `.send()` and call `pywebpush.webpush` directly, as `app/routes/settings.py::check_webpush` does.

**Routes are organized by concern, not REST resource**: `dashboard.py` (the `/` page), `settings.py` (`/settings` GET/POST + `/settings/check/*` htmx endpoints that validate a channel's credentials without saving them), `api.py` (`/api/session/current`, an htmx fragment polled by the dashboard), `push.py` (service worker + Web Push subscribe/unsubscribe JSON API). Templates extend `base.html`; htmx (vendored in `app/static/htmx.min.js`) is used for partial page updates instead of a JS framework — see `hx-post`/`hx-target` attributes in `settings.html` and the polling in `dashboard.html`.

**Tests run against a throwaway SQLite DB** — `tests/conftest.py` points `ENTRACTE_DB_PATH` at a fresh temp file before any app module is imported, so tests never touch `./data/entracte.db`. Tests use fabricated data/mocked HTTP, not a live Plex server.
