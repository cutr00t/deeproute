---
name: deeproute__update
description: Keep DeepRoute markdown routing in sync after code changes
triggers:
  - after creating new files or directories
  - after renaming or moving modules
  - after significant refactoring
  - after git pull with many changes
---

# DeepRoute Update

After making or pulling significant code changes in a repo with `.deeproute/`:

1. **Call `dr_update`** via the DeepRoute MCP server with the repo path.
2. **Review the changelog** returned by `dr_update` to see what routing docs were refreshed.
3. **If `dr_update` reports structural changes**, briefly review the updated `ROUTER.md` to ensure routing still matches your mental model.
4. **For workspace-level changes** (new repo added, service renamed), run `dr_workspace_init` to regenerate cross-repo routing.
