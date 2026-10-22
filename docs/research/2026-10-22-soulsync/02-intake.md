# 02 · Intake: where wanted music comes from

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed).
Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a claim
without one. Music only: video requests (`SoulSync:core/requests/video.py`), audiobook and podcast wishlists are named
here once and skipped.

## What SoulSync does

Every path into SoulSync ends in one table, `wishlist_tracks` ("for storing failed download tracks for retry",
`SoulSync:database/music_database.py:805-817`), written by one function, `MusicDatabase.add_to_wishlist_detailed`
(`SoulSync:database/music_database.py:15481`, insert at `SoulSync:database/music_database.py:15768`). A scheduled job drains it every 30 minutes
(`SoulSync:core/automation_engine.py:78-83`). Playlists, the artist watchlist, member requests, the Lidarr shim and
failed downloads are producers of wishlist rows; there is no separate "request" or "wanted" queue.

```
 Spotify (OAuth/embed/SpotipyFree)  Tidal Qobuz Deezer YT-Music Beatport ListenBrainz Last.fm iTunes
        │  PlaylistSource.get_playlist / refresh_playlist   (core/playlists/sources/base.py:118-167)
        ▼
 mirrored_playlists + mirrored_playlist_tracks   ◄── MusicDatabase.mirror_playlist (music_database.py:25146)
        │  run_playlist_discovery_worker  (match to Spotify/iTunes ids, core/discovery/playlist.py)
        ▼
 auto_sync_playlist → run_sync_task → PlaylistSyncService._sync_playlist   (have vs missing at 0.7)
        │  matched → server playlist (Navidrome reconcile_playlist / Plex / Jellyfin)
        │  missing → _wishlist_unmatched → WishlistService.add_spotify_track_to_wishlist
        ▼
 watchlist scan (24 h) ── WatchlistScanner.add_track_to_wishlist ──┐
 album / discography / upgrade clicks ── add_album_track_to_wishlist ┤
 Lidarr shim AlbumSearch ── queue_album_tracks ─────────────────────┤
 failed download ── add_failed_tracks_to_wishlist ─────────────────┤
        ▼                                                          ▼
 MusicDatabase.add_to_wishlist_detailed  →  wishlist_tracks row  (member profile: pending until admin approves)
        │  Auto-Process Wishlist, every 30 min: process_wishlist_automatically → split_due_for_retry
        ▼
 _run_wishlist_cycle → executor.submit(run_full_missing_tracks_process) → core/downloads/master.py
 side door: POST /api/v1/request → download_orchestrator.search_and_download_best  (no wishlist row)
```

Citations for the arrows: `SoulSync:core/playlists/sources/base.py:118-167`,
`SoulSync:database/music_database.py:25146-25239`, `SoulSync:core/discovery/playlist.py:1-24`,
`SoulSync:core/automation/handlers/sync_playlist.py:586-606`, `SoulSync:core/discovery/sync.py:674-684`,
`SoulSync:services/sync_service.py:685-718`, `SoulSync:services/sync_service.py:1187-1245`,
`SoulSync:core/watchlist_scanner.py:3036`, `SoulSync:core/wishlist/routes.py:790`,
`SoulSync:core/lidarr_compat/service.py:371-396`, `SoulSync:core/downloads/wishlist_failed.py:47`,
`SoulSync:core/wishlist/processing.py:1052`, `SoulSync:core/wishlist/retry_backoff.py:221`,
`SoulSync:core/wishlist/processing.py:163`, `SoulSync:core/wishlist/processing.py:278-279`,
`SoulSync:core/downloads/master.py:645-651`, `SoulSync:api/request.py:306`.

### Spotify

- **Auth flow: authorization code, user's own app.** `core/spotify_client.py` builds spotipy's `SpotifyOAuth` from
  `spotify.client_id`, `spotify.client_secret` and `spotify.redirect_uri` in settings
  (`SoulSync:core/spotify_client.py:800-819`); with no id or secret it logs "Spotify credentials not configured" and
  stops (`SoulSync:core/spotify_client.py:802-804`). The settings defaults are empty strings with redirect
  `http://127.0.0.1:8888/callback` (`SoulSync:core/settings.py:497-501`); the README tells the user to create an app
  on the developer dashboard and paste its id and secret (`SoulSync:README.md:444-446`). `SpotifyClientCredentials`
  is imported but never constructed (`SoulSync:core/spotify_client.py:2`), and the only PKCE flow in the repo is
  Tidal's (`SoulSync:web_server.py:1344`). No embedded client id was found (01-map, "Embedded API credentials").
  Each profile may bring its own app, falling back to the global one (`SoulSync:web_server.py:5483-5508`).
- **Scopes** are read-only: library, private and collaborative playlists, email, followed artists
  (`SoulSync:core/spotify_client.py:29-32`); playlist-modify is asked only by a separate export login, because
  widening the base scope invalidates every cached token (`SoulSync:core/spotify_client.py:23-27`).
