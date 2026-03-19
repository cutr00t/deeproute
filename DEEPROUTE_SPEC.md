# SPEC: DeepRoute MCP — Multi-Layer Markdown Routing for Agentic Code Assistants

> **Purpose**: This document is an executable plan for Claude Code CLI.  
> Read it fully, then build out the system described below, step by step.  
> After building, register the MCP server with yourself, restart with `--continue`,  
> then run the verification suite at the end.

---

## 1 · Overview

**DeepRoute** is a Python MCP server that:

1. Exposes LangGraph Deep Agent capabilities as MCP tools.
2. Bootstraps and maintains a **multi-layer markdown routing system** for any git repo (or multi-repo workspace).
3. Integrates with **Claude Code CLI** via MCP registration and optionally adds namespaced Claude skills/agents.
4. Works identically when connected from **Cursor IDE** (or any MCP client) — the MCP surface is the full contract; Claude-specific skills are additive, not required.
5. Keeps generated files **local by default** (`.gitignore`d), with an opt-in to check them in.

### Design Principles

- **Synergistic, not dependent**: MCP tools work standalone; Claude skills enhance but aren't required.
- **Git-native**: Uses git history for incremental updates instead of full re-scans.
- **Multi-repo aware**: Supports a workspace directory containing multiple git repos that form a product.
- **Namespace everything**: All generated files, skills, and agents are prefixed `deeproute__` to avoid collision.
- **Config-over-convention**: A single `~/.deeproute/config.json` registry plus per-repo `.deeproute/config.json` overrides.

---

## 2 · Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Claude Code CLI / Cursor IDE             │
│                        (MCP Client)                          │
└──────────────┬───────────────────────────────────────────────┘
               │  MCP (stdio or streamable-http)
               ▼
┌──────────────────────────────────────────────────────────────┐
│                   DeepRoute MCP Server                       │
│  (Python · FastMCP · single long-running process)            │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Tool:       │  │ Tool:        │  │ Tool:               │ │
│  │ dr_init     │  │ dr_update    │  │ dr_query            │ │
│  │             │  │              │  │                     │ │
│  │ Bootstrap   │  │ Git-diff     │  │ Route a question    │ │
│  │ repo layout │  │ incremental  │  │ through DeepAgent   │ │
│  │ + md files  │  │ refresh      │  │ with md context     │ │
│  └─────────────┘  └──────────────┘  └─────────────────────┘ │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Tool:       │  │ Tool:        │  │ Tool:               │ │
│  │ dr_status   │  │ dr_register  │  │ dr_workspace_init   │ │
│  │             │  │              │  │                     │ │
│  │ Show config │  │ Add/remove   │  │ Multi-repo          │ │
│  │ and health  │  │ repo paths   │  │ workspace bootstrap │ │
│  └─────────────┘  └──────────────┘  └─────────────────────┘ │
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ LangGraph DeepAgent Runtime (in-process)                 ││
│  │  - ChatAnthropic / ChatOpenAI model backend              ││
│  │  - FileSystem tools (read/write within registered repos) ││
│  │  - Git tools (log, diff, blame)                          ││
│  │  - Skill router (reads SKILL.md files)                   ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
               │
               ▼  (reads / writes)
