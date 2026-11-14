# CAMserv Master Architecture Blueprint
**Document ID:** ARCH-BLUEPRINT-2026-001  
**Author:** Chief Software Architect & Principal Systems Engineer  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION PLANNING  
**Target Version:** CAMserv Enterprise 2.5 (Multi-Process Sovereign Architecture)

---

## 1. Architectural Vision & Core Principles

CAMserv is engineered as a zero-cloud-dependent, high-assurance security intelligence platform. It enforces five non-negotiable architectural mandates:
1. **Evidence Before Assumptions:** Algorithmic inferences are explicitly marked as probabilistic predictions ($p \in [0.0, 1.0]$) and never recorded as established facts.
2. **Reliability Before Features:** Ingestion and evidence preservation are isolated from heavy analytical workers; analytics crashes cannot drop camera frames or corrupt storage.
3. **Security Before Convenience:** Zero Trust network isolation, hardware-anchored envelope encryption (AES-256-GCM), asymmetric Ed25519 forensic signing, and immutable audit logs.
4. **Privacy Before Analytics:** Fail-closed identity obfuscation, non-biometric tracking IDs, and zero facial recognition feature vectors.
5. **Universal Hardware Sovereignty:** 100% on-premise operation adapting autonomously to 4 hardware tiers without mandatory cloud API dependencies.

---

## 2. Mermaid Architectural Diagrams

### 2.1 System Context Diagram (C4 Level 1)
```mermaid
flowchart TD
    subgraph External_World["External Physical & Network Environment"]
        CAM["IP Cameras / NVRs<br>(RTSP / ONVIF / H.264 / H.265)"]
        OPERATOR["Security Operators<br>(Web Console Browser)"]
        AUDITOR["Forensic Auditors / Legal<br>(Evidence Verification Tools)"]
        EXT_SYSTEMS["Physical Security / SIEM<br>(Webhooks / Syslog / MQTT)"]
    end

    subgraph CAMserv_Platform["CAMserv Security Intelligence Platform"]
        INGEST["Stream Ingestion & Software ISP"]
        AI_ENGINE["Edge AI & Tracking Core"]
        VAULT["Cryptographic Evidence Vault"]
        API_GW["FastAPI Core & WebSocket Bus"]
    end

    CAM -->|"RTSP/RTP over TCP (Port 554)"| INGEST
    INGEST --> AI_ENGINE
    AI_ENGINE --> VAULT
    AI_ENGINE --> API_GW
    API_GW <-->|"HTTPS (Port 443/8000) & WSS"| OPERATOR
    VAULT -->|"Sealed Evidence (.zip + Ed25519)"| AUDITOR
    API_GW -->|"Encrypted Alert Dispatches"| EXT_SYSTEMS
```

---

### 2.2 Container Architecture Diagram (C4 Level 2)
```mermaid
flowchart LR
    subgraph Ingestion_Container["camserv-ingestion (Process Isolated)"]
        FFMPEG["FFmpeg / NVDEC Subprocesses"]
        ISP_MOD["Software ISP & Ring Buffer"]
        SHM["Shared Memory (POSIX / IPC Frames)"]
    end

    subgraph Analytics_Worker["camserv-worker (GPU Accelerated)"]
        ORT["ONNX Runtime / TensorRT"]
        SEG["YOLOv8-seg & Pose Engine"]
        TRACK["ByteTrack / BoT-SORT Core"]
        THREAT["Local Threat & Arabic Narrative Engine"]
    end

    subgraph Core_Server["camserv-api (FastAPI Core)"]
        ROUTER["REST Endpoints & Auth RBAC"]
        WS_HUB["WebSocket Event Broadcaster"]
        AUDIT_LOG["Tamper-Evident Audit Logger"]
    end

    subgraph Storage_Layer["Sovereign Persistence Layer"]
        SQLITE["SQLite (WAL Mode)"]
        REDIS["Redis / In-Memory PubSub"]
        VAULT_DIR["WORM Evidence Vault (AES-256-GCM)"]
    end

    FFMPEG --> ISP_MOD --> SHM
    SHM --> ORT --> SEG --> TRACK --> THREAT
    THREAT --> WS_HUB
    THREAT --> VAULT_DIR
    ROUTER --> SQLITE
    ROUTER --> REDIS
    AUDIT_LOG --> SQLITE
```

---