- **What it reads** with the user token: own playlists (`SoulSync:core/spotify_client.py:1136-1170`), saved tracks
  (`SoulSync:core/spotify_client.py:1383-1420`), saved albums incrementally (`SoulSync:core/spotify_client.py:1426-1448`),
  one playlist with "Liked Songs" as a virtual playlist (`SoulSync:core/spotify_client.py:1575-1643`), followed artists
  (`SoulSync:core/spotify_client.py:1645-1693`).
- **Throttle and bans.** At least 350 ms between calls (`SoulSync:core/spotify_client.py:90`, configurable at `SoulSync:core/spotify_client.py:109-118`); spotipy runs with
  `retries=0` so it never sleeps through an hours-long Retry-After (`SoulSync:core/spotify_client.py:823-826`). A
  Retry-After over 60 s sets a process-wide ban and raises; exhausted retries ban for 4 h
  (`SoulSync:core/spotify_client.py:375-461`); repeats within an hour double the ban up to 4 h, then a 30 min cooldown
  (`SoulSync:core/spotify_client.py:122-184`). While banned, `is_spotify_authenticated()` is false and callers fall
  back to iTunes/Deezer/free sources (`SoulSync:core/spotify_client.py:886-902`).
- **Token cache.** `core/spotify_token_cache.py` stores spotipy's whole `token_info` (access, refresh, `expires_at`)
  under the config key `spotify.token_info` in the database-backed config store
  (`SoulSync:core/spotify_token_cache.py:29-46`), importing the old `config/.spotify_cache` file once because the
  Docker volume lost it on nightly pulls (`SoulSync:core/spotify_token_cache.py:3-9`). The config store is the
  Fernet-encrypted one in 01-map ("Settings and credentials"). Refresh itself is spotipy's (*unverified*: inside
  spotipy). Per-profile tokens still use loose files (`SoulSync:web_server.py:5506`).
- **Without credentials, two mechanisms.**
  1. `core/spotify_public_scraper.py` GETs `https://open.spotify.com/embed/{playlist|album}/{id}` with a browser
     User-Agent (`SoulSync:core/spotify_public_scraper.py:72-80`) and reads `__NEXT_DATA__` →
     `props.pageProps.state.data.entity.trackList` (`SoulSync:core/spotify_public_scraper.py:94-145`); about 100
     tracks at most (`SoulSync:core/spotify_public_scraper.py:181-182`). This is the same page and the same JSON path
     our `spotify_csv` reads (ours:sourcing/spotify_csv.py:27-40).
  2. `core/spotify_public_api.py` uses the third-party **SpotipyFree** client with no credentials, paging
     `playlist_items` (`SoulSync:core/spotify_public_api.py:56-95`) up to 10,000 tracks (`SoulSync:core/spotify_public_api.py:29`). Its docstring says it talks to
     "Spotify's private API the way the web player does", tracking client-auth headers Spotify rotates
     (`SoulSync:core/spotify_public_api.py:4-9`). The token and GraphQL hosts live inside that library, not in this
     repo (a grep for `api-partner|pathfinder|clienttoken` over `core/` and `api/` is empty; the hosts are
     *unverified*). `fetch_spotify_public` tries SpotipyFree first for playlists and falls back to the embed; albums
     always use the embed (`SoulSync:core/spotify_public_scraper.py:177-202`).
- **`core/spotify_free_metadata.py`** is a "PROTOTYPE" read-only metadata source over SpotipyFree / spotapi
  ("web-player scraping — best-effort, fragile") for search, album, artist and track lookups
  (`SoulSync:core/spotify_free_metadata.py:1-22`). It is used when the user opted in and the official API is
  unauthenticated, banned or over budget (`SoulSync:core/spotify_free_metadata.py:70-80`,
  `SoulSync:core/spotify_client.py:93-107`); the enrichment worker uses it by default to save the official quota
  (`SoulSync:core/spotify_worker.py:245-261`). `spotipyFree` (GPL-3.0) is listed in requirements but
  soft-imported, "never a hard runtime requirement": without it the embed scraper is used
  (`SoulSync:requirements.txt:88-96`). 01-map calls it a hard dependency; V2-08 reconciles the two.
