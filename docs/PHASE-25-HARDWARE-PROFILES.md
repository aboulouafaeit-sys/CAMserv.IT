# CAMserv — Hardware Appliance Profiles Specification

**Document ID:** SPEC-P25-PROFILES-2026-003  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25 — Hardware Appliance Engineering & Physical Reliability Qualification  
**Classification:** Product Engineering & Hardware Sizing Standard  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Hardware Systems Architect, Embedded Linux Engineer, Storage Reliability Engineer, Network Surveillance Architect, Security Engineer & Release Qualification Authority  

---

## 1. Profile Philosophy: Capability-Based, Hardware-Adaptive Architecture

CAMserv strictly avoids artificial hardware gating and marketing-driven hardware mandates. 

### Core Architectural Principle:
**Zero Mandatory Discrete GPU Requirement.**  
Core surveillance video ingestion, frame verification, timestamp indexing, evidence packaging, cryptographic signing, and tier-0 storage archiving operate with zero dependency on discrete graphics processing units. Pure CPU pass-through packaging of native H.264 / H.265 elementary streams consumes $< 5\%$ CPU utilization on modern processors.

Accelerators (integrated GPUs, discrete GPUs, and NPUs) are strictly optional and dedicated to analytical enhancement (AI detection, object tracking, re-identification, visual forensic search). If an accelerator fails or is absent, the system operates uninterrupted on `CPU_UNIVERSAL` fallback mode.

CAMserv appliance profiles are defined by **measured workload envelopes**:
- Ingestion bitrates (Mbps)
- Decode throughput (Frames Per Second)
- Storage write bandwidth (MB/s)
- Sequential disk write latency percentiles ($p_{50}, p_{95}, p_{99}$)
- Thermal dissipation envelopes (°C)
- Electrical power margins under single-PSU failure (N+1 redundancy)

---

## 2. Standardized Appliance Profiles

### 2.1 CAMserv Edge / Low-Power Appliance (`PROFILE_A_LOW_POWER`)

| Engineering Dimension | Specification |
| :--- | :--- |
| **Profile Identifier** | `PROFILE_A_LOW_POWER` |
| **Target Deployment** | Remote electrical substations, gatehouses, retail kiosks, cellular perimeter nodes. |
| **Form Factor** | Ultra-compact fanless aluminum chassis (DIN-rail or VESA mount). |
| **CPU Architecture** | ARM64 (Rockchip RK3588, 8 cores) or x86_64 (Intel Processor N100, 4 cores). |
| **Minimum Memory** | 8 GB LPDDR4x / DDR4 (Minimum 6 GB available for runtime buffers). |
| **Storage Architecture** | 32GB eMMC 5.1 (OS root) + 512GB/1TB Industrial NVMe SSD (M.2 2280 PCIe 3.0, high TBW pSLC/TLC cache). |
| **Network Interfaces** | Dual 1GbE RJ45 (Port 1: Isolated Camera Subnet; Port 2: Management / Cellular Gateway). |
| **Video Decoding** | Native CPU pass-through recording; hardware Rockchip MPP or Intel QSV/VA-API decoding where available. |
| **AI Inference (Optional)**| Integrated 6 TOPS NPU (RKNN) or Intel OpenVINO / CPU ONNX Runtime. |
| **Discrete GPU** | **NONE (Not Supported / Not Required).** |
| **Cooling & Thermal** | 100% Passive convection cooling via monolithic finned chassis; thermal limit 75°C. |
| **Power Consumption** | Typical: 12.0W; Peak: 15.0W; Worst-Case: 18.0W; Wide DC input 9V–36V terminal block (40W PSU). |
| **Workload Envelope** | 1 to 4 streams continuous 1080p30 H.264/H.265 recording + edge motion detection. Max ceiling: 6 streams. |
| **Field Maintenance** | Sealed fanless unit. Maintenance via remote signed OTA updates or USB recovery flash. |
| **Known Limitations** | Limited RAM prevents running simultaneous dense multi-model neural re-ID pipelines; ambient ceiling <= 45°C. |

---

### 2.2 CAMserv Standard Appliance (`PROFILE_B_STANDARD`)

