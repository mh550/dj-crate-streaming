# Download validation: what careful Soulseek users check, and what the code does for you

A file on Soulseek is whatever someone says it is. The file name says "FLAC", "24-bit" or "320", but the audio
inside may be a 128 kbps mp3 re-encoded as FLAC, a CD padded out to 24 bits, a rip cut off halfway, or a
different recording that shares the title. Careful downloaders check every file by hand before it goes into
their library. `sourcing/verify.py` does the same checks by code, and every download `fetch` makes goes
through it at the wanted row's tier. One exception: `fetch` doesn't yet pass the library copy as a reference, so
the right-recording check only runs from the CLI with `--reference` (it needs the real library path, which M6's
beets filing provides).

## What people do by hand

1. **Look at a spectrogram** (Spek, Audacity). Real CD audio has energy up to about 20 kHz. Lossy encoders cut
   everything above a fixed frequency, so a "FLAC" made from an mp3 shows a flat shelf: at about 16 kHz for 128 kbps,
   about 19 kHz for 192–256 kbps, and about 20 kHz for 320 kbps. This is the most common lie, and the main reason
   people open Spek.
2. **`flac -t file.flac`.** A FLAC stores an MD5 of its decoded audio, and `flac -t` checks it. That catches
   corrupt and truncated downloads.
3. **Compare the length** with Discogs or MusicBrainz. A radio edit, an extended mix and a live take of the
   same title differ by seconds or minutes.
4. **Listen to the first and last seconds.** People listen for a cut-off ending, a long silence, the wrong song,
   or a DJ tag spoken over the intro.
5. **Check the bit depth.** A 24-bit file whose lowest 8 bits are always zero is a 16-bit file in disguise. The
   same goes for a 96 kHz file with nothing above 22 kHz, which was upsampled from a CD.
6. **Check the tags and cover art.** Is the artist and title right, and is a cover embedded or next to the file?

## What the code does

`python3 -m sourcing.cli verify <file> --tier crate [--duration S] [--reference library-copy.flac]` runs on the
host, where `ffmpeg`, `flac` and `fpcalc` are installed. The crates container doesn't have these tools, so a
check run there warns that it skipped the audio checks. The command decodes the file once, which takes about
6 s for a 5-minute track, and reports the following:

| You'd do by hand | The code | Hard fail when |
|---|---|---|
| Spectrogram (Spek) | The energy above 11, 13, 15, 16, 17, 18, 19 and 20 kHz, compared with the whole signal. Music fades out gradually, but an encoder's cutoff shows as a **sudden drop of 15 dB or more** between two neighbouring bands. The estimated cutoff is the last band before that drop. | `crate`, and the file claims lossless or ≥320 kbps, but the cutoff is ≤16 kHz (it came from ≤128 kbps). A cutoff of 17–18 kHz is a warning only ("may come from ≤192 kbps"). |
| `flac -t` | `flac -t` (the authority for FLAC) plus a full ffmpeg decode. ffmpeg also complains about things that don't affect the audio, such as a webp cover (69 of the 534 pictures in your library), an odd ID3 frame or one junk mp3 frame. A few complaints are a warning; 10 or more, audio that won't decode, or digital silence fail. | Every tier |
| Length vs MusicBrainz | Within ±4 s of the length on the wanted record (from Spotify or MusicBrainz) | Every tier |
| Cut-off ending | The length in the header compared with the length that actually decodes | Every tier (more than 1 s missing) |
| First/last seconds | Silence longer than 3 s at the start or end (quieter than −60 dB) | Never: a warning |
| Wrong recording | A fingerprint of the audio (`fpcalc`, AcoustID's tool) compared with a reference copy, e.g. the library file being upgraded. The same audio, even through an mp3, scores about 0.01, and different songs about 0.47. | Every tier, when a reference is given and the score is over 0.20 |
| Bit depth | The bits the audio actually uses, compared with the bits the header claims | `crate` (24-bit claimed, 16 used); a warning otherwise |
| Fake hi-res | The bands above 22 and 24 kHz for files at 88.2 kHz and up | `crate` (nothing above ~22 kHz); a warning otherwise |
| Clipping | Peak at 0 dBFS with a "flat factor" ≥ 1 (runs of samples stuck at full scale) | Never: a warning. Loud modern masters often clip. |
| Tags and art | Not checked here. beets rewrites tags when it files the download (M6). | — |

**Tiers** (spec §1) decide how strict this is. `low`, `medium` and `high` are for listening. There, only a broken,
short, truncated or wrong file is rejected, and a lossy-sourced or padded file is accepted with a warning,
because it's still fine to listen to. `crate` is for files that go on real systems, so anything that isn't the
quality it claims is rejected too.

Without `--tier`, `verify` only reads the header (length, sample rate, and for FLAC the bitrate implied by the
file size). That is what `fetch` did before M5.

## Reading the result

```
BAD  /srv/incoming/…/03 - Good Times.flac  (tier crate)
     flac 44100 Hz / 16 bit / 2 ch / 501.0 s  [flac-streaminfo]
     · cutoff ≈16 kHz
     · band dB vs full: >11k -24.8  >13k -26.7  >15k -30.4  >16k -35.0  >17k -82.7  >18k -84.7 …
     · decoded 501.0 s · bits used 16 · peak -9.31 dBFS · flat factor 0.0
     ✗ cutoff ≈16 kHz (energy stops above 16 kHz) for a lossless file: lossless or 320 kbps reaches 19–20 kHz, so this likely came from ≤128 kbps
```

The drop from −35 to −83 dB between 16 and 17 kHz is the shelf you would see in Spek. `✗` lines are hard
problems: `fetch` deletes its own download and marks the row `failed`. `!` lines are warnings. Either way, the
web client shows the last check under the wanted row.

## What it found in your library (10 random FLACs, 2026-10-15)

Nine of the ten reach 20 kHz, including recordings from 1973, 1978 and 1979, so old masters do not trip the check.
One, Mobb Deep's "Shook Ones, Pt. II", drops 15 dB above 18 kHz. That suggests the FLAC was made from a lossy file
(common for 90s hip-hop on Soulseek). It's a warning, not a failure. Three loud masters show clipping warnings.
The full table is in the OVERNIGHT-2 status log.

The whole library was then checked: **22 of 831 files fail `crate`**. Two are broken FLACs, two are damaged mp3s, one
is a 32 kHz mp3, and 17 are FLACs or "320" mp3s made from ~128 kbps sources. See `docs/library-verify-2026-10-15.md`;
these are upgrade candidates.

## Limits

- Some lossy encoders, and some mp3s made with unusual settings, have no sharp cutoff, so the spectrum check can
  miss them. Some genuine recordings have a lowpass of their own, such as a 1990s sampler, a cassette master, or
  a FLAC mastered from DAT at 32 kHz. These show up as the 17–18 kHz warning, and you decide.
- The recording check needs a reference copy. A lookup in the public AcoustID database needs a free API key
  (see Needs Michael in the runbook).
- The checks run where the tools are, on the host. Downloads are filed from the host anyway, because `fetch
  --approve` refuses to run inside the crates container.
