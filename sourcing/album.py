"""The album-first plan (spec S2-04): one album search's responses and a request's rows → which folder each row comes
from. Pure and without I/O, so it is tested on synthetic responses; the album job (S2-05) does the searching and
enqueueing.

Soulseek matches the whole path, so a search for "<artist> <album>" returns whole folders. Files are grouped by
(peer, directory); in each folder the scorer's per-file rules (S1-01's title-slot rejection included, policy D24) map
rows to files, each file serving at most one row, the highest score first.

- **primary**: the folder covering the most rows (all of them wins outright), then the summed score, then a free
  slot, then upload speed, then the summed bitrate (the scorer gives a lossless file's bitrate no points, so two
  copies of one rip differ only there), then peer and directory.
- **secondary**: the folder covering the most of the rows the primary lacks; between folders covering as many, the
  same release first: every track it shares with the primary within `LENGTH_TOLERANCE_S` of the primary's file (a
  track the primary lacks: of `listed_lengths`, the MusicBrainz release's lengths by track number), and the same
  format family (lossless or lossy); then the primary's order over those rows.
- A folder covering fewer than `MIN_FOLDER_ROWS` rows is not a folder source: its rows go per-track.
- **alternates**: the other folder sources, ranked like the primary, for a later switch (S2-05).

No peer name leaves this module in text: `describe` labels folders `folder 1`, `folder 2`, ... unless `peers=True`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .policy import DEFAULT_POLICY, QualityPolicy
from .scorer import Candidate, Wanted, rank

LENGTH_TOLERANCE_S = 2       # the same release: a shared track's length within this of the other listing
MIN_FOLDER_ROWS = 2          # a folder covering only one row is not a folder source


@dataclass
class FolderPick:
    username: str
    directory: str                                                     # "" for files at a share root
    rows: list[tuple[dict, Candidate]] = field(default_factory=list)   # in the order of the request's rows
    at: list[int] = field(default_factory=list, repr=False)            # each pair's index in the rows given

    @property
    def score(self) -> float:
        return round(sum(c.score for _, c in self.rows), 1)

    def rank_key(self) -> tuple:
        """Lower sorts first: more rows, a higher summed score, a free slot, a faster peer, a higher summed bitrate,
        then peer and directory (so a re-plan of the same responses picks the same folder)."""
        c = self.rows[0][1] if self.rows else None
        return (-len(self.rows), -self.score, not (c and c.has_free_slot), -(c.upload_speed if c else 0),
                -sum(c.bit_rate or 0 for _, c in self.rows), self.username, self.directory)

    def only(self, indices: set[int]) -> FolderPick:
        """This folder's pairs for those rows only."""
        keep = [k for k, i in enumerate(self.at) if i in indices]
        return FolderPick(self.username, self.directory, [self.rows[k] for k in keep], [self.at[k] for k in keep])


@dataclass
class AlbumPlan:
    primary: FolderPick | None
    secondary: FolderPick | None
    per_track: list[dict]                 # rows no folder serves, in the request's order
    alternates: list[FolderPick]          # ranked, without primary and secondary
    total: int = 0                        # the request's row count

    def assignments(self) -> list[tuple[dict, Candidate]]:
        """The planned files: the primary's rows, then the secondary's."""
        return [p for f in (self.primary, self.secondary) if f for p in f.rows]


def wanted(row: dict) -> Wanted:
    """A request row (a wanted_row dict) as the scorer's Wanted, as sourcing.fetch builds it."""
    return Wanted(row.get("artist") or "", row["title"], row.get("album"), row.get("duration"), row.get("year"))


def folder_of(filename: str) -> str:
    """A remote file's directory, as folders are grouped: everything before the last separator ("" at a share root)."""
    return re.split(r"[\\/](?=[^\\/]*$)", filename)[0] if re.search(r"[\\/]", filename) else ""


def _folders(responses: list[dict]) -> dict[tuple[str, str], dict]:
    """(peer, directory) → one response holding only that directory's files, its fileCount theirs (the scorer's
    "album?" bonus); the peer's slot and speed from its first response."""
    out: dict[tuple[str, str], dict] = {}
    for r in responses:
        for f in r.get("files", []):
            key = (r.get("username", "?"), folder_of(f.get("filename", "")))
            out.setdefault(key, dict(r, files=[]))["files"].append(f)
    for r in out.values():
        r["fileCount"] = len(r["files"])
    return out


