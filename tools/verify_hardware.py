#!/usr/bin/env python3
"""
WiLidar Physical Hardware Diagnostic & Validation Tool
Probes UDP sockets, measures packet rates, validates CRC32 integrity, and verifies Redis stream ingestion.
"""

import os
import sys
import time
import socket
import struct
import zlib
import redis
import numpy as np

# Add root path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.utils.config import settings


def calculate_crc32(packet_bytes: bytes) -> int:
    return zlib.crc32(packet_bytes) & 0xFFFFFFFF


def run_diagnostics(duration_sec: int = 10):
    print("=" * 80)
    print(" WiLidar Hardware Signal Diagnostics Utility ".center(80, "="))
    print("=" * 80)

    # 1. Test Redis Connection
    print(f"[Redis] Connecting to {settings.REDIS_HOST}:{settings.REDIS_PORT}...")
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        r.ping()
        print("✅ Redis Connection: ONLINE")
    except Exception as e:
        print(f"❌ Redis Connection: OFFLINE ({str(e)})")
        r = None

    # 2. Setup UDP Socket
    print(f"[Network] Binding to UDP {settings.UDP_HOST}:{settings.UDP_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.bind((settings.UDP_HOST, settings.UDP_PORT))
        print("✅ UDP Bind: BOUND (Listening for ESP32-S3 streams...)")
    except Exception as e:
        print(f"❌ UDP Bind: FAILED ({str(e)})")
        print("Ensure no other daemon or docker container is using port 5005.")
        sock.close()
        return

    # 3. Collect Packets
    print("\n[Diagnostics] Starting 10-second signal capture...")
    start_time = time.time()
    packet_intervals = []
    node_packet_counts = {}
    corrupted_packets = 0
    total_packets = 0
    last_packet_time = None

    # Pre-CRC format: 4B NodeID, 4B Seq, 8B Timestamp, 1B RSSI, 1B Noise, 1B Chan, 1B Bandwidth, 64B Amps, 64B Phases
    expected_packet_size = 152  # 148 bytes payload + 4 bytes CRC

    try:
        while time.time() - start_time < duration_sec:
            try:
                data, addr = sock.recvfrom(512)
                now = time.time()
                total_packets += 1

                # Measure arrival interval
                if last_packet_time is not None:
                    packet_intervals.append(
                        (now - last_packet_time) * 1000
                    )  # milliseconds
                last_packet_time = now

                # Check size
                if len(data) != expected_packet_size:
                    corrupted_packets += 1
                    continue

                # Verify CRC32
                payload = data[:-4]
                received_crc = struct.unpack("<I", data[-4:])[0]
                calculated_crc = calculate_crc32(payload)

                if received_crc != calculated_crc:
                    corrupted_packets += 1
                    continue

                # Unpack header
                header = struct.unpack("<IIqbbBB", data[:20])
                node_id = header[0]
                seq = header[1]
                header[2]
                rssi = header[3]
                noise = header[4]
                header[5]
                header[6]

                if node_id not in node_packet_counts:
                    node_packet_counts[node_id] = {
                        "count": 0,
                        "rssi_sum": 0,
                        "noise_sum": 0,
                        "last_seq": seq,
                        "dropped_packets": 0,
                        "ip": addr[0],
                    }

                node = node_packet_counts[node_id]
                node["count"] += 1
                node["rssi_sum"] += rssi
                node["noise_sum"] += noise

                # Track sequence dropouts
                seq_diff = seq - node["last_seq"]
                if seq_diff > 1:
                    node["dropped_packets"] += seq_diff - 1
                node["last_seq"] = seq

            except socket.timeout:
                sys.stdout.write(".")
                sys.stdout.flush()

        print("\n[Diagnostics] Capture completed.")

    finally:
        sock.close()

    # 4. Analyze Results
    print("\n" + "=" * 80)
    print(" REPORT SUMMARY ".center(80, "="))
    print("=" * 80)

    if total_packets == 0:
        print("❌ STATUS: OFFLINE")
        print("No packets received on UDP port 5005.")
        print(
            "Check ESP32-S3 power, router status, and verify target host IP in config.h."
        )
        return

    print(f"Total Packets Captured: {total_packets}")
    print(
        f"CRC Checksum Failures : {corrupted_packets} ({corrupted_packets/total_packets*100:.2f}%)"
    )

    if packet_intervals:
        mean_interval = np.mean(packet_intervals)
        std_interval = np.std(packet_intervals)
        print(f"Mean Ingestion Interval: {mean_interval:.2f}ms (Target: 10.0ms)")
        print(f"Jitter Standard Dev   : {std_interval:.2f}ms")

    for node_id, stats in node_packet_counts.items():
        avg_rssi = stats["rssi_sum"] / stats["count"]
        avg_noise = stats["noise_sum"] / stats["count"]
        p_rate = stats["count"] / duration_sec
        print(f"\n📡 Node ID: {node_id} (Source IP: {stats['ip']})")
        print(f"  - Ingestion Rate     : {p_rate:.1f} Hz (Target: 100 Hz)")
        print(f"  - Average RSSI       : {avg_rssi:.1f} dBm")
        print(f"  - Average Noise Floor: {avg_noise:.1f} dBm")
        print(f"  - Sequence Dropouts  : {stats['dropped_packets']} packets missed")

        # Verify Redis integration status
        if r:
            stream_key = f"csi:node:{node_id}:raw"
            if r.exists(stream_key):
                length = r.xlen(stream_key)
                print(
                    f"  - Redis Stream Key   : {stream_key} (Size: {length} entries) ✅"
                )
            else:
                print(f"  - Redis Stream Key   : {stream_key} (MISSING IN REDIS) ❌")

    print("\n" + "=" * 80)
    print(" DECISION & RECOMMENDATIONS ".center(80, "="))
    print("=" * 80)

    # Final overall score assessment
    is_healthy = True
    for node_id, stats in node_packet_counts.items():
        p_rate = stats["count"] / duration_sec
        if p_rate < 90.0:
            print(
                f"⚠️ Warning: Node {node_id} streaming rate ({p_rate:.1f}Hz) is below 90Hz."
            )
            print(
                "  Make sure your router is locked to a static channel and WMM power save is disabled."
            )
            is_healthy = False
        if stats["dropped_packets"] > 10:
            print(
                f"⚠️ Warning: Node {node_id} has high sequence dropouts ({stats['dropped_packets']})."
            )
            print(
                "  Check antenna alignments and avoid placing nodes near thick metallic obstructions."
            )
            is_healthy = False

    if corrupted_packets > 0:
        print(
            "⚠️ Warning: CRC checksum errors detected. Verify power bricks deliver stable 5V current."
        )
        is_healthy = False

    if is_healthy:
        print("🏆 STATUS: EXCELLENT")
        print(
            "Signal parameters are stable. Proceed to run calibration walks (calibrate.py)."
        )
    else:
        print("⚡ STATUS: DEGRADED")
        print("Follow the troubleshooting tips above to stabilize physical nodes.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_diagnostics()
