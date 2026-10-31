import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from agents.execution.diagnostics import PatchGenerationError
from agents.execution.patches import (
    CreateEdit,
    InsertEdit,
    PatchIntentBatch,
    ReplaceEdit,
    build_patch,
    generate_patch,
)
from agents.execution.source import patch_paths, source_lines
from agents.execution.tools import ToolExecutionContext
from external_repositories.service import ReviewSourceFileError
from remediations.migrate_patches import validate_legacy_patch


def context(files, kind="github"):
    class Reader:
        def read_file(self, *, path, **kwargs):
            if path not in files:
                raise ReviewSourceFileError("path_not_found")
            return files[path]

    return ToolExecutionContext(
        owner_id=uuid4(),
        source_kind=kind,
        source_identifier="123",
        source_revision="a" * 40,
        repository_access=Reader(),
        review_id=uuid4(),
    )


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("app.py", "old\n", "new\n"),
        ("my app.py", "old", "new"),
        ("日本語.py", "old\r\n", "new\r\n"),
        ('say "hello".py', "old\n", "new\n"),
        ("mixed.py", "one\r\ntwo\nlast", "one\r\nnew\nlast"),
        ("separator.py", "a\u2028b\n", "c\u2028d\n"),
        ("empty.py", "old\n", ""),
    ],
)
def test_native_git_roundtrip(name, old, new):
    patch = build_patch(
        original={name: old}, updated={name: new}, snapshot={"revision": "a" * 40}
    )
    assert patch.diff.startswith("diff --git ")
    assert patch_paths(patch.diff) == [name]
    assert patch.files[0].operation == "replace"


@pytest.mark.parametrize("content", ["", "new", "new\r\n", "new \n"])
@pytest.mark.parametrize("kind", ["github", "local"])
def test_create_and_whitespace_warning(content, kind):
    patch = generate_patch(
        intents=PatchIntentBatch(
            edits=[CreateEdit(path="new dir/privacy.md", content=content)]
        ),
        context=context({}, kind),
    )
    assert patch.files[0].original_sha256 is None
    assert patch.files[0].operation == "create"
    assert ("added_whitespace_errors" in patch.warnings) == (content == "new \n")


def test_source_refs_and_range_integrity():
    ctx = context({"app.py": "one\r\ntwo\nlast"})
    ref = ctx.register_source(path="app.py", content="one\r\ntwo\nlast")
    edits = PatchIntentBatch(
        edits=[
            ReplaceEdit(source_ref=ref, start_line=2, end_line=2, replacement="new\n"),
            InsertEdit(source_ref=ref, before_line=1, replacement="first\r\n"),
        ]
    )
    patch = generate_patch(intents=edits, context=ctx)
    assert len(patch.files) == 1
    with pytest.raises(PatchGenerationError, match="invalid_source_reference"):
        generate_patch(intents=edits, context=context({"app.py": "one\r\ntwo\nlast"}))
    with pytest.raises(PatchGenerationError, match="invalid_source_reference"):
        generate_patch(intents=edits, context=replace(ctx, attempt_id=uuid4()))
    edits.edits[0].end_line = 99
    with pytest.raises(PatchGenerationError, match="invalid_line_range") as error:
        generate_patch(intents=edits, context=ctx)
    assert error.value.detail.expected_count == 3


def test_unicode_separator_is_not_a_source_line():
    assert source_lines("a\u2028b\r\nlast") == ["a\u2028b\r\n", "last"]


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        ".git/config",
        "a/.GIT/config",
        "a\\b",
        "a\tb",
        "C:/file",
    ],
)
def test_unsafe_paths(path):
    with pytest.raises(PatchGenerationError, match="unsafe_path"):
        generate_patch(
            intents=PatchIntentBatch(edits=[CreateEdit(path=path, content="new")]),
            context=context({}),
        )


def test_multiple_hunks_and_files():
    a = "".join(f"line{i}\n" for i in range(40))
    changed = a.replace("line2\n", "changed2\n").replace("line35\n", "changed35\n")
    patch = build_patch(
        original={"a": a, "b": None},
        updated={"a": changed, "b": "created"},
        snapshot={},
    )
    assert patch.diff.count("@@ -") == 3


def test_no_change_is_explicit():
    with pytest.raises(PatchGenerationError, match="no_change"):
        build_patch(original={"a": "x"}, updated={"a": "x"}, snapshot={})


