import pytest

from muninn.llm import LLM, Usage
from muninn.store import Store


class FakeLLM(LLM):
    """Returns canned responses per purpose ("extract", "reconcile", "ask"), in order."""

    def __init__(self, tmp_path, responses):
        super().__init__(tmp_path, model="fake")
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls = []

    def json(self, purpose, system, user, schema, effort=None):
        self.calls.append((purpose, user))
        return self.responses[purpose].pop(0), Usage()


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


@pytest.fixture
def fake(tmp_path):
    return lambda **responses: FakeLLM(tmp_path, responses)
