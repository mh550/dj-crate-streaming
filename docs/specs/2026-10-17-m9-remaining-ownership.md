# M9: the remaining ownership and identity considerations

**Status:** draft for Michael's review, written 2026-10-16 on `overnight2/2026-10-15` (M8 Parts A–C built, Part D
play-now in progress). Nothing here is built. It follows the binding design in
[`2026-10-16-ownership-and-identity.md`](2026-10-16-ownership-and-identity.md) (D18–D23) and changes none of it.

**What M9 is:** the items M6–M8 deliberately left out. They come from the "Open items" of the M7 and M8 plans, the M7
and M8 ledgers, `docs/architecture.md` §10–§11 and `TODO-MICHAEL.md`. Each claim marked *(checked)* was read in the
code at `40b0d47`.

**One rule carried through every item:** a fact has one owner. M9 adds no new owner. It adds commands that apply an
owner's intent once (a placement, a reviewed tag write, a reviewed trash) and checks that catch a mirror drifting.

| # | Item | Size | Michael decides |
|---|---|---|---|
| 1 | A downloaded track goes into its playlist at its Spotify position | M | yes (Q1, Q2) |
| 2 | Proposals for playlists tiered later, and for filings made blind | S | yes (Q3) |
| 3 | Garbage-collect the 102 "copies of one version" groups | L | yes (Q4, Q5) |
| 4 | Write the version label into `VERSION`/`TIT3` | M | yes (Q6) |
| 5 | Pickers: identity `search`/`ambiguous`/`none`, and the 11 import `review` rows | M + M | yes (Q7–Q9) |
| 6 | Enforce "one beets writer" and "no download without approval" in code | S | defaults (Q10) |
| 7 | Playlist health check after scans; export history | S | default (Q11) |
| 8 | Small items (AcoustID cache, "99 Luftballons", crates.db snapshot, pinning, …) | S each | some (Q12–Q14) |

---

## 1. Place a downloaded track at its Spotify position

**Problem.** A filed external row is in the library but not in the playlist that wanted it. `fetch.finish` sets the
row `ok` and stops *(checked, `sourcing/fetch.py:216-222`)*; the column comment "where a later fetch inserts the
track" on `external_wanted.position` is unimplemented. A re-run of `import-playlist` appends it **at the end**
(`import_playlist.py`, `new_ids` appended). Live example: "Tea tent" is Spotify-ordered (99 + 27 rows, starting with
Donald Byrd "The Weasil"); its missing tracks are wanted rows at medium. Each one that arrives would land after the
last track, so a set built in Spotify order loses its order. Play-now (D20) has the same gap: the track plays but is
not in its playlist.

A second, smaller problem *(checked, `crates/store.py:502-523`)*: wanted rows are one per lead artist + title across
**all** playlists, and `add_external_wanted` re-records `playlist_id`/`position` on the existing row. A track wanted
by two playlists remembers only the last import's slot.

**Owner.** Membership and order stay **Navidrome's** (fact 5). Spotify is an import source, never synced. *Where the
import wanted a track* is part of the request, so it is operational state in **crates.db** (fact 10) until the track
is placed. After placement Navidrome owns it, and M9 never moves it again.

**Mechanism.**
- New table `import_order(playlist_id, position, song_id, wanted_id)`: every row of an import in Spotify order, with
  the Navidrome song it matched or the wanted row it queued. Written by every `import-playlist` run (dry runs too,
  as a report only). This replaces "neighbours" with the whole order, so a neighbour Michael removed is skipped and
  the next one is used.
- `wanted_id` × `playlist_id` is many-to-many through this table, which fixes the "last slot wins" problem without
  changing how rows are keyed.
- `crates/placement.py`, called by the worker after `finish` turns a row `ok` (and for play-now copies):
  for each `import_order` row naming this wanted id whose playlist still exists and is `#imported`:
  1. skip if the playlist already holds the song, or `imported_entries` says it was added once (D13: removed stays
     removed);
  2. read `checked_entries`; walk back from the row's position to the nearest earlier `import_order` song that is in
     the playlist now and insert after it; none → before the nearest later one; none → append;
  3. one `playlist_edit.rewrite(before, after)`; record the song in `imported_entries`; event `placed`.
