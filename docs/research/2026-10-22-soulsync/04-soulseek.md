# 04 · Soulseek sourcing (part 1: search, scoring, folders, fallbacks, peer memory)

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed).
Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a claim
without one. Numbers marked **hand estimate** were re-computed with a few lines of our own stdlib Python (difflib) in
the run's scratch directory, never by running SoulSync. Part 2 (V2-03b) adds enqueue, transfer polling, cancel and
remove, 4xx/5xx and outage handling, throttling and the slskd endpoint table; this part touches them only where a
fallback decision depends on them. The candidate *match* score (title/artist/duration weights, the base-title veto,
the version gate) is in `03-matching.md` and is only summarised here. Music only: the audiobook `.m4b` widening of
the search filter (`SoulSync:core/soulseek_client.py:446-464`) is named once and skipped.

**Corrections to the feature's file list** (what the files turned out to be):
- `core/download_plugins/query_variants.py` builds query ladders for **indexer** searches (Prowlarr → Newznab/torrent),
  not Soulseek (`SoulSync:core/download_plugins/query_variants.py:1-16`); its only users are the torrent plugin and
  Tidal (`SoulSync:core/download_plugins/torrent.py:1336`, `SoulSync:core/tidal_download_client.py:594-595`).
  Soulseek queries come from `MusicMatchingEngine.generate_download_queries` plus a legacy list in the task worker.
- `core/download_plugins/candidate_store.py` is a token store for Prowlarr download URLs, so indexer keys never
  reach the browser (`SoulSync:core/download_plugins/candidate_store.py:1-15`); Soulseek candidates do not use it.
- `core/downloads/prioritize.py` holds no scoring terms: it moves a queued track or batch to the front of the
  download queue on the user's request (`SoulSync:core/downloads/prioritize.py:1-5`,
  `SoulSync:core/downloads/prioritize.py:104-118`).
- `release_identity.py` is `core/download_plugins/release_identity.py`, and it identifies **torrent/usenet** releases
  only (`_RELEASE_PROTOCOLS = {'torrent', 'usenet'}`, `SoulSync:core/download_plugins/release_identity.py:19`,
  `SoulSync:core/download_plugins/release_identity.py:80-89`). A Soulseek folder has no release identity.
- `core/download_plugins/album_bundle.py` is the torrent/usenet release picker; Soulseek borrows only its poll
  interval, poll timeout and atomic copy (`SoulSync:core/soulseek_client.py:23-27`,
  `SoulSync:core/download_plugins/album_bundle.py:1-12`). Soulseek's own album bundle is
  `SoulseekClient.download_album_to_staging` (`SoulSync:core/soulseek_client.py:1930`).

## What SoulSync does

```
 per-track task (download_track_worker)                      album batch (run_full_missing_tracks_process)
   cached candidates (retry only) ─► batch folder reuse        album pre-flight: 1-3 album queries, score folders
   ─► staged album file ─► queries 1..n (artist+album+title,   ─► Soulseek bundle: one folder, alternatives ≤ 4
   artist+title, title, ...) ─► slskd search, poll            ─► stage what arrived ─► per-track tasks claim staged
   ─► match score > 0.58, quality profile, artist in path      files; what is missing ─► per-track (left column)
   ─► walk candidates (bands, peer speed) until one starts
   ─► monitor: errors / stalls / quarantine ─► re-run worker
```

### Search and candidates

**Query ladder for one track.** `generate_download_queries` returns, in order and deduplicated case-insensitively
(`SoulSync:core/matching_engine.py:728-919`):
1. a raw `artist title` when either is non-ASCII, because unidecode mangles CJK
   (`SoulSync:core/matching_engine.py:749-757`);
2. "Priority 0": `artist album title` with the cleaned album, unless the album is `single`, `ep` or `greatest hits`
   (`SoulSync:core/matching_engine.py:769-778`);
3. "Priority 1": `artist title` with an album name detected inside the title removed
   (`SoulSync:core/matching_engine.py:780-786`);
4. "Priority 2": the part before ` - ` when the dash tail carries no version word, and the title without a
   `(feat …)`/`(explicit)` group when the group carries no version word (`SoulSync:core/matching_engine.py:791-850`);
5. "Priority 3": `artist cleaned-title`, only when no album was detected in the title
   (`SoulSync:core/matching_engine.py:852-857`);
