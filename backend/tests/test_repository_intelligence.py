import base64
import hashlib
from pathlib import Path

import pytest

from repository_intelligence.local_snapshot import decode_snapshot_entries
from repository_intelligence.local_source import LocalReviewSourceAccess
from repository_intelligence.scanner import scan_files

FIXTURES = Path(__file__).resolve().parents[1] / "repository_intelligence" / "fixtures"


def test_typescript_ast_emits_candidate_calls_without_treating_comments_as_calls() -> (
    None
):
    pack = scan_files(
        source_kind="github",
        source_identifier="123",
        revision="a" * 40,
        files={
            "app/api/payments/route.ts": (
                b'// eval("ignored")\n'
                b'import { charge } from "./payments";\n'
                b'export async function POST() { return fetch("https://example.test"); }\n'
            ),
            "app/api/payments/payments.ts": b"export const charge = () => true;",
        },
    )
    assert any(fact.kind == "function" and fact.symbol == "POST" for fact in pack.facts)
    assert any(fact.kind == "outbound_request" for fact in pack.facts)
    assert not any(
        hit.rule_id == "javascript.dynamic_execution" for hit in pack.rule_hits
    )
    assert any(edge.to_path == "app/api/payments/payments.ts" for edge in pack.edges)


def test_javascript_ast_dynamic_execution_hit_is_versioned() -> None:
    pack = scan_files(
        source_kind="github",
        source_identifier="123",
        revision="a" * 40,
        files={"server.js": b"const value = eval(userInput);"},
    )
    assert [(hit.rule_id, hit.version, hit.line) for hit in pack.rule_hits] == [
        ("javascript.dynamic_execution", 1, 1)
    ]


def test_desktop_manifest_recomputes_digest_and_rejects_traversal() -> None:
    content = b"old\n"
    digest = hashlib.sha256(b"trace-local-source-snapshot\0v1\0")
    digest.update(b"F")
    digest.update((5).to_bytes(8, "big"))
    digest.update(b"a.txt")
    digest.update(hashlib.sha256(content).digest())
    entries = [
        {
            "path": "a.txt",
            "directory": False,
            "content_base64": base64.b64encode(content).decode(),
        }
    ]
    assert decode_snapshot_entries(entries, digest.hexdigest()) == {"a.txt": content}
    with pytest.raises(ValueError, match="snapshot_digest_mismatch"):
        decode_snapshot_entries(entries, "0" * 64)
    with pytest.raises(ValueError, match="snapshot_path_invalid"):
        decode_snapshot_entries(
            [{**entries[0], "path": "../a.txt"}], digest.hexdigest()
        )


def _manifest_digest(records: list[tuple[str, bytes | None]]) -> str:
    digest = hashlib.sha256(b"trace-local-source-snapshot\0v1\0")
    for path, content in sorted(records):
        digest.update(b"F")
        digest.update(len(path.encode()).to_bytes(8, "big"))
        digest.update(path.encode())
        digest.update(hashlib.sha256(content or b"").digest())
    return digest.hexdigest()


def test_oversized_and_binary_files_are_verified_by_hash_and_never_stored() -> None:
    text = b"const value = 1;\n"
    large = b"x" * 300_000
    image = b"\x89PNG\x00\x01"
    digest = _manifest_digest(
        [("a.ts", text), ("bundle.min.js", large), ("logo.png", image)]
    )
    entries: list[dict[str, object]] = [
        {
            "path": "a.ts",
            "directory": False,
            "content_base64": base64.b64encode(text).decode(),
        },
        {
            "path": "bundle.min.js",
            "directory": False,
            "content_sha256": hashlib.sha256(large).hexdigest(),
        },
        {
            "path": "logo.png",
            "directory": False,
            "content_sha256": hashlib.sha256(image).hexdigest().upper(),
        },
    ]

    # The digest covers every file, but only readable text is returned for storage.
    assert decode_snapshot_entries(entries, digest) == {"a.ts": text}

    changed = [{**entries[1], "content_sha256": hashlib.sha256(b"y").hexdigest()}]
    with pytest.raises(ValueError, match="snapshot_digest_mismatch"):
        decode_snapshot_entries([entries[0], *changed, entries[2]], digest)


@pytest.mark.parametrize(
    "entry",
    [
        {"content_base64": "AA==", "content_sha256": "0" * 64},
        {"content_sha256": "not-a-hash"},
        {"content_sha256": "0" * 63},
        {"content_sha256": 7},
        {},
    ],
)
def test_hash_only_entries_must_be_well_formed(entry: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="snapshot_entry_invalid"):
        decode_snapshot_entries(
            [{"path": "a.bin", "directory": False, **entry}], "0" * 64
        )


def test_directories_cannot_carry_content_hashes() -> None:
    with pytest.raises(ValueError, match="snapshot_entry_invalid"):
        decode_snapshot_entries(
            [{"path": "src", "directory": True, "content_sha256": "0" * 64}],
            "0" * 64,
        )


def test_local_source_diff_validation_uses_uploaded_revision() -> None:
    reader = LocalReviewSourceAccess({"a.txt": b"old\n"})
    diff = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    assert reader.validate_diff(diff=diff, log_context=None)
    assert not LocalReviewSourceAccess({"a.txt": b"changed\n"}).validate_diff(
        diff=diff, log_context=None
    )


@pytest.mark.parametrize("language", ["javascript", "python"])
def test_ast_rule_positive_and_negative_fixtures(language: str) -> None:
    suffix = ".ts" if language == "javascript" else ".py"
    for expected, label in ((True, "positive"), (False, "negative")):
        raw = (FIXTURES / f"{language}_dynamic_execution_{label}{suffix}").read_bytes()
        pack = scan_files(
            source_kind="github",
            source_identifier="1",
            revision="a" * 40,
            files={f"source{suffix}": raw},
        )
        assert bool(pack.rule_hits) is expected


def test_scanner_is_deterministic_and_keeps_source_out_of_facts() -> None:
    files = {
        "app/api/user/route.ts": b'import { clerkClient } from "@clerk/nextjs";\n',
        "app/privacy/page.tsx": b"export default function Privacy() { return null; }\n",
        "src/risky.py": b"def execute(value):\n    return eval(value)\n",
        "node_modules/secret.js": b"const token = 'private';\n",
    }
    arguments = {
        "source_kind": "github",
        "source_identifier": "123",
        "revision": "a" * 40,
        "files": files,
    }

    pack = scan_files(**arguments)

    assert pack == scan_files(**arguments)
    assert any(fact.kind == "route" for fact in pack.facts)
    assert any(fact.kind == "policy_or_disclosure" for fact in pack.facts)
    assert any(hit.rule_id == "python.dynamic_execution" for hit in pack.rule_hits)
    assert pack.skipped_counts["excluded"] == 1
    assert "private" not in repr(pack)


def test_scanner_rejects_unsafe_paths_and_large_or_binary_files() -> None:
    pack = scan_files(
        source_kind="local",
        source_identifier="local-id",
        revision="b" * 64,
        files={
            "../escape.py": b"eval('x')",
            "src/binary.py": b"\0",
            "src/large.py": b"x" * 256_001,
        },
    )

    assert not pack.facts
    assert not pack.rule_hits
    assert pack.skipped_counts["excluded"] == 1
    assert pack.skipped_counts["binary"] == 1
    assert pack.skipped_counts["oversized"] == 1
