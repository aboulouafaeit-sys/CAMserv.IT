# CAMserv — Phase 21 Rockchip RK3588 Edge Appliance Deployment Runbook

**Document ID:** RUNBOOK-RK3588-DEPLOY-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Hardware:** Profile A — Industrial Edge NVR (Rockchip RK3588 / RK3588S SoC)  
**Reference Target Boards:** Radxa ROCK 5B, Firefly ITX-3588J, Orange Pi 5 Plus, Khadas Edge2  
**Target OS:** Debian 13 Trixie arm64 / Debian 12 Bookworm arm64 (Kernel 6.1 LTS / 6.6 LTS Rockchip BSP)  
**Target Software Release:** CAMserv `0.10.0` (Pre-LTS)  
**Date:** November 17, 2026  
**Auditor:** Independent Embedded Systems Engineering Board  

---

## 1. Overview & Appliance Architecture

This runbook provides the definitive, reproducible engineering procedure to deploy CAMserv `0.10.0` onto physical Rockchip RK3588 hardware appliances. Profile A appliances serve as high-density edge NVRs capable of multi-channel H.264/H.265 ingestion, hardware-accelerated video decoding via Rockchip MPP (Media Process Platform), real-time privacy redaction and security inference via the integrated 6 TOPS tri-core NPU (RKNN-Toolkit2), and local tamper-evident cryptographic evidence storage.

```
       +-------------------------------------------------------------+
       |            Rockchip RK3588 SoC (4x A76 + 4x A55)           |
       |                                                             |
       |  +--------------------+             +--------------------+  |
       |  |  Rockchip MPP VPU  |             |  Tri-Core NPU      |  |
       |  |  (Hardware H.264/  |             |  (6 TOPS INT8)     |  |
       |  |   H.265 Decode)    |             |  (librknnrt.so)    |  |
       |  +---------+----------+             +---------+----------+  |
       |            |                                  |             |
       |            +-----------------+----------------+             |
       |                              |                              |
       |             +----------------v---------------+              |
       |             |  CAMserv Core Appliance Engine |              |
       |             |  - Multi-Channel Ingestion     |              |
       |             |  - Privacy Spatial Blurring    |              |
       |             |  - Ed25519 Cryptographic Seals |              |
       |             |  - StorageLease Writer Fencing |              |
       |             +----------------+---------------+              |
       +------------------------------|------------------------------+
                                      |
                      +---------------v---------------+
                      | PCIe 3.0 x4 M.2 NVMe Storage  |
                      | - /var/lib/camserv/recordings |
                      | - SQLite WAL Evidence Index   |
                      +-------------------------------+
```

---

## 2. Laboratory Equipment & Tooling Prerequisites

### 2.1 Hardware Apparatus
1. **Target Board:** Radxa ROCK 5B (or equivalent RK3588 development board) with $\ge 8\text{ GB}$ LPDDR4x/LPDDR5 RAM.
2. **Primary Storage:** 1 TB M.2 2280 PCIe 3.0/4.0 NVMe SSD (Samsung 980 Pro, Micron 7450, or WD Red SN700) or high-speed eMMC 5.1 module ($\ge 64\text{ GB}$).
3. **Power Supply:** USB-PD 65W ($20\text{V} / 3.25\text{A}$) compliant power adapter.
4. **Serial Debug Interface:** USB-to-UART bridge (FTDI FT232R or CP2102) supporting **1,500,000 baud** (Rockchip standard).
5. **Flashing Interface:** High-speed USB Type-C to Type-A data cable.

### 2.2 Host Software & Utilities (Linux/Debian Workstation)
```bash
sudo apt-get update && sudo apt-get install -y \
    rkdeveloptool \
    fastboot \
    minicom \
    picocom \
    libusb-1.0-0-dev \
    device-tree-compiler
```

---

## 3. Storage Flashing & Firmware Provisioning

### 3.1 Entering Maskrom Recovery Mode
1. Ensure power is disconnected from the target board.
2. Depress and hold the onboard **Maskrom / Recovery** hardware switch.
3. Connect the board's USB-C OTG port to the host workstation.
4. Apply power while continuing to hold the switch for 3 seconds, then release.
5. On the host workstation, verify device attachment:
```bash
rkdeveloptool ld
# Output must report: DevNo=1  Vid=0x2207,Pid=0x350b,LocationID=... Maskrom
```

### 3.2 Initializing DDR Memory & Flashing SPL/U-Boot
Download the certified Rockchip RK3588 bootloader binaries:
```bash
# Initialize DRAM controller
rkdeveloptool db rk3588_spl_loader_v1.15.113.bin

# Program GPT partition table and U-Boot into target eMMC/NVMe
rkdeveloptool gpt parameter_rk3588_camserv.txt
rkdeveloptool wl 0x40 idbloader.img
rkdeveloptool wl 0x10000 u-boot.itb
rkdeveloptool rd
```

### 3.3 Root Filesystem Provisioning (Debian 13 arm64)
Flash the target Debian 13 minimal image containing Rockchip 6.1/6.6 BSP kernel:
```bash
# Flash boot partition (Kernel, DTB, Initramfs)
rkdeveloptool wl 0x200000 boot_camserv_rk3588.img

# Flash rootfs partition (Debian 13 arm64)
rkdeveloptool wl 0x800000 rootfs_debian13_arm64.img

# Reboot target board into normal operating mode
rkdeveloptool rd
```

---

## 4. Operating System Configuration & Driver Hardening

Connect the serial debug console to verify first boot:
```bash
picocom -b 1500000 /dev/ttyUSB0
```

