# ADR-005: Dual-Layer Persistence (SQLite & Milvus) with Zero-Biometrics Guarantee

## Status
Accepted

## Context
The existing implementation maintained camera settings, active user records, and dynamic rules in transient Python dictionaries on `app.state`, causing configuration loss upon process termination. Furthermore, while Milvus vector storage is integrated, its privacy boundaries must be strictly defended against accidental biometric ingestion.

## Decision
1. Implement a durable transactional relational storage layer (`src/camserv/storage/sqlite_store.py`) using SQLite with WAL (Write-Ahead Logging) mode enabled for high-concurrency read/write operations.
2. Store camera definitions, persistent event history, user credentials (PBKDF2 hashes), and privacy zone coordinates in SQLite.
3. Restrict Milvus vector storage exclusively to scene-level perceptual embeddings (e.g. ambient environmental descriptors, scene lighting changes) with a 128-dimensional schema.
4. Programmatically reject any vector insertion associated with a `person` or `face` class ID.
5. Provide automatic schema migrations and encrypted automated backup CLI tools.

## Consequences
- Positive: State survives reboots without requiring external SQL server dependencies; zero deployment friction for edge nodes.
- Negative: SQLite requires local disk I/O; multi-node clusters will require WAL synchronization or future Postgres migration.
