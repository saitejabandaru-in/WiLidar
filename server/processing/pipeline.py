import os
import pickle
import pandas as pd
import numpy as np
from typing import Dict, List
from sklearn.decomposition import PCA
from server.utils.config import settings
from server.utils.logger import logger
from server.processing.filters import (
    phase_sanitize,
    hampel_filter_2d,
    butterworth_bandpass,
)
from server.processing.features import build_feature_vector


class CSIPipeline:
    def __init__(self, baseline_phase_offset: Dict[int, np.ndarray] = None):
        """
        Initializes the signal processing pipeline.

        Args:
            baseline_phase_offset (dict): Dictionary mapping node_id to their empty-room
                                          baseline phase mean arrays (shape 64,).
        """
        self.baseline_phases = baseline_phase_offset or {}
        self.pca: PCA = None
        self.load_pca_model()

    def load_pca_model(self):
        """
        Loads the pre-fitted PCA model from the models directory.
        """
        pca_path = os.path.join(settings.MODELS_DIR, "pca_model.pkl")
        if os.path.exists(pca_path):
            try:
                with open(pca_path, "rb") as f:
                    self.pca = pickle.load(f)
                logger.info(f"Successfully loaded fitted PCA model from {pca_path}")
            except Exception as e:
                logger.error(f"Failed to load PCA model from disk: {str(e)}")
                self.pca = None
        else:
            logger.warning(
                "Fitted PCA model not found. Running with mock PCA fallback."
            )
            self.pca = None

    def fit_and_save_pca(self, baseline_amplitudes: np.ndarray):
        """
        Fits PCA on empty-room baseline data collected during calibration (Step 1 of Section 9).
        Saves the fitted PCA object to disk.

        Args:
            baseline_amplitudes (np.ndarray): Shape (num_samples, num_features).
        """
        logger.info(
            f"Fitting PCA on baseline amplitude data of shape {baseline_amplitudes.shape}"
        )
        pca = PCA(n_components=settings.PCA_COMPONENTS)
        pca.fit(baseline_amplitudes)

        pca_path = os.path.join(settings.MODELS_DIR, "pca_model.pkl")
        try:
            with open(pca_path, "wb") as f:
                pickle.dump(pca, f)
            self.pca = pca
            logger.info(f"Fitted PCA model saved successfully to {pca_path}")
        except Exception as e:
            logger.error(f"Failed to save fitted PCA model to disk: {str(e)}")

    def sync_and_align_streams(
        self, raw_node_data: Dict[int, List[dict]], window_len_sec: float = 1.0
    ) -> pd.DataFrame:
        """
        Aligns raw frames from multiple nodes by timestamp using pandas.merge_asof with 10ms tolerance.

        Args:
            raw_node_data: Dict mapping node_id to a list of raw frames retrieved from Redis.

        Returns:
            pd.DataFrame: Aligned dataframe with matched timestamps and subcarrier lists.
        """
        dfs = []
        for node_id, frames in raw_node_data.items():
            if not frames:
                continue

            # Extract timestamp, amplitudes and phases
            records = []
            for frame in frames:
                t_us = int(frame["timestamp_us"])
                records.append(
                    {
                        "timestamp": pd.to_datetime(t_us, unit="us"),
                        "timestamp_us": t_us,
                        f"node_{node_id}_amp": np.fromstring(
                            frame["amplitudes"], sep=",", dtype=np.int8
                        ),
                        f"node_{node_id}_phase": np.fromstring(
                            frame["phases"], sep=",", dtype=np.int8
                        ),
                        f"node_{node_id}_rssi": int(frame["rssi"]),
                    }
                )

            df = pd.DataFrame(records).sort_values("timestamp")
            dfs.append((node_id, df))

        if not dfs:
            return pd.DataFrame()

        # Sort by node ID to ensure predictable merging order
        dfs = sorted(dfs, key=lambda x: x[0])

        # Merge dataframes using asof join
        merged_df = dfs[0][1]
        for node_id, df in dfs[1:]:
            merged_df = pd.merge_asof(
                merged_df,
                df,
                on="timestamp",
                tolerance=pd.Timedelta("10ms"),
                direction="nearest",
            )

        # Drop rows where any of the nodes did not align (missing data)
        merged_df = merged_df.dropna()
        return merged_df

    def process_frames(
        self, aligned_df: pd.DataFrame, node_ids: List[int]
    ) -> np.ndarray:
        """
        Executes the signal processing pipeline steps (Sanitization -> Hampel -> Butterworth -> PCA -> Features).

        Args:
            aligned_df (pd.DataFrame): Synchronized data from all active nodes.
            node_ids (List[int]): List of node IDs used to construct the feature vector.

        Returns:
            np.ndarray: The final 228-dimensional feature vector.
        """
        if aligned_df.empty or len(aligned_df) < 30:
            # Need a minimum sequence length to apply Butterworth bandpass filtering safely
            raise ValueError(
                f"Insufficient aligned frames: {len(aligned_df)} (needs >= 30)"
            )

        num_frames = len(aligned_df)

        # We process node by node
        processed_amps = {}
        processed_phases = {}

        # Features to fit into PCA
        # If we have 2 nodes, we concatenate their amplitudes for PCA: shape (num_frames, 64 * num_nodes)
        pca_features_list = []

        for node_id in node_ids:
            # Extract series of amplitude arrays (num_frames, 64)
            raw_amps = np.vstack(aligned_df[f"node_{node_id}_amp"].values).astype(
                np.float32
            )
            # Extract series of phase arrays (num_frames, 64)
            raw_phases = np.vstack(aligned_df[f"node_{node_id}_phase"].values).astype(
                np.float32
            )

            # Map phase from [-128, 127] back to radians [-pi, pi]
            raw_phases = (raw_phases / 127.0) * np.pi

            # 1. Phase Sanitization (Step 2)
            base_offset = self.baseline_phases.get(node_id, None)
            clean_phase = phase_sanitize(raw_phases, base_offset)

            # 2. Amplitude Outlier Rejection (Step 3 Hampel)
            clean_amp = hampel_filter_2d(
                raw_amps,
                window_size=settings.HAMPEL_WINDOW_SIZE,
                t0=settings.HAMPEL_N_SIGMAS,
            )

            # 3. Butterworth Zero-Phase Bandpass (Step 4)
            # Rejects drift and line noise, isolates human motion frequencies [0.1 - 10 Hz]
            filtered_amp = butterworth_bandpass(
                clean_amp,
                lowcut=settings.BUTTERWORTH_LOWCUT,
                highcut=settings.BUTTERWORTH_HIGHCUT,
                fs=settings.SAMPLING_RATE,
                order=settings.BUTTERWORTH_ORDER,
            )

            processed_amps[node_id] = filtered_amp
            processed_phases[node_id] = clean_phase

            pca_features_list.append(filtered_amp)

        # 4. Dimensionality Reduction (Step 5 PCA)
        # Combine subcarrier amplitudes across all nodes for spatial mapping
        combined_amps = np.hstack(
            pca_features_list
        )  # shape (num_frames, 64 * len(node_ids))

        if self.pca is not None:
            # Fit PCA output dimension count
            try:
                pca_data = self.pca.transform(combined_amps)
            except Exception as e:
                logger.error(
                    f"PCA transformation failed: {str(e)}. Using fallback projections."
                )
                pca_data = combined_amps[
                    :, : settings.PCA_COMPONENTS
                ]  # fallback projection
        else:
            # Mock PCA fallback (keeps first columns and pads if necessary)
            pca_data = np.zeros((num_frames, settings.PCA_COMPONENTS), dtype=np.float32)
            cols = min(settings.PCA_COMPONENTS, combined_amps.shape[1])
            pca_data[:, :cols] = combined_amps[:, :cols]

        # 5. Extract Feature Vector (Step 6)
        # Compute sliding stats over the 100-frame (1-second) window
        # Get the latest frame's amplitude and phase for cross-node features
        latest_amps = {nid: processed_amps[nid][-1] for nid in node_ids}
        latest_phases = {nid: processed_phases[nid][-1] for nid in node_ids}

        node_amp_phase = {
            nid: (latest_amps[nid], latest_phases[nid]) for nid in node_ids
        }

        # Build 228-dimensional vector from PCA window history and cross-node stats
        feature_vector = build_feature_vector(pca_data, node_amp_phase)

        return feature_vector