- **The February 2026 developer-mode limits.**
  - Playlist items: the client calls the new `playlists/{id}/items` first, because `/tracks` "returns 403 for
    Development Mode apps after the Feb 2026 API changes", and falls back to `/tracks` on 403/404
    (`SoulSync:core/spotify_client.py:1510-1530`); items are read as `item.track or item.item`
    (`SoulSync:core/spotify_client.py:1547-1548`).
  - A followed (not owned) playlist: on the background path (`get_playlist_by_id`, used by sync and mirror refresh)
    a 403 logs "Spotify only serves the items of playlists you own or collaborate on … Copy it into a playlist of
    your own" and returns nothing (`SoulSync:core/spotify_client.py:1599-1607`); a refresh keeps the stored tracks
    (`SoulSync:tests/automation/test_handlers_playlist.py:373-376`). On the UI path
    (`GET /api/spotify/playlist/<id>`) it falls back to `fetch_spotify_public` and marks the result
    `incomplete` (`SoulSync:web_server.py:19959-20007`).
  - "Premium required for the owner of the app" 403s are detected (`SoulSync:core/spotify_client.py:366-372`) and
    sent to the public path for playlists (`SoulSync:web_server.py:19940-19957`) and to SpotipyFree for artists
    (`SoulSync:core/spotify_client.py:2353-2365`).
  - Search max limit 50 → 10 cut the enrichment worker's daily budget from 3,000 to 500 items
    (`SoulSync:core/spotify_worker.py:88-94`).
  - Not handled: `audio_features` (`SoulSync:core/spotify_client.py:2046`) and related-artists
    (`SoulSync:core/personalized_playlists.py:1013-1016`) are still called, their errors only caught; nothing about
    the 5-user allowlist was found (grep for `allowlist|5 users|user management`, *absence inferred*).
- **Into the wanted flow.** The UI fetches a playlist (`SoulSync:web_server.py:19872-19873`) and posts its tracks to
  `POST /api/sync/start` → `start_playlist_sync_from_payload` → `sync_executor.submit(_run_sync_task, …)`
  (`SoulSync:api/source_playlists.py:5387-5462`); `run_sync_task` turns the JSON into `SpotifyTrack` objects and calls
  `sync_service.sync_playlist` (`SoulSync:core/discovery/sync.py:393`, `SoulSync:core/discovery/sync.py:684`). Public
  links have their own `/api/spotify-public/sync/start/<url_hash>` (`SoulSync:api/source_playlists.py:3704`).
  `core/spotify_worker.py` is not an intake: it enriches the existing library with Spotify ids
  (`SoulSync:core/spotify_worker.py:35-43`).

### Other playlist sources

All sources implement one `PlaylistSource` adapter (`is_authenticated`, `list_playlists`, `get_playlist`,
`refresh_playlist`; `SoulSync:core/playlists/sources/base.py:118-167`) returning `NormalizedTrack` (position, track
and artist and album name, `duration_ms`, `source_track_id`, `needs_discovery`, `extra`;
`SoulSync:core/playlists/sources/base.py:64-115`). `build_playlist_source_registry` wires twelve source keys
(`SoulSync:core/playlists/sources/base.py:35-61`, `SoulSync:core/playlists/sources/bootstrap.py:46-116`).

**Tidal.** OAuth PKCE with scope `user.read playlists.read collection.read` (`SoulSync:core/tidal_client.py:316-341`),
client id and secret from the `tidal` settings section (`SoulSync:core/tidal_client.py:206-216`). Playlists come from
the openapi v2 JSON:API `GET /playlists/{id}` and cursor-paged `/relationships/items`
(`SoulSync:core/tidal_client.py:1488-1525`, `SoulSync:core/tidal_client.py:1665-1677`); per track: id, name, artists,
album, `duration_ms`, popularity, explicit (`SoulSync:core/tidal_client.py:103-112`), of which the adapter keeps the
first artist only (`SoulSync:core/playlists/sources/tidal.py:88-106`). No Tidal paste-a-link parser exists (grep,
*absence inferred*).

**Deezer.** Public playlists need no login (`SoulSync:core/playlists/sources/deezer.py:1-7`):
`api.deezer.com/playlist/{id}` paged 400 at a time, plus one request per album for real track numbers
(`SoulSync:core/deezer_client.py:1864-1940`); per track id, name, one artist, album, cover, `duration_ms`,
`track_number` (`SoulSync:core/deezer_client.py:1943-1962`). The user's own playlist list comes only through the
ARL-cookie download client (`SoulSync:core/deezer_download_client.py:474-518`). It has the best link parsing:
`deezer.com/[xx/]playlist/<n>`, a bare number, and `link.deezer.com` / `deezer.page.link` share links resolved by a
HEAD redirect (`SoulSync:core/deezer_client.py:1982-2068`), behind `GET /api/deezer/playlist/<id-or-url>`
(`SoulSync:api/source_playlists.py:2528-2545`).

**YouTube Music.** Two adapters. `ytmusic` reads the user's library with ytmusicapi and browser cookies from settings
(`SoulSync:core/playlists/sources/ytmusic.py:1-5`, `SoulSync:core/ytmusic_library.py:111-130`). `youtube` takes a
pasted `youtube.com/playlist` or `music.youtube.com/playlist` URL (`SoulSync:api/source_playlists.py:4216-4246`),
tries the ytmusicapi catalog, then yt-dlp flat extraction (`SoulSync:web_server.py:14656-14698`). Tracks carry the
video id, name, first artist and length; album only from the catalog path
(`SoulSync:core/playlists/sources/youtube.py:71-90`).

