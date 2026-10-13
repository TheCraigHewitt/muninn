from bruh.extract import ACTIVE_AT, Candidate, check
from bruh.sources import UNKNOWN_SPEAKER, Line


def lines(*rows):
    return {f"L{i + 1}": Line(f"L{i + 1}", author, text) for i, (author, text) in enumerate(rows)}


def cand(type="decision", conf=0.9, evidence=None):
    return Candidate(type, "We ship Friday.", "Launch", conf, "clear", evidence or [{"id": "L1", "quote": "ship Friday"}])


def test_good_citation_passes():
    assert check(cand(), lines(("Ana", "We ship Friday, agreed.")), {"L1": "sincere"}) == []


def test_quote_must_be_verbatim():
    assert "quote is not verbatim" in check(cand(), lines(("Ana", "We ship on Friday")), {})[0]


def test_cannot_cite_a_joke():
    assert "joking" in check(cand(), lines(("Ana", "sure, ship Friday lol")), {"L1": "joking"})[0]


def test_bots_cannot_decide():
    problems = check(cand(), lines(("ci [bot]", "ship Friday")), {})
    assert "a bot can't decide or commit" in problems[0]


def test_low_confidence_is_dropped():
    assert "below" in check(cand(conf=0.4), lines(("Ana", "ship Friday")), {})[0]


def test_unknown_speaker_decision_needs_review():
    c = cand(conf=0.95)
    assert check(c, lines((UNKNOWN_SPEAKER, "ship Friday")), {}) == []
    assert c.confidence < ACTIVE_AT and c.needs_review
