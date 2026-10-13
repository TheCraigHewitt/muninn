# Bruh | Product Requirements Document

Open-source organizational memory • PRD v0.2 • October 2026

> Terms in **bold** are defined in [`CONTEXT.md`](../CONTEXT.md), and design decisions are recorded in [`docs/adr/`](./adr/).

## Executive summary

Bruh is an open-source, self-hostable organizational memory service. It continuously turns authorized Slack discussions, meeting transcripts and **Agent Reports** into a cited, evolving record of **Decisions**, **Rationale**, **Commitments**, **Facts**, **Proposals** and open **Questions**. People and AI **Agents** can ask what was decided, why, and what changed. Agents can also contribute what they learn.

Positioning: "Your company talked about it. Bruh remembers."

Bruh is a **shared context layer for people and Agents**. Teams talking in Slack and meetings is the first use case. A group of Agents that need durable, trustworthy, permission-aware organizational context is potentially a much larger market. v0.1 proves the human use case and builds the Agent model into the core, so it doesn't have to be retrofitted later.

Strategy: open source first (Apache-2.0). Prove usefulness and trust in a real pilot organization and build community adoption. A commercial hosted service may come later.

## Problem and opportunity

Important context is scattered across chat threads and meetings. Search finds messages but rarely reconstructs decisions, rationale, changes or current state. Manual documentation goes stale, and meeting notes end up as isolated documents.

Agents make this worse. Every Agent starts with no context, re-derives what the organization already decided, and its own findings disappear when its session ends.

Differentiator: a model of organizational decisions that tracks change over time and backs every claim with Evidence, shared by people and Agents under the same access rules. It is not another chatbot over vectorized messages, a meeting summarizer, or an Agent scratchpad.

## Audience and jobs to be done

### Primary users

- Small and midsize organizations with active Slack workspaces and recurring meetings.
- Founders, managers, product and engineering teams, and new hires who need decision context.
- AI Agents (coding, support, research, ops) that need organizational context before acting, and that have findings worth keeping.

### Core jobs

- "What did we decide about X, and why?"
- "Has our position on X changed since March?"
- "Who committed to Y, and is it resolved?"
- "What unresolved questions remain about Project Z?"
- *(Agent)* "What has the organization already decided that bears on the task I'm about to do?"
- *(Agent)* "Record what I found and what I recommend, so the next person or Agent doesn't start from zero."

## Product principles

- **No manual upkeep** after authorized connections and initial setup. Explicit **Markers** are optional helpers, never required.
- **Citations first.** Every substantive claim can be traced to permissible Evidence. Bruh never records a Memory without Evidence.
- **History is preserved.** Bruh never silently overwrites past positions. Changes are new Memories linked by **Supersedes**, and corrections are citable **Admin Rulings**. The one deliberate exception is deletion: when a Source is deleted, everything derived from it is erased (ADR-0003).
- **Only people make Decisions.** Jokes, sarcasm, hypotheticals and Agent statements never become Decisions (ADR-0007).
- **Access is enforced at every layer**: ingestion, storage, retrieval and output. An answer is never wider than its **Answer Audience** (ADR-0004), and a restricted Memory never leaks through a status, Topic label or Agent Report (ADR-0002, ADR-0008).
- **No DMs**, including Slack direct and group messages.
- **Durable memory only.** Bruh stores what will still matter next week, not Agents' working state (ADR-0006).
- **Works fully when self-hosted.** No mandatory hosted account or proprietary API. Model providers can be swapped, and local inference is supported.

## MVP scope: v0.1

### Included

