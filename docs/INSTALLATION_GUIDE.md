# CAMserv Installation & Setup Guide

**Enterprise Security Intelligence Platform**  
**Version:** 1.0 (Production Release)

---

## 1. System Requirements

### 1.1 Minimum Hardware (Tier 1 Profile)
- **CPU:** Dual-core x86_64 or ARM64 (2.0 GHz+)
- **Memory:** 4 GB RAM (8 GB recommended)
- **Storage:** 20 GB available SSD storage
- **Network:** 100 Mbps Ethernet

### 1.2 Recommended Hardware (Tier 3 Profile)
- **CPU:** 8-core Intel Core i7/i9 or AMD Ryzen 7/9
- **Memory:** 16–32 GB DDR4/DDR5 RAM
- **GPU:** NVIDIA GeForce RTX 3060 (6GB+) / RTX 4070 or NVIDIA A2 / Jetson AGX Orin
- **Storage:** 500 GB NVMe SSD (forensic evidence vault)
- **Network:** Gigabit Ethernet (1 Gbps+)

### 1.3 Supported Operating Systems
- **Linux:** Ubuntu 22.04 / 24.04 LTS, Debian 12, Rocky Linux 9, RHEL 9
- **Windows:** Windows 10 Pro / Windows 11 / Windows Server 2022
- **macOS:** macOS Sonoma / Sequoia (Apple Silicon M1/M2/M3/M4 via Metal/MPS)

---

## 2. Quickstart Installation

### Step 1: Clone the Official Repository
```bash
git clone git@github.com:aboulouafaeit-sys/CAMserv.IT.git
cd CAMserv.IT
```

### Step 2: Set Up Python Environment
Ensure Python 3.11+ is installed:
```bash
# Verify Python version
python3 --version

# Create virtual environment
python3 -m venv .venv

# Activate on Linux/macOS:
source .venv/bin/activate

# Activate on Windows (PowerShell):
.venv\Scripts\Activate.ps1
```

### Step 3: Install Core Dependencies
```bash
pip install --upgrade pip
pip install -e .
```

### Step 4: Verify System Hardware & Hardware Tier
Run the built-in diagnostic probe to verify GPU/CUDA availability and assigned operating tier:
```bash
python -m camserv.main detect-hw
```

### Step 5: Start the CAMserv Application Server
```bash
python -m camserv.main serve --host 127.0.0.1 --port 8000
```

Access the interactive web console at:
`http://127.0.0.1:8000/`

---

## 3. Production Deployment with Systemd (Linux)

For 24/7 autonomous surveillance deployments, configure CAMserv as a systemd daemon:

1. Create `/etc/systemd/system/camserv.service`:
```ini
[Unit]
Description=CAMserv Security Intelligence Platform
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=camserv
Group=camserv
WorkingDirectory=/opt/camserv
Environment="PYTHONPATH=/opt/camserv/src"
Environment="CAMSERV_SECURITY__JWT__SECRET_KEY=generate-a-strong-32-char-key-here"
ExecStart=/opt/camserv/.venv/bin/python -m camserv.main serve --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

2. Reload and enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now camserv.service
sudo systemctl status camserv.service
```

---

## 4. Environment Variables Configuration

Create a `.env` file in the project root:

```ini
# Core Configuration
CAMSERV_ENVIRONMENT=production
CAMSERV_DEBUG=false
CAMSERV_LOG_LEVEL=INFO

# Networking & Ingestion
CAMSERV_API__HOST=0.0.0.0
CAMSERV_API__PORT=8000
CAMSERV_STREAM__MAX_QUEUED_FRAMES=128

# Inference Accelerators
CAMSERV_INFERENCE__DEVICE=cuda
CAMSERV_INFERENCE__ENGINE=tensorrt
CAMSERV_INFERENCE__CONFIDENCE_THRESHOLD=0.55

# Cryptography & Forensic Evidence Vault
CAMSERV_SECURITY__JWT__SECRET_KEY=replace-with-secure-32-char-random-string
CAMSERV_STORAGE__EVIDENCE_DIR=/var/lib/camserv/evidence
```

---

## 5. Automated Verification Test Suite

Verify all 118 automated security, tracking, and cryptographic tests pass on your machine:
```bash
pytest tests/ -v
```
All tests must report green before connecting operational camera feeds.
