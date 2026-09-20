from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend import mount_frontend


def test_frontend_mount_is_optional(tmp_path):
    app = FastAPI()
    assert mount_frontend(app, directory=tmp_path / "missing") is False


def test_frontend_mount_serves_spa_without_masking_api_404(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        "<html><body>zero-nvr web</body></html>",
        encoding="utf-8",
    )
    (tmp_path / "assets" / "app.js").write_text(
        "console.log('zero-nvr')",
        encoding="utf-8",
    )

    app = FastAPI()

    @app.get("/api/v1/ping")
    def ping():
        return {"status": "ok"}

    assert mount_frontend(app, directory=tmp_path) is True

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert "zero-nvr web" in client.get("/cameras").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/v1/ping").json() == {"status": "ok"}

        missing_api = client.get("/api/v1/missing")
        assert missing_api.status_code == 404
        assert "zero-nvr web" not in missing_api.text
