# CAMserv — Phase 26.4: Technical Architecture Diagrams & Visual Documentation

**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** 0.10.0-rc7  
**Subsystem:** Technical Architecture & System Engineering Diagrams  
**Document:** `docs/PHASE-26.4-ARCHITECTURE-DIAGRAMS.md`  
**Classification:** System Architecture Specification & Visual Models  

---

## 1. Executive Summary

This document presents the official, updated technical architecture diagrams for CAMserv 0.10.0-rc7. All diagrams are authored in clean, editable **Mermaid syntax** and reflect the actual verified state of the codebase following the completion of Phase 25 (Hardware Adaptation & Appliance Engineering) and Phases 26–26.3 (Local-First Zero-Trust Identity Foundation & Trust Boundary Closure).

---

## 2. Diagram 1: High-Level Platform Architecture

```mermaid
flowchart TD
    subgraph INGEST ["1. Video Acquisition & Optical Pipeline"]
        direction TB
        CAM["IP Cameras (ONVIF / RTSP)"] --> SUPERV["Ingestion Supervisor & Worker Isolation"]
        SUPERV --> ISP["Software ISP (LAB CLAHE & Denoise)"]
        ISP --> SHM["Zero-Copy Shared Memory Ring Buffer"]
    end

    subgraph PIPELINE ["2. Ingestion Stability & Continuity"]
        direction TB
        SHM --> BPQ["Bounded Pipeline Queue (Bounded Queues)"]
        BPQ --> RCL["Recording Continuity Ledger (Discontinuity Tracking)"]
        RCL --> SEGW["Segment Storage Writer"]
    end

    subgraph ADAPTIVE ["3. Universal Hardware Adaptation (Phase 25)"]
        direction TB
        SHM --> ADAPT["Adaptive Resource Governor"]
        ADAPT --> DETECT["ONNX Neural Engine (DirectML / CUDA / OpenVINO)"]
        ADAPT -.->|High Load / GPU Unavailable| CPU_FAIL["CPU Fallback Admission Control"]
        CPU_FAIL --> CPU_DET["Quantized CPU Inference"]
        DETECT --> TRACK["Anonymous Tracker (ByteTrack / BoT-SORT)"]
        CPU_DET --> TRACK
    end

    subgraph PRIVACY ["4. Centralized Privacy Pipeline"]
        direction TB
        DETECT --> PRIV["Fail-Closed Privacy Pipeline"]
        PRIV -->|Normal Redaction| MASKED["Anonymized Derivative Video"]
        PRIV -->|Timeout / Fault| BLACKOUT["Fail-Closed Blackout State"]
        PRIV -->|Original Stream| VAULT["Forensic Evidence Preservation"]
    end

    subgraph IDENTITY ["5. Zero-Trust Identity & Access (Phase 26–26.3)"]
        direction TB
        CLIENT["Web / API Client"] --> SENTINEL["Sentinel Threat Engine & Anti-Spoofing"]
        SENTINEL --> AUTH["Argon2id Hasher & TOTP MFA (AAL2)"]
        AUTH --> SESS["Stateful Session Manager (Fixation Defense)"]
        SESS --> POLICY["Zero-Trust Policy Engine (BOLA / IDOR Defense)"]
        LOCK["Emergency Lockdown Manager (HMAC Latch)"] -.->|Emergency Containment| POLICY
    end

    subgraph STORAGE ["6. Tiered Storage & Forensics"]
        direction TB
        SEGW --> NVME["Operational Storage Pool (Auto-Purge)"]
        VAULT --> EVID["Encrypted Vault (AES-256-GCM + WORM)"]
        EVID --> HASH["Tamper-Evident SHA-256 Hash Chain Ledger"]
        HASH --> ANCHOR["External Signed Checkpoint Store (trust_anchor.json)"]
    end

    subgraph WORKFLOW ["7. Operator Console & HITL Review"]
        direction TB
        TRACK --> THREAT["Kinematic Threat Engine"]
        THREAT --> HITL["Human-in-the-Loop Review Queue"]
        HITL --> DISPATCH["Authorized Incident Dispatch"]
        HITL --> QUORUM["Dual-Control Quorum Evidence Export"]
    end

    POLICY ==> WORKFLOW
```