**Beatport.** Scraping, not an API: the page's `__NEXT_DATA__` through a Cloudflare/FlareSolverr-capable scraper
(`SoulSync:core/beatport/fetch.py:40-76`, `SoulSync:core/beatport/next_data.py:1-8`). A "ref" names the list (top-10,
hype-100, a genre list, a chart, a release; `SoulSync:core/beatport/refs.py:1-15`); charts and genre lists refresh,
releases never do (`SoulSync:core/beatport/refs.py:76-79`). Tracks carry mix name, remixers, label, BPM, key and
**ISRC** (`SoulSync:core/beatport/next_data.py:175-232`), though the adapter maps only title, artists, release, length
and id (`SoulSync:core/playlists/sources/beatport.py:88-103`).

**ListenBrainz.** User token from settings sent as `Authorization: Token` (`SoulSync:core/listenbrainz_client.py:27`,
`SoulSync:core/listenbrainz_client.py:178-179`); created-for, user and collaborative playlists
(`SoulSync:core/playlists/sources/listenbrainz.py:43-46`), first cached into its own tables by
`ListenBrainzManager` (`SoulSync:core/listenbrainz_manager.py:27-62`). Tracks have recording MBIDs but are still
marked `needs_discovery` (`SoulSync:core/playlists/sources/listenbrainz.py:345-360`). Last.fm "radio" and pasted
Apple Music / iTunes links are two more sources (`SoulSync:core/playlists/sources/lastfm.py:1-11`,
`SoulSync:api/source_playlists.py:3730`), and Qobuz is a registered source too
(`SoulSync:core/playlists/sources/bootstrap.py:74`; not read further here).

**What a mirrored playlist is.** A local copy of a source playlist: `mirrored_playlists` (source,
`source_playlist_id`, name, owner, `profile_id`, `quality_profile_id`, `is_request_list`, `auto_remove_fulfilled`,
unique on source + id + profile; `SoulSync:database/music_database.py:1384-1403`) and `mirrored_playlist_tracks`
(position, names, `duration_ms`, `source_track_id`, `extra_data` JSON;
`SoulSync:database/music_database.py:1404-1419`). Migrations add `sync_mode`, `custom_name` and the linked server
playlist id (`SoulSync:database/music_database.py:2834-2889`). `mirror_playlist` upserts the row and rewrites every
track, carrying each surviving track's `extra_data` (its discovery match) across
(`SoulSync:database/music_database.py:25245-25296`), and refuses a payload whose tracks are all blank
(`SoulSync:database/music_database.py:25165-25179`); a failed Spotify fetch raises rather than coming back as an
empty playlist that would wipe the mirror (`SoulSync:core/spotify_client.py:1594-1596`). The browser creates a mirror by POSTing the fetched playlist to
`/api/mirror-playlist` (`SoulSync:web_server.py:21179-21269`). `api/mirrored_playlists.py` lists, renames, links to a
server playlist, re-points the source (`SoulSync:api/mirrored_playlists.py:251-265`) and runs the pipeline. There is
no single paste-any-link endpoint; each source has its own parser route (`SoulSync:api/source_playlists.py:3482`,
`SoulSync:api/source_playlists.py:3730`, `SoulSync:api/beatport.py:858`).

**How often sync runs.** No built-in schedule refreshes mirrors: `SYSTEM_AUTOMATIONS` has no refresh or pipeline
entry (`SoulSync:core/automation_engine.py:77-248`; grep for the action names, *absence inferred*). The user builds an
automation from blocks "Refresh Mirrored Playlist", "Sync Playlist" or "Playlist Pipeline" (refresh → identify →
sync → download; `SoulSync:core/automation/blocks.py:353-379`), whose schedule trigger defaults to every 6 h
(`SoulSync:core/automation/blocks.py:38-44`), or presses Run (`SoulSync:api/mirrored_playlists.py:677-699`). After
downloads a built-in chain rescans and re-syncs playlists (`SoulSync:core/automation_engine.py:139-157`,
`SoulSync:core/sync/post_download_sync.py:1-8`).

**What a sync writes** (`core/playlists/pipeline.py`, `core/sync/`, `services/sync_service.py`):
1. refresh: `auto_refresh_mirrored` → `adapter.refresh_playlist` → `mirror_playlist`, emitting `playlist_changed`
   when the id set changed (`SoulSync:core/automation/handlers/refresh_mirrored.py:277-351`);
2. identify: `run_playlist_discovery_worker` matches tracks to Spotify (preferred) or iTunes and stores the match in
   `extra_data`; a miss becomes a "Wing It" stub (`SoulSync:core/discovery/playlist.py:1-24`);