def test_shared_desktop_and_preview_fixtures():
    fixtures = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "frontend/src/components/findings/fixtures/reliable-patches.json"
        ).read_text()
    )
    for fixture in fixtures:
        files = (
            {} if fixture["before"] is None else {fixture["path"]: fixture["before"]}
        )
        patch = validate_legacy_patch(
            fixture["diff"], context(files).source_reader(), {}
        )
        assert (
            patch.files[0].result_sha256
            == hashlib.sha256(fixture["after"].encode()).hexdigest()
        )
        from agents.execution.tools import validate_diff_for_review
        from repository_intelligence.local_source import LocalReviewSourceAccess

        ctx = context(files, "local")
        ctx = replace(
            ctx,
            repository_access=LocalReviewSourceAccess(
                {path: value.encode() for path, value in files.items()}
            ),
        )
        assert (
            validate_diff_for_review(source="local", diff=fixture["diff"], context=ctx)[
                "valid"
            ]
            is True
        )


def test_schema_corrections_stop_after_three_submissions(monkeypatch):
    import agents.execution.agent as module
    from agents.execution.agent import (
        Agent,
        DiffAgent,
        ReviewFindingOutput,
        ReviewTarget,
    )

    calls = []
    submissions = []

    class Runtime:
        def invoke(self, inputs, *, context, config):
            calls.append(inputs["messages"])
            config["callbacks"][0].on_chat_model_start()
            return {
                "structured_response": {
                    "edits": [{"operation": "replace", "start_line": "bad"}]
                }
            }

    monkeypatch.setattr(Agent, "_model", lambda self: object())
    monkeypatch.setattr(module, "create_agent", lambda **kwargs: Runtime())
    with pytest.raises(PatchGenerationError, match="invalid_edit_schema"):
        DiffAgent(provider="openai", model="test").run(
            finding=ReviewFindingOutput(
                severity="high",
                title="Issue",
                explanation="Evidence",
                prompt_text="Fix",
            ),
            review_target=ReviewTarget("github", "123", "a" * 40),
            tool_context=context({}),
            on_submission=lambda **values: submissions.append(values),
        )
    assert len(calls) == len(submissions) == 3
    assert all(item["model_call_count"] == 1 for item in submissions)
    assert "invalid_edit_schema" in calls[1][-1].content


def test_overlapping_edits_and_binary_contents_are_rejected():
    ctx = context({"a": "first\nsecond\n"})
    ref = ctx.register_source(path="a", content="first\nsecond\n")
    with pytest.raises(PatchGenerationError, match="overlapping_edits"):
        generate_patch(
            context=ctx,
            intents=PatchIntentBatch(
                edits=[
                    ReplaceEdit(
                        source_ref=ref, start_line=1, end_line=2, replacement="all\n"
                    ),
                    ReplaceEdit(
                        source_ref=ref, start_line=2, end_line=2, replacement="part\n"
                    ),
                ]
            ),
        )
    with pytest.raises(PatchGenerationError, match="binary_patch_unsupported"):
        build_patch(original={"a": "binary\0data"}, updated={"a": "clean"}, snapshot={})


def test_serialization_is_deterministic_and_respects_tracked_ignored_files():
    original = {".gitignore": "app.py\n", "app.py": "old\n"}
    updated = {".gitignore": "app.py\n", "app.py": "new\n"}
    first = build_patch(original=original, updated=updated, snapshot={})
    second = build_patch(original=original, updated=updated, snapshot={})
    assert first == second
    assert [item.path for item in first.files] == ["app.py"]


def scripted_specialist(monkeypatch, replies):
    """Drive the real LangChain agent loop with a local fake chat model.

    Each reply is the list of edit batches the model submits as parallel tool calls.
    """
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from agents.execution.agent import Agent

    conversations = []

    class ScriptedModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "scripted"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            conversations.append(list(messages))
            calls = [
                {
                    "name": "PatchIntentBatch",
                    "args": batch,
                    "id": f"call-{len(conversations)}-{index}",
                }
                for index, batch in enumerate(replies[len(conversations) - 1])
            ]
            return ChatResult(
                generations=[
                    ChatGeneration(message=AIMessage(content="", tool_calls=calls))
                ]
            )

    monkeypatch.setattr(Agent, "_model", lambda self: ScriptedModel())
    return conversations


def run_specialist(ctx):
    from agents.execution.agent import DiffAgent, ReviewFindingOutput, ReviewTarget

    submissions = []
    finding = ReviewFindingOutput(
        severity="high", title="Issue", explanation="Evidence", prompt_text="Fix"
    )
    try:
        patch = DiffAgent(provider="openai", model="test").run(
            finding=finding,
            review_target=ReviewTarget("github", "123", "a" * 40),
            tool_context=ctx,
            on_submission=lambda **values: submissions.append(values),
        )
    except PatchGenerationError:
        patch = None
    return patch, submissions


