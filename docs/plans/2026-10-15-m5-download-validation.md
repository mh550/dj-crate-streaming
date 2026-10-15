# M5: download validation — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans (inline) with superpowers:test-driven-development. Code only:
> no downloads (D7). Verify runs on the host (`ffmpeg`, `ffprobe`, `flac`, `fpcalc` in `/usr/bin`); the crates
> image has none of them.

**Goal (spec §3a):** `verify(path, expected_duration_s, tier, reference=None) -> Verdict` with hard `problems`,
soft `warnings` and a `measurements` dict, doing by code what careful Soulseek users do by hand.

**Spec:** `docs/specs/2026-10-13-next-session-design.md` §3a (and §1 for the tiers).

## Global constraints

- stdlib Python + the host tools above; no numpy, no sox. No binary fixtures committed: audio fixtures are
  generated in the tests with ffmpeg from seeded noise (`anoisesrc …:s=<seed>`).
- Existing tests unchanged. `verify(path, duration)` without a tier behaves exactly as today (header checks
  only, no decoding): `fetch.py` and `sourcing.cli verify` keep working until step 3 moves them.
- Tiers: `low`, `medium`, `high`, `crate` (`sourcing.policy.TIERS`).

## Calibration (measured before writing the plan, 2026-10-15)

One ffmpeg pass: `asplit` into a full-band branch (`astats` + `silencedetect`) and one branch per band edge
(`firequalizer=gain='if(gte(f,E),0,-120)'` → `astats`), reading `RMS level dB` per branch. `afftfilt` was
tried first and took minutes per track; `firequalizer` takes 4–10 s for a full track with 9 branches.

| file | >16 | >17 | >18 | >19 | >20 kHz (dB vs full band) |
|---|---|---|---|---|---|
| white noise FLAC | −5.7 | −6.4 | −7.4 | −8.7 | −10.4 |
| same → 128 kbps mp3 → FLAC | −15.0 | **−62.7** | −64.7 | −66.4 | −68.4 |
| library FLACs (6, 1974–2016) | −30…−50 | | | | −40…−63, steps of 2–7 dB per edge |
| library mp3 (Sinbad) | −55.7 | −62.0 | −71.7 | **−98.4** | −108 |

Music falls off smoothly; an encoder's lowpass is a **cliff**. So the cutoff estimate is the last edge before
the first step of ≥15 dB between adjacent edges, or before a band that is empty (≥90 dB under the full band).
Absolute levels can't be used: a quiet 1950s jazz FLAC sits at −85 dB above 19 kHz with no lowpass at all.

- 24-bit padding: `astats` "Bit depth: a/b" — `b` is the bits actually used (16 for a padded file, 24 for
  real 24-bit), which is the spec's "low byte all zero" check without a second decode.
- >48 kHz: a 44.1 k file upsampled to 96 k has a cliff between 22 and 24 kHz (−9 then −21 dB); real 96 k
  noise is flat to 30 kHz. Edges 22 and 24 are added when the sample rate is above 48 kHz.
- Truncation: a FLAC cut to 63 % decoded without one ffmpeg error; the decoded sample count (astats
  "Number of samples", per channel) against STREAMINFO caught it, and so did `flac -t`.
- Fingerprints (`fpcalc -raw`, bit-error rate at the best offset): same audio via 128 kbps mp3 0.01 (noise)
  and 0.008 (library track); different library tracks 0.47; two pink-noise seeds 0.25. Different = BER > 0.20.
- Clipping: noise boosted 20 dB → peak +0.0003 dB, flat factor 4.7; unclipped noise 0.0–0.2.

## Design

`sourcing/verify.py` (one file; it already holds the header probes):

