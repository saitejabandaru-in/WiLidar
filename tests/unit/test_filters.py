import numpy as np
from server.processing.filters import (
    hampel_filter_1d,
    butterworth_bandpass,
    phase_sanitize,
)


def test_hampel_filter():
    """
    Test Hampel outlier removal. Inject a massive spike and verify it is replaced by median.
    """
    # 20 flat samples
    data = np.ones(20, dtype=np.float32) * 5.0
    # Inject massive spike outlier at index 10
    data[10] = 500.0

    cleaned = hampel_filter_1d(data, window_size=5, t0=3.0)

    # Outlier should have been replaced with median (5.0)
    assert cleaned[10] < 10.0
    assert cleaned[10] == 5.0


def test_butterworth_bandpass():
    """
    Test Butterworth bandpass filter removes low/high frequency noise.
    """
    fs = 100.0
    t = np.arange(0, 5, 1 / fs)

    # Target frequency (human breath at 0.3 Hz)
    target_freq = 0.3
    signal = np.sin(2 * np.pi * target_freq * t)

    # Add low frequency drift (0.02 Hz) and high frequency noise (45 Hz)
    drift = np.sin(2 * np.pi * 0.02 * t) * 5.0
    noise = np.sin(2 * np.pi * 45 * t) * 0.5
    raw_signal = signal + drift + noise

    # Reshape to (num_frames, num_channels)
    raw_signal_2d = raw_signal.reshape(-1, 1)

    filtered = butterworth_bandpass(
        raw_signal_2d, lowcut=0.1, highcut=10.0, fs=fs, order=4
    )

    # Verify high frequency noise and low frequency drift are significantly attenuated
    # Filtered signal standard deviation should be smaller than raw signal standard deviation
    assert np.std(filtered) < 1.0
    assert np.std(filtered) < np.std(raw_signal_2d)


def test_phase_sanitize():
    """
    Test Phase Sanitization wraps phase and removes linear trends.
    """
    num_subcarriers = 64
    subcarrier_idx = np.arange(num_subcarriers)

    # Generate linear slope + constant offset phase pattern (simulate hardware artifacts)
    slope = 0.15
    offset = 1.2
    phase_pattern = slope * subcarrier_idx + offset

    # Create 5 identical frames of raw phase
    raw_phases = np.vstack([phase_pattern] * 5)

    sanitized = phase_sanitize(raw_phases)

    # After subtracting linear trend, the resulting phase across subcarriers should be flat (approx 0)
    # Average absolute value of sanitized phase should be very close to zero
    assert np.mean(np.abs(sanitized)) < 1e-4
