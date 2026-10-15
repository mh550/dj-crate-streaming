# M4: quality tiers in the sourcing policy — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans (inline) with superpowers:test-driven-development. Code only: no downloads (D7).

**Goal (spec §1, D9):** one setting, four values: `low`, `medium`, `high`, `crate`. It drives what the
Soulseek getter picks and, by the same name, the stream transcode. `crate` is today's policy, unchanged.

**Design:**
- `QualityPolicy` gains `name`, `speed_weight` (0 = quality only … 1 = speed only), `arrival_budget_s`
  (what counts as "arrives soon") and `download_cap_Bps` (our own download cap, bytes/s; 0 = none).
  `TIERS = {"low", "medium", "high", "crate"}`; `DEFAULT_POLICY is TIERS["crate"]`.

  | tier | lossy floor | speed_weight | arrival budget | formats |
  |---|---|---|---|---|
  | low | 32 kbps | 0.8 | 60 s | any lossy or lossless except wma/ra/mid |
  | medium | 64 kbps | 0.6 | 60 s | same |
  | high | 128 kbps | 0.35 | 300 s | same |
  | crate | 320 kbps (lossless preferred) | 0 | — | today's allow/deny |

- `estimated_arrival_s(candidate, cap)`: `size / min(uploadSpeed, cap)` (unknown speed → 50 kB/s,
  pessimistic) plus, without a free slot, `30 s + 20 s × queueLength`.
- `score = (1 − w) × quality + w × speed`, where quality is today's score (name, format, lossless
  sanity, duration, hints, peer reliability) and `speed = 100 × B / (B + arrival)`. `w = 0` reproduces
  today's numbers exactly, so every existing test holds under `crate`. Name-match and floor
  rejections stay hard for every tier.

**Acceptance (spec):** a 2 MB 64 kbps mp3 on a fast peer and a 30 MB FLAC on a slow, queued peer: the
mp3 ranks first under `low` and `medium`; the FLAC under `crate` (and under `high`, where 64 kbps is
below the floor). A test pins each tier's floor. Hand check: arrivals ≈ 1 s vs ≈ 430 s; under low
`0.2·70 + 0.8·98 ≈ 92` beats `0.2·91 + 0.8·12 ≈ 28`.

**Next step (runbook M4 step 2):** `sourcing.cli rank/fetch --tier`, `external_wanted` and crate rows
carry a tier, web selector renamed to the four tiers with the stream mapping (opus 64/96/160, raw).
