"""Unit: the human-gated venue-id resolver refuses safely and edits surgically (D-63a).

`scripts/resolve_resy_venue_ids.py` is the one step in this phase that genuinely needs a
human: it needs a real `RESY_API_KEY` captured from Chrome DevTools, and the endpoint it
calls is `[ASSUMED]` (research A4). None of that makes it untestable. What IS testable, and
what these tests pin, is everything the script does BEFORE and AFTER the network call:

  * it refuses without credentials rather than half-running (exit 2, the
    `check_poll_success.py` convention),
  * a `--dry-run` makes ZERO network calls and leaves the seed file byte-identical,
  * it never prints the API key (T-03-11),
  * it refuses to write outside the repository (T-03-13),
  * and its YAML edit is surgical: the integer lands on the right line, the
    `resy_url_slug` survives, and the file's extensive comment blocks — which
    `yaml.safe_dump` would destroy — are still there afterwards.

The network call itself is one small function (`_resolve_one`) so the `[ASSUMED]` shape can
be corrected in one place after the DevTools capture. Every test here substitutes it.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import scripts.resolve_resy_venue_ids as resolver

REPO_ROOT = Path(__file__).resolve().parents[2]

SAMPLE_YAML = textwrap.dedent(
    """\
    # scripts/seed/restaurants.yml
    # A comment block that yaml.safe_dump would silently delete.
    #
    # Schema: name, slug, ..., resy_url_slug (string), resy_venue_id (int | null)

    restaurants:
      - name: "Carbone"
        slug: "carbone-nyc"
        neighborhood: "Greenwich Village"
        cuisine: "Italian-American"
        price_tier: 4
        cover_photo_url: "https://placeholder.mise.place/carbone.jpg"
        opentable_rid: 900000001  # TODO(01-05 spike)
        resy_url_slug: "carbone-new-york-new-york"
        resy_venue_id: null  # TODO(03 spike): numeric venue_id from Resy DevTools

      - name: "Lilia"
        slug: "lilia-williamsburg"
        neighborhood: "Williamsburg"
        cuisine: "Italian"
        price_tier: 3
        cover_photo_url: "https://placeholder.mise.place/lilia.jpg"
        opentable_rid: 900000002
        resy_url_slug: "lilia-brooklyn"
        resy_venue_id: null  # TODO(03 spike)

      - name: "Gramercy Tavern"
        slug: "gramercy-tavern"
        neighborhood: "Flatiron"
        cuisine: "New American"
        price_tier: 4
        cover_photo_url: "https://placeholder.mise.place/gt.jpg"
        opentable_rid: 900000003
        resy_venue_id: null

      - name: "Already Resolved"
        slug: "already-resolved"
        neighborhood: "SoHo"
        cuisine: "Test"
        price_tier: 2
        cover_photo_url: "https://placeholder.mise.place/ar.jpg"
        opentable_rid: 900000004
        resy_url_slug: "already-resolved-new-york"
        resy_venue_id: 12345
    """
)

API_KEY = "super-secret-resy-key-do-not-print"


@pytest.fixture
def seed_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A seed file inside a fake repository root, so path containment is exercised."""
    repo = tmp_path / "repo"
    (repo / "scripts" / "seed").mkdir(parents=True)
    path = repo / "scripts" / "seed" / "restaurants.yml"
    path.write_text(SAMPLE_YAML)
    monkeypatch.setattr(resolver, "REPO_ROOT", repo)
    monkeypatch.setattr(resolver, "DEFAULT_YAML_PATH", path)
    return path


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESY_API_KEY", raising=False)
    monkeypatch.delenv("RESY_API_BASE", raising=False)


