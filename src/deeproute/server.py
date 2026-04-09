"""DeepRoute MCP Server — multi-layer markdown routing for agentic code assistants."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from mcp.server.fastmcp import FastMCP

from .config import (
    DEEPROUTE_DIR,
    get_config_value,
    get_effective_model,
    load_global_config,
    load_history,
    register_repo,
    register_workspace,
    save_history,
    set_config_value,
    unregister_repo,
)
from .deepagent import analyze_repo, analyze_repo_v2, query
from .llm_client import LLMBackend, get_backend, resolve_model, model_display_name
from .generator import (
    update_gitignore,
    write_routing_system,
    write_v2_schema,
    write_workspace_router,
)
from .git_utils import get_git_repos_in_dir, get_head_sha, get_repo_name, is_git_repo
from .models import HistoryEntry
from .scanner import scan_repo
from .integrations import integration_status
from .skills_installer import install_skills
from .updater import incremental_update

mcp = FastMCP("deeproute")


@mcp.tool()
async def dr_init(
    path: str,
    mode: str = "repo",
    model: str = "",
    local_only: bool = True,
) -> dict:
    """Bootstrap multi-layer markdown routing for a repo or workspace.

    Scans the entire file tree, analyzes structure via LLM, and generates
    .deeproute/ with ROUTER.md + layer files.
    """
    p = Path(path).resolve()
    if not p.exists():
        return {"success": False, "error": f"Path does not exist: {p}"}

    # Auto-detect mode
    if mode == "repo" and not is_git_repo(str(p)):
        repos = get_git_repos_in_dir(str(p))
        if repos:
            mode = "workspace"

    if mode == "workspace":
        return await _init_workspace(str(p), model, local_only)

    if not is_git_repo(str(p)):
        return {"success": False, "error": f"Not a git repo: {p}"}

    effective_model = model or get_effective_model(str(p))

    # Scan
    inventory = scan_repo(str(p))

    # Determine models
    gc = load_global_config()
    init_model = model or gc.defaults.init_model or effective_model

    # Analyze v1 (markdown)
    routing_system = await analyze_repo(inventory, effective_model)

    # Write v1
    written = write_routing_system(str(p), routing_system)

    # Analyze + write v2 (structured schema)
    v2_written: list[str] = []
    try:
        v2_data = await analyze_repo_v2(inventory, init_model)
        v2_written = write_v2_schema(str(p), v2_data, init_model)
    except Exception as e:
        logger.warning(f"v2 schema generation failed (v1 still written): {e}")

    # History
    head_sha = get_head_sha(str(p))
    now = datetime.now(timezone.utc).isoformat()
    save_history(str(p), HistoryEntry(
        last_sha=head_sha,
        last_update=now,
        init_sha=head_sha,
        init_time=now,
    ))

    # Gitignore
    if local_only:
        update_gitignore(str(p))

    # Register
    register_repo(str(p), mode)

    return {
        "success": True,
        "path": str(p),
        "files_scanned": inventory.total_files,
        "languages": inventory.languages,
        "files_written": written + v2_written,
        "layers": [l.filename for l in routing_system.layers],
        "v2_files": v2_written,
        "model_used": effective_model,
        "init_model": init_model,
    }


async def _init_workspace(path: str, model: str, local_only: bool) -> dict:
    """Initialize a multi-repo workspace."""
    repos = get_git_repos_in_dir(path)
    if not repos:
        return {"success": False, "error": f"No git repos found under {path}"}

    results = []
    components = []
    for repo_path in repos:
        result = await dr_init(repo_path, mode="repo", model=model, local_only=local_only)
        results.append(result)
        repo_name = get_repo_name(repo_path)
        components.append({
            "name": repo_name,
            "repo": repo_name,
            "description": f"Component: {repo_name}",
        })

    # Write workspace router
    ws_name = Path(path).name
    write_workspace_router(path, ws_name, components)

    # Register workspace
    register_workspace(path, repos)

    if local_only:
        update_gitignore(path)

    return {
        "success": True,
        "workspace": path,
        "repos_initialized": len(repos),
        "repo_results": results,
        "components": [c["name"] for c in components],
    }


@mcp.tool()
async def dr_update(path: str = "", force: bool = False) -> dict:
    """Incremental update of markdown routing using git history.

    Fast — only re-analyzes changed files since last update.
    If path is omitted, updates all registered repos.
    """
    if path:
        p = Path(path).resolve()
        return await incremental_update(str(p), force=force)

    # Update all registered repos
    gc = load_global_config()
    results = {}
    for repo_path in gc.repos:
        results[repo_path] = await incremental_update(repo_path, force=force)
    return {"success": True, "results": results}


@mcp.tool()
async def dr_query(
    question: str,
    path: str = "",
    depth: str = "normal",
) -> dict:
    """Route a natural-language question through DeepAgent using markdown routing as context.

    depth: shallow (router only), normal (router + relevant layers), deep (all layers)
    """
    gc = load_global_config()

    # Determine target paths
    if path:
        targets = [str(Path(path).resolve())]
    else:
        targets = list(gc.repos.keys())

    if not targets:
        return {"success": False, "error": "No repos registered. Run dr_init first."}

    # Auto-update if configured
    if gc.defaults.auto_update_on_query:
        for t in targets:
            history = load_history(t)
            if history:
                try:
                    head = get_head_sha(t)
                    if head != history.last_sha:
                        await incremental_update(t)
                except Exception:
                    pass

    # Collect router + layer content
    all_router_md = ""
    all_layers: dict[str, str] = {}

    for t in targets:
        dr_dir = Path(t) / DEEPROUTE_DIR
        router_path = dr_dir / "ROUTER.md"
        if router_path.exists():
            all_router_md += f"\n--- Repo: {Path(t).name} ---\n{router_path.read_text()}\n"

        if depth in ("normal", "deep"):
            layers_dir = dr_dir / "layers"
            if layers_dir.exists():
                for lf in sorted(layers_dir.iterdir()):
                    if lf.suffix == ".md":
                        all_layers[f"{Path(t).name}/{lf.name}"] = lf.read_text()

        if depth == "shallow":
            # Only load overview layer
            overview = dr_dir / "layers" / "overview.md"
            if overview.exists():
                all_layers[f"{Path(t).name}/overview.md"] = overview.read_text()

    if not all_router_md:
        return {"success": False, "error": "No ROUTER.md found. Run dr_init first."}

    model = get_effective_model(targets[0] if targets else None)
    answer = await query(question, all_router_md, all_layers, model)

    return {
        "success": True,
        "answer": answer,
        "repos_consulted": [Path(t).name for t in targets],
        "layers_loaded": list(all_layers.keys()),
        "depth": depth,
    }


@mcp.tool()
async def dr_status(path: str = "") -> dict:
    """Show current configuration, registered repos, last update times, and health."""
    gc = load_global_config()

    if path:
        p = str(Path(path).resolve())
        if p in gc.repos:
            history = load_history(p)
            dr_exists = (Path(p) / DEEPROUTE_DIR).exists()
            return {
                "path": p,
                "registered": True,
                "deeproute_exists": dr_exists,
                "mode": gc.repos[p].mode.value,
                "last_init": gc.repos[p].last_init,
                "last_update": history.last_update if history else "never",
                "last_sha": history.last_sha if history else "unknown",
                "healthy": dr_exists and history is not None,
            }
        return {"path": p, "registered": False}

    # Show all
    repos_status = {}
    for rp, entry in gc.repos.items():
        history = load_history(rp)
        dr_exists = (Path(rp) / DEEPROUTE_DIR).exists()
        repos_status[rp] = {
            "mode": entry.mode.value,
            "last_init": entry.last_init,
            "last_update": history.last_update if history else "never",
            "healthy": dr_exists and history is not None,
        }

    workspaces_status = {}
    for wp, entry in gc.workspaces.items():
        workspaces_status[wp] = {
            "repos": entry.repos,
            "last_init": entry.last_init,
        }

    # Detect LLM backend
    try:
        backend = get_backend().value
    except Exception:
        backend = "unknown"

    return {
        "defaults": gc.defaults.model_dump(),
        "llm_backend": backend,
        "model_resolved": model_display_name(resolve_model(gc.defaults.model)),
        "init_model_resolved": model_display_name(resolve_model(gc.defaults.init_model)),
        "repos": repos_status,
        "workspaces": workspaces_status,
        "integrations": integration_status(),
    }


@mcp.tool()
async def dr_register(path: str, action: str = "add") -> dict:
    """Add or remove a repo path from the global registry without running init."""
    p = str(Path(path).resolve())
    if action == "add":
        register_repo(p)
        return {"success": True, "action": "added", "path": p}
    elif action == "remove":
        unregister_repo(p)
        return {"success": True, "action": "removed", "path": p}
    return {"success": False, "error": f"Unknown action: {action}"}


@mcp.tool()
async def dr_workspace_init(
    path: str,
    repo_filter: list[str] | None = None,
) -> dict:
    """Initialize a multi-repo workspace from a parent directory.

    Discovers git repos under path, runs dr_init on each, then generates
    workspace-level routing.
    """
    p = Path(path).resolve()
    repos = get_git_repos_in_dir(str(p))

    if repo_filter:
        import fnmatch
        filtered = []
        for r in repos:
            name = Path(r).name
            if any(fnmatch.fnmatch(name, pat) for pat in repo_filter):
                filtered.append(r)
        repos = filtered

    if not repos:
        return {"success": False, "error": f"No matching git repos under {p}"}

    return await _init_workspace(str(p), "", True)


@mcp.tool()
async def dr_install_skills(force: bool = False) -> dict:
    """Install DeepRoute's namespaced Claude skills into ~/.claude/skills/."""
    result = install_skills(force=force)
    return {"success": True, **result}