┌──────────────────────────────────────────────────────────────┐
│  Repo / Workspace Filesystem                                 │
│                                                              │
│  workspace/                   (optional multi-repo root)     │
│  ├── .deeproute/                                             │
│  │   ├── config.json          workspace-level config         │
│  │   ├── ROUTER.md            cross-repo routing entry point │
│  │   └── components/                                         │
│  │       ├── service-a.md     per-repo summary + links       │
│  │       └── service-b.md                                    │
│  ├── service-a/               (git repo)                     │
│  │   ├── .deeproute/                                         │
│  │   │   ├── config.json      repo-level config              │
│  │   │   ├── ROUTER.md        repo entry-point routing doc   │
│  │   │   ├── layers/                                         │
│  │   │   │   ├── overview.md  high-level architecture        │
│  │   │   │   ├── backend.md   backend subsystem detail       │
│  │   │   │   ├── infra.md     IaC / deploy detail            │
│  │   │   │   └── api.md       API surface detail             │
│  │   │   ├── skills/                                         │
│  │   │   │   └── refactor/                                   │
│  │   │   │       └── SKILL.md                                │
│  │   │   └── history.json     last-scanned commit SHA + ts   │
│  │   ├── .gitignore           ← .deeproute/ appended         │
│  │   └── src/ ...                                            │
│  └── service-b/               (git repo)                     │
│      └── ... (same structure)                                │
│                                                              │
│  ~/.deeproute/                                               │
│  ├── config.json              global config + repo registry  │
│  └── skills/                  global skills (shared)         │
│      └── general/                                            │
│          └── SKILL.md                                        │
│                                                              │
│  ~/.claude/                                                  │
│  ├── AGENTS.md                ← existing, read but not owned │
│  ├── settings.json                                           │
│  └── skills/                                                 │
│      └── deeproute__nav/      ← namespaced skill we add     │
│          └── SKILL.md                                        │
└──────────────────────────────────────────────────────────────┘
```

---

## 3 · MCP Tools Specification

All tool names are prefixed `dr_` (DeepRoute).

### 3.1 `dr_init`

**Description**: Full bootstrap of a repo (or workspace). Scans the entire file tree, analyzes structure, and generates the `.deeproute/` directory with all markdown layers.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute path to repo root or workspace root |
| `mode` | enum: `repo`, `workspace` | no (default `repo`) | Whether this is a single repo or multi-repo workspace |
| `model` | string | no (default from config) | LLM model to use for analysis |
| `local_only` | bool | no (default `true`) | If true, append `.deeproute/` to `.gitignore` |

**Behavior**:

1. Detect if `path` is a git repo or contains multiple git repos (auto-detect `mode` if not specified).
2. For each git repo found:
   a. Walk the file tree (respecting `.gitignore`). Collect file paths, sizes, languages.
   b. Read key files: README, package.json/pyproject.toml/Cargo.toml, Dockerfile, Makefile, CI configs, existing AGENTS.md.
   c. Send this inventory to the LangGraph DeepAgent with a structured prompt:
      - "Analyze this repository and produce a multi-layer routing system."
      - The agent produces: `ROUTER.md`, `layers/*.md`, and optionally `skills/*/SKILL.md`.
   d. Write generated files to `.deeproute/`.
   e. Record current HEAD commit SHA in `.deeproute/history.json`.
   f. If `local_only`, append `.deeproute/` to `.gitignore` (idempotent).
3. If `mode=workspace`:
   a. Also generate workspace-level `.deeproute/ROUTER.md` that links to each repo's router.
   b. Generate `.deeproute/components/*.md` summaries.
4. Register the path in `~/.deeproute/config.json`.
5. Return a summary of what was generated.

### 3.2 `dr_update`

**Description**: Incremental update using git history. Fast — only re-analyzes changed files.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | no | Repo or workspace path. If omitted, updates all registered repos. |
| `force` | bool | no (default `false`) | If true, do a full re-scan instead of incremental. |

**Behavior**:

1. Read `.deeproute/history.json` to get last-scanned commit.
2. Run `git log --oneline <last_sha>..HEAD` and `git diff --name-status <last_sha>..HEAD`.
3. Classify changes:
   - **Structural** (new/deleted/renamed dirs, new top-level configs): triggers layer-level regeneration.
   - **Content** (modified files within known subsystems): triggers targeted layer update.
   - **Minor** (docs, comments, formatting): may skip or do lightweight update.
4. For each affected layer, send the diff + current layer markdown to the DeepAgent: "Update this layer document given these changes."
5. Update `history.json` with new HEAD.
6. If workspace mode, also update cross-repo summaries if component interfaces changed.
7. Return a changelog of what was updated.

### 3.3 `dr_query`

**Description**: Route a natural-language question through the DeepAgent using the markdown routing system as context.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | string | yes | The user's question or task description |
| `path` | string | no | Repo/workspace to scope to. If omitted, uses all registered. |
| `depth` | enum: `shallow`, `normal`, `deep` | no (default `normal`) | How many layers to traverse |

**Behavior**:

1. Load the `ROUTER.md` for the target path.
2. The DeepAgent reads the router, determines which layers and skills are relevant.
3. Based on `depth`:
   - `shallow`: only use ROUTER.md + overview layer.
   - `normal`: follow the routing table to relevant layers.
   - `deep`: load all layers + relevant source files.
4. The DeepAgent produces an answer with file references and suggested actions.
5. Return the answer as MCP tool output.

### 3.4 `dr_status`

**Description**: Show current configuration, registered repos, last update times, health.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | no | Specific repo to check. If omitted, show all. |

**Behavior**: Read `~/.deeproute/config.json` and each repo's `.deeproute/history.json`. Return structured status.

### 3.5 `dr_register`

**Description**: Add or remove a repo path from the global registry without running init.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Repo path |
| `action` | enum: `add`, `remove` | yes | Add or remove |

### 3.6 `dr_workspace_init`

**Description**: Initialize a multi-repo workspace from a parent directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Parent directory containing multiple git repos |
| `repo_filter` | string[] | no | Glob patterns to include/exclude repos |

**Behavior**: Discover git repos under `path`, run `dr_init` on each, then generate workspace-level routing.

### 3.7 `dr_install_skills`

**Description**: Install DeepRoute's namespaced Claude skills and agents into `~/.claude/`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `force` | bool | no (default `false`) | Overwrite existing skills |

**Behavior**:

1. Read existing `~/.claude/AGENTS.md` and `~/.claude/skills/` to understand current patterns.
2. Generate `~/.claude/skills/deeproute__nav/SKILL.md` — a Claude skill that teaches the agent how to use `.deeproute/ROUTER.md` files for navigation.
3. Generate `~/.claude/skills/deeproute__update/SKILL.md` — a skill that reminds the agent to call `dr_update` after significant code changes.
4. Do NOT modify existing files. Only add `deeproute__*` namespaced entries.

### 3.8 `dr_config`

**Description**: Get or set configuration values.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `key` | string | yes | Dot-notation config key (e.g., `defaults.model`, `defaults.local_only`) |
| `value` | string | no | If provided, set. If omitted, get. |
| `scope` | enum: `global`, `repo`, `workspace` | no (default `global`) | Config scope |
| `path` | string | no | Required if scope is `repo` or `workspace` |

---

## 4 · Markdown Layer Design

### 4.1 ROUTER.md (Entry Point)

The ROUTER.md is the **top-level index**. It must be concise and machine-readable.

```markdown
# Project Router — {project_name}

## Identity
{1-2 sentence project description}

## Tech Stack
{Languages, frameworks, key dependencies — bullet list}

## Directory Map
{Tree-style layout, 2 levels deep max}

## Routing Table

| Domain / Task Type | Context Layer | Key Paths | Skip Paths | Skills |
|--------------------|---------------|-----------|------------|--------|
| Backend logic      | layers/backend.md | src/api/, src/services/ | infra/, frontend/ | — |
| Infrastructure     | layers/infra.md | infra/, terraform/ | src/ | terraform |
| Frontend           | layers/frontend.md | frontend/, public/ | src/api/ | — |
| Testing            | layers/testing.md | tests/, src/**/*_test.* | — | pytest |
| Documentation      | layers/docs.md | docs/, *.md | src/ | — |

