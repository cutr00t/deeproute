"""Cross-system integration detection for DeepRoute.

Detects whether meta-prompt (or other companion systems) are installed
and exposes integration status for tools and skills to adapt behavior.
"""

from __future__ import annotations

from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"


def detect_meta_prompt() -> dict:
    """Check if meta-prompt customization system is installed."""
    customize_cmd = CLAUDE_DIR / "commands" / "customize.md"
    manage_cmd = CLAUDE_DIR / "commands" / "customize-manage.md"
    help_cmd = CLAUDE_DIR / "commands" / "help-agent.md"
    customizations_doc = CLAUDE_DIR / "CUSTOMIZATIONS.md"

    installed = customize_cmd.exists() or manage_cmd.exists()

    commands = [
        f.stem for f in (CLAUDE_DIR / "commands").iterdir()
        if f.suffix == ".md"
    ] if (CLAUDE_DIR / "commands").is_dir() else []

    agents = [
        f.stem for f in (CLAUDE_DIR / "agents").iterdir()
        if f.suffix == ".md"
    ] if (CLAUDE_DIR / "agents").is_dir() else []

    mcps = [
        d.name for d in (CLAUDE_DIR / "mcps").iterdir()
        if d.is_dir()
    ] if (CLAUDE_DIR / "mcps").is_dir() else []

    return {
        "installed": installed,
        "has_manage": manage_cmd.exists(),
        "has_help": help_cmd.exists(),
        "has_customizations_doc": customizations_doc.exists(),
        "commands": commands,
        "agents": agents,
        "mcps": mcps,
    }


def detect_deeproute_skills() -> dict:
    """Check which DeepRoute skills are installed."""
    skills_dir = CLAUDE_DIR / "skills"
    dr_skills = ["deeproute__nav", "deeproute__update", "deeproute__help"]
    installed = []
    missing = []
    for name in dr_skills:
        if (skills_dir / name / "SKILL.md").exists():
            installed.append(name)
        else:
            missing.append(name)
    return {"installed": installed, "missing": missing}


def integration_status() -> dict:
    """Full integration status across all companion systems."""
    return {
        "meta_prompt": detect_meta_prompt(),
        "deeproute_skills": detect_deeproute_skills(),
    }
