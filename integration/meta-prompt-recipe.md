# DeepRoute Integration Recipe for Meta-Prompt

This recipe is for the meta-prompt `/customize-manage` command (or manual setup).
It describes how to install DeepRoute into an existing meta-prompt customization environment.

## Prerequisites

- `uv` installed
- `git` installed
- Claude Code with meta-prompt customizations already running

## Installation Steps

### 1. Clone and install

```bash
DEEPROUTE_DIR="$HOME/.claude/mcps/deeproute"
if [ ! -d "$DEEPROUTE_DIR" ]; then
  # SSH (collaborators) or HTTPS (public/PAT)
  git clone git@github.com:cutr00t/deeproute.git "$DEEPROUTE_DIR" 2>/dev/null \
    || git clone https://github.com/cutr00t/deeproute.git "$DEEPROUTE_DIR"
fi
cd "$DEEPROUTE_DIR" && uv sync
```

### 2. Register MCP server

Add to `~/.claude/settings.json` under `mcpServers` (merge, don't overwrite):

```json
"deeproute": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--directory", "$HOME/.claude/mcps/deeproute", "python", "-m", "deeproute"],
  "env": {}
}
```

### 3. Install DeepRoute skills

```bash
cd "$HOME/.claude/mcps/deeproute"
uv run python -c "from deeproute.skills_installer import install_skills; install_skills(force=True)"
```

This installs three skills to `~/.claude/skills/`:
- `deeproute__nav` — progressive disclosure navigation
- `deeproute__update` — post-change refresh reminders
- `deeproute__help` — interactive help and troubleshooting

### 4. Update `/help-agent` command

Add DeepRoute to the available tools section:

```
## DeepRoute MCP Tools (codebase routing)
dr_init     — scan and generate routing docs for a repo
dr_update   — incremental refresh after code changes
dr_query    — ask codebase questions using routing context
dr_status   — health check and integration status
```

Add workflow examples:

```
WORKFLOW: Understand a new codebase
1. dr_init path="/path/to/repo"    — generate routing docs
2. Read .deeproute/ROUTER.md       — get oriented
3. /analyze                        — deep analysis with routing context
4. dr_query "how does auth work?"  — targeted questions
```

### 5. Update code-related commands

For any command that analyzes or navigates code (`/analyze`, `/impl`, `/plan`, etc.),
add this section:

```
## DeepRoute Integration
If the current repo has a `.deeproute/` directory, read `.deeproute/ROUTER.md` first
for fast project orientation before diving into source files. This saves tokens and
provides better-structured context than scanning the file tree directly.
```

### 6. Update CUSTOMIZATIONS.md

Add DeepRoute to the MCP servers section with its tool listing.

## Post-Install

After restarting Claude Code:

1. Initialize your primary repos:
   ```
   dr_init path="/path/to/your/repo"
   ```

2. Verify integration:
   ```
   dr_status
   ```
   Should show `integrations.meta_prompt.installed: true`

## How They Work Together

- **Meta-prompt commands** read `.deeproute/ROUTER.md` for fast codebase orientation
- **DeepRoute skills** trigger automatically alongside meta-prompt commands
- **`/help-agent`** recommends DeepRoute tools for navigation questions
- **`dr_status`** reports whether meta-prompt is installed
- **`/customize-manage`** can modify DeepRoute config or add new repos
