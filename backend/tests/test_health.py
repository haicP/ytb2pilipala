from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_create_app_importable_from_package():
    from backend.app import create_app

    app = create_app()

    assert isinstance(app, FastAPI)


def test_create_app_can_skip_init_db(monkeypatch):
    from backend.app import main

    called = False

    def fake_init_db() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(main, "init_db", fake_init_db)

    app = main.create_app(init_database=False)

    with TestClient(app):
        pass

    assert called is False


def test_health_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ytb2pilipala"}