6. "Priority 4": the title alone, only if `_title_is_distinctive_enough_to_broadcast` (#1102)
   (`SoulSync:core/matching_engine.py:859-869`);
7. "Priority 5", last resort: the title with edition decoration (`[2005 Remaster]`, `(Deluxe)`, `(Mono)`) stripped,
   artist-qualified, plus the bare form if distinctive (`SoulSync:core/matching_engine.py:871-909`).
With no artist at all it returns only the cleaned title, because the artist gate would reject every result
(`SoulSync:core/matching_engine.py:735-747`). The task worker appends legacy queries, `title firstword-of-artist`
("The" skipped), the bare title and the title without any bracket group, the last two only when distinctive
(`SoulSync:core/downloads/task_worker.py:501-534`), dedupes (`SoulSync:core/downloads/task_worker.py:539-549`), and
runs them **one at a time, stopping at the first query whose candidates start a download**
(`SoulSync:core/downloads/task_worker.py:615-799`). On a quarantine retry the queries already run are skipped and
their cached candidates walked instead (`SoulSync:core/downloads/task_worker.py:598-639`).

For comparison, `indexer_query_variants` (torrent/usenet only, see the corrections) yields, in order and
deduplicated, at most 5: the original; noise tokens dropped (`feat`, `ft`, `featuring`, `with`, `prod`, `produced`);
a trailing balanced bracket group stripped; every balanced bracket group stripped; both; and, past 100 characters,
the bracket-stripped and then the original text cut at a word boundary
(`SoulSync:core/download_plugins/query_variants.py:41-46`, `SoulSync:core/download_plugins/query_variants.py:126-158`).

**Query for an album.** `_album_search_queries(artist, album, year)`: `artist album`, then `clean-artist album` when
a bracket or feat. credit was removed, then `album`; for a self-titled album `artist year` then `album`
(`SoulSync:core/downloads/master.py:130-143`). All of them run, and folders are deduplicated by `(username,
album_path)` with the first query's `AlbumResult` kept; later hits for the same folder are dropped
(`SoulSync:core/downloads/master.py:1269-1281`). The bundle's own fallback search (no pre-flight pick) is the single
query `artist album` (`SoulSync:core/soulseek_client.py:1985-1988`).

**The search call.** `SoulseekClient.search` POSTs `searches` with `searchText`, `timeout` in ms, `filterResponses:
true`, `minimumResponseFileCount: 1` and `minimumPeerUploadSpeed` (the setting in Mbps × 125,000)
(`SoulSync:core/soulseek_client.py:695-710`). The download paths pass `timeout=30`
(`SoulSync:core/downloads/task_worker.py:695-699`, `SoulSync:core/downloads/master.py:1271`), except the hybrid
fallback's direct search with `timeout=20` (`SoulSync:core/downloads/task_worker.py:95-101`); the default is the
`soulseek.search_timeout` setting, 60 s (`SoulSync:core/soulseek_client.py:686-687`). Ours sends `searchTimeout`
instead of `timeout` (`ours:sourcing/slskd_client.py:42-43`); which key slskd 0.26 reads is *unverified* here and goes
to V2-03b's endpoint table.

**Wait and poll.** It polls `GET searches/{id}/responses` every 1 s for up to timeout + `search_timeout_buffer`
(15 s default) (`SoulSync:core/soulseek_client.py:734-755`, `SoulSync:core/soulseek_client.py:763-767`). Responses
are merged by peer and files deduped by `(username, filename, size)`, capped at 250 peers and 20,000 files
(`SoulSync:core/soulseek_client.py:404-429`, `SoulSync:core/soulseek_client.py:75-76`). After 15 polls, and 2 polls
without new files, it reads `GET searches/{id}` and stops on an explicitly terminal state; without a readable state
it stops after 5 quiet polls (`SoulSync:core/soulseek_client.py:79-81`, `SoulSync:core/soulseek_client.py:807-822`,
`SoulSync:core/soulseek_client.py:432-441`). Any exception returns `([], [])`
(`SoulSync:core/soulseek_client.py:831-833`).

**Candidate records.** Every audio file becomes a `TrackResult`: `username`, `filename` (the full remote path),
`size`, `bitrate` (`bitRate` or attribute 0), `duration` in ms (slskd's `length` × 1000), `quality` (from the
extension), `free_upload_slots` (`hasFreeUploadSlot` as 0/1), `upload_speed`, `queue_length`, `sample_rate`,
`bit_depth` (`SoulSync:core/soulseek_client.py:466-512`, `SoulSync:core/download_plugins/types.py:23-39`), plus
`artist`/`title`/`album`/`track_number` parsed from the filename (`SoulSync:core/download_plugins/types.py:114-142`).
Files are grouped by `(username, parent directory)`; a directory with **two or more** hits becomes an `AlbumResult`
(`username, album_path, album_title, artist, track_count, total_size, tracks, dominant_quality, year`, the peer's
slot/speed/queue) (`SoulSync:core/soulseek_client.py:516-519`, `SoulSync:core/soulseek_client.py:560-606`,
`SoulSync:core/download_plugins/types.py:145-160`). `search` returns `(individual_tracks, albums)`, and
individual tracks are only the files **not** grouped into an album (`SoulSync:core/soulseek_client.py:524-534`). The
per-track worker keeps only the first list (`tracks_result, _ = …search(…)`,
`SoulSync:core/downloads/task_worker.py:708-710`), and neither the orchestrator nor the engine adds album tracks back
(`SoulSync:core/download_orchestrator.py:335-377`, `SoulSync:core/download_engine/engine.py:428-434`). So, read from
the code, a file whose folder gave two or more hits for the same query is not a per-track candidate (not run; no test
of this was found). The exclusion is keyed on the filename alone; files in a root directory, or in one whose name
starts with `@` or is one character long, never group (`SoulSync:core/soulseek_client.py:536-557`). In hybrid mode a
Soulseek search whose files all grouped counts as "no tracks" and the next source is tried
(`SoulSync:core/download_engine/engine.py:430-432`).
During the download walk `candidates.py` adds to each record the `confidence`, `version_type`,
`preferred_version_hit` and `soulseek_match_evidence` set by matching, and keys attempts as `peer_filename`
(`SoulSync:core/downloads/candidates.py:483-525`). `core/download_plugins/candidate_store.py` plays no part for
Soulseek: it maps opaque tokens to Prowlarr URLs, 6 h TTL, 5,000 entries
(`SoulSync:core/download_plugins/candidate_store.py:26-33`). For the inspector, `candidate_pool.candidate_row` flattens a candidate into a dict with the same fields plus
`display_name`, `quality_label`, `confidence`, `source_service`, `source_query`, `blacklisted` and the decision; at
most 50 rejected rows are kept (`SoulSync:core/downloads/candidate_pool.py:17`,
`SoulSync:core/downloads/candidate_pool.py:33-66`).

### Scoring

Three layers decide which file is tried first. None of the rows below reads a MusicBrainz id or a release's track
lengths (the cited code; that nothing else on this path does is *unverified*).

| Layer | Term | Numbers | Cite |
|---|---|---|---|
| Search | peer upload speed floor | `minimumPeerUploadSpeed` = setting × 125,000 B/s (default 0) | `SoulSync:core/soulseek_client.py:696-704` |
| Match (03) | title / artist / duration | 0.45 / 0.40 / 0.15; duration 1.0 within 5 s; FLAC +0.03, MP3 ≥ 320 +0.02; album segment +0.10; accept > 0.58, plus a recovery pass re-admitting rows with confidence > 0, an exact-title `match_track` and the artist in the path | `SoulSync:core/matching_engine.py:1122-1141`, `SoulSync:core/matching_engine.py:1026-1058`, `SoulSync:core/matching_engine.py:1631`, `SoulSync:core/downloads/validation.py:861-882` |
| Match | peer queue gate | drop peers with `queue_length` > `soulseek.max_peer_queue` (default 0 = off), unless that drops all | `SoulSync:core/downloads/validation.py:859-860`, `SoulSync:core/matching_engine.py:1582-1587` |
| Match | sort | (asked version, confidence, original before version, `quality_score`, size) | `SoulSync:core/matching_engine.py:1612-1626` |
| Quality | profile filter | quarantined `(peer, file)` dropped; size cap `download_source.max_mb_per_minute` (default 0 = off) × duration; then only the **best ranked target present** survives, or all when nothing matches and fallback is on | `SoulSync:core/soulseek_client.py:2784-2817`, `SoulSync:core/downloads/size_limit.py:23-53`, `SoulSync:core/quality/model.py:286-313` |
| Quality | artist in path | every word of a wanted artist in one path segment, else dropped | `SoulSync:core/downloads/validation.py:982-1015` |
| Peer | `quality_score` | format flac 1.0, mp3 0.8, ogg 0.7, aac 0.6, wma 0.5, else 0.3; bitrate ≥ 320 +0.2, ≥ 256 +0.1, < 128 −0.2; no free slot −0.15, a free slot +0.05; upload ≥ 5 MB/s +0.15, ≥ 1 MB/s +0.10, ≥ 500 kB/s +0.05, < 100 kB/s −0.05; queue > 50 −0.25, > 20 −0.15, > 10 −0.10; capped at 1.0 | `SoulSync:core/download_plugins/types.py:67-111` |
| Walk | confidence bands | candidates within **0.08** of the band leader count as equally right; inside a band sort by `peer_availability_key`, then `quality_score`, then confidence, and round-robin peers | `SoulSync:core/downloads/candidates.py:115-118`, `SoulSync:core/downloads/candidates.py:348-372` |
| Walk | `peer_availability_key` | measured ≥ 500 kB/s first, never measured second, measured slower last; then measured B/s, free slots, −queue, −our own active transfers to that peer, advertised speed | `SoulSync:core/downloads/peer_observation.py:14`, `SoulSync:core/downloads/peer_observation.py:53-68`, `SoulSync:core/downloads/candidates.py:441-457` |
| Walk | best-quality mode (opt-in) | profile rank first, then the same band order within a rung | `SoulSync:core/downloads/candidates.py:326-347`, `SoulSync:core/downloads/task_worker.py:104-138` |
| Queue | `prioritize.py` | no candidate terms: a user's "download next" moves a queued track or batch forward | `SoulSync:core/downloads/prioritize.py:121-168` |
| Transfer | observed speed (opt-in) | a 30 s window, then 30 s more below `soulseek.min_observed_download_speed_kbps` (250) → next candidate; off unless `soulseek.observed_speed_fallback_enabled` | `SoulSync:core/downloads/observed_speed.py:9-10`, `SoulSync:core/downloads/observed_speed.py:44-73`, `SoulSync:core/downloads/monitor.py:1369-1405` |

Read together: among accepted files, quality is applied before the walk: the profile filter keeps only the best rung
present, so a FLAC at 0.62 confidence beats an MP3 at 0.95 (`SoulSync:core/quality/model.py:305-313`). Within that
rung confidence leads, except inside the 0.08 band, where a measured fast peer beats a slightly better-named file.
Format and bitrate act twice: as that profile *filter* and as a small tie-break inside `quality_score`.

### Album requests and folder choice

An album batch (`is_album_download`, from an album page or a wishlist album batch,
`SoulSync:core/wishlist/processing.py:153`) runs after the "what is missing" analysis, so an owned album never
starts a download (`SoulSync:core/downloads/master.py:1099-1102`). For Soulseek:

1. **Pre-flight search and folder score** (`SoulSync:core/downloads/master.py:1249-1408`). Each folder's tracks pass
   the quality profile filter, then `assign_album_tracks` maps the wanted tracks onto its files one to one (maximum
   bipartite matching; an edge is an exact title key, ranked by agreeing / unknown / disagreeing track number, or a
   fuzzy title ≥ 0.80) (`SoulSync:core/downloads/soulseek_identity.py:301-340`,
   `SoulSync:core/downloads/soulseek_identity.py:236-287`). `_score_album_folder` then returns 0 if coverage < 0.8
   or album-title similarity < 0.65, else **0.24 album + 0.16 artist + 0.16 count + 0.28 coverage + 0.06 year +
   0.06 profile-eligible share + 0.04 peer `quality_score` − variant penalty** (0.12 per remix/live/instrumental/…
   word and 0.06 per deluxe/remaster/edition word the request lacks, at most 0.30); count is 1.0 exact, 0.75 within 2,
   0.35 within 5 (`SoulSync:core/downloads/master.py:438-516`, `SoulSync:core/downloads/master.py:50-57`,
   `SoulSync:core/downloads/master.py:146-159`).
2. **Pick.** Sort by score; folders within **0.06** of the leader, with coverage within **0.05** and the same variant
   penalty, are treated as the same release and re-sorted by `peer_availability_key`; the winner must reach **0.62**
   (`SoulSync:core/downloads/master.py:44-49`, `SoulSync:core/downloads/master.py:1315-1350`). The check reads the
   score of the row first *after* the re-sort, so a faster in-band folder under 0.62 cancels the pick even when the
   leader passed (`SoulSync:core/downloads/master.py:1343-1350`).
3. **Browse** the winner's folder (`GET users/{peer}/directory`, V2-03b) and re-check coverage ≥ 0.8 on the full
   listing; a failed browse uses the search's files (`SoulSync:core/downloads/master.py:1359-1401`).
4. **Bundle.** `download_album_to_staging` gets the pick plus the other folders among the top 5 that scored ≥ 0.62
   (`SoulSync:core/downloads/master.py:1418-1455`), of which it uses at most 4
   (`SoulSync:core/soulseek_client.py:2208`). Without a pick it searches `artist album` itself and ranks with a
   simpler score: 0.32 album + 0.18 artist + 0.12 count (≥ 3 files) + 0.12 profile share + 0.10 `quality_score` +
   0.16 coverage, ≥ 0.58 (`SoulSync:core/soulseek_client.py:2297-2352`). It enqueues **only the files that answer
   wanted tracks** (`SoulSync:core/soulseek_client.py:2073-2097`), polls, may switch folders (next section), copies
   what arrived into private staging and removes slskd's copy (`SoulSync:core/soulseek_client.py:2156-2182`).
5. **Hand-off.** The batch goes on as per-track tasks; each first tries to claim a staged file (title similarity
   ≥ 0.80 and a combined title/artist score ≥ 0.75, `SoulSync:core/downloads/staging.py:289-328`,
   `SoulSync:core/downloads/staging.py:364-365`). A track the folder did not have falls through to the
   ordinary per-track search (#743, `SoulSync:core/downloads/task_worker.py:208-216`).
6. **No bundle** (fallback-eligible failure, `SoulSync:core/downloads/album_bundle_dispatch.py:203-217`): the pre-flight
   folder is preloaded as the batch's `last_good_source` (`SoulSync:core/downloads/master.py:1478-1490`) and the
   batch runs **one Soulseek track at a time** (`SoulSync:web_server.py:2187-2205`). Each track first tries that
   folder: every folder file scored with the *base* match score (no base-title veto and no version gate, both of which
   live only in the enhanced scorer, `SoulSync:core/matching_engine.py:1269-1290`), ≥ **0.70** kept,
   quality-filtered; a file naming the artist is preferred but not required: with none, the top file is taken
   (`verified if verified else filtered[:1]`, `SoulSync:web_server.py:16755-16797`). As soon as any per-track download
   *starts* (before transfer or verify end), the batch browses that file's folder and stores it as the new
   `last_good_source` (`SoulSync:web_server.py:16813-16872`, called at
   `SoulSync:core/downloads/task_worker.py:455-472`, `SoulSync:core/downloads/task_worker.py:793-798`). Wishlist batches get the same reuse
   (`SoulSync:web_server.py:16702-16707`).

"**Pinned**" is not album stickiness: `pinned_batch.py` turns files the user picked on the basic search page into a
batch whose tasks download exactly that file, with no search and no swap to another peer
(`SoulSync:core/downloads/pinned_batch.py:1-15`, `SoulSync:core/downloads/pinned_batch.py:221-241`); the monitor and the
quarantine retry leave such `_user_manual_pick` tasks alone (`SoulSync:core/downloads/monitor.py:845-851`,
`SoulSync:core/downloads/monitor.py:289-293`). **Release identity** is not used for Soulseek folders:
`candidate_release_key` returns None for any username other than `torrent`/`usenet`
(`SoulSync:core/download_plugins/release_identity.py:80-83`); its other use is a `failed_release_ids` skip that
therefore never fires for Soulseek (`SoulSync:core/downloads/candidates.py:509-518`). `album_bundle.py` supplies the
Soulseek bundle only its poll interval (2 s), deadline (6 h) and atomic copy into staging
(`SoulSync:core/download_plugins/album_bundle.py:64-94`, `SoulSync:core/download_plugins/album_bundle.py:1537-1560`); "the same release" is approximated only by the folder score's album title, year, track count and
variant words, and a Soulseek bundle ignores the expected album duration it is passed
(`SoulSync:core/soulseek_client.py:1948-1953`).

```
 album request (album_context + artist_context + missing tracks)
   │
   ├─ pre-flight: "artist album", "clean-artist album", "album"  ──► folders = search hits grouped by (peer, dir), ≥ 2 files
   │     each folder: quality filter ─► assign_album_tracks (title key / fuzzy ≥ 0.80) ─► coverage ≥ 0.8 ─► score ≥ 0.62
   │     band (±0.06, ±0.05 coverage, same variant words) re-sorted by peer speed ─► winner ─► browse ─► coverage ≥ 0.8
   │
   ├─ bundle: enqueue the winner's matched files ─► poll ─┬─ complete ──────────────────────────────┐
   │                                                       ├─ partial / failed / timeout ─► alternatives (≤ 4, each must
   │                                                       │     cover 100 % of what is owed) one after another
   │                                                       └─ crawling (opt-in) ─► cancel, alternatives, else re-ask crawler
   │                                                                                                ▼
   ├─ stage what arrived ─► per-track tasks: claim a staged file (title ≥ 0.80)  ─► done
   │                                    └─ not staged ─► per-track search (queries, any peer) ─► stores its folder
   └─ no bundle ─► per-track tasks, 1 at a time: preloaded folder (base score ≥ 0.70) ─► else per-track search
```

**ext-74 on these paths** (the question V2-02 left open, `03-matching.md`). The bundle path does **not** run the
base-title veto: it maps files with `assign_album_tracks`. For "I'm Still In Love With You" against
`09 - One of These Good Old Days` the keys differ; `match_track` takes the best ratio over all title interpretations
(`SoulSync:core/downloads/soulseek_identity.py:108-209`, `SoulSync:core/downloads/soulseek_identity.py:257-270`), and
the best one, the artist-prefix reading `im still in love with you 09 one of these good old days` of a flat name,
scores 0.625 (0.275 for the bare basename; hand estimates), below the 0.80 weak edge, so track 09 is never assigned to
track 1 (`SoulSync:core/downloads/soulseek_identity.py:301-307`). A folder missing
only track 1 still qualifies (8/9 = 0.89 ≥ 0.8) and track 1 goes per-track. The **source-reuse** path is weaker: it
uses the base `calculate_slskd_match_confidence` at ≥ 0.70 (`SoulSync:web_server.py:16757-16762`), which has no veto
and no version gate and which 03 estimates at about 0.89 for exactly this file. So when a preloaded or stored folder lacks track 1 but has
track 09, track 09 is downloaded for track 1 (read from the code; not run). Only AcoustID, off by default, would then
catch it (03).

### When a track fails

Order for one per-track task, read from the code:

| Step | Trigger | What happens | How many | Cite |
|---|---|---|---|---|
| 1 | the peer refuses the enqueue (no download id) | next candidate in the same walk; nothing counted | every candidate | `SoulSync:core/downloads/candidates.py:497-525`, `SoulSync:core/downloads/candidates.py:700-709` |
| 2 | nothing in the best quality rung starts | re-judge the same results without those rows, so the next rung may win | until no new row | `SoulSync:core/downloads/task_worker.py:276-315` |
| 3 | no query yields a starting candidate | hybrid mode: the next sources, first 2 queries each (all for torrent/usenet) | each source once | `SoulSync:core/downloads/task_worker.py:819-906` |
| 4 | transfer `Errored`, `Failed`, `Rejected` or `TimedOut` | cancel with `remove=True`, mark `(peer, file)` used, re-run the whole worker: batch folder reuse, then a **fresh search** of every query, walking only unused `(peer, file)`s | 3 per task, ≥ 5 s apart | `SoulSync:core/downloads/monitor.py:921-989`, `SoulSync:core/downloads/monitor.py:690`, `SoulSync:core/downloads/monitor.py:697-700` |
| 5 | queued > 90 s or `InProgress` at 0 % > 90 s (15 s each when the task's `track_info` says `is_album_download`), or gone from slskd's list > 90 s (always 90 s) | same reset as step 4 | 3 per task, ≥ 30 s apart | `SoulSync:core/downloads/monitor.py:853-896`, `SoulSync:core/downloads/monitor.py:1062-1084`, `SoulSync:core/downloads/monitor.py:1160-1180` |
| 6 | sustained slow transfer (opt-in) | next candidate; the slow one is kept and tried last | until candidates run out | `SoulSync:core/downloads/monitor.py:1362-1464`, `SoulSync:core/downloads/candidates.py:459-470` |
| 7 | after 3 errors / 3 stalls | hybrid: mark Soulseek exhausted, re-search the other sources; else `failed` | once per source | `SoulSync:core/downloads/monitor.py:202-250`, `SoulSync:core/downloads/monitor.py:993-1046` |
| 8 | the file fails verification (AcoustID, integrity, duration) | quarantine; re-run walking the **cached** candidates first, then the queries not yet run | 5 per task (default); per-source budgets in the opt-in exhaustive mode, total ≤ 100 | `SoulSync:core/downloads/monitor.py:49-66`, `SoulSync:core/downloads/monitor.py:257-428`, `SoulSync:core/downloads/task_worker.py:141-195` |

`used_sources` survives every retry (`SoulSync:core/downloads/task_worker.py:435-439`). **Same peer again:** the same
`(peer, file)` is never retried, except the slow fallback above and the bundle's re-ask of an abandoned crawler; the
same peer with *another* file of the song can be (the key is `peer_filename`,
`SoulSync:core/downloads/candidates.py:520-525`). Whether `is_album_download` is ever set on a task's `track_info`,
which step 5's 15 s needs, is *unverified* (it is set on the batch and on the wishlist re-queue context,
`SoulSync:core/wishlist/processing.py:582`).

**Per album.** Inside the bundle (`SoulSync:core/soulseek_client.py:2099-2154`):
- the chosen folder's transfers end `complete`, `partial` (all terminal, some failed), `failed`, `timeout` (6 h
  default, `SoulSync:core/download_plugins/album_bundle.py:61-65`) or `unresolved` (slskd says done, no local file
  after 45 s). A peer frozen for 180 s has its stuck transfers cancelled with `remove=True` and counted failed
  (`SoulSync:core/soulseek_client.py:2405-2626`);
- unless `unresolved`, it walks up to **4** alternative folders in pre-flight order, **each of which must cover every
  track still owed**; a folder that cannot is skipped, not used partly (`SoulSync:core/soulseek_client.py:2197-2259`);
- with the opt-in speed check, a crawling folder is abandoned mid-way only when it already covers ≥ 0.8 and some
  alternative covers 100 %; the crawler's pending transfers are cancelled with `remove=True` and confirmed terminal
  first (3 polls), else it rides the crawler out (`SoulSync:core/soulseek_client.py:2104-2131`,
  `SoulSync:core/soulseek_client.py:2261-2295`); after a crawl switch, the crawler is asked again for whatever is
  still owed whenever something is, unless an alternative's cancellation was left unconfirmed
  (`SoulSync:core/soulseek_client.py:2136-2146`);
- nothing at all completed → fallback to per-track for the whole album
  (`SoulSync:core/soulseek_client.py:2148-2154`).
In the per-track fallback, the batch folder `peer:folder` is dropped for the rest of the batch (`failed_sources`) only
when no file from it starts (`SoulSync:web_server.py:16802-16810`), or when the task still holds the previous attempt's
peer and download id (`SoulSync:web_server.py:16737-16751`). Every monitor retry clears those first
(`SoulSync:core/downloads/monitor.py:973-976`, `SoulSync:core/downloads/monitor.py:1113-1116`,
`SoulSync:core/downloads/monitor.py:410-413`), so a transfer error or a verify failure does **not** drop the folder:
the next attempt tries it again, minus the `(peer, file)`s already used. The next per-track download that starts
elsewhere becomes the new batch folder (`SoulSync:web_server.py:16865-16872`).

**Against goal E** (primary folder → one secondary folder preferring the same release → per-track last,
`ours:docs/specs/2026-10-22-soulsync-review.md:41-42`):

| Goal E | SoulSync | Match? |
|---|---|---|
| one peer's folder for the whole album | yes when one folder covers ≥ 80 % and scores ≥ 0.62; only the matched files are enqueued | yes |
| on trouble, switch to **one** other folder | up to **4** others in a row, each only if it covers *all* that is owed | partly: more switches, stricter per switch |
| prefer the same release | folder score (title, year, count, variant words); no track lengths, no MusicBrainz release | no |
| switch the rest, not one track | yes inside the bundle; in the per-track fallback the batch folder moves with each success | partly |
| per-track only as the last resort | yes: tracks no folder supplied go per-track, any peer | yes |
| failure classes: start timeout of a peer | 180 s frozen-progress stall guard per bundle; 90 s (15 s) per track | yes, shorter |

**Against S2-04 and S1-06** (`ours:docs/specs/2026-10-22-downloads-and-requests.md:120-138`,
`ours:docs/specs/2026-10-22-downloads-and-requests.md:85-88`):

| Planned (ours) | SoulSync | Note |
|---|---|---|
| S2-04: one search `"<artist> <album>"` | 1-3 album queries, folders merged | more recall, more searches |
| S2-04: group by (peer, directory); map rows with the scorer's per-file rules (S1-01, D24) | group by (peer, directory), ≥ 2 hits; map by title key or fuzzy ≥ 0.80, one to one | S1-01's key rule is close to SoulSync's exact edge; the 0.80 fuzzy edge is looser than D26 |
| S2-04 primary: most rows covered, then summed quality, then slot and speed | weighted score with coverage 0.28, then a ±0.06 band re-sorted by peer speed; folders under 80 % coverage are never primary | ours lets a 6/9 folder be primary; SoulSync sends it per-track |
| S2-04 secondary: most of what the primary lacks; same release by lengths within 2 s or MB release, same format family | next folder in score order that covers **all** that is owed | ours is the "same release" rule SoulSync lacks |
| S2-04: a one-row folder is not a folder source | a 2-file folder is an album; coverage gate does the rest | similar |
| S2-04: at most two folders, then per-track | up to five folders, then per-track | ours caps churn |
| S2-05 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:139-156`): switch on transfer error, start timeout (600 s), a "not what it claims" verify finding, or 2 failures | switch on bundle end (partial/failed/timeout), frozen 180 s, or a crawl (opt-in); verify findings are per track (quarantine retry), never distrust a folder | ours distrusts a fake folder; SoulSync does not |
| S1-06: one more candidate from another peer on a transfer error, once per approval | 3 error retries, 3 stall retries, each a fresh search; 5 quarantine retries | ours is deliberately bounded by D7 |

### Peer memory

| What | Key | How long | Blocks | Cite |
|---|---|---|---|---|
| observed throughput | peer name (no IP or path) | 1 h TTL, at most 512 peers, in process memory (lost on restart) | nothing; orders the walk and the folder band | `SoulSync:core/downloads/peer_observation.py:1-50`, `SoulSync:core/downloads/peer_observation.py:71-81` |
| tried sources | `peer_filename` per task | the task's life | that file from that peer, for that track | `SoulSync:core/downloads/candidates.py:520-556` |
| failed batch folder | `peer:folder` per batch | the batch's life | folder reuse for that batch | `SoulSync:web_server.py:16723-16733` |
| quarantine record | `(peer, file)` from quarantine sidecars on disk | until the quarantine entry goes | that file in every search | `SoulSync:core/soulseek_client.py:2710-2749` |
| user blacklist | `(peer, file)` in `download_blacklist` | until removed | that file | `SoulSync:database/music_database.py:3749-3760`, `SoulSync:database/music_database.py:21381-21393`, `SoulSync:core/downloads/candidates.py:527-534` |
| failed-download blocklist | SHA1 of service + artist + title + size; **every peer collapses to `soulseek`** | 90 days, ≤ 5,000 rows | a file of that size and those names from any peer | `SoulSync:core/downloads/failed_blocklist.py:1-15`, `SoulSync:core/downloads/failed_blocklist.py:27-28`, `SoulSync:core/downloads/failed_blocklist.py:142-157` |

There is **no per-peer block** in the music download path: every key above includes the file or the batch, and a grep
of `core/` for per-peer blocks finds them only under `core/video` (skipped, non-music) (grep-based, so
*unverified* as an absence). A peer that sent a fake or a wrong song keeps its other files eligible. The artist /
album / track blocklist in `core/blocklist` bans metadata, not peers (`SoulSync:core/blocklist/__init__.py:1-6`). The
failed-download blocklist is recorded from the *wanted* track's artist and title and the picked size
(`SoulSync:core/downloads/failed_blocklist.py:160-176`) but checked against the *candidate's* parsed artist and title
(`SoulSync:core/downloads/failed_blocklist.py:142-154`), so it bites only when the filename parse equals the wanted
names (read from the code; how often is *unverified*). `soulseek_identity.py` stores nothing: it grades one path
against one wanted track (`SoulSync:core/downloads/soulseek_identity.py:1-14`). On the per-track path its result never
rejects: it is logged evidence (`SoulSync:core/downloads/validation.py:888-895`), and it can *admit* a row the score
put under 0.58 (the recovery pass, `SoulSync:core/downloads/validation.py:861-882`).

## How ours does it

**Search and pick** (`ours:sourcing/fetch.py:386-405`): one query `"<artist> <title>"`, an 8 s slskd search with
`maximumPeerQueueLength` 50 (`ours:sourcing/slskd_client.py:40-44`), wait up to 30 s for the state, read the
responses (re-read when a counted search answers `[]`, `ours:sourcing/slskd_client.py:58-66`), rank, delete the
search. The top unrejected candidate is downloaded, or the one Michael approved if still offered (D18). Without
`--approve` it prints the pick and stops (`ours:sourcing/fetch.py:397-398`); the worker only fetches approved rows,
one approval at a time (`ours:sourcing/worker.py:267-279`), so every row of an album is its own search and its own
peer.

**Score terms** (`ours:sourcing/scorer.py:138-254`), about 0-100:

| Term | Numbers | Cite |
|---|---|---|
| rejections | format not allowed, locked file, lossy under the floor, name match < 0.55, another version (D26), implied lossless rate < 500 kbps | `ours:sourcing/scorer.py:141-151`, `ours:sourcing/scorer.py:155-156`, `ours:sourcing/scorer.py:165-176`, `ours:sourcing/scorer.py:184-187` |
| name match | 45 × best of three passes (artist-title ratio, × 0.85 without the artist in the path; title + artist in path; title in the title slot + artist in path) | `ours:sourcing/scorer.py:91-117`, `ours:sourcing/scorer.py:157` |
| format | 20 − 5 × rank in the preferred list | `ours:sourcing/scorer.py:178-181` |
| lossless sanity | +6 plausible; −5 odd sample rate, −5 odd bit depth; +2 hi-res | `ours:sourcing/scorer.py:183-195` |
| duration | +15 within 4 s, +3 within 20 s, −15 beyond | `ours:sourcing/scorer.py:197-211`, `ours:sourcing/policy.py:32-33` |
| album / year in folder | +4 / +2 | `ours:sourcing/scorer.py:223-227` |
| peer | free slot +5, none −3; queue > 50 −7, > 10 −3; ≥ 2 MB/s +5, < 200 kB/s −3; ≥ 4 matching files from that peer +2 | `ours:sourcing/scorer.py:229-244` |
| speed blend | `speed_weight` 0 in every live tier, so off | `ours:sourcing/scorer.py:246-251`, `ours:deploy/policy.toml:28`, `ours:deploy/policy.toml:37`, `ours:deploy/policy.toml:46`, `ours:deploy/policy.toml:55` |

**D24 floor** (`ours:docs/specs/2026-10-17-amperfy-pivot.md:19`): lossless, or mp3/m4a at ≥ 256 kbps; ogg, opus,
wma refused; strict verify on every tier (`ours:deploy/policy.toml:5-6`, `ours:deploy/policy.toml:31`, `ours:deploy/policy.toml:40`, `ours:deploy/policy.toml:49`, `ours:deploy/policy.toml:58`). The
scorer reads it as `format_rank` (allow/deny) and `min_lossy_bitrate` (`ours:sourcing/policy.py:25-26`, `ours:sourcing/policy.py:51-58`,
`ours:sourcing/scorer.py:142-151`).

**Failure:** a transfer that ends in any `Completed, …` other than `Succeeded`, or runs past the 600 s timeout,
fails the row with no second candidate (`ours:sourcing/fetch.py:430-446`, `ours:sourcing/fetch.py:162`); a verify
failure deletes the file and fails the row (`ours:sourcing/fetch.py:462-464`). A failed row waits for Michael's next
approval (D7). **Peer memory: none that blocks.** Nothing in `sourcing/` blocks a peer or a file across attempts (a
grep for blocklist/blacklist/peer state finds only the policy's word "blacklist", `ours:sourcing/policy.py:3`). The
only carry-over is the approved candidate (peer and file), passed to the next fetch as `prefer` and taken while still
offered (`ours:sourcing/worker.py:278`, `ours:sourcing/fetch.py:399-405`): a preference, not a block. A retry runs a
fresh search and may pick the same failed peer and file.

**Albums:** there is no album path today. The only album signal is +4 for a folder named like the album and +2 for a
peer with ≥ 4 matching files (`ours:sourcing/scorer.py:224-225`, `ours:sourcing/scorer.py:243-244`). On 10-21 the
Al Green album's tracks therefore came from 5 peers and 4 releases
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:48-50`,
`ours:docs/specs/2026-10-22-downloads-and-requests.md:100-102`). S2-04/S2-05 plan the album path
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:120-165`); S1-06 the one retry
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:85-88`). The S1 branch
`origin/harness/dj-crate-streaming-2026-10-22-fixes` did not exist on 2026-10-22 (`git ls-remote` printed nothing),
so none of S1 is compared as built.

