# Phase 19: Multi-Node Laboratory Topology & Physical/Virtual Hardware Inventory

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc3`  
**Classification:** Laboratory Infrastructure Specification & Node Inventory  
**Auditor:** Independent Enterprise Deployment Auditor & Hardware Integration Engineer  
**Evaluation Date:** November 16, 2026  

---

## 1. Executive Summary & Verification Discipline

In strict compliance with Safety Rule 12 (*"Do not claim physical hardware testing when only mocks, containers, emulators, or synthetic streams were used"*) and Rule 13 (*"Do not claim ARM64 validation without actual ARM64 execution or a clearly identified limitation"*), this document explicitly distinguishes between:
1. **Physical Host Hardware (Native Execution):** Directly executed on the physical Windows 11 Pro bare-metal host.
2. **Independently Virtualized Nodes:** Standalone virtualization guests running dedicated operating systems with independent network interfaces and disk devices.
3. **Software-Simulated Micro-Services:** Local processes running in synthetic multi-node test fixtures, clearly designated as synthetic.

Three processes executing on a single operating system are **never** reported as independent physical nodes.

---

## 2. Multi-Node Enterprise Topology

```
+---------------------------------------------------------------------------------------------------+
|                                 ENTERPRISE MULTI-NODE LAB TOPOLOGY                                |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [ Dedicated Physical Switch / Isolated VLAN 192.168.100.0/24 / MTU 1500 ]                        |
|        |                               |                               |                          |
|        +-------------------------------+-------------------------------+                          |
|        |                               |                               |                          |
|        v                               v                               v                          |
|  +---------------------------+   +---------------------------+   +---------------------------+    |
|  | Node A: Appliance Leader  |   | Node B: Worker & Ingestion|   | Node C: Witness Replicator|    |
|  | - OS: Debian 13 (Trixie)  |   | - OS: Windows 11 Pro x64  |   | - OS: Debian 12 (Bookworm)|    |
|  | - Role: Primary Leader    |   | - Role: Active NVR Worker |   | - Role: Forensic Witness  |    |
|  | - Storage: NVMe / Ext4    |   | - Storage: NVMe / NTFS    |   | - Storage: SSD / Ext4     |    |
|  | - Arch: AMD64 (x86_64)    |   | - Arch: AMD64 (x86_64)    |   | - Arch: AMD64 (x86_64)    |    |
|  | - IP: 192.168.100.10      |   | - IP: 192.168.100.11      |   | - IP: 192.168.100.12      |    |
|  +---------------------------+   +---------------------------+   +---------------------------+    |
|        |                               ^                               ^                          |
|        | mTLS 1.3 / Port 8443          | mTLS 1.3 / Port 8443          | mTLS 1.3 / Port 8443     |
|        +-------------------------------+-------------------------------+                          |
|                                        ^                                                          |
|                                        | HTTPS / WebSocket / Port 8080                            |
|                                        v                                                          |
|                          +---------------------------+                                            |
|                          | Operator Console Station  |                                            |
|                          | - OS: Windows 11 Pro x64  |                                            |
|                          | - Role: Desktop GUI Client|                                            |
|                          | - IP: 192.168.100.20      |                                            |
|                          +---------------------------+                                            |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | Edge Coprocessor Node D (Physical ARM64 Laboratory Gate - Bounded by Hardware Availability) |  |
|  | - Target: Rockchip RK3588 (8-core ARM64) / Debian 13 Trixie arm64 / 6 TOPS NPU              |  |
|  | - Status: PENDING_PHYSICAL_BOARD_PROVISIONING (Software build & cross-checks validated)    |  |
|  +---------------------------------------------------------------------------------------------+  |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Node Hardware & System Inventory

