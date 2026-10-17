# Muninn | Developer Specification

Architecture and implementation contract • v0.2 • October 2026

> Vocabulary follows [`CONTEXT.md`](../CONTEXT.md), and design decisions are recorded in [`docs/adr/`](./adr/). Product requirements are in [`PRD.md`](./PRD.md).

## Scope and system boundaries

This is the reference implementation for Muninn v0.1. It is a self-hosted service for a single Organization and a single Slack Workspace, and it includes:

- a Slack connector for selected public channels
- a Google Meet connector for **Meeting Series**
- transcript upload and API
- an Agent Report write path
- the memory engine, which tracks change over time
- permission-aware query
- a web UI, a Slack bot, and an MCP server

Running as a hosted service with multiple Organizations is not required yet, but every table carries `org_id`.

**Trust boundary:** outside text (Slack messages, transcripts, Agent Reports) never becomes system instructions. There are no DM scopes and no way to ingest DMs.

## Reference architecture

```
Connectors (Slack, Meet, transcript API, Agent Reports, Admin Rulings)
  → ingestion queue
  → immutable Sources + Source Revisions
  → Discussion grouping (grouping model)
  → extraction (sincerity check → typed candidate Memories + Confidence)
  → Topic / Entity resolution
  → reconciliation
  → Memories (each in one scope) + relationships + status events
  → retrieval scoped to each viewer (scope check, per-viewer status and labels, Answer Audience)
  → answer service → web / Slack bot / REST / MCP
```

**Stack:** Python FastAPI; PostgreSQL with pgvector and full-text search; Redis with RQ or Celery-style workers; React or a minimal server-rendered UI; Docker Compose.

Postgres is the source of truth. Redis is disposable infrastructure. Optional source files go in blob storage or the filesystem, referenced from Postgres. Transcripts are stored as text only, with no audio or video.

### Model roles

The model interface defines two roles. Each one can be pointed at a hosted or local endpoint independently.

- **Grouping and triage model:** cheap, high-volume work. It groups messages into Discussions, classifies sincerity, and discards chatter. Most messages produce no Memory, so this model filters out most of the work.
- **Extraction and answer model:** the work that needs heavier reasoning, namely extraction, reconciliation proposals and answer generation.

Local models are optional. When **local-only mode** is on, both roles must point at local endpoints and Muninn makes no outbound model or telemetry calls. A test enforces this.

## Data contracts

### Organization, Workspace and identity

- **Principal:** `principal_id, org_id, kind (human | agent), display_name, disabled_at`.
  - A human Principal links to a full (non-guest) Workspace member through Sign in with Slack.
  - An agent Principal carries admin-set grants.
- **Agent token:** `token_id, agent_principal_id, on_behalf_of_principal_id (nullable), issued_by, expires_at, revoked_at`.
- **Person:** `person_id, org_id, display_name, slack_user_id (nullable), principal_id (nullable)`. A Person is a human who appears in Evidence, and is also an Entity.
- **Author:** a Person or an agent Principal. Evidence and Commitment ownership refer to an Author: `author_kind, author_id`.
- **Speaker mapping:** transcript speaker labels map to Persons only through explicit mappings, set at upload time or on the Meeting Series. There is no name-based guessing.

### Access

- **Access Scope:** `access_scope_id, org_id, kind (workspace | channel | principal_list | meeting_series | agent_report), ref, policy`.
  - For a public channel, the scope is every full Workspace member.
  - For a transcript, it is either a list of named Principals (always including the uploader) or the whole Workspace.
  - For a Meeting Series, it is fixed when the series is opted in.
- **Access membership:** synchronized membership snapshots with a version number, cached with a short time limit and checked at query time.

### Sources

- **Source:** `source_id, org_id, connector_type, external_id, source_kind (slack_message | transcript | agent_report | admin_ruling), source_uri, created_at, updated_at, observed_at, access_scope_id, content_hash, deleted_at, retention_expires_at`. Unique on `(org_id, connector_type, external_id)`.
  - A Slack message is one Source, with external ID `channel_id:ts`.
  - A transcript is one Source.
  - An Agent Report is one Source.
- **Source Revision:** `source_revision_id, source_id, revision_no, content, observed_at, content_dropped_at`. Every edit creates a new revision.
- **Meeting Series:** `meeting_series_id, org_id, calendar_id, recurring_event_id, organizer_identity, access_scope_id, speaker_mappings, enabled_by, enabled_at, disabled_at`. The series is identified by its recurring Google Calendar event ID, never by title.
- **Agent session read log:** `session_id, agent_token_id, read_scope_ids[], started_at`. This is used to enforce the Agent Report scope ceiling.

