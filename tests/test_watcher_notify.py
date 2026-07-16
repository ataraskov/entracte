from datetime import timedelta

import pytest

from app.db import SessionLocal
from app.models import SessionState as SessionStateModel
from app.plex import watcher
from app.plex.client import Chapter, PlaySession


class FakeClient:
    def __init__(self, session: PlaySession, chapters: list[Chapter], duration_ms: int):
        self._session = session
        self._chapters = chapters
        self._duration_ms = duration_ms

    async def get_sessions(self) -> list[PlaySession]:
        return [self._session]

    async def get_chapters(self, rating_key: str):
        return self._chapters, self._duration_ms


async def _drain_background_tasks() -> None:
    for task in list(watcher._background_tasks):
        await task


@pytest.mark.asyncio
async def test_notify_fires_once_when_entering_window_then_dedups(monkeypatch):
    calls = []

    async def fake_notify(title: str, body: str) -> None:
        calls.append((title, body))

    monkeypatch.setattr(watcher.dispatcher, "notify", fake_notify)

    session_key = "test-session-1"
    with SessionLocal() as db:
        db.query(SessionStateModel).filter_by(session_key=session_key).delete()
        db.commit()
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]
    # min=2,400,000ms, max=3,600,000ms -> midpoint 3,000,000ms -> chapter 5 (index 5) starts exactly there.
    # lead_time=120s -> notify window is [2,880,000, 3,000,000]ms.

    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=0, thumb="",
    )
    client = FakeClient(session, chapters, duration_ms)

    # The segment anchor is initialized to view_offset_ms the first time a
    # session is seen (so a Plex mid-video "resume" anchors from there
    # instead of from absolute video-start). Poll once at offset 0 first so
    # the anchor lands at video-start, matching this test's window math.
    await watcher.poll_once(client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120)

    session.view_offset_ms = 2_950_000
    await watcher.poll_once(client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120)
    await _drain_background_tasks()
    assert len(calls) == 1
    assert calls[0][0] == "Time for a break"

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.notified_at is not None

    # Second poll, same session, still inside the window: must not double-notify.
    session.view_offset_ms = 2_980_000
    await watcher.poll_once(client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120)
    await _drain_background_tasks()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_notify_does_not_fire_outside_window(monkeypatch):
    calls = []

    async def fake_notify(title: str, body: str) -> None:
        calls.append((title, body))

    monkeypatch.setattr(watcher.dispatcher, "notify", fake_notify)

    session_key = "test-session-2"
    with SessionLocal() as db:
        db.query(SessionStateModel).filter_by(session_key=session_key).delete()
        db.commit()
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]

    # Far from the suggested break point (midpoint 3,000,000ms; window starts at 2,880,000ms).
    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=500_000, thumb="",
    )
    client = FakeClient(session, chapters, duration_ms)

    await watcher.poll_once(client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120)
    await _drain_background_tasks()
    assert calls == []


