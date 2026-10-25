# 08 · UI, API and the phone (routes, web UI, auth, streaming, MCP, automation, requests)

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed, built or
served). Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a
claim without one, *absence inferred* marks an absence read from a grep (the grep is given), and "read from code"
marks a consequence derived from cited lines but not run. Music only: `api/video/` (29 files, 304 routes),
`api/video_v1.py`, `api/audiobooks.py`, `api/audiobook_routes.py` and `api/podcasts.py` are named here once and skipped.

## What SoulSync does

```
 phone / desktop browser                         bots, Shortcuts, AI clients, request apps
   │  GET /  (Jinja index.html: ~90 classic scripts + React 19 app + shell.js)      │
   │  sw.js caches images/static only                                             │ API key (Bearer / X-API-Key / ?api_key=)
   ▼                                                                               ▼
 Flask app (web_server.py:285) ── before_request: profile context, opt-in login / launch PIN
   ├─ 255 @app.route in web_server.py           ├─ /api/v1/* blueprint (17 modules, 60/min)  ── POST /api/v1/request: 1 track, now
   ├─ ~40 blueprints registered one by one      ├─ /mcp (off by default, key)                ── request_track / request_album …
   ├─ /stream/audio, /stream/library-audio      └─ /lidarr/api/v1 (off by default, admin key) ── album → wishlist
   │     ├─ library file on disk (Range, as is)
   │     ├─ Navidrome /rest/stream proxied (Range passed through)
   │     └─ not owned: download whole into Stream/ first (YouTube by default)
   └─ AutomationEngine: threading.Timer + events → actions → then-steps (ntfy, Discord, webhook …)
```

### Routes and how they are registered

- One Flask app: `Flask(__name__, template_folder=webui, static_folder=webui/static)`
  (`SoulSync:web_server.py:285-289`). The public API is one `api_v1` blueprint built by `create_api_blueprint()` from 17
  modules that each expose `register_routes(bp)` (`SoulSync:api/__init__.py:26-67`), rate-limited to 60 per minute
  (`SoulSync:api/__init__.py:51-52`) and mounted at `/api/v1` (`SoulSync:web_server.py:1829`).
- Every other module is registered by hand, `configure(...)` + `create_blueprint()` + `app.register_blueprint(...)`, in
  one block at the end of `web_server.py`, from enrichment (`SoulSync:web_server.py:23411`) to video
  (`SoulSync:web_server.py:23927-23928`); examples are login (`SoulSync:web_server.py:23540-23544`), lidarr-compat
  (`SoulSync:web_server.py:23798-23800`) and MCP (`SoulSync:web_server.py:23803-23806`). There is no registration loop:
  `grep -nE 'register_blueprint|add_url_rule' web_server.py` gives 43 lines, all `register_blueprint`; `add_url_rule`
  is unused (*absence inferred*: `grep -rnE 'add_url_rule' api core web_server.py`).
- **Counts at 34bf7cf9c741.** `api/*.py` (top level): **63 files**, 6 of them without routes (`__init__`, `helpers`,
  `serializers`, `key_store`, `auth`, `content_guard`). `grep -cE '@.*\.route\(' web_server.py` = **255**; the same grep
  summed over `api/*.py` = **957**; together **1,212** decorator lines. Not in that sum: `core/enrichment/api.py` (12)
  and `api/video/` (304, skipped). The grep is not an undercount of URL rules: the custom decorators
  (`SoulSync:api/auth.py:181`, `SoulSync:core/profile_context.py:160`, `SoulSync:core/profile_context.py:185`,
  `SoulSync:api/lidarr_compat.py:116`) wrap views and register nothing. Some decorators take two methods
  (`SoulSync:web_server.py:4252`). 13 `@socketio.on` handlers sit beside them (`grep -cE '@socketio\.on' web_server.py`).
- **Music route families** (prefix: example):
  - search: `POST /api/search` against the download sources (`SoulSync:web_server.py:6298`), `POST /api/enhanced-search`
    against metadata catalogs (`SoulSync:web_server.py:6337`), link lookup `POST /api/enhanced-search/by-id`
    (`SoulSync:web_server.py:6387`), v1 `/search/tracks|albums|artists` (`SoulSync:api/search.py:16`).
  - requests: `/api/requests/music` with `/quota`, `/approve`, `/decline`, `/withdraw`
    (`SoulSync:api/music_requests.py:134-347`); v1 `POST /request` (`SoulSync:api/request.py:345`).
  - downloads: `POST /api/download` (`SoulSync:web_server.py:6971`), `GET /api/downloads/status`
    (`SoulSync:web_server.py:7339`), `POST /api/playlists/<id>/start-missing-process` (`SoulSync:web_server.py:19291`).
  - wishlist: `/api/wishlist/process|count|stats|cycle` (`SoulSync:api/wishlist_routes.py:82-190`),
    `POST /api/add-album-to-wishlist` (`SoulSync:api/wishlist_routes.py:605`).
  - playlists: `/api/playlists` (`SoulSync:web_server.py:6222`), `/api/playlists/<id>/download_missing`
    (`SoulSync:web_server.py:16878`); `api/source_playlists.py` alone holds 133 routes.
  - library: v1 `/library/artists|albums|tracks|…` (`SoulSync:api/library.py:14-451`).
  - stream: `/api/stream/start|status|stop` and `/stream/audio`, `/stream/library-audio`
    (`SoulSync:web_server.py:12608-12900`).
- The page itself: `/` renders `index.html` (`SoulSync:web_server.py:3265-3267`), `/sw.js` is served from static at
  root scope (`SoulSync:web_server.py:3270-3285`), and `/<path:page>` is the SPA catch-all
  (`SoulSync:web_server.py:3288-3293`), which leaves `/api`, `/auth`, `/callback`, `/deezer`, `/socket.io`,
  `/static`, `/stream`, `/tidal` and `/status` alone (`SoulSync:core/webui/spa.py:5-23`).

### The web UI

- **`webui/index.html` (12,932 lines) is not a one-file SPA.** It is a Jinja template rendered by Flask: it uses
  `{{ url_for('static', …) }}` (`SoulSync:webui/index.html:9`), `{% if initial_reduce_effects %}`
  (`SoulSync:webui/index.html:161`) and `{% include 'track-detail-modal.html' %}` (`SoulSync:webui/index.html:12720`);
  context processors inject a cache-busting `static_v`, the version and the profile gate rules
  (`SoulSync:web_server.py:428-459`). The markup of every page lives in that one document.
