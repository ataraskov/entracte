from __future__ import annotations

from app.plex.client import Chapter


def suggest_break(
    chapters: list[Chapter],
    duration_ms: int,
    min_duration_ms: int = 20 * 60_000,
    max_duration_ms: int = 60 * 60_000,
) -> Chapter | None:
    """Pick the chapter boundary closest to the midpoint of
    [min_duration_ms, max_duration_ms] of watching time, preferring chapters
    that fall inside that window. Falls back to the full chapter list if none
    fall inside it, and to None if there are no chapters at all (the title
    has no embedded chapter markers)."""
    if not chapters or duration_ms <= 0:
        return None

    target = (min_duration_ms + max_duration_ms) / 2

    candidates = [
        c for c in chapters if min_duration_ms <= c.start_offset_ms <= max_duration_ms
    ] or chapters
    return min(candidates, key=lambda c: abs(c.start_offset_ms - target))
