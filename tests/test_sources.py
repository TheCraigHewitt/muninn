from pathlib import Path

from muninn import sources
from muninn.sources import UNKNOWN_SPEAKER, Line, Source

DATA = Path(__file__).parent / "data"


def test_transcript_header_speakers_and_wrapped_lines():
    s, = sources.load(DATA / "meeting.txt")
    assert s.kind == "meeting"
    assert s.title == "Weekly sync"
    assert [l.author for l in s.lines] == ["Maya", "Maya Chen", UNKNOWN_SPEAKER, "Maya Chen"]
    assert s.lines[3].text == "Friday works, we're going with Friday. that's the plan"
    assert [l.id for l in s.lines] == ["L1", "L2", "L3", "L4"]
    assert s.held_on == ""  # "Mar 2" has no year and the file name has no date


def test_transcript_date_from_file_name(tmp_path):
    path = tmp_path / "standup-2026-03-02.txt"
    path.write_text("Ana: hi\n")
    assert sources.load(path)[0].held_on == "2026-03-02"


def test_slack_channel_keeps_threads_together_and_labels_bots():
    s, = sources.load(DATA / "slack" / "general")
    assert s.kind == "slack" and s.title == "#general"
    authors = [l.author for l in s.lines]
    assert authors == ["Maya Chen", "Sam Ortiz (thread reply)", "Sam Ortiz", "deploybot [bot]"]
    assert "@Maya Chen" in s.lines[1].text
    assert "[reactions: :+1:x2]" in s.lines[1].text
    assert all("joined" not in l.text for l in s.lines)
    assert s.held_on == s.lines[0].ts[:10]


def test_long_slack_source_splits_at_the_quiet_gap():
    times = [f"2026-03-02 09:{m:02d}" for m in range(10)] + [f"2026-03-02 15:{m:02d}" for m in range(10)]
    lines = [Line(f"L{i + 1}", "A", "x", t) for i, t in enumerate(times)]
    parts = sources.chunks(Source("slack", "c", "#c", "2026-03-02", lines), max_lines=12)
    assert [len(p) for p in parts] == [10, 10]


def test_slack_channel_splits_into_weeks_keeping_threads_whole():
    channel = Source("slack", "dev", "#dev", "2026-03-06", [
        Line("L1", "Ana", "friday question", "2026-03-06 10:00"),
        Line("L2", "Ben (thread reply)", "monday answer", "2026-03-09 09:00"),
        Line("L3", "Ana", "new week", "2026-03-09 10:00"),
    ])
    first, second = sources.by_week(channel)
    assert [l.text for l in first.lines] == ["friday question", "monday answer"]
    assert [l.id for l in second.lines] == ["L1"] and second.held_on == "2026-03-09"
    assert first.name == "dev-2026-W10" and second.title == "#dev"
