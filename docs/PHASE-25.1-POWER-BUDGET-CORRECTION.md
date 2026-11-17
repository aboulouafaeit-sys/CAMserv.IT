# CAMserv — Phase 25.1 Appliance Power Budget & Electrical Redundancy Audit

**Document ID:** SPEC-P25.1-POWER-2026-002  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25.1 — Reliability Correction & Engineering Hardening  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Hardware Systems Architect, Electrical Power Engineer & Release Qualification Authority  
**Classification:** Systems Engineering & Electrical Sizing Standard  

---

## 1. Executive Summary & Audit Context

In Phase 25, an inconsistency was identified in the Enterprise appliance power model:
- The specification claimed a 680W worst-case power draw while simultaneously listing two NVIDIA GeForce RTX 4090 GPUs, 32 CPU cores, and 16 HDDs on dual 800W PSUs with a claimed 15% surviving-PSU margin.
- **Physical Reality:** A single unconstrained NVIDIA RTX 4090 draws up to $450\text{ W}$ at full load. Two RTX 4090s alone consume $900\text{ W}$, which immediately exceeds the total 800W continuous output of a single surviving PSU. When combined with CPU, memory, drives, and fans, the worst-case draw can exceed $1,500\text{ W}$.

This document provides a rigorous component-level electrical power audit, corrects the hardware configuration across all four appliance tiers, establishes realistic enterprise accelerator alternatives, mandates staggered HDD spin-up, and recalculates single surviving PSU capacities with thermal derating.

---

## 2. Component-by-Component Electrical Load Breakdown

### 2.1 Compute Processors (CPU Package Power)

| Processor Model | Architecture | Base TDP | Sustained Load (All Cores Recording) | PL2 / Turbo Peak Load | Notes |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Intel N100 / RK3588** | 4-8 Cores (Low-Power) | 6.0 W | 8.5 W | 12.0 W | Edge fanless profiles |
| **Intel Core i5-13500** | 14 Cores (6P + 8E) | 65.0 W | 55.0 W | 85.0 W | Base Standard NVR |
| **Intel Core i7-13700** | 16 Cores (8P + 8E) | 65.0 W | 75.0 W | 125.0 W | Base Professional NVR |
| **AMD EPYC 7302P / 9124**| 16–32 Server Cores | 155.0 W | 145.0 W | 200.0 W | Enterprise Base Server |

### 2.2 Storage Drives & Inrush Current

