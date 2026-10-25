"""S4-01: the downloads checklist carries the S2/S3 live steps (the spec's addition steps 4 and 6) and the slskd
captures, every live command in the deployed image and every crates.db write under the live lock; the morning
checklist links it, and architecture §4 (e) and next-todos say what exists and that none of it is deployed."""
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
CHECKLIST = DOCS / "plans" / "2026-10-22-downloads-checklist.md"
MORNING = DOCS / "plans" / "2026-10-22-morning-checklist.md"
CAPTURE = Path(__file__).resolve().parent.parent / "scripts" / "capture_spotify.py"
LOCK = "flock -n /srv/docker/crates/live.lock "
S4 = "## 4. Album request through the request API"
S6 = "## 6. Spotify developer app and the capture"
CAPTURES = "## Captures for the fixtures"
CLI = Path(__file__).resolve().parent.parent / "sourcing" / "cli.py"
# A one-off command that writes crates.db: a request, its cached plan, approvals, a reopen, a seed, an import, a retier.
WRITES = re.compile(r"sourcing\.cli (request (add|preview|approve)|seed-spotify|import-playlist|retier)\b"
                    r"|sourcing\.cli fetch\b.*--approve|--apply\b")


def _section(text, heading):
    assert f"\n{heading}\n" in text, heading
    return text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]


def _commands(text):
    """The lines of the fenced code blocks: the commands Michael copies."""
    return [line.strip() for block in re.findall(r"```[a-z]*\n(.*?)```", text, re.S) for line in block.splitlines()
            if line.strip()]


def _inline(text):
    """The inline code spans outside the fenced blocks (a command in the prose)."""
    return re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))


def test_the_checklist_has_sections_4_and_6_and_the_captures_in_order():
    text = CHECKLIST.read_text()
    order = ["## 3. Re-test the Al Green album", S4, "## 5. Duplicate cleanup plan", S6, "## 7. gluetun", CAPTURES]
    at = [text.index(f"\n{h}") for h in order]
    assert at == sorted(at), order
    assert "belong to the S2–S4 run" not in text          # the S1 placeholder for steps 4 and 6 is gone


def test_sections_4_and_6_each_have_a_check_and_an_undo():
    text = CHECKLIST.read_text()
    for heading in (S4, S6):
        body = _section(text, heading)
        assert re.search(r"^ *Check:", body, re.M), heading
        assert re.search(r"^ *Undo:", body, re.M), heading


def test_every_live_run_command_is_a_python_module_and_every_write_holds_the_lock():
    text = CHECKLIST.read_text()
    commands = _commands(text)
    runs = [c for c in commands if "scripts/live-run.sh" in c]
    assert runs
    for c in runs:
        assert c.removeprefix(LOCK).startswith("scripts/live-run.sh python3 -m "), c
    for span in _inline(text):                           # prose: the same rule; `<command…>` is the convention's
        if span.startswith("scripts/live-run.sh ") and span != "scripts/live-run.sh <command…>":
            assert re.match(r"scripts/live-run\.sh (--print )?python3 -m ", span), span
        if "python3 -m " in span and WRITES.search(span):     # a write command in the prose holds the lock too
            assert span.startswith(LOCK + "scripts/live-run.sh python3 -m "), span
    writes = [c for c in commands if WRITES.search(c)]
    assert len(writes) >= 4
    for c in writes:
        assert c.startswith(LOCK + "scripts/live-run.sh python3 -m "), c


def test_section_4_is_add_preview_approve_of_the_al_green_album_after_the_deploy():
    body = _section(CHECKLIST.read_text(), S4)
    commands = _commands(body)
    add = "sourcing.cli request add https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z"
    for step in (add, "sourcing.cli request preview <id>", "sourcing.cli request approve <id>"):
        assert any(c.endswith(step) for c in commands), step
    assert "<the sha step 2 deployed>" in body
    assert "D7" in body and "wanted reopen" in body and "/api/events" in body
    assert "dj_album:1:" in body                         # the album-tags plan's live steps: the key, one row, all
    assert "One row first" in body and "count(DISTINCT album_id)" in body


def test_section_4s_expected_outputs_are_what_the_cli_prints():
    body, cli = _section(CHECKLIST.read_text(), S4), CLI.read_text()
    for said, code in (("; already requested", '"; already requested"'),
                       ("nothing to plan", '"nothing to plan"'),
                       ("the worker downloads them on its next tick", "the worker downloads them on its next tick"),
                       ("musicbrainz release <mbid>", 'f"musicbrainz release {'),
                       ("one to one; the request goes on without ids", "one to one; \"\n"),
                       ("the request goes on without MusicBrainz ids", "the request goes on without MusicBrainz ids")):
        assert said in body, said
        assert code in cli, code


def test_section_6_is_the_capture_scripts_own_command_and_its_checks():
    body = _section(CHECKLIST.read_text(), S6)
    usage = next(line.strip() for line in CAPTURE.read_text().split('"""')[1].splitlines()
                 if "python3 -m scripts.capture_spotify" in line)
    assert usage in _commands(body)
    assert "developer.spotify.com" in body and "Premium" in body
    assert "grep -c tok_ fixtures/spotify_*.captured.json" in body
    assert "git add fixtures/spotify_search.captured.json fixtures/spotify_album.captured.json" in body
    assert "rotate" in body


def test_the_captures_name_each_fixture_and_the_test_that_reads_it():
    body = _section(CHECKLIST.read_text(), CAPTURES)
    for fixture in ("fixtures/slskd_enqueue.captured.json", "fixtures/slskd_transfers.captured.json",
                    "fixtures/slskd_remove.captured.json"):
        assert fixture in body, fixture
    assert "POST /transfers/downloads/<peer>" in body and "?remove=true" in body
    assert "tests/test_fake_slskd.py" in body and "sourcing/fake_slskd.py" in body


def test_the_morning_checklist_has_the_pr_16_line_once_and_links_sections_4_and_6():
    text = MORNING.read_text()
    assert text.count("PR #16 must be on main first") == 1
    at = text.index("PR #16 must be on main first")       # the first line of its deploy step (S1-09)
    assert text.index("\n## 4. Deploy `main`") < at < text.index("\n## 5. ")
    nine = _section(text, "## 9. What R4–R7 change live, and how to look at it")
    assert "2026-10-22-downloads-checklist.md" in nine and "section 4" in nine and "section 6" in nine


def test_architecture_and_next_todos_say_built_not_deployed_prs_open():
    arch = _section((DOCS / "architecture.md").read_text(), "### (e) Album request → plan → approve → album job")
    todos = (DOCS / "next-todos.md").read_text()
    state = _section(todos, "## State at hand-off")
    for text in (arch, state):
        assert "not deployed, PRs open" in text
        for word in ("request", "album job", "/api/requests", "sourcing.cli request"):
            assert word in text, word
    items = _section(todos, "## In order")
    assert "Spotify provider (after the S3-06 capture)" in items and "client UI (question B)" in items