### 2.3 Component Architecture Diagram (C4 Level 3)
```mermaid
flowchart TD
    subgraph Pipeline_Subsystem["Pipeline & Backpressure Subsystem"]
        ACQ["CameraStream (RTSP Ingest)"]
        DEC["FrameDecoder (Validation & Resizing)"]
        ISP["StreamProfiler (LAB CLAHE & ISP)"]
        Q_IN["RingBackpressureQueue (DROP_OLDEST)"]
    end

    subgraph Analytics_Subsystem["Inference & Reasoning Subsystem"]
        DET["ONNX/TensorRT ObjectDetector"]
        POSE["Pose & Keypoint Estimator"]
        HUD["Cinematic HUD & Contouring Renderer"]
        PRIV["Privacy Anonymizer (Blur / Mosaic)"]
        TEMP["Temporal Persistence Engine"]
        SCENE["Scene Anomaly Intelligence"]
    end

    subgraph Storage_Subsystem["Storage & Forensic Subsystem"]
        RAM_BUF["15s RAM Pre-Roll RingBuffer"]
        REC_TRIG["Incident Vault Trigger"]
        CRYPTO["Envelope Encryptor (AES-GCM)"]
        MERKLE["SHA-256 Merkle Chain & Ed25519"]
        WORM["WORM Retention Manager"]
    end

    ACQ --> DEC --> ISP --> Q_IN
    Q_IN --> DET --> POSE --> HUD --> PRIV
    DET --> TEMP --> SCENE
    ISP --> RAM_BUF
    SCENE --> REC_TRIG
    RAM_BUF --> REC_TRIG --> CRYPTO --> MERKLE --> WORM
```

---

### 2.4 Data Flow Diagram (End-to-End Pipeline)
```mermaid
sequenceDiagram
    autonumber
    actor Cam as RTSP Camera
    participant Ingest as Video Ingest Worker
    participant ISP as Software ISP Engine
    participant Infer as GPU Inference Worker
    participant Event as Temporal Event Engine
    participant Vault as Forensic Evidence Vault
    actor Op as Security Operator Web Console

    Cam->>Ingest: RTSP H.264/H.265 Packets (TCP)
    Ingest->>ISP: Raw BGR Frame Buffer
    ISP->>ISP: Auto CLAHE & Stream Profiling
    ISP->>Vault: Feed Continuous 15s RAM Pre-Roll
    ISP->>Infer: Push Frame to Zero-Copy IPC Queue
    Infer->>Infer: YOLOv8-seg Contours & Pose Extraction
    Infer->>Event: Detection DTOs + Keypoints + Tracks
    Event->>Event: Evaluate Threat Score & Rules
    alt Threat Score >= HIGH (70+)
        Event->>Vault: Trigger Incident Preservation
        Vault->>Vault: Package RAM Pre-Roll + Incident Stream
        Vault->>Vault: AES-256-GCM Encrypt + Ed25519 Sign
        Event->>Op: Broadcast WebSocket Critical Alert
        Op->>Event: Submit Operator HITL Verification
    else Normal Telemetry
        Event->>Op: Stream Anonymized HUD Telemetry
    end
```

---

### 2.5 Video Processing Pipeline Diagram
```mermaid
flowchart LR
    A["RTSP Video Stream<br>(H.264/H.265)"] -->|"Demux & Transport<br>(TCP Interleaved)"| B["Hardware Decoder<br>(NVDEC / VAAPI / CPU)"]
    B -->|"Raw YUV420p Surface"| C["Format Conversion<br>(YUV -> RGB / BGR)"]
    C -->|"1080p Frame"| D["Stream Profiler & ISP<br>(LAB CLAHE Luminance Boost)"]
    D -->|"RAM Ring Buffer"| E["15s Pre-Roll Buffer<br>(Zero Disk I/O)"]
    D -->|"Letterboxed 640x640"| F["Inference Tensor<br>(FP16 / INT8 CUDA)"]
    F -->|"Neural Latents"| G["Segmentation Polygons<br>& 17-Keypoint Poses"]
    G -->|"Tracks & Contours"| H["Cinematic HUD Layer<br>(Ground Rings & Reticles)"]
    H -->|"Final Blended Feed"| I["Privacy Masking Layer<br>(Gaussian / Mosaic Redaction)"]
    I -->|"Display Surface"| J["Operator Live Console<br>(WebRTC / MJPEG WSS)"]
```

---

### 2.6 Security Trust Boundary Diagram
```mermaid
flowchart TD
    subgraph Untrusted_Zone["Untrusted Network Zone"]
        CAM_NET["Camera IP Network (VLAN 20)"]
        PUB_NET["External Internet / Untrusted Clients"]
    end

    subgraph DMZ_Boundary["CAMserv Edge Security Boundary"]
        FIREWALL["Local Firewall & IP Filter"]
        TLS_TERM["TLS 1.3 Termination & Reverse Proxy"]
    end

    subgraph Application_Boundary["Protected Application Sandbox"]
        AUTH_MW["JWT & RBAC Security Middleware"]
        API_CORE["FastAPI Core Runtime"]
        WORKER_CORE["GPU Inference Workers (Non-Root)"]
    end

    subgraph Secure_Storage_Boundary["Isolated Forensic Vault Boundary"]
        KEY_STORE["Hardware TPM / Protected Key Ring"]
        EVIDENCE_DIR["Immutable WORM File Storage (chattr +i)"]
        AUDIT_STORE["Append-Only SHA-256 Chained Audit Log"]
    end

    CAM_NET -->|"Strict Firewall Rule (RTSP 554 only)"| FIREWALL
    PUB_NET -->|"TLS 1.3 Encrypted HTTPS/WSS"| TLS_TERM
    FIREWALL --> WORKER_CORE
    TLS_TERM --> AUTH_MW --> API_CORE
    API_CORE --> WORKER_CORE
    WORKER_CORE -->|"Encrypted Evidence Payload"| EVIDENCE_DIR
    API_CORE --> AUDIT_STORE
    KEY_STORE -.->|"Envelope Key Decryption"| EVIDENCE_DIR
```

