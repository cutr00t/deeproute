---
name: deeproute__nav
description: Navigate codebases using DeepRoute's hybrid schema system — AST-accurate lookups, semantic search, progressive disclosure
version: "2.0"
triggers:
  - navigating unfamiliar code
  - finding where something is implemented
  - understanding project structure
  - working across multiple repos
  - looking for functions, classes, or patterns
---

# DeepRoute Navigation (v2)

When working in a repo with a `.deeproute/` directory, use this layered approach:

## 1. Orient with the manifest

```
dr_lookup section="manifest"
```

Get the project overview: tech stack, module list, conventions, complexity level. This costs zero tokens.

## 2. Find specific code

**By name** (exact, AST-accurate):
```
dr_lookup function="function_name"
dr_lookup class_name="ClassName"
dr_lookup file="src/path/to/file.py"
```

**By concept** (semantic, embedding-based):
```
dr_search query="how does authentication work" semantic=True
```

**By tag** (cross-cutting):
```
dr_search tags=["auth", "middleware"]
```

All of these are zero-cost schema-mode operations.

## 3. Drill into a module

```
dr_lookup module="src/app"
```

Returns: all files with roles, function specs (with parameter types, line numbers), class specs, complexity score, model hints, drift score. Source tracking shows whether data came from AST (factual) or LLM (interpretive).

## 4. Get deeper context

```
dr_notes module="src/app"
```

Freeform markdown with architectural decisions, design context, deeper explanations.

## 5. View patterns and interfaces

```
dr_lookup section="patterns"      # architectural patterns
dr_lookup section="interfaces"    # HTTP endpoints, event handlers
```

## 6. Multi-repo navigation

If there's a workspace registered:
```
dr_search tags=["database"] 
```
Searches across ALL registered repos. Use `dr_plan` to understand the workspace structure before diving into individual repos.

## Key principles

- **Start with `dr_lookup`/`dr_search`** — they're free and fast
- **Use `semantic=True`** when you don't know exact names
- **Check `source` field** on function/class specs: `"ast"` = factual ground truth, `"llm"` = interpretive
- **Check `drift_score`** — if > 0.3, the schema may be stale. Run `dr_update`
- Only use `dr_query` (LLM-powered) when schema-mode tools aren't enough
