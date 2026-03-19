"""Repo scanning — walk file tree, detect languages, read key files."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .config import get_effective_excludes
from .models import FileInfo, RepoInventory

# Extension -> language mapping
EXT_LANG: dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".hpp": "C++", ".cc": "C++",
    ".cs": "C#",
    ".swift": "Swift",
    ".r": "R", ".R": "R",
    ".sql": "SQL",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".tf": "Terraform", ".tfvars": "Terraform",
    ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".md": "Markdown",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS",
    ".dockerfile": "Docker",
    ".proto": "Protobuf",
    ".graphql": "GraphQL", ".gql": "GraphQL",
}

KEY_FILENAMES: set[str] = {
    "README.md", "README.rst", "README.txt", "README",
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "tsconfig.json",
    "Cargo.toml",
    "go.mod",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "Makefile",
    "Gemfile",
    ".github/workflows/ci.yml", ".github/workflows/ci.yaml",
    ".github/workflows/main.yml",
    "AGENTS.md", "CLAUDE.md",
    "requirements.txt",
    "Procfile",
    "serverless.yml",
    "terraform.tf", "main.tf",
}

MAX_KEY_FILE_SIZE = 50_000  # 50KB limit for key file content


def _should_exclude(path: Path, root: Path, patterns: list[str]) -> bool:
    rel = str(path.relative_to(root))
    name = path.name
    for pat in patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
            return True
        # Also match directory components
        if any(fnmatch.fnmatch(part, pat) for part in path.relative_to(root).parts):
            return True
    return False


def _detect_language(ext: str, filename: str) -> str:
    if filename.lower() == "dockerfile" or filename.lower().startswith("dockerfile."):
        return "Docker"
    if filename.lower() == "makefile":
        return "Make"
    return EXT_LANG.get(ext.lower(), "")


def _build_tree_summary(root: Path, files: list[FileInfo], max_depth: int = 2) -> str:
    """Build a tree-style directory summary, limited depth."""
    dirs: set[str] = set()
    for f in files:
        parts = Path(f.path).parts
        for depth in range(1, min(len(parts), max_depth + 1)):
            dirs.add("/".join(parts[:depth]))
    lines = [f"{root.name}/"]
    for d in sorted(dirs):
        depth = d.count("/")
        indent = "  " * (depth + 1)
        name = d.split("/")[-1]
        lines.append(f"{indent}{name}/")
    return "\n".join(lines[:60])  # cap output


def scan_repo(repo_path: str | Path) -> RepoInventory:
    """Walk a repo and produce a structured inventory."""
    root = Path(repo_path).resolve()
    excludes = get_effective_excludes(str(root))

    files: list[FileInfo] = []
    languages: dict[str, int] = {}
    key_files: dict[str, str] = {}

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if _should_exclude(p, root, excludes):
            continue

        rel = str(p.relative_to(root))
        ext = p.suffix
        lang = _detect_language(ext, p.name)

        try:
            size = p.stat().st_size
        except OSError:
            continue

        files.append(FileInfo(path=rel, size=size, extension=ext, language=lang))

        if lang:
            languages[lang] = languages.get(lang, 0) + 1

        # Check if this is a key file
        if p.name in KEY_FILENAMES or rel in KEY_FILENAMES:
            if size <= MAX_KEY_FILE_SIZE:
                try:
                    key_files[rel] = p.read_text(errors="replace")
                except OSError:
                    pass

    # Also check for CI configs that might be in subdirs
    for pattern in (".github/workflows/*.yml", ".github/workflows/*.yaml"):
        for ci_file in root.glob(pattern):
            rel = str(ci_file.relative_to(root))
            if rel not in key_files and ci_file.stat().st_size <= MAX_KEY_FILE_SIZE:
                try:
                    key_files[rel] = ci_file.read_text(errors="replace")
                except OSError:
                    pass

    inventory = RepoInventory(
        root=str(root),
        name=root.name,
        files=files,
        languages=languages,
        key_files=key_files,
        total_files=len(files),
        tree_summary=_build_tree_summary(root, files),
    )
    return inventory
