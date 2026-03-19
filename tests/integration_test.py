"""Integration test — creates dummy repos and exercises all MCP tools."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

TEST_ROOT = Path("/tmp/deeproute-test")

# --- Dummy repo content ---

API_SERVICE_FILES = {
    "src/main.py": '''\
from fastapi import FastAPI
from src.routes.users import router as users_router
from src.routes.items import router as items_router

app = FastAPI(title="API Service")
app.include_router(users_router, prefix="/users")
app.include_router(items_router, prefix="/items")
''',
    "src/routes/__init__.py": "",
    "src/routes/users.py": '''\
from fastapi import APIRouter
router = APIRouter()

@router.get("/")
async def list_users():
    return [{"id": 1, "name": "Alice"}]

@router.get("/{user_id}")
async def get_user(user_id: int):
    return {"id": user_id, "name": "Alice"}
''',
    "src/routes/items.py": '''\
from fastapi import APIRouter
router = APIRouter()

@router.get("/")
async def list_items():
    return [{"id": 1, "name": "Widget"}]
''',
    "src/models/__init__.py": "",
    "src/models/schemas.py": '''\
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str

class Item(BaseModel):
    id: int
    name: str
    price: float = 0.0
''',
    "src/services/__init__.py": "",
    "src/services/db.py": '''\
"""Database service — simple in-memory store."""
_store: dict = {}

def get(key: str):
    return _store.get(key)

def put(key: str, value):
    _store[key] = value
''',
    "src/__init__.py": "",
    "tests/__init__.py": "",
    "tests/test_users.py": '''\
def test_list_users():
    assert True  # placeholder

def test_get_user():
    assert True  # placeholder
''',
    "Dockerfile": '''\
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0"]
''',
    "pyproject.toml": '''\
[project]
name = "api-service"
version = "0.1.0"
dependencies = ["fastapi", "uvicorn", "pydantic"]
''',
    "README.md": """\
# API Service

REST API built with FastAPI. Handles user and item management.

## Running
```
uvicorn src.main:app
```
""",
}

WORKER_SERVICE_FILES = {
    "src/tasks/__init__.py": "",
    "src/tasks/email.py": '''\
"""Email sending tasks."""

def send_welcome_email(user_id: int, email: str) -> bool:
    """Send welcome email to new user."""
    print(f"Sending welcome to {email}")
    return True

def send_report_email(recipients: list[str], report_data: dict) -> bool:
    """Send report email to recipients."""
    return True
''',
    "src/tasks/reports.py": '''\
"""Report generation tasks."""

def generate_daily_report() -> dict:
    """Generate daily summary report."""
    return {"date": "today", "users": 42, "items": 100}

def generate_monthly_report(month: int, year: int) -> dict:
    """Generate monthly summary report."""
    return {"month": month, "year": year}
''',
    "src/__init__.py": "",
    "src/config.py": '''\
"""Worker configuration."""
BROKER_URL = "redis://localhost:6379/0"
RESULT_BACKEND = "redis://localhost:6379/1"
TASK_SERIALIZER = "json"
''',
    "Dockerfile": '''\
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["python", "-m", "celery", "worker"]
''',
    "pyproject.toml": '''\
[project]
name = "worker-service"
version = "0.1.0"
dependencies = ["celery", "redis"]
''',
    "README.md": """\
# Worker Service

Async task worker using Celery. Handles email sending and report generation.

## Tasks
- `email.send_welcome_email` — send welcome emails
- `email.send_report_email` — send report emails
- `reports.generate_daily_report` — daily summary
- `reports.generate_monthly_report` — monthly summary
""",
}


def _create_repo(path: Path, files: dict[str, str]) -> None:
    """Create a git repo with given files."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    for rel, content in files.items():
        fp = path / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=path, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )


def setup_test_workspace() -> tuple[Path, Path, Path]:
    """Create the test workspace with two repos."""
    api_path = TEST_ROOT / "api-service"
    worker_path = TEST_ROOT / "worker-service"
    _create_repo(api_path, API_SERVICE_FILES)
    _create_repo(worker_path, WORKER_SERVICE_FILES)
    return TEST_ROOT, api_path, worker_path