### Discussions and Evidence

- **Discussion:** `discussion_id, org_id, access_scope_id, source_ids[], grouping_run_id, hints (thread_ts, window_id), status (open | closed), last_activity_at`. A Discussion never spans more than one Access Scope. Grouping can be revised, and a late message can join an existing Discussion.
- **Evidence:** `evidence_id, source_id, source_revision_id, discussion_id, author_kind, author_id, event_time, locator (message ts, or start/end offsets plus timestamps), exact_text, sincerity (sincere | hypothetical | joking | quoting), access_scope_id, checksum, withdrawn_at, deleted_at`. `exact_text` is kept after Retention Expiry (ADR-0009).

### Memory

- **Memory:** `memory_id, org_id, type, subject, statement, access_scope_id, topic_id, confidence, confidence_reason, valid_from, valid_to, recorded_at, extraction_run_id, deleted_at`.
  - Types: `decision, rationale, fact, commitment, proposal, question`.
  - `statement` never changes after insert.
  - All of a Memory's Evidence shares its `access_scope_id` (ADR-0001).
  - `valid_from` and `valid_to` are when the claim holds in the world. `recorded_at` is when Muninn recorded it.
  - Commitments add `owner_author_kind, owner_author_id`.
- **Memory status event:** `memory_id, status, effective_at, recorded_at, cause (edge_id | admin_ruling_id | source_edit | extractor_revision)`.
  - Statuses: `proposed, active, disputed, superseded, resolved, withdrawn`.
  - The stored status is the view of someone who can see everything. Each viewer's status is worked out at query time (ADR-0002).
- **Relationship:** `edge_id, from_memory_id, to_memory_id, relation, confidence, rationale, evidence_ids, created_at`. Relations:
  - `SUPPORTS`: corroboration
  - `CONTRADICTS`
  - `SUPERSEDES`
  - `RESOLVES`: closes a Commitment or a Question
  - `EXPLAINS`: links a Rationale to a Decision or Proposal
  - `RELATES_TO`
- **Topic:** `topic_id, org_id, canonical_key`. There is no stored display label. Labels are generated for each set of visible scopes and cached by scope-set key.
- **Entity:** `entity_id, org_id, kind (person | product | customer | project | other), canonical_name, aliases`.

### Oversight

- **Flag:** `flag_id, memory_id, principal_id, reason, created_at, resolved_by_ruling_id`.
- **Review item:** `review_id, kind (low_confidence_transition | contradiction | flag | scope_widening | merge_split), subject_ids, created_at, resolved_at`.
- **Admin Ruling:** stored as a Source with `source_kind = admin_ruling`. It is reconciled like any other Source and can cite the Memories it affects.
- **Marker config:** `marker_id, org_id, kind (reaction | phrase), value, signals (decision | commitment_done | question | …), enabled`.

### Recommended tables

`organizations, principals, agent_tokens, agent_sessions, persons, entities, connectors, meeting_series, sources, source_revisions, discussions, evidence, topics, topic_label_cache, memories, memory_status_events, memory_entities, memory_evidence, memory_relationships, access_scopes, access_memberships, markers, flags, review_items, extraction_runs, grouping_runs, processing_jobs, audit_events, tombstones`.

**Indexes:**

- external ID, unique per connector
- `event_time`
- `topic_id` with the current status
- vector ANN, applied only to candidates that pass the permission check
- tsvector for keyword search
- `access_scope_id` on every table that can be retrieved

Every query is strictly scoped by `org_id`.

## Ingestion pipeline

1. **Connect and receive.**
   - The Slack connector backfills allowlisted public channels and consumes authorized updates. The server rejects DM, group-DM and Slack Connect events even if they arrive by accident. Messages from guests are ingested as Evidence, but guests never become Principals.
   - The Meet connector watches each Meeting Series and pulls each meeting's transcript once it is available.
   - Transcripts and Agent Reports arrive through the API.
2. **Normalize and upsert** by external ID and revision. Store the minimum user information necessary.
3. **Attach the Access Scope.**
   - Transcripts are denied to everyone until a scope is set.
   - A Meeting Series meeting inherits the series scope.
   - An Agent Report's scope is capped at the narrowest scope the session has read (ADR-0008). A request to widen it goes to the Review Queue.
4. **Group into Discussions** with the grouping model.
   - Threads and Conversation Windows are hints, not boundaries. Defaults are a 2-hour quiet gap and 200 messages, configurable per install.
   - Never group across Access Scopes.
   - When a message joins a Discussion that has already been processed, re-read that whole Discussion.
