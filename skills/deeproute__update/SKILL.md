---
name: deeproute__update
description: Keep DeepRoute schemas accurate after code changes — AST-aware hybrid refresh
version: "2.0"
triggers:
  - after creating new files or directories
  - after renaming or moving modules
  - after significant refactoring
  - after git pull with many changes
  - when drift score is high
---

# DeepRoute Update (v2)

After making or pulling code changes in a repo with `.deeproute/`:

## 1. Run hybrid update

```
dr_update path="/path/to/repo"
```

This runs the hybrid pipeline:
- **Always**: AST re-indexes changed files (free, fast). Function names, params, line numbers are refreshed.
- **If drift >= 0.3**: LLM re-analyzes for updated descriptions, tags, patterns (paid, targeted).
- **If drift < 0.3**: Only factual data refreshes. No LLM cost.

## 2. Review the result

The response shows:
- `factual_updates`: modules with refreshed AST data
- `llm_refreshes`: modules that triggered LLM re-analysis
- `drift_report`: per-module drift scores
- `changelog`: what was updated

## 3. Check freshness

```
dr_lookup module="src/app"
```

Look at `drift_score` and `last_factual_update` to verify the schema is current.

## When to update

- **After creating/deleting files**: Structural changes need factual refresh
- **After changing function signatures**: Parameters or return types changed
- **After pull with many commits**: Check with `dr_plan action="update"` first
- **High drift score**: If `dr_lookup` shows drift > 0.3, run `dr_update`

## Cost control

- Check estimated costs before updating a workspace: `dr_plan action="update"`
- Set a budget: `dr_config key="token_budget" value="50000"`
- Most updates are free (AST-only). LLM calls happen only on significant drift.

## Workspace updates

```
dr_update
```

Without a path, updates all registered repos. Repos with no changes are skipped.
