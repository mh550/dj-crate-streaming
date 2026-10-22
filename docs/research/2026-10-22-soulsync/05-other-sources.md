# 05 · Other sources (every non-Soulseek getter, its credentials and legal flag, and how the orchestrator chooses)

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed).
Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a claim
without one. Credentials are described by mechanism and `file:line` only; no key, app id, secret or cookie value is
reproduced here. The `**ToS/legal:**` flags are our reading of the cited mechanism, not legal advice:
`streaming rip` = the full stream of a streaming service saved as a file outside its own apps (own account or someone
else's proxy); `grey` = P2P / indexers / unofficial public proxies, where legality depends on what is shared;
`clean` = public metadata or a licensed path. Music only: the audiobook source order
(`SoulSync:core/settings.py:1025-1027`) and YouTube's video features are named here once and skipped.

## What SoulSync does

Eleven download sources are registered as plugins: amazon, soulseek, youtube, tidal, qobuz, hifi, deezer (legacy
alias `deezer_dl`), lidarr, soundcloud, torrent, usenet (`SoulSync:core/download_plugins/registry.py:182-196`). The
docstring above them still says "eight" (`SoulSync:core/download_plugins/registry.py:169`). Bandcamp and JioSaavn
are **not** plugins; they are metadata providers (below). Every plugin satisfies one structural protocol:
`is_configured()`, `check_connection()`, `search()` → (tracks, albums), and `download()` that returns a download id,
or `None` when the source "can't / won't handle this download" (`SoulSync:core/download_plugins/base.py:59-108`).
A plugin whose constructor raises is stored as `None` and skipped, so one broken source never stops the others
(`SoulSync:core/download_plugins/registry.py:100-111`). Every source that has a `download_path` writes into
Soulseek's download folder, so those files land in one tree (`SoulSync:core/download_orchestrator.py:138-155`).
Torrent and Usenet land in their downloader's save path instead, and post-processing copies the picked track out
(`SoulSync:core/downloads/post_processing.py:301-344`).

### Deezer

Download path `core/deezer_download_client.py` (1,374 lines), registered as `deezer`/`deezer_dl`
(`SoulSync:core/download_plugins/registry.py:191-192`); `core/deezer_client.py` is the separate public-API metadata
client (`SoulSync:core/deezer_client.py:406`). It logs in to Deezer's private web gateway (`gw-light.php`,
`deezer.getUserData`) with the user's **ARL** browser cookie, then gets a license token and, per track, a track
token (`SoulSync:core/deezer_download_client.py:207-231`, `SoulSync:core/deezer_download_client.py:775-777`). It
POSTs both to `media.deezer.com/v1/get_url` for a CDN URL in FLAC, MP3 320 or MP3 128
(`SoulSync:core/deezer_download_client.py:779-819`), and Blowfish-CBC-decrypts every third 2,048-byte chunk with a
per-track key derived from the track id and a **hard-coded secret** (`SoulSync:core/deezer_download_client.py:38`,
`SoulSync:core/deezer_download_client.py:1236-1274`; the code calls it "public knowledge"). Nothing is transcoded.
The tier comes from the global quality profile, and a refused tier steps down flac → mp3_320 → mp3_128 while
`deezer_download.allow_fallback` is on (a default that exists only in code,
`SoulSync:core/deezer_download_client.py:1194-1219`). **Credentials:** the ARL (`deezer_download.arl`, read at
`SoulSync:core/deezer_download_client.py:152`, encrypted at rest per `SoulSync:core/settings.py:110`).
`is_configured()` is a lazy network login (`SoulSync:core/deezer_download_client.py:354-375`). Embedded: the
Blowfish secret only; no app id. The same client also writes playlists back to the user's Deezer account through
the gateway, which its own code labels unofficial (`SoulSync:core/deezer_download_client.py:393-398`).
**ToS/legal:** streaming rip; it decrypts a subscription stream through a private gateway with a hard-coded key.

### Tidal

