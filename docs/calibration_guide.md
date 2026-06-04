# WiLidar Calibration Guide

Calibration is the process of mapping Channel State Information (CSI) signal signatures to physical coordinates. This guide walks you through building an accurate tracking model.

---

## Step 1: Background Baseline (Empty-Room Collection)

Before the system can detect people, it must understand the "quiet state" of the room, including static reflections from walls, furniture, and fixed metal objects.

1. **Clear the space**: Remove all people and pets from the monitored rooms. Close all doors.
2. **Launch the baseline recorder**: Run `python calibration/calibrate.py` and select `real` mode.
3. **Wait 45 minutes**: Let the system stream raw packets. This data is used to fit the Principal Component Analysis (PCA) model. Fitting PCA on a quiet room isolates the background frequencies, so that any dynamic components can be classified as movement.

---

## Step 2: Presence Classifier Training

Next, the system must learn to distinguish between an empty room and a room with human presence.

1. Enter the room being calibrated.
2. Run the presence labeler:
   ```bash
   python -m server.collector.labeler
   ```
3. Use the **SPACEBAR** to set `Presence = 1` (Present) when you are inside.
4. Perform these activities to build a robust model:
   - **Walking**: Walk around all sections of the room (5 minutes).
   - **Sitting**: Sit on chairs, sofas, and stools (3 minutes).
   - **Lying Down**: Lie down on the bed or sofa (2 minutes).
   - **Breathing**: Sit completely still. The system's Butterworth bandpass filter captures micro-movements (breathing at 0.1–0.3Hz).
5. Exit the room, press **SPACEBAR** to set `Presence = 0` (Empty Room), and leave it empty for another 5 minutes.
6. Press **q** to save and exit the labeler.

---

## Step 3: Coordinate Grid Fingerprinting

Coordinate fingerprinting maps CSI signals to exact $(X, Y)$ locations in meters.

1. **Mark the Floor**: Use masking tape to mark a grid on the floor spaced **0.5m apart**.
2. **Establish the Coordinate System**:
   - Set the bottom-left corner of your room as $(0.0, 0.0)$ meters.
   - The X-axis runs along the width of the room.
   - The Y-axis runs along the length of the room.
3. Start the calibration wizard and navigate to Step 3.
4. For each intersection on your tape grid:
   - Walk to the coordinate point (e.g. $x=1.5$m, $y=2.0$m).
   - Input the coordinate into the labeling terminal.
   - Stand on the coordinate for 5 seconds facing **North**.
   - Pivot and stand facing **East** for 5 seconds.
   - Repeat facing **South** and **West**.
   *(Facing direction matters because the human body absorbs and redirects WiFi waves differently from the front, back, and sides).*

---

## Step 4: Retrain and Verify

Once all data is logged in the SQLite database, execute the model retraining pipeline:

```bash
python server/models/trainer.py --mode full
```

### Checking Validation Outputs
The script will output performance metrics:
- **Presence Recall**: Must be $\ge 0.97$ (ensuring we do not miss a person in the room).
- **Room Accuracy**: Must be $\ge 0.92$.
- **Coordinate RMSE**: Must be $\le 1.0$ meter.

If accuracy metrics are low, identify which room has high coordinate error, print a new tape grid, and collect additional fingerprint points for that specific room.