5. **Create Evidence** with stable locators and hashes, aligned to messages and sentences.
6. **Classify sincerity** for each Evidence span. Non-sincere Evidence (hypothetical, joking, quoting) produces no Memory.
7. **Extract** typed candidate Memories as structured output, validated against a JSON Schema, each with Confidence and a reason. Apply Marker signals as Confidence boosts. They never override the sincerity check.
8. **Resolve Topics and Entities** using deterministic rules, retrieval and model-assisted candidate selection, with conservative merge thresholds.
9. **Reconcile** (next section) and persist the new Memories, edges and status events in one transaction.
10. **Publish** the indexed records. Periodically reconcile connector edits, deletions and access changes.

### Confidence routing

| Candidate | Confidence < 0.6 | 0.6 to 0.85 | ≥ 0.85 |
|---|---|---|---|
| Any type | Not recorded | Recorded | Recorded |
| Decision or Supersedes | Not recorded | `proposed`, sent to the Review Queue | `active` |

The thresholds are starting values, calibrated in Phase 4.

### Agent Report rules

- Agent Evidence can produce Proposals, Facts, Questions, Rationale, and Commitments owned by the Agent. It never produces Decisions (ADR-0007).
- A person can promote an Agent Proposal to a Decision by endorsing it, with a Decision Marker or an "agreed" reply. That endorsement is human Evidence.
- Rate limits apply per Agent.
- Ranking gives Agent-authored Evidence a lower weight, configurable per install.

## Reconciliation algorithm

1. Retrieve the nearest existing Memories in the same Topic, using keywords, vectors and Entity IDs, within the same Organization.
2. The extraction model proposes one of `NEW, SUPPORTS, CONTRADICTS, SUPERSEDES, RESOLVES, EXPLAINS, DUPLICATE, NEEDS_REVIEW`, with Evidence IDs and an explicit rationale.
3. Validate the proposal deterministically:
   - the Evidence exists
   - the chronology is consistent
   - the status transition is allowed
   - no self-cycles
   - no Decision without human Evidence
   - no unsupported inferred decisions
4. A `DUPLICATE` in the **same** scope adds the new Evidence to the existing Memory. A duplicate in a **different** scope creates a new Memory with a `SUPPORTS` edge (ADR-0001).
5. When uncertain, mark the Memory `disputed` or `proposed` instead of changing an active Decision. Create a review item, and have answers present both positions with a caveat.
6. Never change a Memory's statement. Every change is a new Memory, a new edge or a new status event.
7. **Re-extraction** after a model or prompt change is started manually by an admin and never runs automatically. It reconciles into the existing Memories, and the resulting changes are recorded with cause `extractor_revision`.

## Edits, deletes and retention (ADR-0003, ADR-0009)

- **Edit:** a new Source Revision. Evidence citing the old revision is withdrawn and the Discussion is re-read. A Memory with no Evidence left gets a `withdrawn` status event and stays in history.
- **Delete** (from the connector, the API or an admin): tombstone the Source and erase its revisions, Evidence, embeddings, and any Memory left without support, with no history. Recompute the support that remains, invalidate caches, and propagate the deletion to backups according to the retention policy. Deleting a single Meeting Series meeting is how an admin opts out of it.
- **Retention Expiry:** by default, drop the content of the Source Revisions but keep `exact_text` for cited Evidence. A per-channel or per-transcript setting makes expiry erase everything, the same as a delete.

## Retrieval and authorization

- Authenticate the Principal on every endpoint. Resolve which scopes the Principal can see from synchronized membership data, using a cache that is invalidated when access is revoked.
- **Agent access:** an agent Principal's grants. When the token has an on-behalf-of human, use the *intersection* of the Agent's grants and that human's access.
- **Answer Audience** (ADR-0004): the set of scopes visible to *every* Principal who will see the answer.
  - For the web UI, MCP, REST, and ephemeral Slack answers, it's the asker.
  - For in-channel Slack answers, it's every member of the channel.
  - For Agent output that will be shared, it's the declared audience.
- **Hybrid recall:** full-text and vector candidates filtered by Answer Audience, expanded along the Topic graph to neighboring Memories in time, then reranked by relevance, recency, strength of Evidence and Author kind.
- **Per-viewer views** (ADR-0002):
  - Status is worked out only from edges whose two Memories are both visible.
  - A Topic is visible only if at least one of its Memories is visible.
  - Topic labels are generated from visible Memories only.
  - Autocomplete only matches visible labels.
- Every Memory consumed by an Agent session is logged, which is how the Agent Report scope ceiling is enforced.
- The answer prompt includes only permitted passages and Memory records, with source text escaped and tool contexts isolated. Every material claim cites a source, a message and a timestamp. If a claim can't be justified, express uncertainty or decline to answer. Show answers as "decided" or "proposed", never as Confidence numbers.

