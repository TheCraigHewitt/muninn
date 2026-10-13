# Bruh

**Your company talked about it. Bruh remembers.**

Bruh is an open-source, self-hostable organizational memory. It turns authorized Slack discussions, meeting transcripts and reports from AI agents into a cited record of what your organization **decided**, **why**, who **committed** to what, and what's still **open**, and it tracks how all of that changes over time.

People ask questions like "Why did we reject the public API?" or "Has our position on pricing changed since March?" and get answers backed by citations, limited to what they're allowed to see. AI agents use the same memory, under the same access rules, to get context before acting and to record what they found.

## Principles

- **Citations first.** Every claim traces back to the exact message or transcript span it came from.
- **History is preserved.** A reversed decision is never overwritten. Bruh keeps both the old decision and the evidence that replaced it.
- **Only people make decisions.** Jokes, hypotheticals and statements made by agents never become decisions.
- **Access is enforced at every layer.** An answer never reveals anything that someone who will see it isn't allowed to see.
- **No DMs.** Ever.
- **Self-hosted by default.** No mandatory hosted account, swappable model providers, and local inference supported.

## Try it

You need [uv](https://docs.astral.sh/uv/) and an [Anthropic API key](https://console.anthropic.com/).

```sh
git clone https://github.com/TheCraigHewitt/bruh && cd bruh
cp .env.example .env            # then paste your API key into .env
uv run --env-file .env bruh ingest path/to/transcripts/*.txt path/to/slack-export
uv run --env-file .env bruh serve
```

Then open http://127.0.0.1:8765, ask a question, browse Topics to see how decisions changed, and confirm anything waiting in Review.

**What it reads**

- **Meeting transcripts** as `.txt`, one turn per line (`Speaker: words`, optionally `[00:01:41] Speaker: words`). The header that meeting-notes apps export (`Meeting Title:`, `Date:`, `Meeting participants:`, then `Transcript:`) is understood. Put the date in the file name (`standup-2026-03-02.txt`) so Bruh knows when it happened.
- **Slack exports.** In Slack, go to *Workspace settings → Import/Export Data → Export*, unzip the result, and point Bruh at the folder or at individual channel folders.

Everything Bruh stores (the database, cached model responses, a usage log) lives in `data/`, which git ignores. `uv run bruh spend` shows what model calls have cost so far.

**Other commands:** `bruh ask "question"` answers in the terminal, `bruh review` lists what's waiting for confirmation, and `bruh eval` runs the extraction checks in `eval/fixtures/`.

## Status

**v0, local and single-user.** [`docs/V0.md`](docs/V0.md) explains what v0 does and how it differs from the full design.

| Document | What it covers |
|---|---|
| [`docs/V0.md`](docs/V0.md) | The local version: what it does, what it leaves out, and rules learned from real data |
| [`docs/PRD.md`](docs/PRD.md) | Product requirements: problem, audience, v0.1 scope, release gates |
| [`docs/TECH_SPEC.md`](docs/TECH_SPEC.md) | The full design: architecture, data model, pipeline, permissions, API, connectors |
| [`CONTEXT.md`](CONTEXT.md) | Glossary of the domain language used everywhere else |
| [`docs/adr/`](docs/adr/) | Architecture decision records for the choices that would be costly to undo |

## Development

```sh
uv run pytest          # offline tests, no API calls
uv run --env-file .env bruh eval   # extraction checks against the real model
```

Feedback is welcome. Please open an issue.

## License

[Apache-2.0](LICENSE)
