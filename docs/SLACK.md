# Bruh in Slack

Bruh joins your Slack as **@bruh**. It does two things:

- **Reads** the public channels you invite it to. Messages pile up while people are talking; once a channel has been quiet for 30 minutes, Bruh reads the new messages and folds them into what it already knows: new decisions, reversals, who's on the hook.
- **Answers.** `@bruh what did we decide about pricing?` answers in a thread, with receipts: the original words, who said them, and a link back to the message. `/bruh …` answers just for you.

It connects over Socket Mode, so it runs anywhere that can reach the internet (a laptop, a Mac mini, a small server) without a public URL.

## Set it up (about 10 minutes, needs a Slack admin)

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From a manifest**, pick your workspace, and paste in [`slack-manifest.yml`](slack-manifest.yml). Create it.
2. **Basic Information** → **App-Level Tokens** → **Generate Token and Scopes**. Name it `socket`, add the `connections:write` scope, and generate. Copy the `xapp-…` token.
3. Optionally, under **Display Information**, upload [`assets/slack-icon.png`](../assets/slack-icon.png) as the app icon.
4. **Install App** → **Install to Workspace** → **Allow**. Copy the **Bot User OAuth Token** (`xoxb-…`).
5. Put both tokens in `.env`:

   ```sh
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   ```

6. Start Bruh with Slack switched on:

   ```sh
   uv run --env-file .env bruh serve --slack     # web app + Slack bot
   uv run --env-file .env bruh slack             # or just the bot
   ```

7. In each channel Bruh should remember: `/invite @bruh`. It catches up on that channel's last 30 days, then follows along.

## What it reads, and what it doesn't

- **Only public channels it's been invited to.** Private channels, DMs, group DMs and channels shared with other companies (Slack Connect) are never read, even if someone invites it. It has no permission to read DMs at all.
- **Not questions asked of it, and not its own answers.** Talking to Bruh doesn't become part of the record.
- **Reactions count.** A 👍 on "let's do $5" is agreement.
- **Deleting a message in Slack deletes it from Bruh**, along with any Memory that rested only on it.
- **Edits** made before Bruh reads the message are picked up. Edits after that aren't followed yet.
- **Catching up** starts after whatever Bruh last read from that channel, so a channel already imported from a Slack export isn't read twice. If Bruh was offline, it catches up when it restarts.

## Who sees what

v0 has one audience: **anyone who can ask Bruh can hear about anything Bruh has read**, including meeting transcripts. An `@bruh` answer in a channel is visible to everyone in that channel. Only give Bruh conversations the whole team could see anyway. (Per-person access is designed, in [ADR-0004](adr/0004-answers-limited-to-answer-audience.md), but not built yet.)

## Settings

| Setting | Default | What it does |
|---|---|---|
| `BRUH_SLACK_BACKFILL_DAYS` | `30` | How far back Bruh reads when it joins a channel |
| `BRUH_SLACK_QUIET_MINUTES` | `30` | How long a channel must be quiet before Bruh reads it (it never waits more than 4 hours) |

## Keep it running

Bruh has to be running to hear things. On a Mac that stays on, keep it in a terminal tab or `tmux`. Anything said while it's off is caught up on when it restarts.