| Engineering Dimension | Specification |
| :--- | :--- |
| **Profile Identifier** | `PROFILE_B_STANDARD` |
| **Target Deployment** | Small-to-medium commercial offices, retail storefronts, primary schools, medical clinics. |
| **Form Factor** | Compact desktop mini-tower or shallow-depth 1U rackmount chassis. |
| **CPU Architecture** | x86_64 (Intel Core i3/i5 12th/13th/14th Gen or AMD Ryzen 5 5600G / Embedded, 6–14 cores). |
| **Minimum Memory** | 16 GB DDR4/DDR5 (Dual-channel 3200 MT/s). |
| **Storage Architecture** | 512GB NVMe M.2 SSD (OS & Pre-Roll Staging) + 2x 4TB Surveillance SATA CMR HDDs (JBOD or RAID-1). |
| **Network Interfaces** | Dual 2.5GbE RJ45 (Port 1: Camera POE Switch VLAN; Port 2: Corporate LAN). |
| **Video Decoding** | Native CPU pass-through recording; Intel Quick Sync Video (QSV) / VA-API hardware decoding. |
| **AI Inference (Optional)**| Intel OpenVINO / ONNX Runtime FP16 on integrated graphics / host CPU. |
| **Discrete GPU** | **NONE (Base specification uses CPU/iGPU; discrete GPU strictly optional).** |
| **Cooling & Thermal** | Active quiet PWM internal chassis fan (<= 28 dBA); thermal limit 78°C. |
| **Power Consumption** | Typical: 35.0W; Peak: 65.0W; Worst-Case: 85.0W; Internal 150W 80-Plus Bronze power supply. |
| **Workload Envelope** | 4 to 16 streams continuous 1080p30 H.264/H.265 recording + zone analytics. Max ceiling: 20 streams. |
| **Field Maintenance** | Toolless chassis access; modular 3.5" drive caddies with SATA locking cables. |
| **Known Limitations** | Single AC power supply input (no redundant feed); not engineered for multi-camera 4K facial recognition. |

---

### 2.3 CAMserv Professional Appliance (`PROFILE_C_PROFESSIONAL`)

| Engineering Dimension | Specification |
| :--- | :--- |
| **Profile Identifier** | `PROFILE_C_PROFESSIONAL` |
| **Target Deployment** | Corporate headquarters, logistics distribution warehouses, manufacturing plants, hotel resorts. |
| **Form Factor** | 1U or 2U EIA-310 19" rackmount chassis with sliding rails. |
| **CPU Architecture** | x86_64 (Intel Core i7-13700 / AMD Ryzen 7 7700X, 8–16 physical cores). |
| **Minimum Memory** | 32 GB DDR5 (Dual-channel 4800 MT/s). |
| **Storage Architecture** | 1TB NVMe M.2 (OS & High-IOPS Staging Buffer) + 4x 8TB Surveillance SATA CMR HDDs (RAID-10 or RAID-5). |
| **Network Interfaces** | Dual 2.5GbE RJ45 + Dedicated 1GbE Out-of-Band Management port. |
| **Video Decoding** | Native CPU pass-through recording (100% full capacity without GPU); optional NVDEC / QSV decoding. |
| **AI Inference (Optional)**| **Optional Add-on:** Dedicated NVIDIA RTX 4060 (8GB VRAM) or Intel Arc A770 (16GB VRAM) via TensorRT / OpenVINO. Base config runs CPU/iGPU analytics. |
| **Cooling & Thermal** | Dual PWM ball-bearing hot-swappable cooling fans; thermal limit 82°C. |
| **Power Consumption** | **Base (CPU/iGPU):** Typical: 65W; Peak: 135W; Worst-Case: 160W.<br>**With Optional GPU:** Typical: 95.0W; Peak Budget: 180.0W; Worst-Case: 245.0W. |
| **Power Supply** | Dual 450W 80-Plus Gold redundant hot-swap PSUs. Single surviving PSU carries 245W worst-case load with 83% margin ($450\text{W} \ge 245\text{W}$). |
| **Workload Envelope** | 16 to 32 streams continuous 1080p30 or 8 streams 4K30 with real-time neural tracking. Max ceiling: 40 streams. |
| **Field Maintenance** | Front-accessible hot-swap 3.5" drive bays; hot-swappable fans; redundant hot-swap PSUs. |
| **Known Limitations** | Requires minimum 100mm front/rear rack clearance for directional airflow. |

---

### 2.4 CAMserv Enterprise Appliance (`PROFILE_D_ENTERPRISE`)