@mcp.tool()
async def dr_config(
    key: str,
    value: str = "",
    scope: str = "global",
    path: str = "",
) -> dict:
    """Get or set configuration values.

    key: dot-notation config key (e.g., 'model', 'local_only')
    value: if provided, set; if empty, get
    scope: 'global', 'repo', or 'workspace'
    path: required if scope is 'repo' or 'workspace'
    """
    if value:
        set_config_value(key, value, scope, path or None)
        return {"success": True, "action": "set", "key": key, "value": value, "scope": scope}
    else:
        current = get_config_value(key, scope, path or None)
        return {"success": True, "action": "get", "key": key, "value": current, "scope": scope}


@mcp.tool()
async def dr_lookup(
    path: str = "",
    module: str = "",
    file: str = "",
    function: str = "",
    class_name: str = "",
    section: str = "",
) -> dict:
    """Look up specific structural information from the v2 DeepRoute schema.

    Zero LLM calls — programmatic JSON parsing only.

    section: "manifest", "interfaces", "patterns", "config_files"
    module: module name, e.g. "src/app/routes"
    file: specific file path to look up
    function: function name to find across all modules
    class_name: class name to find across all modules
    """
    from .schema_reader import SchemaReader

    gc = load_global_config()
    targets = [str(Path(path).resolve())] if path else list(gc.repos.keys())
    if not targets:
        return {"success": False, "error": "No repos registered. Run dr_init first."}

    results: dict[str, Any] = {"success": True}

    for t in targets:
        reader = SchemaReader(t)
        if not reader.has_v2():
            results[Path(t).name] = {"error": "No v2 schema. Run dr_init or dr_migrate."}
            continue

        repo_name = Path(t).name
        try:
            if section == "manifest":
                results[repo_name] = reader.load_manifest().model_dump()
            elif section == "interfaces":
                results[repo_name] = reader.load_interfaces().model_dump()
            elif section == "patterns":
                results[repo_name] = reader.load_patterns().model_dump()
            elif section == "config_files":
                results[repo_name] = reader.load_config_files().model_dump()
            elif module:
                mod = reader.load_module(module)
                if mod:
                    results[repo_name] = mod.model_dump()
                else:
                    results[repo_name] = {
                        "error": f"Module '{module}' not found.",
                        "available": reader.list_modules(),
                    }
            elif file:
                result = reader.lookup_file(file)
                results[repo_name] = result or {"error": f"File '{file}' not found in schema."}
            elif function:
                results[repo_name] = {"matches": reader.lookup_function(function)}
            elif class_name:
                results[repo_name] = {"matches": reader.lookup_class(class_name)}
            else:
                # Default: return manifest summary
                results[repo_name] = reader.load_manifest().model_dump()
        except FileNotFoundError as e:
            results[repo_name] = {"error": str(e)}

    return results


