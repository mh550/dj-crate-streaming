"""A Spotify URL asked for as one request (S2-02): an album or a track becomes a `requests` row in crates.db whose
rows are external_wanted rows (request_id, track_no). A playlist is imported as before (import-playlist); its import
then becomes a `playlist` request over the import's wanted rows (S2-07, `add_playlist`; `import-playlist --request`),
which album_job approves in one go. A link asked for over HTTP (`POST /api/requests`, S3-01) goes through
`parse_link`, `fetch_link` (the one Spotify fetch) and `add_link` (a playlist: the import with `--merge` semantics,
then its request); `view` is the request as the API shows it.

`rows_from_spotify` is the one place that reads the embed; this module only records what it gives. An album request
then gets its MusicBrainz release when exactly one matches its rows one to one (S2-03): fetch verifies each row
against its recording id."""
from __future__ import annotations

import re
from dataclasses import dataclass

from crates.reconcile import CommentNotKept
from crates.store import public
from . import identity
from .import_playlist import import_playlist
from .musicbrainz import match_release
from .playlist_sources import lead_artist, rows_from_spotify
from .policy import IMPORT_TIER
from .spotify_csv import URL, fetch_entity


KINDS = ("album", "playlist", "track")
_OPEN = re.compile(r"^(?:https?://)?open\.spotify\.com/(?:intl-[A-Za-z-]+/)?([a-z]+)(?:/([A-Za-z0-9]+))?")
_URI = re.compile(r"^spotify:([a-z]+):([A-Za-z0-9]+)$")
_HOST = re.compile(r"^(?:[a-z]+://)?([^/?#\s]+)")


class UnknownLink(ValueError):
    """A link that is not a Spotify album, playlist or track; its text is the reason (`unknown link kind: …`)."""


class SpotifyUnreachable(Exception):
    """The embed could not be fetched or read (spotify_csv.fetch_entity's network and page errors)."""


def parse_link(url: str) -> tuple[str, str]:
    """(kind, id) of a Spotify link: `https://open.spotify.com/[intl-xx/]<kind>/<id>[?…]` or `spotify:<kind>:<id>`.
    Anything else raises UnknownLink naming what it is: another platform's host, or Spotify's other kinds (artist,
    show …). Other platforms are out on purpose (spec S3, Out)."""
    url = url.strip()
    m = _OPEN.match(url) or _URI.match(url)
    if m is None:
        host = _HOST.match(url)
        raise UnknownLink(f"unknown link kind: {host.group(1) if host and '.' in host.group(1) else url}")
    kind, sid = m.groups()
    if kind not in KINDS:
        raise UnknownLink(f"unknown link kind: {kind}")
    if not sid:
        raise UnknownLink(f"unknown link kind: {kind} without an id")
    return kind, sid


@dataclass
class Link:
    kind: str           # album | playlist | track (parse_link's)
    url: str            # https://open.spotify.com/<kind>/<id>: what is fetched and recorded as the source
    entity: dict        # the embed's entity


def fetch_link(url: str, fetch=fetch_entity) -> Link:
    """The link parsed (UnknownLink before anything is asked) and its embed fetched, once. A fetch that fails
    (URLError, HTTPError, IncompleteRead; fetch_entity's SystemExit; a page whose JSON changed shape) or an embed
    add_link could not read raises SpotifyUnreachable: Spotify's page is at fault, not the link."""
    kind, sid = parse_link(url)
    link = f"https://open.spotify.com/{kind}/{sid}"
    try:
        entity = fetch(link)
    except (Exception, SystemExit) as e:        # the page is untrusted and changes: any failure is Spotify's
        raise SpotifyUnreachable(f"cannot reach Spotify ({type(e).__name__}: {e})") from None
    if not _readable(entity, kind):
        raise SpotifyUnreachable(f"cannot reach Spotify (its page for {link} is no {kind} this code can read)")
    return Link(kind, link, entity)


def _readable(entity, kind: str) -> bool:
    """Whether the embed has what add_link reads: its type, name and rows (an album's subtitle too); an album or a
    track has at least one row."""
    try:
        rows = rows_from_spotify(entity)
        entity["name"].strip()
        if kind == "album":
            entity["subtitle"].split(",\xa0")
    except (KeyError, TypeError, AttributeError, ValueError):
        return False
    return isinstance(entity, dict) and entity.get("type") == kind and (kind == "playlist" or bool(rows))


@dataclass
class Added:
    request: dict | None    # store.request(); None for a playlist none of whose rows is wanted
    created: bool           # a new request (the HTTP 201); False when the link's request answers again
    report: object = None   # a playlist's import_playlist.Report


