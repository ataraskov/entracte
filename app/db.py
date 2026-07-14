import os

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, Session

from app.config import config
from app.models import Settings
from app.notifications.vapid import generate_vapid_keypair

os.makedirs(os.path.dirname(config.db_path) or ".", exist_ok=True)

engine = create_engine(f"sqlite:///{config.db_path}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _run_migrations() -> None:
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{config.db_path}")

    with engine.connect() as conn:
        current_rev = MigrationContext.configure(conn).get_current_revision()

    if current_rev is None and inspect(engine).has_table("settings"):
        # DB predates Alembic (created via Base.metadata.create_all): adopt
        # it at the baseline revision instead of re-running its CREATE
        # TABLEs against tables that already exist.
        command.stamp(alembic_cfg, "0001")

    command.upgrade(alembic_cfg, "head")


def init_db() -> None:
    _run_migrations()
    with SessionLocal() as db:
        settings = db.get(Settings, 1)
        if settings is None:
            settings = Settings(id=1, plex_base_url=config.plex_base_url_default)
            db.add(settings)
            db.commit()
        if not settings.vapid_public_key or not settings.vapid_private_key:
            public_key, private_key = generate_vapid_keypair()
            settings.vapid_public_key = public_key
            settings.vapid_private_key = private_key
            db.commit()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
