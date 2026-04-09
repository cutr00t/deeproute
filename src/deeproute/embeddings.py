"""Lightweight embeddings with backend abstraction — OpenAI or Vertex AI.

Embeds function descriptions, module summaries, and tags for semantic search.
Stores as .deeproute/v2/embeddings.npz — flat file, no infra required.

Backend selection mirrors llm_client.py:
- Personal (OPENAI_API_KEY set, no Vertex): OpenAI text-embedding-3-small
- Work (Vertex/ADC credentials): Google text-embedding-004 via Vertex AI
- Both set: respects DEEPROUTE_BACKEND or DEEPROUTE_EMBEDDING_BACKEND override
- Neither: embeddings skipped, text search still works
"""

from __future__ import annotations

import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EMBEDDINGS_FILE = "embeddings.npz"


class EmbeddingBackend(str, Enum):
    OPENAI = "openai"
    VERTEX = "vertex"
    NONE = "none"


# Backend configs
_BACKEND_CONFIG: dict[EmbeddingBackend, dict[str, Any]] = {
    EmbeddingBackend.OPENAI: {
        "model": "text-embedding-3-small",
        "dim": 1536,
    },
    EmbeddingBackend.VERTEX: {
        "model": "text-embedding-004",
        "dim": 768,
    },
}


def detect_embedding_backend() -> EmbeddingBackend:
    """Auto-detect embedding backend from environment.

    Priority:
    1. DEEPROUTE_EMBEDDING_BACKEND explicit override
    2. DEEPROUTE_BACKEND (shared with LLM client)
    3. Auto-detect: Vertex credentials → vertex, OpenAI key → openai
    """
    # Explicit embedding backend override
    explicit = os.environ.get("DEEPROUTE_EMBEDDING_BACKEND", "").strip().lower()
    if explicit in ("openai", "vertex"):
        return EmbeddingBackend(explicit)

    # Fall back to shared LLM backend setting
    shared = os.environ.get("DEEPROUTE_BACKEND", "").strip().lower()
    if shared == "vertex":
        return EmbeddingBackend.VERTEX
    if shared == "anthropic":
        # Anthropic doesn't have embeddings — use OpenAI if key exists
        if os.environ.get("OPENAI_API_KEY"):
            return EmbeddingBackend.OPENAI
        return EmbeddingBackend.NONE

    # Auto-detect
    has_vertex = bool(
        os.environ.get("CLOUD_ML_REGION")
        or os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
    )
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))

    if has_vertex and not has_openai:
        return EmbeddingBackend.VERTEX
    if has_openai:
        return EmbeddingBackend.OPENAI
    return EmbeddingBackend.NONE


def _get_backend_config() -> tuple[EmbeddingBackend, dict[str, Any]]:
    """Return (backend, config) for the detected embedding backend."""
    backend = detect_embedding_backend()
    config = _BACKEND_CONFIG.get(backend, {"model": "", "dim": 0})
    return backend, config


def _embed_openai(texts: list[str], model: str, batch_size: int) -> list[list[float]]:
    """Embed via OpenAI API."""
    from openai import OpenAI
    client = OpenAI()
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch = [t if t.strip() else " " for t in batch]
        response = client.embeddings.create(model=model, input=batch)
        for item in response.data:
            all_embeddings.append(item.embedding)
    return all_embeddings


def _embed_vertex(texts: list[str], model: str, batch_size: int) -> list[list[float]]:
    """Embed via Vertex AI (Google ADC auth)."""
    from google.auth import default as google_auth_default
    from google.auth.transport.requests import Request as AuthRequest
    import json as _json
    import urllib.request

    credentials, project = google_auth_default()
    region = os.environ.get("CLOUD_ML_REGION", "us-central1")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID") or project

    credentials.refresh(AuthRequest())
    endpoint = (
        f"https://{region}-aiplatform.googleapis.com/v1/"
        f"projects/{project}/locations/{region}/publishers/google/models/{model}:predict"
    )

    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch = [t if t.strip() else " " for t in batch]
        body = _json.dumps({
            "instances": [{"content": t} for t in batch],
        }).encode()
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req) as resp:
            data = _json.loads(resp.read())
        for prediction in data.get("predictions", []):
            embedding = prediction.get("embeddings", {}).get("values", [])
            all_embeddings.append(embedding)

    return all_embeddings


def embed_texts(texts: list[str], batch_size: int = 100) -> Any:
    """Embed texts using the auto-detected backend.

    Returns numpy array of shape (len(texts), embedding_dim).
    Raises if no embedding backend is available.
    """
    import numpy as np

    backend, config = _get_backend_config()
    model = config["model"]
    dim = config["dim"]

    if not texts:
        return np.zeros((0, dim), dtype=np.float32)

    if backend == EmbeddingBackend.NONE:
        raise RuntimeError("No embedding backend available. Set OPENAI_API_KEY or configure Vertex AI.")

    logger.info(f"Embedding {len(texts)} items via {backend.value} ({model})")

    if backend == EmbeddingBackend.OPENAI:
        raw = _embed_openai(texts, model, batch_size)
    elif backend == EmbeddingBackend.VERTEX:
        raw = _embed_vertex(texts, model, batch_size)
    else:
        raise RuntimeError(f"Unknown embedding backend: {backend}")

    return np.array(raw, dtype=np.float32)


def cosine_similarity(query_vec: Any, matrix: Any) -> Any:
    """Compute cosine similarity between a query vector and a matrix of vectors."""
    import numpy as np

    # Normalize
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    matrix_norm = matrix / norms
    return matrix_norm @ query_norm