3. skip if unchanged: an MD5 fingerprint of the ids, quality profile and sync mode, kept in the `sync_statuses`
   preference, plus a check that the matched files still exist (`SoulSync:core/automation/handlers/sync_playlist.py:378-452`,
   `SoulSync:core/sync/sync_fingerprint.py:9`, `SoulSync:core/sync/library_presence.py:1-7`);
4. have vs missing: `_find_track_in_media_server` per track at a 0.7 threshold
   (`SoulSync:services/sync_service.py:685-718`);
5. server playlist: matched tracks written to Plex, Jellyfin/Emby or Navidrome in `reconcile` (the automation
   default), `append` or `replace` mode (`SoulSync:services/sync_service.py:921-944`,
   `SoulSync:core/automation/handlers/sync_playlist.py:403`), the server playlist id remembered
   (`SoulSync:core/sync/mirrored_server_link.py:1-24`);
6. missing: `_wishlist_unmatched` → `add_spotify_track_to_wishlist(source_type='playlist')`
   (`SoulSync:services/sync_service.py:1187-1245`), then the wishlist phase
   (`SoulSync:core/automation/handlers/_pipeline_shared.py:232-267`).

### Wishlist and watchlist

**Wishlist.** Columns: `spotify_track_id` (any provider's id), `spotify_data` (the whole track as JSON),
`failure_reason`, `retry_count`, `last_attempted`, `source_type`, `source_info`
(`SoulSync:database/music_database.py:807-817`), later `profile_id` with `UNIQUE(profile_id, spotify_track_id)`
(`SoulSync:database/music_database.py:5999-6010`) and `request_status` (`SoulSync:database/music_database.py:27476-27478`).
What enters: missing playlist tracks (above); permanently failed downloads (`SoulSync:core/downloads/wishlist_failed.py:47`);
watchlist finds; album, discography and quality-upgrade clicks (`SoulSync:api/wishlist_routes.py:605`,
`SoulSync:api/artist_detail.py:2451-2454`, `SoulSync:core/artists/quality.py:476-479`); discography backfill repair
(`SoulSync:core/repair_jobs/discography_backfill.py:548-551`); `POST /api/v1/wishlist` with an API key
(`SoulSync:api/wishlist.py:88-97`). The add path skips blocklisted ids, a 30-day ignore list of removed or cancelled
tracks, tracks the user manually matched to a library file, and adds over a request quota (`SoulSync:database/music_database.py:15563-15597`,
`SoulSync:core/wishlist/ignore.py:30`).
**Retry cadence:** "Auto-Process Wishlist" every 30 min, first run 60 s after start
(`SoulSync:core/automation_engine.py:78-83`), alternating album and single batches
(`SoulSync:core/wishlist/processing.py:1228-1240`). A failure bumps `retry_count`
(`SoulSync:database/music_database.py:16814-16819`); scheduled runs back off by attempts (0-1 none, 2 → 4 h, 3 → 24 h,
4+ → 7 d) and "tracks never auto-abandon" (`SoulSync:core/wishlist/retry_backoff.py:7-17`). Each run first drops rows
already in the library (`SoulSync:core/wishlist/processing.py:1128-1139`), then groups the rest into album batches and
one per-track batch and submits each to the download master (`SoulSync:core/wishlist/processing.py:211`,
`SoulSync:core/wishlist/processing.py:363-364`). A row is deleted once its file is published and not staged
(`SoulSync:core/wishlist/resolution.py:161-192`, `SoulSync:core/wishlist/removal_guard.py:20-25`), with an audit row
in `wishlist_removals` (`SoulSync:database/music_database.py:828-838`).

**Watchlist.** `watchlist_artists` holds one id per provider (Spotify, iTunes, Deezer, Discogs, MusicBrainz, Amazon)
and `last_scan_timestamp` (`SoulSync:database/music_database.py:1058-1071`), with per-artist flags: albums, EPs and
singles on; live, remix, acoustic, compilation, instrumental and other-artist off
(`SoulSync:database/music_database.py:4166-4194`); `auto_download` default 1
(`SoulSync:database/music_database.py:4215`). "Auto-Scan Watchlist" runs every 24 h
(`SoulSync:core/automation_engine.py:85-91`): the discography comes from the artist's preferred metadata source or
the global priority list, default order Deezer, iTunes, Spotify, Discogs, … MusicBrainz
(`SoulSync:core/watchlist_scanner.py:1255-1280`, `SoulSync:core/metadata/registry.py:21`), incremental from the last
scan (`SoulSync:core/watchlist_scanner.py:1782`). Release type is guessed from track count (7+ album, 4-6 EP, 1-3
single; `SoulSync:core/watchlist_scanner.py:2662-2694`). Each included track missing from the library is added
**track by track** to the wishlist when auto-download is on (`SoulSync:core/watchlist_scanner.py:1963-1981`,
`SoulSync:core/watchlist_scanner.py:3111-3114`); "follow only" artists surface releases without adding them
(`SoulSync:core/watchlist_scanner.py:1971-1975`). The
global auto-download default is on (`SoulSync:core/watchlist_auto_download.py:67-81`). Labels can be watched too,
through MusicBrainz (`SoulSync:core/automation/handlers/scan_watchlist_labels.py:106`).

### Requests

A request is **not** a separate record. A profile without download rights (`profiles.can_download`) keeps a wishlist
the scheduled run skips; each of its rows with no `request_status` is a pending request
(`SoulSync:core/requests/music.py:3-8`, `SoulSync:core/wishlist/processing.py:1078-1080`). Rows are grouped into an
**album** or a **track** request by `group_key`; there is no playlist kind (`SoulSync:core/requests/music.py:50-99`).
States: pending, approved, available, declined, removed (`SoulSync:core/requests/music.py:20`). Only an admin approves
(`POST /api/requests/music/approve`, 403 otherwise; `SoulSync:api/music_requests.py:247-266`), which sets
`request_status='approved'` on the rows (`SoulSync:database/music_database.py:27564-27585`); the next 30-minute run
downloads them. Decline removes and ignore-lists the rows (`SoulSync:api/music_requests.py:303-332`); a member may
withdraw (`SoulSync:api/music_requests.py:335-347`). A history row in `music_requests` keeps kind, title, artist,
tracks JSON, status, admin response and timestamps (`SoulSync:database/music_database.py:27480-27497`); "available" is
set lazily once every row has left the wishlist and the library has the tracks
(`SoulSync:core/requests/music.py:102-113`). Optional per-profile quotas (default unlimited;
`SoulSync:core/requests/quota.py:13-26`). There is no auto-approve setting (grep `auto_approve`, *absence inferred*);
a profile with `can_download=1`, the default, never makes requests at all
(`SoulSync:database/music_database.py:6533`). Members create requests with the ordinary search and add buttons; no
request-specific create endpoint exists (`SoulSync:api/music_requests.py:134-363`).

Separately, `api/request.py` is an API-key endpoint `POST /api/v1/request` taking a free-text `query` (plus optional
title, artist, length, `notify_url`) (`SoulSync:api/request.py:345-363`) that calls
`download_orchestrator.search_and_download_best` at once, with no wishlist row and no approval
(`SoulSync:api/request.py:287-306`); its records live in memory for an hour (`SoulSync:api/request.py:20-25`).

### Lidarr compatibility

`core/lidarr_compat/` makes SoulSync "pretend to be lidarr" so Lidarr-only request apps (Singarr, MusicSeerr 1.x) can
send album requests to it; a requested album lands on one configured profile's wishlist
(`SoulSync:core/lidarr_compat/__init__.py:1-10`). It is off by default and needs an admin API key
(`SoulSync:api/lidarr_compat.py:42-44`, `SoulSync:api/lidarr_compat.py:121-126`), serves `/lidarr/api/v1`
artist/album/command/lookup routes from MusicBrainz data (`SoulSync:api/lidarr_compat.py:25`,
`SoulSync:api/lidarr_compat.py:152-369`), and an `AlbumSearch` command fetches the MusicBrainz tracklist and queues
each track with `queue_album_tracks` (`SoulSync:core/lidarr_compat/service.py:371-396`,
`SoulSync:api/lidarr_compat.py:77-79`, `SoulSync:core/wishlist/album_request.py:14-37`). If the target profile cannot download, the album goes through the
admin approval above (`SoulSync:api/lidarr_compat.py:49-61`).

**Discovery, briefly.** Discovery surfaces (inbox, stations) do not add to the wishlist by themselves
(`SoulSync:core/discovery/inbox.py:14-17`); Wing It guesses do only when `wishlist.wing_it_guesses` is set, default off
(`SoulSync:core/discovery/wing_it.py:72-89`); a discovery playlist the user
syncs goes through the same `_wishlist_unmatched` path (`SoulSync:services/sync_service.py:1187`) and then starts the
wishlist run (`SoulSync:core/discovery/sync.py:59`, `SoulSync:core/discovery/sync.py:133`).

## How ours does it

- **Sources: Spotify only, three shapes, one `Row`.** `sourcing/playlist_sources.py` reads a public Spotify playlist
  or album URL (the embed page, 100-track cap), an Exportify CSV for private or long playlists, or a SpotiFLAC report
  (ours:sourcing/playlist_sources.py:1-14) into `Row(position, title, artist, duration_s, spotify_id, album, isrc…)`
  (ours:sourcing/playlist_sources.py:29-38); `load` dispatches on URL or file suffix
  (ours:sourcing/playlist_sources.py:123-131). The URL path is `sourcing/spotify_csv.py`: the embed's
  `__NEXT_DATA__`, no credentials (ours:sourcing/spotify_csv.py:1-6, ours:sourcing/spotify_csv.py:27-40), accepting
  `open.spotify.com/(playlist|album)/<id>` (ours:sourcing/spotify_csv.py:24). No Spotify app, no OAuth, no other
  service.
- **`import-playlist`** (ours:sourcing/cli.py:155-160) runs `import_playlist`
  (ours:sourcing/import_playlist.py:263-282): each row is matched against Navidrome by search3 + `sourcing.identity`
  (ISRC, then same version, then an accepted other version; ours:sourcing/import_playlist.py:1-21); matched songs
  go into a public Navidrome playlist in Spotify order, appended only, never removed
  (ours:sourcing/import_playlist.py:300-304); every other row becomes an `external_wanted` row that remembers the
  playlist and position (ours:sourcing/import_playlist.py:355-357), and ambiguous ones are parked as `review`
  (ours:sourcing/import_playlist.py:358-359); the whole order is recorded for later placement
  (ours:sourcing/import_playlist.py:360-362).
- **`seed-spotify`** (ours:sourcing/cli.py:151-153, ours:sourcing/cli.py:226-240) queues every track of a public
  Spotify playlist or album as an `external_wanted` row with no playlist and no matching; re-seeding is a no-op.
- **The wanted record** is `crates.db` `external_wanted`: artist, title, album, year, duration, source URL, status
  (`needs_source` → `sourcing` → `verify` → `ok`/`failed`/`review`), playlist id + position, tier, the names first
  asked for, the filed song (ours:crates/store.py:63-76). `add_external_wanted` dedupes by artist/title; for an import it
  re-asks a failed row instead of queuing a second, while `seed-spotify` re-queues a failed row as a new one
  (ours:crates/store.py:668-686). Tracks of a crate playlist that are not
  playable live in `crate_tracks` with the same statuses (ours:crates/store.py:47-58).
- **Approval and queue.** Nothing downloads without a record in `approvals` (D23; ours:crates/store.py:105-108,
  ours:docs/specs/2026-10-13-next-session-design.md:77); the web client lists wanted rows and offers preview,
  approve and play-now (ours:crates/service.py:439-441, ours:crates/service.py:478-481, ours:web/app.js:313,
  ours:web/app.js:355). The worker spends approvals and places a filed track at its Spotify position
  (ours:sourcing/worker.py:26).
- **No schedule, no watchlist, no member requests.** An import or seed is a CLI run by Michael; nothing re-reads a
  Spotify playlist on a timer and nothing watches artists (no such code in `sourcing/` or `crates/`; *absence
  inferred* from `grep -rn -iE 'schedule|watchlist' sourcing crates`). One user (CLAUDE.md), so no profiles.
- **Planned (S2/S3, not built on this base).**
  - S2-01 adds a `requests` table (kind `album|playlist|track`, source, artist, album, year, `mb_release_id`) and
    `request_id`, `track_no`, `mb_recording_id` on `external_wanted`; a request's status is derived from its rows
    (ours:docs/specs/2026-10-22-downloads-and-requests.md:103-108).
  - S2-02: a Spotify album URL fills `album`, `track_no` and `year` on every row
    (ours:docs/specs/2026-10-22-downloads-and-requests.md:109-111).
  - S2-07: a playlist request is the import plus one approval for all open rows; rows sharing artist and album (3+)
    are sourced as an album job (ours:docs/specs/2026-10-22-downloads-and-requests.md:183-186).
  - S3-01 `POST /api/requests {"url"}` for a Spotify track, album or playlist; S3-02 a catalog search over
    MusicBrainz behind a provider interface, Spotify next "using Michael's own developer app"; S3-03 preview/approve
    per request; S3-06 a Client Credentials capture script for his app
    (ours:docs/specs/2026-10-22-downloads-and-requests.md:188-221). Other platforms' links and embedded credentials
    are out on purpose (ours:docs/specs/2026-10-22-downloads-and-requests.md:233-234).

## The difference that matters

**Goal C, requests from the phone, Spotify only through Michael's own app.**
- SoulSync's Spotify login is the shape C asks for: authorization code with the user's own developer app, no embedded
  client id (`SoulSync:core/spotify_client.py:800-819`). Ours has no login at all today; S3-06 plans Client
  Credentials (ours:docs/specs/2026-10-22-downloads-and-requests.md:215-221), which can search and read albums but
  cannot read his private playlists or Liked Songs; that needs the authorization-code flow SoulSync uses.
- SoulSync's code already met the 2026 limits: `/items` before `/tracks`, a clear "copy it into your own playlist"
  for followed playlists, Premium-owner 403 detection (`SoulSync:core/spotify_client.py:1510-1530`,
  `SoulSync:core/spotify_client.py:1599-1607`, `SoulSync:core/spotify_client.py:366-372`). That is the knowledge S3's
  "Spotify next" needs, and it is cheaper to read than to rediscover.
- Its fallback, though, is SpotipyFree, a GPL client that imitates the web player's rotating auth headers
  (`SoulSync:core/spotify_public_api.py:4-9`). That is the "never embedded credentials" C rules out in spirit, and the
  downloads spec rules it out explicitly (ours:docs/specs/2026-10-22-downloads-and-requests.md:234). The embed scrape
  both projects use is the 100-track public page, not a credential.
- From the phone: SoulSync has no single paste-a-link endpoint; each source has its own route and the browser
  orchestrates fetch → mirror → sync. Its one-call API (`POST /api/v1/request`) takes a query (optionally title,
  artist and length the result must match, `SoulSync:api/request.py:345-363`) and downloads the best hit at once,
  with no approval (`SoulSync:api/request.py:287-306`), which breaks D7. S3-01's
  `POST /api/requests {"url"}` with preview/approve is the better shape for an iOS Shortcut; SoulSync's Deezer
  share-link resolution (`SoulSync:core/deezer_client.py:2030-2068`) shows what "share a link" really receives
  (short redirect links), worth handling for Spotify's `spotify.link` too (*unverified* that Spotify shares such
  links to the share sheet; check from the phone).
