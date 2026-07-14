from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
from datetime import datetime, timezone

import websockets

from app.breaks.heuristic import suggest_break
from app.db import SessionLocal
from app.models import Settings, SessionState as SessionStateModel
from app.notifications import dispatcher
from app.plex.client import Chapter, PlaySession, PlexClient

logger = logging.getLogger(__name__)

# Keep references to fire-and-forget notify tasks so they aren't garbage
# collected mid-flight (asyncio only holds a weak reference otherwise).
_background_tasks: set[asyncio.Task] = set()

# Set by the websocket listener to wake the polling loop early when Plex
# reports a "playing" state change, for lower latency than the plain poll
# interval. The websocket API is undocumented/unstable, so it's used purely
# as a "poll now" trigger, never as the data source itself.
_poll_now = asyncio.Event()


@dataclasses.dataclass
class CurrentSession:
    session_key: str
    rating_key: str
    title: str
    thumb: str
    duration_ms: int
    view_offset_ms: int
    chapters: list[Chapter]
    suggested_break: Chapter | None
    player_machine_identifier: str = ""


class SessionStore:
    """In-process holder for the latest known playback session. Chapters and
    live position are kept here rather than in the DB since they're ephemeral;
    only what's needed for notify dedup is persisted (see SessionState)."""

    def __init__(self) -> None:
        self._current: CurrentSession | None = None
        self._lock = asyncio.Lock()

    async def set(self, session: CurrentSession | None) -> None:
        async with self._lock:
            self._current = session

    async def get(self) -> CurrentSession | None:
        async with self._lock:
            return self._current


store = SessionStore()


def _session_sort_key(session_key: str) -> int:
    try:
        return int(session_key)
    except ValueError:
        return -1


def _persist_session_state(session: PlaySession, suggested: Chapter | None, duration_ms: int) -> None:
    with SessionLocal() as db:
        row = (
            db.query(SessionStateModel)
            .filter_by(session_key=session.session_key)
            .one_or_none()
        )
        if row is None:
            row = SessionStateModel(session_key=session.session_key)
            db.add(row)
        row.rating_key = session.rating_key
        row.title = session.title
        row.duration_ms = duration_ms
        row.suggested_break_offset_ms = suggested.start_offset_ms if suggested else None
        db.commit()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _maybe_notify(
    session_key: str, title: str, suggested: Chapter | None, view_offset_ms: int, lead_time_s: int
) -> None:
    """Fires the break notification once per session, when playback crosses
    into the [suggested_offset - lead_time, suggested_offset] window. Dedup
    is enforced via SessionState.notified_at so reconnects/restarts of the
    poll loop can't double-send."""
    if suggested is None:
        return

    threshold_ms = suggested.start_offset_ms - lead_time_s * 1000
    if not (threshold_ms <= view_offset_ms <= suggested.start_offset_ms):
        return

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one_or_none()
        if row is None or row.notified_at is not None:
            return
        row.notified_at = datetime.now(timezone.utc)
        db.commit()

    minutes = suggested.start_offset_ms / 60_000
    chapter_label = f" ({suggested.title})" if suggested.title else ""
    body = f'Good spot for a break in "{title}" around {minutes:.0f} min{chapter_label}'
    _fire_and_forget(dispatcher.notify("Time for a break", body))


async def _maybe_autopause(
    client: PlexClient,
    session_key: str,
    player_machine_identifier: str,
    suggested: Chapter | None,
    view_offset_ms: int,
    enabled: bool,
) -> None:
    """Pauses playback once per approach to the suggested break point. Dedup
    is enforced via SessionState.paused_at, same pattern as _maybe_notify,
    but re-armed whenever position drops back below the break point (e.g.
    the user resumes from before it, or seeks backward) so a fresh crossing
    pauses again instead of being permanently suppressed for the session."""
    if not enabled or suggested is None:
        return
    if view_offset_ms < suggested.start_offset_ms:
        with SessionLocal() as db:
            row = db.query(SessionStateModel).filter_by(session_key=session_key).one_or_none()
            if row is not None and row.paused_at is not None:
                row.paused_at = None
                db.commit()
        return
    if not player_machine_identifier:
        logger.info("Autopause enabled but session has no controllable player; skipping")
        return

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one_or_none()
        if row is None or row.paused_at is not None:
            return

    try:
        await client.pause(player_machine_identifier)
    except Exception:
        # Don't mark paused_at on failure (e.g. a transient 404 from Plex
        # when the target player briefly isn't reachable as a controllable
        # client) - leave the dedup slot open so the next poll retries,
        # rather than silently giving up on this crossing.
        logger.exception(
            "Failed to auto-pause playback (session=%s player=%s); will retry next poll",
            session_key, player_machine_identifier,
        )
        return

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one_or_none()
        if row is not None:
            row.paused_at = datetime.now(timezone.utc)
            db.commit()