class EmbeddingStore:
    """Manages embeddings for a repo's v2 schema."""

    def __init__(self, v2_dir: Path):
        self.v2_dir = v2_dir
        self.file_path = v2_dir / EMBEDDINGS_FILE
        self._texts: list[str] | None = None
        self._metadata: list[dict] | None = None
        self._embeddings: Any = None  # numpy array

    @property
    def available(self) -> bool:
        """True if embeddings exist on disk."""
        return self.file_path.exists()

    @staticmethod
    def can_generate() -> bool:
        """True if any embedding backend is available."""
        return detect_embedding_backend() != EmbeddingBackend.NONE

    def load(self) -> bool:
        """Load embeddings from disk. Returns True if successful."""
        if not self.file_path.exists():
            return False

        try:
            import numpy as np
            data = np.load(self.file_path, allow_pickle=True)
            self._embeddings = data["embeddings"]
            self._texts = list(data["texts"])
            self._metadata = [json.loads(m) for m in data["metadata"]]
            return True
        except Exception as e:
            logger.warning(f"Failed to load embeddings: {e}")
            return False

    def save(self) -> None:
        """Save current embeddings to disk."""
        import numpy as np

        if self._embeddings is None or self._texts is None or self._metadata is None:
            return

        self.v2_dir.mkdir(parents=True, exist_ok=True)
        np.savez(
            self.file_path,
            embeddings=self._embeddings,
            texts=np.array(self._texts, dtype=object),
            metadata=np.array([json.dumps(m) for m in self._metadata], dtype=object),
        )
        logger.info(f"Saved {len(self._texts)} embeddings to {self.file_path}")

    def build_from_index(self, search_index: list[dict]) -> int:
        """Build embeddings from a schema reader's search index.

        Each index item gets embedded with a composite text of its
        name, description, tags, and type for rich semantic matching.

        Returns number of items embedded.
        """
        backend = detect_embedding_backend()
        if backend == EmbeddingBackend.NONE:
            logger.info("No embedding backend available — skipping generation")
            return 0

        texts = []
        metadata = []

        for item in search_index:
            # Build rich text for embedding
            parts = [
                item.get("_type", ""),
                item.get("name", ""),
                item.get("description", ""),
                item.get("role", ""),
                " ".join(item.get("tags", [])),
            ]
            text = " | ".join(p for p in parts if p)
            if not text.strip():
                continue

            texts.append(text)
            # Store minimal metadata for result reconstruction
            metadata.append({
                "type": item.get("_type", ""),
                "name": item.get("name", ""),
                "path": item.get("path", ""),
                "module": item.get("module", ""),
                "description": item.get("description", ""),
                "tags": item.get("tags", []),
            })

        if not texts:
            return 0

        self._embeddings = embed_texts(texts)
        self._texts = texts
        self._metadata = metadata
        self.save()
        return len(texts)

    def search(self, query: str, top_k: int = 10) -> list[tuple[dict, float]]:
        """Semantic search over embeddings.

        Returns list of (metadata_dict, similarity_score) tuples, sorted by relevance.
        """
        if self._embeddings is None:
            if not self.load():
                return []

        if self._embeddings is None or len(self._embeddings) == 0:
            return []

        # Embed the query
        query_embedding = embed_texts([query])[0]
        scores = cosine_similarity(query_embedding, self._embeddings)

        # Top-k indices
        import numpy as np
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < 0.1:  # Relevance threshold
                break
            results.append((self._metadata[idx], score))

        return results

    def incremental_update(
        self,
        added_items: list[dict],
        removed_names: set[str],
    ) -> int:
        """Incrementally update embeddings — add new, remove deleted.

        More efficient than full rebuild for small changes.
        Returns number of new items embedded.
        """
        backend = detect_embedding_backend()
        if backend == EmbeddingBackend.NONE:
            return 0

        import numpy as np

        if self._embeddings is None:
            self.load()

        if self._metadata is None:
            self._texts = []
            self._metadata = []
            _, config = _get_backend_config()
            self._embeddings = np.zeros((0, config["dim"]), dtype=np.float32)

        # Remove deleted items
        if removed_names:
            keep_mask = [
                m.get("name", "") not in removed_names
                for m in self._metadata
            ]
            self._texts = [t for t, k in zip(self._texts, keep_mask) if k]
            self._metadata = [m for m, k in zip(self._metadata, keep_mask) if k]
            self._embeddings = self._embeddings[keep_mask]

        # Add new items
        if not added_items:
            self.save()
            return 0

        new_texts = []
        new_metadata = []
        for item in added_items:
            parts = [
                item.get("_type", ""),
                item.get("name", ""),
                item.get("description", ""),
                " ".join(item.get("tags", [])),
            ]
            text = " | ".join(p for p in parts if p)
            if text.strip():
                new_texts.append(text)
                new_metadata.append({
                    "type": item.get("_type", ""),
                    "name": item.get("name", ""),
                    "path": item.get("path", ""),
                    "module": item.get("module", ""),
                    "description": item.get("description", ""),
                    "tags": item.get("tags", []),
                })

        if new_texts:
            new_embeddings = embed_texts(new_texts)
            self._texts.extend(new_texts)
            self._metadata.extend(new_metadata)
            self._embeddings = np.vstack([self._embeddings, new_embeddings])

        self.save()
        return len(new_texts)