**What `fake_slskd` models** (`ours:sourcing/fake_slskd.py:1-12`): every search completes at once with the same
fixed `responses`, whatever the query (`ours:sourcing/fake_slskd.py:106-108`, `ours:sourcing/fake_slskd.py:121-129`);
`empty_reads` empty answers first (`ours:sourcing/fake_slskd.py:34`); an enqueue writes the bytes and is `Completed,
Succeeded` at once, or stays `InProgress` forever with `complete=False`, or answers 500 with `fail_enqueue`
(`ours:sourcing/fake_slskd.py:57-67`, `ours:sourcing/fake_slskd.py:109-113`); per-peer transfer listing grouped by
directory with slskd 0.26's 404 for a peer with none (`ours:sourcing/fake_slskd.py:69-74`,
`ours:sourcing/fake_slskd.py:133-138`); any DELETE removes the record (`ours:sourcing/fake_slskd.py:142-151`).
It does **not** model: different results per query, a folder browse (`/users/{peer}/directory`), queued or slow
peers, a transfer that fails part-way (`Completed, Errored`, `Rejected`, `TimedOut`), several files with mixed
outcomes, or `remove=true` (S1-04 plans that, `ours:docs/specs/2026-10-22-downloads-and-requests.md:76-79`). An
album job and a folder switch cannot be tested on it as it stands.

