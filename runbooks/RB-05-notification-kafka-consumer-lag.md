# RB-05 - Notification Consumer Lag and Rebalance Loop

Use when notifications are delayed but the broker is still reachable. The root
is often notification-svc consumer behavior, not kafka-broker hardware.

Clues:

- consumer group notifications lag increasing
- SMS/email provider call takes tens of seconds
- consumer poll interval exceeded
- rebalance triggered repeatedly
- payment events are produced normally, but receipts arrive late

Checks:

- Compare producer rate with consumer lag.
- Search notification-svc logs for provider timeout, blocked worker, retry
  storm, or dead-letter queue.
- Check whether only one partition or one provider path is slow.
- Confirm kafka-broker disk/network errors before blaming the broker.

Do not confuse:

- A broker rebalance log is not automatically broker root cause.
- s3 receipt failures can also delay notification, but they usually show PUT
  throttling or object errors.
- payment-api success logs mean the customer payment may be fine while the
  notification workflow is degraded.

Mitigation:

- increase consumer concurrency cautiously
- add timeout around provider calls
- pause the poison path or route to retry topic
- record lag before and after mitigation in the incident ticket

