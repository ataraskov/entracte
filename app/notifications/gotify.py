from __future__ import annotations

import httpx


class GotifyNotifier:
    def __init__(self, base_url: str, app_token: str):
        self._base_url = base_url.rstrip("/")
        self._app_token = app_token

    async def send(self, title: str, body: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._base_url}/message",
                params={"token": self._app_token},
                json={"title": title, "message": body, "priority": 5},
            )
            resp.raise_for_status()
