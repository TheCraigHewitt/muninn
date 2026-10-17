"""muninn: command line entry point.

    muninn ingest PATH...     read transcripts (.txt) and Slack export folders into memory
    muninn ask "QUESTION"     answer from memory, with citations
    muninn serve              open the web app at http://127.0.0.1:8765
                            (--slack also runs the Slack bot, --watch DIR the folder watcher)
    muninn slack              run the Slack bot: read invited channels, answer @muninn and /muninn
    muninn watch DIR...       read new meeting transcripts as they appear in these folders
    muninn review             list memories waiting for a person to confirm them
    muninn eval               run the extraction evals in eval/fixtures
    muninn spend              show model usage and estimated cost
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
    path = Path(os.environ.get("MUNINN_DATA", ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def open_store() -> Store:
    return Store(data_dir() / "muninn.db")


def check_folders(folders: list[Path]) -> None:
    missing = [str(f) for f in folders if not f.is_dir()]
    if missing:
        sys.exit(f"not a folder: {', '.join(missing)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="muninn", description="Your company talked about it. Muninn remembers.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest", help="read conversations into memory")
    p.add_argument("paths", nargs="+", type=Path)
    p = sub.add_parser("ask", help="ask a question")
    p.add_argument("question", nargs="+")
    p = sub.add_parser("serve", help="run the web app")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--slack", action="store_true", help="also run the Slack bot")
    p.add_argument("--watch", type=Path, action="append", default=[], metavar="DIR",
                   help="also read new transcripts from this folder (repeatable)")
    sub.add_parser("slack", help="run the Slack bot")
    p = sub.add_parser("watch", help="read new transcripts from folders as they appear")
    p.add_argument("folders", nargs="+", type=Path)
    p.add_argument("--interval", type=float, default=30, help="seconds between looks (default 30)")
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
        for para in result["answer"].splitlines():
            print(textwrap.fill(para, 100, subsequent_indent="  " if para.lstrip().startswith("-") else ""))
        print()
        for m in result["memories"]:
            print(f"[M{m['id']}] {m['type']} · {m['status']} · {m['as_of']} · {m['topic']}")
            for e in m["evidence"][:2]:
                print(f"     “{e['quote']}” — {e['author']}, {e['source_title']} {e['ts'] or e['held_on']}")
    elif args.command == "serve":
        import threading

        import uvicorn

        from .web.app import create_app

        check_folders(args.watch)
        if args.slack:
            from .slack import run

            run(LLM(data_dir()), data_dir() / "muninn.db", block=False)
        if args.watch:
            from .watch import Watcher

            watcher = Watcher(LLM(data_dir()), open_store(), args.watch, log=lambda m: print(f"[watch] {m}", flush=True))
            threading.Thread(target=watcher.run, name="muninn-watch", daemon=True).start()
        print(f"Muninn is running at http://127.0.0.1:{args.port}")
        uvicorn.run(create_app(open_store(), LLM(data_dir())), host="127.0.0.1", port=args.port, log_level="warning")
    elif args.command == "slack":
        from .slack import run

        run(LLM(data_dir()), data_dir() / "muninn.db")
    elif args.command == "watch":
        from .watch import Watcher

        check_folders(args.folders)
        Watcher(LLM(data_dir()), open_store(), args.folders).run(args.interval)
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