- A refusal (`PlaylistSkew`, `PlaylistChanged`, `NotOwned`, smart playlist) leaves a `placement` row open; the worker
  retries on the next tick, at most N times, then an event says "not placed: <why>; re-run the import to append".
- Existing playlists have no `import_order` yet: a re-run of `import-playlist` records it (adds nothing new beyond
  today's behaviour).

**Safety rules.**
- Only `#imported` playlists our user owns; never one Michael made by hand or the amperfy account's.
- Insert only, never move or remove an existing entry. A track already appended at the end by an earlier re-run
  stays where it is.
- Every edit goes through `playlist_edit.rewrite` (guards for hidden rows and concurrent edits, readback).
- One placement per (wanted row, playlist), ever.

**Decides.** Q1 (insert vs append), Q2 (leave already-appended tracks). Defaults below. **Size M.**

## 2. Proposals for playlists that become tiered later, or filings made blind

**Problem.** Version-swap and unproven-copy questions are created **only at filing time**, inside `fetch.finish`
*(checked, `fetch.py:221` and `:263` via `ask`)*. Two gaps:
- A playlist flagged `#crate` (or raised to a tier whose `prefer` list favours 12"/extended) *after* the 12" was
  filed gets no question. Example: a playlist holding a radio edit while the library already has that song's 12".
- When navidrome.db could not be read at filing, `ask` logs "not asked about <rel>: navidrome.db is not available"
  and nothing asks again. The same holds for an unproven copy kept beside the old one: the row says `review` but has
  no question to answer.

The ledger records this as M9 (M8 Task 9 review: "re-scan for proposals when a playlist becomes tiered later").

**Owner.** Unchanged: the question lives in `proposals` (crates.db); the answer edits Navidrome (fact 5); which
version the system prefers is `deploy/policy.toml` (fact 8).

**Mechanism.** `proposals.sweep(store, db, playlist_ids=None)`:
- for every slot of a tiered playlist, find library songs with the same `song_key` and run the existing
  `version_swaps` logic for each (it already refuses same version, untiered, already-held, not-preferred and
  label-dropping cases);
- for every `review` row whose reason is "kept beside …" and that has no open or decided question, run
  `unproven_copy`.
- `store.add_proposal` already never asks the same question twice, and never again after a no, so a sweep is safe to
  repeat.
- Run by the worker: after a reconcile that changed a playlist's effective tier (the `tier` / `crate_on` events), for
  that playlist only; and once a day for all tiered playlists (covers blind filings).

**Safety rules.** A sweep only *asks*; it edits nothing. At most 20 open questions per playlist per sweep (oldest
slots first), so flagging a large playlist does not bury the Proposals tab. An unreadable navidrome.db skips the sweep
with an event.

**Decides.** Q3 (whether existing library versions are offered at all). **Size S.**

## 3. Garbage-collect the 102 "copies of one version" groups

**Problem.** `docs/identity-backfill-report.md` lists 102 groups, 217 files, that `identity.same_version` calls
copies of one version (D2/D10: at most one copy per version). M8's replacement handles only *downloads* that verify
against the old copy, so these stay. They are not bit-identical (M3's `dedupe_copies` already removed identical
audio by decoded MD5). Live examples:

| Group | Copies |
|---|---|
| Al Kooper – Lookin' For a Home | mp3 + flac, same album folder, 5:52 both |
| Buckshot LeFonque – I Know Why The Caged Bird Sings | 2 mp3 (title case differs) + flac in a third folder |
| Bahamadia – Rugged Ruff | m4a 3:11 in "Kollage" + flac 3:09 in "Kollage (1996)" |
| Cameo – Use It Or Lose It | flac under Cameo + flac under Compilations/Intuition |
| Bobbi Humphrey – Baby's Gone | "(Remastered 1999)" mp3 + flac (a remaster is a copy) |

**Owner.** Which version a file is: its tags (fact 2). Quality: measured (fact 9). Which copy sits in a playlist slot
does not matter within one version, so repointing to the kept copy changes nothing Michael chose. The decision to
delete is **Michael's** (a reviewed proposal), the way M2 and M3 worked.

**Mechanism.** `scripts/copy_gc.py`, run in the worker (fpcalc, the library mount, beets):
1. `propose` (read-only): groups from `same_version` over current tags (after the identity apply, so recording ids
   decide where present). Per group pick a **keeper**: lossless over lossy, then higher bitrate, then
   `dedupe_copies.keep_rank` (own album artist over Compilations, no ".1", earliest year).
2. For each other copy run `verify(keeper, reference=copy, intent="copy")`: the copy may go only if the result has
   `replaceable is True` (full-length fingerprint BER ≤ 0.20, durations within 4 s, different files, verdict ok).
   Store that verification in crates.db under a `gc-<n>` id, with size and mtime of both files.
3. Report (`docs/copy-gc-report.md`): per group the keeper, each copy to trash and why, and the groups held back
   (not replaceable, both lossless, a placeholder tag). Michael marks `skip` on any line.
4. `apply`: each accepted copy becomes a `replacements` job (`sourcing/replace.py`) with the stored verification as
   its licence. The job does what M8 does for downloads: repoint every playlist through `playlist_edit`, move the
   copy to trash only when `references()` is empty, `BeetsFiler.forget`, rescan, done. Resumable.

**Safety rules.**
- Trash only through `replace.py`'s guards (licence literally `True`, file unchanged since compared, `same_version`
  re-checked, no reference left including hidden rows). No new deleting code path.
- Every doubt keeps both: no fingerprint, a length mismatch, a recording-id disagreement, a `conflict` row (item 5).
- Two lossless copies (usually different masters) are listed, not accepted, unless Michael says otherwise (Q4).
- Trash is never emptied by code; `MOVES.txt` holds the reverse `mv`.
- `apply --limit 5` first, then the rest.

**Decides.** Q4 (two lossless masters), Q5 (keeper order). **Size L** (new propose, reuse of replace).

## 4. Write the version label into `VERSION` / `TIT3`

**Problem.** D22 says the label lives in the display title *and* in the version field. M7 only reads the field
(ruling c, default "later, its own reviewed proposal"). Today 84 of 831 titles carry a label; of 37 files with a
version field, 35 hold a year or rip-group name there, not a label. Also *(checked)*: mediafile 0.12 has **no** version
field (`MediaFile.fields()` lists none), so `write_minimal` cannot write it as it stands; `identity_backfill` reads it
with mutagen (`_version_tag`).

**Owner.** The file's tags (fact 2). The title copy stays (it is what Amperfy and Serato show).

**Mechanism.**
- Extend `tag_cleanup.write_minimal` with one key, `version`, written by mutagen: Vorbis `VERSION`, ID3 `TIT3`, MP4
  freeform `----:com.apple.iTunes:VERSION`; ID3 version kept; `remove_ids`-style revert for it.
- `identity_backfill labels propose`: for each file whose title parses to a label and whose version field is empty,
  propose the label text as written in the title (e.g. `12" Mix`, `Live 1979`). Report + JSON, same review as ids.
- `labels apply` / `revert`: the M7 apply rules (unchanged file since propose, empty field only, log first, read back,
  no other tag changed, first problem stops).

**Safety rules.**
- Never overwrite: the 35 files with a year there are listed, not written.
- Measure first on a throwaway Navidrome: that the song id is unchanged after the write (an in-place retag keeps it),
  and whether 0.64 shows `TIT3` as a subtitle beside the title (a doubled "12" Mix" on screen would argue for Vorbis
  only, or for not writing).
- Run after the id apply and after GC: every tag write changes mtime, which invalidates any pending proposal on that
  file (they check size and mtime).

**Decides.** Q6. **Size M.**

## 5. Pickers: identity classes and the parked import `review` rows

### 5a. Identity backfill: `search` (239), `ambiguous` (116), `none` with candidates (33), `conflict` (24)

**Problem.** `apply` writes `confirmed`, `isrc`, `acoustid` by default; `search` waits for Michael (ruling a), and
`ambiguous`/`none` need a `"choose": "<mbid>"` typed into the JSON. Typing MBIDs into a 4,300-line report is not
a real review. From `docs/identity-backfill-proposal.json`: 87 of the 116 ambiguous rows have no candidate on the
file's own album and 22 have several (they are mostly MusicBrainz duplicates of one recording: "In da Club" has 8 fits
at 3:13–3:15); 99 of the 239 search rows hold an ISRC that fit nothing. `conflict` rows (an existing id that does not
fit the file) matter because `same_version`, GC and M8 trust recording ids.

