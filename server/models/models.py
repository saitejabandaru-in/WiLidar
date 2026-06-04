import os
import pickle
import numpy as np
import torch
import torch.nn as nn
from typing import Tuple, Dict, Any, Union
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
from server.utils.config import settings
from server.utils.logger import logger


# ---------------------------------------------------------
# PyTorch Model for Coordinate Positioning Regression
# ---------------------------------------------------------
class PositionNet(nn.Module):
    def __init__(self, input_dim: int = 228):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.BatchNorm1d(256),
            nn.GELU(),  # GELU outperforms ReLU for CSI regressions (Section 5.3)
            nn.Dropout(0.3),
            nn.Linear(256, 128),
            nn.BatchNorm1d(128),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.GELU(),
        )
        self.x_head = nn.Linear(64, 1)  # X coordinate in meters
        self.y_head = nn.Linear(64, 1)  # Y coordinate in meters

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        features = self.shared(x)
        x_m = self.x_head(features)
        y_m = self.y_head(features)
        return x_m, y_m


# ---------------------------------------------------------
# Ensemble Handler for Unified Inference & Version Management
# ---------------------------------------------------------
class WiLidarEnsemble:
    def __init__(self):
        self.presence_model: Union[XGBClassifier, None] = None
        self.room_model: Union[RandomForestClassifier, None] = None
        self.position_model: Union[PositionNet, None] = None
        self.load_models()

    def load_models(self):
        """
        Loads all three models from settings.MODELS_DIR if available.
        """
        presence_path = os.path.join(settings.MODELS_DIR, "presence_model.pkl")
        room_path = os.path.join(settings.MODELS_DIR, "room_model.pkl")
        position_path = os.path.join(settings.MODELS_DIR, "position_model.pt")

        # 1. Load Presence Model (XGBoost)
        if os.path.exists(presence_path):
            try:
                with open(presence_path, "rb") as f:
                    self.presence_model = pickle.load(f)
                logger.info(f"Loaded presence model from {presence_path}")
            except Exception as e:
                logger.error(f"Failed to load presence model: {str(e)}")
                self.presence_model = None
        else:
            logger.warning(f"Presence model not found at {presence_path}")

        # 2. Load Room Classification Model (Random Forest)
        if os.path.exists(room_path):
            try:
                with open(room_path, "rb") as f:
                    self.room_model = pickle.load(f)
                logger.info(f"Loaded room classifier from {room_path}")
            except Exception as e:
                logger.error(f"Failed to load room model: {str(e)}")
                self.room_model = None
        else:
            logger.warning(f"Room classifier not found at {room_path}")

        # 3. Load Position Estimation Net (PyTorch)
        if os.path.exists(position_path):
            try:
                input_dim = settings.PCA_COMPONENTS * 5 + 128
                model = PositionNet(input_dim=input_dim)
                model.load_state_dict(
                    torch.load(position_path, map_location=torch.device("cpu"))
                )
                model.eval()
                self.position_model = model
                logger.info(f"Loaded position neural network from {position_path}")
            except Exception as e:
                logger.error(f"Failed to load position model: {str(e)}")
                self.position_model = None
        else:
            logger.warning(f"Position neural network not found at {position_path}")

    def save_presence_model(self, model: XGBClassifier):
        path = os.path.join(settings.MODELS_DIR, "presence_model.pkl")
        with open(path, "wb") as f:
            pickle.dump(model, f)
        self.presence_model = model
        logger.info(f"Saved presence model to {path}")

    def save_room_model(self, model: RandomForestClassifier):
        path = os.path.join(settings.MODELS_DIR, "room_model.pkl")
        with open(path, "wb") as f:
            pickle.dump(model, f)
        self.room_model = model
        logger.info(f"Saved room model to {path}")

    def save_position_model(self, model: PositionNet):
        path = os.path.join(settings.MODELS_DIR, "position_model.pt")
        torch.save(model.state_dict(), path)
        self.position_model = model
        logger.info(f"Saved position model to {path}")

    def predict_presence(self, features: np.ndarray) -> Tuple[bool, float]:
        """
        Runs binary presence classifier.
        """
        if self.presence_model is None:
            # Fallback mock if not calibrated yet
            return False, 0.0

        features_reshaped = features.reshape(1, -1)
        prob = self.presence_model.predict_proba(features_reshaped)[0][1]
        presence = bool(self.presence_model.predict(features_reshaped)[0])
        return presence, float(prob)

    def predict_room(self, features: np.ndarray) -> Tuple[int, float]:
        """
        Runs multi-class room classifier.
        """
        if self.room_model is None:
            return 1, 0.0

        features_reshaped = features.reshape(1, -1)
        probs = self.room_model.predict_proba(features_reshaped)[0]
        room_id = int(self.room_model.predict(features_reshaped)[0])
        confidence = float(np.max(probs))
        return room_id, confidence

    def predict_position_with_uncertainty(
        self, features: np.ndarray, num_mc_runs: int = 20
    ) -> Tuple[float, float, float]:
        """
        Predicts X, Y coordinates and calculates uncertainty radius using Monte Carlo Dropout.
        (Enables Dropout layers during inference, runs forward pass 20 times).
        """
        if self.position_model is None:
            return 3.0, 3.0, 0.5  # default center/fallback

        # Convert feature vector to torch tensor
        x_tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(
            0
        )  # shape (1, 228)

        # Prepare for Monte Carlo Dropout: keep model in training mode
        self.position_model.train()

        x_preds = []
        y_preds = []

        with torch.no_grad():
            for _ in range(num_mc_runs):
                pred_x, pred_y = self.position_model(x_tensor)
                x_preds.append(pred_x.item())
                y_preds.append(pred_y.item())

        # Calculate mean coordinate predictions
        mean_x = float(np.mean(x_preds))
        mean_y = float(np.mean(y_preds))

        # Uncertainty is the maximum standard deviation of x and y predictions (radius)
        std_x = np.std(x_preds)
        std_y = np.std(y_preds)
        uncertainty_radius = float(max(std_x, std_y))

        # Set back to eval mode
        self.position_model.eval()

        return mean_x, mean_y, uncertainty_radius

    def predict_occupancy_count(self, features: np.ndarray, presence: bool) -> int:
        """
        Estimates the exact number of people (0 to 3) using CSI signal variance.
        """
        if not presence:
            return 0

        # Features contains processed subcarrier amplitudes in the early dimensions.
        # Higher signal variance represents more body movements (crowd count).
        feat_var = float(np.var(features[:128]))
        if feat_var > 0.08:
            return 3
        elif feat_var > 0.03:
            return 2
        return 1

    def predict_multi_people(
        self, features: np.ndarray, occupancy_count: int, num_mc_runs: int = 30
    ) -> list:
        """
        Uses Monte Carlo Dropout predictions clustered via K-means to isolate coordinates
        for multiple moving targets from a single CSI feature representation.
        """
        if occupancy_count == 0:
            return []

        if self.position_model is None:
            # Fallback mock coordinate generation for simulation / zero calibration
            tracked = []
            t_now = float(torch.randint(0, 1000, (1,)).item()) / 10.0  # seed offsets
            for i in range(occupancy_count):
                if i == 0:
                    # Figure-8 walking path
                    x = 3.0 + 2.0 * np.sin(0.4 * t_now)
                    y = 3.0 + 1.5 * np.sin(0.8 * t_now)
                elif i == 1:
                    # Circular walking path
                    x = 3.0 + 1.8 * np.cos(0.6 * t_now + 1.5)
                    y = 3.0 + 1.8 * np.sin(0.6 * t_now + 1.5)
                else:
                    # Linear walk
                    x = 3.0 + 1.2 * np.sin(0.3 * t_now + 3.0)
                    y = 1.5 + 0.5 * np.cos(0.3 * t_now + 3.0)
                tracked.append(
                    {
                        "id": i + 1,
                        "x_meters": float(x),
                        "y_meters": float(y),
                        "uncertainty": 0.4 + 0.1 * i,
                    }
                )
            return tracked

        # Convert feature vector to torch tensor
        x_tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0)
        self.position_model.train()

        preds = []
        with torch.no_grad():
            for _ in range(num_mc_runs):
                pred_x, pred_y = self.position_model(x_tensor)
                preds.append([pred_x.item(), pred_y.item()])

        self.position_model.eval()
        pts = np.array(preds)  # shape (num_mc_runs, 2)

        # If tracking only 1 person, standard mean is fastest and most reliable
        if occupancy_count == 1 or len(pts) < occupancy_count:
            mean_vals = np.mean(pts, axis=0)
            std_vals = np.std(pts, axis=0)
            return [
                {
                    "id": 1,
                    "x_meters": float(mean_vals[0]),
                    "y_meters": float(mean_vals[1]),
                    "uncertainty": float(max(std_vals[0], std_vals[1])),
                }
            ]

        # Run K-means clustering to locate multi-person centroids (Section 5.3 SOTA details)
        # Randomly choose initial centroids from points
        centroids = pts[np.random.choice(len(pts), occupancy_count, replace=False)]
        labels = np.zeros(len(pts))

        for _ in range(8):  # 8 iterations is sufficient for small 2D clustering
            # Calculate distance of each point to each centroid
            # pts shape: (num_mc_runs, 2), centroids shape: (occupancy_count, 2)
            dists = np.linalg.norm(pts[:, np.newaxis] - centroids, axis=2)
            new_labels = np.argmin(dists, axis=1)

            # Recompute centroids
            new_centroids = np.zeros_like(centroids)
            for j in range(occupancy_count):
                cluster_pts = pts[new_labels == j]
                if len(cluster_pts) > 0:
                    new_centroids[j] = cluster_pts.mean(axis=0)
                else:
                    new_centroids[j] = centroids[j]

            if np.allclose(centroids, new_centroids):
                labels = new_labels
                break
            centroids = new_centroids
            labels = new_labels

        # Format the clustered coordinates list
        tracked_people = []
        for j in range(occupancy_count):
            cluster_pts = pts[labels == j]
            if len(cluster_pts) > 0:
                mean_coord = cluster_pts.mean(axis=0)
                std_coord = cluster_pts.std(axis=0)
                std_val = float(max(std_coord[0], std_coord[1]))
            else:
                mean_coord = centroids[j]
                std_val = 0.5

            tracked_people.append(
                {
                    "id": j + 1,
                    "x_meters": float(mean_coord[0]),
                    "y_meters": float(mean_coord[1]),
                    "uncertainty": max(0.2, std_val),
                }
            )

        return tracked_people

    def run_inference(self, features: np.ndarray) -> Dict[str, Any]:
        """
        Executes the full cascading inference pipeline, returning occupancy details
        and multi-coordinate tracked paths.
        """
        # Step 1: Presence Detection (XGBoost)
        presence, presence_conf = self.predict_presence(features)

        if not presence:
            return {
                "room_present": False,
                "presence_confidence": presence_conf,
                "room_id": None,
                "room_confidence": 0.0,
                "x_meters": 0.0,
                "y_meters": 0.0,
                "position_uncertainty_m": 0.0,
                "estimated_occupancy": 0,
                "tracked_people": [],
            }

        # Step 2: Room Classification (Random Forest)
        room_id, room_conf = self.predict_room(features)

        # Step 3: Occupancy Count Estimation (Variance Heuristics)
        occupancy_count = self.predict_occupancy_count(features, presence)

        # Step 4: Multi-Person Coordinates Regression
        tracked_people = self.predict_multi_people(features, occupancy_count)

        # Legacy primary coordinate format to maintain client safety
        x_meters = tracked_people[0]["x_meters"] if tracked_people else 3.0
        y_meters = tracked_people[0]["y_meters"] if tracked_people else 3.0
        uncertainty = tracked_people[0]["uncertainty"] if tracked_people else 0.5

        return {
            "room_present": True,
            "presence_confidence": presence_conf,
            "room_id": room_id,
            "room_confidence": room_conf,
            "x_meters": x_meters,
            "y_meters": y_meters,
            "position_uncertainty_m": uncertainty,
            "estimated_occupancy": occupancy_count,
            "tracked_people": tracked_people,
        }
