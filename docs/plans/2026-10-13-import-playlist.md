# import-playlist (Spotify → Navidrome) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python3 -m sourcing.cli import-playlist <spotify-url | report.txt | exportify.csv>… [--name N]` creates or updates a **public** Navidrome playlist with the library tracks it can match, in Spotify order, and queues the rest as `external_wanted` rows that remember their playlist and position.

**Architecture:** Three tiny parsers turn each input into the same `Row` list (`sourcing/playlist_sources.py`). A matcher asks Navidrome `search3` word-wise and picks by duration ±4 s, else by normalised title + lead artist, with a dedupe rule for the library's redundant copies (`sourcing/import_playlist.py`). A builder creates/updates the playlist idempotently and writes wanted rows; the CLI glues sources together. The fake Navidrome is corrected from the captured live fixtures first (it must omit `public` when false and fold accents/punctuation in `search3`).

**Tech Stack:** Python 3.12 stdlib only; existing `subsonic.client.SubsonicClient`, `subsonic.fake_server`, `crates.store.CrateStore`, `sourcing.spotify_csv`. Tests with the pipx pytest: `~/.local/bin/pytest -q`.

**Spec:** `docs/specs/2026-10-13-next-session-design.md` §2a (D11), plus fixtures captured 2026-10-13: `fixtures/navidrome_playlist_song_search3.sample.json`, `fixtures/spotiflac_report_*.head30.txt`, `fixtures/spotify_embed_*.json`.

## Global Constraints

- stdlib only; no new dependencies.
- Never commit to `main`; work on `overnight2/2026-10-13`. Commit after every task.
- Playlists are created **public** (spec §2a "Visibility"). The `amperfy` user is never touched.
- Idempotent: re-running the same input never duplicates an entry and never removes a track (spec §2a "Idempotent").
- Matching: `search3` on artist+title words → duration within **±4 s** when the row has one → else exact normalised title + lead artist (spec §2a "Matching").
- Unmatched or ambiguous → `external_wanted` row with `playlist_id` + `position` (spec §2a).
- Fakes mirror the live API: every fake change in this plan cites the fixture line it copies.
- Suite stays green: 80 passing at start.

## Review Focus

1. **Report titles containing ` - `** ("Catendé - Live - Vinícius de Moraes; Maria Creuza; Toquinho"): the artist is after the *last* ` - `; splitting on the first would make the title "Catendé". Pinned in Task 1.
2. **Band names with commas** ("Earth, Wind & Fire"): a comma split would store artist "Earth" on the wanted row. The query uses every artist word (live search3 ignores punctuation), and the wanted row's lead artist comes from the track's own embed when the artist string has a comma. Pinned in Tasks 1 and 3.
3. **Redundant library copies** (28 files exist twice; live `search3 "Donald Byrd The Weasil"` → two hits, 540 s and 538 s): two hits with the same normalised artist|title are one track, not an ambiguity; pick the one nearest in duration, then the one not under `Compilations/`. Pinned in Task 3.
4. **Re-run after Michael edits the playlist by hand** (he removed a track in Amperfy, or added one): the importer appends only matched ids not already present and never removes anything. Pinned in Task 4.
5. **Private or unreachable Spotify URL**: `spotify_csv.fetch_entity` raises `SystemExit`; the CLI must exit non-zero with the message and leave the DB and Navidrome untouched. Pinned in Task 5.

---

### Task 1: Parsers — one `Row` shape from three inputs

**Files:**
- Create: `sourcing/playlist_sources.py`
- Test: `tests/test_playlist_sources.py`

