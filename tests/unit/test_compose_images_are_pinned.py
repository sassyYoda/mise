"""Unit: IN-04 — every compose image is pinned, and the obsolete `version:` key is gone.

`provectuslabs/kafka-ui:latest` made `make up` non-reproducible — in a phase whose whole point
was pinning the Kafka image after `bitnami/kafka:3.8` was withdrawn from Docker Hub (D-56).
`version: "3.9"` is ignored by Compose v2 and emits a deprecation warning on every command.
"""
from __future__ import annotations

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "ops" / "docker-compose.yml"
IMAGE_LINE = re.compile(r"^\s*image:\s*(\S+)\s*$", re.MULTILINE)


def test_every_image_is_pinned_to_an_explicit_tag() -> None:
    images = IMAGE_LINE.findall(COMPOSE.read_text())
    assert images, "no image: lines found — has the compose file moved?"
    for image in images:
        assert ":" in image, f"{image} has no tag at all"
        assert not image.endswith(":latest"), f"{image} is not reproducible"


def test_the_obsolete_version_key_is_absent() -> None:
    for line in COMPOSE.read_text().splitlines():
        assert not line.startswith("version:"), f"Compose v2 ignores {line!r}"