- `Verdict(ok, problems, info, warnings=[], measurements={})` — existing fields first, so callers keep working.
- Pure functions (tested without ffmpeg):
  - `estimate_cutoff(full_db, bands: dict[float, float]) -> float` — kHz edge as above; `0.0` = nothing above
    the first edge.
  - `fingerprint_ber(a, b, max_shift=80, min_overlap=20) -> float` (±80 items ≈ ±10 s: a vinyl rip and a CD
    rip start at different places).
  - `parse_ffmpeg(stderr, n_bands) -> dict` — errors (`[error]`/`[fatal]` lines), per-branch astats, silences.
    Tested against a captured real stderr in `fixtures/ffmpeg_analysis.sample.txt`.
- `analyse(path, sample_rate) -> dict` runs the one ffmpeg pass (`-loglevel level+info`), plus `flac -t` for
  FLAC. `fingerprint(path) -> list[int]` runs `fpcalc`.
- `verify(path, expected_duration_s=None, tier=None, reference=None, tolerance_s=4.0, min_lossless_kbps=500)`
  collects `(check, message)` findings, then sorts them by tier:

  | check | how | hard in |
  |---|---|---|
  | missing / unreadable | as today | every tier |
  | integrity | ffmpeg `[error]` lines; `flac -t` exit code | every tier |
  | duration | ±4 s vs the wanted record (as today) | every tier |
  | truncated | container − decoded > 1 s | every tier |
  | recording | `reference` given and BER > 0.20 | every tier (spec: wrong song is wrong) |
  | transcode | claims lossless or ≥320 kbps, cutoff ≤ 16 kHz | crate (flag otherwise) |
  | fake 24-bit | claims 24, bits used ≤ 16 | crate (flag otherwise) |
  | fake hi-res | sample rate > 48 k, cutoff ≤ 22 kHz | crate (flag otherwise) |
  | implied kbps / sample rate | as today | crate (flag otherwise) |
  | maybe 192k source | claims lossless/≥320, cutoff 17–18 kHz | flag |
  | silence | > 3 s at start or end (`silencedetect n=-60dB d=3`) | flag |
  | clipping | peak ≥ −0.1 dBFS and flat factor ≥ 1 | flag |
  | tools missing | no ffmpeg / fpcalc on PATH | flag (the check is skipped, the message says so) |

  `tier=None` = today: header checks only, every finding hard. Messages say what was measured
  ("cutoff ≈16 kHz (energy stops above 16 kHz; lossless or 320 kbps reaches 19–20 kHz)").
- `measurements`: `codec, sample_rate, bit_depth, bits_used, duration_s, decoded_s, kbps, cutoff_khz,
  bands_db, peak_db, flat_factor, silence_start_s, silence_end_s, fingerprint_ber` (only what was measured).

## Steps (runbook M5)

1. This plan; TDD the pure functions, `parse_ffmpeg` on the captured stderr, the tier sorting and
   `verify` on generated fixtures (true FLAC, mp3→FLAC). Existing 3 verify tests untouched.
2. The spec's fixture set end to end: true FLAC, 128 kbps mp3 → FLAC, 16-bit padded to 24-bit, truncated
   copy, plus upsampled 96 k, leading silence, clipped noise and a wrong recording vs a reference.
3. `sourcing.cli verify <path> [--duration] [--tier] [--reference]` prints a table; `fetch` verifies with
   the row's tier and stores `measurements` on the row (new `measurements` JSON column via `_migrate()`),
   the web client shows them. Run over 10 random library FLACs; cutoffs into the log.
4. `docs/download-validation.md` for Michael.
5. Review (Opus), `/simplify`, milestone push.

## Review focus

1. A genuine old or lo-fi lossless recording must not hard-fail `crate` on the cutoff: only a cliff counts,
   and the message says what was measured. (Step 3 runs 10 library FLACs to check.)
2. Digital silence / `-inf` levels from astats must not crash the parser or invent a cliff
   (test: a silent band parses as −inf and `estimate_cutoff` treats it as empty).
3. A file ffmpeg can't open at all → one hard "integrity" problem, not an exception.
4. A lossy file (mp3) asked at `low` passes with warnings only, even with a 16 kHz cutoff.
5. Without ffmpeg (the crates container) a tiered verify must not pass silently: it warns that the decoded
   checks were skipped.
