# RB-20 - Linux Disk or Inode Cleanup for Utility Hosts

This is a generic operations note for non-application utility hosts. Use it for
disk-full alerts, inode exhaustion, rotated log buildup, or temporary file leaks.
It is not specific to payment-api, GLPI, Postgres max_connections, auth token
cache, Kafka consumer lag, or receipt uploads.

Checks:

- df -h and df -i
- largest directories under /var/log and /tmp
- rotated compressed files older than retention
- journald vacuum settings

Avoid deleting database directories or live object storage cache without owner
approval.

