# CAMserv — Hardware Bill of Materials (BOM) Candidates

**Document ID:** BOM-P25-CANDIDATES-2026-004  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25 — Hardware Appliance Engineering & Physical Reliability Qualification  
**Classification:** Hardware Systems Engineering & Supply Chain Evaluation  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Hardware Systems Architect, Embedded Linux Engineer, Storage Reliability Engineer, Network Surveillance Architect, Security Engineer & Release Qualification Authority  

---

## 1. Executive Summary & Sourcing Strategy

This document establishes candidate Bills of Materials (BOM) across CAMserv's standardized reference hardware platforms:
- **Profile A (Low-Power / Edge):** ARM64 / Low-Power x86 Embedded Appliance (`PROFILE_A_LOW_POWER`)
- **Profile B (Standard):** x86_64 Compact Desktop / 1U Short-Depth Appliance (`PROFILE_B_STANDARD`)
- **Profile C (Professional):** x86_64 Performance 1U/2U Rackmount Appliance (`PROFILE_C_PROFESSIONAL`)
- **Profile D (Enterprise):** x86_64 Enterprise Multi-Spindle 2U/4U Surveillance Server (`PROFILE_D_ENTERPRISE`)

### Core Engineering Invariant:
**Surveillance recording does NOT require discrete graphics hardware.**  
All base BOM candidates are engineered to ingest, verify, index, sign, and archive 100% of their rated stream count using pure CPU zero-copy elementary stream pass-through. Dedicated accelerators (discrete GPUs, PCIe NPUs) are strictly optional analytical acceleration add-ons.

Component candidates are selected against four non-negotiable criteria:
1. **Surveillance Workload Reliability:** Industrial temperature ratings (-20°C to +70°C for edge; 0°C to +40°C for enterprise), 24/7 continuous operation rating, and high Mean Time Between Failures (MTBF $\ge 1,000,000$ hours).
2. **True Conventional Magnetic Recording (CMR):** Strict rejection of drive-managed SMR disks to eliminate write-buffer exhaustion and stream stalls.
3. **Hardware Video Decoding & Inference Support:** Proven silicon support under mainline Linux or vendor BSP (Rockchip MPP, Intel VA-API/QSV, NVIDIA NVDEC, TensorRT, OpenVINO).
4. **Supply Chain Longevity:** Minimum 5-year commercial availability and vendor lifecycle support.

---

## 2. Profile A: Low-Power / Edge Appliance Candidate BOM (`PROFILE_A_LOW_POWER`)

### Reference Option A.1: FriendlyElec CM3588 Industrial Quad-M.2 Carrier
- **Form Factor:** Compact Industrial DIN-rail / Wall-mount chassis.
- **Target Tier:** CAMserv Edge Appliance (1–4 streams continuous, max 6 streams).
- **Core Video Acceleration:** Integrated Rockchip MPP VPU (no discrete GPU).

| Item | Component | Manufacturer / Model | Spec / Description | Qty | Unit Cost (Est. USD) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Compute Core** | Rockchip RK3588 SOM | FriendlyElec CM3588 | 8-core CPU (4x A76 + 4x A55), 6 TOPS NPU, 8GB LPDDR4x, 64GB eMMC 5.1 | 1 | $145.00 |
| **Carrier Board** | Quad-M.2 NAS Baseboard | FriendlyElec NAS Carrier | Dual 2.5GbE Realtek RTL8125B, 4x M.2 NVMe slots (PCIe 3.0 x1 each), 12V DC in | 1 | $65.00 |
| **NVMe Staging** | Industrial M.2 SSD | Micron 2450 / Kingston Industrial | 512GB M.2 2280 PCIe 3.0, 300 TBW, TLC with pSLC cache | 1 | $48.00 |
| **Thermal Dissipation**| Passive Finned Heatsink | Custom Aluminum Enclosure | Monolithic extruded aluminum alloy 6063-T5 with integrated thermal pads | 1 | $38.00 |
| **Power Supply** | Industrial DIN-Rail PSU | Mean Well MDR-40-12 | 12V DC, 3.33A, 40W, Universal AC input 85–264V, DIN-rail mount | 1 | $24.00 |
| **Interconnects** | Antenna & Cables | Amphenol / Molex | Wi-Fi 6 / BT pigtails, industrial terminal block connector | 1 | $12.00 |
| **Total BOM (Sample)** | | | **Single Unit Prototype** | | **$332.00** |
| **Total BOM (Volume)** | | | **1,000-Unit Production Run** | | **$265.00** |

