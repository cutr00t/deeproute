"""DeepAgent — LLM-powered analysis for repo routing generation.

Supports two backends:
  - "direct": Anthropic SDK calls (simpler, fewer deps)
  - "langgraph": LangGraph StateGraph with planner/generator/reviewer
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from .models import (
    FileChange,
    LayerDoc,
    RepoInventory,
    RoutingSystem,
    SkillDoc,
)

logger = logging.getLogger(__name__)

# --- Prompt templates ---

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


def _extract_json(raw: str) -> dict:
    """Robustly extract JSON from LLM response, handling fences and trailing content."""
    raw = raw.strip()
    # Strip markdown fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if "```" in raw:
            raw = raw[:raw.rfind("```")]
        raw = raw.strip()
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try to find the outermost JSON object
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
    # Last resort: take everything from first { to last }
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
    # Truncate key file contents to avoid blowing context
    for k, v in list(d["key_files"].items()):
        if len(v) > 3000:
            d["key_files"][k] = v[:3000] + "\n... (truncated)"
    return d


# --- Direct backend (Anthropic SDK) ---

async def _call_anthropic(prompt: str, model: str, system: str = "") -> str:
    """Make a direct Anthropic API call."""
    import anthropic
    client = anthropic.AsyncAnthropic()
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": 8192,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return response.content[0].text


async def analyze_repo_direct(inventory: RepoInventory, model: str) -> RoutingSystem:
    """Analyze a repo using direct Anthropic API calls."""
    inv_dict = _truncate_inventory(inventory)
    prompt = FULL_SCAN_PROMPT.format(
        inventory_json=json.dumps(inv_dict, indent=2, default=str),
        router_template=ROUTER_TEMPLATE.format(project_name=inventory.name),
        layer_template=LAYER_TEMPLATE.format(subsystem_name="{subsystem}"),
    )
    raw = await _call_anthropic(
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


async def update_layer_direct(
    current_md: str,
    changes: list[FileChange],
    commits: list[dict[str, str]],
    model: str,
) -> str:
    """Update a single layer using direct Anthropic API call."""
    diff_summary = "\n".join(f"  {c.status.value} {c.path}" for c in changes)
    commit_msgs = "\n".join(f"  {c.get('sha', '')}: {c.get('message', '')}" for c in commits)
    prompt = UPDATE_PROMPT.format(
        current_layer_md=current_md,
        diff_summary=diff_summary,
        commit_messages=commit_msgs,
    )
    return await _call_anthropic(prompt, model)


async def query_direct(
    question: str,
    router_md: str,
    layer_contents: dict[str, str],
    model: str,
) -> str:
    """Answer a query using the routing system as context."""
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
    return await _call_anthropic(prompt, model)


# --- LangGraph backend ---

class AgentState(TypedDict, total=False):
    inventory: dict
    router_md: str
    layers: list[dict]
    skills: list[dict]
    review_notes: str
    model: str
    final: bool


async def _planner_node(state: AgentState) -> AgentState:
    """Plan which layers to generate based on repo inventory."""
    inv = state["inventory"]
    model = state.get("model", "claude-sonnet-4-20250514")
    prompt = (
        "Given this repo inventory, list the layer documents needed.\n"
        "Respond as JSON: {\"layers\": [{\"name\": ..., \"filename\": ...}]}\n\n"
        f"{json.dumps(inv, indent=2, default=str)}"
    )
    raw = await _call_anthropic(prompt, model, system="You are a code architect. JSON only.")
    data = _extract_json(raw)
    state["layers"] = [{"name": l["name"], "filename": l["filename"], "content": ""} for l in data.get("layers", [])]
    return state


async def _generator_node(state: AgentState) -> AgentState:
    """Generate router + layer content."""
    inv = state["inventory"]
    model = state.get("model", "claude-sonnet-4-20250514")
    layers_plan = state.get("layers", [])
    prompt = FULL_SCAN_PROMPT.format(
        inventory_json=json.dumps(inv, indent=2, default=str),
        router_template=ROUTER_TEMPLATE.format(project_name=inv.get("name", "project")),
        layer_template=LAYER_TEMPLATE.format(subsystem_name="{subsystem}"),
    )
    if layers_plan:
        prompt += f"\n\nPlanned layers: {json.dumps(layers_plan)}"
    raw = await _call_anthropic(prompt, model, system="You are a code analysis expert. Respond with valid JSON only.")
    data = _extract_json(raw)
    state["router_md"] = data.get("router_md", "")
    state["layers"] = data.get("layers", [])
    state["skills"] = data.get("skills", [])
    return state


async def _reviewer_node(state: AgentState) -> AgentState:
    """Review generated content for coherence."""
    model = state.get("model", "claude-sonnet-4-20250514")
    prompt = (
        "Review this routing system for coherence. Check:\n"
        "1. Router table references match layer filenames\n"
        "2. Key paths don't overlap between layers\n"
        "3. Content is concise and actionable\n\n"
        f"Router:\n{state.get('router_md', '')}\n\n"
        f"Layers: {json.dumps(state.get('layers', []), indent=2)}\n\n"
        "If everything is coherent, respond: {\"ok\": true}\n"
        "If issues found, respond: {\"ok\": false, \"notes\": \"...\"}"
    )
    raw = await _call_anthropic(prompt, model, system="You are a technical reviewer. JSON only.")
    data = _extract_json(raw)
    state["review_notes"] = data.get("notes", "")
    state["final"] = data.get("ok", True)
    return state


async def analyze_repo_langgraph(inventory: RepoInventory, model: str) -> RoutingSystem:
    """Analyze a repo using LangGraph StateGraph."""
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        logger.warning("langgraph not available, falling back to direct")
        return await analyze_repo_direct(inventory, model)

    inv_dict = _truncate_inventory(inventory)

    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner_node)
    graph.add_node("generator", _generator_node)
    graph.add_node("reviewer", _reviewer_node)
    graph.set_entry_point("planner")
    graph.add_edge("planner", "generator")
    graph.add_edge("generator", "reviewer")
    graph.add_edge("reviewer", END)
    app = graph.compile()

    initial_state: AgentState = {
        "inventory": inv_dict,
        "model": model,
    }
    result = await app.ainvoke(initial_state)

    layers = [
        LayerDoc(name=l["name"], filename=l["filename"], content=l["content"])
        for l in result.get("layers", [])
    ]
    skills = [
        SkillDoc(name=s["name"], directory=s["directory"], content=s["content"])
        for s in result.get("skills", [])
    ]
    return RoutingSystem(
        router_md=result.get("router_md", ""),
        layers=layers,
        skills=skills,
    )


# --- Public API ---

async def analyze_repo(
    inventory: RepoInventory,
    model: str = "claude-sonnet-4-20250514",
    backend: str = "direct",
) -> RoutingSystem:
    """Analyze a repo and produce a routing system."""
    if backend == "langgraph":
        return await analyze_repo_langgraph(inventory, model)
    return await analyze_repo_direct(inventory, model)


async def update_layer(
    current_md: str,
    changes: list[FileChange],
    commits: list[dict[str, str]],
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """Update a layer document based on changes."""
    return await update_layer_direct(current_md, changes, commits, model)


async def query(
    question: str,
    router_md: str,
    layer_contents: dict[str, str],
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """Answer a question using the routing system."""
    return await query_direct(question, router_md, layer_contents, model)
