"""R7-04: the web client's Identity tab (M9 §5a, plan docs/plans/2026-10-21-r7-identity-picker.md "The Identity tab").

There is no JS runner in the suite (tests/test_web_m8.py style), so these check what the served files must contain:
the tab and its controls, the endpoints the script calls, the button labels, the MusicBrainz links, that the client
never applies anything, the phone-first CSS, and that every row field the script reads is one the API serves.
"""
import re

from tests.test_identity_api import RA, T1, T2, api, call, pick, rows  # noqa: F401  (fixture)
from tests.test_identity_backfill import template  # noqa: F401  (fixture)
from tests.test_web_m8 import asset, svc  # noqa: F401  (fixture)

CLASSES = ["search", "ambiguous", "none", "conflict", "error"]


def identity_js(js):
    """The Identity tab's part of app.js, between its markers."""
    m = re.search(r"// identity:begin(.*?)// identity:end", js, re.S)
    assert m, "app.js has no // identity:begin … // identity:end block"
    return m.group(1)


def test_page_has_the_tab_its_count_its_filter_and_its_list(svc):
    html = asset(svc, "")
    assert re.search(r'<button data-tab="identity">Identity <span id="identity-count" class="pill"></span></button>',
                     html)
    section = re.search(r'<section id="tab-identity" class="tab">(.*?)</section>', html, re.S)
    assert section, "no Identity section"
    body = section.group(1)
    assert '<select id="identity-class"' in body and '<ul id="identity"' in body
    assert re.findall(r'<option value="(\w*)"', body) == [""] + CLASSES        # all, then each picker class


def test_script_calls_the_identity_endpoints(svc):
    block = identity_js(asset(svc, "app.js"))
    assert '"/api/identity"' in block and '"/api/identity/choice"' in block
    assert "?class=" in block


def test_script_has_the_three_buttons_and_musicbrainz_links(svc):
    block = identity_js(asset(svc, "app.js"))
    for label in ('"Accept"', '"Choose"', '"Skip"'):
        assert label in block
    assert '"https://musicbrainz.org/recording/"' in block
    assert 'type = "radio"' in block and ".suggested" in block                 # the album-only candidate pre-checked


def test_the_client_never_applies_and_never_names_a_library_path(svc):
    js = asset(svc, "app.js")
    assert js.count("apply") == 0                                               # `grep -c apply web/app.js` is 0
    assert "/srv" not in js and "/srv" not in asset(svc, "")


def test_accept_sends_the_shown_recording_and_skip_is_the_only_button_on_conflict_and_error(svc):
    block = identity_js(asset(svc, "app.js"))
    assert re.search(r'"accept",\s*r\.proposed\.id', block)                   # Accept posts the proposed.id it showed
    assert re.search(r'r\.cls === "search"', block)
    assert re.search(r'\["ambiguous", "none"\]\.includes\(r\.cls\)', block)    # Choose only where there are candidates


def test_a_click_paints_its_own_row_and_errors_show_the_servers_words(svc):
    block = identity_js(asset(svc, "app.js"))
    for word in ("accepted", "chosen: ", "skipped", "stale: pick again"):
        assert word in block
    assert "e.message" in block
    assert "changeError" not in block and "alert(" not in block                # playlist texts and alerts stay out
    assert "loadWanted" not in block and "loadPlaylists" not in block           # nothing else reloads


def test_the_tab_loads_on_open_and_a_hash_opens_it(svc):
    js = asset(svc, "app.js")
    assert re.search(r"identity:\s*loadIdentity", js)
    assert "location.hash" in js


def test_the_count_pill_and_the_filter_are_filled(svc):
    block = identity_js(asset(svc, "app.js"))
    assert '"#identity-count"' in block and '"#identity-class"' in block and ".counts" in block


def test_phone_first_css(svc):
    css = asset(svc, "app.css")
    assert "#identity" in css
    widths = [int(n) for n in re.findall(r"(?<![\w-])(?:min-)?width:\s*(\d+)px", css)]
    widths += [int(n) for n in re.findall(r"flex(?:-basis)?:[^;}]*?(\d+)px", css)]
    assert widths and max(widths) <= 375, widths
    assert re.search(r"\.tabs\s*\{[^}]*overflow-x:\s*auto", css)               # five tabs fit a 375 px phone
    assert re.search(r"#identity[^{]*\.title[^{]*\{[^}]*overflow-wrap:\s*anywhere", css)   # long titles wrap


