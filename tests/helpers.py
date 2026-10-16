"""Shared test helpers (plain functions, no pytest fixtures)."""
import json
import os
import shutil
import sqlite3
import struct
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Callable

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load_responses() -> list[dict]:
    """The slskd-shaped search responses fixture; [0]["files"][0] is vinylhead77's Good Times FLAC."""
    return json.loads((FIXTURES / "search_responses.sample.json").read_text())


def make_flac(path: Path, sr=44100, bps=16, ch=2, total=44100 * 300, pad_bytes=0) -> Path:
    """Minimal FLAC: marker + STREAMINFO block (last) with a fake sample count; no frames.
    `pad_bytes` of zeros stand in for the audio so size-based checks (fake-lossless) work."""
    bits = (sr << 44) | ((ch - 1) << 41) | ((bps - 1) << 36) | total
    si = struct.pack(">HH", 4096, 4096) + b"\x00\x00\x00" * 2 + bits.to_bytes(8, "big") + b"\x00" * 16
    hdr = bytes([0x80 | 0]) + len(si).to_bytes(3, "big")
    path.write_bytes(b"fLaC" + hdr + si + b"\x00" * pad_bytes)
    return path


def convert(src: Path, dst: Path, *args) -> Path:
    """ffmpeg src → dst with extra output args (e.g. '-b:a', '128k')."""
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *args, str(dst)], check=True)
    return dst


def make_audio(path: Path, *, seconds=8, seed=42, rate=44100, sample_fmt="s16", bits=None, color="white",
               af=None, lead_silence=0, via_mp3_kbps=None) -> Path:
    """Real audio from seeded noise (spec §3a: no binary fixtures). `via_mp3_kbps` round-trips through a lossy
    mp3 first (a 'fake' lossless file); `lead_silence` prepends that many seconds of digital silence; `af`
    is an extra ffmpeg filter (e.g. 'volume=20dB' to clip). Every stage is forced to `sample_fmt`, because a
    bare anullsrc concat negotiates down to 8-bit."""
    import subprocess
    src = f"anoisesrc=d={seconds}:c={color}:r={rate}:a=0.3:s={seed}"
    if af:
        src += f",{af}"
    tmp = path.with_suffix(".src.mp3") if via_mp3_kbps else None
    if tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-ac", "2", "-b:a", f"{via_mp3_kbps}k",
                        str(tmp)], check=True)
    inputs = ["-i", str(tmp)] if tmp else ["-f", "lavfi", "-i", src]
    graph = f"[0]aformat=sample_fmts={sample_fmt}:channel_layouts=stereo[m]"
    if lead_silence:
        inputs = ["-f", "lavfi", "-i", f"anullsrc=r={rate}:cl=stereo:d={lead_silence}"] + inputs
        graph = (f"[0]aformat=sample_fmts={sample_fmt}[s];[1]aformat=sample_fmts={sample_fmt}:channel_layouts=stereo[n];"
                 f"[s][n]concat=n=2:v=0:a=1[m]")
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[m]", "-ac", "2", "-ar", str(rate)]
    if bits:
        cmd += ["-bits_per_raw_sample", str(bits)]
    subprocess.run(cmd + [str(path)], check=True)
    if tmp:
        tmp.unlink()
    return path


def beets_items_db(path: Path) -> Path:
    """An empty beets library.db with just the `items` columns the filer reads, with the real column types
    (measured on beets 1.6.0: path is a BLOB)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, path BLOB, mb_trackid TEXT, artist TEXT, title TEXT)")
    return path


def fake_beet(music: Path, library: Path, target_rel: str, *, artist="", title="", mb_trackid="",
              matched=False, import_nothing=False, rc=0) -> Callable:
    """A subprocess.run stand-in for `beet`. Every cmd lands in `.calls`. On `import` it moves the single
    file in cmd[-1] to music/target_rel, adds an `items` row and writes this call's -l log the way beets
    1.6.0 does (appending): `asis <src>` for an as-is import, nothing for an applied match, `duplicate-skip <src>` (and
    no move) with `import_nothing`."""
    def run(cmd, **kwargs):
        run.calls.append(list(cmd))
        if "import" in cmd and not rc:
            src = next(p for p in Path(cmd[-1]).iterdir() if p.is_file())
            log = Path(cmd[cmd.index("-l") + 1])
            if import_nothing:
                with log.open("a") as fh:              # beets' FileHandler appends
                    fh.write(f"duplicate-skip {src}\n")
            else:
                dst = music / target_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(src, dst)
                with closing(sqlite3.connect(library)) as db, db:
                    db.execute("INSERT INTO items(path, mb_trackid, artist, title) VALUES (?, ?, ?, ?)",
                               (os.fsencode(dst.absolute()), mb_trackid, artist, title))
                with log.open("a") as fh:
                    fh.write("" if matched else f"asis {src}\n")
        return subprocess.CompletedProcess(cmd, rc, "", "boom" if rc else "")
    run.calls = []
    return run
