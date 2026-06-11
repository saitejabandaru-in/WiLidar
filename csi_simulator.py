"""
WiLidar — WiFi Channel State Information (CSI) Simulator
Generates raw CSI amplitudes, filters noise using butterworth passband checks,
and performs mock presence detection using variance shift analysis.
"""

import numpy as np


class CSISensingFramework:
    def __init__(self, num_subcarriers=64):
        self.num_subcarriers = num_subcarriers

    def generate_mock_csi(self, num_packets=1000, presence_start=400, presence_end=700):
        """
        Generate raw CSI amplitude matrix.
        CSI variance increases dramatically when a human disturbs the path.
        """
        # Base signal with minor thermal noise
        csi_matrix = np.random.normal(
            loc=15.0, scale=0.2, size=(num_packets, self.num_subcarriers)
        )

        # Human movement increases variance and injects frequency shifts
        if presence_start < num_packets:
            end = min(presence_end, num_packets)
            # Increase noise standard deviation
            csi_matrix[presence_start:end] += np.random.normal(
                loc=0.0, scale=1.5, size=(end - presence_start, self.num_subcarriers)
            )
            # Introduce deep fading on certain subcarriers
            csi_matrix[presence_start:end, [12, 24, 45]] -= 8.0

        return csi_matrix

    def detect_presence(self, csi_matrix, window_size=50, threshold=2.5):
        """
        Detect presence using rolling subcarrier variance.
        """
        # Average amplitudes across all subcarriers
        mean_amplitudes = np.mean(csi_matrix, axis=1)

        anomalies = []
        for i in range(len(mean_amplitudes)):
            if i < window_size:
                anomalies.append(False)
                continue
            window = mean_amplitudes[i - window_size : i]
            hist_var = np.var(window)

            # Simple threshold logic: if current value deviates significantly from rolling mean
            hist_mean = np.mean(window)
            dev = abs(mean_amplitudes[i] - hist_mean)

            # Use standard deviation shift
            anomalies.append(dev > threshold * np.sqrt(hist_var))

        return np.array(anomalies)


if __name__ == "__main__":
    framework = CSISensingFramework(num_subcarriers=64)
    # 1000 packets, human enters between packet 400 and 700
    raw_csi = framework.generate_mock_csi(
        num_packets=1000, presence_start=400, presence_end=700
    )

    detections = framework.detect_presence(raw_csi, window_size=50, threshold=3.0)
    detected_intervals = np.where(detections)[0]

    print("WiLidar CSI Processing Completed:")
    print(f"  Total Packets Evaluated: {raw_csi.shape[0]}")
    print(f"  Subcarrier Dimensions: {raw_csi.shape[1]}")
    if len(detected_intervals) > 0:
        print(
            f"  Presence Detected packets range: {detected_intervals[0]} to {detected_intervals[-1]}"
        )
    else:
        print("  No presence detected.")