def _map(peer: str, directory: str, response: dict, rows: list[dict], policy: QualityPolicy) -> FolderPick:
    """Rows to this folder's files: every accepted (row, file) pair, the highest score first, each row and each file
    used once."""
    pairs = [(c.score, i, j, c) for i, row in enumerate(rows)
             for j, c in enumerate(rank([response], wanted(row), policy)) if c.rejected is None]
    taken_rows: dict[int, Candidate] = {}
    taken_files: set[str] = set()
    for _, i, _, c in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
        if i not in taken_rows and c.filename not in taken_files:
            taken_rows[i] = c
            taken_files.add(c.filename)
    at = sorted(taken_rows)
    return FolderPick(peer, directory, [(rows[i], taken_rows[i]) for i in at], at)


def _family(c: Candidate, policy: QualityPolicy) -> bool:
    return policy.is_lossless(c.extension or c.basename.rsplit(".", 1)[-1])


def _other_release(f: FolderPick, primary: FolderPick, listed_lengths: dict[int, float] | None,
                   policy: QualityPolicy) -> bool:
    """True when `f` shows itself another release than the primary: a format family the primary lacks, or a track
    length more than LENGTH_TOLERANCE_S off the primary's file of that row (or the listed length). A file without a
    length shows nothing."""
    if {_family(c, policy) for _, c in f.rows} - {_family(c, policy) for _, c in primary.rows}:
        return True
    theirs = {i: c for i, (_, c) in zip(primary.at, primary.rows)}
    for i, (row, c) in zip(f.at, f.rows):
        ref = theirs[i].length_s if i in theirs else (listed_lengths or {}).get(row.get("track_no"))
        if ref is not None and c.length_s is not None and abs(c.length_s - ref) > LENGTH_TOLERANCE_S:
            return True
    return False


def _unlike(f: FolderPick, like: dict[int, float]) -> bool:
    """A length of `f`'s more than LENGTH_TOLERANCE_S off `like`'s for that track number (a file without one shows
    nothing)."""
    return any(c.length_s is not None and like.get(row.get("track_no")) is not None
               and abs(c.length_s - like[row["track_no"]]) > LENGTH_TOLERANCE_S for row, c in f.rows)


def plan_album(responses: list[dict], rows: list[dict], *, policy: QualityPolicy = DEFAULT_POLICY,
               listed_lengths: dict[int, float] | None = None,
               exclude: set[tuple[str, str]] = frozenset(), like: dict[int, float] | None = None,
               min_rows: int = MIN_FOLDER_ROWS) -> AlbumPlan:
    """The album-first plan for `rows` (the request's live rows) over one album search's `responses`.
    `listed_lengths`: track number → seconds of the matched MusicBrainz release, when known. A switch (S2-05b)
    passes `exclude`, (peer, directory) folders never planned (the failed ones), `like`, track number → seconds of
    the release the job has been filing (a folder matching it ranks first after coverage), and `min_rows=1` (one
    row may switch to a folder)."""
    folders = [_map(peer, directory, response, rows, policy)
               for (peer, directory), response in _folders(responses).items() if (peer, directory) not in exclude]
    folders = [f for f in folders if len(f.rows) >= min_rows]
    folders.sort(key=(lambda f: f.rank_key()[:1] + (_unlike(f, like),) + f.rank_key()[1:]) if like
                 else FolderPick.rank_key)
    primary = folders[0] if folders else None
    rest = folders[1:]
    secondary = None
    if primary:
        lacks = set(range(len(rows))) - set(primary.at)
        options = [(f, f.only(lacks)) for f in rest]
        options = [(m.rank_key()[:1] + (_other_release(f, primary, listed_lengths, policy),) + m.rank_key()[1:], f, m)
                   for f, m in options if len(m.rows) >= min_rows]
        if options:
            _, chosen, secondary = min(options, key=lambda o: o[0])
            rest = [f for f in rest if f is not chosen]
    served = set(primary.at if primary else []) | set(secondary.at if secondary else [])
    return AlbumPlan(primary, secondary, [r for i, r in enumerate(rows) if i not in served], rest, total=len(rows))


def describe(plan: AlbumPlan, peers: bool = False) -> str:
    """The plan as text: each folder as `folder N` (its peer only with peers=True), its coverage and each row's file;
    then the rows going per-track and the alternates."""
    lines = []
    picks = [("", plan.primary), ("secondary ", plan.secondary)] if plan.primary else []
    picks += [("alternate ", f) for f in plan.alternates]
    for n, (role, f) in enumerate((p for p in picks if p[1]), 1):
        who = f" ({f.username})" if peers else ""
        lines.append(f"{role}folder {n}{who}: {len(f.rows)} of {plan.total}, score {f.score:.1f}")
        if role != "alternate ":
            lines += [f"  {row.get('track_no') or '-'}. {row['title']} → {c.basename}" for row, c in f.rows]
    if plan.per_track:
        lines.append(f"per track: {len(plan.per_track)} of {plan.total}")
        lines += [f"  {row.get('track_no') or '-'}. {row['title']}" for row in plan.per_track]
    return "\n".join(lines)