## API surface

| Endpoint | Purpose |
|---|---|
| `POST /v1/transcripts` | Metadata, text, timestamps, explicit Access Scope, speaker mappings, idempotency key |
| `POST /v1/agent-reports` | Agent token auth. Body, optional narrower scope, session ID. Scope ceiling enforced |
| `GET /v1/memories`, `GET /v1/topics/{id}` | Views filtered by the Answer Audience |
| `POST /v1/query` | Question, optional Topic or time filters, optional audience. Returns answer, citations and uncertainty |
| `GET /v1/sources/{id}`, `DELETE /v1/sources/{id}` | Source metadata after the scope check. Delete tombstones the Source and erases everything derived from it |
| `POST /v1/memories/{id}/flags` | Flag a visible Memory |
| `GET/POST /v1/review` | Admin Review Queue, and creating Admin Rulings (including merges and splits) |
| `GET/POST/DELETE /v1/meeting-series` | Admin: opt a recurring calendar event in or out |
| `GET/PUT /v1/markers` | Admin: Marker configuration |
| `POST /v1/connectors/slack/sync`, `GET /v1/jobs/{id}` | Admin sync and monitoring |
| `POST /v1/admin/reextract` | Admin: start re-extraction manually |

**MCP tools** (each bound to the authenticated Principal or Agent token):

- `search_memory`, `get_topic_history`, `get_memory_evidence`: read tools.
- `submit_agent_report`: the only write tool.

**Slack bot:**

- When mentioned in a channel, it answers in the channel, limited to the channel's audience.
- A `/muninn` slash command gives an ephemeral answer using the asker's full access.

## Connectors

- **Slack:** bot scopes `channels:read`, `channels:history` and `users:read` (plus `channels:join` only if the bot joins channels itself). Never request DM or group-DM scopes. The bot must be a member of each allowlisted channel. Incremental sync uses `message.channels` events (including the `message_changed` and `message_deleted` subtypes), plus `channel_shared`/`channel_unshared`, `user_change`, `user_guest_status_changed` and `team_join`. Reject any event whose `channel_type` isn't `channel`, and any channel flagged `is_private`, `is_im`, `is_mpim`, `is_ext_shared` or `is_pending_ext_shared`. Backfill can't reach history a free-plan workspace hides (older than 90 days). See [research](research/slack-backfill-and-meet-transcripts.md). Private channels stay disabled until the access logic is verified, and are then opted in one at a time (P1).
- **Google Meet (Meeting Series):** an admin opts in a recurring Calendar event. The organizer authorizes an Internal OAuth app (offline access) with `calendar.events.owned.readonly` and `meetings.space.readonly`. The connector lists the series' meetings with `events.instances`, matches each to a Meet conference record by meeting code and start time (and stores the meeting space name, because meeting codes can be reused), and reads the transcript entries. Each entry's participant ID maps to a Person through the series' speaker mappings. The Meet API deletes transcript entries 30 days after a meeting, so the connector must poll within that window. Its fallback for older meetings reads the transcript Google Doc with `documents.readonly`. `drive.file` can't see that Doc, and broader Drive scopes need Google's restricted-scope review. Meet transcription needs Google Workspace Business Standard or higher. See [research](research/slack-backfill-and-meet-transcripts.md).
- **Granola (v0.1):** a documented script turns a Granola export into a `POST /v1/transcripts` call, with the person running it setting the Access Scope. Automatic Granola sync is P1. Granola's API is Enterprise-only and only covers shared folders. Those folders would map onto Meeting Series.

## Security and privacy implementation

- **Sign-in:** Sign in with Slack (OpenID Connect, `openid profile email`) for human Principals. OIDC doesn't reveal guest status, so after sign-in Muninn checks the workspace ID claim and calls `users.info` (`is_restricted`, `is_ultra_restricted`) to confirm the user is a full member. Guests can't get a Principal. One bootstrap admin account is used for setup. Agents use admin-issued, revocable tokens. The Slack bot verifies Slack's request signatures and maps Slack IDs to Principals.
- Track the Access Scope behind every Memory. When source permissions change, revoke access through derived indexes and invalidate caches, including the Topic label cache.
- Treat every piece of outside text, Agent Reports included, as untrusted. Defend against prompt injection, and never follow instructions that come from a connector.
- Encryption at rest depends on how the host's storage is configured. Support external secrets and TLS. Logs record identifiers, never the text of conversations.

## Deployment and operations

