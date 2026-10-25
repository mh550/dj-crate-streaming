# 01 · Map: what SoulSync is

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed).
Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a claim
without one. Counts come from `wc -l`, `grep -c` and `find … | wc -l` run on the clone on 2026-10-22.

## What SoulSync does

One Python 3.11 container (`SoulSync:Dockerfile:43`) running one Flask + Flask-SocketIO app
(`SoulSync:web_server.py:285`, `SoulSync:web_server.py:495`) under gunicorn with a single worker process
(`SoulSync:gunicorn.conf.py:4-5`). That one process holds the HTTP API, the web UI, every background worker, the
scheduler and the download pipeline; state lives in one SQLite file, `music_library.db`, which also stores the
configuration and the encrypted credentials. It covers music, music videos, video/TV, audiobooks and podcasts (the system automations alone span all five,
`SoulSync:core/automation_engine.py:77`); this
report reads only the music side. Size: 970 `.py` files and 428,883 lines of Python outside `tests/`
(`find . -name '*.py' -not -path './tests/*'`), plus a React 19 front end in `webui/src/` (1,321 files, about
350k lines of TypeScript, `SoulSync:webui/package.json:25`). The two largest Python files are
`web_server.py` (24,916 lines) and `database/music_database.py` (28,019).

The sections below follow the V1-01 brief (process model, data stores, settings and credentials, deployment, tests and
CI, module map, license, maintenance health); the comparison with ours comes after them.

## Process model

```
 browser (React app + legacy index.html) ─┬─ HTTP  ─▶ gunicorn :8008, 1 process, gthread × 8
 phone / API client                        └─ Socket.IO (threading mode)      │
                                                                              ▼
                     web_server.py: Flask app + 43 api/ blueprints ─── module import builds clients,
                          │                                                 executors and workers
                          │ start_runtime_services() (once per process)
                          ├─ AutomationEngine: threading.Timer per automation, emit() → thread per event
                          ├─ daemon threads: download monitor, auto-import, repair, MusicBrainz/Spotify/…
                          │  enrichment workers, simple background monitor, gc sweeper
                          ├─ ThreadPoolExecutors: downloads, album bundles, post-processing, sync, …
                          └─ ~20 socketio background loops pushing status to the browser
                                                                              │
                                     slskd / torrent / usenet / streaming APIs │  SQLite (WAL)
                                                                              ▼
                              /app/data/music_library.db  (+ video_library.db, audiobooks.db: skipped)
```

- **Server.** `gunicorn.conf.py` binds `0.0.0.0:8008`, `worker_class = "gthread"`, `workers = 1`, `threads = 8`
  (`SoulSync:gunicorn.conf.py:3-6`), request timeout 120 s (`SoulSync:gunicorn.conf.py:9`). The image's `CMD` is
  `gunicorn -c gunicorn.conf.py wsgi:application` (`SoulSync:Dockerfile:168`). `wsgi.py` imports `app` and
  `start_runtime_services` from `web_server` and calls the latter at import (`SoulSync:wsgi.py:3-8`). Running
  `web_server.py` directly instead uses `socketio.run(..., allow_unsafe_werkzeug=True)`
  (`SoulSync:web_server.py:24915-24916`), the dev path.
- **App creation.** `app = Flask(...)` with `template_folder=webui` and `static_folder=webui/static`
  (`SoulSync:web_server.py:285-288`); `socketio = SocketIO(app, async_mode='threading', ...)`
  (`SoulSync:web_server.py:495`). Most routes are blueprints in `api/` registered from `web_server.py`, e.g. the
  auto-import blueprint at `SoulSync:web_server.py:23511-23513`.
- **Built at module import** (so in every process that imports `web_server`): the clients
  (`SoulSync:web_server.py:1176`, `DownloadOrchestrator()` at `SoulSync:web_server.py:1243`, `MediaServerEngine` at
  `SoulSync:web_server.py:1214`); the thread pools `StreamPrep` (4), `SyncWorker` (3), `DBUpdate` (1),
  `MissingTrackWorker` (configurable), `AlbumBundleWorker` (3), `PostProcessWorker` (3), `ImportSingleWorker` (3)
  (`SoulSync:web_server.py:1318`, `SoulSync:web_server.py:1352`, `SoulSync:web_server.py:1358`,
  `SoulSync:web_server.py:1432`, `SoulSync:web_server.py:1442`, `SoulSync:web_server.py:1455`,
  `SoulSync:web_server.py:1464`); `AutomationEngine(get_database())` (`SoulSync:web_server.py:1528`);
  `WebUIDownloadMonitor()` (`SoulSync:web_server.py:2393`); and three workers constructed **and started** in
  module-level `try` blocks: `MusicBrainzWorker` (`SoulSync:web_server.py:21646-21653`), the Spotify enrichment
  `SpotifyWorker` (`SoulSync:web_server.py:21834-21841`) and `RepairWorker` (`SoulSync:web_server.py:22528-22599`).
  The code itself names the hazard for one timer it moved out of import: it "started the 30s loop in every importer —
  tests, workers, CLI tools" (`SoulSync:web_server.py:24650-24653`).
- **`start_runtime_services()`** (`SoulSync:web_server.py:24629`, guarded by a lock and a started flag): OAuth
  callback servers for Spotify/Tidal (`SoulSync:web_server.py:24648`, defined at `SoulSync:web_server.py:21379`); the
  batch-healing timer (`SoulSync:web_server.py:24654`, `SoulSync:web_server.py:2697`); stuck-flag recovery (`SoulSync:web_server.py:24676`), a
  sweep of orphaned album-bundle staging (`SoulSync:web_server.py:24710`) and recovery of orphaned atomic-publish
  staging (`SoulSync:web_server.py:24735`); the simple background monitor thread (`SoulSync:web_server.py:24765`, thread at
  `SoulSync:web_server.py:15702-15706`, body `SoulSync:web_server.py:15668`); the import-suggestions cache
  (`SoulSync:web_server.py:24772`, `SoulSync:core/imports/staging.py:619`); a `gc-sweeper` thread
  (`SoulSync:web_server.py:24826`); `automation_engine.start()` (`SoulSync:web_server.py:24834`); and 21
  `socketio.start_background_task(_emit_*_loop)` status pushers (`SoulSync:web_server.py:24854-24887`).
