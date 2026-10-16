"""Spotify/report playlist rows → Navidrome playlist + wanted rows (spec §2a, D11).

A row names a *song*; which version stands at that spot is the playlist's choice (spec Part 2). Matching:
search3 on artist+title words (Navidrome ignores case, accents and punctuation; every word must hit), then
`sourcing.identity` splits the row's and every hit's title into a base title and a version label, and three
questions are asked in order:
  1. same recording: the row's ISRC (Exportify) is among the hit's ISRCs, whatever the titles say;
  2. same version: the same version key (label kinds + credit; "original mix" is neutral). With a row length:
     hits within ±4 s whose base title fits; without one: the lead artist and the *same* base title;
  3. an accepted other version: the lead artist, the same base title, another key every kind of which the
     tier's policy accepts (deploy/policy.toml `accept`, D16: a 12" may stand in; a 12" Dub is a dub too).
     Matched, `how` names the label, and the report notes it, so a stand-in is never silent.
Otherwise the row is `ambiguous` (a review row): "other version" (the same song with a label the tier does not
accept), "length differs" (the same song at another length), "title differs" (no length; a title that only
*contains* the row's), "several versions" (more than one candidate version). A wrong match puts the wrong
version in a set; a missed one only queues a download, so every doubt stays a review row.
Noise that does not change the recording is identity's: file extension, track-number prefix, the artist's name
glued on, " - 2012 Remaster", "(feat. X)". Redundant copies (same base title and key, lengths within ±4 s)
collapse to one match. No hits at all → retry with the title words only, keeping hits that name the artist or
have no artist tag (library titles sometimes carry it: "A Change Is Gonna Come - Jennifer Lara").
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from crates import attrs
from crates.reconcile import CommentNotKept, Reconciler
from crates.store import CrateStore
from subsonic.client import Song, SubsonicClient
from .identity import Title, loose, parse_title, stands_in
from .playlist_sources import Row, lead_artist, track_lead
from .policy import IMPORT_TIER, TIERS

TOLERANCE_S = 4
MARKER = "#imported"          # in the playlist comment: "this playlist is managed by import-playlist"
PAGE = 20                     # Navidrome search3 page size we ask for; a full page means "ask for more"
MAX_PAGES = 5


class NameCollision(Exception):
    """A playlist with this name exists and was not created by import-playlist (pass merge=True to adopt it)."""

    def __init__(self, name: str, playlist_id: str):
        super().__init__(f"playlist {name!r} already exists ({playlist_id}) and is not marked {MARKER}")
        self.name, self.playlist_id = name, playlist_id


def _fold(s: str | None) -> str:
    """Case-, accent- and punctuation-insensitive, like Navidrome's search: letters/digits and spaces only.
    Mirrors Navidrome's search tokeniser, not identity (it drops "&"; identity makes it "and")."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s if not unicodedata.combining(ch)).casefold()


norm = loose                      # "is this the same text": identity owns it (accents and "&" included)


def query_words(*parts: str) -> list[str]:
    return [w for w in _fold(" ".join(parts)).split() if len(w) >= 2]


def build_query(row: Row) -> str:
    return " ".join(query_words(row.artist, row.title))


@dataclass
class Match:
    row: Row
    status: str                 # "matched" | "ambiguous" | "missing"
    song_id: str | None = None
    candidates: list[str] = field(default_factory=list)   # ids considered (ambiguous → the tie; matched → the copies)
    why: str | None = None      # ambiguous: "several versions" | "other version" | "title differs" | "length differs"
    how: str | None = None      # matched: "same recording" | "same version" | "other version: <hit's label>"
    title: str | None = None    # matched: the chosen hit's title (names a stand-in in the notes)
    note: str | None = None     # matched: a doubt the report must name (an ISRC match across different labels)


def _blob(h: Song) -> str:
    return norm(f"{h.artist} {h.title}")


def _untagged(artist: str | None) -> bool:
    """A file with no artist tag ("[Unknown Artist]", "Various") is no evidence against a match."""
    return norm(artist) in ("", "unknownartist", "various", "variousartists", "unknown")


def _title_fits(want: Title, hit: Song, got: Title) -> bool:
    """The row's base title appears in the hit, or the hit's in the row's ("Fascination" vs "Fascination
    Remix"). Guards the length strategy against artist-only queries."""
    t, h = loose(want.base), loose(got.base)
    return bool(t and h) and (t in norm(f"{hit.artist} {got.base}") or h in t)