**Interfaces:**
- Consumes: `sourcing.spotify_csv.fetch_entity(url) -> dict`, `sourcing.spotify_csv._next_data(path) -> dict` (track embed has `artists[0].name`).
- Produces:
  ```python
  @dataclass
  class Row:
      position: int              # 1-based, in source order
      title: str
      artist: str                # as the source wrote it: "A; B" (report) or "A, B" (Spotify / Exportify)
      duration_s: int | None     # None for report rows
      spotify_id: str | None = None
      album: str | None = None
      note: str | None = None    # report rows: "success" | "skipped" | "error: <message>"
  def rows_from_spotify(entity: dict) -> list[Row]
  def rows_from_report(text: str) -> list[Row]
  def rows_from_csv(text: str) -> list[Row]            # Exportify header or sockseek "Artist,Title,Length"
  def concat(groups: list[list[Row]]) -> list[Row]      # renumbers positions 1..N across groups
  def load(src: str, fetch=fetch_entity) -> tuple[str, list[Row]]   # (default name, rows); dispatches on URL / .txt / .csv
  def lead_artist(row: Row, resolve=_track_lead) -> str
  def _track_lead(spotify_id: str) -> str | None       # embed lookup; None on any failure
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_playlist_sources.py
import json
from pathlib import Path

from sourcing import playlist_sources as ps
from tests.helpers import FIXTURES


def test_spotify_rows_keep_order_duration_and_id():
    entity = json.loads((FIXTURES / "spotify_embed_tea-tent-2.json").read_text())
    rows = ps.rows_from_spotify(entity)
    assert len(rows) == 27 and [r.position for r in rows] == list(range(1, 28))
    r = rows[0]
    assert r.title == "Piano Joint (This Kind Of Love)" and r.artist == "Michael Kiwanuka"
    assert r.duration_s == 232 and r.spotify_id == "1I44zWi6wdcWcnd2B68Hio"


def test_spotify_subtitle_nbsp_is_normalised():
    entity = json.loads((FIXTURES / "spotify_embed_secondset.json").read_text())
    r = ps.rows_from_spotify(entity)[0]
    assert r.artist == "Roy Ayers, Dee Dee Bridgewater, Wayne Garfield"     # fixture has ",\xa0"


def test_report_rows_cover_success_skipped_and_errors():
    text = (FIXTURES / "spotiflac_report_nothin_to_it.head30.txt").read_text()
    rows = ps.rows_from_report(text)
    assert [r.position for r in rows] == [1, 2, 3, 4, 5, 6, 7]
    assert rows[0].title == "FIND YOUR WINGS (feat. Roy Ayers, Sydney Bennett & Kali Uchis)"
    assert rows[0].artist == "Tyler, The Creator; Roy Ayers; Syd; Kali Uchis" and rows[0].note == "success"
    err = rows[6]
    assert err.title == "World's Famous" and err.artist == "DJ KOCO aka SHIMOKITA; 45trio"
    assert err.album == "World's Famous" and err.spotify_id == "2sdU23lpqA9LamR7TWSlI7"
    assert err.note.startswith("error: This is normal") and err.duration_s is None


def test_report_title_with_dashes_splits_on_the_last_one():
    rows = ps.rows_from_report("Download Report - x\n---\n\n[SUCCESS] Catendé - Live - Vinícius de Moraes; Maria Creuza; Toquinho\n[SKIPPED] One - Three Dog Night\n")
    assert rows[0].title == "Catendé - Live" and rows[0].artist == "Vinícius de Moraes; Maria Creuza; Toquinho"
    assert rows[1].title == "One" and rows[1].artist == "Three Dog Night" and rows[1].note == "skipped"


def test_perfect_songs_head_parses_27_successes():
    rows = ps.rows_from_report((FIXTURES / "spotiflac_report_perfect_songs.head30.txt").read_text())
    assert len(rows) == 27 and rows[24].artist == "Earth, Wind & Fire" and rows[24].title == "After the Love Has Gone"


EXPORTIFY = (
    "Track URI,Track Name,Album Name,Artist Name(s),Release Date,Duration (ms),Popularity,Explicit,Added By,Added At,Genres,Record Label,Danceability\n"
    "spotify:track:4qZ1OgsTZMAgZA776w3USt,The Weasil,Fancy Free,Donald Byrd,1970,540626,40,false,spotify:user:x,2024-01-01T00:00:00Z,jazz,Blue Note,0.5\n"
    "spotify:track:abc,After the Love Has Gone,I Am,\"Earth, Wind & Fire\",1979,278000,60,false,spotify:user:x,2024-01-01T00:00:00Z,soul,Columbia,0.6\n"
)
SOCKSEEK = "Artist,Title,Length\nChic,Good Times,501\n"


def test_csv_exportify_and_sockseek_shapes():
    rows = ps.rows_from_csv(EXPORTIFY)
    assert rows[0] == ps.Row(1, "The Weasil", "Donald Byrd", 541, "4qZ1OgsTZMAgZA776w3USt", "Fancy Free")
    assert rows[1].artist == "Earth, Wind & Fire" and rows[1].duration_s == 278
    assert ps.rows_from_csv(SOCKSEEK) == [ps.Row(1, "Good Times", "Chic", 501)]


def test_concat_renumbers_positions():
    a = [ps.Row(1, "a", "x", None), ps.Row(2, "b", "x", None)]
    b = [ps.Row(1, "c", "x", None)]
    assert [r.position for r in ps.concat([a, b])] == [1, 2, 3] and ps.concat([a, b])[2].title == "c"


def test_load_dispatches_and_names(tmp_path):
    rep = tmp_path / "nothin to it.txt"
    rep.write_text((FIXTURES / "spotiflac_report_nothin_to_it.head30.txt").read_text())
    name, rows = ps.load(str(rep))
    assert name == "nothin to it" and len(rows) == 7
    csv_path = tmp_path / "secondset.csv"; csv_path.write_text(SOCKSEEK)
    assert ps.load(str(csv_path)) == ("secondset", [ps.Row(1, "Good Times", "Chic", 501)])
    entity = json.loads((FIXTURES / "spotify_embed_tea-tent-1.json").read_text())
    name, rows = ps.load("https://open.spotify.com/playlist/0wPBj1mjvAJcmr6zdaz228", fetch=lambda url: entity)
    assert name == "Tea tent" and len(rows) == 99 and rows[0].title == "The Weasil"


def test_lead_artist_resolves_commas_via_track_embed_and_semicolons_locally():
    assert ps.lead_artist(ps.Row(1, "t", "Donald Byrd", None)) == "Donald Byrd"
    assert ps.lead_artist(ps.Row(1, "t", "Tyler, The Creator; Roy Ayers", None)) == "Tyler, The Creator"   # report: ';' is the separator
    calls = []
    def resolve(sid): calls.append(sid); return "Earth, Wind & Fire"
    assert ps.lead_artist(ps.Row(1, "t", "Earth, Wind & Fire", 278, spotify_id="abc"), resolve=resolve) == "Earth, Wind & Fire"
    assert calls == ["abc"]
    assert ps.lead_artist(ps.Row(1, "t", "Roy Ayers, Dee Dee Bridgewater", 1, spotify_id="z"), resolve=lambda s: None) == "Roy Ayers"   # lookup failed → first segment
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/projects/dj-crate-streaming && ~/.local/bin/pytest -q tests/test_playlist_sources.py`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'sourcing.playlist_sources'`

- [ ] **Step 3: Write the implementation**

```python
# sourcing/playlist_sources.py
"""Playlist definitions from three places, one `Row` shape, Spotify order kept.

  1. Spotify playlist URL (public) — the embed page via `spotify_csv.fetch_entity`; 100-track cap.
  2. Exportify CSV (private / long playlists; Michael drops it in /srv/incoming/playlists/) or the
     `Artist,Title,Length` CSV that `spotify_csv` itself writes.
  3. SpotiFLAC download report `<name>.txt` (fixtures/spotiflac_report_*.head30.txt):
        [SUCCESS] Title - Artist; Artist2
        [SKIPPED] Title - Artist
        1. Title - Artist (Album)            ← numbered error entry, followed by indented lines
           Error: …
           ID: <spotify track id>
           URL: https://open.spotify.com/track/<id>
     Titles may contain " - " ("Catendé - Live - Vinícius de Moraes"); the artist is after the LAST one.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from .spotify_csv import URL as SPOTIFY_URL, _next_data, fetch_entity


@dataclass
class Row:
    position: int
    title: str
    artist: str
    duration_s: int | None
    spotify_id: str | None = None
    album: str | None = None
    note: str | None = None


def rows_from_spotify(entity: dict) -> list[Row]:
    out = []
    for i, t in enumerate(entity["trackList"], 1):
        artist = re.sub(r",\s*", ", ", t["subtitle"].replace("\xa0", " ")).strip()
        sid = t.get("uri", "").split(":")[-1] or None
        out.append(Row(i, t["title"].strip(), artist, round(t["duration"] / 1000), sid))
    return out


_STATUS = re.compile(r"^\[(SUCCESS|SKIPPED)\] (.*)$")
_ERROR = re.compile(r"^\d+\. (.*)$")
_ALBUM = re.compile(r"^(.*) \(([^()]*)\)$")           # "Title - Artist (Album)" → the LAST parenthetical


def _split_title_artist(s: str) -> tuple[str, str]:
    title, _, artist = s.rpartition(" - ")
    return (title.strip(), artist.strip()) if title else (s.strip(), "")


def rows_from_report(text: str) -> list[Row]:
    rows: list[Row] = []
    for line in text.splitlines():
        m = _STATUS.match(line)
        if m:
            title, artist = _split_title_artist(m.group(2))
            rows.append(Row(len(rows) + 1, title, artist, None, note=m.group(1).lower()))
            continue
        m = _ERROR.match(line)
        if m:
            body, album = m.group(1), None
            am = _ALBUM.match(body)
            if am:
                body, album = am.group(1), am.group(2)
            title, artist = _split_title_artist(body)
            rows.append(Row(len(rows) + 1, title, artist, None, album=album, note="error"))
            continue
        if rows and rows[-1].note and rows[-1].note.startswith("error") and line.startswith("   "):
            key, _, val = line.strip().partition(": ")
            if key == "Error":
                rows[-1].note = "error: " + val
            elif key == "ID":
                rows[-1].spotify_id = val
    return rows


def rows_from_csv(text: str) -> list[Row]:
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for i, r in enumerate(reader, 1):
        if "Track Name" in r:                                  # Exportify
            ms = r.get("Duration (ms)") or ""
            sid = (r.get("Track URI") or "").split(":")[-1] or None
            out.append(Row(i, r["Track Name"].strip(), (r.get("Artist Name(s)") or "").strip(),
                           round(int(ms) / 1000) if ms.isdigit() else None, sid, (r.get("Album Name") or None)))
        else:                                                  # sockseek / spotify_csv: Artist,Title,Length
            length = (r.get("Length") or "").strip()
            out.append(Row(i, r["Title"].strip(), r["Artist"].strip(), int(float(length)) if length else None))
    return out


def concat(groups: list[list[Row]]) -> list[Row]:
    out = []
    for g in groups:
        for r in g:
            out.append(Row(len(out) + 1, r.title, r.artist, r.duration_s, r.spotify_id, r.album, r.note))
    return out


def load(src: str, fetch=fetch_entity) -> tuple[str, list[Row]]:
    if SPOTIFY_URL.search(src):
        entity = fetch(src)
        return entity["name"].strip(), rows_from_spotify(entity)
    p = Path(src)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".csv":
        return p.stem, rows_from_csv(text)
    return p.stem, rows_from_report(text)


def _track_lead(spotify_id: str) -> str | None:
    try:
        return _next_data(f"track/{spotify_id}")["artists"][0]["name"]
    except (SystemExit, KeyError, IndexError, TypeError):
        return None


def lead_artist(row: Row, resolve=_track_lead) -> str:
    """Report rows separate artists with ';' so the first segment is exact. Spotify/Exportify join
    with ', ', which mangles 'Earth, Wind & Fire' — ask the track's own embed when we have its id."""
    if ";" in row.artist:
        return row.artist.split(";")[0].strip()
    if "," not in row.artist:
        return row.artist
    if row.spotify_id:
        got = resolve(row.spotify_id)
        if got:
            return got
    return row.artist.split(",")[0].strip()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/pytest -q tests/test_playlist_sources.py`
Expected: `10 passed`

- [ ] **Step 5: Run the whole suite, then commit**

Run: `~/.local/bin/pytest -q` → `90 passed`
```bash
git add sourcing/playlist_sources.py tests/test_playlist_sources.py
git commit -m "sourcing: playlist_sources — Spotify embed, Exportify/sockseek CSV and SpotiFLAC report → Row list"
```

---

### Task 2: Store — wanted rows remember their playlist and position

**Files:**
- Modify: `crates/store.py` (schema after `external_wanted`, `__init__`, `add_external_wanted`, `_insert_external`, `_ext_row`)
- Test: `tests/test_crates.py` (append)

**Interfaces:**
- Produces: `CrateStore.add_external_wanted(artist, title, album=None, duration_s=None, year=None, source=None, playlist_id=None, position=None) -> str` (existing row: `playlist_id`/`position` are updated when given); `_ext_row` dicts carry `playlist_id` and `position`; `CrateStore.external_for_playlist(playlist_id) -> list[dict]` ordered by position.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_crates.py`)

