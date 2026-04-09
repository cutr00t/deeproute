"""Programmatic reader for v2 structured schema. Zero LLM calls.

Loads and indexes JSON files from .deeproute/v2/ for fast lookup and search.
Supports semantic search via embeddings when available.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .schema import (
    ConfigFilesSchema,
    InterfaceSchema,
    Manifest,
    ModuleSchema,
    PatternsSchema,
)

logger = logging.getLogger(__name__)
V2_DIR = "v2"


class SchemaReader:
    """Parse v2 structured schema files. No LLM calls."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.v2_dir = self.repo_path / ".deeproute" / V2_DIR
        self._manifest: Manifest | None = None
        self._modules: dict[str, ModuleSchema] = {}
        self._interfaces: InterfaceSchema | None = None
        self._config_files: ConfigFilesSchema | None = None
        self._patterns: PatternsSchema | None = None
        self._search_index: list[dict] | None = None
        self._embedding_store: Any = None

    def has_v2(self) -> bool:
        return (self.v2_dir / "manifest.json").exists()

    def load_manifest(self) -> Manifest:
        if self._manifest is None:
            data = self._read_json("manifest.json")
            self._manifest = Manifest.model_validate(data)
        return self._manifest

    def list_modules(self) -> list[str]:
        """List available module names from manifest."""
        manifest = self.load_manifest()
        return [m.name for m in manifest.modules]

    def load_module(self, name: str) -> ModuleSchema | None:
        """Load a module schema by name. Returns None if not found."""
        if name in self._modules:
            return self._modules[name]
        # Try sanitized filename
        filename = name.replace("/", "__") + ".json"
        path = self.v2_dir / "modules" / filename
        if not path.exists():
            # Try finding by module name in available files
            modules_dir = self.v2_dir / "modules"
            if modules_dir.is_dir():
                for f in modules_dir.iterdir():
                    if f.suffix == ".json":
                        data = json.loads(f.read_text())
                        if data.get("name") == name or data.get("path") == name:
                            mod = ModuleSchema.model_validate(data)
                            self._modules[name] = mod
                            return mod
            return None
        data = json.loads(path.read_text())
        mod = ModuleSchema.model_validate(data)
        self._modules[name] = mod
        return mod

    def load_all_modules(self) -> dict[str, ModuleSchema]:
        """Load all module schemas."""
        modules_dir = self.v2_dir / "modules"
        if not modules_dir.is_dir():
            return {}
        for f in sorted(modules_dir.iterdir()):
            if f.suffix == ".json":
                data = json.loads(f.read_text())
                name = data.get("name", f.stem)
                if name not in self._modules:
                    self._modules[name] = ModuleSchema.model_validate(data)
        return self._modules

    def load_interfaces(self) -> InterfaceSchema:
        if self._interfaces is None:
            data = self._read_json("interfaces.json")
            self._interfaces = InterfaceSchema.model_validate(data)
        return self._interfaces

    def load_config_files(self) -> ConfigFilesSchema:
        if self._config_files is None:
            data = self._read_json("config_files.json")
            self._config_files = ConfigFilesSchema.model_validate(data)
        return self._config_files

    def load_patterns(self) -> PatternsSchema:
        if self._patterns is None:
            data = self._read_json("patterns.json")
            self._patterns = PatternsSchema.model_validate(data)
        return self._patterns

    def load_notes(self, module: str) -> str | None:
        """Load freeform markdown notes for a module."""
        filename = module.replace("/", "__") + ".md"
        notes_path = self.v2_dir / "notes" / filename
        if notes_path.exists():
            return notes_path.read_text()
        # Try direct module notes_file reference
        mod = self.load_module(module)
        if mod and mod.notes_file:
            p = self.v2_dir / mod.notes_file
            if p.exists():
                return p.read_text()
        return None

    def lookup_file(self, file_path: str) -> dict | None:
        """Find which module a file belongs to and its role."""
        modules = self.load_all_modules()
        for mod_name, mod in modules.items():
            for f in mod.files:
                if f.path == file_path:
                    return {
                        "module": mod_name,
                        "path": f.path,
                        "role": f.role,
                        "tags": f.tags,
                        "functions": f.functions,
                        "classes": f.classes,
                    }
        return None

    def lookup_function(self, name: str) -> list[dict]:
        """Find functions by name across all modules."""
        results = []
        modules = self.load_all_modules()
        for mod_name, mod in modules.items():
            for fn in mod.functions:
                if fn.name == name or name in fn.name:
                    results.append({
                        "module": mod_name,
                        **fn.model_dump(),
                    })
            for cls in mod.classes:
                for method in cls.key_methods:
                    if method.name == name or name in method.name:
                        results.append({
                            "module": mod_name,
                            "class": cls.name,
                            **method.model_dump(),
                        })
        return results

    def lookup_class(self, name: str) -> list[dict]:
        """Find classes by name across all modules."""
        results = []
        modules = self.load_all_modules()
        for mod_name, mod in modules.items():
            for cls in mod.classes:
                if cls.name == name or name in cls.name:
                    results.append({
                        "module": mod_name,
                        **cls.model_dump(),
                    })
        return results

    def get_embedding_store(self):
        """Get or create the embedding store for this repo."""
        if self._embedding_store is None:
            try:
                from .embeddings import EmbeddingStore
                self._embedding_store = EmbeddingStore(self.v2_dir)
            except ImportError:
                pass
        return self._embedding_store

    def search(
        self,
        query: str = "",
        tags: list[str] | None = None,
        item_type: str = "",
        limit: int = 20,
        semantic: bool = False,
    ) -> list[dict]:
        """Search across all schemas by text, tags, or type.

        item_type: "function", "class", "file", "endpoint", "pattern", "module"
        semantic: if True and embeddings available, use cosine similarity for query matching
        """
        # Semantic search path
        if semantic and query and not tags:
            store = self.get_embedding_store()
            if store and store.available:
                try:
                    results = store.search(query, top_k=limit)
                    semantic_results = []
                    for meta, score in results:
                        if item_type and meta.get("type", "") != item_type:
                            continue
                        result = dict(meta)
                        result["_type"] = result.pop("type", "")
                        result["_score"] = round(score, 3)
                        semantic_results.append(result)
                    if semantic_results:
                        return semantic_results[:limit]
                except Exception as e:
                    logger.debug(f"Semantic search fallback to text: {e}")

        # Text/tag search (original behavior)
        if self._search_index is None:
            self._build_search_index()
        assert self._search_index is not None

        results = []
        query_lower = query.lower() if query else ""
        tag_set = set(tags) if tags else set()

        for item in self._search_index:
            # Type filter
            if item_type and item["_type"] != item_type:
                continue
            # Tag filter
            if tag_set and not tag_set.intersection(item.get("tags", [])):
                continue
            # Text search
            if query_lower:
                searchable = " ".join([
                    item.get("name", ""),
                    item.get("description", ""),
                    item.get("role", ""),
                    item.get("path", ""),
                    " ".join(item.get("tags", [])),
                ]).lower()
                if query_lower not in searchable:
                    continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def _build_search_index(self) -> None:
        """Build a flat searchable index across all schema types."""
        index: list[dict] = []
        modules = self.load_all_modules()

        for mod_name, mod in modules.items():
            # Module itself
            index.append({
                "_type": "module",
                "name": mod.name,
                "path": mod.path,
                "description": mod.summary,
                "tags": mod.tags,
                "module": mod_name,
            })
            # Files
            for f in mod.files:
                index.append({
                    "_type": "file",
                    "name": Path(f.path).name,
                    "path": f.path,
                    "role": f.role,
                    "description": f.role,
                    "tags": f.tags,
                    "module": mod_name,
                })
            # Functions (from top-level function specs)
            for fn in mod.functions:
                index.append({
                    "_type": "function",
                    "name": fn.name,
                    "path": fn.file,
                    "description": fn.description,
                    "tags": fn.tags,
                    "module": mod_name,
                    "return_type": fn.return_type,
                })
            # Functions listed in file entries (fallback when LLM didn't populate top-level)
            seen_fns = {fn.name for fn in mod.functions}
            for f in mod.files:
                for fn_name in f.functions:
                    if fn_name not in seen_fns:
                        index.append({
                            "_type": "function",
                            "name": fn_name,
                            "path": f.path,
                            "description": "",
                            "tags": f.tags,
                            "module": mod_name,
                        })
                        seen_fns.add(fn_name)
            # Classes (from top-level class specs)
            for cls in mod.classes:
                index.append({
                    "_type": "class",
                    "name": cls.name,
                    "path": cls.file,
                    "description": cls.description,
                    "tags": cls.tags,
                    "module": mod_name,
                })
            # Classes listed in file entries (fallback)
            seen_cls = {cls.name for cls in mod.classes}
            for f in mod.files:
                for cls_name in f.classes:
                    if cls_name not in seen_cls:
                        index.append({
                            "_type": "class",
                            "name": cls_name,
                            "path": f.path,
                            "description": "",
                            "tags": f.tags,
                            "module": mod_name,
                        })
                        seen_cls.add(cls_name)

        # Interfaces
        try:
            ifaces = self.load_interfaces()
            for ep in ifaces.http_endpoints:
                index.append({
                    "_type": "endpoint",
                    "name": f"{ep.method} {ep.path}",
                    "path": ep.handler,
                    "description": ep.description,
                    "tags": ep.tags,
                })
            for eh in ifaces.event_handlers:
                index.append({
                    "_type": "event_handler",
                    "name": eh.event,
                    "path": eh.handler,
                    "description": eh.description,
                    "tags": [],
                })
        except FileNotFoundError:
            pass

        # Patterns
        try:
            patterns = self.load_patterns()
            for p in patterns.patterns:
                index.append({
                    "_type": "pattern",
                    "name": p.name,
                    "description": p.description,
                    "tags": p.tags,
                    "locations": p.locations,
                })
        except FileNotFoundError:
            pass

        self._search_index = index

    def _read_json(self, filename: str) -> dict:
        path = self.v2_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {path}")
        return json.loads(path.read_text())