@pytest.fixture
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any call into the one network-touching function is an immediate test failure."""

    async def _explode(*args: object, **kwargs: object) -> int:
        raise AssertionError("the resolver made a network call when it must not have")

    monkeypatch.setattr(resolver, "_resolve_one", _explode)


# --------------------------------------------------------------------------------------
# Parsing the work set
# --------------------------------------------------------------------------------------


def test_targets_are_the_entries_with_a_url_slug_and_no_numeric_id() -> None:
    targets = resolver.parse_targets(SAMPLE_YAML)
    assert [t.slug for t in targets] == ["carbone-nyc", "lilia-williamsburg"]
    assert [t.url_slug for t in targets] == [
        "carbone-new-york-new-york",
        "lilia-brooklyn",
    ]


def test_an_entry_with_no_url_slug_is_not_a_target() -> None:
    """Gramercy Tavern is not on Resy at all — there is nothing for a human to resolve."""
    assert "gramercy-tavern" not in {t.slug for t in resolver.parse_targets(SAMPLE_YAML)}


def test_an_already_resolved_entry_is_not_a_target() -> None:
    """Re-running the resolver must not re-look-up (or overwrite) a verified id."""
    assert "already-resolved" not in {t.slug for t in resolver.parse_targets(SAMPLE_YAML)}


def test_each_target_points_at_its_own_venue_id_line() -> None:
    lines = SAMPLE_YAML.splitlines()
    for target in resolver.parse_targets(SAMPLE_YAML):
        assert lines[target.venue_line].strip().startswith("resy_venue_id:")


# --------------------------------------------------------------------------------------
# Preconditions: exit 2, no network, no writes
# --------------------------------------------------------------------------------------


async def test_dry_run_without_a_key_reports_the_work_and_exits_two(
    seed_file: Path, forbid_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    before = seed_file.read_bytes()
    code = await resolver.run(["--dry-run"])
    out = capsys.readouterr().out

    assert code == 2, "a dry run has not resolved anything, so it is exit 2 (preconditions)"
    assert "2" in out, out
    assert "unresolved" in out.lower(), out
    assert "docs/runbooks/resy-cookie-capture.md" in out, out
    assert seed_file.read_bytes() == before, "a dry run must write nothing"


async def test_no_api_key_without_dry_run_exits_two_and_names_the_variable(
    seed_file: Path, forbid_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    before = seed_file.read_bytes()
    code = await resolver.run([])
    output = capsys.readouterr()
    combined = output.out + output.err

    assert code == 2
    assert "RESY_API_KEY" in combined, combined
    assert "docs/runbooks/resy-cookie-capture.md" in combined, combined
    assert seed_file.read_bytes() == before


async def test_a_dry_run_names_the_slugs_it_would_resolve(
    seed_file: Path, forbid_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    await resolver.run(["--dry-run"])
    out = capsys.readouterr().out
    assert "carbone-new-york-new-york" in out
    assert "lilia-brooklyn" in out


async def test_the_slug_flag_restricts_the_work_set(
    seed_file: Path, forbid_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    await resolver.run(["--dry-run", "--slug", "carbone-nyc"])
    out = capsys.readouterr().out
    assert "carbone-new-york-new-york" in out
    assert "lilia-brooklyn" not in out


async def test_the_slug_flag_also_accepts_the_resy_url_slug(
    seed_file: Path, forbid_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both slugs are printed by a dry run, so both must be usable as its argument."""
    await resolver.run(["--dry-run", "--slug", "lilia-brooklyn"])
    out = capsys.readouterr().out
    assert "lilia-brooklyn" in out
    assert "carbone-new-york-new-york" not in out


