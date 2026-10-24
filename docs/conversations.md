# Conversations, summaries, and search

Gork uses separate DM and group conversation agents. Both can request database
context or remote tools and produce replies or actions. Configure their models
and prompts in the panel; see [agent packages](agents.md) for code defaults.

## Start a conversation

- In an authorized DM, send a message to the connected WhatsApp account.
- In an authorized group, mention Gork or reply to its message.
- Enable automatic replies per group if you want Gork to decide when to join in.

Whitelist authorization, blacklist rules, and command permissions all apply.
Test mode accepts only the configured contact in DMs and disables group activity.

For example, mention Gork and ask what the group decided about a trip. Reply
to its answer with “turn that into a checklist” to preserve the reply chain.

## Context and memory

DM history is scoped to the private conversation and its participants. Group
requests include sender identities, recent messages, reply chains, and available
media descriptions. Older quoted ancestors are loaded separately so a reply does
not inherit names or questions from an unrelated parallel discussion.

The agent can request additional messages, users, images, and saved observations.
The backend derives ownership from the current chat rather than trusting model
scope IDs. [Observations](observations.md) persist useful notes across turns and
are retrieved on demand rather than inserted into every request.

Automatic group replies use a buffer and filter agent; they are not guaranteed
for each message. Group conversation work is serialized, while explicit media
commands and moderation use separate dispatch paths.

## Commands

| Command | Behavior |
| --- | --- |
| `!help` | Show the catalog and supported parameters |
| `!status` / `!model` | Check readiness and the resolved conversation model |
| `!resume` | Summarize recent saved messages; repeated requests have a two-hour cooldown |
| `!search <query>` | Search online and return a summary |
| `!audio <request>` | Request a spoken response through OpenRouter |

The summary flow loads up to 100 stored messages chronologically. Its source is
what Gork has saved, which may differ from all history visible in WhatsApp.
Online search uses the `web-search` agent and OpenRouter's search tool; it is
separate from private database retrieval.

## External tools and troubleshooting

Add remote endpoints through the panel's [MCP settings](mcp.md). Descriptions
help the model choose tools; fixed credentials/arguments stay backend-controlled.

If Gork does not reply, check WAHA's `WORKING` status, access rules, test mode,
and the selected model. Try an explicit group mention to distinguish connection
issues from automatic-response filtering. Then inspect application logs for
provider errors: WhatsApp connectivity does not prove OpenRouter is available.
