"""bruh: command line entry point.

    bruh ingest PATH...     read transcripts (.txt) and Slack export folders into memory
    bruh ask "QUESTION"     answer from memory, with citations
    bruh serve              open the web app at http://127.0.0.1:8765
    bruh review             list memories waiting for a person to confirm them
    bruh eval               run the extraction evals in eval/fixtures
    bruh spend              show model usage and estimated cost
"""

import argparse
import os
import sys
import textwrap
from pathlib import Path

from .llm import LLM, spending
from .store import Store

ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    path = Path(os.environ.get("BRUH_DATA", ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def open_store() -> Store:
    return Store(data_dir() / "bruh.db")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bruh", description="Your company talked about it. Bruh remembers.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest", help="read conversations into memory")
    p.add_argument("paths", nargs="+", type=Path)
    p = sub.add_parser("ask", help="ask a question")
    p.add_argument("question", nargs="+")
    p = sub.add_parser("serve", help="run the web app")
    p.add_argument("--port", type=int, default=8765)
    sub.add_parser("review", help="list memories waiting for review")
    p = sub.add_parser("eval", help="run extraction evals")
    p.add_argument("folder", nargs="?", type=Path, default=ROOT / "eval" / "fixtures")
    sub.add_parser("spend", help="show model usage")
    args = parser.parse_args(argv)

    if args.command == "ingest":
        from .ingest import ingest_paths

        missing = [p for p in args.paths if not p.exists()]
        if missing:
            sys.exit(f"not found: {', '.join(map(str, missing))}")
        ingest_paths(LLM(data_dir()), open_store(), args.paths)
        print(f"\nspent so far: ~${spending(data_dir())['estimated_usd']}")
    elif args.command == "ask":
        from .ask import ask

        result = ask(LLM(data_dir()), open_store(), " ".join(args.question))
        print(textwrap.fill(result["answer"], 100, replace_whitespace=False) + "\n")
        for m in result["memories"]:
            print(f"[M{m['id']}] {m['type']} · {m['status']} · {m['as_of']} · {m['topic']}")
            for e in m["evidence"][:2]:
                print(f"     “{e['quote']}” — {e['author']}, {e['source_title']} {e['ts'] or e['held_on']}")
    elif args.command == "serve":
        import uvicorn

        from .web.app import create_app

        print(f"Bruh is running at http://127.0.0.1:{args.port}")
        uvicorn.run(create_app(open_store(), LLM(data_dir())), host="127.0.0.1", port=args.port, log_level="warning")
    elif args.command == "review":
        for m in open_store().memories(status="review"):
            print(f"M{m['id']} {m['type']} ({m['confidence']:.2f}) {m['statement']}")
    elif args.command == "eval":
        from .evals import run

        passed, total = run(LLM(data_dir()), args.folder)
        print(f"\n{passed}/{total} checks passed")
        sys.exit(0 if passed == total else 1)
    elif args.command == "spend":
        for k, v in spending(data_dir()).items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
