# Extraction prototype: verdict

**Question:** can a model reliably turn messy conversation into typed Memories (Decision, Proposal, Rationale, Commitment, Fact, Question), skip things people didn't mean literally, and cite the exact evidence?

**Answer:** yes with Opus, with caveats that belong to the pipeline around the model rather than to extraction itself.

## What was run

- Synthetic fixtures (`fixtures/`, 27 checks): sarcasm, hypotheticals, emoji-only agreement, a reversal, a prompt injection.
- Real data from the pilot organization (kept local, never committed): four meeting transcripts (about an hour each, exported from a meeting-notes app) and a month of three Slack channels.
- Models: Opus 5.5, Sonnet 5.5 and Haiku 5.5, at medium effort.

## Results on real data

| | Opus | Sonnet | Haiku |
|---|---|---|---|
| Memories | 137 | 70 | 89 |
| Decisions confident enough to go active | 3 | 3 | 0 |
| Rationales | 11 | 3 | 7 |
| Quotes that weren't verbatim (caught by the check) | 3 | 2 | 0 |
| Synthetic checks | 27/27 | 27/27 | 27/27 |

- Opus recorded an explicit decision to end a contractor engagement as active. A week later it recorded the same decision, retold, as a Fact rather than a new Decision. It linked a mid-meeting reversal with Supersedes, and the Slack change of a spam threshold too.
- Sonnet matched Opus on the headline decisions and commitments but missed most reversals and reasons, which are what Bruh is for.
- Haiku recorded one reversal backwards and never cleared the confidence bar for a Decision.
- Small talk produced nothing. Bot messages were never cited as evidence.

## What the real data showed that the synthetic data could not

1. **Speaker labels are the weakest link.** The meeting-notes export labels other people "Them" and sometimes merges several speakers into one turn. Who made a Decision or owns a Commitment can't be trusted from such lines.
2. **Lots of short-lived status.** Vacation dates and "merging PR 298" are true but aren't organizational memory, so extraction needs a durability rule.
3. **Duplication across sources.** One feature launch showed up in four sources, which calls for reconciliation.
4. **Identity across sources.** One person is spelled differently in Slack and in transcripts.
5. **Confidence is lower on real speech** and differs by model, so thresholds have to be set per model.

## Decisions carried into the build

- Default extraction model: Opus. Model choice stays configuration.
- Extraction keeps only durable memory: decisions, reasons, owned commitments with a deliverable, open questions, and lasting facts.
- A retold decision supports the existing Memory. It is never a new Decision.
- Supersedes only replaces a position that was recorded as a Decision.
- Lines whose speaker is unknown can't produce a Decision or a Commitment owner.
