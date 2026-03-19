"""Install DeepRoute's namespaced Claude skills into ~/.claude/."""

from __future__ import annotations

from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SKILLS_DIR = CLAUDE_DIR / "skills"

NAV_SKILL = """\
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
"""

UPDATE_SKILL = """\
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
"""


def install_skills(force: bool = False) -> dict:
    """Install DeepRoute skills into ~/.claude/skills/."""
    installed: list[str] = []
    skipped: list[str] = []

    skills = {
        "deeproute__nav": NAV_SKILL,
        "deeproute__update": UPDATE_SKILL,
    }

    for name, content in skills.items():
        skill_dir = SKILLS_DIR / name
        skill_file = skill_dir / "SKILL.md"

        if skill_file.exists() and not force:
            skipped.append(name)
            continue

        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(content)
        installed.append(name)

    return {
        "installed": installed,
        "skipped": skipped,
        "skills_dir": str(SKILLS_DIR),
    }
