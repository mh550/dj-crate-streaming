"""scripts/snapshot-crates-db.sh: consistent copies of crates.db and navidrome.db (sqlite3 .backup + integrity check)."""
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("sqlite3") is None, reason="sqlite3 not on PATH")

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "snapshot-crates-db.sh"


def _wal_db(path, rows):
    """A WAL-mode database whose rows sit in the -wal file (no checkpoint), as live; the connection stays open."""
    conn = sqlite3.connect(path)
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma wal_autocheckpoint=0")
    conn.execute("create table t (x text)")
    conn.executemany("insert into t values (?)", [(r,) for r in rows])
    conn.commit()
    assert os.path.getsize(f"{path}-wal") > 0
    return conn


def _rows(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [r for (r,) in conn.execute("select x from t order by x")]
    finally:
        conn.close()


def _journal_mode(path):
    out = subprocess.run(["sqlite3", str(path), "pragma journal_mode"], capture_output=True, text=True)
    return out.stdout.strip()


def _integrity(path):
    out = subprocess.run(["sqlite3", str(path), "pragma integrity_check"], capture_output=True, text=True)
    return out.stdout.strip()


def _run(tmp_path, *args, crates=None, navidrome=None):
    env = {k: v for k, v in os.environ.items() if k not in ("CRATES_DB", "NAVIDROME_DB")}
    env["CRATES_DB"] = str(crates or tmp_path / "crates.db")
    env["NAVIDROME_DB"] = str(navidrome or tmp_path / "navidrome.db")
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60)


@pytest.fixture
def dbs(tmp_path):
    conns = [_wal_db(tmp_path / "crates.db", ["approval", "wanted"]), _wal_db(tmp_path / "navidrome.db", ["song"])]
    yield tmp_path / "crates.db", tmp_path / "navidrome.db"
    for c in conns:
        c.close()


def test_no_arguments_snapshots_both_databases_with_their_wal_contents(tmp_path, dbs):
    out = _run(tmp_path)
    assert out.returncode == 0, out.stderr
    for db, rows in ((tmp_path / "crates.db", ["approval", "wanted"]), (tmp_path / "navidrome.db", ["song"])):
        snap = Path(f"{db}.snap")
        assert _integrity(snap) == "ok"
        assert _rows(snap) == rows                       # the rows that sat only in the -wal file
        assert f"{snap} " in out.stdout and "integrity ok" in out.stdout
    assert out.stdout.count("\n") == 2
    for db in (tmp_path / "crates.db", tmp_path / "navidrome.db"):    # the live databases stay as they were
        assert _journal_mode(db) == "wal" and os.path.getsize(f"{db}-wal") > 0
    # each snapshot is one self-contained file: no -wal/-shm beside it, nothing half-written left over
    assert sorted(p.name for p in tmp_path.iterdir() if ".snap" in p.name) == ["crates.db.snap", "navidrome.db.snap"]


def test_suffix_writes_run_named_snapshots_and_leaves_the_nightly_ones_alone(tmp_path, dbs):
    assert _run(tmp_path).returncode == 0
    nightly = {p: p.read_bytes() for p in (tmp_path / "crates.db.snap", tmp_path / "navidrome.db.snap")}
    sqlite3.connect(tmp_path / "crates.db").execute("insert into t values ('later')").connection.commit()

    out = _run(tmp_path, "--suffix", "pre-x")
    assert out.returncode == 0, out.stderr
    assert _rows(tmp_path / "crates.db.pre-x.snap") == ["approval", "later", "wanted"]
    assert _rows(tmp_path / "navidrome.db.pre-x.snap") == ["song"]
    assert _integrity(tmp_path / "crates.db.pre-x.snap") == "ok"
    assert _integrity(tmp_path / "navidrome.db.pre-x.snap") == "ok"
    assert {p: p.read_bytes() for p in nightly} == nightly
    assert "crates.db.pre-x.snap" in out.stdout and "navidrome.db.pre-x.snap" in out.stdout


@pytest.mark.parametrize("args", [["--suffix"], ["--suffix", ""], ["--suffix", "a/b"], ["--suffix", "it's"], ["--suffix", "a b"], ["--suffix", "x", "extra"], ["--nope"]])
def test_bad_arguments_exit_2_and_write_nothing(tmp_path, dbs, args):
    out = _run(tmp_path, *args)
    assert out.returncode == 2
    assert "usage" in out.stderr
    assert not [p for p in tmp_path.iterdir() if ".snap" in p.name]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(["crates.db", "crates.db-wal", "crates.db-shm",
                                                                "navidrome.db", "navidrome.db-wal", "navidrome.db-shm"])