## Cross-References
{If workspace: links to sibling component summaries}

## Conventions
{Coding standards, branch strategy, PR process — brief}
```

### 4.2 Layer Files (layers/*.md)

Each layer provides **subsystem-specific depth**:

```markdown
# {Subsystem Name}

## Purpose
{What this subsystem does, 2-3 sentences}

## Architecture
{Key patterns, data flow, dependencies}

## Key Files
| File / Dir | Role |
|------------|------|
| src/api/routes.py | HTTP endpoint definitions |
| src/services/auth.py | Authentication logic |

## Conventions
{Subsystem-specific patterns, naming, error handling}

## Common Tasks
{Brief recipes: "to add a new endpoint, …", "to modify the schema, …"}
```

### 4.3 Workspace ROUTER.md (Multi-Repo)

```markdown
# Workspace Router — {product_name}

## Components

| Component | Repo | Router | Description |
|-----------|------|--------|-------------|
| API Gateway | service-a/ | service-a/.deeproute/ROUTER.md | REST API |
| Worker | service-b/ | service-b/.deeproute/ROUTER.md | Async jobs |

## Inter-Component Relationships
{How services communicate: gRPC, HTTP, queues, shared DB}

## Cross-Cutting Concerns
{Auth, logging, deployment pipeline, shared libs}
```

---

## 5 · Configuration Schema

### 5.1 Global: `~/.deeproute/config.json`

```json
{
  "version": "1.0.0",
  "defaults": {
    "model": "claude-sonnet-4-20250514",
    "local_only": true,
    "auto_update_on_query": true,
    "max_files_full_scan": 5000,
    "exclude_patterns": ["node_modules", ".git", "__pycache__", "*.pyc", "dist", "build"]
  },
  "repos": {
    "/home/user/projects/my-app": {
      "mode": "repo",
      "last_init": "2026-03-19T09:00:00Z",
      "last_update": "2026-03-19T09:30:00Z"
    }
  },
  "workspaces": {
    "/home/user/projects/my-platform": {
      "repos": ["/home/user/projects/my-platform/api", "/home/user/projects/my-platform/worker"],
      "last_init": "2026-03-19T09:00:00Z"
    }
  }
}
```

### 5.2 Repo-Level: `<repo>/.deeproute/config.json`

```json
{
  "model_override": null,
  "custom_layers": ["layers/ml-pipeline.md"],
  "custom_skills": ["skills/data-migration/"],
  "exclude_patterns_extra": ["data/raw/"],
  "update_strategy": "incremental",
  "router_hints": {
    "primary_language": "python",
    "framework": "fastapi",
    "deployment": "gcp-cloudrun"
  }
}
```

---

## 6 · Implementation Plan

Build in this order. Each phase should be committed and tested before moving on.

### Phase 1: Project Skeleton + MCP Server Shell

1. Create project directory: `~/projects/deeproute-mcp/`
2. Initialize with `uv init` or a standard Python project:
   ```
   deeproute-mcp/
   ├── pyproject.toml
   ├── src/
   │   └── deeproute/
   │       ├── __init__.py
   │       ├── server.py          # FastMCP server, tool definitions
   │       ├── config.py          # Config loading/saving
   │       ├── scanner.py         # Repo scanning logic
   │       ├── generator.py       # Markdown generation via DeepAgent
   │       ├── git_utils.py       # Git operations (log, diff, status)
   │       ├── updater.py         # Incremental update logic
   │       ├── deepagent.py       # LangGraph DeepAgent wrapper
   │       ├── skills_installer.py # Claude skill installation
   │       └── models.py          # Pydantic models for config, state
   ├── skills/                    # Built-in SKILL.md templates
   │   ├── deeproute__nav/
   │   │   └── SKILL.md
   │   └── deeproute__update/
   │       └── SKILL.md
   └── tests/
       └── ...
   ```
3. Dependencies in `pyproject.toml`:
   ```
   mcp[cli]
   langchain
   langgraph
   langchain-anthropic
   gitpython
   pydantic>=2
   ```
4. Implement `server.py` with FastMCP:
   ```python
   from mcp.server.fastmcp import FastMCP

   mcp = FastMCP("deeproute", stateless_http=False)

   @mcp.tool()
   async def dr_init(path: str, mode: str = "repo", local_only: bool = True) -> dict:
       """Bootstrap multi-layer markdown routing for a repo or workspace."""
       ...

   @mcp.tool()
   async def dr_update(path: str = "", force: bool = False) -> dict:
       """Incremental update of markdown routing using git history."""
       ...

   # ... (all tools from Section 3)
   ```
5. Implement stdio transport for Claude Code CLI compatibility:
   ```python
   if __name__ == "__main__":
       mcp.run(transport="stdio")
   ```

### Phase 2: Scanner + Git Utils

1. `scanner.py`:
   - Walk file tree respecting `.gitignore` and configured exclude patterns.
   - Collect: file paths, sizes, extensions, language detection (by extension).
   - Read key files (README, config files, CI, Dockerfiles, existing AGENTS.md).
   - Produce a structured `RepoInventory` (Pydantic model).
2. `git_utils.py`:
   - `get_head_sha(repo_path) -> str`
   - `get_diff_since(repo_path, since_sha) -> list[FileChange]`
   - `get_recent_log(repo_path, since_sha) -> list[CommitInfo]`
   - `get_git_repos_in_dir(workspace_path) -> list[str]`
   - Use `gitpython` for all operations.

### Phase 3: DeepAgent + Generator

1. `deepagent.py`:
   - Wrap a LangGraph `StateGraph` with:
     - A planner node that reads the repo inventory.
     - A generator node that produces markdown content.
     - A reviewer node that checks coherence.
   - Use `ChatAnthropic` as the model backend.
   - Expose `analyze_repo(inventory: RepoInventory) -> RoutingSystem` and `update_layer(layer_content: str, changes: list[FileChange]) -> str`.
   - **Fallback**: If LangGraph/DeepAgents dependencies cause issues, implement as direct LLM calls with structured prompts. The routing architecture is the value — the specific agent framework is secondary.
2. `generator.py`:
   - Take DeepAgent output and write `.deeproute/` directory structure.
   - Templates for ROUTER.md, layer files, SKILL.md files.
   - Idempotent: re-running doesn't duplicate content.

### Phase 4: Updater (Incremental)

1. `updater.py`:
   - Read `history.json`, compute git diff.
   - Classify changes by impact (structural vs. content vs. minor).
   - For each affected layer, call DeepAgent with targeted update prompt.
   - Update `history.json`.
   - For workspace mode, detect cross-repo interface changes.

### Phase 5: Config + Registry

1. `config.py`:
   - Load/save global config (`~/.deeproute/config.json`).
   - Load/save repo config (`.deeproute/config.json`).
   - Merge configs with repo overriding global.
   - `dr_config` tool implementation.
2. `models.py`:
   - Pydantic models for all config, state, and data structures.

### Phase 6: Claude Skills Installer

1. `skills_installer.py`:
   - Read `~/.claude/` to discover existing patterns.
   - Generate namespaced skills:
     - `deeproute__nav/SKILL.md`: Teaches Claude how to find and read `.deeproute/ROUTER.md`, follow routing tables, and load layers progressively.
     - `deeproute__update/SKILL.md`: Teaches Claude to call `dr_update` after making significant code changes, and how to interpret update results.
   - Write to `~/.claude/skills/` without modifying existing files.

### Phase 7: Integration + Registration

1. Add a CLI entry point for manual use:
   ```
   python -m deeproute.server          # stdio mode (for Claude Code)
   python -m deeproute.server --http   # HTTP mode (for Cursor or remote)
   ```
2. Self-register with Claude Code CLI. **After the server is built**, run:
   ```bash
   claude mcp add deeproute -- python -m deeproute.server
   ```
   This registers the stdio-based MCP server globally.
3. Test connection:
   ```bash
   claude mcp list   # should show deeproute
   ```

### Phase 8: Verification Suite

Build a test harness that proves the system works end-to-end.

1. **Create a dummy multi-repo workspace**:
   ```
   /tmp/deeproute-test/
   ├── api-service/          (git repo, Python FastAPI app)
   │   ├── src/
   │   │   ├── main.py
   │   │   ├── routes/
   │   │   │   ├── users.py
   │   │   │   └── items.py
   │   │   ├── models/
   │   │   │   └── schemas.py
   │   │   └── services/
   │   │       └── db.py
   │   ├── tests/
   │   │   └── test_users.py
   │   ├── Dockerfile
   │   ├── pyproject.toml
   │   └── README.md
   └── worker-service/       (git repo, Python Celery worker)
       ├── src/
       │   ├── tasks/
       │   │   ├── email.py
       │   │   └── reports.py
       │   └── config.py
       ├── Dockerfile
       ├── pyproject.toml
       └── README.md
   ```
   Each with `git init` + initial commit.

2. **Test sequence** (run from Claude Code CLI after MCP registration):

   ```
   Step 1: Call dr_init on api-service/
     → Verify .deeproute/ created with ROUTER.md + layers/
     → Verify .gitignore updated
     → Verify history.json has HEAD sha

   Step 2: Call dr_init on worker-service/
     → Same checks

   Step 3: Call dr_workspace_init on parent directory
     → Verify workspace-level .deeproute/ with cross-repo router

   Step 4: Call dr_status
     → Should show both repos + workspace, all green

   Step 5: Make a code change in api-service (add a new route file)
     → git add + commit
     → Call dr_update on api-service/
     → Verify layers updated to reflect new route
     → Verify history.json updated

   Step 6: Call dr_query with "How do the API and worker services communicate?"
     → Should use workspace router to load both component summaries
     → Should return a coherent answer

   Step 7: Call dr_install_skills
     → Verify ~/.claude/skills/deeproute__nav/ created
     → Verify existing ~/.claude/ files untouched

   Step 8: Call dr_config to change default model
     → Verify config updated
   ```

3. **Create a test script** (`tests/integration_test.py`) that:
   - Sets up the dummy repos.
   - Programmatically calls each MCP tool.
   - Asserts expected file structure and content.
   - Cleans up afterward.

---

## 7 · Claude Skill Definitions

### 7.1 `deeproute__nav/SKILL.md`

```markdown
---
name: deeproute__nav
description: Navigate codebases using DeepRoute's multi-layer markdown routing system
triggers:
  - navigating unfamiliar code
  - finding where something is implemented
  - understanding project structure
  - working across multiple repos
