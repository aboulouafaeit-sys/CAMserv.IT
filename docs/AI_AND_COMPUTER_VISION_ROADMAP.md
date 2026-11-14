# CAMserv AI & Computer Vision Engineering Roadmap
**Document ID:** AI-ROADMAP-2026-001  
**Author:** Principal Computer Vision Engineer & AI Systems Lead  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Core Objective:** High-Speed Edge Neural Inference with Epistemic Transparency

---

## 1. Vision Architecture & Model Topologies

CAMserv transitions from crude bounding-box detection to **Cinematic Visual Intelligence** powered by lightweight, ultra-local instance segmentation and pose estimation models running in ONNX Runtime and NVIDIA TensorRT.

### 1.1 Model Selection Matrix
| Model Architecture | Task | Input Resolution | Edge Latency (RTX 3060) | CPU Latency (i7-12700) | Precision | Status in CAMserv |
|---|---|---|---|---|---|---|
| **YOLOv8n-seg** | Instance Segmentation & Polygons | $640 \times 640$ | $4.2\text{ ms}$ | $28.5\text{ ms}$ | FP16 / INT8 | **Primary Production Model** |
| **YOLOv11s-seg** | Enhanced Contours & Small Objects | $640 \times 640$ | $6.8\text{ ms}$ | $44.1\text{ ms}$ | FP16 / INT8 | **High-Assurance Deployment** |
| **YOLOv8n-pose** | 17-Keypoint Skeletal Estimation | $640 \times 640$ | $3.9\text{ ms}$ | $26.1\text{ ms}$ | FP16 / INT8 | **Active Biomechanics Model** |
| **RT-DETR-l** | Transformer-Based Dense Crowds | $640 \times 640$ | $14.5\text{ ms}$ | $112.0\text{ ms}$ | FP16 | **Evaluated for Enterprise Tier 4** |
| **ByteTrack Core** | Anonymous Multi-Object Tracking | Vectors | $< 1.0\text{ ms}$ | $1.8\text{ ms}$ | Native CPU | **Active Tracking Baseline** |
| **BoT-SORT** | Camera Motion Compensation (GMC) | Vectors + ORB | $2.5\text{ ms}$ | $6.2\text{ ms}$ | Native CPU | **Active PTZ / Moving Camera** |

---

## 2. Anonymous Multi-Object Tracking & Kinematics

### 2.1 Non-Biometric Identity Mandate
Under GDPR Article 9 and the EU AI Act, tracking must strictly avoid biometric fingerprinting or facial recognition embeddings.
* Every detected entity is assigned an ephemeral integer tracking ID ($ID \in \mathbb{N}$).
* Tracking relies exclusively on **spatial-temporal kinematics**:
  $$\mathbf{x}_k = [x, y, a, h, \dot{x}, \dot{y}, \dot{a}, \dot{h}]^T$$
* ID switches and fragmentation are minimized via two-stage Hungarian bipartite matching combining Kalman predicted state distance and IoU overlap.
* When an object departs the camera field of view for $> 30.0\text{s}$, its ID is permanently retired and its state vector purged from memory.

---

## 3. Threat Engine Calibration & Epistemic Uncertainty

### 3.1 Five-Factor Threat Scoring Formulation
The local deterministic threat engine calculates threat score $T \in [0, 100]$ without cloud LLM latency:
$$T = \min\left(100, \sum_{i=1}^5 w_i \cdot S_i\right)$$
Where:
1. $S_1$: Kinematic Velocity Anomaly ($\text{Running / Sudden Darting}$). Weight $w_1 = 20$.
2. $S_2$: Biomechanical Fall / Posture Alert ($\text{Torso Angle } > 60^\circ \text{ or Rapid Height Drop}$). Weight $w_2 = 25$.
3. $S_3$: Restricted Perimeter Breach ($\text{Geo-fence / Tripwire Incursion}$). Weight $w_3 = 30$.
4. $S_4$: Loitering & Dwelling Time ($\text{Stationary in Sensitive Zone } > 60\text{s}$). Weight $w_4 = 15$.
5. $S_5$: Unattended Luggage Persistence ($\text{Baggage Abandoned } > 180\text{s}$). Weight $w_5 = 10$.

### 3.2 Epistemic Uncertainty & Confidence Calibration
Raw neural network softmax outputs are notorious for overconfidence. CAMserv incorporates:
* **Platt Scaling / Isotonic Temperature Scaling:** Softmax probabilities $z_i$ are calibrated:
  $$\hat{p}_i = \sigma\left(\frac{z_i}{T_{cal}}\right)$$
* **Epistemic Transparency Flag:** Every inference payload includes:
  ```json
  {
    "is_prediction": true,
    "calibrated_confidence": 0.884,
    "confidence_interval_95": [0.821, 0.947],
    "model_topology": "yolov8n-seg.onnx",
    "inference_device": "cuda:0"
  }
  ```

---

## 4. Deterministic Bilingual Situation Narratives (Arabic & English)

To eliminate cloud LLM API recurring costs, token rate limits, and network latency, CAMserv features an embedded deterministic narrative generator:
* Formulates natural language situational summaries in **Arabic** and **English** within $< 0.1\text{ ms}$.
* Example Output:
  - *English:* "ALERT: Unauthorized subject detected breaching Restricted Perimeter Zone North. Subject displayed rapid running velocity (3.2 m/s). Immediate operator confirmation required."
  - *Arabic:* "تنبيه: تم رصد شخص غير مصرح به يخترق المنطقة المحظورة (البوابة الشمالية). أظهر الهدف سرعة جري عالية (3.2 م/ث). يتطلب تأكيد المشغل الفوري."
