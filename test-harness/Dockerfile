FROM python:3.13-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl nodejs npm jq \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code@latest 2>/dev/null || true

# Git config for test repos
RUN git config --global user.name "test" && \
    git config --global user.email "test@test.com" && \
    git config --global init.defaultBranch main

# Setup directories
RUN mkdir -p /root/.claude/commands /root/.claude/agents /root/.claude/skills /root/.claude/mcps

# Both repos are bind-mounted at runtime (private repos, no clone needed):
#   -v /path/to/deeproute:/opt/deeproute
#   -v /path/to/meta-prompt-claude-code-extension:/opt/meta-prompt

# Pre-create the work directory
RUN mkdir -p /opt/deeproute /opt/meta-prompt /opt/tests

WORKDIR /opt/tests
ENTRYPOINT ["bash"]
