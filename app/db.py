import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import config
from app.models import Base, Settings
from app.notifications.vapid import generate_vapid_keypair

os.makedirs(os.path.dirname(config.db_path) or ".", exist_ok=True)

engine = create_engine(f"sqlite:///{config.db_path}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
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
