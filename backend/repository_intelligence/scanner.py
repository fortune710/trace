"""Bounded source inventory and candidate signals without model calls."""

from __future__ import annotations

import ast
import hashlib
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser

from repository_intelligence.rules import (
    JAVASCRIPT_DYNAMIC_EXECUTION,
    PYTHON_DYNAMIC_EXECUTION,
)

ANALYZER_VERSION = "1"
MAX_FILES = 3_000
MAX_FILE_BYTES = 256_000
EXCLUDED_PARTS = frozenset(
    {"node_modules", "vendor", "dist", "build", ".git", "_generated", "__pycache__"}
)
_SOURCE_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".py", ".json", ".md"})
_ROUTE_PATH = re.compile(r"(?:^|/)(?:api/.*?/route|pages/api/.*|routes/.*)\.[jt]sx?$")
_INTEGRATION = re.compile(
    r"\b(stripe|posthog|clerk|sentry|resend|openai|anthropic)\b", re.IGNORECASE
)
_POLICY = re.compile(
    r"(?:privacy|terms|consent|pricing|refund|delete-account)", re.IGNORECASE
)
_IMPORT = re.compile(r"\b(?:import\s+.*?\s+from|require\()\s*['\"]([^'\"]+)['\"]")
_LANGUAGES = {
    ".js": Language(tree_sitter_javascript.language()),
    ".jsx": Language(tree_sitter_javascript.language()),
    ".ts": Language(tree_sitter_typescript.language_typescript()),
    ".tsx": Language(tree_sitter_typescript.language_tsx()),
}


@dataclass(frozen=True)
class Fact:
    kind: str
    path: str
    line: int | None
    symbol: str | None
    value: str | None
    digest: str


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    version: int
    path: str
    line: int
    symbol: str | None
    digest: str


@dataclass(frozen=True)
class Edge:
    from_path: str
    to_path: str
    relationship: str
    line: int


@dataclass(frozen=True)
class IntelligencePack:
    source_kind: str
    source_identifier: str
    revision: str
    analyzer_version: str
    frameworks: tuple[str, ...]
    facts: tuple[Fact, ...]
    rule_hits: tuple[RuleHit, ...]
    skipped_counts: Mapping[str, int]
    edges: tuple[Edge, ...] = ()


def scan_files(
    *,
    source_kind: str,
    source_identifier: str,
    revision: str,
    files: Mapping[str, bytes],
) -> IntelligencePack:
    """Analyze a trusted immutable file map; return pointers, never source text."""

    facts: list[Fact] = []
    hits: list[RuleHit] = []
    edges: list[Edge] = []
    skipped = {"excluded": 0, "oversized": 0, "binary": 0, "limit": 0}
    frameworks: set[str] = set()
    accepted = 0
    for path, raw in sorted(files.items()):
        parts = PurePosixPath(path).parts
        if (
            not path
            or path.startswith("/")
            or ".." in parts
            or any(part in EXCLUDED_PARTS for part in parts)
            or PurePosixPath(path).suffix not in _SOURCE_SUFFIXES
        ):
            skipped["excluded"] += 1
            continue
        if len(raw) > MAX_FILE_BYTES:
            skipped["oversized"] += 1
            continue
        if b"\0" in raw:
            skipped["binary"] += 1
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped["binary"] += 1
            continue
        if accepted >= MAX_FILES:
            skipped["limit"] += 1
            continue
        accepted += 1
        digest = hashlib.sha256(raw).hexdigest()
        facts.append(Fact("file", path, None, None, None, digest))
        if _ROUTE_PATH.search(path):
            facts.append(Fact("route", path, None, None, None, digest))
        if _POLICY.search(path):
            facts.append(Fact("policy_or_disclosure", path, None, None, None, digest))
        if path.endswith("package.json"):
            for name in ("next", "react", "convex", "prisma"):
                if f'"{name}"' in content:
                    frameworks.add(name)
        for number, line in enumerate(content.splitlines(), 1):
            for match in _INTEGRATION.finditer(line):
                facts.append(
                    Fact(
                        "integration_reference",
                        path,
                        number,
                        None,
                        match.group(1).lower(),
                        digest,
                    )
                )
            for match in _IMPORT.finditer(line):
                facts.append(Fact("import", path, number, None, match.group(1), digest))
                if match.group(1).startswith("."):
                    base = posixpath.normpath(
                        posixpath.join(posixpath.dirname(path), match.group(1))
                    )
                    target = next(
                        (
                            candidate
                            for candidate in (
                                base,
                                f"{base}.ts",
                                f"{base}.tsx",
                                f"{base}.js",
                                f"{base}.jsx",
                                f"{base}/index.ts",
                                f"{base}/index.tsx",
                                f"{base}/index.js",
                            )
                            if candidate in files
                        ),
                        None,
                    )
                    if target is not None:
                        edges.append(Edge(path, target, "imports", number))
        language = _LANGUAGES.get(PurePosixPath(path).suffix)
        if language is not None:
            tree = Parser(language).parse(raw)
            pending = [tree.root_node]
            while pending:
                node = pending.pop()
                pending.extend(reversed(node.named_children))
                if node.type in {"function_declaration", "method_definition"}:
                    name_node = node.child_by_field_name("name")
                    if name_node is not None:
                        facts.append(
                            Fact(
                                "function",
                                path,
                                node.start_point.row + 1,
                                raw[name_node.start_byte : name_node.end_byte].decode(
                                    "utf-8"
                                ),
                                None,
                                digest,
                            )
                        )
                if node.type == "call_expression":
                    function = node.child_by_field_name("function")
                    if function is None:
                        continue
                    called = raw[function.start_byte : function.end_byte].decode(
                        "utf-8"
                    )
                    if called in {"eval", "Function"}:
                        hits.append(
                            RuleHit(
                                JAVASCRIPT_DYNAMIC_EXECUTION.id,
                                JAVASCRIPT_DYNAMIC_EXECUTION.version,
                                path,
                                node.start_point.row + 1,
                                called,
                                digest,
                            )
                        )
                    elif called in {"fetch", "axios", "axios.post", "axios.get"}:
                        facts.append(
                            Fact(
                                "outbound_request",
                                path,
                                node.start_point.row + 1,
                                called,
                                None,
                                digest,
                            )
                        )
        if path.endswith(".py"):
            try:
                python_tree = ast.parse(content, filename=path)
            except SyntaxError:
                continue
            for python_node in ast.walk(python_tree):
                if isinstance(python_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    facts.append(
                        Fact(
                            "function",
                            path,
                            python_node.lineno,
                            python_node.name,
                            None,
                            digest,
                        )
                    )
                if (
                    isinstance(python_node, ast.Call)
                    and isinstance(python_node.func, ast.Name)
                    and python_node.func.id in {"eval", "exec"}
                ):
                    hits.append(
                        RuleHit(
                            PYTHON_DYNAMIC_EXECUTION.id,
                            PYTHON_DYNAMIC_EXECUTION.version,
                            path,
                            python_node.lineno,
                            python_node.func.id,
                            digest,
                        )
                    )
    return IntelligencePack(
        source_kind=source_kind,
        source_identifier=source_identifier,
        revision=revision,
        analyzer_version=ANALYZER_VERSION,
        frameworks=tuple(sorted(frameworks)),
        facts=tuple(facts),
        rule_hits=tuple(hits),
        skipped_counts=skipped,
        edges=tuple(edges),
    )
