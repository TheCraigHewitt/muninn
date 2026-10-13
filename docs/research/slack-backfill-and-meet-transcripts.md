# Research: Slack backfill and Google Meet transcripts

Answers two items from TECH_SPEC "Still needs early validation". All sources were read on 2026-10-12, and only vendor-owned pages were used: docs.slack.dev, slack.com/help, developers.google.com and support.google.com.

## Summary and recommendations

**Slack.** Each deployment creates its own single-workspace Slack app from a manifest that Bruh ships, and does not distribute it.

- **Rate limits.** Slack says internal customer-built apps keep Tier 3 limits (50+ requests per minute, up to about 1,000 messages per page) on `conversations.history` and `conversations.replies`. The 1 request per minute, 15 messages per page limit applies only to apps commercially distributed outside the Marketplace.
- **Bot scopes:** `channels:read`, `channels:history`, `users:read`. Add `channels:join` only if the bot should join allowlisted channels itself. The alternative is having an admin `/invite` it.
- **What Bruh must never request:** `groups:*`, `im:*` or `mpim:*`.
- **Events to subscribe to:**
  - `message.channels`, which also delivers the `message_changed` and `message_deleted` subtypes
  - `channel_shared` and `channel_unshared`
  - `user_change`, `user_guest_status_changed` and `team_join`
  - Socket Mode works for installs that can't expose a public URL.
- **Rejecting what Bruh must not ingest.** Reject any event whose `channel_type` isn't `"channel"`. Separately, reject channels where `conversations.info` shows `is_private`, `is_im`, `is_mpim`, `is_ext_shared` or `is_pending_ext_shared`.
- **Guests.** Detect them with `users.info` (`is_restricted` / `is_ultra_restricted`).
- **Correction for TECH_SPEC (applied).** Sign in with Slack (scopes `openid profile email`) does not return guest status. Bruh must call `users.info` on the `sub` user ID after sign-in.

**Google.** Register an OAuth client of user type **Internal** in a Google Cloud project owned by the deploying Workspace organization. The **organizer** of each Meeting Series grants per-user OAuth with offline access.

- **Scopes:**
  - `https://www.googleapis.com/auth/calendar.events.owned.readonly` if the series lives on a calendar the organizer owns, otherwise `calendar.events.readonly`. Used for `events.instances` and `conferenceData`.
  - `https://www.googleapis.com/auth/meetings.space.readonly` for `conferenceRecords`, `transcripts` and `transcripts.entries`.
  - Optional fallback for transcripts older than the 30-day Meet API window: `https://www.googleapis.com/auth/documents.readonly`. With it, read the transcript Doc by ID through the Docs API. This scope is sensitive, not restricted.
  - Avoid `drive.readonly`, and avoid `drive.meet.readonly` unless needed. Both are restricted.
- **TECH_SPEC's original plan did not work (now corrected).** It read the transcript Doc using "minimal Drive and Calendar scopes". `drive.file` can't see files that Meet created, so Calendar plus `drive.file` is not enough.
- **Better primary path: Meet API transcript entries.** They are structured and carry a participant reference that resolves to a Google user ID, which fits the "no name guessing" rule for speaker mapping. The catch is that they are deleted 30 days after the meeting ends, so Bruh must poll inside that window.
- Domain-wide delegation is an optional alternative for admins who prefer it. It needs super-admin setup and grants broader impersonation power.

---

## Question 1: Slack backfill and ingestion

### Rate limits and the 2025 non-Marketplace change