---

### 2.7 Failure Propagation Diagram
```mermaid
flowchart TD
    subgraph Failure_Origins["Component Failure Event"]
        F1["Camera Disconnect / Packet Loss"]
        F2["GPU Out-of-Memory (OOM)"]
        F3["Corrupted Video Frame"]
        F4["Database Lock / Disk Exhaustion"]
    end

    subgraph Containment_Mechanisms["Containment & Isolation Layer"]
        C1["RTSP Reconnect Circuit Breaker<br>(Exponential Backoff 1s..60s)"]
        C2["CUDA OOM Trap & Degradation<br>(Auto Fallback to CPU Tier 1)"]
        C3["Frame Validator<br>(Drop Corrupted / Non-Zero Check)"]
        C4["Adaptive Vault Storage Guard<br>(RAM Pre-Roll Retention / Purge Tier 1)"]
    end

    subgraph Platform_State["Platform Impact State"]
        S1["Single Camera Stalled<br>(All Other Streams Continue Unaffected)"]
        S2["Reduced Analytical FPS<br>(Zero Platform Crash)"]
        S3["Single Frame Dropped<br>(Pipeline Continues Smoothly)"]
        S4["Critical Evidence Preserved in RAM<br>(Alert Sent to Operator)"]
    end

    F1 --> C1 --> S1
    F2 --> C2 --> S2
    F3 --> C3 --> S3
    F4 --> C4 --> S4
```

---

### 2.8 Deployment Architecture Diagram
```mermaid
flowchart TD
    subgraph Host_System["Edge Server / Enterprise Workstation (Linux / Windows)"]
        subgraph Hardware_Layer["Hardware Resources"]
            CPU["Multi-Core Host CPU (Intel / AMD / ARM)"]
            GPU["NVIDIA RTX GPU (CUDA 12+ / TensorRT)"]
            RAM["Host RAM (16 GB - 64 GB)"]
            NVME["Fast NVMe Storage (Forensic Vault)"]
        end

        subgraph Container_Runtime["Docker / Systemd Service Supervision"]
            C_API["camserv-api (Port 8000/443)"]
            C_WORKER["camserv-worker (GPU Pass-through)"]
            C_REDIS["camserv-cache (Redis 7 - Optional)"]
            C_MILVUS["camserv-vector (Milvus 2.4 - Optional)"]
        end
    end

    Hardware_Layer --- Container_Runtime
```

---

## 3. Module Interface Contracts & Boundary Specifications

### Module Contract Registry
1. **Video Ingestion Worker (`camserv.acquisition.camera`):**
   - *Input:* RTSP URL, transport protocol (`tcp`), reconnect interval.
   - *Output:* Raw `VideoFrame` DTO with monotonic timestamp, sequence number, and decoded numpy BGR surface.
   - *Failure Boundary:* Crash of capture loop triggers local worker restart without terminating pipeline engine.
2. **Software ISP (`camserv.acquisition.isp`):**
   - *Input:* `VideoFrame` (Raw BGR).
   - *Output:* `VideoFrame` (Luminance-equalized via LAB CLAHE, profiled with contrast/sharpness metrics).
   - *Contract:* Must execute in $< 4.5\text{ ms}$ per frame on 1080p.
3. **Inference & Contouring Engine (`camserv.inference.detector` & `segmentation`):**
   - *Input:* Preprocessed frame tensor ($640 \times 640 \times 3$).
   - *Output:* List of `Detection` DTOs with polygon contour coordinates, 17 COCO keypoints, posture hint, and bounded confidence $p \in [0.0, 1.0]$.
4. **Deterministic Threat Engine (`camserv.events.threat_engine`):**
   - *Input:* List of active `Track` objects, scene telemetry, exclusion zones.
   - *Output:* `ThreatAssessment` with composite score $T \in [0, 100]$, factor breakdown ($w_1\dots w_5$), and bilingual Arabic/English situation narrative.
5. **Cryptographic Vault (`camserv.storage.adaptive_vault`):**
   - *Input:* Evidence package containing incident metadata, video chunks, and operator review logs.
   - *Output:* Sealed `.vault` archive with AES-256-GCM ciphertext, SHA-256 Merkle root, and Ed25519 asymmetric signature.
