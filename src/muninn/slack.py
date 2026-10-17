"""Muninn in Slack: reads the public channels it's invited to, and answers when asked.

It connects over Socket Mode, so it needs no public URL, only two tokens: SLACK_BOT_TOKEN (xoxb-…)
and SLACK_APP_TOKEN (xapp-…). See docs/SLACK.md for setting up the app.

Reading: each message in a channel Muninn is a member of is kept as it arrives. Once the channel has
been quiet for a while, or the oldest message has waited long enough, the waiting messages are read
as one conversation, split by week, and reconciled like any other. Questions asked of Muninn and
Muninn's own replies are never read as conversation. Private, shared (Slack Connect) and direct
conversations are never read at all.

Answering: @muninn in a channel answers in a thread, for everyone there. /muninn answers privately.
"""

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from .ask import ask
from .ingest import ingest_sources
from .llm import LLM
from .sources import SKIPPED_SUBTYPES, by_week, slack_source
from .store import Store

SCHEMA = """
-- state: waiting (not read yet) | read
CREATE TABLE IF NOT EXISTS slack_messages (
    channel_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    raw TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'waiting',
    PRIMARY KEY (channel_id, ts)
);
CREATE TABLE IF NOT EXISTS slack_users (id TEXT PRIMARY KEY, name TEXT NOT NULL);
"""

QUIET_SECONDS = 60 * float(os.environ.get("MUNINN_SLACK_QUIET_MINUTES", 30))
MAX_WAIT_SECONDS = 4 * 3600
BACKFILL_DAYS = float(os.environ.get("MUNINN_SLACK_BACKFILL_DAYS", 30))
CHANNEL_RECHECK_SECONDS = 3600
NOT_READABLE = ("is_private", "is_im", "is_mpim", "is_group", "is_ext_shared", "is_pending_ext_shared", "is_archived")

HELP = ("Ask me what the team decided, why, or who's on the hook. Like `@muninn what did we decide about pricing?`\n"
        "`/muninn your question` answers just for you.")
THINKING = "_checking the receipts…_"
MAX_RECEIPTS = 12


