# Library check at `crate`, 2026-10-15

`sourcing.cli verify <file> --tier crate` over all 831 files in `/srv/music` (520 FLAC, 267 mp3, 42 m4a,
2 wav). The run was read-only and took about 75 minutes on the host. No file crashed the checker.

**22 files fail `crate`.** They still play, and nothing was moved or changed. These are the files to
replace when a better copy turns up: Soulseek re-encodes and broken downloads that came in with the
original import.

| Why | Files |
|---|---|
| **Broken FLAC** (`flac -t` fails; the audio stops early) | M-Beat ft. General Levy, "Incredible (Phibes Remix)" (stops at 307 s of 319 s) · `_/Singles/00 -.1.flac` (stops at 89 s of 185 s) |
| **Damaged / cut mp3** | George Benson, "Turn Your Love Around" (*Collection*, 32 bad frames) · *Le Top De La Disco*, "Don't You Worry 'Bout a Thing" (2.7 s short) |
| **FLAC made from a lossy file** (energy stops at 11–15 kHz) | Cali Life Style, "Get Higher" (13) · American Gypsy, "Don't Give Up" (13) · Gino Soccio, "So Lonely" ×2 (13; the 320 mp3 copy is the same) · William DeVaughn, "Figures Can't Calculate" (15) · George Benson, "Give Me the Night" (15) · Dawn Penn, "Chilling" (*Vintage 2*, 15) · Wendell Harrison, "Winter" (11) · Huey Daze, "Bishopgate Jewel Case" (15) |
| **"320 kbps" mp3 made from ~128 kbps** (energy stops at 13–15 kHz) | Gino Soccio, "So Lonely" · Ruby Rushton, "Together at Last" · Elements Of Life et al. (djsoundtop) · Robert Palmer, "Sneakin' Sally Through the Alley" · Dawn Penn, "Chilling" (*Come Again*) · O'Donel Levy, "Freedom and Good Times" · Kleeer, "It's Magic" |
| **Low sample rate** | Lynda Dawn, "Arise" (32 kHz mp3) |
| **FLAC smaller than real FLAC usually is** | Davishmar, "a rose blooms in chaos" (435 kbps; energy stops ≈18 kHz, so likely lossy-sourced too) |

**Warnings only (these pass):**

| Warning | Count | What it means |
|---|---|---|
| Silence over 3 s at the start or end | 180 | Mostly hidden tracks and long fades |
| Clipping | 83 | Loud masters |
| ffmpeg complained about metadata | 67 | Mostly webp covers |
| Cutoff 17–18 kHz on a lossless or 320 kbps file | 12 | "May come from ≤192 kbps"; e.g. Mobb Deep, "Shook Ones, Pt. II" |
| Low FLAC bitrate but a full spectrum | 9 | Quiet or sparse music |

**Cutoffs:** FLAC: 460 reach 20 kHz, the 34 hi-res files reach 24 kHz, 13 reach 19 kHz, and 4 sit at 18 kHz.
mp3: 157 reach 19–20 kHz, and the rest show their encoder's lowpass.

The sweep also found a bug, fixed before this report. When ffprobe *estimates* an mp3's length from its
bitrate (a VBR file without a length header, or one with big cover art), that estimate was being trusted.
It made 4 good mp3s look truncated. The decoded length now decides.
