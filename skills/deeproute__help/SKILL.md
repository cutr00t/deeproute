---
name: deeproute__help
description: Interactive help for DeepRoute — explains tools, workflows, and troubleshooting based on current situation
triggers:
  - asking how to use deeproute
  - confused about deeproute tools
  - first time using deeproute
  - deeproute errors or unexpected behavior
  - wanting to know which deeproute tool to use
---

# DeepRoute Help

You are a helpful guide for the DeepRoute MCP server system. Assess the user's situation and provide targeted advice.

## What is DeepRoute?

DeepRoute is an MCP server that generates and maintains a **multi-layer markdown routing system** for codebases. It gives AI coding assistants fast, structured access to project knowledge instead of reading raw source files every time.

The core loop is: **scan repo → LLM-analyze → generate markdown docs → serve via MCP tools → keep in sync with git**.

## Available Tools (Quick Reference)

| Tool | When to use |
|------|-------------|
| `dr_init` | First time setting up a repo — scans everything and generates `.deeproute/` |
| `dr_update` | After code changes — incrementally refreshes only what changed |
| `dr_query` | Ask questions about the codebase using the routing system as context |
| `dr_status` | Check what repos are registered, health, last update times |
| `dr_register` | Add/remove a repo from tracking without running a full scan |
| `dr_workspace_init` | Set up a multi-repo workspace (parent dir containing several git repos) |
| `dr_install_skills` | Install Claude Code skills for automatic navigation and update behaviors |
| `dr_config` | Read or change settings (model, excludes, auto-update, etc.) |

## Common Workflows

### "I just cloned a repo and want to set it up"
1. Run `dr_init` with the repo path
2. It scans files, detects languages, reads key configs, then LLM-generates routing docs
3. Check `.deeproute/ROUTER.md` to see the generated overview
4. The repo is now registered and ready for `dr_query` and `dr_update`

### "I have several repos that form one product"
1. Put them under a common parent directory (or they already are)
2. Run `dr_workspace_init` with the parent path
3. Each repo gets its own `.deeproute/`, plus a workspace-level `ROUTER.md` for cross-repo routing
4. `dr_query` will search across all repos when no specific path is given

### "I made code changes and want to refresh the docs"
1. Run `dr_update` with the repo path (or omit path to update all registered repos)
2. It diffs from the last known SHA, classifies changes, and only refreshes affected layers
3. Structural changes (new dirs, config files) also update ROUTER.md

### "I want to ask a question about the codebase"
1. Use `dr_query` with your question
2. Optional: set `depth` to control how much context is loaded:
   - `shallow` — ROUTER.md only (fast orientation)
   - `normal` — ROUTER.md + relevant layers (default, good for most questions)
   - `deep` — All layers loaded (complex cross-cutting questions)
3. If `auto_update_on_query` is enabled (default), it auto-refreshes stale repos first

### "I want to change the LLM model used for analysis"
```
dr_config key="model" value="claude-sonnet-4-20250514"           # global
dr_config key="model_override" value="claude-haiku-4-5-20251001" scope="repo" path="/path/to/repo"  # per-repo
```

### "I want to exclude certain directories from scanning"
```
dr_config key="exclude_patterns_extra" value='["vendor","generated"]' scope="repo" path="/path/to/repo"
```

## Troubleshooting

### "dr_init failed with 'not a git repo'"
- DeepRoute requires a git repo with at least one commit
- If the directory contains multiple repos, it auto-detects workspace mode
- Run `git init && git add . && git commit -m "initial"` first if needed

### "dr_update says 'no history found'"
- The repo hasn't been initialized yet — run `dr_init` first
- Or history.json was deleted — run `dr_init` again to regenerate

### "dr_query returns shallow/unhelpful answers"
- Try `depth="deep"` to load all layers
- Check that `.deeproute/layers/` has content: `ls .deeproute/layers/`
- If layers are stale, run `dr_update` with `force=true` to regenerate

### "I want to regenerate everything from scratch"
- Delete `.deeproute/` and run `dr_init` again
- Or run `dr_update` with `force=true` (will tell you to re-init if no history)

### "The generated docs don't match my project well"
- Check `.deeproute/config.json` for custom hints: `router_hints` lets you guide the LLM
- Consider adding `custom_layers` in the repo config for domain-specific subsystems
- The LLM model matters — Sonnet is the default; Opus produces richer analysis

## Architecture (for contributors)

```
src/deeproute/
├── server.py            # FastMCP server, 8 tool handlers
├── models.py            # Pydantic models for all data structures
├── config.py            # Global + per-repo config, registry
├── scanner.py           # File tree walking, language detection, key file reading
├── git_utils.py         # Git operations via GitPython (diff, log, SHA, discovery)
├── deepagent.py         # LLM analysis — Anthropic SDK + optional LangGraph backend
├── generator.py         # Writes .deeproute/ directory structure from LLM output
├── updater.py           # Incremental update logic — git-diff-driven layer refresh
└── skills_installer.py  # Installs Claude skills to ~/.claude/skills/
```

## Tips

- **Start simple**: `dr_init` on one repo, then `dr_query` to test. Expand to workspaces later.
- **Let auto-update work**: The default `auto_update_on_query=true` keeps things fresh without manual `dr_update` calls.
- **Read ROUTER.md directly**: The generated `.deeproute/ROUTER.md` is a great starting point even without the MCP tools — any AI assistant can read it as a file.
- **Skills are optional**: The MCP tools work in any MCP client (Claude Code, Cursor, etc.). The Claude skills (`dr_install_skills`) just add automatic behaviors for Claude Code specifically.