def _corrupt_page(db):
    """Zero one page in the middle of a valid database: .backup copies it, integrity_check catches it."""
    conn = sqlite3.connect(db)
    conn.execute("create table big (x text)")
    conn.execute("create index big_x on big (x)")
    conn.executemany("insert into big values (?)", [(f"row-{i:05d}-" + "x" * 50,) for i in range(3000)])
    conn.commit()
    conn.close()
    data = bytearray(db.read_bytes())
    page = 4096
    mid = (len(data) // page // 2) * page
    data[mid:mid + page] = bytes(page)
    db.write_bytes(bytes(data))


def _bad_garbage(path):
    path.write_bytes(b"this is not a database" * 200)


def _bad_unreadable(path):
    path.chmod(0)


def _bad_page(path):
    path.unlink()
    _corrupt_page(path)


@pytest.mark.parametrize("which", ["crates.db", "navidrome.db"])
@pytest.mark.parametrize("spoil", [_bad_garbage, _bad_unreadable, _bad_page], ids=["garbage", "unreadable", "bad-page"])
@pytest.mark.parametrize("suffix", [[], ["--suffix", "pre-x"]], ids=["nightly", "suffix"])
def test_a_bad_source_exits_1_and_replaces_no_snapshot(tmp_path, which, spoil, suffix):
    if spoil is _bad_unreadable and os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    for name in ("crates.db", "navidrome.db"):
        sqlite3.connect(tmp_path / name).execute("create table t (x text)").connection.close()
    end = ".".join(["", suffix[1], "snap"]) if suffix else ".snap"
    before = {}
    for name in ("crates.db", "navidrome.db"):
        p = tmp_path / f"{name}{end}"
        p.write_bytes(b"the previous snapshot of " + name.encode())
        before[p] = p.read_bytes()
    spoil(tmp_path / which)
    try:
        out = _run(tmp_path, *suffix)
    finally:
        (tmp_path / which).chmod(0o644)
    assert out.returncode == 1, (out.stdout, out.stderr)
    assert which in out.stderr
    assert {p: p.read_bytes() for p in before} == before
    assert sorted(p.name for p in tmp_path.iterdir() if ".snap" in p.name) == sorted(p.name for p in before)


def test_a_missing_crates_db_exits_1_and_creates_nothing(tmp_path, dbs):
    out = _run(tmp_path, crates=tmp_path / "gone.db")
    assert out.returncode == 1
    assert "gone.db" in out.stderr
    assert not (tmp_path / "gone.db").exists()                 # sqlite3 would have created an empty one
    assert not [p for p in tmp_path.iterdir() if ".snap" in p.name]


def test_a_missing_navidrome_db_snapshots_crates_db_only_with_a_one_line_note(tmp_path, dbs):
    missing = tmp_path / "nowhere" / "navidrome.db"
    out = _run(tmp_path, navidrome=missing)
    assert out.returncode == 0, out.stderr
    assert _rows(tmp_path / "crates.db.snap") == ["approval", "wanted"]
    assert not missing.exists() and not missing.parent.exists()
    notes = [line for line in out.stderr.splitlines() if str(missing) in line]
    assert len(notes) == 1 and "skipped" in notes[0]
    assert sorted(p.name for p in tmp_path.iterdir() if ".snap" in p.name) == ["crates.db.snap"]


def test_a_source_locked_for_a_moment_is_waited_for(tmp_path):
    """H1-04 review: .backup fails at the first SQLITE_BUSY unless the shell has a busy timeout."""
    import threading
    import time
    db = tmp_path / "crates.db"
    conn = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    conn.execute("create table t (x text)")
    conn.execute("insert into t values ('a')")
    conn.execute("begin exclusive")                    # rollback-journal mode: readers are locked out too
    unlock = threading.Timer(1.5, lambda: conn.execute("commit"))
    unlock.start()
    t0 = time.monotonic()
    p = _run(tmp_path)
    unlock.join()
    conn.close()
    assert p.returncode == 0, p.stderr
    assert time.monotonic() - t0 >= 1.0
    assert _rows(tmp_path / "crates.db.snap") == ["a"]
