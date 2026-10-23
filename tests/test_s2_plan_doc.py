"""S2-01: the S2 plan file exists and fixes the album-job design the later S2 features build on."""
from pathlib import Path

PLAN = Path(__file__).resolve().parent.parent / "docs" / "plans" / "2026-10-22-s2-album-requests.md"


def test_s2_plan_has_its_sections():
    text = PLAN.read_text()
    for heading in ("## Schema", "## Request status", "## Album job", "## Live steps"):
        assert f"\n{heading}\n" in text, heading


def test_s2_plan_status_words_match_the_store():
    # The plan's status list and crates.store's are one list: each word the code can answer is in the plan.
    from crates.store import REQUEST_STATUSES
    section = PLAN.read_text().split("## Request status", 1)[1].split("\n## ", 1)[0]
    for word in REQUEST_STATUSES:
        assert f"`{word}`" in section, word
