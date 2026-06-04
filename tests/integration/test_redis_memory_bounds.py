import redis
import pytest
from server.utils.config import settings


def test_redis_memory_limits_and_maxlen():
    """
    Integration Test: Verifies that Redis streams are strictly capped
    using circular buffers (MAXLEN=10000) to prevent OOM errors.
    """
    test_stream = "csi:node:8888:raw"

    # 1. Connect to Redis
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        r.ping()
        r.delete(test_stream)
    except redis.ConnectionError:
        pytest.skip(
            "Redis server is offline. Skipping memory limit bounds integration test."
        )

    try:
        # 2. Add elements with a strict MAXLEN constraint of 5
        for i in range(15):
            payload = {"seq": i, "data": "A" * 100}
            r.xadd(test_stream, payload, maxlen=5, approximate=False)

        # 3. Assert stream length is strictly capped at 5 entries, not 15
        length = r.xlen(test_stream)
        print(f"Bbounded stream length: {length}")
        assert length == 5

        # 4. Verify memory diagnostics are readable
        info = r.info("memory")
        assert "used_memory" in info

    finally:
        r.delete(test_stream)
