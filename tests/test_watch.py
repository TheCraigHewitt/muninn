import os
import time

from bruh.watch import Watcher
from test_ingest import extraction, mem

TRANSCRIPT = "Ana: We're going with a Friday launch.\nBen: Sounds good.\n"


def test_reads_a_transcript_once_it_stops_changing(tmp_path, fake, store):
    folder = tmp_path / "transcripts"
    folder.mkdir()
    llm = fake(extract=[extraction(mem("decision", "Launch on Friday.", "L1", "going with a Friday launch"))])
    watcher = Watcher(llm, store, [folder], log=lambda m: None)

    (folder / "launch-sync.txt").write_text(TRANSCRIPT)
    (folder / ".hidden.txt").write_text(TRANSCRIPT)
    later = time.time() + 60
    assert watcher.scan(now=later) == 0  # first sighting: might still be being written
    assert watcher.scan(now=later) == 1
    assert watcher.scan(now=later) == 0

    decision, = store.memories()
    saved = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(folder / "launch-sync.txt")))
    assert decision["as_of"] == saved  # no date in the name: the day the file was saved


def test_a_restarted_watcher_skips_what_it_already_read(tmp_path, fake, store):
    (tmp_path / "2026-03-02-sync.txt").write_text(TRANSCRIPT)
    first = Watcher(fake(extract=[extraction()]), store, [tmp_path], log=lambda m: None)
    first.scan(now=time.time() + 60), first.scan(now=time.time() + 60)
    again = fake()
    second = Watcher(again, store, [tmp_path], log=lambda m: None)
    assert second.scan(now=time.time() + 60) + second.scan(now=time.time() + 60) == 0
    assert again.calls == []