def _lead(row: Row) -> str:
    return norm(lead_artist(row, resolve=None))          # never a network call while matching


def _artist_gate(hits: list[Song], lead: str) -> list[Song]:
    """For the title-only retry: the artist must still be there, unless the file has none."""
    return [h for h in hits if lead and (lead in _blob(h) or _untagged(h.artist))]


def _isrcs(h: Song) -> set[str]:
    """Navidrome (OpenSubsonic) sends `isrc` as a list; a single string is read too."""
    v = h.raw.get("isrc") or []
    return {x.strip().upper() for x in ([v] if isinstance(v, str) else v) if isinstance(x, str) and x.strip()}


def _by_length(row: Row, hits: list[Song], t: dict[str, Title], want: Title) -> list[Song]:
    def d(h: Song) -> int:
        return abs(h.duration - row.duration_s)
    fit = [h for h in hits if h.duration is not None and d(h) <= TOLERANCE_S and _title_fits(want, h, t[h.id])]
    if not fit:
        return []
    best = min(map(d, fit))
    return [h for h in fit if d(h) == best]


def _by_title(hits: list[Song], t: dict[str, Title], want: Title, lead: str) -> tuple[list[Song], list[Song]]:
    """(the same song, hits that only contain the row's base title) among hits that name the lead artist."""
    title = loose(want.base)
    named = [h for h in hits if title and lead and title in _blob(h) and lead in _blob(h)]
    same = [h for h in named if loose(t[h.id].base) == title]
    return same, [h for h in named if h not in same]


def _decide(row: Row, fit: list[Song], t: dict[str, Title], how: str) -> Match:
    durs = [h.duration for h in fit if h.duration is not None]
    # One base title and version key is a redundant copy only when the lengths agree too; "The Magician"
    # 353 s vs 300 s are two recordings, and without a row duration we cannot pick → ambiguous.
    # Parsed titles, not raw tags: "122 - Wendell Harrison - Peace Of Mind.mp3" is a copy too.
    if len({(loose(t[h.id].base), t[h.id].key) for h in fit}) > 1 or (durs and max(durs) - min(durs) > TOLERANCE_S):
        return Match(row, "ambiguous", candidates=[h.id for h in fit], why="several versions")
    # The cleanly tagged, properly filed copy first.
    fit.sort(key=lambda h: (norm(h.title) != norm(row.title), (h.path or "").startswith("Compilations/")))
    return Match(row, "matched", fit[0].id, [h.id for h in fit], how=how, title=fit[0].title)


def choose(row: Row, hits: list[Song], accept: frozenset[str] = frozenset()) -> Match:
    """Same recording → same version → an other version the tier accepts (`accept`: version kinds)."""
    if not hits:
        return Match(row, "missing")
    lead = _lead(row)
    lead_name = lead_artist(row, resolve=None)
    want = parse_title(row.title, lead_name)
    t = {h.id: parse_title(h.title, lead_name) for h in hits}
    if row.isrc:
        rec = [h for h in hits if row.isrc.strip().upper() in _isrcs(h)]
        if rec:
            m = _decide(row, rec, t, "same recording")
            if m.status == "matched" and t[m.song_id].key != want.key:     # library ISRC tags can be wrong
                m.note = (f"same recording by ISRC, but the labels differ: {t[m.song_id].label or 'no label'} vs "
                          f"{want.label or 'no label'}")
            return m
    same, near = _by_title(hits, t, want, lead)
    if row.duration_s is not None:
        fit = _by_length(row, [h for h in hits if t[h.id].key == want.key], t, want)
        if fit:
            return _decide(row, fit, t, "same version")
    else:
        fit = [h for h in same if t[h.id].key == want.key]
        if fit:
            return _decide(row, fit, t, "same version")
    # A stand-in must be the same song by the same artist: the same base title, never one that only fits; and
    # `identity.stands_in` (it keeps what the row asked for, everything it adds is accepted: a 12" Dub is a dub).
    other = [h for h in same if stands_in(t[h.id], want, accept)]
    if other:
        m = _decide(row, other, t, "other version")
        if m.status == "matched":
            m.how = f"other version: {t[m.song_id].label}"
        return m
    if row.duration_s is not None:
        if same or near:                                 # right song name, another length or label
            relabelled = any(t[h.id].key != want.key and h.duration is not None
                             and abs(h.duration - row.duration_s) <= TOLERANCE_S for h in same)
            return Match(row, "ambiguous", candidates=[h.id for h in same + near],
                         why="other version" if relabelled else "length differs")
    elif same:                                           # the same song, a label the tier does not accept
        return Match(row, "ambiguous", candidates=[h.id for h in same + near], why="other version")
    elif near:
        return Match(row, "ambiguous", candidates=[h.id for h in near], why="title differs")
    return Match(row, "missing", candidates=[h.id for h in hits])