---

# DeepRoute Navigation

When working in a repo that has a `.deeproute/` directory, use this progressive disclosure pattern:

1. **Start with ROUTER.md**: Read `.deeproute/ROUTER.md` first. It contains the project overview, directory map, and routing table.

2. **Follow the routing table**: Match the current task to a row in the routing table. Load only the referenced layer file (e.g., `layers/backend.md`), NOT all layers.

3. **Go deeper only when needed**: If the layer file references specific source files, read those. Don't read source files preemptively.

4. **Multi-repo**: If there's a workspace-level `.deeproute/ROUTER.md` in the parent directory, start there when working across repos.

5. **Prefer MCP tools**: If the `deeproute` MCP server is available, use `dr_query` for complex questions — it routes through the full DeepAgent with all context.

6. **After changes**: After making significant code changes (new files, renamed modules, architectural shifts), call `dr_update` via MCP to keep the routing system current.
```

### 7.2 `deeproute__update/SKILL.md`

```markdown
---
name: deeproute__update
description: Keep DeepRoute markdown routing in sync after code changes
triggers:
  - after creating new files or directories
  - after renaming or moving modules
  - after significant refactoring
  - after git pull with many changes
---

# DeepRoute Update

After making or pulling significant code changes in a repo with `.deeproute/`:

