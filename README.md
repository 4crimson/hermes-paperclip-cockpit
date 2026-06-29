# Hermes Paperclip Cockpit

A compact Hermes plugin that turns Telegram into a deterministic control surface for Paperclip.

```text
Telegram -> Hermes command or rewrite hook -> Paperclip API
```

This is complementary to [NousResearch/hermes-paperclip-adapter](https://github.com/NousResearch/hermes-paperclip-adapter): that adapter lets Paperclip run Hermes-backed workers; this plugin lets Hermes operate Paperclip from a chat interface.

## What It Does

- Adds one visible Hermes command. Default: `/pc`; configurable per project.
- Lists Paperclip companies, agents, tasks, task details, and comments.
- Can move an issue between Paperclip statuses when writes are explicitly enabled.
- Can rewrite simple natural-language Telegram messages into `/pc ...` commands before the LLM is called.
- Can route project-specific natural-language intents into configured project actions.
- Keeps Paperclip control out of the model context, which helps avoid slow or bloated prompts.
- Ships a model-facing skill note in `skills/paperclip-control/SKILL.md`.

## Safety Defaults

The public defaults are intentionally conservative:

- Slash-command reads are enabled.
- Slash-command writes are disabled unless `PAPERCLIP_COCKPIT_ENABLE_WRITES=1`.
- Natural-language rewrites are enabled for read operations.
- Natural-language writes are disabled unless `PAPERCLIP_COCKPIT_NL_WRITES=1`.
- Only `/pc` is registered by default, so Telegram command menus stay small.

## Install

From GitHub after this repository is published:

```bash
hermes plugins install 4crimson/hermes-paperclip-cockpit --enable
```

For local development:

```bash
./scripts/install-local.sh myprofile
myprofile plugins enable paperclip-cockpit
```

The script copies this plugin into `~/.hermes/profiles/<profile>/plugins/paperclip-cockpit`.

## Environment

```bash
PAPERCLIP_API_BASE=http://127.0.0.1:3100/api
PAPERCLIP_PUBLIC_BASE=http://127.0.0.1:3100
PAPERCLIP_DEFAULT_COMPANY="Example Workspace"

# Optional:
PAPERCLIP_COCKPIT_ENABLE_WRITES=0
PAPERCLIP_COCKPIT_NL_REWRITE=1
PAPERCLIP_COCKPIT_NL_WRITES=0
PAPERCLIP_COCKPIT_REGISTER_EXPLICIT=0
PAPERCLIP_COCKPIT_ALLOWED_PLATFORMS=telegram
PAPERCLIP_COCKPIT_ALLOWED_CHATS=
```

## Project Config

Put `paperclip-cockpit.json` in the Hermes profile directory or in the profile `terminal.cwd`.

If a config defines a command name, that command replaces `/pc` in the Telegram menu. For example, `"name": "work"` registers `/work`, not `/pc`.

See `examples/paperclip-cockpit.example.json` for a generic placeholder config. The plugin itself should not contain project-specific nouns, scripts, or prompts.

Optional gateway behavior:

```json
{
  "gateway": {
    "reset_on_gateway_shutdown": true
  }
}
```

When enabled, the plugin resets Hermes gateway sessions that Hermes marked as `resume_pending` after an interrupted gateway shutdown. This is useful for command-cockpit profiles where a fresh Telegram turn is safer than automatic continuation.

Company selection order:

1. `--company "Company Name"` in a command.
2. `company_hints` in `paperclip-cockpit.json`.
3. `PAPERCLIP_DEFAULT_COMPANY` or `PAPERCLIP_COMPANY_NAME`.
4. The basename of `terminal.cwd` from the Hermes profile config.
5. The Hermes profile directory name.

## Commands

```text
/pc help
/pc companies
/pc health
/pc agents [--company NAME] [--tags|--tag TAG]
/pc tasks [--company NAME] [open|all|todo|in_progress|blocked|done|cancelled] [limit]
/pc task ISSUE
/pc comments ISSUE
/pc move ISSUE <todo|in_progress|blocked|done|cancelled>
/pc capabilities
```

Short aliases:

```text
/pc orgs
/pc people
/pc list
/pc t ISSUE
/pc m ISSUE STATUS
```

## Natural-Language Rewrites

When `PAPERCLIP_COCKPIT_PRE_GATEWAY=1`, the plugin can rewrite simple messages before they reach the LLM:

```text
show paperclip companies      -> /pc companies
покажи задачи                 -> /pc tasks
who is in paperclip           -> /pc agents
what about ABC-9              -> /pc task ABC-9
comments ABC-9                -> /pc comments ABC-9
```

If agents carry `metadata.tags`, the agents command displays them. Use `/pc agents --tags` for a tag summary or `/pc agents --tag research` to filter agents by one tag.

Project configs can also map explicit natural-language intents to project actions:

```json
{
  "actions": {
    "research": {
      "usage": "research QUESTION",
      "exec": ["./scripts/research"]
    }
  },
  "intents": {
    "create_research": {
      "action": "research",
      "aliases": ["start research", "create research task"],
      "require_tail": true,
      "min_tail_chars": 10
    }
  }
}
```

This keeps project words in `paperclip-cockpit.json`: the plugin only knows how to route an intent to an action. Use `require_tail` and `min_tail_chars` for actions that create work, so vague confirmations do not become empty tasks.

Write rewrites are disabled by default. To allow phrases like `move THE-9 done`, set both:

```bash
PAPERCLIP_COCKPIT_ENABLE_WRITES=1
PAPERCLIP_COCKPIT_NL_WRITES=1
```

## Model-Facing Skill

Copy or reference `skills/paperclip-control/SKILL.md` from your Hermes assistant profile. It tells the model:

- Paperclip facts should come from the configured command, not memory.
- Writes require explicit user intent.
- Replies should label Paperclip API facts separately from inference.

Project-specific wording belongs in `paperclip-cockpit.json`, not in the plugin.

## Development

Run local checks:

```bash
python3 -m py_compile __init__.py
python3 -m unittest discover -s tests
```

This plugin uses only the Python standard library.