def _search_all(client: SubsonicClient, query: str) -> list[Song]:
    """search3 pages: a full page of common words ("love") can hide the real hit past the first 20."""
    hits: list[Song] = []
    for page in range(MAX_PAGES):
        batch = client.search_songs(query, count=PAGE, offset=page * PAGE)
        hits.extend(batch)
        if len(batch) < PAGE:
            break
    return hits


def match(client: SubsonicClient, row: Row, accept: frozenset[str] = frozenset()) -> Match:
    query = build_query(row)
    if not query:                                        # nothing searchable: an empty search3 lists everything
        return Match(row, "missing")
    hits = _search_all(client, query)
    if not hits:
        title_only = " ".join(query_words(row.title))
        hits = _artist_gate(_search_all(client, title_only), _lead(row)) if title_only else []
    return choose(row, hits, accept)


@dataclass
class Report:
    name: str
    playlist_id: str | None
    created: bool
    matches: list[Match]
    added: int                  # entries appended this run (or that a dry run would append)
    kept: int = 0               # entries the existing playlist already had before this run
    notes: list[str] = field(default_factory=list)   # things Michael should know (unresolved artists …)

    def _count(self, status: str) -> int:
        return sum(1 for m in self.matches if m.status == status)

    @property
    def matched(self) -> int:
        return self._count("matched")

    @property
    def wanted(self) -> int:
        return self._count("missing")

    @property
    def ambiguous(self) -> int:
        return self._count("ambiguous")

    def table(self) -> str:
        lines = []
        for m in self.matches:
            tail = f"→ {m.song_id}" if m.song_id else (f"? {', '.join(m.candidates)}" if m.candidates else "")
            tail += f"  ({m.why})" if m.why else ""
            lines.append(f"{m.row.position:4d}  {m.status:<9}  {m.row.artist} — {m.row.title}  {tail}".rstrip())
        lines.append(f"{self.name}: {self.matched} matched, {self.wanted} wanted, {self.ambiguous} ambiguous"
                     + (f"; {self.added} added to playlist {self.playlist_id}" if self.playlist_id else ""))
        if self.playlist_id:
            lines.append(f"created playlist {self.name!r}" if self.created else
                         f"updated existing playlist {self.name!r}: {self.kept} entries were already there (kept, not reordered)")
        lines.extend(f"note: {n}" for n in self.notes)
        return "\n".join(lines)


def _rerun_comment(existing_comment: str | None, ours: bool, tier: str | None) -> str | None:
    """The comment a re-run writes, None to leave it alone: adopting (merge) appends MARKER; a given `tier`
    rewrites `#tier:` (D15: a plain re-run never changes the tier). Every other byte stays."""
    old = existing_comment or ""
    new = old if ours else old + ("" if not old or old.endswith("\n") else " ") + MARKER
    if tier is not None:
        new = attrs.write(new, tier=tier)
    return None if new == old else new


def _comment_kept(client: SubsonicClient, store: CrateStore, playlist_id: str, wrote: str) -> None:
    """D21: the comment owns #crate/#tier; read it back and only then cache what it says."""
    back = client.playlist(playlist_id)
    if (back.comment or "") != wrote:
        raise CommentNotKept(f"{back.name}: wrote comment {wrote!r} but Navidrome now has {back.comment or ''!r}")
    Reconciler(client, store).refresh_cache(back)


