"""Markdown generation — write .deeproute/ directory structure from routing system.

For v2 schemas, merges AST-derived factual data with LLM-derived interpretive data.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import DEEPROUTE_DIR
from .models import RoutingSystem

logger = logging.getLogger(__name__)


def write_routing_system(repo_path: str | Path, system: RoutingSystem) -> list[str]:
    """Write a RoutingSystem to disk. Returns list of files written."""
    root = Path(repo_path) / DEEPROUTE_DIR
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    # ROUTER.md
    router_path = root / "ROUTER.md"
    router_path.write_text(system.router_md)
    written.append(str(router_path))

    # layers/
    layers_dir = root / "layers"
    layers_dir.mkdir(exist_ok=True)
    for layer in system.layers:
        fn = layer.filename
        if not fn.endswith(".md"):
            fn += ".md"
        # Strip leading "layers/" if present in filename
        fn = fn.removeprefix("layers/")
        layer_path = layers_dir / fn
        layer_path.write_text(layer.content)
        written.append(str(layer_path))

    # skills/
    for skill in system.skills:
        skill_dir = root / "skills" / skill.directory
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(skill.content)
        written.append(str(skill_path))

    return written


def write_workspace_router(
    workspace_path: str | Path,
    workspace_name: str,
    components: list[dict[str, str]],
    cross_cutting: str = "",
    relationships: str = "",
) -> str:
    """Write workspace-level ROUTER.md."""
    root = Path(workspace_path) / DEEPROUTE_DIR
    root.mkdir(parents=True, exist_ok=True)

    # Build components table
    rows = []
    for comp in components:
        rows.append(
            f"| {comp['name']} | {comp['repo']}/ | "
            f"{comp['repo']}/.deeproute/ROUTER.md | {comp.get('description', '')} |"
        )
    table = "\n".join(rows)

    content = f"""# Workspace Router — {workspace_name}

## Components

| Component | Repo | Router | Description |
|-----------|------|--------|-------------|
{table}

## Inter-Component Relationships
{relationships or "See individual component routers for details."}