| Storage Component | Operating Power (Active Write) | Spin-Up / Inrush Power (12V Rail) | Inrush Duration | Staggered Spin-Up Management |
| :--- | :---: | :---: | :---: | :--- |
| **Industrial NVMe SSD (M.2)** | 3.5 W – 5.5 W | 6.0 W (Peak) | $< 100\text{ ms}$ | Negligible inrush impact |
| **Surveillance SATA HDD (3.5")** | 6.2 W | 20.4 W ($1.7\text{A} @ 12\text{V}$) | $2.5\text{ s} - 3.5\text{ s}$ | SAS/SATA controller enforces 2-drive stagger |
| **Enterprise SAS HDD (7200 RPM)**| 7.8 W | 24.0 W ($2.0\text{A} @ 12\text{V}$) | $3.5\text{ s} - 5.0\text{ s}$ | Broadcom MegaRAID enforces 2-drive stagger |

*Spin-up Inrush Analysis for 16 HDDs:*
- **Simultaneous Spin-up (Prohibited):** $16 \times 24.0\text{W} = \mathbf{384.0\text{ W}}$ transient spike on 12V rail alone.
- **Staggered Spin-up (Mandatory):** Staggering 2 drives every 2.0 seconds limits maximum simultaneous spin-up load to:  
  $$P_{\text{hdd\_inrush}} = (14 \times 7.8\text{W}) + (2 \times 24.0\text{W}) = 109.2\text{W} + 48.0\text{W} = \mathbf{157.2\text{ W}} \quad [\text{Sustained Transient Peak}]$$

### 2.3 Video & AI Accelerators

| Accelerator | Architecture | Typical Surveillance Load | Max TGP / Board Power | Suitability for N+1 Redundancy |
| :--- | :--- | :---: | :---: | :--- |
| **Intel UHD Graphics 770** | Integrated iGPU | 8.0 W | 15.0 W | Excellent (Included in CPU budget) |
| **NVIDIA RTX 4060 (8GB)** | Discrete Ada Lovelace | 65.0 W | 115.0 W | Excellent for 1U/2U Professional NVR |
| **NVIDIA RTX 4000 Ada SFF** | Low-Profile Enterprise | 50.0 W | 70.0 W | Ideal for 2U Enterprise Server |
| **NVIDIA L4 (24GB)** | PCIe Single-Slot | 55.0 W | 72.0 W | Ideal for Multi-Stream Enterprise AI |
| **NVIDIA RTX 4090 (24GB)** | Consumer Flagship | 180.0 W (clamped) | 450.0 W (unclamped) | **UNSAFE for 800W Redundant PSU** unless clamped to 150W |
| **NVIDIA L40S (48GB)** | Data Center | 160.0 W (clamped) | 350.0 W (unclamped) | Requires 1600W Titanium PSUs if dual unconstrained |

---

## 3. Reconciled Appliance Electrical Power Profiles

### 3.1 Profile A — Low-Power / Entry Appliance (`PROFILE_A_LOW_POWER`)
- **Target Deployment:** Remote gatehouses, solar substations, kiosks.
- **Configuration:** Rockchip RK3588 (8 cores) or Intel N100 (4 cores), 8GB RAM, 512GB Industrial NVMe SSD.
- **Discrete GPU Requirement:** NONE (Zero discrete GPU).

| Load State | Compute Core | Memory & Board | NVMe SSD | Networking | Total Power (DC) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Typical Operating** | 6.5 W | 3.0 W | 1.8 W | 0.7 W | **12.0 W** |
| **Maximum Workload** | 9.5 W | 3.5 W | 3.5 W | 1.5 W | **18.0 W** |
| **Transient Peak** | 12.0 W | 4.0 W | 4.5 W | 1.5 W | **22.0 W** |

- **Power Supply:** 40W 12V/24V DC Terminal Block.
- **Safety Margin:** $\frac{40 - 22}{22} \times 100\% = \mathbf{81.8\% \text{ Headroom}}$.

---

### 3.2 Profile B — Standard Appliance (`PROFILE_B_STANDARD`)
- **Target Deployment:** Small-to-medium business, retail stores, clinics.
- **Configuration:** Intel Core i5-13500 (14 cores), 16GB DDR5, 512GB NVMe + 2x 4TB SATA CMR HDDs.
- **Discrete GPU Requirement:** NONE (Zero discrete GPU; uses Intel UHD 770 QSV / CPU).

| Load State | CPU (i5-13500) | Motherboard & RAM | NVMe SSD | 2x HDDs | Fans & Misc | Total Power (AC) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Typical Operating** | 22.0 W | 18.0 W | 2.5 W | 12.4 W | 3.5 W | **58.4 W** |
| **Maximum Workload** | 55.0 W | 22.0 W | 4.5 W | 14.0 W | 6.0 W | **101.5 W** |
| **Worst-Case Spin-Up**| 65.0 W | 24.0 W | 5.0 W | 38.0 W (inrush) | 7.0 W | **139.0 W** |

- **Power Supply:** 250W 80-Plus Bronze Internal PSU. (Corrected from 150W to provide reliable spin-up headroom).
- **Safety Margin:** $\frac{250 - 139}{139} \times 100\% = \mathbf{79.9\% \text{ Headroom}}$.

---

### 3.3 Profile C — Professional Appliance (`PROFILE_C_PROFESSIONAL`)
- **Target Deployment:** Logistics warehouses, multi-building corporate offices.
- **Configuration:** Intel Core i7-13700 (16 cores), 32GB DDR5, 1TB NVMe + 4x 8TB SATA CMR HDDs.
- **Discrete GPU:** Optional NVIDIA RTX 4060 (8GB, 115W TGP). Base configuration runs CPU/iGPU.

| Load State | CPU | MB & RAM | NVMe | 4x HDDs (Staggered) | Opt. GPU (RTX 4060) | Fans | Total Load |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Base Typical (No GPU)** | 35.0 W | 24.0 W | 3.0 W | 24.8 W | 0.0 W | 6.0 W | **92.8 W** |
| **Base Worst-Case (No GPU)** | 115.0 W | 28.0 W | 6.0 W | 52.0 W | 0.0 W | 12.0 W | **213.0 W** |
| **Full Typical (with GPU)** | 45.0 W | 26.0 W | 3.5 W | 24.8 W | 65.0 W | 8.0 W | **172.3 W** |
| **Full Worst-Case (with GPU)**| 125.0 W | 30.0 W | 6.5 W | 52.0 W | 115.0 W | 15.0 W | **343.5 W** |

- **Power Supply:** Dual Redundant 500W 80-Plus Gold PSUs (N+1).
- **Single Surviving PSU Capacity:** $500\text{ W}$ continuous.
- **Surviving Headroom under Full Worst-Case Load:**  
  $$\text{Margin} = \frac{500 - 343.5}{343.5} \times 100\% = \mathbf{45.6\% \text{ Safety Margin}}$$
- **Thermal Derating (45°C ambient, 10% derating $\rightarrow 450\text{W}$):**  
  $$\text{Derated Margin} = \frac{450 - 343.5}{343.5} \times 100\% = \mathbf{31.0\% \text{ Safety Margin}}$$

---

### 3.4 Profile D — Enterprise Appliance (`PROFILE_D_ENTERPRISE`)

#### Configuration Archetypes:
1. **Base Enterprise Server (Zero Discrete GPU):**
   - Dual AMD EPYC 7302P / 9124, 64GB ECC Registered DDR5, 2x NVMe RAID-1, 16x 16TB Enterprise SAS HDDs, Quad 10GbE SFP+.
   - Pure CPU pass-through recording (32–64+ streams) + distributed analytics nodes.
2. **Enterprise Analytical Appliance (Power-Engineered Accelerators — Recommended):**
   - Base Server + Dual NVIDIA RTX 4000 Ada SFF ($2 \times 70\text{W} = 140\text{W}$) or Dual NVIDIA L4 ($2 \times 72\text{W} = 144\text{W}$).
3. **Enterprise Dense AI Appliance (Clamped Flagship Accelerators):**
   - Base Server + Dual NVIDIA RTX 4090 / Dual L40S with **mandatory hardware firmware power clamp to $150\text{ W}$ per card** ($300\text{W}$ total).

#### Electrical Load Table:

| Subsystem Component | Base Server (No GPU) | Base + Dual L4 (Rec) | Base + Dual RTX 4090 (Clamped) | Unclamped Dual 4090 (Prohibited) |
| :--- | :---: | :---: | :---: | :---: |
| **EPYC CPU (Max Package)** | 200.0 W | 200.0 W | 200.0 W | 250.0 W |
| **Motherboard, 64GB ECC, 10GbE** | 65.0 W | 65.0 W | 65.0 W | 70.0 W |
| **Boot NVMe RAID-1** | 7.0 W | 7.0 W | 7.0 W | 7.0 W |
| **16x Enterprise SAS HDDs (Staggered)** | 157.2 W | 157.2 W | 157.2 W | 384.0 W (Simultaneous) |
| **Chassis High-CFM Fan Matrix** | 35.0 W | 35.0 W | 35.0 W | 40.0 W |
| **PCIe Accelerators (Full Load)** | **0.0 W** | **144.0 W** | **300.0 W (Clamped)** | **900.0 W (Unclamped)** |
| **Worst-Case Simultaneous Draw** | **464.2 W** | **608.2 W** | **764.2 W** | $\mathbf{1,651.0\text{ W}}$ |
| **PSU Configuration** | Dual 800W (N+1) | Dual 800W (N+1) | Dual 800W (N+1) | Requires Dual 1600W Titanium |
| **Surviving Single PSU Rating** | 800 W | 800 W | 800 W | 800 W (FAILS - TRIPPED) |
| **Surviving Margin (Nominal)** | **+72.3%** | **+31.5%** | **+4.7%** | **-51.5% (OVERLOAD)** |
| **Surviving Margin (45°C Derated)** | **+55.1%** | **+18.4%** | **-5.8% (Borderline)**| **-56.4% (OVERLOAD)** |

---

## 4. Engineering Directives & Safety Mandates

1. **Mandatory SAS Staggered Drive Spin-Up:**
   All enterprise storage backplanes must configure SAS controller parameter `spinup_delay=2` and `spinup_group_size=2`. Un-staggered spin-up is prohibited.
2. **Discrete GPU Disqualification from Base Specification:**
   Surveillance core recording across all profiles operates with 100% throughput on CPU/integrated graphics. Discrete GPUs are strictly optional analytical accelerators.
3. **Enterprise GPU Selection Standard:**
   Enterprise installations requiring local deep neural analytics should select high-efficiency accelerators (e.g., NVIDIA L4 / RTX 4000 Ada SFF) rather than consumer flagship gaming GPUs.
4. **Mandatory Firmware Power Clamping if RTX 4090 is Deployed:**
   If a client specifically installs NVIDIA GeForce RTX 4090 GPUs in an 800W redundant enclosure, CAMserv startup scripts must enforce:
   ```bash
   nvidia-smi -i 0 -pl 150
   nvidia-smi -i 1 -pl 150
   ```
   Any system detecting unclamped RTX 4090 GPUs on dual 800W PSUs will flag a high-priority warning: `ELECTRICAL_SAFETY_HAZARD_INSUFFICIENT_REDUNDANT_PSU`.