```python
def test_external_wanted_remembers_playlist_and_position(tmp_path):
    store = CrateStore(tmp_path / "c.db")
    ext = store.add_external_wanted("Chic", "Good Times", duration_s=501, source="report", playlist_id="pl-9", position=3)
    row = store.external(ext)
    assert row["playlist_id"] == "pl-9" and row["position"] == 3
    # same artist/title again from another playlist position → same row, position updated, still one row
    assert store.add_external_wanted("chic", "good times!", playlist_id="pl-9", position=7) == ext
    assert store.external_count() == 1 and store.external(ext)["position"] == 7
    # re-adding without a playlist leaves the remembered one alone
    store.add_external_wanted("Chic", "Good Times")
    assert store.external(ext)["playlist_id"] == "pl-9"
    assert [r["song_id"] for r in store.external_for_playlist("pl-9")] == [ext]


def test_store_migrates_old_external_wanted_table(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE external_wanted (id INTEGER PRIMARY KEY, artist TEXT NOT NULL, title TEXT NOT NULL,
        album TEXT, year INTEGER, duration INTEGER, source TEXT, status TEXT NOT NULL DEFAULT 'needs_source', reason TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL);
        INSERT INTO external_wanted(artist,title,created_at,updated_at) VALUES('A','B',0,0);""")
    con.commit(); con.close()
    store = CrateStore(db)                      # must add the two columns without losing the row
    assert store.external("ext-1")["playlist_id"] is None and store.external_count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/pytest -q tests/test_crates.py -k "remembers_playlist or migrates"`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'playlist_id'` and `sqlite3.OperationalError`/`KeyError: 'playlist_id'`

- [ ] **Step 3: Implement**

In `crates/store.py`, schema: add two columns to the `CREATE TABLE IF NOT EXISTS external_wanted` block after `reason TEXT,`:
```sql
  playlist_id TEXT, position INTEGER,             -- import-playlist: where a later fetch inserts the track
