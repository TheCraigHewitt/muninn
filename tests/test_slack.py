from muninn.slack import QUIET_SECONDS, SlackConnector
from test_ingest import extraction, mem

T0 = 1772611200.0  # 2026-03-04
PRODUCT = {"id": "C1", "name": "product", "is_channel": True, "is_member": True}


class FakeSlack:
    """Just enough of slack_sdk's WebClient."""

    def __init__(self, history=(), replies=None, channels=None):
        self.chans = {c["id"]: c for c in channels or [PRODUCT]}
        self.history, self.replies, self.asked_oldest = list(history), replies or {}, []

    def auth_test(self):
        return {"user_id": "UMUNINN", "bot_id": "BMUNINN", "url": "https://team.slack.com/", "user": "muninn"}

    def conversations_info(self, channel):
        return {"channel": self.chans[channel]}

    def conversations_list(self, **_):
        return {"channels": list(self.chans.values())}

    def users_info(self, user):
        return {"user": {"real_name": {"U1": "Ana Ruiz", "U2": "Ben Cho"}[user]}}

    def conversations_history(self, channel, oldest, limit, cursor=None):
        self.asked_oldest.append(oldest)
        msgs = [m for m in self.history if float(m["ts"]) > float(oldest)]
        return {"messages": msgs[:1], "response_metadata": {"next_cursor": "p2"}} if not cursor else {"messages": msgs[1:]}

    def conversations_replies(self, channel, ts, oldest, limit, cursor=None):
        return {"messages": self.replies.get(ts, [])}


def msg(seconds, text, user="U1", **extra):
    return {"type": "message", "channel": "C1", "channel_type": "channel", "user": user, "text": text,
            "ts": f"{T0 + seconds:.6f}", **extra}


def bot(tmp_path, llm=None, **slack):
    return SlackConnector(llm, tmp_path / "test.db", FakeSlack(**slack), log=lambda m: None)


def waiting(b):
    return [r["ts"] for r in b.store.db.execute("SELECT ts FROM slack_messages WHERE state = 'waiting' ORDER BY ts")]


def test_keeps_only_public_channel_conversation(tmp_path):
    secret = {"id": "C2", "name": "secret", "is_channel": True, "is_private": True}
    shared = {"id": "C3", "name": "partners", "is_channel": True, "is_ext_shared": True}
    b = bot(tmp_path, channels=[PRODUCT, secret, shared])
    b.on_message(msg(0, "We're going with $5."))
    b.on_message({**msg(1, "dm"), "channel_type": "im"})
    b.on_message({**msg(2, "private"), "channel": "C2"})
    b.on_message({**msg(3, "shared"), "channel": "C3"})
    b.on_message(msg(4, "<@UMUNINN> what did we decide?"))
    b.on_message(msg(5, "Here's what I found", user="UMUNINN", bot_id="BMUNINN"))
    b.on_message(msg(6, "joined", subtype="channel_join"))
    assert waiting(b) == [f"{T0:.6f}"]


def test_reads_a_channel_once_it_goes_quiet(tmp_path, fake):
    llm = fake(extract=[extraction(mem("decision", "Price is $5.", "L1", "going with $5", topic="Pricing"))])
    b = bot(tmp_path, llm)
    b.on_message(msg(0, "We're going with $5. <@U2> can you update the site?"))
    b.on_reaction({"reaction": "+1", "item": {"type": "message", "channel": "C1", "ts": f"{T0:.6f}"}}, True)

    assert b.flush(now=T0 + QUIET_SECONDS - 60) == 0  # still talking
    assert b.flush(now=T0 + QUIET_SECONDS + 60) == 1
    assert waiting(b) == []
    sent = llm.calls[0][1]
    assert "Ana Ruiz" in sent and "@Ben Cho" in sent and ":+1:x1" in sent
    decision = b.store.memory(b.store.memories()[0]["id"])
    assert decision["source_title"] == "#product"
    assert decision["evidence"][0]["ref"] == f"C1:{T0:.6f}"


def test_a_late_thread_reply_is_read_with_its_parent(tmp_path, fake):
    llm = fake(extract=[extraction(), extraction()])
    b = bot(tmp_path, llm)
    b.on_message(msg(0, "Should the free tier get 3 shows?"))
    b.flush(now=T0 + QUIET_SECONDS + 1)
    b.on_message(msg(9000, "Yes, 3 shows.", user="U2", thread_ts=f"{T0:.6f}"))
    b.flush(now=T0 + 9000 + QUIET_SECONDS + 1)
    second = llm.calls[1][1]
    assert "Should the free tier get 3 shows?" in second and "Ben Cho (thread reply): Yes, 3 shows." in second


def test_deleting_in_slack_deletes_from_memory(tmp_path, fake):
    llm = fake(extract=[extraction(mem("decision", "Price is $5.", "L1", "going with $5"))])
    b = bot(tmp_path, llm)
    b.on_message(msg(0, "We're going with $5."))
    b.flush(now=T0 + QUIET_SECONDS + 1)
    assert len(b.store.memories()) == 1
    b.on_message({"type": "message", "subtype": "message_deleted", "channel": "C1", "channel_type": "channel",
                  "deleted_ts": f"{T0:.6f}"})
    assert b.store.memories() == []
    line = b.store.db.execute("SELECT text FROM lines").fetchone()
    assert line["text"] == ""


