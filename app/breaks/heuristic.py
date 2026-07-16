from __future__ import annotations

from app.plex.client import Chapter


def suggest_break(
    chapters: list[Chapter],
    duration_ms: int,
    min_duration_ms: int = 20 * 60_000,
    max_duration_ms: int = 60 * 60_000,
    anchor_ms: int = 0,
) -> Chapter | None:
    """Pick the chapter boundary closest to the midpoint of
    [anchor_ms + min_duration_ms, anchor_ms + max_duration_ms] of watching
    time since anchor_ms (the start of the current watching segment - video
    start for a fresh session, or a later offset once a break has been taken
    or a long real-world pause pushed the segment forward - see
    watcher.py::_advance_segment), preferring chapters that fall inside that
    window. Falls back to the closest chapter after anchor_ms if none fall
    inside the window, and to None if there are no chapters at all, or none
    left after anchor_ms (nothing more to suggest before the title ends)."""
    if not chapters or duration_ms <= 0:
        return None

    after_anchor = [c for c in chapters if c.start_offset_ms > anchor_ms]
    if not after_anchor:
        return None

    lo, hi = anchor_ms + min_duration_ms, anchor_ms + max_duration_ms
    target = (lo + hi) / 2

    candidates = [c for c in after_anchor if lo <= c.start_offset_ms <= hi] or after_anchor
    return min(candidates, key=lambda c: abs(c.start_offset_ms - target))


def suggest_breaks(
    chapters: list[Chapter],
    duration_ms: int,
    min_duration_ms: int = 20 * 60_000,
    max_duration_ms: int = 60 * 60_000,
    anchor_ms: int = 0,
) -> list[Chapter]:
    """Full sequence of break suggestions from anchor_ms to the end of the
    runtime, each one anchored at the previous pick's offset. Used for the
    dashboard timeline display - the watcher recomputes this every poll from
    the session's live segment anchor (see watcher.py::_advance_segment), so
    the displayed marks stay in sync with the actual next suggestion after a
    segment advance or a long-pause resume, instead of always showing the
    sequence for a fresh video-start watch."""
    breaks: list[Chapter] = []
    while True:
        pick = suggest_break(chapters, duration_ms, min_duration_ms, max_duration_ms, anchor_ms)
        if pick is None:
            return breaks
        breaks.append(pick)
        anchor_ms = pick.start_offset_ms
