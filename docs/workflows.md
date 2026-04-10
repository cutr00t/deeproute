# DeepRoute Workflows

Practical usage patterns for common scenarios.

## Getting Started

### Initialize a Single Repo

```
dr_init path="/path/to/your/repo"
```

This runs the full pipeline:
1. Scans the file tree for all source files
2. AST-indexes every supported file (Python, JS/TS, Go, Rust, etc.)
3. LLM-analyzes the codebase for descriptions, tags, patterns
4. Merges AST facts + LLM interpretations into hybrid schema
5. Computes complexity scores per module
6. Generates embeddings for semantic search (if OpenAI/Vertex key available)
7. Writes `.deeproute/` (v1 markdown + v2 JSON)
8. Registers the repo globally

After init, all schema-mode tools work immediately.

### Initialize a Workspace (Multi-Repo)

```
dr_workspace_init path="/path/to/workspace"
```

Discovers git repos one level deep under the path, runs `dr_init` on each, then generates a workspace-level `ROUTER.md` with cross-repo routing.

### Check Status

```
dr_status
```

Shows: LLM backend, resolved models, embedding backend, registered repos, token usage, health status.

```
dr_status path="/path/to/repo"
```

Shows: repo-specific status including last init time, last update, health, SHA.

## Day-to-Day Usage

### Find a Function

```
dr_lookup function="resolve_model"
```

Returns the function spec with file, line number, parameters, return type, source (ast/llm/merged).

### Find a Class

```
dr_lookup class_name="SchemaReader"
```

### Browse a Module

```
dr_lookup module="src/deeproute"
```

Returns: all files with roles, all functions with specs, all classes, complexity score, model hints.

### Search by Tags

```
dr_search tags=["llm", "backend"]
```

Cross-cutting search across all modules. Returns functions, classes, files, and patterns tagged with any of the specified tags.

### Search by Text

```
dr_search query="model" type="function"
```

Text search across function names, descriptions, and tags. The `type` filter narrows to specific item types: `function`, `class`, `file`, `endpoint`, `pattern`, `module`.

### Semantic Search

```
dr_search query="how does backend detection work" semantic=True
```

Embeds the query and finds conceptually similar items by cosine similarity. Much more powerful than keyword matching — finds `detect_backend()` even though the query doesn't contain that exact name.

Requires embeddings to be generated (needs OpenAI or Vertex key during `dr_init`).

### View Project Overview

```
dr_lookup section="manifest"
```

Returns: project name, description, tech stack, module list with summaries, conventions, complexity level, recommended models.

### View Patterns

```
dr_lookup section="patterns"
```

Returns detected architectural, structural, and behavioral patterns with file locations.

### View Interfaces

```
dr_lookup section="interfaces"
```

Returns HTTP endpoints, gRPC services, event handlers, CLI commands.

### Get Deeper Context

```
dr_notes module="src/deeproute"
```

Returns freeform markdown notes for a module — architectural decisions, design context, deeper explanations that don't fit the structured schema.

## Keeping Schemas Current

### After Code Changes

```
dr_update path="/path/to/repo"
```

Runs the hybrid update pipeline:
1. Detects changed files (committed + uncommitted)
2. AST re-indexes changed files (free)
3. Computes drift score per module
4. If drift >= 0.3: LLM re-analyzes for updated descriptions/tags
5. If drift < 0.3: only factual data refreshes (free)

### Update All Registered Repos

```
dr_update
```

Without a path, updates all registered repos.

### Automatic Updates

If `auto_update_on_query` is enabled (default), `dr_query` automatically refreshes stale repos before answering.

## Planning Operations

### Preview Costs Before Running

```
dr_plan path="/path/to/workspace" action="init"
```

Returns a per-module breakdown:
- Which model would be used (based on complexity hints)
- Estimated tokens
- Estimated cost
- Reason (complexity factors)

Review the plan before running `dr_init` on a large workspace.

