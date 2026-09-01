# RB-07 - S3 Receipt Upload Throttling and Retry Backlog

Use when receipt attachments fail, notification-svc queues messages for retry,
or object storage returns SlowDown/503. The payment may be successful while the
receipt workflow is degraded.

Signals:

- s3-receipts logs SlowDown or reduce request rate
- PUT receipts batch returns 503 throttled
- notification-svc cannot attach receipt and retries later
- failures cluster around month-end or replay jobs

Checks:

- Inspect s3-receipts WARN and ERROR logs around the first delayed email.
- Check whether a batch regeneration job started.
- Compare retry rate with object write rate.
- Do not blame kafka-broker unless consumer lag exists independently of S3
  failures.

Messy notes:

- notification backlog may appear first in alerts.
- payment-api can be healthy.
- repeated retries can turn a small throttle into a large queue.

Mitigation:

- add exponential backoff with jitter
- slow the regeneration job using a token bucket
- split large object prefixes if hot partitions are suspected
- keep failed receipt IDs for replay after throttling clears

