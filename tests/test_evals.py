import pytest

from bruh.evals import check
from bruh.extract import Candidate, Extraction


def test_checks():
    c = Candidate("decision", "s", "t", 0.9, "r", [{"id": "L2", "quote": "q"}], supersedes="old")
    ex = Extraction([c], [], {"L1": "joking", "L2": "sincere"})
    results = check({"checks": [
        {"kind": "memory_from", "ids": ["L2"], "types": ["decision"]},
        {"kind": "memory_from", "ids": ["L2"], "types": ["fact"]},
        {"kind": "no_memory_from", "ids": ["L1"]},
        {"kind": "supersedes_from", "ids": ["L2"]},
        {"kind": "label", "ids": ["L1"], "sincerity": "joking"},
    ]}, ex)
    assert [r["ok"] for r in results] == [True, False, True, True, True]
    with pytest.raises(ValueError):
        check({"checks": [{"kind": "nope"}]}, ex)
