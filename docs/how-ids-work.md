# How ISRC, MusicBrainz and AcoustID work, and how this system uses them

Written 2026-10-17 for Michael. Code: `scripts/identity_backfill.py`, `sourcing/musicbrainz.py`, `sourcing/acoustid.py`,
`sourcing/identity.py`. Results of the live proposal: `docs/identity-backfill-report.md`.

## The three things, briefly

**ISRC** = International Standard Recording Code. A 12-character code (like `USRC17607839`) that a label assigns to one
specific recording (a master). It is printed in the metadata of the release, shipped in the file's tags
(`ISRC`/`TSRC`) and carried by Spotify, so an Exportify CSV has it. Same master re-released on a compilation: usually
the same ISRC. A remix or a new edit: usually a new ISRC. It is label-entered, so it can be missing, reused or wrong.

**MusicBrainz** (MB) = an open, volunteer-edited catalogue of music. It keeps separate things, each with a UUID (MBID):
an *artist*; a *recording* (one specific take or mix, such as the 12" mix); a *release* (an album or single); a *work*
(the composition behind many recordings). MB links an ISRC to the recording(s) that carry it, and stores each
recording's length and a human note ("12" version"). Asking MB is an HTTP call to `musicbrainz.org/ws/2`: look up by ISRC,
search by artist + title, or fetch one recording by id. MB asks for about one request a second and a descriptive
User-Agent, so the client waits between calls, retries when MB answers 503 "busy" (about 1 in 10 did), and caches every
answer on disk so an interrupted ~45-minute run never repeats a question.

**AcoustID** = a lookup by *sound*. The program `fpcalc` (Chromaprint) turns the audio of a file into a short
fingerprint. The AcoustID web service holds fingerprints that users submitted, each linked to MB recording ids, and
answers with matches and a score from 0 to 1. It needs a free application key (`ACOUSTID_KEY`). The `acoustid_id`
we store in a file's tag is AcoustID's own id for that fingerprint.

## How they relate

```
 your file ── tags: ISRC? title, artist, length
     │
     ├─ ISRC ───────▶ MusicBrainz: "which recordings carry this ISRC?" ──┐
     ├─ title+artist ▶ MusicBrainz: search ─────────────────────────────┼─▶ candidate recordings
     └─ audio ──fpcalc──▶ AcoustID: "which recordings sound like this?" ─┘        │
                                                                                  ▼
                                   our FIT CHECK on each candidate: same lead artist, same base title and version
                                   label ("12" Mix" ≠ "Radio Edit"), length within 4 s, not a video recording
                                                                                  ▼
                                     one fit ─▶ propose it    several ─▶ ambiguous    none ─▶ none/conflict
```

ISRC and AcoustID are two independent routes *to* a MusicBrainz recording id. MusicBrainz is the catalogue both point
into. Our fit check is a gate in front of all of them, because each can be wrong in its own way.

## What the backfill writes, and where

Only three tag fields, and only where the file's own field is empty: the MB **recording** id
(`musicbrainz_trackid`, the tag's historical name), the MB **work** id, and the **AcoustID** id. Nothing else in the file
changes; a log with the old values is written first and `revert` undoes it.

Why this matters beyond tidiness: (1) Navidrome builds its song id from the recording id when the tag exists, so ids
survive retags and moves (the cause of the M2 "new id" problem); (2) `same_version()` in `sourcing/identity.py`
treats two files with the same recording id as one recording and lets M8 trash the worse copy. **A wrong id can make the
system treat two different versions as one and trash a real one.** That is why the bar is high.

## The classes, and why I apply only the first three by default

| Class | What proves it | Files | Apply? |
|---|---|---:|---|
| `confirmed` | the file already carries a recording id and MB agrees (name, version, length) | 77 | yes: only fills a missing work id |
| `isrc` | the file's own ISRC leads to exactly one recording that passes the fit check | 172 | yes |
| `acoustid` | the audio fingerprint matches at 0.8+ and singles out one recording that passes the fit check | 236 | yes |
| `search` | only names + length: exactly one MB recording fits | 16 | **not by default** (trial of all 16 applied 2026-10-17) |
| `ambiguous` | several recordings fit | 89 | only if you choose one |
| `conflict` | the file's id does not fit, or two ids disagree | 38 | no, needs a look |
| `none` | nothing fits | 203 | only if you choose one |

Counts are from the second proposal (2026-10-17, with the AcoustID key). The first one (no key) had `acoustid` 0 and
`search` 239: the key moved 223 files from `search` to `acoustid`, which is the point of the next paragraph.

The first three each have a proof that does not come from the title: a label-assigned code, or the sound itself, plus
the fit check. `search` has only names and length, and MB often holds two recordings at one length (about a third of
the searches did), so "exactly one fits" can mean "the other one is not in MB yet", not "this is the one". Stamping a
wrong id costs more than leaving a file unlabelled (see above), and a file without an id still works.

My suggestion: get the AcoustID key first. It turns many `search` rows into `acoustid` rows with audio proof, which
shrinks the 239. Then look at a sample of the rest with `apply --classes confirmed,isrc,acoustid,search --limit 20`
(the log lets `revert` undo it) before deciding on the remainder.