async def run_tests():
    """Run the full integration test sequence."""
    from deeproute.server import (
        dr_config,
        dr_init,
        dr_install_skills,
        dr_query,
        dr_register,
        dr_status,
        dr_update,
        dr_workspace_init,
    )

    print("=" * 60)
    print("DeepRoute Integration Test")
    print("=" * 60)

    # Setup
    print("\n--- Setting up test workspace ---")
    ws_path, api_path, worker_path = setup_test_workspace()
    print(f"  Created: {api_path}")
    print(f"  Created: {worker_path}")

    passed = 0
    failed = 0
    total = 8

    # Step 1: dr_init on api-service
    print("\n--- Step 1: dr_init on api-service ---")
    try:
        result = await dr_init(str(api_path))
        dr_dir = api_path / ".deeproute"
        assert result["success"], f"dr_init failed: {result}"
        assert dr_dir.exists(), ".deeproute/ not created"
        assert (dr_dir / "ROUTER.md").exists(), "ROUTER.md not created"
        assert (dr_dir / "layers").exists(), "layers/ not created"
        assert (dr_dir / "history.json").exists(), "history.json not created"
        gi = (api_path / ".gitignore").read_text()
        assert ".deeproute/" in gi, ".gitignore not updated"
        print(f"  PASS: {len(result['files_written'])} files written")
        print(f"  Languages: {result['languages']}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Step 2: dr_init on worker-service
    print("\n--- Step 2: dr_init on worker-service ---")
    try:
        result = await dr_init(str(worker_path))
        dr_dir = worker_path / ".deeproute"
        assert result["success"], f"dr_init failed: {result}"
        assert dr_dir.exists(), ".deeproute/ not created"
        assert (dr_dir / "ROUTER.md").exists(), "ROUTER.md not created"
        print(f"  PASS: {len(result['files_written'])} files written")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Step 3: dr_workspace_init
    print("\n--- Step 3: dr_workspace_init ---")
    try:
        result = await dr_workspace_init(str(ws_path))
        ws_dr = ws_path / ".deeproute"
        assert result["success"], f"workspace init failed: {result}"
        assert ws_dr.exists(), "workspace .deeproute/ not created"
        assert (ws_dr / "ROUTER.md").exists(), "workspace ROUTER.md not created"
        assert (ws_dr / "components").exists(), "components/ not created"
        print(f"  PASS: {result['repos_initialized']} repos, components: {result['components']}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Step 4: dr_status
    print("\n--- Step 4: dr_status ---")
    try:
        result = await dr_status()
        assert "repos" in result, "No repos in status"
        assert len(result["repos"]) >= 2, f"Expected >=2 repos, got {len(result['repos'])}"
        all_healthy = all(v.get("healthy") for v in result["repos"].values())
        print(f"  PASS: {len(result['repos'])} repos, all healthy: {all_healthy}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Step 5: Make a change + dr_update
    print("\n--- Step 5: dr_update after code change ---")
    try:
        new_route = api_path / "src" / "routes" / "orders.py"
        new_route.write_text('''\
from fastapi import APIRouter
router = APIRouter()

@router.get("/")
async def list_orders():
    return [{"id": 1, "total": 99.99}]
''')
        subprocess.run(["git", "add", "."], cwd=api_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add orders route"],
            cwd=api_path, capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com"},
        )
        result = await dr_update(str(api_path))
        print(f"  PASS: {result}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Step 6: dr_query
    print("\n--- Step 6: dr_query ---")
    try:
        result = await dr_query("How do the API and worker services communicate?")
        assert result["success"], f"query failed: {result}"
        assert result["answer"], "No answer returned"
        print(f"  PASS: answer length={len(result['answer'])}, repos={result['repos_consulted']}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Step 7: dr_install_skills
    print("\n--- Step 7: dr_install_skills ---")
    try:
        result = await dr_install_skills(force=True)
        assert result["success"], f"install_skills failed: {result}"
        nav_skill = Path.home() / ".claude" / "skills" / "deeproute__nav" / "SKILL.md"
        assert nav_skill.exists(), "deeproute__nav SKILL.md not created"
        print(f"  PASS: installed={result['installed']}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Step 8: dr_config
    print("\n--- Step 8: dr_config ---")
    try:
        result = await dr_config(key="model", value="claude-sonnet-4-20250514")
        assert result["success"], f"config set failed: {result}"
        result = await dr_config(key="model")
        assert result["value"] == "claude-sonnet-4-20250514", f"config get mismatch: {result}"
        print(f"  PASS: model={result['value']}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Summary
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} passed, {failed}/{total} failed")
    print("=" * 60)

    # Print generated ROUTER.md files
    for name, path in [("api-service", api_path), ("worker-service", worker_path)]:
        router = path / ".deeproute" / "ROUTER.md"
        if router.exists():
            print(f"\n--- {name} ROUTER.md ---")
            print(router.read_text()[:2000])

    ws_router = ws_path / ".deeproute" / "ROUTER.md"
    if ws_router.exists():
        print("\n--- Workspace ROUTER.md ---")
        print(ws_router.read_text()[:2000])

    return passed, failed


def cleanup():
    """Remove test artifacts."""
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    print(f"Cleaned up {TEST_ROOT}")


if __name__ == "__main__":
    try:
        passed, failed = asyncio.run(run_tests())
    finally:
        pass  # Don't auto-cleanup so we can inspect results
