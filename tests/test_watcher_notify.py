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
        duration_ms=duration_ms, view_offset_ms=2_950_000, thumb="",
    )
    client = FakeClient(session, chapters, duration_ms)

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
