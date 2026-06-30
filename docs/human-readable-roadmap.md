# Human-Readable Presentation Roadmap

Goal: make `hermes-paperclip-cockpit` a beautiful, calm, low-noise Telegram control surface for Paperclip, while keeping the plugin domain-neutral and reusable across many projects.

The plugin must not contain project-specific nouns such as philosopher, agora, board, researcher, director, council, or any other deployment-specific vocabulary. Projects provide their words, labels, aliases, and visible menu copy through `paperclip-cockpit.json`.

## Product Principles

1. Human first, debug second.
   Default Telegram output should be short, readable, and useful to a non-engineer. Technical details remain available through explicit `debug`, `full`, `raw`, or `capabilities` commands.

2. No domain nouns in plugin code.
   The plugin only knows generic Paperclip concepts: companies, agents, tasks/issues, comments, runs, actions, health, capabilities, and errors.

3. Configuration owns the voice.
   Project config controls command name, visible terms, aliases, menu items, section titles, limits, and whether technical details are shown.

4. Stable behavior beats clever prose.
   Slash commands and natural-language rewrites should be deterministic. The model should not be needed for routine Paperclip state.

5. Minimal symbols.
   Default output should avoid dense CLI formatting, UUIDs, long dashed separators, nested bullets, and noisy status tables. A few plain bullets are fine.

6. Honest durable work.
   The plugin must never imply background monitoring, future notifications, or research-in-progress unless Paperclip has a real issue/run/automation that proves it.

7. Backward compatible by default.
   Existing raw command behavior should remain available. Human presentation should wrap or replace default views without removing technical escape hatches.

## Target Command Experience

### Home

Default command with no arguments should not show raw `Usage`, `Safety`, or `Company selection` blocks.

Generic shape:

```text
Connected to Paperclip.

Useful commands:
- /pc status - show current state
- /pc latest - show the latest task summary
- /pc agents - show the team
- /pc tasks - show active tasks

More:
- /pc help full
- /pc debug
```

Project config may replace every visible sentence:

```json
{
  "presentation": {
    "home": {
      "intro": "I am connected to Paperclip.",
      "items": [
        { "action": "status", "text": "show current state" },
        { "action": "latest", "text": "show latest task summary" },
        { "action": "agents", "text": "show the team" },
        { "action": "tasks", "text": "show active tasks" }
      ],
      "more": [
        { "command": "help full", "text": "technical help" },
        { "command": "debug", "text": "diagnostics" }
      ]
    }
  }
}
```

The plugin resolves `action` through configured terms and command name. A project can display `/work team` or `/lab reviewers` without the plugin knowing those words.

### Help

Default `/pc help` should be a human help page.

`/pc help full`, `/pc help raw`, or `/pc debug` should show the current full technical output:

- usage
- safety switches
- company selection order
- action registry
- config paths
- read/write settings

### Status

Default `/pc status` should answer the question: "Is the Paperclip workspace alive and what matters right now?"

Generic shape:

```text
Paperclip is reachable.

Agents: 18
Active agents: 2
Open tasks: 4
Latest task: ABC-42
Latest done task: ABC-39

Details:
- /pc tasks
- /pc status full
```

The default status should not list every idle agent, every run, or UUIDs.

`/pc status full` should expose the current raw detailed view.

### Agents

Default `/pc agents` should be compact.

Generic shape:

```text
Agents: 18

Active:
- Alice
- Build Bot

Idle: 16

More:
- /pc agents full
- /pc agents --tags
```

If all agents are idle, show a count and a short sample instead of 80 repeated `idle` rows.

`/pc agents full` keeps the current detailed list.

### Tasks

Default `/pc tasks` should show open tasks first and keep the list short.

Generic shape:

```text
Open tasks: 4

- ABC-42 - in progress - Prepare release notes
- ABC-41 - todo - Review source mapping
- ABC-40 - blocked - Waiting for API key
- ABC-38 - todo - Add integration tests

More:
- /pc tasks all
- /pc tasks full
```

No raw UUIDs in default mode. Use issue identifiers when available.

### One Task

Default `/pc task ABC-42` should show a readable task card.

Generic shape:

```text
ABC-42
Prepare release notes

Status: in progress
Assignee: Alice
Parent: none

Recent notes:
- Alice, 12:10: Draft is ready.
- User, 12:15: Add migration warning.

Open:
http://127.0.0.1:3100/issues/...
```

`/pc task ABC-42 full` can include full description, raw metadata, hidden fields, and all comments.

### Comments

Default `/pc comments ABC-42` should show the last few comments with clean authors and clipped text.

Config controls comment limit and clip length.

`/pc comments ABC-42 full` shows the full comment stream.

### Runs

Runs are debug information by default. They should not appear in normal `status` unless configured.

If shown in human mode, summarize:

```text
Recent runs: 12
Succeeded: 10
Cancelled: 1
Failed: 1
```

