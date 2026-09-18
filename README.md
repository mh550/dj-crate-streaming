# DJ crate streaming — sourcing prototype (Phase 1, unknown-users variant)

Spec: `../ideas/dj-crate-streaming/spec.md` (§7 slskd bullet, §8 Phase 1).
This folder holds the first real code for the project: **the piece that turns
"I want this track" into "the right lossless file from whichever Soulseek peer has
it"**, now that we assume the peers are unknown.

```
sourcing/policy.py        quality policy (preferred/allow/deny formats, bitrate floors, tolerances)
sourcing/scorer.py        pure ranking of slskd search responses → explained candidates
sourcing/verify.py        post-download checks: FLAC STREAMINFO parse, duration vs expected, fake-lossless heuristic, ffprobe if present
sourcing/slskd_client.py  stdlib-only slskd REST client (search → poll → responses → enqueue → downloads)
sourcing/cli.py           `rank` (fixture or live slskd) and `verify`
fixtures/                 slskd-shaped search responses covering the failure modes
tests/                    pytest (12 tests, no network)
```

## Try it (offline, no slskd needed)

```bash
cd ~/projects/dj-crate-streaming
python3 -m pytest -q
python3 -m sourcing.cli rank --fixture fixtures/search_responses.sample.json \
  --artist Chic --title "Good Times" --album "Risqué" --duration 501 --year 1979
```

Each candidate prints its score and *why* — that explanation is the point of the
prototype: when the orchestrator later picks a file automatically, you can audit
the choice.

## Against a real slskd (once the Phase 0 box exists)

```bash
export SLSKD_API_KEY=...   # slskd.yml → web.authentication.api_keys
python3 -m sourcing.cli rank --slskd http://server:5030 --artist Chic --title "Good Times" --duration 501
python3 -m sourcing.cli rank --slskd http://server:5030 --artist Chic --title "Good Times" --duration 501 --download
python3 -m sourcing.cli verify "/srv/incoming/03 - Good Times.flac" --duration 501
```

## What the scorer does (and why)

Candidates come from *anyone*, so trust is earned per file:

- **Hard rejects:** disallowed formats, locked files, lossy below the floor (320
  kbps default), and "FLAC" whose size/length implies < 500 kbps (a lossy
  transcode wearing a .flac extension).
- **Name match (dominant, 0–45):** soularr-style passes — `artist - title`
  similarity, title match *plus* artist appearing somewhere in the path, exact
  title in name. A bare `Good Times.flac` with no artist anywhere is capped so it
  can't outrank a properly named file (INXS also has a "Good Times").
- **Format preference (0–20):** policy order, FLAC first.
- **Duration vs known length (−15…+15):** the strongest identity signal we have
  before downloading. ±4 s = match; 4–20 s = maybe a different edit; more = probably
  a different version (7" edit, live, remix).
- **Album/year folder hints (0–6), peer reliability (−10…+10):** free slot, queue
  length, upload speed, and "peer has the whole album" as a rip-quality proxy.

Weights are guesses to be tuned on real results. The fixture encodes the cases we
care about: real album rip, hi-res remaster, 320 mp3, 128 mp3, fake FLAC, 7" edit,
same-title-different-artist, locked file, other track from the same folder.

## Not done yet

- AcoustID fingerprint verification (`fpcalc`) — the definitive "is this the
  recording" check. `verify.py` has the hook.
- Metadata lookup for the *expected* duration/album (Spotify or MusicBrainz) —
  today you pass `--duration` by hand. SpotiFLAC (`../library/SpotiFLAC`) already
  does Spotify search; reuse.
- Tagging + moving into `/srv/music` (beets), and the reconcile loop that drives
  this from crate playlists — that's the orchestrator (Phase 2).
- Fallback to SpotiFLAC when Soulseek has nothing.