- Self-hosted Docker Compose install with guided environment setup.
- One **Organization** and one Slack **Workspace** per install.
- **Slack:** admin-selected public channels, with threads, initial backfill and incremental sync. Full (non-guest) members only.
- **Google Meet Meeting Series:** an admin opts in a recurring Google Calendar meeting (identified by its calendar event ID, never its title). Every meeting in the series is ingested automatically under the Access Scope set once for the series. To opt out of one meeting, delete it afterwards.
- **Transcript upload** and a generic ingestion API, plus a documented script that turns a Granola export into an API upload.
- Grouping messages into **Discussions** using a model, with Threads and Conversation Windows as hints.
- Extracting Decisions, Rationale, Commitments, Facts, Proposals and Questions, with a sincerity check and **Confidence**-based routing.
- Admin-configurable **Markers** (emoji reactions and phrases) that signal intent on purpose.
- Links from every Memory to exact Evidence, change tracking over time, and reversals via Supersedes.
- A minimal **Review Queue**: users **Flag** Memories, and admins settle disputes and low-confidence changes with Admin Rulings, including Topic and Entity merges and splits.
- A web query UI with citations.
- A Slack Q&A bot. In-channel answers are limited to what the whole channel can see. A slash command gives an ephemeral answer using the asker's full access.
- A permission-aware MCP server and REST API: read tools plus one write tool, `submit_agent_report`.
- **Agents** as Principals, using admin-issued tokens and an optional on-behalf-of human.
- Sign in with Slack, plus one bootstrap admin account.
- Channel allowlist, deletion, resync and retention controls, and basic audit logging.
- Pluggable model and embedding adapters. Local inference is possible but not required.

### Excluded from v0.1

- Native Teams sync, Zoom, automatic Granola sync, and calendar-driven import of meetings that aren't a Meeting Series.
- Slack private channels, Slack Connect (externally shared) channels, and guest access.
- DM ingestion, bots that join or record meetings, and proactive interruptions.
- Agents making Decisions, and Agent working state (task queues, scratchpads, locks).
- A full knowledge-graph UI, BI dashboards and workflow execution.
- Hosted SaaS, enterprise SSO/SCIM, and multiple Organizations or Workspaces per install.

## Critical user journeys

1. An admin installs Bruh, connects Slack with least-privilege permissions, and chooses eligible public channels.
2. An admin opts in the weekly team meeting as a Meeting Series scoped to the whole Workspace. Every following week's transcript arrives automatically. One week's meeting gets into something sensitive, and the admin deletes it, which erases it from Bruh entirely.
3. An admin uploads a one-off transcript, listing the attendees as its Access Scope. Bruh extracts Memories and cites timestamped snippets.
4. A user asks "Why did we reject the public API?" They get the latest conclusion they're allowed to see, its Rationale, and links to the supporting messages.
5. A later Discussion reverses an old Decision. Bruh keeps the history and points to the superseding Evidence.
6. Someone posts "oh sure, let's rewrite it all in Rust 🙃". Bruh records nothing.
7. A user loses access to a channel. Its Evidence and the Memories derived from it disappear from that user's results.
8. A coding Agent queries Bruh before changing the webhook system, learns that v1 webhooks are scheduled for deprecation, and files an Agent Report with its findings and a recommendation. The recommendation becomes a Proposal. It becomes a Decision only when a person endorses it.
9. A user Flags a Memory that misread a hypothetical. An admin withdraws it with an Admin Ruling, and the correction is visible and citable.

## Functional requirements

### P0

- Channel allowlist and opt-in permissions, with no DM scopes. Opt-in for Meeting Series.
- Backfill, incremental ingestion, idempotency and source timestamps.
- Grouping into Discussions, with gap and size limits configurable per install.
- Extraction of single, self-contained Memories with Evidence spans, a sincerity check, Confidence and Markers.
- Deduplication of Topics and Entities, and reconciliation of Memories (Supports, Contradicts, Supersedes, Resolves, Explains).
- Retrieval that filters by permission and works out status and Topic labels for each viewer, with answers full of citations.
- Answer Audience enforcement on every surface.
- An Agent Report write path with an Access Scope ceiling (ADR-0008), rate limits, and a lower ranking weight for Agent-authored Evidence.
- ACL refresh, edits that withdraw Memories, deletes that erase them, retention controls, and prompt-injection defenses.
- A minimal Review Queue: Flag, and Admin Ruling.
- An evaluation harness covering answer fidelity, chronology, sincerity and access leaks.

