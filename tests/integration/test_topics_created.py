"""Integration: FOUND-04 — all 5 Kafka topics exist with correct retention. Implemented by Plan 02.

This test requires a container runtime (Docker/Podman) to spin up the KafkaContainer
testcontainers fixture. It is skipped automatically if no runtime is available.
"""
import asyncio
import os

import pytest

pytestmark = pytest.mark.integration

# Named Symbols (D-27) — authoritative topic list and retention.ms values
EXPECTED_RETENTION_MS = {
    "availability.raw": 86_400_000,         # 24h
    "availability.events": 604_800_000,     # 7d
    "polls.completed": 604_800_000,         # 7d
    "notifications.queued": 2_592_000_000,  # 30d
    "notifications.sent": 2_592_000_000,    # 30d
}


async def _run_create_topics(bootstrap: str) -> None:
    """Invoke the module-level main() from scripts/create_topics.py."""
    # Import inside the coro so pytest collection never fails if aiokafka missing
    import importlib.util
    import pathlib

    script = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "create_topics.py"
    spec = importlib.util.spec_from_file_location("create_topics", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Override the module-level BOOTSTRAP_SERVERS via env before exec
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = bootstrap
    spec.loader.exec_module(mod)
    await mod.main()


async def _describe_topic_configs(bootstrap: str, topic_names: list[str]) -> dict[str, dict[str, str]]:
    """Return {topic: {config_name: config_value}} using AIOKafkaAdminClient."""
    from aiokafka.admin import AIOKafkaAdminClient, ConfigResource, ConfigResourceType

    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        resources = [ConfigResource(ConfigResourceType.TOPIC, name) for name in topic_names]
        result = await admin.describe_configs(resources)
        out: dict[str, dict[str, str]] = {}
        # Shape varies across aiokafka versions — handle both tuple/list results
        for entry in result:
            # aiokafka returns a list of DescribeConfigsResponse; unpack defensively
            if hasattr(entry, "resources"):
                for r in entry.resources:
                    name = r[3] if isinstance(r, (list, tuple)) else getattr(r, "resource_name", None)
                    configs = r[4] if isinstance(r, (list, tuple)) else getattr(r, "config_entries", [])
                    cfg_dict = {}
                    for c in configs:
                        if isinstance(c, (list, tuple)):
                            cfg_dict[c[0]] = c[1]
                        else:
                            cfg_dict[getattr(c, "config_names", getattr(c, "name", ""))] = getattr(
                                c, "config_value", getattr(c, "value", "")
                            )
                    if name:
                        out[name] = cfg_dict
        return out
    finally:
        await admin.close()


def test_all_five_topics_have_retention(kafka_container):
    """
    Run scripts/create_topics.py against testcontainers Kafka.
    Assert all 5 topics exist with correct retention.ms.
    Run twice; assert idempotency (no error).
    """
    bootstrap = kafka_container.get_bootstrap_server()

    # First run — creates topics
    asyncio.run(_run_create_topics(bootstrap))

    # Second run — idempotent no-op
    asyncio.run(_run_create_topics(bootstrap))

    # Verify all 5 topics exist with correct retention
    configs = asyncio.run(_describe_topic_configs(bootstrap, list(EXPECTED_RETENTION_MS.keys())))

    assert set(configs.keys()) == set(EXPECTED_RETENTION_MS.keys()), (
        f"Missing topics. Expected {set(EXPECTED_RETENTION_MS)}, got {set(configs)}"
    )
    for topic, expected_ms in EXPECTED_RETENTION_MS.items():
        actual = configs[topic].get("retention.ms")
        assert actual is not None, f"{topic}: retention.ms missing from describe_configs response"
        assert int(actual) == expected_ms, (
            f"{topic}: retention.ms mismatch. Expected {expected_ms}, got {actual}"
        )
