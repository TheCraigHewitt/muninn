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

## Status

Bruh is in the **design stage**. There's no code yet. The design is captured in:

| Document | What it covers |
|---|---|
| [`docs/PRD.md`](docs/PRD.md) | Product requirements: problem, audience, v0.1 scope, release gates |
| [`docs/TECH_SPEC.md`](docs/TECH_SPEC.md) | Architecture, data model, pipeline, permissions, API, connectors, test plan |
| [`CONTEXT.md`](CONTEXT.md) | Glossary of the domain language used everywhere else |
| [`docs/adr/`](docs/adr/) | Architecture decision records for the choices that would be costly to undo |

Feedback on the design is welcome. Please open an issue.

## License

[Apache-2.0](LICENSE)