- **Background worker classes** (each a `threading.Thread(daemon=True)` owner):
  - `AutoImportWorker` (`SoulSync:core/auto_import_worker.py:210`, thread at
    `SoulSync:core/auto_import_worker.py:437`), created and started from the import blueprint
    (`SoulSync:api/import_routes.py:356-365`);
  - `RepairWorker` (`SoulSync:core/repair_worker.py:393`, thread `SoulSync:core/repair_worker.py:813`);
  - `MusicBrainzWorker` (`SoulSync:core/musicbrainz_worker.py:25`, thread `SoulSync:core/musicbrainz_worker.py:64`);
  - `SpotifyWorker` (`SoulSync:core/spotify_worker.py:35`, thread `SoulSync:core/spotify_worker.py:107`);
  - `DownloadEngine` (`SoulSync:core/download_engine/engine.py:44`), which owns a `BackgroundDownloadWorker`
    (`SoulSync:core/download_engine/engine.py:93`, `SoulSync:core/download_engine/worker.py:58`) that spawns one
    thread per source download (`SoulSync:core/download_engine/worker.py:199`);
  - `WebUIDownloadMonitor` (`SoulSync:core/downloads/monitor.py:493`, loop thread
    `SoulSync:core/downloads/monitor.py:517`);
  - `WatchlistScanner` (`SoulSync:core/watchlist_scanner.py:689`, process singleton
    `SoulSync:core/watchlist_scanner.py:5339`);
  - per-provider enrichment workers of the same shape: `DeezerWorker` (`SoulSync:core/deezer_worker.py:33`),
    `TidalWorker` (`SoulSync:core/tidal_worker.py:39`), `iTunesWorker` (`SoulSync:core/itunes_worker.py:27`),
    `QobuzWorker` (`SoulSync:core/qobuz_worker.py:18`), `DiscogsWorker` (`SoulSync:core/discogs_worker.py:49`),
    `LastFMWorker` (`SoulSync:core/lastfm_worker.py:17`), `GeniusWorker` (`SoulSync:core/genius_worker.py:17`),
    `AudioDBWorker` (`SoulSync:core/audiodb_worker.py:16`), `AmazonWorker` (`SoulSync:core/amazon_worker.py:17`),
    `JioSaavnWorker` (`SoulSync:core/jiosaavn_worker.py:21`), `BandcampWorker` (`SoulSync:core/bandcamp_worker.py:16`),
    `SoulIDWorker` (`SoulSync:core/soulid_worker.py:66`), `SimilarArtistsWorker`
    (`SoulSync:core/similar_artists_worker.py:138`), `ListeningStatsWorker`
    (`SoulSync:core/listening_stats_worker.py:30`), `HydrabaseWorker` (`SoulSync:core/hydrabase_worker.py:21`).
  - `grep -rn 'threading\.Thread(' core --include=*.py`, excluding audiobook/podcast/video paths, finds 56 thread
    starts.
- **Scheduler: `AutomationEngine`** (`SoulSync:core/automation_engine.py:537`). One `threading.Timer` per scheduled
  automation, kept in `self._timers` (`SoulSync:core/automation_engine.py:540`, created at
  `SoulSync:core/automation_engine.py:1640`); trigger types `schedule`, `daily_time`, `weekly_time`, `monthly_time`
  (`SoulSync:core/automation_engine.py:576-581`). `start()` seeds the built-in "system automations", loads enabled rows
  from the `automations` table and schedules them (`SoulSync:core/automation_engine.py:993-1011`); event triggers go
  through `emit()`, which starts one thread per event (`SoulSync:core/automation_engine.py:1058-1067`). Music system
  automations: process wishlist every 30 min (`SoulSync:core/automation_engine.py:79`), scan watchlist every 24 h
  (`SoulSync:core/automation_engine.py:86`), library scan on `batch_complete`
  (`SoulSync:core/automation_engine.py:141-142`), database update on `library_scan_completed`
  (`SoulSync:core/automation_engine.py:147-148`), playlist sync after the update
  (`SoulSync:core/automation_engine.py:153`), clean completed downloads every 5 min
  (`SoulSync:core/automation_engine.py:191`), weekly deep scan (`SoulSync:core/automation_engine.py:219`), database
  backup every 3 days (`SoulSync:core/automation_engine.py:238`). Automations are rows in a table
  (`SoulSync:database/music_database.py:1426`), so the schedule is data, not code (user-editable from the Automations
  pages: *unverified*, V2-07 reads the routes).
- **Consequence.** Everything shares one address space: in-process locks, module globals and ~20 polling loops. That
  is why `workers = 1` is fixed: a second gunicorn worker would start a second set of threads and timers
  (*unverified*: inferred from the import-time starts above; no comment in `gunicorn.conf.py` says so). Peer speed
  memory, for one, is process-local with a one-hour TTL (`SoulSync:core/downloads/peer_observation.py:1`,
  `SoulSync:core/downloads/peer_observation.py:11-12`) and is lost on restart.

## Data stores

- **`music_library.db`** (SQLite). Path from `DATABASE_PATH`, default `database/music_library.db`
  (`SoulSync:database/music_database.py:430-431`, same rule in `SoulSync:core/settings.py:65-69`); the image sets
  `/app/data/music_library.db` (`SoulSync:Dockerfile:153`) on the named volume `soulsync_database`
  (`SoulSync:docker-compose.yml:119`). WAL mode (`SoulSync:database/music_database.py:515`); connections use a 30 s
  timeout (`SoulSync:database/music_database.py:512`); startup runs a read-only `PRAGMA quick_check`
  (`SoulSync:database/music_database.py:454-456`).
- **Schema management is in-process, at every boot**: `_initialize_database` (`SoulSync:database/music_database.py:584`)
  runs every `CREATE TABLE IF NOT EXISTS` plus additive migrations recorded in `schema_migrations`
  (`SoulSync:database/music_database.py:777`, `_record_migration` at `SoulSync:database/music_database.py:2073`).
  `grep -c 'ALTER TABLE' database/music_database.py` = 320; `tracks` alone gains 63 distinct columns that way, starting
  at `SoulSync:database/music_database.py:1770` (per-provider ids with `*_match_status`/`*_last_attempted`, `isrc`,
  `musicbrainz_recording_id`, `soul_id`, `play_count`, …).
- **The same file holds the configuration**: a key/value `metadata` table (`SoulSync:database/music_database.py:734`,
  also created by `SoulSync:core/settings.py:312`), row `app_config` (`SoulSync:core/settings.py:341`).
- **Other SQLite files**: `video_library.db` (`SoulSync:Dockerfile:158`) and `audiobooks.db`
  (`SoulSync:Dockerfile:161`, `SoulSync:core/audiobook_database.py:34`), both skipped; an image cache
  `image_cache.sqlite3` (`SoulSync:core/image_cache.py:140`).
