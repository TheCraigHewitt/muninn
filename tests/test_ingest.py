from muninn.ingest import ingest_source, review
from muninn.sources import Line, Source


def source(day, *rows, name="sync"):
    return Source("meeting", f"{name}-{day}.txt", name, day,
                  [Line(f"L{i + 1}", a, t) for i, (a, t) in enumerate(rows)])


def mem(type, statement, line, quote, conf=0.9, topic="Launch", **extra):
    return {"type": type, "statement": statement, "topic": topic, "confidence": conf, "confidence_reason": "r",
            "owner": "", "explains": "", "supersedes": "", "retold": False,
            "evidence": [{"id": line, "quote": quote}], **extra}


def extraction(*memories):
    return {"line_labels": [], "memories": list(memories)}


FIRST = source("2026-03-01", ("Ana", "We're going with a Friday launch."), ("Ana", "Because the press is ready."),
               ("Ben", "Ha, let's launch on the moon"))


def test_first_source_needs_no_reconciliation(fake, store):
    llm = fake(extract=[extraction(
        mem("decision", "Launch on Friday.", "L1", "going with a Friday launch"),
        mem("rationale", "The press is ready.", "L2", "the press is ready", explains="Launch on Friday."),
    )])
    report = ingest_source(llm, store, FIRST)
    assert report.created == 2 and [c[0] for c in llm.calls] == ["extract"]
    decision, = store.memories(type="decision")
    assert decision["status"] == "active" and decision["as_of"] == "2026-03-01"
    assert store.memory(decision["id"])["relations"][0]["kind"] == "explains"


def test_reingesting_the_same_conversation_is_free(fake, store):
    llm = fake(extract=[extraction()])
    ingest_source(llm, store, FIRST)
    assert ingest_source(llm, store, FIRST).skipped
    assert len(llm.calls) == 1


def test_uncited_and_unsure_candidates_never_reach_memory(fake, store):
    llm = fake(extract=[extraction(
        mem("decision", "Launch on the moon.", "L3", "not in the line"),
        mem("decision", "Launch Friday maybe.", "L1", "Friday launch", conf=0.7),
    )])
    report = ingest_source(llm, store, FIRST)
    assert len(report.rejected) == 1
    assert [m["status"] for m in store.memories()] == ["review"]


def seed(fake, store):
    ingest_source(fake(extract=[extraction(mem("decision", "Launch on Friday.", "L1", "Friday launch"))]), store, FIRST)
    return store.memories()[0]["id"]


def test_repeat_adds_evidence_instead_of_a_duplicate(fake, store):
    old = seed(fake, store)
    later = source("2026-03-08", ("Ana", "As agreed, Friday launch."))
    llm = fake(extract=[extraction(mem("decision", "Launch on Friday.", "L1", "Friday launch", retold=True))],
               reconcile=[{"results": [{"candidate": 0, "action": "same", "target": old, "topic": "Launch"}]}])
    report = ingest_source(llm, store, later)
    assert report.merged == 1 and len(store.memories()) == 1
    assert [e["role"] for e in store.memory(old)["evidence"]] == ["origin", "support"]


def test_reversal_supersedes_the_old_decision(fake, store):
    old = seed(fake, store)
    later = source("2026-03-08", ("Ana", "Change of plan, we're launching Monday instead."))
    llm = fake(extract=[extraction(mem("decision", "Launch on Monday.", "L1", "launching Monday"))],
               reconcile=[{"results": [{"candidate": 0, "action": "supersedes", "target": old, "topic": "Launch"}]}])
    ingest_source(llm, store, later)
    assert store.memory(old)["status"] == "superseded"
    new = store.memories(status="active")[0]
    assert new["statement"] == "Launch on Monday." and new["topic"] == "Launch"


def test_unsure_reversal_waits_for_a_person(fake, store):
    old = seed(fake, store)
    later = source("2026-03-08", ("Ana", "I guess Monday then?"))
    llm = fake(extract=[extraction(mem("decision", "Launch on Monday.", "L1", "Monday then", conf=0.7))],
               reconcile=[{"results": [{"candidate": 0, "action": "supersedes", "target": old, "topic": "Launch"}]}])
    ingest_source(llm, store, later)
    assert store.memory(old)["status"] == "active"
    pending, = store.memories(status="review")
    review(store, pending["id"], approve=True)
    assert store.memory(old)["status"] == "superseded"


def test_supersedes_across_types_becomes_a_conflict(fake, store):
    old = seed(fake, store)
    later = source("2026-03-08", ("Ana", "Marketing thinks Monday is better."))
    llm = fake(extract=[extraction(mem("proposal", "Launch on Monday.", "L1", "Monday is better"))],
               reconcile=[{"results": [{"candidate": 0, "action": "supersedes", "target": old, "topic": "Launch"}]}])
    ingest_source(llm, store, later)
    assert store.memory(old)["status"] == "active"
    assert store.memory(old)["relations"][0]["kind"] == "contradicts"


def test_rejecting_a_review_hides_it(fake, store):
    ingest_source(fake(extract=[extraction(mem("decision", "Launch Friday.", "L1", "Friday launch", conf=0.7))]), store, FIRST)
    pending, = store.memories(status="review")
    review(store, pending["id"], approve=False)
    assert store.memories() == []


def test_bot_channels_are_skipped(fake, store):
    bots = Source("slack", "alerts", "#alerts", "2026-03-01", [Line(f"L{i}", "pager [bot]", "down") for i in range(10)])
    assert ingest_source(fake(), store, bots).skipped == "almost entirely bot messages"
