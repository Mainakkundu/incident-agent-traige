# RB-23 - Feature Flag Rollback Checklist

Use when a recently enabled feature flag changes user-visible behavior without a
binary deploy. Evidence normally includes flag audit events, cohort percentage,
and app logs showing the new code path.

This document is intentionally broad. It may mention payment, checkout, auth,
and notifications, but it is not enough to diagnose root cause without a flag
change in the alert window.

Checks:

- flag change timestamp
- rollout percentage
- affected cohort
- whether rollback changes error rate

Do not use this as a substitute for reading deploys, logs, or CMDB dependencies.

