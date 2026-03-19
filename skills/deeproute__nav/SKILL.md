---
name: deeproute__nav
description: Navigate codebases using DeepRoute's multi-layer markdown routing system
triggers:
  - navigating unfamiliar code
  - finding where something is implemented
  - understanding project structure
  - working across multiple repos
---

# DeepRoute Navigation

When working in a repo that has a `.deeproute/` directory, use this progressive disclosure pattern:

1. **Start with ROUTER.md**: Read `.deeproute/ROUTER.md` first. It contains the project overview, directory map, and routing table.

2. **Follow the routing table**: Match the current task to a row in the routing table. Load only the referenced layer file (e.g., `layers/backend.md`), NOT all layers.

3. **Go deeper only when needed**: If the layer file references specific source files, read those. Don't read source files preemptively.

4. **Multi-repo**: If there's a workspace-level `.deeproute/ROUTER.md` in the parent directory, start there when working across repos.

5. **Prefer MCP tools**: If the `deeproute` MCP server is available, use `dr_query` for complex questions — it routes through the full DeepAgent with all context.

6. **After changes**: After making significant code changes (new files, renamed modules, architectural shifts), call `dr_update` via MCP to keep the routing system current.