`core/tidal_download_client.py` (1,276 lines), on `tidalapi==0.8.11` (`SoulSync:requirements.txt:81`), registered
as `tidal` (`SoulSync:core/download_plugins/registry.py:185`); `core/tidal_client.py` is the metadata/playlist
client. It requests `openapi.tidal.com/v2/trackManifests/{id}` with `usage=DOWNLOAD`, `manifestType=HLS` and a format
of FLAC_HIRES, FLAC, AACLC or HEAACV1, authorised with the tidalapi session's bearer token
(`SoulSync:core/tidal_download_client.py:159-180`, `SoulSync:core/tidal_download_client.py:902-925`). It fetches the
HLS segments into one file (`SoulSync:core/tidal_download_client.py:1076-1126`) and, for FLAC, demuxes MP4 → .flac
with `ffmpeg -c copy`, with no re-encode and no DRM step (`SoulSync:core/tidal_download_client.py:989-1012`). Tiers
are hires 24/96, lossless 16/44.1, AAC 320 and AAC 96 (`SoulSync:core/tidal_download_client.py:131-156`). The chain
walks down to AAC 96 while `tidal_download.allow_fallback` is on (default on, in code,
`SoulSync:core/tidal_download_client.py:1058-1062`). **Credentials:** a device-code login (the user approves at
link.tidal.com) whose tokens are saved to `tidal_download.session`
(`SoulSync:core/tidal_download_client.py:451-469`, `SoulSync:core/tidal_download_client.py:396-404`, encrypted per
`SoulSync:core/settings.py:101`). `is_configured()` = tidalapi importable and session authenticated
(`SoulSync:core/tidal_download_client.py:511-515`). The metadata client needs the user's own developer app id and
secret instead (`SoulSync:core/settings.py:502-506`). Embedded: none in the clone. The session is built with
tidalapi's defaults (`SoulSync:core/tidal_download_client.py:260`); that tidalapi ships its own app client id is
*unverified* (the library is not in the clone; would be verified by reading `tidalapi.Session`'s config in the pinned
`tidalapi==0.8.11`, `SoulSync:requirements.txt:81`). Its own comment says bursts of download requests can draw
a 401/403 plus captcha ("bot-like behavior") that deauths the session
(`SoulSync:core/tidal_download_client.py:46-55`). **ToS/legal:** streaming rip; it saves full
`usage=DOWNLOAD` streams outside Tidal's apps on the user's own subscription.

### Qobuz

`core/qobuz_client.py` (1,436 lines), one class for metadata and download, registered as `qobuz`
(`SoulSync:core/download_plugins/registry.py:186`). It calls `track/getFileUrl` with `format_id` 5/6/7/27 (MP3 320,
FLAC 16/44.1, 24/96, 24/192), `intent=stream` and an MD5 `request_sig` over the method, params, timestamp and the
app secret (`SoulSync:core/qobuz_client.py:75-104`, `SoulSync:core/qobuz_client.py:1125-1153`). It then does a
plain GET of the returned URL, with no decryption and no ffmpeg (`SoulSync:core/qobuz_client.py:1283-1300`). A
30-second `sample` URL (no subscription, or region-locked) is refused (`SoulSync:core/qobuz_client.py:1258-1261`).
The chain hires_max → hires → lossless → mp3 runs while `qobuz.allow_fallback` is on (default on, in code,
`SoulSync:core/qobuz_client.py:1230-1252`). **Credentials:** a Qobuz email and password to `user/login`, or a pasted
browser `user_auth_token` (`SoulSync:core/qobuz_client.py:390-439`, `SoulSync:core/qobuz_client.py:468-484`).
They are stored with the app id and secret in `qobuz.session` (`SoulSync:core/settings.py:641-648`, encrypted per
`SoulSync:core/settings.py:103`). The docstring requires a paid subscription (`SoulSync:core/qobuz_client.py:11`),
and `is_configured()` = token, app id and secret all present (`SoulSync:core/qobuz_client.py:577-589`). Embedded:
nothing hard-coded, but the app id and secret are **scraped at runtime** from the web player's `bundle.js`
(`SoulSync:core/qobuz_client.py:216-351`), run on login when they are missing
(`SoulSync:core/qobuz_client.py:400-404`). The scrape regexes the app id, rebuilds candidate secrets from per-timezone
seed strings, and validates each with a real signed stream request (`SoulSync:core/qobuz_client.py:353-377`). It
throttles to 1 request/s process-wide (`SoulSync:core/qobuz_client.py:38-59`) and honours a 429's `Retry-After`
(`SoulSync:core/qobuz_client.py:1161-1164`).
**ToS/legal:** streaming rip; it impersonates the web player with a scraped secret and saves stream URLs, not
purchases.

### Amazon

`core/amazon_download_client.py` (498 lines), registered as `amazon`
(`SoulSync:core/download_plugins/registry.py:182`), although its own docstring says it is not wired in yet
(`SoulSync:core/amazon_download_client.py:3`). It talks to **T2Tunes**, a third-party REST proxy over the Amazon
Music catalogue (`SoulSync:core/amazon_client.py:1-17`), with `https://t2tunes.site` as the default instance
(`SoulSync:core/amazon_client.py:59`). `media-from-asin` returns a stream URL **and its AES decryption key**
(`SoulSync:core/amazon_client.py:837-871`). The client downloads the encrypted MP4 and runs
`ffmpeg -decryption_key … -c copy` to .flac, .opus or .eac3 (`SoulSync:core/amazon_download_client.py:280-320`,
`SoulSync:core/amazon_download_client.py:346-381`). `allow_fallback` (default on, in code,
`SoulSync:core/amazon_download_client.py:88`) only steps down the codec order flac → opus → eac3
(`SoulSync:core/amazon_download_client.py:43`, `SoulSync:core/amazon_download_client.py:252-264`). **Credentials:** none. `is_configured()` returns True
unconditionally (`SoulSync:core/amazon_download_client.py:111-114`); `amazon.base_url` and country are optional
(`SoulSync:core/amazon_client.py:301-322`). Embedded: none hard-coded; the key arrives per track from the proxy
(`SoulSync:core/amazon_client.py:844-845`). The public host "shut down for good (#1300)"
(`SoulSync:core/amazon_outage.py:64-66`), and the UI drops `amazon` from saved chains
(`SoulSync:webui/static/settings.js:2013-2016`). The plugin still reports itself configured against that dead
default. **ToS/legal:** streaming rip; the proxy hands out Amazon streams with their content keys from someone
else's access, with no subscription of the user's.

### HiFi

`core/hifi_client.py` (1,332 lines), registered as `hifi` (`SoulSync:core/download_plugins/registry.py:187`), and
also a metadata source (`SoulSync:core/metadata/source.py:845-873`). Its docstring: "Tidal-sourced FLAC … the API
instances handle Tidal credentials internally" (`SoulSync:core/hifi_client.py:4-6`). It sends hifi-api requests to
**seven hard-coded third-party instances** (`SoulSync:core/hifi_client.py:114-122`), seeded into the
`hifi_instances` table (`SoulSync:database/music_database.py:27958-27971`). It uses the first enabled instance and
rotates a failed one (timeout, 5xx, 403, 429) to the end (`SoulSync:core/hifi_client.py:386-395`,
`SoulSync:core/hifi_client.py:452-469`). Audio comes from Tidal `usage=DOWNLOAD` HLS manifests via the instance
(`SoulSync:core/hifi_client.py:792-806`, `SoulSync:core/hifi_client.py:1112-1160`), or a legacy direct-URL manifest
that is refused when encrypted (`SoulSync:core/hifi_client.py:512-522`). ffmpeg only demuxes
(`SoulSync:core/hifi_client.py:948-973`). Tiers are Tidal's (FLAC 24/96, FLAC 16/44.1, AAC 320, AAC 96,
`SoulSync:core/hifi_client.py:69-102`), and the chain walks down to AAC 96 with fallback on, the default
(`SoulSync:core/hifi_client.py:1061-1066`). Two preview guards (an HLS length under 85 % of the track,
`SoulSync:core/hifi_client.py:47`, and a manifest-seconds check) and a post-download decode plus FLAC-bitrate check exist because "previews fake the FULL length in
every header" (`SoulSync:core/hifi_client.py:847-859`, `SoulSync:core/hifi_client.py:1190-1212`). **Credentials:**
none; `is_configured()` = an instance is selected (`SoulSync:core/hifi_client.py:486-487`). Embedded: the instance
host list only, no keys. **ToS/legal:** streaming rip; it saves Tidal streams through anonymous proxies that hold
someone else's Tidal credentials.

### YouTube/yt-dlp

`core/youtube_client.py` (2,315 lines), with `youtube_cookies.py`, `youtube_errors.py`, `youtube_music_meta.py`,
`youtube_track_meta.py` and `ytdlp_update.py`, registered as `youtube`
(`SoulSync:core/download_plugins/registry.py:184`). Search goes first to the YouTube Music catalogue through
ytmusicapi (anonymous unless cookies are pasted), and otherwise to yt-dlp `ytsearch50:`
(`SoulSync:core/youtube_client.py:1345-1373`). Download is yt-dlp `extract_info(download=True)` with a three-step
retry ladder of player clients and cookies (`SoulSync:core/youtube_client.py:1817-1881`). Audio is always lossy
(Opus/AAC; tier selectors up to ~256 kbps, `SoulSync:core/youtube_client.py:184-212`). **By default it is
re-encoded to MP3 320** (`youtube.transcode: True`, `SoulSync:core/settings.py:1106-1115`), so a ~128-256 kbps
stream is filed and ranked as "MP3 320" (`SoulSync:core/youtube_client.py:227-260`). A 0.05-confidence band keeps a
better-encoded wrong recording from winning (`SoulSync:core/youtube_client.py:166-181`), and a small format probe
(`refresh_claimed_quality`, at most 3 player fetches) looks for the best encode of the right one
(`SoulSync:core/youtube_client.py:152`, `SoulSync:core/youtube_client.py:1475`). **Credentials:** none required; optional browser cookies or a
pasted cookies file (`youtube.cookies_browser`, `SoulSync:core/settings.py:1107`;
`SoulSync:core/youtube_cookies.py:113-136`), which unlock Premium formats. `is_configured()` = yt-dlp importable and
ffmpeg present (`SoulSync:core/youtube_client.py:867-877`, delegating to
`SoulSync:core/youtube_client.py:717-738`). That ffmpeg check can **download a static ffmpeg from
GitHub at runtime with no checksum** (`SoulSync:core/youtube_client.py:1001-1080`). yt-dlp itself updates through an
admin `pip install -U` on the nightly channel (`SoulSync:core/ytdlp_update.py:33-54`). Embedded: none (cookie names
only). YouTube is also the default playback source and legacy hybrid secondary
(`SoulSync:core/settings.py:567-569`). **ToS/legal:** streaming rip; it saves an ad-supported/Premium service's
streams outside its apps, optionally with the user's account cookies.

### SoundCloud

`core/soundcloud_client.py` (708 lines), registered as `soundcloud`
(`SoulSync:core/download_plugins/registry.py:194`), despite a docstring that says it is intentionally not wired in
(`SoulSync:core/soundcloud_client.py:11-13`). It runs entirely through yt-dlp's SoundCloud extractor: `scsearchN:`,
direct and private-share URLs, and `bestaudio/best` with no postprocessor
(`SoulSync:core/soundcloud_client.py:220-330`, `SoulSync:core/soundcloud_client.py:520-535`). It is anonymous only,
"128 kbps MP3 for most public tracks", no Go+ 256 AAC, no FLAC (`SoulSync:core/soundcloud_client.py:15-22`), and
every result is stamped `bitrate=128, quality='mp3'` whatever yt-dlp picks
(`SoulSync:core/soundcloud_client.py:369-375`). Its only client-level preview guard is a 100 KB floor
(`SoulSync:core/soundcloud_client.py:560-572`); a 30 s 128 kbps preview is about 480 KB (hand estimate), so it
passes there and is left to the import pipeline's duration-agreement check, which needs a known expected length
(`SoulSync:core/imports/file_integrity.py:20-24`). **Credentials:** none; `is_configured()` = yt-dlp importable
(`SoulSync:core/soundcloud_client.py:159-169`). Embedded: no SoundCloud client id in the clone (grep finds none
outside tests); obtaining one is left to yt-dlp's extractor, *unverified* how (yt-dlp is not in the clone; would be
verified by reading the SoundCloud extractor of the `yt-dlp>=2026.3.17` it requires, `SoulSync:requirements.txt:63`). **ToS/legal:** streaming rip; it
saves stream transcodes through yt-dlp, not the uploader's download button.

### Bandcamp

`core/bandcamp_client.py` (589 lines) and `core/bandcamp_worker.py` (560): **metadata only, no audio**. It is not in
the plugin registry (`SoulSync:core/download_plugins/registry.py:41-51`) and is used through the metadata registry
(`SoulSync:core/metadata/registry.py:283-289`). It reads Bandcamp's public autocomplete JSON, release pages' JSON-LD
and the artist `/music` grid (`SoulSync:core/bandcamp_client.py:225-275`, `SoulSync:core/bandcamp_client.py:315-326`).
The worker writes label, release date, genres and track count into the library DB
(`SoulSync:core/bandcamp_worker.py:416-480`). It is gated by `experimental.bandcamp_enabled`, off by default
(`SoulSync:core/metadata/registry.py:50-70`). **Credentials:** none ("No API key required",
`SoulSync:core/bandcamp_client.py:222-223`); embedded: none. **ToS/legal:** clean; it reads public metadata and
fetches no audio.

### JioSaavn

`core/jiosaavn_client.py` (597 lines) and `core/jiosaavn_worker.py` (680): **metadata only, no audio**. It is not a
plugin and is used by the metadata registry (`SoulSync:core/metadata/registry.py:279-281`). It sends GETs to a
third-party unofficial JioSaavn proxy (`DEFAULT_BASE_URL`, `SoulSync:core/jiosaavn_client.py:61`), and only to
search, song, album and artist endpoints (`SoulSync:core/jiosaavn_client.py:7-15`). `preview_url` exists on its
`Track` but is never filled (`SoulSync:core/jiosaavn_client.py:144`). It is gated by `experimental.jiosaavn_enabled`,
off by default (`SoulSync:core/settings.py:1125-1128`). **Credentials:** none; `is_authenticated()` is always True
(`SoulSync:core/jiosaavn_client.py:274-276`); embedded: the proxy host only. **ToS/legal:** grey; no audio, but the
metadata comes through an unofficial scraper of JioSaavn's private API.

### Torrent

`core/download_plugins/torrent.py` (1,483 lines) and `torrent_stall.py`, with adapters for qBittorrent,
Transmission, Deluge and aria2 under `core/torrent_clients/` (`SoulSync:core/torrent_clients/__init__.py:36-60`),
registered as `torrent` (`SoulSync:core/download_plugins/registry.py:195`). Per track it searches Prowlarr with
`protocol='torrent'`, turns each release into a candidate (format guessed from the title and category, seeders as
"free slots"), and prefers the .torrent over the magnet (`SoulSync:core/download_plugins/torrent.py:200-269`).
SoulSync fetches the .torrent itself and pushes the bytes to the client, falling back to the magnet, then to the raw
URL (`SoulSync:core/torrent_clients/base.py:294-339`). When the quality profile disables fallback it vetoes on the
title before grabbing and again on the .torrent's file list
(`SoulSync:core/download_plugins/torrent.py:346-356`, `SoulSync:core/download_plugins/torrent.py:402-421`). After
seeding/completed it walks the save path and extracts archives
(`SoulSync:core/download_plugins/torrent.py:546-602`), and post-processing then picks the requested track out of the
release or fails (`SoulSync:core/downloads/post_processing.py:301-344`). Album bundles go through
`pick_best_album_release`'s gate order (album relevance, artist, format, size vs claimed quality, seeders, a 40 MB-3 GB
window, profile rank; `SoulSync:core/download_plugins/album_bundle.py:431-488`). By default grabs **seed forever**
(`SoulSync:core/settings.py:713-720`). **Credentials:** Prowlarr URL and API key plus the client's URL/user/password
(`SoulSync:core/settings.py:681-705`); `is_configured()` = both configured
(`SoulSync:core/download_plugins/torrent.py:178-182`). Embedded: none; indexer URLs carry Prowlarr's key and are kept
out of logs (`SoulSync:core/torrent_clients/base.py:323-337`). **ToS/legal:** grey; BitTorrent through the user's
indexers, legality per release, and it uploads (seeds) by default.

### Usenet/Prowlarr

`core/download_plugins/usenet.py` (710 lines), `core/prowlarr_client.py` (664) and `prowlarr_throttle.py`, with
SABnzbd and NZBGet adapters under `core/usenet_clients/` (`SoulSync:core/usenet_clients/__init__.py:33-49`),
registered as `usenet` (`SoulSync:core/download_plugins/registry.py:196`). Prowlarr is asked over `/api/v1/*` with the
key in `X-Api-Key` (`SoulSync:core/prowlarr_client.py:618-622`), in music categories 3000/3010/3040/3050/3060
(`SoulSync:core/prowlarr_client.py:81-87`), with video and audiobook categories excluded on purpose
(`SoulSync:core/prowlarr_client.py:54-59`). Searches share one
process-wide budget: a 2 s gap and 20 searches a minute (`SoulSync:core/prowlarr_throttle.py:35-39`). The NZB URL goes
straight to the downloader (`SoulSync:core/download_plugins/usenet.py:278`), and unpacking is left to SAB/NZBGet, with
SoulSync extracting only what is left over (`SoulSync:core/download_plugins/usenet.py:10-12`). It has the same title veto and the same album picker,
without the seeder gate (`SoulSync:core/download_plugins/usenet.py:225-238`,
`SoulSync:core/download_plugins/usenet.py:620-645`). **Credentials:** the Prowlarr URL and key, plus SAB's URL and key
or NZBGet's URL, user and password (`SoulSync:core/usenet_clients/sabnzbd.py:74-75`,
`SoulSync:core/usenet_clients/nzbget.py:72-73`); the user's own Usenet provider sits behind the downloader.
`is_configured()` = Prowlarr and adapter configured (`SoulSync:core/download_plugins/usenet.py:87-91`). Embedded:
none. **ToS/legal:** grey; indexer and provider accounts are the user's, and legality depends on the content.

### Lidarr

`core/lidarr_download_client.py` (718 lines), registered as `lidarr`
(`SoulSync:core/download_plugins/registry.py:193`). Search is Lidarr's `album/lookup` (≤ 10 albums), and every track
becomes a candidate that **claims** `quality='flac'`, 1,411 kbps and 999 free slots with no evidence
(`SoulSync:core/lidarr_download_client.py:118-163`). Download adds the artist unmonitored if missing, then adds the
album monitored with `searchForNewAlbum`, or posts an `AlbumSearch` command
(`SoulSync:core/lidarr_download_client.py:264-331`). Lidarr always grabs the **whole album** from its own indexers and
download clients (`SoulSync:core/lidarr_download_client.py:2-12`) under its own quality profile (default "Any",
`SoulSync:core/settings.py:676`), not SoulSync's. The client polls once a second for at most 10 minutes
(`SoulSync:core/lidarr_download_client.py:346-400`). It fuzzy-matches the wanted title (≥ 0.7,
`SoulSync:core/lidarr_download_client.py:563-565`) and copies that one file out of Lidarr's root folder; if no title
matches it copies every file (`SoulSync:core/lidarr_download_client.py:422-471`). This needs a shared filesystem view. **Credentials:** Lidarr URL
and API key (`SoulSync:core/settings.py:672-678`, `SoulSync:core/lidarr_download_client.py:76-77`); embedded: none.
**ToS/legal:** grey; the API use is clean, but the audio comes from Lidarr's own torrent/Usenet indexers.