## The difference that matters

(part 2, transfers: V2-03b)

- **Goal E (album-first).** SoulSync has a working album-first path: score folders as releases, take one, enqueue
  only the matched files, switch to other folders on trouble, per-track for what is left. That is the shape S2-04/05
  plan. Its gaps are exactly where S2-04 is stricter: no "same release" test (no track lengths, no MusicBrainz
  release), up to five folders instead of two, and a verify failure never distrusts the folder (fakes come as folders).
- **The exact track (D26).** The bundle's file mapping is title-key equality with a fuzzy ≥ 0.80 edge; the
  source-reuse path uses the base score at ≥ 0.70 with no base-title veto, which is the ext-74 shape. Ours must not
  copy the reuse path; S1-01's key equality is the rule to apply on every path, folder ones included.
- **D7 (nothing without approval).** SoulSync retries on its own: 3 + 3 + 5 attempts per track, each a fresh search
  that may pick any peer, plus hybrid fallbacks. S1-06's "one more source, once per approval" is the bound we need;
  SoulSync's counts are not portable.
- **D24.** SoulSync's quality layer is a profile ladder that keeps only the best rung present, with an optional
  fallback to anything; D24 is a fixed floor. Our rejection rules are simpler and stricter (implied lossless rate).
- **Peer speed.** SoulSync measures real throughput per peer (1 h memory) and lets it reorder candidates of equal
  correctness and folders of equal score. Ours ranks by advertised slot/queue/speed only and, with `speed_weight` 0,
  arrival time is ignored. A measured-speed tie-break inside an equal band is cheap and fits S2-04's "then free slot
  and speed".