```
In `__init__`, after `self.db.executescript(SCHEMA)`:
```python
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was created (CREATE IF NOT EXISTS does not alter)."""
        have = {r[1] for r in self.db.execute("PRAGMA table_info(external_wanted)")}
        for col, typ in (("playlist_id", "TEXT"), ("position", "INTEGER")):
            if col not in have:
                self.db.execute(f"ALTER TABLE external_wanted ADD COLUMN {col} {typ}")
        self.db.commit()
```
Replace `add_external_wanted` / `_insert_external`:
```python
    def add_external_wanted(self, artist: str, title: str, album: str | None = None, duration_s: float | None = None,
                            year: int | None = None, source: str | None = None,
                            playlist_id: str | None = None, position: int | None = None) -> str:
        """Returns the existing id when the same artist/title is already queued (re-running a seed is a no-op);
        a playlist position, when given, is (re)recorded on that row."""
        existing = self.find_external(artist, title)
        if existing:
            if playlist_id is not None:
                self.db.execute("UPDATE external_wanted SET playlist_id=?, position=?, updated_at=? WHERE id=?",
                                (playlist_id, position, time.time(), _ext_pk(existing["song_id"])))
            return existing["song_id"]
        return self._insert_external(artist, title, album, duration_s, year, source, playlist_id, position)

    def _insert_external(self, artist, title, album, duration_s, year, source, playlist_id=None, position=None) -> str:
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO external_wanted(artist,title,album,year,duration,source,playlist_id,position,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (artist, title, album, year, int(duration_s) if duration_s else None, source, playlist_id, position, now, now))
        self.log(None, f"ext-{cur.lastrowid}", "wanted", f"{artist} — {title}")
        return f"ext-{cur.lastrowid}"

    def external_for_playlist(self, playlist_id: str) -> list[dict]:
        return [self._ext_row(r) for r in self.db.execute(
            "SELECT * FROM external_wanted WHERE playlist_id=? ORDER BY position, id", (playlist_id,))]
```
(`_ext_row` already does `dict(r)`, so the new columns come through unchanged.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/pytest -q tests/test_crates.py` → all pass (existing external tests unchanged).

- [ ] **Step 5: Full suite and commit**

Run: `~/.local/bin/pytest -q` → `92 passed`
```bash
git add crates/store.py tests/test_crates.py
git commit -m "store: external_wanted remembers playlist_id/position; column migration for existing DBs"
```

---

### Task 3: Fake Navidrome mirrors the live fixtures; the matcher

**Files:**
- Modify: `subsonic/fake_server.py` (`playlist_json`, `m_search3`)
- Create: `sourcing/import_playlist.py` (matching half)
- Test: `tests/test_subsonic.py` (append), `tests/test_import_playlist.py` (new)

**Interfaces:**
- Consumes: `SubsonicClient.search_songs(query, count) -> list[Song]` (`Song.id/title/artist/album/duration/path`), `playlist_sources.Row`.
- Produces:
  ```python
  TOLERANCE_S = 4
  @dataclass
  class Match:
      row: Row
      status: str                 # "matched" | "ambiguous" | "missing"
      song_id: str | None = None
      candidates: list[str] = field(default_factory=list)   # ids considered (ambiguous → the tie)
      picked: Song | None = None
  def norm(s: str | None) -> str                 # casefold, strip accents, drop everything but letters/digits
  def query_words(*parts: str) -> list[str]      # words of ≥2 chars, punctuation removed, feat./parenthetical kept as words
  def build_query(row: Row) -> str               # artist words + title words
  def choose(row: Row, hits: list[Song]) -> Match
  def match(client: SubsonicClient, row: Row) -> Match     # search3 artist+title; no hits → title-only words
  ```

**Fixture facts this task copies** (`fixtures/navidrome_playlist_song_search3.sample.json`): `getPlaylists_sample[*]` has no `public` key at all for a non-public playlist (keys: changed, coverArt, created, duration, id, name, owner, readonly, songCount). Live probes 2026-10-13: `search3 "Catende Live Vinicius de Moraes"` finds "Catendé - Live" (accent-insensitive); `"Earth, Wind & Fire After the Love Has Gone"` finds the track (punctuation ignored); `"Michael Kiwanuka Piano Joint (This Kind Of Love)"` → 0 (not in library, correct); `"Donald Byrd The Weasil"` → two hits 540 s / 538 s (redundant copies).

- [ ] **Step 1: Write the failing fake-server tests** (append to `tests/test_subsonic.py`)

```python
def test_fake_omits_public_when_false_like_navidrome():
    # fixtures/navidrome_playlist_song_search3.sample.json: getPlaylists entries have no "public" key when not public
    from subsonic.fake_server import FakeState
    st = FakeState()
    d = st.playlist_json(st.playlists["pl-1"], False)
    assert "public" not in d
    st.playlists["pl-1"]["public"] = True
    assert st.playlist_json(st.playlists["pl-1"], False)["public"] is True


def test_fake_search3_folds_accents_and_punctuation():
    with FakeSubsonicServer() as srv:
        srv.state.songs["s9"] = dict(srv.state.songs["s1"], id="s9", title="Catendé - Live", artist="Vinícius de Moraes • Maria Creuza", duration=302)
        c = SubsonicClient(srv.url, "demo", "demo")
        assert [s.id for s in c.search_songs("Catende Live Vinicius de Moraes")] == ["s9"]
        assert [s.id for s in c.search_songs("Earth, Wind & Fire good times")] == []
        assert [s.id for s in c.search_songs("chic good-times")] == ["s1"]
```
(`FakeSubsonicServer` and `SubsonicClient` are already imported at the top of `tests/test_subsonic.py`; check and add if not.)

- [ ] **Step 2: Run them to verify they fail**

Run: `~/.local/bin/pytest -q tests/test_subsonic.py -k "omits_public or folds"`
Expected: FAIL — `"public" in d` and the accent query returns `[]`.

- [ ] **Step 3: Fix the fake**

In `subsonic/fake_server.py`, `playlist_json`: replace `"public": p["public"],` by building the dict without it and then
```python
        if p.get("public"):            # Navidrome omits the key when false (fixture: getPlaylists_sample)
            d["public"] = True
```
Add a module-level helper under `API_VERSION`:
```python
def _fold(s: str) -> str:
    """Navidrome's full-text search is case-, accent- and punctuation-insensitive; so is the fake."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s if not unicodedata.combining(ch)).casefold()
```
and in `m_search3` replace the two matching lines with
```python
            words = _fold(q.get("query", "")).split()      # Navidrome: every word must match somewhere
            hits = [dict(s, isDir=False, type="music") for s in state.songs.values()
                    if all(w in _fold(f"{s['title']} {s['artist']} {s['album']}") for w in words)]
```

- [ ] **Step 4: Run the fake tests, then the whole suite**

Run: `~/.local/bin/pytest -q tests/test_subsonic.py` → pass. `~/.local/bin/pytest -q` → `94 passed` (nothing else relied on `public: false` being present — if a test does, it is asserting the wrong contract; fix the test and say so in the commit).

- [ ] **Step 5: Commit the fake fix**

```bash
git add subsonic/fake_server.py tests/test_subsonic.py
git commit -m "fake_server: omit public when false and fold accents/punctuation in search3 (mirrors live Navidrome fixtures)"
```

- [ ] **Step 6: Write the failing matcher tests**

```python
# tests/test_import_playlist.py
from sourcing import import_playlist as ip
from sourcing.playlist_sources import Row
from subsonic.client import Song, SubsonicClient
from subsonic.fake_server import FakeSubsonicServer


def song(id, title, artist, duration, path="x/y.flac", album="A"):
    return Song.from_json({"id": id, "title": title, "artist": artist, "album": album, "duration": duration, "path": path})


