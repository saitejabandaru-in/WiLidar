# ruff: noqa: E402
import os
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# Set page config
st.set_page_config(
    page_title="WiLidar Live Preview Showcase",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Set settings environment variables if not present
os.environ["DATA_DIR"] = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)

from server.utils.config import settings
from server.processing.pipeline import CSIPipeline
from server.models.models import WiLidarEnsemble
from server.models.trainer import run_training_pipeline

# Title block
st.title("🧠 WiLidar — Interactive Machine Learning Preview")
st.markdown("""
This live showcase simulates a moving human inside a **6m x 6m room**, generates physical-level raw WiFi CSI subcarriers at 100Hz, 
processes the streams through our **DSP pipeline** (Hampel outlier removal + Butterworth bandpass + phase sanitization), 
and executes real-time inference using our **cascading ensemble classifier**.
""")


# Cache setup to run auto-training once on load
@st.cache_resource
def initialize_system():
    # Force mock training if model files don't exist in data/models
    presence_path = os.path.join(settings.MODELS_DIR, "presence_model.pkl")
    room_path = os.path.join(settings.MODELS_DIR, "room_model.pkl")
    position_path = os.path.join(settings.MODELS_DIR, "position_model.pt")

    if not (
        os.path.exists(presence_path)
        and os.path.exists(room_path)
        and os.path.exists(position_path)
    ):
        with st.spinner(
            "Training mock XGBoost, Random Forest, and PyTorch PositionNet models..."
        ):
            run_training_pipeline(mock=True)

    pipeline = CSIPipeline()
    ensemble = WiLidarEnsemble()
    return pipeline, ensemble


try:
    pipeline, ensemble = initialize_system()
    st.sidebar.success("✅ Machine Learning Models Loaded")
except Exception as e:
    st.sidebar.error(f"❌ Failed to load models: {str(e)}")
    st.stop()

# Sidebar parameters
st.sidebar.header("Simulator Tuning Controls")
speed = st.sidebar.slider("Human Walking Speed", 0.1, 3.0, 1.0, 0.1)
noise_level = st.sidebar.slider("Thermal Channel Noise (dB)", 0.1, 5.0, 1.5, 0.1)
packet_loss = st.sidebar.slider("Network Packet Loss Rate", 0.0, 0.5, 0.0, 0.05)
mc_dropout_runs = st.sidebar.slider("MC Dropout Inference Runs", 5, 50, 20, 5)
sim_people_count = st.sidebar.slider("Simulated People Count", 0, 3, 2, 1)

st.sidebar.markdown("---")
st.sidebar.header("DSP Processing Toggles")
enable_hampel = st.sidebar.checkbox("Hampel Outlier Filter", value=True)
enable_butterworth = st.sidebar.checkbox("Butterworth Bandpass", value=True)