*Operational Rating: Industrial -20°C to +70°C; Fanless convection.*

---

## 3. Profile B: Standard Compact Appliance Candidate BOM (`PROFILE_B_STANDARD`)

### Reference Option B.1: Supermicro / In-Win Mini-ITX Smart NVR
- **Form Factor:** Compact Desktop Mini-Tower or Shallow-Depth 1U Rackmount Chassis.
- **Target Tier:** CAMserv Standard Appliance (4–16 streams continuous, max 20 streams).
- **Core Video Acceleration:** Intel Quick Sync Video (QSV) via Intel UHD 770 / CPU (no discrete GPU required).

| Item | Component | Manufacturer / Model | Spec / Description | Qty | Unit Cost (Est. USD) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Processor** | Intel Core i5-13500 | Intel Raptor Lake | 14 cores (6P + 8E), 20 threads, Intel UHD Graphics 770 (Dual QSV engines) | 1 | $245.00 |
| **Motherboard** | Industrial Mini-ITX | Supermicro X13SAE-F / AsRock Rack | Intel W680/B760 chipset, Dual 2.5GbE RJ45, 4x SATA3, 2x M.2 NVMe | 1 | $280.00 |
| **Memory** | DDR5 Unbuffered RAM | Crucial / Kingston | 16 GB (2x 8GB) DDR5-4800 Non-ECC | 1 | $65.00 |
| **OS / Staging SSD** | High-Endurance NVMe | Samsung 980 PRO / Micron 7450 | 512GB M.2 2280 PCIe 4.0 x4, 300 TBW, enterprise endurance | 1 | $68.00 |
| **Archive Storage** | Surveillance CMR HDDs | Western Digital Purple WD43PURZ | 2x 4TB 3.5" SATA 6Gb/s, 5400 RPM, AllFrame firmware (CMR) | 2 | $190.00 ($95 ea) |
| **Chassis & Power** | Mini-Tower / 1U Chassis | Seasonic / In-Win | Short-depth, 150W 80-Plus Bronze internal PSU, quiet PWM fan | 1 | $120.00 |
| **Cabling & Hardware** | SATA Cables & Screws | Supermicro / Molex | Locking SATA data cables, vibration-damped drive grommets | 1 | $15.00 |
| **Total Base BOM (Sample)**| | | **Standard Appliance Base (iGPU / No Discrete GPU)** | | **$983.00** |
| **Total Base BOM (Volume)**| | | **1,000-Unit Production Run** | | **$795.00** |

*Operational Rating: Commercial 0°C to +40°C; Active quiet PWM internal fan cooling ($< 28\text{ dBA}$). Continuous PSU capacity: 150W vs peak load 65W ($130\%$ safety margin).*

---

## 4. Profile C: Professional Rackmount Appliance Candidate BOM (`PROFILE_C_PROFESSIONAL`)

### Reference Option C.1: 1U/2U Performance Server NVR
- **Form Factor:** 1U or 2U EIA-310 19" Short-Depth Rackmount Chassis.
- **Target Tier:** CAMserv Professional Appliance (16–32 streams continuous, max 40 streams).
- **Core Video Acceleration:** Intel Core i7 / AMD Ryzen multi-core pass-through (Discrete GPU strictly optional).