- It runs **three front-end layers in one page**:
  1. ~90 classic `<script src>` files from `webui/static/` with no framework (`grep -c '<script' webui/index.html` = 93;
     load order at `SoulSync:webui/index.html:12667-12706`; the comment "SoulSync is vanilla" at
     `SoulSync:webui/index.html:12687-12688`), plus graphology/sigma from cdn.jsdelivr.net
     (`SoulSync:webui/index.html:12689-12691`).
  2. A **React 19 + TanStack Router** app (`SoulSync:webui/package.json:18-30`, Vite at
     `SoulSync:webui/package.json:46`) mounted into `#webui-react-root` (`SoulSync:webui/index.html:892`). Its bundle
     tags come from `vite_assets`, which reads `webui/static/dist/.vite/manifest.json`
     (`SoulSync:core/webui/assets.py:83-126`) and returns `""` when the build is missing
     (`SoulSync:core/webui/assets.py:112-114`), leaving the vanilla layer alone.
  3. A "shell" IIFE bundle `dist/shell.js` (global `SoulSyncShell`) that holds classic scripts ported to TypeScript
     and called through `window` globals (`SoulSync:webui/vite.shell.config.ts:4-16`,
     `SoulSync:webui/index.html:12676-12684`).
- **Flask does not choose between old and new pages; the browser does.** A route manifest marks each page `react` or
  `legacy` (`SoulSync:webui/src/platform/shell/route-manifest.ts:29-61`): 20 of 24 pages are React (dashboard, sync,
  search, discover, wishlist, active-downloads, library, requests, …), 4 are legacy (settings, help, hydrabase, chat,
  `SoulSync:webui/src/platform/shell/route-manifest.ts:53`). The splat route hands legacy paths to the vanilla page
  switcher (`SoulSync:webui/src/routes/$.tsx:5-12`). The global player is still vanilla
  (`SoulSync:webui/index.html:12670-12671`).
- The React build is not committed: `webui/.gitignore` lists `static/dist` (`SoulSync:webui/.gitignore:3`), and a
  `node:24-slim` Dockerfile stage runs `npm ci` and `npm run build` (`SoulSync:Dockerfile:4-12`), copied into the
  runtime image (`SoulSync:Dockerfile:101`).
