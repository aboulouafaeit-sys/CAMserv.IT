# CAMserv Phase 27.2 — Tracking & Traffic Analytics Integration Report

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 27.2 — Gate 27.2-E  
**Architecture:** Single Organization / Local-First Deployment  
**Audited Components:** `src/camserv/intelligence/traffic.py` & `src/camserv/intelligence/contracts.py`

---

## 1. Executive Summary

Phase 27.1 highlighted that vehicle velocity calculations in km/h based on scalar `pixels_per_meter` suffer from severe perspective distortion (foreshortening), rendering distant speeds inaccurately high or near-camera speeds inaccurately low.

Gate 27.2-E integrated $3\times3$ planar road homography matrix transformation into `CameraCalibration` and `TrafficAnalyticsEngine`. When a calibrated homography matrix is present, image coordinates $(u, v)$ are projected to ground plane $(X_w, Y_w)$ in meters, rectifying foreshortening and enabling accurate real-world road speed measurement.

---

## 2. Projective Geometry & Homography Formulation

The 2D planar homography transforms image pixel coordinates $[u, v, 1]^T$ to world ground coordinates $[X_w, Y_w, W]^T$:

$$\begin{bmatrix} X' \\ Y' \\ W' \end{bmatrix} = \begin{bmatrix} h_{00} & h_{01} & h_{02} \\ h_{10} & h_{11} & h_{12} \\ h_{20} & h_{21} & h_{22} \end{bmatrix} \begin{bmatrix} u \\ v \\ 1 \end{bmatrix}$$

Ground plane coordinates (meters):
$$X_w = \frac{X'}{W'}, \quad Y_w = \frac{Y'}{W'}$$

For a vehicle track moving with velocity vector $(v_x, v_y)$ at bounding box center $(u, v)$:
1. Ground point at $t_0$: $(X_0, Y_0) = \text{project}(u, v)$
2. Ground point at $t_1$: $(X_1, Y_1) = \text{project}(u + v_x, v + v_y)$
3. Ground velocity (m/s):
$$V_{\text{ground}} = \sqrt{(X_1 - X_0)^2 + (Y_1 - Y_0)^2}$$
4. Calibrated road speed (km/h):
$$\text{Speed}_{\text{km/h}} = V_{\text{ground}} \times 3.6$$

---

## 3. Epistemic Speed Classification

`SpeedMeasurementStatus` enforces 3 truthful classifications:
- `CALIBRATED_ACCURATE`: Valid $3\times3$ homography matrix or documented calibration present. Km/h reported with calibrated error margin.
- `RELATIVE_MOVEMENT_ONLY`: Uncalibrated stream. Only relative pixel velocity ($\text{px/s}$) reported. Km/h explicitly `None`.
- `SPEED_UNAVAILABLE`: Stationary vehicles or insufficient track history to compute movement.

---

## 4. Traffic Intelligence Capabilities

The engine supports:
- Virtual directional counting lines with normal crossing vector evaluation (forward / reverse counts).
- Monitored polygon zones for dwell and occupancy tracking.
- Wrong-way travel detection against nominal lane flow vectors (antiparallel dot product $<-0.70$).
- Stationary vehicle detection (threshold $<5\text{ px/s}$ across $>20\text{ frames}$).
- Multi-tier congestion estimation (`FREE_FLOW`, `MODERATE`, `CONGESTED`, `STANDSTILL`).

---

## 5. Verification Evidence

In `tests/test_phase27_2_real_ai_and_process_isolation.py`:
- `test_planar_homography_perspective_speed_calibration()`: Vehicle with $100\text{ px/s}$ velocity projected through $3\times3$ homography yielding exact $18.0\text{ km/h}$, status `CALIBRATED_ACCURATE`, projection method `planar_homography_3x3`. PASS.
- In `tests/test_phase27_1_speed_calibration.py`: PASS.
- Total traffic analytics tests: 5 / 5 passing.
