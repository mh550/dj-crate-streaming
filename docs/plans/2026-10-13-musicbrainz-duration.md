# Expected-duration lookup via MusicBrainz — plan (not started)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** planned 2026-10-13 overnight (stretch item). Nothing implemented.

**Goal:** When a wanted track's length is unknown or untrustworthy, ask MusicBrainz for the known
lengths of that recording's editions and let the scorer and verifier judge a candidate against the
*nearest known edition* instead of one number.

**Why:** Today `Wanted.duration_s` comes from the crate's old (often lossy) file or from Spotify. The first
live search tonight showed the failure mode: every "Good Times" FLAC scored "duration close (Δ13s) —
different edit?" because the wanted length was one edition and the peers had another. "Good Times" exists
as a 3:35 single edit and an 8:13 album version; both are legitimate, and which one Michael wants is a
crate decision, not a verifier decision. The verifier (`tolerance_s=4`) would currently *reject* a perfect
album version if the crate's old file was the single edit.

**Architecture:** One new stdlib module `sourcing/musicbrainz.py` (urllib, 1 request/s, descriptive
User-Agent, small on-disk JSON cache) returns `list[Edition(length_s, title, release, mbid)]` for
(artist, title[, album]). `Wanted` grows an optional `editions: list[float]`; scorer and verifier compare
against the nearest edition, preferring `duration_s` when both exist. `fetch` fills `editions` when
`duration_s` is missing or when `--mb` is passed. No AcoustID, no tagging, no automatic retries.

**Tech Stack:** Python stdlib; MusicBrainz WS/2 JSON (`/ws/2/recording?query=…&fmt=json`); pytest with a
fixture of a real response. **Spec:** `~/projects/OVERNIGHT.md` stretch item; `ideas/dj-crate-streaming/spec.md`.

## Global Constraints

