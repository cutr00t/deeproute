"""Pydantic models for DeepRoute config, state, and data structures."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---

class InitMode(str, Enum):
    REPO = "repo"
    WORKSPACE = "workspace"


class QueryDepth(str, Enum):
    SHALLOW = "shallow"
    NORMAL = "normal"
    DEEP = "deep"


class RegisterAction(str, Enum):
    ADD = "add"
    REMOVE = "remove"


class ConfigScope(str, Enum):
    GLOBAL = "global"
    REPO = "repo"
    WORKSPACE = "workspace"


class ChangeImpactLevel(str, Enum):
    STRUCTURAL = "structural"
    CONTENT = "content"
    MINOR = "minor"


class ForceMode(str, Enum):
    AGENT = "agent"
    SCHEMA = "schema"


# --- Scanner models ---

class FileInfo(BaseModel):
    path: str
    size: int
    extension: str
    language: str = ""


class RepoInventory(BaseModel):
    root: str
    name: str
    files: list[FileInfo] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)  # lang -> file count
    key_files: dict[str, str] = Field(default_factory=dict)   # filename -> content
    total_files: int = 0
    tree_summary: str = ""


# --- Git models ---

class FileChangeStatus(str, Enum):
    ADDED = "A"
    MODIFIED = "M"
    DELETED = "D"
    RENAMED = "R"


class FileChange(BaseModel):
    path: str
    status: FileChangeStatus
    old_path: str | None = None  # for renames


class CommitInfo(BaseModel):
    sha: str
    message: str
    timestamp: str = ""


# --- Change classification ---

class ChangeImpact(BaseModel):
    level: ChangeImpactLevel
    affected_layers: list[str] = Field(default_factory=list)
    structural_changes: list[FileChange] = Field(default_factory=list)
    content_changes: list[FileChange] = Field(default_factory=list)
    minor_changes: list[FileChange] = Field(default_factory=list)


# --- Generated routing system ---

class LayerDoc(BaseModel):
    name: str
    filename: str
    content: str


class SkillDoc(BaseModel):
    name: str
    directory: str
    content: str


class RoutingSystem(BaseModel):
    router_md: str
    layers: list[LayerDoc] = Field(default_factory=list)
    skills: list[SkillDoc] = Field(default_factory=list)


# --- History ---

class HistoryEntry(BaseModel):
    last_sha: str
    last_update: str  # ISO timestamp
    init_sha: str = ""
    init_time: str = ""


# --- Config models ---

class GlobalDefaults(BaseModel):
    model: str = "sonnet"
    init_model: str = "sonnet"
    local_only: bool = True
    auto_update_on_query: bool = True
    max_files_full_scan: int = 5000
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "node_modules", ".git", "__pycache__", "*.pyc",
            "dist", "build", ".venv", "venv", ".tox",
        ]
    )
    force_mode: ForceMode | None = None


class RepoEntry(BaseModel):
    mode: InitMode = InitMode.REPO
    last_init: str = ""
    last_update: str = ""


class WorkspaceEntry(BaseModel):
    repos: list[str] = Field(default_factory=list)
    last_init: str = ""


class GlobalConfig(BaseModel):
    version: str = "1.0.0"
    defaults: GlobalDefaults = Field(default_factory=GlobalDefaults)
    repos: dict[str, RepoEntry] = Field(default_factory=dict)
    workspaces: dict[str, WorkspaceEntry] = Field(default_factory=dict)


class RepoConfig(BaseModel):
    model_override: str | None = None
    custom_layers: list[str] = Field(default_factory=list)
    custom_skills: list[str] = Field(default_factory=list)
    exclude_patterns_extra: list[str] = Field(default_factory=list)
    update_strategy: str = "incremental"
    router_hints: dict[str, str] = Field(default_factory=dict)


# --- Tool result models ---

class ToolResult(BaseModel):
    success: bool
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