- **`CREATE TABLE` count**: `grep -c 'CREATE TABLE' database/music_database.py` = **118** at `34bf7cf9c741`. Of
  those, 5 are comments (e.g. `SoulSync:database/music_database.py:1567`), 8 are one-row migration markers such as
  `_discovery_cache_v2_migrated` (`SoulSync:database/music_database.py:1803`), and 17 are `*_new` rebuild copies
  used by table-rewrite migrations (e.g. `tracks_new` at `SoulSync:database/music_database.py:3267`). That leaves 88
  statements; dropping `hifi_instances`, created twice (`SoulSync:database/music_database.py:1899`,
  `SoulSync:database/music_database.py:27707`), and `watchlist_podcasts_migrating`, a rebuild copy without the `_new`
  suffix (`SoulSync:database/music_database.py:1154`), leaves **86 distinct live table names** in this file. More tables live in other modules on the same database:
  `quality_profiles` (`SoulSync:core/quality/schema.py:62`), `personalized_playlists` / `_tracks` / `_track_history`
  (`SoulSync:database/personalized_schema.py:57`), `track_artist_credits` and `album_artist_credits` with `_pending`
  twins (`SoulSync:core/library/artist_credits.py:48`), `client_music_matches` (`SoulSync:core/client_match.py:218`),
  `lidarr_compat_artists` / `_albums` (`SoulSync:core/lidarr_compat/store.py:19`), issue comment threads
  (`SoulSync:core/issues/thread_store.py:38`).

Music tables in `database/music_database.py`, by subsystem (line = its `CREATE TABLE`):

| Subsystem | Table(s): what each holds |
|---|---|
| Library | `artists` (`SoulSync:database/music_database.py:592`), `albums` (`SoulSync:database/music_database.py:605`), `tracks` (`SoulSync:database/music_database.py:622`): the mirror of the media server's library, with `file_path`, `bitrate`, `file_size`, `acquired_quality_json`, `retention_json` and the 63 added provider/identity columns. |
| Library | `track_credits` (`SoulSync:database/music_database.py:4438`): normalised credit names per track. `manual_metadata_files` (`SoulSync:database/music_database.py:2295`): files whose metadata the user locked. `manual_library_track_matches` (`SoulSync:database/music_database.py:9114`): a user's "this source track is that library track" overrides per profile. |
| Library | `library_history` (`SoulSync:database/music_database.py:1534`): log of downloads and server imports (title, quality, file_path, download_source). `library_issues` (`SoulSync:database/music_database.py:1508`): user-reported problems with an entity, with admin response. `curation_signals` (`SoulSync:database/music_database.py:753`): per server user favourite/rating/in-playlist flags. `listening_history` (`SoulSync:database/music_database.py:7452`): scrobble-style plays. |
| Library (DJ-adjacent) | `sample_analysis` (`SoulSync:database/music_database.py:646`): `bpm`, `onsets_json` per track, versioned by analyser. `sample_stash` (`SoulSync:database/music_database.py:661`), `sample_stems` (`SoulSync:database/music_database.py:698`), `sample_analysis_text` (`SoulSync:database/music_database.py:3189`): sample chops, stem separations, text analysis. |
| Library repair | `reorganize_queue` (`SoulSync:database/music_database.py:792`): queued album moves. `retag_groups` / `retag_tracks` (`SoulSync:database/music_database.py:5836`, `SoulSync:database/music_database.py:5851`): downloads grouped for the retag tool. `repair_findings` (`SoulSync:database/music_database.py:9015`), `repair_job_runs` (`SoulSync:database/music_database.py:9040`): repair-worker results and runs. `rematch_hints` (`SoulSync:database/music_database.py:1655`): staged files with content hash, ISRC and the intended track/album, plus `replace_track_id`. |
| Playlists / sync | `mirrored_playlists` (`SoulSync:database/music_database.py:1385`): a source playlist (Spotify, Tidal, …) copied locally, with `is_request_list` and `auto_remove_fulfilled`. `mirrored_playlist_tracks` (`SoulSync:database/music_database.py:1405`): its rows in order. `sync_history` (`SoulSync:database/music_database.py:1683`): one row per sync/download batch with per-track results. `sync_match_cache` (`SoulSync:database/music_database.py:3730`): source track → server track with confidence. `playlist_pipeline_run_history` (`SoulSync:database/music_database.py:1465`). `playlist_export_targets` (`SoulSync:database/music_database.py:3922`): mirrored playlist → target service playlist id. `listenbrainz_playlists` / `listenbrainz_tracks` (`SoulSync:database/music_database.py:3455`, `SoulSync:database/music_database.py:3470`). `spotify_library_cache` (`SoulSync:database/music_database.py:8881`): the user's saved Spotify albums. |
| Wishlist / watchlist | `wishlist_tracks` (`SoulSync:database/music_database.py:807`): wanted tracks keyed by `spotify_track_id` with `failure_reason`, `retry_count`, `source_type`. `wishlist_removals` (`SoulSync:database/music_database.py:828`): why and where a wanted row was fulfilled. `wishlist_ignore` (`SoulSync:database/music_database.py:867`). `watchlist_artists` (`SoulSync:database/music_database.py:1058`) and `watchlist_labels` (`SoulSync:database/music_database.py:1083`): followed artists/labels with per-provider ids and a quality profile. `watchlist_scan_runs` (`SoulSync:database/music_database.py:1604`). |
| Downloads / candidates / peers | `track_downloads` (`SoulSync:database/music_database.py:3764`): provenance of each file: `source_service`, `source_username` (the peer), `source_filename`, `source_size`, `audio_quality`. `download_decisions` (`SoulSync:database/music_database.py:3830`): the pick and its alternatives as JSON, `search_mode`, outcome: an audit trail of every choice. `auto_import_history` (`SoulSync:database/music_database.py:1622`): folder-level import attempts with confidence and match data. `torrent_seed_grabs` (`SoulSync:database/music_database.py:3873`). `hifi_instances` (`SoulSync:database/music_database.py:1899`): HiFi API endpoints. No peer table: peer observations are in memory (see Process model). |
| Requests | `music_requests` (`SoulSync:database/music_database.py:27480`): per-profile requests (`kind`, `title`, `artist`, `tracks`, `status`, `admin_response`, `available_at`, `seen_at`): an approval queue between non-admin profiles and the admin. |
| Quarantine / blocklist | `quarantine_source_blocks` (`SoulSync:database/music_database.py:911`): peer + filename blocked after a failed check, with the expected artist/track. `download_blacklist` (`SoulSync:database/music_database.py:3749`): per track, a blocked filename/peer. `failed_download_blocklist` (`SoulSync:database/music_database.py:4041`): fingerprint + service + size, with `expires_at`. `blocklist` (`SoulSync:database/music_database.py:3952`): artist/album/track entities a profile never wants. `discovery_artist_blacklist` (`SoulSync:database/music_database.py:3933`). |
| Metadata caches | `metadata_cache_entities` (`SoulSync:database/music_database.py:8926`) and `metadata_cache_searches` (`SoulSync:database/music_database.py:8974`): provider responses with TTL. `musicbrainz_cache` (`SoulSync:database/music_database.py:5020`), `mb_album_release_cache` (`SoulSync:database/music_database.py:3893`), `mb_recording_cache` (`SoulSync:database/music_database.py:3911`). `discovery_match_cache` (`SoulSync:database/music_database.py:3711`). `genre_translation_cache` (`SoulSync:database/music_database.py:1364`). |
| Discovery (brief) | `similar_artists` (`SoulSync:database/music_database.py:3355`), `discovery_pool` (`SoulSync:database/music_database.py:3371`), `recent_releases` (`SoulSync:database/music_database.py:3397`), `discovery_recent_albums` (`SoulSync:database/music_database.py:3416`), `discovery_curated_playlists` (`SoulSync:database/music_database.py:3435`), `discovery_pool_metadata` (`SoulSync:database/music_database.py:3445`), `discovery_feedback` (`SoulSync:database/music_database.py:3977`), `discovery_inbox` (`SoulSync:database/music_database.py:3999`), `discovery_layout` (`SoulSync:database/music_database.py:4023`), `mix_recipes` (`SoulSync:database/music_database.py:4060`), `liked_artists_pool` / `liked_albums_pool` (`SoulSync:database/music_database.py:4073`, `SoulSync:database/music_database.py:4105`). |
| Settings / auth / automation | `metadata` (`SoulSync:database/music_database.py:734`): key/value, holds `app_config`. `schema_migrations` (`SoulSync:database/music_database.py:777`). `profiles` (`SoulSync:database/music_database.py:5904`): name, `pin_hash`, `is_admin`. `profile_audit`, `profile_devices`, `profile_invites` (`SoulSync:database/music_database.py:6433`, `SoulSync:database/music_database.py:6448`, `SoulSync:database/music_database.py:6460`). `service_credentials` (`SoulSync:database/music_database.py:7175`) and `profile_service_credentials` (`SoulSync:database/music_database.py:7191`): named credential sets and which one a profile uses. `automations` (`SoulSync:database/music_database.py:1426`), `automation_run_history` (`SoulSync:database/music_database.py:1448`). `notification_history` (`SoulSync:database/music_database.py:929`). `bubble_snapshots` (`SoulSync:database/music_database.py:1307`): persisted UI state. |
| Social (not music pipeline) | `chat_room_messages`, `chat_room_reactions`, `chat_game_carriers`, `arcade_bank`, `chat_user_notes` (`SoulSync:database/music_database.py:947`-`SoulSync:database/music_database.py:1021`). |