1. **Call `dr_update`** via the DeepRoute MCP server with the repo path.
2. **Review the changelog** returned by `dr_update` to see what routing docs were refreshed.
3. **If `dr_update` reports structural changes**, briefly review the updated `ROUTER.md` to ensure routing still matches your mental model.
4. **For workspace-level changes** (new repo added, service renamed), run `dr_workspace_init` to regenerate cross-repo routing.
```

---

## 8 · Key Implementation Details

### 8.1 DeepAgent Prompts

**Full scan analysis prompt** (used by `dr_init`):

```
You are analyzing a software repository to create a multi-layer markdown routing system.

Given the following repository inventory:
{inventory_json}

Generate:
1. A ROUTER.md following this template: {router_template}
2. Layer files for each major subsystem following this template: {layer_template}
3. Suggested skills (if any common workflows are apparent)

Rules:
- ROUTER.md must be concise — it's a routing index, not documentation.
- Layer files should have enough detail to orient an AI coding agent.
- Routing table entries must have non-overlapping scopes.
- Prefer fewer, well-scoped layers over many thin ones (3-7 layers is ideal).
- Include a "Common Tasks" section in each layer with 2-3 recipes.
```

**Incremental update prompt** (used by `dr_update`):

```
You are updating a markdown routing layer document based on recent code changes.

