# Bruh

Bruh is open-source organizational memory: it turns authorized Slack discussions, meeting transcripts and Agent Reports into a cited, evolving record of what an organization decided, committed to, knows, proposed and still has open. Bruh is a shared context layer for both people and Agents. It holds durable memory only, never Agents' working state.

## Language

### Installation and access

**Organization**:
The single company whose conversations one Bruh install remembers.
_Avoid_: Tenant, company, account

**Workspace**:
The one Slack workspace connected to an Organization.
_Avoid_: Team, tenant

**Principal**:
Someone allowed to query Bruh, linked to a full (non-guest) member of the Workspace.
_Avoid_: User account, member

**Agent**:
An AI system that is a Principal in its own right, with grants set by an admin. When acting on behalf of a human, it sees only what both it and that human can see.
_Avoid_: Bot, assistant, integration

**Author**:
Whoever wrote a piece of Evidence: a Person or an Agent.
_Avoid_: Speaker, sender, creator

**Person**:
A human who appears in Evidence, such as a Slack author or a transcript speaker. A Person is an Entity and may or may not be linked to a Principal.
_Avoid_: User, participant, speaker (as a general term)

**Access Scope**:
The audience allowed to see a Source, such as everyone in the Workspace for a public channel, or the people listed for a transcript.
_Avoid_: ACL, permission group

### Sources and evidence

**Source**:
One original item that Bruh learns from: a single Slack message, one uploaded transcript, one Agent Report, or one Admin Ruling.
_Avoid_: Document, record

**Agent Report**:
A Source written by an Agent, such as findings, a recommendation or a commitment. It goes through the same extraction as human conversation, so every claim an Agent makes is citable Evidence.
_Avoid_: Agent memory, agent write

**Meeting Series**:
A recurring meeting that an admin has opted in, so each meeting's transcript is ingested automatically under an Access Scope set once for the whole series. Opting out means deleting an individual meeting afterwards.
_Avoid_: Recurring meeting (when meaning an opted-in one), standing meeting

**Source Revision**:
One version of a Source's content, created each time the original is edited.
_Avoid_: Edit, version

**Thread**:
A Slack top-level message together with its replies. A hint for grouping messages into Discussions, not a boundary.
_Avoid_: Conversation, discussion

**Conversation Window**:
A run of top-level messages in one channel with no quiet gap long enough to break it. A hint for grouping messages into Discussions, not a boundary.
_Avoid_: Session, burst, chat

**Marker**:
An admin-chosen emoji reaction or phrase (such as `Decision:`) that people use to signal a Memory type on purpose. A Marker raises Confidence but never overrides the sincerity check.
_Avoid_: Tag, label

**Discussion**:
A group of messages, a stretch of transcript, or an Agent Report that a model judged to be one exchange about one subject. A Discussion is what extraction reads, never spans more than one Access Scope, and can grow as later messages join it.
_Avoid_: Conversation, chat, exchange

**Evidence**:
An exact span of a Source (a message, or a timestamped stretch of transcript) that a Memory cites.
_Avoid_: Chunk, snippet, quote

### Memory

**Memory**:
One atomic claim about the Organization, drawn from Evidence in a single Access Scope. Its statement never changes once recorded.
_Avoid_: Note, fact (when meaning any Memory), insight

**Decision**:
A Memory recording that the Organization sincerely committed to a course of action, made by a human Person with explicit commit language and no objection left open in its Discussion. Jokes, sarcasm, hypotheticals, quotes of other people and Agent assertions are never Decisions.
_Avoid_: Agreement, conclusion

**Proposal**:
A Memory recording a suggested course of action that hasn't become a Decision.
_Avoid_: Idea, suggestion

**Rationale**:
A Memory recording why a Decision or Proposal was made.
_Avoid_: Reason, justification

**Commitment**:
A Memory recording that someone undertook to do something.
_Avoid_: Action item, task, todo

**Fact**:
A Memory recording something stated as true about the Organization or its world.

**Question**:
A Memory recording something the Organization asked and hadn't answered.
_Avoid_: Open issue, unknown

**Memory Status**:
Where a Memory stands at a point in time: proposed, active, disputed, superseded, resolved or withdrawn. Status changes are dated and kept as history. Each Principal sees a status worked out only from the Memories and relationships they can see.

**Withdrawn**:
The status of a Memory whose Evidence was edited away, so its Source no longer says it. Withdrawn Memories stay in history; deleted Sources leave nothing behind.
_Avoid_: Retracted, invalidated

**Confidence**:
How sure Bruh is that a Memory's type and statement correctly read its Evidence. It decides whether the Memory is recorded, goes to the Review Queue, or becomes active, and is never shown in answers as a number.

**Commitment Owner**:
The Author (a Person or an Agent) who undertook a Commitment.
_Avoid_: Assignee

**Topic**:
The ongoing subject a line of Memories builds up under, such as "public API strategy". Each Memory belongs to exactly one Topic. A Principal can see a Topic only through Memories they can see, and its label is generated from those Memories alone.
_Avoid_: Theme, category, tag

**Entity**:
A named real-world thing that Memories mention, such as a person, product, customer or project.
_Avoid_: Object, thing

**Project**:
A named body of work. It is an Entity and can span many Topics.

### Relationships between Memories

**Supports**:
One Memory backs up another, such as the same Decision seen in a second Access Scope.

**Contradicts**:
Two Memories take incompatible positions and neither has clearly replaced the other.

**Supersedes**:
A later Memory replaces an earlier position. The earlier Memory stays in history as superseded.
_Avoid_: Overrides, replaces, updates

**Resolves**:
A later Memory closes a Commitment by showing the work was done, or closes a Question by answering it.
_Avoid_: Closes, completes

**Explains**:
A Rationale gives the reason for a Decision or Proposal.
_Avoid_: Justifies, Supports (Supports means corroboration)

### Answers

**Answer Audience**:
The set of Principals who can see an answer. An answer may only use Memories visible to everyone in its Answer Audience, so an answer posted in a Slack channel is limited to what the whole channel can see.

### Oversight

**Review Queue**:
Where an admin settles uncertain changes of state, such as a Contradiction or a low-confidence Supersedes.
_Avoid_: Inbox, moderation

**Flag**:
A Principal's report that a Memory they can see looks wrong, which sends it to the Review Queue.
_Avoid_: Report, dispute (disputed is a Memory Status)

**Admin Ruling**:
A Source written by an admin to settle a review, correct a Memory, or merge or split Topics or Entities. It is citable and reconciled like any other Source, so corrections are never silent edits.
_Avoid_: Override, manual edit

**Retention Expiry**:
The end of a Source's retention period. By default the full Source is dropped but the exact Evidence spans that Memories cite are kept. A setting can make expiry erase everything, the same as a deletion.

**Extraction Run**:
One pass of a particular extractor over Evidence. Memories record which run produced them, so changes caused by a re-extraction show up in history as revisions by the extractor, not as the Organization changing its mind.