def add_link(store, client, link: Link, *, tier: str | None = None) -> Added:
    """Record a fetched link as a request. An album or a track is add_spotify's request. A playlist is first
    imported as `import-playlist --merge` does (matched songs into the playlist of that name, made or adopted; the
    rest wanted rows) and then is add_playlist's request over those rows. `client` is Navidrome's SubsonicClient
    (a playlist only). NameCollision (another user's playlist of that name) and CommentNotKept reach the caller;
    for the latter the request is recorded first, as the CLI does."""
    entity = link.entity
    if link.kind == "playlist":
        name = entity["name"].strip()
        before = store.find_playlist_request(name)
        try:
            rep = import_playlist(name, rows_from_spotify(entity), client, store, source=link.url, merge=True,
                                  tier=tier)
        except CommentNotKept as e:
            add_spotify(store, link.url, fetch=lambda _url: entity, playlist_id=e.report.playlist_id)
            raise
        req = add_spotify(store, link.url, fetch=lambda _url: entity, playlist_id=rep.playlist_id)
        return Added(req, req is not None and before is None, rep)
    before = store.find_request(link.url)
    req = add_spotify(store, link.url, fetch=lambda _url: entity, tier=tier)
    return Added(req, before is None and req is not None and req["source"] == link.url)


def view(req: dict) -> dict:
    """`{"request": …, "rows": […]}`, camelCase, through store.public (no peer name, no absolute path)."""
    return public({
        "request": {"id": req["id"], "kind": req["kind"], "source": req["source"], "artist": req["artist"],
                    "album": req["album"], "year": req["year"], "mbReleaseId": req["mb_release_id"],
                    "status": req["status"], "createdAt": req["created_at"]},
        "rows": [{"id": r["song_id"], "trackNo": r["track_no"], "artist": r["artist"], "title": r["title"],
                  "album": r["album"], "year": r["year"], "durationS": r["duration"], "status": r["status"],
                  "reason": r["reason"], "librarySongId": r["library_song_id"], "mbRecordingId": r["mb_recording_id"]}
                 for r in req["rows"]]})


def canonical(url: str) -> str:
    """The URL without its share parameters, so a re-run of the same album finds its request."""
    m = URL.search(url)
    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}" if m else url


def add_playlist(store, playlist_id: str | None, *, source: str, name: str) -> dict | None:
    """Record the import of playlist `playlist_id` as one `playlist` request (S2-07) and return it: its rows are the
    wanted rows of the playlist's last import (`import_order`), `track_no` None, `album` the playlist's name, which
    is the request's identity (the import finds its playlist by name; a file source is none). A row another request
    holds stays with it; this one holds its rows loosely (an album or track request asked for later takes those not
    going yet, CrateStore.takeable). Idempotent: the same name finds its request; a re-import's new rows join it and
    rows it no longer lists leave, unless they are going. None when no row would join a new request."""
    wanted = [o["wanted_id"] for o in store.import_order(playlist_id) if o["wanted_id"]] if playlist_id else []
    rid = store.find_playlist_request(name)
    if rid is None:
        if not any((store.external(w) or {}).get("request_id") is None for w in wanted):
            return None
        rid = store.add_request(kind="playlist", source=source, artist=None, album=name, year=None)
    store.attach_request(rid, wanted)
    store.detach_request(rid, keep=wanted)
    store.commit()
    return store.request(rid)


def add_spotify(store, url: str, *, fetch=fetch_entity, tier: str | None = None,
                default_tier: str = IMPORT_TIER, playlist_id: str | None = None) -> dict | None:
    """Record the album or track at `url` as one request and return it (`store.request(id)`). A playlist is a
    request only once imported: with `playlist_id` (the Navidrome playlist its import made) add_playlist records
    it; without, None.
    Idempotent: the same URL again finds its request by source, and add_external_wanted returns the rows already
    queued (a row queued earlier joins the request when it belongs to none). When every row already belongs to a
    request, that request answers (the first row's) and no empty one is made. An album listing the same artist and
    title twice gets one row for both (add_external_wanted's same-row rule)."""
    entity = fetch(url)
    kind = entity.get("type")
    if kind == "playlist" and playlist_id is not None:
        return add_playlist(store, playlist_id, source=canonical(url), name=entity["name"].strip())
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
        found = [store.find_external(lead_artist(r, resolve=None), r.title) for r in rows]
        if all(f and not store.takeable(f) for f in found):        # a playlist's loose hold is no hold (S2-07)
            return store.request(found[0]["request_id"])
    tracktotal = max((r.track_no for r in rows if r.track_no), default=None) if kind == "album" else None
    rid = rid or store.add_request(kind=kind, source=source, artist=artist, album=album, year=year,
                                   tracktotal=tracktotal)
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
