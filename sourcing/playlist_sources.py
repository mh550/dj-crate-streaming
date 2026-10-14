"""Playlist definitions from three places, one `Row` shape, Spotify order kept.

  1. Spotify playlist URL (public) — the embed page via `spotify_csv.fetch_entity`; 100-track cap.
  2. Exportify CSV (private / long playlists; Michael drops it in /srv/incoming/playlists/) or the
     `Artist,Title,Length` CSV that `spotify_csv` itself writes.
  3. SpotiFLAC download report `<name>.txt` (fixtures/spotiflac_report_*.head30.txt):
        [SUCCESS] Title - Artist; Artist2
        [SKIPPED] Title - Artist
        1. Title - Artist (Album)            ← numbered error entry, followed by indented lines
           Error: …
           ID: <spotify track id>
           URL: https://open.spotify.com/track/<id>
     Titles may contain " - " ("Catendé - Live - Vinícius de Moraes"); the artist is after the LAST one.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from .spotify_csv import URL as SPOTIFY_URL, _next_data, fetch_entity


@dataclass
class Row:
    position: int
    title: str
    artist: str
    duration_s: int | None
    spotify_id: str | None = None
    album: str | None = None
    note: str | None = None


def rows_from_spotify(entity: dict) -> list[Row]:
    out = []
    for i, t in enumerate(entity["trackList"], 1):
        artist = re.sub(r",\s*", ", ", t["subtitle"].replace("\xa0", " ")).strip()
        sid = t.get("uri", "").split(":")[-1] or None
        out.append(Row(i, t["title"].strip(), artist, round(t["duration"] / 1000), sid))
    return out


_STATUS = re.compile(r"^\[(SUCCESS|SKIPPED)\] (.*)$")
_ERROR = re.compile(r"^\d+\. (.*)$")


def _strip_album(body: str) -> tuple[str, str | None]:
    """'Title - Artist (Album)' → ('Title - Artist', 'Album'); the album may itself hold parentheses
    ("Reachin' (A New Refutation Of Time And Space)"), so walk back to the '(' that balances the final ')'."""
    if not body.endswith(")"):
        return body, None
    depth = 0
    for i in range(len(body) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(body[i], 0)
        if depth == 0:
            if i > 0 and body[i - 1] == " ":
                return body[: i - 1], body[i + 1:-1]
            break
    return body, None


def _split_title_artist(s: str) -> tuple[str, str]:
    title, _, artist = s.rpartition(" - ")
    return (title.strip(), artist.strip()) if title else (s.strip(), "")


def rows_from_report(text: str) -> list[Row]:
    rows: list[Row] = []
    for line in text.splitlines():
        m = _STATUS.match(line)
        if m:
            title, artist = _split_title_artist(m.group(2))
            rows.append(Row(len(rows) + 1, title, artist, None, note=m.group(1).lower()))
            continue
        m = _ERROR.match(line)
        if m:
            body, album = _strip_album(m.group(1))
            title, artist = _split_title_artist(body)
            rows.append(Row(len(rows) + 1, title, artist, None, album=album, note="error"))
            continue
        if rows and rows[-1].note and rows[-1].note.startswith("error") and line.startswith("   "):
            key, _, val = line.strip().partition(": ")
            if key == "Error":
                rows[-1].note = "error: " + val
            elif key == "ID":
                rows[-1].spotify_id = val
    return rows


def rows_from_csv(text: str) -> list[Row]:
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for i, r in enumerate(reader, 1):
        if "Track Name" in r:                                  # Exportify
            ms = r.get("Duration (ms)") or ""
            sid = (r.get("Track URI") or "").split(":")[-1] or None
            out.append(Row(i, r["Track Name"].strip(), (r.get("Artist Name(s)") or "").strip(),
                           round(int(ms) / 1000) if ms.isdigit() else None, sid, (r.get("Album Name") or None)))
        else:                                                  # sockseek / spotify_csv: Artist,Title,Length
            length = (r.get("Length") or "").strip()
            out.append(Row(i, r["Title"].strip(), r["Artist"].strip(), int(float(length)) if length else None))
    return out


def concat(groups: list[list[Row]]) -> list[Row]:
    out = []
    for g in groups:
        for r in g:
            out.append(Row(len(out) + 1, r.title, r.artist, r.duration_s, r.spotify_id, r.album, r.note))
    return out


def load(src: str, fetch=fetch_entity) -> tuple[str, list[Row]]:
    if SPOTIFY_URL.search(src):
        entity = fetch(src)
        return entity["name"].strip(), rows_from_spotify(entity)
    p = Path(src)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".csv":
        return p.stem, rows_from_csv(text)
    return p.stem, rows_from_report(text)


def _track_lead(spotify_id: str) -> str | None:
    try:
        return _next_data(f"track/{spotify_id}")["artists"][0]["name"]
    except (SystemExit, KeyError, IndexError, TypeError):
        return None


def lead_artist(row: Row, resolve=_track_lead) -> str:
    """Report rows separate artists with ';' so the first segment is exact (and a lone comma is part
    of the name). Spotify/Exportify join with ', ', which mangles 'Earth, Wind & Fire' — ask the
    track's own embed when we have its id."""
    if ";" in row.artist:
        return row.artist.split(";")[0].strip()
    if "," not in row.artist or row.note is not None:      # report rows use ';' between artists: a comma is part of one name
        return row.artist
    if row.spotify_id:
        got = resolve(row.spotify_id)
        if got:
            return got
    return row.artist.split(",")[0].strip()