## Cross-Cutting Concerns
{cross_cutting or "See individual component routers for conventions."}
"""
    router_path = root / "ROUTER.md"
    router_path.write_text(content)

    # Also write component summaries
    comp_dir = root / "components"
    comp_dir.mkdir(exist_ok=True)
    for comp in components:
        summary = f"# {comp['name']}\n\n{comp.get('description', '')}\n\nRouter: `{comp['repo']}/.deeproute/ROUTER.md`\n"
        (comp_dir / f"{comp['repo']}.md").write_text(summary)

    return str(router_path)


def _merge_ast_into_module(
    mod_data: dict,
    ast_indexes: dict,
    module_path: str,
    repo_path: Path,
) -> dict:
    """Merge AST-derived factual data into LLM-derived module schema.

    AST provides: function names, params, return types, line numbers, classes, bases.
    LLM provides: descriptions, tags, purpose, summaries, common_tasks.
    Merged result has accurate factual data + rich interpretive metadata.
    """
    from .ast_indexer import FileIndex

    # Collect all AST functions and classes for files in this module
    ast_functions: dict[str, dict] = {}  # name -> spec dict
    ast_classes: dict[str, dict] = {}
    module_file_indexes: dict[str, FileIndex] = {}

    for rel_path, idx in ast_indexes.items():
        # Check if file belongs to this module
        if module_path and not rel_path.startswith(module_path):
            continue
        module_file_indexes[rel_path] = idx
        for fn in idx.functions:
            ast_functions[fn.name] = fn.model_dump()
        for cls in idx.classes:
            ast_classes[cls.name] = cls.model_dump()

    if not ast_functions and not ast_classes:
        return mod_data

    # Merge functions: AST factual + LLM interpretive
    llm_fn_map = {f.get("name", ""): f for f in mod_data.get("functions", [])}
    merged_functions = []
    for name, ast_fn in ast_functions.items():
        if name in llm_fn_map:
            llm_fn = llm_fn_map[name]
            # Take factual from AST, interpretive from LLM
            ast_fn["description"] = llm_fn.get("description", "")
            ast_fn["tags"] = llm_fn.get("tags", [])
            ast_fn["source"] = "merged"
        merged_functions.append(ast_fn)

    # Keep LLM-only functions that AST didn't find (might be in unsupported files)
    for name, llm_fn in llm_fn_map.items():
        if name not in ast_functions:
            llm_fn["source"] = "llm"
            merged_functions.append(llm_fn)

    # Same for classes
    llm_cls_map = {c.get("name", ""): c for c in mod_data.get("classes", [])}
    merged_classes = []
    for name, ast_cls in ast_classes.items():
        if name in llm_cls_map:
            llm_cls = llm_cls_map[name]
            ast_cls["description"] = llm_cls.get("description", "")
            ast_cls["tags"] = llm_cls.get("tags", [])
            ast_cls["source"] = "merged"
            # Merge method descriptions from LLM
            llm_methods = {m.get("name", ""): m for m in llm_cls.get("key_methods", [])}
            for method in ast_cls.get("key_methods", []):
                if method["name"] in llm_methods:
                    method["description"] = llm_methods[method["name"]].get("description", "")
                    method["tags"] = llm_methods[method["name"]].get("tags", [])
                    method["source"] = "merged"
        merged_classes.append(ast_cls)

    for name, llm_cls in llm_cls_map.items():
        if name not in ast_classes:
            llm_cls["source"] = "llm"
            merged_classes.append(llm_cls)

    # Update file roles with AST data
    file_roles = {f.get("path", ""): f for f in mod_data.get("files", [])}
    for rel_path, idx in module_file_indexes.items():
        if rel_path in file_roles:
            file_roles[rel_path]["functions"] = [fn.name for fn in idx.functions]
            file_roles[rel_path]["classes"] = [cls.name for cls in idx.classes]
        else:
            file_roles[rel_path] = {
                "path": rel_path,
                "role": "",
                "tags": [],
                "functions": [fn.name for fn in idx.functions],
                "classes": [cls.name for cls in idx.classes],
            }

    mod_data["functions"] = merged_functions
    mod_data["classes"] = merged_classes
    mod_data["files"] = list(file_roles.values())
    mod_data["drift_score"] = 0.0
    mod_data["last_factual_update"] = _now_iso()

    return mod_data


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def write_v2_schema(
    repo_path: str | Path,
    v2_data: dict,
    generated_by: str = "",
    ast_indexes: dict | None = None,
) -> list[str]:
    """Write v2 structured schema to .deeproute/v2/. Returns list of files written.

    If ast_indexes is provided, merges AST-derived factual data into each module.
    """
    import json
    from datetime import datetime, timezone

    root = Path(repo_path) / DEEPROUTE_DIR / "v2"
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    # Manifest
    manifest = v2_data.get("manifest", {})
    manifest["schema_version"] = "2.0.0"
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["generated_by"] = generated_by
    manifest["last_factual_update"] = datetime.now(timezone.utc).isoformat()
    manifest["drift_score"] = 0.0

    # Add module file references to manifest
    modules_data = v2_data.get("modules", {})
    if isinstance(modules_data, dict):
        for mod_name in modules_data:
            filename = mod_name.replace("/", "__") + ".json"
            if "modules" in manifest:
                for m in manifest["modules"]:
                    if m.get("name") == mod_name:
                        m["_file"] = f"modules/{filename}"
    elif isinstance(modules_data, list):
        modules_dict = {}
        for mod in modules_data:
            name = mod.get("name", mod.get("path", "unknown"))
            modules_dict[name] = mod
        modules_data = modules_dict

    # Check for notes
    notes = v2_data.get("notes", {})
    manifest["has_notes"] = bool(notes)

    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    written.append(str(manifest_path))

    # Modules (with optional AST merge)
    modules_dir = root / "modules"
    modules_dir.mkdir(exist_ok=True)
    for mod_name, mod_data in modules_data.items():
        if isinstance(mod_data, dict):
            mod_data["schema_version"] = "2.0.0"
            if "name" not in mod_data:
                mod_data["name"] = mod_name

            # Merge AST data if available
            if ast_indexes:
                mod_path = mod_data.get("path", mod_name)
                mod_data = _merge_ast_into_module(
                    mod_data, ast_indexes, mod_path, Path(repo_path),
                )

            if notes.get(mod_name):
                mod_data["notes_file"] = f"notes/{mod_name.replace('/', '__')}.md"
            filename = mod_name.replace("/", "__") + ".json"
            mod_path = modules_dir / filename
            mod_path.write_text(json.dumps(mod_data, indent=2) + "\n")
            written.append(str(mod_path))

    # Interfaces
    interfaces = v2_data.get("interfaces", {})
    if interfaces:
        interfaces["schema_version"] = "2.0.0"
        iface_path = root / "interfaces.json"
        iface_path.write_text(json.dumps(interfaces, indent=2) + "\n")
        written.append(str(iface_path))

    # Config files
    config_files = v2_data.get("config_files", {})
    if config_files:
        config_files["schema_version"] = "2.0.0"
        cf_path = root / "config_files.json"
        cf_path.write_text(json.dumps(config_files, indent=2) + "\n")
        written.append(str(cf_path))

    # Patterns
    patterns = v2_data.get("patterns", {})
    if patterns:
        patterns["schema_version"] = "2.0.0"
        pat_path = root / "patterns.json"
        pat_path.write_text(json.dumps(patterns, indent=2) + "\n")
        written.append(str(pat_path))

    # Notes (freeform markdown)
    if notes:
        notes_dir = root / "notes"
        notes_dir.mkdir(exist_ok=True)
        for mod_name, note_content in notes.items():
            if note_content:
                filename = mod_name.replace("/", "__") + ".md"
                note_path = notes_dir / filename
                note_path.write_text(note_content)
                written.append(str(note_path))

    return written


def update_gitignore(repo_path: str | Path) -> bool:
    """Append .deeproute/ to .gitignore if not already present."""
    gi = Path(repo_path) / ".gitignore"
    marker = ".deeproute/"
    if gi.exists():
        content = gi.read_text()
        if marker in content:
            return False
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n# DeepRoute generated files\n{marker}\n"
        gi.write_text(content)
    else:
        gi.write_text(f"# DeepRoute generated files\n{marker}\n")
    return True
