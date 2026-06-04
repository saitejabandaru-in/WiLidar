| Configuration | Mean Error (m) | Std Dev (m) | Degradation Factor |
| --- | --- | --- | --- |
| Full Pipeline (DSP + Regression) | 8.037m | 5.114m | Baseline (1.0x) |
| Without Hampel (No Outlier Rejection) | 9.499m | 8.189m | 1.18x error increase |
| Without Phase Sanitization (Raw CFO) | 9.758m | 5.211m | 1.21x error increase |
| Without Butterworth (No Drift Rejection) | 2.780m | 1.279m | 0.35x error increase |
| No Filters (Raw Amplitudes & Phases) | 3.421m | 3.220m | 0.43x error increase |
