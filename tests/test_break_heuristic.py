from app.breaks.heuristic import suggest_break, suggest_breaks
from app.plex.client import Chapter


def chapter(index, start_ms, end_ms, title=""):
    return Chapter(index=index, start_offset_ms=start_ms, end_offset_ms=end_ms, title=title)


def test_no_chapters_returns_none():
    assert suggest_break([], duration_ms=6_000_000) is None


def test_zero_duration_returns_none():
    chapters = [chapter(0, 0, 1000)]
    assert suggest_break(chapters, duration_ms=0) is None


def test_picks_chapter_nearest_midpoint_of_min_max():
    # 10 evenly spaced chapters over a 100-minute (6,000,000ms) movie.
    duration_ms = 6_000_000
    chapters = [chapter(i, i * 600_000, (i + 1) * 600_000) for i in range(10)]
    # min=40min, max=60min -> midpoint 50min=3,000,000ms -> chapter 5 starts exactly there.
    result = suggest_break(
        chapters, duration_ms, min_duration_ms=2_400_000, max_duration_ms=3_600_000
    )
    assert result.index == 5


def test_falls_back_to_full_list_when_no_candidate_in_window():
    duration_ms = 6_000_000
    # Only two chapters: one right at the very start, one right at the very end.
    chapters = [
        chapter(0, 0, 100_000, title="cold open"),
        chapter(1, 5_950_000, 6_000_000, title="credits"),
    ]
    # Window is [900,000, 5,400,000]ms; neither chapter falls inside it, so it
    # should fall back to the full candidate list and pick the closest to the
    # window's midpoint.
    result = suggest_break(
        chapters, duration_ms, min_duration_ms=900_000, max_duration_ms=5_400_000
    )
    assert result is not None
    assert result.index in (0, 1)


def test_prefers_candidate_inside_window_over_outside():
    duration_ms = 6_000_000
    chapters = [
        chapter(0, 0, 500_000, title="cold open"),  # outside window (before lo=900,000)
        chapter(1, 2_900_000, 3_100_000, title="mid"),  # inside window, near target
        chapter(2, 5_950_000, 6_000_000, title="credits"),  # outside window (after hi)
    ]
    result = suggest_break(
        chapters, duration_ms, min_duration_ms=900_000, max_duration_ms=5_400_000
    )
    assert result.index == 1


def test_custom_min_max_window():
    duration_ms = 4_000_000
    chapters = [chapter(i, i * 1_000_000, (i + 1) * 1_000_000) for i in range(4)]
    # min=max=3,000,000ms -> target=3,000,000ms -> chapter 3 starts there.
    result = suggest_break(
        chapters, duration_ms, min_duration_ms=3_000_000, max_duration_ms=3_000_000
    )
    assert result.index == 3


def test_anchor_shifts_window_forward():
    # Same 10-chapter/100-minute layout as above, but anchored at chapter 5's
    # start (3,000,000ms) instead of video start: window becomes
    # [5,400,000, 6,600,000]ms -> only chapter 9 (starts at 5,400,000) falls
    # in range.
    duration_ms = 6_000_000
    chapters = [chapter(i, i * 600_000, (i + 1) * 600_000) for i in range(10)]
    result = suggest_break(
        chapters, duration_ms,
        min_duration_ms=2_400_000, max_duration_ms=3_600_000, anchor_ms=3_000_000,
    )
    assert result.index == 9


def test_anchor_excludes_chapter_starting_exactly_at_anchor():
    duration_ms = 3_000_000
    chapters = [chapter(0, 1_000_000, 2_000_000), chapter(1, 2_000_000, 3_000_000)]
    result = suggest_break(
        chapters, duration_ms,
        min_duration_ms=0, max_duration_ms=2_000_000, anchor_ms=1_000_000,
    )
    assert result.index == 1


def test_duration_under_min_threshold_returns_none():
    # A 15-minute title with a 20-minute min session threshold is too short
    # to warrant a break at all, regardless of chapter layout.
    duration_ms = 900_000
    chapters = [chapter(0, 0, 450_000), chapter(1, 450_000, 900_000)]
    result = suggest_break(chapters, duration_ms, min_duration_ms=1_200_000, max_duration_ms=3_600_000)
    assert result is None


def test_anchor_past_all_chapters_returns_none():
    duration_ms = 6_000_000
    chapters = [chapter(i, i * 600_000, (i + 1) * 600_000) for i in range(10)]
    result = suggest_break(
        chapters, duration_ms,
        min_duration_ms=2_400_000, max_duration_ms=3_600_000, anchor_ms=5_999_000,
    )
    assert result is None


def test_suggest_breaks_empty_when_no_chapters():
    assert suggest_breaks([], duration_ms=6_000_000) == []


def test_suggest_breaks_single_break_for_short_content():
    duration_ms = 1_200_000
    chapters = [chapter(0, 0, 600_000), chapter(1, 600_000, 1_200_000)]
    result = suggest_breaks(chapters, duration_ms, min_duration_ms=600_000, max_duration_ms=1_200_000)
    assert [c.index for c in result] == [1]


def test_suggest_breaks_empty_when_duration_under_min_threshold():
    duration_ms = 900_000
    chapters = [chapter(0, 0, 450_000), chapter(1, 450_000, 900_000)]
    result = suggest_breaks(chapters, duration_ms, min_duration_ms=1_200_000, max_duration_ms=3_600_000)
    assert result == []


def test_suggest_breaks_returns_sequence_across_long_runtime():
    # Same 10-chapter/100-minute layout: with a 20-40 min window, the
    # sequence should keep advancing until nothing is left after the anchor,
    # producing multiple spaced-out breaks instead of just one.
    duration_ms = 6_000_000
    chapters = [chapter(i, i * 600_000, (i + 1) * 600_000) for i in range(10)]
    result = suggest_breaks(
        chapters, duration_ms, min_duration_ms=1_200_000, max_duration_ms=2_400_000
    )
    assert [c.index for c in result] == [3, 6, 9]