**Owner.** The id is the file's tag (fact 2); which candidate is right is **Michael's** call; the choice is recorded
in a choices file beside the proposal until `apply` writes it.

**Mechanism.**
- An "Identity" view in the web client, served by the crates container (which already mounts `/data/identity`):
  one row per file with its tags, length and a ▶ (Navidrome stream by path → song id), and the candidates with
  length, release, disambiguation and a MusicBrainz link.
- Buttons: **Accept** (a `search` row), **Choose** (one listed candidate: `ambiguous`, `none`, `search`), **Skip**.
  `conflict` and `error` rows show the evidence and offer only Skip (the existing rule).
- Choices go to `identity-choices.json` (crates writes only its own data dir); `apply --choices` merges them, with
  the existing check that a choice is among the row's candidates.
- Suggested pick (pre-selected, never applied without a click): the only candidate on the file's own album.
- **With an AcoustID key:** a fresh `propose` gives the fingerprint's recordings. Rows whose top result (score ≥ 0.8)
  agrees become `acoustid` (accepted by default); among MusicBrainz duplicates the fingerprint usually narrows to
  one or two. Expect most of the 239 and many of the 116 to move. Do 8a (AcoustID cache) first.

**Size M.**

### 5b. The 11 import `review` rows (several versions in the library)

