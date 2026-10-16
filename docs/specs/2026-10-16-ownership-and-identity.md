# Ownership of facts, and songs vs versions

**Status:** design, 2026-10-16. Written after Michael's review answers. M6–M8 follow it. The decisions are D18–D23 in
`2026-10-13-next-session-design.md` §0.

**Why now:** most bugs so far came from two stores disagreeing about one fact:
- titles right in beets but wrong on the phone;
- song ids changing after a retag plus a move;
- a 12" rejected because a Spotify row was shorter.

M6 adds a second writer (the worker), and M7/M8 add replacement and repointing. So who owns what has to be settled before
any of them is built.

---

## Part 1 · Who owns each fact

**The rule:** every fact has exactly one owner. Every other copy is either *derived* (rebuildable from the owner) or a
*mirror* (written from the owner, never read back as truth). The one exception is recovery: a mirror may restore the
owner after a loss, and only by an explicit command.

| # | Fact | Owner | Derived / mirrors | Why this owner |
|---|------|-------|-------------------|----------------|
| 1 | What a track is called (artist, title, album, year, track no., genre) | **The file's tags** (D5) | Navidrome's index; beets DB; Subsonic "paths" | Tags travel with the file into Serato, Mixxx, a USB stick or another server. Every tool reads them, and they survive the loss of any database. Navidrome is read-only on files by design. |
| 2 | Which recording a file is (MusicBrainz recording id, ISRC, AcoustID id) and its version label | **The file's tags** | identity index (Part 2) | Same reason. Navidrome builds its song id from `musicbrainz_trackid` when present, so these tags also make song ids **survive retags and moves**: the root of the M2 "new id" problem. |
| 3 | Where a file lives and its file name | **beets path rules** (`deploy/beets.yaml`), computed from #1 | the path itself | The convention is one definition. A path is never read as a fact (Navidrome's Subsonic paths are virtual anyway). |
| 4 | Which songs exist and their ids | **Navidrome** (its scan of `/srv/music`) | crates.db holds Navidrome ids as references | It is the server every client talks to. The ids are only stable while #2 is filled in, so a playlist check runs after every scan (planned; today: manual `export_playlists check`, and identity apply runs it). |
| 5 | Playlists: membership and order, *including which version sits at each position* | **Navidrome** (D11, now edited in any client) | `.m3u8` exports (backup, rewritten after each change (planned; today: manual `export_playlists export`)); Spotify is an *import source* only, never synced | Michael edits playlists in Amperfy or the web UI, so the server they write to has to be the owner. |
| 6 | Playlist attributes: is it a crate; which tier its tracks should be sourced at | **The playlist itself**, as tags in Navidrome's playlist comment: `#crate`, `#tier:medium` | crates.db (`crates` table) becomes a cache rebuilt by `reconcile` | It is a property of the playlist, so it lives with the playlist. It is visible in every client, survives losing crates.db, and is in Navidrome's backup. **Change from today:** today crates.db owns the flag and mirrors `#crate` into the comment. |
| 7 | The tier a track *should* reach | **Derived:** the highest tier among the playlists that contain it (`crate` if any is a crate); for a track not yet owned, the tier of the playlist that wants it | stored on wanted rows as a cache | A track has no tier of its own. It needs what its most demanding playlist needs. Flagging or un-flagging a playlist then re-derives everything, with nothing to keep in sync by hand. |
| 8 | What each tier accepts (floors, speed weights) and the version preferences | **Repo config** (was `sourcing/policy.py`; `deploy/policy.toml` since M7, read with stdlib `tomllib`) | — | These are Michael's policy and change without code (D17, D16 "not set in stone"). |
| 9 | Quality facts about a file (codec, bitrate, spectral cutoff, verdict) | **Measured** (`verify`) | crates.db `verifications` (a cache) | They can always be re-measured from the file. A cache can't drift into "truth" because the file wins. |
| 10 | The sourcing queue, candidates, **approvals**, downloads and the log | **crates.db** | — (in the nightly restic backup) | This is operational state with nowhere else to live. It is the one store whose loss loses information, which is why it is backed up. |
| 11 | Stream quality (format, bitrate per stream) | **The client** (Amperfy's Wi-Fi/cellular settings; Navidrome's player profile for web clients) (D19) | — | Decoupled from sourcing tiers. The tier decides what file we *keep*; the client decides what it *streams* from it. |
| 12 | Originals | **`/srv/incoming/library-import/`**, read-only, Michael's | `/srv/music` holds working copies | The safety net under everything else. |
| 13 | Secrets | **`/srv/docker/.env`** | container environments | Unchanged. |