def test_every_field_the_script_reads_is_served(api):
    """The script reads these names off a row and off a POST answer: the API must serve each of them."""
    app, srv, ident = api
    by = rows(srv)
    s, amb = by["K/search.flac"], by["K/tie.flac"]
    assert {"path", "cls", "why", "file", "songId", "proposed", "candidates", "suggested", "choice"} <= set(s)
    assert {"artist", "title", "album", "length_s"} <= set(s["file"])
    assert {"id", "title", "length_s", "url"} <= set(s["proposed"])
    assert amb["candidates"] and all({"id", "title", "artist", "length_s", "release", "disambiguation", "url"} <= set(c)
                                     for c in amb["candidates"])
    assert {c["url"] for c in amb["candidates"]} == {f"https://musicbrainz.org/recording/{T1}",
                                                     f"https://musicbrainz.org/recording/{T2}"}
    code, body = pick(srv, "K/search.flac", "accept", RA)
    assert code == 200 and {"action", "mbid", "stale"} <= set(body["choice"])
    code, body = call(f"{srv.url}/api/identity")
    assert set(body["counts"]) == set(CLASSES)


def test_the_script_reads_only_served_fields(svc):
    block = identity_js(asset(svc, "app.js"))
    for name in ("r.path", "r.why", "r.file", "r.songId", "r.proposed", "r.candidates", "r.suggested", "r.choice",
                 ".stale", ".action", ".mbid", ".release", ".disambiguation", ".length_s", ".counts"):
        assert name in block, name


# ── R7-04 review (Opus, scratch r7-04.diff): all Minor ─────────────────────────────────────────────────────────────

ROW_KEYS = {"path", "cls", "why", "file", "songId", "proposed", "candidates", "suggested", "choice"}
FILE_KEYS = {"artist", "title", "album", "length_s", "isrc", "version_tag", "mb_trackid", "mb_workid", "acoustid_id"}
CAND_KEYS = {"id", "title", "artist", "length_s", "release", "disambiguation", "url"}
CHOICE_KEYS = {"action", "mbid", "at", "decided_by", "stale"}


def test_the_script_reads_no_field_the_api_lacks(svc):
    block = identity_js(asset(svc, "app.js"))
    assert set(re.findall(r"\br\.(\w+)", block)) <= ROW_KEYS
    assert set(re.findall(r"\bf\.(\w+)", block)) <= FILE_KEYS
    assert set(re.findall(r'\["(\w+)", "(\w+)", "(\w+)"\]\.filter\(k => f\[k\]\)', block)[0]) <= FILE_KEYS
    assert set(re.findall(r"\bc\.(\w+)", block)) <= CAND_KEYS | CHOICE_KEYS
    assert set(re.findall(r"\br\.proposed\.(\w+)", block)) <= {"id", "title", "length_s", "url"}
    assert set(re.findall(r"\br\.choice\.(\w+)", block)) <= CHOICE_KEYS


def test_nothing_is_sent_but_from_a_button_and_nothing_is_parsed_as_html(svc):
    block = identity_js(asset(svc, "app.js"))
    assert block.count('"/api/identity/choice"') == 1
    assert not re.search(r"innerHTML|insertAdjacentHTML|outerHTML|document\.write", block)
    for handler in re.findall(r"onchange = ([^;]*);", block):                  # a change only enables Choose
        assert "send(" not in handler and "api(" not in handler, handler


def test_a_late_answer_never_overwrites_a_newer_list(svc):
    block = identity_js(asset(svc, "app.js"))
    assert re.search(r"seq = \+\+idSeq", block) and re.search(r"if \(seq !== idSeq\) return", block)


def test_an_error_keeps_the_stored_choice_and_never_shows_blank(svc):
    block = identity_js(asset(svc, "app.js"))
    assert re.search(r"e\.message \|\|", block)                                 # an empty message still says something
    assert re.search(r"idPaint\(box, r\.choice\);\s*box\.append\(", block)       # the error goes under the stored choice
    assert re.search(r"e\.status === 409", block) and '"reload"' in block       # the 409 says reload: offer it


def test_the_held_choice_and_the_suggestion_compare_ids_in_lowercase(svc):
    block = identity_js(asset(svc, "app.js"))
    assert ".toLowerCase()" in block


def test_the_hash_opener_loads_the_identity_list_once(svc):
    js = asset(svc, "app.js")
    assert re.search(r'if \(!opened \|\| opened\.dataset\.tab !== "identity"\) loadIdentity\(\);\s*if \(opened\) opened\.click\(\);', js)
