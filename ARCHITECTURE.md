# DeepRoute Architecture Plan — Phases 1–3

Living document. Updated as we build and learn.

---

## Phase 1: Model Flexibility + Graceful Degradation

**Status: Complete**

### Problem
Model IDs are hardcoded and vary by context:
- OAuth/subscription: `opus`, `sonnet`, `haiku` (no version suffixes)
- Anthropic API: full IDs like `claude-sonnet-4-20250514`
- Vertex AI: same full IDs, but only models enabled in the GCP project are available

A 404 from the API crashes the tool instead of falling back or explaining.

### Solution

**Model aliases** in `llm_client.py`:
```
"opus"    → try claude-opus-4-20250514, fall back to claude-opus-4
"sonnet"  → try claude-sonnet-4-20250514, fall back to claude-sonnet-4
"haiku"   → try claude-haiku-4-5-20251001, fall back to claude-haiku-4-5
```

Users set `model: "sonnet"` in config. The client resolves the alias to whatever works on the current backend. If the resolved model 404s, catch and retry with the base alias before failing.

**Changes:**
- `llm_client.py`: add `resolve_model(alias) -> str` with try/fallback
- `deepagent.py`: wrap `_call_llm` with model fallback on 404
- `config.py` / `models.py`: update defaults to use aliases
- `server.py`: surface resolved model in dr_status
- README: full rewrite reflecting v2 architecture

### Acceptance
- `dr_init` works in OAuth mode (aliases resolve)
- `dr_init` works with API key (full IDs or aliases)
- Model 404 produces a clear error message, not a stack trace
- `dr_status` shows which model resolved to what
- README is current

---

## Phase 2: Complexity-Aware Model Hints + dr_plan

**Status: Design**

### Concept
During `dr_init`, the analysis captures complexity metrics per module. These metrics inform model selection for subsequent operations — a simple utils module doesn't need Opus, but a complex distributed auth system does.

### Schema additions to v2

**In `manifest.json`:**
```json
{
  "workspace_complexity": "high",
  "total_modules": 12,
  "cross_repo_dependencies": 8,
  "recommended_init_model": "opus",
  "recommended_update_model": "sonnet"
}
```

**In each module JSON:**
```json
{
  "complexity": {
    "score": 7,              // 1-10
    "factors": ["high coupling", "complex state machine", "multiple integrations"],
    "file_count": 24,
    "function_count": 89,
    "depth": 4,              // directory nesting
    "cross_module_deps": 5
  },
  "model_hints": {
    "analysis": "opus",      // for deep init/re-analysis
    "update": "sonnet",      // for incremental updates
    "query": "haiku",        // for lookups (if agent mode)
    "use_agents": true       // whether to spawn subagents for this module
  }
}
```

### New MCP tool: `dr_plan`

Before running expensive operations across a workspace, `dr_plan` reads all module complexity scores and model hints, then proposes an execution plan:

```
dr_plan action="init" path="/workspace"

Returns:
{
  "plan": [
    {"repo": "auth-service", "model": "opus", "est_tokens": 12000, "reason": "high complexity, 89 functions"},
    {"repo": "utils", "model": "haiku", "est_tokens": 2000, "reason": "low complexity, 8 functions"},
    {"repo": "api-gateway", "model": "sonnet", "est_tokens": 6000, "reason": "medium complexity"}
  ],
  "total_est_tokens": 20000,
  "est_cost": "$0.08",
  "auto_approve": false
}
```

User reviews the plan, approves, and it executes. Or sets `auto_approve: true` in config for trusted workspaces.

### HTTP/SSE transport

Switch default from stdio to HTTP for persistent state:
- Session-level token tracking across concurrent callers
- Cached schema readers (avoid re-parsing JSON per call)
- Budget enforcement: `max_session_tokens` config field
- Multiple Claude Code subagents can share one server instance

### Token budget tracking

```json
// In session state (server memory, not persisted)
{
  "session_id": "abc123",
  "tokens_used": {
    "input": 45000,
    "output": 12000,
    "by_model": {"sonnet": 50000, "opus": 7000}
  },
  "budget_limit": 100000,
  "budget_remaining": 43000
}
```

`dr_status` reports session token usage. When budget is near limit, tools return warnings. When exceeded, agent-mode tools refuse to run (schema-mode tools always work, zero cost).

### Acceptance
- `dr_init` writes complexity scores and model hints into v2 schema
- `dr_plan` produces costed execution plans for workspace operations
- HTTP transport maintains session state
- Token budget tracked and enforced
- Model hints influence automatic model selection

---

## Phase 3: Recursive Agent Orchestration (Aspirational)

**Status: Spec / exploration**

### Vision

A multi-layer agent system where:
1. The primary Claude Code session delegates complex analysis to DeepRoute
2. DeepRoute spawns targeted subagents per module/repo, each with model hints from the schema
3. Subagents can spawn their own subagents for deeper analysis (recursive)
4. Results coalesce upward through structured handoffs
5. All of this is budget-controlled and plan-approved

