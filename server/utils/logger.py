import logging
import json
import os
import sys
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as single-line JSON structures.
    Useful for production log collectors.
    """

    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logger(
    name: str = "wilidar", level: str = "INFO", json_format: bool = False
) -> logging.Logger:
    """
    Configure and return a structured logger.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers if already configured
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Ensure logs directory exists if logging to file
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(
        os.path.join(log_dir, f"{name}.log"), encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# Default app logger
logger = setup_logger()
