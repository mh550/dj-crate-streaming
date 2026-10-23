# S2 plan: album tags and the album path (S2-06)

Milestone S2 of `docs/specs/2026-10-22-downloads-and-requests.md`, item 6 ("album path", Michael's answer of
2026-10-22, D50 in the pivot spec). Written by S2-06a; S2-06b builds it. A track filed for an **album request** carries
the request's album identity, written field by field on our own staged download before beets sees it, and lands at
`$albumartist/$album ($year)/$track - $title`, so the primary folder's, the secondary folder's and the per-track
fallback's files form one folder and one Navidrome album. Every other download is filed as today
(`$artist/Singles/$title`, `fill_missing_tags` only). Nothing here trashes a file or touches a library file during
filing; the only library-file write is the manual reverse below. Build-only: nothing live until a deploy, which is
Michael's (downloads checklist).


## Fields

Which rows: in S2-06b, a row with a `request_id` whose request has `kind = 'album'`. Nothing else: plain rows,
`track` and `playlist` requests get no album tags. (S2-07 later passes the same identity for a playlist's album
group; that is S2-07's own step, not S2-06b's.)

| field (mediafile name) | value | when the request lacks it |
|---|---|---|
| `album` | `requests.album` | never lacks it (an album request has a name) |
| `albumartist` | `requests.artist` | never lacks it |
| `track` | the row's `track_no` (position across all discs: the embed has no disc number, S2-02) | not written |
| `tracktotal` | the album's highest listed `track_no`, stored on the request by `add_spotify` (`requests.tracktotal`, S2-06b review: a duplicate title merged into one row or a row held by another request does not lower it), else the highest among the request's rows | not written |
| `year` | `requests.year`; `month` and `day` are cleared with it | **cleared** with `month` and `day` (D51 *default*) |
| `mb_albumid` | `requests.mb_release_id` (S2-03) | **cleared** (`None`) |
| `mb_albumartistid` | not written | **cleared** (`None`) together with `mb_albumid` |
| `comp` | `False` | written only when the file says `True` |

- **Only what differs is written.** The writer reads the staged file with `mediafile.MediaFile`, compares each field
  with the value above and writes only the fields that differ, in one `write_minimal` call. A file that already
  agrees is not saved at all (no `tagged` event). `comp=False` on a file without a `COMPILATION` tag would add
  `COMPILATION=0` (measured), so `comp` is in the diff only when the file says `True` (its old value is then always
  `true`).
- **Why clear when the request has no value.** Files from different peers carry their uploaders' own values. The
  path's `$year` splits one album into `Album (1972)/` and `Album/` (measured below). Navidrome groups albums by its
  album PID, by default `musicbrainz_albumid|albumartistid,album,albumversion,releasedate` (Navidrome's
  documentation for 0.55+, not measured on this box), where `albumartistid` follows `MUSICBRAINZ_ALBUMARTISTID` when a
  file has one: one file with an uploader's release id or album-artist id and one without would be two albums. With
  S2-03's release matched every file gets the same `mb_albumid` and the PID's first branch decides; without it
  `mb_albumid` and `mb_albumartistid` are cleared so the second branch sees the same album artist and name. The Al
  Green fixture has `releaseDate: null`, so an unknown `year` is the canonical case: cleared, all files share
  `Al Green/I'm Still in Love With You/` (D51 *default*: the alternative, the first filed file's year becoming
  `requests.year`, keeps a correct year but makes the folder depend on which peer came first).
- **How a clear lands on disk** (measured): `write_minimal(path, {"year": None, "month": None, "day": None})` removes
  `DATE`/`YEAR` (FLAC) and `TDRC` (MP3) outright. `write_minimal(path, {"mb_albumid": None})` removes the MP3's
  `TXXX:MusicBrainz Album Id` but leaves an empty `MUSICBRAINZ_ALBUMID=` in a FLAC (mediafile's none value); an empty
  id is no id for grouping (Navidrome documentation; the live check in `## Live steps` step 3 confirms it).
- **Not written** (left as the file has them): `artist`, `title` (`fill_missing_tags` still fills an empty one, as
  today), `disc`, `disctotal`, `mb_releasegroupid`, `albumtype`, `RELEASEDATE`/`ORIGINALDATE`, genres, other ids.
  See `## Out` for the grouping gap that leaves.
- **Fan-out on disk** (mediafile 0.12.0, measured): on FLAC `albumartist` writes `ALBUMARTIST`, `ALBUM ARTIST` and
  `ALBUM_ARTIST`; `track` writes `TRACKNUMBER` and `TRACK`; `tracktotal` writes `TRACKTOTAL`, `TOTALTRACKS` and
  `TRACKC`; `year` writes `DATE` and `YEAR`; `mb_albumid` writes `MUSICBRAINZ_ALBUMID`. On MP3 (ID3v2.4 kept):
  `TALB`, `TPE2`, `TRCK` (`1/9`), `TDRC`, `TXXX:MusicBrainz Album Id`; `write_minimal` also deletes the ID3
  album-artist aliases (`TXXX:ALBUM ARTIST` …). Only FLAC and MP3 were measured; `AUDIO_EXT` also has m4a (`trkn`
  holds track and total in one atom), ogg, opus, wma, wav and aiff, so S2-06b's tests cover m4a and ogg too (made
  with `tests.helpers.convert`, skipped without ffmpeg).

