# CAMserv System Dependency Map

```mermaid
graph TD
    subgraph UI ["Layer 4: Presentation & Product Experience"]
        WEB["CAMserv Enterprise Web Console (HTML5/CSS3/TS)"]
        CLI["CAMserv Unified CLI (src/camserv/main.py)"]
        BRAND["Brand Assets & Design Tokens (SVG/CSS)"]
    end

    subgraph API ["Layer 3: Service & Interface Layer"]
        FASTAPI["FastAPI Application Factory (src/camserv/api/app.py)"]
        ROUTES["REST & WebSocket Endpoints (src/camserv/api/routes.py)"]
        AUTH["RBAC & RS256 AuthManager (src/camserv/security/auth.py)"]
    end

    subgraph CORE ["Layer 2: Core Processing Engine"]
        PIPE["Pipeline Engine & Bounded Queues (src/camserv/pipeline/)"]
        INFER["Inference Engine & Scene Analyzer (src/camserv/inference/)"]
        TRACK["ByteTrack & BoT-SORT Trackers (src/camserv/tracking/)"]
        EVENT["Temporal Event Detector & Alert Manager (src/camserv/events/)"]
        ONVIF["ONVIF & RTSP Camera Manager (src/camserv/acquisition/)"]
        PRIV["Privacy & Anonymization Filter (src/camserv/inference/privacy.py)"]
    end

    subgraph DATA ["Layer 1: Persistence, Forensics & Cryptography"]
        SQL["SQLite Metadata Store (src/camserv/storage/sqlite_store.py)"]
        REDIS["Redis State Cache (src/camserv/storage/redis_cache.py)"]
        MILVUS["Milvus Scene Vector Store (src/camserv/storage/milvus_store.py)"]
        EVID["Evidence Store & Ed25519 Forensics (src/camserv/storage/evidence.py)"]
        AUDIT["Immutable Hash-Chained Audit Trail (src/camserv/security/audit.py)"]
        CRYPTO["AES-256-GCM & HKDF Encryption Manager (src/camserv/security/encryption.py)"]
        HW["Hardware Detection & Capabilities (src/camserv/platform/hardware.py)"]
    end

    WEB --> FASTAPI
    CLI --> PIPE
    CLI --> FASTAPI
    CLI --> EVID
    FASTAPI --> ROUTES
    ROUTES --> AUTH
    ROUTES --> PIPE
    ROUTES --> SQL
    ROUTES --> REDIS
    ROUTES --> EVID
    ROUTES --> AUDIT
    PIPE --> ONVIF
    PIPE --> INFER
    PIPE --> PRIV
    PIPE --> TRACK
    PIPE --> EVENT
    PIPE --> SQL
    PIPE --> REDIS
    PIPE --> EVID
    EVID --> CRYPTO
    AUDIT --> CRYPTO
    INFER --> HW
```

### Subsystem Inter-Dependencies:
1. **Acquisition Layer** depends on `OpenCV` / `aiohttp` / socket networking; falls back to synthetic video generators in headless/offline tests.
2. **Inference Layer** depends on `ONNXRuntime` / `CUDA` / `NumPy`; falls back to pure NumPy/CPU math when hardware acceleration is unavailable.
3. **Tracking Layer** depends on `SciPy` (Hungarian assignment) / `NumPy`; operates purely on numerical coordinates and anonymous integer IDs.
4. **Events Layer** depends on Tracking outputs and Privacy-filtered spatial zones; enforces human verification for consequential alerts.
5. **Storage Layer** provides hybrid persistence: SQLite for transactional configurations and state, Redis for low-latency active tracks, Milvus for non-identifying scene vectors, and encrypted disk for tamper-evident evidence packages.
6. **API & Web Console** depends on FastAPI, consuming the storage and pipeline layers while serving static assets and REST/WebSocket APIs.