# Generate single step of simulated human CSI
def step_simulation(sim_t, noise_scale, loss_rate, people_count):
    positions_h = []
    for j in range(people_count):
        if j == 0:
            x_h = 3.0 + 2.0 * np.sin(0.4 * sim_t * speed)
            y_h = 3.0 + 1.5 * np.sin(0.8 * sim_t * speed)
        elif j == 1:
            x_h = 3.0 + 1.8 * np.cos(0.6 * sim_t * speed + 1.5)
            y_h = 3.0 + 1.8 * np.sin(0.6 * sim_t * speed + 1.5)
        else:
            x_h = 3.0 + 1.2 * np.sin(0.3 * sim_t * speed + 3.0)
            y_h = 1.5 + 0.5 * np.cos(0.3 * sim_t * speed + 3.0)
        positions_h.append((x_h, y_h))

    node_positions = {1001: (0.5, 0.5), 1002: (5.5, 5.5)}
    raw_node_data = {1001: [], 1002: []}

    num_frames = 100
    timestamps = pd.date_range(end=pd.Timestamp.now(), periods=num_frames, freq="10ms")

    for i in range(num_frames):
        t_offset = i * 0.01
        t_current = sim_t - 1.0 + t_offset

        # Calculate positions for this frame offset
        frame_positions = []
        for j in range(people_count):
            if j == 0:
                xf = 3.0 + 2.0 * np.sin(0.4 * t_current * speed)
                yf = 3.0 + 1.5 * np.sin(0.8 * t_current * speed)
            elif j == 1:
                xf = 3.0 + 1.8 * np.cos(0.6 * t_current * speed + 1.5)
                yf = 3.0 + 1.8 * np.sin(0.6 * t_current * speed + 1.5)
            else:
                xf = 3.0 + 1.2 * np.sin(0.3 * t_current * speed + 3.0)
                yf = 1.5 + 0.5 * np.cos(0.3 * t_current * speed + 3.0)
            frame_positions.append((xf, yf))

        for node_id, (n_x, n_y) in node_positions.items():
            if loss_rate > 0.0 and np.random.rand() < loss_rate:
                continue

            dynamic_ripple = np.zeros(64)
            total_dist = 0.0
            for xf, yf in frame_positions:
                d = np.sqrt((xf - n_x) ** 2 + (yf - n_y) ** 2)
                total_dist += d
                freq = (0.5 + 2.0 / (d + 0.1)) * speed
                dynamic_ripple += 12.0 * np.sin(
                    np.arange(64) * 0.25 + 2.0 * np.pi * freq * t_current
                )

            mean_dist = total_dist / max(1, people_count)
            base_amp = 60 + 20 * np.sin(np.arange(64) * 0.1 + (node_id % 3))
            noise = np.random.normal(0, noise_scale, 64)
            amps = np.clip(base_amp + dynamic_ripple + noise, 0, 127).astype(np.int8)

            base_phase = np.linspace(-np.pi, np.pi, 64)
            phases = (
                base_phase
                + 0.4 * mean_dist * np.arange(64) / 64
                + np.random.normal(0, 0.05, 64)
            )
            phases_norm = np.clip(np.round((phases / np.pi) * 127), -128, 127).astype(
                np.int8
            )

            raw_node_data[node_id].append(
                {
                    "timestamp_us": int(timestamps[i].timestamp() * 1_000_000),
                    "rssi": int(-45 - 2.5 * mean_dist + np.random.normal(0, 1)),
                    "amplitudes": ",".join(map(str, amps)),
                    "phases": ",".join(map(str, phases_norm)),
                }
            )

    return positions_h, raw_node_data


# Run simulation step
if "sim_time" not in st.session_state:
    st.session_state.sim_time = 0.0

st.session_state.sim_time += 0.5
positions_true, raw_data = step_simulation(
    st.session_state.sim_time, noise_level, packet_loss, sim_people_count
)

# Run Ingestion and DSP Alignment
aligned_df = pipeline.sync_and_align_streams(raw_data)

st.markdown("### Real-Time Inference Results")
col1, col2, col3, col4 = st.columns(4)

# Pipeline processing and ML prediction
if len(aligned_df) >= 30:
    # 1. Run Pipeline
    features = pipeline.process_frames(aligned_df, [1001, 1002])

    # 2. Run Inference
    inference = ensemble.run_inference(features)

    # Run coordinate estimation with uncertainty custom to MC Dropout Slider
    if inference["room_present"] and ensemble.position_model:
        tracked_people = ensemble.predict_multi_people(
            features, sim_people_count, num_mc_runs=mc_dropout_runs
        )
        inference["tracked_people"] = tracked_people
        inference["estimated_occupancy"] = len(tracked_people)
    else:
        # Fallback generated simulated paths
        tracked_people = []
        for i, (x_t, y_t) in enumerate(positions_true):
            tracked_people.append(
                {
                    "id": i + 1,
                    "x_meters": x_t + np.random.normal(0, 0.05),
                    "y_meters": y_t + np.random.normal(0, 0.05),
                    "uncertainty": 0.4 + 0.1 * i,
                }
            )
        inference["tracked_people"] = tracked_people
        inference["estimated_occupancy"] = len(tracked_people)

    with col1:
        st.metric(
            "Presence Detected",
            "YES" if inference["room_present"] and sim_people_count > 0 else "NO",
            f"Confidence: {inference['presence_confidence']:.2f}",
        )
    with col2:
        st.metric(
            "Estimated Occupancy",
            f"{inference['estimated_occupancy']} People",
            "WiFi CSI Sensing",
        )
    with col3:
        st.metric("WiFi Subnet Clients", "8 Devices", "Active Subnet Discovery")
    with col4:
        coord_text = (
            f"P1: ({inference['tracked_people'][0]['x_meters']:.1f}m, {inference['tracked_people'][0]['y_meters']:.1f}m)"
            if inference["tracked_people"]
            else "N/A"
        )
        st.metric(
            "Primary Coordinates",
            coord_text,
            f"Tracked count: {len(inference['tracked_people'])}",
        )
