import sys
import os
import tty
import termios
import select
import time
import sqlite3
from server.utils.config import settings
from server.utils.logger import logger


def get_key():
    """
    Reads a single keypress from standard input without blocking or requiring Enter.
    Works natively on macOS.
    """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        # Wait up to 0.1s for input
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if rlist:
            key = sys.stdin.read(1)
            # Handle escape sequences for arrow keys
            if key == "\x1b":
                # Read next two characters
                rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                if rlist:
                    key += sys.stdin.read(2)
            return key
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def init_db():
    """
    Ensures the calibration labeling tables exist in the SQLite database.
    """
    conn = sqlite3.connect(settings.SQLITE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calibration_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_us INTEGER NOT NULL,
            presence INTEGER NOT NULL, -- 0 = empty, 1 = present
            room_id INTEGER NOT NULL,
            x_m REAL NOT NULL,
            y_m REAL NOT NULL,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_label(presence: int, room_id: int, x_m: float, y_m: float, notes: str = ""):
    """
    Saves a labeling state update to the SQLite database.
    """
    conn = sqlite3.connect(settings.SQLITE_PATH)
    cursor = conn.cursor()
    # Log with microsecond timestamp matching the ESP32 timestamps
    timestamp_us = int(time.time() * 1_000_000)
    cursor.execute(
        "INSERT INTO calibration_labels (timestamp_us, presence, room_id, x_m, y_m, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (timestamp_us, presence, room_id, x_m, y_m, notes),
    )
    conn.commit()
    conn.close()


def main():
    init_db()

    presence = 0  # 0 = Empty Room, 1 = Person Present
    room_id = 1
    x_m = 0.0
    y_m = 0.0

    # ANSI escape sequences for terminal display
    os.system("clear")
    print("=================================================================")
    print("                WiLidar Calibration Labeling Tool                ")
    print("=================================================================")
    print("Controls:")
    print("  [SPACE]     : Toggle Human Presence (Empty Room vs. Present)")
    print("  [1, 2, 3, 4]: Set Room ID (1=Living Room, 2=Bedroom, 3=Kitchen, etc.)")
    print("  [w/s]       : Adjust Y-coordinate (+0.5m / -0.5m)")
    print("  [a/d]       : Adjust X-coordinate (-0.5m / +0.5m)")
    print("  [q]         : Exit labeling tool")
    print("=================================================================")
    print("\nPress any key to start logging...")

    # Wait for initial keystroke
    while get_key() is None:
        time.sleep(0.05)

    last_print = 0
    try:
        while True:
            key = get_key()
            if key is not None:
                if key == "q":
                    logger.info("Exiting calibration labeling tool.")
                    break
                elif key == " ":
                    presence = 1 - presence
                    log_label(presence, room_id, x_m, y_m, "Manual presence toggle")
                elif key in ["1", "2", "3", "4"]:
                    room_id = int(key)
                    log_label(presence, room_id, x_m, y_m, f"Changed room to {room_id}")
                elif key == "w":
                    y_m += 0.5
                    log_label(presence, room_id, x_m, y_m, "Coordinate Y increase")
                elif key == "s":
                    y_m = max(0.0, y_m - 0.5)
                    log_label(presence, room_id, x_m, y_m, "Coordinate Y decrease")
                elif key == "d":
                    x_m += 0.5
                    log_label(presence, room_id, x_m, y_m, "Coordinate X increase")
                elif key == "a":
                    x_m = max(0.0, x_m - 0.5)
                    log_label(presence, room_id, x_m, y_m, "Coordinate X decrease")

            # Print current state in a fixed box layout
            now = time.time()
            if now - last_print > 0.2:
                sys.stdout.write("\r\033[K")  # Clear line
                presence_str = (
                    "\033[92mPRESENT\033[0m"
                    if presence == 1
                    else "\033[90mEMPTY ROOM\033[0m"
                )
                sys.stdout.write(
                    f"State: [{presence_str}] | "
                    f"Room: {room_id} | "
                    f"Coordinates: ({x_m:.1f}m, {y_m:.1f}m) | "
                    f"Press 'q' to Quit"
                )
                sys.stdout.flush()
                last_print = now

            time.sleep(0.02)

    except KeyboardInterrupt:
        pass
    print("\nLabeler shut down.")


if __name__ == "__main__":
    main()
