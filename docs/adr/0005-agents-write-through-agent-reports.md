# Agents write through Agent Reports, never directly as Memories

Agents add to Muninn by submitting Agent Reports, a kind of Source that goes through the same extraction, Evidence and reconciliation pipeline as Slack messages and transcripts. Letting Agents write Memories directly looks simpler and faster, but it would create Memories with no Evidence behind them, skip the sincerity and Confidence checks, and bypass the Access Scope lineage that ADR-0001 relies on. One pipeline means one trust model: every claim, human or Agent, can be cited and audited.