### Who may write what

- **File tags.** Two writers only:
  - `scripts/tag_cleanup.write_minimal`: field by field, for corrections on existing files.
  - `beet import` in the worker: fresh downloads only (M6).
  - Nothing else writes tags. `beet write`, `beet modify` and `mbsync` stay forbidden on the existing library.
- **File moves.** Only beets. On import (M6), and `beet move` after a reviewed tag change (as in M2).
- **Navidrome playlists.**
  - Michael, in any client.
  - Our code, only through logged, tested commands: import, repoint, `crates.cli rename|merge|delete`, crate toggle.
- **crates.db.** The crates service and the worker. Both use SQLite, so one writer at a time, with short transactions.

### Where beets fits

beets is a **tool, not an owner**. It is used for one job it does well: filing new files by the path convention (and
looking up their MusicBrainz match on import). It does not propose ids for the existing library (M7, below).
Its `library.db` is a **disposable index**:
- it can be rebuilt from the files;
- before beets is used on existing files, `beet update -M` refreshes it from the tags (file → DB, no moves);
- nothing ever reads a fact from it in preference to the file.

- **M6: the filer for new files.**
  - The worker runs `beet import -q -s` (singleton) on each verified download, from its own fresh folder.
  - **Tag writing on fresh downloads:**
    - With a confident MusicBrainz match, beets writes its full tag set, including the MusicBrainz recording id.
      An uploader's tags are no better than beets', and the id makes the song id stable from day one.
    - Without a match, the file goes in as-is.
    - Either way, the result is compared before and after on a temp library in the tests (the M2 trap).
  - The worker becomes the **only** process that runs beets, and the host stops running it. This avoids two writers on
    `library.db`.
  - The beets version is pinned to 1.6.0 to match the existing DB. An upgrade to beets 2.x is a separate, later decision.
- **M7: the identity lookup.**
  - beets does **not** propose ids for the existing library. Measured: it matched a 412 s "(Original 12'' Version)" to
    a 403 s "(Get Down in the 90's-mix)" recording at 96.8% similarity. A 12" taken for a 90's mix is the mistake
    M8 must never inherit.
  - Our own code proposes: MusicBrainz (ISRC, recording lookups, search) and AcoustID when a key exists
    (`scripts/identity_backfill.py propose`). A recording fits a file only when the artist, the base title, the
    version label and the length (±4 s) all agree.
  - The proposal lands in a review report, the way the M2 tag cleanup did. Michael reads it.
    `apply` then writes only the accepted id fields (recording, work, AcoustID) with `write_minimal`, where the
    file's own field is empty. beets never writes to existing files, and that stands.
  - This fills fact #2 for the library: today 98 of 831 files have a recording id, 9 a work id, 13 an AcoustID id,
    487 an ISRC.
  - It makes Navidrome ids stable and gives Part 2 exact answers where guesses were needed before.

---

## Part 2 · Songs, versions and copies

### The model: three levels

```
Song      "Double Exposure — My Love Is Free"          what Michael thinks of; what a playlist row *means*
 ├─ Version  radio / album (459 s)                     a distinct recording: edit, 12"/extended, club, dub,
 ├─ Version  12" M&M mix (580 s)                       instrumental, a cappella, live, remix (by X), re-edit (by X)
 │    ├─ Copy  FLAC from the 1976 LP rip               same recording: different master, release or encode
 │    └─ Copy  320 mp3 from a compilation              ← dedupe (M3) and upgrades (D10) work at this level
 └─ Version  live 1979
```

