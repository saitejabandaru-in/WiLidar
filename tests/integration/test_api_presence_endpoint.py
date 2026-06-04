import httpx
import pytest


def test_api_status_and_configure():
    """
    Integration Test: Queries REST API status endpoints and validates response structures.
    """
    status_url = "http://127.0.0.1:8000/api/status"
    config_url = "http://127.0.0.1:8000/api/configure"

    # 1. Test GET /api/status
    try:
        response = httpx.get(status_url, timeout=3.0)
        assert response.status_code == 200
        payload = response.json()
        assert "status" in payload
        assert "models_loaded" in payload
        assert "sqlite_rooms" in payload
        assert "sqlite_nodes" in payload
        assert "online_nodes" in payload
        assert "server_time" in payload
    except (httpx.ConnectError, httpx.ConnectTimeout):
        pytest.skip(
            f"API server is offline at {status_url}. Skipping integration test."
        )

    # 2. Test POST /api/configure
    config_payload = {
        "rooms": [{"id": 1, "name": "Living Room", "width_m": 6.0, "height_m": 6.0}],
        "nodes": [
            {"id": 1001, "x": 0.5, "y": 0.5, "room_id": 1},
            {"id": 1002, "x": 5.5, "y": 5.5, "room_id": 1},
        ],
    }

    response = httpx.post(config_url, json=config_payload, timeout=3.0)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