Current layer document:
{current_layer_md}

Git changes since last update:
{diff_summary}

Commit messages:
{commit_messages}

Update the layer document to reflect these changes. Preserve existing structure.
Only modify sections affected by the changes. If the changes don't affect this
layer, return it unchanged.
```

### 8.2 Git-Aware Change Classification

```python
def classify_changes(changes: list[FileChange]) -> ChangeImpact:
    structural_patterns = [
        "*/new_directory/*",     # new directories
        "Dockerfile",            # containerization changes
        "*.toml", "*.json",      # config files at root
        "*.yml", "*.yaml",       # CI/CD changes
    ]
    # STRUCTURAL: new/deleted top-level dirs, config changes, new services
    # CONTENT: modified files within existing subsystem boundaries
    # MINOR: docs-only, comment-only, formatting-only changes
```

### 8.3 MCP Server Transport

For Claude Code CLI, use **stdio** transport (simplest, most reliable):

```python
# server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("deeproute")

# ... tool registrations ...

if __name__ == "__main__":
    import sys
    if "--http" in sys.argv:
        # For Cursor IDE or remote clients
        import uvicorn
        from fastapi import FastAPI
        app = FastAPI()
        app.mount("/mcp", mcp.streamable_http_app())
        uvicorn.run(app, host="0.0.0.0", port=7432)
    else:
        # For Claude Code CLI (stdio)
        mcp.run(transport="stdio")