- **`templates/` holds no Flask templates** (Flask's template folder is `webui/`, `SoulSync:web_server.py:287`).
  `templates/soulsync.xml` is an Unraid Community Apps container template (`<Container version="2">`, WebUI on port
  8008, `SoulSync:templates/soulsync.xml:2-17`) that says it "Requires slskd" (`SoulSync:templates/soulsync.xml:23`);
  `soulsync.png` is its icon (`SoulSync:templates/soulsync.xml:17`).

### Auth, sessions and profiles

- **No login by default.** `security.require_login` defaults to False (`SoulSync:web_server.py:608`), and so does the
  launch PIN (`SoulSync:web_server.py:669`, `SoulSync:web_server.py:676`). With one profile and no session a request
  acts as profile 1, the admin (`SoulSync:core/security/session_profile.py:25-38`). The code says so itself: "single-admin
  installs have no actual gate here" (`SoulSync:core/profile_context.py:163-168`). The websocket gate is open too
  (`SoulSync:core/security/ws_gate.py:33-38`).
- **Three opt-in gates** (before_request hooks, `SoulSync:web_server.py:623-888`):
  1. Login mode: profile name + password at `POST /api/auth/login`, 10 attempts per 300 s per (ip, user)
     (`SoulSync:api/login.py:28`, `SoulSync:api/login.py:68-101`); werkzeug `pbkdf2:sha256` hashes
     (`SoulSync:database/music_database.py:9774-9799`); "Sign in with Plex" (`SoulSync:api/login.py:114-151`).
  2. One launch PIN for the whole install (`SoulSync:core/security/launch_lock.py:30-92`).
  3. A trusted auth-proxy header such as `Remote-User`, honoured in PIN mode only
     (`SoulSync:core/security/auth_proxy.py:1-37`, `SoulSync:web_server.py:687-698`).
- **Sessions:** Flask's signed cookie `soulsync_session` (`SoulSync:web_server.py:478`); the secret is 32 random hex
  bytes stored in the DB `metadata` table (`SoulSync:web_server.py:462-474`); no lifetime is set (*absence inferred*:
  `grep -rnE '\.permanent|PERMANENT_SESSION' --include=*.py .` outside tests finds nothing). `Secure`,
  `SameSite=Lax` and HSTS come only with `security.trust_reverse_proxy` (off by default,
  `SoulSync:core/security/reverse_proxy.py:23-57`). No CSRF token anywhere (*absence inferred*:
  `grep -rniE 'csrf' web_server.py api core/security`); CORS is `*` on `/api/*` (`SoulSync:core/security/cors.py:44-66`).
- **Profiles = several users on one install.** The `profiles` table starts as `id, name, avatar_color, pin_hash,
  is_admin` with profile 1 'Admin' seeded (`SoulSync:database/music_database.py:5904-5920`); later columns add
  `allowed_pages`, `home_page`, `can_download` (`SoulSync:database/music_database.py:6531-6533`), request quotas,
  `hide_explicit`, `max_rating`, `session_epoch`, `disabled` (`SoulSync:database/music_database.py:6408-6416`) and
  per-profile Spotify/Plex/Jellyfin/Navidrome credentials (`SoulSync:database/music_database.py:6748-6785`). Without login
  mode, `POST /api/profiles/select` asks for a PIN only when the profile has one and there is more than one profile
  (`SoulSync:api/user_profiles.py:767-784`).
- **Permissions are per-profile fields, not roles.** `can_download` is checked by `check_download_permission()`
  (`SoulSync:core/permissions.py:29-49`, `SoulSync:web_server.py:1097-1103`; 12 calls in `web_server.py` besides the definition);
  `allowed_pages` is enforced on the server for five API prefixes only (`SoulSync:core/permissions.py:94-117`,
  `SoulSync:web_server.py:883-886`) and otherwise just hides pages; `@admin_only` guards admin routes
  (`SoulSync:core/profile_context.py:160`).
- **API keys:** `sk_` + `token_urlsafe(32)`, stored as SHA-256 and compared with `hmac.compare_digest`
  (`SoulSync:api/auth.py:104-121`, `SoulSync:api/auth.py:148-163`); scope `admin` (the default) or `read`
  (`SoulSync:api/auth.py:40-101`). An admin key acts as admin profile 1 with download rights
  (`SoulSync:api/auth.py:166-178`). `@require_api_key` sits on 112 routes (`grep -c '@require_api_key' api/*.py`
  summed), documented in `Support/API.md` (2,689 lines).
- **Login mode exempts `/api/v1/*` wholesale** (`SoulSync:core/security/login_gate.py:47-48`), and
  `POST /api/v1/api-keys/bootstrap` has no decorator and mints the first key while none exist
  (`SoulSync:api/settings.py:120-138`, `SoulSync:api/key_store.py:62-71`). Read from code: on a login-mode install that
  never made a key, an anonymous caller could mint an admin key (the blueprint is mounted at `/api/v1`,
  `SoulSync:web_server.py:1829`, and a key defaults to `admin`, `SoulSync:api/auth.py:104`; *unverified*, nothing was
  run: would be verified by an unauthenticated `POST /api/v1/api-keys/bootstrap` to a fresh login-mode instance).

### Streaming, playback and radio

- **SoulSync streams audio itself, but only to its own browser player**, one track per browser session:
  `POST /api/stream/start` (`SoulSync:web_server.py:12608-12659`), `GET /stream/audio`
  (`SoulSync:web_server.py:12798-12832`), `GET /stream/library-audio?path=` for the experimental crossfade
  (`SoulSync:web_server.py:12835-12861`, `SoulSync:webui/static/media-player.js:2277-2282`), and
  `POST /api/library/play` (`SoulSync:web_server.py:11051-11106`). The player loads `/stream/audio?t=<ts>`
  (`SoulSync:webui/static/media-player.js:780`).
- Three sources, none **transcoded on the fly** (source 3's default YouTube file is already an MP3 320 re-encode, 05-other-sources.md):
  1. A library file on disk, served as is with a hand-rolled `Range` → 206 reply in 64 KB chunks
     (`SoulSync:web_server.py:12744-12785`), or `send_file` without a Range header (`SoulSync:web_server.py:12786-12791`).
     The only `ffmpeg` calls in `web_server.py` are the three ReplayGain routes' availability checks
     (`SoulSync:web_server.py:10283-10284`, `SoulSync:web_server.py:10330-10331`,
     `SoulSync:web_server.py:10444-10445`).
  2. **Navidrome only:** its Subsonic `/rest/stream` URL with token + salt, client `c=SoulSync`, `max_bitrate=0`
     (`SoulSync:core/navidrome_client.py:451-473`), proxied with the browser's `Range` passed upstream and the body
     streamed through unbuffered (`SoulSync:web_server.py:12693-12723`, issue #809 in the docstring). Plex/Jellyfin
     tracks must be on a disk mount instead (`SoulSync:web_server.py:11032-11045`).
  3. **A track it does not own:** `prepare_stream_task` downloads the whole file through the normal download
     orchestrator (`SoulSync:core/streaming/prepare.py:114-123`), with a 60 s overall timeout
     (`SoulSync:core/streaming/prepare.py:136-138`), moves it into a per-session `Stream/` folder
     (`SoulSync:core/streaming/prepare.py:248-257`) and removes the transfer record with `remove=True`
     (`SoulSync:core/streaming/prepare.py:267-284`). The source is `download_source.stream_source`, default
     `"youtube"`; `"active"` falls back to YouTube when the active source is Soulseek; `"deezer_preview"` plays a 30 s clip
     (`SoulSync:core/settings.py:569`, `SoulSync:core/streaming/deezer_preview.py:22-23`).
- **The play queue can grow the library:** `POST /api/playback/queue/prefetch` sends queue rows it does not own through
  the normal download and import pipeline, up to 250 tracks (`SoulSync:web_server.py:6842-6858`,
  `SoulSync:core/playback/prefetch.py:15-16`), gated only by `can_download` (`SoulSync:web_server.py:6845-6847`).
- Play logging: a play becomes a `listening_history` row with source `soulsync_web`
  (`SoulSync:core/playback/play_log.py:1-19`), posted ~10 s into a track (`SoulSync:web_server.py:11109-11130`).
- **Radio** is library-only endless play: `GET /api/library/radio` (`SoulSync:web_server.py:12566-12598`), seeded tiers
  same artist → genre → mood/style → random (`SoulSync:core/radio/selection.py:37-43`), ranked by
  `log1p(plays) + 0.5·log1p(lastfm) − 2.0 if recent + jitter` (`SoulSync:core/radio/selection.py:161-214`).
- **No Subsonic server.** SoulSync is a Subsonic *client* of Navidrome only (`SoulSync:core/navidrome_client.py:451-481`).
  *absence inferred*: `grep -rhn -o -E "route\(['\"][^'\"]*" --include=*.py web_server.py api/ | grep -iE "rest|subsonic|ping|getSong"`
  matches only `…/restore` routes. Amperfy, or any Subsonic app, cannot connect to SoulSync.
- **Lidarr-compatible API** at `/lidarr/api/v1` so Lidarr-only request apps (Singarr, MusicSeerr 1.x) can add albums to
  the wishlist (`SoulSync:api/lidarr_compat.py:1-8`, `SoulSync:api/lidarr_compat.py:25`); 404 while off (the default),
  admin key only when on (`SoulSync:api/lidarr_compat.py:116-126`).

### MCP

- `POST /mcp`: MCP over plain HTTP JSON-RPC, one JSON reply per POST, no SSE, no sessions; GET and DELETE answer 405
  (`SoulSync:api/mcp.py:148-153`, `SoulSync:core/mcp/protocol.py:1-11`). Methods `initialize`, `ping`,
  `server/discover`, `tools/list`, `tools/call` (`SoulSync:core/mcp/protocol.py:99-148`).
- **Off by default** (`mcp.enabled: False`, `SoulSync:core/settings.py:668-671`; 404 while off,
  `SoulSync:api/mcp.py:48-52`). It needs a Bearer API key (`SoulSync:api/mcp.py:163-167`) and checks that a browser
  `Origin` matches the Host (`SoulSync:api/mcp.py:55-64`). Tools replay `/api/v1` calls in-process with the same key, so a
  tool can do no more than the key (`SoulSync:api/mcp.py:110-135`).
- 35 tools: 33 `/api/v1` wrappers (`SoulSync:core/mcp/tools.py:76-172`) and 2 custom ones
  (`SoulSync:api/mcp.py:69-100`). Read-only ones browse the library, wishlist, downloads and catalogs (`search_music`,
  `find_album`). **Four can start downloads:** `request_track` (= `POST /api/v1/request`, one track now),
  `request_album` (a whole MusicBrainz album onto the wishlist), `process_wishlist` and `scan_watchlist`
  (`SoulSync:core/mcp/tools.py:144-148`, `SoulSync:api/mcp.py:67-101`). Settings, keys, profiles, cancel-all and
  blocklist clearing are left out on purpose (`SoulSync:core/mcp/tools.py:3-5`). No tool deletes files or writes to the
  media server (read from the tool list above).

### Automation, webhooks and notifications

- **Engine:** trigger → action → up to 3 "then" steps, with conditions and signals between automations
  (`SoulSync:core/automation_engine.py:1-13`), chain depth capped at 5 (`SoulSync:core/automation_engine.py:558-560`).
  Schedules are `threading.Timer` daemons with `next_run` saved in the DB (`SoulSync:core/automation_engine.py:1615-1647`);
  events start one thread each (`SoulSync:core/automation_engine.py:1058-1068`).
- **Triggers** (music side, `SoulSync:core/automation/blocks.py:38-240`): time (`schedule`, `daily_time`,
  `weekly_time`, `monthly_time`), downloads (`track_downloaded`, `batch_complete`, `download_failed`,
  `download_quarantined`), wishlist/watchlist, playlists, library and import scans, requests
  (`music_request_approved|declined|available`), issues, `signal_received` and `webhook_received`.
- **Actions** (`SoulSync:core/automation/blocks.py:342-472`): downloads (`process_wishlist`, `scan_watchlist`,
  `search_and_download`, `complete_incomplete_albums`, `apply_quality_upgrades`, `playlist_pipeline`), media-server writes
  (`scan_library`, `sync_playlist`, `sync_downloaded_playlists`, `SoulSync:core/automation/blocks.py:352-383`), deletes
  (`run_duplicate_cleaner`, `clear_quarantine`, `library_cleanup`, `full_cleanup`,
  `SoulSync:core/automation/blocks.py:411-416`), maintenance, and `run_script` (a script from `scripts.path`, ≤ 300 s,
  realpath-guarded, `SoulSync:core/automation/handlers/run_script.py:1-48`).
- **Shipped enabled** (`SoulSync:database/music_database.py:26651-26656`): Auto-Process Wishlist every 30 min, first run
  60 s after start (`SoulSync:core/automation_engine.py:76-83`); Auto-Scan Watchlist daily; the chain `batch_complete` →
  `scan_library` → `start_database_update` → `sync_downloaded_playlists`; Full Cleanup every 12 h, 15 min after start
  (`SoulSync:core/automation_engine.py:245-249`), which deletes everything in the quarantine folder with no age rule
  (`SoulSync:core/library/cleanup.py:34-55`). Only Weekly Cleanup ships off (`SoulSync:core/automation_engine.py:225-236`).
  Of the automation routes only the master toggle is `@admin_only` (`SoulSync:api/automations.py:73-77`).
- **Webhooks.** Inbound: only `POST /api/v1/request` (API key), which also emits `webhook_received`
  (`SoulSync:api/request.py:391-410`). No Plex, Jellyfin or Navidrome webhook (*absence inferred*:
  `grep -rhn -o -E "route\(['\"][^'\"]*(webhook|hook|notify|callback|event)[^'\"]*" --include=*.py web_server.py api/`
  finds only OAuth callbacks, `test-notify` and `listening-events`). Outbound: the request's `notify_url` callback (any
  http(s) URL, 10 s timeout, `SoulSync:api/request.py:121-150`, `SoulSync:api/request.py:369-373`) and the automation
  "then" steps: Discord, Pushbullet, Telegram, ntfy, Gotify and a generic webhook with headers and a payload template
  (`SoulSync:core/automation/blocks.py:638-657`, `SoulSync:core/automation_engine.py:1868-2086`). In-app notices are
  socket.io toasts per profile (`SoulSync:core/profile_notify.py:1-25`). No Web Push (*absence inferred*:
  `grep -rn -i -E "pywebpush|vapid|pushManager|showNotification"` finds nothing outside node_modules).

### A request from the phone

Who may download: profile 1 always; others by `can_download`, default True (`SoulSync:core/permissions.py:17-26`); the
Teen, Kids and Guest presets ship with it off (`SoulSync:webui/static/init.js:3080-3083`). For such a "member" the UI
hides download buttons **with CSS only** (`SoulSync:webui/static/style.css:41860-41882`) and relabels "Add to Wishlist"
as "Request" (`SoulSync:webui/static/wishlist-tools.js:963-964`).

**(a) A search in the UI.** The default search queries metadata catalogs plus the local library: one primary source at once, the
alternates fetched by the browser (`SoulSync:core/search/orchestrator.py:1-13`). The sources a search may name are
`spotify, itunes, deezer, discogs, hydrabase, musicbrainz, amazon, jiosaavn, bandcamp`
(`SoulSync:core/search/orchestrator.py:33-35`); the alternates are iTunes, Deezer, Amazon, MusicBrainz and YouTube
videos, plus Spotify, Discogs and Hydrabase only when configured (`SoulSync:core/search/orchestrator.py:229-256`). A basic mode searches the download sources directly, Soulseek included
(`SoulSync:web_server.py:6298-6325`); its file pick posts `POST /api/download`, which is permission-checked
(`SoulSync:web_server.py:6971-6976`). A catalog card opens one dialog with two buttons
(`SoulSync:webui/static/shared-helpers.js:1877-1886`):

```
album/track card → openSearchAlbum / openSearchTrack          webui/src/routes/search/-search.actions.ts:208-297
  ├─ "Begin Analysis" → POST /api/playlists/enhanced_search_album_<id>/start-missing-process
  │     {tracks, is_album_download, album_context, …}          webui/static/downloads.js:1850-1875
  │   → start_missing_tracks_process                           web_server.py:19291
  │   → in-memory download_batches[batch_id] + sync-history row web_server.py:19397-19457
  │   ⇒ analysis then downloads, at once                       web_server.py:19512-19517
  └─ "Add to Wishlist" / "Request" → one POST per track: /api/add-album-to-wishlist
        {track, artist, album, source_type:'album', …}         webui/static/wishlist-tools.js:1539-1556
      → add_album_track_to_wishlist (skips owned tracks)       core/wishlist/routes.py:790-876
      → INSERT OR REPLACE INTO wishlist_tracks (…profile_id…)  database/music_database.py:15766-15773
      ⇒ waits for Auto-Process Wishlist (30 min)               core/automation_engine.py:76-83
      member: row has request_status NULL = pending            database/music_database.py:27469-27478
        → admin: POST /api/requests/music/approve              api/music_requests.py:247-266
        → UPDATE wishlist_tracks SET request_status='approved' database/music_database.py:27565-27585
        → INSERT music_requests (status 'approved')            api/music_requests.py:259-263
        ⇒ still waits for the 30-min run                       core/wishlist/processing.py:1076-1091
```
(All paths in the flow are `SoulSync:` paths.) The record is a `wishlist_tracks` row per track; a member's request has
no table of its own, and `music_requests` records only outcomes, `approved | available | declined | removed`
(`SoulSync:database/music_database.py:27479-27496`, `SoulSync:core/requests/music.py:1-12`). `approved` becomes
`available` lazily, when someone lists requests or an open page polls the nav badge (every 60 s)
(`SoulSync:api/music_requests.py:95-118`, `SoulSync:api/music_requests.py:145-148`,
`SoulSync:api/music_requests.py:204-217`, `SoulSync:webui/static/core.js:805-806`). Read from code: `start-missing-process` calls no `check_download_permission()`
(`sed -n 19291,19518p web_server.py | grep -nE "perm|denied|403|can_download"` matches only `permanently_failed_tracks`),
and the page gate covers five other API prefixes, not `/api/playlists` (`SoulSync:core/permissions.py:94-100`), so a member
who calls it directly could likely skip approval (*unverified* at runtime: would be verified by POSTing to the route as a
member profile with downloads off). Albums and playlists go in whole: the dialog
sends every checked track (`SoulSync:webui/static/wishlist-tools.js:1412-1421`), and the Requests page groups rows back
into album or track asks (`SoulSync:core/requests/music.py:50-99`).

**(b) A pasted link.** Two parsers, neither complete:

```
search bar, single http(s) token or MBID → POST /api/enhanced-search/by-id        webui/src/routes/search/-search.api.ts:109-117
  → parse_metadata_identifier: open.spotify.com, spotify:, music.apple.com, deezer.com,
    musicbrainz.org, discogs.com; keyword album|release|release-group|master → album,
    track|recording|song → track, artist → artist                                core/search/by_id.py:53-56, 83-91
  → one search card → flow (a)                                                    webui/src/routes/search/-ui/search-page.tsx:181-203
  playlist URL → no keyword → hint "Paste a full link …"                          core/search/by_id.py:305-308
Sync page "Paste a link" (playlist or album)                                      webui/src/routes/sync/-ui/add-playlist-sheet.tsx:121
  → Spotify POST /api/spotify/parse-public (regex playlist|album only)            api/source_playlists.py:3482; core/spotify_public_scraper.py:39-42
  → Apple POST /api/itunes-link/parse; YouTube POST /api/youtube/parse; Deezer GET /api/deezer/playlist/<id>
                                                                                  api/source_playlists.py:3730, 4216, 2528-2540
  → discovery (match each row) → same dialog: Begin Analysis | Add to Wishlist    webui/static/sync-services.js:1150-1153
```
(Again `SoulSync:` paths.) So a Spotify **playlist** link works only on the Sync page, a Spotify **track** link only in
the search bar, and Tidal links nowhere (`SoulSync:core/search/by_id.py:45-48`). The records are the same as in (a): an
in-memory batch for Begin Analysis, `wishlist_tracks` rows for Add to Wishlist.

**(c) A share sheet, bookmarklet or Shortcut.** None in the code. The manifest has no `share_target`
(`SoulSync:webui/static/manifest.json:1-37`); *absence inferred*:
`grep -rln "share_target\|navigator\.share"` and
`grep -rln "iOS Shortcut\|Siri\|Tasker\|intent://\|android\.intent\|bookmarklet"`, each with
`--include=*.json --include=*.js --include=*.ts --include=*.tsx --include=*.html --include=*.py`, find nothing outside
node_modules. What exists instead:

```
iOS Shortcut / bot (built by the user) → POST /api/v1/request {query, title?, artist?, duration_ms?, notify_url?}
    Authorization: Bearer <admin key>                                api/request.py:345-374; api/auth.py:166-178
  → _pending_requests[uuid] status 'queued' (memory, 1 h)            api/request.py:20-25, 377-389
  → thread: download_orchestrator.search_and_download_best(query)    api/request.py:272-341
  ⇒ ONE track, downloaded now, no wishlist, no approval; 202 {request_id}   api/request.py:426-430
  → GET /api/v1/request/<id>: queued → searching → downloading → completed | not_found | failed
                                                                     api/request.py:432-462
```
The README offers it "for Discord bots and shortcuts" (`SoulSync:README.md:322`); it takes a free-text query, not a
link. Other external intakes: MCP `request_album` puts a whole album on the wishlist (`SoulSync:api/mcp.py:67-101`), and
the Lidarr API sends album requests to a configured profile's wishlist, through the approval queue when that profile
cannot download (`SoulSync:api/lidarr_compat.py:49-61`). The "SoulSync Companion" browser extension (Chrome/Firefox, in
a separate repo, `SoulSync:README.md:332-334`) is desktop-only. Server comments name two endpoints it calls,
`/api/image-proxy` (`SoulSync:api/auth.py:265-267`, `SoulSync:api/discover_routes.py:3296`) and
`/api/mirrored-playlists/resolve` (`SoulSync:api/mirrored_playlists.py:482`, `SoulSync:api/mirrored_playlists.py:502-503`),
reached with an API key on non-v1 paths (`SoulSync:api/auth.py:284-287`) and CORS on every `/api/*` path
(`SoulSync:core/security/cors.py:1-10`, `SoulSync:core/security/cors.py:39-41`); the full list is *unverified* (its code
is not in the clone; reading the soulsync-extension repo would verify it). Chat
`/want` posts to Soulseek rooms, not to the local queue (`SoulSync:webui/static/chat.js:7082-7083`).

What the requester sees afterwards: a Requests page with a badge polled every 60 s
(`SoulSync:webui/static/core.js:805-806`), socket toasts on approve/decline/arrival
(`SoulSync:core/profile_notify.py:41-64`), and whatever notifications the user wires into automations. Nothing reaches
a closed phone app (no Web Push, above).

### Phone fit

- **Responsive: yes, by a dedicated stylesheet.** Viewport
  `width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover`
  (`SoulSync:webui/index.html:6`). `webui/static/mobile.css` (4,617 lines, "overrides for ≤768px",
  `SoulSync:webui/static/mobile.css:1-4`) is linked after `style.css` (`SoulSync:webui/index.html:98`) and holds 43
  `@media` rules: `max-width: 768px` ×27 (first at `SoulSync:webui/static/mobile.css:79`), `480px` ×7
  (`SoulSync:webui/static/mobile.css:1787`), `hover: none` ×3 (first at
  `SoulSync:webui/static/mobile.css:2091`), and one each at 1024 px (`SoulSync:webui/static/mobile.css:3157`), 720 px
  (`SoulSync:webui/static/mobile.css:4452`), 561-768 px (`SoulSync:webui/static/mobile.css:4463`), 340 px
  (`SoulSync:webui/static/mobile.css:4478`), 640 px (`SoulSync:webui/static/mobile.css:4613`), and `max-height: 500px`
  (`SoulSync:webui/static/mobile.css:3733`). The top-level
  `webui/static/*.css` files hold 372 `@media` rules (242 in `style.css`, 76,604 lines); `index.html` holds none.
- Navigation on a phone is a hamburger (`SoulSync:webui/static/mobile.css:10-28`) and a 280 px slide-in drawer
  (`SoulSync:webui/static/mobile.css:166-199`) with tap-vs-drag detection (`SoulSync:webui/static/init.js:4407-4446`); no
  bottom tab bar (*absence inferred*: `grep -nE 'bottom-nav|bottom-tab|tab-bar|tabbar' webui/static/mobile.css
  webui/static/style.css webui/index.html` finds only Settings' `.stg-tabbar`). One safe-area rule
  (`SoulSync:webui/static/mobile.css:3469`). Playwright tests a download dialog at 393×852 and 320×568
  (`SoulSync:webui/tests/download-modal-mobile.spec.ts:16-19`).
- **Installable: yes on paper.** `<link rel="manifest">` (`SoulSync:webui/index.html:91`), `apple-touch-icon`
  (`SoulSync:webui/index.html:93`), `theme-color` from the user's accent (`SoulSync:webui/index.html:92`); the manifest is
  `display: standalone`, `start_url ../`, 192/512 `any` + `maskable` icons (`SoulSync:webui/static/manifest.json:5-36`).
  A real service worker `sw.js` (218 lines) registers on load (`SoulSync:webui/static/init.js:3887-3892`), caches images
  cache-first and `/static/*` stale-while-revalidate, passes HTML and API through, and has no offline page, push or
  share handler (`SoulSync:webui/static/sw.js:1-26`, `SoulSync:webui/static/sw.js:93-111`). It is skipped on non-secure
  origins (`SoulSync:webui/static/init.js:3881-3886`), so install needs HTTPS. No `apple-mobile-web-app-*` meta
  (*absence inferred*: `grep -nE 'apple-mobile-web-app' webui/index.html`).
- **Not provable from code, all *unverified*:** whether iOS Safari honours `user-scalable=no` (it blocks pinch-zoom on a
  dense UI where it is honoured); whether the fixed hamburger overlaps page headers; notch and home-bar overlap beyond
  the one safe-area rule; how fast ~90 scripts + the React bundle + 76k lines of CSS load on a phone; whether iOS shows
  the standalone app correctly without the Apple meta tags. Each would be verified by loading the UI on Michael's
  iPhone, in Safari and installed to the home screen.

## How ours does it

- **The API, `crates/service.py`.** Stdlib `BaseHTTPRequestHandler` on a `ThreadingHTTPServer`
  (`ours:crates/service.py:25`, `ours:crates/service.py:508-513`); `_route` serves `web/` for any non-`api` path
  with a traversal guard and sends the rest to `_api` (`ours:crates/service.py:385-410`), a hand-written `if head == …`
  chain (`ours:crates/service.py:428-497`), GET and POST only (`ours:crates/service.py:499-503`). "Any client (this web
  UI, a future native app, the CLI) talks to this API; only this process holds the Navidrome credentials"
  (`ours:crates/service.py:1-6`).
  - 14 GET routes (`ours:crates/service.py:430-464`): status, playlists, one playlist with crate status and its
    `wanted` rows, crates, wanted, one wanted row (`ours:crates/service.py:441-442`), proposals, identity, events, **library-only** `search` through Navidrome
    (`ours:crates/service.py:159-161`), stream-tier, `stream/<id>`, `download/<id>` (Navidrome's raw original, not a
    Soulseek download) and `cover/<id>`.
  - 12 POST routes (`ours:crates/service.py:465-496`): crate switch, tier, add songs, create playlist, wanted
    preview / approve / play-now, proposals accept / decline, identity choice, reconcile, stream-tier.
  - **Downloads:** only `approve` and `play-now` lead to one, and both only record an approval row
    (`ours:crates/service.py:233-279`); downloads happen in the worker, which "downloads only what has been approved"
    (`ours:sourcing/worker.py:1`), or from a shell with `fetch --approve` (`ours:docs/architecture.md:362`).
    Preview searches slskd and caches the pick behind an opaque token with no peer name
    (`ours:crates/service.py:216-231`). D7: "Automatic downloads only after Michael has approved at least one manual
    download and said go" (`ours:docs/specs/2026-10-13-next-session-design.md:61`).
  - **Auth:** none. The service binds loopback by default (`ours:crates/service.py:58-59`), compose publishes
    `127.0.0.1:4580` (`ours:deploy/compose.yml:45`) and `tailscale serve` fronts it for the phone
    (`ours:crates/service.py:8-12`). Approvals are recorded as `"michael"` (`ours:crates/service.py:250`). Known
    limit 22: "anyone on the tailnet can approve", stream redirects carry the admin token + salt
    (`ours:docs/architecture.md:545-546`).
- **Streaming (D19 → D25).** `GET /api/stream/<id>?tier=<t>` answers **302** to a freshly signed Navidrome `stream`
  URL (`ours:crates/service.py:454-459`, `_redirect` at `ours:crates/service.py:378-383`) under client name
  `dj-crates-web` (`ours:crates/service.py:40`); tier `server` sends no format or bitrate, so Navidrome's player
  profile decides; `low|medium|high` are opus 64/96/160, `crate` is raw; "Audio never passes through our process"
  (`ours:docs/architecture.md:229-236`; that section still cites `service.py:288-293`, now stale). D25 moved stream
  quality to the client and Navidrome, keeping our presets as notes for a future client
  (`ours:docs/specs/2026-10-17-amperfy-pivot.md:20`). Amperfy talks Subsonic to Navidrome directly
  (`ours:docs/architecture.md:47-48`) with its own account; we never touch the `amperfy` account's playlists
  (`ours:crates/playlist_edit.py:38`).
- **The web client, `web/`.** A phone web app without a service worker. Viewport
  `width=device-width, initial-scale=1, viewport-fit=cover` (`ours:web/index.html:5`), Apple
  `apple-mobile-web-app-capable` / status-bar / title meta (`ours:web/index.html:7-9`), a manifest link
  (`ours:web/index.html:10`) to `display: standalone`, `start_url "/"` and one SVG icon
  (`ours:web/manifest.webmanifest:1-9`); no `share_target`, no PNG icon. No service worker (*absence inferred*:
  `grep -rnE 'serviceWorker|service-worker|sw\.js' web/` finds nothing). Widths: `main` is capped at 860 px
  (`ours:web/app.css:21`); breakpoints at 560 px (`ours:web/app.css:72`) and 420 px (`ours:web/app.css:94`); 40 px
  buttons and 44 px tabs (`ours:web/app.css:9`, `ours:web/app.css:17`); a fixed bottom player padded by
  `env(safe-area-inset-bottom)` (`ours:web/app.css:56`); a comment sizing rows for a 320 px phone
  (`ours:web/app.css:97`). `app.js` sets no widths (*absence inferred*: `grep -nE 'style\.|width|innerWidth' web/app.js`
  finds nothing).
  - Five tabs (`ours:web/index.html:24-30`): Playlists (crate switch, tracks, a "Not in the library yet" list with
    play-now, `ours:web/app.js:94-112`), Wanted (Proposals Swap/Keep, Preview → Approve, Re-check,
    `ours:web/app.js:359-376`), Search (library only, play-only, `ours:web/app.js:382-390`), Log, Identity. No playlist
    editing in the UI beyond Swap, which edits one slot through the guarded `proposals.apply`
    (`ours:web/app.js:151`, `ours:crates/service.py:320-325`); the crate toggle writes `crates.db` only under
    `CRATES_OWNER=app` (`ours:web/app.js:114-119`, `ours:crates/reconcile.py:228-229`).
  - The player is one `<audio>` whose `src` is `/api/stream/<id>?tier=` (`ours:web/app.js:503-513`), no queue.
    Play-now primes `<audio>` with a silent WAV on the tap (`ours:web/app.js:196-203`) and polls the row from 2 s to
    10 s, paused while hidden, for up to 10 min (`ours:web/app.js:229-255`).
- **Requests today and planned (S3).** Today a Spotify link enters only through the CLI (`import-playlist <url>`,
  `ours:docs/architecture.md:365`). S3 is a client-agnostic request API, "No UI in this run (concern B is open)",
  drivable by "the current web client, Amperfy's successor, a phone shortcut"
  (`ours:docs/specs/2026-10-22-downloads-and-requests.md:188-190`):
  - S3-01 `POST /api/requests {"url"}`: Spotify track → one row, album → an album request, playlist → imported with
    `--merge`; also `{"mbReleaseId"|"mbRecordingId"}` from a catalog pick; creating downloads nothing
    (`ours:docs/specs/2026-10-22-downloads-and-requests.md:191-196`).
  - S3-02 `GET /api/catalog/search?q=&kind=album|track`: MusicBrainz behind a provider interface, Spotify next through
    Michael's own developer app (`ours:docs/specs/2026-10-22-downloads-and-requests.md:197-206`).
  - S3-03 list / show / preview / approve; approve = S2-05; "Same auth and exposure as today's `/api/*`"
    (`ours:docs/specs/2026-10-22-downloads-and-requests.md:207-211`).
  - S3-04 the same as a CLI, S3-05 `docs/api.md`, S3-06 a Spotify Client Credentials capture script
    (`ours:docs/specs/2026-10-22-downloads-and-requests.md:212-221`).
  - Out of scope: client UI until B is answered; other platforms' links ask first; embedded credentials never
    (`ours:docs/specs/2026-10-22-downloads-and-requests.md:232-234`). No item plans a share target or a Shortcut
    (*absence inferred*: `grep -rniE 'Shortcut|share.sheet|share_target' docs/specs docs/next-todos.md web` finds only the
    B option text and its question, `ours:docs/specs/2026-10-22-soulsync-review.md:35`,
    `ours:docs/specs/2026-10-22-soulsync-review.md:144`, and "a phone shortcut" above).
- **No MCP, no webhooks, no profiles.** Automation is the worker loop: a 30 s tick (`ours:sourcing/cli.py:272`;
  play-now approvals first, other approvals after reconcile and re-checks), reconcile every 600 s, `verify` re-checks
  every 300 s, playlist export every 300 s (`ours:sourcing/worker.py:8-37`); a health push every
  10 min to Gatus (`ours:deploy/systemd/dj-health-push.timer:5-6`), which alerts through ntfy
  (`ours:deploy/compose.yml:119-125`).

## The difference that matters

The B options are listed in the review spec (`ours:docs/specs/2026-10-22-soulsync-review.md:34-37`); the pivot spec's
"What Amperfy cannot do" list is what any of them has to deliver (`ours:docs/specs/2026-10-17-amperfy-pivot.md:71-88`).

**B1: Amperfy + our web client as a phone web app + an iOS share-sheet Shortcut.** SoulSync cannot be Amperfy's
server (no Subsonic server, above); it would sit beside Navidrome as a second web app. Its UI is a 24-page admin
console (`SoulSync:webui/src/platform/shell/route-manifest.ts:29-61`) that is responsive and installable with a real
service worker, which ours lacks; but its request paths fail D7. "Begin Analysis" downloads at once
(`SoulSync:web_server.py:19512-19517`). "Add to Wishlist" is picked up by a 30-minute automation that ships enabled
(`SoulSync:core/automation_engine.py:76-83`). The only Shortcut-shaped endpoint, `POST /api/v1/request`, downloads the
best hit for a free-text query with an admin key and no approval (`SoulSync:api/request.py:272-341`). Its member
approval is per profile, not per download, and is enforced in the scheduler rather than at `start-missing-process`
(read from code, above). Neither project has a `share_target`. For B1 the useful shape is ours: S3-01 takes the link
itself (track, album or playlist in one endpoint, where SoulSync splits them over two parsers that each miss one kind,
`SoulSync:core/search/by_id.py:305-308`, `SoulSync:core/spotify_public_scraper.py:39-42`), and S3-03 keeps
preview/approve. What SoulSync adds for B1 is a checklist for the web app: a service worker so iOS/Android treat it as
an app, PNG icons (ours has only an SVG, `ours:web/manifest.webmanifest:8`), and a way to tell the phone a request is
done. SoulSync stops at socket toasts and user-wired ntfy/Discord; ours already has ntfy through Gatus
(`ours:deploy/compose.yml:119-125`). Running SoulSync's UI for B1 would also bring its playlist sync and deletes
(07-filing-library.md) and a second tagger into the library, which the B1 option does not need.

**B2: a Subsonic proxy inside crates, in octo-fiesta's style.** SoulSync has no Subsonic server, so there is nothing to
adopt. Two pieces are relevant patterns. Its Navidrome proxy forwards `Range` upstream and streams the body through
unbuffered (`SoulSync:web_server.py:12693-12723`), which is what a proxy in crates must do for seeking (ours today
answers 302 and never carries audio, `ours:crates/service.py:454-459`). Its "play a track you don't own" downloads the
whole file before playing (`SoulSync:core/streaming/prepare.py:114-123`), YouTube by default
(`SoulSync:core/settings.py:569`), and its queue prefetch files up to 250 unowned tracks into the library without a
per-track approval (`SoulSync:web_server.py:6842-6858`). That is the octo-fiesta idea (a Subsonic client sees
"missing" tracks and playing one fetches it; octo-fiesta's own behaviour is *unverified* here: its source is in
neither the clone nor ours, and reading its stream handler would verify it). It breaks D7 and D24
(a YouTube re-encode as the copy) as SoulSync does it. Ours keeps the same idea as play-now: one tap = one approved
low-tier copy (`ours:crates/service.py:253-279`). A B2 proxy would have to turn a Subsonic `stream` of a missing id into
that approval, not into a silent download.

**B3: a native fork (Cassette/Minidisc, or Yuzic).** SoulSync has no native app and no Subsonic surface, so a native
Subsonic client would still talk to Navidrome and reach SoulSync only through `/api/v1` (112 key-gated routes,
`Support/API.md`) or MCP. The lesson is its API, not its app: a documented, key-scoped API (`SoulSync:api/auth.py:40-101`)
with request status a client can poll (`SoulSync:api/request.py:432-462`). Ours plans the same through S3-03 and S3-05,
but with no auth: "Same auth and exposure as today's `/api/*`"
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:211`), i.e. anyone on the tailnet can approve
(`ours:docs/architecture.md:545-546`). A native client on the tailnet does not change that risk; a client off the
tailnet would need a key. SoulSync's own defaults (no login, an admin key that downloads at once) are no better.

**Goal C (requests from the phone) in one line each.** Search bar over the common catalogs: SoulSync has it (about five catalogs on
an unconfigured install, more with Spotify/Discogs configured, plus the library,
`SoulSync:core/search/orchestrator.py:229-256`), ours plans MusicBrainz first, then Spotify
through Michael's app (S3-02). Paste a link: SoulSync partly (two parsers, no playlist in search, no Spotify track on the
Sync page), ours plans one endpoint (S3-01). Share a link: neither. Approval before any download: ours (D7, S3-03);
SoulSync only for members, only in the scheduler.

## Worth taking?

- **Take (adapt) for S3-01:** the link-parsing table from `parse_metadata_identifier`, path keyword → kind
  (`album|release|release-group|master`, `track|recording|song`, `artist`, `SoulSync:core/search/by_id.py:83-91`), plus
  `spotify:` URIs and Apple's `?i=` track form (`SoulSync:core/search/by_id.py:83-155`). Add `playlist` (which SoulSync's
  search-bar parser lacks) so one endpoint takes all three kinds; Spotify only in this run (the spec asks first for the
  others, `ours:docs/specs/2026-10-22-downloads-and-requests.md:233`).
- **Take (adapt) for the web client under B1:** a minimal service worker, a reduced form of SoulSync's (which caches
  images cache-first, `/api/image-proxy` included, and `/static/*` stale-while-revalidate,
  `SoulSync:webui/static/sw.js:93-111`): static files only, every other `/api/*` call passed through, 192/512 PNG icons, and a manifest `share_target` that POSTs a
  shared URL to S3-01 (neither project has one, `SoulSync:webui/static/manifest.json:1-37`,
  `ours:web/manifest.webmanifest:1-9`; Android honours it, iOS needs the Shortcut, *unverified* until tried on
  Michael's phone). Small, and it serves B1 without a native app.
- **Take (learn) for S3-03:** request states a client can show, `pending → approved → available | declined | removed`,
  with an "available" check against the library (`SoulSync:core/requests/music.py:20`,
  `SoulSync:core/requests/music.py:102-115`). Ours should push the "available" change (ntfy) rather than wait for an open
  page's badge poll to sweep it.
- **Take (learn) for B2:** `Range` passthrough when a proxy carries audio (`SoulSync:web_server.py:12693-12723`).
- **Don't take:** the UI itself (three front-end layers, a Node build, a CDN dependency at runtime); auth off by
  default and the `/api/v1` login exemption with key bootstrap; admin-by-default API keys that download at once;
  `POST /api/v1/request` without approval; download-to-play and queue prefetch without approval (D7, D24); automations
  that delete or run scripts, shipped enabled; MCP download tools with no confirmation step.

**Verdict:** no. SoulSync's UI and API cannot serve as any of the three B options: it has no Subsonic server for
Amperfy or a native client, its phone story is an installable admin console, and every phone request path either
downloads at once or on a 30-minute timer, with approval only for restricted profiles. Ours has the better request
shape planned (S3: one link endpoint, preview, explicit approve); take its link-keyword table, a static-only service
worker plus a `share_target` for our web client, and its request status names.
