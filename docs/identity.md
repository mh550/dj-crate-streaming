# Songs, versions and copies

This is how the code decides what counts as "the same". The rules live in `sourcing/identity.py`. The design is in
`docs/specs/2026-10-16-ownership-and-identity.md` (Part 2).

## Three levels

| Level | What it is | Example from the library |
|---|---|---|
| **Song** | The artist's piece. Lead artist plus the title without version words. | Double Exposure, "My Love Is Free" |
| **Version** | One recording of a song: radio edit, 12", dub, live, a remix by someone. | "My Love Is Free" (the album cut) and "My Love Is Free (Tom Moulton 12" Mix)" |
| **Copy** | One file of a version. Copies differ only in quality: master, rip, encode. | A FLAC and a 320 kbps MP3 of the same 12" |

A cover by another artist is a different song. A remaster is a copy, not a version.

Two rules follow:
- A version has **at most one copy**. A better copy replaces the old one.
- A song can have **several versions**. A new version is added, never swapped in for another one.

## How a title is read

The title carries the version. The code peels decorations off the **end** of the title: `(...)`, `[...]` and
` - ...`. A decoration is a version label if it holds a version word. It is a copy marker if it is only a remaster
note, "Album Version" or "feat. X". Anything else stays in the song name.

| Title | Song | Version | Copy marker |
|---|---|---|---|
| `Good Times` (Chic) | Good Times | the plain version | |
| `Good Times (7in Edit)` | Good Times | edit | |
| `My Love Is Free (tom Moulton 12" Mix)` | My Love Is Free | extended, by Tom Moulton | |
| `Where You Are - Live` | Where You Are | live | |
| `Baby's Gone (Remastered 1999)` | Baby's Gone | the plain version | Remastered 1999 |
| `Mary Jane (All Night Long)` | Mary Jane (All Night Long) | the plain version | |
| `Downstairs - Alternate Take 21` | Downstairs | alternate, take 21 | |

Version words that are really part of the name are left alone: "In da Club", "Tropical Club", "All Night Long",
"Peace and Love Dub", "(They Long to Be) Close to You".

Details that matter:
- **12" has many spellings.** `12"`, `12''`, `12'`, `12”`, `12 Inch` and `12-Inch` all mean extended.
- **"Original Mix" is a label but counts for nothing in the comparison.** "Glide - Original Mix" is the same
  version as "Glide". It still counts when the policy prefers originals.
- **Clean, explicit, mono and stereo are versions.** "Clean Edit" is not "Edit". So are take numbers and years or places
  in a live or mix credit: "Take 21" is not "Take 22", "Live 1977" is not "Live 1979".
- **A `VERSION` or `TIT3` tag counts only when it reads as a label.** In the library 35 of 37 hold a year such as
  `2003`, which is ignored.
- **An en dash is not a separator.** None of the 831 titles has one.

## The same-version test

Two files are the same version when all of these hold:
1. They are the same song (same recording id, same work id, or same lead artist and base title).
2. Their version labels agree.
3. Their lengths are within 4 seconds.
4. They do not carry different recording ids.

A shared **work id decides only the song.** It never makes two versions one. A missed match leaves a duplicate,
which costs disk. A false match deletes a version, which costs music. So every doubt goes toward "different".

Real example: the library holds "Get Down Saturday Night (Original 12'' Version)" at 412 s. MusicBrainz has "(Get
Down in the 90's-mix)" at 403 s. They share a song, but the labels differ (extended against a named remix), so
they are two versions. beets called them one at 96.8%, which is why beets does not propose ids here.

On the live library the rules find **131 pairs of the same version in 102 groups**. Those are the copies M8 will
deal with. Mostly they differ only by a remaster note or "feat. X": "I Can't Tell You Why" and "I Can't Tell You
Why (2013 Remaster)", "Touch" and "Touch (feat. Paul Williams)".

## Where it is used

- **Import matching** asks three questions, in order: the same recording (ISRC)? The same version? Another version of
  the song that the tier accepts? The third is logged as "matched with another version", never silently.
- **Scoring** reads the labels from file names. The policy's `prefer` list adds points. A crate upgrade refuses
  another version outright.
- **Verify** is told whether a download is a copy upgrade or a new version (below).
- **Dedupe and the text comparisons** (`loose`, `words`) all fold text the same way now: accents ignored, `&` is "and".

## Stand-in versions

When a playlist row names a version the library lacks, the matcher may use another version of the song. That
needs the song to match and **every** version word to be on the tier's `accept` list. With `accept = ["extended"]`,
a "12" Version" or "Extended Mix" qualifies. A "12" Dub" does not: dub is not accepted, so the row goes to review.
See "Editing the policy" in `docs/worker.md`.

## Copy upgrades and `replaceable`

For an upgrade of an owned song, verify fingerprints the new file against the old one over the **full length**.
It reports `replaceable: true` only when all of these hold:
- the bit-error rate is at most 0.20;
- the two durations agree;
- they are different files;
- the verdict is `ok`.

If the reference is missing, `replaceable` is false and a `reference` warning is recorded. A truncated download
cannot pass, because the duration check catches it. M8 (copy replacement) will trash the old copy only when this
flag is true.

A **new version** is not compared with anything, because it is expected to differ. Its expected length is not
taken from the playlist row (that is the length of the version the row asked for). Truncation is still caught by
the decoded checks, and a download shorter than the peer listed is a hard failure.

## The id backfill

The tags own which recording a file is, but only 98 of 831 files carry a recording id. The backfill proposes the
rest, you review it, and only then does anything write. See "Identity backfill" in `docs/worker.md` for the
commands.

How a proposal is made, per file:
1. If the file has an ISRC, MusicBrainz is asked which recording has it.
2. If the file already has a recording id, MusicBrainz is asked whether it fits.
3. Otherwise MusicBrainz is searched by artist and base title. AcoustID is used only when `ACOUSTID_KEY` is set.

A recording fits only when the lead artists are equal, the base titles and version labels agree, it is not a video,
and the lengths agree within 4 seconds. A recording with no length never fits. MusicBrainz often has two recordings
at one length (about a third of the searches), and those rows are not guessed.

The report groups each file in one class:

| Class | Meaning | Written by default |
|---|---|---|
| `confirmed` | The file's own recording id is right and MusicBrainz agrees | only a missing work id |
| `isrc` | The file's ISRC leads to exactly one recording that fits | yes |
| `acoustid` | A confident AcoustID match (0.8 or more) singles out one fitting recording | yes |
| `search` | Exactly one recording fits by name and length | no, you ask for it |
| `ambiguous` | Several recordings fit. Candidates are listed | no, unless you set `"choose"` |
| `conflict` | The file's id does not fit, or two ids disagree, or it cannot be checked | no |
| `none` | Nothing fits. Near misses (everything but the lead artist) are listed for you | no, unless you set `"choose"` |
| `error` | The file could not be read or looked up | no |

The only fields ever written are the recording id, the work id and the AcoustID id, and only where the file's own
field is empty. A different existing id is never overwritten. Everything else in the file stays as it is. beets is
not involved.