def import_playlist(name: str, rows: list[Row], client: SubsonicClient, store: CrateStore,
                    source: str, dry_run: bool = False, merge: bool = False, resolve=track_lead, tier: str | None = None) -> Report:
    """Create or update the playlist `name`: matched tracks in row order (appending only what is
    missing on a re-run, never removing), public; everything else becomes an external_wanted row
    that remembers the playlist and position. Ambiguous rows are parked as `verify` with the ids.

    A same-named playlist that this tool did not create (no `#imported` in its comment) raises
    NameCollision unless `merge=True`, which adopts it (adds the marker, leaves its visibility alone).

    The tier lives in the comment (D21): a created playlist gets `#imported #tier:<tier or IMPORT_TIER>`; a re-run
    rewrites `#tier:` only when `tier` is given. Without `tier`, a re-run matches and queues at the existing
    playlist's effective tier (its comment's #crate / #tier:), else IMPORT_TIER. A written comment is read back before crates.db caches it; if
    Navidrome did not keep it, the playlist edit and the wanted rows are still recorded, then CommentNotKept is
    raised with `.report` set."""
    existing = next((p for p in client.playlists() if p.name == name), None)
    at = tier or (existing and attrs.parse(existing.comment).effective) or IMPORT_TIER     # D21: the comment's tier
    accept = frozenset(TIERS[at].accept_versions)
    matches = [match(client, r, accept) for r in rows]
    ours = existing is not None and MARKER in (existing.comment or "")
    if existing is not None and not ours and not merge:
        raise NameCollision(name, existing.id)
    have = {e.id for e in client.playlist(existing.id).entries} if existing else set()
    added_before = store.imported(existing.id) if existing else set()
    present = have | added_before
    for m in matches:                    # a copy of this track is already there (or was, until Michael removed it)
        if m.status == "matched" and m.song_id not in present:
            m.song_id = next((i for i in m.candidates if i in present), m.song_id)
    ordered = list(dict.fromkeys(m.song_id for m in matches if m.status == "matched"))
    new_ids = [i for i in ordered if i not in present]          # a track Michael removed stays removed
    playlist_id = existing.id if existing else None
    # Resolve lead artists (may ask Spotify) before touching anything, so a failure leaves nothing half-written.
    failed = set()

    def _resolve(sid):
        got = resolve(sid)
        if not got:
            failed.add(sid)
        return got

    pending = [(m, lead_artist(m.row, resolve=_resolve)) for m in matches if m.status != "matched"]
    notes = [f"lead artist of {m.row.artist!r} could not be resolved; wanted row uses {lead!r}"
             for m, lead in pending if m.row.spotify_id in failed]
    notes += [f"matched with another version: {m.row.position} {m.row.artist} — {m.row.title} → {m.title}"
              for m in matches if (m.how or "").startswith("other version")]
    notes += [f"same recording by ISRC, but the labels differ: {m.row.position} {m.row.artist} — {m.row.title} → "
              f"{m.title}" for m in matches if m.note]
    if not dry_run:
        if existing is None:
            playlist_id = client.create_playlist(name, new_ids).id
            comment = attrs.write(MARKER, tier=tier or IMPORT_TIER)                # D15: the import tier, owned by the comment
            client.update_playlist(playlist_id, public=True, comment=comment)     # spec §2a: visible to every user
        else:                                       # visibility is set once, at creation: Michael may change it
            comment = _rerun_comment(existing.comment, ours, tier)
            client.update_playlist(existing.id, add_song_ids=new_ids, comment=comment)
        not_kept = None
        if comment is not None:
            try:
                _comment_kept(client, store, playlist_id, comment)
            except CommentNotKept as e:          # the songs are in: still record our own facts, then raise
                not_kept = e
        store.mark_imported(playlist_id, ordered)
        queued = {r["position"]: r for r in store.external_for_playlist(playlist_id)}
        for m in matches:                           # a wanted row whose track is now in the library is done
            r = queued.get(m.row.position)
            if m.status == "matched" and r and norm(r["title"]) == norm(m.row.title) and r["status"] in ("needs_source", "review", "failed"):
                store.set_external_status(r["song_id"], "ok", f"in library: {m.song_id}")
        for m, lead in pending:
            ext = store.add_external_wanted(lead, m.row.title, album=m.row.album, duration_s=m.row.duration_s,
                                            source=source, playlist_id=playlist_id, position=m.row.position, tier=tier,
                                            default_tier=at)
            if m.status == "ambiguous" and store.external(ext)["status"] in ("needs_source", "review"):
                store.set_external_status(ext, "review", f"ambiguous ({m.why}): " + ", ".join(m.candidates))
        store.commit()
    rep = Report(name, playlist_id, existing is None, matches, len(new_ids), len(have), notes)
    if not dry_run and not_kept is not None:
        not_kept.report = rep                    # what was done, for the CLI to print before the error
        raise not_kept
    return rep
