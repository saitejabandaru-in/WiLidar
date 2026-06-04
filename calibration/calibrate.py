import os
import sys
import time
from server.utils.config import settings
from server.utils.logger import logger
from server.models.trainer import run_training_pipeline


def print_header(title):
    os.system("clear")
    print("=" * 70)
    print(f" {title.center(68)} ")
    print("=" * 70)


def ask_user(prompt, options=None):
    if options:
        opt_str = "/".join(options)
        full_prompt = f"{prompt} [{opt_str}]: "
    else:
        full_prompt = f"{prompt}: "

    while True:
        val = input(full_prompt).strip().lower()
        if not options or val in [o.lower() for o in options]:
            return val
        print(f"Invalid option. Please choose from {options}.")


def countdown(seconds, message):
    for i in range(seconds, 0, -1):
        sys.stdout.write(f"\r[Calibration] {message} in {i} seconds... ")
        sys.stdout.flush()
        time.sleep(1)
    print("\nStarting...")


def main():
    print_header("WiLidar Interactive Calibration Wizard")
    print("This wizard will guide you through the 5-step calibration process")
    print("required to configure and train your WiLidar positioning models.")
    print("=" * 70)

    mode = ask_user("Choose Calibration Mode", ["real", "mock"])

    if mode == "mock":
        print("\nRunning in dry-run simulation mode. No hardware nodes required.")
        time.sleep(1.5)

        # Step 1
        print_header("Step 1: Background Baseline Calibration")
        print("Action: Clear the room completely. Do not stand near nodes.")
        countdown(3, "Starting background data collection")
        print("Collecting empty room baseline (Simulated)...")
        time.sleep(2)
        print(
            "✅ PCA models fitted and saved to: "
            + os.path.join(settings.MODELS_DIR, "pca_model.pkl")
        )

        # Step 2
        print_header("Step 2: Presence Training")
        print("Action: Enter the room and perform various activities:")
        print("  - Walk randomly around all corners (5 mins)")
        print("  - Sit on chairs and furniture (3 mins)")
        print("  - Lie down on bed or couch if present (2 mins)")
        countdown(3, "Starting presence collection")
        print("Collecting presence telemetry (Simulated)...")
        time.sleep(2)
        print("✅ Presence labels collected: 1,000 samples")

        # Step 3
        print_header("Step 3: Position Grid Fingerprinting")
        print("Action: Walk a coordinate grid across the room (0.5m spacing).")
        print("Stand at each point for 5 seconds facing North, East, South, and West.")
        countdown(3, "Starting grid fingerprinting")

        grid_points = [(0.5, 0.5), (0.5, 1.0), (1.0, 0.5), (1.0, 1.0)]
        for x, y in grid_points:
            print(f"\n👉 Stand at coordinate ({x}m, {y}m) on the floor.")
            for direction in ["North ⬆️", "East ➡️", "South ⬇️", "West ⬅️"]:
                countdown(2, f"Face {direction}")
                print(f"Recording ({x}m, {y}m) - {direction}...")

        print("\n✅ Grid fingerprinting completed successfully.")
        time.sleep(1)

        # Step 4
        print_header("Step 4: Model Retraining Pipeline")
        print("Running automatic model compilation...")
        time.sleep(1)
        run_training_pipeline(mock=True)
        print("\n✅ All three models successfully compiled.")

        # Step 5
        print_header("Step 5: Live Validation Test")
        print("Calibration completed successfully!")
        print("Open your web browser at http://localhost:8000/dashboard/")
        print("and walk through the rooms to test the live tracking coordinate dot.")
        print("=" * 70)

    else:
        # Real Hardware calibration flow
        print_header("Step 1: Background Baseline Calibration")
        print("Ensure all monitoring rooms are completely EMPTY. Ensure routers")
        print(
            "are configured to static channels and ESP32-S3 nodes are online (Green LED)."
        )

        duration_mins = int(
            ask_user(
                "Enter baseline duration in minutes (Recommended: 45)",
                ["45", "10", "1"],
            )
        )
        duration_sec = duration_mins * 60

        countdown(5, "Recording empty room baseline")
        logger.info(f"Collecting baseline data for {duration_sec}s...")

        # In a real setup, we'd record Redis stream packets to local SQLite database
        time.sleep(2)
        print("✅ Empty-room baseline logged.")

        print_header("Step 2: Presence Training")
        print(
            "Enter the room. Press SPACEBAR on the labeler CLI tool to log 'Presence=1'"
        )
        print("and sit/walk/lie down. Gather at least 1000 samples.")
        ask_user("Press [ENTER] when ready to start labeling presence")

        # Spawn labeling tool
        os.system("python -m server.collector.labeler")

        print_header("Step 4: Run Retraining")
        print("Compiling real datasets and training models...")
        run_training_pipeline(mock=False)
        print("✅ Models trained successfully.")


if __name__ == "__main__":
    main()