Skipped as non-music: `audiobook_routes` (`SoulSync:database/music_database.py:885`), `watchlist_podcasts`
(`SoulSync:database/music_database.py:1102`), `downloaded_podcast_episodes`
(`SoulSync:database/music_database.py:1203`), `music_video_requests` (`SoulSync:database/music_database.py:27728`);
`database/video_database.py` (10,460 lines, its own `video_library.db`) and `core/audiobook_database.py`
(`audiobooks.db`).

## Settings and credentials

- **Where config lives.** `ConfigManager` (`SoulSync:core/settings.py:30`) takes `config/config.json`, overridable by
  `SOULSYNC_CONFIG_PATH` (`SoulSync:core/settings.py:33-41`), but the primary store is the database: load order is
  database row → `config.json` (one-time migration) → defaults (`SoulSync:core/settings.py:1132-1137`). The row is
  JSON in `metadata.app_config` (`SoulSync:core/settings.py:341`), written by `_save_to_database`
  (`SoulSync:core/settings.py:432`). WAL and a 30 s busy timeout on that connection
  (`SoulSync:core/settings.py:287-297`). Settings are edited in the web UI through `GET|POST /api/settings` (`SoulSync:web_server.py:4252`); there is no per-setting environment
  override: `core/settings.py` reads the environment only for `SOULSYNC_IN_DOCKER` (`SoulSync:core/settings.py:24`,
  again at `SoulSync:core/settings.py:492`), `SOULSYNC_CONFIG_PATH` (`SoulSync:core/settings.py:39`), `DATABASE_PATH`
  (`SoulSync:core/settings.py:65`, `SoulSync:core/settings.py:784`) and `SOULSYNC_LOG_LEVEL`
  (`SoulSync:core/settings.py:407`), plus OAuth callback ports in compose
  (`SoulSync:docker-compose.yml:24-35`). Startup logs every `SOULSYNC_*` variable verbatim
  (`SoulSync:web_server.py:24639-24641`).
- **Encryption at rest.** `_SENSITIVE_PATHS` lists the secrets encrypted inside the config JSON: Spotify
  `client_id`/`client_secret`, Tidal client and token dicts, the Qobuz session (`app_id`, `app_secret`,
  `user_auth_token`), Plex token, Jellyfin key, Navidrome password, the slskd API key (`soulseek.api_key`), Deezer
  ARL, Lidarr/Prowlarr/usenet keys, torrent password, ListenBrainz/AcoustID/Last.fm/Genius/Discogs tokens
  (`SoulSync:core/settings.py:91-130`). Each value becomes a Fernet token (`SoulSync:core/settings.py:161-168`,
  `_encrypt_sensitive` at `SoulSync:core/settings.py:199`). The key is a file `.encryption_key` **next to the
  database** (`SoulSync:core/settings.py:136`), generated on first use and `chmod 0600`
  (`SoulSync:core/settings.py:150-156`). So in Docker the key and the ciphertext share the `/app/data` volume: the
  encryption protects a copied config row, not a copied volume or backup.
- **Plaintext fallback.** The config is written to `config.json` by `_save_config_file_atomic` in two cases: when
  the database save keeps failing with "database is locked" (`SoulSync:core/settings.py:1242-1248`), and for every save
  of a session whose boot could not read the config row, which marks the row protected
  (`SoulSync:core/settings.py:1161-1164`, `SoulSync:core/settings.py:1225-1229`). That function dumps the in-memory
  `config_data` (`SoulSync:core/settings.py:1257-1258`), which holds decrypted values
  (`SoulSync:core/settings.py:355`); encryption happens only on a deep copy made for the database write
  (`SoulSync:core/settings.py:199-201`, `SoulSync:core/settings.py:445`). So in either case the secrets land in
  `config/config.json` in plaintext.
- **`core/credentials/`** is one 85-line module, `store.py`: pure validation and selection for *named, switchable
  credential sets* per service ("pills"), required keys per service, e.g. Spotify `client_id` + `client_secret`,
  Deezer `arl`, Navidrome `base_url` + `username` + `password` (`SoulSync:core/credentials/store.py:22-30`). Its
  docstring says storage is encrypted in the `service_credentials` / `profile_service_credentials` tables and that the
  capability is "dormant … until wired" (`SoulSync:core/credentials/store.py:1-12`). The database encrypts per-profile
  tokens with the same Fernet helper (`SoulSync:database/music_database.py:6623`,
  `SoulSync:database/music_database.py:6833`).