@mcp.tool()
async def dr_search(
    path: str = "",
    query: str = "",
    tags: list[str] | None = None,
    type: str = "",
    limit: int = 20,
) -> dict:
    """Search across the v2 structured schema by tags, types, or text.

    Zero LLM calls — programmatic index search only.

    type: "function", "class", "file", "endpoint", "pattern", "module"
    tags: filter by tags, e.g. ["auth", "api"]
    query: text search across names, descriptions, tags
    """
    from .schema_reader import SchemaReader

    gc = load_global_config()
    targets = [str(Path(path).resolve())] if path else list(gc.repos.keys())
    if not targets:
        return {"success": False, "error": "No repos registered."}

    all_results: list[dict] = []
    for t in targets:
        reader = SchemaReader(t)
        if not reader.has_v2():
            continue
        matches = reader.search(query=query, tags=tags, item_type=type, limit=limit)
        for m in matches:
            m["_repo"] = Path(t).name
        all_results.extend(matches)

    return {
        "success": True,
        "results": all_results[:limit],
        "total": len(all_results),
    }


@mcp.tool()
async def dr_notes(
    path: str = "",
    module: str = "",
) -> dict:
    """Load freeform markdown notes for deeper context on a module.

    Zero LLM calls. Use after dr_lookup when you need more narrative
    context than the structured schema provides.
    """
    from .schema_reader import SchemaReader

    gc = load_global_config()
    targets = [str(Path(path).resolve())] if path else list(gc.repos.keys())
    if not targets:
        return {"success": False, "error": "No repos registered."}

    for t in targets:
        reader = SchemaReader(t)
        if not reader.has_v2():
            continue
        if module:
            content = reader.load_notes(module)
            if content:
                return {"success": True, "module": module, "notes": content}
        else:
            # List available notes
            notes_dir = reader.v2_dir / "notes"
            if notes_dir.is_dir():
                available = [f.stem.replace("__", "/") for f in notes_dir.iterdir() if f.suffix == ".md"]
                return {"success": True, "available_notes": available}

    return {"success": False, "error": f"No notes found for module '{module}'."}