### How the orchestrator chooses

`DownloadOrchestrator` builds the registry and reads `download_source.mode`, the legacy `hybrid_primary` and
`hybrid_secondary`, and `hybrid_order` (`SoulSync:core/download_orchestrator.py:46-79`). The shipped defaults are
**mode `soulseek`**, primary `soulseek`, secondary `youtube` and `hybrid_order: []`
(`SoulSync:core/settings.py:565-568`). The code-level fallback `['hifi', 'youtube', 'soulseek']` applies only when the
key is missing (`SoulSync:core/download_orchestrator.py:79`). The order is set in Settings
(`SoulSync:webui/static/settings.js:6475`).

- **Enable flags.** There is no server-side per-source flag. The Settings toggles per source only edit membership of
  `hybrid_order` (`SoulSync:webui/static/settings.js:2019`, `SoulSync:webui/static/settings.js:2686-2688`). In hybrid
  mode a source takes part when it is in the chain, its constructor did not fail
  (`SoulSync:core/download_plugins/registry.py:100-111`), and `is_configured()` (the protocol's "has the credentials it needs" check,
  `SoulSync:core/download_plugins/base.py:59-63`) is true at call time
  (`SoulSync:core/download_engine/engine.py:420-426`); single-source mode does not check `is_configured()`
  (`SoulSync:core/download_orchestrator.py:340-348`). That makes "configured" credential-shaped for
  Deezer/Tidal/Qobuz/torrent/usenet/Lidarr, and almost always true for HiFi, YouTube, SoundCloud and Amazon (above).
- **Single-source mode** sends every search to that one client (`SoulSync:core/download_orchestrator.py:335-348`).
- **Hybrid, priority mode (default).** The chain is `hybrid_order` (aliases normalised, duplicates dropped), else
  [primary, secondary] (`SoulSync:core/download_orchestrator.py:286-311`). `search_with_fallback` tries sources in
  order and **returns the first one with any tracks**, quality-agnostic by design; exceptions and empty results fall
  through (`SoulSync:core/download_engine/engine.py:398-442`).
- **Hybrid, best-quality mode** (a quality-profile `search_mode`, default `priority`,
  `SoulSync:core/quality/selection.py:196-199`, checked at `SoulSync:core/download_orchestrator.py:364`) queries
  every configured source concurrently and pools the results
  (`SoulSync:core/download_engine/engine.py:444-511`). The candidate order then puts the quality-profile target
  first and the chain position second (`SoulSync:core/downloads/candidates.py:192-193`,
  `SoulSync:core/downloads/candidates.py:321`).
- **Fall-through after search.** Because the first source with *any* hits wins, the per-track worker has its own
  second loop, in priority mode only (`SoulSync:core/downloads/task_worker.py:825`). Only after every query fails
  does it search each remaining chain source directly, re-judging the hits. It skips element 0 of `hybrid_order`
  (or of [primary, secondary]) and exhausted sources (`SoulSync:core/downloads/task_worker.py:828-850`), and tries
  only the first 2 queries on non-release sources (`SoulSync:core/downloads/task_worker.py:858`).
- **Fall-through after a failed download.** `orchestrator.download` routes to exactly one plugin by the candidate's
  `username` (a source name, else a Soulseek peer) (`SoulSync:core/download_orchestrator.py:546-565`), after a
  minimum-free-disk guard (`SoulSync:core/download_orchestrator.py:534-542`). The engine's `download_with_fallback`
  has **no caller** outside tests and comments (`SoulSync:core/download_engine/engine.py:513`). After 3 failed
  tries (missing, errored, queued too long, stuck at 0 %, stuck in a state; `SoulSync:core/downloads/monitor.py:897`,
  `SoulSync:core/downloads/monitor.py:992`, `SoulSync:core/downloads/monitor.py:1132`,
  `SoulSync:core/downloads/monitor.py:1227`, `SoulSync:core/downloads/monitor.py:1338`) the monitor marks the source
  exhausted and restarts the search on the rest of the chain (`SoulSync:core/downloads/monitor.py:202-250`). That
  list is built from `hybrid_order` **only** (`SoulSync:core/downloads/monitor.py:183-199`), so a config with the
  shipped `[]` has no give-up fallback although search uses primary/secondary. In practice any save from Settings
  writes a non-empty order (`SoulSync:webui/static/settings.js:2811-2820`, `SoulSync:webui/static/settings.js:6475`),
  so this bites only configs never saved there.
