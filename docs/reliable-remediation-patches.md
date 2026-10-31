# Reliable remediation patches

Reviewers return evidence-backed findings and an implementation prompt. The worker
commits the complete finding batch before running a same-model remediation
specialist for each finding. A remediation failure leaves the finding intact and
does not fail an otherwise successful review.

## Edits and verification

`read_file` returns numbered source, line-ending information, and an opaque
`source_ref`. References are scoped to one specialist attempt, including its two
possible correction turns. Existing-file edits name a reference and an inclusive
replacement range or insertion boundary; new-file edits name a safe relative path.
Models never compute hashes or hunk counts.

Application code retains the exact revision-bound bytes, builds intended output,
asks native Git to serialize the changes, checks and applies the patch in a
disposable workspace, and compares resulting bytes. Applicability uses
`--whitespace=nowarn`; whitespace problems are separate warnings. File deletion,
renames, mode changes, symlinks, submodules, and binary changes are unsupported.
Desktop application additionally rejects filenames that cannot exist on its OS.

## Stored data and consumers

Migration `20261030_0055` adds remediation generation state and private encrypted
patch artifacts and generation diagnostics. Executable patches are immutable and
encrypted through the existing configured credential-encryption adapter; this
feature adds no required environment variables. Artifact AAD binds the owner and
artifact identity. The encrypted payload includes the source revision and exact
original/result hashes for every affected file.

Retain verification keys for immutable artifacts when rotating local encryption
keys. The credential-only rotation job does not rewrite patch artifacts; Vault
continues to decrypt ciphertext written with its retained key versions.

`proposed_diff` is a redacted **display preview**, never executable input. GitHub
publication decrypts the artifact. Updated desktop clients retrieve
`GET /api/v1/remediations/{id}/patch` after the finding is accepted and the review
is completed. The endpoint is owner-scoped and sends `Cache-Control: no-store`.
Desktop verifies the patch and file hashes, preflights all files, and backs up
existing contents before applying. Rollback removes only newly created files
recorded by that operation and restores modified files.

Generation states are `pending`, `running`, `ready`, `failed`, and
`legacy_unverified`. Safe failure metadata is available on remediation responses;
reviews expose `remediation_generation_incomplete` warnings and affected counts.
Each specialist submission records safe diagnostics and execution counts. Source,
patch content, raw provider errors, and raw Git stderr are excluded from these
records. There are at most three specialist submissions per finding.

## Rollout and historical patches

Apply the additive migration before loading the new backend. Upgrade the web UI
and desktop together with the backend; old preview-based application is obsolete.
Rebuild the review worker to load the new runtime. No review should be retried or
new paid run initiated automatically during rollout.

Historical proposed patches are unavailable for application until explicitly
checked against their original revision. With the backend's normal database and
encryption configuration:

```sh
python -m remediations.migrate_patches --owner OWNER_UUID --limit 100
python -m remediations.migrate_patches --owner OWNER_UUID --limit 100 --apply
```

The first command is a dry run. The second encrypts valid exact patches and marks
invalid patches unavailable. Neither calls a model, retries a review, rewrites
redacted anchors, nor changes existing applied/rejected history. Validation can
read the pinned GitHub revision or an uploaded local snapshot.

Shared Git/desktop/preview regression fixtures live in
`frontend/src/components/findings/fixtures/reliable-patches.json`. Patch validity
means the intended bytes can be applied; it does not certify the semantic fix or
that the repository's tests pass.
