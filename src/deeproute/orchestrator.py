"""Recursive agent orchestration — multi-model analysis with complexity-driven dispatch.

Phase 3 core: orchestrates per-module LLM calls with model hints from
complexity scoring, then synthesizes results into a unified analysis.

Levels:
  1. Flat dispatch: one LLM call per module with schema context (always)
  2. Sub-component drill: break complex modules into file clusters (if depth > 1)
  3. Synthesis: combine per-module results into workspace-level answer

Token tracking is integrated — every LLM call goes through _call_llm
which records usage in the session tracker.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .deepagent import _call_llm, token_tracker
from .schema import ModuleSchema

logger = logging.getLogger(__name__)


@dataclass
class ModuleAnalysis:
    """Result of analyzing a single module."""
    module: str
    model_used: str
    analysis: str
    key_findings: list[str] = field(default_factory=list)
    complexity_score: int = 0
    tokens_used: int = 0
    sub_analyses: list[ModuleAnalysis] = field(default_factory=list)


@dataclass
class OrchestrationResult:
    """Full orchestration result with per-module breakdowns."""
    question: str
    synthesis: str
    module_analyses: list[ModuleAnalysis] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0
    models_used: dict[str, int] = field(default_factory=dict)  # model → call count
    elapsed_ms: int = 0
    depth_reached: int = 1


# --- Prompt templates ---

MODULE_ANALYSIS_PROMPT = """\
You are analyzing a specific module of a codebase to answer a question.

## Question
{question}

## Module: {module_name}
{module_context}

## Instructions
Analyze this module in the context of the question. Be specific and reference
actual function names, classes, and file paths from the schema above.

Respond with JSON:
{{
  "analysis": "your detailed analysis (2-4 paragraphs)",
  "key_findings": ["finding 1", "finding 2", ...],
  "relevant_code": ["file:function_or_class", ...]
}}
"""

SUBCOMPONENT_PROMPT = """\
You are doing a focused analysis of specific files within a module.

## Question
{question}

## Module: {module_name}
## Focus: {subcomponent}

### Files in this subcomponent:
{file_details}

## Instructions
Analyze these specific files in detail. Reference actual function names and
line numbers. Be precise about what the code does.

Respond with JSON:
{{
  "analysis": "focused analysis (1-2 paragraphs)",
  "key_findings": ["finding 1", ...]
}}
"""

SYNTHESIS_PROMPT = """\
You are synthesizing the results of a multi-module codebase analysis.

## Original Question
{question}

## Per-Module Analyses
{module_results}

## Instructions
Synthesize these per-module analyses into a unified, coherent answer to the
original question. Identify cross-cutting themes, contradictions, and the
overall picture. Reference specific modules and functions where relevant.

