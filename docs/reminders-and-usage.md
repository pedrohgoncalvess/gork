# Reminders, favorites, and usage

These features use Gork's access rules and store their records in PostgreSQL.
References to saved attachments can also depend on MinIO files.

## Reminders

Describe the time and message using natural language:

```text
!remember tomorrow at 4 pm, confirm the reservation
!remember on November 12 at 9 am, submit the report
```

The `remember-formatter` agent returns a structured datetime, reminder text,
and confirmation. The handler stores and schedules delivery to the current chat.
Times use `America/Sao_Paulo`. Give an explicit date/time when “next Friday” or
similar expressions could be ambiguous, and check the confirmation.

Pending reminders are loaded when the scheduler starts. Delivery requires Gork
and WhatsApp connectivity to be available. If a reminder does not arrive, inspect
the parsed date, stored record, and scheduler/application logs.

Agent code, prompt, and schema are in `agents/remember_formatter/`. Scheduled
delivery is in `services/remember.py`; these are separate from
[conversation observations](observations.md), which are notes without a due date.

## Favorites

Reply to a message with `!favorite` to bookmark it. Use the options shown by
`!help` and command feedback to list or remove favorites. A quoted message Gork
never stored may not have enough information to bookmark.

A favorite is a message reference, not a separate attachment backup. Preserve
the message database and MinIO files together to keep saved media usable.

## Usage reports

```text
!usage
!usage :when 7d :granularity d
!usage :when 3w :granularity w
!usage :user "Maria Silva" :when 2m :granularity m
```

`:when` selects days, weeks, or months of history. `:granularity` groups that
window by day, week, or month; daily is the default. In a group, `:user` filters
by all or part of a participant's name.

Reports use recorded interactions, token counts, and model price snapshots.
They help compare conversations and expensive flows but are not provider
invoices. Missing usage metadata or price information can limit cost estimates.
Changing the active model does not reassign past interactions to the new model.

Use `!model` to inspect the current conversation model and review user/group
overrides in the panel when one conversation behaves differently.