```

Registration:
```bash
# Global (available in all repos)
claude mcp add deeproute -- python -m deeproute.server

# Or scoped to a workspace
claude mcp add deeproute --scope /path/to/workspace -- python -m deeproute.server
```

### 8.4 Progressive Disclosure for Token Efficiency

The routing system must be **cheap to enter and expensive only when needed**:

- `ROUTER.md`: ~200-400 tokens (always loaded)
- Each `layers/*.md`: ~300-800 tokens (loaded on demand)
- `SKILL.md` files: ~100-300 tokens (loaded when skill triggered)
- Source files: variable (loaded only by explicit reference)

The DeepAgent should be instructed to load the minimum necessary context at each step.

---

## 9 · Post-Build Verification Checklist

After building, confirm each item:

- [ ] `python -m deeproute.server` starts without error (stdio mode)
- [ ] `python -m deeproute.server --http` starts HTTP server on port 7432
- [ ] `claude mcp add deeproute -- python -m deeproute.server` succeeds
- [ ] `claude mcp list` shows `deeproute` with all `dr_*` tools
- [ ] Restart Claude Code CLI with `--continue`; tools are accessible
- [ ] `dr_init` on a test repo creates expected `.deeproute/` structure
- [ ] `dr_update` after a commit produces incremental changes
- [ ] `dr_query` returns contextual answers using the routing system
- [ ] `dr_workspace_init` handles multi-repo correctly
- [ ] `dr_install_skills` adds `deeproute__*` skills to `~/.claude/`
- [ ] `.gitignore` is updated and `.deeproute/` is not tracked
- [ ] Integration test script passes
- [ ] HTTP mode works for Cursor IDE connection

---

## 10 · Build + Test Execution Instructions

**For Claude Code CLI — execute in this order:**

```
1. Create ~/projects/deeproute-mcp/ and implement Phase 1-7 above.
2. Run unit tests to verify each module.
3. Start the MCP server and register it:
     claude mcp add deeproute -- python -m deeproute.server
4. Restart with: claude --continue
5. Create the dummy test workspace at /tmp/deeproute-test/ (Phase 8).
6. Run through the 8-step test sequence using MCP tool calls.
7. Fix any issues discovered.
8. Run dr_install_skills to add Claude skills.
9. Confirm the skills work by navigating the test repo using .deeproute/ files.
10. Clean up test artifacts.
```

**After confirming everything works, report:**
- Which tools passed/failed
- The generated ROUTER.md for the test repos (paste them)
- Any design adjustments made during implementation
- Suggestions for improvements

---

## Appendix A: Environment Assumptions

- Python 3.11+
- `uv` available for dependency management
- `git` available on PATH
- Claude Code CLI installed and authenticated
- `ANTHROPIC_API_KEY` set in environment (for DeepAgent LLM calls)
- `~/.claude/` exists with current Claude Code configuration

## Appendix B: Fallback Strategy

If `langchain` / `langgraph` / `deepagents` cause dependency conflicts or runtime issues:

1. Implement the DeepAgent as **direct Anthropic API calls** using `anthropic` Python SDK.
2. The routing logic (read ROUTER.md → pick layer → load context → answer) can be implemented as a simple state machine without LangGraph.
3. The MCP tools and markdown generation remain identical — only the internal "brain" changes.
4. This fallback should be implemented as a config option: `"agent_backend": "langgraph" | "direct"`.