def test_editing_before_muninn_reads_replaces_and_a_deleted_thread_parent_goes(tmp_path):
    b = bot(tmp_path)
    b.on_message(msg(0, "We're going with $6."))
    b.on_message({**msg(1, ""), "subtype": "message_changed", "message": msg(0, "We're going with $5.")})
    raw = b.store.db.execute("SELECT raw FROM slack_messages").fetchone()["raw"]
    assert "$5" in raw and "$6" not in raw
    b.on_message({**msg(2, ""), "subtype": "message_changed",
                  "message": msg(0, "This message was deleted.", subtype="tombstone")})
    assert waiting(b) == []


def test_backfill_starts_where_muninn_left_off_and_follows_threads(tmp_path, fake, monkeypatch):
    monkeypatch.setattr("muninn.slack.BACKFILL_DAYS", 10_000)
    history = [msg(10, "Parent", reply_count=1), msg(20, "Another")]
    replies = {f"{T0 + 10:.6f}": [msg(10, "Parent"), msg(30, "A reply", user="U2", thread_ts=f"{T0 + 10:.6f}")]}
    b = bot(tmp_path, fake(), history=history, replies=replies)
    b.store.db.execute("INSERT INTO slack_messages (channel_id, ts, raw, state) VALUES ('C1', ?, '{}', 'read')",
                       (f"{T0:.6f}",))
    b.backfill_all()
    assert b.client.asked_oldest[0] == f"{T0:.6f}"
    assert waiting(b) == [f"{T0 + s:.6f}" for s in (10, 20, 30)]


def test_answers_read_well_in_slack(tmp_path):
    b = bot(tmp_path)
    m = lambda id, status, ev: {"id": id, "type": "decision", "status": status, "as_of": "2026-03-09", "evidence": [ev]}
    slack_ev = {"quote": "going with <$5>", "author": "Ana Ruiz", "ref": f"C1:{T0:.6f}", "source_title": "#product",
                "source_kind": "slack", "held_on": "2026-03-04"}
    meet_ev = {"quote": "six dollars", "author": "Ben Cho", "ref": "", "source_title": "Weekly sync",
               "source_kind": "meeting", "held_on": "2026-03-02"}
    text = b.format({"answer": "**$5 now** [M7], was $6 [M3][M99].\n- see above",
                     "memories": [m(7, "active", slack_ev), m(3, "superseded", meet_ev)]})
    assert text.startswith("*$5 now* [1], was $6 [2].\n• see above")
    assert "*[2]* Decision · Mar 9, 2026 · _replaced later_" in text
    assert f"<https://team.slack.com/archives/C1/p{T0 * 1e6:.0f}|#product>" in text
    assert "“going with &lt;$5&gt;” — Ana Ruiz" in text
    assert "Weekly sync (Mar 2, 2026)" in text


def test_help_when_there_is_no_question(tmp_path):
    assert "/muninn" in bot(tmp_path).answer("<@UMUNINN>  ")


def stub_slack_api(monkeypatch, sent):
    """Answer every slack_sdk WebClient call from FakeSlack (Bolt makes its own clients, so patch the class)."""
    from slack_sdk import WebClient
    from slack_sdk.web import SlackResponse

    fake = FakeSlack()

    def api_call(self, api_method, *, http_verb="POST", files=None, data=None, params=None, json=None, **_):
        args = {**(params or {}), **(data or {}), **(json or {})}
        sent.append((api_method, args))
        body = {"ok": True, "ts": "1.0"}
        if api_method == "auth.test":
            body.update(fake.auth_test())
        elif api_method == "conversations.info":
            body.update(fake.conversations_info(args["channel"]))
        elif api_method == "users.info":
            body.update(fake.users_info(args["user"]))
        return SlackResponse(client=self, http_verb=http_verb, api_url=api_method, req_args=args,
                             data=body, headers={}, status_code=200)

    monkeypatch.setattr(WebClient, "api_call", api_call)
    return WebClient(token="xoxb-test")


def dispatch(app, body):
    from slack_bolt.request import BoltRequest

    return app.dispatch(BoltRequest(body=body, mode="socket_mode"))


def event(e):
    return {"type": "event_callback", "team_id": "T1", "api_app_id": "A1", "event": e, "event_id": "Ev1",
            "event_time": 1}


def test_bolt_wiring_answers_mentions_and_keeps_messages(tmp_path, fake, monkeypatch):
    from muninn.slack import build_app

    monkeypatch.setattr("muninn.slack.ask", lambda llm, store, q: {"answer": f"You asked: {q}", "memories": []})
    sent = []
    app, b = build_app(fake(), tmp_path / "test.db", "xoxb-test", log=lambda m: None,
                       client=stub_slack_api(monkeypatch, sent))
    dispatch(app, event({"type": "app_mention", "user": "U1", "text": "<@UMUNINN> pricing?", "ts": "5.0", "channel": "C1"}))
    dispatch(app, event(msg(0, "We're going with $5.")))
    eventually(lambda: [(m, a.get("text")) for m, a in sent if m.startswith("chat.")] ==
               [("chat.postMessage", "_checking the receipts…_"), ("chat.update", "You asked: pricing?")])
    eventually(lambda: waiting(b) == [f"{T0:.6f}"])


def eventually(check, seconds=3.0):
    """Bolt runs listeners on its own threads."""
    import time

    deadline = time.time() + seconds
    while not check():
        assert time.time() < deadline, "listener didn't finish"
        time.sleep(0.02)
