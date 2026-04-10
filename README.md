# DeepRoute

Multi-layer routing MCP server for agentic code assistants.

DeepRoute scans git repos, combines LLM analysis with AST-based factual extraction to generate hybrid structured schemas, then serves targeted codebase context through MCP tools — giving AI coding assistants fast, accurate access to project knowledge without re-scanning source files.

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

## How It Works

DeepRoute uses a three-legged approach to codebase understanding:

1. **AST extraction** (factual, free) — Python `ast` module + regex for 10+ languages. Extracts every function, class, parameter, return type, and import with accurate line numbers. This is the ground truth.

2. **LLM analysis** (interpretive, paid) — Anthropic models analyze the codebase for descriptions, tags, patterns, and architectural context. Rich but approximate.

3. **Embeddings** (semantic search, cheap) — OpenAI or Vertex AI embeddings over schema items. Enables queries like "how does backend detection work" → finds `detect_backend()` at 0.686 similarity.

The hybrid merge produces schemas that are always factually accurate (AST) with rich interpretive metadata (LLM), searchable by meaning (embeddings).

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
| `dr_init` | Scan a repo, AST-index + LLM-analyze, generate hybrid v1 markdown + v2 structured schema |
| `dr_update` | Incremental refresh — AST re-index changed files (free), LLM re-analyze only when drift exceeds threshold |
| `dr_query` | Route a question through the LLM using routing docs as context |
| `dr_migrate` | Upgrade a v1-only `.deeproute/` to v2 structured schema |
| `dr_workspace_init` | Multi-repo workspace setup with cross-repo routing |

### Lookup (zero cost, no credentials)

| Tool | Description |
|------|-------------|
| `dr_lookup` | Targeted retrieval — by module, file, function, class, or section |
| `dr_search` | Cross-cutting search by tags, text, or semantic similarity across all modules |
| `dr_notes` | Load optional freeform markdown for deeper module context |

### Planning & Management

| Tool | Description |
|------|-------------|
| `dr_plan` | Costed execution plan — reads complexity scores, proposes per-module model selection + token/cost estimates |
| `dr_status` | Health check — backend, models, embedding backend, token usage, drift scores |
| `dr_register` | Add/remove repos from the global registry |
| `dr_config` | Get/set config values (model aliases, excludes, token budget, etc.) |
| `dr_install_skills` | Install Claude Code skills for automatic nav/update behaviors |

## Hybrid Schema Architecture

### AST Indexing (Phase 1.5)

During `dr_init`, DeepRoute runs AST extraction on every supported file:

- **Python**: stdlib `ast` module — full parameter types, return types, decorators, async detection
- **JavaScript/TypeScript, Go, Rust, Java, Kotlin, Ruby, C#, Swift, Shell, Terraform**: regex-based extraction

Each `FunctionSpec` and `ClassSpec` carries a `source` field: `"ast"` (factual ground truth), `"llm"` (interpretive), or `"merged"` (AST facts + LLM descriptions/tags).

### Drift Scoring

When code changes, the updater computes a drift score (0.0-1.0):
- Added/removed functions or classes: weight 1.0
- Changed function signatures: weight 0.5
- Normalized by total symbol count

When drift exceeds the threshold (default 0.3), LLM re-analyzes the module for updated descriptions and tags. Below threshold, only factual data refreshes — free.

### Complexity Scoring (Phase 2)

Each module gets a programmatic complexity score (1-10) computed from:
- Symbol density (functions + classes per file)
- Public API surface size
- Parameter complexity (avg/max params)
- Cross-module coupling (import graph)
- Structural depth (directory nesting)
- Async ratio
- Volume (file count)

Scores derive **model hints**: low complexity (1-3) → haiku, medium (4-6) → sonnet, high (7-10) → opus. `dr_plan` uses these to produce costed execution plans.

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

## Embedding Configuration

Embeddings enable semantic search (`dr_search semantic=True`). Backend auto-detected:

| Context | Backend | Model | Env Var |
|---------|---------|-------|---------|
| Personal | OpenAI | text-embedding-3-small (1536d) | `OPENAI_API_KEY` |
| Work (GCP) | Vertex AI | text-embedding-004 (768d) | ADC / `CLOUD_ML_REGION` |
| Override | Either | — | `DEEPROUTE_EMBEDDING_BACKEND=openai\|vertex` |
| Neither | None | — | Embeddings skipped, text search works |

