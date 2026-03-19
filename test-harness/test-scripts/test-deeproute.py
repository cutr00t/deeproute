#!/usr/bin/env python3
"""Test DeepRoute end-to-end: scan, init, update, query across demo repos."""

import asyncio
import subprocess
import sys
from pathlib import Path

# Ensure demo repos exist
def setup():
    script = Path(__file__).parent / "setup-demo-repos.sh"
    subprocess.run(["bash", str(script)], check=True)

async def run():
    # Add deeproute to path
    sys.path.insert(0, "/opt/deeproute/src")
    from deeproute.server import dr_init, dr_query, dr_status, dr_update, dr_workspace_init, dr_install_skills

    DEMO = "/tmp/demo-workspace"
    passed = 0
    failed = 0

    tests = [
        ("dr_init on Python API repo", lambda: dr_init(f"{DEMO}/notes-api")),
        ("dr_init on journal (non-code)", lambda: dr_init(f"{DEMO}/daily-journal")),
        ("dr_init on frontend", lambda: dr_init(f"{DEMO}/webapp-frontend")),
        ("dr_workspace_init", lambda: dr_workspace_init(DEMO)),
        ("dr_status (all repos)", lambda: dr_status()),
        ("dr_query (code question)", lambda: dr_query("How do I add a new API endpoint to notes-api?")),
        ("dr_query (cross-repo)", lambda: dr_query("How does the frontend connect to the backend?")),
        ("dr_query (non-code)", lambda: dr_query("What templates are available for journal entries?", path=f"{DEMO}/daily-journal")),
        ("dr_install_skills", lambda: dr_install_skills(force=True)),
    ]

    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            result = await fn()
            success = result.get("success", True) if isinstance(result, dict) else True
            if not success:
                print(f"  FAIL: {result.get('error', result)}")
                failed += 1
            else:
                # Print key info
                if isinstance(result, dict):
                    for k in ("files_scanned", "languages", "layers", "repos_initialized",
                              "components", "repos", "answer", "installed"):
                        if k in result:
                            val = result[k]
                            if k == "answer":
                                val = val[:200] + "..." if len(str(val)) > 200 else val
                            print(f"  {k}: {val}")
                print(f"  PASS")
                passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    # Integration status check
    print(f"\n--- Integration status ---")
    try:
        status = await dr_status()
        integrations = status.get("integrations", {})
        mp = integrations.get("meta_prompt", {})
        skills = integrations.get("deeproute_skills", {})
        print(f"  meta_prompt installed: {mp.get('installed', False)}")
        print(f"  meta_prompt commands: {len(mp.get('commands', []))}")
        print(f"  deeproute skills installed: {skills.get('installed', [])}")
    except Exception as e:
        print(f"  Error: {e}")

    total = len(tests)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed}/{total} failed")
    print(f"{'='*60}")
    return passed, failed

if __name__ == "__main__":
    setup()
    passed, failed = asyncio.run(run())
    sys.exit(1 if failed > 0 else 0)
