# Queueing Convention

This project uses the same RabbitMQ topology for each asynchronous job type. A job starts in its main queue, moves through fixed retry delays after transient failures, and lands in a dead-letter queue after a permanent failure or exhausted retry budget.

## Topology

For a job family named `<domain>.<job>`, create these durable resources:

```text
<domain>.<job>.send
  -> <domain>.<job>.retry.1
  -> <domain>.<job>.retry.2
  -> <domain>.<job>.retry.3
  -> <domain>.<job>.dlx
  -> <domain>.<job>.dead-letter
```

`<domain>.<job>.send` is the main work queue. Consumers take messages from this queue.

Each retry queue has a fixed message TTL. On expiry, RabbitMQ dead-letters the message back to the main exchange and queue. Configure progressively longer delays. The initial email-delivery configuration uses 30 seconds, 5 minutes, and 30 minutes. Keep delays and the maximum attempt count in configuration rather than application code.

The dead-letter exchange (`<domain>.<job>.dlx`) routes terminal messages. The dead-letter queue (`<domain>.<job>.dead-letter`) persists them for operational inspection, alerting, and manual remediation. A worker must not automatically resend messages from a dead-letter queue.

For email delivery, the concrete names are:

```text
trace.email.send
trace.email.retry.1
trace.email.retry.2
trace.email.retry.3
trace.email.dlx
trace.email.dead-letter
```

## Message contract

Messages contain only the identifier needed for the worker to retrieve the durable job record, plus bounded routing metadata such as `attempt` and a schema version. Do not put passwords, access tokens, refresh tokens, recovery tokens, verification tokens, SMTP credentials, or email bodies in RabbitMQ messages.

The application writes the durable job record in the same database transaction as the event that requires work. A dispatcher publishes the job identifier after commit. If RabbitMQ is unavailable, the pending job remains in the database for a later dispatcher attempt.

Workers must make processing idempotent. Redelivery can occur after a process crash or lost acknowledgement. A worker must check the job state before sending an external request and must not repeat a completed operation.

## Publish and consume rules

- Declare exchanges and queues as durable and publish persistent messages.
- Wait for a publisher confirmation before treating a publish as successful.
- Use manual consumer acknowledgements.
- On success, record completion and acknowledge the delivery.
- For a transient failure below the configured retry limit, publish to the next retry queue, wait for confirmation, then acknowledge the original delivery.
- For a permanent failure, malformed message, or exhausted retry limit, route the delivery to the dead-letter exchange and record the terminal failure.
- Set a bounded consumer prefetch value so a worker does not hold more unacknowledged work than it can process.
- Close consumer connections cleanly during shutdown. RabbitMQ will redeliver unacknowledged messages to another healthy worker.

## Failure classification

Treat temporary provider errors, connection failures, and timeouts as retryable. Treat invalid job payloads, missing required records, and invalid recipient addresses as terminal unless the provider identifies the error as temporary.

Record structured audit events with a job identifier, bounded failure reason, attempt count, request identifier when available, and result. Do not log message payloads or secrets.

## Adding a new queue

When adding a new asynchronous capability, define its durable job record, main queue, three retry queues, dead-letter exchange, and dead-letter queue. Add tests that prove successful acknowledgement, retry routing, retry-limit handling, dead-letter routing, consumer redelivery safety, and behavior when RabbitMQ cannot accept a publish.

Use a different topology only when the capability has a documented operational reason, such as strict ordering or a provider-mandated delay policy. Document that exception beside the queue declaration.
