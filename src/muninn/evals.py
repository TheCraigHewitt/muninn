"""Extraction evals: run conversations with known answers and check what comes out.

Each conversation `<name>.txt` sits next to `<name>.expect.json`:

    {"checks": [
      {"kind": "memory_from",     "ids": ["L8"], "types": ["decision"], "why": "..."},
      {"kind": "no_memory_from",  "ids": ["L2"], "why": "sarcasm must produce nothing"},
      {"kind": "supersedes_from", "ids": ["L7"], "why": "..."},
      {"kind": "label",           "ids": ["L3"], "sincerity": "hypothetical", "why": "..."}
    ]}

`types` is optional and narrows which memory types count.
"""

import json
from pathlib import Path

from . import sources
from .extract import MEMORY_TYPES, Extraction, extract
from .llm import LLM


def check(expect: dict, extraction: Extraction) -> list[dict]:
    results = []
    for c in expect.get("checks", []):
        ids = set(c.get("ids", []))
        types = set(c.get("types", MEMORY_TYPES))
        citing = [m for m in extraction.candidates if m.type in types and ids & {e["id"] for e in m.evidence}]
        kind = c["kind"]
        if kind == "memory_from":
            ok = bool(citing)
        elif kind == "no_memory_from":
            ok = not citing
        elif kind == "supersedes_from":
            ok = any(m.supersedes for m in citing)
        elif kind == "label":
            ok = all(extraction.labels.get(i) == c["sincerity"] for i in ids)
        else:
            raise ValueError(f"unknown check kind {kind!r}")
        results.append({**c, "ok": ok})
    return results


def run(llm: LLM, folder: Path, progress=print) -> tuple[int, int]:
    passed = total = 0
    for expect_path in sorted(folder.glob("*.expect.json")):
        convo = expect_path.with_name(expect_path.name.removesuffix(".expect.json") + ".txt")
        extraction = extract(llm, sources.load(convo)[0])
        results = check(json.loads(expect_path.read_text()), extraction)
        ok = sum(r["ok"] for r in results)
        passed, total = passed + ok, total + len(results)
        progress(f"{convo.name}: {ok}/{len(results)}")
        for r in results:
            if not r["ok"]:
                progress(f"   FAIL {r['kind']} {', '.join(r.get('ids', []))}: {r.get('why', '')}")
        for c in extraction.rejected:
            progress(f"   dropped {c.type}: {c.statement[:80]} ({'; '.join(c.problems)})")
    return passed, total
