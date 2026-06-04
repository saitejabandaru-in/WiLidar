import httpx
import redis
import pytest
import time
from server.utils.config import settings


def test_system_handles_node_dropout():
    """
    Integration Test: Simulates a node going offline and verifies that
    the API status endpoint degrades gracefully and doesn't raise exceptions.
    """
    status_url = "http://127.0.0.1:8000/api/status"

    # 1. Connect to Redis
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        r.ping()
    except redis.ConnectionError:
        pytest.skip("Redis server offline. Skipping node dropout integration test.")

    # 2. Simulate node 9999 online state
    status_key = "node:9999:status"
    r.hset(
        status_key,
        mapping={
            "ip": "127.0.0.1",
            "queue_fill_percent": 0,
            "rssi": -45,
            "last_seen": time.time(),
        },
    )
    r.expire(status_key, 2)  # set short 2s TTL for test fast expiry

    # Check status endpoint - should return node 9999 online
    try:
        response = httpx.get(status_url, timeout=3.0)
        assert response.status_code == 200
        payload = response.json()
        online_nodes = [node["node_id"] for node in payload["online_nodes"]]
        assert 9999 in online_nodes
    except httpx.ConnectError:
        pytest.skip("API server offline. Skipping node dropout integration test.")

    # 3. Wait for TTL to expire (simulates node dropout)
    time.sleep(2.5)

    # Query status endpoint again - should NOT contain 9999, but must return 200 OK
    response = httpx.get(status_url, timeout=3.0)
    assert response.status_code == 200
    payload = response.json()
    online_nodes = [node["node_id"] for node in payload["online_nodes"]]
    assert 9999 not in online_nodes
