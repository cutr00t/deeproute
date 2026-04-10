# DeepRoute Configuration Reference

## Config Files

### Global Config — `~/.deeproute/config.json`

Created automatically on first use. Controls defaults for all repos.

```json
{
  "version": "1.0.0",
  "defaults": {
    "model": "sonnet",
    "init_model": "sonnet",
    "local_only": true,
    "auto_update_on_query": true,
    "max_files_full_scan": 5000,
    "exclude_patterns": ["node_modules", ".git", "__pycache__", "*.pyc", "dist", "build", ".venv", "venv", ".tox"],
    "force_mode": null
  },
  "repos": { ... },
  "workspaces": { ... }
}
```

### Per-Repo Config — `.deeproute/config.json`

Overrides global defaults for a specific repo.

```json
{
  "model_override": "opus",
  "custom_layers": [],
  "custom_skills": [],
  "exclude_patterns_extra": ["generated/", "vendor/"],
  "update_strategy": "incremental",
  "router_hints": {}
}
```

## Config Keys Reference

Set via `dr_config key="<key>" value="<value>"`.

### Global Defaults

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model` | string | `"sonnet"` | Default model alias for updates and queries |
| `init_model` | string | `"sonnet"` | Model for initial deep analysis. Set to `"opus"` for richer output |
| `local_only` | bool | `true` | Add `.deeproute/` to `.gitignore` during init |
| `auto_update_on_query` | bool | `true` | Auto-refresh stale repos before `dr_query` |
| `max_files_full_scan` | int | `5000` | Skip repos with more files than this |
| `exclude_patterns` | list | See above | Glob patterns to skip during scanning |
| `force_mode` | string\|null | `null` | Force `"agent"` or `"schema"` mode. Null = auto-detect |

### Session-Level Config

These are not persisted — they live in server memory for the current session.

| Key | Effect |
|-----|--------|
| `token_budget` | Set session token limit. `dr_config key="token_budget" value="50000"`. Set to `"none"` for unlimited |
| `token_reset` | Reset token usage counter. `dr_config key="token_reset" value="1"` |

## Environment Variables

### LLM Backend

| Variable | Purpose | Example |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API authentication | `sk-ant-...` |
| `CLOUD_ML_REGION` | GCP Vertex AI region | `us-east5` |
| `ANTHROPIC_VERTEX_PROJECT_ID` | GCP project for Vertex AI | `my-project-123` |
| `DEEPROUTE_BACKEND` | Force LLM backend | `anthropic` or `vertex` |

**Detection logic:**
1. If `DEEPROUTE_BACKEND` is set → use that
2. If both API key and Vertex creds are set → error (ambiguous)
3. If only Vertex creds → use Vertex
4. If only API key → use Anthropic
5. If neither → schema mode (no LLM calls)

### Embedding Backend

| Variable | Purpose | Example |
|----------|---------|---------|
| `OPENAI_API_KEY` | OpenAI embedding API | `sk-proj-...` |
| `GOOGLE_CLOUD_PROJECT` | GCP project for Vertex embeddings | `my-project-123` |
| `DEEPROUTE_EMBEDDING_BACKEND` | Force embedding backend | `openai` or `vertex` |

**Detection logic:**
1. If `DEEPROUTE_EMBEDDING_BACKEND` is set → use that
2. If `DEEPROUTE_BACKEND=vertex` → use Vertex for embeddings
3. If `DEEPROUTE_BACKEND=anthropic` → use OpenAI if key exists (Anthropic has no embeddings)
4. If Vertex creds set and no OpenAI key → Vertex
5. If OpenAI key set → OpenAI
6. If neither → no embeddings (text search still works)

**Why two backends?** Anthropic doesn't offer embedding models. At work (GCP/Vertex), you may not want to send code to OpenAI. The separation lets you use Vertex AI for embeddings in the same GCP contract as your LLM.

## Model Aliases

Aliases resolve to full model IDs at runtime:

| Alias | Resolves to |
|-------|-------------|
| `opus` | `claude-opus-4-20250514` |
| `sonnet` | `claude-sonnet-4-20250514` |
| `haiku` | `claude-haiku-4-5-20251001` |

Full model IDs are also accepted and passed through unchanged. If a model returns 404, DeepRoute tries fallback candidates before failing.

## Embedding Models

| Backend | Model | Dimensions | Cost |
|---------|-------|-----------|------|
| OpenAI | `text-embedding-3-small` | 1536 | ~$0.02/1M tokens |
| Vertex AI | `text-embedding-004` | 768 | ~$0.025/1M tokens |

Both produce embeddings suitable for cosine similarity search. The dimension difference is handled transparently — stored embeddings include their dimensions.

## Drift Threshold

The drift threshold controls when `dr_update` triggers LLM re-analysis:

- Default: `0.3` (30% of symbols changed)
- Below threshold: only AST factual data refreshes (free)
- At/above threshold: LLM re-analyzes for updated descriptions, tags, patterns

Currently hardcoded in `updater.py` as `LLM_DRIFT_THRESHOLD`. Future: configurable via `dr_config`.

## Complexity Scoring Weights

Complexity scoring dimensions and their weights (hardcoded in `complexity.py`):

| Dimension | Weight | Normalized range |
|-----------|--------|-----------------|
| symbol_density | 15% | 2-15 symbols/file |
| api_surface | 10% | 5-50 public symbols |
| param_complexity | 15% | 1-5 avg params, 3-10 max |
| coupling | 20% | 5-30 imports, 1-8 cross-module |
| structural_depth | 10% | 2-6 directory levels |
| async_complexity | 10% | 0-100% async functions |
| volume | 10% | 3-30 files |
| method_density | 10% | 3-12 methods/class |

## Token Budget Enforcement

When a token budget is set:

1. Before each LLM call, `_call_llm` checks `token_tracker.budget_exceeded`
2. If exceeded, the call raises a `RuntimeError` with a message suggesting schema-mode tools
3. Schema-mode tools (`dr_lookup`, `dr_search`, `dr_notes`, `dr_plan`) always work — they make zero LLM calls
4. Token usage is tracked per-model with input/output breakdown
5. `dr_status` reports current usage in the `token_usage` section

## Exclude Patterns

Files matching these glob patterns are skipped during scanning:

```
node_modules, .git, __pycache__, *.pyc, dist, build, .venv, venv, .tox
```

Add repo-specific patterns via per-repo config:

```
dr_config key="exclude_patterns_extra" value='["generated/", "vendor/"]' scope="repo" path="/path/to/repo"
```

## Transport Modes

| Mode | Flag | Port | Use case |
|------|------|------|----------|
| stdio | (default) | — | Claude Code CLI integration |
| HTTP | `--http` | 7432 | Cursor, other MCP clients, persistent sessions |

HTTP mode provides cached schema readers and persistent token tracking across requests within the same server process.