Stored as `.deeproute/v2/embeddings.npz` — flat file, no infrastructure needed.

## Token Budget

Track and limit LLM spend per session:

```
dr_config key="token_budget" value="50000"   # set budget (tokens)
dr_config key="token_budget"                 # check current budget
dr_config key="token_reset"                  # reset usage counter
dr_status                                    # see token_usage breakdown
```

When budget is exceeded, LLM-requiring tools refuse to run. Schema-mode tools (`dr_lookup`, `dr_search`, `dr_notes`) always work — zero cost.

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
├── manifest.json      # project overview, module index, tech stack, complexity, model hints
├── modules/           # one JSON per package — file roles, function specs, class specs
│   ├── src__app.json  #   each with complexity score, drift score, source tracking
│   └── tests.json
├── interfaces.json    # HTTP endpoints, gRPC services, event handlers
├── config_files.json  # parsed Dockerfile, docker-compose, CI summaries
├── patterns.json      # detected design patterns with locations
├── embeddings.npz     # semantic search vectors (OpenAI or Vertex AI)
└── notes/             # optional freeform markdown for deeper context
    └── *.md
```

## Workspace Mode

For multi-repo projects (microservices, monorepo-adjacent):

```
dr_workspace_init path="/path/to/workspace"
```

Discovers git repos under the directory, initializes each, then generates a workspace-level `ROUTER.md` with cross-repo routing. All repos are registered and queryable as a unit.

Use `dr_plan` to see costed execution plans across the workspace before running expensive operations.

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
| `token_budget` | `null` | Session token limit (null = unlimited) |

Environment variables:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API authentication |
| `CLOUD_ML_REGION` | Vertex AI region |
| `ANTHROPIC_VERTEX_PROJECT_ID` | Vertex AI project |
| `DEEPROUTE_BACKEND` | Force LLM backend: `anthropic` or `vertex` |
| `OPENAI_API_KEY` | OpenAI embeddings |
| `DEEPROUTE_EMBEDDING_BACKEND` | Force embedding backend: `openai` or `vertex` |

## Source Architecture

```
src/deeproute/
├── server.py            # FastMCP server, 14 tool handlers, cached readers
├── llm_client.py        # Backend detection (Anthropic/Vertex/none), model aliases
├── deepagent.py         # LLM analysis — v1 markdown + v2 structured schema, token tracking
├── ast_indexer.py       # Python AST + regex extraction for 10+ languages
├── complexity.py        # Programmatic complexity scoring (1-10), model hints, cost estimation
├── embeddings.py        # OpenAI/Vertex AI embeddings with npz storage, semantic search
├── schema.py            # Pydantic models for v2 structured schema
├── schema_reader.py     # Programmatic JSON parser for dr_lookup/dr_search, semantic mode
├── models.py            # Config and data structure models
├── config.py            # Config load/save/merge, registry
├── scanner.py           # Repo file tree walking, language detection
├── generator.py         # Write .deeproute/ v1 markdown + v2 JSON, AST merge
├── git_utils.py         # Git operations — committed + uncommitted diff support
├── updater.py           # Hybrid incremental updates — AST factual + LLM threshold
├── integrations.py      # Cross-system detection (meta-prompt awareness)
└── skills_installer.py  # Claude skill installation
```

## Requirements

- Python 3.11+
- `uv` for package management
- For agent mode: `ANTHROPIC_API_KEY` or GCP Vertex AI credentials
- For schema mode: just the generated `.deeproute/v2/` files (no credentials needed)
- For embeddings: `OPENAI_API_KEY` or GCP ADC credentials (optional)

## Transports

- **stdio** (default) — For Claude Code CLI integration
- **HTTP** — `deeproute --http` starts on port 7432 for Cursor/other MCP clients

## Claude Skills

`dr_install_skills` installs namespaced skills into `~/.claude/skills/`:

- **deeproute__nav** — Progressive disclosure: manifest → modules → functions → source
- **deeproute__update** — Reminds to refresh routing after code changes
- **deeproute__help** — Interactive help, workflows, troubleshooting

## Meta-Prompt Integration

If using the [meta-prompt customization framework](https://github.com/cutr00t/meta-prompt-claude-code-extension), DeepRoute can be installed as a companion during bootstrap or added later via `/customize-manage`. See `integration/meta-prompt-recipe.md` for details.

## License

LGPL-3.0 — See [LICENSE](LICENSE) for details.
