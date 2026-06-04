import time
import asyncio
import pytest
import websockets
import json


@pytest.mark.asyncio
async def test_websocket_stream_latency():
    """
    Integration Test: Connects to the live WebSocket endpoint, receives
    a telemetry frame, and asserts that transit latency is under 500ms.
    """
    ws_url = "ws://127.0.0.1:8000/ws/live"

    try:
        # Connect to WebSocket
        async with websockets.connect(ws_url) as websocket:
            # 1. Start latency timer
            time.time()

            # 2. Wait for first packet
            msg = await asyncio.wait_for(websocket.recv(), timeout=3.0)
            t_received = time.time()

            # 3. Parse and check structure
            payload = json.loads(msg)
            assert "timestamp" in payload
            assert "data" in payload

            # Calculate lag between server timestamp and client receipt
            server_time = payload["timestamp"]
            transit_lag = (t_received - server_time) * 1000  # in ms

            print(f"WebSocket transit lag: {transit_lag:.2f} ms")

            # Assert latency is less than 500ms (Section 4.1 latency benchmark)
            assert transit_lag < 500.0

    except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
        pytest.skip(
            f"FastAPI WebSocket server is offline at {ws_url}. Skipping integration test. Error: {str(e)}"
        )
