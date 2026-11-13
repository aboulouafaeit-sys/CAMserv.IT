"""CAMserv Milvus vector storage for privacy-preserving visual analytics.

Provides :class:`MilvusStore`: an enterprise vector store for non-identifying
visual analytics such as scene descriptors, global context embeddings, and
anomaly vectors.

CRITICAL PRIVACY GUARANTEE:
  * NO biometric data, face recognition embeddings, or personally identifiable
    information (PII) is permitted or stored in this collection.
  * Only anonymous scene-level features and environmental context vectors
    (e.g., crowding, background change, optical flow summaries) are stored.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Try importing pymilvus
try:
    from pymilvus import (
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        connections,
        utility,
    )

    HAS_MILVUS = True
except ImportError:  # pragma: no cover
    HAS_MILVUS = False
    Collection = None  # type: ignore[assignment,misc]
    CollectionSchema = None  # type: ignore[assignment,misc]
    DataType = None  # type: ignore[assignment,misc]
    FieldSchema = None  # type: ignore[assignment,misc]
    connections = None  # type: ignore[assignment,misc]
    utility = None  # type: ignore[assignment,misc]


class MilvusStore:
    """Vector database client for storing and querying non-identifying scene analytics.

    Index Configuration & Trade-offs:
      - IVF_FLAT:
          * Pros: Fast build time, low memory footprint, good balance of recall and search latency for <1M vectors.
          * Cons: Requires nprobe tuning; recall degrades if nprobe is too small.
      - HNSW (Hierarchical Navigable Small World):
          * Pros: Extremely high recall (>98%) with sub-millisecond query latency; graph-based navigation.
          * Cons: Higher RAM overhead and longer indexing build time.

    Default configured index is IVF_FLAT with nlist=128 for lightweight edge/server deployments.
    """

    # Primary collection schema fields
    FIELD_ID = "id"
    FIELD_VECTOR = "scene_vector"
    FIELD_CAMERA_ID = "camera_id"
    FIELD_TIMESTAMP = "timestamp"  # unix epoch float
    FIELD_ANALYTIC_TYPE = "analytic_type"  # e.g. "scene_context", "anomaly_pattern"
    FIELD_DESCRIPTION = "description"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        collection_name: str = "camserv_scene_analytics",
        dim: int = 128,
        index_type: str = "IVF_FLAT",
        metric_type: str = "IP",  # Inner Product (cosine if normalised)
        nprobe: int = 16,
        alias: str = "default",
        enable_fallback: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.dim = dim
        self.index_type = index_type.upper()
        self.metric_type = metric_type.upper()
        self.nprobe = nprobe
        self.alias = alias
        self.enable_fallback = enable_fallback

        self._collection: Any | None = None
        self._is_connected = False
        self._lock = asyncio.Lock()

        # In-memory fallback for unit testing or when Milvus is not running
        # list of dicts: {"id": str, "vector": np.ndarray, "camera_id": str, "timestamp": float, ...}
        self._memory_vectors: list[dict[str, Any]] = []

    async def connect(self) -> bool:
        """Connect to Milvus server and initialise collection."""
        if not HAS_MILVUS:
            logger.warning("milvus.unavailable", reason="pymilvus not installed")
            self._is_connected = False
            return False

        async with self._lock:
            if self._is_connected and self._collection is not None:
                return True

            try:
                # Milvus connections are synchronous; wrap in asyncio executor
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: connections.connect(
                        alias=self.alias,
                        host=self.host,
                        port=str(self.port),
                        timeout=5.0,
                    ),
                )
                self._is_connected = True
                await self._init_collection()
                logger.info("milvus.connected", host=self.host, port=self.port, collection=self.collection_name)
                return True
            except Exception as exc:
                logger.warning(
                    "milvus.connection_failed",
                    host=self.host,
                    port=self.port,
                    error=str(exc),
                    fallback="in-memory" if self.enable_fallback else "none",
                )
                self._is_connected = False
                return False

    async def _init_collection(self) -> None:
        """Create collection and index if they do not exist."""
        loop = asyncio.get_running_loop()

        def _setup() -> None:
            if not utility.has_collection(self.collection_name, using=self.alias):
                fields = [
                    FieldSchema(
                        name=self.FIELD_ID,
                        dtype=DataType.VARCHAR,
                        max_length=64,
                        is_primary=True,
                        auto_id=False,
                    ),
                    FieldSchema(
                        name=self.FIELD_VECTOR,
                        dtype=DataType.FLOAT_VECTOR,
                        dim=self.dim,
                    ),
                    FieldSchema(
                        name=self.FIELD_CAMERA_ID,
                        dtype=DataType.VARCHAR,
                        max_length=64,
                    ),
                    FieldSchema(
                        name=self.FIELD_TIMESTAMP,
                        dtype=DataType.DOUBLE,
                    ),
                    FieldSchema(
                        name=self.FIELD_ANALYTIC_TYPE,
                        dtype=DataType.VARCHAR,
                        max_length=32,
                    ),
                    FieldSchema(
                        name=self.FIELD_DESCRIPTION,
                        dtype=DataType.VARCHAR,
                        max_length=256,
                    ),
                ]
                schema = CollectionSchema(
                    fields=fields,
                    description="CAMserv anonymous scene-level analytics vector collection. NO BIOMETRICS.",
                )
                col = Collection(
                    name=self.collection_name,
                    schema=schema,
                    using=self.alias,
                )
            else:
                col = Collection(name=self.collection_name, using=self.alias)

            # Build index if not present
            if not col.has_index():
                if self.index_type == "HNSW":
                    index_params = {
                        "metric_type": self.metric_type,
                        "index_type": "HNSW",
                        "params": {"M": 16, "efConstruction": 200},
                    }
                else:  # Default IVF_FLAT
                    index_params = {
                        "metric_type": self.metric_type,
                        "index_type": "IVF_FLAT",
                        "params": {"nlist": 128},
                    }
                col.create_index(field_name=self.FIELD_VECTOR, index_params=index_params)
            col.load()
            self._collection = col

        await loop.run_in_executor(None, _setup)

    async def close(self) -> None:
        """Disconnect from Milvus."""
        async with self._lock:
            if self._is_connected and HAS_MILVUS:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: connections.disconnect(alias=self.alias),
                    )
                except Exception:
                    pass
            self._is_connected = False
            self._collection = None
            self._memory_vectors.clear()
            logger.info("milvus.closed")

    async def health_check(self) -> bool:
        """Verify vector store connectivity."""
        if not self._is_connected or self._collection is None:
            return await self.connect()
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: utility.has_collection(self.collection_name, using=self.alias),
            )
        except Exception as exc:
            logger.warning("milvus.health_check_failed", error=str(exc))
            self._is_connected = False
            return False

    # ---------------------------------------------------------------------------
    # Vector insertion & query
    # ---------------------------------------------------------------------------

    async def insert_scene_analytic(
        self,
        record_id: str,
        vector: Sequence[float] | np.ndarray,
        camera_id: str,
        timestamp: datetime | float | None = None,
        analytic_type: str = "scene_context",
        description: str = "",
    ) -> bool:
        """Insert an anonymous scene-level vector embedding.

        CRITICAL: Never pass face or biometric embeddings to this method.
        """
        arr = np.asarray(vector, dtype=np.float32).flatten()
        if arr.shape[0] != self.dim:
            raise ValueError(f"Vector dimension {arr.shape[0]} does not match collection dim {self.dim}")

        ts_epoch: float
        if timestamp is None:
            ts_epoch = datetime.now(timezone.utc).timestamp()
        elif isinstance(timestamp, datetime):
            ts_epoch = timestamp.timestamp()
        else:
            ts_epoch = float(timestamp)

        record = {
            "id": record_id,
            "vector": arr,
            "camera_id": camera_id,
            "timestamp": ts_epoch,
            "analytic_type": analytic_type,
            "description": description[:255],
        }

        if self._is_connected and self._collection is not None:
            try:
                loop = asyncio.get_running_loop()
                data = [
                    [record_id],
                    [arr.tolist()],
                    [camera_id],
                    [ts_epoch],
                    [analytic_type],
                    [description[:255]],
                ]
                await loop.run_in_executor(
                    None,
                    lambda: self._collection.insert(data),  # type: ignore[union-attr]
                )
                return True
            except Exception as exc:
                logger.warning("milvus.insert_failed", id=record_id, error=str(exc))
                self._is_connected = False

        if self.enable_fallback:
            # Update existing or append
            self._memory_vectors = [v for v in self._memory_vectors if v["id"] != record_id]
            self._memory_vectors.append(record)
            return True

        return False

    async def search_similar_scenes(
        self,
        query_vector: Sequence[float] | np.ndarray,
        top_k: int = 10,
        camera_id: str | None = None,
        analytic_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar non-identifying scene context vectors."""
        q_arr = np.asarray(query_vector, dtype=np.float32).flatten()
        if q_arr.shape[0] != self.dim:
            raise ValueError(f"Query vector dim {q_arr.shape[0]} != {self.dim}")

        if self._is_connected and self._collection is not None:
            try:
                loop = asyncio.get_running_loop()
                search_params = {"metric_type": self.metric_type, "params": {"nprobe": self.nprobe}}
                expr = ""
                expr_parts = []
                if camera_id:
                    expr_parts.append(f'camera_id == "{camera_id}"')
                if analytic_type:
                    expr_parts.append(f'analytic_type == "{analytic_type}"')
                if expr_parts:
                    expr = " and ".join(expr_parts)

                def _search() -> list[dict[str, Any]]:
                    results = self._collection.search(  # type: ignore[union-attr]
                        data=[q_arr.tolist()],
                        anns_field=self.FIELD_VECTOR,
                        param=search_params,
                        limit=top_k,
                        expr=expr if expr else None,
                        output_fields=[
                            self.FIELD_ID,
                            self.FIELD_CAMERA_ID,
                            self.FIELD_TIMESTAMP,
                            self.FIELD_ANALYTIC_TYPE,
                            self.FIELD_DESCRIPTION,
                        ],
                    )
                    out: list[dict[str, Any]] = []
                    if results and len(results) > 0:
                        for hit in results[0]:
                            out.append({
                                "id": hit.id,
                                "score": float(hit.score),
                                "camera_id": hit.entity.get(self.FIELD_CAMERA_ID),
                                "timestamp": hit.entity.get(self.FIELD_TIMESTAMP),
                                "analytic_type": hit.entity.get(self.FIELD_ANALYTIC_TYPE),
                                "description": hit.entity.get(self.FIELD_DESCRIPTION),
                            })
                    return out

                return await loop.run_in_executor(None, _search)
            except Exception as exc:
                logger.warning("milvus.search_failed", error=str(exc))
                self._is_connected = False

        if self.enable_fallback:
            return self._search_memory(q_arr, top_k=top_k, camera_id=camera_id, analytic_type=analytic_type)

        return []

    def _search_memory(
        self,
        query: np.ndarray,
        top_k: int,
        camera_id: str | None,
        analytic_type: str | None,
    ) -> list[dict[str, Any]]:
        """In-memory similarity search using numpy cosine / inner product."""
        candidates = self._memory_vectors
        if camera_id:
            candidates = [c for c in candidates if c["camera_id"] == camera_id]
        if analytic_type:
            candidates = [c for c in candidates if c["analytic_type"] == analytic_type]

        if not candidates:
            return []

        q_norm = np.linalg.norm(query)
        if q_norm == 0:
            q_norm = 1e-8

        scored: list[tuple[float, dict[str, Any]]] = []
        for cand in candidates:
            vec = cand["vector"]
            v_norm = np.linalg.norm(vec)
            if v_norm == 0:
                v_norm = 1e-8
            # Cosine similarity
            score = float(np.dot(query, vec) / (q_norm * v_norm))
            scored.append((score, cand))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[dict[str, Any]] = []
        for score, item in scored[:top_k]:
            results.append({
                "id": item["id"],
                "score": score,
                "camera_id": item["camera_id"],
                "timestamp": item["timestamp"],
                "analytic_type": item["analytic_type"],
                "description": item["description"],
            })
        return results

    # ---------------------------------------------------------------------------
    # Retention Policy Enforcement
    # ---------------------------------------------------------------------------

    async def enforce_retention(self, older_than_seconds: float) -> int:
        """Purge vectors older than specified age for GDPR / retention compliance.

        Returns the number of deleted records (or estimated deleted count).
        """
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_seconds
        deleted = 0

        if self._is_connected and self._collection is not None:
            try:
                loop = asyncio.get_running_loop()
                expr = f"{self.FIELD_TIMESTAMP} < {cutoff}"

                def _delete() -> None:
                    self._collection.delete(expr)  # type: ignore[union-attr]

                await loop.run_in_executor(None, _delete)
                logger.info("milvus.retention_enforced", cutoff_timestamp=cutoff)
            except Exception as exc:
                logger.warning("milvus.retention_enforce_failed", error=str(exc))
                self._is_connected = False

        if self.enable_fallback:
            initial_len = len(self._memory_vectors)
            self._memory_vectors = [v for v in self._memory_vectors if v["timestamp"] >= cutoff]
            deleted = initial_len - len(self._memory_vectors)

        return deleted
