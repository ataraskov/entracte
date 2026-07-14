from app.breaks.heuristic import suggest_break
from app.plex.client import Chapter


def chapter(index, start_ms, end_ms, title=""):
    return Chapter(index=index, start_offset_ms=start_ms, end_offset_ms=end_ms, title=title)


def test_no_chapters_returns_none():
    assert suggest_break([], duration_ms=6_000_000) is None


def test_zero_duration_returns_none():
    chapters = [chapter(0, 0, 1000)]
    assert suggest_break(chapters, duration_ms=0) is None


def test_picks_chapter_nearest_midpoint():
    # 10 evenly spaced chapters over a 100-minute (6,000,000ms) movie.
    duration_ms = 6_000_000
    chapters = [chapter(i, i * 600_000, (i + 1) * 600_000) for i in range(10)]
    result = suggest_break(chapters, duration_ms, target_pct=0.5)
    # Midpoint is 3,000,000ms -> chapter 5 starts at exactly 3,000,000ms.
    assert result.index == 5


def test_skips_chapters_in_head_and_tail_window():
    duration_ms = 6_000_000
    # Only two chapters: one right at the very start, one right at the very end.
    chapters = [
        chapter(0, 0, 100_000, title="cold open"),
        chapter(1, 5_950_000, 6_000_000, title="credits"),
    ]
    # skip_start_pct=0.15 -> lo=900,000ms; skip_end_pct=0.10 -> hi=5,400,000ms.
    # Neither chapter falls inside [lo, hi], so it should fall back to the
    # full candidate list and still pick the closest to the target.
    result = suggest_break(
        chapters, duration_ms, target_pct=0.5, skip_start_pct=0.15, skip_end_pct=0.10
    )
    assert result is not None
    assert result.index in (0, 1)


def test_prefers_candidate_inside_skip_window_over_outside():
    duration_ms = 6_000_000
    chapters = [
        chapter(0, 0, 500_000, title="cold open"),  # outside window (before lo=900,000)
        chapter(1, 2_900_000, 3_100_000, title="mid"),  # inside window, near target
        chapter(2, 5_950_000, 6_000_000, title="credits"),  # outside window (after hi)
    ]
    result = suggest_break(
        chapters, duration_ms, target_pct=0.5, skip_start_pct=0.15, skip_end_pct=0.10
    )
    assert result.index == 1


def test_custom_target_pct():
    duration_ms = 4_000_000
    chapters = [chapter(i, i * 1_000_000, (i + 1) * 1_000_000) for i in range(4)]
    # target_pct=0.75 -> target=3,000,000ms -> chapter 3 starts there.
    result = suggest_break(chapters, duration_ms, target_pct=0.75, skip_start_pct=0, skip_end_pct=0)
    assert result.index == 3