- **Embedded API credentials.** None found for Spotify: `grep -rnE 'client_id|client_secret|api_key'
  core/spotify*.py core/credentials` returns only key names and config reads (e.g.
  `SoulSync:core/spotify_client.py:63`, `SoulSync:core/credentials/store.py:23`); the user brings their own Spotify
  app. Spotify **without** credentials goes through the public embed page's `__NEXT_DATA__`
  (`SoulSync:core/spotify_public_scraper.py:72`, `SoulSync:core/spotify_public_scraper.py:89-100`), capped at about
  100 tracks, or the GPL-3.0 `spotipyFree` library that mimics the web player
  (`SoulSync:core/spotify_public_api.py:1-15`); 02-intake covers both. A wider grep for long string literals assigned
  to `*_KEY`/`*_SECRET`/`api_key` names in `core`, `api`, `services`, `utils` and `web_server.py` found only database
  key names and one embedded third-party key, YouTube's public InnerTube web key
  (`SoulSync:core/video/youtube.py:408`, video side, skipped). Credentials obtained **at runtime from a service's
  own client** rather than embedded: Qobuz `app_id`/`app_secret` are extracted from the Qobuz web player's
  `bundle.js` (`SoulSync:core/qobuz_client.py:218-244`); Tidal downloads go through the `tidalapi` library
  (`SoulSync:core/tidal_download_client.py:28`), whose own client id is not in SoulSync's tree (*unverified*: inside
  the library); and `spotipyFree` itself exists to track the client-auth headers Spotify's web player rotates
  (`SoulSync:core/spotify_public_api.py:4-9`). All three are terms-of-service questions for 02-intake and
  05-other-sources.

## Deployment

- **`Dockerfile`** (168 lines), three stages:
  - `node:24-slim` builds the React UI (`npm ci`, `npm run build`; `SoulSync:Dockerfile:4-12`) into
    `webui/static/dist` (`SoulSync:Dockerfile:101`, `SoulSync:webui/vite.config.ts:34`).
  - `python:3.11-slim` builder installs `requirements.txt` into `/opt/venv` (`SoulSync:Dockerfile:15-30`) and then
    the current **pre-release yt-dlp** at build time (`SoulSync:Dockerfile:38-40`), so two builds of one commit can
    differ.
  - `python:3.11-slim` runtime (`SoulSync:Dockerfile:43`) with apt packages `curl`, `gosu`, `ffmpeg`, `flac`,
    `libarchive-tools`, `libchromaprint-tools` (`fpcalc`), `rubberband-cli`, `unzip`
    (`SoulSync:Dockerfile:53-61`), and Deno from `curl … | sh` for yt-dlp's JS challenges
    (`SoulSync:Dockerfile:70`).
  - **No beets**: `grep -i beet Dockerfile requirements.txt` finds nothing. Tagging is in-house with `mutagen`
    (`SoulSync:requirements.txt:21`); fingerprints via `pyacoustid` (`SoulSync:requirements.txt:75`); audio analysis
    via `librosa` and `onnxruntime` (`SoulSync:requirements.txt:25`, `SoulSync:requirements.txt:28`).
  - Runs as user `soulsync` uid 1000 (`SoulSync:Dockerfile:82`); volumes `/app/config`, `/app/data`, `/app/logs`,
    `/app/downloads`, `/app/Transfer`, `/app/MusicVideos`, `/app/scripts` (`SoulSync:Dockerfile:134`); `EXPOSE 8008`
    and a `curl -f http://localhost:8008/` healthcheck (`SoulSync:Dockerfile:144-148`); database paths in `ENV`
    (`SoulSync:Dockerfile:153-161`); `ENTRYPOINT ["/entrypoint.sh"]`, `CMD` gunicorn
    (`SoulSync:Dockerfile:167-168`).
- **`docker-compose.yml`** (197 lines): one service `soulsync`, image `boulderbadgedad/soulsync:latest`
  (`SoulSync:docker-compose.yml:8-9`, a floating tag); ports 8008 (app), 8888 and 8889 (Spotify and Tidal OAuth
  callbacks; `SoulSync:docker-compose.yml:32-35`); bind mounts for config, logs, downloads, `Staging`, music videos,
  scripts, movies/TV/YouTube (`SoulSync:docker-compose.yml:36-84`); the database volume
  (`SoulSync:docker-compose.yml:116-119`); the music library mount and `Transfer` (the final library folder) are left
  commented for the user to set (`SoulSync:docker-compose.yml:44-52`, `SoulSync:docker-compose.yml:123-128`);
  limits 2 CPU / 2 GB (`SoulSync:docker-compose.yml:160-164`). slskd is an optional, commented-out second service
  (`SoulSync:docker-compose.yml:169-185`); there is no VPN container (the only active service is `soulsync`,
  `SoulSync:docker-compose.yml:8-10`; gluetun is mentioned only as a possible port clash at
  `SoulSync:docker-compose.yml:27`). slskd, torrent and usenet clients are expected
  to drop finished files into the shared `downloads` input folder (`SoulSync:docker-compose.yml:40-41`).
- **`entrypoint.sh`** (122 lines): remaps the `soulsync` uid/gid to `PUID`/`PGID` (`SoulSync:entrypoint.sh:19-37`);
  chowns app directories when the data dir owner differs (`SoulSync:entrypoint.sh:40-46`); applies `UMASK`
  (`SoulSync:entrypoint.sh:53`); copies a default `config.json` if missing (`SoulSync:entrypoint.sh:58-64`); deletes an
  obsolete `config/settings.py` (`SoulSync:entrypoint.sh:73-77`); creates directories and warns about unwritable ones
  (`SoulSync:entrypoint.sh:91-105`); `exec gosu soulsync "$@"` (`SoulSync:entrypoint.sh:118-122`). It runs **no
  migrations**: schema changes happen inside the app at boot (Data stores above).

## Tests and CI

- **Tests**: `find tests -name 'test_*.py' | wc -l` = **1,669** test files (1,731 files under `tests/` in all), pytest
  run with `-n auto` (xdist) in CI (`SoulSync:.github/workflows/build-and-test.yml:44`). Front-end tests: `npm run
  check`, `npm run build`, `npm test` (`SoulSync:.github/workflows/build-and-test.yml:67-76`) and Playwright in
  `mcr.microsoft.com/playwright` (`SoulSync:.github/workflows/build-and-test.yml:90`). Tests were not run (the brief
  forbids executing anything from the clone), so their pass rate is unknown.