@mcp.tool()
async def dr_migrate(path: str) -> dict:
    """Migrate a v1 .deeproute/ directory to v2 structured schema.

    Requires LLM credentials. Reads existing ROUTER.md + layers/*.md,
    re-analyzes with the structured schema prompt, and writes v2/ files.
    Preserves v1 files for backward compatibility.
    """
    from .generator import write_v2_schema

    p = Path(path).resolve()
    dr_dir = p / DEEPROUTE_DIR
    if not dr_dir.exists():
        return {"success": False, "error": f"No .deeproute/ found at {p}. Run dr_init first."}

    v2_dir = dr_dir / "v2"
    if v2_dir.exists():
        return {"success": False, "error": "v2 schema already exists. Use dr_update to refresh."}

    # Scan and analyze with v2 prompt
    gc = load_global_config()
    model = gc.defaults.init_model
    inventory = scan_repo(str(p))
    v2_data = await analyze_repo_v2(inventory, model)

    # Write v2 files
    written = write_v2_schema(str(p), v2_data, model)

    return {
        "success": True,
        "path": str(p),
        "files_written": written,
        "model_used": model,
    }


def main():
    """Entry point for the DeepRoute MCP server."""
    if "--http" in sys.argv:
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Mount

        app = Starlette(routes=[Mount("/mcp", app=mcp.streamable_http_app())])
        uvicorn.run(app, host="0.0.0.0", port=7432)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