Provide a clear, well-structured answer (3-6 paragraphs).
"""


def _build_module_context(mod: ModuleSchema) -> str:
    """Build a compact context string from a module schema."""
    parts = [f"**Path**: {mod.path}"]

    if mod.summary:
        parts.append(f"**Summary**: {mod.summary}")
    if mod.purpose:
        parts.append(f"**Purpose**: {mod.purpose}")

    # Complexity info
    if mod.complexity.score > 0:
        factors = ", ".join(mod.complexity.factors) if mod.complexity.factors else "N/A"
        parts.append(f"**Complexity**: {mod.complexity.score}/10 ({factors})")

    # Files with roles
    if mod.files:
        file_lines = []
        for f in mod.files[:20]:  # Cap at 20 files
            role = f" — {f.role}" if f.role else ""
            fns = f" [{', '.join(f.functions[:5])}]" if f.functions else ""
            file_lines.append(f"  - `{f.path}`{role}{fns}")
        parts.append("**Files**:\n" + "\n".join(file_lines))

    # Key functions (public only, capped)
    public_fns = [fn for fn in mod.functions if fn.is_public][:15]
    if public_fns:
        fn_lines = []
        for fn in public_fns:
            params = ", ".join(f"{p.name}: {p.type}" for p in fn.params if p.type)
            sig = f"({params})" if params else "()"
            ret = f" → {fn.return_type}" if fn.return_type else ""
            desc = f" — {fn.description}" if fn.description else ""
            async_tag = "async " if fn.is_async else ""
            fn_lines.append(f"  - `{async_tag}{fn.name}{sig}{ret}`{desc}")
        parts.append("**Functions**:\n" + "\n".join(fn_lines))

    # Key classes (capped)
    if mod.classes[:10]:
        cls_lines = []
        for cls in mod.classes[:10]:
            bases = f"({', '.join(cls.bases)})" if cls.bases else ""
            desc = f" — {cls.description}" if cls.description else ""
            methods = ", ".join(m.name for m in cls.key_methods[:5])
            method_str = f" [{methods}]" if methods else ""
            cls_lines.append(f"  - `{cls.name}{bases}`{desc}{method_str}")
        parts.append("**Classes**:\n" + "\n".join(cls_lines))

    # Tags
    if mod.tags:
        parts.append(f"**Tags**: {', '.join(mod.tags)}")

    return "\n\n".join(parts)


def _group_files_by_cluster(mod: ModuleSchema, max_clusters: int = 4) -> list[dict]:
    """Group a module's files into logical clusters for sub-component analysis.

    Clusters by directory prefix, then by semantic proximity if too many groups.
    """
    from collections import defaultdict

    dir_groups: dict[str, list] = defaultdict(list)
    for f in mod.files:
        parts = Path(f.path).parts
        # Group by first 2 directory levels within the module
        if len(parts) > 2:
            key = "/".join(parts[:2])
        elif len(parts) > 1:
            key = parts[0]
        else:
            key = "(root)"
        dir_groups[key].append(f)

    clusters = []
    for group_name, files in sorted(dir_groups.items()):
        fn_names = []
        cls_names = []
        for f in files:
            fn_names.extend(f.functions)
            cls_names.extend(f.classes)
        clusters.append({
            "name": group_name,
            "files": files,
            "functions": fn_names,
            "classes": cls_names,
        })

    # If too many clusters, merge the smallest ones
    while len(clusters) > max_clusters:
        clusters.sort(key=lambda c: len(c["files"]))
        smallest = clusters.pop(0)
        clusters[0]["files"].extend(smallest["files"])
        clusters[0]["functions"].extend(smallest["functions"])
        clusters[0]["classes"].extend(smallest["classes"])
        clusters[0]["name"] = f"{clusters[0]['name']}+{smallest['name']}"

    return clusters


def _extract_json_safe(raw: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Skip first and last lines (fences)
        inner = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = inner.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return {"analysis": raw, "key_findings": []}


async def analyze_module(
    mod: ModuleSchema,
    question: str,
    model: str = "sonnet",
    depth: int = 1,
    sub_model: str = "haiku",
) -> ModuleAnalysis:
    """Analyze a single module, optionally breaking into sub-components.

    Args:
        mod: Module schema with functions, classes, files.
        question: The question to analyze against.
        model: Model to use for this module's analysis.
        depth: If > 1, break complex modules into sub-component analyses.
        sub_model: Model to use for sub-component analyses.
    """
    context = _build_module_context(mod)
    tokens_before = token_tracker.total_tokens

    # Level 1: Module-level analysis
    prompt = MODULE_ANALYSIS_PROMPT.format(
        question=question,
        module_name=mod.name,
        module_context=context,
    )
    raw = await _call_llm(
        prompt, model,
        system="You are a code analysis expert. Respond with valid JSON only.",
        max_tokens=4096,
    )
    data = _extract_json_safe(raw)

    result = ModuleAnalysis(
        module=mod.name,
        model_used=model,
        analysis=data.get("analysis", raw),
        key_findings=data.get("key_findings", []),
        complexity_score=mod.complexity.score,
    )

    # Level 2: Sub-component drill-down for complex modules
    if depth > 1 and mod.complexity.score >= 6 and len(mod.files) > 5:
        clusters = _group_files_by_cluster(mod)
        for cluster in clusters:
            if not cluster["functions"] and not cluster["classes"]:
                continue

            file_details = []
            for f in cluster["files"][:10]:
                fns = ", ".join(f.functions[:8]) if f.functions else "none"
                cls = ", ".join(f.classes[:5]) if f.classes else "none"
                file_details.append(f"- `{f.path}`: functions=[{fns}] classes=[{cls}]")

            sub_prompt = SUBCOMPONENT_PROMPT.format(
                question=question,
                module_name=mod.name,
                subcomponent=cluster["name"],
                file_details="\n".join(file_details),
            )
            sub_raw = await _call_llm(
                sub_prompt, sub_model,
                system="You are a code analysis expert. Respond with valid JSON only.",
                max_tokens=2048,
            )
            sub_data = _extract_json_safe(sub_raw)
            result.sub_analyses.append(ModuleAnalysis(
                module=f"{mod.name}/{cluster['name']}",
                model_used=sub_model,
                analysis=sub_data.get("analysis", sub_raw),
                key_findings=sub_data.get("key_findings", []),
            ))

    result.tokens_used = token_tracker.total_tokens - tokens_before
    return result


async def synthesize(
    question: str,
    module_analyses: list[ModuleAnalysis],
    model: str = "sonnet",
) -> str:
    """Synthesize per-module analyses into a unified answer."""
    if len(module_analyses) == 1:
        # Single module — no synthesis needed
        return module_analyses[0].analysis

    module_results = []
    for ma in module_analyses:
        findings = "\n".join(f"  - {f}" for f in ma.key_findings) if ma.key_findings else "  (none)"
        section = f"### {ma.module} (complexity {ma.complexity_score}/10, via {ma.model_used})\n{ma.analysis}\n\nKey findings:\n{findings}"

        # Include sub-analyses if present
        for sub in ma.sub_analyses:
            sub_findings = "\n".join(f"    - {f}" for f in sub.key_findings) if sub.key_findings else "    (none)"
            section += f"\n\n#### {sub.module} (via {sub.model_used})\n{sub.analysis}\nFindings:\n{sub_findings}"

        module_results.append(section)

    prompt = SYNTHESIS_PROMPT.format(
        question=question,
        module_results="\n\n---\n\n".join(module_results),
    )
    return await _call_llm(
        prompt, model,
        system="You are a senior software architect. Synthesize the analysis clearly and precisely.",
        max_tokens=4096,
    )


async def deep_analyze(
    question: str,
    modules: dict[str, ModuleSchema],
    depth: int = 1,
    synthesis_model: str = "sonnet",
    parallel: bool = False,
) -> OrchestrationResult:
    """Full orchestration: per-module analysis with model hints, then synthesis.

    Args:
        question: The analysis question.
        modules: Module name → ModuleSchema mapping.
        depth: Max recursion depth (1 = flat, 2 = sub-components for complex modules).
        synthesis_model: Model for the final synthesis step.
        parallel: If True, run module analyses concurrently (faster but harder to debug).
    """
    start = datetime.now(timezone.utc)
    tokens_before = token_tracker.total_tokens
    models_used: dict[str, int] = {}

    # Determine model per module from complexity hints
    module_plans: list[tuple[str, ModuleSchema, str]] = []
    for mod_name, mod in modules.items():
        if depth > 1:
            model = mod.model_hints.analysis
        else:
            model = mod.model_hints.update  # Use lighter model for flat analysis
        module_plans.append((mod_name, mod, model))

    # Execute per-module analyses
    analyses: list[ModuleAnalysis] = []

    if parallel and len(module_plans) > 1:
        # Concurrent execution
        tasks = []
        for mod_name, mod, model in module_plans:
            sub_model = mod.model_hints.query  # lightest model for sub-components
            tasks.append(analyze_module(mod, question, model, depth, sub_model))
        analyses = await asyncio.gather(*tasks)
    else:
        # Sequential execution (easier to debug, respects budget)
        for mod_name, mod, model in module_plans:
            sub_model = mod.model_hints.query
            try:
                result = await analyze_module(mod, question, model, depth, sub_model)
                analyses.append(result)
            except RuntimeError as e:
                if "budget" in str(e).lower():
                    logger.warning(f"Budget exceeded during analysis of {mod_name}")
                    analyses.append(ModuleAnalysis(
                        module=mod_name,
                        model_used=model,
                        analysis=f"Skipped — token budget exceeded.",
                        complexity_score=mod.complexity.score,
                    ))
                    break
                raise

    # Track models used
    for a in analyses:
        models_used[a.model_used] = models_used.get(a.model_used, 0) + 1
        for sub in a.sub_analyses:
            models_used[sub.model_used] = models_used.get(sub.model_used, 0) + 1

    # Synthesis
    synthesis = await synthesize(question, analyses, synthesis_model)

    elapsed = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    total_tokens = token_tracker.total_tokens - tokens_before

    # Estimate cost
    from .complexity import estimate_cost
    total_cost = 0.0
    for model, count in models_used.items():
        # Rough per-call estimate
        per_call_tokens = total_tokens // max(sum(models_used.values()), 1)
        total_cost += estimate_cost(per_call_tokens * count, model)

    max_depth = 1
    for a in analyses:
        if a.sub_analyses:
            max_depth = 2

    return OrchestrationResult(
        question=question,
        synthesis=synthesis,
        module_analyses=analyses,
        total_tokens=total_tokens,
        total_cost=total_cost,
        models_used=models_used,
        elapsed_ms=elapsed,
        depth_reached=max_depth,
    )
