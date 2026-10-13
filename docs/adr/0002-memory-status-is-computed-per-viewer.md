# Each Principal sees a Memory Status worked out from what they can see

A Memory's status depends on its relationships. Take a public "No public API" Decision that a restricted leadership transcript later Supersedes. The stored status would be `superseded`, and showing that to a public-only Principal would reveal that a restricted Decision exists. So Bruh works out each Memory's status for the asking Principal using only the Memories and relationships they can see. That Principal sees the public Decision as still `active`. The stored status is only the view of someone who can see everything. We accept answers that may be out of date for restricted readers, in exchange for never leaking restricted positions. The fix for a stale answer is to share the decision somewhere people can see it, not to give Bruh wider access.

## Considered Options

- **Show the stored status with "replaced by something you can't access"**: rejected because it reveals that a restricted Decision exists, and when it happened.
- **Add a "positions may exist that you can't see" note to every answer**: rejected because on sensitive Topics it still hints at something, and on every other Topic it's just noise.

## Extended to Topic labels

The same rule applies to Topics. A Principal sees a Topic only if they can see at least one Memory in it, and the Topic's label is generated from the Memories they can see. Search and autocomplete only match against labels the viewer can see. Otherwise a label drawn from restricted Memories ("Q3 layoffs") would leak through Topic lists, autocomplete and `get_topic_history`.