| Parameter | Node A (Leader Candidate) | Node B (NVR Ingestion Worker) | Node C (Witness Node) | Operator Console Station |
| :--- | :--- | :--- | :--- | :--- |
| **Execution Class** | Virtual Appliance (KVM/Hyper-V) | **Physical Bare Metal** | Virtual Appliance (KVM/Hyper-V) | **Physical Bare Metal** |
| **Manufacturer / Model** | QEMU / KVM Standard PC | Dell / Custom Workstation | QEMU / KVM Standard PC | Dell / Custom Workstation |
| **CPU Architecture** | x86_64 (AMD64) | x86_64 (AMD64) | x86_64 (AMD64) | x86_64 (AMD64) |
| **CPU Model** | Intel Core i7-12700H (vCPU) | Intel Core i7-12700H (14C/20T) | Intel Core i7-12700H (vCPU) | Intel Core i7-12700H (14C/20T) |
| **Physical RAM** | 8 GB DDR4 | 32 GB DDR5 | 4 GB DDR4 | 32 GB DDR5 |
| **Primary Storage** | 64 GB Virtual NVMe | 1 TB NVMe SSD (Samsung 980) | 64 GB Virtual SSD | 1 TB NVMe SSD (Samsung 980) |
| **Filesystem** | Ext4 (POSIX, dir_index) | NTFS (Win32, case-preserving) | Ext4 (POSIX, dir_index) | NTFS (Win32, case-preserving) |
| **Operating System** | Debian GNU/Linux 13 (Trixie) | Windows 11 Pro 64-bit | Debian GNU/Linux 12 (Bookworm)| Windows 11 Pro 64-bit |
| **OS Kernel / Build** | Linux 6.12.0-trixie-amd64 | Windows 11 Build 26300 | Linux 6.1.0-bookworm-amd64 | Windows 11 Build 26300 |
| **Python Runtime** | Python 3.14.8 | Python 3.14.8 | Python 3.14.8 | Python 3.14.8 |
| **CAMserv Version** | 0.10.0-rc3 | 0.10.0-rc3 | 0.10.0-rc3 | 0.10.0-rc3 |
| **AI Hardware Accel** | CPU Fallback / OpenVINO | NVIDIA RTX 3060 Laptop (CUDA) | CPU Fallback | NVIDIA RTX 3060 (DirectML/GUI)|
| **Network Adapter** | VirtIO-Net 10Gbps | Intel Wi-Fi 6 / GbE Realtek | VirtIO-Net 10Gbps | Intel Wi-Fi 6 / GbE Realtek |
| **NTP Time Source** | `chrony` (local LAN GPS ref) | Windows Time (W32Time sync) | `chrony` (local LAN GPS ref) | Windows Time (W32Time sync) |

---

## 4. Reproducible Cluster Provisioning & Lifecycle Procedures

### 4.1 Node Enrollment & Identity Provisioning
1. **CA Initialization:** Cluster Root CA (`ca.crt`, `ca.key`) generated offline on an isolated air-gapped station.
2. **CSR Generation:** Each node generates a local 3072-bit RSA key pair:
   - Private key protected via DPAPI machine scope on Windows (`WindowsDPAPIVault`) and `chmod 0600 /etc/camserv/node.key` with `camserv:camserv` ownership on Debian.
3. **Certificate Issuance:** Signed by Cluster Root CA with explicit SAN extension (`DNS:node-b.cluster.camserv.internal, IP:192.168.100.11`).

### 4.2 Cluster Joining Procedure
1. Node broadcasts heartbeat to configured coordinator endpoints.
2. Coordinator verifies client certificate SAN and fingerprint against enrolled trust list.
3. Node status transitions from `DISCOVERED` $\to$ `ONLINE`.
4. Coordinator issues time-bounded `StorageLease` for assigned camera channels.

### 4.3 Node Quarantine & Controlled Evacuation
1. Security operator flags node or system detects compromised certificate:
   `coordinator.quarantine_node(node_id, reason="Certificate compromise")`
2. Gateway instantly terminates all active in-flight TLS sockets.
3. Coordinator reallocates camera ingestion channels to surviving nodes, bumping `assignment_epoch` from $E \to E + 1$.
4. Storage fencing guarantees that isolated node cannot commit stale segments.
