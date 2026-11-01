"""Read-only diagnostics for findings that arrive without a diff or prompt.

Run through the ``remediation-diagnostics`` Compose service. It never writes to
the database and never calls a model provider.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import sqlalchemy as sa

from agents.execution.patches import PatchGenerationError, build_patch
from db.session import get_maintenance_engine

WORKER_GRANTS = (
    ("public.remediations", "generation_status"),
    ("public.remediations", "generation_contract_version"),
)
WORKER_TABLES = (
    "private.remediation_patch_artifacts",
    "private.remediation_generation_attempts",
)


def section(title: str) -> None:
    print(f"\n== {title} ==")


def show(connection: sa.Connection, statement: str, **parameters: object) -> None:
    result = connection.execute(sa.text(statement), parameters)
    columns = list(result.keys())
    rows = result.all()
    print(" | ".join(columns))
    for row in rows:
        print(" | ".join("" if value is None else str(value) for value in row))
    if not rows:
        print("(no rows)")


def check_runtime() -> None:
    section("Container: git, /tmp, patch round trip")
    print(f"git: {shutil.which('git') or 'MISSING'}")
    usage = shutil.disk_usage(tempfile.gettempdir())
    print(f"tmp free: {usage.free // 1_048_576} MiB of {usage.total // 1_048_576} MiB")
    try:
        patch = build_patch(
            original={"a.txt": "one\n"},
            updated={"a.txt": "two\n"},
            snapshot={"a.txt": "0" * 64},
        )
        print(f"build_patch smoke test: OK ({len(patch.diff)} bytes)")
    except PatchGenerationError as error:
        print(f"build_patch smoke test: FAILED {error.diagnostic()}")
    except Exception as error:  # noqa: BLE001 - diagnostic must report anything.
        print(f"build_patch smoke test: FAILED {type(error).__name__}: {error}")
    print(f"python tempdir writable: {Path(tempfile.gettempdir()).is_dir()}")


def check_database(connection: sa.Connection, hours: int) -> None:
    section("Migration version")
    show(connection, "SELECT version_num FROM public.alembic_version")

    section("trace_internal grants needed to stage remediations")
    for table, column in WORKER_GRANTS:
        show(
            connection,
            "SELECT :c AS column_name, "
            "has_column_privilege('trace_internal', :t, :c, 'INSERT') AS can_insert",
            t=table,
            c=column,
        )
    for table in WORKER_TABLES:
        show(
            connection,
            "SELECT :t AS table_name, "
            "has_table_privilege('trace_internal', :t, 'INSERT') AS can_insert",
            t=table,
        )

    section(f"Remediations by status (last {hours}h)")
    show(
        connection,
        """
        SELECT generation_status,
               generation_failure ->> 'code' AS failure_code,
               generation_failure ->> 'stage' AS failure_stage,
               prompt_text IS NOT NULL AS has_prompt,
               count(*) AS remediations
        FROM public.remediations
        WHERE created_at > now() - make_interval(hours => :hours)
        GROUP BY 1, 2, 3, 4
        ORDER BY remediations DESC
        """,
        hours=hours,
    )

    section(f"Recent reviews: findings vs remediation rows (last {hours}h)")
    show(
        connection,
        """
        SELECT r.id AS review_id, r.status, r.created_at,
               count(DISTINCT f.id) AS findings,
               count(DISTINCT rem.id) AS remediations
        FROM public.reviews AS r
        JOIN public.findings AS f ON f.review_id = r.id
        LEFT JOIN public.remediations AS rem ON rem.finding_id = f.id
        WHERE r.created_at > now() - make_interval(hours => :hours)
        GROUP BY r.id, r.status, r.created_at
        ORDER BY r.created_at DESC
        LIMIT 10
        """,
        hours=hours,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    arguments = parser.parse_args()
    check_runtime()
    with get_maintenance_engine().connect() as connection:
        check_database(connection, arguments.hours)


if __name__ == "__main__":
    main()
