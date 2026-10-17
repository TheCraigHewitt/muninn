"""Watch folders for meeting transcripts and read each new one into memory.

Point it at wherever transcripts land (a meeting-notes app's export folder, a synced Drive folder).
A file is read once it has stopped changing, so a transcript still being written isn't read half
done. Files Muninn has already read are skipped, so restarting the watcher is safe.
"""

import time
from datetime import datetime
from pathlib import Path

from . import sources as src
from .ingest import ingest_sources
from .llm import LLM
from .store import Store

PATTERNS = ("*.txt", "*.md")


class Watcher:
    def __init__(self, llm: LLM, store: Store, folders: list[Path], log=print):
        self.llm, self.store, self.folders, self.log = llm, store, folders, log
        self.seen: dict[Path, tuple[int, float]] = {}  # size and modified time at the last look
        self.done: dict[Path, tuple[int, float]] = {}  # handled at this size and time; don't look again

    def files(self) -> list[Path]:
        return sorted({f for folder in self.folders for pattern in PATTERNS for f in folder.rglob(pattern)
                       if not any(part.startswith(".") for part in f.relative_to(folder).parts)})

    def scan(self, now: float | None = None) -> int:
        """Read every transcript that has settled since the last scan. Returns how many were read."""
        now = now or time.time()
        ready = []
        for f in self.files():
            try:
                stat = f.stat()
            except FileNotFoundError:
                continue
            shape = (stat.st_size, stat.st_mtime)
            if self.done.get(f) == shape:
                continue
            settled = self.seen.get(f) == shape and now - stat.st_mtime >= 5
            self.seen[f] = shape
            if settled:
                ready.append((f, shape))

        new = []
        for f, shape in ready:
            self.done[f] = shape
            try:
                source = src.load_transcript(f)
            except Exception as e:
                self.log(f"can't read {f.name}: {e}")
                continue
            if not source.held_on:  # no date in the name or header: use when the file was saved
                source.held_on = datetime.fromtimestamp(shape[1]).strftime("%Y-%m-%d")
            if source.lines and not self.store.has_source(source):
                new.append(source)
        if new:
            self.log(f"found {len(new)} new transcript{'s' if len(new) > 1 else ''}")
            ingest_sources(self.llm, self.store, new, progress=self.log)
        return len(new)

    def run(self, interval: float = 30) -> None:
        self.log(f"watching {', '.join(map(str, self.folders))} for transcripts")
        while True:
            try:
                self.scan()
            except Exception as e:
                self.log(f"reading new transcripts failed, will try again: {e}")
                self.done.clear()
            time.sleep(interval)