- stdlib only; no `musicbrainzngs`.
- MusicBrainz etiquette: ≤ 1 request/s, `User-Agent: dj-crate-streaming/0.1 (michael@…)`, cache every
  answer (JSON file under `CRATES_DB`'s directory, e.g. `/srv/docker/crates/mb-cache.json`), never call
  it from tests (fixture only).
- A lookup failure (offline, 503, no match) must degrade to today's behaviour, never block a fetch.
- Keep `pytest -q` green (80 today).

## Review Focus

1. Recording search returns many near-misses (live versions, remixes, karaoke): editions must be filtered to
   recordings whose artist-credit matches and whose title matches after `scorer.norm`, else the nearest
   edition is a karaoke track and anything passes. → Task 1 `test_editions_filter_title_and_artist`.
2. MusicBrainz down or rate-limited: `lookup` returns `[]` and logs, fetch proceeds with `duration_s` only.
   → Task 1 `test_lookup_failure_returns_empty`.
3. Both `duration_s` and `editions` known and disagreeing (crate had the single, MB knows both): scorer
   should award full points to either edition but prefer the crate's own length when choosing the top
   candidate. → Task 2 `test_scorer_prefers_crate_length_but_accepts_other_edition`.
4. Verifier with editions: a 8:13 album cut passes when 8:13 is a known edition even if the crate's old file
   was 3:35; a 5:00 cut (no such edition) fails. → Task 3 `test_verify_accepts_any_known_edition`.
5. Cache poisoning: a cached `[]` from a transient failure must not stick forever; cache only non-empty
   answers, or store a timestamp and retry after 24 h. → Task 1 `test_empty_results_are_not_cached`.

---

### Task 1: `sourcing/musicbrainz.py`

**Files:** Create `sourcing/musicbrainz.py`, `fixtures/mb_recording_good_times.json` (a real WS/2 response,
trimmed to ~10 recordings incl. one live and one karaoke), Test `tests/test_musicbrainz.py`.

**Interfaces:**
- Produces: `@dataclass Edition(length_s: float, title: str, artist: str, release: str | None, mbid: str)`;
  `lookup(artist: str, title: str, album: str | None = None, *, fetch=_http_get, cache_path: Path | None = None) -> list[Edition]`
  (sorted by length; de-duplicated to 1 s); `_http_get(url) -> dict` is the only network touch and is injectable.

- [ ] Write failing tests: `test_editions_filter_title_and_artist` (fixture → exactly the Chic recordings, lengths
      {215, 493} s), `test_lookup_failure_returns_empty` (fetch raises → `[]`), `test_empty_results_are_not_cached`,
      `test_cache_hit_skips_fetch`, `test_rate_limit_sleeps_between_calls` (monkeypatch `time.sleep`, two lookups → one sleep ≥ 1 s).
- [ ] Run: `~/.local/bin/pytest -q tests/test_musicbrainz.py` → FAIL (module missing).
- [ ] Implement: query `recording:"<title>" AND artist:"<artist>"` (+ `AND release:"<album>"` when given), `limit=25`;
      keep recordings where `norm(rec["title"]) == norm(title)` and any artist-credit `norm(name) == norm(artist)`
      and `"length" in rec`; map to `Edition`; cache `{key: [editions], "ts": …}` only when non-empty.
- [ ] Run → PASS. Commit: `sourcing/musicbrainz: edition lengths for a recording (stdlib, cached, 1 rps)`.

### Task 2: scorer — nearest known edition

**Files:** Modify `sourcing/scorer.py` (`Wanted` +`editions: list[float] = field(default_factory=list)`; the
duration block at ~163-172), Test `tests/test_scorer.py` (append).

- [ ] Failing tests: `test_scorer_uses_nearest_edition` (wanted editions [215, 493], candidate 492 → "duration match"),
      `test_scorer_prefers_crate_length_but_accepts_other_edition` (duration_s=215, editions [215, 493]: a 215 s
      candidate outranks a 493 s one by the small "crate's own length" bonus, both get the +15).
- [ ] Implement: `targets = ([w.duration_s] if w.duration_s else []) + w.editions`; `d = min(abs(c.length_s - t) for t in targets)`;
      same thresholds as today; +2 bonus when the nearest target is `duration_s` itself; reason names the edition length.
- [ ] Run suite → PASS. Commit: `scorer: judge length against the nearest known edition`.

### Task 3: verifier — any known edition passes

**Files:** Modify `sourcing/verify.py` (`verify(path, expected_duration_s=None, *, editions=(), tolerance_s=4.0, …)`),
Test `tests/test_verify.py` (append).

- [ ] Failing test: `test_verify_accepts_any_known_edition` (493 s file, expected 215, editions [215, 493] → ok;
      300 s file → problem names both known lengths).
- [ ] Implement: `targets = [expected_duration_s, *editions]` minus Nones; fail only if the file is > tolerance from *all*.
- [ ] Run → PASS. Commit: `verify: duration passes if it matches any known edition`.

### Task 4: wire into `fetch` and the CLI

**Files:** Modify `sourcing/fetch.py` (after building `wanted`), `sourcing/cli.py` (`fetch --mb`, `rank --mb`), `README.md`.

- [ ] Failing test in `tests/test_fetch.py`: `test_fetch_fills_editions_when_duration_missing` (crate row with
      `duration=None`, injected `lookup` returning [215, 493] → scorer reasons mention an edition; no network).
- [ ] Implement: `if mb and (not wanted.duration_s or force): wanted.editions = [e.length_s for e in lookup(...)]`;
      pass `editions` to `verify`; `--mb` flag defaults on when `duration` is missing, off otherwise. Degrade silently on `[]`.
- [ ] Run suite → PASS. Commit: `fetch/cli: --mb fills known edition lengths from MusicBrainz`. README: one line under the fetch examples.

### Out of scope (say no when tempted)

AcoustID fingerprints (`fpcalc`), writing MB ids into tags, choosing *which* edition a crate wants (that is a
crate policy question for Michael), MusicBrainz release matching for albums (beets already does that).
