"""Turn files on disk into Sources: numbered lines with an author and a time.

Supported inputs:
  * A meeting transcript (.txt): one turn per line, "[optional timestamp] Speaker: text".
    An optional "Key: value" header ending in a "Transcript:" line (the shape meeting-notes
    apps export) gives the title, date and participants. "Me" is the first participant;
    "Them" is someone the transcript couldn't identify.
  * A Slack export channel folder (one JSON file per day, users.json in the parent folder),
    or a single day file.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

UNKNOWN_SPEAKER = "Unknown speaker"
LINE_RE = re.compile(r"^(?:\[(?P<ts>[^\]]+)\]\s*)?(?P<author>[^:]{1,60}):\s*(?P<text>.*)$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SKIPPED_SUBTYPES = {"channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name"}


@dataclass
class Line:
    id: str
    author: str
    text: str
    ts: str = ""  # "YYYY-MM-DD HH:MM" for Slack, "HH:MM:SS" offsets for transcripts, or ""
    ref: str = ""  # where it lives outside Bruh: "CHANNEL_ID:TS" for live Slack messages


@dataclass
class Source:
    kind: str  # "meeting" or "slack"
    name: str
    title: str
    held_on: str  # YYYY-MM-DD the conversation took place (first day, for Slack)
    lines: list[Line] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        body = "\n".join(f"{l.ts}|{l.author}|{l.text}" for l in self.lines)
        return hashlib.sha256(f"{self.kind}|{self.title}|{body}".encode()).hexdigest()

    def describe(self) -> str:
        if self.kind == "meeting":
            return (f'Meeting transcript "{self.title}", held {self.held_on}. Automatic transcription: '
                    f"speaker labels and words may be wrong; '{UNKNOWN_SPEAKER}' means the transcript "
                    "could not tell who spoke.")
        days = sorted({l.ts[:10] for l in self.lines if l.ts})
        span = f"{days[0]} to {days[-1]}" if days else self.held_on
        return f"Slack channel {self.title}, messages from {span}. Authors marked [bot] are software."


def load(path: Path) -> list[Source]:
    """A transcript is one Source; a Slack channel becomes one Source per week, so time order holds."""
    if path.is_dir() or path.suffix == ".json":
        return by_week(load_slack(path))
    return [load_transcript(path)]


def by_week(channel: Source) -> list[Source]:
    """Split a channel into ISO weeks. A thread stays in the week its first message was posted."""
    weeks: dict[str, list[Line]] = {}
    week = ""
    for line in channel.lines:
        if "(thread reply)" not in line.author and line.ts:
            year, num, _ = datetime.strptime(line.ts[:10], "%Y-%m-%d").isocalendar()
            week = f"{year}-W{num:02d}"
        weeks.setdefault(week, []).append(line)
    out = []
    for week, lines in sorted(weeks.items()):
        lines = [Line("", l.author, l.text, l.ts, l.ref) for l in lines]
        _number(lines)
        days = sorted(l.ts[:10] for l in lines if l.ts)
        out.append(Source("slack", f"{channel.name}-{week}" if week else channel.name, channel.title,
                          days[0] if days else channel.held_on, lines))
    return out


def load_transcript(path: Path) -> Source:
    raw_lines = path.read_text().splitlines()
    header = {}
    end = next((i for i, r in enumerate(raw_lines[:15]) if r.strip() == "Transcript:"), None)
    if end is not None:
        for r in raw_lines[:end]:
            if ":" in r:
                key, value = r.split(":", 1)
                header[key.strip().lower()] = value.strip()
        raw_lines = raw_lines[end + 1:]

    participants = [p.strip() for p in header.get("meeting participants", "").split(",") if p.strip()]
    speakers = {"Them": UNKNOWN_SPEAKER}
    if participants:
        speakers["Me"] = participants[0]

    lines: list[Line] = []
    for raw in raw_lines:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        m = LINE_RE.match(raw)
        if m:
            author = m["author"].strip()
            lines.append(Line("", speakers.get(author, author), m["text"].strip(), m["ts"] or ""))
        elif lines:  # a turn that wrapped onto the next line
            lines[-1].text += " " + raw
    _number(lines)

    date = DATE_RE.search(path.name)
    held_on = date[0] if date else _parse_loose_date(header.get("date", "")) or ""
    title = header.get("meeting title") or path.stem.replace("_", " ").replace("-", " ")
    return Source("meeting", path.name, title, held_on, lines)


def load_slack(path: Path) -> Source:
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    messages = [m for f in files for m in json.loads(f.read_text())]
    users_file = (path if path.is_dir() else path.parent).parent / "users.json"
    names = {}
    if users_file.exists():
        for u in json.loads(users_file.read_text()):
            profile = u.get("profile") or {}
            names[u["id"]] = u.get("real_name") or profile.get("real_name") or u.get("name", u["id"])
    channel = path.name if path.is_dir() else path.parent.name
    return slack_source(channel, messages, names)


def slack_source(channel: str, messages: list[dict], names: dict[str, str], channel_id: str = "") -> Source:
    """Slack messages (as the API or an export gives them) as one Source. With a channel_id, each line
    remembers which message it came from."""
    # Keep each thread together: replies sit right after their parent, in time order.
    messages = sorted(messages, key=lambda m: (float(m.get("thread_ts") or m.get("ts", 0)), float(m.get("ts", 0))))

    lines: list[Line] = []
    for msg in messages:
        if msg.get("subtype") in SKIPPED_SUBTYPES:
            continue
        if msg.get("bot_id") or msg.get("subtype") == "bot_message":
            author = ((msg.get("bot_profile") or {}).get("name") or msg.get("username") or "bot") + " [bot]"
        else:
            author = (msg.get("user_profile") or {}).get("real_name") or names.get(msg.get("user"), msg.get("user", "?"))
        text = re.sub(r"<@(U[A-Z0-9]+)>", lambda m: "@" + names.get(m[1], m[1]), msg.get("text", ""))
        text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", text)
        text += "".join(f" [link: {a['fallback']}]" for a in msg.get("attachments", []) if a.get("fallback"))
        text += "".join(f" [file: {f.get('title') or f.get('name', '')}]" for f in msg.get("files", []))
        reactions = " ".join(f":{r['name']}:x{r.get('count', 1)}" for r in msg.get("reactions", []))
        if reactions:
            text += f"  [reactions: {reactions}]"
        if not text.strip():
            continue
        if msg.get("thread_ts") and msg.get("thread_ts") != msg.get("ts"):
            author += " (thread reply)"
        ts = datetime.fromtimestamp(float(msg["ts"])).strftime("%Y-%m-%d %H:%M") if msg.get("ts") else ""
        ref = f"{channel_id}:{msg['ts']}" if channel_id and msg.get("ts") else ""
        lines.append(Line("", author, text.strip(), ts, ref))
    _number(lines)

    days = sorted(l.ts[:10] for l in lines if l.ts)
    return Source("slack", channel, f"#{channel}", days[0] if days else "", lines)


def chunks(source: Source, max_lines: int = 250) -> list[list[Line]]:
    """Split a long source into pieces the model can read at once.

    Slack channels split at the longest quiet gap near the limit, so a discussion
    isn't cut in half; transcripts split evenly.
    """
    lines = source.lines
    if len(lines) <= max_lines:
        return [lines]
    out, start = [], 0
    while len(lines) - start > max_lines:
        end = start + max_lines
        if source.kind == "slack":
            window = range(start + max_lines // 2, end)
            end = max(window, key=lambda i: _gap_minutes(lines[i - 1], lines[i])) if window else end
        out.append(lines[start:end])
        start = end
    out.append(lines[start:])
    return out


def _gap_minutes(a: Line, b: Line) -> float:
    try:
        fmt = "%Y-%m-%d %H:%M"
        return (datetime.strptime(b.ts, fmt) - datetime.strptime(a.ts, fmt)).total_seconds() / 60
    except ValueError:
        return 0.0


def _number(lines: list[Line]) -> None:
    for i, line in enumerate(lines, 1):
        line.id = f"L{i}"


def _parse_loose_date(text: str) -> str | None:
    for fmt in ("%Y-%m-%d", "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
