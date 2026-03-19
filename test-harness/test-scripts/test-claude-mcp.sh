#!/usr/bin/env bash
# Test DeepRoute MCP tools via non-interactive claude CLI.
# Requires ANTHROPIC_API_KEY and claude CLI installed.
set -euo pipefail

echo "=== Testing DeepRoute via Claude CLI (non-interactive) ==="

# Setup demo repos
bash "$(dirname "$0")/setup-demo-repos.sh"

DEMO="/tmp/demo-workspace"
PASS=0
FAIL=0

run_test() {
    local name="$1"
    local prompt="$2"
    echo ""
    echo "--- $name ---"
    if output=$(claude --print --no-input "$prompt" 2>&1); then
        echo "  PASS (${#output} chars)"
        echo "  Preview: $(echo "$output" | head -3 | tr '\n' ' ')"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $output"
        FAIL=$((FAIL + 1))
    fi
}

# Test 1: Use dr_status to verify MCP is connected
run_test "dr_status via MCP" \
    "Use the dr_status MCP tool and show me the result. Just the raw output, no commentary."

# Test 2: Init a repo
run_test "dr_init on notes-api" \
    "Use the dr_init MCP tool with path='$DEMO/notes-api'. Show the result."

# Test 3: Query
run_test "dr_query about notes-api" \
    "Use the dr_query MCP tool with question='What is the structure of the notes API?' and path='$DEMO/notes-api'. Show the answer."

# Test 4: Status after init
run_test "dr_status after init" \
    "Use the dr_status MCP tool with path='$DEMO/notes-api'. Show the health status."

echo ""
echo "========================================"
echo "Results: $PASS passed, $FAIL failed"
echo "========================================"

[ "$FAIL" -eq 0 ] || exit 1
