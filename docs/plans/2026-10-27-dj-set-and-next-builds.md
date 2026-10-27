# The 2026-10-31 set and the next builds: who drives what

Written 2026-10-27 00:30 EDT, from a read-only look at the repo, the live containers, `harness status` and the
rane-one-mixxx repo, plus web research on beat grids, key and stems. Nothing live was changed. The set date is assumed
to be **Saturday 2026-10-31**. If it's Friday, move every step below up a day.

## The decision

**Michael orchestrates this week himself, in interactive Claude Code sessions. The harness builds in the background.**
One run is queued now; more follow once their design questions are answered. After the set, the default flips: specced
build work goes to the harness, and interactive sessions are for design, live steps that need judgment, and anything on
the laptop.

Why the set doesn't go to the harness:

| What the set needs | Harness fit | Interactive fit |
|---|---|---|
| Deploy 381 commits of main, days before a gig, then watch it | Possible (`POLICY=live-staged`), but a bad deploy surfaces overnight | Michael sees it at once and can roll back |
| Soulseek approvals | **Never by an agent** (D7, CLAUDE.md "Never"). A run would park on every one | Michael clicks; the session watches the worker and triages |
| Choosing the songs, triaging `review` rows, deciding what to buy | Each one parks the run | Seconds each |
| Getting files onto the Windows laptop, Serato prep | No agent access to the laptop | Michael's hands, with a session beside him |
| A fixed deadline (4 days) | Overnight turnaround, plus queueing behind a self-improvement run that's changing `lib/driver.sh` | Same day |

Why the builds do go to the harness: they are specced, verifiable by the suite, have no deadline, and take hours. That
is what the harness does well (verified milestones, `MERGE_POLICY=auto`). **Rule for this week: nothing on the set's
critical path depends on a harness run landing.**

## What shapes the plan

- **Live is the 10-21 hotfix image** `dj-crates:41fcc5bc01`. Main (`7b6275c`) is 381 commits ahead. Album downloads
  (S2), the request API (S3), the Al Green fixes (S1), guards (R1–R8) and N2–N4 only work after a deploy from main.
  The hotfix patches are on main (`59c6f6a`), so a deploy from main no longer rolls them back.
- **Downloads need Michael's click** until auto-approve is built and he says "go" (D7). D7's precondition, a first
  manual download, was met on 10-21: 19 approvals, 8 filed.
- **The DJ laptop is Windows, running Serato**. Its Tailscale node is `michael`. Nothing syncs to it, and no agent can
  reach it. The Rane One is plugged into pop-os for the Mixxx mapping work, and `~/.rane-armed` may be present.
- **Harness slots:**
  - `MAX_PARALLEL_RUNS=2`, one run per project.
  - `agent-harness-2026-10-25-memory` (18/23) holds one slot.
  - `agent-harness-2026-10-26` is stopped and waiting to rebase after it.
  - The dj slot is free. dj runs use `POLICY=live-staged` and `MERGE_POLICY=auto`.
- **No live writes and no deploy from 03:15 to 04:30** (restic), or while `restic-backup.service` is active.
- **Analysis, stems and sync don't exist yet.** The worker writes every playlist to `/srv/music/_playlists/*.m3u8`
  every 300 s, which is the hook for sync. `/srv/music` and `/srv/crates` are on one filesystem, so crate folders can
  use hardlinks.

---

## Track A: the set (interactive, Michael orchestrating)

Each step names its owner and when it counts as done. "Session" means an Opus Claude Code session started in
`~/projects/dj-crate-streaming`; paste the prompt shown.

### A0. The song list (Michael, today)

- **What:** decide the playlist name; this plan uses `set-2026-10-31`. Then provide the list in one of three forms:
  - a Spotify playlist URL (public, 100-track cap);
  - an Exportify CSV (no cap);
  - plain "Artist – Title" lines, which the session turns into a CSV.
- **Also:** mark which tracks you want **as the full album** (the S2 album request), not just the track.

### A1. Deploy main (session, Tuesday daytime)

- **Prompt:** "Deploy origin/main per `docs/runbooks/2026-10-22-morning-checklist.md` and the deploy part (§2) of
  `docs/runbooks/2026-10-22-downloads-checklist.md`, under CLAUDE.md → Live system: backup status, snapshot
  `--suffix pre-deploy-20261027`, record the rollback tag, `scripts/deploy.sh` from a fresh worktree, Check green, then
  `crates.cli imported migrate` dry run → `--apply`. Stop before the duplicate-cleanup `trash`, the id backfill and the
  import re-runs; those wait until after the set."
