import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from shorts.gui.server import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "config.yaml"))


def test_index_served_without_cache(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_config_roundtrip(client, tmp_path):
    cfg = client.get("/api/config").json()
    cfg["clip_selection"]["clips_per_source"] = 7
    assert client.put("/api/config", json=cfg).status_code == 200
    assert client.get("/api/config").json()["clip_selection"]["clips_per_source"] == 7
    assert (tmp_path / "config.yaml").exists()


def test_invalid_config_rejected(client):
    cfg = client.get("/api/config").json()
    cfg["clip_selection"]["clips_per_source"] = "many"
    assert client.put("/api/config", json=cfg).status_code == 422
