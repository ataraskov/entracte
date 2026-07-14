from __future__ import annotations

from app.plex.client import Chapter


def suggest_break(
    chapters: list[Chapter],
    duration_ms: int,
    target_pct: float = 0.5,
    skip_start_pct: float = 0.15,
    skip_end_pct: float = 0.10,
) -> Chapter | None:
    """Pick the chapter boundary closest to `target_pct` of the runtime,
    preferring chapters outside the head/tail skip window. Falls back to the
    full chapter list if none fall inside that window, and to None if there
    are no chapters at all (the title has no embedded chapter markers)."""
    if not chapters or duration_ms <= 0:
        return None

    lo = duration_ms * skip_start_pct
    hi = duration_ms * (1 - skip_end_pct)
    target = duration_ms * target_pct

    candidates = [c for c in chapters if lo <= c.start_offset_ms <= hi] or chapters
    return min(candidates, key=lambda c: abs(c.start_offset_ms - target))