class SlackConnector:
    def __init__(self, llm: LLM, db_path: Path, client, log=print):
        self.llm, self.db_path, self.client, self.log = llm, db_path, client, log
        self.store = Store(db_path)  # events and answers; flushing opens its own connection
        self.store.db.executescript(SCHEMA)
        me = client.auth_test()
        self.bot_user, self.bot_id, self.base_url = me["user_id"], me.get("bot_id"), me["url"]
        self.channels: dict[str, tuple[float, dict | None]] = {}
        self._flush_store: Store | None = None

    # ---- which channels Muninn may read ----

    def channel(self, channel_id: str) -> dict | None:
        """The channel's info if Muninn may read it (public, not shared outside, not archived), else None."""
        checked = self.channels.get(channel_id)
        if checked and time.time() - checked[0] < CHANNEL_RECHECK_SECONDS:
            return checked[1]
        try:
            info = self.client.conversations_info(channel=channel_id)["channel"]
        except Exception as e:
            self.log(f"can't look up channel {channel_id}: {e}")
            info = {}
        ok = info.get("is_channel") and not any(info.get(k) for k in NOT_READABLE)
        self.channels[channel_id] = (time.time(), info if ok else None)
        return info if ok else None

    def recheck(self, channel_id: str) -> None:
        self.channels.pop(channel_id, None)

    # ---- keeping messages as they arrive ----

    def on_message(self, event: dict) -> None:
        if event.get("channel_type") != "channel":
            return
        channel_id, subtype = event["channel"], event.get("subtype")
        if subtype == "message_deleted":
            self.forget(channel_id, event["deleted_ts"])
        elif subtype == "message_changed" and event["message"].get("subtype") == "tombstone":
            self.forget(channel_id, event["message"]["ts"])  # a deleted thread parent, kept for its replies
        elif subtype == "message_changed":
            self.edit(channel_id, event["message"])
        elif subtype not in ("message_replied", "channel_history_changed") and self.channel(channel_id):
            self.keep(channel_id, event)

    def ignored(self, msg: dict) -> bool:
        """Muninn's own replies and questions put to Muninn aren't part of the conversation."""
        return (msg.get("subtype") in SKIPPED_SUBTYPES or msg.get("user") == self.bot_user
                or (self.bot_id is not None and msg.get("bot_id") == self.bot_id)
                or f"<@{self.bot_user}>" in msg.get("text", ""))

    def keep(self, channel_id: str, msg: dict) -> None:
        if self.ignored(msg):
            return
        for user in {msg.get("user"), *re.findall(r"<@(U[A-Z0-9]+)>", msg.get("text", ""))} - {None}:
            self.name(user)
        self.store.db.execute("INSERT OR IGNORE INTO slack_messages (channel_id, ts, raw) VALUES (?, ?, ?)",
                              (channel_id, msg["ts"], json.dumps(msg)))
        self.store.commit()

    def edit(self, channel_id: str, msg: dict) -> None:
        """An edit before Muninn has read the message just replaces it. (Edits after that aren't followed yet.)"""
        row = self._waiting(channel_id, msg["ts"])
        if row is not None and not self.ignored(msg):
            msg = {**msg, "reactions": json.loads(row["raw"]).get("reactions", [])}
            self._save(channel_id, msg)

    def forget(self, channel_id: str, ts: str) -> None:
        """Deleted in Slack means deleted in Muninn: the message, every quote of it, and Memories resting on it."""
        self.store.db.execute("DELETE FROM slack_messages WHERE channel_id = ? AND ts = ?", (channel_id, ts))
        gone = self.store.erase_line(f"{channel_id}:{ts}")
        if gone:
            self.log(f"a message was deleted in Slack; dropped {gone} memories that rested on it")

    def on_reaction(self, event: dict, added: bool) -> None:
        item = event.get("item") or {}
        row = self._waiting(item.get("channel", ""), item.get("ts", "")) if item.get("type") == "message" else None
        if row is None:
            return
        msg = json.loads(row["raw"])
        reactions = {r["name"]: r for r in msg.get("reactions", [])}
        r = reactions.setdefault(event["reaction"], {"name": event["reaction"], "count": 0})
        r["count"] += 1 if added else -1
        msg["reactions"] = [r for r in reactions.values() if r["count"] > 0]
        self._save(item["channel"], msg)

    def on_joined(self, event: dict) -> None:
        if event.get("user") == self.bot_user:
            self.recheck(event["channel"])
            self.backfill(event["channel"])

    def name(self, user_id: str) -> str:
        row = self.store.db.execute("SELECT name FROM slack_users WHERE id = ?", (user_id,)).fetchone()
        if row:
            return row["name"]
        try:
            user = self.client.users_info(user=user_id)["user"]
            name = user.get("real_name") or (user.get("profile") or {}).get("real_name") or user.get("name") or user_id
        except Exception:
            return user_id
        self.store.db.execute("INSERT OR REPLACE INTO slack_users (id, name) VALUES (?, ?)", (user_id, name))
        return name

    def _waiting(self, channel_id: str, ts: str):
        return self.store.db.execute("SELECT raw FROM slack_messages WHERE channel_id = ? AND ts = ? AND state = 'waiting'",
                                     (channel_id, ts)).fetchone()

    def _save(self, channel_id: str, msg: dict) -> None:
        self.store.db.execute("UPDATE slack_messages SET raw = ? WHERE channel_id = ? AND ts = ?",
                              (json.dumps(msg), channel_id, msg["ts"]))
        self.store.commit()

    # ---- catching up on history ----

    def backfill_all(self) -> None:
        for ch in self._pages(self.client.conversations_list, "channels", types="public_channel",
                              exclude_archived=True, limit=200):
            if ch.get("is_member"):
                self.backfill(ch["id"])

    def backfill(self, channel_id: str) -> int:
        """Keep recent history Muninn hasn't seen: since the last thing it read from this channel
        (live or from an export), going back at most MUNINN_SLACK_BACKFILL_DAYS."""
        info = self.channel(channel_id)
        if info is None:
            return 0
        since = time.time() - BACKFILL_DAYS * 86400
        last_read = self.store.last_line_ts("slack", f"#{info['name']}")
        if last_read:
            since = max(since, datetime.strptime(last_read, "%Y-%m-%d %H:%M").timestamp() + 60)
        kept = self.store.db.execute("SELECT MAX(CAST(ts AS REAL)) FROM slack_messages WHERE channel_id = ?",
                                     (channel_id,)).fetchone()[0]
        since = max(since, kept or 0)

        count = 0
        for msg in self._pages(self.client.conversations_history, "messages", channel=channel_id,
                               oldest=f"{since:.6f}", limit=200):
            if msg.get("reply_count"):
                for reply in self._pages(self.client.conversations_replies, "messages", channel=channel_id,
                                         ts=msg["ts"], oldest=f"{since:.6f}", limit=200):
                    if reply["ts"] != msg["ts"] and float(reply["ts"]) > since:
                        self.keep(channel_id, reply)
                        count += 1
            self.keep(channel_id, msg)
            count += 1
        if count:
            self.log(f"caught up on {count} messages in #{info['name']}")
        return count

    @staticmethod
    def _pages(method, key: str, **kwargs):
        cursor = None
        while True:
            page = method(**kwargs, **({"cursor": cursor} if cursor else {}))
            yield from page.get(key) or []
            cursor = (page.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return

    # ---- reading waiting messages into memory ----

    def flush(self, now: float | None = None) -> int:
        """Read each channel whose waiting messages are ready. Returns how many conversations were read."""
        now = now or time.time()
        if self._flush_store is None:
            self._flush_store = Store(self.db_path)
        db = self._flush_store.db
        waiting: dict[str, list[dict]] = {}
        for row in db.execute("SELECT channel_id, raw FROM slack_messages WHERE state = 'waiting'"):
            waiting.setdefault(row["channel_id"], []).append(json.loads(row["raw"]))

        read = 0
        for channel_id, msgs in waiting.items():
            stamps = [float(m["ts"]) for m in msgs]
            if now - max(stamps) < QUIET_SECONDS and now - min(stamps) < MAX_WAIT_SECONDS:
                continue  # people are still talking
            info = self.channel(channel_id)
            if info is None:
                db.execute("DELETE FROM slack_messages WHERE channel_id = ? AND state = 'waiting'", (channel_id,))
                db.commit()
                continue
            # A reply to an older thread reads better with the message it replies to.
            have = {m["ts"] for m in msgs}
            parents = {m["thread_ts"] for m in msgs if m.get("thread_ts") and m["thread_ts"] != m["ts"]} - have
            context = [json.loads(r["raw"]) for p in parents
                       if (r := db.execute("SELECT raw FROM slack_messages WHERE channel_id = ? AND ts = ?",
                                           (channel_id, p)).fetchone())]
            names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM slack_users")}
            channel = slack_source(f"{info['name']}-live-{int(min(stamps))}", msgs + context, names, channel_id)
            channel.title = f"#{info['name']}"
            sources = by_week(channel)
            try:
                ingest_sources(self.llm, self._flush_store, sources, progress=self.log)
            except Exception as e:
                self.log(f"couldn't read #{info['name']} yet, will try again: {e}")
                continue
            db.executemany("UPDATE slack_messages SET state = 'read' WHERE channel_id = ? AND ts = ?",
                           [(channel_id, ts) for ts in have])
            db.commit()
            read += len(sources)
        return read

    # ---- answering ----

    def answer(self, question: str) -> str:
        question = re.sub(rf"<@{self.bot_user}>", "", question).strip()
        if not question or question.lower() in ("help", "hi", "hello", "hey", "?"):
            return HELP
        try:
            return self.format(ask(self.llm, self.store, question))
        except Exception as e:
            self.log(f"answering failed: {e}")
            return "Muninn tripped over something and couldn't answer. Try again in a minute."

    def format(self, result: dict) -> str:
        """The answer in Slack's markup, with numbered receipts that quote the original words."""
        memories = {m["id"]: m for m in result["memories"]}
        numbers: dict[int, int] = {}

        def cite(match):
            mid = int(match[1])
            return f"[{numbers.setdefault(mid, len(numbers) + 1)}]" if mid in memories else ""

        text = escape(result["answer"])
        text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        text = re.sub(r"\[M(\d+)\]", cite, text)
        text = re.sub(r"^(\s*)[-*] ", r"\1• ", text, flags=re.M)
        for mid in memories:
            numbers.setdefault(mid, len(numbers) + 1)

        receipts = []
        ordered = sorted(numbers.items(), key=lambda x: x[1])
        for mid, n in ordered[:MAX_RECEIPTS]:
            m = memories[mid]
            status = {"superseded": " · _replaced later_", "review": " · _not confirmed yet_"}.get(m["status"], "")
            receipts.append(f"*[{n}]* {m['type'].capitalize()} · {pretty_date(m['as_of'])}{status}")
            if m["evidence"]:
                e = m["evidence"][0]
                quote = e["quote"] if len(e["quote"]) <= 200 else e["quote"][:200] + "…"
                receipts.append(f">“{escape(quote)}” — {escape(e['author'] or 'someone')}, {self.where(e)}")
        if len(ordered) > MAX_RECEIPTS:
            receipts.append(f"_…and {len(ordered) - MAX_RECEIPTS} more in the web app_")
        if receipts:
            text += "\n\n*Receipts*\n" + "\n".join(receipts)
        return text

    def where(self, e: dict) -> str:
        if e.get("ref"):
            channel_id, ts = e["ref"].split(":")
            return f"<{self.base_url}archives/{channel_id}/p{ts.replace('.', '')}|{escape(e['source_title'])}>"
        when = pretty_date(e["held_on"])
        return f"{escape(e['source_title'])} ({when})" if e["source_kind"] == "meeting" else escape(e["source_title"])


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pretty_date(day: str) -> str:
    try:
        return datetime.strptime(day[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
    except ValueError:
        return day


def build_app(llm: LLM, db_path: Path, bot_token: str, log, client=None):
    """The Bolt app with Muninn's listeners, and the connector behind them."""
    from slack_bolt import App
    from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

    app = App(client=client) if client else App(token=bot_token)
    app.client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    bot = SlackConnector(llm, db_path, app.client, log)

    @app.event("app_mention")
    def mention(event, client):
        thread = event.get("thread_ts") or event["ts"]
        placeholder = client.chat_postMessage(channel=event["channel"], thread_ts=thread, text=THINKING)
        client.chat_update(channel=event["channel"], ts=placeholder["ts"], text=bot.answer(event.get("text", "")))

    @app.command("/muninn")
    def command(ack, command, respond):
        question = command.get("text", "").strip()
        ack(response_type="ephemeral", text=THINKING if question else HELP)
        if question:
            respond(response_type="ephemeral", text=bot.answer(question))

    app.event("message")(lambda event: bot.on_message(event))
    app.event("reaction_added")(lambda event: bot.on_reaction(event, True))
    app.event("reaction_removed")(lambda event: bot.on_reaction(event, False))
    app.event("member_joined_channel")(lambda event: bot.on_joined(event))
    for name in ("channel_shared", "channel_unshared"):
        app.event(name)(lambda event: bot.recheck(event["channel"]))
    return app, bot


def run(llm: LLM, db_path: Path, block: bool = True, log=None) -> None:
    """Connect to Slack and start reading and answering. With block=False it runs in the background."""
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    bot_token, app_token = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_APP_TOKEN")
    if not (bot_token and app_token):
        raise SystemExit("Slack needs SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env (see docs/SLACK.md)")
    log = log or (lambda msg: print(f"[slack] {msg}", flush=True))
    app, bot = build_app(llm, db_path, bot_token, log)

    def reader():
        try:
            bot.backfill_all()
        except Exception as e:
            log(f"catching up on history failed: {e}")
        while True:
            try:
                bot.flush()
            except Exception as e:
                log(f"reading waiting messages failed: {e}")
            time.sleep(60)

    threading.Thread(target=reader, name="muninn-slack-reader", daemon=True).start()
    handler = SocketModeHandler(app, app_token)
    log("connected. Invite me to a channel with /invite @muninn, then ask me something.")
    handler.start() if block else handler.connect()
