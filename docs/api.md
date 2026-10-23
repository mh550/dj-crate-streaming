# Request API

For a future client (a web page, an app). The examples are the assertions of `tests/test_requests_api.py` and
`tests/test_catalog.py`, not invented. Code: `crates/service.py` (`CrateApp.add_request`, `requests`,
`request_detail`, `preview_request`, `approve_request`, `catalog_search`), `sourcing/requests.py` (the JSON shapes).
There is no client for it yet.

## Auth and exposure

The same as every other `/api/*` route of the crates app (`docs/architecture.md` §2, §8): no auth. The app listens on
`127.0.0.1:4580` and `tailscale serve` puts it on the tailnet, so anyone on the tailnet can call it, **including
approve**. The API never proxies audio. Bodies are JSON in and out; an error is `{"error": "<reason>"}` with the
status below. Camel-case keys. A body that is not a JSON object (a list, a string, a number, `null`) is 400
`body must be a JSON object` on every POST; one that is not JSON is 400 `bad request: …`.

Peer names (Soulseek users) and absolute paths never appear in any payload: a planned file is a basename, the
candidate's `username`, folder and path stay server side (`store.public` strips them). A row's `reason` may name a
file by its path inside the library (`Al Green/Singles/…flac`), as the web client's wanted list does.

## Statuses

**Row status** (`rows[].status`): `needs_source` (nothing asked of Soulseek yet), `review` (waiting for a pick or a
human, `reason` says why), `sourcing` (being fetched), `verify` (filed, Navidrome has not picked it up), `ok` (in the
library; `librarySongId` is set), `failed` (`reason` says why). A superseded row is `removed` and is not shown in
`rowCounts`.

**Request status** (`request.status`), the first that applies: `done` every row ok; `failed` no row ok and none
open; `partly` some row ok; `approved` some row is on its way (fetched, filed, or has an approval waiting); `open`.

## `POST /api/requests`

Body, one of: `{"url": "<Spotify track, album or playlist link>"}` (the open.spotify.com URL or a `spotify:` URI),
`{"mbReleaseId": "<uuid>"}` (an album) or `{"mbRecordingId": "<uuid>"}` (a track), the ids a catalog hit carries.
Downloads nothing. The same link again answers the existing request.

**201** a new request, **200** one that already existed (or, for a playlist the library has whole, `request: null`):

```json
{"request": {"id": 1, "kind": "album", "source": "https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z",
             "artist": "Al Green", "album": "I'm Still in Love With You", "year": null, "mbReleaseId": null,
             "status": "open", "createdAt": 1790000000.0},
 "rows": [{"id": "ext-1", "trackNo": 1, "artist": "Al Green", "title": "I'm Still In Love With You",
           "album": "I'm Still in Love With You", "year": null, "durationS": 196, "status": "needs_source",
           "reason": null, "librarySongId": null, "mbRecordingId": null}]}
```

(nine rows for this album; `source`/`createdAt` shown with the test's link and any timestamp). A track request has
`kind: "track"`, `album: null`, one row, `trackNo: null`. A playlist request has `kind: "playlist"`, `album` = the
playlist's name, and also `"playlist": {"id": "<navidrome id>", "name": "Tea tent", "matched": 0, "wanted": 3,
"ambiguous": 0}` (the playlist is made in Navidrome as `import-playlist` does). Rows the library already has come
back `ok` with `librarySongId`.

| Status | Reason text |
|---|---|
| 400 | `url is required`; `one of url, mbReleaseId, mbRecordingId`; `mbReleaseId is not a MusicBrainz id` (same for `mbRecordingId`); `unknown link kind: music.apple.com` / `unknown link kind: artist` |
| 404 | `MusicBrainz has no release <id>` / `MusicBrainz has no recording <id>`; `MusicBrainz release <id> lists no tracks` |
| 409 | a playlist of that name belongs to another user (the text names both) |
| 502 | `cannot reach Spotify (…)`, `cannot reach MusicBrainz (…)`, `MusicBrainz sent a reply this code cannot read (…)`, `could not write comment…` (the request is recorded all the same), or `cannot reach Navidrome: …` (a playlist's import; a Subsonic error code is 400 with its `code`) |

## `GET /api/requests`

Every request, newest first, with its rows counted by status (`removed` rows are not counted):

```json
{"requests": [{"id": 1, "kind": "album", "album": "I'm Still in Love With You", "status": "partly", "…": "…",
               "rowCounts": {"ok": 1, "needsSource": 4, "sourcing": 1, "verify": 0, "failed": 1, "review": 1}}]}
```

No requests yet is `{"requests": []}`. Errors: none of its own.

## `GET /api/requests/<id>`

The `POST` shape plus `preview` (the cached plan from the last preview, or `null`) and, on each row, `approval`
(its newest approval, or `null`):

```json
{"request": {"…": "…", "status": "approved"}, "preview": null,
 "rows": [{"id": "ext-1", "…": "…",
           "approval": {"id": 1, "purpose": "album", "ts": 1790000100.0, "usedAt": 1790000200.0,
                        "result": "ok: in library (al01)"}}]}