| Item | Component | Manufacturer / Model | Spec / Description | Qty | Unit Cost (Est. USD) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Processor** | Intel Core i7-13700 | Intel Raptor Lake | 16 cores (8P + 8E), 24 threads, Intel UHD Graphics 770 | 1 | $385.00 |
| **Motherboard** | Server Mini-ITX / Micro-ATX | Supermicro X13SAE-F | Intel W680, Dual 2.5GbE RJ45 + 1GbE IPMI 2.0, 8x SATA3, 3x M.2 | 1 | $340.00 |
| **System Memory** | DDR5 Unbuffered RAM | Micron / Crucial | 32 GB (2x 16GB) DDR5-4800 ECC Unbuffered / Non-ECC | 1 | $110.00 |
| **OS / Staging SSD** | High-Endurance NVMe | Micron 7450 PRO / Samsung 990 | 1TB M.2 2280 PCIe 4.0 x4, 1,200 TBW, 1.0 DWPD enterprise endurance | 1 | $115.00 |
| **Archive Storage** | Surveillance CMR HDDs | Western Digital Purple WD84PURZ | 4x 8TB 3.5" SATA 6Gb/s, 5640 RPM, AllFrame firmware (CMR) | 4 | $780.00 ($195 ea) |
| **Chassis & Power** | 1U/2U Rack + Dual PSU | Supermicro CSE-813 / In-Win | 4-bay hot-swap 3.5" chassis, Dual Redundant 450W 80-Plus Gold PSUs | 1 | $390.00 |
| **Chassis Cooling** | Ball-Bearing Fans | Nidec / Delta | Dual 40mm/80mm PWM ball-bearing hot-swap fans | 2 | $30.00 |
| **Total Base BOM (Sample)**| | | **Professional Base (CPU/iGPU Only — No Discrete GPU)** | | **$2,150.00** |
| **Total Base BOM (Volume)**| | | **500-Unit Production Run** | | **$1,720.00** |
| **Optional GPU Add-on** | Dedicated AI Accelerator | NVIDIA GeForce RTX 4060 | 8GB GDDR6, Dual 8th Gen NVDEC, 115W TGP (Analytical AI Acceleration) | 1 | +$299.00 |
| **Total Full BOM w/ GPU** | | | **Professional Full Prototype (with Optional RTX 4060)** | | **$2,449.00** |

*Operational Rating: Commercial 0°C to +40°C; Dual 450W redundant PSUs (N+1). Single surviving PSU delivers 450W continuous, carrying 245W worst-case load with 83% safety margin ($450\text{W} \ge 245\text{W}$).*

---

## 5. Profile D: Enterprise Multi-Rack Surveillance Server Candidate BOM (`PROFILE_D_ENTERPRISE`)

### Reference Option D.1: 2U Enterprise Supermicro SuperServer
- **Form Factor:** 2U EIA-310 19" Rackmount Server (Depth 650mm).
- **Target Tier:** CAMserv Enterprise Appliance (32–64+ streams continuous, max 80–128 streams).
- **Core Video Acceleration:** Native AMD EPYC multi-core pass-through recording (Zero GPU required for recording).

