# Each Memory draws its Evidence from exactly one Access Scope

A Memory may only cite Evidence from a single Access Scope. When a second scope backs up the same claim (for example, a public Slack Decision that is also confirmed in a restricted meeting transcript), Muninn records a separate Memory in that scope and links the two with a Supports edge, rather than attaching mixed-scope Evidence to one Memory. Whether a Principal can see a Memory then comes down to one check on its scope, and they see an edge only if they can see the Memories at both ends. This keeps access leaks testable without any LLM judgment at query time.

## Considered Options

- **Decide sufficiency at query time** (the Developer Spec's original wording): use only the Evidence the Principal can see, and judge whether it alone supports the claim. Rejected because it needs model judgment on every query, its outcome can't be predicted, and it's hard to cover with access-leak tests.
- **Require every piece of Evidence to be visible**: rejected because corroboration from a restricted scope would hide a Memory that the public Evidence fully supports on its own.

## Consequences

- When reconciliation finds a duplicate in a different Access Scope, it creates a new Memory with a Supports edge instead of merging the two.
- More Memories are stored, and answers have to merge Memories that Support each other into one position.
- Discussions never span more than one Access Scope. Memories from different channels or transcripts are linked at the Topic level, never by grouping their Evidence into one Discussion.
