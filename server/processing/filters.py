import numpy as np
import scipy.signal
from typing import Union


def phase_sanitize(
    raw_phases: np.ndarray, base_offset: Union[np.ndarray, None] = None
) -> np.ndarray:
    """
    Sanitizes raw CSI phase matrices to remove hardware-induced linear slope and random offset artifacts.

    Args:
        raw_phases (np.ndarray): 2D array of shape (num_frames, 64) containing raw phase values.
        base_offset (np.ndarray, optional): 1D array of shape (64,) representing the baseline mean of
                                            static empty-room phases to subtract.

    Returns:
        np.ndarray: Cleaned phase matrices of shape (num_frames, 64).
    """
    num_frames, num_subcarriers = raw_phases.shape
    subcarrier_idx = np.arange(num_subcarriers)
    sanitized_phases = np.zeros_like(raw_phases, dtype=np.float32)

    # 1. Unwrap phase to fix +/- PI wrapping discontinuities along subcarrier index axis
    unwrapped = np.unwrap(raw_phases, axis=1)

    # 2. Fit and remove linear trend per frame (due to clock offsets and linear delay)
    for t in range(num_frames):
        # Fit a 1st degree polynomial: unwrapped[t] = slope * subcarrier_idx + offset
        slope, intercept = np.polyfit(subcarrier_idx, unwrapped[t], 1)
        fitted_line = slope * subcarrier_idx + intercept
        sanitized_phases[t] = unwrapped[t] - fitted_line

    # 3. Remove constant phase offset by subtracting calibration empty-room baseline
    if base_offset is not None:
        sanitized_phases -= base_offset

    return sanitized_phases


def hampel_filter_1d(
    x: np.ndarray, window_size: int = 10, t0: float = 3.0
) -> np.ndarray:
    """
    Vectorized 1D Hampel filter for outlier removal.
    Replaces outliers with the rolling median rather than deleting them.

    Args:
        x (np.ndarray): 1D array (time series of a single subcarrier's amplitude).
        window_size (int): Size of the sliding window.
        t0 (float): Threshold scale (typically 3 * MAD).

    Returns:
        np.ndarray: Cleaned time series.
    """
    n = len(x)
    y = x.copy()
    half_w = window_size // 2

    for i in range(n):
        # Extract sliding window boundaries
        start = max(0, i - half_w)
        end = min(n, i + half_w + 1)
        window = x[start:end]

        median = np.median(window)
        mad = np.median(np.abs(window - median))

        # Avoid dividing by zero for flat segments
        scale = 1.4826
        sigma = max(scale * mad, 1e-4)
        if np.abs(x[i] - median) > t0 * sigma:
            y[i] = median

    return y


def hampel_filter_2d(
    matrix: np.ndarray, window_size: int = 10, t0: float = 3.0
) -> np.ndarray:
    """
    Applies Hampel filter to each subcarrier column in a 2D matrix (num_frames, num_subcarriers).
    """
    cleaned = np.zeros_like(matrix)
    num_subcarriers = matrix.shape[1]

    for i in range(num_subcarriers):
        cleaned[:, i] = hampel_filter_1d(matrix[:, i], window_size, t0)

    return cleaned


def butterworth_bandpass(
    data: np.ndarray,
    lowcut: float = 0.1,
    highcut: float = 10.0,
    fs: float = 100.0,
    order: int = 4,
) -> np.ndarray:
    """
    Applies a zero-phase Butterworth bandpass filter.
    Preserves phase characteristics (filtfilt) and rejects environmental drifts/electrical interference.

    Args:
        data (np.ndarray): 2D array of shape (num_frames, num_channels) to filter.
        lowcut (float): Lower frequency cutoff (Hz).
        highcut (float): Upper frequency cutoff (Hz).
        fs (float): Sampling frequency of the data (Hz).
        order (int): Order of the Butterworth filter.

    Returns:
        np.ndarray: Filtered signals of the same shape.
    """
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq

    # Generate Butterworth filter coefficients
    b, a = scipy.signal.butter(order, [low, high], btype="band")

    # Apply zero-phase filtering along time axis (axis=0)
    # filtfilt avoids shifting signal phases (Pitfall 6)
    filtered = scipy.signal.filtfilt(b, a, data, axis=0)
    return filtered
