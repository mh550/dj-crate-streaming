# Library import report

_Generated 2026-10-13 from `beet import --pretend` with `deploy/beets.yaml`. Source `/srv/incoming/library-import` (read-only); destination `/srv/music`._

## Dry run

- Files beets would import: **917** (library-map.csv has 917 audio files)
- Directory groups (beets 'albums'): **445**
- Group sizes: 1 files × 375, 2 files × 44, 3 files × 7, 4 files × 5, 6 files × 3, 8 files × 1, 9 files × 2, 14 files × 3, 43 files × 1, 59 files × 1, 62 files × 1, 73 files × 1, 90 files × 1
- Groups with one consistent album tag (likely real albums → MusicBrainz lookup): **423** (500 files)
- Groups with mixed or empty album tags (loose genre folders → will import as-is per track): **22** (417 files)
- Files missing title or artist tags: **4**; unreadable: **0**

## Loose groups (as-is on their own tags; Michael's to tidy later in Picard)

| folder | files | distinct album tags | distinct artists |
|---|---:|---:|---:|
| sockseek/shakori | 90 | 84 | 70 |
| sockseek/Tea tent | 73 | 51 | 44 |
| sockseek/secondset | 62 | 58 | 49 |
| firstset？ | 59 | 50 | 49 |
| mainstream/mainstream-classics | 43 | 26 | 20 |
| sockseek/freedom | 14 | 13 | 13 |
| sockseek/shakori2 | 14 | 11 | 11 |
| uncategorized | 14 | 14 | 10 |
| (root) | 9 | 8 | 6 |
| uncat-2 | 9 | 9 | 8 |
| disco-fonk-daft-punk/french-touch | 6 | 2 | 2 |
| Haus-Jungle-GhettoTech-Dance/DnB | 4 | 3 | 3 |
| sockseek/buck-bumble | 4 | 4 | 4 |
| disco-fonk-daft-punk/disco | 2 | 2 | 2 |
| disco-fonk-daft-punk/dj-revisions | 2 | 2 | 2 |
| Haus-Jungle-GhettoTech-Dance | 2 | 1 | 2 |
| Haus-Jungle-GhettoTech-Dance/rallycar | 2 | 2 | 2 |
| sockseek/2-japanese-songs | 2 | 2 | 2 |
| sockseek/clouds | 2 | 2 | 2 |
| Soul-Motown/studio-pop-70s-80s-90s/Michael Jackson | 2 | 2 | 1 |
| playlists/shakori/Al Green/I'm Still in Love with You | 1 | 1 | 1 |
| playlists/skate three unofficial soundtrack/Three Dog Night/Celebrate_ The Three Dog Night Story, 1965–1975 | 1 | 1 | 1 |

## Real import

_Run 2026-10-13 04:14–05:05, `beet import -q -c -P` (copy mode; source untouched, verified by mtime)._

| | |
|---|---:|
| Files in `/srv/music` | **859** |
| beets items / albums | 859 / 358 |
| Distinct audio streams in the source | 831 |
| Redundant copies now in `/srv/music` (same audio, different tags/folders) | 28 |
| Originals mapped to a new path in `library-map.csv` | 917 / 917 (`other_copies` lists the 28 redundant files) |

**Pass 1 (album mode, `duplicate_action: skip`):** 455 groups as-is, 2 MusicBrainz matches, 87 groups
skipped as duplicates. Quiet mode only auto-applies *strong* matches, and most groups are
one track of a multi-track album, so MusicBrainz tagging essentially didn't happen; the
library is on Michael's existing tags. Fine for Navidrome; Picard/`beet import -t` later
if he wants canonical tags.

**Why 87 duplicate-skips:** beets dedupes by album artist + album *tag*, so a second
folder holding the same album (byte-identical copies filed in two playlists) is skipped —
correct — but so is a *different* track whose tags collide with one already imported
(e.g. several `Unknown Artist` albums). 52 files were real misses.

**Pass 2 (those 52 files only, singleton mode, `duplicate_action: keep`):** all 52 imported
(17 flagged duplicate-keep, 1 MusicBrainz match). Nothing from the source is
missing. The 28 redundant copies are a later `beet duplicates` / taste
decision, not an overnight one.

**MusicBrainz-tagged albums:** `started Tue Oct 13 04:11:45 2026`, `started Tue Oct 13 04:14:23 2026`, `started Tue Oct 13 05:06:54 2026`.

**Hand-fix list for Michael:** everything else is as-is — see `/srv/docker/beets/import.log`
(`asis` lines) and the "Loose groups" table above; the 4 files missing title/artist tags
landed under `Singles/` or an empty artist. `docs/library-map.csv` says where each file came from.

## Folders → playlists

`scripts/folders_to_playlists.py` recreated the genre/vibe folders as **35 Navidrome playlists, 907 entries**
(one per folder that holds tracks; nested folders as `Parent / Child`; Artist/Album dirs inside a
folder are not playlists). The 10 tracks that sat loose at the library root are in no playlist.
None are flagged as crates — that's a per-playlist choice in the crate UI.
