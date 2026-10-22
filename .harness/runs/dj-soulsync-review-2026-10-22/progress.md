# Progress log — run `dj-soulsync-review-2026-10-22` (branch `harness/dj-soulsync-review-2026-10-22`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it wrote, what it learned, what it asks. Nobody edits older entries.
The feature list is `.harness/runs/dj-soulsync-review-2026-10-22/feature_list.json`: array order is priority order; a
session gets the first feature whose `passes` is false and whose `after` all pass, and may flip only its own `passes`.
Michael steers through `INBOX.md` on this branch (first line `status: run|pause|stop`; answers under `## Answers`).
Every session reads `INBOX.md` and this file first, then the spec `docs/specs/2026-10-22-soulsync-review.md` and the
brief `brief.md` (the brief wins on scope).

### 2026-10-22 · V1-02 · passes
- **New:** `## Maintenance health` in `docs/research/2026-10-22-soulsync/01-map.md` (releases, contributors, issues/PRs/stars, size of recent change), every figure with its `gh api` call, read 2026-10-22. Docs only; tests 1615 → 1615.
- **Numbers:** 101 releases (median 2.16 days between the latest 20); 41 contributors, Nezreka 7,590 of 8,544 (88.8%), bus factor 1; 16 open issues, 14 open PRs, 2,309 stars; 1,592 commits in 30 days (377 merges); `core/soulseek_client.py` 8 commits in 30 days (last 10-06), `core/downloads/` 71 (last 10-21); newest merge #1821 is 275 files, +37,273/−14,355.
- **Verified:** suite green in 580 s, 1615 tests. Release prerelease flags checked from the saved output (all false).
- **For later sessions:** `core/downloads/` churns daily, so cited line numbers are valid at 34bf7cf9c741 only (stated in the section). Commit author names ("BoulderBadgeDad", "Nez", "Claude") differ from the API login; I marked the identity *unverified*.
- **Questions for Michael:** none. **Proposed changes:** none.

### 2026-10-22 07:10 · V1-01 · passes
- **New:** `docs/research/2026-10-22-soulsync/README.md` (skeleton: `## Summary` "(written by V4-02)", links to 01-09, empty `## Stage-by-stage comparison` / `## Fit to goals` for V3) and `01-map.md` (380+ lines: process model + ASCII diagram, data stores with all music tables grouped by subsystem, settings/credentials, deployment, tests/CI, module map with `wc -l`, MIT license, `## Maintenance health` "(written by V1-02)", then the four comparison headings, **Verdict: adapt**). Docs only; tests 1615 → 1615.
- **Verified:** the citation check prints no BAD line (≈300 unique citations); an Opus review spot-checked ~190 and found 2 wrong lines (fixed) and some gaps (filled); every uncited claim carries `*unverified*` (4 marks). Suite: `check.sh` green in 582 s, 1615 tests.
- **Findings V2 should reuse:** the 118 `CREATE TABLE`s are 86 distinct live tables (5 comments, 8 markers, 17 `*_new`, a duplicate `hifi_instances`, `watchlist_podcasts_migrating`). There is no peer table: peer speed memory is in-process with a 1 h TTL (`core/downloads/peer_observation.py:11`). Secrets are Fernet-encrypted in `music_library.db` with the key file on the same volume, and they fall back to **plaintext** `config.json` (`core/settings.py:1225-1258`). No Spotify credential is embedded. Qobuz app secrets are scraped from its web player's bundle.js (`core/qobuz_client.py:218`). `spotipyFree` (GPL-3.0) is a hard dependency in `requirements.txt:95`, although its docstring says optional. No beets anywhere. `:latest` is published on every push to `main`, and CI never tests that merge commit.
- **Correction to the initializer's notes:** the UI is not only `webui/index.html`: `webui/src/` holds a React 19 + TanStack Router + Vite app (1,321 files) built into `webui/static/dist` (`Dockerfile:4-12`, `:101`). V2-07 must read both. `core/downloads/` has 46 `.py` files, and `api/` has 92 `.py` files recursively.
- **Questions for Michael:** none new.
- **Proposed changes:** none.

### 2026-10-22 · initializer

**This is a research run: documents only.** Every feature writes under `docs/research/2026-10-22-soulsync/`
(V4-02 also adds one line to `docs/next-todos.md`). No `.py` changes, nothing live, nothing executed from the clone.
Base: `6fb134e` on top of `origin/main` `5b3e3701c9`. Init: suite green, 1615 tests, 583 s.

