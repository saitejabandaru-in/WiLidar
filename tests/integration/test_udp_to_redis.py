import time
import socket
import struct
import zlib
import redis
import pytest
from server.utils.config import settings


def calculate_crc32(packet_bytes_without_crc: bytes) -> int:
    return zlib.crc32(packet_bytes_without_crc) & 0xFFFFFFFF


def test_udp_stream_to_redis():
    """
    Integration Test: Fires 100 UDP CSI packets to port 5005 and asserts
    that Redis stream collects them successfully within tolerance.
    """
    node_id = 9999  # unique node id for test
    stream_key = f"csi:node:{node_id}:raw"

    # Check if Redis is running, otherwise skip this integration test
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        r.ping()
        # Clean stream before starting
        r.delete(stream_key)
    except redis.ConnectionError:
        pytest.skip("Redis server is offline. Skipping UDP to Redis integration test.")

    # Check if the API server (and background UDP collector) is running
    import httpx

    try:
        httpx.get("http://127.0.0.1:8000/api/status", timeout=2.0)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        pytest.skip(
            "API server (UDP collector) is offline. Skipping UDP to Redis integration test."
        )

    # 1. Setup UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = ("127.0.0.1", settings.UDP_PORT)

    # 2. Fire 100 mock packets
    print(f"Firing 100 UDP packets for Node {node_id} to 127.0.0.1:{settings.UDP_PORT}")

    pre_crc_format = "<IIqbbBB64b64b"
    amps = [60] * 64
    phases = [10] * 64

    for seq in range(100):
        packed = struct.pack(
            pre_crc_format,
            node_id,
            seq,
            int(time.time() * 1_000_000),
            -50,  # rssi
            -95,  # noise
            6,  # channel
            1,  # bandwidth
            *amps,
            *phases,
        )
        crc = calculate_crc32(packed)
        packet = packed + struct.pack("<I", crc)

        sock.sendto(packet, dest)
        time.sleep(0.005)  # 5ms interval

    sock.close()

    # 3. Wait 1 second for asyncio receiver processing
    time.sleep(1.0)

    # 4. Check Redis stream length
    length = r.xlen(stream_key)
    print(f"Redis stream {stream_key} contains {length} entries.")

    # Clean up
    r.delete(stream_key)

    # Verify we got between 95 and 100 packets (allowing slight network packet drop)
    assert 95 <= length <= 100
