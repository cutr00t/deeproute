# DeepRoute Architecture Plan — Phases 1–3

Living document. Updated as we build and learn.

---

## Phase 1: Model Flexibility + Graceful Degradation

**Status: In progress**

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

## Observations & Learnings

_Updated as we build and use the system._

### Phase 1
- (to be filled in as we implement and use)

### Phase 2
- (future)

### Phase 3
- (future)
