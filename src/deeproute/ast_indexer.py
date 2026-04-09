"""AST-based factual extraction — Python via stdlib ast, other languages via regex.

Produces FunctionSpec and ClassSpec objects with source="ast" that represent
ground-truth symbol tables. These are merged with LLM-derived interpretive
data (descriptions, tags) to create hybrid schemas that are always factually
accurate.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import NamedTuple

from .schema import ClassSpec, FileRole, FunctionSpec, ParamSpec

logger = logging.getLogger(__name__)


class FileIndex(NamedTuple):
    """Factual extraction result for a single file."""
    path: str
    functions: list[FunctionSpec]
    classes: list[ClassSpec]
    imports: list[str]  # module names imported


# --- Python AST extraction ---

def _python_param_spec(arg: ast.arg) -> ParamSpec:
    """Extract parameter info from an ast.arg node."""
    type_str = ""
    if arg.annotation:
        type_str = ast.unparse(arg.annotation)
    return ParamSpec(name=arg.arg, type=type_str)


def _python_return_type(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if node.returns:
        return ast.unparse(node.returns)
    return ""


def _python_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    return [ast.unparse(d) for d in node.decorator_list]


def _extract_python_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: str,
) -> FunctionSpec:
    """Extract a FunctionSpec from a Python function/method AST node."""
    params = []
    for arg in node.args.args:
        if arg.arg == "self" or arg.arg == "cls":
            continue
        params.append(_python_param_spec(arg))

    # Keyword-only args
    for arg in node.args.kwonlyargs:
        params.append(_python_param_spec(arg))

    # *args
    if node.args.vararg:
        p = _python_param_spec(node.args.vararg)
        params.append(ParamSpec(name=f"*{p.name}", type=p.type))

    # **kwargs
    if node.args.kwarg:
        p = _python_param_spec(node.args.kwarg)
        params.append(ParamSpec(name=f"**{p.name}", type=p.type))

    return FunctionSpec(
        name=node.name,
        file=file_path,
        line=node.lineno,
        params=params,
        return_type=_python_return_type(node),
        is_public=not node.name.startswith("_"),
        source="ast",
        decorators=_python_decorators(node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


def _extract_python_class(
    node: ast.ClassDef,
    file_path: str,
) -> ClassSpec:
    """Extract a ClassSpec from a Python class AST node."""
    bases = [ast.unparse(b) for b in node.bases]
    methods = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_extract_python_function(item, file_path))

    return ClassSpec(
        name=node.name,
        file=file_path,
        line=node.lineno,
        bases=bases,
        key_methods=methods,
        source="ast",
    )


def index_python_file(file_path: str, content: str) -> FileIndex:
    """Extract functions, classes, and imports from a Python file using stdlib ast."""
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        logger.debug(f"Syntax error parsing {file_path}: {e}")
        return FileIndex(path=file_path, functions=[], classes=[], imports=[])

    functions: list[FunctionSpec] = []
    classes: list[ClassSpec] = []
    imports: list[str] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_extract_python_function(node, file_path))
        elif isinstance(node, ast.ClassDef):
            classes.append(_extract_python_class(node, file_path))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return FileIndex(path=file_path, functions=functions, classes=classes, imports=imports)


# --- Regex-based extraction for other languages ---

# Patterns: each returns (name, line_content) tuples
_LANG_PATTERNS: dict[str, dict[str, list[re.Pattern]]] = {
    "JavaScript": {
        "functions": [
            re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE),
            re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(", re.MULTILINE),
            re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^(?:export\s+)?class\s+(\w+)", re.MULTILINE),
        ],
    },
    "TypeScript": {
        "functions": [
            re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*[<(]", re.MULTILINE),
            re.compile(r"^(?:export\s+)?(?:const|let)\s+(\w+)\s*(?::\s*[^=]+)?\s*=\s*(?:async\s+)?\(", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE),
            re.compile(r"^(?:export\s+)?(?:type|interface)\s+(\w+)", re.MULTILINE),
        ],
    },
    "Go": {
        "functions": [
            re.compile(r"^func\s+(\w+)\s*\(", re.MULTILINE),
            re.compile(r"^func\s+\(\w+\s+\*?\w+\)\s+(\w+)\s*\(", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^type\s+(\w+)\s+struct\s*\{", re.MULTILINE),
            re.compile(r"^type\s+(\w+)\s+interface\s*\{", re.MULTILINE),
        ],
    },
    "Rust": {
        "functions": [
            re.compile(r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^(?:pub\s+)?struct\s+(\w+)", re.MULTILINE),
            re.compile(r"^(?:pub\s+)?enum\s+(\w+)", re.MULTILINE),
            re.compile(r"^(?:pub\s+)?trait\s+(\w+)", re.MULTILINE),
        ],
    },
    "Java": {
        "functions": [
            re.compile(r"^\s+(?:public|private|protected)?\s*(?:static\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\(", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^(?:public\s+)?(?:abstract\s+)?(?:class|interface|enum)\s+(\w+)", re.MULTILINE),
        ],
    },
    "Kotlin": {
        "functions": [
            re.compile(r"^\s*(?:(?:public|private|internal|protected)\s+)?(?:suspend\s+)?fun\s+(\w+)", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^(?:(?:public|private|internal)\s+)?(?:data\s+|sealed\s+|abstract\s+)?class\s+(\w+)", re.MULTILINE),
            re.compile(r"^(?:(?:public|private|internal)\s+)?interface\s+(\w+)", re.MULTILINE),
        ],
    },
    "Ruby": {
        "functions": [
            re.compile(r"^\s*def\s+(\w+)", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^(?:\s*)class\s+(\w+)", re.MULTILINE),
            re.compile(r"^(?:\s*)module\s+(\w+)", re.MULTILINE),
        ],
    },
    "C#": {
        "functions": [
            re.compile(r"^\s+(?:public|private|protected|internal)?\s*(?:static\s+)?(?:async\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\(", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^(?:public\s+)?(?:abstract\s+|sealed\s+)?(?:class|interface|struct|enum|record)\s+(\w+)", re.MULTILINE),
        ],
    },
    "Swift": {
        "functions": [
            re.compile(r"^\s*(?:public\s+|private\s+|internal\s+)?func\s+(\w+)", re.MULTILINE),
        ],
        "classes": [
            re.compile(r"^(?:public\s+|private\s+)?(?:class|struct|enum|protocol)\s+(\w+)", re.MULTILINE),
        ],
    },
    "Shell": {
        "functions": [
            re.compile(r"^(?:function\s+)?(\w+)\s*\(\s*\)", re.MULTILINE),
        ],
        "classes": [],
    },
    "Terraform": {
        "functions": [],
        "classes": [
            re.compile(r'^resource\s+"(\w+)"\s+"(\w+)"', re.MULTILINE),
            re.compile(r'^module\s+"(\w+)"', re.MULTILINE),
        ],
    },
}

# Aliases for language name variants
_LANG_ALIASES: dict[str, str] = {
    "JS": "JavaScript", "jsx": "JavaScript",
    "TS": "TypeScript", "tsx": "TypeScript",
    "Python": "Python", "py": "Python",
}


def _find_line_number(content: str, match_start: int) -> int:
    """Convert character offset to line number."""
    return content[:match_start].count("\n") + 1


def index_regex_file(file_path: str, content: str, language: str) -> FileIndex:
    """Extract functions and classes using regex patterns for non-Python languages."""
    lang_key = _LANG_ALIASES.get(language, language)
    patterns = _LANG_PATTERNS.get(lang_key)
    if not patterns:
        return FileIndex(path=file_path, functions=[], classes=[], imports=[])

    functions: list[FunctionSpec] = []
    classes: list[ClassSpec] = []

    for pat in patterns.get("functions", []):
        for m in pat.finditer(content):
            name = m.group(1)
            line = _find_line_number(content, m.start())
            is_public = not name.startswith("_")
            # Language-specific public detection
            if lang_key in ("Go",):
                is_public = name[0].isupper() if name else False
            functions.append(FunctionSpec(
                name=name,
                file=file_path,
                line=line,
                is_public=is_public,
                source="ast",
            ))

    for pat in patterns.get("classes", []):
        for m in pat.finditer(content):
            # Some patterns have multiple groups (e.g., Terraform resource)
            name = m.group(m.lastindex or 1)
            line = _find_line_number(content, m.start())
            classes.append(ClassSpec(
                name=name,
                file=file_path,
                line=line,
                source="ast",
            ))

    return FileIndex(path=file_path, functions=functions, classes=classes, imports=[])


# --- Unified entry point ---

def index_file(file_path: str, content: str, language: str) -> FileIndex:
    """Index a single file — dispatches to Python AST or regex based on language."""
    if language == "Python":
        return index_python_file(file_path, content)
    return index_regex_file(file_path, content, language)


def index_repo(
    repo_path: Path,
    file_infos: list[dict],
    excludes: list[str] | None = None,
    max_file_size: int = 500_000,
) -> dict[str, FileIndex]:
    """Index all supported files in a repo.

    Args:
        repo_path: Root path of the repository.
        file_infos: List of dicts with 'path', 'language' keys (from scanner).
        excludes: Glob patterns to skip.
        max_file_size: Skip files larger than this (bytes).

    Returns:
        Dict mapping relative file paths to their FileIndex.
    """
    results: dict[str, FileIndex] = {}

    for info in file_infos:
        rel_path = info["path"]
        language = info.get("language", "")
        if not language:
            continue

        full_path = repo_path / rel_path
        if not full_path.exists() or not full_path.is_file():
            continue

        try:
            size = full_path.stat().st_size
            if size > max_file_size:
                continue
            content = full_path.read_text(errors="replace")
        except OSError:
            continue

        idx = index_file(rel_path, content, language)
        if idx.functions or idx.classes or idx.imports:
            results[rel_path] = idx

    return results


def build_module_file_roles(
    file_indexes: dict[str, FileIndex],
) -> list[FileRole]:
    """Build FileRole entries from AST-indexed files."""
    roles = []
    for path, idx in sorted(file_indexes.items()):
        roles.append(FileRole(
            path=path,
            functions=[fn.name for fn in idx.functions],
            classes=[cls.name for cls in idx.classes],
        ))
    return roles


def compute_drift_score(
    old_functions: list[FunctionSpec],
    new_functions: list[FunctionSpec],
    old_classes: list[ClassSpec],
    new_classes: list[ClassSpec],
) -> float:
    """Compute a drift score (0.0-1.0) between old and new AST extractions.

    Factors:
    - New/removed functions or classes (high weight)
    - Changed function signatures (medium weight)
    - Changed line numbers only (low weight, ignored)

    Returns 0.0 for no drift, 1.0 for complete divergence.
    """
    if not old_functions and not old_classes and not new_functions and not new_classes:
        return 0.0

    old_fn_names = {fn.name for fn in old_functions}
    new_fn_names = {fn.name for fn in new_functions}
    old_cls_names = {cls.name for cls in old_classes}
    new_cls_names = {cls.name for cls in new_classes}

    # Additions and removals
    added_fns = new_fn_names - old_fn_names
    removed_fns = old_fn_names - new_fn_names
    added_cls = new_cls_names - old_cls_names
    removed_cls = old_cls_names - new_cls_names

    total_symbols = max(len(old_fn_names | new_fn_names) + len(old_cls_names | new_cls_names), 1)
    structural_changes = len(added_fns) + len(removed_fns) + len(added_cls) + len(removed_cls)

    # Signature changes (same name, different params/return)
    old_fn_map = {fn.name: fn for fn in old_functions}
    new_fn_map = {fn.name: fn for fn in new_functions}
    signature_changes = 0
    for name in old_fn_names & new_fn_names:
        old_fn = old_fn_map[name]
        new_fn = new_fn_map[name]
        old_sig = (tuple((p.name, p.type) for p in old_fn.params), old_fn.return_type)
        new_sig = (tuple((p.name, p.type) for p in new_fn.params), new_fn.return_type)
        if old_sig != new_sig:
            signature_changes += 1

    # Weighted score
    score = (structural_changes * 1.0 + signature_changes * 0.5) / total_symbols
    return min(score, 1.0)