- **Done when:**
  - `crates` and `worker` are healthy on the new tag.
  - `scripts/live-check.sh` passes.
  - `imported migrate --apply` is logged.
- **If it goes wrong:** roll back to `dj-crates:41fcc5bc01` (the CLAUDE.md rollback line). Then run the set with the
  per-track Preview/Approve flow that works today. Slower, but proven.

### A2. Smoke-test the album flow (session + Michael, Tuesday)

- **What:** downloads checklist §3–4, on a known album before the set's requests:
  - `wanted reopen` ext-74; approve ext-74 and ext-78;
  - `request add` the Al Green *I'm Still in Love with You* link, then preview, and Michael approves.
- **Done when:**
  - the album files to `Al Green/I'm Still in Love With You (1972)/NN - Title.flac` from as few peers as possible;
  - AcoustID passes on every track;
  - no transfer is left in slskd.
- **If it fails:** the session diagnoses it read-only, and the fix becomes a small interactive fix-and-deploy. Don't
  queue it; it's on the critical path.

### A3. Import the set and request what's missing (session + Michael, Tuesday evening)

- **Steps:**
  - `sourcing.cli request add <spotify playlist URL>` (or `import-playlist --request <csv>`). This makes the Navidrome
    playlist the way `import-playlist` does, and records **one** playlist request (`docs/api.md`).
  - Tracks already in the library land in the playlist. Missing ones become the request's rows. Three or more from one
    album go as one album job (S2-07).
  - Add the album-marked tracks from A0 as their own `request add` album requests.
  - `request preview <id>` for each request. The session lists the picks in one table and flags the weak ones
    (title-only matches, a low margin, odd durations).
  - Michael runs `request approve <id>`, one click per request. Rows he doesn't like get re-picked or `review`ed
    first.
  - Flag the playlist as a crate.
  - The session watches the worker and triages the `review` rows with him.
- **Done when:** every row is filed, `review`d, or marked "buy".

### A4. Buy or cut the misses (Michael, by Wednesday night)