def test_norm_and_query_words():
    assert ip.norm("Catendé - Live!") == "catendelive"
    assert ip.query_words("Earth, Wind & Fire", "After the Love Has Gone") == ["earth", "wind", "fire", "after", "the", "love", "has", "gone"]
    assert ip.build_query(Row(1, "Piano Joint (This Kind Of Love)", "Michael Kiwanuka", 232)) == "michael kiwanuka piano joint this kind of love"


def test_choose_by_duration_within_tolerance():
    row = Row(1, "After the Love Has Gone", "Earth, Wind & Fire", 278)
    hits = [song("a", "After The Love Has Gone", "Earth, Wind & Fire", 267), song("b", "After the Love Has Gone", "Earth, Wind & Fire", 278)]
    m = ip.choose(row, hits)
    assert m.status == "matched" and m.song_id == "b"


def test_choose_treats_redundant_copies_as_one_track():
    row = Row(1, "The Weasil", "Donald Byrd", 541)
    hits = [song("c1", "The Weasil", "Donald Byrd", 540, path="Compilations/Tea tent/01 - The Weasil.flac"),
            song("c2", "The Weasil", "Donald Byrd", 538, path="Donald Byrd/Fancy Free (1970)/01 - The Weasil.flac")]
    m = ip.choose(row, hits)
    assert m.status == "matched" and m.song_id == "c1"           # nearest duration wins
    hits[1].duration = 540
    assert ip.choose(row, hits).song_id == "c2"                  # tie → the copy not under Compilations/


def test_choose_is_ambiguous_when_two_different_tracks_fit():
    row = Row(1, "The Magician", "Twain", None)                  # report row: no duration
    hits = [song("t1", "The Magician", "Twain", 353, album="Rare Feeling"), song("t2", "The Magician (Live)", "Twain", 300)]
    assert ip.choose(row, hits).status == "matched" and ip.choose(row, hits).song_id == "t1"   # exact normalised title wins
    hits[1].title = "The Magician"; hits[1].album = "Live at X"      # same name, 353 s vs 300 s: two recordings
    m = ip.choose(row, hits)
    assert m.status == "ambiguous" and set(m.candidates) == {"t1", "t2"}
    hits[1].duration = 351                                             # within ±4 s of each other → one track, two copies
    assert ip.choose(row, hits).status == "matched"


def test_choose_without_duration_needs_title_and_lead_artist():
    row = Row(1, "A Change Is Gonna Come", "Jennifer Lara", None)
    assert ip.choose(row, [song("j", "A Change Is Gonna Come - Jennifer Lara", "Studio One", 145)]).status == "matched"
    assert ip.choose(row, [song("k", "A Change Is Gonna Come", "Sam Cooke", 190)]).status == "missing"
    assert ip.choose(row, []).status == "missing"


def test_match_retries_with_title_only_words():
    with FakeSubsonicServer() as srv:
        srv.state.songs["m1"] = dict(srv.state.songs["s1"], id="m1", title="Smokey Robinson - Why You Wanna See My Bad Side.mp3", artist="100 - Smokey Robinson", duration=224)
        c = SubsonicClient(srv.url, "demo", "demo")
        assert ip.match(c, Row(1, "Why You Wanna See My Bad Side", "Smokey Robinson", 224)).song_id == "m1"
        assert ip.match(c, Row(2, "Why You Wanna See My Bad Side", "William Robinson Jr.", 224)).song_id == "m1"   # artist words miss → title-only retry
        assert ip.match(c, Row(3, "Piano Joint", "Michael Kiwanuka", 232)).status == "missing"
