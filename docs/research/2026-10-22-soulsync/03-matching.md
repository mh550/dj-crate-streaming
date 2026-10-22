# 03 · Matching: "have it / missing", identity, versions and editions

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed).
Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a claim
without one. Numbers marked **hand estimate** were computed by re-doing the cited arithmetic in a few lines of our own
stdlib Python (difflib, re) in the run's scratch directory, not by running SoulSync; they model the cited formula, not
every branch around it. Music only: the audiobook branch of the library check
(`SoulSync:database/music_database.py:12746-12751`, `SoulSync:database/music_database.py:12760-12793`) is named here once and skipped.

## What SoulSync does

SoulSync matches by **fuzzy string scores with numeric thresholds**, in several scorers that share one normaliser
and one similarity function (`MusicMatchingEngine.similarity_score`, `SoulSync:core/matching_engine.py:265-369`).
External ids exist and are stored per provider, but the two everyday decisions, "is this playlist track in my
library?" (playlist sync) and "is this Soulseek file the track I want?", are made from title, artist and (for
Soulseek only) duration strings. Ids decide only in the watchlist and in the import pre-check.

```
 wanted track (Spotify/Deezer/... metadata: name, artists, album, duration_ms; ids in the source row)
   │
   ├─ "have it?" ── sync_service._find_track_in_media_server ──► sync_match_cache (source track id)
   │                                                           ► manual match override
   │                                                           ► MusicDatabase.check_track_exists(threshold 0.7)
   │                 MatchResult(match_threshold=0.7).is_match ──► owned → added to the server playlist
   │                                                           └► not owned → wishlist (02-intake.md)
   │
   ├─ "is this file it?" (Soulseek) ── find_best_slskd_matches_enhanced
   │        calculate_slskd_match_confidence (path vs metadata, gates) ─► base-title veto ─► version gate
   │        ─► keep confidence > 0.58 ─► recovery (soulseek_identity.match_track, only rows with confidence > 0)
   │
   └─ "is the downloaded file it?" (optional, off by default) ── AcoustID verification in the import pipeline
            title/artist of AcoustID's recordings vs expected ─► PASS / SKIP / FAIL (quarantine)
```

### Normalisation and the shared similarity

- `normalize_string`: unidecode except for CJK text (kept, then lowercased), KoЯn mapped, `pt.`/`vol.`/`feat.`
  expanded, `. _ / & : -` turned into spaces, everything but `[a-z0-9 $]` (plus CJK ranges) dropped
  (`SoulSync:core/matching_engine.py:121-201`). A backslash is *not* in the separator set, so it is deleted, not
  spaced (`SoulSync:core/matching_engine.py:183`, `SoulSync:core/matching_engine.py:196`): a Windows path
  `Al Green\I'm Still…` normalises to `al greenim still…`.
- `clean_title` removes only `(explicit)`, `(clean)` and feat. credits (`SoulSync:core/matching_engine.py:78-91`,
  `SoulSync:core/matching_engine.py:211-218`); `clean_album_name` removes edition suffixes (deluxe, remaster, any
  `(… version)`, and everything after ` - `) (`SoulSync:core/matching_engine.py:229-263`).
- `similarity_score` = `SequenceMatcher.ratio()` with three overrides (`SoulSync:core/matching_engine.py:271-369`):
  - shorter string a prefix of the longer and the extra text contains `remaster` → **0.75**
    (`SoulSync:core/matching_engine.py:298-312`);
  - otherwise the extra text contains a version keyword → **0.30**
    (`SoulSync:core/matching_engine.py:314-321`). The list: remix, mix, rmx, live, acoustic, unplugged, slowed,
    reverb, sped up, radio edit/version, single edit, album edit, instrumental, karaoke, extended, demo, rough cut
    (`SoulSync:core/matching_engine.py:39-52`). This is a substring test, and the remaster test runs first, so a
    "Live - Remastered 2011" tail gets 0.75, not 0.30;
  - both strings carry version keywords that differ, or that leave different residues when stripped (another remixer,
    another venue) → **0.30** (`SoulSync:core/matching_engine.py:343-367`).

### "Have it / missing": the library check

- **The function.** `MusicDatabase.check_track_exists(title, artist, confidence_threshold=0.8, …, album=…)` returns
  `(track, confidence)` (`SoulSync:database/music_database.py:12438`). It runs exact SQL on `tracks.title_norm` ×
  artist-name variations first, then `search_tracks` (20 per variation pair) when the exact pass is under the
  threshold and the artist exists at all (`SoulSync:database/music_database.py:12361-12406`,
  `SoulSync:database/music_database.py:12494-12538`). The artist variations are the unidecoded form, with or without a
  leading "The", and a hard-coded KoЯn (`SoulSync:database/music_database.py:12324-12358`).