### 4.1 Storage Partitioning & Mount Options
Format and mount the NVMe video storage volume with high-throughput options:
```bash
# Create dedicated evidence volume
mkfs.ext4 -m 1 -O dir_index,extent,sparse_super -b 4096 /dev/nvme0n1p1

# Create mount points
mkdir -p /var/lib/camserv/storage
mkdir -p /var/lib/camserv/database

# Update /etc/fstab with performance flags
cat << 'EOF' >> /etc/fstab
/dev/nvme0n1p1  /var/lib/camserv/storage  ext4  defaults,noatime,nodiratime,commit=30,barrier=1,errors=remount-ro  0  2
EOF

mount -a
```

### 4.2 Kernel Sysctl Hardening & Tuning
Create `/etc/sysctl.d/99-camserv-appliance.conf`:
```ini
# Video buffer memory allocations
net.core.rmem_max = 33554432
net.core.wmem_max = 33554432
net.core.rmem_default = 8388608
net.core.wmem_default = 8388608
net.ipv4.udp_mem = 67108864 134217728 268435456

# Storage writeback parameters
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10
vm.dirty_expire_centisecs = 3000

# File descriptor limits
fs.file-max = 2097152

# Hardware watchdog
kernel.watchdog = 1
kernel.watchdog_thresh = 10
```
Apply immediately:
```bash
sysctl -p /etc/sysctl.d/99-camserv-appliance.conf
```

---

## 5. Hardware Acceleration: MPP & RKNN-Toolkit2 Setup

### 5.1 Rockchip MPP (Media Process Platform)
Install the hardware video decoding user-space libraries:
```bash
sudo apt-get install -y librockchip-mpp-dev librockchip-mpp1

# Verify kernel MPP service node
ls -l /dev/mpp_service
# Set non-root service group permissions
sudo chown root:video /dev/mpp_service
sudo chmod 660 /dev/mpp_service
```

### 5.2 RKNN NPU Driver & Runtime Library
Install the Rockchip NPU runtime driver (`librknnrt.so`):
```bash
# Verify RKNPU kernel driver interface
ls -l /dev/rknpu
sudo chown root:video /dev/rknpu
sudo chmod 660 /dev/rknpu

# Install runtime libraries to system path
sudo cp /opt/camserv/drivers/rknn/librknnrt.so /usr/lib/aarch64-linux-gnu/
sudo ldconfig

# Verify NPU frequency and power governor
cat /sys/class/devfreq/fdab0000.npu/cur_freq
echo performance > /sys/class/devfreq/fdab0000.npu/governor
```

---

## 6. CAMserv Service Installation & Configuration

### 6.1 Deploying CAMserv Debian Package
```bash
sudo dpkg -i camserv_0.10.0-1_arm64.deb
sudo apt-get install -f -y
```

### 6.2 Appliance Configuration (`/etc/camserv/camserv.yaml`)
```yaml
appliance:
  profile: "profile_a_rk3588"
  node_id: "rk3588-appliance-01"
  cluster_nodes:
    - "rk3588-appliance-01"
    - "camserv-core-win11"
    - "debian13-witness-01"
  expected_cluster_size: 3

hardware:
  hardware_accel: "rockchip_mpp"
  ai_backend: "rknn"
  npu_device: "/dev/rknpu"
  npu_core_mask: 7  # Enable all 3 NPU cores (RKNN_NPU_CORE_0_1_2)

storage:
  root_path: "/var/lib/camserv/storage"
  database_path: "/var/lib/camserv/database/camserv.db"
  max_capacity_gb: 900
  retention_days: 30
  writer_fencing:
    lease_duration_sec: 15
    lease_renewal_interval_sec: 5
    quarantine_directory: "/var/lib/camserv/storage/quarantine"

privacy:
  enforce_redaction: true
  fail_closed_blackout: true
  redaction_confidence_threshold: 0.35
  dual_control_witness_required: true

security:
  audit_log_path: "/var/lib/camserv/logs/audit.jsonl"
  preserve_audit_invariant: true
```

### 6.3 Systemd Service Hardening & Hardware Watchdog
Verify `/lib/systemd/system/camserv.service`:
```ini
[Unit]
Description=CAMserv Security Intelligence Platform Service
After=network-online.target systemd-sysctl.service
Wants=network-online.target

[Service]
Type=notify
User=camserv
Group=camserv
SupplementaryGroups=video
WorkingDirectory=/var/lib/camserv
ExecStart=/usr/bin/camserv-service --config /etc/camserv/camserv.yaml
Restart=always
RestartSec=5s

# Hardware and Service Watchdog Integration
WatchdogSec=30s

# Linux Namespaces & Sandboxing
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
ReadWritePaths=/var/lib/camserv /run/camserv

# Resource Limits
LimitNOFILE=65536
LimitNPROC=4096
LimitMEMLOCK=infinity

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now camserv.service
```

---

## 7. Post-Deployment Verification & Telemetry Inspection

Execute the following verification commands on the physical board:
```bash
# 1. Verify service health and watchdog heartbeats
systemctl status camserv.service

# 2. Inspect active hardware accelerator bindings
curl -s http://127.0.0.1:8080/system/telemetry | jq '{
  hardware_profile: .profile,
  active_decoder: .decoder,
  ai_backend: .ai_engine,
  npu_utilization: .npu_cores_active,
  lease_active: .storage_lease_valid
}'

# 3. Check hardware thermal zones
cat /sys/class/thermal/thermal_zone*/temp
```

Expected output:
* `hardware_profile`: `"profile_a_rk3588"`
* `active_decoder`: `"rockchip_mpp"`
* `ai_backend`: `"rknn"`
* `npu_cores_active`: `3`
* `storage_lease_valid`: `true`
* Thermal readings: between $42000$ and $58000$ ($42^\circ\text{C} - 58^\circ\text{C}$).
