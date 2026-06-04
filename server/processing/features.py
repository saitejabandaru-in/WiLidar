import numpy as np
from typing import Dict, Tuple


def compute_zero_crossing_rate(arr: np.ndarray) -> float:
    """
    Computes zero crossing rate of a 1D array relative to its mean.
    """
    mean_subtracted = arr - np.mean(arr)
    # Detect transitions across zero
    crossings = np.diff(np.sign(mean_subtracted)) != 0
    return np.sum(crossings) / len(arr)


def extract_pca_features(pca_data: np.ndarray) -> np.ndarray:
    """
    Extracts statistical features from PCA components over a sliding window.

    Args:
        pca_data (np.ndarray): 2D array of shape (window_len, num_components)
                               representing the PCA components over time.

    Returns:
        np.ndarray: 1D array of shape (num_components * 5,) containing features.
    """
    window_len, num_components = pca_data.shape
    features = []

    for i in range(num_components):
        comp = pca_data[:, i]

        # 1. Mean
        mean_val = np.mean(comp)
        # 2. Standard deviation (intensity proxy)
        std_val = np.std(comp)
        # 3. Maximum absolute value (peak detector)
        max_abs = np.max(np.abs(comp))
        # 4. Signal energy (sum of squares)
        energy = np.sum(comp**2) / window_len
        # 5. Zero-crossing rate (frequency proxy to distinguish walking vs standing)
        zcr = compute_zero_crossing_rate(comp)

        features.extend([mean_val, std_val, max_abs, energy, zcr])

    return np.array(features, dtype=np.float32)


def extract_cross_node_features(
    node0_amp: np.ndarray,
    node1_amp: np.ndarray,
    node0_phase: np.ndarray,
    node1_phase: np.ndarray,
) -> np.ndarray:
    """
    Computes amplitude ratio and phase differences between two nodes.
    These cross-node features are critical for positioning accuracy.

    Args:
        node0_amp (np.ndarray): 1D array of shape (64,) representing subcarrier amplitudes for Node 0.
        node1_amp (np.ndarray): 1D array of shape (64,) representing subcarrier amplitudes for Node 1.
        node0_phase (np.ndarray): 1D array of shape (64,) representing subcarrier phases for Node 0.
        node1_phase (np.ndarray): 1D array of shape (64,) representing subcarrier phases for Node 1.

    Returns:
        np.ndarray: 1D array of shape (128,) containing cross-node features.
    """
    # 1. Amplitude Ratio: Node 0 / Node 1 (add epsilon to prevent divide by zero)
    # Convert from scaled int8 [0, 127] back to normalized float [0, 1] range first
    amp0 = node0_amp.astype(np.float32) / 127.0
    amp1 = node1_amp.astype(np.float32) / 127.0
    amp_ratio = (amp0 + 1e-5) / (amp1 + 1e-5)

    # 2. Phase Difference: Node 0 - Node 1 (in radians, mapping back from int8 [-128, 127])
    phase0 = (node0_phase.astype(np.float32) / 127.0) * np.pi
    phase1 = (node1_phase.astype(np.float32) / 127.0) * np.pi
    phase_diff = np.angle(
        np.exp(1j * (phase0 - phase1))
    )  # wraps phase difference to [-pi, pi]

    # Normalize outputs to fit tabular models comfortably
    norm_phase_diff = phase_diff / np.pi

    return np.hstack([amp_ratio, norm_phase_diff])


def build_feature_vector(
    pca_data: np.ndarray, node_amp_phase: Dict[int, Tuple[np.ndarray, np.ndarray]]
) -> np.ndarray:
    """
    Assembles the complete 228-dimensional feature vector:
    - 100 features from 20 PCA components (5 stats each)
    - 128 features from Node 0 and Node 1 cross-node calculations

    If one node is missing, fallback padding is applied.
    """
    # 1. Extract PCA Features (100 values)
    pca_features = extract_pca_features(pca_data)

    # 2. Extract Cross-Node Features (128 values)
    node_ids = sorted(list(node_amp_phase.keys()))

    if len(node_ids) >= 2:
        n0_amp, n0_phase = node_amp_phase[node_ids[0]]
        n1_amp, n1_phase = node_amp_phase[node_ids[1]]
        cross_features = extract_cross_node_features(n0_amp, n1_amp, n0_phase, n1_phase)
    else:
        # Fallback: if we do not have 2 nodes, fill with defaults (Pitfall 10)
        cross_features = np.zeros(128, dtype=np.float32)

    return np.hstack([pca_features, cross_features])
