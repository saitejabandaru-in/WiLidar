# WiLidar: Open-Source WiFi CSI Sensing Framework

WiLidar is an open-source, device-free spatial intelligence and localization framework that processes multi-path Channel State Information (CSI) phase and amplitude variations. By analyzing subcarrier phase perturbations against baseline calibration models, it offers a high-resolution, privacy-preserving alternative to optical cameras and high-cost LiDAR networks at a fraction of the hardware complexity.

---

## 🌐 Live Interactive Sandbox

The static web showcase and interactive spatial sandbox dashboard is hosted publicly on GitHub Pages:
👉 **[Launch WiLidar Interactive Sandbox](https://saitejabandaru-in.github.io/WiLidar/)**

### Key Core Features of the Showcase
* **Interactive Floor Plan Room Mapper**: Real-time room occupancy coordinate mapping using simulated wireless path walks.
* **PCA Telemetry Oscilloscope**: Real-time signal visualization graphing the top three dominant eigenvalues extracted from multi-channel subcarrier phase variances.
* **Developer Hub**: Comprehensive documentation detailing local FastAPI REST API integration endpoints (`/api/status`, `/api/configure`, `/api/model/retrain`) for establishing hardware links with ESP32 nodes.

---

## 🔬 Research & Scientific Modeling

The signal modeling and spatial mapping algorithms are developed in affiliation with the **Department of Engineering** at the **University of Campania Luigi Vanvitelli (Caserta, Italy)**.

For mathematical derivations (RF CSI formulas, phase variances, covariance matrix projections) and academic benchmarks (median localization error $\le 0.75\text{m}$), visit the **[Scientific Methodology & Research Foundation Section](https://saitejabandaru-in.github.io/WiLidar/#section-research)** in the sandbox.

---

## 📄 License

This project is open-source and licensed under the MIT License.