| Engineering Dimension | Specification |
| :--- | :--- |
| **Profile Identifier** | `PROFILE_D_ENTERPRISE` |
| **Target Deployment** | International airports, mass transit hubs, critical municipal infrastructure, university campuses. |
| **Form Factor** | 2U or 4U Heavy-Duty Enterprise Rackmount Server. |
| **CPU Architecture** | x86_64 (AMD EPYC 7003/9004 or Intel Xeon Scalable, 16–32 physical cores). |
| **Minimum Memory** | 64 to 128 GB ECC Registered DDR4/DDR5 (Multi-channel memory interleaving). |
| **Storage Architecture** | 2x 1TB NVMe M.2 (Hardware RAID-1 OS) + 8x to 16x 16TB Enterprise SAS/SATA CMR HDDs (RAID-6 dual parity). |
| **Network Interfaces** | Quad 10GbE SFP+ optical ports + Dual 2.5GbE RJ45 + Dedicated IPMI 2.0 / Redfish BMC port. |
| **Video Decoding** | Native CPU pass-through recording (100% full capacity without GPU); optional multi-GPU NVDEC pipeline. |
| **AI Inference (Optional)**| **Optional Add-on:** Dual NVIDIA RTX 4090 (24GB) or NVIDIA L40S (48GB) PCIe accelerators (TensorRT FP16/INT8). Base config runs CPU multi-core analytics. |
| **Cooling & Thermal** | N+1 Redundant, hot-swappable high-CFM chassis fan matrix; thermal limit 85°C. |
| **Power Consumption** | **Base (CPU/No GPU):** Typical: 180W; Peak: 310W; Worst-Case: 380W.<br>**With Dual Enterprise GPUs:** Typical: 320.0W; Peak: 550.0W; Worst-Case: 680.0W (dual GPU TDP + 32 CPU cores + 16 HDD spin-up inrush). |
| **Power Supply** | Dual 800W 80-Plus Platinum redundant hot-swap PSUs (N+1 redundancy). Single surviving PSU delivers 800W continuous capacity, exceeding worst-case 680W load with 15% safety headroom ($800\text{W} \ge 680\text{W}$, load is $85\%$ of single PSU rating). |
| **Workload Envelope** | 32 to 64+ streams continuous 1080p30 / 4K30 with full multi-camera re-identification. Max ceiling: 80–128 streams. |
| **Field Maintenance** | 100% Hot-swappable disks, fans, and power supplies; remote BMC KVM over IP. |
| **Known Limitations** | High acoustic output (> 55 dBA) requires dedicated server room or soundproof rack enclosure; dual 208–240V feeds recommended. |

---

## 3. Side-by-Side Appliance Comparison Matrix

| Feature | CAMserv Edge (`PROFILE_A`) | CAMserv Standard (`PROFILE_B`) | CAMserv Professional (`PROFILE_C`) | CAMserv Enterprise (`PROFILE_D`) |
| :--- | :---: | :---: | :---: | :---: |
| **Target Stream Range** | 1 – 4 streams | 4 – 16 streams | 16 – 32 streams | 32 – 64+ streams |
| **Max Stream Ceiling** | 6 streams | 20 streams | 40 streams | 80 – 128 streams |
| **Processor Architecture** | ARM64 / x86_64 Low-Power | x86_64 Desktop Core | x86_64 Performance Core | x86_64 Enterprise Server |
| **Physical Cores** | 4 – 8 cores | 6 – 14 cores | 8 – 16 cores | 16 – 32 cores |
| **System RAM** | 8 GB LPDDR4x | 16 GB DDR4/DDR5 | 32 GB DDR5 | 64 – 128 GB ECC Registered |
| **Core Recording GPU Requirement** | **NONE (Zero GPU)** | **NONE (Zero GPU)** | **NONE (Zero GPU)** | **NONE (Zero GPU)** |
| **Optional Analytical Accelerators** | Integrated 6 TOPS NPU | Integrated GPU (QSV) | Opt. RTX 4060 / Arc A770 | Opt. Dual RTX 4090 / L40S |
| **Storage Topology** | NVMe Direct Staging | NVMe + 2x SATA CMR | NVMe + 4x SATA (RAID-10) | NVMe + 8-16x SAS (RAID-6) |
| **Network Interfaces** | Dual 1GbE | Dual 2.5GbE | Dual 2.5GbE + Mgmt | Quad 10GbE SFP+ + IPMI |
| **Cooling Mode** | Passive / Fanless | Active Quiet Fan | Dual Ball-Bearing Fans | N+1 Redundant Hot-Swap Fans |
| **Typical Power (Base / Opt GPU)** | 12.0 W | 35.0 W | 65.0 W / 95.0 W | 180.0 W / 320.0 W |
| **Peak Power (Base / Opt GPU)** | 15.0 W | 65.0 W | 135.0 W / 180.0 W | 310.0 W / 550.0 W |
| **Worst-Case Load** | 18.0 W | 85.0 W | 245.0 W | 680.0 W |
| **PSU Configuration** | 40W DC Input | 150W Single AC | Dual 450W Redundant (N+1) | Dual 800W Redundant (N+1) |
| **Surviving PSU Headroom** | N/A (Single DC) | N/A (Single AC) | **83% Headroom** ($450\text{W} \ge 245\text{W}$) | **15% Headroom** ($800\text{W} \ge 680\text{W}$) |
| **Estimated Base BOM (USD)** | $265 – $350 | $750 – $1,050 | $1,350 – $1,800 | $4,200 – $5,800 |
| **Estimated Full BOM w/ GPU (USD)**| N/A | N/A | $1,650 – $2,200 | $7,150 – $8,600 |
