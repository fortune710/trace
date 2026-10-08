import ast
from pathlib import Path

BACKEND = Path(__file__).parents[1]
FEATURE_MODEL_MODULES = (
    "agents/models.py",
    "artifacts/models.py",
    "audit/models.py",
    "auth/models.py",
    "credentials/models.py",
    "external_repositories/models.py",
    "findings/models.py",
    "projects/models.py",
    "remediations/models.py",
    "reviews/models.py",
    "users/models.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_legacy_models_module_contains_no_table_declarations() -> None:
    tree = ast.parse((BACKEND / "db/models.py").read_text())
    assert not any(isinstance(node, ast.ClassDef) for node in tree.body)
    assert "db.model_registry" not in _imports(BACKEND / "db/models.py")


def test_feature_models_do_not_depend_on_application_layers() -> None:
    forbidden = {"routes", "service", "repository", "db.model_registry"}
    for relative_path in FEATURE_MODEL_MODULES:
        imports = _imports(BACKEND / relative_path)
        assert not any(
            imported.split(".")[-1] in forbidden or imported in forbidden
            for imported in imports
        ), relative_path


def test_production_code_no_longer_imports_legacy_models() -> None:
    offenders: list[str] = []
    for path in BACKEND.rglob("*.py"):
        if (
            "tests" in path.parts
            or ".venv" in path.parts
            or path == BACKEND / "db/models.py"
        ):
            continue
        if "db.models" in path.read_text():
            offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == []
