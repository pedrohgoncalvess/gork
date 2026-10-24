# Conversation observations

## What belongs in an observation?

Save stable, useful context: a recurring nickname, an agreed convention, or a
communication preference observed over time. A one-off request belongs in the
current reply; a message that must be delivered at a future time belongs in a
[reminder](reminders-and-usage.md). Observations do not schedule notifications.

For example, after learning that a group calls its monthly meeting “the council,”
Gork can save that convention. In a later turn, searching observations can help
interpret “when is the next council?” without scanning every old message. It
should still verify facts such as dates from the current request or tools.

Gork can proactively save useful context such as inside jokes, shared references,
and recurring situations, including recurring communication styles. Notes are stored in `manager.observation`, separate
from scheduled reminders. Each note belongs to exactly one group or one DM.
Group notes are shared by participants; DM notes belong to the current user.
Style descriptions use the prefix `Estilo de conversa:` and describe observed
human vocabulary, message length/splitting, humor, punctuation, and media
preferences, with context and uncertainty. They guide natural text and spoken
delivery while current requests take priority. Gork's own output and human
silence are not evidence of a human preference. Notes are searched on demand
with that prefix, avoiding duplicate saves on every turn. Spoken scripts expand
texting abbreviations even when the typed conversation uses them.
The backend selects the scope from the conversation and ignores scope IDs sent
by the model. The triggering message ID is attached by the backend.

The existing structured database tool-call loop supports:

```json
{
  "queries": [
    {
      "query_type": "save_observation",
      "parameters": {"content": "The group calls Pedro's late arrivals 'the Swiss clock'; this is an inside joke."}
    }
  ],
  "next_call_instruction": "Continue answering the current request after saving the note.",
  "actions": []
}
```

Use `search_observations` with optional `query`, `mode`, and `limit` to retrieve
notes in later requests. Modes are `term`, `similarity`, and `hybrid` (default).
Omitting the query lists recent notes. The default limit is 10, maximum 50;
content and queries accept at most 4000 characters. Hybrid search merges lexical
and semantic rankings using reciprocal rank fusion. Exact duplicate content in
the same scope is deduplicated, including concurrent saves. Model instructions
also encourage checking existing notes to avoid redundant paraphrases.

Term search uses case-insensitive literal substring matching in the application,
after PostgreSQL restricts notes to the current conversation. Encrypted text
cannot use PostgreSQL full-text or trigram indexes; the older migration's text
indexes do not accelerate this path. Embeddings use the configured
default embedding model and existing usage accounting, with 2560 dimensions;
an HNSW cosine index casts to `halfvec` to support this dimension count. Semantic
search is restricted to embeddings from the current embedding model. Older
notes remain available through term search if the model changes.

If embeddings are unavailable, notes still save with `embedding_indexed: false`.
Hybrid search still returns lexical matches and reports `semantic_available:
false`; similarity-only search reports the same flag with no semantic results.
Saving the same unindexed content later retries embedding generation.

The migration `20261001_01_ConversationObservations` runs through the existing
startup migration runner. It requires PostgreSQL with pgvector >= 0.7 (`halfvec`)
and permission to enable `pg_trgm`. Rollback drops the observations table and its
indexes; it does not remove shared extensions. Notes are retrieved on demand
through tool calls, rather than injected into every model request.

## Check retrieval and isolation

To verify behavior, save a distinctive note in a test conversation and retrieve
it there, then query from another DM/group. The second conversation must not
inherit the first one's notes. Use term search first if semantic retrieval is
unavailable; notes saved without embeddings remain usable lexically.

If similar context is saved repeatedly, check existing notes before adding a
paraphrase. Exact-content deduplication is automatic, but it does not collapse
every semantically similar sentence. Changing embedding models can temporarily
reduce semantic matches without deleting old observations.
