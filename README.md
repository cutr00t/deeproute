# DeepRoute

Multi-layer markdown routing MCP server for agentic code assistants.

DeepRoute scans git repos, uses LLM analysis to generate a structured markdown routing system (`.deeproute/`), then serves that context through MCP tools — giving AI coding assistants like Claude Code and Cursor fast, targeted access to codebase knowledge.

## Quick Start

```bash
# Install
uv sync

# Register with Claude Code
claude mcp add deeproute -- uv run --directory /path/to/deeproute python -m deeproute

# Initialize on a repo (restart Claude Code first)
# Then use the dr_init MCP tool on any repo path
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `dr_init` | Scan a repo, LLM-analyze it, generate `.deeproute/` routing docs |
| `dr_update` | Incremental refresh — only re-analyzes what changed (git-diff-driven) |
| `dr_query` | Route natural-language questions through the routing system |
| `dr_status` | Health check — registered repos, last update times |
| `dr_register` | Add/remove repos from the global registry |
| `dr_workspace_init` | Multi-repo workspace setup with cross-repo routing |
| `dr_install_skills` | Install Claude Code skills for automatic nav/update behaviors |
| `dr_config` | Get/set config values (model, excludes, etc.) |

## How It Works

### 1. Init (`dr_init`)

Scans the repo file tree, reads key files (README, pyproject.toml, Dockerfile, etc.), detects languages, and sends a structured inventory to an LLM. The LLM produces:

- **ROUTER.md** — Project overview, tech stack, directory map, and a routing table mapping task types to subsystem layers
- **layers/*.md** — Per-subsystem deep context (architecture, key files, conventions, common tasks)

### 2. Update (`dr_update`)

Uses `git diff` from the last known SHA to detect changes. Classifies them as structural (new dirs, config changes), content (source code), or minor (docs). Only refreshes affected layers.

### 3. Query (`dr_query`)

Loads the routing system as LLM context and answers questions with three depth levels:
- `shallow` — ROUTER.md only (fast, for orientation)
- `normal` — ROUTER.md + relevant layers (default)
- `deep` — All layers loaded (for complex cross-cutting questions)

### 4. Workspace Mode (`dr_workspace_init`)

For multi-repo projects: discovers git repos under a directory, runs `dr_init` on each, then generates a workspace-level `ROUTER.md` with cross-repo routing.

## Generated Structure

```
repo/
└── .deeproute/           # gitignored by default
    ├── ROUTER.md          # routing index
    ├── config.json        # per-repo config overrides
    ├── history.json       # last SHA + timestamps
    ├── layers/
    │   ├── backend.md     # subsystem-specific context
    │   ├── frontend.md
    │   └── infra.md
    └── skills/            # optional custom skills
```

## Configuration

Global config lives at `~/.deeproute/config.json`. Per-repo overrides in `.deeproute/config.json`.

```bash
# Set default model
# (via dr_config MCP tool)
dr_config key="model" value="claude-sonnet-4-20250514"

# Set repo-specific override
dr_config key="model_override" value="claude-haiku-4-5-20251001" scope="repo" path="/path/to/repo"
```

Key settings:
- `model` — Default LLM model for analysis
- `local_only` — Whether to gitignore `.deeproute/` (default: true)
- `auto_update_on_query` — Auto-run `dr_update` before queries (default: true)
- `exclude_patterns` — Glob patterns to skip during scanning
- `agent_backend` — `direct` (Anthropic SDK, default) or `langgraph`

## Claude Skills

`dr_install_skills` installs two namespaced skills into `~/.claude/skills/`:

- **deeproute__nav** — Progressive disclosure pattern: start with ROUTER.md, follow routing table to relevant layer, go deeper only when needed
- **deeproute__update** — Reminds to call `dr_update` after significant code changes

## Architecture

```
src/deeproute/
├── server.py            # FastMCP server, all tool definitions
├── models.py            # Pydantic models
├── config.py            # Config load/save/merge
├── scanner.py           # Repo file tree walking, language detection
├── git_utils.py         # Git operations via GitPython
├── deepagent.py         # LLM analysis (Anthropic SDK + LangGraph)
├── generator.py         # Write .deeproute/ structure
├── updater.py           # Incremental update logic
└── skills_installer.py  # Claude skill installation
```

## Requirements

- Python 3.11+
- `uv` for package management
- `ANTHROPIC_API_KEY` environment variable
- Git repos to analyze

## Transports

- **stdio** (default) — For Claude Code CLI integration
- **HTTP** — `deeproute --http` starts on port 7432 for Cursor/other MCP clients

## License

LGPL-3.0 — See [LICENSE](LICENSE) for details.