- Its member/admin approval is close to ours in spirit (nothing downloads until approved) but per profile, not per
  download, and approval means "the 30-minute job may try it", with automatic retries forever
  (`SoulSync:core/wishlist/retry_backoff.py:7-17`). Ours approves one download (D23); a retry needs a new approval.

**Goal D, whole albums and whole playlists at once.**
- SoulSync has both today: a playlist sync wishlists every missing track in one go, and an album click queues each
  track (`SoulSync:api/wishlist_routes.py:605-606`, `SoulSync:core/wishlist/routes.py:790`); the wishlist run then submits album batches
  (`SoulSync:core/wishlist/processing.py:211`). But the album identity is lost at intake: a wishlist row is one track
  keyed by a provider track id with the album only inside `spotify_data` JSON
  (`SoulSync:database/music_database.py:807-817`), and a request is grouped back into an album only for display
  (`SoulSync:core/requests/music.py:50-99`). Ours plans the album as a first-class record (S2-01 `requests`,
  `track_no`, `mb_release_id`) so S2-04/05 can source one folder; SoulSync's shape is the one that produced our
  10-21 "5 peers, 4 releases" outcome, and whether its batches pin one folder is V2-03a's question.
- Mirrors that refresh on a schedule and auto-wishlist whatever is new are the opposite of D7 for us; the
  fingerprint skip and "keep stored tracks on a failed refresh" rules (`SoulSync:core/automation/handlers/sync_playlist.py:378-452`,
  `SoulSync:tests/automation/test_handlers_playlist.py:373-376`) are worth having for any re-import, with approval
  kept manual.
