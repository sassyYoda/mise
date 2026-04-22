# Contributing

## Async Hygiene Rules (Pitfall 16)

The following patterns are BANNED in `services/` and `shared/` and will cause CI to fail:

- `import requests` — use `httpx.AsyncClient` (D-05)
- `time.sleep(` — use `asyncio.sleep(`
- `import redis\n` or `from redis import` without `.asyncio` submodule — use `import redis.asyncio as redis` (D-03)

CI enforcement:
```
grep -rn "import requests" services/ shared/ && echo "BANNED: use httpx.AsyncClient" && exit 1 || true
grep -rn "time\.sleep(" services/ shared/ && echo "BANNED: use asyncio.sleep" && exit 1 || true
```

## Alembic

NEVER run `alembic revision --autogenerate` after a hypertable exists. Always hand-write hypertable migrations using `op.execute("SELECT create_hypertable(...)")`. See migrations/README.md.

## Redis Atomicity (Pitfall 7)

NEVER use `SETNX` + `EXPIRE` as two separate commands. Always use the single atomic `SET key value NX EX ttl` form. The codebase has zero occurrences of `SETNX` — keep it that way.
