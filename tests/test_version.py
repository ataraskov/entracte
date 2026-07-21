from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import dashboard
from app.version import __version__


def test_footer_shows_version():
    app = FastAPI()
    app.include_router(dashboard.router)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert f"Entracte v{__version__}" in response.text
