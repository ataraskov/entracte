import httpx
import pytest

from app.plex.client import PlexClient


def make_client(handler) -> PlexClient:
    client = PlexClient("http://plex.local:32400", "tok")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://plex.local:32400",
    )
    return client


@pytest.mark.asyncio
async def test_get_sessions_parses_movie_session():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/status/sessions"
        return httpx.Response(
            200,
            json={
                "MediaContainer": {
                    "Metadata": [
                        {
                            "sessionKey": "7",
                            "ratingKey": "123",
                            "title": "Arrival",
                            "type": "movie",
                            "duration": 6600000,
                            "viewOffset": 120000,
                            "thumb": "/library/metadata/123/thumb",
                        }
                    ]
                }
            },
        )

    client = make_client(handler)
    sessions = await client.get_sessions()
    assert len(sessions) == 1
    s = sessions[0]
    assert s.session_key == "7"
    assert s.rating_key == "123"
    assert s.title == "Arrival"
    assert s.type == "movie"
    assert s.duration_ms == 6600000
    assert s.view_offset_ms == 120000


@pytest.mark.asyncio
async def test_get_sessions_parses_player_machine_identifier():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "MediaContainer": {
                    "Metadata": [
                        {
                            "sessionKey": "7",
                            "ratingKey": "123",
                            "title": "Arrival",
                            "type": "movie",
                            "duration": 6600000,
                            "viewOffset": 120000,
                            "Player": {"machineIdentifier": "player-xyz"},
                        }
                    ]
                }
            },
        )

    client = make_client(handler)
    sessions = await client.get_sessions()
    assert sessions[0].player_machine_identifier == "player-xyz"


@pytest.mark.asyncio
async def test_pause_sends_target_client_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/player/playback/pause"
        assert request.url.params["type"] == "video"
        assert request.headers["X-Plex-Target-Client-Identifier"] == "player-xyz"
        # Plex's PMS rejects /player/* commands missing commandID with a
        # bare 400 Bad Request (confirmed against a real server).
        assert "commandID" in request.url.params
        return httpx.Response(200)

    client = make_client(handler)
    await client.pause("player-xyz")


@pytest.mark.asyncio
async def test_pause_increments_command_id_across_calls():
    seen_command_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_command_ids.append(request.url.params["commandID"])
        return httpx.Response(200)

    client = make_client(handler)
    await client.pause("player-xyz")
    await client.pause("player-xyz")
    assert len(set(seen_command_ids)) == 2


@pytest.mark.asyncio
async def test_get_sessions_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"MediaContainer": {}})

    client = make_client(handler)
    sessions = await client.get_sessions()
    assert sessions == []


@pytest.mark.asyncio
async def test_get_chapters_parses_chapter_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/library/metadata/123"
        assert request.url.params["includeChapters"] == "1"
        return httpx.Response(
            200,
            json={
                "MediaContainer": {
                    "Metadata": [
                        {
                            "duration": 6600000,
                            "Chapter": [
                                {"startTimeOffset": 0, "endTimeOffset": 1000000, "tag": "Ch 1"},
                                {"startTimeOffset": 1000000, "endTimeOffset": 3200000, "tag": "Ch 2"},
                            ],
                        }
                    ]
                }
            },
        )

    client = make_client(handler)
    chapters, duration_ms = await client.get_chapters("123")
    assert duration_ms == 6600000
    assert [c.title for c in chapters] == ["Ch 1", "Ch 2"]
    assert chapters[1].start_offset_ms == 1000000


@pytest.mark.asyncio
async def test_get_chapters_no_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"MediaContainer": {}})

    client = make_client(handler)
    chapters, duration_ms = await client.get_chapters("999")
    assert chapters == []
    assert duration_ms == 0
