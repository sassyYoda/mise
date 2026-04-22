# Migrations

## Rules

**NEVER run `alembic revision --autogenerate` after a hypertable exists.**

TimescaleDB wraps the `time` column in internal chunk management structures.
If autogenerate scans the live database, it will try to drop/recreate the time index
and corrupt the hypertable (Alembic issue #1465, Pitfall 12 in PITFALLS.md).

Always hand-write hypertable migrations using:
```python
op.execute(
    "SELECT create_hypertable('table_name', 'time', "
    "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
)
```

## Migration Order

| Revision | Table / Action |
|----------|----------------|
| 0001_extensions | CREATE EXTENSION timescaledb, pgcrypto |
| 0002_create_users | users table |
| 0003_create_restaurants | restaurants table |
| 0004_create_watchlist_entries | watchlist_entries table |
| 0005_create_notification_log | notification_log table |
| 0006_create_availability_events_hypertable | availability_events hypertable (chunk=1d) |
| 0007_create_poll_log_hypertable | poll_log hypertable (chunk=1d) |
