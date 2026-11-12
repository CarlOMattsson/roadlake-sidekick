"""The backend serves no product SPA: the desktop same-origin fallback is retired."""

import pytest
from fastapi.testclient import TestClient

from sidekick.api.app import create_app
from sidekick.shared.config import Settings

# Paths the retired desktop fallback answered with index.html or a static asset, plus
# unknown API and health paths that must never be captured by a catch-all route.
FORMER_SPA_PATHS = (
    "/",
    "/index.html",
    "/assets/app.js",
    "/projects",
    "/projects/example",
    "/settings/desktop",
    "/desktop/onboarding",
    "/api/v1/not-a-route",
    "/health/not-a-route",
    "/ready",
)


@pytest.mark.parametrize("path", FORMER_SPA_PATHS)
def test_web_mode_does_not_install_spa_fallback(path: str) -> None:
    app = create_app(Settings(_env_file=None, environment="test"))
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<html" not in response.text.lower()