def replace_batch(reference, **overrides):
    edit = {
        "operation": "replace",
        "source_ref": reference,
        "start_line": 2,
        "end_line": 2,
        "replacement": "TWO\n",
    }
    return {"edits": [{**edit, **overrides}]}


def test_corrections_keep_the_conversation_and_previous_edits(monkeypatch):
    ctx = context({})
    reference = ctx.register_source(path="app.py", content="one\ntwo\n")
    conversations = scripted_specialist(
        monkeypatch,
        [
            [replace_batch(reference, start_line=9, end_line=9)],
            [{"edits": [{"operation": "replace", "start_line": "bad"}]}],
            [replace_batch(reference)],
        ],
    )

    patch, submissions = run_specialist(ctx)

    assert patch is not None and patch.files[0].path == "app.py"
    assert [
        (item["submission_number"], (item["diagnostic"] or {}).get("code"))
        for item in submissions
    ] == [(1, "invalid_line_range"), (2, "invalid_edit_schema"), (3, None)]
    # Each submission continues the same conversation rather than restarting it.
    assert [len(item) for item in conversations] == [2, 5, 8]
    third = conversations[2]
    assert third[2].tool_calls[0]["args"]["edits"][0]["start_line"] == 9
    assert "invalid_line_range" in third[4].content
    assert '"start_line": 9' in third[4].content
    assert "invalid_edit_schema" in third[-1].content


def test_schema_failures_name_the_field_and_rule_but_not_the_value(monkeypatch):
    ctx = context({})
    reference = ctx.register_source(path="app.py", content="one\ntwo\n")
    secret = "sk-" + "Z" * 24
    conversations = scripted_specialist(
        monkeypatch,
        [
            [
                {
                    "edits": [
                        {
                            "operation": "replace",
                            "source_ref": reference,
                            "start_line": secret,
                            "end_line": 2,
                            "replacement": "x\n",
                        }
                    ]
                }
            ],
            [replace_batch(reference)],
        ],
    )

    patch, submissions = run_specialist(ctx)

    assert patch is not None
    diagnostic = submissions[0]["diagnostic"]
    assert diagnostic["code"] == "invalid_edit_schema"
    assert diagnostic["fields"] == ["edits.0.replace.start_line: int_parsing"]
    # Stored diagnostics carry the field path and rule, never the submitted value.
    assert secret not in json.dumps(diagnostic)
    # The model is told which field to fix, in the tool result and the correction.
    tool_feedback = [
        message.content
        for message in conversations[1]
        if type(message).__name__ == "ToolMessage"
    ]
    assert tool_feedback == [
        "Invalid edit schema: edits.0.replace.start_line: int_parsing"
    ]
    assert "edits.0.replace.start_line: int_parsing" in conversations[1][-1].content


def test_several_edit_batches_in_one_reply_get_their_own_diagnostic(monkeypatch):
    ctx = context({})
    reference = ctx.register_source(path="app.py", content="one\ntwo\n")
    conversations = scripted_specialist(
        monkeypatch,
        [
            [
                replace_batch(reference),
                replace_batch(reference, start_line=1, end_line=1),
            ],
            [replace_batch(reference)],
        ],
    )

    patch, submissions = run_specialist(ctx)

    assert patch is not None
    diagnostic = submissions[0]["diagnostic"]
    assert diagnostic["code"] == "multiple_edit_batches"
    assert (diagnostic["actual_count"], diagnostic["expected_count"]) == (2, 1)
    assert [
        message.content
        for message in conversations[1]
        if type(message).__name__ == "ToolMessage"
    ] == ["Return exactly one edit batch containing every edit for this finding."] * 2


def test_legacy_patch_is_stored_as_the_canonical_verified_patch():
    canonical = build_patch(
        original={"app.py": "old\n"}, updated={"app.py": "new\n"}, snapshot={}
    )
    # Git applies this, but the index line is not what Git would serialize.
    legacy = re.sub(r"index \S+\.\.\S+", "index 1234567..89abcde", canonical.diff)
    assert legacy != canonical.diff

    stored = validate_legacy_patch(
        legacy, context({"app.py": "old\n"}).source_reader(), {}
    )

    assert stored.diff == canonical.diff
    assert "1234567" not in stored.diff
    assert stored.sha256 == hashlib.sha256(stored.diff.encode()).hexdigest()
    assert stored.files == canonical.files