- **`.github/workflows/`**, five files:
  - `build-and-test.yml`: on push to any branch except `main` and `dev` (`SoulSync:.github/workflows/build-and-test.yml:3-8`):
    ruff lint, `compileall`, pytest, then the web UI checks/build/tests and Playwright
    (`SoulSync:.github/workflows/build-and-test.yml:35-44`).
  - `dev-nightly.yml`: daily at 04:00 UTC (skipped when `dev` had no commits in 24 h,
    `SoulSync:.github/workflows/dev-nightly.yml:18`), on push to `dev` and by hand
    (`SoulSync:.github/workflows/dev-nightly.yml:5-12`): ruff
    + pytest (`SoulSync:.github/workflows/dev-nightly.yml:59-64`), then builds and pushes a dev image
    (`SoulSync:.github/workflows/dev-nightly.yml:91`).
  - `docker-publish.yml`: builds and pushes `:latest` on **every push to `main`**, plus a manual trigger with a version
    tag (`SoulSync:.github/workflows/docker-publish.yml:4-12`, push at
    `SoulSync:.github/workflows/docker-publish.yml:52-62`). It runs no tests of its own (`grep -nE 'pytest|ruff' docker-publish.yml` finds none); `main` is fed by PRs from
    `dev` (the pinned commit is "Merge pull request #1821 from Nezreka/dev"), and `build-and-test.yml` ignores pushes
    to `main` and has no `pull_request` trigger, so the merge commit that becomes `:latest` is not itself tested in CI.
  - `cleanup-dev-images.yml`: weekly (Sunday 06:00 UTC) deletion of old dev image versions
    (`SoulSync:.github/workflows/cleanup-dev-images.yml:4-23`).
  - `visual-baselines.yml`: manual job rendering Playwright visual baselines, artifacts kept 7 days
    (`SoulSync:.github/workflows/visual-baselines.yml:9-10`, `SoulSync:.github/workflows/visual-baselines.yml:62`).

## Module map

Line counts are `wc -l` at `34bf7cf9c741`; a directory shows `.py` file count and total lines. Corrected paths from
the run's progress log are used (`post_processing.py`, `atomic_*`, `review_reject.py`, `lifecycle.py`, `staging.py` in
`core/downloads/`).

| V2 subsystem | SoulSync files (lines) |
|---|---|
| Intake (V2-01, `02-intake.md`) | `core/spotify_client.py` 2,429; `core/spotify_public_api.py` 125; `core/spotify_public_scraper.py` 202; `core/spotify_token_cache.py` 84; `core/spotify_free_metadata.py` 361; `core/spotify_worker.py` 1,493; `api/source_playlists.py` 5,575; `api/mirrored_playlists.py` 1,447; `core/playlists/` 31 files 5,416; `core/sync/` 10 files 2,097; `services/sync_service.py` 1,820; `core/wishlist/` 17 files 5,461 (+ `core/wishlist_service.py` 5, a shim); `core/watchlist_scanner.py` 5,340; `core/watchlist/` 5 files 758; `core/watchlist_auto_download.py` 165; `core/watchlist_sources.py` 143; `api/music_requests.py` 508; `api/request.py` 468; `core/requests/` 4 files 314; `core/lidarr_compat/` 5 files 958 |
| Matching (V2-02, `03-matching.md`) | `core/matching_engine.py` 1,716; `core/matching/` 9 files 1,803; `core/client_match.py` 728; `core/source_ids.py` 157; `core/download_plugins/release_identity.py` 255 (and `core/library/release_identity.py` 65); `core/edition_grouping.py` 176; `core/discovery/isrc_match.py` 118; `core/musicbrainz_client.py` 969; `core/musicbrainz_search.py` 1,326; `core/musicbrainz_service.py` 2,053; `core/musicbrainz_worker.py` 582; `core/acoustid_client.py` 519 |
| Soulseek (V2-03a/b, `04-soulseek.md`) | `core/soulseek_client.py` 3,171; `core/slskd_throttle.py` 93; `core/download_plugins/` 11 files 5,144, of which `album_bundle.py` 1,596, `query_variants.py` 166, `candidate_store.py` 133; `core/downloads/` 46 files 17,134, of which `candidates.py` 953, `candidate_pool.py` 240, `album_bundle_dispatch.py` 266, `pinned_batch.py` 255, `prioritize.py` 169, `peer_observation.py` 81, `observed_speed.py` 80, `failed_blocklist.py` 212, `soulseek_identity.py` 340, `monitor.py` 1,531, `cancel.py` 123, `lifecycle.py` 1,412, `staging.py` 598; `core/download_orchestrator.py` 721; `core/download_engine/` 4 files 1,022 |
| Other sources (V2-04, `05-other-sources.md`) | `core/deezer_download_client.py` 1,374; `core/tidal_download_client.py` 1,276; `core/qobuz_client.py` 1,436; `core/amazon_download_client.py` 498; `core/hifi_client.py` 1,332; `core/youtube_client.py` 2,315; `core/soundcloud_client.py` 708; `core/bandcamp_client.py` 589; `core/jiosaavn_client.py` 597; `core/torrent_clients/` 7 files 1,778; `core/usenet_clients/` 4 files 832; `core/prowlarr_client.py` 664; `core/lidarr_download_client.py` 718; `core/download_plugins/torrent.py` 1,483; `core/download_plugins/usenet.py` 710; `core/download_plugins/registry.py` 198 |
| Verification (V2-05, `06-verification.md`) | `core/downloads/validation.py` 1,015; `core/downloads/post_processing.py` 691; `core/downloads/atomic_album_publish.py` 462; `core/downloads/atomic_manifest.py` 202; `core/downloads/atomic_recovery.py` 350; `core/album_consistency.py` 897; `core/acoustid_verification.py` 730; `core/audio_length.py` 60; `core/quality/` 11 files 2,873; `core/replaygain.py` 379; `api/quarantine.py` 499; `core/downloads/review_reject.py` 47; `core/blocklist/` 4 files 297 |
| Filing / library / Navidrome (V2-06, `07-filing-library.md`) | `core/tag_writer.py` 840; `core/metadata/` 48 files 18,391; `core/enrichment/` 6 files 1,228; `core/library_reorganize.py` 3,066; `core/repair_jobs/library_reorganize.py` 568; `core/reorganize_queue.py` 628; `core/reorganize_runner.py` 246; `core/imports/` 40 files 17,089, of which `pipeline.py` 2,285; `core/auto_import_worker.py` 2,722; `core/library/` 35 files 9,024; `core/navidrome_client.py` 2,112; `core/media_server/` 8 files 1,324; `core/repair_worker.py` 6,885; `api/deleted_files.py` 102; `core/maintenance/` 2 files 139 |
| UI / API / phone (V2-07, `08-ui-api.md`) | `web_server.py` 24,916; `api/` 92 files 51,454 (incl. `api/auth.py` 295, `api/profiles.py`, `api/user_profiles.py`); `webui/index.html` 12,932 (legacy page) and `webui/src/` 1,321 files (React 19 + TanStack Router + Vite, `SoulSync:webui/package.json:7-46`); `templates/` holds no HTML templates; `core/streaming/` 4 files 585; `core/playback/` 3 files 216; `core/radio/` 2 files 250; `core/mcp/` 3 files 400; `core/automation_engine.py` 2,102 |

