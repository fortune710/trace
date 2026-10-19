# Review-submission contract

`POST /api/v1/reviews` creates a queued review using explicit owner-scoped
agent selections. Its request body contains only `project_id` and a non-empty,
unique `agent_ids` list. Callers must provide a printable `Idempotency-Key`
header of at most 255 characters.

The backend resolves source integrity from the stored project: GitHub projects
must have a full 40-character commit SHA and local projects must have a
32-byte SHA-256 source hash. Client-provided source revisions and selected
categories are rejected. Review-level categories are not stored.

The same builder, idempotency key, and semantic request returns the originally
queued review. Reusing the key for another project or selected-agent set
returns `409`. Only a SHA-256 digest of the key is retained.

Project and agent lookup follows this order: project, then each agent in the
request order. A resource owned by another builder returns `403`; an absent
resource returns `404`; an archived project, disabled agent, or unusable source
snapshot returns `409`. Validation failures return `422`, except a missing or
malformed idempotency header, which returns `400`.

Review creation exposes `queued`, and cancellation transitions a queued review
to `cancelled`. Execution and provider attempts remain deferred. Cancellation
also terminally cancels any unpublished dispatch jobs; a future consumer must
verify the durable review status before it starts execution.

Review creation writes one private dispatch job per review-agent assignment in
the same transaction. The internal review-dispatch worker claims due jobs,
publishes `ReviewDispatchMessageV1` to the durable `trace.review.dispatch.v1`
queue, and records `pending`, `processing`, `published`, or `dead_letter`.
Broker failures use bounded database-backed retry; accepted-but-unrecorded
publishes may repeat, so delivery is at least once.

The message payload contains only `review_id`, `review_agent_id`, `owner_id`,
`idempotency_id`, and `version`; it must never contain credentials, raw
idempotency keys, source contents, local paths, tokens, or provider payloads.