async def poll_once(
    client: PlexClient,
    min_duration_ms: int,
    max_duration_ms: int,
    lead_time_s: int,
    autopause_enabled: bool = False,
) -> None:
    sessions = await client.get_sessions()
    movie_sessions = [s for s in sessions if s.type == "movie"]

    if not movie_sessions:
        await store.set(None)
        return

    # Plex's sessionKey increments monotonically per new playback session, so
    # the highest one is the most recently started. Picking the plain first
    # entry Plex returns is unreliable: a stale session left behind by a
    # client that dropped without a clean disconnect can still show up in
    # /status/sessions (and sort ahead of a genuinely active one), which
    # would otherwise permanently lock the watcher onto a dead session.
    session = max(movie_sessions, key=lambda s: _session_sort_key(s.session_key))
    current = await store.get()

    if current and current.session_key == session.session_key:
        # Same session as last poll: just refresh the playback position,
        # no need to re-fetch chapters/recompute the break point.
        current.view_offset_ms = session.view_offset_ms
        await store.set(current)
        _maybe_notify(
            session.session_key, current.title, current.suggested_break,
            session.view_offset_ms, lead_time_s,
        )
        await _maybe_autopause(
            client, session.session_key, current.player_machine_identifier,
            current.suggested_break, session.view_offset_ms, autopause_enabled,
        )
        return

    chapters, duration_ms = await client.get_chapters(session.rating_key)
    duration_ms = duration_ms or session.duration_ms
    suggested = (
        suggest_break(chapters, duration_ms, min_duration_ms, max_duration_ms)
        if chapters
        else None
    )

    await store.set(
        CurrentSession(
            session_key=session.session_key,
            rating_key=session.rating_key,
            title=session.title,
            thumb=session.thumb,
            duration_ms=duration_ms,
            view_offset_ms=session.view_offset_ms,
            chapters=chapters,
            suggested_break=suggested,
            player_machine_identifier=session.player_machine_identifier,
        )
    )
    _persist_session_state(session, suggested, duration_ms)
    _maybe_notify(
        session.session_key, session.title, suggested, session.view_offset_ms, lead_time_s
    )
    await _maybe_autopause(
        client, session.session_key, session.player_machine_identifier,
        suggested, session.view_offset_ms, autopause_enabled,
    )


async def _poll_cycle() -> None:
    try:
        with SessionLocal() as db:
            s = db.get(Settings, 1)
            base_url, token = s.plex_base_url, s.plex_token
            min_duration_ms = s.break_min_duration_min * 60_000
            max_duration_ms = s.break_max_duration_min * 60_000
            lead_time_s = s.break_lead_time_s
            autopause_enabled = s.autopause_enabled

        if base_url and token:
            client = PlexClient(base_url, token)
            try:
                await poll_once(
                    client, min_duration_ms, max_duration_ms, lead_time_s, autopause_enabled
                )
            finally:
                await client.aclose()
        else:
            await store.set(None)
    except Exception:
        logger.exception("Plex poll failed")


def _to_ws_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :]
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :]
    return base_url


def _is_playing_notification(raw_message: str | bytes) -> bool:
    try:
        data = json.loads(raw_message)
    except (TypeError, ValueError):
        return False
    return data.get("NotificationContainer", {}).get("type") == "playing"


async def _websocket_loop() -> None:
    """Best-effort low-latency trigger: connects to Plex's undocumented
    notification websocket and wakes the poll loop on "playing" events.
    Any failure here just falls back to the plain poll interval."""
    while True:
        try:
            with SessionLocal() as db:
                s = db.get(Settings, 1)
                base_url, token = s.plex_base_url, s.plex_token

            if not (base_url and token):
                await asyncio.sleep(5)
                continue

            ws_url = f"{_to_ws_url(base_url)}/:/websockets/notifications?X-Plex-Token={token}"
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                logger.info("Connected to Plex notification websocket")
                async for message in ws:
                    if _is_playing_notification(message):
                        _poll_now.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Plex websocket unavailable (%s); relying on polling", exc)
            await asyncio.sleep(10)


async def run_forever(poll_interval_s: float) -> None:
    ws_task = asyncio.create_task(_websocket_loop())
    try:
        while True:
            await _poll_cycle()
            _poll_now.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(_poll_now.wait(), timeout=poll_interval_s)
    finally:
        ws_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ws_task