## Writer

`scripts.tag_cleanup.write_minimal(path, changes)` only: the one field-by-field writer (mediafile saves only the
fields set; the ID3 version is kept; ID3 aliases of a changed field go in the same save). Never `beet write`,
`beet modify` with writing, `beet import` without `-W` or `mbsync`: beets 1.6 rewrites every field it knows, which
collapsed multi-valued GENRE/ISRC and added zero DISCTOTAL/TRACKTOTAL in M2 (`docs/hard-won-facts.md` "beets 1.6",
`deploy/beets.yaml`'s header).

S2-06b's shape: `sourcing/filer.py` gains `AlbumIdentity(album, albumartist, track, tracktotal, year, mb_albumid)`
and, beside `fill_missing_tags` (same lazy import of `write_minimal`, same `MediaFile` read), `album_changes(path,
identity) -> (changes, old)`: the fields that differ and their current values (`year` with `month` and `day`).
`BeetsFiler.file(folder, log, names=…, album=identity, on_tagged=…)`, after `fill_missing_tags`:

1. computes `changes, old` on the one staged audio file; nothing differs → no write, no callback;
2. calls `on_tagged(old)`, which **logs and commits** the `tagged` event (`store.log` alone only INSERTs; the commit
   makes the record survive a kill and releases the write lock before beets runs, as `fetch` does around the
   verifier);
3. only then `write_minimal(path, changes)`;
4. runs `beet import -q -s -m -W --set dj_album=1 …`.

So every write has a committed record before it, and a kill between 2 and 3 leaves a record of a write that never
happened (harmless: its reverse writes the values the file already has). `FiledItem` also carries `old`. Without
`album=` nothing is written, no callback runs and no `--set` is passed. `sourcing/fetch.py` builds the identity from
`store.request(row["request_id"])`. S2-06b's test: a kill (exception) raised inside the import leaves the `tagged`
event in the store when it is reopened.

**As built (S2-06b).** `sourcing/filer.py`: `AlbumIdentity`, `album_changes`, `BeetsFiler.file(…, album=, on_tagged=)`
(`FiledItem.old`); `sourcing/fetch.py`: `album_identity(store, row)` (kind `album` only; `tracktotal` the highest
`track_no`) and `tagged(old)`, which logs and commits; `scripts/tag_cleanup.py`: `restore_fields`;
`deploy/beets.yaml`: the `dj_album:1:` key before `default:` and `singleton:`. From the review: `requests.tracktotal`;
an album-artist key mediafile does not read (FLAC/ogg) or an ID3 alias that says otherwise counts as a difference;
`album=` without `on_tagged` is refused before anything is written. The kill test checks that the event is
committed when beets starts and survives a rollback (`tests/test_fetch_filing.py`).

## When

- Only on our fresh download in `<downloads>/.staging/<id>-<ts>/`, after verify passed and the file moved there, and
  before `beet import -q -s -m -W --set dj_album=1` moves it into the library. `BeetsFiler.file` already refuses any
  folder whose resolved parent is not `.staging`, so the writer inherits that guard; the writer itself never takes a
  path from the caller other than the one audio file it found in that folder.
- Never on a library file, never on `/srv/incoming/library-import`, never on a file Navidrome has seen: the tags are
  final before the file's first scan, so no Navidrome id changes (the "retag + move between two scans" trap cannot
  arise at filing).
- Only the worker files (it holds `worker.lock`, the one beets writer, D18). `-W` keeps the import from writing; the
  import leaves the file byte-identical (measured below).