- Reconcile mode writes the server playlist from the source, so a track Michael removed in Navidrome comes back on the
  next sync (*unverified*: depends on `reconcile_playlist`'s rules, V2-06 reads it). Ours never removes and never
  re-adds a removed track (D13, ours:docs/specs/2026-10-13-next-session-design.md:66; ours:sourcing/import_playlist.py:302), which crates need.

**Crates.** SoulSync keeps one wanted row per track id per profile, without playlist position
(`SoulSync:database/music_database.py:5999-6010`); ours remembers playlist and position on the wanted row
(ours:crates/store.py:69) so a filed track lands at its Spotify place. The other sources (Beatport charts with BPM,
key and ISRC; Deezer; ListenBrainz) are reachable for a DJ but none is asked for in the goals.

## Worth taking?

- **Take (as knowledge):** the 2026 Spotify rules in code form (`/items` first, followed-playlist 403 message,
  Premium-owner detection, 350 ms throttle, Retry-After bans that stop all calls instead of sleeping) for S3's Spotify
  provider, plus the authorization-code flow with Michael's own app so his private playlists are reachable, which
  Client Credentials alone cannot do.
- **Adapt:** the source-adapter interface (one normalized track shape, `refresh_playlist`) matches S3-02's planned
  provider interface; Deezer's share-link redirect resolution; the "a failed fetch never empties a stored playlist"
  and fingerprint-skip guards for a future re-import.
- **Don't take:** SpotipyFree or any web-player imitation (GPL-3.0 and the embedded-credential problem); the
  download-now API without approval; scheduled mirror refresh that auto-wishlists and auto-retries without approval; the
  track-only wishlist row that drops album identity.

**Verdict:** adapt. SoulSync's intake is broader than ours (twelve source keys, watchlist, members, Lidarr shim), but for
goals C and D the parts worth having are its Spotify handling and adapter shape; its wanted record and its
approve-once-retry-forever queue are weaker than the planned S2-01/S3 for album-first sourcing under D7.