```

- [ ] **Step 7: Run them to verify they fail**

Run: `~/.local/bin/pytest -q tests/test_import_playlist.py` → `ModuleNotFoundError: sourcing.import_playlist`

- [ ] **Step 8: Implement the matching half**

```python
# sourcing/import_playlist.py
"""Spotify/report playlist rows → Navidrome playlist + wanted rows (spec §2a, D11).

Matching, in order: search3 on artist+title words (Navidrome ignores case, accents and punctuation;
every word must hit) → keep hits within ±4 s when the row has a duration → else hits whose normalised
title and lead artist both appear in the hit's normalised "artist title" → nearest duration →
redundant copies (same normalised artist|title, lengths within ±4 s of each other) collapse to the
one outside Compilations/ → still >1 distinct track → ambiguous. No hits at all → retry with the title words only (library titles
sometimes carry the artist, e.g. "A Change Is Gonna Come - Jennifer Lara").
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from subsonic.client import Song, SubsonicClient
from .playlist_sources import Row, lead_artist

TOLERANCE_S = 4


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if ch.isalnum() and not unicodedata.combining(ch)).casefold()


def query_words(*parts: str) -> list[str]:
    text = unicodedata.normalize("NFKD", " ".join(parts))
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text if not unicodedata.combining(ch))
    return [w for w in text.casefold().split() if len(w) >= 2]


def build_query(row: Row) -> str:
    return " ".join(query_words(row.artist.replace(";", " "), row.title))


@dataclass
class Match:
    row: Row
    status: str
    song_id: str | None = None
    candidates: list[str] = field(default_factory=list)
    picked: Song | None = None


def _key(s: Song) -> str:
    return norm(s.artist) + "|" + norm(s.title)


def choose(row: Row, hits: list[Song]) -> Match:
    if not hits:
        return Match(row, "missing")
    if row.duration_s is not None:
        fit = [h for h in hits if h.duration is not None and abs(h.duration - row.duration_s) <= TOLERANCE_S]
        if fit:
            best = min(abs(h.duration - row.duration_s) for h in fit)
            fit = [h for h in fit if abs(h.duration - row.duration_s) == best]
    else:
        fit = []
    if not fit:
        title, lead = norm(row.title), norm(lead_artist(row, resolve=lambda sid: None))
        fit = [h for h in hits if title and title in norm(f"{h.artist} {h.title}") and lead and lead in norm(f"{h.artist} {h.title}")]
        exact = [h for h in fit if norm(h.title) == title or norm(h.title).endswith(title + lead) or norm(h.title) == title + lead]
        if exact:
            fit = exact
    if not fit:
        return Match(row, "missing", candidates=[h.id for h in hits])
    distinct = {_key(h) for h in fit}
    durs = [h.duration for h in fit if h.duration is not None]
    # Same artist|title twice is a redundant copy only when the lengths agree; "The Magician" 353 s
    # vs 300 s are two recordings, and without a row duration we cannot pick → ambiguous.
    if len(distinct) > 1 or (durs and max(durs) - min(durs) > TOLERANCE_S):
        return Match(row, "ambiguous", candidates=[h.id for h in fit])
    fit.sort(key=lambda h: (h.path or "").startswith("Compilations/"))      # the properly filed copy first
    return Match(row, "matched", fit[0].id, [h.id for h in fit], fit[0])


def match(client: SubsonicClient, row: Row) -> Match:
    hits = client.search_songs(build_query(row), count=20)
    if not hits:
        title_only = " ".join(query_words(row.title))
        hits = client.search_songs(title_only, count=20) if title_only else []
    return choose(row, hits)
```
Note on `lead_artist(..., resolve=lambda sid: None)`: matching never touches the network; the comma fallback (first segment) is fine for a containment check because the full artist words were already required by `search3`.

- [ ] **Step 9: Run the matcher tests, then the suite**

Run: `~/.local/bin/pytest -q tests/test_import_playlist.py` → `6 passed`; `~/.local/bin/pytest -q` → `100 passed`.

- [ ] **Step 10: Commit**

```bash
git add sourcing/import_playlist.py tests/test_import_playlist.py
git commit -m "import_playlist: search3 word-wise match, ±4 s duration, copy-dedupe, ambiguity"
```

---

### Task 4: Builder — public playlist in order, idempotent, wanted rows with positions

**Files:**
- Modify: `sourcing/import_playlist.py` (append)
- Test: `tests/test_import_playlist.py` (append)

**Interfaces:**
- Consumes: Task 2 `store.add_external_wanted(..., playlist_id, position)`, `store.set_external_status`, `store.external_for_playlist`; `SubsonicClient.playlists/playlist/create_playlist/update_playlist`.
- Produces:
  ```python
  @dataclass
  class Report:
      name: str
      playlist_id: str | None
      created: bool
      matches: list[Match]
      added: int                 # entries appended this run
      @property matched / wanted / ambiguous -> int
      def table(self) -> str     # one line per row: "  3  matched    Donald Byrd — The Weasil  → <id>"
  def import_playlist(name: str, rows: list[Row], client: SubsonicClient, store: CrateStore,
                      source: str, dry_run: bool = False) -> Report
  ```

- [ ] **Step 1: Write the failing tests** (append to `tests/test_import_playlist.py`)

```python
from crates.store import CrateStore


def _lib(srv):
    s = srv.state.songs
    s["w1"] = dict(s["s1"], id="w1", title="The Weasil", artist="Donald Byrd", duration=540, path="Donald Byrd/Fancy Free (1970)/01 - The Weasil.flac")
    s["w2"] = dict(s["s1"], id="w2", title="The Weasil", artist="Donald Byrd", duration=538, path="Compilations/Tea tent/01 - The Weasil.flac")
    s["k1"] = dict(s["s1"], id="k1", title="Bag Lady", artist="Erykah Badu", duration=347)
    s["t1"] = dict(s["s1"], id="t1", title="The Magician", artist="Twain", duration=353, album="Rare Feeling")
    s["t2"] = dict(s["s1"], id="t2", title="The Magician", artist="Twain", duration=300, album="Live")


ROWS = [Row(1, "The Weasil", "Donald Byrd", 541, "sp1"), Row(2, "Piano Joint (This Kind Of Love)", "Michael Kiwanuka", 232, "sp2"),
        Row(3, "Bag Lady", "Erykah Badu", 347, "sp3"), Row(4, "The Magician", "Twain", None, "sp4")]


def test_import_creates_public_playlist_in_order_and_queues_the_rest():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rep = ip.import_playlist("Tea tent", ROWS, c, store, source="https://open.spotify.com/playlist/x")
        assert rep.created and rep.matched == 2 and rep.wanted == 1 and rep.ambiguous == 1 and rep.added == 2
        pl = c.playlist(rep.playlist_id)
        assert pl.name == "Tea tent" and pl.public is True and [e.id for e in pl.entries] == ["w1", "k1"]
        ext = store.external_for_playlist(rep.playlist_id)
        assert [(r["artist"], r["title"], r["position"], r["status"]) for r in ext] == [
            ("Michael Kiwanuka", "Piano Joint (This Kind Of Love)", 2, "needs_source"),
            ("Twain", "The Magician", 4, "verify")]
        assert ext[1]["reason"].startswith("ambiguous: ") and set(ext[1]["reason"][11:].split(", ")) == {"t1", "t2"}
        assert ext[0]["source"] == "https://open.spotify.com/playlist/x" and ext[0]["duration"] == 232
        assert "matched" in rep.table() and "The Weasil" in rep.table()


def test_import_is_idempotent_and_never_removes_or_duplicates():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        # Michael removes one entry and adds his own by hand
        c.update_playlist(first.playlist_id, remove_indexes=[1], add_song_ids=["s5"])
        second = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert not second.created and second.playlist_id == first.playlist_id and second.added == 1
        assert [e.id for e in c.playlist(first.playlist_id).entries] == ["w1", "s5", "k1"]   # s5 kept, k1 re-added once
        assert store.external_count() == 2
        third = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert third.added == 0 and [e.id for e in c.playlist(first.playlist_id).entries] == ["w1", "s5", "k1"]


def test_import_makes_an_existing_private_playlist_public_and_dry_run_touches_nothing():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        existing = c.create_playlist("Tea tent", ["k1"])
        dry = ip.import_playlist("Tea tent", ROWS, c, store, source="s", dry_run=True)
        assert dry.playlist_id == existing.id and dry.matched == 2 and dry.added == 1   # what it *would* add
        assert [e.id for e in c.playlist(existing.id).entries] == ["k1"] and c.playlist(existing.id).public is False
        assert store.external_count() == 0
        rep = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert rep.playlist_id == existing.id and c.playlist(existing.id).public is True
        assert [e.id for e in c.playlist(existing.id).entries] == ["k1", "w1"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `~/.local/bin/pytest -q tests/test_import_playlist.py -k import_` → `AttributeError: module 'sourcing.import_playlist' has no attribute 'import_playlist'`

- [ ] **Step 3: Implement** (append to `sourcing/import_playlist.py`; add `from crates.store import CrateStore` to the imports)

```python
@dataclass
class Report:
    name: str
    playlist_id: str | None
    created: bool
    matches: list[Match]
    added: int

    def _count(self, status: str) -> int:
        return sum(1 for m in self.matches if m.status == status)

    @property
    def matched(self) -> int: return self._count("matched")
    @property
    def wanted(self) -> int: return self._count("missing")
    @property
    def ambiguous(self) -> int: return self._count("ambiguous")

    def table(self) -> str:
        lines = []
        for m in self.matches:
            tail = f"→ {m.song_id}" if m.song_id else (f"? {', '.join(m.candidates)}" if m.candidates else "")
            lines.append(f"{m.row.position:4d}  {m.status:<9}  {m.row.artist} — {m.row.title}  {tail}".rstrip())
        lines.append(f"{self.name}: {self.matched} matched, {self.wanted} wanted, {self.ambiguous} ambiguous"
                     + (f"; {self.added} added to playlist {self.playlist_id}" if self.playlist_id else ""))
        return "\n".join(lines)


def import_playlist(name: str, rows: list[Row], client: SubsonicClient, store: CrateStore,
                    source: str, dry_run: bool = False) -> Report:
    matches = [match(client, r) for r in rows]
    ordered: list[str] = []
    for m in matches:
        if m.status == "matched" and m.song_id not in ordered:
            ordered.append(m.song_id)
    existing = next((p for p in client.playlists() if p.name == name), None)
    created = existing is None
    if existing is None:
        new_ids, playlist_id = ordered, None
    else:
        have = {e.id for e in client.playlist(existing.id).entries}
        new_ids, playlist_id = [i for i in ordered if i not in have], existing.id
    if not dry_run:
        if existing is None:
            playlist_id = client.create_playlist(name, new_ids).id
            client.update_playlist(playlist_id, public=True)              # spec §2a: visible to every user
        else:
            if new_ids:
                client.update_playlist(existing.id, add_song_ids=new_ids)
            if not existing.public:
                client.update_playlist(existing.id, public=True)
        for m in matches:
            if m.status == "matched":
                continue
            ext = store.add_external_wanted(lead_artist(m.row), m.row.title, album=m.row.album, duration_s=m.row.duration_s,
                                            source=source, playlist_id=playlist_id, position=m.row.position)
            if m.status == "ambiguous":
                store.set_external_status(ext, "verify", "ambiguous: " + ", ".join(m.candidates))
        store.commit()
    return Report(name, playlist_id, created, matches, len(new_ids))
```
`lead_artist(m.row)` uses the default resolver, which asks Spotify only for comma-joined artists with a track id (tests use report-style rows or single artists, so no network).

- [ ] **Step 4: Run the tests, then the suite**

Run: `~/.local/bin/pytest -q tests/test_import_playlist.py` → `9 passed`; `~/.local/bin/pytest -q` → `103 passed`.

- [ ] **Step 5: Commit**

```bash
git add sourcing/import_playlist.py tests/test_import_playlist.py
git commit -m "import_playlist: build/update a public playlist in order; wanted rows carry playlist+position; dry-run"
```

---

### Task 5: CLI `import-playlist`, `crates.cli publish`, docs

**Files:**
- Modify: `sourcing/cli.py` (docstring, new subparser, handler)
- Modify: `crates/cli.py` (new `publish` subcommand)
- Modify: `Dockerfile` (`COPY scripts/ scripts/` so scripts can run in the container — runbook rule 4)
- Modify: `README.md` (command list), `docs/specs/2026-10-13-next-session-design.md` §2a (one line: implemented, date)
- Test: `tests/test_sourcing_cli.py`, `tests/test_crates.py` (append)

**Interfaces:**
- `python3 -m sourcing.cli import-playlist SRC [SRC …] [--name N] [--dry-run]` — several sources concatenate in order into one playlist; without `--name` exactly one source is allowed and its own name is used. Exit 0 on success, 1 on a bad/unreachable source (nothing written), 2 when `SUBSONIC_USER/PASS` are missing.
- `python3 -m crates.cli publish [NAME …]` — makes the named (default: all) playlists public; prints one line per playlist.

- [ ] **Step 1: Write the failing CLI tests** (append to `tests/test_sourcing_cli.py`)

```python
def _env(monkeypatch, nd, db):
    monkeypatch.setenv("SUBSONIC_URL", nd.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
    monkeypatch.setenv("CRATES_DB", str(db))


def test_import_playlist_from_report_and_two_urls(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"
    report = tmp_path / "nothin to it.txt"
    report.write_text("Download Report - x\n---\n\n[SUCCESS] Good Times - Chic\n[SUCCESS] Nope - Nobody\n")
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        rc = cli.main(["import-playlist", str(report)])
        out = capsys.readouterr().out
        assert rc == 0 and "nothin to it: 1 matched, 1 wanted, 0 ambiguous" in out
        from subsonic.client import SubsonicClient
        c = SubsonicClient(nd.url, "demo", "demo")
        pl = next(p for p in c.playlists() if p.name == "nothin to it")
        assert pl.public and [e.id for e in c.playlist(pl.id).entries] == ["s1"]
        w = CrateStore(db).external_for_playlist(pl.id)
        assert [(x["title"], x["position"]) for x in w] == [("Nope", 2)]

        e1 = {"name": "Tea tent", "trackList": [{"title": "I Feel Love", "subtitle": "Donna Summer", "duration": 356_000, "uri": "spotify:track:a"}]}
        e2 = {"name": "Tea tent2222", "trackList": [{"title": "Strings of Life", "subtitle": "Rhythim Is Rhythim", "duration": 480_000, "uri": "spotify:track:b"}]}
        monkeypatch.setattr(cli, "fetch_entity", lambda url: e1 if url.endswith("/one") else e2)
        rc = cli.main(["import-playlist", "--name", "Tea tent", "https://open.spotify.com/playlist/one", "https://open.spotify.com/playlist/two"])
        assert rc == 0 and "Tea tent: 2 matched, 0 wanted, 0 ambiguous" in capsys.readouterr().out
        pl = next(p for p in c.playlists() if p.name == "Tea tent")
        assert [e.id for e in c.playlist(pl.id).entries] == ["s2", "s5"]


def test_import_playlist_rejects_two_sources_without_name_and_bad_url(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        assert cli.main(["import-playlist", "a.txt", "b.txt"]) == 1
        assert "--name" in capsys.readouterr().err
        def boom(url): raise SystemExit("embed page had no __NEXT_DATA__ (private playlist, or Spotify changed the page)")
        monkeypatch.setattr(cli, "fetch_entity", boom)
        assert cli.main(["import-playlist", "https://open.spotify.com/playlist/private"]) == 1
        assert "private playlist" in capsys.readouterr().err
        assert len(nd.state.playlists) == 3 and not db.exists()
```
And in `tests/test_crates.py`:
```python
def test_publish_makes_playlists_public(env, capsys):
    from crates.cli import main
    assert main(["publish", "Disco Edits"]) == 0
    st = env.server.state.playlists
    assert st["pl-1"]["public"] is True and st["pl-2"]["public"] is False
    assert main(["publish"]) == 0 and all(p["public"] for p in st.values())
    assert "public already" in capsys.readouterr().out
```
(Check how the existing `env` fixture in `tests/test_crates.py` exposes the fake server and sets `SUBSONIC_*` env; use its attribute names. If `crates.cli.main` reads `Config.from_env()`, the fixture already sets the env for the other CLI tests — confirm with `grep -n "env" tests/test_crates.py | head`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `~/.local/bin/pytest -q tests/test_sourcing_cli.py tests/test_crates.py -k "import_playlist or publish"` → `argparse` error `invalid choice: 'import-playlist'` / `'publish'`.

- [ ] **Step 3: Implement the CLI**

`sourcing/cli.py` — docstring gets one line:
```
  python -m sourcing.cli import-playlist <spotify-url|report.txt|exportify.csv>... [--name N] [--dry-run]   # D11: Spotify playlists → public Navidrome playlist + wanted rows
```
subparser, after `seed-spotify`:
```python
    ip = sub.add_parser("import-playlist", help="Spotify URL / Exportify CSV / SpotiFLAC report → public Navidrome playlist; the rest become wanted rows")
    ip.add_argument("sources", nargs="+", help="several sources concatenate in order into one playlist (needs --name)")
    ip.add_argument("--name", help="playlist name (default: the source's own name; required with several sources)")
    ip.add_argument("--dry-run", action="store_true", help="match and report, write nothing")
```
handler, before `if a.cmd == "seed-spotify":`:
```python
    if a.cmd == "import-playlist":
        from crates.service import Config
        from crates.store import CrateStore
        from subsonic.client import SubsonicClient
        from .import_playlist import import_playlist
        from .playlist_sources import concat, load
        if len(a.sources) > 1 and not a.name:
            print("several sources make one playlist: say which with --name", file=sys.stderr); return 1
        cfg = Config.from_env()
        if not (cfg.username and cfg.password):
            print("set SUBSONIC_USER / SUBSONIC_PASS (and SUBSONIC_URL)", file=sys.stderr); return 2
        groups, name = [], a.name
        for src in a.sources:
            try:
                src_name, rows = load(src, fetch=fetch_entity)
            except (SystemExit, OSError) as e:          # private playlist, no network, missing file: nothing written
                print(f"{src}: {e}", file=sys.stderr); return 1
            groups.append(rows); name = name or src_name
        rows = concat(groups)
        Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
        store = CrateStore(cfg.db_path)
        rep = import_playlist(name, rows, SubsonicClient(cfg.subsonic_url, cfg.username, cfg.password), store,
                              source=" ".join(a.sources), dry_run=a.dry_run)
        print(rep.table())
        if a.dry_run:
            print("(dry run: nothing written)")
        return 0
```
`fetch_entity` is already imported at module top (the test monkeypatches `cli.fetch_entity`), which is why `load(src, fetch=fetch_entity)` passes it explicitly. Note the bad-URL test asserts the DB file does not exist afterwards: the store is only opened after every source loaded.

`crates/cli.py` — add `p = sub.add_parser("publish"); p.add_argument("names", nargs="*", help="playlist names (default: all)")` next to the other subparsers, and a branch:
```python
    elif a.cmd == "publish":
        for pl in app.api.playlists():
            if a.names and pl.name not in a.names:
                continue
            if pl.public:
                print(f"public already  {pl.name}")
            else:
                app.api.update_playlist(pl.id, public=True); print(f"made public     {pl.name}")
```
(`app.api` is the `SubsonicClient` the fetch command already uses as `navidrome=app.api`.)

`Dockerfile`: add `COPY scripts/ scripts/` after `COPY web/ web/`.

- [ ] **Step 4: Run the tests, then the suite**

Run: `~/.local/bin/pytest -q` → `106 passed`.

- [ ] **Step 5: Docs**

`README.md`: in the command list add
```
python3 -m sourcing.cli import-playlist <spotify-url|report.txt|exportify.csv>... [--name N] [--dry-run]
    # D11: Spotify playlist → public Navidrome playlist (library matches, in order) + wanted rows with playlist/position
python3 -m crates.cli publish [NAME ...]        # make playlists visible to every Navidrome user
```
Spec §2a: append to the "Acceptance" paragraph: `**Implemented 2026-10-13** (`sourcing/playlist_sources.py`, `sourcing/import_playlist.py`, `sourcing.cli import-playlist`, `crates.cli publish`).`

- [ ] **Step 6: Commit**

```bash
git add sourcing/cli.py crates/cli.py Dockerfile README.md docs/specs/2026-10-13-next-session-design.md tests/test_sourcing_cli.py tests/test_crates.py
git commit -m "cli: import-playlist (URL/CSV/report → public playlist + wanted rows) and crates.cli publish; scripts/ in the image"
```

---

### Task 6: Run it live (runbook M1 steps 3–5) — not code, but the plan's acceptance

- [ ] Rebuild the image: `cd /srv/docker && docker compose up -d --build crates` (picks up the new code and `scripts/`).
- [ ] Dry run first on one report: `docker compose exec -T crates python3 -m sourcing.cli import-playlist --dry-run "/srv/incoming/library-import/playlists/perfect songs/perfect songs.txt"` — needs the report path inside the container: the crates service has no `/srv/incoming` volume, so copy the nine `.txt` files to `/srv/docker/crates/reports/` (bind-mounted as `/data`) and use `/data/reports/<name>.txt`. Read the table: matched / wanted / ambiguous must look sane before `--apply` (no `--dry-run`).
- [ ] Run all nine reports, then `--name "Tea tent" <url1> <url2>` and `<secondset url>`. Record matched / wanted / ambiguous per playlist in the runbook Status log.
- [ ] `docker compose exec -T crates python3 -m crates.cli publish` → 35 folder playlists public (verify with `getPlaylists`: `public: true` present).
- [ ] "What Michael will see": 10 random entries from the new playlists via `getPlaylist` — artist / title / album / playlist — as a table in the Status log.
- [ ] Code review (`superpowers:requesting-code-review`) on the branch diff, fix Critical/Important RED→GREEN, `/simplify`, milestone push.

---

## Self-review notes

- Spec §2a coverage: inputs (Task 1) ✓, matching rules (Task 3) ✓, wanted rows with playlist+position (Tasks 2, 4) ✓, idempotent/never-delete (Task 4) ✓, several URLs per `--name` (Task 5) ✓, public + folder playlists public (Tasks 4, 5) ✓, acceptance on the perfect-songs report (Task 6) ✓. Deferred by the spec itself: the web client's one-tap pick for ambiguous rows (they are visible as `verify` rows with `ambiguous: id, id` reasons).
- Names used consistently: `Row`, `Match`, `Report`, `norm`, `query_words`, `build_query`, `choose`, `match`, `import_playlist`, `lead_artist`, `concat`, `load`, `external_for_playlist`, `add_external_wanted(playlist_id=, position=)`.
- Known limit, stated: Spotify order is guaranteed on first creation; later runs append new matches at the end (Subsonic has no insert-at-index). A later `fetch` of a wanted row uses `position` to insert in place (fetch.py already swaps entries by index for crates; extending that to plain playlists is M6 work).
