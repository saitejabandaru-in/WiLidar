import time
import socket
import struct
import zlib
import numpy as np
import random
import argparse

# UDP destination configs
SERVER_IP = "127.0.0.1"
UDP_PORT = 5005
HEARTBEAT_PORT = 5006

SUBCARRIER_COUNT = 64
PACKET_FORMAT = "<IIqbbBB64b64bI"

NODE_POSITIONS = {
    1001: (0.5, 0.5),  # Node 1001 position (X, Y) in meters
    1002: (5.5, 5.5),  # Node 1002 position (X, Y) in meters
}


def calculate_crc32(packet_bytes_without_crc: bytes) -> int:
    return zlib.crc32(packet_bytes_without_crc) & 0xFFFFFFFF


class CSISimulatorStateMachine:
    def __init__(self, seed: int = None, people_count: int = 2):
        self.rng = np.random.default_rng(seed)
        if seed is not None:
            random.seed(seed)

        self.state = "STILL"  # STILL, WALKING, BURST, TRANSITION
        self.state_start_time = time.time()
        self.people_count = people_count

        # Human position coordinates (X, Y) in meters
        self.x = 3.0
        self.y = 3.0
        self.positions = [(3.0, 3.0)] * people_count

        # Leaky random walk drifts
        self.amp_drift = np.zeros(SUBCARRIER_COUNT, dtype=np.float32)
        self.phase_drift = np.zeros(SUBCARRIER_COUNT, dtype=np.float32)

        # Current room context (1 = Room 1 [0-6m], 2 = Room 2 [6-12m])
        self.current_room = 1

    def update(self, sim_t: float, dt: float):
        """
        Updates the human state and coordinates based on a simple 60-second schedule state machine.
        """
        elapsed = time.time() - self.state_start_time

        # State transitions every 10-15 seconds
        if self.state == "STILL" and elapsed > 10.0:
            self.state = "WALKING"
            self.state_start_time = time.time()
            print(
                f"[{time.strftime('%H:%M:%S')}] Simulator State -> WALKING (Normal speed, Room 1)"
            )
        elif self.state == "WALKING" and elapsed > 15.0:
            self.state = "BURST"
            self.state_start_time = time.time()
            print(
                f"[{time.strftime('%H:%M:%S')}] Simulator State -> BURST (High-speed running, Room 1)"
            )
        elif self.state == "BURST" and elapsed > 10.0:
            self.state = "TRANSITION"
            self.state_start_time = time.time()
            print(
                f"[{time.strftime('%H:%M:%S')}] Simulator State -> TRANSITION (Moving Room 1 to Room 2)"
            )
        elif self.state == "TRANSITION" and elapsed > 15.0:
            # Check if we moved to Room 2
            if self.x > 6.0:
                self.state = "STILL_ROOM2"
                self.current_room = 2
                print(
                    f"[{time.strftime('%H:%M:%S')}] Simulator State -> STILL (Standing still in Room 2)"
                )
            else:
                self.state = "STILL"
                self.current_room = 1
                print(
                    f"[{time.strftime('%H:%M:%S')}] Simulator State -> STILL (Standing still in Room 1)"
                )
            self.state_start_time = time.time()
        elif self.state == "STILL_ROOM2" and elapsed > 10.0:
            self.state = "TRANSITION_BACK"
            self.state_start_time = time.time()
            print(
                f"[{time.strftime('%H:%M:%S')}] Simulator State -> TRANSITION_BACK (Returning to Room 1)"
            )
        elif self.state == "TRANSITION_BACK" and elapsed > 10.0:
            self.state = "STILL"
            self.current_room = 1
            self.state_start_time = time.time()
            print(
                f"[{time.strftime('%H:%M:%S')}] Simulator State -> STILL (Standing still in Room 1)"
            )

        self.positions = []
        for i in range(self.people_count):
            if i == 0:
                # Person 1 path: uses the state machine configuration (figure-8, transitions etc)
                if self.state == "STILL":
                    px = 3.0 + self.rng.normal(0, 0.01)
                    py = 3.0 + self.rng.normal(0, 0.01)
                elif self.state == "STILL_ROOM2":
                    px = 9.0 + self.rng.normal(0, 0.01)
                    py = 3.0 + self.rng.normal(0, 0.01)
                elif self.state == "WALKING":
                    px = 3.0 + 2.0 * np.sin(0.4 * sim_t)
                    py = 3.0 + 1.5 * np.sin(0.8 * sim_t)
                elif self.state == "BURST":
                    px = 3.0 + 2.2 * np.sin(1.2 * sim_t)
                    py = 3.0 + 1.8 * np.sin(2.4 * sim_t)
                elif self.state == "TRANSITION":
                    ratio = min(1.0, elapsed / 10.0)
                    px = 3.0 + ratio * 6.0
                    py = 3.0 + 0.5 * np.sin(np.pi * ratio)
                elif self.state == "TRANSITION_BACK":
                    ratio = min(1.0, elapsed / 8.0)
                    px = 9.0 - ratio * 6.0
                    py = 3.0 - 0.5 * np.sin(np.pi * ratio)
                else:
                    px, py = 3.0, 3.0
            elif i == 1:
                # Person 2 path: Circular walk in Room 1
                px = 3.0 + 1.8 * np.cos(0.6 * sim_t + 1.5)
                py = 3.0 + 1.8 * np.sin(0.6 * sim_t + 1.5)
            else:
                # Person 3 path: Linear sweep
                px = 3.0 + 1.2 * np.sin(0.3 * sim_t + 3.0)
                py = 1.5 + 0.5 * np.cos(0.3 * sim_t + 3.0)

            px = np.clip(px, 0.1, 11.9)
            py = np.clip(py, 0.1, 5.9)
            self.positions.append((px, py))

        if self.people_count > 0:
            self.x, self.y = self.positions[0]
        else:
            self.x, self.y = 3.0, 3.0

        # Update drifts
        self.amp_drift = 0.995 * self.amp_drift + self.rng.normal(
            0, 0.05, SUBCARRIER_COUNT
        )
        self.phase_drift = 0.995 * self.phase_drift + self.rng.normal(
            0, 0.02, SUBCARRIER_COUNT
        )

    def generate_csi(
        self, node_x: float, node_y: float, sim_t: float, node_id: int
    ) -> tuple:
        """
        Simulates physically realistic composite subcarrier amplitudes and phases
        superimposed from all active tracked people.
        """
        # Base baseline amplitude profile
        base_amp = 60 + 20 * np.sin(np.arange(SUBCARRIER_COUNT) * 0.1 + (node_id % 3))

        # Calculate dynamic ripple by superimposing scattering effects from all active people
        dynamic_ripple = np.zeros(SUBCARRIER_COUNT, dtype=np.float32)
        total_dist = 0.0

        for px, py in self.positions:
            dist = np.sqrt((px - node_x) ** 2 + (py - node_y) ** 2)
            total_dist += dist

            if self.state in ["STILL", "STILL_ROOM2"] and self.people_count == 1:
                person_ripple = self.rng.normal(0, 0.5, SUBCARRIER_COUNT)
            else:
                speed_factor = 2.4 if self.state == "BURST" else 1.0
                speed_freq = (0.5 + 2.0 / (dist + 0.1)) * speed_factor
                person_ripple = 12.0 * np.sin(
                    np.arange(SUBCARRIER_COUNT) * 0.25
                    + 2.0 * np.pi * speed_freq * sim_t
                )

            dynamic_ripple += person_ripple

        mean_dist = total_dist / max(1, self.people_count)

        # Combine base, ripple, drifts, and random noise
        noise = self.rng.normal(0, 1.5, SUBCARRIER_COUNT)
        amps = base_amp + dynamic_ripple + self.amp_drift + noise
        amps_normalized = np.clip(amps, 0, 127).astype(np.int8)

        # Phase delay calculation proportional to average distance
        base_phase = np.linspace(-np.pi, np.pi, SUBCARRIER_COUNT)
        dist_delay = 0.4 * mean_dist * np.arange(SUBCARRIER_COUNT) / SUBCARRIER_COUNT
        phases = (
            base_phase
            + dist_delay
            + self.phase_drift
            + self.rng.normal(0, 0.05, SUBCARRIER_COUNT)
        )

        phases_normalized = np.clip(np.round((phases / np.pi) * 127), -128, 127).astype(
            np.int8
        )

        return list(amps_normalized), list(phases_normalized)


