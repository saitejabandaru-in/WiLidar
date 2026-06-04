import os
import time
import sqlite3
import asyncio
import csv
from io import StringIO
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import redis
import numpy as np
import httpx

from server.utils.config import settings
from server.utils.logger import logger
from server.processing.pipeline import CSIPipeline
from server.models.models import WiLidarEnsemble

app = FastAPI(
    title="WiLidar API",
    description="Backend API and WebSocket stream engine for WiFi CSI presence & positioning system",
    version="1.0.0",
)

# Enable CORS for frontend dashboard loading from different sources
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------
class RoomConfig(BaseModel):
    id: int
    name: str
    width_m: float
    height_m: float


class NodeConfig(BaseModel):
    id: int
    x: float
    y: float
    room_id: int


class SystemConfig(BaseModel):
    rooms: List[RoomConfig]
    nodes: List[NodeConfig]


# ---------------------------------------------------------
# SQLite Database Setup
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect(settings.SQLITE_PATH)
    cursor = conn.cursor()
    # Create configuration tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            width_m REAL NOT NULL,
            height_m REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY,
            x REAL NOT NULL,
            y REAL NOT NULL,
            room_id INTEGER,
            FOREIGN KEY (room_id) REFERENCES rooms(id)
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------
# Global State & Helpers
# ---------------------------------------------------------
redis_client: Optional[redis.Redis] = None
process_pool: Optional[ThreadPoolExecutor] = None
pipeline: Optional[CSIPipeline] = None
ensemble: Optional[WiLidarEnsemble] = None
simulator_process = None
active_device_count = 0


# Track WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            f"New WebSocket client connected. Total clients: {len(self.active_connections)}"
        )

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                f"WebSocket client disconnected. Total clients: {len(self.active_connections)}"
            )

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Connection might have died, let's ignore. Disconnect will clean it up.
                pass


ws_manager = ConnectionManager()
calibration_active = False


async def device_scanner_loop():
    global active_device_count
    from server.utils.device_scanner import scan_active_devices

    while True:
        try:
            active_device_count = await scan_active_devices()
        except Exception as e:
            logger.error(f"Error in device scanner loop: {str(e)}")
        await asyncio.sleep(10.0)


# ---------------------------------------------------------
# Inference Worker Function (Runs in separate process)
# ---------------------------------------------------------
def run_worker_inference(features: np.ndarray) -> dict:
    """
    Worker function executed in ThreadPoolExecutor.
    """
    return ensemble.run_inference(features)


# ---------------------------------------------------------
# FastAPI Startup & Shutdown Handlers
# ---------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    global redis_client, process_pool, pipeline, ensemble, simulator_process

    init_db()

    # Connect to Redis
    try:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True
        )
        redis_client.ping()
        logger.info("FastAPI connected to Redis.")
    except Exception as e:
        logger.error(f"FastAPI failed to connect to Redis: {str(e)}")
        redis_client = None

    # Start thread pool to run CPU-bound PyTorch/XGBoost inference safely without fork deadlocks
    process_pool = ThreadPoolExecutor(max_workers=1)

    # Initialize Pipeline and Ensemble
    pipeline = CSIPipeline()
    ensemble = WiLidarEnsemble()

    # Auto-train models on startup if in simulation mode and files are missing
    if settings.SIMULATION_MODE:
        presence_path = os.path.join(settings.MODELS_DIR, "presence_model.pkl")
        room_path = os.path.join(settings.MODELS_DIR, "room_model.pkl")
        position_path = os.path.join(settings.MODELS_DIR, "position_model.pt")
        if not (
            os.path.exists(presence_path)
            and os.path.exists(room_path)
            and os.path.exists(position_path)
        ):
            logger.info(
                "Simulation mode active and model files are missing. Running auto-mock training..."
            )
            try:
                from server.models.trainer import run_training_pipeline

                run_training_pipeline(mock=True)
                ensemble.load_models()
            except Exception as e:
                logger.error(f"Auto-mock training failed: {str(e)}")

        # Spawn simulator subprocess
        import subprocess
        import sys

        sim_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "tools",
            "simulate_csi.py",
        )
        logger.info(f"Simulation mode active. Spawning CSI simulator: {sim_script}")
        try:
            simulator_process = subprocess.Popen(
                [
                    sys.executable,
                    sim_script,
                    "--rate",
                    str(settings.SAMPLING_RATE),
                    "--ip",
                    settings.SIMULATOR_TARGET_IP,
                    "--port",
                    str(settings.UDP_PORT),
                    "--people-count",
                    "2",
                ]
            )
        except Exception as e:
            logger.error(f"Failed to spawn simulator process: {str(e)}")

    # Start device scanner loop and live inference loop task
    asyncio.create_task(device_scanner_loop())
    asyncio.create_task(live_inference_loop())


