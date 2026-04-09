"""DeepAgent — LLM-powered analysis for repo routing generation.

Uses the Anthropic SDK (AsyncAnthropic or AsyncAnthropicVertex) via
llm_client for backend-aware client creation. Supports both v1 (freeform
markdown) and v2 (structured JSON schema) output.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .llm_client import get_client, get_model_fallbacks, model_display_name, resolve_model
from .models import (
    FileChange,
    LayerDoc,
    RepoInventory,
    RoutingSystem,
    SkillDoc,
)

logger = logging.getLogger(__name__)

# --- Prompt templates (v1 markdown) ---

ROUTER_TEMPLATE = """\
# Project Router — {project_name}

## Identity
{{1-2 sentence project description}}

## Tech Stack
{{Languages, frameworks, key dependencies — bullet list}}

## Directory Map
{{Tree-style layout, 2 levels deep max}}

## Routing Table

| Domain / Task Type | Context Layer | Key Paths | Skip Paths | Skills |
|--------------------|---------------|-----------|------------|--------|
| ... | layers/....md | ... | ... | — |

## Conventions
{{Coding standards, branch strategy, PR process — brief}}
"""

LAYER_TEMPLATE = """\
# {subsystem_name}

## Purpose
{{What this subsystem does, 2-3 sentences}}

## Architecture
{{Key patterns, data flow, dependencies}}

## Key Files
| File / Dir | Role |
|------------|------|
| ... | ... |

## Conventions
{{Subsystem-specific patterns, naming, error handling}}

## Common Tasks
{{Brief recipes: "to add a new endpoint, …", "to modify the schema, …"}}
"""

FULL_SCAN_PROMPT = """\
You are analyzing a software repository to create a multi-layer markdown routing system.

Given the following repository inventory:
{inventory_json}

Generate a JSON response with:
1. "router_md": A ROUTER.md following this template:
{router_template}

2. "layers": An array of objects, each with "name", "filename", "content".
   Each layer provides subsystem-specific depth following this template:
{layer_template}

3. "skills": An array of objects, each with "name", "directory", "content" (optional, only if common workflows are apparent).

Rules:
- ROUTER.md must be concise — it's a routing index, not documentation.
- Layer files should have enough detail to orient an AI coding agent.
- Routing table entries must have non-overlapping scopes.
- Prefer fewer, well-scoped layers over many thin ones (3-7 layers is ideal).
- Include a "Common Tasks" section in each layer with 2-3 recipes.
- Respond ONLY with valid JSON matching the structure above. No markdown fences.
"""

UPDATE_PROMPT = """\
You are updating a markdown routing layer document based on recent code changes.

Current layer document:
{current_layer_md}

Git changes since last update:
{diff_summary}

Commit messages:
{commit_messages}

Update the layer document to reflect these changes. Preserve existing structure.
Only modify sections affected by the changes. If the changes don't affect this
layer, return it unchanged.

Respond with ONLY the updated markdown content, no JSON wrapping or fences.
"""

QUERY_PROMPT = """\
You are a code navigation assistant using a multi-layer markdown routing system.

Router document:
{router_md}

{layer_context}

User question: {question}

Provide a clear, actionable answer with specific file references where relevant.
If you need information from files not included in the context, mention which files
would need to be consulted.
"""


# --- V2 structured schema prompt ---

V2_INIT_PROMPT = """\
You are analyzing a software repository to create a structured JSON schema for code navigation.

Repository inventory:
{inventory_json}

Generate a JSON response with these exact top-level keys:

1. "manifest": {{
     "project_name": "<name>",
     "description": "<1-2 sentence description>",
     "tech_stack": [{{"category": "<language|framework|database|infra|ci|tool>", "name": "<name>", "version": "<version or empty>"}}],
     "modules": [{{"name": "<path>", "summary": "<1 sentence>", "tags": ["<tag>"], "primary_language": "<lang>", "file_count": <n>}}],
     "conventions": ["<brief coding standard>"],
     "tree_summary": "<2-level directory tree>"
   }}