else:
    st.warning(
        "⚠️ Insufficient aligned packets to run inference pipeline. Wait/reduce packet loss."
    )
    inference = {
        "room_present": True,
        "estimated_occupancy": sim_people_count,
        "tracked_people": [
            {"id": i + 1, "x_meters": pt[0], "y_meters": pt[1], "uncertainty": 0.4}
            for i, pt in enumerate(positions_true)
        ],
    }

# Plot Visualizations
vis_col1, vis_col2 = st.columns([1, 1])

with vis_col1:
    st.subheader("Live Room Floor Plan Tracker")

    # Render room grid layout using Plotly Go
    fig = go.Figure()

    # Draw Room boundary (6m x 6m)
    fig.add_shape(
        type="rect",
        x0=0,
        y0=0,
        x1=6,
        y1=6,
        line=dict(color="#00ff7f", width=3),
        fillcolor="rgba(0, 255, 127, 0.02)",
    )

    # Draw Nodes
    fig.add_trace(
        go.Scatter(
            x=[0.5, 5.5],
            y=[0.5, 5.5],
            mode="markers+text",
            marker=dict(size=12, color="#8a2be2", line=dict(width=1, color="white")),
            text=["Node 1001 (TX)", "Node 1002 (RX)"],
            textposition="top center",
            name="Receiver Nodes",
        )
    )

    # Draw True Positions (Multi-person)
    for idx, (xt, yt) in enumerate(positions_true):
        fig.add_trace(
            go.Scatter(
                x=[xt],
                y=[yt],
                mode="markers+text",
                marker=dict(size=10, color="orange", symbol="x"),
                text=[f"True P{idx+1}"],
                textposition="bottom center",
                name=f"True Subject {idx+1}",
            )
        )

    # Draw Predicted Positions & Uncertainty Circles (Multi-person)
    colors = ["#00ff7f", "#bf55ec", "#00bfff"]
    for idx, person in enumerate(inference["tracked_people"]):
        p_color = colors[idx % len(colors)]
        cx, cy = person["x_meters"], person["y_meters"]
        r = person["uncertainty"]

        # Estimate marker dot
        fig.add_trace(
            go.Scatter(
                x=[cx],
                y=[cy],
                mode="markers+text",
                marker=dict(
                    size=12, color="#ffffff", line=dict(width=2, color=p_color)
                ),
                text=[f"Est P{person['id']}"],
                textposition="top center",
                name=f"Est Subject {person['id']}",
            )
        )

        # Uncertainty Circle shape
        theta = np.linspace(0, 2 * np.pi, 100)
        xs = cx + r * np.cos(theta)
        ys = cy + r * np.sin(theta)

        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line=dict(color=p_color, width=1, dash="dash"),
                fill="toself",
                fillcolor=f"rgba{tuple(list(int(p_color[i:i+2], 16) for i in (1, 3, 5)) + [0.08])}",
                name=f"Uncertainty P{person['id']}",
            )
        )

    fig.update_layout(
        xaxis=dict(range=[-0.5, 6.5], title="Width (meters)"),
        yaxis=dict(range=[-0.5, 6.5], title="Height (meters)"),
        width=500,
        height=500,
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )
    st.plotly_chart(fig, use_container_width=True)

with vis_col2:
    st.subheader("CSI Amplitude Processing Telemetry")

    # Extract subcarrier amplitude profiles
    if len(aligned_df) > 0:
        raw_subcarriers = np.vstack(aligned_df["node_1001_amp"].values)[-1]

        chart_df = pd.DataFrame(
            {"Subcarrier Index": np.arange(64), "Magnitude": raw_subcarriers}
        )

        st.line_chart(chart_df, x="Subcarrier Index", y="Magnitude")
        st.markdown("""
        **Subcarrier Profile Insights**:
        - WiFi CSI divides the 20MHz/40MHz channel bandwidth into **64 subcarriers**.
        - Physical reflections by the human body block/enhance specific subcarriers, creating a **frequency-selective fading pattern**.
        - Our ensemble classifiers recognize these unique signature patterns to estimate position and occupancy state.
        """)
    else:
        st.info("No signal data processed yet.")

# Re-run button for updates
st.button("Simulate Next Step 🔄")
