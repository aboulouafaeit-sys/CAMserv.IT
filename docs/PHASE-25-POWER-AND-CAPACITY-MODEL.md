# CAMserv — Performance, Power & Capacity Sizing Model

**Document ID:** MOD-P25-SIZING-2026-009  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25 — Hardware Appliance Engineering & Physical Reliability Qualification  
**Classification:** Systems Engineering & Mathematical Capacity Standard  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Hardware Systems Architect, Embedded Linux Engineer, Storage Reliability Engineer, Network Surveillance Architect, Security Engineer & Release Qualification Authority  

---

## 1. Executive Summary & Sizing Methodology

Accurate hardware sizing is essential for enterprise security installations. Under-sizing an appliance results in dropped frames, system crashes, and shortened disk life. Over-sizing results in unnecessary capital and electrical operating expenses.

This document establishes the verified mathematical sizing formulas implemented in `ApplianceCatalog` and provides exhaustive capacity, retention, and electrical power tables across all supported CAMserv appliance tiers.

### Attribution Legend
- **[MEASURED]:** Directly measured on physical host test hardware (Intel Core i7-12700H, Micron 2450 NVMe SSD).
- **[CALCULATED]:** Deterministically computed from verified mathematical equations.
- **[ESTIMATED]:** Standard surveillance industry baseline derived from manufacturer datasheets.

---

## 2. Core Mathematical Formulations

### 2.1 Ingestion Network Bandwidth ($B_{\text{net}}$)
Incoming surveillance network bandwidth must account for RTP/RTSP transport headers and TCP/UDP packet overhead:
$$B_{\text{net}} = \frac{N \times R_{\text{kbps}} \times (1 + \alpha)}{1000} \quad [\text{Mbps}]$$
Where:
- $N$ = Number of active camera streams.
- $R_{\text{kbps}}$ = Elementary stream video bitrate in kilobits per second.
- $\alpha$ = Network protocol packet overhead ($\alpha = 0.08$ or $8\%$ for RTP/RTSP/IP headers).

### 2.2 Daily Storage Consumption Rate ($S_{\text{daily}}$)
Storage consumption accounts for raw video elementary streams, keyframe index metadata, and filesystem sector allocation:
$$S_{\text{daily}} = \frac{N \times R_{\text{kbps}} \times (1 + \beta) \times 86,400}{8 \times 1,024 \times 1,024} \quad [\text{GB / Day}]$$
Where:
- $\beta$ = Container muxing and keyframe index overhead ($\beta = 0.05$ or $5\%$).
- $86,400$ = Seconds per calendar day.
- $8 \times 1024 \times 1024$ = Bits per Gigabyte ($2^{23}$).

### 2.3 Continuous Retention Duration ($D_{\text{retention}}$)
The maximum continuous retention duration supported by a given storage pool before automated FIFO pruning:
$$D_{\text{retention}} = \frac{C_{\text{usable}}}{S_{\text{daily}}} \quad [\text{Days}]$$
Where:
- $C_{\text{usable}}$ = Usable formatted storage capacity in Gigabytes (after RAID parity and $10\%$ safety reserve).

### 2.4 Electrical Power & Thermal Heat Dissipation
Daily electrical consumption and BTU heat dissipation:
$$E_{\text{daily}} = \frac{P_{\text{watts}} \times 24}{1,000} \quad [\text{kWh / Day}]$$
$$Q_{\text{thermal}} = P_{\text{watts}} \times 3.41214 \quad [\text{BTU / Hour}]$$

---

## 3. Storage Retention Capacity Tables

### 3.1 1080p30 H.265 / HEVC Stream Profile ($R_{\text{kbps}} = 2,500\text{ kbps}$)
*Daily Storage Consumption per Camera: **$27.03\text{ GB/day}$** [CALCULATED].*

| Cameras ($N$) | Daily Ingest (GB/Day) | 7 Days Retention | 14 Days Retention | 30 Days Retention | 60 Days Retention | 90 Days Retention | 180 Days Retention | 365 Days Retention |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **4 Cams** | **108.1 GB** | 756.7 GB | 1.51 TB | 3.24 TB | 6.48 TB | 9.72 TB | 19.44 TB | 39.42 TB |
| **8 Cams** | **216.3 GB** | 1.51 TB | 3.02 TB | 6.48 TB | 12.96 TB | 19.44 TB | 38.88 TB | 78.84 TB |
| **16 Cams** | **432.5 GB** | 3.02 TB | 6.05 TB | 12.97 TB | 25.95 TB | 38.92 TB | 77.85 TB | 157.68 TB |
| **32 Cams** | **865.1 GB** | 6.05 TB | 12.10 TB | 25.95 TB | 51.90 TB | 77.85 TB | 155.70 TB | 315.36 TB |
| **64 Cams** | **1,730.2 GB** | 12.10 TB | 24.20 TB | 51.90 TB | 103.80 TB | 155.70 TB | 311.40 TB | 630.72 TB |