2. "modules": {{
     "<module_path>": {{
       "name": "<module_path>",
       "path": "<directory path>",
       "summary": "<1 sentence>",
       "purpose": "<2-3 sentences>",
       "tags": ["<tag>"],
       "files": [{{"path": "<relative path>", "role": "<brief role>", "tags": ["<tag>"], "functions": ["<fn_name>"], "classes": ["<class_name>"]}}],
       "functions": [{{
         "name": "<fn_name>", "file": "<path>", "line": <n>,
         "params": [{{"name": "<name>", "type": "<type>", "description": "<brief>"}}],
         "return_type": "<type>", "description": "<1 sentence>",
         "tags": ["<tag>"], "is_public": true
       }}],
       "classes": [{{
         "name": "<class_name>", "file": "<path>", "line": <n>,
         "description": "<1 sentence>", "bases": ["<base>"],
         "key_methods": [<same as function spec>],
         "tags": ["<tag>"]
       }}],
       "dependencies": [{{"module": "<other module>", "relationship": "<imports|calls|extends>", "description": "<brief>"}}],
       "common_tasks": [{{"task": "<what>", "steps": "<how>"}}]
     }}
   }}

3. "interfaces": {{
     "http_endpoints": [{{"method": "<GET|POST|...>", "path": "<url>", "handler": "<file:function>", "description": "<brief>", "request_body": "<brief schema>", "response": "<brief schema>", "tags": ["<tag>"]}}],
     "grpc_services": [],
     "event_handlers": [{{"event": "<event_name>", "handler": "<file:function>", "source": "<pubsub|celery|kafka>", "description": "<brief>"}}],
     "cli_commands": []
   }}

4. "config_files": {{
     "files": [{{"file": "<path>", "type": "<dockerfile|docker-compose|ci|terraform|pyproject>", "summary": "<1 sentence>"}}],
     "docker_stages": [{{"name": "<stage>", "base_image": "<image>", "purpose": "<brief>"}}],
     "compose_services": [{{"name": "<svc>", "image": "<img>", "ports": ["<port>"], "depends_on": ["<dep>"], "purpose": "<brief>"}}],
     "ci_pipelines": [{{"name": "<step>", "trigger": "<when>", "actions": ["<action>"]}}]
   }}

5. "patterns": {{
     "patterns": [{{"name": "<pattern name>", "category": "<architectural|structural|behavioral>", "locations": ["<file paths>"], "description": "<brief>", "tags": ["<tag>"]}}]
   }}

6. "notes": {{
     "<module_path>": "<optional freeform markdown with deeper architectural context, design decisions, or explanations that don't fit the structured schema>"
   }}

Rules:
- Be thorough on function/class specs — include ALL public functions and classes
- Tags should enable cross-cutting search (e.g., "auth" on auth-related items across ALL modules)
- Keep descriptions concise (1 sentence for functions, 2-3 for modules)
- File paths must be relative to repo root
- For functions: include accurate parameter types and return types where detectable
- For config files: extract the most operationally useful information
- Respond with valid JSON only. No markdown fences.
"""

V2_UPDATE_PROMPT = """\
You are updating a structured JSON schema for a code module based on recent changes.

Current module schema:
{current_schema_json}

Git changes since last update:
{diff_summary}

Commit messages:
{commit_messages}

Update the module schema to reflect these changes. Rules:
- Add new files/functions/classes that were added
- Remove entries for deleted files/functions/classes
- Update descriptions and tags if behavior changed
- Preserve unchanged entries exactly
- Respond with valid JSON only matching the original structure. No markdown fences.
"""


def _extract_json(raw: str) -> dict:
    """Robustly extract JSON from LLM response, handling fences and trailing content."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if "```" in raw:
            raw = raw[:raw.rfind("```")]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in response: {raw[:200]}")
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(raw[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:i + 1])
    end = raw.rfind("}")
    if end > start:
        return json.loads(raw[start:end + 1])
    raise ValueError(f"Could not parse JSON from response: {raw[:200]}")


def _truncate_inventory(inventory: RepoInventory, max_files: int = 200) -> dict:
    """Produce a trimmed inventory dict suitable for LLM context."""
    d = inventory.model_dump()
    if len(d["files"]) > max_files:
        d["files"] = d["files"][:max_files]
        d["_note"] = f"Truncated to {max_files} of {inventory.total_files} files"
    for k, v in list(d["key_files"].items()):
        if len(v) > 3000:
            d["key_files"][k] = v[:3000] + "\n... (truncated)"
    return d


# --- LLM call wrapper ---

