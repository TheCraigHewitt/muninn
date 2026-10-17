# Muninn holds durable organizational memory, not Agent working state

As a shared context layer for Agents, Muninn will be pulled toward also storing task queues, scratchpads, locks and step-by-step progress. It deliberately doesn't. Muninn stores what would still matter next week: Decisions, Rationale, Facts, Commitments, Proposals and Questions, each backed by Evidence. Working state belongs in the Agents' own frameworks. This keeps the product focused, keeps every record citable, and stops Muninn becoming a general-purpose key-value store with a provenance problem.
