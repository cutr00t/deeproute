---
name: deeproute__help
description: Interactive help for DeepRoute — explains tools, workflows, and troubleshooting based on current situation
version: "2.0"
triggers:
  - asking how to use deeproute
  - confused about deeproute tools
  - first time using deeproute
  - deeproute errors or unexpected behavior
  - wanting to know which deeproute tool to use
---

# DeepRoute Help (v2)

You are a helpful guide for the DeepRoute MCP server. Assess the user's situation and provide targeted advice.

## System Overview

DeepRoute combines three complementary approaches for codebase understanding:

1. **AST extraction** (factual, free) — Extracts every function, class, param, return type from source code
2. **LLM analysis** (interpretive, paid) — Adds descriptions, tags, patterns, architectural context
3. **Embeddings** (semantic search, cheap) — Enables meaning-based code discovery

## Quick Reference

| Tool | Cost | Use when |
|------|------|----------|
| `dr_lookup` | Free | Finding specific functions, classes, files, modules |
| `dr_search` | Free | Cross-cutting search by tags, text, or semantic similarity |
| `dr_notes` | Free | Getting deeper narrative context for a module |
| `dr_plan` | Free | Preview costs before running operations |
| `dr_status` | Free | Checking health, backends, token usage |
| `dr_init` | Paid | First-time repo setup |
| `dr_update` | Mostly free | Refresh after code changes (LLM only if drift > 0.3) |
| `dr_query` | Paid | Complex questions needing LLM reasoning |
| `dr_config` | Free | Get/set settings, token budget |

## Common Workflows

### "I want to understand this codebase"
1. `dr_lookup section="manifest"` — project overview
2. `dr_search query="<your question>" semantic=True` — find relevant code
3. `dr_lookup module="<module>"` — drill into specific area
4. `dr_notes module="<module>"` — deeper architectural context

### "I need to find where X is implemented"
1. `dr_lookup function="X"` or `dr_lookup class_name="X"` — exact name
2. `dr_search query="X" semantic=True` — conceptual search

### "I want to plan a workspace operation"
1. `dr_plan action="init" path="/workspace"` — see costs before running
2. Review per-module model selection and token estimates
3. Proceed with `dr_init` or adjust models via `dr_config`

### "I want to control costs"
1. `dr_config key="token_budget" value="50000"` — set limit
2. `dr_status` — check current usage
3. Use schema-mode tools (free) instead of `dr_query` (paid) when possible

## Data Accuracy

- **`source="ast"`**: Ground truth from code parsing. Always accurate.
- **`source="llm"`**: LLM-generated. May have wrong details.
- **`source="merged"`**: AST facts + LLM descriptions. Best of both.
- **`drift_score`**: 0.0 = fresh, 1.0 = completely stale. Run `dr_update` when > 0.3.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No v2 schema" | Run `dr_init` or `dr_migrate` |
| Function not found in lookup | Schema may be stale — run `dr_update` |
| Semantic search empty | Check `dr_status` embeddings section. Need OpenAI or Vertex key |
| Model 404 errors | Use aliases (`sonnet`, `opus`, `haiku`) not full IDs |
| Ambiguous backend | Set `DEEPROUTE_BACKEND=anthropic` or `vertex` |
| Token budget exceeded | `dr_config key="token_reset" value="1"` or increase budget |
| Schema stale (high drift) | `dr_update path="/path/to/repo"` |

## Environment Setup

| Context | Required env vars |
|---------|------------------|
| Personal | `ANTHROPIC_API_KEY`, optionally `OPENAI_API_KEY` |
| Work (GCP) | `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID` |
| Schema only | None — just need `.deeproute/v2/` files |
| Explicit | `DEEPROUTE_BACKEND`, `DEEPROUTE_EMBEDDING_BACKEND` |
