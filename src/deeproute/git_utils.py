"""Git operations for DeepRoute — log, diff, status, repo discovery."""

from __future__ import annotations

from pathlib import Path

import git

from .models import CommitInfo, FileChange, FileChangeStatus


def is_git_repo(path: str | Path) -> bool:
    try:
        git.Repo(str(path))
        return True
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return False


def get_head_sha(repo_path: str | Path) -> str:
    repo = git.Repo(str(repo_path))
    return repo.head.commit.hexsha


def get_diff_since(repo_path: str | Path, since_sha: str) -> list[FileChange]:
    """Get file changes between since_sha and HEAD."""
    repo = git.Repo(str(repo_path))
    try:
        old_commit = repo.commit(since_sha)
    except (git.BadName, ValueError):
        return []
    head = repo.head.commit
    diff = old_commit.diff(head)
    changes: list[FileChange] = []
    for d in diff:
        if d.new_file:
            changes.append(FileChange(path=d.b_path or "", status=FileChangeStatus.ADDED))
        elif d.deleted_file:
            changes.append(FileChange(path=d.a_path or "", status=FileChangeStatus.DELETED))
        elif d.renamed_file:
            changes.append(FileChange(
                path=d.b_path or "",
                status=FileChangeStatus.RENAMED,
                old_path=d.a_path,
            ))
        else:
            changes.append(FileChange(path=d.b_path or d.a_path or "", status=FileChangeStatus.MODIFIED))
    return changes


def get_recent_log(repo_path: str | Path, since_sha: str, max_count: int = 50) -> list[CommitInfo]:
    """Get commit log from since_sha to HEAD."""
    repo = git.Repo(str(repo_path))
    commits: list[CommitInfo] = []
    for c in repo.iter_commits(max_count=max_count):
        if c.hexsha == since_sha:
            break
        commits.append(CommitInfo(
            sha=c.hexsha[:8],
            message=c.message.strip().split("\n")[0],
            timestamp=c.committed_datetime.isoformat(),
        ))
    return commits


def get_git_repos_in_dir(workspace_path: str | Path) -> list[str]:
    """Discover git repos under a directory (one level deep)."""
    wp = Path(workspace_path)
    repos: list[str] = []
    if not wp.is_dir():
        return repos
    for child in sorted(wp.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            repos.append(str(child.resolve()))
    return repos


def get_repo_name(repo_path: str | Path) -> str:
    return Path(repo_path).name