- **What:** some tracks won't be on Soulseek or will fail verify. Buy them (Bandcamp, Qobuz, Beatport), import them
  the way purchased files go in today (`/srv/incoming` is Michael's), or cut them from the set.
- **Deadline:** **Wednesday 23:59.** After that, the list is what's in the library.

### A5. Get the set onto the laptop (session + Michael, Wednesday night or Thursday)

The sync design is Track B2's job. For this week, copy once:

- **Session prompt:** "Export playlist `set-2026-10-31` to `~/dj-export/set-2026-10-31/`: copy, never move, every file
  in its `/srv/music` layout, plus `set-2026-10-31.m3u8` with paths relative to that folder and a `MANIFEST.txt`
  (relative path, size, sha256). Read-only on `/srv`."
- **Michael, on the laptop (PowerShell; the OpenSSH client is built into Windows):**
  `scp -r mh550@pop-os:dj-export/set-2026-10-31 "$HOME\Music\"`. Tailscale must be up on both machines.
- **Check:** the file count and total size match `MANIFEST.txt`.
- **In Serato:** drag the folder (or the m3u8) onto the crate panel to make the crate.
- **Done when:** every track loads in Serato from local disk, with Wi-Fi off.

### A6. Serato prep (Michael, Thursday)

- **Serato version:**
  - **Don't move to Serato DJ 5.0 this week** if you aren't on it already. Its "Lucid" Flexible beat grids are the
    feature you want, but a major-version change days before a gig is avoidable risk. Try it on a copy after the set
    (B3).
  - If you're already on 5.0, use Flexible for the live-drummer tracks and Fixed for the rest.
- **Steps:**
  - Analyze the crate and check the grid on every track by ear.
  - Live-played tracks (disco, soul, funk, Al Green, Coltrane) will drift on a fixed grid. Fix the worst by hand and
    **list them**: that list is B3's test set.
  - **Key:** Serato's detection came last in a 2020 community test (~60%). If harmonic mixing matters for this set, run
    the crate through Mixed In Key (trial or paid); it writes the key into the tags, which Serato reads. Otherwise
    trust your ears.
  - **Stems:** Serato's built-in stems. Test on the laptop with the busiest track, and watch the CPU meter. Turn them
    off if it stutters.
  - Set hot cues and intro/outro points; set auto-gain or check levels across sources.
  - Check versions. D26 sources the exact track the playlist names, so you may have radio edits where you wanted
    extended mixes, or explicit versions where the venue needs clean ones.
- **Done when:** every track is analyzed, the drifters are fixed or noted, cues are set and levels are even.

### A7. Freeze and rehearse (Michael, Friday)

- **Freeze:** no more library changes reach the laptop.
- **Controller (these steps are Michael's alone):**
  - Unplug the Rane One from pop-os.
  - `rm ~/.rane-armed` on pop-os (TODO-MICHAEL; it stops the mapping's MIDI sends).
  - Connect the Rane One to the laptop and check platters, pads and mixer in Serato.
- **Backups:**
  - Copy the set folder plus Serato's `_Serato_` folder to a USB stick.
  - Spare cables. If possible, a second device that can play the set.
- **Rehearse:** Wi-Fi off, load every track once, play a 30-minute run-through.
- **Done when:** the run-through is clean and the USB backup is checked.

### A8. After the set (Sunday)

- Save Serato's history for this session (it feeds Pathways later).
- Write down what hurt: grids, keys, missing versions, levels. That note feeds B3 and the B2 design.

---

## Track B: the builds (harness, queued)

A pattern repeats: **interactive design → spec committed to main → harness build-only run → live steps in a
runbook**. Those live steps are run by Michael, or by a live-staged session once the runbook is routine.

### B1. Hands-off fetch and an album-shaped library (queue now, build-only)

- **Goal:** a request goes from "add" to "filed in its album folder with art" with no clicks when the pick is clear,
  and with one click per request when it isn't.
- **Scope:** build-only. Nothing in B1 deploys before Sunday 2026-11-01. Its live steps go into a runbook.

**Milestones** (each milestone's first feature gets an explicit `after`):

- **F1. A one-click approve that doesn't approve blindly.**
  - `request approve <id>` already approves a whole album, track or playlist request in one click
    (`crates/service.py` `approve_request`, S3).
  - First measure what it does with a weak pick. Then give each row of a request preview a confidence flag
    (`clear` / `weak`, with the reason: title-only, margin, duration, version mismatch). `approve` takes the `clear`
    rows and leaves the `weak` ones for a per-row look.
  - The same flag is F3's gate.
  - Tests: the fake slskd, one album request and one playlist request with a weak row.
- **F2. Auto-preview.**
  - The worker previews new `external_wanted` rows and new requests on its own. That means a search plus `rank`; a
    search is not a transfer, so D7 still holds.
  - Rate-limited, at most N searches a minute (default 6), with backoff on slskd errors.
  - The cached pick and its score breakdown are visible in `/api/requests/<id>`.
- **F3. Auto-approve policy, off by default.**
  - `deploy/policy.toml [auto_approve] enabled = false`. Turning it on is D7's "go" and Michael's alone; the run never
    flips it.
  - **When on**, a row auto-approves only if all of these hold:
    - the top candidate is a full artist+title match (never title-only; see `scorer.py:134`);
    - it passes the quality policy;
    - duration is within tolerance of the wanted row;
    - the score margin over the next candidate clears a threshold (the run measures the threshold on recorded
      responses and reports it);
    - the row is not a `review` row.
  - **Caps:** per request (default 30 rows) and per day (default 100).
  - Every auto-approval is an `approvals` row with `approved_by='policy:auto'` (the column already allows
    `policy:<name>`) and an event.
  - **Kill switch:** `enabled=false` takes effect at the next worker tick.
  - Everything else waits for a click as today. Post-download verify (AcoustID hard fail, transcode checks) is the
    backstop, and a failed row moves to the next source (S1).
- **F4. Album folders for every matched track.**
  - Extend D50: a single-track download whose MusicBrainz recording resolves to a release files to
    `$albumartist/$album ($year)/$track - $title`, with the album tags written through `write_minimal`. Otherwise it
    stays in `Singles`.
  - **Decision (default, Michael may overturn):** a song on many releases files under its **original album**. That
    means the earliest release group with primary type Album and no Compilation, Live or Soundtrack secondary type;
    D53 gives the year.
  - No match leaves the song in `Singles`.
  - The filer and `deploy/beets.yaml` get tests in a scratch beets, the same way S2-06a was measured.
- **F5. Re-file the existing `Singles`.**
  - `scripts/refile_albums.py plan` (dry run: old path → new path, per release, with the MusicBrainz evidence), then
    `apply` with a reverse log.
  - Moves go through the N1/N4 repoint machinery, so playlists keep their tracks: crates.db repoint, Navidrome scan,
    playlist check (R-series health check). Same guards as the duplicate cleanup.
  - `apply` is a **staged runbook step** and stays at `plan` until Michael lifts it.
- **F6. Cover art.**
  - Embed front art from the Cover Art Archive by release MBID, for album-filed tracks only: fetchart + embedart in
    `deploy/beets.yaml`, or a small fetcher if beets 1.6.0's plugins misbehave in scratch.
  - Max 1200 px, JPEG.
  - Verify and snapshot the bytes before and after: embedding changes the file, so restic sees new versions. That's
    expected; note it in `docs/backup-plan.md`.
- **F7. Runbook.**
  - `docs/runbooks/<date>-b1-live-steps.md`: deploy, auto-preview watch, F5 `plan`, the F5 `apply` gate, and the
    one-line D7 switch.
  - Update `docs/next-todos.md` and `docs/decisions.md` (the F4 default, the F3 default thresholds).

**Out of scope for B1:** the gluetun NAT-PMP drop (compose, Michael's; the code already survives a drop), the phone UI
(B5), and Spotify search (item 11).

**Queue it (Michael):**

```
harness queue add ~/projects/dj-crate-streaming --spec docs/plans/2026-10-27-dj-set-and-next-builds.md \
  --brief "Track B1 only (F1–F7). Build-only: no deploy, no live write, no Soulseek transfer; D7 and D26 bind. auto_approve ships disabled. Live steps go in the F7 runbook."
harness queue start
```

It can start at once: the dj slot is free, and the memory run holds the other slot. If you'd rather keep the second
slot for `agent-harness-2026-10-26`'s restart, queue B1 after it instead.

### B2. Server → laptop crate sync (design session first, then a run)

- **Goal:** flag a playlist as a crate on the server (or on the phone), and it appears in Serato on the laptop with its
  files, by itself. Edits flow the same way.
- **Shape I'd propose:**
  - The worker keeps `/srv/crates/<crate>/` as a mirror of each crate's files, using hardlinks (same filesystem, no
    extra space) in the album layout.
  - Syncthing over Tailscale sends `/srv/crates` to the laptop.
  - The worker writes a Serato `.crate` file per crate (`_Serato_/Subcrates/<name>.crate`; the format is documented in
    Holzhaus/serato-tags), with laptop-side paths.
  - The m3u8 stays as the portable fallback.
- **Questions to settle in a ~1 h interactive design session (brainstorming), before any spec:**
  1. **Who owns the tags?** Serato writes its analysis (grids, cues, BPM, key) into the audio files' tags.
     - One-way sync either flags those edits as local changes, or loses them when the server file changes.
     - Two-way sync sends them back. Syncthing replaces files via temp-and-rename, which breaks the hardlink, so the
       crate copy diverges from `/srv/music`. It also brings un-verified bytes into the backup.
     - Options: (a) the laptop owns analysis and the server never rewrites a file once it's in a crate; (b) the server
       owns analysis (B3) and Serato's writes are throwaway; (c) two-way, with the server re-verifying returned files.
     - This one decision shapes B2 and B3.
  2. **Scope:** crates only (proposed), or the whole library?
  3. **Deletions:** when a track leaves a crate, does it disappear from the laptop? Proposed: it leaves the crate file
     at once, and the audio is pruned after N days unless another crate holds it.
  4. **Safety for gigs:** a "freeze" switch per crate, so nothing changes on the laptop in the 24 h before a set.
  5. **Laptop setup:** Syncthing on Windows as a service, and where the library lives (a dedicated drive or folder).
- **After the session:** spec → harness run (build-only), with a laptop setup checklist for Michael.

### B3. Analysis: grids, key, and the "smart" beat grid (evaluate first)

The variable beat grid is **not blocked by the DJ software's storage**:

- **Serato:** its BeatGrid tag holds many markers, each with a position and a beat count to the next.
- **Mixxx 2.5:** saves a `BeatMap` (a position for every beat) whenever the grid isn't constant. Its analyzer keeps
  raw beats if "Assume constant tempo" is off, but there is no editor for multi-marker grids.
- **Rekordbox XML:** takes several `TEMPO` entries per track.

The real limits are **editing tools and analyzer quality**, not the format. Serato 5.0's Lucid Flexible and VirtualDJ's
Fluid now do this automatically. Those are most likely the projects seen on Instagram.

**Step 1, evaluation** (interactive, or a small harness run; about one evening):

- Take the A6 list of drifting tracks, 15–20 of them.
- Compare three sources against beats tapped by hand on 3–4 of them, and by ear on the rest:
  - Serato today;
  - Serato 5.0 Flexible, on a copy;
  - **Beat This!** (CPJKU 2024, `pip install beat-this`, per-beat timestamps, runs on the 1070 Ti).
- **Output:** a short findings doc and a build or don't-build call.
- **If Serato 5 Flexible is good enough,** the smart grid is Serato's job, and B3 shrinks to server-side key and BPM
  tags.

**Step 2, if building** (harness run, after B2's tag-ownership answer):

- A server-side analyzer runs after filing: Beat This! for beats and downbeats, KeyFinder or essentia for key.
- It writes to every target in use:
  - Serato BeatGrid markers (one per beat or per drift segment);
  - Mixxx `BeatMap` + `bpm_lock`, after first checking that Mixxx keeps an injected grid;
  - optionally Rekordbox XML.
- Per-track mode: constant grid for programmed music, variable for live-played, chosen by the measured tempo variance.
- This is also the "Essentia/libKeyFinder → Serato GEOB" item on `ideas/ROADMAP.md`.

### B4. Stems (deferred; gated on the platform)

- **If Serato stays the gig platform:** Serato's built-in stems are the answer, because Serato doesn't load stems made
  elsewhere.
- **If Mixxx becomes it (rane-one-mixxx reaching gig-ready):** build a server pipeline (htdemucs_ft or a RoFormer
  model on the 1070 Ti, `--segment` for its 8 GB) → NI `.stem.mp4` in `/srv/stems`, synced with the crates.
- Mixxx stems are 2.6-beta only today.
- **Revisit when** rane-one-mixxx's M5–M6 land.

### B5. Phone requests (waits on question B)

- The request API is on main.
- The phone screen waits on Michael's client choice (next-todos item 12).
- Spotify search waits on a Spotify developer app and the `capture_spotify.py` capture (item 11).

### After the set: the older live steps

These go in the order `docs/next-todos.md` gives:

- the duplicate-cleanup `trash` (once Michael lifts the gate);
- the 485-row id backfill (after he reads the report);
- the import re-runs for the 13 `review` rows;
- the backup restore drill.

None are urgent. Each is a live-staged interactive session, or a live-staged run once the runbook has been done once by
hand.

---

## The week at a glance

| Day | Track A (interactive) | Track B (harness / design) | Michael only |
|---|---|---|---|
| Tue 10-27 | A1 deploy, A2 Al Green smoke test, A3 import + approve | B1 queued and running overnight | A0 list; approvals |
| Wed 10-28 | A3 triage, A4 buy/cut (deadline 23:59), A5 copy | B1 running | buying; approvals |
| Thu 10-29 | A6 Serato prep | B1 lands (self-merges; not deployed) | all of A6 |
| Fri 10-30 | A7 freeze + rehearsal | — | Rane move, `~/.rane-armed`, USB |
| Sat 10-31 | **Set** | — | — |
| Sun 11-01 | A8 notes | Deploy B1 (live-staged session); B2 design session | D7 "go" if wanted |
| Week of 11-02 | — | B3 evaluation, B2 spec → run, then B3 build if warranted | laptop Syncthing setup |

## How to choose, from here on

**Queue a harness run when** all of these hold:

- the work has a spec or plan on main;
- it's build-only, or its live steps are a runbook that has run before;
- the suite can verify it;
- no decision is expected mid-run;
- it's more than ~2 h of work;
- nothing depends on it within 24 h.

**Run an interactive session when any of these hold:**

- a live step needs judgment;
- there's a deadline;
- there's a design question;
- Soulseek approvals are involved;
- the laptop or hardware is involved;
- someone has to listen to the result.

**Keep runs small and unblocked:**

- One dj run at a time, scoped by `--brief` to one track of a plan.
- Give each milestone's first feature an explicit `after`.
- Answer a parked run's INBOX the same day, or it holds the slot.

## Risks

| Risk | Guard |
|---|---|
| The deploy of 381 commits breaks downloads days before the set | Do it Tuesday for slack, record the rollback tag, fall back to the per-track flow on the old image. Once files are on the laptop, the set doesn't depend on the server. |
| Tracks aren't on Soulseek, or the VPN drops mid-transfer (gluetun NAT-PMP, every 5–15 min) | S1 retries another peer after a drop. A buy-or-cut deadline Wednesday. |
| A Serato upgrade or new analysis changes grids the night before | No major Serato upgrade this week; freeze Friday. |
| The Rane One still armed for Mixxx sends | Michael removes `~/.rane-armed` before the move (A7). |
| B1 merges to main mid-week and someone redeploys | One deploy this week (A1); B1's deploy waits until Sunday. |
| Harness self-improvement churn (`lib/driver.sh`) while B1 runs | The memory run merges per milestone. If B1 parks on a harness error, `harness continue` after the memory run ends. |
