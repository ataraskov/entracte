from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENTRACTE_", env_file=".env")

    db_path: str = "./data/entracte.db"
    host: str = "0.0.0.0"
    port: int = 8000

    # Optional first-run default so the /settings form isn't empty; the Plex
    # token itself is always entered via the UI since it's a secret.
    plex_base_url_default: str = "http://localhost:32400"

    # How often the polling fallback checks Plex when the websocket is down.
    poll_interval_s: float = 7.0


config = AppConfig()
