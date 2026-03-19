#!/usr/bin/env bash
# Run DeepRoute + meta-prompt integration tests in Docker.
# Bind-mounts both repos (private, no clone) and runs test suite.
#
# Usage:
#   ./run.sh              # run all tests
#   ./run.sh shell         # drop into shell for manual testing
#   ./run.sh python        # run Python-only tests (no claude CLI needed)
#   ./run.sh mcp           # run MCP tests via claude CLI (uses API key)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEEPROUTE_DIR="$(dirname "$SCRIPT_DIR")"
META_PROMPT_DIR="$(dirname "$DEEPROUTE_DIR")/meta-prompt-claude-code-extension"

# --- API key ---
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
if [ -z "$ANTHROPIC_API_KEY" ]; then
    for keyfile in ~/sec/anthropic_key ~/sec/anthropic_api_key ~/.anthropic/api_key; do
        if [ -f "$keyfile" ]; then
            ANTHROPIC_API_KEY="$(cat "$keyfile")"
            break
        fi
    done
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "Warning: No ANTHROPIC_API_KEY found. Python tests will fail on LLM calls."
    echo "Set ANTHROPIC_API_KEY or place key in ~/sec/anthropic_key"
fi

# --- Build image ---
IMAGE_NAME="deeproute-test"
echo "Building test image..."
docker build -t "$IMAGE_NAME" "$SCRIPT_DIR" 2>&1 | tail -3

# --- Common volumes ---
VOLUMES=(
    -v "$DEEPROUTE_DIR:/opt/deeproute:ro"
    -v "$SCRIPT_DIR/test-scripts:/opt/tests"
)
if [ -d "$META_PROMPT_DIR" ]; then
    VOLUMES+=(-v "$META_PROMPT_DIR:/opt/meta-prompt:ro")
fi

ENV_ARGS=()
if [ -n "$ANTHROPIC_API_KEY" ]; then
    ENV_ARGS+=(-e "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
fi

MODE="${1:-all}"

case "$MODE" in
    shell)
        echo "Dropping into test container shell..."
        echo "  DeepRoute: /opt/deeproute"
        echo "  Meta-prompt: /opt/meta-prompt"
        echo "  Tests: /opt/tests"
        exec docker run -it --rm "${VOLUMES[@]}" "${ENV_ARGS[@]}" "$IMAGE_NAME"
        ;;
    python)
        echo "Running Python-only tests..."
        docker run --rm "${VOLUMES[@]}" "${ENV_ARGS[@]}" "$IMAGE_NAME" -c "
            cd /opt/deeproute && uv sync --quiet 2>/dev/null
            uv run --directory /opt/deeproute python /opt/tests/test-deeproute.py
        "
        ;;
    mcp)
        echo "Running MCP tests via claude CLI..."
        docker run --rm "${VOLUMES[@]}" "${ENV_ARGS[@]}" "$IMAGE_NAME" -c "
            cd /opt/deeproute && uv sync --quiet 2>/dev/null
            # Register DeepRoute MCP
            echo '{\"mcpServers\":{\"deeproute\":{\"type\":\"stdio\",\"command\":\"uv\",\"args\":[\"run\",\"--directory\",\"/opt/deeproute\",\"python\",\"-m\",\"deeproute\"],\"env\":{}}}}' > /root/.claude/settings.json
            # Install skills
            uv run --directory /opt/deeproute python -c 'from deeproute.skills_installer import install_skills; install_skills(force=True)'
            # Copy meta-prompt bootstrap if available
            [ -f /opt/meta-prompt/bootstrap/customize.md ] && cp /opt/meta-prompt/bootstrap/customize.md /root/.claude/commands/customize.md || true
            bash /opt/tests/test-claude-mcp.sh
        "
        ;;
    all)
        echo "Running full test suite..."
        docker run --rm "${VOLUMES[@]}" "${ENV_ARGS[@]}" "$IMAGE_NAME" -c "
            cd /opt/deeproute && uv sync --quiet 2>/dev/null
            echo ''
            echo '=========================================='
            echo ' Phase 1: Python API tests (DeepRoute)'
            echo '=========================================='
            uv run --directory /opt/deeproute python /opt/tests/test-deeproute.py

            echo ''
            echo '=========================================='
            echo ' Phase 2: Integration status'
            echo '=========================================='
            # Install skills + meta-prompt
            uv run --directory /opt/deeproute python -c 'from deeproute.skills_installer import install_skills; install_skills(force=True)'
            [ -f /opt/meta-prompt/bootstrap/customize.md ] && cp /opt/meta-prompt/bootstrap/customize.md /root/.claude/commands/customize.md || true
            uv run --directory /opt/deeproute python -c '
from deeproute.integrations import integration_status
import json
status = integration_status()
print(json.dumps(status, indent=2))
'
        "
        ;;
esac