---

## 3. Diagram 2: Video Ingestion & Recording Continuity Flow

```mermaid
sequenceDiagram
    autonumber
    participant RTSP as Camera (RTSP/ONVIF)
    participant Worker as Camera Worker Process
    participant BPQ as BoundedPipelineQueue
    participant RCL as RecordingContinuityLedger
    participant Disk as Segment Storage (NVMe/SATA)
    participant Crypto as SHA-256 Evidence Hasher

    RTSP->>Worker: 1. H.264/H.265 NAL Units
    Worker->>Worker: 2. Optical Conditioning (LAB CLAHE)
    Worker->>BPQ: 3. push_frame(pts, seq, payload)
    Note over BPQ: Bounded queue prevents memory exhaustion during storage latency
    BPQ->>RCL: 4. record_frame(camera_id, seq, pts)
    Note over RCL: Discontinuity accounting: confirmed vs estimated vs unknown frame loss
    BPQ->>Disk: 5. Write Segment (.mp4 / .ts)
    Disk->>Crypto: 6. Update Sequential SHA-256 Digest
    Crypto-->>Disk: 7. Atomic Segment Manifest (.manifest.json)
```

---

## 4. Diagram 3: Identity, Authentication & Zero-Trust Authorization

```mermaid
flowchart TD
    User["Connecting User / Client"] --> Login["POST /api/v1/auth/token"]
    Login --> IP_Check["resolve_client_ip (Untrusted Header Stripping)"]
    IP_Check --> Sentinel["Sentinel Threat Engine (Brute-Force & Anti-Lockout)"]
    
    Sentinel --> Pwd["Argon2id Password Verification"]
    Pwd -- "Valid" --> MFA_Check{"Is User Admin or AAL2?"}
    Pwd -- "Invalid" --> Fail["Login Failure Event + Progressive Delay"]
    
    MFA_Check -- "Yes" --> TOTP["RFC 6238 TOTP Validation / Recovery Codes"]
    MFA_Check -- "No" --> IssueAAL1["Issue Session Token (AAL1)"]
    TOTP -- "Valid" --> IssueAAL2["Issue Session Token (AAL2)"]
    TOTP -- "Invalid" --> FailMFA["MFA Failure Event"]

    subgraph Authorization_Pipeline ["Zero-Trust Object-Level Policy Engine"]
        Req["Target Operation (e.g. camera:view, evidence:export)"]
        Req --> Check_Lockdown{"Is Emergency Lockdown Active?"}
        Check_Lockdown -- "Yes" --> Lockdown_Gate{"Is Action Whitelisted?<br/>(recording:ingest, system:status, emergency:lift)"}
        Lockdown_Gate -- "No" --> DenyLock["DENY: Emergency Lockdown Active"]
        Lockdown_Gate -- "Yes" --> AllowLock["PERMIT: Invariant Pipeline Action"]

        Check_Lockdown -- "No" --> Check_AAL{"Does Action Mandate AAL2?<br/>(evidence:export, system:config)"}
        Check_AAL -- "Yes & Session=AAL1" --> StepUp["DENY: Step-Up MFA Challenge Required"]
        Check_AAL -- "Satisfied" --> Check_BOLA{"Object-Level Scope Check<br/>(Is Target Camera in User's Scopes?)"}
        
        Check_BOLA -- "Yes" --> Permit["PERMIT: Action Authorized"]
        Check_BOLA -- "No" --> DenyBOLA["DENY: BOLA/IDOR Scope Violation"]
    end

    IssueAAL1 --> Authorization_Pipeline
    IssueAAL2 --> Authorization_Pipeline
```

---

## 5. Diagram 4: Security Trust Boundaries & Audit Checkpoint Anchoring

