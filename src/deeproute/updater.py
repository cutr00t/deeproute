"""Hybrid incremental update — AST-based factual refresh + threshold-triggered LLM analysis.

Two update modes:
1. Factual update (always, no LLM): Re-index changed files via AST, update function/class
   specs, compute drift scores. Fast and free.
2. Interpretive update (threshold-triggered, LLM): When cumulative drift crosses a threshold,
   re-analyze affected modules for tags, descriptions, patterns. Targeted and cost-controlled.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .ast_indexer import (
    FileIndex,
    compute_drift_score,
    index_file,
)
from .config import (
    DEEPROUTE_DIR,
    get_effective_model,
    load_history,
    save_history,
)
from .deepagent import update_layer, update_module_v2
from .git_utils import (
    get_changed_file_paths,
    get_diff_since,
    get_head_sha,
    get_recent_log,
    get_uncommitted_changes,
)
from .models import (
    ChangeImpact,
    ChangeImpactLevel,
    FileChange,
    FileChangeStatus,
    HistoryEntry,
)
from .schema import FunctionSpec, ClassSpec, ModuleSchema

logger = logging.getLogger(__name__)

# Drift threshold: above this, trigger LLM re-analysis for the module
LLM_DRIFT_THRESHOLD = 0.3

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

# Language detection for AST indexing
EXT_LANG: dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript",
    ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".swift": "Swift",
    ".cs": "C#", ".sh": "Shell",
}


def _matches_any(path: str, patterns: list[str]) -> bool:
    name = Path(path).name
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(path, p) for p in patterns)


def classify_changes(changes: list[FileChange]) -> ChangeImpact:
    """Classify file changes by impact level."""
    structural: list[FileChange] = []
    content: list[FileChange] = []
    minor: list[FileChange] = []

    for c in changes:
        if c.status in (FileChangeStatus.ADDED, FileChangeStatus.DELETED):
            parts = Path(c.path).parts
            if len(parts) <= 2:
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


def _detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    name = Path(file_path).name.lower()
    if name == "dockerfile" or name.startswith("dockerfile."):
        return "Docker"
    return EXT_LANG.get(ext, "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_file_safe(path: Path, max_size: int = 500_000) -> str | None:
    """Read file content, returning None if too large or unreadable."""
    try:
        if path.stat().st_size > max_size:
            return None
        return path.read_text(errors="replace")
    except OSError:
        return None


# --- Factual update (AST-based, no LLM) ---

def factual_update_module(
    repo_path: Path,
    module_json_path: Path,
    changed_files: set[str],
) -> tuple[dict, float]:
    """Update a module's factual data (functions, classes, file roles) via AST.

    Returns (updated_module_dict, drift_score).
    """
    module_data = json.loads(module_json_path.read_text())
    module_path = module_data.get("path", module_data.get("name", ""))

    # Find which changed files belong to this module
    module_files = {f["path"] for f in module_data.get("files", [])}
    affected_files = changed_files & module_files

    # Also check for new files in the module directory
    if module_path:
        module_dir = repo_path / module_path
        if module_dir.is_dir():
            for p in module_dir.rglob("*"):
                if p.is_file():
                    rel = str(p.relative_to(repo_path))
                    if rel in changed_files or rel not in module_files:
                        lang = _detect_language(rel)
                        if lang:
                            affected_files.add(rel)

    if not affected_files:
        return module_data, 0.0

    # Collect old AST-sourced specs for drift calculation
    old_functions = [
        FunctionSpec.model_validate(f)
        for f in module_data.get("functions", [])
    ]
    old_classes = [
        ClassSpec.model_validate(c)
        for c in module_data.get("classes", [])
    ]

    # Re-index affected files
    new_file_indexes: dict[str, FileIndex] = {}
    for rel_path in affected_files:
        full_path = repo_path / rel_path
        content = _read_file_safe(full_path)
        if content is None:
            continue
        lang = _detect_language(rel_path)
        if lang:
            new_file_indexes[rel_path] = index_file(rel_path, content, lang)

    # Merge: replace AST-sourced entries for affected files, keep LLM entries for unaffected
    # Functions
    new_functions: list[dict] = []
    affected_fn_names: set[str] = set()
    for rel_path, idx in new_file_indexes.items():
        for fn in idx.functions:
            affected_fn_names.add(fn.name)
            fn_dict = fn.model_dump()
            # Preserve LLM-derived fields if they existed before
            for old_fn in module_data.get("functions", []):
                if old_fn.get("name") == fn.name and old_fn.get("file") == fn.file:
                    # Keep description and tags from LLM
                    if old_fn.get("description") and old_fn.get("source") != "ast":
                        fn_dict["description"] = old_fn["description"]
                    if old_fn.get("tags") and old_fn.get("source") != "ast":
                        fn_dict["tags"] = old_fn["tags"]
                    fn_dict["source"] = "merged"
                    break
            new_functions.append(fn_dict)

    # Keep functions from unaffected files
    for fn in module_data.get("functions", []):
        if fn.get("name") not in affected_fn_names:
            file_path = fn.get("file", "")
            if file_path not in affected_files:
                new_functions.append(fn)

    # Classes (same merge logic)
    new_classes: list[dict] = []
    affected_cls_names: set[str] = set()
    for rel_path, idx in new_file_indexes.items():
        for cls in idx.classes:
            affected_cls_names.add(cls.name)
            cls_dict = cls.model_dump()
            for old_cls in module_data.get("classes", []):
                if old_cls.get("name") == cls.name and old_cls.get("file") == cls.file:
                    if old_cls.get("description") and old_cls.get("source") != "ast":
                        cls_dict["description"] = old_cls["description"]
                    if old_cls.get("tags") and old_cls.get("source") != "ast":
                        cls_dict["tags"] = old_cls["tags"]
                    cls_dict["source"] = "merged"
                    break
            new_classes.append(cls_dict)

    for cls in module_data.get("classes", []):
        if cls.get("name") not in affected_cls_names:
            file_path = cls.get("file", "")
            if file_path not in affected_files:
                new_classes.append(cls)

    # Update file roles
    files_list = list(module_data.get("files", []))
    for rel_path, idx in new_file_indexes.items():
        # Find or create file entry
        found = False
        for f in files_list:
            if f["path"] == rel_path:
                f["functions"] = [fn.name for fn in idx.functions]
                f["classes"] = [cls.name for cls in idx.classes]
                found = True
                break
        if not found:
            files_list.append({
                "path": rel_path,
                "role": "",
                "tags": [],
                "functions": [fn.name for fn in idx.functions],
                "classes": [cls.name for cls in idx.classes],
            })

    # Remove file entries for deleted files
    files_list = [
        f for f in files_list
        if (repo_path / f["path"]).exists()
    ]

    module_data["functions"] = new_functions
    module_data["classes"] = new_classes
    module_data["files"] = files_list
    module_data["last_factual_update"] = _now_iso()

    # Compute drift
    new_fn_specs = [FunctionSpec.model_validate(f) for f in new_functions]
    new_cls_specs = [ClassSpec.model_validate(c) for c in new_classes]
    drift = compute_drift_score(old_functions, new_fn_specs, old_classes, new_cls_specs)
    module_data["drift_score"] = drift

    return module_data, drift


def _find_affected_layers(
    changes: list[FileChange],
    layers_dir: Path,
) -> list[str]:
    """Determine which layer files need updating based on changed paths."""
    if not layers_dir.exists():
        return []
    layer_files = [f.name for f in layers_dir.iterdir() if f.suffix == ".md"]
    return layer_files


# --- Main update entry point ---

async def incremental_update(
    repo_path: str | Path,
    force: bool = False,
    include_uncommitted: bool = True,
) -> dict:
    """Hybrid incremental update: always refresh factual data, conditionally invoke LLM.

    Steps:
    1. Detect changed files (committed + uncommitted)
    2. AST-index changed files and update module schemas (always, free)
    3. Compute drift scores per module
    4. If drift > threshold, invoke LLM for interpretive refresh (descriptions, tags)
    5. Update v1 layers if structural changes detected
    6. Update embeddings incrementally if available
    """
    repo = Path(repo_path).resolve()
    dr_dir = repo / DEEPROUTE_DIR

    if not dr_dir.exists():
        return {"error": f"No .deeproute/ found at {repo}. Run dr_init first."}

    history = load_history(repo)
    current_head = get_head_sha(repo)

    if not force and history and history.last_sha == current_head and not include_uncommitted:
        return {"message": "Already up to date.", "updated_layers": [], "factual_updates": 0}

    if not history:
        return {"message": "No history found. Use dr_init for full scan.", "updated_layers": []}

    model = get_effective_model(str(repo))
    changelog: list[str] = []

    # Step 1: Get all changed files
    changed_paths = get_changed_file_paths(
        repo, history.last_sha, include_uncommitted=include_uncommitted,
    )

    if not changed_paths and not force:
        save_history(str(repo), HistoryEntry(
            last_sha=current_head,
            last_update=_now_iso(),
            init_sha=history.init_sha,
            init_time=history.init_time,
        ))
        return {"message": "No file changes detected.", "updated_layers": [], "factual_updates": 0}

    # Step 2: Factual update of v2 module schemas
    v2_dir = dr_dir / "v2"
    modules_dir = v2_dir / "modules"
    factual_updates = 0
    llm_refreshes = 0
    drift_report: dict[str, float] = {}

    if modules_dir.is_dir():
        for module_file in sorted(modules_dir.iterdir()):
            if module_file.suffix != ".json":
                continue

            updated_data, drift = factual_update_module(
                repo, module_file, changed_paths,
            )
            drift_report[module_file.stem] = drift

            if drift > 0:
                # Write updated factual data
                module_file.write_text(json.dumps(updated_data, indent=2) + "\n")
                factual_updates += 1
                changelog.append(f"Factual update: {module_file.stem} (drift={drift:.2f})")

                # Step 3: Threshold check for LLM refresh
                if drift >= LLM_DRIFT_THRESHOLD:
                    try:
                        commits = get_recent_log(str(repo), history.last_sha)
                        commit_dicts = [{"sha": c.sha, "message": c.message} for c in commits]
                        changes = get_diff_since(str(repo), history.last_sha)
                        module_changes = [
                            c for c in changes
                            if c.path in changed_paths
                        ]
                        refreshed = await update_module_v2(
                            updated_data, module_changes, commit_dicts, model,
                        )
                        # Preserve factual fields from AST, take interpretive from LLM
                        for fn in refreshed.get("functions", []):
                            if fn.get("source") != "ast":
                                fn["source"] = "llm"
                        refreshed["last_factual_update"] = updated_data.get("last_factual_update", "")
                        refreshed["drift_score"] = 0.0  # Reset after LLM refresh
                        module_file.write_text(json.dumps(refreshed, indent=2) + "\n")
                        llm_refreshes += 1
                        changelog.append(f"LLM refresh: {module_file.stem}")
                    except Exception as e:
                        logger.warning(f"LLM refresh failed for {module_file.stem}: {e}")
                        changelog.append(f"LLM refresh failed: {module_file.stem} ({e})")

    # Step 4: Update v1 layers (same as before, LLM-based)
    changes = get_diff_since(str(repo), history.last_sha)
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

    # Only update v1 layers if there are committed changes and drift is significant
    if all_changes and any(d >= LLM_DRIFT_THRESHOLD for d in drift_report.values()):
        for layer_file in affected:
            layer_path = layers_dir / layer_file
            if not layer_path.exists():
                continue
            current_md = layer_path.read_text()
            try:
                updated_md = await update_layer(current_md, all_changes, commit_dicts, model)
                if updated_md.strip() != current_md.strip():
                    layer_path.write_text(updated_md)
                    updated_layers.append(layer_file)
                    changelog.append(f"Updated {layer_file}")
            except Exception as e:
                logger.warning(f"Layer update failed for {layer_file}: {e}")

        # Update ROUTER.md if structural changes
        if impact.level == ChangeImpactLevel.STRUCTURAL:
            router_path = dr_dir / "ROUTER.md"
            if router_path.exists():
                current_router = router_path.read_text()
                try:
                    updated_router = await update_layer(
                        current_router, impact.structural_changes, commit_dicts, model
                    )
                    if updated_router.strip() != current_router.strip():
                        router_path.write_text(updated_router)
                        changelog.append("Updated ROUTER.md")
                except Exception as e:
                    logger.warning(f"ROUTER.md update failed: {e}")

    # Step 5: Incremental embedding update
    embedding_updates = 0
    try:
        from .embeddings import EmbeddingStore
        store = EmbeddingStore(v2_dir)
        if store.available and store.can_generate():
            # Build items for changed modules
            from .schema_reader import SchemaReader
            reader = SchemaReader(repo)
            reader._search_index = None  # Force rebuild
            reader._build_search_index()
            if reader._search_index:
                # Simple approach: rebuild all embeddings
                # (incremental merge is complex for tag/description changes)
                embedding_updates = store.build_from_index(reader._search_index)
                if embedding_updates:
                    changelog.append(f"Updated {embedding_updates} embeddings")
    except Exception as e:
        logger.debug(f"Embedding update skipped: {e}")

    # Save history
    save_history(str(repo), HistoryEntry(
        last_sha=current_head,
        last_update=_now_iso(),
        init_sha=history.init_sha,
        init_time=history.init_time,
    ))

    # Update manifest drift score (max across modules)
    manifest_path = v2_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            manifest["drift_score"] = max(drift_report.values()) if drift_report else 0.0
            manifest["last_factual_update"] = _now_iso()
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        except Exception:
            pass

    return {
        "message": f"Updated {factual_updates} modules factually, {llm_refreshes} via LLM.",
        "impact": impact.level.value if changes else "none",
        "changes_detected": len(changed_paths),
        "factual_updates": factual_updates,
        "llm_refreshes": llm_refreshes,
        "drift_report": drift_report,
        "llm_threshold": LLM_DRIFT_THRESHOLD,
        "updated_layers": updated_layers,
        "embedding_updates": embedding_updates,
        "changelog": changelog,
    }
