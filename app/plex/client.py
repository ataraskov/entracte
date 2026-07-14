from __future__ import annotations

import dataclasses
import itertools
import logging

import httpx

logger = logging.getLogger(__name__)

# Per the Plex Companion protocol, every /player/* command must carry a
# commandID that increments with each command sent - the PMS rejects
# requests missing it with a bare 400 Bad Request. Module-level so it keeps
# incrementing across PlexClient instances (a new one is created each poll
# cycle) rather than resetting to the same value every time.
_command_id = itertools.count(1)


@dataclasses.dataclass
class Chapter:
    index: int
    start_offset_ms: int
    end_offset_ms: int
    title: str = ""


@dataclasses.dataclass
class PlaySession:
    session_key: str
    rating_key: str
    title: str
    type: str
    duration_ms: int
    view_offset_ms: int
    thumb: str = ""
    player_machine_identifier: str = ""


class PlexClient:
    """Thin async client over the parts of the Plex REST API this app needs:
    the active-sessions list and a title's chapter markers. Plex's HTTP API
    is largely undocumented; field names below match what Plexopedia/
    python-plexapi observe in practice."""

    def __init__(self, base_url: str, token: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-Plex-Token": token, "Accept": "application/json"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_sessions(self) -> list[PlaySession]:
        resp = await self._client.get("/status/sessions")
        resp.raise_for_status()
        data = resp.json()
        items = data.get("MediaContainer", {}).get("Metadata", [])
        return [
            PlaySession(
                session_key=str(item.get("sessionKey", "")),
                rating_key=str(item.get("ratingKey", "")),
                title=item.get("title", ""),
                type=item.get("type", ""),
                duration_ms=int(item.get("duration", 0)),
                view_offset_ms=int(item.get("viewOffset", 0)),
                thumb=item.get("thumb", ""),
                player_machine_identifier=item.get("Player", {}).get("machineIdentifier", ""),
            )
            for item in items
        ]

    async def pause(self, player_machine_identifier: str) -> None:
        """Pauses playback on a client via the PMS's player-control proxy
        (the same mechanism Plex Companion/plexapi use to target a specific
        connected client by machineIdentifier rather than talking to it
        directly)."""
        resp = await self._client.get(
            "/player/playback/pause",
            params={"type": "video", "commandID": next(_command_id)},
            headers={"X-Plex-Target-Client-Identifier": player_machine_identifier},
        )
        logger.info(
            "Pause request to player %s: HTTP %s", player_machine_identifier, resp.status_code
        )
        resp.raise_for_status()

    async def get_chapters(self, rating_key: str) -> tuple[list[Chapter], int]:
        resp = await self._client.get(
            f"/library/metadata/{rating_key}", params={"includeChapters": "1"}
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("MediaContainer", {}).get("Metadata", [])
        if not items:
            return [], 0
        item = items[0]
        duration_ms = int(item.get("duration", 0))
        raw_chapters = item.get("Chapter", [])
        chapters = [
            Chapter(
                index=i,
                start_offset_ms=int(c.get("startTimeOffset", 0)),
                end_offset_ms=int(c.get("endTimeOffset", 0)),
                title=c.get("tag", ""),
            )
            for i, c in enumerate(raw_chapters)
        ]
        return chapters, duration_ms
