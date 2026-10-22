# 04 · Soulseek sourcing (search, scoring, folders, fallbacks, peer memory, transfers, endpoints)

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed).
Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a claim
without one. Numbers marked **hand estimate** were re-computed with a few lines of our own stdlib Python (difflib) in
the run's scratch directory, never by running SoulSync. Part 1 (V2-03a) covers search, scoring, folder choice,
fallbacks and peer memory; part 2 (V2-03b) covers enqueue, transfer polling, cancel and remove, 4xx/5xx and outage
handling, throttling and the slskd endpoint table (`### Transfers` onwards). The candidate *match* score (title/artist/duration weights, the base-title veto,
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
instead of `timeout` (`ours:sourcing/slskd_client.py:42-43`); which key slskd 0.26 reads is *unverified* here (the
`POST /searches` capture with each key, below, would settle it) and goes to the endpoint table below.

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
lengths (the cited code; a grep for MusicBrainz ids over the matching engine, candidate, validation, identity and
slskd client modules finds none, and the MusicBrainz release an album batch pins is for tagging only,
`SoulSync:core/downloads/master.py:757-765`, read back in post-processing, `SoulSync:core/metadata/source.py:525-527`).

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
3. **Browse** the winner's folder (`POST users/{peer}/directory`, see the endpoint table) and re-check coverage ≥ 0.8 on the full
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
`SoulSync:core/downloads/candidates.py:520-525`). Step 5's 15 s reads `is_album_download` from the task's `track_info`
(`SoulSync:core/downloads/monitor.py:1073-1074`), but no Python line writes that key there (grep): album batches put
`_is_explicit_album_download` on `track_info` (`SoulSync:core/downloads/master.py:1586`,
`SoulSync:core/downloads/master.py:1679`) and `is_album_download` on batches and post-processing contexts, never on `track_info`
(`SoulSync:core/downloads/pinned_batch.py:136`, `SoulSync:core/wishlist/processing.py:153`) and the wishlist re-queue
context (`SoulSync:core/wishlist/processing.py:582`). So the 15 s applies only if a track dict handed in (browser
JSON, a wishlist row's data) already carries the key at top level; read from the code, it is 90 s.

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
| quarantine record | `(peer, file)` in `quarantine_source_blocks` (plus any sidecars still on disk) | no TTL, oldest pruned past 25,000 rows; survives the 12-hourly quarantine purge | that file in every search | `SoulSync:core/imports/quarantine.py:107-135`, `SoulSync:core/imports/guards.py:107-124`, `SoulSync:database/music_database.py:24102`, `SoulSync:core/soulseek_client.py:2710-2749` |
| user blacklist | `(peer, file)` in `download_blacklist` | until removed | that file | `SoulSync:database/music_database.py:3749-3760`, `SoulSync:database/music_database.py:21381-21393`, `SoulSync:core/downloads/candidates.py:527-534` |
| failed-download blocklist | SHA1 of service + artist + title + size; **every peer collapses to `soulseek`** | 90 days, ≤ 5,000 rows | a file of that size and those names from any peer | `SoulSync:core/downloads/failed_blocklist.py:1-15`, `SoulSync:core/downloads/failed_blocklist.py:27-28`, `SoulSync:core/downloads/failed_blocklist.py:142-157` |

There is **no per-peer block** in the music download path: every key above includes the file or the batch, and a grep
of `core/` for per-peer blocks finds them only under `core/video` (skipped, non-music): the one per-user check,
`blocked_usernames`, is in the video database (`SoulSync:database/video_database.py:3688-3691`) and is called only
from `core/video` and `api/video` (`SoulSync:core/video/download_monitor.py:1377`, `SoulSync:api/video/downloads.py:247`),
while the music `is_blacklisted` takes peer and file together (`SoulSync:database/music_database.py:21381-21390`)
(grep-based). A peer that sent a fake or a wrong song keeps its other files eligible. The artist /
album / track blocklist in `core/blocklist` bans metadata, not peers (`SoulSync:core/blocklist/__init__.py:1-6`). The
failed-download blocklist is recorded from the *wanted* track's artist and title and the picked size
(`SoulSync:core/downloads/failed_blocklist.py:160-176`) but checked against the *candidate's* parsed artist and title
(`SoulSync:core/downloads/failed_blocklist.py:142-154`), so it bites only when the filename parse equals the wanted
names (read from the code; how often is *unverified*, and logging the parsed against the wanted names over real
searches would measure it). `soulseek_identity.py` stores nothing: it grades one path
against one wanted track (`SoulSync:core/downloads/soulseek_identity.py:1-14`). On the per-track path its result never
rejects: it is logged evidence (`SoulSync:core/downloads/validation.py:888-895`), and it can *admit* a row the score
put under 0.58 (the recovery pass, `SoulSync:core/downloads/validation.py:861-882`).

### Transfers

**Enqueue: one POST per file.** `download(username, filename, size)` POSTs `transfers/downloads/{username}` with a
one-element array `[{"filename", "size", "path"}]`, where `path` is SoulSync's own download directory, sent as a
"Try custom download path" (`SoulSync:core/soulseek_client.py:860-878`). Whether slskd 0.26 reads a `path` field is
*unverified* (SoulSync's own comment calls it a try, `SoulSync:core/soulseek_client.py:861`; enqueuing one file with a
`path` on 0.26 and checking where it lands would verify it); SoulSync finds the file afterwards from its own `soulseek.download_path` either way
(`SoulSync:core/soulseek_client.py:2628-2666`). An album is enqueued the same way, one POST per matched file in a
loop (`_enqueue_album_tracks`, `SoulSync:core/soulseek_client.py:2184-2195`). No call puts several files in one
body. When the POST answers anything but 2xx (or times out), it tries three other paths with the same array, then the
same three with an object body `{"files": [{"filename", "size"}]}`: up to **7 POSTs** for one file, whatever the
first error was (`SoulSync:core/soulseek_client.py:894-960`). Those paths are untargeted "alternative patterns"
(`SoulSync:core/soulseek_client.py:894-902`); whether 0.26 has any of them is *unverified* (0.26's
`GET /swagger/v1/swagger.json` or its controller routes would settle it).

**The transfer id.** `_extract_transfer_id` takes the id from `{"enqueued": [Transfer, …], "failed": […]}`, matching
the filename or using a single entry, or from an older bare `{"id"}` / `[{"id"}]` body
(`SoulSync:core/soulseek_client.py:968-993`). With no id, `download` returns **the filename** as the "id"
(`SoulSync:core/soulseek_client.py:881-887`). Two comments in the same file disagree on what slskd 0.26 sends: one
says 0.25.x/0.26 answers 201 with `enqueued` Transfer records (`SoulSync:core/soulseek_client.py:971-973`), the other
that "an enqueue response carries no id, which slskd 0.26 does" (`SoulSync:core/soulseek_client.py:998-1000`).
SoulSync's tests pin the first shape by hand, and their comment names slskd's `TransfersController.EnqueueAsync` in
0.25.1 and 0.26.0 as the source (`SoulSync:tests/test_soulseek_scoped_cleanup.py:208-213`); no captured response backs
it (*unverified* as a capture; the enqueue-reply capture below, S4-01, would verify it). Only an id from the response is recorded as "ours". It goes into a
persistent registry (`soulseek_owned_transfers` in the metadata table), never the filename ("fail closed",
`SoulSync:core/soulseek_client.py:838-849`, `SoulSync:core/soulseek_client.py:1387-1388`).

**How it finds its own transfer afterwards.** On the main paths, by peer and filename, not by id:
- the per-track monitor reads the **global** listing `GET transfers/downloads` once per 1 s tick
  (`SoulSync:core/downloads/monitor.py:553-562`, `SoulSync:core/downloads/monitor.py:759`). It keys every file by
  `(username, full remote path)` (`SoulSync:core/downloads/monitor.py:760-768`,
  `SoulSync:core/downloads/monitor.py:449-461`). A second record under the same key overwrites the first (a dict
  assignment, `SoulSync:core/downloads/monitor.py:768`), so the last one listed wins, like our `mine[-1]`;
- the bundle reads the same listing every 2 s and indexes it by `(username, filename)`. It falls back to
  `(username, basename)` because "slskd sometimes reports a path spelled differently"
  (`SoulSync:core/soulseek_client.py:83-100`);
- `get_download_status(id)` asks `GET transfers/downloads/{id}` for a UUID-like id. A filename "id" is looked up in
  the listing by basename instead, because asking for it as a path made slskd answer 400/405 and cancelled good
  transfers (#1229, `SoulSync:core/soulseek_client.py:995-1034`, `SoulSync:core/soulseek_client.py:1036-1042`). On
  slskd 0.26, `transfers/downloads/{x}` is the per-peer route (ours:docs/specs/2026-10-22-downloads-and-requests.md:25),
  so a UUID there would be read as a username. That is *unverified* (`GET /transfers/downloads/<transfer id>` on 0.26,
  in the S4-01 captures, would show a 404 or the record). Callers: post-processing and the status fallback
  (`SoulSync:core/downloads/post_processing.py:300`, `SoulSync:core/downloads/status.py:288`).

**Poll loops and timeouts.**

| What | Number | Cite |
|---|---|---|
| every slskd HTTP call | total 120 s, connect 15 s, socket read 60 s (#499: unbounded calls wedged all 3 workers) | `SoulSync:core/soulseek_client.py:39-61` |
| per-track monitor tick | 1 s, one global listing per tick | `SoulSync:core/downloads/monitor.py:562`, `SoulSync:core/downloads/monitor.py:759` |
| transfer errored (`Errored`, `Failed`, `Rejected`, `TimedOut`) | retry at once, ≥ 5 s apart, 3 times | `SoulSync:core/downloads/monitor.py:922`, `SoulSync:core/downloads/monitor.py:937` |
| queued too long | 90 s (15 s when `track_info.is_album_download`), 3 times, ≥ 30 s apart | `SoulSync:core/downloads/monitor.py:1062-1084` |
| `InProgress` below 1 % | 90 s (15 s when `track_info.is_album_download`), 3 times, ≥ 30 s apart | `SoulSync:core/downloads/monitor.py:1160-1180` |
| gone from the listing | 90 s, 3 times, ≥ 30 s apart, then `failed` | `SoulSync:core/downloads/monitor.py:854-858`, `SoulSync:core/downloads/monitor.py:895-912` |
| "Completed" before every byte | `bytesTransferred < size` → wait, not done | `SoulSync:core/downloads/monitor.py:637-644`, `SoulSync:core/soulseek_client.py:2475` |
| error state with no retry progress | 60 s, then `failed` (#836) | `SoulSync:core/downloads/status.py:48` |
| `searching` too long | 600 s → `not_found` | `SoulSync:core/downloads/lifecycle.py:1160-1166` |
| `post_processing` too long | 1,800 s → `completed` if the file exists, else `failed` | `SoulSync:core/downloads/lifecycle.py:57`, `SoulSync:core/downloads/lifecycle.py:1169-1178` |
| bundle poll | every 2 s, deadline 6 h | `SoulSync:core/download_plugins/album_bundle.py:64-65` |
| bundle: nothing moves | 180 s → stuck transfers cancelled (`remove=True`) and failed | `SoulSync:core/soulseek_client.py:2438`, `SoulSync:core/soulseek_client.py:2551-2564` |
| bundle: slskd says done, no local file | 45 s → `unresolved` | `SoulSync:core/soulseek_client.py:2424` |
| bundle: confirm a cancel before switching | 3 listings ≤ 1 s apart | `SoulSync:core/soulseek_client.py:2283-2295` |

**Cancel and remove.** `cancel_download(id, username, remove=False)` first finds the username in the listing if it
wasn't given. It then tries, stopping at the first answer that isn't None: `DELETE
transfers/downloads/{username}/{id}?remove={remove}`, `DELETE transfers/downloads/{id}`, and `DELETE
transfers/downloads/{username}/{id}` **without** the query. For a filename "id" it ends with a listing lookup by
basename and a DELETE with the real id (`SoulSync:core/soulseek_client.py:1159-1231`). So when the first form fails,
forms 2 and 3 (neither carries `?remove=`, `SoulSync:core/soulseek_client.py:1191-1193`) can turn a remove into a
plain cancel, which leaves the record (read from the code). `remove` defaults to
False, but every download-path caller passes `remove=True`: the monitor's deferred cancel
(`SoulSync:core/downloads/monitor.py:690`), the slow-transfer replacement
(`SoulSync:core/downloads/monitor.py:131-132`), a task cancelled mid-start
(`SoulSync:core/downloads/candidates.py:923`), the bundle's stall guard and folder switch
(`SoulSync:core/soulseek_client.py:2564`, `SoulSync:core/soulseek_client.py:2276`) and the manual cancel
(`SoulSync:core/downloads/cancel.py:51`). Only the clients tab passes the request's own flag
(`SoulSync:api/clients.py:304-305`). `signal_download_completion` names the pattern at
`SoulSync:core/soulseek_client.py:1250`: `?remove=true` means "completion", false means "cancellation"
(`SoulSync:core/soulseek_client.py:1234-1266`). Its only caller is the stream-preview path, as a fallback
(`SoulSync:core/streaming/prepare.py:279-283`).

**Finished transfers are not removed when they finish.** The per-track path hands the file to post-processing and
sends no DELETE (`SoulSync:core/downloads/monitor.py:645-664`). The bundle copies the files into staging and deletes
slskd's *files* (`remove_source=True`), but not the *records* (`SoulSync:core/soulseek_client.py:2156-2160`). Records
are removed by `clear_all_completed_downloads`. In scope `own` (the default) it reads the listing and sends `DELETE
…?remove=true` for each terminal record whose id is in the registry; it then prunes registry ids slskd no longer lists
(`SoulSync:core/soulseek_client.py:1589-1670`). Scope `all` sends `DELETE transfers/downloads/all/completed`, which
clears every client's completed, cancelled and errored transfers (`SoulSync:core/soulseek_client.py:1595-1617`). This
runs from the system automation "Clean Completed Downloads" every 5 min (`SoulSync:core/automation_engine.py:190-196`),
which skips any run while a batch is active (`SoulSync:core/automation/handlers/download_cleanup.py:70-94`); from each
music batch's end, in its wishlist step, without checking other batches ("[Auto-Cleanup] … after batch",
`SoulSync:core/downloads/wishlist_failed.py:266-272`, wired at `SoulSync:web_server.py:16202-16208`); from the 12-hourly
`full_cleanup` automation (`SoulSync:core/automation_engine.py:246-249`,
`SoulSync:core/automation/handlers/download_cleanup.py:158`); and from the Downloads page's clear buttons
(`SoulSync:core/downloads/cancel.py:55-74`). Two consequences, read from the code: a finished record stays in slskd until
the batch that made it ends (or a 5-min run finds no active batch), and a transfer whose enqueue reply had no id is never
"own", so scope `own` never removes it (`SoulSync:core/soulseek_client.py:1506-1510`).

**Searches are not deleted after use either.** The search id is remembered (`SoulSync:core/soulseek_client.py:727`).
Searches are removed by "Clean Search History", run hourly, which deletes the oldest down to 50 once the client owns
more than 200 (`SoulSync:core/automation_engine.py:183-189`,
`SoulSync:core/automation/handlers/download_cleanup.py:44-51`, `SoulSync:core/soulseek_client.py:1845-1906`), by the
`full_cleanup` automation (`SoulSync:core/automation/handlers/download_cleanup.py:268`) and by manual endpoints
(`SoulSync:web_server.py:8529-8556`). `close()` on shutdown deletes only searches still in flight: each finished search
drops its id from `active_searches` in its own `finally` (`SoulSync:core/soulseek_client.py:3117-3136`,
`SoulSync:core/soulseek_client.py:835-837`).

**A track task's states.** Non-terminal states: `pending`, `queued`, `searching`, `downloading`, `post_processing`
(`SoulSync:core/downloads/master.py:603`). Terminal states: `completed`, `failed`, `not_found`, `cancelled`, `skipped`,
`already_owned` (`SoulSync:core/downloads/cancel.py:40-42`).

```
 pending ──► searching ──► downloading ─────────────────────────────────────────┐ "Completed, Succeeded", all bytes
 master:1771  task_worker:430  candidates:568  (UI shows "queued" while slskd says Queued, status:610-613)   │
     ▲                                                                         ▼
     │                                                              post_processing ──► completed | failed
     │                                                              monitor:660           (verify, tag, move)
     └── searching again: errored, stuck, gone, slow, quarantined (monitor:887, 979, 1119, 1215, 1329, 415)
 searching ──► not_found: no query started a download (task_worker:926), or searching > 600 s (lifecycle:1164)
 any ──► failed: retries used up (monitor:908-912); cancelled: by the user, or slskd says "Cancelled" (status:507-508)
```

The diagram's lines, cited: `SoulSync:core/downloads/master.py:1771`, `SoulSync:core/downloads/task_worker.py:430`,
`SoulSync:core/downloads/monitor.py:660`; the resets to `searching` at `SoulSync:core/downloads/monitor.py:887`,
`SoulSync:core/downloads/monitor.py:979`, `SoulSync:core/downloads/monitor.py:1119`,
`SoulSync:core/downloads/monitor.py:1215`, `SoulSync:core/downloads/monitor.py:1329` and
`SoulSync:core/downloads/monitor.py:415`; `not_found` at `SoulSync:core/downloads/task_worker.py:926` and
`SoulSync:core/downloads/lifecycle.py:1164`; `failed` at `SoulSync:core/downloads/monitor.py:908-912`; `completed`
after post-processing's import at `SoulSync:core/imports/pipeline.py:1816-1819`, and by stuck detection for a
`post_processing` task whose file exists at `SoulSync:core/downloads/lifecycle.py:1169-1175`. `downloading` is set **before** the enqueue POST (`SoulSync:core/downloads/candidates.py:568`) and stays until
post-processing or a retry. `queued` is only a *reported* status: the status builder sets it in the UI payload
(`task_status`) from slskd's state (`SoulSync:core/downloads/status.py:610-613`), and a grep of `core/downloads` and
`web_server.py` finds no line setting a track task's own status to `queued`. The staging
shortcut jumps from `searching` straight to `post_processing` (`SoulSync:core/downloads/staging.py:1-25`). A peer that
cancels (`Completed, Cancelled`) makes the task `cancelled`, as if the user had done it, and nothing retries
(`SoulSync:core/downloads/status.py:503-508`). The monitor's error tokens are `Errored`, `Failed`, `Rejected` and
`TimedOut` (`SoulSync:core/downloads/monitor.py:632`, `SoulSync:core/downloads/monitor.py:922`); the bundle adds
`Aborted` and `Cancelled` (`SoulSync:core/soulseek_client.py:2465-2466`). A per-track `Completed, Aborted`
is neither an error token nor `Queued`/`InProgress`, so it falls to the monitor's unknown-state branch
(`SoulSync:core/downloads/monitor.py:1253-1262`): with no bytes the 90 s timer retries it like a 0 % stall; with some
bytes the timers reset, and the completion check sees `Completed` with bytes short and waits
(`SoulSync:core/downloads/monitor.py:632-644`), so the monitor sets no timer; once the task is 600 s old (`soulseek.download_timeout`), the status builder's safety valve, which runs only while the batch status is polled, probes for the file and marks the task `failed` if it is not there (`SoulSync:core/downloads/status.py:418-436`, `SoulSync:core/downloads/status.py:97-120`; read from the code, not run). Batches have their own `phase` (e.g. `downloading`,
`SoulSync:core/downloads/master.py:1476`); it is not listed here.

### Errors and outages

**4xx/5xx.** One handler serves every call. `_make_request` returns parsed JSON (or `{}`) for 200/201/204 and None for
anything else. It logs a 404 at debug level, the first 401 as a warning (later ones are suppressed), and every other
code as an error. A 429 on `POST searches` starts the shared cooldown (`SoulSync:core/soulseek_client.py:235-273`).
Timeouts (`asyncio.TimeoutError`), connection errors (`aiohttp.ClientConnectorError`, counted in `_conn_failures`) and
any other exception also return None (`SoulSync:core/soulseek_client.py:275-306`). **Nothing at this layer retries or
backs off. The status is logged per call (with reason and body; method and URL only at debug), but it never reaches
the caller or the task's reason.** Each caller reads None its own way. A search returns
`([], [])` (`SoulSync:core/soulseek_client.py:711-713`). An enqueue walks the 7-POST cascade, then the next candidate
(part 1, step 1). A listing becomes `[]` (`SoulSync:core/soulseek_client.py:1079-1082`). A cancel tries the next form,
and a bundle poll sees an empty listing for that tick (`SoulSync:core/soulseek_client.py:2441-2446`). Retries live a
level up, in the monitor's counts above.

**Backoff after connection failures.** `unreachable_backoff_active` waits 15 s after one failure, doubling up to 300 s;
any answer resets it (`SoulSync:core/soulseek_client.py:3103-3111`, `SoulSync:core/soulseek_client.py:232`). Only the
chat pollers use it (`SoulSync:web_server.py:22801`, `SoulSync:web_server.py:22977`); downloads do not.

**Detecting "slskd down" or "not logged in".** `check_connection` reads `GET server`, then `GET server/state`, and
needs both `isConnected` and `isLoggedIn`. Without them it falls back to "did `GET session` answer"
(`SoulSync:core/soulseek_client.py:2668-2690`). `get_chat_connection_state` probes the same two endpoints for chat, without the `session` fallback; the endpoint
note is at `SoulSync:core/soulseek_client.py:2901-2902`, the loop at `SoulSync:core/soulseek_client.py:2905-2916`. The
dashboard's status calls it (`SoulSync:web_server.py:3492-3507`), and so does the connection test
(`SoulSync:core/connection_test.py:208`). **No download path calls it.** A grep of `core/downloads`,
`core/download_engine`, `core/wishlist` and `download_orchestrator.py` for `check_connection`, `isConnected` and
`isLoggedIn` finds only the orchestrator's pass-through (`SoulSync:core/download_orchestrator.py:243-259`).
`core/connection_detect.py` is the settings page's LAN auto-detect, not an outage check: it scans the subnet for
`GET /api/v0/session` on port 5030 (`SoulSync:core/connection_detect.py:18-26`,
`SoulSync:core/connection_detect.py:121-135`). Nothing handles a VPN: a grep for `vpn` and `gluetun` over every `.py` file in the clone finds
only a Tidal error hint (`SoulSync:core/tidal_download_client.py:505`) and an Invidious host name
(`SoulSync:core/video/youtube.py:268`).

**What happens to transfers in flight**, read from the code (not run):
- **slskd unreachable** (restart, container down). `_make_request` returns None instead of raising, so the monitor's
  "poll failed" guard (`SoulSync:core/downloads/monitor.py:576-583`) never fires. Its Soulseek half of the lookup is
  simply empty (`SoulSync:core/downloads/monitor.py:759-768`), and every Soulseek task looks *gone from slskd's list*.
  The 90 s counts from the task's last status change, not from the outage (`SoulSync:core/downloads/monitor.py:854`),
  so on the first tick every task idle in its state for over 90 s is retried: a cancel (which fails while slskd is
  down), its `(peer, file)` marked used, and the worker re-run. While slskd stays down that re-search gets `([], [])`
  (`SoulSync:core/soulseek_client.py:711-713`), the task ends `not_found` (`SoulSync:core/downloads/task_worker.py:918-927`)
  and the monitor stops watching it (`SoulSync:core/downloads/monitor.py:609`). Three rounds and `failed` ("disappeared
  from transfer list 3 times") happen only if slskd answers in between (`SoulSync:core/downloads/monitor.py:854-912`). The guard's tests use an orchestrator that *raises*
  (`SoulSync:tests/downloads/test_backend_review_downloading.py:97-133`), so the None path is untested. Meanwhile the
  real transfers keep running in slskd. The retry put their key in `_orphaned_download_keys`
  (`SoulSync:core/downloads/monitor.py:870-881`); when one completes later, the `/api/downloads/status` handler deletes
  the landed file and cancels the record with `remove=True`, unless the retry re-used that source
  (`SoulSync:web_server.py:7392-7428`). That runs only while a browser polls that endpoint.
- **slskd unreachable during a bundle.** Every poll sees an empty listing
  (`SoulSync:core/soulseek_client.py:2441-2446`). Nothing moves, so after 180 s every pending transfer is marked
  `Stalled`; its cancel is skipped, because an empty listing gives no id. The bundle then ends `partial` or `failed`,
  and the rest goes to alternatives and per-track (`SoulSync:core/soulseek_client.py:2525-2610`).
- **VPN drop** (slskd stays up but is logged out of Soulseek for about 10 s,
  ours:docs/specs/2026-10-22-downloads-and-requests.md:44-47). A transfer that ends `Completed, Errored` is retried at
  once (≥ 5 s): cancel with `remove=True`, `(peer, file)` marked used, a full re-search
  (`SoulSync:core/downloads/monitor.py:922-985`). Nothing waits for slskd to log in again. What slskd 0.26 answers to a
  search made while logged out is *unverified* (the `GET /server` capture during a drop, below, plus one search then,
  would verify it). If no query starts a download the task becomes `not_found`
  (`SoulSync:core/downloads/task_worker.py:918-927`). Failed and cancelled tracks are collected for the wishlist
  (`SoulSync:core/downloads/lifecycle.py:10-13`), and its automatic run retries them (`02-intake.md`). In a bundle,
  the errored file fails and the walk to alternative folders covers it (`SoulSync:core/soulseek_client.py:2463-2472`).

### Throttling

- **Search creation:** one process-wide sliding window of **35 searches per 220 s**, shared by music and video. Each
  caller reserves its own slot, so concurrent searches get distinct start times
  (`SoulSync:core/slskd_throttle.py:1-23`, `SoulSync:core/slskd_throttle.py:32-33`,
  `SoulSync:core/slskd_throttle.py:40-63`). That 35/220 is slskd's limit by SoulSync's comment only (*unverified*
  against slskd; slskd 0.26's search rate-limit setting, or 36 searches inside 220 s answered 429, would verify it). There is an optional gap between searches, `soulseek.search_min_delay_seconds`, default 0, added for
  an ISP that cuts the line after bursts (`SoulSync:core/soulseek_client.py:63-71`,
  `SoulSync:core/soulseek_client.py:124-135`, `SoulSync:core/soulseek_client.py:171-192`). A 429 on `POST searches`
  sets a shared cooldown: `Retry-After`, else 30 s, clamped to 5-120 s (`SoulSync:core/slskd_throttle.py:66-73`,
  `SoulSync:core/soulseek_client.py:265-268`). `max_wait_seconds` lets a caller get "rate limited" instead of blocking
  (`SoulSync:core/slskd_throttle.py:45-61`), but music searches never pass it and always wait
  (`SoulSync:core/soulseek_client.py:183`); only the video side does (skipped).
- **Concurrency:** the per-track pool has `max(3, min(download_source.max_concurrent, 16))` threads, default 3
  (`SoulSync:web_server.py:1424-1432`). Each batch runs `max_concurrent` at a time, but a Soulseek album batch runs
  **one at a time** (`SoulSync:web_server.py:2187-2205`). When Soulseek is in play, a global cap equal to
  `max_concurrent` applies across all batches (#1166, `SoulSync:web_server.py:2207-2238`). Album bundles have their own
  3-thread pool (`SoulSync:web_server.py:1434-1442`).
- **`core/download_engine/rate_limit.py`** gives each source a `RateLimitPolicy(download_concurrency=1,
  download_delay_seconds=0.0)`, applied to the engine's worker at registration
  (`SoulSync:core/download_engine/rate_limit.py:31-54`, `SoulSync:core/download_engine/rate_limit.py:57-76`,
  `SoulSync:core/download_engine/engine.py:117-135`). Only YouTube declares its own policy
  (`SoulSync:core/youtube_client.py:616`). `SoulseekClient` declares none and never dispatches through the engine
  worker (a grep of `soulseek_client.py` for `set_engine` and `engine.worker` finds nothing). For Soulseek the policy is
  the inert default, and transfer concurrency is slskd's own business. SoulSync sets no slskd limit: it only reads `options` (row 23), and
  its POSTs and one PUT go to searches, enqueue, browse and chat (`SoulSync:core/soulseek_client.py:710`,
  `SoulSync:core/soulseek_client.py:877`, `SoulSync:core/soulseek_client.py:1283`,
  `SoulSync:core/soulseek_client.py:2924-2964`; grep-based).

### Every slskd endpoint SoulSync calls

Every call goes to `{slskd_url}/api/v0/{endpoint}` with an `X-API-Key` header
(`SoulSync:core/soulseek_client.py:199-212`). `_make_direct_request` builds the URL without the `/api/v0/` prefix
(`SoulSync:core/soulseek_client.py:315-321`), but nothing calls it: its only reference is the orchestrator's
pass-through (`SoulSync:core/download_orchestrator.py:632-648`), and that has no caller (grep). The same goes for
`explore_api_endpoints` (`GET /swagger/v1/swagger.json`, then `GET transfers`, `downloads`, `transfers/downloads`,
`api/transfers`, `api/downloads`, with and without the prefix, `SoulSync:core/soulseek_client.py:3016-3101`): dead
code, so not in the table. The onboarding probes call slskd with `requests` directly, not through the client; they
are rows 22, 24 and 25. Onboarding discovery also sends `GET {base}/` (slskd's web root, outside `/api/v0`) and looks
for "slskd" in the text (`SoulSync:core/onboarding/discovery.py:56`); the table covers `/api/v0` only. The video and audiobook sides share the client but are skipped (music only).

Every row: **from SoulSync's code, not captured.** There are **36 rows**: 5 search, 10 transfer, 4 peer, 6
server/app, 11 chat.

| # | Method | Path (`/api/v0/…`) | Request body / query | Response fields read | Cite | Note |
|---|---|---|---|---|---|---|
| 1 | POST | `searches` | `searchText`, `timeout` (ms), `filterResponses: true`, `minimumResponseFileCount: 1`, `minimumPeerUploadSpeed` (B/s); no `id` sent | `id` (dict, or `[0].id`) | `SoulSync:core/soulseek_client.py:699-720` | from SoulSync's code, not captured |
| 2 | GET | `searches/{id}/responses` | – | a list, or a dict under `responses`/`results`/`items`/`data`; per peer `username`, `hasFreeUploadSlot`, `uploadSpeed`, `queueLength`, `files[]` (`filename`, `size`, `bitRate`, `length`, `sampleRate`, `bitDepth`, `attributes[]{type,value}`) | `SoulSync:core/soulseek_client.py:764`, `SoulSync:core/soulseek_client.py:385-401`, `SoulSync:core/soulseek_client.py:466-512` | from SoulSync's code, not captured |
| 3 | GET | `searches/{id}` | – | `state` (terminal?) | `SoulSync:core/soulseek_client.py:807-822` | from SoulSync's code, not captured |
| 4 | GET | `searches` | – | list; `id`, `startedAt` | `SoulSync:core/soulseek_client.py:1683-1690`, `SoulSync:core/soulseek_client.py:1806-1809` | from SoulSync's code, not captured |
| 5 | DELETE | `searches/{id}` | – | any 2xx | `SoulSync:core/soulseek_client.py:1713-1715`, `SoulSync:core/soulseek_client.py:3126` | from SoulSync's code, not captured |
| 6 | POST | `transfers/downloads/{username}` | `[{"filename", "size", "path"}]`, one file | `enqueued[].id`/`.filename`, else `id`, else `[0].id` | `SoulSync:core/soulseek_client.py:862-878`, `SoulSync:core/soulseek_client.py:968-993` | from SoulSync's code, not captured |
| 7 | POST | `transfers/{username}/enqueue` | the same array, then `{"files": [{"filename", "size"}]}` | as row 6 | `SoulSync:core/soulseek_client.py:898-958` | from SoulSync's code, not captured; fallback only |
| 8 | POST | `users/{username}/downloads` | as row 7 | as row 6 | `SoulSync:core/soulseek_client.py:898-958` | from SoulSync's code, not captured; fallback only |
| 9 | POST | `users/{username}/enqueue` | as row 7 | as row 6 | `SoulSync:core/soulseek_client.py:898-958` | from SoulSync's code, not captured; fallback only |
| 10 | GET | `transfers/downloads` | – | list of `{username, directories[{files[{id, filename, state, size, bytesTransferred, averageSpeed, timeRemaining, progress, percentComplete}]}]}` | `SoulSync:core/soulseek_client.py:1079-1115`, `SoulSync:core/downloads/monitor.py:759-768`, `SoulSync:web_server.py:2292`, `SoulSync:web_server.py:3973`, `SoulSync:web_server.py:7354` | from SoulSync's code, not captured |
| 11 | GET | `transfers/downloads/{id}` | – | `id`, `filename`, `username`, `state`, `percentComplete`, `size`, `bytesTransferred`, `averageSpeed`, `timeRemaining` (dict or `[0]`) | `SoulSync:core/soulseek_client.py:1036-1067` | from SoulSync's code, not captured; on 0.26 this path is the per-peer route (`ours:sourcing/slskd_client.py:9`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:25`); its answer to a transfer id is *unverified* (S4-01 capture) |
| 12 | GET | `transfers/uploads` | – | as row 10 | `SoulSync:core/soulseek_client.py:1123-1151` | from SoulSync's code, not captured |
| 13 | DELETE | `transfers/downloads/{username}/{id}` | `?remove=true|false`, or no query (form 3) | any 2xx | `SoulSync:core/soulseek_client.py:1187-1222`, `SoulSync:core/soulseek_client.py:1250-1255`, `SoulSync:core/soulseek_client.py:1568-1569`, `SoulSync:core/soulseek_client.py:1649-1651` | from SoulSync's code, not captured |
| 14 | DELETE | `transfers/downloads/{id}` | – | any 2xx | `SoulSync:core/soulseek_client.py:1191` | from SoulSync's code, not captured; cancel form 2 |
| 15 | DELETE | `transfers/downloads/all/completed` | – | any 2xx | `SoulSync:core/soulseek_client.py:1606-1612` | from SoulSync's code, not captured; scope `all` only |
| 16 | POST | `users/{username}/directory` | `{"directory": <path>}` | dict `files[]`, or `directories[0].files[]`, or a list whose `[0].files[]`; per file as row 2 | `SoulSync:core/soulseek_client.py:1269-1321`, `SoulSync:core/soulseek_client.py:1323-1366` | from SoulSync's code, not captured; the folder browse (part 1, album step 3) |
| 17 | GET | `users/{username}/browse` | – | `directories[]` (or a list): `name`, `fileCount`, `files` | `SoulSync:core/soulseek_client.py:2967-2985` | from SoulSync's code, not captured |
| 18 | GET | `users/{username}/status` | – | passed through raw | `SoulSync:core/soulseek_client.py:2987-2989` | from SoulSync's code, not captured |
| 19 | GET | `users/{username}/info` | – | passed through raw | `SoulSync:core/soulseek_client.py:2991-2993` | from SoulSync's code, not captured |
| 20 | GET | `server` | – | `isConnected`/`IsConnected`, `isLoggedIn`/`IsLoggedIn`, `username` | `SoulSync:core/soulseek_client.py:2675-2683`, `SoulSync:core/soulseek_client.py:2856-2863`, `SoulSync:core/soulseek_client.py:2905-2916` | from SoulSync's code, not captured |
| 21 | GET | `server/state` | – | as row 20 | same lines as row 20 | from SoulSync's code, not captured |
| 22 | GET | `session` | – | "answered" (connection fallback), `username` | `SoulSync:core/soulseek_client.py:2686`, `SoulSync:core/soulseek_client.py:2856-2863`, `SoulSync:core/connection_detect.py:126`, `SoulSync:core/onboarding/discovery.py:53` | from SoulSync's code, not captured |
| 23 | GET | `options` | – | `soulseek.username`, `shares.directories[].path` | `SoulSync:core/soulseek_client.py:2872-2877`, `SoulSync:core/soulseek_client.py:2995-3014` | from SoulSync's code, not captured |
| 24 | GET | `application` | – | `version.full`, `shares.files` | `SoulSync:core/onboarding/probes.py:71-82`, `SoulSync:core/onboarding/probes.py:94-96` | from SoulSync's code, not captured |
| 25 | GET | `shares` | – | share list (counted) | `SoulSync:core/onboarding/probes.py:101` | from SoulSync's code, not captured |
| 26 | GET | `rooms/joined` | – | list | `SoulSync:core/soulseek_client.py:2920` | from SoulSync's code, not captured; chat |
| 27 | POST | `rooms/joined` | a JSON string (room name) | any 2xx | `SoulSync:core/soulseek_client.py:2924` | from SoulSync's code, not captured; chat |
| 28 | DELETE | `rooms/joined/{room}` | – | any 2xx | `SoulSync:core/soulseek_client.py:2928` | from SoulSync's code, not captured; chat |
| 29 | GET | `rooms/joined/{room}/messages` | – | list | `SoulSync:core/soulseek_client.py:2932` | from SoulSync's code, not captured; chat |
| 30 | GET | `rooms/joined/{room}/users` | – | list | `SoulSync:core/soulseek_client.py:2936` | from SoulSync's code, not captured; chat |
| 31 | POST | `rooms/joined/{room}/messages` | a JSON string (message) | any 2xx | `SoulSync:core/soulseek_client.py:2940` | from SoulSync's code, not captured; chat |
| 32 | GET | `rooms/available` | – | list | `SoulSync:core/soulseek_client.py:2945` | from SoulSync's code, not captured; chat |
| 33 | GET | `conversations` | – | list | `SoulSync:core/soulseek_client.py:2949` | from SoulSync's code, not captured; chat |
| 34 | GET | `conversations/{username}` | – | raw | `SoulSync:core/soulseek_client.py:2955` | from SoulSync's code, not captured; chat |
| 35 | POST | `conversations/{username}` | a JSON string (message) | any 2xx | `SoulSync:core/soulseek_client.py:2958` | from SoulSync's code, not captured; chat |
| 36 | PUT | `conversations/{username}` | – | any 2xx (acknowledge) | `SoulSync:core/soulseek_client.py:2964` | from SoulSync's code, not captured; chat |

The download path uses rows 1-3, 6 (7-9 only as fallbacks), 10, 11, 13, 14 and 16. Rows 4, 5 and 15 are cleanup,
rows 20-25 are status and onboarding, and rows 26-36 are chat.

### What our S1-04 and S2 should capture

We have never captured these shapes; SoulSync's guesses above disagree with each other or with our fake.
- **The enqueue response** of `POST /transfers/downloads/{peer}`, for one file and for several files in one body.
  SoulSync never sends several, and its two comments disagree on whether 0.26 returns ids (above). Our fake answers a
  bare list of records (ours:sourcing/fake_slskd.py:109-113), which is a third guess. Ties to **S1-04**: own-transfer
  identification must not depend on it, as planned (ours:docs/specs/2026-10-22-downloads-and-requests.md:80-81). Also
  to **S2-05**: one POST with all planned files (ours:docs/specs/2026-10-22-downloads-and-requests.md:142-143), and
  the `failed` list for a partial enqueue. The S4 checklist already asks for one real enqueue response
  (ours:docs/specs/2026-10-22-downloads-and-requests.md:253).
- **The folder browse.** SoulSync calls it as `POST /users/{peer}/directory` with `{"directory"}` and accepts three
  response shapes (row 16). Ties to **S2-04** (browse-before-trust: re-check coverage on the full listing) and
  **S2-05** (re-plan on a switch).
- **The per-transfer record** in `GET /transfers/downloads/{peer}` and the global listing: `id`, `filename`, `state`,
  `size`, `bytesTransferred`, `percentComplete`, `averageSpeed`. Capture it for `Queued, Remotely`, `InProgress` and
  every `Completed, …` outcome (`Succeeded`, `Errored`, `Cancelled`, `Aborted`, `TimedOut`, `Rejected`), and twice for
  the same file (an old and a new record). Ties to **S1-04** (the "id not there before the enqueue" rule), **S1-06**
  (which states mean "try another peer") and **S2-05** (the start timeout reads "not started").
- **`DELETE /transfers/downloads/{peer}/{id}?remove=true`** on a running and on a finished record: the status code
  and whether the record is gone. Ties to **S1-04**; the spec has the no-`remove` case from slskd's source
  (ours:docs/specs/2026-10-22-downloads-and-requests.md:39-41).
- **`POST /searches`** with `searchTimeout` and with `timeout`, to settle which key 0.26 reads: the state's `endedAt` −
  `startedAt` tells. Ties to **S2-04**, whose single album search must run long enough.
- **`GET /server`** during one of the VPN drops (`isLoggedIn` false). Ties to **S1-06**: wait for the login before
  the second source.
Each capture is a live step for Michael's checklist (S4-01), not for this run.

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

**Transfers (part 2).** `SlskdClient` makes eight calls, all through one `urllib` helper with a 30 s timeout and no
error handling of its own (`ours:sourcing/slskd_client.py:26-37`):

| Method | Path (`/api/v0/…`) | Body / what is read | Cite |
|---|---|---|---|
| POST | `searches` | `id` (our uuid), `searchText`, `searchTimeout` (8,000 ms), `filterResponses`, `maximumPeerQueueLength` 50, `minimumPeerUploadSpeed` 0 | `ours:sourcing/slskd_client.py:40-44` |
| GET | `searches/{id}` | `state`, polled every 1 s for up to 30 s; `responseCount` | `ours:sourcing/slskd_client.py:46-56` |
| GET | `searches/{id}/responses` | the list; re-read up to 5 times when the state counted responses | `ours:sourcing/slskd_client.py:58-66` |
| DELETE | `searches/{id}` | right after the read, in a `finally` | `ours:sourcing/slskd_client.py:68-69`, `ours:sourcing/fetch.py:391-392` |
| POST | `transfers/downloads/{peer}` | `[{filename, size}]`, one file; the response is returned but fetch ignores it | `ours:sourcing/slskd_client.py:72-74`, `ours:sourcing/fetch.py:429` |
| GET | `transfers/downloads` | all peers; no caller in `sourcing/`, `crates/` or `scripts/` (grep) | `ours:sourcing/slskd_client.py:77-78` |
| GET | `transfers/downloads/{peer}` | `directories[].files[]` with `id`, `filename`, `state`; a 404 means no transfers (the hotfix) | `ours:sourcing/slskd_client.py:79-84`, `ours:sourcing/slskd_client.py:90-93` |
| DELETE | `transfers/downloads/{peer}/{id}` | no `?remove=true`, so slskd cancels and keeps the record | `ours:sourcing/slskd_client.py:86-87`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:39-43` |

**The transfer loop** (`ours:sourcing/fetch.py:424-446`). First it "forgets" earlier `Completed` records of the same
file from that peer, with the DELETE above, which does not forget them. Then it enqueues one file and polls that
peer's listing every `poll_s` (1 s), taking `mine[-1]` among records with the same filename
(`ours:sourcing/fetch.py:432-433`, `ours:sourcing/fetch.py:162`). `Completed, Succeeded` plus a landed file goes on to
verify. Any other `Completed, …` fails the row with "download ended: <state>", and more than 600 s fails it with
"download timed out". Neither failure cancels the transfer in slskd (no DELETE on that path), so a timed-out transfer
can still land later. A successful record is never removed either. Any exception (an `HTTPError`, a `URLError` while
slskd is down, a socket timeout) fails the row with `<Type>: <text>` (`ours:sourcing/fetch.py:498-503`); that is how
the 10-21 404 showed on rows (`ours:docs/specs/2026-10-22-downloads-and-requests.md:25`). One attempt per approval
(D7), and a failing tick never stops the worker (`ours:sourcing/worker.py:46`).

**The hotfix's per-peer 404** (commit `19fedea`): `downloads(peer)` reads slskd 0.26's 404 for a peer with no
transfers as an empty listing (`ours:sourcing/slskd_client.py:79-84`). The fake answers the same 404 and a test pins
it (`ours:sourcing/fake_slskd.py:133-138`, `ours:tests/test_fake_slskd.py:54-66`). Nothing else reads a status code:
the enqueue, the DELETE and the search calls raise on any 4xx/5xx.

**Throttling and outages: none.** There is no 429 handling in `sourcing/` (a grep for `429` and `Retry-After` finds
only the MusicBrainz client, `ours:sourcing/musicbrainz.py:209`), no connection probe and no backoff. The bound is
structural: one search per fetch, one approval at a time (`ours:sourcing/worker.py:267-279`).

**Planned** (`ours:docs/specs/2026-10-22-downloads-and-requests.md`):
- **S1-04 hygiene** (`:76-81`): `?remove=true` with a 404 read as gone; a fake that keeps the record without it; own
  transfer = a record for the filename whose id was not there before the enqueue, never `mine[-1]` or the enqueue
  response.
- **S1-05** (`:82-84`): a reason names the step and endpoint, `slskd GET /transfers/downloads/<peer>: HTTP 404`,
  never the peer's name or a key.
- **S1-06** (`:85-88`): on `Completed, Errored`/`TimedOut`/`Rejected`/`Cancelled`, a connection error or a 5xx, the
  next acceptable candidate from another peer, once per approval; both attempts appear in the reason.
- **S2-05** (`:139-165`): all planned files to one peer in **one** POST, `ALBUM_START_TIMEOUT_S` 600 s, and on a
  switch, cancel and forget with `?remove=true` (`:142-143`, `:147-148`, `:151-152`).
The S1 branch `origin/harness/dj-crate-streaming-2026-10-22-fixes` still did not exist on 2026-10-22 when this part
was written (`git ls-remote origin 'harness/dj-crate-streaming-2026-10-22*'` printed nothing), so S1 is compared as
planned, not as built.

## The difference that matters

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
  time (the transfer-side classes follow).
- **Failure class: 404 from `GET /transfers/downloads/{peer}`.** SoulSync never asks the per-peer listing. It reads the
  global `GET transfers/downloads` once per tick (`SoulSync:core/downloads/monitor.py:759`,
  `SoulSync:core/soulseek_client.py:1079`), which lists every peer, so the 10-21 404 before the first enqueue could
  not happen on that path. It never asks the per-peer route on purpose, but row 11 may reach it with a UUID as the peer
  name (`SoulSync:core/soulseek_client.py:1042`; slskd's answer is *unverified*, the row 11 capture would settle it), and that 404 would be silent. Any 404 it does get becomes a quiet None (`SoulSync:core/soulseek_client.py:257-258`). Ours after
  the hotfix reads that 404 as "no transfers" (`ours:sourcing/slskd_client.py:79-84`), and S1-04 adds "404 on DELETE =
  gone". The global listing is also what an album job needs: one read covers every planned file, whatever peers they
  came from.
- **Failure class: stale records (DELETE without `remove=true`).** SoulSync passes `remove=True` on every cancel in
  the download path, and every 5 min it clears its own finished records, scoped by persisted ids
  (`SoulSync:core/downloads/monitor.py:690`, `SoulSync:core/automation_engine.py:190-196`). It still keeps finished
  records while any batch runs, takes the last of two records with the same peer and path
  (`SoulSync:core/downloads/monitor.py:768`), and cannot own a transfer whose enqueue reply had no id. Its second and third
  DELETE forms also drop `remove`. On our 10-21 retry of ext-74's file the earlier attempt had downloaded and failed verify
  (ours:docs/specs/2026-10-22-downloads-and-requests.md:26). SoulSync's verify-failure retry sends no DELETE either; it
  marks `(peer, file)` used and searches again (`SoulSync:core/downloads/monitor.py:396-416`). So it would not have
  re-taken that file from that peer, and no old record would have been mistaken for a new one. Ours sends no `remove` at all, so
  S1-04's rule (a record whose id was not there before the enqueue) is stricter than both `mine[-1]` and SoulSync's
  last-wins key. Keep the rule, and add the two things SoulSync does: remove on every cancel, and remove our own
  record once the file is filed.
- **Failure class: VPN drop mid-transfer.** SoulSync retries a `Completed, Errored` transfer within 5 s, up to 3
  times, each time with a fresh search on any peer, and the wishlist retries later
  (`SoulSync:core/downloads/monitor.py:922-985`). So it recovers on its own, beyond D7's bound. It never checks that
  slskd is logged in again before retrying, although it has the probe (`SoulSync:core/soulseek_client.py:2668-2690`).
  With a ~10 s drop, the first retry's search may start while slskd is still logged out (*unverified*: logging the
  retry's search start against `GET /server`'s `isLoggedIn` during a drop would verify it). S1-06's "one
  other peer, once per approval" is the right bound. The cheap thing to take: before that second attempt, wait up to
  a minute for `GET /server` to show `isLoggedIn` (a proposal; the shape is not captured).
- **slskd down (not a 10-21 class, but next to it).** SoulSync's monitor reads a refused connection as "every transfer
  gone". It spends all 3 retries, marks good `(peer, file)`s used, and leaves the real transfers running
  (`SoulSync:core/downloads/monitor.py:759-768`, `SoulSync:core/downloads/monitor.py:854-912`). Ours fails the row on
  the `URLError` (`ours:sourcing/fetch.py:498-503`). Both lose a transfer that slskd is still downloading: SoulSync later deletes the file it
  brings as an orphan (`SoulSync:web_server.py:7392-7428`), and ours leaves it unclaimed in slskd's folder. For
  S1-06, a connection error while *polling* should keep polling the same transfer until the 600 s timeout. Only a
  connection error on the *enqueue* is a reason to try another peer.
- **Enqueue shape.** SoulSync sends one POST per file and, on any error, sends up to 7 POSTs over 4 paths. S2-05 plans one POST
  with all files, which SoulSync never does, so nothing here vouches for that body or its reply. Capture it first
  (above).
- **Errors lose their reason in SoulSync.** Every non-2xx becomes None at one choke point, so neither the log
  of a give-up nor the task says which endpoint answered what (`SoulSync:core/soulseek_client.py:235-306`). S1-05's
  "slskd GET /transfers/downloads/<peer>: HTTP 404" is the opposite choice, and the better one.

## Worth taking?

- **Take (adapt):** the album flow's structure for S2-04/S2-05: group by (peer, directory), map wanted tracks to
  files one to one by maximum matching (`assign_album_tracks` is the right algorithm; our edge is S1-01's key rule plus
  D26's version label, with no fuzzy edge), a coverage floor for a folder to count as an album source, enqueue only
  the matched files, keep completed tracks when switching, and per-track for the rest. Paraphrase, don't copy (brief).
- **Take:** measured peer throughput as a tie-break (an in-process map, 1 h TTL, exponential weighting,
  `SoulSync:core/downloads/peer_observation.py:28-50`) and the "frozen for N seconds → cancel with `remove=True`" stall
  guard for a folder. Both are small and need no new slskd shape.
- **Take as test cases:** browse-before-trust (search hits are a subset; re-check coverage on the full listing) once
  we capture `POST /users/{peer}/directory` (see `### What our S1-04 and S2 should capture`); a folder that crawls; a
  folder that has 8 of 9.
- **Do not take:** the multi-query ladders (one search per album is S2-04's choice and spares Soulseek), the 0.70 base
  score reuse, the autonomous retry budgets (D7), five-folder walks, the per-file `failed_blocklist` fingerprint
  without a peer, and the fuzzy 0.80 title edge.
- **Take (transfers):** `?remove=true` on every cancel, and on our own record after filing; the global
  `GET /transfers/downloads` listing as the poll for album jobs; "Completed but fewer bytes than the size" read as
  not done (`SoulSync:core/downloads/monitor.py:637-644`); a bounded timeout on every slskd call (ours already has
  30 s); a `GET /server` login check before S1-06's second attempt; and, if S2 ever runs many searches, a shared
  search window with a 429 cooldown (`SoulSync:core/slskd_throttle.py:40-73`; the 35/220 s figure needs checking
  against slskd first).
- **Do not take (transfers):** the 7-POST enqueue cascade and the 3-form DELETE cascade (they hide the real error, and
  forms 2 and 3 drop `remove`); "any non-2xx → None", which loses the status S1-05 needs; the filename-as-id
  fallback; keeping finished records until a batch ends; and reading an unreachable slskd as "no transfers".

**Verdict:** adapt. SoulSync's Soulseek album path is the closest working example of goal E we have, and S2-04/S2-05
already plan the same shape with the two rules it lacks (same release by lengths/MusicBrainz, distrust a fake folder)
and a tighter bound (two folders, one retry per approval). Take the structure and the measured-speed tie-break; keep
our exact-track rules on every path. On transfers, SoulSync's hygiene (`remove=true` on every cancel, one global
listing per tick, bounded HTTP timeouts) is worth copying in our own code; its error handling (every failure → None,
guessed endpoint cascades, an unreachable slskd read as "no transfers") is not. The transfer side doesn't change the
verdict.