```mermaid
flowchart TD
    subgraph Host_Boundary ["Physical Appliance Host Boundary"]
        subgraph App_Data ["data/ Application Directory"]
            SQLite["data/identity.db<br/>(Security Events & Forward Hash Chain)"]
            Latch["data/.emergency_lockdown.latch<br/>(HMAC-Signed Recovery State)"]
            Token["data/.bootstrap_token<br/>(Pre-Hardened DACL, Single-Use)"]
        end

        subgraph External_Store ["data/checkpoints/ (Independent Trust Anchor)"]
            Anchor["trust_anchor.json<br/>(Signed Monotonic Checkpoints: HMAC/Ed25519)"]
        end

        subgraph Invariant_Logs ["logs/ Invariant Directory"]
            Audit["logs/audit.jsonl<br/>(20,977 bytes, SHA-256 Inviolate)"]
        end
    end

    subgraph Hardware_Boundary ["Independent Hardware Trust Boundary (Enterprise / Planned)"]
        TPM["TPM 2.0 NVRAM Monotonic Counter (Hardware Non-Volatile)"]
        SIEM["Remote Syslog / Immutable Cloud WORM Ledger"]
    end

    SQLite -->|Periodic Head Checkpoint| Anchor
    Anchor -->|Monotonicity Verification| SQLite
    
    Anchor -.->|Enterprise Rollback Defense| TPM
    SQLite -.->|Offsite Audit Streaming| SIEM
    
    Note1["Theorem 1 (Local State Rollback Indistinguishability):<br/>Local software cannot detect host-level disk rollback<br/>without an independent hardware/external trust anchor."]
```

---

## 6. Diagram 5: Multi-Tier Storage Architecture & Forensic Vault

```mermaid
flowchart LR
    subgraph Tier0 ["Tier 0: Volatile RAM"]
        PREROLL["15-Second RAM Pre-Roll Ring Buffer<br/>(Full FPS, Uncompressed)"]
    end

    subgraph Tier1 ["Tier 1: High-Speed NVMe Storage"]
        OPERATIONAL["Operational Video Pool<br/>(48-Hour Retention, Auto-Purge)"]
    end

    subgraph Tier2 ["Tier 2: Encrypted Forensic Archive"]
        VAULT["Cryptographic Evidence Vault<br/>(AES-256-GCM Sealing + Judicial Holds)"]
    end

    subgraph Tier3 ["Tier 3: Export & Chain of Custody"]
        EXPORT["Signed ZIP Package<br/>(Video + Metadata + Ed25519 Signature)"]
    end

    PREROLL -->|Incident Trigger| VAULT
    OPERATIONAL -->|Judicial Hold Flag| VAULT
    VAULT -->|Dual-Control Quorum| EXPORT
```

---

## 7. Diagram 6: Universal Hardware Adaptation & CPU Failover

```mermaid
flowchart TD
    Probe["detect-hw Diagnostic Probe"] --> Inspect{"Inspect Host Capabilities"}
    
    Inspect -- "Discrete NVIDIA GPU (CUDA >= 12.0)" --> T4["Tier 4: Enterprise Hardware<br/>Full 4K Ingestion, Batch Neural Vision, Real-Time HUD"]
    Inspect -- "Intel iGPU / NPU (OpenVINO)" --> T3["Tier 3: Standard Appliance<br/>Full HD 1080p Ingestion, iGPU Neural Vision"]
    Inspect -- "Windows DirectML / AMD iGPU" --> T2["Tier 2: Edge Appliance<br/>720p Ingestion, DirectML Acceleration"]
    Inspect -- "Generic x86_64 CPU Only" --> T1["Tier 1: Minimal Appliance (GPU-Optional)<br/>Quantized CPU Inference, Load Shedding, Full Continuity"]

    subgraph Runtime_Adaptation ["Runtime Adaptive Governor (Phase 25)"]
        T1 --> Gov["Resource Governor & Watchdog"]
        T2 --> Gov
        T3 --> Gov
        T4 --> Gov

        Gov --> Monitor{"Monitor Queue Fill Ratio & Latency"}
        Monitor -- "Queue < 70%" --> Normal["Normal Pipeline Processing"]
        Monitor -- "Queue >= 70%" --> Shed["Load Shedding: Skip Non-Keyframe AI Inference"]
        Monitor -- "GPU Thermal / Driver Stall" --> Fallback["CPU Fallback Admission Control (Continuous Video Guaranteed)"]
    end
```
