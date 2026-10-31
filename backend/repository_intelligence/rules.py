"""Versioned AST rule catalog. Hits are inspection candidates, never findings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StaticRule:
    id: str
    version: int
    languages: tuple[str, ...]
    specialties: tuple[str, ...]
    severity: str


JAVASCRIPT_DYNAMIC_EXECUTION = StaticRule(
    id="javascript.dynamic_execution",
    version=1,
    languages=("javascript", "typescript"),
    specialties=("security", "engineering"),
    severity="medium",
)

PYTHON_DYNAMIC_EXECUTION = StaticRule(
    id="python.dynamic_execution",
    version=1,
    languages=("python",),
    specialties=("security", "engineering"),
    severity="medium",
)

RULES = (JAVASCRIPT_DYNAMIC_EXECUTION, PYTHON_DYNAMIC_EXECUTION)