### Architecture sketch

```
Primary session (Opus 4.6, OAuth)
  │
  ├── dr_deep_analyze(workspace="/figure1")
  │     │
  │     ├── Agent: auth-service (Opus, high complexity)
  │     │     ├── Sub: JWT middleware (Sonnet, medium)
  │     │     └── Sub: OAuth flow (Opus, high)
  │     │
  │     ├── Agent: api-gateway (Sonnet, medium complexity)
  │     │     └── Sub: rate limiter (Haiku, low)
  │     │
  │     └── Agent: utils (Haiku, low complexity)
  │
  └── Results coalesced into workspace-level analysis
```

### Key design questions (to answer through Phase 2 experience)

1. **Is recursive depth actually valuable, or does 2 levels suffice?**
   Most codebases probably don't benefit from more than primary → subagent. Three levels might only matter for very large monorepos or microservice meshes.

2. **Agent overhead vs direct analysis**: Does spawning a Haiku subagent for a simple module actually save tokens vs just having Sonnet read 8 files directly? Need real measurements.

3. **Coordination cost**: How much of the token budget goes to agents describing their findings to parent agents vs doing actual analysis? If >30%, the system is inefficient.

4. **Stale hint problem**: Complexity scores from 2 weeks ago might not reflect today's code. How aggressively do hints need refreshing? Can `dr_update` cheaply re-score without full re-analysis?

5. **Approval UX**: Plan → approve → execute works for explicit commands. But if the user says "refactor the auth system" and Claude Code decides to use DeepRoute's deep analysis, does it pause for approval? Or does pre-approved budget suffice?

6. **Vertex cost sensitivity**: At work, every API call has a dollar cost. The orchestration layer needs to be provably cheaper than the alternative (manual exploration + Sonnet context). Need a benchmark.

### What we'll learn from Phase 2

Before building Phase 3, we need answers to:
- Do complexity scores actually predict when Opus vs Sonnet matters?
- Does `dr_plan` get used, or do people just run `dr_init` and accept defaults?
- How often do model hints need updating?
- Is HTTP/SSE transport stable for concurrent subagent access?
- What's the actual token overhead of agent-mode vs schema-mode for common tasks?

### Tag registry concept

A horizontal index across all repos in a workspace:

```json
// ~/.deeproute/workspace_tags.json
{
  "auth": {
    "modules": ["auth-service/src/auth", "api-gateway/src/middleware"],
    "patterns": ["JWT", "OAuth2", "RBAC"],
    "complexity": "high",
    "model_hint": "opus"
  },
  "database": {
    "modules": ["services_v2/src/db", "functions_v2/src/firestore"],
    "patterns": ["Repository", "Unit of Work"],
    "complexity": "medium"
  }
}
```

This would let `dr_search(tags=["auth"])` work across an entire workspace without loading every module's schema. Built during `dr_workspace_init`, updated by `dr_update`.

---

## Phase 1.5: Accuracy Foundation + Lightweight Embeddings

**Status: Complete**

### Problem

Testing Phase 1 on DeepRoute's own repo revealed a fundamental gap: **the v2 schema is a one-time LLM snapshot that diverges from actual code**. Specific issues:

1. `dr_lookup(function="resolve_model")` returned **zero results** — the function exists at `llm_client.py:52` but the LLM didn't enumerate it during init
2. The schema listed a `DeepAgent` class that doesn't exist (module uses standalone functions)
3. Line numbers were wrong, function signatures were incomplete
4. `dr_search(query="model", type="function")` returned zero results despite 8+ model-related functions
5. Tag-based search worked well — `dr_search(tags=["llm", "backend"])` found 9 correct items
6. Manifest/patterns sections provided genuine orientation value

Root cause: the schema was only as accurate as the LLM's single-pass inference. For factual data (what functions exist, their signatures, line numbers), AST parsing is authoritative. The LLM adds value for interpretive data (descriptions, tags, patterns, purpose).

### Solution

Separate factual extraction (always accurate, no LLM) from interpretive analysis (rich but approximate, LLM-derived).

#### A. AST-based factual extraction — `ast_indexer.py`

New module using Python's stdlib `ast` for Python files and regex patterns for 10+ other languages (JS/TS, Go, Rust, Java, Kotlin, Ruby, C#, Swift, Shell, Terraform).

Extracts: function names, parameters with types, return types, line numbers, async detection, decorators, class names, bases, methods, imports.

Results on deeproute's own repo: **99 functions, 49 classes** across 19 files — all accurate.

#### B. Hybrid schema generation

During `dr_init`:
1. Scanner walks file tree (existing)
2. AST indexer extracts factual symbol tables (new, free)
3. LLM analyzes for interpretive data (existing, paid)
4. Generator merges: AST facts + LLM descriptions/tags (new)