- **Docker Compose services:** `api, worker, postgres/pgvector, redis, frontend`, plus an optional inference adapter.
- **Config:** Slack credentials, Google credentials, DB URI, model endpoints for each role, local-only mode, embedding dimensions, Discussion gap and size, Confidence thresholds, Agent ranking weight, rate limits, admin policies, retention settings. Ship `.env.example`, migrations, a bootstrap CLI, health checks, and backup and restore guidance.
- **Metrics:**
  - ingestion lag
  - grouping and extraction failures
  - reconciliation conflicts
  - Review Queue depth
  - age of the last source permission sync
  - Meeting Series fetch failures
  - query latency
  - rate of uncited answers
  - denied-access events
  - attempts to widen an Agent Report's scope
- Retry with exponential backoff, and move failing jobs to a dead-letter state. Event idempotency prevents duplicate Evidence or Memories when a connector retries.

## Testing and quality gates

- **Unit:**
  - extraction schema validation
  - sincerity classification
  - status transition rules
  - graph cycle safeguards
  - idempotency
  - ACL intersection, including on-behalf-of
  - per-viewer status and label calculation
  - Agent Report scope ceiling
  - edits that withdraw versus deletes that erase
  - retention keeping cited spans
- **Integration:**
  - Slack thread edits and deletes
  - Discussion regrouping when a late message arrives
  - access revocation
  - transcript upload
  - Meeting Series ingestion and deletion of a single meeting
  - Agent Report round trip
  - model failure and retry
  - citation locators
- **Adversarial:**
  - prompt injection in Slack messages and Agent Reports
  - restricted information paraphrased into derived Memories
  - stale membership cache
  - privilege escalation through MCP or an on-behalf-of token
  - laundering through an Agent Report's scope
  - in-channel bot answers exceeding the channel audience
  - Topic label and status leaks
- **Evaluation set:**
  - at least 20 real questions from the pilot organization
  - curated chronology contradictions
  - sarcasm and hypothetical cases taken from the pilot organization's real messages
  - Agent scenarios
  - probes for unauthorized access

  Report accuracy, Evidence precision, refusal rate and reversal accuracy.

**Do not ship** until the no-DM tests, the access-leak tests and every release-blocking case in the PRD pass.

## Implementation phases

1. **Phase 0: foundation.** Repo, a check that every dependency is compatible with Apache-2.0, data schemas, Docker setup, Sign in with Slack, Principals and Agent tokens, ACL design and test harness. Confirm that every meeting in a recurring series shares one meeting code, and that the Slack app counts as internal for rate limits.
2. **Phase 1: ingestion.** Selected public Slack channels, revision tracking, the transcript API and Granola script, Meet Meeting Series, Evidence creation, and the retention, edit and delete paths.
3. **Phase 2: memory engine.** Discussion grouping, the sincerity check, extraction with Confidence and Markers, Topic and Entity resolution, reconciliation, and the Review Queue with Flags and Admin Rulings.
4. **Phase 3: answer surfaces.** Retrieval filtered by Answer Audience, per-viewer views, citations, REST, web UI, the Slack bot (in-channel and slash command), and MCP with `submit_agent_report`.
5. **Phase 4: internal pilot.** Replay 90 days of the pilot organization's history, its weekly team meeting as a Meeting Series, one real Agent, evaluation on 20+ questions, a permissions red team, tuning of thresholds and grouping defaults, and publishing the installation guide, including the guide on using Markers.

## Resolved since v0.1

| v0.1 open item | Resolution |
|---|---|
| Partial visibility for mixed-scope Memories | Each Memory has one Access Scope. Corroboration across scopes is a `SUPPORTS` edge (ADR-0001) |
| Transcript media | Text only |
| Transcript permission defaults | Denied until set. A list of named Principals (including the uploader) or the whole Workspace. Meeting Series set their scope once |
| Granola and Zoom ingestion | Manual Granola upload through a script in v0.1. Meet Meeting Series is the one automatic connector. Zoom and Granola sync are P1 |
| Open-source license | Apache-2.0 (ADR-0010) |
| Reducing raw text retention | Expiry keeps only cited Evidence spans (ADR-0009) |

## Still needs early validation

- Whether every meeting in a recurring Calendar series shares one Meet meeting code (affects matching conference records).
- Whether a self-hosted Slack app counts as "internal" and keeps Tier 3 rate limits. Slack doesn't define the term, and its pages conflict on when the 2025 limits apply to existing installs.
- Model-routing policy for privacy-sensitive installs, and a test that local-only mode makes no outbound calls.
- Calibration of the Confidence thresholds, Discussion defaults and Agent ranking weight.