---

### 3.2 1080p30 H.264 High Profile ($R_{\text{kbps}} = 4,000\text{ kbps}$)
*Daily Storage Consumption per Camera: **$43.25\text{ GB/day}$** [CALCULATED].*

| Cameras ($N$) | Daily Ingest (GB/Day) | 7 Days Retention | 14 Days Retention | 30 Days Retention | 60 Days Retention | 90 Days Retention | 180 Days Retention | 365 Days Retention |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **4 Cams** | **173.0 GB** | 1.21 TB | 2.42 TB | 5.19 TB | 10.38 TB | 15.57 TB | 31.14 TB | 63.07 TB |
| **8 Cams** | **346.0 GB** | 2.42 TB | 4.84 TB | 10.38 TB | 20.76 TB | 31.14 TB | 62.28 TB | 126.14 TB |
| **16 Cams** | **692.1 GB** | 4.84 TB | 9.68 TB | 20.76 TB | 41.52 TB | 62.28 TB | 124.56 TB | 252.28 TB |
| **32 Cams** | **1,384.2 GB** | 9.68 TB | 19.36 TB | 41.52 TB | 83.04 TB | 124.56 TB | 249.12 TB | 504.56 TB |
| **64 Cams** | **2,768.3 GB** | 19.36 TB | 38.72 TB | 83.04 TB | 166.08 TB | 249.12 TB | 498.24 TB | 1,009.12 TB |

---

### 3.3 4K15 High-Resolution H.265 Profile ($R_{\text{kbps}} = 8,000\text{ kbps}$)
*Daily Storage Consumption per Camera: **$86.51\text{ GB/day}$** [CALCULATED].*

| Cameras ($N$) | Daily Ingest (GB/Day) | 7 Days Retention | 14 Days Retention | 30 Days Retention | 60 Days Retention | 90 Days Retention | 180 Days Retention | 365 Days Retention |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **4 Cams** | **346.0 GB** | 2.42 TB | 4.84 TB | 10.38 TB | 20.76 TB | 31.14 TB | 62.28 TB | 126.14 TB |
| **8 Cams** | **692.1 GB** | 4.84 TB | 9.68 TB | 20.76 TB | 41.52 TB | 62.28 TB | 124.56 TB | 252.28 TB |
| **16 Cams** | **1,384.2 GB** | 9.68 TB | 19.36 TB | 41.52 TB | 83.04 TB | 124.56 TB | 249.12 TB | 504.56 TB |
| **32 Cams** | **2,768.3 GB** | 19.36 TB | 38.72 TB | 83.04 TB | 166.08 TB | 249.12 TB | 498.24 TB | 1,009.12 TB |
| **64 Cams** | **5,536.6 GB** | 38.72 TB | 77.44 TB | 166.08 TB | 332.16 TB | 498.24 TB | 996.48 TB | 2,018.24 TB |

---

## 4. Power Consumption & Thermal Dissipation Model

| Appliance Profile | Typical Power ($P_{\text{typ}}$) | Peak Budget ($P_{\text{max}}$) | Daily Electricity (kWh) | Annual Electricity (kWh) | Est. Annual Electric Cost ($0.15/kWh) | Thermal Heat Output (BTU/Hr) | Recommended Cooling Mode |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **CAMserv Edge** | **12.0 W** | 15.0 W | **0.288 kWh** | 105.1 kWh | $15.77 | 40.9 BTU/hr | Passive Convection |
| **CAMserv Standard** | **35.0 W** | 65.0 W | **0.840 kWh** | 306.6 kWh | $45.99 | 119.4 BTU/hr | Internal Quiet Fan |
| **CAMserv Professional**| **95.0 W** | 180.0 W | **2.280 kWh** | 832.2 kWh | $124.83 | 324.2 BTU/hr | Dual PWM Chassis Fans |
| **CAMserv Enterprise** | **320.0 W** | 550.0 W | **7.680 kWh** | 2,803.2 kWh | $420.48 | 1,091.9 BTU/hr | N+1 Server Fan Matrix |