**Problem.** Import found several library versions for these Spotify rows and parked them. Since `40b0d47` they are
listed in Wanted with their reason, but nothing resolves them; the candidate song ids live only in the reason text
("ambiguous (several versions): id1, id2").

**Owner.** Which version sits at this position is **the playlist's** (fact 5), i.e. Michael's pick.

**Mechanism.** In the Wanted tab, a review row lists its candidates (title, length, format, ▶). **Use this** places that
song at the row's Spotify position (item 1's placement) and closes the row `ok` ("picked by michael"); **None of
these** turns it `needs_source` for the asked version (asked length); **Drop** sets `removed`. Candidates move from
the reason text to a `candidates` JSON column (fixes a free-text parse).

**Safety rules (both pickers).** A pick writes one record; the write itself happens through the existing guarded
command (`apply`, `placement`). Every pick is an event with `decided_by=michael`. **Size M** (needs item 1).

## 6. Rules the code does not yet enforce

**Problem** *(checked)*:
- "One beets writer" (Part 1): `scripts/tag_cleanup.py` imports beets and opens `library.db` (`open_lib`, line 36,
  `retag` and `move` passes); `scripts/dedupe_copies.py` writes it in `_forget_in_beets` (`item.remove`). Both run on
  the host. Quirk 14: harmless only if the worker is stopped.
- "No download without an approval" (D23): `sourcing.cli rank --slskd … --download` enqueues the top candidate in
  slskd directly (`cli.py:327-329`): no approval, no verify, no filing, and it prints the peer's name.

**Owner.** beets' index has one writer, the worker (D18); approvals are crates.db's (fact 10).

