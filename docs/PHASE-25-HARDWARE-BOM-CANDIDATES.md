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

This document establishes candidate Bills of Materials (BOM) across CAMserv's three reference hardware platforms:
- **Platform A:** ARM64 Embedded Appliance (Profile A / Edge)
- **Platform B:** x86_64 Compact Appliance (Standard & Professional / Profile B)
- **Platform C:** Enterprise Multi-Rack Surveillance Server (Profile C / Enterprise)

Component candidates were selected against four non-negotiable criteria:
1. **Surveillance Workload Reliability:** Industrial temperature ratings (-20°C to +70°C for edge; 0°C to +40°C for enterprise), 24/7 continuous operation rating, and high Mean Time Between Failures (MTBF $\ge 1,000,000$ hours).
2. **True Conventional Magnetic Recording (CMR):** Strict rejection of drive-managed SMR disks to eliminate write-buffer exhaustion and stream stalls.
3. **Hardware Video Decoding & Inference Support:** Proven silicon support under mainline Linux or vendor BSP (Rockchip MPP, Intel VA-API/QSV, NVIDIA NVDEC, TensorRT, OpenVINO).
4. **Supply Chain Longevity:** Minimum 5-year commercial availability and vendor lifecycle support.

---

## 2. Platform A: ARM64 Embedded Appliance Candidate BOM

### Reference Option A.1: FriendlyElec CM3588 Industrial Quad-M.2 Carrier
- **Form Factor:** Compact Industrial DIN-rail / Wall-mount chassis.
- **Target Tier:** CAMserv Edge Appliance (1–4 streams).

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

## 3. Platform B: x86_64 Compact Appliance Candidate BOM

### Reference Option B.1: OnLogic Helix / Supermicro Mini-ITX Smart NVR
- **Form Factor:** 1U Short-Depth Rackmount / Desktop NVR Chassis.
- **Target Tier:** CAMserv Standard & Professional Appliance (4–16 streams).

| Item | Component | Manufacturer / Model | Spec / Description | Qty | Unit Cost (Est. USD) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Processor** | Intel Core i5-13500 | Intel Raptor Lake | 14 cores (6P + 8E), 20 threads, Intel UHD Graphics 770 (QSV Dual-engine) | 1 | $245.00 |
| **Motherboard** | Industrial Mini-ITX | Supermicro X13SAE-F | Intel W680 chipset, Dual 2.5GbE RJ45 (Intel i225-V), 8x SATA3, IPMI dedicated | 1 | $340.00 |
| **Memory** | DDR5 Unbuffered RAM | Crucial / Kingston | 32 GB (2x 16GB) DDR5-4800 Non-ECC / Optional ECC unbuffered | 1 | $95.00 |
| **OS / Staging SSD** | High-Endurance NVMe | Samsung 980 PRO / Micron 7450 | 1TB M.2 2280 PCIe 4.0 x4, 600 TBW, 1.0 DWPD enterprise endurance | 1 | $98.00 |
| **Archive Storage** | Surveillance CMR HDDs | Western Digital Purple WD84PURZ | 2x 8TB 3.5" SATA 6Gb/s, 5640 RPM, 128MB cache, AllFrame firmware (CMR) | 2 | $390.00 ($195 ea) |
| **Accelerator (Opt)**| Dedicated GPU | NVIDIA GeForce RTX 4060 | 8GB GDDR6, 3072 CUDA cores, Dual 8th Gen NVDEC engines, 115W TGP | 1 | $299.00 |
| **Chassis & Power** | 1U Rack Chassis + PSU | In-Win / Seasonic | 1U short-depth (380mm), 250W 80-Plus Gold Flex-ATX PSU, dual PWM fans | 1 | $185.00 |
| **Total BOM (Sample)** | | | **Single Unit Prototype (with GPU)** | | **$1,652.00** |
| **Total BOM (Base)** | | | **Single Unit Prototype (Standard / iGPU only)** | | **$1,353.00** |
| **Total BOM (Volume)** | | | **1,000-Unit Production Run (with GPU)** | | **$1,320.00** |

*Operational Rating: Commercial 0°C to +40°C; Active dual ball-bearing PWM cooling.*

---

## 4. Platform C: Enterprise Multi-Rack Surveillance Server Candidate BOM

### Reference Option C.1: 2U Enterprise Supermicro SuperServer
- **Form Factor:** 2U EIA-310 19" Rackmount Server (Depth 650mm).
- **Target Tier:** CAMserv Enterprise Appliance (16–64+ streams).

| Item | Component | Manufacturer / Model | Spec / Description | Qty | Unit Cost (Est. USD) |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Compute Processor** | AMD EPYC 7302P / 9124 | AMD Server CPU | 16 cores, 32 threads, 64MB L3 cache, PCIe 4.0/5.0 128 lanes, 155W–200W TDP | 1 | $650.00 |
| **Server Motherboard** | Single-Socket SP3/SP5 | Supermicro H12SSL-i | 8x DDR4/DDR5 channels, Dual 1GbE + Dual 10GbE SFP+, ASPEED AST2600 BMC | 1 | $480.00 |
| **System Memory** | Registered ECC RAM | Micron / SK Hynix | 64 GB (4x 16GB) DDR4-3200 / DDR5-4800 Registered ECC RDIMM | 4 | $260.00 |
| **Boot Drive RAID-1** | Dual NVMe M.2 | Micron 7450 PRO | 2x 960GB M.2 PCIe 4.0 (Hardware mirrored via onboard RAID controller) | 2 | $250.00 ($125 ea) |
| **Storage Backplane** | SAS/SATA Controller | Broadcom MegaRAID 9560-8i | 12Gb/s SAS / 6Gb/s SATA PCIe 4.0 x8 controller with 4GB cache & battery backup | 1 | $450.00 |
| **Archive Storage** | Enterprise CMR HDDs | Seagate Exos X18 / WD Ultrastar | 8x 16TB 3.5" SATA 6Gb/s, 7200 RPM, 256MB cache, 2.5M hours MTBF (CMR) | 8 | $2,160.00 ($270 ea) |
| **Dual Accelerators** | Enterprise AI Accelerators | NVIDIA RTX 4090 / NVIDIA L40S | 2x NVIDIA RTX 4090 (24GB GDDR6X, blower style) or dual L40S (48GB ECC VRAM) | 2 | $3,400.00 ($1,700 ea)|
| **Network Adapter** | Dual 10GbE SFP+ | Intel X520-DA2 / X710 | Dual-port 10GbE SFP+ optical card with SR transceivers | 1 | $180.00 |
| **Chassis & Power** | 2U Rack + Dual PSU | Supermicro CSE-826 | 2U 12-bay hot-swap 3.5" chassis, Dual Redundant 800W 80-Plus Platinum PSUs | 1 | $680.00 |
| **Cooling Matrix** | Hot-Swap High-CFM Fans | Nidec / Delta | 4x 80mm heavy-duty PWM hot-swappable server fans (7000 RPM) | 4 | $80.00 |
| **Total BOM (Sample)** | | | **Single Unit Prototype (with Dual RTX 4090)** | | **$8,590.00** |
| **Total BOM (Volume)** | | | **100-Unit Enterprise Volume Run** | | **$7,150.00** |

*Operational Rating: Data center 10°C to +35°C; Redundant hot-swap N+1 cooling and dual AC inputs.*

---

## 5. Storage Sourcing Guardrails: CMR vs. SMR Verification

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