Raw run IDs only belong in `status full` or `debug`.

### Project Actions

Project action output should be passed through a presentation filter unless the action opts out.

Config knobs:

```json
{
  "actions": {
    "example": {
      "exec": ["node", "scripts/example.mjs"],
      "presentation": {
        "mode": "passthrough",
        "clip": 6000
      }
    }
  }
}
```

Supported action presentation modes:

- `passthrough`: current behavior, clipped only.
- `human`: apply generic cleanup, hide debug blocks when possible.
- `raw`: never touch output.

### Errors

Default errors should be plain:

```text
I could not reach Paperclip.

Check that the local Paperclip API is running.

Details:
/pc debug
```

`presentation.errors.show_details` can include the raw exception text directly.

## Proposed Config Schema

The schema should be permissive: missing values fall back to neutral English text and current behavior where possible.

```json
{
  "presentation": {
    "mode": "human",
    "language": "en",
    "symbols": "minimal",
    "show_technical_by_default": false,
    "status_words": {
      "todo": "todo",
      "in_progress": "in progress",
      "blocked": "blocked",
      "done": "done",
      "cancelled": "cancelled",
      "idle": "idle",
      "active": "active"
    },
    "limits": {
      "agents": 12,
      "tasks": 10,
      "comments": 3,
      "comment_chars": 500,
      "runs": 0,
      "line_chars": 900,
      "output_chars": 12000
    },
    "home": {
      "intro": "Connected to Paperclip.",
      "title": "",
      "items": [
        { "action": "status", "text": "show current state" },
        { "action": "agents", "text": "show agents" },
        { "action": "tasks", "text": "show tasks" }
      ],
      "more": [
        { "command": "help full", "text": "technical help" },
        { "command": "debug", "text": "diagnostics" }
      ]
    },
    "sections": {
      "useful_commands": "Useful commands:",
      "more": "More:",
      "details": "Details:",
      "recent_comments": "Recent comments:",
      "open_tasks": "Open tasks:",
      "active_agents": "Active:",
      "idle_agents": "Idle:"
    },
    "visibility": {
      "home_safety": false,
      "home_company_selection": false,
      "status_agents": "summary",
      "status_tasks": "summary",
      "status_runs": false,
      "agent_status_rows": "active_only",
      "uuids": false
    },
    "debug": {
      "commands": ["debug", "capabilities"],
      "full_tokens": ["full", "raw", "--raw", "--full"]
    },
    "errors": {
      "show_details": false,
      "show_debug_hint": true
    }
  }
}
```

Existing `labels`, `terms`, and `aliases` remain the vocabulary layer:

```json
{
  "labels": {
    "agent": "agent",
    "agents": "agents",
    "task": "task",
    "tasks": "tasks"
  },
  "terms": {
    "agents": "agents",
    "tasks": "tasks",
    "comments": "comments"
  },
  "aliases": {
    "agents": ["people", "team"],
    "tasks": ["issues", "queue"]
  }
}
```

Project-specific words belong here, never in plugin code.

## Implementation Phases

### Phase 1: Presentation Core

Add config helpers:

- `_presentation_config()`
- `_presentation_mode()`
- `_is_full_request(raw_args)`
- `_human_enabled()`
- `_limit(name, default)`
- `_status_word(value)`
- `_format_command(action_or_command)`
- `_line(text, limit)`

Add one small formatting layer:

- plain section headers
- bullet formatting
- line clipping
- list clipping with "and N more"
- issue identifier preference over UUID

Acceptance:

- Existing tests pass.
- With no config, current behavior remains available.
- Human mode can be enabled without project-specific words.

### Phase 2: Human Home and Help

Replace default no-arg `_help()` output in human mode.

Add:

- `_human_home()`
- `_technical_help()`
- `help full` / `help raw`
- `debug` alias to technical diagnostics

Acceptance:

- `/pc` in human mode does not contain `Usage:`, `Safety:`, or `Company selection:`.
- `/pc help full` still contains the technical help.
- Configured command name is used in visible examples.
- Configured `home.items` can point to actions or literal commands.

### Phase 3: Human Status

Add generic plugin-native `status` route or make current `capabilities/status` distinction explicit.

Human status should compute:

- Paperclip reachable
- selected company
- total agents
- active agents
- open tasks
- latest visible root task
- latest visible done task
- optional run summary

Acceptance:

- Default status does not list every idle agent.
- Default status does not print run UUIDs.
- `status full` preserves detailed view.
- Config can hide or show agents, tasks, and runs.

### Phase 4: Human Agents

Update `_agents_cmd`:

- default compact view
- active agents first
- idle count
- optional sample
- tags summary as before
- `agents full` for full table

Acceptance:

- If 80 agents are idle, default output is still short.
- `agents --tags` remains supported.
- `agents --tag research` remains supported.
- Full mode preserves adapter, role, tags, status.

