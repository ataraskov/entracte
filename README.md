# Entracte

Watches what's currently playing on your Plex server, looks at the movie's
chapter markers, suggests a good moment to take a break, and sends you a
notification a bit before that point — via Web Push, Gotify, and/or Telegram.

## How it works

- A background task polls Plex's `/status/sessions` (with a low-latency
  assist from Plex's undocumented notification websocket, when reachable) to
  see what's currently playing.
- When a movie session starts, it fetches the title's embedded chapter
  markers and picks the chapter boundary closest to a configurable point in
  the runtime (default: the midpoint), skipping a configurable head/tail
  window so it won't suggest a break during the cold open or credits.
- A bit before that point (configurable lead time), it sends a notification
  through whichever channels you've enabled.

**Known limitation**: many movie files have no embedded chapter markers at
all (this is different from Plex's auto-generated intro/credits markers).
When a title has none, the dashboard says so and no notification is
scheduled for that session — there's no scene-detection fallback.

## Running it

### Docker (recommended)

```sh
docker compose up -d --build
```

The app listens on `http://localhost:8000`. SQLite data persists in `./data`.

### Locally

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Copy `.env.example` to `.env` to override any defaults (DB path, host/port,
poll interval) — see that file for details. None of this is required to get
started; the app also works with no `.env` at all.

## First-time setup

Open `http://localhost:8000/settings` and fill in:

**Plex connection**
- **Server URL** — e.g. `http://plex.local:32400`.
- **Access token** — see
  [Plex's guide to finding your account token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

**Break heuristic** (sane defaults are pre-filled) — target position in the
runtime, head/tail skip fractions, and how many seconds before the break to
notify.

**Notification channels** — enable any combination:
- **Web Push**: click "Enable push in this browser" on the settings page and
  accept the browser's permission prompt. No external service needed; keys
  are generated automatically on first run.
- **Gotify**: enter your Gotify server URL and an
  [application token](https://gotify.net/docs/pushmsg) created in your
  Gotify instance.
- **Telegram**: create a bot with
  [@BotFather](https://core.telegram.org/bots#6-botfather) to get a bot
  token, then message your bot (or add it to a group) and use
  `https://api.telegram.org/bot<token>/getUpdates` to find the chat ID.

## Development

```sh
pip install -e ".[dev]"
pytest
```

Tests cover the break-suggestion heuristic, the Plex client's response
parsing, notification payload formatting, and the notify-once dedup logic —
all against fabricated data/mocked HTTP, no live Plex server required.

Verifying the full flow end-to-end (dashboard shows the right chapter for a
real title, notifications actually arrive) requires a real Plex Media Server
on the network with a chaptered movie, plus real Gotify/Telegram credentials
and a browser to accept the push permission prompt.
