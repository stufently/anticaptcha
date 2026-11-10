"""The reported version must follow the chart appVersion (one source of truth)."""
import pathlib

import yaml
from fastapi.testclient import TestClient

import app as app_package
from app.main import app

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CHART_PATH = REPO_ROOT / "chart" / "Chart.yaml"


def test_root_version_matches_chart_app_version():
    assert CHART_PATH.is_file(), f"chart/Chart.yaml must exist at {CHART_PATH}"
    chart = yaml.safe_load(CHART_PATH.read_text(encoding="utf-8"))
    app_version = str(chart["appVersion"])

    # No context manager: the lifespan (init_db) is not needed for a version check
    client = TestClient(app)
    root = client.get("/")
    openapi = client.get("/openapi.json")

    assert root.status_code == 200, f"/ must answer, got {root.status_code}"
    assert root.json()["version"] == app_version, (
        f"/ must report the chart appVersion {app_version}"
    )
    assert openapi.json()["info"]["version"] == app_version, (
        f"openapi must report the chart appVersion {app_version}"
    )
    assert app.version == app_version, (
        f"FastAPI must be built with the chart appVersion {app_version}"
    )
    assert app_package.__version__ == app_version, (
        f"app.__version__ must be the chart appVersion {app_version}"
    )
