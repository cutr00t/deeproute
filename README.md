# DeepRoute

Multi-layer markdown routing MCP server for agentic code assistants.

DeepRoute scans git repos, uses LLM analysis to generate structured routing docs, then serves targeted codebase context through MCP tools — giving AI coding assistants fast, accurate access to project knowledge without re-scanning source files.

## Quick Start

```bash
# Install
git clone git@github.com:cutr00t/deeproute.git ~/.claude/mcps/deeproute
cd ~/.claude/mcps/deeproute && uv sync

# Register globally with Claude Code
claude mcp add --scope user deeproute -- uv run --directory ~/.claude/mcps/deeproute python -m deeproute

# Restart Claude Code, then initialize a repo
# dr_init path="/path/to/your/repo"
```

## Two Operating Modes

### Agent Mode (has LLM credentials)
Runs LLM analysis inside the MCP server. Used for `dr_init` (deep scan) and `dr_update` (incremental refresh). Auto-detects backend from environment:

- **Anthropic API**: Set `ANTHROPIC_API_KEY`
- **GCP Vertex AI**: Set `CLOUD_ML_REGION` + `ANTHROPIC_VERTEX_PROJECT_ID`
- **Both set**: Errors with a clear message — set `DEEPROUTE_BACKEND=anthropic|vertex` to choose
- **Neither set**: Falls to schema mode

### Schema Mode (no credentials needed)
Zero LLM calls. Programmatic tools parse structured JSON files from `.deeproute/v2/`. The primary Claude Code session (paid by your subscription) does the reasoning.

Use `dr_lookup`, `dr_search`, and `dr_notes` for fast, free codebase queries.

## MCP Tools

### Generation (requires LLM credentials)

| Tool | Description |
|------|-------------|
| `dr_init` | Scan a repo, LLM-analyze it, generate v1 markdown + v2 structured schema |
| `dr_update` | Incremental refresh — only re-analyzes what changed (git-diff-driven) |
| `dr_query` | Route a question through the LLM using routing docs as context |
| `dr_migrate` | Upgrade a v1-only `.deeproute/` to v2 structured schema |
| `dr_workspace_init` | Multi-repo workspace setup with cross-repo routing |

### Lookup (zero cost, no credentials)

| Tool | Description |
|------|-------------|
| `dr_lookup` | Targeted retrieval — by module, file, function, class, or section |
| `dr_search` | Cross-cutting search by tags, text, or type across all modules |
| `dr_notes` | Load optional freeform markdown for deeper module context |

### Management

| Tool | Description |
|------|-------------|
| `dr_status` | Health check — backend, registered repos, models, last update times |
| `dr_register` | Add/remove repos from the global registry |
| `dr_config` | Get/set config values (model aliases, excludes, mode, etc.) |
| `dr_install_skills` | Install Claude Code skills for automatic nav/update behaviors |

## Model Configuration

DeepRoute uses **model aliases** that resolve to the right ID for your backend:

```
opus   → claude-opus-4-20250514
sonnet → claude-sonnet-4-20250514
haiku  → claude-haiku-4-5-20251001
```

Set via MCP tools:
```
dr_config key="model" value="sonnet"         # default for updates/queries
dr_config key="init_model" value="opus"      # for initial deep analysis
```

Full model IDs also accepted. On 404, DeepRoute tries fallback candidates before failing.

## Generated Structure

### V1 (Markdown)
```
.deeproute/
├── ROUTER.md          # routing index with tech stack, directory map, routing table
├── layers/*.md        # per-subsystem context (architecture, key files, conventions)
├── config.json        # per-repo config overrides
└── history.json       # last SHA + timestamps
```

### V2 (Structured JSON)
```
.deeproute/v2/
├── manifest.json      # project overview, module index, tech stack, tags
├── modules/           # one JSON per package — file roles, function specs, class specs
│   ├── src__app.json
│   └── tests.json
├── interfaces.json    # HTTP endpoints, gRPC services, event handlers
├── config_files.json  # parsed Dockerfile, docker-compose, CI summaries
├── patterns.json      # detected design patterns with locations
└── notes/             # optional freeform markdown for deeper context
    └── *.md
```

V2 files are what `dr_lookup`/`dr_search` parse programmatically. V1 files are still generated for backward compatibility and human readability.

## Workspace Mode

For multi-repo projects (microservices, monorepo-adjacent):

```
dr_workspace_init path="/path/to/workspace"
```

Discovers git repos under the directory, initializes each, then generates a workspace-level `ROUTER.md` with cross-repo routing. All repos are registered and queryable as a unit.

## Configuration

Global config: `~/.deeproute/config.json`
Per-repo overrides: `.deeproute/config.json`

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `sonnet` | Default model for updates and queries |
| `init_model` | `sonnet` | Model for initial deep analysis (set to `opus` for richer output) |
| `force_mode` | `null` | Force `"agent"` or `"schema"` mode (null = auto-detect) |
| `local_only` | `true` | Gitignore `.deeproute/` |
| `auto_update_on_query` | `true` | Auto-refresh stale repos before queries |
| `exclude_patterns` | `[node_modules, .git, ...]` | Glob patterns to skip during scanning |

## Claude Skills

`dr_install_skills` installs three namespaced skills into `~/.claude/skills/`:

- **deeproute__nav** — Progressive disclosure: ROUTER.md → layers → source
- **deeproute__update** — Reminds to refresh routing after code changes
- **deeproute__help** — Interactive help, workflows, troubleshooting

## Architecture

```
src/deeproute/
├── server.py            # FastMCP server, 12 tool handlers
├── llm_client.py        # Backend detection (Anthropic/Vertex/none), model aliases
├── deepagent.py         # LLM analysis — v1 markdown + v2 structured schema prompts
├── schema.py            # Pydantic models for v2 structured schema
├── schema_reader.py     # Programmatic JSON parser for dr_lookup/dr_search
├── models.py            # Config and data structure models
├── config.py            # Config load/save/merge, registry
├── scanner.py           # Repo file tree walking, language detection
├── generator.py         # Write .deeproute/ v1 markdown + v2 JSON
├── git_utils.py         # Git operations via GitPython
├── updater.py           # Incremental git-diff-driven layer refresh
├── integrations.py      # Cross-system detection (meta-prompt awareness)
└── skills_installer.py  # Claude skill installation
```

## Requirements

- Python 3.11+
- `uv` for package management
- For agent mode: `ANTHROPIC_API_KEY` or GCP Vertex AI credentials
- For schema mode: just the generated `.deeproute/v2/` files (no credentials needed)

## Transports

- **stdio** (default) — For Claude Code CLI integration
- **HTTP** — `deeproute --http` starts on port 7432 for Cursor/other MCP clients

## Meta-Prompt Integration

If using the [meta-prompt customization framework](https://github.com/cutr00t/meta-prompt-claude-code-extension), DeepRoute can be installed as a companion during bootstrap or added later via `/customize-manage`. See `integration/meta-prompt-recipe.md` for details.

## License

LGPL-3.0 — See [LICENSE](LICENSE) for details.