async def _call_llm(prompt: str, model: str, system: str = "", max_tokens: int = 8192) -> str:
    """Make an LLM call with model alias resolution and 404 fallback.

    Accepts aliases ("opus", "sonnet", "haiku") or full model IDs.
    On model 404, tries fallback candidates before giving up.
    """
    client = get_client()
    candidates = get_model_fallbacks(resolve_model(model))

    messages = [{"role": "user", "content": prompt}]

    last_error = None
    for candidate in candidates:
        kwargs: dict[str, Any] = {
            "model": candidate,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        try:
            response = await client.messages.create(**kwargs)
            if candidate != candidates[0]:
                logger.info(f"Model fallback: {candidates[0]} → {candidate}")
            return response.content[0].text
        except Exception as e:
            error_str = str(e)
            if "404" in error_str or "not_found" in error_str:
                logger.warning(f"Model {candidate} not available, trying next fallback")
                last_error = e
                continue
            raise  # Non-404 errors propagate immediately

    # All candidates failed
    tried = ", ".join(candidates)
    raise type(last_error)(
        f"No available model found. Tried: {tried}. "
        f"Check your config (dr_config key='model') or set a model "
        f"available on your current backend. Last error: {last_error}"
    ) from last_error


# --- V1 (markdown) analysis ---

async def analyze_repo(
    inventory: RepoInventory,
    model: str = "sonnet",
) -> RoutingSystem:
    """Analyze a repo and produce a v1 markdown routing system."""
    inv_dict = _truncate_inventory(inventory)
    prompt = FULL_SCAN_PROMPT.format(
        inventory_json=json.dumps(inv_dict, indent=2, default=str),
        router_template=ROUTER_TEMPLATE.format(project_name=inventory.name),
        layer_template=LAYER_TEMPLATE.format(subsystem_name="{subsystem}"),
    )
    raw = await _call_llm(
        prompt, model,
        system="You are a code analysis expert. Respond with valid JSON only."
    )
    data = _extract_json(raw)
    layers = [
        LayerDoc(name=l["name"], filename=l["filename"], content=l["content"])
        for l in data.get("layers", [])
    ]
    skills = [
        SkillDoc(name=s["name"], directory=s["directory"], content=s["content"])
        for s in data.get("skills", [])
    ]
    return RoutingSystem(
        router_md=data["router_md"],
        layers=layers,
        skills=skills,
    )


# --- V2 (structured schema) analysis ---

async def analyze_repo_v2(
    inventory: RepoInventory,
    model: str = "sonnet",
) -> dict:
    """Analyze a repo and produce a v2 structured schema (dict).

    Returns the raw parsed JSON dict with keys:
    manifest, modules, interfaces, config_files, patterns, notes
    """
    inv_dict = _truncate_inventory(inventory, max_files=300)
    prompt = V2_INIT_PROMPT.format(
        inventory_json=json.dumps(inv_dict, indent=2, default=str),
    )
    raw = await _call_llm(
        prompt, model,
        system="You are a thorough code analysis expert. Respond with valid JSON only.",
        max_tokens=16384,
    )
    return _extract_json(raw)


async def update_module_v2(
    current_schema: dict,
    changes: list[FileChange],
    commits: list[dict[str, str]],
    model: str = "sonnet",
) -> dict:
    """Update a single v2 module schema based on changes."""
    diff_summary = "\n".join(f"  {c.status.value} {c.path}" for c in changes)
    commit_msgs = "\n".join(f"  {c.get('sha', '')}: {c.get('message', '')}" for c in commits)
    prompt = V2_UPDATE_PROMPT.format(
        current_schema_json=json.dumps(current_schema, indent=2),
        diff_summary=diff_summary,
        commit_messages=commit_msgs,
    )
    raw = await _call_llm(prompt, model)
    return _extract_json(raw)


# --- V1 update + query (unchanged behavior) ---

async def update_layer(
    current_md: str,
    changes: list[FileChange],
    commits: list[dict[str, str]],
    model: str = "sonnet",
) -> str:
    """Update a v1 layer document based on changes."""
    diff_summary = "\n".join(f"  {c.status.value} {c.path}" for c in changes)
    commit_msgs = "\n".join(f"  {c.get('sha', '')}: {c.get('message', '')}" for c in commits)
    prompt = UPDATE_PROMPT.format(
        current_layer_md=current_md,
        diff_summary=diff_summary,
        commit_messages=commit_msgs,
    )
    return await _call_llm(prompt, model)


async def query(
    question: str,
    router_md: str,
    layer_contents: dict[str, str],
    model: str = "sonnet",
) -> str:
    """Answer a question using the v1 routing system."""
    layer_ctx = ""
    for name, content in layer_contents.items():
        layer_ctx += f"\n--- Layer: {name} ---\n{content}\n"
    if not layer_ctx:
        layer_ctx = "(No additional layers loaded)"
    prompt = QUERY_PROMPT.format(
        router_md=router_md,
        layer_context=layer_ctx,
        question=question,
    )
    return await _call_llm(prompt, model)