async def test_an_unknown_slug_exits_two_rather_than_resolving_everything(
    seed_file: Path, forbid_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A typo'd --slug must not silently widen to the whole file."""
    code = await resolver.run(["--dry-run", "--slug", "not-a-restaurant"])
    combined = capsys.readouterr()
    assert code == 2
    assert "not-a-restaurant" in combined.out + combined.err


# --------------------------------------------------------------------------------------
# T-03-13: the --yaml path is confined to the repository, and writes are atomic
# --------------------------------------------------------------------------------------


def test_a_yaml_path_outside_the_repository_is_rejected(
    seed_file: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere.yml"
    outside.write_text(SAMPLE_YAML)
    with pytest.raises(ValueError, match="outside the repository"):
        resolver.resolve_yaml_path(str(outside))


def test_a_traversal_path_is_rejected(seed_file: Path) -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        resolver.resolve_yaml_path("scripts/seed/../../../../etc/passwd")


def test_a_path_inside_the_repository_is_accepted(seed_file: Path) -> None:
    assert resolver.resolve_yaml_path(str(seed_file)) == seed_file.resolve()


def test_a_sibling_directory_sharing_a_prefix_is_rejected(
    seed_file: Path, tmp_path: Path
) -> None:
    """`/tmp/x/repo-evil` must not pass a containment check written as a string prefix."""
    sibling = tmp_path / "repo-evil"
    sibling.mkdir()
    target = sibling / "restaurants.yml"
    target.write_text(SAMPLE_YAML)
    with pytest.raises(ValueError, match="outside the repository"):
        resolver.resolve_yaml_path(str(target))


async def test_an_interrupted_write_cannot_truncate_the_seed_file(
    seed_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write goes through a temp file plus rename (ASVS V12), so a crash mid-write
    leaves the ORIGINAL 55 entries intact rather than a half-file."""
    before = seed_file.read_text()

    def _boom(src: str, dst: str) -> None:
        raise KeyboardInterrupt("simulated Ctrl-C between write and rename")

    monkeypatch.setattr(resolver.os, "replace", _boom)
    with pytest.raises(KeyboardInterrupt):
        resolver.write_atomically(seed_file, "TOTALLY DIFFERENT CONTENT\n")

    assert seed_file.read_text() == before
    assert list(seed_file.parent.glob("*.tmp*")) == [], "a temp file was left behind"


# --------------------------------------------------------------------------------------
# The surgical edit
# --------------------------------------------------------------------------------------


def test_applying_a_resolution_writes_the_integer_on_the_right_line() -> None:
    targets = resolver.parse_targets(SAMPLE_YAML)
    updated = resolver.apply_resolution(SAMPLE_YAML, targets[0], 61977)

    import yaml

    entries = yaml.safe_load(updated)["restaurants"]
    by_slug = {e["slug"]: e for e in entries}
    assert by_slug["carbone-nyc"]["resy_venue_id"] == 61977
    assert by_slug["carbone-nyc"]["resy_url_slug"] == "carbone-new-york-new-york"
    # Nothing else moved.
    assert by_slug["lilia-williamsburg"]["resy_venue_id"] is None
    assert by_slug["already-resolved"]["resy_venue_id"] == 12345
    assert by_slug["gramercy-tavern"]["opentable_rid"] == 900000003


def test_applying_a_resolution_preserves_every_comment_block() -> None:
    """`yaml.safe_dump` would delete all of these, which is why the edit is surgical."""
    targets = resolver.parse_targets(SAMPLE_YAML)
    updated = resolver.apply_resolution(SAMPLE_YAML, targets[0], 61977)

    assert "# A comment block that yaml.safe_dump would silently delete." in updated
    assert "# Schema: name, slug," in updated
    assert "# TODO(01-05 spike)" in updated
    # The TODO on the line that WAS resolved is correctly gone — it is done.
    assert updated.count("TODO(03 spike)") == 1


def test_applying_a_resolution_records_where_the_id_came_from() -> None:
    targets = resolver.parse_targets(SAMPLE_YAML)
    updated = resolver.apply_resolution(SAMPLE_YAML, targets[0], 61977)
    resolved_line = next(
        line for line in updated.splitlines() if "61977" in line
    )
    assert "carbone-new-york-new-york" in resolved_line, (
        "a bare integer is unreviewable; the line must say which slug produced it"
    )


def test_the_line_count_is_unchanged_by_a_resolution() -> None:
    targets = resolver.parse_targets(SAMPLE_YAML)
    updated = resolver.apply_resolution(SAMPLE_YAML, targets[0], 61977)
    assert len(updated.splitlines()) == len(SAMPLE_YAML.splitlines())


# --------------------------------------------------------------------------------------
# A successful run, with the [ASSUMED] network call substituted
# --------------------------------------------------------------------------------------


async def test_a_successful_run_writes_every_id_and_exits_zero(
    seed_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RESY_API_KEY", API_KEY)
    ids = {"carbone-new-york-new-york": 61977, "lilia-brooklyn": 1505}

    async def _fake(client: object, url_slug: str, api_key: str) -> int:
        assert api_key == API_KEY
        return ids[url_slug]

    monkeypatch.setattr(resolver, "_resolve_one", _fake)
    code = await resolver.run([])
    assert code == 0, capsys.readouterr().out

    import yaml

    entries = yaml.safe_load(seed_file.read_text())["restaurants"]
    by_slug = {e["slug"]: e for e in entries}
    assert by_slug["carbone-nyc"]["resy_venue_id"] == 61977
    assert by_slug["lilia-williamsburg"]["resy_venue_id"] == 1505
    assert by_slug["gramercy-tavern"]["resy_venue_id"] is None
    assert "# Schema: name, slug," in seed_file.read_text()


async def test_one_failed_lookup_exits_one_and_keeps_the_successes(
    seed_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 1 = one or more lookups failed. The ids that DID resolve are still written:
    losing them would make the operator re-run every lookup against a rate-limited API."""
    monkeypatch.setenv("RESY_API_KEY", API_KEY)

    async def _fake(client: object, url_slug: str, api_key: str) -> int:
        if url_slug == "lilia-brooklyn":
            raise RuntimeError("404 from the [ASSUMED] endpoint")
        return 61977

    monkeypatch.setattr(resolver, "_resolve_one", _fake)
    code = await resolver.run([])
    assert code == 1

    import yaml

    by_slug = {
        e["slug"]: e for e in yaml.safe_load(seed_file.read_text())["restaurants"]
    }
    assert by_slug["carbone-nyc"]["resy_venue_id"] == 61977
    assert by_slug["lilia-williamsburg"]["resy_venue_id"] is None


async def test_a_non_integer_response_is_refused_not_written(
    seed_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-03-10: a slug or a placeholder must never reach `resy_venue_id`.

    `int(...)` on it raises inside `poll_loop`, which logs and continues WITHOUT releasing
    the job — an unrecoverable poison entry in `sched:polls:inflight` (research B-4).
    """
    monkeypatch.setenv("RESY_API_KEY", API_KEY)

    async def _fake(client: object, url_slug: str, api_key: str) -> int:
        return "carbone-new-york-new-york"  # type: ignore[return-value]

    monkeypatch.setattr(resolver, "_resolve_one", _fake)
    code = await resolver.run([])
    assert code == 1

    import yaml

    by_slug = {
        e["slug"]: e for e in yaml.safe_load(seed_file.read_text())["restaurants"]
    }
    assert by_slug["carbone-nyc"]["resy_venue_id"] is None


# --------------------------------------------------------------------------------------
# T-03-11: the key never reaches stdout, stderr or the file
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["--dry-run"], []])
async def test_the_api_key_is_never_printed(
    argv: list[str],
    seed_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RESY_API_KEY", API_KEY)

    async def _fake(client: object, url_slug: str, api_key: str) -> int:
        return 61977

    monkeypatch.setattr(resolver, "_resolve_one", _fake)
    await resolver.run(argv)
    captured = capsys.readouterr()
    assert API_KEY not in captured.out
    assert API_KEY not in captured.err
    assert API_KEY not in seed_file.read_text()


async def test_a_failure_message_does_not_leak_the_key(
    seed_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The most likely leak: an exception whose text embeds the request that carried it."""
    monkeypatch.setenv("RESY_API_KEY", API_KEY)

    async def _fake(client: object, url_slug: str, api_key: str) -> int:
        raise RuntimeError(f'401 for Authorization: ResyAPI api_key="{api_key}"')

    monkeypatch.setattr(resolver, "_resolve_one", _fake)
    await resolver.run([])
    captured = capsys.readouterr()
    assert API_KEY not in captured.out + captured.err


# --------------------------------------------------------------------------------------
# The pending-human contract
# --------------------------------------------------------------------------------------


def test_the_script_carries_a_pending_human_banner() -> None:
    text = (REPO_ROOT / "scripts" / "resolve_resy_venue_ids.py").read_text()
    assert "STATUS: pending-human" in text
    assert "docs/runbooks/resy-cookie-capture.md" in text


def test_the_assumed_endpoint_is_marked_as_assumed() -> None:
    """Research A4 could not verify it. An unmarked assumption is one nobody re-checks."""
    text = (REPO_ROOT / "scripts" / "resolve_resy_venue_ids.py").read_text()
    assert "[ASSUMED]" in text
    assert "TODO(spike)" in text


def test_the_runbook_documents_the_step_as_pending_human() -> None:
    runbook = REPO_ROOT / "docs" / "runbooks" / "resy-cookie-capture.md"
    assert runbook.is_file(), "the seed YAML points every reader at this file"
    text = runbook.read_text()
    assert "STATUS: pending-human" in text
    assert "resolve_resy_venue_ids.py" in text