def main():
    parser = argparse.ArgumentParser(description="WiLidar 100Hz CSI Hardware Simulator")
    parser.add_argument(
        "--ip", type=str, default="127.0.0.1", help="Target UDP Server IP"
    )
    parser.add_argument("--port", type=int, default=5005, help="Target UDP Port")
    parser.add_argument(
        "--rate", type=float, default=100.0, help="Packet rate per node (Hz)"
    )
    parser.add_argument(
        "--loss", type=float, default=0.0, help="Packet loss rate [0.0 - 1.0]"
    )
    parser.add_argument(
        "--jitter", type=float, default=0.0, help="Max network jitter (seconds)"
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Deterministic random seed"
    )
    parser.add_argument(
        "--people-count",
        type=int,
        default=2,
        choices=[0, 1, 2, 3],
        help="Number of simulated moving subjects",
    )
    args = parser.parse_args()

    print("=========================================================")
    print("      WiLidar 100Hz Advanced CSI Hardware Simulator      ")
    print("=========================================================")
    print(f"Target Server : {args.ip}:{args.port}")
    print(f"Sampling Rate : {args.rate} Hz per node")
    print(f"Packet Loss   : {args.loss * 100.0:.1f}%")
    print(f"Jitter bounds : {args.jitter * 1000.0:.1f} ms")
    print(f"Moving People : {args.people_count} subjects")
    if args.seed is not None:
        print(f"Random Seed   : {args.seed} (Deterministic)")
    print("Nodes simulated: 1001, 1002")
    print("States        : STILL -> WALKING -> BURST -> TRANSITION")
    print("---------------------------------------------------------")
    print("Press Ctrl+C to terminate simulation.")

    # Create UDP Socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Initialize State Machine
    sim = CSISimulatorStateMachine(seed=args.seed, people_count=args.people_count)

    seq_nums = {1001: 0, 1002: 0}
    sim_t = 0.0
    dt = 1.0 / args.rate

    start_time_us = int(time.time() * 1_000_000)
    last_hb_time = 0.0

    try:
        while True:
            t_loop_start = time.time()
            sim_t += dt

            # Update state machine (moves human coordinates and drifts)
            sim.update(sim_t, dt)

            current_us = int(time.time() * 1_000_000) - start_time_us

            # Fire packets for Node 1001 and Node 1002
            for node_id, (n_x, n_y) in NODE_POSITIONS.items():
                # Apply Packet Loss logic (Pitfall 9: handle network dropouts)
                if args.loss > 0.0:
                    if random.random() < args.loss:
                        # Dropped packet! Skip sending, but increment sequence to simulate loss
                        seq_nums[node_id] = (seq_nums[node_id] + 1) & 0xFFFFFFFF
                        continue

                amps, phases = sim.generate_csi(n_x, n_y, sim_t, node_id)

                # Format: Node ID, Seq, Timestamp, RSSI, Noise, Channel, Bandwidth, Amps[64], Phases[64], CRC
                pre_crc_format = "<IIqbbBB64b64b"

                # Dynamic RSSI mapping based on distance to human (signal weakens as human blocks it)
                dist_h = np.sqrt((sim.x - n_x) ** 2 + (sim.y - n_y) ** 2)
                rssi = int(-45 - 2.5 * dist_h + np.random.normal(0, 1))
                rssi = np.clip(rssi, -100, -30)

                noise = -95
                channel = 6
                bandwidth = 1  # 40MHz

                packed_data = struct.pack(
                    pre_crc_format,
                    node_id,
                    seq_nums[node_id],
                    current_us,
                    rssi,
                    noise,
                    channel,
                    bandwidth,
                    *amps,
                    *phases,
                )

                # Append CRC32
                crc = calculate_crc32(packed_data)
                final_packet = packed_data + struct.pack("<I", crc)

                # Send to collector UDP port
                sock.sendto(final_packet, (args.ip, args.port))

                # Increment sequence
                seq_nums[node_id] = (seq_nums[node_id] + 1) & 0xFFFFFFFF

            # Simulate Heartbeats at 5-second intervals (exposed to heartbeat port 5006)
            if time.time() - last_hb_time >= 5.0:
                last_hb_time = time.time()
                for node_id in NODE_POSITIONS.keys():
                    # Heartbeat payload format: uint32 node_id, uint32 queue_fill_percent, int32 rssi
                    # queue utilization increases slightly during rapid movements
                    queue_util = 8 if sim.state == "BURST" else 2
                    hb_packet = struct.pack("<IIi", node_id, queue_util, -50)
                    sock.sendto(hb_packet, (args.ip, HEARTBEAT_PORT))

            # Control frequency and add Jitter if requested
            elapsed = time.time() - t_loop_start
            sleep_time = max(0.0005, dt - elapsed)

            if args.jitter > 0.0:
                # Random jitter offsets
                sleep_time += random.uniform(-args.jitter, args.jitter)
                sleep_time = max(0.0001, sleep_time)

            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nSimulator terminated cleanly.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
