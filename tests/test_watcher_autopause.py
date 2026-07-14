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
        self.pause_calls: list[str] = []

    async def get_sessions(self) -> list[PlaySession]:
        return [self._session]

    async def get_chapters(self, rating_key: str):
        return self._chapters, self._duration_ms

    async def pause(self, player_machine_identifier: str) -> None:
        self.pause_calls.append(player_machine_identifier)


class MultiSessionClient(FakeClient):
    """Reports multiple concurrent sessions, e.g. a stale session left
    behind by a client that dropped without a clean disconnect, alongside
    the genuinely active one."""

    def __init__(self, sessions: list[PlaySession], chapters: list[Chapter], duration_ms: int):
        super().__init__(sessions[0], chapters, duration_ms)
        self._sessions = sessions

    async def get_sessions(self) -> list[PlaySession]:
        return self._sessions


class FlakyThenOkClient(FakeClient):
    """Fails the first N pause() calls (simulating e.g. a transient 404 from
    Plex when the target player briefly isn't reachable), then succeeds."""

    def __init__(self, session, chapters, duration_ms, fail_times: int):
        super().__init__(session, chapters, duration_ms)
        self._fail_times = fail_times

    async def pause(self, player_machine_identifier: str) -> None:
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("simulated transient failure")
        await super().pause(player_machine_identifier)


def _reset(session_key: str) -> None:
    with SessionLocal() as db:
        db.query(SessionStateModel).filter_by(session_key=session_key).delete()
        db.commit()


@pytest.mark.asyncio
async def test_autopause_fires_once_when_reaching_break_point():
    session_key = "autopause-session-1"
    _reset(session_key)
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]
    # min=2,400,000ms, max=3,600,000ms -> midpoint 3,000,000ms -> suggested break at chapter 5 (offset 3,000,000ms).

    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=3_000_000, thumb="",
        player_machine_identifier="player-abc",
    )
    client = FakeClient(session, chapters, duration_ms)

    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == ["player-abc"]

    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.paused_at is not None

    # Second poll, still past the break point: must not pause again.
    session.view_offset_ms = 3_050_000
    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == ["player-abc"]


@pytest.mark.asyncio
async def test_autopause_rearms_after_resuming_from_before_break_point():
    """Regression test: a user who gets auto-paused, then resumes playback
    from before the break point within the same Plex session (e.g. rewinds,
    or their client resumes a few seconds early), should be paused again on
    the next crossing rather than being permanently locked out for the
    session (see production incident where session position dropped back
    below the break point and re-crossed it, but autopause never re-fired)."""
    session_key = "autopause-session-5"
    _reset(session_key)
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]

    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=3_000_000, thumb="",
        player_machine_identifier="player-abc",
    )
    client = FakeClient(session, chapters, duration_ms)

    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == ["player-abc"]

    # User resumes from a bit before the break point and plays back up to it.
    session.view_offset_ms = 2_950_000
    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == ["player-abc"]
    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.paused_at is None

    # Crossing the break point again should pause again.
    session.view_offset_ms = 3_010_000
    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == ["player-abc", "player-abc"]


@pytest.mark.asyncio
async def test_autopause_does_not_fire_before_break_point():
    session_key = "autopause-session-2"
    _reset(session_key)
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]

    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=500_000, thumb="",
        player_machine_identifier="player-abc",
    )
    client = FakeClient(session, chapters, duration_ms)

    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == []


@pytest.mark.asyncio
async def test_autopause_disabled_does_not_pause():
    session_key = "autopause-session-3"
    _reset(session_key)
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]

    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=3_000_000, thumb="",
        player_machine_identifier="player-abc",
    )
    client = FakeClient(session, chapters, duration_ms)

    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=False,
    )
    assert client.pause_calls == []


@pytest.mark.asyncio
async def test_autopause_skips_uncontrollable_player():
    session_key = "autopause-session-4"
    _reset(session_key)
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]

    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=3_000_000, thumb="",
        player_machine_identifier="",
    )
    client = FakeClient(session, chapters, duration_ms)

    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == []


@pytest.mark.asyncio
async def test_autopause_retries_after_transient_pause_failure():
    """Regression test: a pause() call that raises (e.g. Plex returning a
    transient 404 for the target player) must not burn the dedup slot -
    the next poll, still past the break point, should retry rather than
    silently giving up for the rest of the session."""
    session_key = "autopause-session-6"
    _reset(session_key)
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]

    session = PlaySession(
        session_key=session_key, rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=3_000_000, thumb="",
        player_machine_identifier="player-abc",
    )
    client = FlakyThenOkClient(session, chapters, duration_ms, fail_times=1)

    # First attempt fails; must not be recorded as paused.
    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == []
    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.paused_at is None

    # Still past the break point on the next poll: must retry and succeed.
    session.view_offset_ms = 3_010_000
    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == ["player-abc"]
    with SessionLocal() as db:
        row = db.query(SessionStateModel).filter_by(session_key=session_key).one()
        assert row.paused_at is not None


@pytest.mark.asyncio
async def test_poll_once_prefers_newest_session_over_stale_one():
    """Regression test: Plex can report a stale session left behind by a
    client that dropped without a clean disconnect (e.g. a closed browser
    tab) alongside a genuinely active new session. poll_once must track and
    autopause the newest (highest sessionKey) one, not just sessions[0],
    or it can get permanently stuck targeting a dead session while the
    user's real playback goes untouched (see production incident)."""
    _reset("90019")
    _reset("90020")
    await watcher.store.set(None)

    duration_ms = 6_000_000
    chapters = [Chapter(i, i * 600_000, (i + 1) * 600_000, f"Ch {i + 1}") for i in range(10)]

    # Plex sessionKeys are numeric strings that increment per new playback
    # session, so the higher one ("90020") is the more recent, real session.
    stale = PlaySession(
        session_key="90019", rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=3_000_000, thumb="",
        player_machine_identifier="player-stale",
    )
    fresh = PlaySession(
        session_key="90020", rating_key="rk1", title="Test Movie", type="movie",
        duration_ms=duration_ms, view_offset_ms=3_000_000, thumb="",
        player_machine_identifier="player-fresh",
    )
    client = MultiSessionClient([stale, fresh], chapters, duration_ms)

    await watcher.poll_once(
        client, min_duration_ms=2_400_000, max_duration_ms=3_600_000, lead_time_s=120,
        autopause_enabled=True,
    )
    assert client.pause_calls == ["player-fresh"]