| Item | Component | Manufacturer / Model | Spec / Description | Qty | Unit Cost (Est. USD) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Compute Processor** | AMD EPYC 7302P / 9124 | AMD Server CPU | 16 cores, 32 threads, 64MB L3 cache, PCIe 4.0 128 lanes, 155W–200W TDP | 1 | $650.00 |
| **Server Motherboard** | Single-Socket SP3/SP5 | Supermicro H12SSL-i | 8x DDR4/DDR5 channels, Dual 1GbE + Dual 10GbE SFP+, ASPEED AST2600 BMC | 1 | $480.00 |
| **System Memory** | Registered ECC RAM | Micron / SK Hynix | 64 GB (4x 16GB) DDR4-3200 / DDR5-4800 Registered ECC RDIMM | 4 | $260.00 |
| **Boot Drive RAID-1** | Dual NVMe M.2 | Micron 7450 PRO | 2x 960GB M.2 PCIe 4.0 (Hardware mirrored via onboard RAID controller) | 2 | $250.00 ($125 ea) |
| **Storage Backplane** | SAS/SATA Controller | Broadcom MegaRAID 9560-8i | 12Gb/s SAS / 6Gb/s SATA PCIe 4.0 x8 controller with 4GB cache & battery backup | 1 | $450.00 |
| **Archive Storage** | Enterprise CMR HDDs | Seagate Exos X18 / WD Ultrastar | 8x 16TB 3.5" SATA 6Gb/s, 7200 RPM, 256MB cache, 2.5M hours MTBF (CMR) | 8 | $2,160.00 ($270 ea) |
| **Network Adapter** | Dual 10GbE SFP+ | Intel X520-DA2 / X710 | Dual-port 10GbE SFP+ optical card with SR transceivers | 1 | $180.00 |
| **Chassis & Power** | 2U Rack + Dual PSU | Supermicro CSE-826 | 2U 12-bay hot-swap 3.5" chassis, Dual Redundant 800W 80-Plus Platinum PSUs | 1 | $680.00 |
| **Cooling Matrix** | Hot-Swap High-CFM Fans | Nidec / Delta | 4x 80mm heavy-duty PWM hot-swappable server fans (7000 RPM) | 4 | $80.00 |
| **Total Base BOM (Sample)**| | | **Enterprise Base Server (CPU-Only Recording — No GPU)** | | **$5,190.00** |
| **Total Base BOM (Volume)**| | | **100-Unit Enterprise Volume Run** | | **$4,350.00** |
| **Optional Dual GPUs** | Enterprise AI Accelerators | NVIDIA RTX 4090 / NVIDIA L40S | 2x NVIDIA RTX 4090 (24GB GDDR6X) or dual L40S (48GB ECC VRAM) | 2 | +$3,400.00 ($1,700 ea)|
| **Total Full BOM w/ GPUs**| | | **Enterprise Full Prototype (with Dual RTX 4090)** | | **$8,590.00** |
| **Total Full BOM w/ GPUs (Vol)**| | | **100-Unit Enterprise Volume Run (with Dual RTX 4090)** | | **$7,150.00** |

*Operational Rating: Data center 10°C to +35°C; Redundant hot-swap N+1 cooling and dual AC inputs. Dual 800W 80-Plus Platinum PSUs: single surviving PSU delivers 800W continuous, carrying 680W worst-case load with 15% safety headroom ($800\text{W} \ge 680\text{W}$, load is $85\%$ of single PSU capacity).*

---

## 6. Storage Sourcing Guardrails: CMR vs. SMR Verification

Surveillance video writing exhibits continuous, non-stop sequential write pressure across multiple camera channels simultaneously.

### The Physics of Failure on SMR Drives:
1. **Shingled Overlapping Tracks:** Drive-Managed Shingled Magnetic Recording (DM-SMR) writes data in overlapping shingles. Modifying or writing data requires reading, rewriting, and trimming entire multi-megabyte bands.
2. **On-Drive Media Cache Exhaustion:** When all camera streams write simultaneously, the internal disk DRAM/SLC cache saturates within 5 to 15 minutes.
3. **Severe Write Stalls (> 800ms):** Once cache is exhausted, the drive firmware halts incoming write commands to reorganize shingles. Write latency spikes from 12ms to over 800ms.
4. **CAMserv Buffer Overflow:** The host write queue fills, the kernel buffer overflows, and the surveillance engine is forced to drop video frames.

### Mandatory Certified Drive Models:
- **Western Digital Purple:** WD23PURZ (2TB), WD43PURZ (4TB), WD64PURZ (6TB), WD84PURZ (8TB), WD102PURZ (10TB) — All verified CMR.
- **Seagate SkyHawk:** ST4000VX016 (4TB), ST6000VX001 (6TB), ST8000VX004 (8TB) — All verified CMR with ImagePerfect firmware.
- **Toshiba S300 Pro:** HDWT380UZSVA (8TB), HDWT31AUZSVA (10TB) — Verified CMR.

*Strict SMR Disqualification Policy: Any disk detected as `HDD_SMR` via `/sys/block/*/queue/zoned` is immediately flagged with `HardwareAvailabilityState.DEGRADED` and limited to 2 low-bitrate streams.*
