"""Incremental update logic — git-diff-driven layer refresh."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .config import (
    DEEPROUTE_DIR,
    get_effective_model,
    load_history,
    save_history,
)
from .deepagent import update_layer
from .git_utils import get_diff_since, get_head_sha, get_recent_log
from .models import (
    ChangeImpact,
    ChangeImpactLevel,
    FileChange,
    FileChangeStatus,
    HistoryEntry,
)

# Patterns for structural vs content vs minor classification
STRUCTURAL_PATTERNS = [
    "Dockerfile", "docker-compose.*",
    "*.toml", "*.json", "*.yaml", "*.yml",
    "Makefile", "*.tf",
    ".github/**",
]

MINOR_PATTERNS = [
    "*.md", "*.txt", "*.rst",
    "LICENSE*", "CHANGELOG*",
]


def _matches_any(path: str, patterns: list[str]) -> bool:
    name = Path(path).name
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(path, p) for p in patterns)


def classify_changes(changes: list[FileChange]) -> ChangeImpact:
    """Classify file changes by impact level."""
    structural: list[FileChange] = []
    content: list[FileChange] = []
    minor: list[FileChange] = []

    for c in changes:
        # New/deleted top-level directories are always structural
        if c.status in (FileChangeStatus.ADDED, FileChangeStatus.DELETED):
            parts = Path(c.path).parts
            if len(parts) <= 2:  # top-level or one level deep
                structural.append(c)
                continue
        if c.status == FileChangeStatus.RENAMED:
            structural.append(c)
            continue
        if _matches_any(c.path, STRUCTURAL_PATTERNS):
            structural.append(c)
        elif _matches_any(c.path, MINOR_PATTERNS):
            minor.append(c)
        else:
            content.append(c)

    # Determine overall level
    if structural:
        level = ChangeImpactLevel.STRUCTURAL
    elif content:
        level = ChangeImpactLevel.CONTENT
    else:
        level = ChangeImpactLevel.MINOR

    return ChangeImpact(
        level=level,
        structural_changes=structural,
        content_changes=content,
        minor_changes=minor,
    )


def _find_affected_layers(
    changes: list[FileChange],
    layers_dir: Path,
) -> list[str]:
    """Determine which layer files need updating based on changed paths."""
    if not layers_dir.exists():
        return []
    layer_files = [f.name for f in layers_dir.iterdir() if f.suffix == ".md"]
    # For now, return all layers if there are structural changes,
    # otherwise return layers that likely match changed paths
    return layer_files


async def incremental_update(
    repo_path: str | Path,
    force: bool = False,
) -> dict:
    """Run incremental update on a repo. Returns changelog."""
    repo = Path(repo_path).resolve()
    dr_dir = repo / DEEPROUTE_DIR

    if not dr_dir.exists():
        return {"error": f"No .deeproute/ found at {repo}. Run dr_init first."}

    history = load_history(repo)
    current_head = get_head_sha(repo)

    if not force and history and history.last_sha == current_head:
        return {"message": "Already up to date.", "updated_layers": []}

    model = get_effective_model(str(repo))
    changelog: list[str] = []

    if force or not history:
        # Full regeneration needed — caller should use dr_init instead
        return {"message": "No history found or force=True. Use dr_init for full scan.", "updated_layers": []}

    # Get changes since last scan
    changes = get_diff_since(str(repo), history.last_sha)
    if not changes:
        save_history(str(repo), HistoryEntry(
            last_sha=current_head,
            last_update=_now_iso(),
            init_sha=history.init_sha,
            init_time=history.init_time,
        ))
        return {"message": "No file changes detected.", "updated_layers": []}

    impact = classify_changes(changes)
    commits = get_recent_log(str(repo), history.last_sha)
    commit_dicts = [{"sha": c.sha, "message": c.message} for c in commits]

    layers_dir = dr_dir / "layers"
    affected = _find_affected_layers(
        impact.structural_changes + impact.content_changes,
        layers_dir,
    )

    updated_layers: list[str] = []
    all_changes = impact.structural_changes + impact.content_changes

    for layer_file in affected:
        layer_path = layers_dir / layer_file
        if not layer_path.exists():
            continue
        current_md = layer_path.read_text()
        updated_md = await update_layer(current_md, all_changes, commit_dicts, model)
        if updated_md.strip() != current_md.strip():
            layer_path.write_text(updated_md)
            updated_layers.append(layer_file)
            changelog.append(f"Updated {layer_file}")

    # Update ROUTER.md if structural changes
    if impact.level == ChangeImpactLevel.STRUCTURAL:
        router_path = dr_dir / "ROUTER.md"
        if router_path.exists():
            current_router = router_path.read_text()
            updated_router = await update_layer(
                current_router, impact.structural_changes, commit_dicts, model
            )
            if updated_router.strip() != current_router.strip():
                router_path.write_text(updated_router)
                changelog.append("Updated ROUTER.md")

    # Save new history
    save_history(str(repo), HistoryEntry(
        last_sha=current_head,
        last_update=_now_iso(),
        init_sha=history.init_sha,
        init_time=history.init_time,
    ))

    return {
        "message": f"Updated {len(updated_layers)} layers.",
        "impact": impact.level.value,
        "changes_detected": len(changes),
        "updated_layers": updated_layers,
        "changelog": changelog,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
