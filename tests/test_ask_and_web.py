from fastapi.testclient import TestClient

from muninn.ask import ask
from muninn.ingest import ingest_source
from muninn.web.app import create_app
from test_ingest import FIRST, extraction, mem


def seeded(fake, store, answer):
    ingest_source(fake(extract=[extraction(mem("decision", "Launch on Friday.", "L1", "Friday launch"))]), store, FIRST)
    return fake(ask=[answer])


def test_answer_keeps_only_real_citations(fake, store):
    llm = seeded(fake, store, {"answer": "Friday [M1]. Also the moon [M99].", "cited": [1, 99]})
    result = ask(llm, store, "When do we launch?")
    assert result["answer"] == "Friday [M1]. Also the moon ."
    assert [m["id"] for m in result["memories"]] == [1]
    assert result["memories"][0]["evidence"][0]["quote"] == "Friday launch"


def test_empty_memory_says_so(fake, store):
    assert "doesn't remember anything" in ask(fake(), store, "anything?")["answer"]


def test_web_api(fake, store):
    llm = seeded(fake, store, {"answer": "Friday [M1].", "cited": [1]})
    web = TestClient(create_app(store, llm))
    assert "muninn" in web.get("/").text
    assert web.get("/api/stats").json()["decisions"] == 1
    assert web.get("/api/memories?type=decision").json()[0]["statement"] == "Launch on Friday."
    assert web.get("/api/memories?q=nothing-matches").json() == []
    topic = web.get("/api/topics").json()[0]
    assert web.get(f"/api/topics/{topic['id']}").json()["memories"][0]["id"] == 1
    src = web.get("/api/sources/1").json()
    assert src["lines"][0]["memories"] == [1]
    assert web.post("/api/ask", json={"question": "When?"}).json()["memories"][0]["id"] == 1
    assert web.post("/api/memories/1/review", json={"approve": True}).status_code == 409
    assert web.get("/api/memories/42").status_code == 404