Each `FunctionSpec` and `ClassSpec` carries a `source` field: `"ast"`, `"llm"`, or `"merged"`.

#### C. Threshold-based hybrid updates — rewritten `updater.py`

Two update modes:
1. **Factual update** (always, free): Re-index changed files via AST, update specs, compute drift scores
2. **Interpretive update** (threshold-triggered, LLM): When cumulative drift ≥ 0.3, re-analyze affected modules for tags/descriptions

Drift scoring: structural changes (added/removed symbols) weighted 1.0, signature changes weighted 0.5, normalized by total symbol count. Validated: adding 1 function + changing 1 signature out of 4 → drift 0.375 (correctly triggers LLM refresh).

Also supports uncommitted changes via `git diff HEAD` — schema stays accurate even between commits.

#### D. Lightweight embeddings — `embeddings.py`

OpenAI `text-embedding-3-small` for semantic search over schema items. Stored as `.deeproute/v2/embeddings.npz` — flat file, no infrastructure.

Validated: query "model alias resolution" correctly ranks `resolve_model` at 0.653 similarity, far above unrelated functions (~0.2).

Degrades gracefully: no OpenAI key → embeddings skipped, text search still works.

`dr_search` gains `semantic=True` flag for embedding-based similarity search.

#### E. Schema model additions

- `FunctionSpec` / `ClassSpec`: `source`, `decorators`, `is_async` fields
- `ModuleSchema` / `Manifest`: `drift_score`, `last_factual_update`, `has_embeddings`
- All backward-compatible (new fields have defaults)

### Files changed
- `src/deeproute/ast_indexer.py` — new: AST extraction engine
- `src/deeproute/embeddings.py` — new: OpenAI embeddings with npz storage
- `src/deeproute/schema.py` — source tracking, drift fields
- `src/deeproute/schema_reader.py` — semantic search, embedding store
- `src/deeproute/updater.py` — rewritten: hybrid AST/LLM updates with thresholds
- `src/deeproute/generator.py` — AST merge into v2 schemas
- `src/deeproute/git_utils.py` — uncommitted diff support
- `src/deeproute/server.py` — AST indexing in dr_init, semantic search in dr_search
- `pyproject.toml` — numpy, openai deps

### Acceptance
- [x] AST indexer extracts all public functions/classes with correct signatures
- [x] Drift scoring correctly measures structural divergence
- [x] Hybrid schema merge preserves LLM descriptions while fixing factual data
- [x] Semantic search finds relevant items by meaning, not just keyword
- [x] Threshold logic gates LLM calls behind meaningful change detection
- [x] Embeddings gracefully degrade without OpenAI key
- [ ] Full dr_init integration test with AST merge (requires MCP restart)
- [ ] dr_update factual refresh on uncommitted changes

### Impact on Phase 2/3

This phase validates and de-risks several Phase 2/3 assumptions:

1. **Complexity scoring** (Phase 2): Now programmatic. Can use AST-derived metrics (function count, import depth, parameter complexity) instead of LLM estimates. Ready for ML clustering.
2. **Tag registry** (Phase 3): Tag-based search already works well. Embeddings add semantic discovery. The workspace tag registry concept is validated.
3. **Budget control** (Phase 2): Threshold-based LLM gating means most updates are free. Only significant changes trigger paid analysis.
4. **Recursive agents** (Phase 3): Better data quality means agent orchestration won't compound errors. Factual data is always correct; only interpretive data degrades.
5. **Embeddings → vector DB** (Phase 2): The npz approach works now. Migration to ChromaDB/pgvector during HTTP transport phase requires only changing the storage backend — the embedding generation code stays.

---

## Observations & Learnings

_Updated as we build and use the system._

### Phase 1
- Model aliases solve the multi-context problem cleanly. Users set `"sonnet"` and it resolves correctly on OAuth, API key, or Vertex.
- 404 fallback prevents hard crashes when models are unavailable on a specific backend.
- The explicit `DEEPROUTE_BACKEND` override handles the ambiguous-credentials case well.

### Phase 1.5
- **AST vs LLM accuracy**: On deeproute's own repo, the AST indexer found 99 functions; the LLM schema had listed ~15 and hallucinated 3 classes. AST is the ground truth for factual data.
- **Semantic search is immediately valuable**: Even on a small codebase, cosine similarity over embeddings finds relevant functions that keyword search misses. The embedding cost is negligible (~$0.0001 for the whole repo).
- **Drift scoring works as designed**: The weighted formula (structural=1.0, signature=0.5) correctly identifies meaningful changes vs noise. Threshold of 0.3 gates LLM calls appropriately.
- **Hybrid merge is the right pattern**: AST for facts (names, params, line numbers), LLM for meaning (descriptions, tags, patterns). Neither alone is sufficient.
- **Uncommitted diff support is important**: Without it, the schema drifts during active development. With it, `dr_update` can refresh factual data even between commits.

### Phase 2
- (future)

### Phase 3
- (future)
