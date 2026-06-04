import zlib
import httpx
import pytest
from tools.simulate_csi import CSISimulatorStateMachine


def calculate_crc32(packet_bytes_without_crc: bytes) -> int:
    return zlib.crc32(packet_bytes_without_crc) & 0xFFFFFFFF


def test_simulator_state_machine_determinism():
    """
    Unit/Integration Test: Asserts that passing a deterministic seed to the CSI simulator
    produces identical coordinate paths.
    """
    sim1 = CSISimulatorStateMachine(seed=42)
    sim2 = CSISimulatorStateMachine(seed=42)

    # Run updates for 50 steps
    for i in range(50):
        sim1.update(sim_t=i * 0.01, dt=0.01)
        sim2.update(sim_t=i * 0.01, dt=0.01)

        # Coordinates must match exactly
        assert sim1.x == sim2.x
        assert sim1.y == sim2.y

        # Generated CSI subcarrier amplitudes must match exactly
        amps1, phases1 = sim1.generate_csi(0.5, 0.5, sim_t=i * 0.01, node_id=1001)
        amps2, phases2 = sim2.generate_csi(0.5, 0.5, sim_t=i * 0.01, node_id=1001)

        assert amps1 == amps2
        assert phases1 == phases2


def test_api_health_endpoint():
    """
    Integration Test: Queries the FastAPI backend health endpoint and asserts fields.
    """
    health_url = "http://127.0.0.1:8000/api/health"

    try:
        response = httpx.get(health_url, timeout=3.0)
        assert response.status_code == 200
        payload = response.json()

        assert "status" in payload
        assert "demo_mode" in payload
        assert "hardware_mode" in payload
        assert "stream_status" in payload
        assert "active_nodes" in payload
        assert "redis_connected" in payload

        # Ensure modes are boolean complements
        assert payload["demo_mode"] == (not payload["hardware_mode"])

    except (httpx.ConnectError, httpx.ConnectTimeout):
        pytest.skip(
            "FastAPI backend is offline. Skipping API health endpoint integration test."
        )


@pytest.mark.asyncio
async def test_websocket_multi_person_payload():
    """
    Integration Test: Asserts that the WebSockets server streams estimated_occupancy,
    tracked_people array, and active_electronic_devices client counts in its payload.
    """
    import websockets
    import json
    import asyncio

    ws_url = "ws://127.0.0.1:8000/ws/live"
    try:
        async with websockets.connect(ws_url) as websocket:
            # Wait for first packet
            msg = await asyncio.wait_for(websocket.recv(), timeout=3.0)
            payload = json.loads(msg)

            assert "timestamp" in payload
            assert "data" in payload

            data = payload["data"]
            assert "estimated_occupancy" in data
            assert "tracked_people" in data
            assert "active_electronic_devices" in data

            # Verify tracked people coordinates structure
            if data["room_present"] and len(data["tracked_people"]) > 0:
                person = data["tracked_people"][0]
                assert "id" in person
                assert "x_meters" in person
                assert "y_meters" in person
                assert "uncertainty" in person

    except (ConnectionRefusedError, OSError, asyncio.TimeoutError):
        pytest.skip(
            f"FastAPI WebSocket server is offline at {ws_url}. Skipping integration test."
        )