- **A confirmed MusicBrainz match (D22)** then `beet write`s the file as today. beets' singleton match sets artist,
  title and recording fields and leaves album and track alone (`beets/autotag/__init__.py::apply_item_metadata`,
  1.6.0), and `beet write` writes every field from `library.db`, which beets read from our tags at import. Measured
  on the scratch import of ext-2-1 (year cleared): after `beet write path:<file>`, `ALBUM`, the album-artist keys,
  `TRACKNUMBER`, `TRACKTOTAL`, `MUSICBRAINZ_ALBUMID` were unchanged, the cleared year stayed absent, and
  `COMPILATION=0` was added (D22's full write, as for every matched download today). S2-06b keeps D22 as it is; its
  test asserts the album fields after a `_write` equal the identity (with the `fake_beet` helper, which does not run
  real beets, the assertion is that `_write` is still the only post-import writer).
- A row that fails before filing (verify, transfer) writes nothing. If `beet import` fails after the write, the
  tagged file stays in `.staging` (not library material) and its event is already committed.
- **Copies.** With `duplicate_action: keep`, a second copy of an album track (a copy upgrade, or a track filed twice)
  lands beside the first as `01 - Title.1.flac` and Navidrome lists it twice in the album. Accepted: that is today's
  behaviour for singles too, and the N1 duplicate cleanup (`scripts/duplicate_cleanup.py`) is what removes copies.

## Reverse

- **The record.** One `tagged` event per write, logged and committed before the write (`## Writer`), message exactly
  the JSON object of old values with sorted keys. Example for a fresh file with no album tags and no date:
  `{"album": null, "albumartist": null, "track": null, "tracktotal": null}` (an absent id with no release to write
  does not differ, so it is not recorded); a file that said
  `COMPILATION=1` adds `"comp": true`; a written or cleared `year` adds `"year"`, `"month"`, `"day"`. Today's
  `filled artist, title from the wanted row` event stays as it is (its message never starts with `{`).
- **Which event goes with which file.** A row can be tagged more than once (planned folder, switched folder,
  per-track fallback, a failed import before a re-approval). The filed file's record is the row's **last `tagged`
  event whose message starts with `{` before its `filed` event**; the path is the `filed` event's (and the row's
  library path).