- **Song** = lead artist + base title (the title without version markers). This is the MusicBrainz *work* combined with
  the performing artist. A cover by another artist is a different song, which is how a DJ thinks.
- **Version** = a MusicBrainz *recording*. Its key is the recording id when known. Otherwise it is the song + version
  label + duration (±4 s), confirmed by fingerprint.
- **Copy** = a file. Copies of one version are interchangeable apart from quality.
- **Remasters are copies, not versions.** That is why the tag cleanup moved "Remastered 2011" into the comment and kept
  " - Live" in the title (D14). The rule was already there; this names it.

### Rulings that sharpen the model

- **A work id decides only the song.** Two files with one work id are the same *song*. They are the same *version*
  only when the base title and the version label agree too. A missed match leaves a duplicate. A false match deletes
  a version.
- **Clean, explicit, mono and stereo are versions,** not copy words. So are take numbers ("Alternate Take 21" is not
  "Take 22") and years or places in a live or mix credit ("Live 1977" is not "Live 1979"). Only a remaster phrase
  ("Remastered 1999", "2011 Remaster"), "Album Version" and "feat. X" are copy markers, because they do not change
  the recording.
- **A copy upgrade replaces the old copy only when verify reports `replaceable`.** That means the new file's
  fingerprint was compared with the old one over the full length, the bit-error rate is 0.20 or less, the two
  durations agree, the files differ, and the verdict is `ok`. A missing reference, or a prefix that matches only
  because it is short, is never replaceable. M8 reads this one flag.
- **A stand-in version needs every version word accepted.** When the policy lets a 12" stand in for a radio row, a
  "12" Dub" does not qualify: dub is not on the accept list, so it is a review row. This holds in the matcher and in
  the scorer.

### The library invariants

1. **At most one copy per version** (D2, D10). A better copy *replaces* the old one, and the old one goes to trash.
2. **Several versions of a song may coexist.** A radio edit and a 12" are both legitimate in a DJ library.
   A new version is an *addition*, never a replacement.
3. Replacement therefore needs a **same-version** check: same recording id, or the same song + label + duration and
   a fingerprint match. Verify's reference check (M5) is exactly this, so a version swap is never mistaken for an upgrade.

### Who owns what here

| Fact or choice | Owner | Why |
|---|---|---|
| Which version a file *is* (recording id, label) | **The file's tags**: recording id in `MUSICBRAINZ_TRACKID`; the label in Vorbis `VERSION` / ID3 `TIT3` (subtitle), *and* kept in the display title (" - 12\" Mix", like " - Live") | It travels with the file. The title copy keeps it visible in Amperfy and Serato, which don't show the version field. |
| Which versions belong to one song | **Derived** by one `identity` module: work id if present, else normalised lead artist + base title | It's a function of the tags. Storing it separately would drift, and MusicBrainz work ids make it exact where they exist. |
| Which version sits in *this* playlist position | **The playlist** (Navidrome) | Michael's explicit choice. It already exists: a playlist entry points at one file = one version. secondset #32 *is* the record of "the 12" here". |
| Which version to prefer when *the system* picks: matching an import row, choosing a download, proposing a repoint | **Policy config, Michael's**: `deploy/policy.toml`, `versions:` per tier, e.g. `crate: prefer [extended, 12", club, original mix]; listening: as requested` | "Not set in stone", so it's a setting, not code. Only defaults live here, and the playlist overrides them. |
| Whether a new version takes over a playlist slot held by another version | **Michael** (a proposal in the approval queue), unless the policy says `repoint: auto` for that tier | Repointing changes what he hears. D16 says "fine if the 12" replaces the regular copy for streaming", but that stays a *proposal* until he has seen it work. Default: propose. |

### Where each part of the system uses it