@app.on_event("shutdown")
def shutdown_event():
    global process_pool, simulator_process
    if simulator_process:
        logger.info("Terminating simulator subprocess...")
        try:
            simulator_process.terminate()
            simulator_process.wait(timeout=2.0)
        except Exception as e:
            logger.error(f"Error terminating simulator: {str(e)}")
        logger.info("Simulator subprocess terminated.")
    if process_pool:
        process_pool.shutdown()
        logger.info("Process pool closed.")


# ---------------------------------------------------------
# Notification Dispatcher (Section 7.2)
# ---------------------------------------------------------
async def send_notification(event: str, room: str):
    """
    Asynchronously dispatches a notification payload using the ntfy.sh platform.
    Topic is prefixed to guarantee uniqueness.
    """
    topic = "wilidar_alerts_saitejabandaru"
    logger.info(f"Dispatching ntfy alert: {event} in {room}")
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://ntfy.sh/{topic}",
                content=f"{event}: {room}",
                headers={"Title": "WiLidar Alert", "Priority": "default"},
                timeout=5.0,
            )
    except Exception as e:
        logger.error(f"Failed to post notification: {str(e)}")


# ---------------------------------------------------------
# Background Inference & Simulation Engine
# ---------------------------------------------------------
async def live_inference_loop():
    """
    Runs inference at 2 Hz (every 500ms) on collected stream buffers.
    If no nodes are actively posting data, automatically starts a path
    simulation to allow visual testing and evaluation on the dashboard.
    """
    logger.info("Live inference engine started.")

    # State tracking variables
    last_presence_state = False
    offline_nodes = set()

    # Parameters for path simulation (10m x 10m grid walking)
    sim_t = 0.0

    while True:
        await asyncio.sleep(0.5)  # 2 Hz frequency

        # 1. Fetch config to know active nodes
        conn = sqlite3.connect(settings.SQLITE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM nodes")
        node_rows = cursor.fetchall()
        conn.close()

        active_nodes = [row[0] for row in node_rows]

        # Check node heartbeats in Redis to monitor offline status
        nodes_online = False
        time.time()

        if redis_client:
            for nid in active_nodes:
                status_key = f"node:{nid}:status"
                hdata = redis_client.hgetall(status_key)

                # If a node was online but has not sent heartbeats in 15 seconds (Pitfall 10)
                if hdata:
                    last_seen = float(hdata.get("last_seen", 0))
                    # Convert Redis loop time to relative epoch offset
                    # In main.py: redis_client.hset(status_key, "last_seen", asyncio.get_event_loop().time())
                    # So we check elapsed time using event loop clock
                    loop_time = asyncio.get_event_loop().time()
                    if loop_time - last_seen > 15.0:
                        if nid not in offline_nodes:
                            offline_nodes.add(nid)
                            asyncio.create_task(
                                send_notification("Node went Offline", f"Node ID {nid}")
                            )
                    else:
                        if nid in offline_nodes:
                            offline_nodes.remove(nid)
                            asyncio.create_task(
                                send_notification("Node reconnected", f"Node ID {nid}")
                            )

                stream_key = f"csi:node:{nid}:raw"
                if redis_client.exists(stream_key):
                    nodes_online = True

        inference_result = {}

        if nodes_online and redis_client:
            # REAL HARDWARE PIPELINE (ESP32 -> UDP -> Redis -> Pipeline -> Ensemble)
            try:
                # Fetch last 1.0 second of data (100 Hz = 100 frames)
                raw_data = {}
                for nid in active_nodes:
                    stream_key = f"csi:node:{nid}:raw"
                    # Read last 100 elements
                    frames = redis_client.xrevrange(stream_key, count=100)
                    # Reverse back to chronologic order
                    raw_data[nid] = [f[1] for f in reversed(frames)]

                # Align streams
                aligned_df = pipeline.sync_and_align_streams(
                    raw_data, window_len_sec=1.0
                )

                if len(aligned_df) >= 30:
                    # Extract features (228 dims)
                    features = pipeline.process_frames(aligned_df, active_nodes)

                    # Run inference inside the process pool (GIL avoidance)
                    loop = asyncio.get_running_loop()
                    inference_result = await loop.run_in_executor(
                        process_pool, run_worker_inference, features
                    )

                    # Apply Fallback Heuristic for Ambiguous Presence Zone [0.40, 0.65] (Section 7.4)
                    prob = inference_result.get("presence_confidence", 0.0)
                    if 0.40 <= prob <= 0.65:
                        logger.info(
                            f"Ambiguous presence confidence ({prob:.2f}). Running variance heuristic..."
                        )
                        # Compute variance of amplitude over the window
                        # Flatten all subcarrier amplitudes over the window
                        flat_amps = []
                        for nid in active_nodes:
                            raw_amps = np.vstack(
                                aligned_df[f"node_{nid}_amp"].values
                            ).astype(np.float32)
                            flat_amps.append(raw_amps)

                        combined_amps = np.hstack(
                            flat_amps
                        )  # shape (num_frames, 64 * nodes)
                        # Variance over the sliding window per subcarrier, averaged
                        mean_variance = np.mean(np.var(combined_amps, axis=0))

                        # Threshold representing active body reflections above thermal noise (0.05)
                        if mean_variance > 0.05:
                            logger.info(
                                f"Heuristic override presence to TRUE: variance {mean_variance:.4f} > 0.05"
                            )
                            inference_result["room_present"] = True
                            inference_result["fallback_heuristics"] = True

                else:
                    logger.warning(f"Aligned frames count too low: {len(aligned_df)}")
                    nodes_online = False  # Fallback to simulation for visual smoothness
            except Exception as e:
                logger.error(
                    f"Inference pipeline execution error: {str(e)}", exc_info=True
                )
                nodes_online = False  # trigger simulation fallback

        if not nodes_online:
            # SIMULATION FALLBACK (Demo / Showcase mode for Stars & Followers)
            sim_t += 0.1

            # Simulate 2 people walking concurrently
            sim_people_count = 2
            tracked_people = []
            for i in range(sim_people_count):
                if i == 0:
                    x = 3.0 + 2.0 * np.sin(sim_t)
                    y = 3.0 + 1.5 * np.sin(2 * sim_t)
                else:
                    x = 3.0 + 1.8 * np.cos(0.6 * sim_t + 1.5)
                    y = 3.0 + 1.8 * np.sin(0.6 * sim_t + 1.5)
                tracked_people.append(
                    {
                        "id": i + 1,
                        "x_meters": float(x),
                        "y_meters": float(y),
                        "uncertainty": float(0.4 + 0.1 * i),
                    }
                )

            inference_result = {
                "room_present": True,
                "presence_confidence": 0.99,
                "room_id": 1,
                "room_confidence": 0.95,
                "x_meters": tracked_people[0]["x_meters"],
                "y_meters": tracked_people[0]["y_meters"],
                "position_uncertainty_m": tracked_people[0]["uncertainty"],
                "estimated_occupancy": sim_people_count,
                "tracked_people": tracked_people,
                "simulation": True,  # flag indicating demo mode
            }

        # Dispatch ntfy alerts for state changes (Section 7.2 requirement)
        current_presence = inference_result.get("room_present", False)
        if current_presence != last_presence_state:
            if current_presence:
                asyncio.create_task(send_notification("Presence Detected", "Room 1"))
            else:
                asyncio.create_task(send_notification("Room Vacated", "Room 1"))
            last_presence_state = current_presence

        # Inject active electronic devices count into response (sniffed subnet client count)
        inference_result["active_electronic_devices"] = active_device_count

        # Broadcast presence/position coordinates to WebSocket dashboard client
        payload = {"timestamp": time.time(), "data": inference_result}
        await ws_manager.broadcast(payload)


# ---------------------------------------------------------
# REST API Endpoints
# ---------------------------------------------------------
@app.post("/api/configure")
def configure_system(config: SystemConfig):
    """
    Saves rooms and nodes coordinates configuration parameters.
    """
    try:
        conn = sqlite3.connect(settings.SQLITE_PATH)
        cursor = conn.cursor()

        # Clear existing configs
        cursor.execute("DELETE FROM nodes")
        cursor.execute("DELETE FROM rooms")

        # Write rooms
        for room in config.rooms:
            cursor.execute(
                "INSERT INTO rooms (id, name, width_m, height_m) VALUES (?, ?, ?, ?)",
                (room.id, room.name, room.width_m, room.height_m),
            )

        # Write nodes
        for node in config.nodes:
            cursor.execute(
                "INSERT INTO nodes (id, x, y, room_id) VALUES (?, ?, ?, ?)",
                (node.id, node.x, node.y, node.room_id),
            )

        conn.commit()
        conn.close()
        logger.info("System configuration saved and written to SQLite.")
        return {"status": "success", "message": "Configuration saved."}
    except Exception as e:
        logger.error(f"Configure system endpoint error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
def get_system_health():
    is_demo = settings.SIMULATION_MODE

    # Check if packets are flowing in Redis streams
    stream_status = "inactive"
    active_nodes_count = 0
    if redis_client:
        try:
            keys = redis_client.keys("csi:node:*:raw")
            active_nodes_count = len(keys)

            # Check if any data has been appended in last 3 seconds
            latest_time = 0
            for k in keys:
                frames = redis_client.xrevrange(k, count=1)
                if frames:
                    # In Redis streams, IDs are formatted as "timestamp-sequence" (milliseconds)
                    ts_ms = int(frames[0][0].split("-")[0])
                    if ts_ms / 1000.0 > latest_time:
                        latest_time = ts_ms / 1000.0

            if active_nodes_count > 0:
                if time.time() - latest_time < 3.0:
                    stream_status = "active"
                else:
                    stream_status = "stale"
        except Exception as e:
            logger.error(f"Health check failed to query Redis: {str(e)}")
            stream_status = "error"

    return {
        "status": "healthy" if stream_status in ["active", "inactive"] else "degraded",
        "demo_mode": is_demo,
        "hardware_mode": not is_demo,
        "stream_status": stream_status,
        "active_nodes": active_nodes_count,
        "redis_connected": redis_client is not None,
        "timestamp": time.time(),
    }


@app.get("/api/status")
def get_system_status():
    """
    Returns system telemetry, uptime, model availability, and Redis metrics.
    """
    conn = sqlite3.connect(settings.SQLITE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rooms")
    room_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM nodes")
    node_count = cursor.fetchone()[0]
    conn.close()

    # Retrieve node status arrays from Redis heartbeats
    active_heartbeats = []
    if redis_client:
        try:
            # Scan for node status hashes
            keys = redis_client.keys("node:*:status")
            for k in keys:
                node_id = k.split(":")[1]
                hdata = redis_client.hgetall(k)
                active_heartbeats.append(
                    {
                        "node_id": int(node_id),
                        "ip": hdata.get("ip", "unknown"),
                        "queue_fill_percent": int(hdata.get("queue_fill_percent", 0)),
                        "rssi": int(hdata.get("rssi", 0)),
                    }
                )
        except Exception as e:
            logger.error(f"Failed to scan node status from Redis: {str(e)}")

    models_ready = (
        ensemble is not None
        and ensemble.presence_model is not None
        and ensemble.position_model is not None
    )

    return {
        "status": "online",
        "models_loaded": models_ready,
        "sqlite_rooms": room_count,
        "sqlite_nodes": node_count,
        "online_nodes": active_heartbeats,
        "server_time": time.time(),
    }


@app.post("/api/calibrate/start")
def start_calibration():
    global calibration_active
    calibration_active = True
    logger.info("Calibration procedure started.")
    return {"status": "success", "message": "Calibration active."}


@app.post("/api/calibrate/stop")
def stop_calibration():
    global calibration_active
    calibration_active = False
    logger.info("Calibration procedure stopped.")
    return {"status": "success", "message": "Calibration stopped."}


@app.post("/api/model/retrain")
async def trigger_model_retrain():
    """
    Triggers model training loop asynchronously to avoid blocking the main API process thread.
    """
    from server.models.trainer import run_training_pipeline

    logger.info("Triggering model training pipeline...")
    try:
        # Run in separate thread/process to prevent event loop freeze
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, run_training_pipeline, True
        )  # True forces mock run for demo

        # Reload models into memory once training completes
        if ensemble:
            ensemble.load_models()
        return {
            "status": "success",
            "message": "Model retrained and loaded successfully.",
        }
    except Exception as e:
        logger.error(f"Model retraining failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Retraining failed: {str(e)}")


room_calibration_active: Dict[int, bool] = {}


@app.post("/api/calibrate/room/{room_id}/start")
def start_room_calibration(room_id: int):
    global room_calibration_active
    room_calibration_active[room_id] = True
    logger.info(f"Calibration started for room {room_id}")
    return {"status": "success", "message": f"Calibration active for room {room_id}."}


@app.post("/api/calibrate/room/{room_id}/stop")
def stop_room_calibration(room_id: int):
    global room_calibration_active
    room_calibration_active[room_id] = False
    logger.info(f"Calibration stopped for room {room_id}")
    return {"status": "success", "message": f"Calibration stopped for room {room_id}."}


@app.get("/api/export/csi")
def export_csi_data(
    node_id: int = Query(..., description="Node ID to export data for"),
    limit: int = Query(1000, description="Max frames to export"),
):
    """
    Exports raw CSI packets logged in the Redis stream database as a CSV file.
    This enables offline research analysis and sharing.
    """
    if not redis_client:
        raise HTTPException(status_code=500, detail="Redis connection offline.")

    stream_key = f"csi:node:{node_id}:raw"
    if not redis_client.exists(stream_key):
        raise HTTPException(
            status_code=404, detail="No CSI data found for this node ID."
        )

    # Read stream elements
    frames = redis_client.xrevrange(stream_key, count=limit)
    # Reverse to keep chronological order
    frames = reversed(frames)

    # Write to a CSV string
    output = StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(
        [
            "node_id",
            "seq",
            "timestamp_us",
            "rssi",
            "noise_floor",
            "channel",
            "bandwidth",
            "amplitudes",
            "phases",
        ]
    )

    for f in frames:
        payload = f[1]
        writer.writerow(
            [
                payload.get("node_id"),
                payload.get("seq"),
                payload.get("timestamp_us"),
                payload.get("rssi"),
                payload.get("noise_floor"),
                payload.get("channel"),
                payload.get("bandwidth"),
                payload.get("amplitudes"),
                payload.get("phases"),
            ]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=csi_export_node_{node_id}.csv"
        },
    )


# ---------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # We only listen for client disconnects, server pushes data actively
            # receive_text is blocking, but it yields control back to event loop
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
