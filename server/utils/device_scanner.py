import os
import re
import socket
import asyncio
import subprocess
import platform
import random
from typing import Set
from server.utils.config import settings
from server.utils.logger import logger


def get_local_ip() -> str:
    """
    Retrieves the local interface IP address on the primary network.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to a public DNS server to resolve local route interface IP
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


async def ping_ip(ip: str, port: int = 80) -> bool:
    """
    Tries to establish a TCP handshake on a common port to trigger ARP registration.
    """
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=0.1
        )
        writer.close()
        await writer.wait_closed()
        return True
    except asyncio.TimeoutError:
        return False
    except Exception:
        # Any response (e.g. connection refused) means the host is active
        return True


async def trigger_subnet_arp_sweep(base_ip: str) -> Set[str]:
    """
    Performs a fast async TCP scan across the /24 subnet to populate the ARP cache.
    """
    ip_parts = base_ip.split(".")
    if len(ip_parts) != 4:
        return set()

    subnet_prefix = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}."
    tasks = []

    # Sweep IPs 1 to 254 concurrently
    for i in range(1, 255):
        target_ip = f"{subnet_prefix}{i}"
        # Skip self
        if target_ip == base_ip:
            continue
        # Scan common ports 80 and 443 to hit active clients
        tasks.append(ping_ip(target_ip, port=80))
        tasks.append(ping_ip(target_ip, port=443))

    await asyncio.gather(*tasks, return_exceptions=True)
    return set()


def parse_arp_table() -> Set[str]:
    """
    Parses the local ARP cache table to retrieve unique MAC addresses.
    Supports macOS, Linux, and Windows.
    """
    unique_macs = set()
    sys_type = platform.system().lower()

    try:
        if sys_type == "linux":
            # Direct parsing of proc files avoids subprocess execution overhead
            arp_path = "/proc/net/arp"
            if os.path.exists(arp_path):
                with open(arp_path, "r") as f:
                    lines = f.readlines()[1:]  # skip header
                    for line in lines:
                        parts = re.split(r"\s+", line.strip())
                        if len(parts) >= 4:
                            mac = parts[3].lower()
                            # Exclude incomplete entries
                            if mac != "00:00:00:00:00:00" and re.match(
                                r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", mac
                            ):
                                unique_macs.add(mac)
                return unique_macs

        # Command fallback for macOS, Windows, and Linux configurations without procfs
        if sys_type == "windows":
            cmd = ["arp", "-a"]
        else:
            cmd = ["arp", "-an"]

        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)

        # Regex to locate MAC addresses in standard hex notation (e.g. 00-11-22-33-44-55 or 00:11:22:33:44:55)
        mac_regex = re.compile(
            r"([0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2})",
            re.IGNORECASE,
        )
        for mac in mac_regex.findall(output):
            mac_clean = mac.replace("-", ":").lower()
            if mac_clean != "ff:ff:ff:ff:ff:ff" and mac_clean != "00:00:00:00:00:00":
                unique_macs.add(mac_clean)

    except Exception as e:
        logger.error(f"Failed to parse ARP table: {str(e)}")

    return unique_macs


async def scan_active_devices() -> int:
    """
    Main entry point for active device discovery.
    Runs an async sweep and reads the ARP table to determine online device count.
    """
    if settings.SIMULATION_MODE:
        # Simulate active device fluctuations (e.g., 6 to 10 clients)
        # using a simple random walk offset
        base = int(os.environ.get("MOCK_DEVICE_BASE", 8))
        jitter = random.choice([-1, 0, 1])
        return max(1, base + jitter)

    try:
        local_ip = get_local_ip()
        if local_ip == "127.0.0.1":
            # No network interface available
            return len(parse_arp_table())

        # Trigger sweep to update cache
        await trigger_subnet_arp_sweep(local_ip)

        # Parse ARP table to count devices
        macs = parse_arp_table()
        logger.info(f"Subnet scan complete. Found {len(macs)} unique MAC addresses.")
        return len(macs)

    except Exception as e:
        logger.error(f"Error during active device discovery: {str(e)}")
        # Fallback to current table parsing without sweep
        return len(parse_arp_table())
