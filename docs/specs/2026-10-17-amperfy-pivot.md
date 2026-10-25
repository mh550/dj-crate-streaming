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

Moved to [`../decisions.md`](../decisions.md) on 2026-10-25 (D24–D53, IDs kept); new decisions go there too.


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
