# Agent packages

Agents are grouped by name. To change transcription, work in
`agents/transcriber/` rather than separate execution, parser, and prompt folders.

```text
agents/
  agents.yaml                  Default models and prompt/schema paths
  init.py                      Load defaults into the database
  conversation.py              Select the DM or group profile
  conversation_dm/
    agent.py                   DM entry point
    parser.py                  Shared conversation parser export
    prompt.md
    schema.json
  conversation_group/
    agent.py                   Group entry point
    parser.py
    prompt.md
    schema.json
  transcriber/
    agent.py                   Build requests and record interactions
    parser.py                  Identify containers and extract text
    prompt.md
    schema.json
  ...
  _shared/                     Common conversation runtime/parser
```

`parser.py` exists where parsing is separated from execution; other agents keep
response handling in `agent.py`. Agents without structured JSON output do not
need a schema. DM and group agents share context assembly and parsing to avoid
duplicating the conversation engine, while each owns its prompt and contract.

## Responsibilities

| Package | Responsibility |
| --- | --- |
| `conversation_dm` / `conversation_group` | Contextual replies and structured action/query plans |
| `filter` | Decide whether to reply automatically in a group |
| `modify_image` | Image generation, editing, and reference selection |
| `describe_image` | Describe images with conversation context |
| `resize_image` | AI-assisted resizing for sticker flows |
| `video_generation` | Validate options, submit/poll jobs, and deliver video |
| `audio_generation` | Synthesize speech through OpenRouter |
| `transcriber` | Send original audio to OpenRouter and extract text |
| `web_search` | Online search and summarization |
| `resume` | Summarize recent stored messages |
| `remember_formatter` | Convert natural-language reminders into schedules |

WhatsApp command recognition stays in `api/routes/webhook/waha/`. Provider
clients live in `external/`; prompt construction and model-response handling
belong to the relevant agent package.

## Configuration and persistence

`agents/agents.yaml` uses stable database names such as `conversation-dm` and
paths relative to the repository root. Directory names use underscores for
Python imports. Startup reads the prompts and schemas, registers missing models,
and initializes agent defaults before model price discovery.

The panel can select models globally or per user/group. Requests resolve the
model in the current conversation scope. Panel-managed prompts and model values
survive restarts: editing `prompt.md` alone does not overwrite them. Use
**Restore original configuration** in the panel to return to repository defaults.
Response schemas remain code-owned and must match parsing and dispatch.

## Add an agent

1. Create `agents/<agent_name>/agent.py` and `prompt.md`; add a parser and schema
   when the response requires them.
2. Register the stable name, model, and paths in `agents/agents.yaml`.
3. Resolve the configured model for the user/group, call the existing provider
   client, and preserve interaction/token accounting in that scope.
4. Connect the entry point to a handler or conversation action. New commands also
   need dispatch, a catalog entry, and permission handling.
5. Test payload contents, parsing, failure behavior, and conversation isolation.
   Restart/rebuild the application to register and load the files.

Layout tests verify every registered agent's code/prompt/schema paths and ensure
the DM and group contracts remain compatible with their shared parser.
