"""Programmatic complexity scoring — computed from AST data, no LLM calls.

Produces per-module complexity scores (1-10) and model hints derived from
measurable code characteristics. Feeds into dr_plan for cost-aware execution
planning and into module schemas for informed model selection.

Scoring dimensions:
- Symbol density: function + class count relative to file count
- API surface: public functions/classes as proportion of total
- Parameter complexity: avg/max params per function
- Coupling: cross-module imports, dependency count
- Structural depth: directory nesting, class hierarchy depth
- Async ratio: proportion of async functions (proxy for concurrency complexity)
- File volume: raw file count in module
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from .ast_indexer import FileIndex
from .schema import FunctionSpec, ClassSpec, ModuleSchema


class ComplexityFactors(NamedTuple):
    """Raw measurable factors feeding the composite score."""
    file_count: int
    function_count: int
    class_count: int
    public_functions: int
    public_classes: int
    avg_params: float
    max_params: int
    import_count: int
    cross_module_deps: int
    directory_depth: int
    async_ratio: float
    has_decorators: bool
    total_methods: int  # methods across all classes


@dataclass
class ComplexityScore:
    """Composite complexity score with breakdown."""
    score: int  # 1-10
    factors: list[str]  # human-readable factor descriptions
    raw: ComplexityFactors | None = None
    model_hints: dict = field(default_factory=dict)


@dataclass
class ModelHints:
    """Recommended model selection based on complexity."""
    analysis: str = "sonnet"  # for deep init/re-analysis
    update: str = "sonnet"    # for incremental updates
    query: str = "haiku"      # for lookups in agent mode


# --- Scoring weights ---
# Each dimension contributes 0.0-1.0, weighted and summed to produce 1-10

_WEIGHTS = {
    "symbol_density": 0.15,
    "api_surface": 0.10,
    "param_complexity": 0.15,
    "coupling": 0.20,
    "structural_depth": 0.10,
    "async_complexity": 0.10,
    "volume": 0.10,
    "method_density": 0.10,
}


def _sigmoid(x: float, midpoint: float = 0.5, steepness: float = 10.0) -> float:
    """Sigmoid normalization: maps any positive value to 0.0-1.0."""
    return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))


def _linear_clamp(x: float, low: float, high: float) -> float:
    """Linear map from [low, high] to [0.0, 1.0], clamped."""
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (x - low) / (high - low)))


def compute_factors(
    file_indexes: dict[str, FileIndex],
    module_path: str = "",
    all_module_names: list[str] | None = None,
) -> ComplexityFactors:
    """Compute raw complexity factors from AST-indexed files."""
    all_functions: list[FunctionSpec] = []
    all_classes: list[ClassSpec] = []
    all_imports: list[str] = []
    max_depth = 0

    for path, idx in file_indexes.items():
        all_functions.extend(idx.functions)
        all_classes.extend(idx.classes)
        all_imports.extend(idx.imports)

        # Directory depth
        depth = len(Path(path).parts)
        max_depth = max(max_depth, depth)

    # Count methods across all classes
    total_methods = sum(len(cls.key_methods) for cls in all_classes)

    # Parameter stats
    param_counts = [len(fn.params) for fn in all_functions]
    avg_params = sum(param_counts) / max(len(param_counts), 1)
    max_params = max(param_counts) if param_counts else 0

    # Public API surface
    public_fns = sum(1 for fn in all_functions if fn.is_public)
    public_cls = sum(1 for cls in all_classes if not cls.name.startswith("_"))

    # Cross-module dependencies
    cross_deps = 0
    if all_module_names:
        module_set = set(all_module_names)
        for imp in all_imports:
            # Check if import references another module
            for mod_name in module_set:
                if mod_name != module_path and mod_name in imp:
                    cross_deps += 1
                    break

    # Async ratio
    async_count = sum(1 for fn in all_functions if fn.is_async)
    async_ratio = async_count / max(len(all_functions), 1)

    # Decorator usage
    has_decorators = any(fn.decorators for fn in all_functions)

    return ComplexityFactors(
        file_count=len(file_indexes),
        function_count=len(all_functions),
        class_count=len(all_classes),
        public_functions=public_fns,
        public_classes=public_cls,
        avg_params=round(avg_params, 2),
        max_params=max_params,
        import_count=len(set(all_imports)),
        cross_module_deps=cross_deps,
        directory_depth=max_depth,
        async_ratio=round(async_ratio, 2),
        has_decorators=has_decorators,
        total_methods=total_methods,
    )


def score_module(factors: ComplexityFactors) -> ComplexityScore:
    """Compute a 1-10 complexity score from raw factors."""
    dimensions: dict[str, float] = {}
    factor_descriptions: list[str] = []

    # Symbol density: functions + classes per file
    symbol_density = (factors.function_count + factors.class_count) / max(factors.file_count, 1)
    dimensions["symbol_density"] = _linear_clamp(symbol_density, 2.0, 15.0)
    if symbol_density > 10:
        factor_descriptions.append(f"high symbol density ({symbol_density:.0f}/file)")

    # API surface: large public API = more complexity to maintain
    total_symbols = factors.function_count + factors.class_count
    public_ratio = (factors.public_functions + factors.public_classes) / max(total_symbols, 1)
    dimensions["api_surface"] = public_ratio * _linear_clamp(
        factors.public_functions + factors.public_classes, 5, 50,
    )
    if factors.public_functions > 20:
        factor_descriptions.append(f"large public API ({factors.public_functions} public fns)")

    # Parameter complexity
    param_score = _linear_clamp(factors.avg_params, 1.0, 5.0) * 0.6 + _linear_clamp(factors.max_params, 3, 10) * 0.4
    dimensions["param_complexity"] = param_score
    if factors.max_params > 6:
        factor_descriptions.append(f"complex signatures (max {factors.max_params} params)")

    # Coupling: imports + cross-module deps
    coupling = _linear_clamp(factors.import_count, 5, 30) * 0.4 + _linear_clamp(factors.cross_module_deps, 1, 8) * 0.6
    dimensions["coupling"] = coupling
    if factors.cross_module_deps > 3:
        factor_descriptions.append(f"high coupling ({factors.cross_module_deps} cross-module deps)")

    # Structural depth
    dimensions["structural_depth"] = _linear_clamp(factors.directory_depth, 2, 6)
    if factors.directory_depth > 4:
        factor_descriptions.append(f"deep nesting ({factors.directory_depth} levels)")

    # Async complexity
    dimensions["async_complexity"] = factors.async_ratio
    if factors.async_ratio > 0.3:
        factor_descriptions.append(f"async-heavy ({factors.async_ratio:.0%} async)")

    # Volume
    dimensions["volume"] = _linear_clamp(factors.file_count, 3, 30)
    if factors.file_count > 20:
        factor_descriptions.append(f"large module ({factors.file_count} files)")

    # Method density (OOP complexity)
    method_ratio = factors.total_methods / max(factors.class_count, 1) if factors.class_count > 0 else 0
    dimensions["method_density"] = _linear_clamp(method_ratio, 3, 12) if factors.class_count > 0 else 0.0
    if method_ratio > 8:
        factor_descriptions.append(f"method-heavy classes (avg {method_ratio:.0f} methods)")

    # Weighted sum → 1-10
    raw_score = sum(dimensions[k] * _WEIGHTS[k] for k in _WEIGHTS)
    final_score = max(1, min(10, round(raw_score * 10)))

    if not factor_descriptions:
        if final_score <= 3:
            factor_descriptions.append("low complexity")
        elif final_score <= 6:
            factor_descriptions.append("moderate complexity")
        else:
            factor_descriptions.append("high complexity")

    return ComplexityScore(
        score=final_score,
        factors=factor_descriptions,
        raw=factors,
        model_hints=derive_model_hints(final_score),
    )


def derive_model_hints(score: int) -> dict:
    """Map complexity score to recommended model aliases."""
    if score <= 3:
        return {"analysis": "haiku", "update": "haiku", "query": "haiku"}
    if score <= 5:
        return {"analysis": "sonnet", "update": "haiku", "query": "haiku"}
    if score <= 7:
        return {"analysis": "sonnet", "update": "sonnet", "query": "haiku"}
    return {"analysis": "opus", "update": "sonnet", "query": "sonnet"}


def estimate_tokens(factors: ComplexityFactors | dict, operation: str = "init") -> int:
    """Estimate token usage for an operation on a module.

    Accepts either a ComplexityFactors namedtuple or a dict with
    file_count/function_count/class_count keys (e.g., from ComplexityInfo schema).

    Based on empirical observation: ~50 tokens per function for analysis,
    ~20 per function for updates, file content adds ~100 tokens per file.
    """
    if isinstance(factors, dict):
        file_count = factors.get("file_count", 0)
        fn_count = factors.get("function_count", 0)
        cls_count = factors.get("class_count", 0)
    else:
        file_count = factors.file_count
        fn_count = factors.function_count
        cls_count = factors.class_count

    if operation == "init":
        base = file_count * 100
        symbols = (fn_count + cls_count) * 50
        overhead = 2000
        return base + symbols + overhead
    elif operation == "update":
        base = file_count * 30
        symbols = (fn_count + cls_count) * 20
        overhead = 1500
        return base + symbols + overhead
    elif operation == "query":
        return file_count * 20 + 1000
    return 0


# Token cost estimates per 1M tokens (input) — approximate
_MODEL_COSTS: dict[str, float] = {
    "haiku": 0.80,
    "sonnet": 3.00,
    "opus": 15.00,
}


def estimate_cost(tokens: int, model: str) -> float:
    """Estimate cost in USD for a given token count and model."""
    cost_per_m = _MODEL_COSTS.get(model, 3.00)
    return (tokens / 1_000_000) * cost_per_m


def score_repo(
    file_indexes: dict[str, FileIndex],
    module_groups: dict[str, list[str]] | None = None,
) -> dict[str, ComplexityScore]:
    """Score all modules in a repo.

    Args:
        file_indexes: All AST-indexed files (path → FileIndex).
        module_groups: Optional mapping of module names → file paths.
            If None, treats all files as one module.

    Returns:
        Dict of module name → ComplexityScore.
    """
    if module_groups is None:
        # Treat entire repo as one module
        factors = compute_factors(file_indexes)
        return {"(root)": score_module(factors)}

    all_module_names = list(module_groups.keys())
    scores: dict[str, ComplexityScore] = {}

    for mod_name, file_paths in module_groups.items():
        mod_indexes = {p: file_indexes[p] for p in file_paths if p in file_indexes}
        if not mod_indexes:
            scores[mod_name] = ComplexityScore(score=1, factors=["empty module"])
            continue
        factors = compute_factors(mod_indexes, mod_name, all_module_names)
        scores[mod_name] = score_module(factors)

    return scores
