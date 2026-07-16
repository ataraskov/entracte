from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
from datetime import datetime, timezone

import websockets

from app.breaks.heuristic import suggest_break, suggest_breaks
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
    upcoming_breaks: list[Chapter] = dataclasses.field(default_factory=list)
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


def _advance_segment(
    session: PlaySession,
    chapters: list[Chapter],
    duration_ms: int,
    min_duration_ms: int,
    max_duration_ms: int,
    resume_gap_threshold_s: int,
) -> tuple[Chapter | None, int]:
    """Tracks the current watching segment's anchor (segment_start_ms) and
    recomputes the next suggested break relative to it. The anchor advances
    in two cases: (1) playback has already reached the break suggested on a
    prior poll, so the *next* poll's window starts there - this is what
    produces multiple spaced-out suggestions across a long title instead of
    just one; (2) a long real-world gap was detected since view_offset last
    actually moved (a real pause, or the session dropping out of Plex's
    session list and reappearing) - the anchor resets to wherever playback
    resumed, so the break window is computed from the new watching session
    rather than the original video start. Runs on every poll (not just for
    new sessions) so both cases are caught as soon as they happen.

    Case (1) only takes effect for the *next* poll, not this one: this
    poll's returned suggestion is always computed from the anchor as it
    stood at the start of the poll, so the poll that first crosses into a
    break's window still reports that break to _maybe_notify/_maybe_autopause
    below, rather than one already advanced past it."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = (
            db.query(SessionStateModel)
            .filter_by(session_key=session.session_key)
            .one_or_none()
        )
        if row is None:
            row = SessionStateModel(session_key=session.session_key)
            db.add(row)
            row.segment_start_ms = session.view_offset_ms
        else:
            last_progress_at = row.last_progress_at
            if last_progress_at is not None and last_progress_at.tzinfo is None:
                # SQLite round-trips DateTime columns as naive (it has no
                # real timezone support), even though we always set them
                # from an aware datetime.now(timezone.utc) - reattach UTC so
                # this doesn't blow up subtracting from an aware `now`.
                last_progress_at = last_progress_at.replace(tzinfo=timezone.utc)
            gap_s = (now - last_progress_at).total_seconds() if last_progress_at else 0
            if gap_s >= resume_gap_threshold_s:
                # Long real-world stop: re-anchor at wherever playback currently
                # is. Deliberately not gated on the offset having already moved
                # since the *previous* poll - Plex resumes exactly where it
                # paused, so the first poll(s) after pressing play still report
                # the same frozen offset as during the pause. Gating on "moved"
                # would make this a no-op there and defer the real re-anchor to
                # the next poll cycle, which is exactly when a user checking
                # the dashboard right after resuming would see a stale
                # suggestion. Re-anchoring here to the still-frozen offset is
                # a harmless no-op while paused, and becomes correct the
                # instant the offset ticks forward.
                row.segment_start_ms = session.view_offset_ms

        if session.view_offset_ms != row.last_seen_view_offset_ms:
            row.last_progress_at = now
        row.last_seen_view_offset_ms = session.view_offset_ms

        suggested = suggest_break(
            chapters, duration_ms, min_duration_ms, max_duration_ms, anchor_ms=row.segment_start_ms
        )
        # Anchor as of this poll's suggestion - returned as-is below, since
        # the case-1 advance right after this can move row.segment_start_ms
        # on to the *next* segment already (see docstring above), which
        # would desync suggest_breaks() from the suggested break it's
        # supposed to lead off with.
        segment_start_ms = row.segment_start_ms

        # Now that this poll's suggestion is settled, advance the anchor for
        # the *next* poll once playback has moved past the suggested
        # chapter's end - not just its start. Using the chapter's end (not
        # start) as the trigger gives a buffer so a brief rewind-and-reapproach
        # right around the break point (e.g. autopause fires, then the user
        # scrubs back a few seconds and re-crosses it) doesn't permanently
        # commit to the next segment out from under _maybe_autopause's own
        # re-arm logic before the user has actually moved on.
        if suggested is not None and session.view_offset_ms >= suggested.end_offset_ms:
            row.segment_start_ms = suggested.start_offset_ms

        row.rating_key = session.rating_key
        row.title = session.title
        row.duration_ms = duration_ms
        row.suggested_break_offset_ms = suggested.start_offset_ms if suggested else None
        db.commit()
        return suggested, segment_start_ms


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _maybe_notify(
    session_key: str, title: str, suggested: Chapter | None, view_offset_ms: int, lead_time_s: int
) -> None:
    """Fires the break notification once per suggested break offset, when
    playback crosses into the [suggested_offset - lead_time, suggested_offset]
    window. Dedup is enforced via SessionState.notified_for_offset_ms (rather
    than a plain notified-once flag) so that once the segment anchor advances
    and a new, later break is suggested, notification re-arms for it instead
    of being permanently suppressed by the earlier break's notification."""
    if suggested is None:
        return

    threshold_ms = suggested.start_offset_ms - lead_time_s * 1000
    if not (threshold_ms <= view_offset_ms <= suggested.start_offset_ms):
        return

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one_or_none()
        if row is None or row.notified_for_offset_ms == suggested.start_offset_ms:
            return
        row.notified_at = datetime.now(timezone.utc)
        row.notified_for_offset_ms = suggested.start_offset_ms
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
    resume_gap_threshold_s: int = 900,
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
        # Same session as last poll: chapters/duration don't change mid-title,
        # no need to re-fetch them from Plex.
        chapters, duration_ms = current.chapters, current.duration_ms
    else:
        chapters, duration_ms = await client.get_chapters(session.rating_key)
        duration_ms = duration_ms or session.duration_ms

    if chapters:
        suggested, segment_start_ms = _advance_segment(
            session, chapters, duration_ms, min_duration_ms, max_duration_ms,
            resume_gap_threshold_s,
        )
        # Recomputed every poll (not cached alongside chapters/duration_ms
        # above) since the segment anchor can move without the session_key
        # changing - a long-pause resume or crossing into the next segment
        # both re-anchor mid-session, and the timeline's secondary marks
        # need to track that or they'd keep showing the break sequence for
        # a fresh video-start watch forever.
        upcoming_breaks = suggest_breaks(
            chapters, duration_ms, min_duration_ms, max_duration_ms, anchor_ms=segment_start_ms
        )
    else:
        suggested = None
        upcoming_breaks = []

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
            upcoming_breaks=upcoming_breaks,
            player_machine_identifier=session.player_machine_identifier,
        )
    )
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
            resume_gap_threshold_s = s.break_resume_gap_min * 60
            autopause_enabled = s.autopause_enabled

        if base_url and token:
            client = PlexClient(base_url, token)
            try:
                await poll_once(
                    client, min_duration_ms, max_duration_ms, lead_time_s,
                    resume_gap_threshold_s, autopause_enabled,
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
