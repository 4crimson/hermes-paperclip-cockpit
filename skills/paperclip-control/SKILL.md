# Paperclip Control Skill

Use this note when Hermes has the `paperclip-cockpit` plugin installed and the user asks about Paperclip companies, agents, tasks, issues, comments, or status changes.

## Operating Rule

Prefer deterministic Paperclip Cockpit commands over memory or speculation. Paperclip state changes quickly, so ask the plugin for current state instead of guessing.

The command name is configurable. Use `/pc` only when no project config changes it. If the project config defines a command such as `/work`, `/lab`, or another project word, use that command instead.

## Read Commands

- Use `<command> companies` to list organizations.
- Use `<command> health` to check the Paperclip API.
- Use `<command> agents [--company "Name"]` to list workers/agents in a company.
- Use `<command> tasks [--company "Name"] [open|all|todo|in_progress|blocked|done|cancelled] [limit]` to inspect work.
- Use `<command> task ISSUE` for one issue.
- Use `<command> comments ISSUE` for recent discussion.
- Use `<command> capabilities` to see plugin configuration and safety mode.

## Write Commands

Only use `<command> move ISSUE STATUS` when the user explicitly asks to change Paperclip state. Do not infer a write from vague discussion.

Valid statuses:

- `todo`
- `in_progress`
- `blocked`
- `done`
- `cancelled`

The plugin may reject writes unless `PAPERCLIP_COCKPIT_ENABLE_WRITES=1` is set.

## Reporting Style

When answering the user:

- Label current state from the plugin as `Paperclip API`.
- Label your own synthesis as `Inference`.
- Keep task/comment output compact; ask for a specific issue before dumping long history.
- Never reveal tokens, environment variables, chat IDs, or profile secrets.

## Telegram Behavior

The plugin can rewrite simple user messages into the configured command before the LLM runs. Treat those results as tool output, not as conversation memory.
