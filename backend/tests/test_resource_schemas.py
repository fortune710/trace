from __future__ import annotations

import pytest
from pydantic import ValidationError

from resources.schemas import LocalRemediationApply


def test_local_remediation_paths_reject_unsafe_values() -> None:
    file = {
        "file_path": "src/example.py",
        "backup_reference": "backups/example.py",
        "source_hash": "a" * 64,
        "applied_hash": "b" * 64,
    }
    payload = {"files": [file]}

    request = LocalRemediationApply.model_validate(payload)

    assert request.files[0].file_path == "src/example.py"
    assert request.files[0].backup_reference == "backups/example.py"

    for field, unsafe_path in (
        ("file_path", "/etc/passwd"),
        ("file_path", "src/../secrets.txt"),
        ("backup_reference", r"backups\\example.py"),
    ):
        invalid_payload = {"files": [{**file, field: unsafe_path}]}

        with pytest.raises(ValidationError):
            LocalRemediationApply.model_validate(invalid_payload)

    with pytest.raises(ValidationError):
        LocalRemediationApply.model_validate({"files": [file, file]})
