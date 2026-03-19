"""Configuration loading, saving, and merging for DeepRoute."""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    GlobalConfig,
    GlobalDefaults,
    HistoryEntry,
    RepoConfig,
    RepoEntry,
    WorkspaceEntry,
)

GLOBAL_CONFIG_DIR = Path.home() / ".deeproute"
GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_DIR / "config.json"
DEEPROUTE_DIR = ".deeproute"
REPO_CONFIG_FILENAME = "config.json"
HISTORY_FILENAME = "history.json"


def ensure_global_config_dir() -> Path:
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return GLOBAL_CONFIG_DIR


def load_global_config() -> GlobalConfig:
    if GLOBAL_CONFIG_PATH.exists():
        data = json.loads(GLOBAL_CONFIG_PATH.read_text())
        return GlobalConfig.model_validate(data)
    return GlobalConfig()


def save_global_config(config: GlobalConfig) -> None:
    ensure_global_config_dir()
    GLOBAL_CONFIG_PATH.write_text(
        config.model_dump_json(indent=2) + "\n"
    )


def load_repo_config(repo_path: str | Path) -> RepoConfig:
    p = Path(repo_path) / DEEPROUTE_DIR / REPO_CONFIG_FILENAME
    if p.exists():
        data = json.loads(p.read_text())
        return RepoConfig.model_validate(data)
    return RepoConfig()


def save_repo_config(repo_path: str | Path, config: RepoConfig) -> None:
    d = Path(repo_path) / DEEPROUTE_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / REPO_CONFIG_FILENAME).write_text(
        config.model_dump_json(indent=2) + "\n"
    )


def load_history(repo_path: str | Path) -> HistoryEntry | None:
    p = Path(repo_path) / DEEPROUTE_DIR / HISTORY_FILENAME
    if p.exists():
        data = json.loads(p.read_text())
        return HistoryEntry.model_validate(data)
    return None


def save_history(repo_path: str | Path, entry: HistoryEntry) -> None:
    d = Path(repo_path) / DEEPROUTE_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / HISTORY_FILENAME).write_text(
        entry.model_dump_json(indent=2) + "\n"
    )


def get_effective_model(repo_path: str | Path | None = None) -> str:
    """Resolve model: repo override > global default."""
    gc = load_global_config()
    if repo_path:
        rc = load_repo_config(repo_path)
        if rc.model_override:
            return rc.model_override
    return gc.defaults.model


def get_effective_excludes(repo_path: str | Path | None = None) -> list[str]:
    """Merge global + repo exclude patterns."""
    gc = load_global_config()
    excludes = list(gc.defaults.exclude_patterns)
    if repo_path:
        rc = load_repo_config(repo_path)
        excludes.extend(rc.exclude_patterns_extra)
    return excludes


def register_repo(path: str, mode: str = "repo") -> None:
    """Add a repo to the global registry."""
    from datetime import datetime, timezone
    gc = load_global_config()
    gc.repos[path] = RepoEntry(
        mode=mode,
        last_init=datetime.now(timezone.utc).isoformat(),
        last_update=datetime.now(timezone.utc).isoformat(),
    )
    save_global_config(gc)


def unregister_repo(path: str) -> None:
    """Remove a repo from the global registry."""
    gc = load_global_config()
    gc.repos.pop(path, None)
    save_global_config(gc)


def register_workspace(path: str, repo_paths: list[str]) -> None:
    """Add a workspace to the global registry."""
    from datetime import datetime, timezone
    gc = load_global_config()
    gc.workspaces[path] = WorkspaceEntry(
        repos=repo_paths,
        last_init=datetime.now(timezone.utc).isoformat(),
    )
    save_global_config(gc)


def get_config_value(key: str, scope: str = "global", path: str | None = None) -> str | None:
    """Get a config value by dot-notation key."""
    if scope == "global":
        gc = load_global_config()
        obj = gc.defaults.model_dump()
    elif scope == "repo" and path:
        rc = load_repo_config(path)
        obj = rc.model_dump()
    else:
        return None
    parts = key.split(".")
    for part in parts:
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return str(obj)


def set_config_value(key: str, value: str, scope: str = "global", path: str | None = None) -> None:
    """Set a config value by dot-notation key."""
    if scope == "global":
        gc = load_global_config()
        obj = gc.defaults.model_dump()
        _set_nested(obj, key.split("."), value)
        gc.defaults = GlobalDefaults.model_validate(obj)
        save_global_config(gc)
    elif scope == "repo" and path:
        rc = load_repo_config(path)
        obj = rc.model_dump()
        _set_nested(obj, key.split("."), value)
        rc = RepoConfig.model_validate(obj)
        save_repo_config(path, rc)


def _set_nested(obj: dict, keys: list[str], value: str) -> None:
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    # Try to preserve type
    existing = obj.get(keys[-1])
    if isinstance(existing, bool):
        obj[keys[-1]] = value.lower() in ("true", "1", "yes")
    elif isinstance(existing, int):
        obj[keys[-1]] = int(value)
    else:
        obj[keys[-1]] = value
