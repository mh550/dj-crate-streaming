# SoulSync review: how it works, how it compares, what to take

Research run `dj-soulsync-review-2026-10-22` (spec: `docs/specs/2026-10-22-soulsync-review.md`). Subject:
[SoulSync](https://github.com/Nezreka/SoulSync), read from the pinned read-only clone at commit `34bf7cf9c741`
(2026-10-21, "Merge pull request #1821"). Music only; video/TV, audiobooks and podcasts are named once and skipped.

Citations: `SoulSync:<path>:<line>` is a path in that clone at `34bf7cf9c741`; `ours:<path>:<line>` is a path in this
repository at the run's base. A claim with no citation carries the mark *unverified*.

## Summary

(written by V4-02)

## Sections

1. [01-map.md](01-map.md): what SoulSync is (process model, data stores, settings and credentials, deployment,
   tests and CI, module map, license, maintenance health).
2. [02-intake.md](02-intake.md): where wanted music comes from (Spotify, other playlist sources, wishlist and
   watchlist, requests, Lidarr compatibility).
3. [03-matching.md](03-matching.md): "have it / missing", identity, versions and editions.
4. [04-soulseek.md](04-soulseek.md): Soulseek sourcing in full (queries, scoring, album folders, fallback, peer
   memory, transfers, errors, throttling, the slskd endpoint table).
5. [05-other-sources.md](05-other-sources.md): the non-Soulseek music sources, with legality / terms-of-service
   flags, and how the orchestrator picks between sources.
6. [06-verification.md](06-verification.md): what proves a download is right and good (validation, album
   consistency, AcoustID, quarantine).
7. [07-filing-library.md](07-filing-library.md): tags, file placement, the library, and Navidrome.
8. [08-ui-api.md](08-ui-api.md): UI, API and the phone.
9. [09-recommendations.md](09-recommendations.md): the four options, the recommendation, next steps, and questions
   for Michael.

## Stage-by-stage comparison

<!-- V3-01 writes this section -->

## Fit to goals

<!-- V3-02 writes this section -->
