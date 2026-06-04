import asyncio
import struct
import zlib
import redis
from typing import Dict, Tuple
from server.utils.config import settings
from server.utils.logger import logger

# Binary packet format mapping: <IIqbbBB64b64bI (Total: 152 bytes)
# <   : Little-endian
# I   : uint32 (node_id)
# I   : uint32 (sequence)
# q   : int64 (timestamp_us)
# b   : int8 (rssi)
# b   : int8 (noise_floor)
# B   : uint8 (channel)
# B   : uint8 (bandwidth)
# 64b : int8[64] (amplitudes)
# 64b : int8[64] (phases)
# I   : uint32 (crc32)
PACKET_FORMAT = "<IIqbbBB64b64bI"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

# Heartbeat packet format: <III (Total: 12 bytes)
# I   : uint32 (node_id)
# I   : uint32 (queue_fill_percent)
# i   : int32 (rssi)
HEARTBEAT_FORMAT = "<IIi"
HEARTBEAT_SIZE = struct.calcsize(HEARTBEAT_FORMAT)


class CSIUDPServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, redis_client: redis.Redis):
        super().__init__()
        self.redis = redis_client
        self.transport = None
        # Track sequence numbers per node to calculate packet loss
        self.node_stats: Dict[int, Dict[str, int]] = {}

    def connection_made(self, transport):
        self.transport = transport
        logger.info(
            f"CSI UDP Receiver listening on {settings.UDP_HOST}:{settings.UDP_PORT}"
        )

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        if len(data) != PACKET_SIZE:
            logger.warning(
                f"Discarding packet from {addr} with invalid length: {len(data)} (expected {PACKET_SIZE})"
            )
            return

        # 1. Validate CRC32 Checksum (Pitfall 7)
        received_crc = struct.unpack_from("<I", data, offset=PACKET_SIZE - 4)[0]
        calculated_crc = zlib.crc32(data[:-4]) & 0xFFFFFFFF

        if received_crc != calculated_crc:
            logger.warning(
                f"CRC32 mismatch from {addr}! Received: {received_crc}, Calc: {calculated_crc}. Dropping packet."
            )
            return

        # 2. Unpack binary struct
        unpacked = struct.unpack(PACKET_FORMAT, data)
        node_id = unpacked[0]
        seq_num = unpacked[1]
        timestamp_us = unpacked[2]
        rssi = unpacked[3]
        noise_floor = unpacked[4]
        channel = unpacked[5]
        bandwidth = unpacked[6]
        amplitudes = list(unpacked[7:71])
        phases = list(unpacked[71:135])

        # 3. Track Packet Loss Stats (Section 3.1)
        if node_id not in self.node_stats:
            self.node_stats[node_id] = {
                "last_seq": seq_num,
                "lost_packets": 0,
                "total_packets": 1,
            }
        else:
            stats = self.node_stats[node_id]
            expected_seq = (stats["last_seq"] + 1) & 0xFFFFFFFF
            if seq_num != expected_seq:
                gap = (seq_num - expected_seq) & 0xFFFFFFFF
                if gap < 1000:  # sanity check to prevent wrapping glitches
                    stats["lost_packets"] += gap
            stats["last_seq"] = seq_num
            stats["total_packets"] += 1

        # 4. Push to Redis stream (circular buffer limit 10,000 to prevent OOM - Pitfall 14)
        stream_key = f"csi:node:{node_id}:raw"
        payload = {
            "node_id": node_id,
            "seq": seq_num,
            "timestamp_us": timestamp_us,
            "rssi": rssi,
            "noise_floor": noise_floor,
            "channel": channel,
            "bandwidth": bandwidth,
            "amplitudes": ",".join(map(str, amplitudes)),
            "phases": ",".join(map(str, phases)),
        }

        try:
            self.redis.xadd(stream_key, payload, maxlen=10000, approximate=True)
        except redis.RedisError as e:
            logger.error(
                f"Failed to append frame to Redis stream for Node {node_id}: {str(e)}"
            )


class HeartbeatUDPServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, redis_client: redis.Redis):
        super().__init__()
        self.redis = redis_client
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info(
            f"Heartbeat Watchdog listening on {settings.UDP_HOST}:{settings.HEARTBEAT_PORT}"
        )

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        if len(data) != HEARTBEAT_SIZE:
            logger.warning(
                f"Discarding heartbeat from {addr} with invalid length: {len(data)}"
            )
            return

        unpacked = struct.unpack(HEARTBEAT_FORMAT, data)
        node_id = unpacked[0]
        queue_fill = unpacked[1]
        rssi = unpacked[2]

        # Save node status details to Redis hash for dashboard api status check
        status_key = f"node:{node_id}:status"
        try:
            self.redis.hset(
                status_key,
                mapping={
                    "ip": addr[0],
                    "queue_fill_percent": queue_fill,
                    "rssi": rssi,
                    "last_seen": asyncio.get_event_loop().time(),
                },
            )
            # Set key expiry to 15 seconds. If node drops offline, status will expire.
            self.redis.expire(status_key, 15)
        except redis.RedisError as e:
            logger.error(
                f"Failed to update heartbeat in Redis for Node {node_id}: {str(e)}"
            )


async def log_packet_loss_stats(protocol: CSIUDPServerProtocol):
    """
    Every 60 seconds, print packet loss diagnostics to stdout.
    Alert if packet loss exceeds 5% threshold (Section 3.1 requirement).
    """
    while True:
        await asyncio.sleep(60)
        for node_id, stats in list(protocol.node_stats.items()):
            total = stats["total_packets"]
            lost = stats["lost_packets"]
            if total > 0:
                loss_rate = (lost / (total + lost)) * 100.0
                if loss_rate > 5.0:
                    logger.warning(
                        f"🚨 HIGH PACKET LOSS DETECTED on Node {node_id}: "
                        f"{loss_rate:.2f}% (Lost: {lost}, Received: {total})"
                    )
                else:
                    logger.info(
                        f"Diagnostics Node {node_id}: Packet Loss: {loss_rate:.2f}% "
                        f"(Lost: {lost}, Received: {total})"
                    )
            # Reset rolling window stats to prevent accumulation over days
            stats["lost_packets"] = 0
            stats["total_packets"] = 0


async def main():
    # Connect to local Redis instance
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        r.ping()
        logger.info("Connected to Redis successfully.")
    except redis.ConnectionError as e:
        logger.error(
            f"Redis connection failed! Ensure redis-server is running. Error: {str(e)}"
        )
        return

    loop = asyncio.get_running_loop()

    # Start CSI Receiver
    csi_transport, csi_protocol = await loop.create_datagram_endpoint(
        lambda: CSIUDPServerProtocol(r),
        local_addr=(settings.UDP_HOST, settings.UDP_PORT),
    )

    # Start Heartbeat Watchdog
    hb_transport, hb_protocol = await loop.create_datagram_endpoint(
        lambda: HeartbeatUDPServerProtocol(r),
        local_addr=(settings.UDP_HOST, settings.HEARTBEAT_PORT),
    )

    # Schedule statistical logger
    asyncio.create_task(log_packet_loss_stats(csi_protocol))

    try:
        # Keep running indefinitely
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        csi_transport.close()
        hb_transport.close()
        logger.info("UDP Receivers shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
