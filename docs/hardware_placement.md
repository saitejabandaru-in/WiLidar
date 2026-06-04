# WiLidar Node Placement & Layout Optimization Guide

Proper node placement is the single most critical factor for achieving high positioning accuracy and preventing false negatives in human presence detection. This guide explains how to design node placements for various floor plans.

---

## 1. Physics of CSI-Based Tracking

Channel State Information (CSI) measures how a WiFi carrier signal is scattered, reflected, and attenuated between a Transmitter (TX) and a Receiver (RX). Unlike RSSI, which is a single scalar power value, CSI reports the channel coefficient matrix for **64 individual subcarrier frequencies**.

When a human body enters this environment, it behaves as a dielectric object, creating dynamic multipath reflections:

```
                  [ WiFi Router / TX Node ]
                         /       \
                        /         \ (Direct path)
                       /           \
                 (Scattered)     [ Wall / Reflection ]
                     /               \
                    /                 \
            [ Human Body ]             \
                  \                     /
                   \                   /
                  [ ESP32-S3 RX Node ]
```

---

## 2. Spacing and Height Rules

### Waist-Level Height (1.0m–1.2m)
- **Do not place nodes on the floor or ceiling.**
- The human torso contains the highest concentration of water (dielectric mass). Positioning nodes at waist height ensures that walking, sitting, and breathing create maximum multipath disruptions.

### Node Spacing
- **Minimum: 3 Meters**. Placing nodes too close saturates the receiver, masking minor body movements (like breathing).
- **Maximum: 8 Meters**. Spacing nodes too far apart degrades the signal-to-noise ratio (SNR), rendering subcarriers noisy.

---

## 3. Node Configuration Layouts

### 1-Room Layout (2 Nodes)
*Requires: 1 TX Node, 1 RX Node*

```
+---------------------------------------+
|  [RX Node 1002]                       |
|                                       |
|                                       |
|                                       |
|                     [TX Node 1001]    |
+---------------------------------------+
```
*Tip: Place nodes diagonally in opposite corners, but offset them from the exact corner to reduce wall reflection dead zones.*

### 2–3 Room Layout (3 Nodes)
*Requires: 1 TX Node, 2 RX Nodes*

```
+-------------------+-------------------+
|                   |  [RX Node 1003]   |
|      ROOM A       |      ROOM B       |
|                   |                   |
|                   |                   |
+---------     -----+---------     -----+
|      HALLWAY      |                   |
|                   |      ROOM C       |
|  [TX Node 1001]   |  [RX Node 1002]   |
+-------------------+-------------------+
```
*Tip: Place the TX node centrally in a hallway or common area, with RX nodes crossing the signal paths into the bedrooms/offices.*

---

## 4. Major Placement Pitfalls to Avoid

1. **Symmetric Placement**: Placing a TX and RX node directly opposite each other on parallel walls creates a linear symmetric dead zone. A person standing equidistant from both walls will cancel out signal variations. **Mitigation**: Offset nodes by 15–30 degrees.
2. **AC Vent Interference**: Air currents from vents can cause plastic enclosures or antennas to vibrate slightly. Even a 1mm vibration will register as human movement. **Mitigation**: Rigidly tape or screw nodes to solid studs.
3. **Appliance Proximity**: Do not place nodes within 1.5m of microwaves, baby monitors, or heavy inductive appliances (like refrigerators) operating in the 2.4GHz spectrum.
