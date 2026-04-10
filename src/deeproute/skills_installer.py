"""Install DeepRoute's namespaced Claude skills into ~/.claude/.

Loads skill content from the skills/ directory in the repo, which allows
skills to be versioned, updated, and swapped without changing this code.
"""

from __future__ import annotations

from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SKILLS_DIR = CLAUDE_DIR / "skills"

# Skills source directory (relative to package root)
_REPO_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"


def _discover_skills() -> dict[str, str]:
    """Discover all skills from the repo's skills/ directory.

    Returns dict of skill_name → SKILL.md content.
    """
    skills: dict[str, str] = {}

    if not _REPO_SKILLS_DIR.is_dir():
        return skills

    for skill_dir in sorted(_REPO_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            skills[skill_dir.name] = skill_file.read_text()

    return skills


def install_skills(force: bool = False) -> dict:
    """Install DeepRoute skills into ~/.claude/skills/.

    Discovers all skills from the repo's skills/ directory and installs them.
    Use force=True to overwrite existing skills (e.g., to upgrade to v2).
    """
    installed: list[str] = []
    skipped: list[str] = []
    updated: list[str] = []

    skills = _discover_skills()

    for name, content in skills.items():
        skill_dir = SKILLS_DIR / name
        skill_file = skill_dir / "SKILL.md"

        if skill_file.exists() and not force:
            # Check if content differs (upgrade available)
            existing = skill_file.read_text()
            if existing != content:
                skipped.append(f"{name} (update available, use force=True)")
            else:
                skipped.append(name)
            continue

        skill_dir.mkdir(parents=True, exist_ok=True)

        # Track whether this is a new install or upgrade
        if skill_file.exists():
            updated.append(name)
        else:
            installed.append(name)

        skill_file.write_text(content)

    return {
        "installed": installed,
        "updated": updated,
        "skipped": skipped,
        "skills_dir": str(SKILLS_DIR),
        "available_skills": list(skills.keys()),
    }
