---
name: deeproute__plan
description: Cost-aware planning for DeepRoute operations — complexity-driven model selection, budget management
version: "2.0"
triggers:
  - planning expensive operations across repos
  - wanting to preview costs before running dr_init
  - managing token budgets
  - choosing models for analysis
  - workspace-level operations
---

# DeepRoute Planning (v2)

Before running expensive operations, use `dr_plan` to preview costs and model selection.

## 1. Preview before acting

```
dr_plan action="init" path="/path/to/workspace"
```

Returns per-module breakdown:
- **Model**: Selected based on complexity score (low → haiku, medium → sonnet, high → opus)
- **Est. tokens**: Based on file count and symbol density
- **Est. cost**: Computed from model pricing
- **Reason**: Complexity factors driving the model choice

## 2. Review complexity scores

```
dr_lookup module="src/app"
```

Check the `complexity` section:
- `score`: 1-10 programmatic score
- `factors`: what drives the score (e.g., "large public API", "high coupling")
- Raw metrics: file_count, function_count, avg_params, cross_module_deps, async_ratio

## 3. Override model selection

If the plan suggests opus for a module but you want to use sonnet:

```
dr_config key="model" value="sonnet"           # change default
dr_config key="init_model" value="sonnet"      # for init specifically
```

## 4. Set a budget

```
dr_config key="token_budget" value="50000"     # cap at 50K tokens
dr_plan action="init"                           # preview — does it fit?
```

If estimated total exceeds budget, adjust models or exclude low-value repos.

## 5. Budget monitoring

```
dr_status
```

Check `token_usage` for:
- Total input/output tokens
- Per-model breakdown
- Budget remaining
- Whether budget is exceeded

## Decision framework

| Complexity | Score | Recommended | Cost per init | When to use opus |
|-----------|-------|-------------|---------------|------------------|
| Low | 1-3 | haiku | ~$0.002 | Never |
| Medium | 4-6 | sonnet | ~$0.03 | First init of critical modules |
| High | 7-10 | opus | ~$0.15 | Complex systems with many integrations |

## Workspace planning

For multi-repo workspaces, `dr_plan` aggregates across all repos:

```
dr_plan action="init" path="/path/to/workspace"
```

Total cost is the sum of all module estimates. Use this to decide:
- Whether to init all repos or just critical ones
- Whether to use a uniform model or let complexity hints guide selection
- Whether the budget is sufficient for the operation