### P1

- A richer review experience, and self-serve correction.
- Better Slack bot experience, and navigating by Entity and Topic.
- More connectors: Zoom, Granola (Enterprise shared folders map onto Meeting Series), Teams, Slack private channels.
- Admin observability dashboards.
- Decision authority for individual Agents, as an admin opt-in.

## Nonfunctional requirements

- **Security:** strict scoping by Organization, encryption in transit, secrets via environment or a secret store, minimal scopes, restricted logs, and auditing of sensitive access.
- **Privacy:** raw conversations stay under the user's control. Deletion erases everything derived from a Source. When retention expires, the full Source is dropped and only the cited Evidence spans are kept (ADR-0009), and admins can make expiry erase everything.
- **Reliability:** incremental jobs can be retried safely, failed processing never loses events, and admins can see connector outages.
- **Performance targets for the pilot** (proposed, not yet validated): 95% of new messages processed within 10 minutes, and typical questions answered within 10 seconds.
- **Accuracy:** answers flag uncertainty and decline to answer when citations don't support a claim. Confidence drives routing internally and is never shown as a number.

## Success metrics and acceptance criteria

- **Pilot:** replay 90 days of permitted Slack history from the pilot organization, plus its weekly team meeting as a Meeting Series and a representative set of transcripts. Connect at least one real Agent that reads Bruh and files Agent Reports.
- Curate at least 20 answerable questions, plus negative tests and permission tests. Judge correctness, citations, change tracking and refusals manually.
- **Provisional release gates:** at least 85% fully supported answers on the curated answerable questions, at least 95% correct citations, zero confirmed unauthorized disclosures, and no high-confidence false reversals in a dedicated reversal test suite. Calibrate the thresholds after baseline testing.
- **Any single failure of the following blocks release:**
  - A Decision invented from sarcasm, a joke or a hypothetical.
  - A Decision produced from an Agent Report.
  - Restricted information passed into an Agent Report's scope.
  - An in-channel bot answer exceeding its Answer Audience.
  - A Topic label or status leaking restricted information.
  - Any DM ingestion.
- **Qualitative signal:** people and Agents repeatedly retrieve decisions they would otherwise have asked colleagues to reconstruct.

## Open source and commercialization

- License: **Apache-2.0** (ADR-0010). Every dependency must be compatible with it.
- Publish the code, schemas, migrations, connector SDK, extraction and reconciliation logic, and core retrieval.
- Provide local deployment and optional local-model setup, with no vendor-hosted control plane.
- Any later managed service would charge for hosting, setup, scaling, managed integrations, backups, monitoring and enterprise administration. Core memory functionality is never held back.

## Risks, mitigations and open questions

- **Invented or premature decisions** (main risk). Mitigations: the Proposal/Decision distinction, the sincerity check, Decisions only from people, Confidence routing, the Review Queue, and release-blocking sarcasm tests.
- **Access leaks through derived data.** Mitigations: Memories that each belong to one scope (ADR-0001), status and Topic labels worked out per viewer (ADR-0002), Answer Audience (ADR-0004), and the Agent Report scope ceiling (ADR-0008). Bruh can't see what an Agent learned outside Bruh, and the guide says so.
- **Discussion grouping is hard.** A model does the grouping, the gap and size limits are configurable, and grouping can be revised as messages arrive.
- **Matching identities across sources.** Bruh starts with explicit mappings and conservative defaults. Transcript speakers are never matched to people by name guessing.
- **Recording consent.** Bruh doesn't record anything itself. It only ingests transcripts the meeting platform already made. The setup guide recommends adding a notice to calendar invites for each Meeting Series.
- **Open:**
  - Confidence thresholds (starting at 0.6 and 0.85)
  - Discussion gap and size defaults (starting at 2 hours and 200 messages)
  - the ranking weight for Agent-authored Evidence
  - Slack backfill limits under real workspace policies
  - model routing for privacy-sensitive installs
