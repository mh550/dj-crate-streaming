"""Python 3.10 is the floor (CLAUDE.md). Since 3.12 (PEP 701) a string inside an f-string may reuse the f-string's
own quote; 3.10 and 3.11 refuse to import such a file, and ast.parse(feature_version=(3, 10)) does not notice."""
import sys
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="needs 3.12's f-string tokens")


def _quote(text):
    s = text.lstrip("rRbBuUfF")
    return s[:3] if s[:3] in ('"""', "'''") else s[:1]


def _clash(outer, inner):
    return inner == outer or (len(outer) == 1 and inner[0] == outer)


def reused_quotes(path):
    """(line, text) of each string or f-string inside an f-string that uses an enclosing f-string's quote."""
    found, enclosing = [], []
    with tokenize.open(path) as f:
        for tok in tokenize.generate_tokens(f.readline):
            if tok.type in (tokenize.STRING, tokenize.FSTRING_START):
                q = _quote(tok.string)
                if any(_clash(outer, q) for outer in enclosing):
                    found.append((tok.start[0], tok.line.strip()))
                if tok.type == tokenize.FSTRING_START:
                    enclosing.append(q)
            elif tok.type == tokenize.FSTRING_END:
                enclosing.pop()
    return found


def test_the_check_sees_a_reused_quote_and_allows_the_310_forms(tmp_path):
    src = tmp_path / "x.py"
    src.write_text("a = f\"{x or \"b\"}\"\n"
                   "b = f\"{x or 'b'}\"\n"
                   "c = f'''{x or \"b\"}'''\n"
                   "d = f\"{f'{y}'}\"\n")
    assert [line for line, _ in reused_quotes(src)] == [1]


def test_no_f_string_reuses_its_own_quote():
    files = [p for p in REPO.rglob("*.py") if ".git" not in p.parts]
    bad = [f"{p.relative_to(REPO)}:{line}: {text}" for p in files for line, text in reused_quotes(p)]
    assert bad == []