**Mechanism.**
- `rank --download`: **retire** (delete the flag). Routing through the worker already exists: Preview + Approve.
- `tag_cleanup retag|move`: refuse unless they can take `/srv/docker/crates/worker.lock` (flock works across the
  bind mount, so the host sees the worker's lock): the worker must be stopped, and the code says so. Keep
  `write_minimal`/`remove_ids` as library functions (identity uses them).
- `dedupe_copies`: retire once item 3 lands (GC replaces it); until then the same lock guard.
- `identity_backfill apply` stays outside the lock (different files, runs beside the daemon), as today.

**Decides.** Defaults (Q10). **Size S.**

## 7. Playlist checks after scans; export

**Problem.** Spec facts 4 and 5 promise a playlist check after every scan and an export after each change.
- Export: **now covered.** The worker re-exports every `WORKER_EXPORT_S` = 300 s, rewriting only changed files
  *(checked, `sourcing/worker.py:142-155`)*.
- Check: **not covered.** `export_playlists check` is run only by identity `apply`. And auto-export changes what the
  `.m3u8` files are: they now follow Navidrome within 5 minutes, so they are a mirror, not a "before" backup.
  An M2-style loss (retag + move between scans gives a new id; the old entry is hidden) is what the check must catch.
  M8 measured 28 missing `media_file` rows, 0 playlist entries on them.

**Owner.** Navidrome owns songs and playlists (facts 4, 5); the `.m3u8` files are mirrors.

**Mechanism.**
- Worker step after each export: count `playlist_tracks` rows on a missing or unknown `media_file` (the
  `playlist_edit` skew condition), per playlist. New ones → event `playlist_health` and a banner in the web client
  ("2 entries in Tea tent point at missing files").
- `.m3u8` history: before rewriting a changed file, keep the previous one in `_playlists/.history/<date>/` (30 days).
  The export already includes hidden entries with their old paths, so the history is the restore source.
- Healing (rewriting a hidden entry to the new id) stays manual in M9; a proposal kind for it is a later item.

**Decides.** Q11. **Size S.**

## 8. Small items

| Item | Problem / mechanism | Owner / rule | Size |
|---|---|---|---|
| 8a AcoustID cache + spacing (M7 m10) | Answers are not cached and not spaced (limit 3 req/s); a re-propose re-fingerprints every file. Cache by path + size + mtime (`acoustid-cache.jsonl`), route through the process-wide limiter at 3/s. | derived cache; the file wins | S |
| 8b "99 Luftballons" | `strip_trackno` takes "99 " off "99 Luftballons" (`identity.py:266`, used by `parse_filename` and the scorer), so that Soulseek file is ranked down. Strip a bare "NN " only when the rest still fits the wanted title; else keep it. | safe today (missed candidate) | S |
| 8c Disambiguation-only labels (M7 m3) | A MusicBrainz recording whose version is only in its disambiguation (`12" version`) never fits "Good Times (12'' Version)". Parse with `version_tag=disambiguation`. Recall only. | identity | S |
| 8d crates.db snapshot | WAL mode; restic copies the files live; it holds approvals (the one store whose loss loses information). Worker writes `sqlite3 .backup` to `crates.db.snap` hourly, so no root change is needed; restic picks it up. | crates.db (fact 10) | S |
| 8e Pin images | `navidrome:latest`, `slskd:latest`, `gluetun` untagged. The code depends on 0.64.2 behaviour (relative paths, PID, hidden missing rows). Pin tags; an upgrade re-runs the measured-facts checklist on a throwaway first. | repo config | S |
| 8f ".1" names | `duplicate_action: keep` files a same-format upgrade as "… .1.flac"; after the old copy is trashed the ".1" stays. `beet move` it only when the file carries a recording id (PID keeps the song id), with a scan between. | beets path rules (fact 3) | S |
| 8g Filed path in free text | The filed path rides in `reason` and is parsed by regex (`store.py` `filed_path`). Move it to a column; keep the regex for old rows. | crates.db | S |
| 8h Failed rows duplicate on re-import | `find_external` skips failed unfiled rows, so a re-import queues a second row for the same track. Reuse the failed row (back to `needs_source`). | crates.db | S |
| 8i Identity vocabulary gaps | 35 trailing parentheticals are not read as labels ("(Suite)", "(Interlude)", "(Oh What a Night!)"). Rule on each: label, copy note or part of the name. | identity (fact 2) | S |
| 8j `repoint: auto` per tier | D23 "later": a `policy:<name>` decider answers version-swap questions for a tier. The vocabulary exists; nothing decides. | Michael (D23) | M |

Not M9: D17 floors (two numbers, Michael's), the first real download (D7), the rebuild permission, M8 Part D.

---

## Proposed task order for the M9 plan

Order follows risk and dependencies: guards first, then what Michael uses daily, then the reviewed library writes, in
the order ids → GC → labels (each tag write invalidates pending proposals on that file).

| Task | Covers | Needs first |
|---|---|---|
| 1 | Retire `rank --download`; lock guard on `tag_cleanup`/`dedupe_copies` (6) | — |
| 2 | crates.db snapshot (8d); pin images (8e) | Q12 |
| 3 | Playlist health check + `.m3u8` history (7) | — |
| 4 | `import_order` table, placement after filing and play-now (1); failed-row reuse (8h); filed path column (8g) | M8 Part D merged |
| 5 | Proposal sweep (2) | — |
| 6 | Import review picker (5b) | Task 4 |
| 7 | AcoustID cache (8a), trackno (8b), disambiguation (8c), vocabulary (8i); re-propose | AcoustID key (optional) |
| 8 | Identity picker + `apply --choices` (5a); live apply (M7 Task 13) | Task 7, rebuild |
| 9 | Copy GC propose / report / apply via `replace.py` (3) | Task 8 applied |
| 10 | `write_minimal` version key; labels propose / apply / revert (4); ".1" renames (8f) | Task 9; throwaway Navidrome check |
| 11 | `repoint: auto` (8j), only if Michael wants it | Q14 |
| 12 | Docs, whole-milestone review, live checklist | all |

## Questions for Michael (each with the default applied if unanswered)

1. **Placement:** a downloaded track goes into the playlist that wanted it, after the nearest earlier Spotify
   neighbour still in the playlist (else before the next one, else at the end)? *Default: yes, `#imported`
   playlists only.*
2. **Already-appended tracks:** tracks an earlier re-run put at the end stay where they are? *Default: yes, never
   moved.*
3. **Sweep:** when a playlist becomes a crate (or gets a tier that prefers 12"/extended), ask about versions the
   library *already* has? *Default: yes, at most 20 open questions per playlist.*
4. **GC, two lossless copies** (often different masters): trash the lesser one? *Default: no, listed for you only.*
5. **GC keeper order:** lossless > higher bitrate > own album over compilation > earliest year? *Default: yes.*
6. **Version field:** write the label only where `VERSION`/`TIT3` is empty, leave the 35 files with a year there?
   *Default: yes; and only if the throwaway check shows no doubled title on screen.*
7. **`search` class:** accept those rows one by one in the picker rather than as a class? *Default: one by one; the
   class stays out of `--classes`.*
8. **`ambiguous` rows:** pre-select the only candidate on the file's own album, applied only on your click? *Default:
   yes.*
9. **AcoustID key:** register one before Task 7 (it moves many search/ambiguous rows to an automatic class)?
   *Default: none; the pickers work without it.*
10. **Host scripts:** retire `rank --download` and (after GC) `dedupe_copies`; `tag_cleanup` only with the worker
    stopped? *Default: yes.*
11. **`.m3u8` history:** keep 30 days of previous versions under `_playlists/.history/`? *Default: yes.*
12. **Pin images:** Navidrome `0.64.2`, slskd and gluetun at their current tags? *Default: pin.*
13. **crates.db snapshot:** the worker writes `crates.db.snap` hourly (no sudo needed)? *Default: yes; the sudo
    `.backup` step in TODO-MICHAEL becomes optional.*
14. **`repoint: auto`:** let a tier swap preferred versions without asking? *Default: no, every swap stays a
    question.*