- **Preconditions** (CLAUDE.md "Live system", Michael's): restic status 0 and under 26 h old; not 03:15–04:30 and the
  backup not active; `scripts/snapshot-crates-db.sh --suffix pre-untag-<ext-id>` reports "integrity ok" twice; the
  live-writer lock `/srv/docker/crates/live.lock` held for steps 1–2.
- **What the reverse writes**, worker stopped (`docker compose stop worker` from `/srv/docker`, so beets has no other
  writer; `scripts/live-run.sh` runs the one-off in the deployed image):
  1. Tags, in **one** `MediaFile` save: for each field with a value, set it, in the order `year`, `month`, `day` for
     the date (setting `month` or `day` on a file with no year deletes the date: mediafile's date tuple); for each
     field whose old value is `null`, delete it (`delattr`). Neither `write_minimal(path, old)` (it leaves `ALBUM=`,
     `TRACKNUMBER=0`, `TRACKTOTAL=0`, `COMPILATION=0` for a `null`, measured) nor one `write_minimal` per field (the
     sorted order `day`, `month`, `year` loses the month and day, review finding 2) will do. S2-06b adds this as
     `scripts.tag_cleanup.restore_fields(path, old)` next to `remove_ids` (which deletes only id fields, on purpose),
     tested: an absent field comes back absent, `DATE=1972-05-01` comes back as `1972-05-01`, a valued field comes
     back with its value. Measured with that order: the deletions gave back exactly the pre-write `TITLE`/`ARTIST`;
     `DATE=1972-05-01` with both MusicBrainz ids came back whole after a forward clear. Not byte-identical: a
     restored year comes back as `DATE` and `YEAR` even if the file had only `DATE`. **Not restored** (S2-06b review, measured): a value mediafile cannot read is recorded as `null` and so deleted
     by the reverse (`TRACKNUMBER=A1`; `DATE=05/01/1972` comes back as `0005-01-1972`; a second
     `MUSICBRAINZ_ALBUMID` value is lost); a FLAC/ogg album-artist key mediafile did not read comes back with the
     value of the one it read; an m4a with neither track nor total keeps an empty `trkn (0, 0)` atom (reads as
     absent). Also not restored: on MP3, the
     ID3 album-artist aliases `write_minimal` deleted (not recorded); after a D22 match, everything `beet write`
     wrote (as for any matched download today).
  2. beets' index: `beet -c <yaml> modify -W -M -y path:<abs> dj_album!` (drops the flag; `-W` no file write, `-M`
     no move: measured, the file's hash unchanged) and `beet -c <yaml> update -M path:<abs>` (re-reads the tags).
  3. Start the worker; wait for Navidrome's scan (file watcher, seconds). The song keeps its id (a retag in place).
  4. Optional, a separate pass after that scan: `beet -c <yaml> move path:<abs>` puts it back at
     `$artist/Singles/$title` (measured with `move -p`: `Al Green/Singles/I'm Still in Love With You.flac`); scan
     again. Never steps 1 and 4 between two scans: a retag *and* a move gives a new Navidrome id and the song drops
     out of every playlist (`docs/hard-won-facts.md` "Navidrome 0.64").
- **Undoing the path rule** (a rollback deploy, or removing the `dj_album:1` line): nothing moves by itself; files
  already filed stay in their album folders until a `beet move` of them.

## beets measurement

2026-10-23, this box, `/usr/bin/beet` 1.6.0 (Python 3.12.3, no plugins), mediafile 0.12.0, mutagen 1.46.0. All in
scratch `$S=/tmp/harness/dj-crate-streaming/dj-crate-streaming-2026-10-22-build/measure-s2-06a`; nothing under
`/srv`, no network: `$S/beets/config.yaml` (`BEETSDIR`) sets `musicbrainz: host: 127.0.0.1:9`, a closed local
port, so beets' lookup fails at once and the quiet run imports as-is (beets 1.6 reads `musicbrainz:` before `-c`).

`$S/scratch.yaml` is `deploy/beets.yaml`'s `import:` block with `directory: $S/lib`, `library: $S/library.db`,
`statefile`/`log` in `$S`, and these `paths:` (the album key first):

```yaml
paths:
  dj_album:1: $albumartist/%if{$year,$album ($year),$album}/$track - $title
  default: $albumartist/%if{$album,%if{$year,$album ($year),$album},Singles}/$track - $title
  comp: Compilations/%if{$year,$album ($year),$album}/$track - $title
  singleton: $artist/Singles/$title
```

Files: `tests.helpers.make_flac` in `$S/dl/.staging/ext-1-1/x.flac` (and `ext-2-1`, `ext-3-1`); artist and title
by `write_minimal`, then the album fields by `write_minimal` as `## Fields` says (`album` "I'm Still in Love With
You", `albumartist` "Al Green", `tracktotal` 9, `mb_albumid`, `comp` False; ext-1-1 `track` 1 `year` 1972, ext-2-1
`track` 9 and no year; ext-3-1 no album fields, a plain row).

```sh
BEETSDIR=$S/beets beet -c $S/scratch.yaml import -q -s -m -W --set dj_album=1 -l $S/ext-1-1.log $S/dl/.staging/ext-1-1
BEETSDIR=$S/beets beet -c $S/scratch.yaml import -q -s -m -W --set dj_album=1 -l $S/ext-2-1.log $S/dl/.staging/ext-2-1
BEETSDIR=$S/beets beet -c $S/scratch.yaml import -q -s -m -W -l $S/ext-3-1.log $S/dl/.staging/ext-3-1
BEETSDIR=$S/beets beet -c $S/scratch.yaml ls -f '$path $dj_album' dj_album:1
```

Result: **the path key takes for `-s` imports.** Each import exits 0 in 0.2 s ("MusicBrainz not reachable …
Importing as-is."; the log reads `asis <path>`), and:

- `lib/Al Green/I'm Still in Love With You (1972)/01 - I'm Still in Love With You.flac` (ext-1-1)
- `lib/Al Green/I'm Still in Love With You/09 - One of These Good Old Days.flac` (ext-2-1: no year, `%if` drops
  the parentheses; hence `## Fields` clears a year the request lacks, so the album's files share one folder)
- `lib/Al Green/Singles/Plain Song.flac` (ext-3-1, no `--set`: the `singleton:` key as today)
- `beet ls -f '$path $dj_album' dj_album:1` lists exactly the first two, each with `1`; the plain file shows
  `$dj_album` unset.
- The album files' SHA-256 is the same before and after the import (`41d701ec…`, `68e61823…`): `-W` wrote nothing.

How beets does it (1.6.0 source): `--set` fills `import.set_fields`; for a singleton `SingletonImportTask.set_fields`
stores the field on the item in `apply_choice`, after `task.add` and before `manipulate_files` moves the file, and
path formats are matched in yaml order, so `dj_album:1:` must come before `singleton:` (S2-06b's test asserts the
order). The flag lives in beets' `library.db` (`item_attributes`), not in the file: a later `beet move` keeps the
album path; a rebuilt `library.db` would not have it.

## Out

- **SoulSync's "an album folder that already holds files keeps their identity"** (reuse an existing library album's
  tags and folder for a new track): not adopted (`docs/research/2026-10-22-soulsync/`, context only); Michael asks
  if he wants it. An album track already in the library (e.g. "Simply Beautiful") is not retagged or moved, so it
  shows in Navidrome's album only if its own tags already match.
- Disc numbers (the embed has none; `track` runs on across discs), `mb_releasegroupid`, `albumtype`, cover art.
- **A grouping gap left open:** Navidrome's PID reads `releasedate` from `RELEASEDATE`/`ORIGINALDATE` (TDRL/TDOR),
  which this plan does not touch. Without a release id, two files whose uploaders set different release dates would
  still be two albums. Rare in Soulseek rips; `## Live steps` step 3 shows it if it happens, and the fix is a later,
  reviewed addition to `## Fields`.
- Retagging library files to join an album (only the reverse writes a library file).
- Plain rows and `track`/`playlist` requests: `fill_missing_tags` and `Singles` as today.

## Live steps (Michael's, after a deploy; for S4-01's checklist)

None runs in this run. After S2-06b is merged and deployed (worker image with the new `deploy/beets.yaml`):
1. Dry: `scripts/live-run.sh grep -n 'dj_album:1:' deploy/beets.yaml` shows the key in the deployed image (the
   Dockerfile copies `deploy/beets.yaml`). Undo: none needed.
2. One album request, one row (approve one row of the Al Green request). Check: `/api/events` shows `tagged {…}`
   then `filed beets as-is: Al Green/I'm Still in Love With You/01 - …`; Navidrome shows the album "I'm Still in
   Love With You" by Al Green with that track. Undo: `## Reverse` (preconditions, steps 1–3) for that file.
3. The rest of the album. Check: one folder; in Navidrome one album of that name (`getAlbumList2` or the web UI
   search shows one, not two) holding 8–9 tracks; `sqlite3 -readonly` on a snapshot of `navidrome.db`:
   `SELECT count(DISTINCT album_id) FROM media_file WHERE album = 'I''m Still in Love With You'` is 1. Undo:
   `## Reverse` per file.

## Review

Opus review subagent, 2026-10-23, of this plan with `scripts/tag_cleanup.py` (`write_minimal`, `remove_ids`),
`sourcing/filer.py`, `deploy/beets.yaml` and `sourcing/fetch.py`'s filing path. 1 Critical, 4 Important, 8 Minor;
all addressed in the text above (two re-measured first).

- **C1 the record was not durable.** `store.log` only INSERTs; logged in `on_tagged` *after* the write, the event
  stayed uncommitted through a `beet import` of up to 600 s (a kill lost it) and held the write lock. Fixed: old
  values read, event logged **and committed**, then the write (`## Writer` steps 1–4, with a kill test).
- **I2 the reverse lost month and day** (one `write_minimal` per sorted field: `day`, `month`, `year`). Fixed: one
  save, `year` before `month` and `day`; re-measured, `1972-05-01` comes back whole.
- **I3 "beet write writes our fields back unchanged" was overstated.** The reviewer measured `MediaFile.update` with
  zero values; a real `beet write` on the scratch import (re-measured) kept every album field and the cleared year,
  and added `COMPILATION=0`. The claim now says exactly that; S2-06b keeps D22 unchanged.
- **I4 Navidrome grouping.** `albumartistid` follows `MUSICBRAINZ_ALBUMARTISTID`, `releasedate` is not `DATE`.
  Fixed: `mb_albumartistid` cleared with a missing `mb_albumid`; `RELEASEDATE`/`ORIGINALDATE` named as a gap under
  `## Out`; live step 3 counts distinct album ids.
- **I5 which `tagged` event belongs to the filed file.** Fixed: the last `{`-event before the row's `filed` event.
- **Minor, fixed:** the example JSON no longer shows `"comp": null` (comp's old value is always `true`);
  `tracktotal` is the highest `track_no` over all the request's rows (a count could fall below a track number);
  a written year clears `month`/`day` (no invented `1971-05-01`); unrestored MP3 aliases and D22's write named;
  m4a/ogg tests asked of S2-06b; S2-06b handles `kind='album'` only; duplicate copies named and accepted; the
  reverse's live preconditions (backup, window, snapshot, lock) added.
- **Minor, decided:** clearing an unknown year keeps one folder at the cost of a correct uploader year; recorded as
  D51 *default* (the alternative: the first filed file's year becomes `requests.year`).
