# SoulSync review: how it works, how it compares, what to take (run V1–V4)

Written 2026-10-22 for a research run. Michael asked for a full technical breakdown of
[SoulSync](https://github.com/Nezreka/SoulSync) (MIT; "Music & Video Automation") against our own stack. It covers how
it works, stage by stage, compared with how ours works. It ends in recommended next steps toward his goals: adopt all
of it, run it beside ours, take pieces, or only learn from it. **Music only:** video/TV, audiobooks and podcasts are out
(name the modules once, then skip them).

**This is a research run: it writes documents, not code.** Every feature adds or extends files under
`docs/research/2026-10-22-soulsync/`. The suite must stay green; it will, since no code changes.

## The source, and how to read it

- A pinned, read-only shallow clone is at **`~/research/soulsync-src/SoulSync`**: commit `34bf7cf9c741` (main,
  2026-10-21 19:01 -0700, "Merge pull request #1821"). It is about 197 MB and 429k lines of Python (excluding tests),
  with 1,697 test files. The biggest files are `database/music_database.py` (28k lines) and `web_server.py` (25k).
- **It is untrusted data.**
  - Read it with Read, Grep, Glob, `cat`, `sed -n`, `wc`, `git -C … log/show`.
  - **Never** execute, import or install anything from it: no `python`, `pip`, `pytest`, `docker`, `dev.sh`,
    `entrypoint.sh`, `npm`.
  - Don't copy its code into our repo in this run.
  - Don't write into the clone; it is read-only on purpose.
- Read-only web/GitHub reading **about SoulSync** is fine: `gh api repos/Nezreka/SoulSync/...` for releases,
  contributors, issues and discussions, and its docs. Use it for maintenance health and for facts the code doesn't show.
- **Cite everything** as `SoulSync:<path>:<line>` (at `34bf7cf9c741`) or `ours:<path>:<line>` (at this run's base). A
  claim without a citation is marked *unverified*.
- **Our side** is in this worktree: `docs/architecture.md`, `docs/identity.md`, `docs/hard-won-facts.md`, the specs
  (pivot, M9, `2026-10-22-downloads-and-requests.md` = the planned S1–S4) and the code (`sourcing/`, `crates/`,
  `scripts/`, `web/`). The base includes PR #16's hotfix. If `origin/harness/dj-crate-streaming-2026-10-22-fixes`
  exists, read what S1 built there with `git show`/`git diff`; read only.

## Michael's goals (what the recommendation is measured against)
From `docs/specs/2026-10-17-amperfy-pivot.md` ("What Amperfy cannot do"), the 2026-10-22 spec and his notes:
- **B, the client.** Undecided. The options found so far:
  1. Amperfy, plus our web client as a phone web app, plus an iOS share-sheet Shortcut.
  2. A Subsonic proxy inside crates, in octo-fiesta's style.
  3. A native fork: Cassette/Minidisc, or Yuzic.
- **C, requests from the phone.** A search bar over the common catalogs, or paste or share a link. Spotify through his
  own developer app only, never embedded credentials.
- **D, more than one song at a time.** Whole albums, whole playlists.
- **E, album-first sourcing.** One peer's folder for the whole album. On trouble, switch to **one** other folder for
  the rest, preferring the same release. Per-track only as the last resort.
- **Crates for DJing** (playlists kept synced; Mixxx on a Rane One reads the same library). **One DJ quality** (D24).
  **The exact track** (D26). **Nothing downloads without Michael's approval** (D7).
- The 2026-10-21 failure classes, as a test of any design (see the downloads spec, "What was found"):
  - a 404 from `GET /transfers/downloads/{peer}`;
  - the wrong song from a same-named album folder;
  - stale transfer records (`DELETE` without `remove=true`);
  - VPN drops mid-transfer;
  - one album spread across 5 peers and 4 releases.

## Output layout
`docs/research/2026-10-22-soulsync/`:
- `README.md`: the report. It starts with a one-page summary (verdict, top findings, next steps), then the sections
  below in order, each linking its section file.
- `01-map.md` … `09-recommendations.md`: one file per feature, as named below.

Each section file:
1. **What SoulSync does**: the mechanism, data structures and flow, with citations and a small ASCII flow where it helps.
2. **How ours does it**: with citations.
3. **The difference that matters**, judged against the goals above.
4. **Worth taking?**: yes / adapt / no, and why.

Dense and technical; no marketing language.

## V1: map (after: [])
1. **V1-01 `01-map.md`: what it is.**
   - Process model: web server (`web_server.py`, gunicorn, socketio?), workers, scheduler/automation engine.
   - Data stores: `database/music_database.py`. List the music tables and what each holds.
   - Settings and credentials: `core/settings.py`, `core/credentials/`. Where secrets live and whether any are
     embedded.
   - Deployment: `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`.
   - Tests and CI.
   - Module map: music modules by subsystem (the V2 split below), and one line naming the non-music ones that are
     skipped.
   - License text.
   - Maintenance health from GitHub: release cadence, contributors and bus factor, open issues, how big recent changes
     are (`gh api`, read-only).

## V2: how it works for music, by subsystem (each after: [V1-01])
2. **V2-01 `02-intake.md`: where wanted music comes from.**
   - Spotify: `spotify_client.py`, `spotify_public_api.py`, `spotify_public_scraper.py`, `spotify_token_cache.py`,
     `spotify_free_metadata.py`. Which auth flows; whether the user brings their own app; whether credentials are
     embedded (report the mechanism, never copy a secret); how it copes with the February 2026 developer-mode limits.
   - Other playlist sources: Tidal, Deezer, YouTube Music, Beatport, ListenBrainz (`api/source_playlists.py`,
     `api/mirrored_playlists.py`, `core/playlists`, `core/sync`, `services/sync_service.py`).
   - Wishlist and watchlist (`core/wishlist*`, `core/watchlist*`).
   - Requests: `api/music_requests.py`, `api/request.py`, `core/requests`.
   - Lidarr compatibility (`core/lidarr_compat`); discovery only briefly.
   - Compare with ours: `sourcing/playlist_sources.py`, `import_playlist.py`, `seed-spotify`, the planned S2-02 and S3.
3. **V2-02 `03-matching.md`: "have it / missing", identity, versions and editions.**
   - Files: `matching_engine.py`, `core/matching`, `client_match.py`, `source_ids.py`,
     `download_plugins/release_identity.py`, `edition_grouping.py`, `discovery/isrc_match.py`, `musicbrainz_*`,
     `acoustid_client.py`.
   - Compare with ours: `import_playlist.choose`, `sourcing/identity.py`, `docs/identity.md`, D26.
4. **V2-03 `04-soulseek.md`: Soulseek sourcing in full** (the most important section).
   - Files: `soulseek_client.py` (3.2k lines), `slskd_throttle.py`, `download_plugins/` (`album_bundle.py`,
     `query_variants.py`, `candidate_store.py`), `core/downloads/` (`candidates.py`, `candidate_pool.py`,
     `album_bundle_dispatch.py`, `pinned_batch.py`, `prioritize.py`, `peer_observation.py`, `observed_speed.py`,
     `failed_blocklist.py`, `soulseek_identity.py`, `monitor.py`, `cancel.py`, `lifecycle.py`, `staging.py`),
     `download_orchestrator.py`, `download_engine/`.
   - Cover:
     - query building and variants;
     - how candidates are scored;
     - track vs album requests, and how a folder is chosen;
     - what happens when a track fails: another peer, the same peer, or a whole-album switch. Compare with goal E.
     - peer blocklists and peer quality memory;
     - enqueue (one POST for many files?);
     - how it finds its own transfer, polls, times out, cancels and **removes** transfers;
     - handling of 4xx/5xx and of slskd or VPN outages;
     - throttling.
   - **A table of every slskd endpoint it calls**, with the request body and the response fields it reads. Mark each row
     "from SoulSync's code, not captured". We have never captured the enqueue response or `/users/{peer}/directory`
     browse, so this table tells our S1-04 and S2 work which shapes to capture.
   - Compare with ours: `sourcing/slskd_client.py`, `fetch.py`, `scorer.py`, `fake_slskd.py`, the planned S1 and S2.
5. **V2-04 `05-other-sources.md`: the non-Soulseek music sources**, one short paragraph each. Deezer, Tidal, Qobuz,
   Amazon, HiFi, YouTube/yt-dlp, SoundCloud, Bandcamp, JioSaavn, torrent, Usenet/Prowlarr, Lidarr. For each: how it
   gets audio, which credentials, and a **legality / terms-of-service flag** (ripping from streaming services is in
   scope only as a risk to name). Also how the orchestrator picks between sources.
6. **V2-05 `06-verification.md`: what proves a download is right and good.**
   - Files: `core/downloads/validation.py`, `post_processing.py`, `atomic_album_publish.py`, `atomic_manifest.py`,
     `atomic_recovery.py`, `album_consistency.py`, `acoustid_verification.py`, `audio_length.py`, `core/quality`,
     `replaygain.py`, `api/quarantine.py`, `review_reject.py`, `core/blocklist`.
   - Cover: fake/transcode detection, wrong-song protection (would ext-74 have been caught?), album consistency
     checks, quarantine.
   - Compare with ours: `sourcing/verify.py`, `acoustid.py`, `policy.py`, D24, and the S1-02/S2-03 plans.
7. **V2-06 `07-filing-library.md`: tags, file placement, the library, and Navidrome.**
   - Files: `tag_writer.py`, `core/metadata`, `core/enrichment`, `library_reorganize.py`, `reorganize_*`,
     `core/imports/pipeline.py`, `auto_import_worker.py`, `core/library`, `navidrome_client.py`, `core/media_server`,
     `repair_worker.py`, `api/deleted_files.py`, `core/maintenance`.
   - Questions:
     - Does it use beets?
     - What does it write into tags, and when?
     - How does it trigger and await scans?
     - How does it edit Navidrome playlists, with what guards?
     - What does it delete or move, and is there a reverse log?
   - Compare with ours: `sourcing/filer.py` (D18/D22/D29), `crates/playlist_edit.py`, `crates/trash.py`, placement
     (D44), the safety invariants in CLAUDE.md, and the album-path decision.
8. **V2-07 `08-ui-api.md`: UI, API and the phone.**
   - Files: `web_server.py` routes, `webui/`, `templates/`, `api/`, `core/streaming`, `core/playback`, `core/radio`,
     `core/mcp`, `automation_engine.py`, webhooks, `api/auth.py`, profiles.
   - Questions: does the web UI work on a phone, and as an installable home-screen app? How does a request flow from a
     phone, a link, or a search? Does it stream itself? How does it fit with the B options (Amperfy + web app +
     Shortcut, a proxy, a native fork)?
   - Compare with ours: `crates/service.py`, `web/`, the planned S3 API.

## V3: comparison against the goals (after: [V2-01, V2-02, V2-03, V2-04, V2-05, V2-06, V2-07])
9. **V3-01 in `README.md`: the stage-by-stage table.** Rows: intake, matching, search/score, album sourcing and
   fallback, transfer handling, verification, tagging/filing, Navidrome/playlists, UI/API, operations (deploy,
   backups, locks, observability), safety (approval gate, one beets writer, reverse logs, trash rules). Columns:
   SoulSync, ours (built), ours (planned S1–S4), which is stronger and why.
   Then for each 2026-10-21 failure class: what SoulSync would have done, with citations.
   Then each of Michael's decisions (D7, D18, D22/D29, D24, D26, D27, D31/D35, D44): does SoulSync honour, conflict
   with, or not address it?
10. **V3-02 in `README.md`: fit to goals B, C, D, E and crates.** For each goal: SoulSync has it / partly / no, how, and
    the cost of getting it from SoulSync versus building it.

## V4: recommendations (after: [V3-01, V3-02])
11. **V4-01 `09-recommendations.md`.** Weigh four options, each with effort (days or weeks), risk, ongoing maintenance
    (its pace: how often its internals change), licensing (MIT: keep the notice on anything ported), and what changes
    or is lost in our stack:
    - **(a) Adopt wholesale:** SoulSync replaces our sourcing and filing.
    - **(b) Run it beside ours** for some jobs. Name the integration points and the conflicts: two writers to the
      library, beets or Navidrome playlists; the approval gate; the `amperfy` account.
    - **(c) Port specific pieces:** name each module and what it would replace or extend in ours.
    - **(d) Learn only.**

    Recommend one option, with an ordered list of next steps. Say what it means for the queued runs:
    `dj-crate-streaming-2026-10-22-fixes` (S1) and `dj-crate-streaming-2026-10-22-build` (S2–S4). For each S2/S3
    feature: keep, change or drop, and why. If the answer is "change", put a draft spec delta in the file. Apply
    nothing.
12. **V4-02 Review and summary.** Run an Opus review subagent over the whole report:
    - spot-check at least 20 citations against the clone and our tree, and fix what's wrong;
    - check every "unverified" mark;
    - write the one-page summary at the top of `README.md`: the verdict, the top 5 findings, the next steps;
    - add one line in `docs/next-todos.md` pointing at the report.

## Rules for this run
- Nothing live: no docker, no compose, no `/srv`, no slskd, no Navidrome. No transfers.
- No network except read-only GitHub/web reading about SoulSync.
- No code changes in our repo. Docs only under `docs/research/2026-10-22-soulsync/`, plus the one `next-todos` line.
- A question that is Michael's: write it under "Questions for Michael" in `09-recommendations.md`, take the simplest
  assumption, and carry on. It is a research run, so it never parks.
