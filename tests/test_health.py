from unittest.mock import patch

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from stemlab.main import app

client = TestClient(app)


def test_liveness_is_independent_of_queue():
    assert client.get("/health/live").json() == {"status": "ok"}


def test_readiness_reports_queue_failure():
    with patch("stemlab.main.Redis.from_url", side_effect=ConnectionError):
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["queue"] == "down"


def test_readiness_with_queue():
    with patch("stemlab.main.Redis.from_url") as redis:
        response = client.get("/health/ready")
        redis.return_value.__enter__.return_value.ping.assert_called_once()
    assert response.status_code == 200


def test_landing_page_is_packaged():
    response = client.get("/")
    assert response.status_code == 200
    assert "StemLab" in response.text