Skipped, non-music (named once): `core/audiobook_*.py` (23 files), `core/podcast_*.py` (5 files), `core/video/`
(120 files), `api/video/`, `api/video_v1.py`, `api/audiobooks.py`, `api/audiobook_routes.py`, `api/podcasts.py`,
`database/video_database.py`, `core/audiobook_database.py`. `core/youtube_client.py` and `core/youtube_*meta.py`
serve music (YouTube audio as a source) and stay in "Other sources".

## License

`license.txt` is the MIT license (`SoulSync:license.txt:1-18`). The copyright line reads:

> Copyright (c) [2025] [SoulSync]

(`SoulSync:license.txt:1`; the bracketed template placeholders are left in, so the holder is named only as
"SoulSync"). The retention clause:

> The above copyright notice and this permission notice shall be included in all copies or substantial portions of
> the Software.

(`SoulSync:license.txt:10-11`). What that requires of anything we port: any file containing a substantial portion of
SoulSync code keeps that copyright line and the full permission notice, in the file header or in a
`THIRD_PARTY_NOTICES` file that ships with the code (and so with the `dj-crates` image). Ideas, data shapes and
algorithms re-implemented in our own words need no notice. Our repository has no `LICENSE` file at its root (`ls`
at the run's base), so a port would be the first licence text in the tree. Two related cautions:
- The published image installs `spotipyFree`, which is GPL-3.0, as a normal pip dependency
  (`SoulSync:requirements.txt:88-95`), although `core/spotify_public_api.py` still describes it as an optional,
  un-bundled install (`SoulSync:core/spotify_public_api.py:11-15`). Porting the code that calls it is fine under MIT;
  shipping `spotipyFree` in our image would bring GPL-3.0 obligations for that component.
- MIT gives no warranty and grants no rights in the third-party services SoulSync talks to (see 05-other-sources).

## Maintenance health

All figures were read on **2026-10-22** with `gh api` (read-only GET, logged in as mh550).
The clone is depth 1 (`git -C ~/research/soulsync-src/SoulSync log` shows one commit, 34bf7cf9c741), so it says nothing
about history; every number below comes from the GitHub API, nothing was run from the clone. Counts move daily.

### Releases

| Figure | Value | Command (2026-10-22) |
|---|---|---|
| Releases, all pages | **101** (oldest `v0.65`, 2025-08-21; none are prereleases) | `gh api --paginate 'repos/Nezreka/SoulSync/releases?per_page=100' --jq '.[].tag_name'` piped to `wc -l` (one page of 100 plus 1) |
| Median days between the latest 20 | **2.16** (mean 2.43) | same call, gaps between the 20 newest `published_at` values |

Latest 10 tags (same call):

| Tag | Published |
|---|---|
| 3.5.9 | 2026-10-22 |
| 3.5.8 | 2026-10-20 |
| 3.5.7 | 2026-10-17 |
| 3.5.6 | 2026-10-15 |
| 3.5.5 | 2026-10-15 |
| 3.5.4 | 2026-10-13 |
| 3.5.3 | 2026-10-09 |
| 3.5.2 | 2026-10-07 |
| 3.5.1 | 2026-10-07 |
| 3.5.0 | 2026-10-04 |

About one release every two days, and 3.5.0 → 3.5.9 took 18 days. Cadence is a sign of an active maintainer, not of
tested stability: CI never tests the merge commit that `:latest` is built from (see Tests and CI above).

### Contributors

`gh api 'repos/Nezreka/SoulSync/contributors?per_page=100'` (2026-10-22): 41 contributors, 8,544 contributions in total.

| # | Login | Contributions | Share |
|---|---|---|---|
| 1 | Nezreka | 7,590 | **88.8%** |
| 2 | kettui | 258 | 3.0% |
| 3 | Thundernerd | 167 | 2.0% |
| 4 | mandos21 | 68 | 0.8% |
| 5 | nick2000713 | 65 | 0.8% |

**Bus factor: 1.** One account wrote about nine in ten of the contributions and the next contributor has 3%, so if
Nezreka stops, the project effectively stops (we would be maintaining a fork). In the last 30 days the commit *author
names* are led by "BoulderBadgeDad" (917 of the 1,592 commits), then "Nez" (260), Thundernerd (167), "Claude" (42),
mandos21 (39), from `gh api --paginate 'repos/Nezreka/SoulSync/commits?since=2026-09-22T00:00:00Z&per_page=100' --jq '.[].commit.author.name' | sort | uniq -c | sort -rn`.
That the "BoulderBadgeDad" and "Nez" names belong to the Nezreka login is *unverified* (the API's login field was not
compared with author names); the "Claude" commits show AI-assisted authoring is in use.

### Issues, PRs, stars

| Figure | Value | Command (2026-10-22) |
|---|---|---|
| `open_issues_count` (issues + PRs) | 30 | `gh api repos/Nezreka/SoulSync --jq .open_issues_count` |
| Open PRs | 14 | `gh api 'search/issues?q=repo:Nezreka/SoulSync+is:pr+is:open' --jq .total_count` |
| Open issues | 16 | `gh api 'search/issues?q=repo:Nezreka/SoulSync+is:issue+is:open' --jq .total_count` |
| Stars / forks | 2,309 / 131 | `gh api repos/Nezreka/SoulSync --jq '[.stargazers_count,.forks_count]'` |
| Created / last push | 2025-07-09 / 2026-10-22T02:03Z | `gh api repos/Nezreka/SoulSync --jq '[.created_at,.pushed_at]'` |

Five most recently closed issues (`gh api 'search/issues?q=repo:Nezreka/SoulSync+is:issue+is:closed&sort=updated&order=desc&per_page=5' --jq '.items[]|[.number,.closed_at,.title]|@tsv'`):

| # | Closed (UTC) | Title |
|---|---|---|
| 1817 | 2026-10-21 22:39 | Bug: YouTube Music tracks rejected by matching engine despite exact artist/title match |
| 1810 | 2026-10-21 21:17 | [Bug] Redownload with "delete old file" leaves two catalog rows pointing to the replacement when its path changes |
| 1807 | 2026-10-21 14:29 | Randomly downloading movies and shows |
| 1805 | 2026-10-21 04:26 | [FEATURE REQUEST] Configurable Duration Mismatch Tolerance Setting |
| 1804 | 2026-10-21 03:08 | [BUG] AcoustID & Metadata Match False Positives across Downloads and Imports |

Issues are closed within a day or so, so the tracker is responsive. Three of five are about matching and
verification (our V2-02 / V2-05 topics) and one about duplicate catalog rows after replace (our duplicate-cleanup
topic).

### Size of recent change

- **Commits in the last 30 days (since 2026-09-22): 1,592**, 377 of them merge commits. Commands:
  `gh api --paginate 'repos/Nezreka/SoulSync/commits?since=2026-09-22T00:00:00Z&per_page=100' --jq length | paste -sd+ | bc` and the same
  with `--jq '.[]|select(.parents|length>1)|1' | wc -l`. The count includes commits that arrived through merged branches.
- Five newest merge commits to `main` (`gh api 'repos/Nezreka/SoulSync/commits?per_page=30' --jq '.[]|select(.parents|length>1)'`, then
  `gh api repos/Nezreka/SoulSync/commits/<sha> --jq '[.stats.additions,.stats.deletions,(.files|length)]'`):

| Merge commit | Date (UTC) | Files | + lines | − lines | Touches `core/soulseek_client.py` or `core/downloads/` |
|---|---|---|---|---|---|
| 34bf7cf9c7 (#1821 dev→main, the clone's HEAD) | 2026-10-22 02:01 | 275 | 37,273 | 14,355 | `core/downloads/review_reject.py`, `row_art.py`, `status.py` |
| 7145bfa9e8 (#1820) | 2026-10-22 01:05 | 13 | 506 | 21 | no |
| edd65e9d92 (#1819) | 2026-10-22 01:05 | 3 | 122 | 0 | no |
| 09a5fb07ca (#1818) | 2026-10-22 01:05 | 7 | 444 | 16 | no |
| bc047f4e4e (#1812) | 2026-10-21 21:39 | 1 | 493 | 493 | no |

  The first row is a dev→main release merge: 275 files and 37k added lines in one commit, so "one release" can be a
  large drop, not a small step. (The API lists at most 300 files per commit; 275 is under that.)
- **How often the internals we cite changed**, `gh api --paginate 'repos/Nezreka/SoulSync/commits?path=<p>&since=2026-09-22T00:00:00Z&per_page=100' --jq length`:
  `core/soulseek_client.py` **8 commits** in 30 days (latest `ec0e61323d`, 2026-10-06, so it has been stable for 16 days);
  `core/downloads/` **71 commits** (latest `abeb005f8e`, 2026-10-21). Only the newest merge commit touches
  `core/downloads/`. Line numbers cited in this report will drift in `core/downloads/` within days; they are valid at
  34bf7cf9c741 only.

### What this means for us

Active and responsive, but a single-maintainer project with a release every two days and very large merges. Adopting
it as a dependency means tracking a fast-moving target; reading it for ideas (the brief's purpose) is safe. The bus
factor and the unreviewed `:latest` publication are the two risks for any "run SoulSync alongside" option in V3/V4.

## How ours does it

- **Process model.** Separate containers with separate jobs (`ours:deploy/compose.yml:12`, `ours:deploy/compose.yml:37`,
  `ours:deploy/compose.yml:74`, `ours:deploy/compose.yml:119`): Navidrome serves and scans; `crates` is a stdlib
  `ThreadingHTTPServer` (`ours:crates/service.py:25`, `ours:crates/service.py:488`) with no library mount; `worker`
  runs `python -m sourcing.cli worker` (`ours:sourcing/cli.py:145`), refuses to start outside its container
  (`ours:sourcing/cli.py:243`), and is the only process that downloads, runs beets or moves files into `/srv/music`
  (`ours:docs/architecture.md:72-75`, D18 at `ours:docs/specs/2026-10-13-next-session-design.md:72`). One-off
  commands that write take the worker's lock (`ours:sourcing/worker.py:84-86`). slskd runs in gluetun's VPN
  namespace (`ours:docs/architecture.md:65-66`).
- **Data stores.** `crates.db` (SQLite WAL, `ours:crates/store.py:286`) with 14 tables
  (`ours:crates/store.py:36-117`), for wanted rows, approvals, placements and replacements; library facts live in
  file tags, beets' disposable `library.db` and Navidrome's DB (`ours:docs/architecture.md:82-100`). Schema and
  config are small enough to read in one sitting.
- **Settings and credentials.** Environment variables read at the CLI edge, e.g. `SLSKD_URL`, `SLSKD_API_KEY`,
  `ACOUSTID_KEY`, `NAVIDROME_DB` (`ours:sourcing/cli.py:44-45`, `ours:sourcing/cli.py:105-106`), supplied from
  `/srv/docker/.env`, which sessions never read (CLAUDE.md, Off-limits). No credential is stored in a database.
- **Deployment.** One image for `crates` and `worker`: `python:3.12-slim` + ffmpeg, flac, fpcalc and pinned beets
  1.6.0 (`ours:Dockerfile:1-5`), tagged with the commit it was built from (`ours:deploy/compose.yml:39`); Navidrome and
  gatus pinned (`ours:deploy/compose.yml:13`, `ours:deploy/compose.yml:120`).
- **Tests and CI.** 67 test files, 1,615 tests in `.harness/check.sh` (init output of this run); no `.github/`
  directory, so no CI: the harness runs the suite before every merge.

## The difference that matters

- **One process versus separated writers.** SoulSync's web request threads, downloaders, tagger, repair worker and
  scheduler share one process and one database file, configuration included. Ours puts the only library writer in its
  own container with its own lock (D18) and keeps the web-facing service without a library mount. Against our safety
  invariants (one beets writer, no trash while a playlist holds the file, logged reverses), a SoulSync component
  dropped beside ours would be a **second library writer** unless it is confined to an input folder.
- **Scale of moving parts.** 86 live tables, 63 columns bolted onto `tracks` by in-place migration, ~20 polling
  loops and a schedule stored as data: a lot to run beside ours, and a lot of surface that changes under a fast release
  cadence (V1-02 measures it). Ours is 14 tables and env-configured.
- **Credentials.** SoulSync stores every secret in the database, encrypted with a key that sits on the same volume,
  with a plaintext `config.json` fallback; ours keeps secrets out of the database and the code. Neither embeds a
  Spotify credential; SoulSync's credential-less Spotify paths (embed scraping, `spotipyFree`) are the opposite of
  goal C's "his own developer app only".
- **Supply chain.** SoulSync builds with a floating pre-release yt-dlp and a `curl | sh` Deno install and publishes
  `:latest` on every push to `main`; ours pins beets, Navidrome and gatus and tags images by commit.
- **Useful as data, not as a runtime.** The table list itself is a design checklist we lack in places: provenance per
  file with the peer and filename (`track_downloads`), an audit of every pick with its alternatives
  (`download_decisions`), expiring blocklists keyed by fingerprint and size (`failed_download_blocklist`), per-peer
  quarantine (`quarantine_source_blocks`), and a request queue with admin responses (`music_requests`). V2 judges
  each in its own section.

## Worth taking?

As a whole system, no: it is a single-process monolith whose writers, scheduler and secrets model conflict with D18,
the one-writer invariant and goal C. As a source of designs, yes: the provenance, decision-audit and blocklist tables
above, and later the Soulseek album logic (04), are worth adapting into `crates.db` and `sourcing/` in our own code,
with the MIT notice kept on anything copied rather than re-written.

**Verdict:** adapt