- **The import matcher** asks, in order:
  1. same recording (ISRC or recording id)?
  2. same version (song + label + length ±4 s)?
  3. another version of the same song that the policy accepts (e.g. a 12" for a radio row at crate)?
  Step 3 matches are logged as "matched with another version", so an alternative-version match is never silent.
- **The scorer** gets candidate labels from file names (12", extended, dub…). Version preference becomes a scoring term
  from the policy, not a hard rule. The length check compares against the *wanted version's* expected length.
- **verify** gets the intended version:
  - for a **copy upgrade**, the fingerprint must match the old file;
  - for a **new version**, the fingerprint is not expected to match. The AcoustID lookup (when a key exists) confirms the
    recording instead.
- **Dedupe and GC** act only within a version.
- **Today's five ad-hoc normalisers** fold into `identity`: `scorer.norm`, `import_playlist.norm`/`_core`,
  `store._loose`, `dedupe._norm`, `tag_rules._same`. They disagree today. For example, `scorer._NOISE` throws "original
  mix" away as noise, but under D16 it is a version label.

---

## Part 3 · Sourcing flows this supports

- **Imports (D15):**
  - new rows default to `medium`;
  - the importing playlist gets `#tier:medium` (fact #6), and a playlist's tier can later be raised in one place;
  - flagging it `#crate` raises its tracks' derived tier (fact #7) and queues upgrades.
- **Play-now (D20):**
  - Michael presses play on a track that's queued but not in the library.
  - Pressing play is the approval for **one fast copy**: tier `low` scoring, fastest arrival.
  - It is filed as a *provisional copy*, plays when it lands (realistically 20–60 s: a Soulseek search takes 5–15 s,
    then the transfer), and an **upgrade row** at the track's derived tier is queued automatically.
  - The upgrade is a copy replacement (same version), so invariant 1 applies: the provisional file goes to trash once
    the better one is verified.
  - The upgrade itself waits for approval, which is manual for now.
- **Approval (D18 confirmed, D23):**
  - Every download carries an approval record: `approved_by` (`michael` | `policy:<name>` | `agent:<id>`), the candidate
    chosen, the time, and the tier.
  - Today only `michael` exists, through the web client's Approve button and play-now.
  - Automated or agent-supervised approval later is a new `approved_by` value plus a policy, not a redesign.
- **Streaming (D19):**
  - "Tier" now means only *what file we keep*. Stream quality belongs to the client: Amperfy's own Wi-Fi/cellular
    settings, and Navidrome's player profile for the web client.
  - The web client's quality menu gains a default **"server"**, which sends no format so Navidrome's player setting
    decides. The opus 64/96/160 presets stay as overrides, and later get an AAC/mp3 fallback for Apple devices.

## What changes in the plan

| Milestone | Builds | Depends on |
|---|---|---|
| **M6: worker and filing** | `/srv/incoming/soulseek/` for slskd; the worker container (D18); approval records and the Approve button; `beet import` filing of new downloads (the only beets writer); names reconcile back onto rows; reference fingerprint for copy upgrades; AcoustID when the key exists; the web client "server" stream default (D19) | — |
| **M7: identity** | `sourcing/identity.py` (song/version/copy, version labels); the five normalisers folded in; `deploy/policy.toml` (tiers + `versions:`); the matcher, scorer and verify use the intended version; the **identity backfill proposal** (MusicBrainz and AcoustID lookups by our own code, not beets → reviewed `write_minimal` of the id fields only) | M6 (worker has the tools) |
| **M8: lifecycle** | Playlist attributes in the comment (`#crate`, `#tier:`) with crates.db as cache; derived track tiers; upgrade = copy replacement + playlist repoint + trash (Stretch §4.3 GC); play-now (D20); version-swap *proposals* | M7 (replacement needs the same-version check) |

## Open choices for Michael (each has a default; defaults are in place)

1. **D21:** playlist attributes live in the playlist comment (`#crate`, `#tier:medium`), and crates.db is a cache.
   *Default: yes.*
2. **D22:** beets writes a full tag set on *fresh downloads* when it has a confident MusicBrainz match.
   *Default: yes; never on existing files.*
3. **D22:** the version label stays in the display title *and* goes in the version field.
   *Default: yes (consistent with D14).*
4. **D23:** a newly arrived preferred version (e.g. a 12") is *proposed* for playlist slots held by another version,
   not swapped automatically. *Default: propose.*
5. **D20:** pressing play on a not-yet-owned track approves one fast provisional download.
   *Default: yes; the upgrade still waits for approval.*
