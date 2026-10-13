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

_Pending — filled in after `beet import -q`._

