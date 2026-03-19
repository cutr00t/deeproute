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
