"""The one place Muninn talks to a model.

Every call asks for JSON matching a schema. Responses are cached on disk by a
hash of the request, so re-running an ingest or an eval costs nothing, and
token usage is appended to a log so spending stays visible.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5-5"

# Rough list prices in USD per million tokens (input, output), for the usage report only.
PRICES = {
    "claude-opus-5-5": (5.0, 25.0),
    "claude-sonnet-5-5": (3.0, 15.0),
    "claude-haiku-5-5": (1.0, 5.0),
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False


class LLM:
    """JSON-in, JSON-out model calls with a disk cache and a usage log."""

    def __init__(self, data_dir: Path, model: str | None = None, effort: str = "medium", client=None):
        self.model = model or os.environ.get("MUNINN_MODEL", DEFAULT_MODEL)
        self.effort = effort
        self.cache_dir = data_dir / "cache"
        self.usage_log = data_dir / "usage.jsonl"
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def json(self, purpose: str, system: str, user: str, schema: dict, effort: str | None = None) -> tuple[dict, Usage]:
        effort = effort or self.effort
        key = hashlib.sha256(
            json.dumps([self.model, effort, system, user, schema], sort_keys=True).encode()
        ).hexdigest()
        cached = self.cache_dir / f"{key}.json"
        if cached.exists():
            return json.loads(cached.read_text()), Usage(cached=True)

        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise RuntimeError(f"model refused the {purpose} request")
        if response.stop_reason == "max_tokens":
            raise RuntimeError(f"{purpose} response hit max_tokens; the input is too long")
        text = next(b.text for b in response.content if b.type == "text")
        result = json.loads(text)

        usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(result))
        with self.usage_log.open("a") as log:
            log.write(json.dumps({
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "purpose": purpose,
                "model": self.model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            }) + "\n")
        return result, usage


def spending(data_dir: Path) -> dict:
    """Totals from the usage log, with an estimated cost."""
    totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_usd": 0.0}
    log = data_dir / "usage.jsonl"
    if not log.exists():
        return totals
    for raw in log.read_text().splitlines():
        row = json.loads(raw)
        price_in, price_out = PRICES.get(row["model"], PRICES[DEFAULT_MODEL])
        totals["calls"] += 1
        totals["input_tokens"] += row["input_tokens"]
        totals["output_tokens"] += row["output_tokens"]
        totals["estimated_usd"] += (row["input_tokens"] * price_in + row["output_tokens"] * price_out) / 1e6
    totals["estimated_usd"] = round(totals["estimated_usd"], 2)
    return totals
