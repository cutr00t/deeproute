"""LLM client factory — supports Anthropic API, Vertex AI, and schema-only mode."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any


class LLMBackend(str, Enum):
    ANTHROPIC = "anthropic"
    VERTEX = "vertex"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


class LLMClientError(Exception):
    """Raised when LLM client cannot be constructed or backend is ambiguous."""


_client: Any = None
_backend: LLMBackend | None = None


def detect_backend() -> LLMBackend:
    """Auto-detect which LLM backend to use based on environment.

    Rules:
    - DEEPROUTE_BACKEND env var is an explicit override (anthropic|vertex)
    - If both API key and Vertex credentials are set → AMBIGUOUS (error on use)
    - If only Vertex → VERTEX
    - If only API key → ANTHROPIC
    - If neither → NONE (schema mode, no LLM calls)
    """
    # Explicit override takes precedence
    explicit = os.environ.get("DEEPROUTE_BACKEND", "").strip().lower()
    if explicit in ("anthropic", "vertex"):
        return LLMBackend(explicit)

    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_vertex = bool(
        os.environ.get("CLOUD_ML_REGION")
        or os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
    )

    if has_api_key and has_vertex:
        return LLMBackend.AMBIGUOUS
    if has_vertex:
        return LLMBackend.VERTEX
    if has_api_key:
        return LLMBackend.ANTHROPIC
    return LLMBackend.NONE


def get_backend() -> LLMBackend:
    """Return the current detected backend (cached after first call)."""
    global _backend
    if _backend is None:
        _backend = detect_backend()
    return _backend


def reset_client() -> None:
    """Reset cached client and backend detection. Used when env changes."""
    global _client, _backend
    _client = None
    _backend = None


def create_client() -> Any:
    """Create the appropriate async Anthropic client.

    Returns None for NONE backend.
    Raises LLMClientError for AMBIGUOUS backend.
    """
    backend = get_backend()

    if backend == LLMBackend.AMBIGUOUS:
        raise LLMClientError(
            "Both ANTHROPIC_API_KEY and Vertex AI credentials "
            "(CLOUD_ML_REGION / ANTHROPIC_VERTEX_PROJECT_ID) are set. "
            "DeepRoute won't guess which to use — set DEEPROUTE_BACKEND=anthropic "
            "or DEEPROUTE_BACKEND=vertex to choose, or unset one."
        )

    if backend == LLMBackend.NONE:
        return None

    if backend == LLMBackend.VERTEX:
        from anthropic import AsyncAnthropicVertex
        return AsyncAnthropicVertex(
            region=os.environ.get("CLOUD_ML_REGION", "us-east5"),
            project_id=os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID"),
        )

    # ANTHROPIC (default)
    from anthropic import AsyncAnthropic
    return AsyncAnthropic()


def get_client() -> Any:
    """Get or create the singleton async client.

    Raises LLMClientError if no credentials are available or if ambiguous.
    """
    global _client
    if _client is None:
        _client = create_client()
    if _client is None:
        raise LLMClientError(
            "No LLM credentials available. DeepRoute is running in schema mode. "
            "Agent operations (dr_init, dr_update, dr_query) require either "
            "ANTHROPIC_API_KEY or Vertex AI credentials "
            "(CLOUD_ML_REGION + ANTHROPIC_VERTEX_PROJECT_ID). "
            "Use dr_lookup / dr_search for zero-cost schema queries."
        )
    return _client
