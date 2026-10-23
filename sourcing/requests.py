"""A Spotify URL asked for as one request (S2-02): an album or a track becomes a `requests` row in crates.db whose
rows are external_wanted rows (request_id, track_no). A playlist URL is not a request yet (S2-07); seed-spotify and
import-playlist handle it as before.

`rows_from_spotify` is the one place that reads the embed; this module only records what it gives. An album request
then gets its MusicBrainz release when exactly one matches its rows one to one (S2-03): fetch verifies each row
against its recording id."""
from __future__ import annotations

from . import identity
from .musicbrainz import match_release
from .playlist_sources import lead_artist, rows_from_spotify
from .policy import IMPORT_TIER
from .spotify_csv import URL, fetch_entity


def canonical(url: str) -> str:
    """The URL without its share parameters, so a re-run of the same album finds its request."""
    m = URL.search(url)
    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}" if m else url


def add_spotify(store, url: str, *, fetch=fetch_entity, tier: str | None = None,
                default_tier: str = IMPORT_TIER) -> dict | None:
    """Record the album or track at `url` as one request and return it (`store.request(id)`); None for a playlist.
    Idempotent: the same URL again finds its request by source, and add_external_wanted returns the rows already
    queued (a row queued earlier joins the request when it belongs to none). When every row already belongs to a
    request, that request answers (the first row's) and no empty one is made. An album listing the same artist and
    title twice gets one row for both (add_external_wanted's same-row rule)."""
    entity = fetch(url)
    kind = entity.get("type")
    if kind not in ("album", "track"):
        return None
    rows = rows_from_spotify(entity)
    source = canonical(url)
    if kind == "album":
        artist = identity.lead_artist(entity["subtitle"].split(",\xa0")[0])
        album, year = entity["name"].strip(), rows[0].year if rows else None
    else:
        artist, album, year = lead_artist(rows[0], resolve=None), None, None
    rid = store.find_request(source)
    if rid is None and rows:
        held = [(store.find_external(lead_artist(r, resolve=None), r.title) or {}).get("request_id") for r in rows]
        if all(held):
            return store.request(held[0])
    rid = rid or store.add_request(kind=kind, source=source, artist=artist, album=album, year=year)
    for r in rows:
        store.add_external_wanted(lead_artist(r, resolve=None), r.title, album=r.album, duration_s=r.duration_s,
                                  year=r.year, source=source, tier=tier, default_tier=default_tier,
                                  request_id=rid, track_no=r.track_no)
    store.commit()
    return store.request(rid)


def match_request_release(store, request_id: int, mb) -> bool:
    """Store the album request's MusicBrainz release and each row's recording (S2-03); True when it has them.

    No one-to-one release → nothing stored, False: the request goes on without ids. The match is over the request's
    live rows: not `removed`, and per track number the newest (a re-seed queues a new row beside the failed one).
    A matched request is not searched again; a row added since (a re-seed) gets its recording from the stored
    release, fetched again (the cache answers it). Rows and release are written in one transaction.
    `mb` is a `MusicBrainz` client; its errors (MusicBrainzError, OSError from its cache) reach the caller."""
    req = store.request(request_id)
    if req is None or req["kind"] != "album" or not req["album"]:
        return False
    live = {r["track_no"]: r for r in sorted((r for r in req["rows"] if r["status"] != "removed"),
                                             key=lambda r: int(r["song_id"].removeprefix("ext-")))}
    rows = list(live.values())
    if req["mb_release_id"]:
        if all(r["mb_recording_id"] for r in rows):
            return True
        releases = [{"id": req["mb_release_id"], "track-count": len(rows)}]
    else:
        releases = mb.release_search(req["artist"] or "", req["album"])
    m = match_release(rows, releases, mb.release)
    if m is None:
        return False
    if not req["mb_release_id"]:
        said = " ".join(x for x in (m.format, m.date) if x)
        store.log(None, None, "release", f"#{request_id} musicbrainz release {m.id} ({said})")
    store.set_request_release(request_id, m.id, {t.position: t.recording_id for t in m.tracks})   # commits the event
    return True