**Features: 15.** V1 map: 2 (V1-01 map + README skeleton, V1-02 GitHub maintenance health). V2 subsystems: 9
(V2-01 intake, V2-02 matching, V2-03a Soulseek search/score/album/fallback, V2-03b Soulseek transfers + the slskd
endpoint table, V2-04 other sources, V2-05 verification, V2-06 filing/library/Navidrome, V2-07 UI/API/phone, V2-08
review of 02-08). V3 comparison: 2 (V3-01 stage table + failure classes + decisions, V3-02 fit to goals). V4: 2
(V4-01 recommendations, V4-02 whole-report review + summary + next-todos line). The spec's V2-03 is split in two
(a: search → folder choice → fallback → peer memory; b: transfers, errors, throttling, endpoint table) because
`core/soulseek_client.py` alone is 3,171 lines and `core/downloads/` has 48 files. V2-08 is added so V3 builds on
checked citations. Dependencies follow the brief: V1-01 `after: []`, every V2 feature `after: [V1-01]` (V2-03b also
after V2-03a), V3 after all of V2, V4 after V3.

#### The SoulSync clone (read-only, untrusted data)
- `~/research/soulsync-src/SoulSync`, commit `34bf7cf9c741` ("Merge pull request #1821 from Nezreka/dev",
  2026-10-21 19:01 -0700). The directory is mode `dr-xr-xr-x`: you cannot write into it, and you must not try.
- **Shallow clone, depth 1.** `git -C … log` shows exactly one commit. History, releases, issues and contributors come
  from `gh api repos/Nezreka/SoulSync/...` (read-only; `gh auth status` is logged in as mh550). At init: 30 releases on
  the first page (paginate for the total), newest `3.5.9` 2026-10-22, then 3.5.8 (10-20), 3.5.7 (10-17), 3.5.6 and
  3.5.5 (10-15); top contributor Nezreka 7,590 contributions, next kettui 258; 2,309 stars; `open_issues_count` 29.
- **Never execute anything from it:** no `python`, `pip`, `pytest`, `npm`, `docker`, `dev.sh`, `entrypoint.sh`. Read
  with `cat`, `sed -n`, `grep`, `wc`, `find`, `ls`, Read/Grep/Glob. Don't copy its code into our repo (paraphrase; a
  quoted line or two with a citation is fine, a function body is not).
- **Huge files; never Read them whole.** `web_server.py` 24,916 lines, `database/music_database.py` 28,019,
  `webui/index.html` 12,932 (the whole UI is this one file; `templates/` holds only a png and an xml),
  `core/repair_worker.py` 6,885, `api/source_playlists.py` 5,575, `core/watchlist_scanner.py` 5,340. Grep first, then
  `sed -n 'A,Bp'`. `grep -c 'CREATE TABLE' database/music_database.py` = 118.