### Phase 5: Human Tasks

Update `_tasks_cmd`:

- default limit from config
- open tasks first
- issue identifier, status word, title
- optional parent marker only if useful
- no UUIDs by default
- `tasks full` or `tasks all full` for raw/detail mode

Acceptance:

- Default tasks output fits in one Telegram message for normal projects.
- `tasks all 50 full` remains available.
- Status filtering remains unchanged.

### Phase 6: Human Task and Comments

Update `_task_cmd` and `_comments_cmd`:

- readable task card
- last N comments
- clipped description
- full mode for complete description/comments
- author/date formatting that does not feel like logs

Acceptance:

- `task ABC-1` is readable by a human.
- `task ABC-1 full` exposes technical detail.
- `comments ABC-1` does not flood Telegram by default.

### Phase 7: Project Action Presentation

Add optional action output presentation:

```json
{
  "actions": {
    "latest": {
      "exec": ["node", "scripts/latest.mjs"],
      "presentation": {
        "mode": "human",
        "clip": 10000
      }
    }
  }
}
```

Initial implementation may only support `raw`, `passthrough`, and clipping. Later versions can add structured action output if scripts return JSON.

Acceptance:

- Existing project actions keep working.
- Default action behavior remains passthrough.
- Config can reduce noisy action output.

### Phase 8: Errors and Recovery Messages

Wrap Paperclip/API errors:

- short human message
- optional detail block
- debug hint

Acceptance:

- Human mode does not dump Python exception text by default.
- Full/debug mode preserves actionable technical details.
- Errors still include enough information to recover.

### Phase 9: Documentation and Examples

Update:

- `README.md`
- `examples/paperclip-cockpit.example.json`
- `skills/paperclip-control/SKILL.md`

Add examples:

- generic team project
- research project
- localized Russian labels
- debug-heavy operator profile

Acceptance:

- README explains human vs debug mode.
- Example config has no project-specific private paths.
- Skill tells the model to prefer cockpit commands for Paperclip facts.

### Phase 10: Release Hardening

Before publishing:

- run py_compile and unit tests
- add snapshot tests for human outputs
- test no-config fallback
- test custom command name
- test localized terms
- test full/raw escape hatches
- test large agent/task lists
- test Paperclip down
- test malformed config

Acceptance:

- No command produces unbounded output by default.
- No project-specific noun appears in plugin source.
- No live restart is needed to validate formatting locally.

## Test Plan

Unit tests should cover formatting without requiring a live Paperclip server where possible. Mock `_api`.

Core snapshots:

1. `help_human_default`
   - Input: `/pc`
   - Assert: contains configured intro.
   - Assert: does not contain `Safety:` or `Company selection:`.

2. `help_full_raw`
   - Input: `/pc help full`
   - Assert: contains `Usage:`.
   - Assert: contains safety settings.

3. `status_human_large_roster`
   - 80 idle agents, 0 active agents.
   - Assert: output contains `Agents: 80`.
   - Assert: output does not contain 80 idle rows.

4. `status_human_runs_hidden`
   - Recent runs with UUIDs.
   - Assert: no UUID pattern in default output.

5. `agents_human_active_only`
   - Mixed active and idle agents.
   - Assert: active names shown.
   - Assert: idle summarized.

6. `agents_full_preserves_detail`
   - Assert: role, adapter, tags remain visible.

7. `tasks_human_limits`
   - 30 tasks.
   - Assert: only configured limit appears.
   - Assert: "and N more" appears.

8. `task_human_card`
   - Assert: card fields readable.
   - Assert: comments clipped.

9. `comments_full`
   - Assert: full comment stream available.

10. `project_terms_are_config_only`
   - Use custom terms such as `operators`.
   - Assert: visible commands use configured term.
   - Assert: plugin source has no deployment-specific noun.

## Non-Goals

- Do not build a full templating language in the first version.
- Do not make the LLM rewrite command output.
- Do not hide write safety internally. Hide it from default human help, but keep it in debug/capabilities.
- Do not remove raw technical commands.
- Do not encode any one project vocabulary into plugin source.

## Migration Strategy

1. Land presentation helpers with no behavior change.
2. Enable human home behind config.
3. Enable human status behind config.
4. Convert agents/tasks/task/comments one by one.
5. Update example config.
6. Configure one real project as a pilot.
7. Compare old vs new outputs in local command calls.
8. Only after review, apply to a live Hermes profile.

## Done Definition

The plugin is ready when:

- A non-technical user can type the command with no args and understand what to do next.
- Default status answers "what is happening?" in less than one Telegram screen.
- Large rosters and long run histories never flood chat by default.
- Full technical detail is still one explicit command away.
- Project-specific language is entirely config-driven.
- Tests cover human mode, raw mode, custom terms, and large output.
- No restart or live gateway manipulation is required for normal formatting tests.