- **The score** (`SoulSync:database/music_database.py:14149-14181`): confidence = 0.5·title + 0.5·artist, times 0.3
  when the artist is under 0.6. **No duration, no album, no id** enters it.
  - Title (`SoulSync:database/music_database.py:14004-14103`): the better of the raw and the cleaned similarity. The
    cleaner (`SoulSync:database/music_database.py:14191-14262`) turns brackets and dashes into spaces and deletes
    explicit/clean, feat., `remaster…`, "original/album/single version" and soundtrack notes. It keeps live, remix,
    acoustic, instrumental, demo, extended and radio/single/album edit, so those meet the 0.30 rule above.
  - Then a length-ratio penalty (ratio < 0.7 multiplies the score by the ratio,
    `SoulSync:database/music_database.py:14027-14036`), two re-scores that drop a qualifier restating the album
    (#808) or a non-version subtitle (#825) (`SoulSync:database/music_database.py:14038-14081`), a word-overlap guard
    (`titles_plausibly_same`: near-identical ≥ 0.85, or one shared content word,
    `SoulSync:core/text/title_match.py:65`, `SoulSync:core/text/title_match.py:75-105`; it also passes any pair where
    neither title has two content words, `SoulSync:core/text/title_match.py:103-104`), and a floor: title < 0.6
    returns half the title score (`SoulSync:database/music_database.py:14090-14101`).
  - Artist: the best of the album artist, `track_artist` and each credit piece split on `; , & feat ft vs x`
    (`SoulSync:database/music_database.py:14105-14147`).
  - An album-aware fallback (only when `album` is passed) accepts a title that passes the same guards, with album
    title ≥ 0.8, at max(0.7, threshold) (`SoulSync:database/music_database.py:12556-12744`).
  - Playlist sync passes pre-fetched `candidate_tracks` (`SoulSync:services/sync_service.py:1500-1503`), which takes
    the in-memory batched path instead of the SQL passes; the scoring is the same
    (`SoulSync:database/music_database.py:12463-12472`).
- **The bar.** `MatchResult.match_threshold` defaults to 0.8 (`SoulSync:core/matching_engine.py:28-39`); playlist sync
  passes 0.7, "the app-wide 'you own this' bar" (`SoulSync:services/sync_service.py:705-714`). Sync's finder tries the
  `sync_match_cache` by source track id, then a manual match, then `check_track_exists` at 0.7, also with a canonical
  YouTube-style title (`SoulSync:services/sync_service.py:1333`, `SoulSync:services/sync_service.py:1393-1512`).
  Others at 0.7: wishlist cleanup and add-time refusal via `find_owned_match`
  (`SoulSync:core/wishlist/library_match.py:194-215`), the watchlist (`SoulSync:core/watchlist_scanner.py:2982-2984`),
  download analysis (`SoulSync:core/downloads/master.py:312-354`), playlist materialise
  (`SoulSync:core/playlists/materialize_service.py:189`). Member requests use 0.8
  (`SoulSync:api/music_requests.py:86`).
- **The wishlist adds a strict check.** `find_owned_match(strict_identity=True)` is what all three wishlist callers
  pass (`SoulSync:core/wishlist/processing.py:788-790`, `SoulSync:core/downloads/cleanup.py:114-116`,
  `SoulSync:core/wishlist/routes.py:831-834`): after the fuzzy hit, the titles must reduce to the same identity key
  with version words kept, and the artist key must be equal (`SoulSync:core/wishlist/library_match.py:156-191`,
  `SoulSync:core/wishlist/library_match.py:220-229`). Its comment names the fuzzy failure it exists for: "Runaway
  Train" → "The Sun Maid" at 0.74 (`SoulSync:core/wishlist/library_match.py:220-224`). Playlist sync has no such
  check: it calls `check_track_exists` and accepts at `confidence >= 0.7`
  (`SoulSync:services/sync_service.py:1500-1512`, *absence inferred* from that path).
- **Ids first, in two places only.** `find_library_track_by_external_id` ORs exact matches on Spotify, iTunes, Deezer,
  Tidal, Qobuz, MusicBrainz recording, AudioDB, Hydrabase and ISRC columns
  (`SoulSync:core/library/track_identity.py:144-188`). It runs before the fuzzy match only in the watchlist's
  `is_track_missing_from_library` (`SoulSync:core/watchlist_scanner.py:2900-2976`) and in the import pre-check, which
  skips a file only on an exact MBID/ISRC pairing ("a false 'already owned' is silent data loss",
  `SoulSync:core/imports/library_check.py:12-17`, `SoulSync:core/imports/library_check.py:202-225`).
- **Albums.** Album ownership is `check_album_exists_with_editions` + `check_album_completeness` (owned ≥ expected)
  (`SoulSync:database/music_database.py:13401-13438`, `SoulSync:database/music_database.py:12918-12936`), scored 0.5
  title + 0.5 artist with an edition bonus/penalty (`SoulSync:database/music_database.py:13779-13817`).
  `find_best_album_match` in the engine (≥ 0.8, `SoulSync:core/matching_engine.py:1697-1716`) has no caller outside
  tests (grep, *absence inferred*).
- **Not the library match:** `core/client_match.py` adopts downloads SoulSync did not start (the Clients tab), keyed
  by torrent hash, usenet id or, for music Soulseek transfers, `(username, filename)`, with no fuzzy scoring
  (`SoulSync:core/client_match.py:1-10`, `SoulSync:core/client_match.py:156-168`). `core/matching/` holds helpers:
  album-context title stripping for download analysis (`SoulSync:core/matching/album_context_title.py:1-15`),
  cross-script artist aliases for verification (`SoulSync:core/matching/artist_aliases.py:1-15`), a script-mismatch
  detector (`SoulSync:core/matching/script_compat.py:1-15`), the live/original exception
  (`SoulSync:core/matching/version_mismatch.py:44-72`) and a history-row path resolver
  (`SoulSync:core/matching/history_paths.py:1-13`).

### "Is this Soulseek file it?": the candidate score

`calculate_slskd_match_confidence` scores the whole slskd path against Spotify-shaped metadata
(`SoulSync:core/matching_engine.py:944-1160`); `filename` is slskd's full remote path, unchanged
(`SoulSync:core/soulseek_client.py:475`, `SoulSync:core/soulseek_client.py:494-496`).

| Part | Rule | Cite |
|---|---|---|
| Title | `SequenceMatcher(clean title, whole normalised path)`; +0.3 if the title occurs as whole words anywhere in the path (folders included) | `SoulSync:core/matching_engine.py:960-976` |
| Artist | 1.0 on a word-boundary hit in any path segment, else best per-segment ratio × 0.7 | `SoulSync:core/matching_engine.py:978-1021` |
| Duration | 1.0 within 5 s, else `max(0, 1 − 5·diff/max)`; 0.5 when unknown | `SoulSync:core/matching_engine.py:371-381` |
| Bonuses | FLAC +0.03, MP3 ≥ 320 +0.02; a path segment ≥ 0.85 like the album +0.10 (≥ 0.60 +0.03) | `SoulSync:core/matching_engine.py:1026-1058` |
| Gates (→ 0.0) | a whole path segment equal to `various artists`, `various artist`, `va`, `unknown artist` or `unknown album`; title < 0.30 without a word hit; artist < 0.25 | `SoulSync:core/matching_engine.py:1072-1108` |
| Weights | 0.45 title + 0.40 artist + 0.15 duration (YouTube 0.60/0.20/0.20); × 0.4 for a title ≤ 5 chars with artist < 0.5 | `SoulSync:core/matching_engine.py:1122-1141` |
| Accept | the enhanced finder keeps confidence > 0.58 (the older finder > 0.63), sorted by preferred version, confidence, original-first, peer quality, size | `SoulSync:core/matching_engine.py:1626-1631`, `SoulSync:core/matching_engine.py:1184` |

The enhanced pass (`SoulSync:core/matching_engine.py:1269-1448`, used by `SoulSync:core/downloads/validation.py:860`)
adds:
- **Base-title veto (#1626).** When the artist hit is exact (≥ 0.99), reduce both sides to the bare song title
  (`base_title_of`: last path segment, extension, brackets, track number, artist prefix and a trailing version
  qualifier removed, `SoulSync:core/matching_engine.py:1476-1508`) and reject when their ratio is under **0.30**
  (`SoulSync:core/matching_engine.py:1307-1335`).
- **Version gate.** `detect_version_type` reads the *candidate* path: radio (−0.08), slowed/sped up (−0.20), remix
  (incl. a bare `edit`, −0.15), live (−0.20), acoustic (−0.12), instrumental (−0.25), clean (−0.08), extended
  (−0.05), demo (−0.18), explicit (−0.02), first hit wins (`SoulSync:core/matching_engine.py:1188-1267`). A live,
  remix, acoustic or instrumental candidate is rejected unless the wanted title carries that marker or the user's
  preferred version is that type (`SoulSync:core/matching_engine.py:1345`, `SoulSync:core/matching_engine.py:1356-1418`); a tempo edit is rejected in both directions
  (`SoulSync:core/matching_engine.py:1350-1354`); every other type keeps half its penalty
  (`SoulSync:core/matching_engine.py:1420-1446`); with `content_filter.prefer_explicit` on, radio and clean files
  lose a further 0.10 and explicit ones gain 0.05 (`SoulSync:core/matching_engine.py:1429-1433`). The code says what this leaves open: the gate "only rejects on the
  CANDIDATE's version: a plain studio file classifies as 'original' and is never rejected"
  (`SoulSync:core/matching_engine.py:620-625`).
- **Recovery.** Rows under 0.58 with confidence > 0, an exact-title reading from `soulseek_identity.match_track` and
  the artist in a parent folder are added back (`SoulSync:core/downloads/validation.py:861-882`,
  `SoulSync:core/downloads/soulseek_identity.py:236-276`); a vetoed or gated row has confidence 0 and stays out.
- A user preference `soulseek.preferred_version` (off by default) lifts the gate and the penalty for that version
  (`SoulSync:core/matching_engine.py:1434-1438`) and ranks it first, but only when `base_title_of` is *equal* on both
  sides (`SoulSync:core/matching_engine.py:1462-1474`,
  `SoulSync:core/matching_engine.py:1510-1557`).

Streaming, torrent and usenet results are scored by the metadata scorer `score_track_match` instead (60 % title,
30 % artist, 10 % duration; a core-title fast path at 0.90 + 0.09·artist; a −0.15…−0.35 penalty past 15 s and 15 %)
(`SoulSync:core/matching_engine.py:383-459`, `SoulSync:core/downloads/validation.py:578-585`). 05-other-sources.md
covers them.

### Ids, editions and releases

- **Ids kept.** `core/source_ids.py` is a registry of column names, not a schema change
  (`SoulSync:core/source_ids.py:11-15`): per track `spotify_track_id`, `itunes_track_id`, `deezer_id`,
  `musicbrainz_recording_id`, `amazon_id`, `tidal_id`, `qobuz_id`, `audiodb_id`, `genius_id`, `soul_id`,
  `jiosaavn_id`, `bandcamp_url` (`SoulSync:core/source_ids.py:61-74`); per album `spotify_album_id`,
  `itunes_album_id`, `deezer_id`, `musicbrainz_release_id`, `discogs_id` and the same other providers minus Genius
  (`SoulSync:core/source_ids.py:42-60`). ISRC is a plain `tracks.isrc` column
  (`SoulSync:database/music_database.py:5800-5801`); `track_downloads` carries the provider ids and ISRC, indexed
  (`SoulSync:database/music_database.py:3800-3823`). No release-group column was found (grep `release_group` in
  `database/music_database.py`, *absence inferred*).
- **MusicBrainz** enriches library rows in a background worker: artist MBID, `musicbrainz_release_id` via
  `match_release`, `musicbrainz_recording_id` and `recording_disambiguation` via `match_recording` (artist MBID,
  duration, ISRC) (`SoulSync:core/musicbrainz_worker.py:381-460`, `SoulSync:core/musicbrainz_service.py:1995-2017`),
  accepting at confidence ≥ 70 (`SoulSync:core/musicbrainz_service.py:718`,
  `SoulSync:core/musicbrainz_service.py:1398`), at most one call per 1.05 s on the public server
  (`SoulSync:core/musicbrainz_client.py:41-44`). Existing ids are kept (`SoulSync:core/musicbrainz_worker.py:344-379`).
  `core/musicbrainz_search.py` only adapts MusicBrainz as a search tab with Cover Art Archive art
  (`SoulSync:core/musicbrainz_search.py:1-6`). The library check above does not read these ids (none appears in
  `SoulSync:database/music_database.py:14004-14181`, *absence inferred*).
- **ISRC** resolves a *source* track (Beatport, a Spotify second pass) to a Spotify or Deezer track before any title
  search (`SoulSync:core/discovery/isrc_match.py:1-10`); it needs a valid code and artist containment, and anything
  else falls back to search (`SoulSync:core/discovery/isrc_match.py:25-46`,
  `SoulSync:core/discovery/isrc_match.py:96-117`).
- **Editions.** `edition_grouping` collapses album titles by stripping known edition words (anniversary, super
  deluxe, deluxe, expanded, remaster [year], special/collector's/… edition, bonus tracks, extended, reissue, clean,
  explicit) and keeps real subtitles such as "(Live)" (`SoulSync:core/edition_grouping.py:9-15`,
  `SoulSync:core/edition_grouping.py:53-107`). Which edition the watchlist takes is `watchlist.edition_preference`:
  `all` (default), `one_standard` (fewest tracks) or `one_complete` (most tracks, skipping any edition over 4.5× the
  smallest) (`SoulSync:core/edition_grouping.py:48`, `SoulSync:core/edition_grouping.py:148-176`,
  `SoulSync:core/watchlist_scanner.py:585-595`).
- **`release_identity` is not a music identity.** It keys torrent/usenet *releases* (infohash, or name + size + quality)
  for de-duplicating indexer results (`SoulSync:core/download_plugins/release_identity.py:1-19`,
  `SoulSync:core/download_plugins/release_identity.py:59-71`).
- **AcoustID** is off by default (`acoustid.enabled: False`, `SoulSync:core/settings.py:745-748`); the client also
  needs pyacoustid, an API key and fpcalc/chromaprint before it reports itself available
  (`SoulSync:core/acoustid_client.py:240-260`). When on, it runs in
  the import pipeline after the download and before the move (`SoulSync:core/imports/pipeline.py:1045-1091`). It
  compares strings: expected title/artist against the titles/artists of AcoustID's recordings
  (`SoulSync:core/acoustid_verification.py:1-8`). Fingerprint < 0.80 → SKIP; title ≥ 0.70 and artist ≥ 0.60 → match
  (`SoulSync:core/matching/audio_verification.py:26-29`); a confident fingerprint naming another title ends in
  `FAIL "Audio mismatch"` (`SoulSync:core/matching/audio_verification.py:829-831`), and FAIL quarantines the file
  (`SoulSync:core/imports/pipeline.py:1112-1146`). Version labels come from the same `detect_version_type`
  (`SoulSync:core/matching/audio_verification.py:196-217`); a different label FAILs ("Version mismatch") unless it is
  live vs original with fingerprint ≥ 0.85, or the file's length backs the asked version (then SKIP)
  (`SoulSync:core/matching/audio_verification.py:682-704`, `SoulSync:core/matching/version_mismatch.py:44-60`).

### Remaster, live, extended, radio edit

Wanted is the plain album cut unless the row says otherwise. "Library" is `check_track_exists` as playlist sync uses
it (0.7, title and artist only); "Soulseek" is the enhanced candidate score; "AcoustID" applies only when enabled.
The library hand estimates use a 12-character title ("Ain't Nobody") and an album title that does not repeat the
qualifier; the length-ratio penalty (`SoulSync:database/music_database.py:14027-14036`) makes them move with title
length (extended about 0.04-0.10, radio edit 0.04-0.15 for 4-26 characters).

Two branches widen "have it" beyond the table. **Album context (#808):** a qualifier whose words appear in the library
row's album title is dropped before scoring (`SoulSync:database/music_database.py:14050-14062`,
`SoulSync:core/text/title_match.py:111-142`). So "Song (Live)" on an album "Live at Wembley" scores as the bare "Song"
(1.0) and owns the studio wish; the same holds for "(Extended Mix)" or "(Radio Edit)" on a single whose album title
repeats the qualifier. **"Radio Version":** the cleaner strips a trailing `version`
(`SoulSync:database/music_database.py:14238`), leaving "song radio", and a bare "radio" is not a keyword
(`SoulSync:core/matching_engine.py:46`), so the raw ratio decides: "Bohemian Rhapsody (Radio Version)" scores about
0.93 against "Bohemian Rhapsody" (hand estimate).

| Case | SoulSync library ("have it") | SoulSync Soulseek candidate | SoulSync AcoustID (opt-in) | Ours |
|---|---|---|---|---|
| **Remaster** ("Song - 2011 Remaster") | Same: the cleaner deletes `remaster…` (`SoulSync:database/music_database.py:14224-14226`); hand estimate 1.00 | Not a version: no `detect_version_type` pattern, so `original`, no penalty (`SoulSync:core/matching_engine.py:1188-1267`) | `original` = `original`, no version check fires (same function, `SoulSync:core/matching/audio_verification.py:204`) | A copy, not a version (`ours:docs/identity.md:14`, `_COPY` at `ours:sourcing/identity.py:100-101`): the same key, so `choose` matches it |
| **Live** ("Song (Live)") | Different: 0.30 by the version keyword (`SoulSync:core/matching_engine.py:314-321`), then the 0.6 floor; hand estimate 0.15. But "Ain't Nobody (Live - Remastered 2011)" scores **0.875** (owned): the remaster test fires first (`SoulSync:core/matching_engine.py:298-312`) and no duration is read; for titles under about 12 characters the length penalty brings it under the bar (the 4-letter "Song" gives 0.17) | Rejected for a plain row (`SoulSync:core/matching_engine.py:1356-1374`). For a live row a studio file is *not* rejected by the gate (`SoulSync:core/matching_engine.py:620-625`) | FAIL unless fingerprint ≥ 0.85, title ≥ 0.70, artist ≥ 0.60 (the one excused pair, `SoulSync:core/matching/version_mismatch.py:44-60`) | Kind `live` (`ours:sourcing/identity.py:81`): another key; `choose` gives `ambiguous`/`missing` unless the tier accepts it; the scorer rejects it for a plain row (`ours:sourcing/scorer.py:171-177`) |
| **Extended mix** | Different: `extended`/`mix` keep the 0.30 (`SoulSync:core/matching_engine.py:314-321`); hand estimate 0.07 | **Accepted**: `extended` is only −0.05 halved to −0.025 (`SoulSync:core/matching_engine.py:1246-1248`, `SoulSync:core/matching_engine.py:1421`); a remix-named "… Mix" is rejected as remix only if the path says `remix`/`rmx`/`rework`/`edit` (`SoulSync:core/matching_engine.py:1218-1221`) | FAIL "Version mismatch" unless the length backs the asked version (`SoulSync:core/matching/audio_verification.py:682-704`) | Kind `extended`, 12" spellings too (`ours:sourcing/identity.py:78`, `ours:sourcing/identity.py:106-111`); never a stand-in (D26, `ours:docs/specs/2026-10-17-amperfy-pivot.md:21`); the scorer rejects it unless accepted (`ours:sourcing/scorer.py:171-177`) |
| **Radio edit** | Different in both directions: 0.30 (`SoulSync:core/matching_engine.py:46`); hand estimate 0.08 | **Accepted** both ways: radio is −0.08 halved (`SoulSync:core/matching_engine.py:1204-1206`); a plain file for a radio-edit row classifies `original` and is not gated (`SoulSync:core/matching_engine.py:620-625`) | FAIL "Version mismatch" (radio ≠ original) unless the length backs it (`SoulSync:core/matching/audio_verification.py:682-704`) | Kind `edit` (`ours:sourcing/identity.py:80`): another key for `choose`; the scorer ranks but does not reject an edit/plain swap (`edit` is excluded from the reject rule, `ours:sourcing/scorer.py:171-177`) |

## How ours does it

**Three levels, one module.** `ours:sourcing/identity.py:1-16` decides "the same" and nothing else does: a *song* is lead
artist + base title, a *version* is a recording (radio edit, 12"/extended, club, dub, live, remix by X), a *copy* is a
file, and "a remaster is a copy, not a version" (`ours:docs/identity.md:14`). Every doubt resolves to "different
version" because replacement trusts `same_version` (`ours:sourcing/identity.py:7-9`).

- **Folding.** `words` NFKD-folds Latin accents only (Japanese dakuten stay), casefolds, reads `&` as "and" and keeps
  letters of any script (`ours:sourcing/identity.py:36-50`); `loose` drops the spaces and is the equality key
  (`ours:sourcing/identity.py:53-55`). No fuzzy ratio is used for identity.
- **Labels from the title.** `parse_title` peels trailing `(…)`, `[…]` and ` - …` decorations right to left and
  classifies each as a version label (it holds a vocabulary word) or a copy note (a remaster phrase, "Album Version",
  "feat. X") (`ours:sourcing/identity.py:195-247`). The vocabulary is twelve kinds (`ours:sourcing/identity.py:24`),
  matched as whole words: `extended|long version`, `single version|single edit|short version|radio|edit`, `club`,
  `dub`, `live`, `demo`, … (`ours:sourcing/identity.py:76-86`); 12" in its spellings adds `extended`, 7" adds `edit`
  (`ours:sourcing/identity.py:106-113`); mono/stereo/clean/explicit/dirty add `alt` and stay in the credit
  (`ours:sourcing/identity.py:88-91`). The version key is the sorted kinds minus `original` plus the loose credit
  ("tommoulton") (`ours:sourcing/identity.py:189-192`), so "Live 1977" ≠ "Live 1979" and "Clean Edit" ≠ "Edit"
  (`ours:docs/identity.md:43-44`).
- **Same version.** Two copies are one version when neither is a placeholder, and either their recording ids agree
  *and* their labels agree *and* their lengths are within 4 s when both are known, or (no ids) lead artist, base title and label agree and
  both lengths are known and within 4 s; a differing work id only ever rejects (`ours:sourcing/identity.py:359-386`,
  `ours:docs/identity.md:54-62`). `version_groups` unions by song key and recording id, then groups pairwise
  same-version copies so a 300/303/306 s chain never joins 300 and 306 (`ours:sourcing/identity.py:389-422`).

**"Have it / missing" = `import_playlist.choose`.** For each playlist row, `match` asks Navidrome `search3` (up to 5
pages of 20, `ours:sourcing/import_playlist.py:48-49`), retrying title-only with the artist still required
(`ours:sourcing/import_playlist.py:212-220`). `choose` then asks three questions in order
(`ours:sourcing/import_playlist.py:155-198`):
1. **Same recording:** the row's ISRC among the hit's ISRC tags (`ours:sourcing/import_playlist.py:163-170`); a match
   whose labels differ is kept with a note, since library ISRC tags can be wrong.
2. **Same version:** with a row duration, hits with the same version key, within `TOLERANCE_S` = 4 s
   (`ours:sourcing/import_playlist.py:37`) and whose base title fits, closest length wins
   (`ours:sourcing/import_playlist.py:125-132`, `ours:sourcing/import_playlist.py:172-175`); without one, the same
   base title (exact `loose` equality, `ours:sourcing/import_playlist.py:135-140`) and key.
3. **Another version the tier accepts** (`stands_in`, `ours:sourcing/import_playlist.py:180-187`): same song, every kind
   the row names except `edit` kept, every credit kept, at least one kind added and every added kind on the tier's
   `accept` list (`ours:sourcing/identity.py:253-263`).

Anything else is `ambiguous` (right song name, other length or label; or several versions in the fit, which
`_decide` refuses to pick between, `ours:sourcing/import_playlist.py:143-152`) or `missing`
(`ours:sourcing/import_playlist.py:188-198`). Misses become `external_wanted` rows that remember the playlist and
position (`ours:sourcing/import_playlist.py:352-357`, `ours:crates/store.py:668-680`); ambiguous rows park as `review`
with the candidate ids. There is no score and no threshold anywhere in `choose`: equality of keys plus a 4 s window.

**Soulseek candidates: `sourcing/scorer.py`.** `name_match` takes the best of three passes over basename and folder
(`ours:sourcing/scorer.py:91-117`); under 0.55 the candidate is rejected (`ours:sourcing/scorer.py:155-157`). The
title-slot rule (`ours:sourcing/scorer.py:99-105`, commit `59c6f6a`): after a mid-name track number only the words
after it count as the title, because an album title track's name is in every file of that album. Version: the file is
read with `parse_filename` (track number, file junk, then `parse_title`, `ours:sourcing/identity.py:313-321`) and a
candidate that names a version the row did not ask for and the tier does not accept is `rejected`, not ranked lower
(`ours:sourcing/scorer.py:171-177`); for a crate copy upgrade any other version is rejected
(`ours:sourcing/scorer.py:165-170`).

**After download: verify.** `_acoustid_check` fails a file only when AcoustID disagrees with a *known* recording id;
with no recording id, "nothing known … never fails" (`ours:sourcing/verify.py:387-404`). The id backfill uses
MusicBrainz (ISRC, then the file's id, then artist + base title) and AcoustID only when `ACOUSTID_KEY` is set
(`ours:docs/identity.md:108-117`), 0.8 being "confident" (`ours:docs/identity.md:135`). Only 98 of 831 library files
carried a recording id when that was written (`ours:docs/identity.md:108`).

**D26** (`ours:docs/specs/2026-10-17-amperfy-pivot.md:21`): source the exact track, the version the playlist row
names; a 12"/extended mix is never preferred and never stands in for a radio edit; the version machinery stays to tell
versions apart.

## The difference that matters

**ext-74, the same-named album folder.** The case (`ours:docs/specs/2026-10-22-downloads-and-requests.md:27`,
`ours:docs/specs/2026-10-22-downloads-and-requests.md:35-40`): wanted "I'm Still In Love With You" by Al Green, album
of the same name, 196 s; the peer offered only `Al Green\I’m Still in Love With You (1972)\09 - One of These Good Old
Days.flac`, 195 s, which our scorer accepted at 84.5. Duration cannot tell track 1 (195.7 s) from track 9 (195.6 s).
Walking SoulSync's Soulseek path over it (hand estimate; the peer's path prefix `@@peer\Music\` assumed):

1. **Base score: accepted.** The artist hits exactly on the `Al Green` segment (1.0,
   `SoulSync:core/matching_engine.py:993-1012`). The album segment is 0.91 like the album (+0.10,
   `SoulSync:core/matching_engine.py:1053-1054`); FLAC +0.03; duration 1.0. The title ratio against the whole path is
   about 0.47. With backslashes the word-boundary bonus misses only because the backslash is deleted (`greenim`,
   `SoulSync:core/matching_engine.py:196`). With `/` separators the album folder supplies the boundary hit and the
   +0.3 (`SoulSync:core/matching_engine.py:969-973`): that is the very failure our title-slot rule was written for.
   Either way the title gate passes (≥ 0.30) and the base score is about 0.89 (`\`) or 1.0 (`/`), well over 0.58.
   **SoulSync's base scorer would have accepted track 09.**
2. **Base-title veto: rejected, narrowly.** With the artist exact, `base_title_of` reduces the wish to
   `im still in love with you` and the file to `one of these good old days`; their ratio is **0.275**, under the 0.30
   floor, so the row returns `rejected_base_title_mismatch` (`SoulSync:core/matching_engine.py:1307-1335`). The
   recovery pass skips it (confidence 0, `SoulSync:core/downloads/validation.py:877-879`). The veto rests on the
   folder layout: for a flat name `Al Green - I'm Still in Love With You - 09 - One of These Good Old Days.flac`, no
   track prefix leads, `strip_artist_prefix` removes only "Al Green", and the rsplit tail is no version qualifier
   (`SoulSync:core/matching_engine.py:1497-1507`), so the candidate base keeps the album words and scores about 0.61:
   no veto (hand estimate). That "Artist - Album - NN - Title" shape is the one our title-slot rule
   targets (`ours:sourcing/scorer.py:99-105`). Even in the folder layout the margin is 0.025 of a character ratio: a wrong sibling title sharing a few more letters with the wish (or a typo'd filename, which the
   floor is deliberately lenient for, `SoulSync:core/matching_engine.py:1300-1301`) would pass. It is a floor on
   similarity, not an identity test.
3. **AcoustID: would FAIL it, if enabled.** AcoustID named "One of These Good Old Days" at 0.958 on 10-21 (our spec,
   line 27 above). That is ≥ 0.80 with a title < 0.70, so SoulSync returns `FAIL "Audio mismatch"` and quarantines
   (`SoulSync:core/matching/audio_verification.py:829-831`, `SoulSync:core/imports/pipeline.py:1112-1146`), provided
   both titles are plain ASCII: at a fingerprint ≥ 0.95 with the artist agreeing, any non-ASCII character in either
   title (a curly ’ in "I’m") turns the result into SKIP, "Likely same song in different language/script"
   (`SoulSync:core/matching/audio_verification.py:794-797`, `SoulSync:core/matching/audio_verification.py:823-827`). It is off
   by default (`SoulSync:core/settings.py:745-748`). It needs no recording id: it compares titles. Ours needs one
   (`ours:sourcing/verify.py:402`), which is exactly why ext-74 passed verify. S1-02 plans that title comparison
   (`ours:docs/specs/2026-10-22-downloads-and-requests.md:68-72`), and S2-03 plans the recording id
   (`ours:docs/specs/2026-10-22-downloads-and-requests.md:112-118`).
4. **Album downloads.** The veto does not run when SoulSync takes a whole album folder (album bundle): the bundle
   maps files to tracks with `assign_album_tracks` (`SoulSync:core/soulseek_client.py:2070-2077`), whose module
   imports no matching engine (`SoulSync:core/downloads/soulseek_identity.py:18-26`), while the veto lives only in
   `calculate_slskd_match_confidence_enhanced` (`SoulSync:core/matching_engine.py:1269`,
   `SoulSync:core/matching_engine.py:1307-1335`). That path would not assign track 09 to track 1, but the per-track source-reuse path scores a stored folder's files with the base score at ≥ 0.70 and no veto (`SoulSync:web_server.py:16757-16762`), so a reused folder lacking track 1 yields track 09; 04-soulseek walks ext-74 on both paths.

So SoulSync would most likely have **rejected** ext-74's file as it was laid out (an album folder), by a 0.025 margin
in step 2, on the per-track search path; on the folder-reuse path it would have accepted it (step 4). It would have **accepted** the same wrong file under a flat "Artist - Album - NN - Title" name. Step 3 is a
stronger net, but it is off by default and steps aside for non-ASCII titles. Our planned S1-01 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:61-66`) is the
exact version of step 2: the title slot's song key must equal the wanted key, with no threshold.

**Against D26 (the exact track).**
- *Plain wanted, extended or radio-edit file:* SoulSync's Soulseek path accepts both with a 0.025/0.04 penalty
  (0.14 for a radio edit with `content_filter.prefer_explicit` on; table above). That breaks D26's "never stands in". Ours rejects extended unless the tier accepts it, and with
  `[versions.*]` gone from the policy nothing is accepted (`ours:docs/specs/2026-10-17-amperfy-pivot.md:21`). Both
  stacks only rank an edit/plain swap (`ours:sourcing/scorer.py:171-177`); that is a gap in ours too.
- *"Have it":* SoulSync's 0.7 bar reads no duration and no id. A remaster counts as owned (as in ours). A
  "Live - Remastered 2011" copy of a 12-character title counts as owning the studio cut (0.875, hand estimate; the
  order at `SoulSync:core/matching_engine.py:298-321`). So does a "(Live)" track on a live album (#808, above). Ours wants equal keys and lengths within 4 s, else `ambiguous` for
  Michael (`ours:sourcing/import_playlist.py:188-197`). For DJ crates, where a 12" and a radio edit are different
  versions (`ours:docs/identity.md:11`), our rule is the safer one. SoulSync's wishlist strict check
  (`SoulSync:core/wishlist/library_match.py:156-191`) is the closest it comes, and playlist sync does not use it
  (`SoulSync:services/sync_service.py:1500-1512`, *absence inferred*).
- *Clean/explicit:* SoulSync treats explicit as the original for verification
  (`SoulSync:core/matching/audio_verification.py:205-217`) and strips explicit/clean in the library cleaner
  (`SoulSync:database/music_database.py:14215-14216`). Ours keeps clean/explicit as versions
  (`ours:sourcing/identity.py:88-91`), because a clean edit must never replace an explicit file.

**Against goals C and D (requests, albums).** SoulSync asks the library before a request downloads, but only by
fuzzy title and artist (`check_track_exists` at 0.8, `SoulSync:api/music_requests.py:86`). Its exact-id check
(`SoulSync:core/library/track_identity.py:144-188`) runs in the watchlist (`SoulSync:core/watchlist_scanner.py:2900-2976`)
and in the import pre-check *after* a download (`SoulSync:core/imports/library_check.py:202-225`); its album
completeness count (`SoulSync:database/music_database.py:12918-12936`) answers "do I already have this album?" for
the discography views. Ours does not ask the library before downloading at all
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:29`, ext-81's second copy). The pattern worth having is "skip
only on an exact id pairing; a fuzzy pairing never skips" (`SoulSync:core/imports/library_check.py:12-17`).

**Breadth.** SoulSync keeps a dozen provider ids per track and per album (`SoulSync:core/source_ids.py:42-74`) and a
MusicBrainz enrichment worker. Ours keeps the recording/work id in the tags and writes proposals only after review
(`ours:docs/identity.md:108-140`). The provider-id spread serves SoulSync's many download sources; ours downloads from
Soulseek only, after Michael's approval (D7, `ours:docs/specs/2026-10-13-next-session-design.md:61`), so the
recording id and the ISRC are the ids that matter.

## Worth taking?

- **Take (adapt):** the title-based AcoustID rule, "a confident fingerprint naming another title is a failure" with
  no recording id needed (S1-02 already plans it), and the base-title idea, done our way as key equality (S1-01).
  Also the import pre-check rule "skip as already owned only on an exact MBID/ISRC pairing"
  (`SoulSync:core/imports/library_check.py:12-17`) for the planned "ask the library before downloading" step.
- **Take the test cases, not the code:** SoulSync's issue-numbered regressions are a free corpus of real naming
  shapes: `(Live)` vs `- Live`, divergent remixers, CJK titles, "Dani California" vs "Californication", a
  same-artist sibling in the right folder (#1626) (`SoulSync:core/matching_engine.py:323-367`,
  `SoulSync:core/matching_engine.py:121-150`, `SoulSync:core/text/title_match.py:75-105`,
  `SoulSync:core/matching_engine.py:1288-1306`). Paraphrasing their filename shapes into our scorer tests costs little.
- **Do not take:** the weighted fuzzy scores and their many hand-tuned thresholds (0.58, 0.63, 0.7, 0.8, 0.30,
  0.25, +0.3, +0.10…). Their own comments record the threshold tuning fighting the path noise
  (`SoulSync:core/matching_engine.py:1517-1529`). The extended/radio leniency contradicts D26, and the library check
  ignores duration.

**Verdict:** adapt. Ours is stricter where D26 and the crates need it: key equality, versions as identity, 4 s length
windows, `ambiguous` instead of a guess. SoulSync's matcher would not improve on it. Two SoulSync rules close real
gaps in ours, both already sketched in S1-01/S1-02: a wrong title in a right folder is rejected, and AcoustID
disagreeing on the *title* fails a download. Add a third: an exact-id "already owned" check before downloading.