- **Spec paths that differ in the clone** (the spec's basenames are right, the folders are not always):
  `post_processing.py`, `atomic_album_publish.py`, `atomic_manifest.py`, `atomic_recovery.py`, `review_reject.py` are
  in `core/downloads/`; `library_reorganize.py` exists twice (`core/` 3,066 lines and `core/repair_jobs/`);
  `lifecycle.py` and `staging.py` also exist in `core/issues/` and `core/imports/` (use `core/downloads/`); the
  Spotify files (`spotify_client.py` …) are under `core/`; `core/matching_engine.py`, `core/client_match.py`,
  `core/source_ids.py`, `core/edition_grouping.py`, `core/acoustid_client.py`, `core/soulseek_client.py`,
  `core/slskd_throttle.py`, `core/download_orchestrator.py`, `core/tag_writer.py`, `core/navidrome_client.py`,
  `core/auto_import_worker.py`, `core/automation_engine.py`, `core/replaygain.py`, `core/album_consistency.py`,
  `core/acoustid_verification.py`, `core/audio_length.py` all exist as named. `core/` has 203 entries, `api/` 64.
- **slskd calls** are built as `f"{self.base_url}/api/v0/{endpoint}"` (`core/soulseek_client.py:210`) with a
  no-prefix "direct" path at `:316`, so grep for `transfers/`, `searches`, `users/`, `server`, not for `/api/v0/`.
  Line 1250 documents `/transfers/downloads/{username}/{download_id}?remove=…`; 2901-2902 probe `/server` vs
  `/server/state`. Process model hints: `gunicorn.conf.py:4-5` (`gthread`, 1 worker); `wsgi.py`; CI in
  `.github/workflows/` (build-and-test, cleanup-dev-images, dev-nightly, docker-publish, visual-baselines).
- `grep -rli beets core --include=*.py` hits `core/settings.py`, `core/auto_import_worker.py`,
  `core/library_reorganize.py`, `core/library/reorganize_tag_source.py` (V2-06 starts there). SoulSync's own
  `docs/api-response-shapes.md` and `docs/download-engine-refactor-plan.md` are worth a read for V2-03.
- Non-music, skip after naming once: `core/audiobook_*`, `core/podcast_*`, `database/video_database.py`
  (10,460 lines), `api/video*`, `api/audiobook*`, `api/podcasts.py`, anything `movie`/`tv`/`youtube` video.

#### Our side (this worktree; cite as `ours:<path>:<line>`)
- The spec's `import_playlist.py` is `sourcing/import_playlist.py`; `fake_slskd.py` is `sourcing/fake_slskd.py`
  (tests use it via `tests/test_fake_slskd.py`); `seed-spotify` is a subcommand in `sourcing/cli.py`. Other names
  are as the spec says: `sourcing/{playlist_sources,spotify_csv,identity,scorer,fetch,slskd_client,verify,acoustid,
  policy,filer,musicbrainz,worker}.py`, `crates/{service,store,playlist_edit,trash,placement,reconcile}.py`, `web/`.
- Decisions by line: `docs/specs/2026-10-13-next-session-design.md` D7 :61, D18 :72, D22 :76;
  `docs/specs/2026-10-17-amperfy-pivot.md` D24 :19, D26 :21, D27 :22, D29 :24, D31 :26, D35 :30, D44 :39.
- The planned S1–S4 and the 2026-10-21 failure findings: `docs/specs/2026-10-22-downloads-and-requests.md` (S1 at
  :61-96, S2 :97-187, S3 :188-222, S4 :223-230, the findings table under `## What was found` :16-51).
- **The S1 branch `origin/harness/dj-crate-streaming-2026-10-22-fixes` did not exist at init** (`git ls-remote`).
  Check again at the start of V2-03a/b and V4-01; if it exists, read it with `git fetch` + `git show`/`git diff`, read only.
- `docs/research/` does not exist yet; V1-01 creates `docs/research/2026-10-22-soulsync/` and `README.md`.
- Tests that read docs: `tests/test_monitoring_doc.py` (docs/monitoring.md) and `tests/test_web_health.py`; none
  reads `docs/next-todos.md` or `docs/research/`, so the one next-todos line (V4-02) is safe.

#### Conventions every section file follows
- Citation form: `SoulSync:<path>:<line>` or `SoulSync:<path>:<a>-<b>`, likewise `ours:…`. Paths are relative to the
  clone root / the worktree root, with no leading `./`.
- A claim with no citation carries the literal mark `*unverified*` (and ideally what would verify it).
- Four headings, in order: `## What SoulSync does`, `## How ours does it`, `## The difference that matters`,
  `## Worth taking?`, ending in a `**Verdict:** yes|adapt|no` line. Dense and technical; no marketing language.
- **Citation check** (run before committing; the verifier runs it too; it prints nothing when all is well):
  ```
  cd /home/mh550/worktrees/dj-crate-streaming/dj-soulsync-review-2026-10-22
  grep -ohE '(SoulSync|ours):[A-Za-z0-9_./-]+:[0-9]+' docs/research/2026-10-22-soulsync/*.md | sort -u |
  while IFS=: read -r src p l; do
    case $src in SoulSync) f=$HOME/research/soulsync-src/SoulSync/$p;; ours) f=$p;; esac
    [ -f "$f" ] && [ "$l" -le "$(wc -l < "$f")" ] || echo "BAD $src:$p:$l"
  done
  ```
  It checks the first line of a range. Write citations with no space before the colon and no trailing punctuation
  inside the token (`SoulSync:core/x.py:12.` is fine: the regex stops at the digit).
- The suite still runs at the end of every feature (`.harness/check.sh`, ~10 min, 1615 tests): docs-only, so it
  must stay at 1615 passed with no new skips. Nothing under `/srv`, no docker, no compose, no live scripts.
- Keep the whole report free of credential values: report a mechanism and a `file:line`, never a key.

#### Questions for Michael (each has a default; answer in INBOX.md to change it; V4-01 copies them into 09-recommendations.md)
1. **Effort unit.** Estimates are given in "harness nights" (one overnight run of this harness) with a days/weeks
   equivalent; default assumption: one harness night ≈ 6-10 features ≈ 1-2 human days.
2. **Baseline for goal B.** B is undecided; the comparison takes option 1 (Amperfy + our web client as a phone web app +
   an iOS Shortcut) as the baseline, since it needs the least new code, and treats options 2 and 3 as deltas.
3. **Trying SoulSync for real.** The brief forbids running it; the report judges from source and public GitHub only.
   Default: no sandbox trial is proposed unless the recommendation is (a) or (b), in which case the next steps include
   an isolated trial Michael runs himself (separate compose project, its own library copy, never `/srv/music`).
4. **Streaming-service sources.** SoulSync's Deezer/Tidal/Qobuz/Amazon/HiFi/YouTube getters are described and flagged
   for terms-of-service and legal risk, and never recommended for our stack (D7, D26, provenance for D24). Default: out.
5. **Spotify auth.** The report assumes Spotify stays "Michael's own developer app only" (goal C) and judges SoulSync's
   public/scraper paths as mechanisms to learn from, not to adopt.