@pytest.mark.asyncio
async def test_notify_fires_again_for_next_break_after_first_is_passed(monkeypatch):
    """Regression test for long titles: once playback carries past the first
    suggested break, the segment anchor should advance and a second,
    further-out break should be suggested and notified for - not just the
    one break for the whole runtime."""
    calls = []

    async def fake_notify(title: str, body: str) -> None:
        calls.append((title, body))

    monkeypatch.setattr(watcher.dispatcher, "notify", fake_notify)

    session_key = "test-session-3"
    with SessionLocal() as db:
        db.query(SessionStateModel).filter_by(session_key=session_key).delete()
        db.commit()
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]
    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=0, thumb="",
    )
    client = FakeClient(session, chapters, duration_ms)

    # Anchor at video start, then cross into the first break's window
    # (chapter 5 @ 3,000,000ms) and notify.
    await watcher.poll_once(client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120)
    session.view_offset_ms = 2_950_000
    await watcher.poll_once(client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120)
    await _drain_background_tasks()
    assert len(calls) == 1

    # Keep watching past chapter 5's own end (3,600,000ms) - the anchor only
    # advances once playback has moved past the *whole* suggested chapter,
    # not merely its start (see watcher.py::_advance_segment), so this poll
    # is what actually commits to the next segment.
    session.view_offset_ms = 3_700_000
    await watcher.poll_once(client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120)
    await _drain_background_tasks()
    assert len(calls) == 1

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.segment_start_ms == 3_000_000

    # The next window is now [5,400,000, 6,600,000]ms -> only chapter 9
    # qualifies. Enter its notify window.
    session.view_offset_ms = 5_350_000
    await watcher.poll_once(client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120)
    await _drain_background_tasks()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_resume_after_long_pause_reanchors_segment():
    """Regression test: after a long real-world pause (or the Plex session
    dropping out of /status/sessions and reappearing), the break window
    should be recomputed relative to the resume point, not the original
    video start."""
    session_key = "test-session-resume-1"
    with SessionLocal() as db:
        db.query(SessionStateModel).filter_by(session_key=session_key).delete()
        db.commit()
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]
    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=0, thumb="",
    )
    client = FakeClient(session, chapters, duration_ms)

    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        resume_gap_threshold_s=60,
    )
    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.segment_start_ms == 0
        assert row.suggested_break_offset_ms == 3_000_000  # chapter 5

        # Simulate a long real-world pause by backdating when playback last
        # actually progressed, well past the 60s resume_gap_threshold_s used
        # here (instead of really sleeping in the test).
        row.last_progress_at = row.last_progress_at - timedelta(minutes=30)
        db.commit()

    # Resume from a point well past the original anchor.
    session.view_offset_ms = 4_500_000
    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        resume_gap_threshold_s=60,
    )

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.segment_start_ms == 4_500_000
        # New window [6,900,000, 8,100,000]ms is past the 6,000,000ms runtime,
        # so it falls back to the closest chapter after the anchor: chapter 9.
        assert row.suggested_break_offset_ms == 5_400_000


@pytest.mark.asyncio
async def test_resume_reanchors_before_view_offset_ticks_forward():
    """Regression test: Plex resumes playback at the exact position it was
    paused at, so the first poll(s) right after a user hits play still report
    the same view_offset_ms as every poll during the pause - the segment
    should still re-anchor on that poll (not wait for a later poll where the
    offset has visibly advanced), since a user checking the dashboard right
    after resuming would otherwise see a stale suggestion."""
    session_key = "test-session-resume-2"
    with SessionLocal() as db:
        db.query(SessionStateModel).filter_by(session_key=session_key).delete()
        db.commit()
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]
    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=0, thumb="",
    )
    client = FakeClient(session, chapters, duration_ms)

    # Watch continuously from the start up to 2,280,000ms (anchor stays 0 the
    # whole time - chapter 4, the original suggestion, hasn't been reached
    # yet), then the user pauses right there.
    for offset in [0, 600_000, 1_200_000, 1_800_000, 2_280_000]:
        session.view_offset_ms = offset
        await watcher.poll_once(
            client, min_duration_ms=1_200_000, max_duration_ms=3_600_000, lead_time_s=120,
            resume_gap_threshold_s=60,
        )

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.segment_start_ms == 0
        assert row.suggested_break_offset_ms == 2_400_000  # chapter 4

        row.last_progress_at = row.last_progress_at - timedelta(minutes=30)
        db.commit()

    # Poll again with the SAME view_offset_ms (Plex hasn't reported any
    # forward movement yet - the player only just unpaused).
    await watcher.poll_once(
        client, min_duration_ms=1_200_000, max_duration_ms=3_600_000, lead_time_s=120,
        resume_gap_threshold_s=60,
    )

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        # Anchor re-anchors to the (still frozen) current position, and the
        # suggestion already reflects the new window [3,480,000, 5,880,000]ms
        # -> chapter 8, without waiting for view_offset_ms to change first.
        assert row.segment_start_ms == 2_280_000
        assert row.suggested_break_offset_ms == 4_800_000  # chapter 8
