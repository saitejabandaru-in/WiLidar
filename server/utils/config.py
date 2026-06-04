import os
import yaml
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    def __init__(self):
        self.REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
        self.REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
        self.SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").lower() == "true"
        self.SIMULATOR_TARGET_IP = os.getenv("SIMULATOR_TARGET_IP", "127.0.0.1")

        self.UDP_HOST = os.getenv("UDP_HOST", "0.0.0.0")
        self.UDP_PORT = int(os.getenv("UDP_PORT", 5005))
        self.HEARTBEAT_PORT = int(os.getenv("HEARTBEAT_PORT", 5006))

        self.DATA_DIR = os.getenv("DATA_DIR", "data")
        self.SQLITE_DB_NAME = os.getenv("SQLITE_DB_NAME", "wilidar.sqlite")

        self.SAMPLING_RATE = int(os.getenv("SAMPLING_RATE", 100))  # 100 Hz
        self.NTP_SERVER = os.getenv("NTP_SERVER", "pool.ntp.org")

        # Load YAML configuration if it exists
        self.yaml_config = {}
        config_yaml_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml"
        )
        if os.path.exists(config_yaml_path):
            try:
                with open(config_yaml_path, "r") as f:
                    self.yaml_config = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[Config] Error loading config.yaml: {str(e)}")

    @property
    def SQLITE_PATH(self):
        os.makedirs(self.DATA_DIR, exist_ok=True)
        return os.path.join(self.DATA_DIR, self.SQLITE_DB_NAME)

    @property
    def MODELS_DIR(self):
        path = os.path.join(self.DATA_DIR, "models")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def BACKUPS_DIR(self):
        path = os.path.join(self.DATA_DIR, "backups")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def HAMPEL_WINDOW_SIZE(self):
        return self.yaml_config.get("dsp", {}).get("hampel", {}).get("window_size", 10)

    @property
    def HAMPEL_N_SIGMAS(self):
        return self.yaml_config.get("dsp", {}).get("hampel", {}).get("n_sigmas", 3.0)

    @property
    def BUTTERWORTH_LOWCUT(self):
        return self.yaml_config.get("dsp", {}).get("butterworth", {}).get("lowcut", 0.1)

    @property
    def BUTTERWORTH_HIGHCUT(self):
        return (
            self.yaml_config.get("dsp", {}).get("butterworth", {}).get("highcut", 10.0)
        )

    @property
    def BUTTERWORTH_ORDER(self):
        return self.yaml_config.get("dsp", {}).get("butterworth", {}).get("order", 4)

    @property
    def PCA_COMPONENTS(self):
        return self.yaml_config.get("dsp", {}).get("pca", {}).get("n_components", 20)

    @property
    def PYTORCH_MODEL_PARAMS(self):
        return self.yaml_config.get("models", {}).get("pytorch_position_net", {})


settings = Config()
