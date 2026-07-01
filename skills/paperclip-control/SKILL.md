# Paperclip Control Skill

Use this note when Hermes has the `paperclip-cockpit` plugin installed and the user asks about Paperclip companies, agents, tasks, issues, comments, or status changes.

## Operating Rule

Prefer deterministic Paperclip Cockpit commands over memory or speculation. Paperclip state changes quickly, so ask the plugin for current state instead of guessing.

The command name is configurable. Use `/pc` only when no project config changes it. If the project config defines a command such as `/work`, `/lab`, or another project word, use that command instead.

## Read Commands

- Use `<command> companies` to list organizations.
- Use `<command> health` to check the Paperclip API.
- Use `<command> status` for a compact workspace overview.
- Use `<command> agents [--company "Name"]` to list workers/agents in a company.
- Use `<command> tasks [--company "Name"] [open|all|todo|in_progress|blocked|done|cancelled] [limit]` to inspect work.
- Use `<command> task ISSUE` for one issue.
- Use `<command> comments ISSUE` for recent discussion.
- Use `<command> capabilities` to see plugin configuration and safety mode.
- Use `<command> debug` or append `full`/`raw` when the user needs technical detail.

## Write Commands

Only use `<command> move ISSUE STATUS` when the user explicitly asks to change Paperclip state. Do not infer a write from vague discussion.

If the project config exposes a `finalize` action, use `<command> finalize ISSUE` when the user explicitly asks to close a parent package/tree after child work is done. Treat it as a real write operation with the same caution as `move`.

Valid statuses:

- `todo`
- `in_progress`
- `blocked`
- `done`
- `cancelled`

The plugin may reject writes unless `PAPERCLIP_COCKPIT_ENABLE_WRITES=1` is set.

Some projects also enable `hooks.after_move.auto_finalize_parents_on_statuses`. In that case, a successful `<command> move ISSUE done|blocked|cancelled` may auto-finalize parent issues and leave durable Paperclip comments. Report only what the command actually returned.

## Project Actions

Project configs may define extra actions such as `research`, `prepare`, `brief`, or `run`. If the user asks to start/create/run project work and the config exposes a matching command, use that command instead of improvising with local files or code.

Project configs may also expose builtin actions through the same action registry. These are still deterministic plugin commands, not free-form model behavior.

When the user confirms a previously discussed plan, reuse the concrete entities from the visible conversation and call the configured project action with an explicit argument list. If the confirmation is too vague to identify the work, ask one short clarification.

## Durable Work And Truthfulness

Paperclip state means Paperclip API objects: companies, agents, issues/tasks, runs, comments, and their identifiers. Local markdown files, repo notes, and temporary scripts are not Paperclip state unless the project action explicitly imports them.

Do not claim that background agents, researchers, web research, or a future notification are active unless a durable Paperclip issue/run/automation was created or observed and you can name it. If a local file is a stub, say it is a local stub. If web tools are unavailable or did not run successfully, say that plainly.

For long-running or interrupt-prone work, prefer a configured project action that creates durable Paperclip work. Do not substitute `delegate_task`, `execute_code`, or ad-hoc local reads when the user asked to create/start/track work in Paperclip.

## Reporting Style

When answering the user:

- Label current state from the plugin as `Paperclip API`.
- Label your own synthesis as `Inference`.
- Keep task/comment output compact. The plugin defaults to human-readable summaries; use `full` only when the user asks for detail or debugging.
- Never reveal tokens, environment variables, chat IDs, or profile secrets.

## Telegram Behavior

The plugin can rewrite simple user messages into the configured command before the LLM runs. Treat those results as tool output, not as conversation memory.