### Plan an Update

```
dr_plan action="update"
```

Shows which modules have drift and would trigger LLM re-analysis.

## Cost Control

### Set a Token Budget

```
dr_config key="token_budget" value="50000"
```

When the budget is reached, LLM-requiring tools refuse to run. Schema-mode tools always work.

### Check Usage

```
dr_status
```

The `token_usage` section shows total tokens, per-model breakdown, and budget remaining.

### Reset Usage Counter

```
dr_config key="token_reset" value="1"
```

### Use Schema Mode at Work

If you're on a Claude Max subscription and want to avoid extra API costs, don't set `ANTHROPIC_API_KEY`. DeepRoute falls to schema mode automatically. The Claude Code session (paid by subscription) does the reasoning using `dr_lookup`/`dr_search` results.

This is the zero-cost workflow:
1. Someone with API access runs `dr_init` once (or at a team level)
2. The `.deeproute/v2/` files are checked in (or shared)
3. Everyone uses schema-mode tools for free

## Working Across Contexts

### Personal Development

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # for LLM analysis
export OPENAI_API_KEY=sk-proj-...       # for embeddings
```

Full capabilities: agent mode + embeddings.

### Work (GCP/Vertex AI)

```bash
export CLOUD_ML_REGION=us-east5
export ANTHROPIC_VERTEX_PROJECT_ID=my-project
# No OPENAI_API_KEY — use Vertex for embeddings too
```

All traffic stays within your Google contract. Embedding backend auto-detects to Vertex.

### Mixed (Personal API + Work Embeddings)

```bash
export ANTHROPIC_API_KEY=sk-ant-...              # personal LLM
export DEEPROUTE_EMBEDDING_BACKEND=vertex        # work embeddings
export CLOUD_ML_REGION=us-east5
export GOOGLE_CLOUD_PROJECT=my-project
```

### Schema Mode Only (No Credentials)

No env vars needed. Just have `.deeproute/v2/` files available. `dr_lookup`, `dr_search`, `dr_notes`, `dr_plan` all work.

## Workspace Patterns

### Microservices

```
dr_workspace_init path="/path/to/services"
dr_plan path="/path/to/services" action="init"
```

Each service gets its own module with independent complexity scoring. The workspace router shows inter-service relationships.

### Monorepo with Packages

```
dr_init path="/path/to/monorepo"
```

DeepRoute discovers package boundaries via directory structure and generates per-module schemas.

### Cross-Cutting Queries

After workspace init, search across all repos:

```
dr_search tags=["auth"] 
```

Finds all auth-related code across all registered repos.

```
dr_search query="database migration" semantic=True
```

Semantic search across the full workspace.

## Troubleshooting

### "No v2 schema" Errors

Run `dr_init` or `dr_migrate` on the repo. Schema-mode tools require `.deeproute/v2/` files.

### Stale Schema Data

Check drift score:
```
dr_lookup module="src/app"
```

Look at the `drift_score` and `last_factual_update` fields. Run `dr_update` to refresh.

### Model 404 Errors

Your backend may not support the configured model. Use aliases (`sonnet`, `opus`, `haiku`) instead of full model IDs — they resolve correctly for your backend.

### Embedding Search Returns Empty

Embeddings may not have been generated. Check:
```
dr_status
```

Look at the `embeddings` section. If `backend` is `none`, set `OPENAI_API_KEY` or configure Vertex, then re-run `dr_init`.

### Ambiguous Backend Error

Both `ANTHROPIC_API_KEY` and Vertex credentials are set. Set `DEEPROUTE_BACKEND=anthropic` or `DEEPROUTE_BACKEND=vertex` to choose explicitly.

### Token Budget Exceeded

```
dr_config key="token_budget"           # check current budget
dr_config key="token_reset" value="1"  # reset counter
dr_config key="token_budget" value="none"  # remove limit
```

Schema-mode tools always work regardless of budget.