- **Album batches.** Hybrid per-track searches exclude torrent/usenet
  (`SoulSync:core/downloads/task_worker.py:655-668`). Album bundles run only on the consecutive bundle-capable
  (torrent, usenet, soulseek) prefix of the chain (`SoulSync:core/downloads/master.py:58`,
  `SoulSync:core/downloads/master.py:536-551`). A bundle failure without `fallback=True` fails the whole batch
  (`SoulSync:core/downloads/album_bundle_dispatch.py:205-221`); torrent's and usenet's "refused on every indexer"
  errors are of that kind (`SoulSync:core/download_plugins/torrent.py:860-862`,
  `SoulSync:core/download_plugins/usenet.py:657-659`).

```
 request (track; album batch first tries a bundle on the chain's torrent/usenet/soulseek prefix)
   │
   ▼
 mode != hybrid ──► that one client.search ──► judge ──► download ──► monitor (no other source)
   │ hybrid
   ▼
 chain = hybrid_order (normalised) or [primary, secondary]      minus exhausted, minus torrent/usenet on albums
   │
   ├─ priority:      src1.search ─ empty/raise ─► src2.search ─ … ─► first source WITH ANY TRACKS wins
   └─ best_quality:  all sources concurrently ─► pool ─► order by profile target, then chain position
   │
   ▼
 per query: judge (match + quality) ─► walk candidates ─► orchestrator.download(username=source) ─► one plugin
   │ all queries fail (priority only)                        │ 3 failures in monitor (hybrid_order only)
   ▼                                                         ▼
 worker's own loop: chain[1:] directly, 2 queries ─► judge  mark source exhausted ─► re-search without it
   │
   ▼
 first candidate that starts and survives the monitor = success; chain exhausted = not_found
```

Two likely bugs, read from code and not run. (1) The monitor records Deezer as `deezer_dl`
(`SoulSync:core/downloads/monitor.py:72-73`), while the orchestrator filters a chain normalised to `deezer`
(`SoulSync:core/download_orchestrator.py:292-298`, `SoulSync:core/download_orchestrator.py:351-354`), so an exhausted
Deezer is probably never excluded from the orchestrator's search; the worker's second loop uses the raw names and
does exclude it (`SoulSync:core/downloads/task_worker.py:845-850`). (2) A Lidarr candidate is not excluded from hybrid album batches
(only torrent/usenet are, `SoulSync:core/downloads/task_worker.py:661-662`), so each track of an album can trigger
another whole-album `AlbumSearch` (`SoulSync:core/lidarr_download_client.py:318-326`).

## How ours does it

