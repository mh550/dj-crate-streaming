"""S2-06a: the album-tags plan exists, is reviewed, and pins the writer and where it writes."""
from pathlib import Path

PLAN = Path(__file__).resolve().parent.parent / "docs" / "plans" / "2026-10-22-S2-album-tags.md"


def _section(text, heading):
    return text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]


def test_album_tags_plan_has_its_sections():
    text = PLAN.read_text()
    for heading in ("## Fields", "## Writer", "## When", "## Reverse", "## beets measurement", "## Review"):
        assert f"\n{heading}\n" in text, heading


def test_album_tags_plan_names_the_writer_and_staging():
    text = PLAN.read_text()
    assert "write_minimal" in _section(text, "## Writer")
    assert ".staging" in _section(text, "## When")


def test_album_tags_plan_fields_are_the_ones_write_minimal_takes():
    # Every field the plan writes is a mediafile field name, so write_minimal(path, {field: value}) sets it.
    text = _section(PLAN.read_text(), "## Fields")
    for name in ("album", "albumartist", "track", "tracktotal", "year", "mb_albumid", "comp"):
        assert f"`{name}`" in text, name