- **Tiers:** Tier 1 is 1+ requests per minute, Tier 2 is 20+, Tier 3 is 50+ and Tier 4 is 100+. Limits apply per method, per workspace, per app. A `429` comes with a `Retry-After` header. [Rate limits](https://docs.slack.dev/apis/web-api/rate-limits/)
- **Events API limit:** 30,000 deliveries per workspace per app per 60 minutes. Above that, Slack sends `app_rate_limited`. [Rate limits](https://docs.slack.dev/apis/web-api/rate-limits/)
- **`conversations.history` and `conversations.replies`:** both are Tier 3 "for Marketplace and internal customer-built applications". [conversations.history](https://docs.slack.dev/reference/methods/conversations.history/), [conversations.replies](https://docs.slack.dev/reference/methods/conversations.replies/)
  - For apps "commercially distributed outside of the Marketplace", both are limited to 1 request per minute, with the `limit` default and maximum cut to 15. This took effect May 29, 2025 for new apps and for new installs of existing apps.
  - Existing installs of such apps "will not be subject to the new posted limits".
- **The changelog (May 29, 2025, later edited):**
  - It says, "This rate limit reduction will apply only to applications that are commercially distributed outside of the Marketplace (also called 'unlisted' apps)."
  - It also says, "Internal customer-built applications are not impacted by these changes and continue to have a rate limit of 1,000 messages per request at 50+ requests per minute."
  - Its FAQ answers "Will my internal app be impacted?" with "No."
  - Source: [Changelog: rate limit changes for non-Marketplace apps](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps/)
- **Clarification (June 3, 2025):** "Any internal customer-built apps will maintain their existing rate limits." [Changelog: clarifying rate limit changes](https://docs.slack.dev/changelog/2025/06/03/rate-limits-clarity/)
- **Terms context.** The same changelog summarizes the API Terms update: the Marketplace is "the only appropriate channel for commercially distributing apps … whether those apps are 'unlisted' … or provide a customer instructions for a templated custom app that connects to your product." [Changelog](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps/)
- **Implication for Bruh.** Bruh is open source, non-commercial and self-hosted, and each operator creates the app in their own workspace. That matches "internal customer-built" and gets Tier 3 limits. No page formally defines "internal customer-built" or "commercially distributed", though. See Unresolved.
- **Backfill planning:**
  - **At Tier 3:** about 50 history pages per minute (200 to 999 messages per page), plus one `conversations.replies` call per thread. Thread replies are the bottleneck.
  - **If Slack ever treated an install as distributed:** about 15 messages per minute, and one thread page per minute.
  - Design the backfill as a resumable, cursor-based job that honors `Retry-After` in either case.

### History visibility by plan

- **Free plan:** "You can view and search messages and files from the last 90 days."
  - Older messages are hidden.
  - "Starting August 26, 2024 … messages and file history older than one year may be deleted on a rolling basis."
  - Free workspaces can install at most 10 apps.
  - Source: [Usage limits for free workspaces](https://slack.com/help/articles/115002422943-Usage-limits-for-free-workspaces)
- **The API on a free plan:** `conversations.history` returns an `is_limited` flag, "only included for free teams that have reached the free message limit." [conversations.history](https://docs.slack.dev/reference/methods/conversations.history/) No Slack page says the API returns messages hidden by the 90-day limit. Assume it does not (see Unresolved).
- **Paid plans:** history is bounded only by the workspace's retention settings. [Customize data retention in Slack](https://slack.com/help/articles/203457187-Customize-data-retention-in-Slack)
- **Full history:** calling `conversations.history` with no `oldest` or `latest` reads the whole history. [conversations.history](https://docs.slack.dev/reference/methods/conversations.history/)

### Scopes and channel membership

| Need | Method or event | Bot scope |
|---|---|---|
| List or inspect channels | `conversations.list` (Tier 2, `types` defaults to `public_channel`), `conversations.info` (Tier 3) | `channels:read` |
| Read messages and threads | `conversations.history`, `conversations.replies` | `channels:history` |
| Look up users and guests | `users.info` (Tier 4) | `users:read` |
| Join a channel (optional) | `conversations.join` (Tier 3) | `channels:join` |

Sources: [conversations.list](https://docs.slack.dev/reference/methods/conversations.list/), [conversations.info](https://docs.slack.dev/reference/methods/conversations.info/), [users.info](https://docs.slack.dev/reference/methods/users.info/), [conversations.join](https://docs.slack.dev/reference/methods/conversations.join/)

- **The bot must be in the channel.**
  - `channels:history` is described as "View messages … in public channels that your Slack app has been added to." [channels:history scope](https://docs.slack.dev/reference/scopes/channels.history/)
  - The history method's `not_in_channel` error says "Only user tokens can access public channels they are not in." [conversations.history](https://docs.slack.dev/reference/methods/conversations.history/)
  - Recommendation: have an admin invite the bot to each allowlisted channel. Joining a channel then makes it visible as an explicit, auditable act. Request `channels:join` only if self-join is wanted.
- **The `channels:history` scope page lists these compatible events:** `message.channels`, `message_changed`, `message_deleted`, `message_replied`, `thread_broadcast` and `channel_history_changed`. [channels:history scope](https://docs.slack.dev/reference/scopes/channels.history/)

### Events for incremental sync

- **`message.channels`** fires for messages in public channels. "Differentiate public channel messages … by looking for the event's `channel_type` field set to `"channel"`." [message.channels](https://docs.slack.dev/reference/events/message.channels/)
- **Edits:** a `message_changed` subtype carries the new `message`. Match it on `message.ts` and `channel`. It can also fire because of automatic language detection, so dedupe on content hash. [message_changed](https://docs.slack.dev/reference/events/message/message_changed/)
- **Deletes:** a `message_deleted` subtype carries `deleted_ts`. "The original message will no longer return in history calls." [message_deleted](https://docs.slack.dev/reference/events/message/message_deleted/)
- **Bulk history changes:** `channel_history_changed` means clients "should reload chat history for the channel". Treat it as a trigger to re-sync. [channel_history_changed](https://docs.slack.dev/reference/events/channel_history_changed/)
- **Sharing changes:** `channel_shared` and `channel_unshared` require `channels:read`. They fire when a channel becomes, or stops being, shared with an external workspace. [channel_shared](https://docs.slack.dev/reference/events/channel_shared/), [channel_unshared](https://docs.slack.dev/reference/events/channel_unshared/)
- **User changes:** `user_change` and `user_guest_status_changed` require `users:read`. The second fires on member↔guest transitions. New users who start as guests arrive via `team_join`. [user_change](https://docs.slack.dev/reference/events/user_change/), [user_guest_status_changed](https://docs.slack.dev/reference/events/user_guest_status_changed/)
- **Without a public URL:** Socket Mode delivers events without a public HTTP endpoint. Socket Mode apps can't be listed in the Marketplace, which doesn't matter for self-hosting. [Using Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)

### Excluding DMs, group DMs, private and Slack Connect channels

The conversation object fields come from [Conversation object](https://docs.slack.dev/reference/objects/conversation-object/):

- `is_im` marks a direct message, and `is_mpim` marks "an unnamed private conversation between multiple users".
- `is_private` marks a private channel ("Use `is_private` to determine whether a channel is private or public"). Legacy private channels created before March 2021 have `is_group: true` instead.
- `is_ext_shared` marks "part of a Shared Channel with a remote organization". `is_pending_ext_shared` marks one awaiting approval.
- `is_shared` is true for any multi-workspace share. `is_org_shared` is true for Enterprise Grid sharing inside one organization. The docs say to look at `is_ext_shared` and `is_org_shared` "to learn which kind it is".
- `connected_team_ids` and `shared_team_ids` list the other workspaces.

**Recommended guard, applied at both ingest and backfill time:**

- Allow only allowlisted channel IDs where `conversations.info` returns `is_channel && !is_private && !is_im && !is_mpim && !is_group && !is_ext_shared && !is_pending_ext_shared`.
- Drop any event whose `channel_type != "channel"`.
- When `channel_shared` arrives, or a `channel_convert_to_private` message subtype is seen, re-check the channel and suspend it.
- Without `im:*`, `mpim:*` or `groups:*` scopes, Slack shouldn't deliver those events anyway. Even so, the server-side rejection is the backstop that TECH_SPEC requires.

### Guests vs full members

These fields come from [User object](https://docs.slack.dev/reference/objects/user-object/) and [users.info](https://docs.slack.dev/reference/methods/users.info/):

- `is_restricted` "Indicates whether or not the user is a guest user."
- `is_ultra_restricted` "Indicates whether or not the user is a single-channel guest."
- `deleted` means the user is deactivated, `is_bot` means a bot, and `is_stranger` means the user belongs to another workspace and isn't in any shared channel visible to the app.
- A full member is `!deleted && !is_bot && !is_restricted && !is_ultra_restricted && !is_stranger`, and the user's `team_id` must match the Workspace.

### Sign in with Slack (OpenID Connect)

All of the following comes from [Sign in with Slack](https://docs.slack.dev/authentication/sign-in-with-slack/) unless another link is given.

- **Endpoints and scopes:** authorize at `https://slack.com/openid/connect/authorize` with scopes `openid` (required), `email` and `profile`. Exchange the code via `openid.connect.token`.
- **Workspace hint:** the `team` parameter takes the user straight to the intended workspace.
- **Separate flow:** OpenID scopes can't be combined with non-OpenID scopes in the same OAuth flow ("scope conflict"). Use a separate flow, which can be on the same app.
- **`id_token` claims:**
  - Standard claims: `sub` (the Slack user ID), `iss`, `aud`, `exp`, `iat`, `auth_time` and `nonce`
  - Slack identity claims: `https://slack.com/team_id` and `https://slack.com/user_id`
  - Profile claims: `email`, `email_verified`, `name`, `given_name`, `family_name`, `locale` and team image URLs
  - `openid.connect.userInfo` adds `team_name`, `team_domain` and avatars. [openid.connect.userInfo](https://docs.slack.dev/reference/methods/openid.connect.userInfo/)
- **No guest field.** Neither response includes any guest, restricted or role field. To decide whether a user can become a Principal, verify `https://slack.com/team_id` equals the Workspace, then call `users.info` with the bot token and apply the full-member test above. Re-check on `user_guest_status_changed`.

---

## Question 2: Google Calendar and Meet transcripts

### (a) Finding the instances of a recurring event

- **`events.instances`** (`GET /calendars/{calendarId}/events/{eventId}/instances`) "Returns instances of the specified recurring event". [events.instances](https://developers.google.com/workspace/calendar/api/v3/reference/events/instances)
  - It supports `timeMin`, `timeMax`, `showDeleted` and `originalStart`, and returns up to 2,500 instances per page.
  - Accepted scopes include `calendar.events.owned.readonly`, `calendar.events.readonly` and `calendar.readonly`, among others.
- **Instance fields.** Each instance has `recurringEventId` ("the id of the recurring event to which this instance belongs") and `originalStartTime`. [Events resource](https://developers.google.com/workspace/calendar/api/v3/reference/events)
- **Meet link fields:**
  - `conferenceData.conferenceId` is the 10-letter meeting code (for example, `aaa-bbbb-ccc`) when the solution type is `hangoutsMeet`.
  - `conferenceData.entryPoints[].meetingCode` and `hangoutLink` are also available.
  - `attachments[]` gives `fileId` (the Drive file ID), `fileUrl`, `mimeType` and `title`, with at most 25 attachments.
  - Source: [Events resource](https://developers.google.com/workspace/calendar/api/v3/reference/events)
- **Scope options** ([Calendar API scopes](https://developers.google.com/workspace/calendar/api/auth), last updated 2026-09-03):
  - `calendar.events.owned.readonly`: "See the events on Google calendars you own". The narrowest.
  - `calendar.events.readonly`: "View events on all your calendars".
  - `calendar.readonly`: "See and download any calendar you can access". Broader, so avoid it.

### (b) Fetching the transcript via the Meet REST API

- **Finding the conference.** `conferenceRecords.list` filters on `space.meeting_code`, `space.name`, `start_time` and `end_time`, for example `space.meeting_code = "abc-mnop-xyz" AND start_time>=…`. Scopes are `meetings.space.created` or `meetings.space.readonly`. [conferenceRecords.list](https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords/list)
- **Mapping an instance to a conference record:**
  1. Take the instance's `conferenceData.conferenceId`, which is the meeting code.
  2. Filter `conferenceRecords.list` by that code and a window around the instance's start time.
  3. Persist the resolved `space` name rather than the code, because meeting codes "can be reused for different meeting spaces in the future" and "generally … expire 365 days after last use." [Meet REST API overview](https://developers.google.com/workspace/meet/api/guides/overview)
- **ConferenceRecord** has `startTime`, `endTime`, `space` and `expireTime`. "The resource is deleted 30 days after the conference ends." [ConferenceRecord](https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords)
- **Transcript** has `state` (`STARTED`, `ENDED`, or `FILE_GENERATED` once the file is ready), `startTime`, `endTime` and `docsDestination`, which points to the Google Doc. A conference can have more than one transcript, one per transcription session. [Transcript](https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords.transcripts)
- **TranscriptEntry** has `participant` (a `conferenceRecords/{id}/participants/{id}` name), `text`, `languageCode`, `startTime` and `endTime`. [TranscriptEntry](https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords.transcripts.entries)
  - `entries.list` returns at most 100 per page, with scopes `meetings.space.created` or `meetings.space.readonly`.
  - Entries "might not match the transcription found in the Google Docs transcript file" when speakers interleave or the Doc is edited. [entries.list](https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords.transcripts.entries/list)
- **Participant** is one of three kinds: `signedinUser` (with `user`: `users/{id}`, "Interoperable with Admin SDK API and People API", plus `displayName`), `anonymousUser`, or `phoneUser`. This gives stable speaker IDs for explicit speaker mappings. [Participant](https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords.participants)
- **Who can call the API:**
  - "If you're a meeting space owner or participant, you can call the get and list methods on the recordings, transcripts, transcripts.entries … resources." [Work with artifacts](https://developers.google.com/workspace/meet/api/guides/artifacts)
  - However, "The list method only returns conferences where you're the meeting organizer." [Work with conferences](https://developers.google.com/workspace/meet/api/guides/conferences)
  - So use the **organizer's** credentials.
- **Retention:**
  - Transcripts are saved to the meeting organizer's Drive and "retained according to Drive rules."
  - "Transcript entries provided by the Meet REST API are deleted 30 days after the conference ends."
  - Source: [Work with artifacts](https://developers.google.com/workspace/meet/api/guides/artifacts)
- **Meet API scopes** ([Meet API scopes](https://developers.google.com/workspace/meet/api/guides/authenticate-authorize), last updated 2026-09-14):
  - `meetings.space.readonly`: "read metadata about any meeting space the user has access to". **Sensitive.**
  - `meetings.space.created`: only for spaces the app created, so it is useless for existing calendar meetings.
- **Push instead of polling (optional).** The Workspace Events API offers `google.workspace.meet.transcript.v2.fileGenerated`. Polling is enough for v0.1. [Subscribe to Google Meet events](https://developers.google.com/workspace/events/guides/events-meet)

### Alternative path: the transcript Google Doc

- **Where the Doc lives.** Transcripts are saved "in the meeting organizer's Google Drive in the 'Google Meet' folder" with a sub-folder per meeting. Starting July 2026, the old "Meet Recordings" folder is renamed "Legacy Meet Recordings". [Use Transcripts with Google Meet](https://support.google.com/meet/answer/12849897?hl=en)
- **Calendar link.** "If the meeting is associated with a Google Calendar event and the meeting takes place during the scheduled time, the transcript is also linked in the Calendar event." [Turn meeting transcription on or off (admin)](https://support.google.com/a/answer/12076932?hl=en) The Doc's ID is then available from `attachments[].fileId` on the instance, or from `docsDestination.document`. The latter "corresponds to the documentId in the documents resource". [Work with artifacts](https://developers.google.com/workspace/meet/api/guides/artifacts)
- **Reading the Doc, cheapest first:**
  - **Docs API `documents.get`** accepts `documents.readonly`, which is **Sensitive**, not Restricted. [documents.get](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/get), [Docs API scopes](https://developers.google.com/workspace/docs/api/auth)
  - **Drive `files.export`**, for example to `text/plain` with a 10 MB limit, accepts `drive`, `drive.file`, `drive.meet.readonly` or `drive.readonly`. [files.export](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export)
  - `drive.meet.readonly` ("View Drive files created or edited by Google Meet") and `drive.readonly` are both **Restricted**. [Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [Meet API scopes](https://developers.google.com/workspace/meet/api/guides/authenticate-authorize)
  - `drive.file` is non-sensitive, but covers only files "that you open with an app or that the user shares with an app while using the Google Picker API". Meet-created Docs aren't covered unless someone picks each one. [Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- **Drawback:** the Doc has only display names, not participant IDs, so speaker mapping is weaker than with API entries.

### Auth model and verification

- **Internal app type.** "For apps used only internally by your Google Workspace organization, scopes aren't listed on the consent screen and use of restricted or sensitive scopes doesn't require further review by Google." [Configure OAuth consent](https://developers.google.com/workspace/guides/configure-oauth-consent)
- **Verification exemptions.** These include "internal use within an organization" and "domain-wide installation". For internal use, "The project must be owned by the organization, and its OAuth consent screen needs to be configured for an Internal user type." [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification), [Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
- **Admin restrictions.** Workspace admins "might restrict access to sensitive scopes" for client IDs they haven't marked trusted. The install guide should cover trusting the client ID. [Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
- **Avoid External + Testing.** External apps in "Testing" status get refresh tokens that expire in 7 days, which would break a background poller. [Using OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)
- **Domain-wide delegation:**
  - A super admin authorizes a service account client ID for listed scopes, and the service account can then impersonate users. [Domain-wide delegation (admin)](https://support.google.com/a/answer/162106?hl=en)
  - Google treats DWD as user authentication for the Meet API. [Meet API auth](https://developers.google.com/workspace/meet/api/guides/authenticate-authorize)
  - Trade-off: no per-organizer consent step, but the key can impersonate **any** user for those scopes. Offer DWD as an option, not the default.

### Workspace editions with Meet transcription

- **Admin Help** lists "Business Standard; Business Plus; Enterprise Standard and Enterprise Plus; Education Plus." It adds that the feature is on by default, and that on Business Standard it can't be turned off in the Admin console. [Turn meeting transcription on or off](https://support.google.com/a/answer/12076932?hl=en)
- **Meet user Help** lists Business Standard, Business Plus, Enterprise Starter, Enterprise Standard, Enterprise Plus, Teaching and Learning Upgrade, Education Plus and Workspace Individual. It says transcripts are on by default except for Education student licenses. [Use Transcripts with Google Meet](https://support.google.com/meet/answer/12849897?hl=en)
- **Automatic transcription** ("Meetings are transcribed by default") is a separate admin setting, available on Business Plus, Enterprise Standard and Plus, Education Plus, Enterprise Essentials and Essentials Plus. [Automatic meeting artifact settings](https://support.google.com/a/answer/15496523?hl=en)
- **Neither list includes Business Starter.**

---

## Unresolved or conflicting

1. **Existing installs and the Slack rate limits.** Search-engine snippets of Slack pages mentioned existing non-Marketplace installs becoming subject to the limits (September 2, 2025, then March 3, 2026). The live English and Japanese changelog and method pages read on 2026-10-12 say existing installs are **not** affected, and none of them mentions those dates. The policy may have been reversed or the snippets may be stale. This doesn't affect internal apps, but re-check before release.
2. **Undefined terms.** No Slack page defines "internal customer-built app" or "commercially distributed". The Terms summary covers "instructions for a templated custom app that connects to your product". A free, open-source, self-hosted app where each operator creates their own app should count as internal, but that is an interpretation.
3. **Page size.** The `conversations.history` reference says `limit` is at most 999 and recommends 200 or fewer per page. The changelog says internal apps get "1,000 messages per request". Use 200.
4. **Hidden free-plan history.** No Slack doc states whether the API returns messages hidden by the free plan's 90-day limit. Test on a free workspace, and surface `is_limited` to the admin.
5. **Meet access rules.** The artifacts guide says owners **or participants** can get and list transcripts. The conferences guide says `conferenceRecords.list` returns only conferences "where you're the meeting organizer". Test whether a non-organizer co-host can list conferences. The design should assume organizer credentials.
6. **Same meeting code across instances?** No Google page states that every instance of a recurring Calendar event shares one Meet space or meeting code. Verify by checking `conferenceData.conferenceId` across instances. Also handle instances that have their own conference data, and multiple conference records or transcripts per instance.
7. **Edition lists disagree.** The admin and user Help pages list different Workspace editions. The user page adds Enterprise Starter, Teaching and Learning Upgrade and Workspace Individual. Treat Business Standard and above as the safe statement.
8. **Folder rename.** The admin Help page still says "Meet Recordings" folder, while the user Help page describes the July 2026 move to a "Google Meet" folder. Don't depend on folder names. Use `docsDestination` or the Calendar attachment `fileId`.
9. **Calendar scope sensitivity.** The Calendar scopes page doesn't label each scope as sensitive or restricted. With an Internal app this doesn't matter.
10. **Entries vs Doc.** Meet API transcript entries can differ from the Doc. Pick one as the canonical Source text per transcript, and record which one was used.