```

`usedAt` and `result` are `null` until the worker claims the approval; then `usedAt` is the claim's time and
`result` is `started`, and the worker's outcome (`ok: …`, `failed: …`) replaces it when the row has ended.

| Status | Reason text |
|---|---|
| 400 | `request id must be a number, not 'abc'` |
| 404 | `no request #99` |

## `POST /api/requests/<id>/preview`

Body `{}`. Searches Soulseek once per album and caches the plan (`req-<id>`); nothing is queued. It can take half a
minute. **200**:

```json
{"plan": {"folders": [{"label": "folder 1", "coverage": "8 of 9",
                       "rows": [{"id": "ext-1", "file": "Al Green - I'm Still in Love With You - 01 - I'm Still In Love With You.flac"}]}],
          "perTrack": ["ext-9"], "ts": 1790000300.0}}
```

`perTrack` are the rows no folder covers: they are searched one by one at approval. A playlist request without an
album group answers `{"plan": {"albums": [], "perTrack": ["ext-1", "ext-2", "ext-3"]}}`.

| Status | Reason text |
|---|---|
| 400 / 404 | as for `GET /api/requests/<id>` |
| 409 | `ext-3 is sourcing (in progress): the worker finishes it` (also `verify`); `ext-1: a download is in progress (approval #N); the worker finishes it`; `nothing to plan` (done request); `request #N: ext-1 in flight; approve it again once that has ended` (approved and claimed while the search ran: that album's plan is not cached) |
| 502 | `cannot reach slskd (slskd POST /searches: connection refused)` (nothing cached) |
| 503 | `slskd is not configured` |

## `POST /api/requests/<id>/approve`

Body `{}`. This is Michael's click (D7): it records one approval per row that needs a file, with the previewed
file where there is one. It downloads **nothing** itself; the worker picks the approvals up on its next tick and
downloads, verifies and files them. Approving without a preview is fine: the job plans when it runs. **200**:

```json
{"approved": [{"wantedId": "ext-1", "approvalId": 1,
               "candidate": {"basename": "Al Green - I'm Still in Love With You - 01 - I'm Still In Love With You.flac"}},
              {"wantedId": "ext-9", "approvalId": 9, "candidate": null}]}
```

`candidate: null` means the job plans that row (or goes per track). A playlist request's album groups (3 or more
open rows of one artist and album) get `album` approvals with their planned files, as an album request does; its
other rows get per-track approvals (`candidate: null`).
Afterwards `request.status` is `approved`. A row waiting for a version pick is not approved with its album.

| Status | Reason text |
|---|---|
| 400 / 404 | as above |
| 409 | the in-progress texts of preview; `nothing to approve` (done request, or all rows removed) |

## `GET /api/catalog/search`

Query: `?q=<text>&kind=album|track`.

What a client searches before it asks for a request. Every registered provider is asked (MusicBrainz, the only one
in this build; Spotify is the next, after `scripts/capture_spotify.py`'s capture). `inLibrary` is `true`/`false` from Navidrome, `null` when Navidrome could
not be asked (still 200). **200**:

```json
{"hits": [{"provider": "musicbrainz", "kind": "album", "title": "I’m Still in Love With You",
           "artist": "Al Green", "year": 1993, "trackCount": 9, "lengthS": null, "format": "CD",
           "ids": {"mbReleaseId": "<uuid>"}, "inLibrary": true}]}
```

A track hit has `ids: {"mbRecordingId": …}`, `lengthS` in seconds, `trackCount: null`. Post `ids` to
`POST /api/requests` to ask for it.

| Status | Reason text |
|---|---|
| 400 | `kind must be album or track`; `q is required` |
| 503 | `MusicBrainz is busy, try again` (after the client's own retries) |

## For a client

1. **Search**: `GET /api/catalog/search?q=…&kind=album`; show `inLibrary` hits as owned.
2. **Request**: `POST /api/requests` with a hit's `ids` or a pasted Spotify link. 201 new, 200 existing.
3. **Preview**: `POST /api/requests/<id>/preview`; show `folders` (label, coverage, files) and `perTrack`.
4. **Approve**: `POST /api/requests/<id>/approve` after the user says yes. Nothing downloads before this.
5. **Poll**: `GET /api/requests/<id>` for the status, rows and `approval.result`; `GET /api/events?limit=50` for
   the log (`status`, `approved`, `filed`, … with file basenames only).

Shell equivalent: `python -m sourcing.cli request add|list|show|preview|approve [--json]` (`docs/worker.md`, "The
morning path, without a client").

Not there yet: a UI (the client is Michael's open question), a Spotify catalog provider, and any `DELETE` or
cancel. The provider waits for real Web API responses: `scripts/capture_spotify.py` (usage in its docstring) captures
them as fixtures.
