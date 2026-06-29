# Hermes Paperclip Cockpit

A compact Hermes plugin that turns Telegram into a deterministic control surface for Paperclip.

```text
Telegram -> Hermes command or rewrite hook -> Paperclip API
```

This is complementary to [NousResearch/hermes-paperclip-adapter](https://github.com/NousResearch/hermes-paperclip-adapter): that adapter lets Paperclip run Hermes-backed workers; this plugin lets Hermes operate Paperclip from a chat interface.

## What It Does

- Adds one visible Hermes command: `/pc`.
- Lists Paperclip companies, agents, tasks, task details, and comments.
- Can move an issue between Paperclip statuses when writes are explicitly enabled.
- Can rewrite simple natural-language Telegram messages into `/pc ...` commands before the LLM is called.
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
./scripts/install-local.sh inneragora
inneragora plugins enable paperclip-cockpit
```

The script copies this plugin into `~/.hermes/profiles/<profile>/plugins/paperclip-cockpit`.

## Environment

```bash
PAPERCLIP_API_BASE=http://127.0.0.1:3100/api
PAPERCLIP_PUBLIC_BASE=http://127.0.0.1:3100
PAPERCLIP_DEFAULT_COMPANY="The Inner Agora"

# Optional:
PAPERCLIP_COCKPIT_ENABLE_WRITES=0
PAPERCLIP_COCKPIT_NL_REWRITE=1
PAPERCLIP_COCKPIT_NL_WRITES=0
PAPERCLIP_COCKPIT_REGISTER_EXPLICIT=0
PAPERCLIP_COCKPIT_ALLOWED_PLATFORMS=telegram
PAPERCLIP_COCKPIT_ALLOWED_CHATS=
```

Company selection order:

1. `--company "Company Name"` in a command.
2. `PAPERCLIP_DEFAULT_COMPANY` or `PAPERCLIP_COMPANY_NAME`.
3. Compatibility variables such as `INNER_AGORA_COMPANY_NAME` or `AI_BOARD_COMPANY_NAME`.
4. The basename of `terminal.cwd` from the Hermes profile config.
5. The Hermes profile directory name.

## Commands

```text
/pc help
/pc companies
/pc health
/pc agents [--company NAME]
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
список философов в перклипе   -> /pc agents
что по THE-9                  -> /pc task THE-9
комменты THE-9                -> /pc comments THE-9
```

Write rewrites are disabled by default. To allow phrases like `move THE-9 done`, set both:

```bash
PAPERCLIP_COCKPIT_ENABLE_WRITES=1
PAPERCLIP_COCKPIT_NL_WRITES=1
```

## Model-Facing Skill

Copy or reference `skills/paperclip-control/SKILL.md` from your Hermes assistant profile. It tells the model:

- Paperclip facts should come from `/pc`, not memory.
- Writes require explicit user intent.
- Replies should label Paperclip API facts separately from inference.

## Development

Run local checks:

```bash
python3 -m py_compile __init__.py
python3 -m unittest discover -s tests
```

This plugin uses only the Python standard library.
