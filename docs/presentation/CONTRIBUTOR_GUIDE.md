# CAMserv — Contributor Guide & Engineering Standards

**Document ID:** GUIDE-CONTRIBUTOR-2026-001  
**Project:** CAMserv Advanced Security Intelligence Platform  
**Target Repository:** `aboulouafaeit-sys/CAMserv.IT`  
**License:** MIT License  
**Date:** November 15, 2026  

---

## 1. Welcome to the CAMserv Engineering Community

We welcome contributions from software engineers, cybersecurity specialists, computer vision researchers, and digital forensics professionals. Because CAMserv is deployed in critical infrastructure, we adhere to rigorous code quality, security, and privacy standards.

---

## 2. Non-Negotiable Invariants for Contributors

Every pull request must uphold the following core principles:
1. **Never Bypass Privacy:** Do not introduce code paths that expose unmasked video frames where privacy masking is required. The privacy pipeline must fail closed.
2. **Never Add External Cloud Dependencies:** Ingestion, neural inference, tracking, and forensic sealing must execute locally. Do not add external cloud API calls for core analytics.
3. **Never Weaken Cryptography:** Do not hardcode secret keys, disable signature verification, or bypass dual-control quorum checks.
4. **Isolate Production Audit Logs:** Tests must NEVER write to `logs/audit.jsonl`. Use isolated in-memory log sinks or temporary mock directories.
5. **Deterministic Testing:** Every new feature, bug fix, or security correction must be accompanied by unit or integration tests. All existing 245 tests must pass without failure.

---

## 3. Development Setup

### 3.1 Prerequisites
- Python 3.11, 3.12, 3.13, or 3.14
- Git 2.30+
- (Optional) NVIDIA GPU with CUDA 12.x or 13.x

### 3.2 Quick Setup
```bash
# Clone your fork
git clone https://github.com/<your-username>/CAMserv.IT.git
cd CAMserv.IT

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode with development & testing dependencies
pip install --upgrade pip setuptools wheel
pip install -e ".[dev,testing]"
```

### 3.3 Running the Test Suite
```bash
# Execute the complete automated test suite
python -m pytest tests/ -v

# Run with short traceback
python -m pytest tests/ --tb=short -q
```

---

## 4. Pull Request Workflow

1. **Create a Feature Branch:** Branch off `main` using descriptive naming: `feat/new-detector`, `fix/rtsp-timestamp-drift`, `docs/api-update`.
2. **Commit Hygiene:** Use Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
3. **Pre-Submit Checklist:**
   - [ ] All 245 automated tests pass cleanly.
   - [ ] No temporary files or production logs (`logs/audit.jsonl`) are modified.
   - [ ] New functionality has dedicated test coverage in `tests/`.
   - [ ] Code conforms to Ruff linting and type annotations.
4. **Open Pull Request:** Use `.github/PULL_REQUEST_TEMPLATE.md` to document your changes, test evidence, and security impact.