Ours is Soulseek-only by design: the one getter is slskd behind the gluetun VPN, which the worker drives
search → score → approved download → verify → beets → rescan
(`ours:docs/architecture.md:36-37`, `ours:docs/architecture.md:53`, `ours:sourcing/fetch.py:1-8`,
`ours:sourcing/fetch.py:386-392`), and SpotiFLAC's Tidal/Qobuz/Deezer backends were looked at and not adopted for
sourcing (`ours:docs/specs/2026-10-13-next-session-design.md:142-143`). Every download waits for an approval (`ours:sourcing/fetch.py:1-4`;
D7 allows automatic downloads only after Michael's go, `ours:docs/specs/2026-10-13-next-session-design.md:61`) and D26 sources the exact track the row names
(`ours:docs/specs/2026-10-17-amperfy-pivot.md:21`), so there is no source order, fallback chain or per-source
credential to manage.

## The difference that matters

- **Quality provenance (D24).** D24 accepts lossless or lossy ≥ 256 kbps and rejects a re-encoded fake
  (`ours:docs/specs/2026-10-17-amperfy-pivot.md:19`), and our verify measures it: spectral cutoff, fake hi-res, implied
  kbps, hard under strict verify (`ours:sourcing/verify.py:9-10`, `ours:sourcing/verify.py:233`). Several SoulSync
  sources *label* quality instead of proving it:
  - YouTube defaults to an MP3 320 re-encode of a lossy stream (`SoulSync:core/settings.py:1106-1115`), which is
    D24's re-encoded fake by definition.
  - SoundCloud stamps every hit 128 kbps MP3 (`SoulSync:core/soundcloud_client.py:369-375`).
  - Lidarr claims FLAC/1,411 for anything it might grab (`SoulSync:core/lidarr_download_client.py:155-163`).
  - Tidal, HiFi, Qobuz and Deezer walk down to AAC 96 or MP3 128 when the top tier is refused, with
    `allow_fallback` on by default (`SoulSync:core/tidal_download_client.py:1058-1062`,
    `SoulSync:core/hifi_client.py:1061-1066`, `SoulSync:core/qobuz_client.py:1230-1237`,
    `SoulSync:core/deezer_download_client.py:1194-1219`). An import guard then probes the file with mutagen against
    the profile's ranked targets, rejecting it unless the profile itself allows fallback
    (`SoulSync:core/imports/guards.py:159-200`); a container probe cannot see that an MP3 320 was made from Opus,
    so the YouTube point stands.
  For a DJ library, where a file goes onto a club system, a mislabelled lossy file is the one failure that is heard.
  Our verify flags a ≥315 kbps file only for a cutoff ≤16 kHz (`transcode`) or ≤18 kHz (`maybe_lossy`)
  (`ours:sourcing/verify.py:435-442`), so it would pass a YouTube MP3 320 made from Opus 256 if Opus's lowpass sits
  near 20 kHz; that lowpass is *unverified* (would be verified by encoding a test file Opus 256 → MP3 320 and running
  ours `verify` on it).
- **Previews posing as tracks.** SoulSync needed explicit preview guards for HiFi and Qobuz
  (`SoulSync:core/hifi_client.py:1190-1212`, `SoulSync:core/qobuz_client.py:1258-1261`), and SoundCloud's 100 KB floor
  does not catch a 30 s clip; only the import duration check does, and only when the expected length is known
  (above). Ours fails truncation and duration on every tier (`ours:sourcing/verify.py:232`). A streaming source would
  add a failure class Soulseek rarely shows.
- **Legal and account risk.** Seven of the eleven plugins are `streaming rip`. Deezer, Tidal and Qobuz tie the rip to
  Michael's own paid account (ARL, device login, account token). HiFi and Amazon ride someone else's account through
  anonymous proxies that come and go (T2Tunes is already dead, `SoulSync:core/amazon_outage.py:64-66`). Tidal already
  answers download bursts with captchas (`SoulSync:core/tidal_download_client.py:46-55`). Torrent seeds forever by default
  (`SoulSync:core/settings.py:713-720`), which is distribution, not just download. Ours keeps the one grey source
  (Soulseek) behind a VPN with a kill switch (`ours:docs/specs/2026-10-13-next-session-design.md:292`).
- **Supply chain.** YouTube support pulls a nightly yt-dlp and can fetch an unchecksummed ffmpeg at runtime
  (`SoulSync:core/ytdlp_update.py:33-54`, `SoulSync:core/youtube_client.py:1001-1080`); ours runs neither.
- **Fallback semantics.** SoulSync's chain falls through on "no results" or an exception, not on "no acceptable
  candidate". The worker papers over that with a second loop, and the download-time fallback is dead code (above).
  Ours has one source, so "not found" means Soulseek has no acceptable copy, and the row stays `needs_source`
  (`ours:sourcing/fetch.py:8`).

## Worth taking?

- **Streaming rips (Deezer, Tidal, Qobuz, Amazon, HiFi, YouTube, SoundCloud):** no. They are outside D7/D26's
  Soulseek-plus-approval model, they carry account and terms risk, and YouTube and SoundCloud label quality instead
  of proving it (D24). Out by default (question 4 under "Questions for Michael" in the run's
  progress.md, which names all of these but SoundCloud);
  nothing to port.
- **Metadata-only (Bandcamp, JioSaavn):** no for sourcing. Bandcamp's label, date and track count would be a clean
  enrichment idea, but MusicBrainz already covers it for us (V2-06 judges metadata).
- **Release sources (torrent, Usenet/Prowlarr):** no now. If S2's album-first sourcing ever wants a second source, the
  idea worth reading is `pick_best_album_release`'s gate order (`SoulSync:core/download_plugins/album_bundle.py:431-488`),
  not the plugins. Seeding defaults and archive handling would each need a decision of Michael's first.
- **Lidarr:** no. It is album-only with unproven quality claims and a 10-minute poll, and it would hand file
  placement to a second library manager beside beets.
- **The orchestrator:** no as code. Two lessons for us if a second source ever comes:
  - fall through on "no acceptable candidate", not on "no results";
  - keep the exhausted-source key and the chain on one canonical name (the `deezer_dl` bug above).

**Verdict:** no. None of the non-Soulseek sources fits our Soulseek-only, approval-gated, provenance-checked design.
The only transferable ideas are the album-release gate order (for S2) and the two fallback lessons above.
