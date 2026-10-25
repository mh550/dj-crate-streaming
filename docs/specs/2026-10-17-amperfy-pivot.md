# Pivot, 2026-10-17: one download quality, Amperfy for now

Michael's direction after reading `TODO-MICHAEL.md`. It replaces earlier decisions where it says so. When a doc and
this page disagree, this page wins.

## What changed, in one paragraph

The system downloads **one kind of file**: good enough to DJ with. Everything else about quality (how loud the
phone's data plan is allowed to be) is the streaming client's and Navidrome's job, through transcoding. Tiers
(low / medium / high / crate) stop being something Michael chooses. A "crate" is only a playlist he has chosen, in
the crates app, to keep synced. Versions are no longer swapped: the exact track a playlist names is the one
sourced. Until the system outgrows it, the client is **Amperfy** (talking to Navidrome); what Amperfy cannot do is
listed below for the later custom client.

## Decisions (new ledger entries)

| # | Decision | Replaces |
|---|---|---|
| D24 | **One download quality.** A file is acceptable when it is lossless (flac preferred, then wav / aiff / alac) or lossy at **256 kbps or more** (mp3 or m4a). ogg, opus, wma and anything lower are refused. Verification is strict for every download (a re-encoded fake is rejected). A lossy file at or above the floor is kept; "flac preferred" only steers which candidate wins when we download, it never queues an upgrade by itself. | D9 tiers as a user choice, D15 (imports default to medium), D17 (floors), the M8 ruling on listening-tier upgrades |
| D25 | **Streaming quality belongs to the client and Navidrome.** We store the one good file; Navidrome's per-player transcoding (Amperfy: its own Wi-Fi / cellular settings) turns it into whatever the connection needs. Our own stream presets stay in the code only as notes for the future client (see "For the future client"). | D19 as a feature of this app |
| D26 | **Source the exact track.** The default is the version the playlist row names (Spotify's). A 12" / extended mix is never preferred and never stands in for a radio edit. `deploy/policy.toml` has no `[versions.*]` table. The version machinery (parse, compare, propose) stays, because it still tells versions apart. | D16 (all of it: crate preference, stand-ins, import and scorer bonuses) |
| D27 | **The crates app owns the crate flag.** Michael picks, in the crates web client, which playlists to keep synced; `crates.db` holds the answer. No `#tier:` and no `#crate` is written to any playlist name or comment. The comment keeps only the import marker `#imported`. `CRATES_OWNER=app` is the default; `comment` is the retired D21 design, kept so its code still runs. | D21 (comment owns crate and tier), the M8 `attrs migrate` step |
| D28 | **Version labels follow the Soulseek habit**: the label stays in the title, in parentheses, as a trailing group: `Title (Extended Mix)`, `Title (Club Mix)`, `Title (Dub)`, `Title (Radio Edit)`, `Title (Live)`. `parse_title` already reads these and the ` - Extended Mix` and `[Dub]` spellings. The version field (`VERSION`/`TIT3`) is filled later, as its own reviewed proposal. | design default (3) |
| D29 | **beets writes full tags on a fresh download only with a confident MusicBrainz match**, and anything doubtful is raised to Michael as a review row. | design default (2) |
| D30 | **Play-now approves one download.** It is the same DJ-quality download, taken at once. With one quality there is no "provisional low copy" to upgrade later, so the old two-step disappears in practice. | D20 (kept; the provisional step is moot) |
| D31 | **Navidrome cleanup: keep the flac, repoint the playlists, trash the rest.** For each group of files that are one recording (`docs/duplicates-report.md`), the lossless copy is kept (ties: the properly filed path), every playlist is repointed to it, and the other files go to `/srv/_trash` with a reverse log. Nothing is trashed while a playlist still holds it. | D10 ("keep one best file"), made concrete; M9 item 3 |
| D32 | **Playlist clutter rules (executed 2026-10-17).** Playlists with a `/` in the name (folders from the original music tree), playlists with fewer than 5 songs, `uncat-2` and `uncategorized` were deleted: 35 playlists, 10 kept. "I'd rather remove clutter and sparse playlists than keep them; I can always reimport." Michael authorised this for the shared playlists too. Restore: `/srv/music/_playlists/*.m3u8` (exports are never deleted), `/srv/docker/navidrome/navidrome.db.pre-cleanup.snap`, list in `/srv/docker/crates/playlists-deleted-2026-10-17.txt`. | |
| D33 | **The `#imported` marker moves into crates.db.** Playlist comments are left empty by this system. | the "comment keeps only `#imported`" part of D27 |
| D34 | **Future, low priority: Spotify ↔ Navidrome playlist sync.** A playlist stays in step with its Spotify source. Michael floated a marker in the Navidrome playlist title for it; that would reverse "no hashtags in names", so ask before building. Exploration only. | |
| D35 | **Two lossless copies: the extras are trashed too** (Michael, 2026-10-19: "trash the extras … apply D31 literally"). A duplicate group with a lossless extra beside a lossless keeper (often two masters) is repointed and trashed like any other; the plan gives it `"note": "lossless pair: released by Michael 2026-10-19 (D35)"` and `report.md` lists it under "Lossless pairs, will be trashed". `plan --hold-lossless` restores the old hold (`"both lossless"`, listed only). Replaces the 2026-10-17 default that held such groups (`docs/plans/2026-10-17-n1-duplicate-cleanup.md`). | refines D31 ("ties: the properly filed path") |
| D36 *default* | **The cleanup's trash step runs only with the worker stopped**, holding `<dirname(CRATES_DB)>/worker.lock`, so beets has one writer (`plan` and `repoint` run beside the daemon). | refines D18 (one beets writer) for D31; instead of M9 §3's worker replacement jobs |
| D37 *default* | **The import flag lives in a new crates.db table**, `imported_playlists` (`docs/plans/2026-10-17-n2-imported-marker.md`), which import-playlist alone decides "ours" from, so a playlist with `#imported` in its comment but no row is foreign. | makes D33 concrete |
| D38 *default* | **A snapshot run is all or nothing**: `scripts/snapshot-crates-db.sh` replaces its `.snap` files only when both databases pass `integrity_check`, else it exits 1 and leaves the last good pair (H1-01). | H1 |
| D39 *default* | **A failed DB snapshot fails the nightly backup**: `deploy/restic-backup` still backs up, then exits 1 with no Gatus heartbeat, so a green `backup` means the `.snap` files are fresh (H2-02 review). | H2 |
| D40 *default* | **The `disk` endpoint has a 30 min heartbeat.** Gatus marks `disk` failed (and alerts at once) when `deploy/health-push.sh` finds no push in the last 30 min, so a stopped timer can't leave a stale green (`deploy/gatus/config.yaml`, H3-02). Gatus checks on a 30 min ticker that starts with Gatus, so a stopped timer is noticed 30–60 min after the last push. Until Michael enables the timer, `disk` turns red 30–60 min after Gatus starts. The alternative is no heartbeat: `disk` shows its last pushed result forever. | H3 |
| D41 *default* | **Gatus reads a copy of the deployed commit's config.** `scripts/deploy.sh gatus` copies `git show HEAD:deploy/gatus/config.yaml` to `/srv/docker/gatus/config/` (renamed into place, so Gatus reloads it) and `deploy/compose.yml` mounts that directory read-only. A config change reaches Gatus only by a deploy, like the images. Reason: a mount of the checkout (H3-02) follows `CRATES_SRC`, which `deploy.sh` sets to the run's worktree; once the worktree is removed, a restart leaves Gatus without its config (H3-02 review I1). The alternative is mounting `~/projects/dj-crate-streaming/deploy/gatus` (follows whatever that checkout has). | H3 |
| D42 | **The disk timer also reports the nightly backup, from systemd** (Michael, 2026-10-19, answering H3-02 review I3). `deploy/health-push.sh` reads `systemctl show restic-backup.service` every 10 min and pushes `backup`: success when the last run succeeded and ended under 26 h ago; failure when it failed, is 26 h old, the box has been up 26 h without a run, or systemctl fails; nothing while a run is in progress or before the first run after a recent boot. Reason: Gatus' 26 h heartbeat restarts with Gatus, so alone it alerts 26–52 h late. `deploy/restic-backup`'s own push and the 26 h heartbeat stay as the fallback. | H3 |
| D43 *default* | **A playlist deleted in Navidrome loses its crates.db rows at the next reconcile**: its `crate_tracks` rows, then (once no download is still `sourcing`/`verify` for it) its `crates` row and import rows are deleted, with one `playlist_gone` event and a JSONL reverse log, never more than 3 playlists in one run; its open wanted rows become `removed` but keep their playlist and position as history (`docs/plans/2026-10-17-n3-vanished-playlist.md`). | N3 |
| D44 *default* | **A filed track goes into its imported playlist at its Spotify position, by the worker, from state.** Each real `import-playlist` run records the playlist's order (`import_order`); once a wanted row is `ok` with its song (play-now's copy included), the worker inserts it after the nearest earlier Spotify neighbour still in the playlist, else before the nearest later one, else at the end (M9 Q1), never moving an existing entry, so a track an earlier re-run appended stays (M9 Q2); one placement per wanted row and playlist, imported playlists only, every edit through `playlist_edit.rewrite`; a failed placement retries at most every `WORKER_RECHECK_S` (an outage is not counted) and gives up after 12 with a `not_placed` event; an edit Navidrome did not confirm is looked at, never retried (`docs/plans/2026-10-17-n4-placement.md`). Existing playlists get an order only on their next re-run. | M9 §1, Q1/Q2 (answered by their defaults); N4 |
| D45 *default* | **Live one-off commands run in the deployed image, resolved from the worker container's revision label.** `scripts/live-run.sh <command…>` reads `org.opencontainers.image.revision` of `dj-worker-1` (running or stopped; the Dockerfile sets it from the 10-char `GIT_SHA` that `scripts/deploy.sh` builds with), refuses when the container is missing, the label is empty, `dev` or not a hex sha, or `dj-crates:<rev>` is not here, and otherwise runs `GIT_SHA=<rev> docker compose --project-directory /srv/docker run --rm --no-deps worker <command…>`. `scripts/live-check.sh` is the Check through it. Only the image is pinned: the worker's environment and mounts still come from `/srv/docker/compose.yml`. Reason: a bare `docker compose run` takes `GIT_SHA` from `/srv/docker/.env` or falls back to `dj-crates:dev`, not what was deployed. The alternative is passing `GIT_SHA=<sha>` by hand on every one-off. | R2 |
| D46 *default* | **Playlist health counts only our user's own, non-smart playlists.** The worker keeps the `playlist_health` rows whose playlist `getPlaylists` lists with `owner` = its Navidrome user, and `export_playlists.playlist_health` leaves out smart playlists (non-empty `rules`). Reason: the `amperfy` account's playlists are off limits and `playlist_edit` refuses another owner's and smart playlists, so a banner line for one could never be healed from here (R5-04 review I1). The export itself still writes every playlist (it is the backup). The alternative is counting every playlist in navidrome.db. | R5 |
| D47 *default* | **The identity picker: `search` rows one by one, the album-only candidate pre-selected** (M9 Q7, Q8 defaults). A `search` row is written only after an Accept tap in the Identity tab, or, as before, with `--classes search`; the class stays out of `apply`'s default. On an `ambiguous` row, or a `none` row with candidates, the only candidate whose release is the file's album is pre-selected and is never applied without a tap. Taps go to `/data/identity/identity-choices.json` (the latest per path wins) and `apply --choices` merges them; `conflict` and `error` rows offer Skip only (`docs/plans/2026-10-21-r7-identity-picker.md`). The alternative is accepting `search` as a class. | M9 §5a, Q7/Q8; R7 |
| D48 *default* | **A row filed as another song is a retryable `review`** (S1-03, ext-74). When Navidrome lists the filed file under a title that cannot be the asked song (`identity.can_be_song`), `fetch` leaves the row's names and `library_song_id` alone, does not place it, and sets `review` "filed <X> as <rel>, asked for <Y>" with a `wrong_song` event naming the path and song id. Approving the row (`RETRYABLE_REVIEW`) is a fresh download; the wrong file stays in the library as its own song. Reason: S1-01/S1-02 now refuse the file that caused ext-74, and an approval is Michael's anyway. Alternative: make the reason non-retryable, so a row needs `wanted reopen` (S1-08) before another download. |
| D49 *default* | **`wanted reopen` deletes the row's placements; the wrong song's playlist entry stays** (S1-08, ext-74). `crates.cli wanted reopen <ext-id> --apply` puts the asked names back, clears `library_song_id` and `provisional`, sets `needs_source` and deletes the row's `placements` rows (and its preview), so placement puts the right file into its imported playlists when it arrives. It edits no playlist and no file: the wrong song stays where it was placed, for Michael to remove by hand or to keep. The `reopened` event holds every old value (the reverse). The alternative is leaving placement `done`, so the right file would never be placed automatically. | — |
| D50 | **The album path** (Michael's answer, 2026-10-22, spec 2026-10-22 S2-06). A track filed for an album request goes to `$albumartist/$album ($year)/$track - $title`, still as a singleton import: the filer passes `--set dj_album=1` and `deploy/beets.yaml` has the path key `dj_album:1: $albumartist/%if{$year,$album ($year),$album}/$track - $title` before `singleton:`. Every other download stays at `$artist/Singles/$title`. The request's album identity is written on the staged download first, through `write_minimal` only (`docs/plans/2026-10-22-S2-album-tags.md`). Measured on this box's beets 1.6.0 in scratch (S2-06a): the key takes for `-s` imports (`Al Green/I'm Still in Love With You (1972)/01 - I'm Still in Love With You.flac`), `beet ls dj_album:1` lists exactly the flagged items, and the import leaves the file byte-identical. Fallback if a live import ever shows otherwise: drop the key, files stay in `Singles` with the album tags, and Navidrome groups them by tags. |
| D51 *default* | **An album request without a year clears the year on its files** (S2-06a). When `requests.year` is unknown (the Spotify album embed often has `releaseDate: null`), the album tags clear `year`, `month` and `day` on each staged file (old values in its `tagged` event), so every file of the album lands in one `$album/` folder and Navidrome sees one release date. Alternative: the first filed file's year becomes `requests.year` (keeps a correct year, but the folder depends on which peer came first). |


## Recorded settings and answers (2026-10-17)

- `dj-crates-web` in Navidrome is set to opus at 128 kbps (done by Michael).
- Amperfy offers: streaming format **mp3 (default) / Raw (original) / Server chooses codec**, a **Wi-Fi** and a
  **cellular** bitrate limit, and a cache format for transcoding. There is no per-network format, only per-network limits.
- Id backfill: Michael asked for the explanation first (`docs/how-ids-work.md`) and approved running a fresh `propose` with
  the AcoustID key (the `search` class stays out of `apply` until reviewed). The version tag (`VERSION`/`TIT3`) comes later.
- "Pin it" meant pinning Navidrome: done, `deluan/navidrome:0.64.2` (same image as `latest`).
- Build order: [`../next-todos.md`](../next-todos.md).

## Consequences in the code (what was done)

- `deploy/policy.toml`: four identical tiers (256 kbps floor, no ogg / opus, quality only, strict). The names stay only
  because the code looks them up. `DJ_POLICY_FILE` points the test suite at a frozen copy of the old file
  (`tests/fixtures/policy-legacy.toml`), because the tier mechanism is still tested.
- `crates/reconcile.py`: `owner="app"`. The toggle writes `crates.db` only; reconcile never reads comments or name
  markers; `set_tier` is retired; a rename in Navidrome refreshes the stored name. `judge` keeps a lossy file at or
  above the floor.
- `sourcing/import_playlist.py`: decides "ours" from crates.db `imported_playlists` (D33, D37; N2) and writes no comment
  under `app`, so a created playlist's comment stays empty. `crates.cli imported migrate` moves the old `#imported`
  comments into that table and strips them.
- `web/`: the tier menu is gone; the crate switch is the one control.
- Not removed: the `crates.tier` column, `crates/attrs.py`, `crates/migrate_attrs.py` (refused under `app`), the
  `--tier` option (accepted, no effect on quality), the stream presets in `sourcing/policy.py`. Removing them is a
  clean-up for when the custom client replaces the web client.

## What Amperfy cannot do (to build in the later client)

Amperfy is a Subsonic client. It shows what Navidrome has and nothing else. So these live in our own web client for now
or wait for a custom client:

1. **One search across everything**: the local library, Spotify, Soulseek and other sources at once, with the result
   marked "have it / can get it". Amperfy only searches Navidrome.
2. **Tracks you do not own, in the playlist, in place.** A Spotify playlist's missing tracks appear greyed at their
   Spotify position, with Preview / Approve / Play-now. In Amperfy they are not there at all; they live in the web
   client's Wanted tab.
3. **Play-now for a track you do not own**: tap, it downloads and starts. Amperfy has no way to ask us for it.
4. **The crate switch and crate status**: pick playlists to keep synced, see which are ready. (Web client now.)
5. **Version questions**: "a different version arrived, swap or keep?", and picking one of several library copies
   (the `review` rows). (Web client now.)
6. **Insert a downloaded track at its Spotify position** (M9). The server can do this; Amperfy cannot show progress.
7. **Per-device stream presets chosen from inside the app** and bound to the connection. Amperfy has its own bitrate
   settings; they are not ours to read.
8. **A download queue view** with progress, failures and re-check.

### For the future client: streaming preferences to carry over

The default is **server decides** (Navidrome's player profile for the client's name). Recorded preferences: opus at
128 kbps on cellular and Wi-Fi as the starting point; "raw" (the original file) on Wi-Fi when wanted; the older web
presets were low = opus 64, medium = opus 96, high = opus 160, crate = raw (`STREAM` in `sourcing/policy.py`).
