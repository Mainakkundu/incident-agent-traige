# RB-21 - TLS Certificate Expiry and Client Trust Failures

Use for certificate expiry, chain mismatch, hostname mismatch, or trust store
problems. Symptoms include browser certificate warnings, handshake failures, and
clients reporting x509 verification errors.

This runbook mentions gateway and payment domains because certificates often sit
near ingress, but it does not diagnose payment-api 503s, Postgres connection
pressure, auth-service OOM, Redis eviction, Kafka lag, or S3 throttling.

Checks:

- inspect certificate notBefore and notAfter
- verify SAN entries
- compare ingress secret with certificate manager status
- restart only components that cache certificates after renewal

