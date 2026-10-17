"""The web app: a JSON API over the store, and one page that uses it."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..ask import ask
from ..ingest import review
from ..llm import LLM
from ..store import Store

PAGE = Path(__file__).parent / "index.html"


class Question(BaseModel):
    question: str


class Ruling(BaseModel):
    approve: bool


def create_app(store: Store, llm: LLM) -> FastAPI:
    app = FastAPI(title="Muninn", docs_url=None, redoc_url=None)

    @app.get("/", include_in_schema=False)
    def page():
        return FileResponse(PAGE)

    @app.get("/api/stats")
    def stats():
        return store.stats()

    @app.post("/api/ask")
    def answer(q: Question):
        if not q.question.strip():
            raise HTTPException(400, "ask a question")
        return ask(llm, store, q.question.strip())

    @app.get("/api/memories")
    def memories(type: str | None = None, status: str | None = None, topic_id: int | None = None, q: str = ""):
        rows = store.memories(type=type, status=status, topic_id=topic_id)
        if q:
            needle = q.lower()
            rows = [m for m in rows if needle in f"{m['statement']} {m['topic']} {m['owner']}".lower()]
        return rows

    @app.get("/api/memories/{memory_id}")
    def memory(memory_id: int):
        found = store.memory(memory_id)
        if found is None:
            raise HTTPException(404, "no such memory")
        return found

    @app.post("/api/memories/{memory_id}/review")
    def rule(memory_id: int, ruling: Ruling):
        try:
            return review(store, memory_id, ruling.approve)
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/topics")
    def topics():
        return store.topics()

    @app.get("/api/topics/{topic_id}")
    def topic(topic_id: int):
        rows = store.memories(topic_id=topic_id)
        if not rows:
            raise HTTPException(404, "no such topic")
        timeline = sorted(rows, key=lambda m: (m["as_of"], m["id"]))
        for m in timeline:
            m["relations"] = store.relations(m["id"])
        return {"id": topic_id, "name": rows[0]["topic"], "memories": timeline}

    @app.get("/api/sources")
    def sources():
        return store.sources()

    @app.get("/api/sources/{source_id}")
    def source(source_id: int):
        found = store.source(source_id)
        if found is None:
            raise HTTPException(404, "no such source")
        return found

    return app
