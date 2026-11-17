# Contributing to CAMserv

Thank you for your interest in contributing to the **CAMserv Advanced Security Intelligence Platform**.

CAMserv operates under a strict engineering governance protocol to guarantee mathematical reliability, defense-in-depth cybersecurity, and privacy preservation.

---

## 1. The 10-Step Engineering Protocol

Every contributor must follow these engineering principles:

1. **Inspect Existing Code:** Thoroughly examine related modules before authoring changes.
2. **Respect Interfaces:** All components must implement the `typing.Protocol` classes defined in `camserv.pipeline.interfaces`.
3. **Epistemic Transparency:** Detections and inferred events must always set `is_prediction: bool = True` and bound confidence to $[0.0, 1.0]$. Inferences must never be asserted as established facts.
4. **Anonymity Guarantee:** Tracks must use transient integer IDs only. Never link, infer, or store biometric templates or real-world identities.
5. **Human-in-the-Loop:** Consequential physical or dispatch alerts (`severity >= HIGH`) must require human operator sign-off.
6. **Controlled Modifications:** Keep pull requests focused, modular, and minimal.
7. **Comprehensive Tests:** Add or update unit, adversarial, or integration tests with every code modification.
8. **Run Verification:** Verify that 100% of the test suite passes (`python -m pytest tests/`).
9. **Document Limitations:** Document operational bounds, hardware requirements, and known constraints.
10. **Architecture Records:** Document non-trivial architectural changes in an Architecture Decision Record (ADR) under `docs/adr/`.

---

## 2. Development Setup

### Prerequisites
* Python 3.11, 3.12, 3.13, or 3.14
* Git
* (Optional) NVIDIA GPU with CUDA drivers for GPU acceleration

### Local Installation
```bash
git clone git@github.com:aboulouafaeit-sys/CAMserv.IT.git
cd CAMserv.IT

# Install in editable mode with development and testing dependencies
pip install -e ".[dev,testing]"
```

### Running the Test Suite
```bash
# Run the complete test suite (615 automated tests across 66 modules)
python -m pytest tests/ -v

# Run with short traceback
python -m pytest tests/ --tb=short -q

# Run with coverage report
python -m pytest tests/ --cov=camserv
```

> For extended architectural standards, PR checklists, and security invariant rules, see the [Comprehensive Contributor Guide](docs/presentation/CONTRIBUTOR_GUIDE.md).

### Running the CLI
```bash
# Hardware diagnostics
python -m camserv.main detect-hw

# Verify audit trail hash continuity
python -m camserv.main audit-verify

# Launch the server with embedded web console
python -m camserv.main serve --host 127.0.0.1 --port 8000
```