- **Failure classes.** "One album spread across 5 peers and 4 releases": SoulSync would most likely have taken one
  folder (if one covered ≥ 80 %); hand-off of the missing tracks goes to any peer, so a mix can still happen, but only
  for the tracks no qualifying folder had. "Wrong song from a same-named album folder": safe on the bundle path,
  unsafe on the reuse path (above). "VPN drops": every errored transfer is retried up to 3 times, a fresh search each
  time (part 2 covers the outage detection).

## Worth taking?

(part 2, transfers: V2-03b)

- **Take (adapt):** the album flow's structure for S2-04/S2-05: group by (peer, directory), map wanted tracks to
  files one to one by maximum matching (`assign_album_tracks` is the right algorithm; our edge is S1-01's key rule plus
  D26's version label, with no fuzzy edge), a coverage floor for a folder to count as an album source, enqueue only
  the matched files, keep completed tracks when switching, and per-track for the rest. Paraphrase, don't copy (brief).
- **Take:** measured peer throughput as a tie-break (an in-process map, 1 h TTL, exponential weighting,
  `SoulSync:core/downloads/peer_observation.py:28-50`) and the "frozen for N seconds → cancel with `remove=True`" stall
  guard for a folder. Both are small and need no new slskd shape.
- **Take as test cases:** browse-before-trust (search hits are a subset; re-check coverage on the full listing) once
  we capture `/users/{peer}/directory` (part 2); a folder that crawls; a folder that has 8 of 9.
- **Do not take:** the multi-query ladders (one search per album is S2-04's choice and spares Soulseek), the 0.70 base
  score reuse, the autonomous retry budgets (D7), five-folder walks, the per-file `failed_blocklist` fingerprint
  without a peer, and the fuzzy 0.80 title edge.

**Verdict:** adapt. SoulSync's Soulseek album path is the closest working example of goal E we have, and S2-04/S2-05
already plan the same shape with the two rules it lacks (same release by lengths/MusicBrainz, distrust a fake folder)
and a tighter bound (two folders, one retry per approval). Take the structure and the measured-speed tie-break; keep
our exact-track rules on every path. Part 2 may revise this after the transfer side.
