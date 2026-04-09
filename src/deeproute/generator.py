"""Markdown generation — write .deeproute/ directory structure from routing system."""

from __future__ import annotations

from pathlib import Path

from .config import DEEPROUTE_DIR
from .models import RoutingSystem


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


def write_v2_schema(
    repo_path: str | Path,
    v2_data: dict,
    generated_by: str = "",
) -> list[str]:
    """Write v2 structured schema to .deeproute/v2/. Returns list of files written."""
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

    # Add module file references to manifest
    modules_data = v2_data.get("modules", {})
    if isinstance(modules_data, dict):
        for mod_name in modules_data:
            filename = mod_name.replace("/", "__") + ".json"
            # Update manifest modules list if present
            if "modules" in manifest:
                for m in manifest["modules"]:
                    if m.get("name") == mod_name:
                        m["_file"] = f"modules/{filename}"
    elif isinstance(modules_data, list):
        # Handle case where LLM returns modules as a list
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

    # Modules
    modules_dir = root / "modules"
    modules_dir.mkdir(exist_ok=True)
    for mod_name, mod_data in modules_data.items():
        if isinstance(mod_data, dict):
            mod_data["schema_version"] = "2.0.0"
            if "name" not in mod_data:
                mod_data["name"] = mod_name
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
