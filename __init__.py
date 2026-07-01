from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_CONFIG_READ_WARNINGS: dict[str, str] = {}

PLUGIN_NAME = "paperclip-cockpit"
VERSION = "0.6.2"

API_BASE = os.environ.get("PAPERCLIP_API_BASE", "http://127.0.0.1:3100/api").rstrip("/")
PUBLIC_BASE = os.environ.get("PAPERCLIP_PUBLIC_BASE", API_BASE.removesuffix("/api")).rstrip("/")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

TASK_STATUSES = {"todo", "in_progress", "blocked", "done", "cancelled"}
OPEN_STATUSES = {"todo", "in_progress", "blocked"}
TERMINAL_STATUSES = {"done", "blocked", "cancelled"}
ISSUE_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,12}-\d+)\b", re.IGNORECASE)
COMMAND_RE = re.compile(r"[^0-9a-z_]+")

DEFAULT_LABELS = {
    "company": "company",
    "companies": "companies",
    "agent": "agent",
    "agents": "agents",
    "task": "task",
    "tasks": "tasks",
    "comment": "comment",
    "comments": "comments",
}

DEFAULT_TERMS = {
    "companies": "companies",
    "health": "health",
    "status": "status",
    "agents": "agents",
    "tasks": "tasks",
    "task": "task",
    "comments": "comments",
    "move": "move",
    "capabilities": "capabilities",
    "debug": "debug",
}

DEFAULT_ALIASES = {
    "help": ["help", "commands", "?", "помощь", "команды"],
    "companies": [
        "companies",
        "company",
        "orgs",
        "org",
        "organizations",
        "list companies",
        "организации",
        "компании",
        "компаний",
        "список компаний",
        "список организаций",
    ],
    "health": ["health", "ping", "здоровье"],
    "status": ["status", "state", "overview", "статус", "состояние"],
    "agents": ["agents", "people", "staff", "roster", "who is in", "агенты", "сотрудники"],
    "tasks": ["tasks", "issues", "list", "таски", "задачи"],
    "task": ["task", "issue", "t", "задача"],
    "comments": ["comments", "comment", "комменты", "комментарии"],
    "move": ["move", "m", "двинь", "перемести"],
    "capabilities": ["capabilities", "caps", "config", "settings", "возможности", "настройки"],
    "debug": ["debug", "diagnostics", "diag", "raw", "отладка", "диагностика"],
}

DEFAULT_MARKERS = ["paperclip", "пеперклип", "перклип", "pc", "пер клип"]

DEFAULT_PRESENTATION = {
    "mode": "human",
    "language": "en",
    "symbols": "minimal",
    "show_technical_by_default": False,
    "status_words": {
        "todo": "todo",
        "in_progress": "in progress",
        "blocked": "blocked",
        "done": "done",
        "cancelled": "cancelled",
        "idle": "idle",
        "active": "active",
        "succeeded": "succeeded",
        "failed": "failed",
        "cancelled_run": "cancelled",
    },
    "limits": {
        "agents": 12,
        "tasks": 10,
        "comments": 3,
        "comment_chars": 500,
        "runs": 0,
        "line_chars": 900,
        "output_chars": 12000,
    },
    "home": {
        "intro": "Connected to Paperclip.",
        "title": "",
        "items": [
            {"action": "status", "text": "show current state"},
            {"action": "agents", "text": "show agents"},
            {"action": "tasks", "text": "show tasks"},
        ],
        "more": [
            {"command": "help full", "text": "technical help"},
            {"action": "debug", "text": "diagnostics"},
        ],
    },
    "sections": {
        "useful_commands": "Useful commands:",
        "more": "More:",
        "details": "Details:",
        "recent_comments": "Recent comments:",
        "open_tasks": "Open tasks:",
        "active_agents": "Active:",
        "idle_agents": "Idle:",
    },
    "visibility": {
        "home_safety": False,
        "home_company_selection": False,
        "status_agents": "summary",
        "status_tasks": "summary",
        "status_runs": False,
        "agent_status_rows": "active_only",
        "uuids": False,
    },
    "debug": {
        "commands": ["debug", "capabilities"],
        "full_tokens": ["full", "raw", "--raw", "--full"],
    },
    "errors": {
        "show_details": False,
        "show_debug_hint": True,
    },
}

DEFAULT_NOTIFICATIONS = {
    "comments": {
        "move_status_changed": "Status changed via Paperclip Cockpit: {old_status} -> {new_status}.",
        "auto_finalized": "Automatically finalized via Paperclip Cockpit: all visible child issues are in terminal statuses.",
    }
}

DEFAULT_HELP_TEXT = {
    "en": {
        "usage_heading": "Usage:",
        "project_actions_heading": "Project actions:",
        "safety_heading": "Safety:",
        "slash_writes": "slash-command writes",
        "natural_writes": "natural-language writes",
        "enabled": "enabled",
        "disabled": "disabled",
        "company_heading": "Company selection:",
        "company_config_hints": "- config company_hints",
        "company_env": "- env PAPERCLIP_DEFAULT_COMPANY or PAPERCLIP_COMPANY_NAME",
        "company_cwd": "- otherwise Hermes terminal.cwd is fuzzy-matched to a Paperclip company",
        "company_flag": "- pass --company \"Company Name\" when needed",
    },
    "ru": {
        "usage_heading": "Команды:",
        "project_actions_heading": "Команды проекта:",
        "safety_heading": "Безопасность:",
        "slash_writes": "записи через slash-команды",
        "natural_writes": "записи через обычный текст",
        "enabled": "включены",
        "disabled": "выключены",
        "company_heading": "Выбор компании:",
        "company_config_hints": "- подсказки из config company_hints",
        "company_env": "- переменные PAPERCLIP_DEFAULT_COMPANY или PAPERCLIP_COMPANY_NAME",
        "company_cwd": "- иначе Hermes terminal.cwd сопоставляется с компанией Paperclip",
        "company_flag": "- можно явно передать --company \"Company Name\"",
    },
}

DEFAULT_COMMAND_DESCRIPTIONS = {
    "en": {
        "help": "show commands",
        "companies": "list companies",
        "health": "check Paperclip API health",
        "status": "short workspace overview",
        "agents": "list agents",
        "tasks": "list issues",
        "task": "show one issue",
        "comments": "show issue comments",
        "move": "move issue status",
        "capabilities": "show plugin capabilities",
        "debug": "diagnostics",
    },
    "ru": {
        "help": "показать команды",
        "companies": "список компаний",
        "health": "проверить Paperclip API",
        "status": "краткий обзор состояния",
        "agents": "список агентов",
        "tasks": "список задач",
        "task": "показать одну задачу",
        "comments": "показать комментарии задачи",
        "move": "изменить статус задачи",
        "capabilities": "показать возможности плагина",
        "debug": "диагностика",
    },
}


class PaperclipError(RuntimeError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "y", "on"}


def _env_csv(name: str) -> set[str]:
    raw = os.environ.get(name, "")
    return {item.strip().casefold() for item in raw.split(",") if item.strip()}


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on"}


def _as_positive_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _writes_enabled() -> bool:
    return _env_bool("PAPERCLIP_COCKPIT_ENABLE_WRITES", False)


def _nl_writes_enabled() -> bool:
    return _env_bool("PAPERCLIP_COCKPIT_NL_WRITES", False)


def _clip(text: str, limit: int = 12000) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n[... clipped {len(text) - limit} chars ...]"


def _api(path: str, *, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 10) -> Any:
    url = f"{API_BASE}{path}"
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else None
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        raise PaperclipError(f"{method} {path} failed: HTTP {exc.code} {text}") from exc
    except Exception as exc:
        raise PaperclipError(f"{method} {path} failed: {exc}") from exc


def _parse_words(raw_args: str) -> list[str]:
    try:
        return shlex.split(raw_args)
    except ValueError:
        return raw_args.split()


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", str(text or "").casefold())


def _compact_id(value: str, size: int = 8) -> str:
    return str(value or "")[:size]


def _nested_yaml_value(text: str, section: str, key: str) -> str:
    in_section = False
    for line in text.splitlines():
        if line and not line.startswith((" ", "\t")):
            in_section = line.strip() == f"{section}:"
            continue
        if not in_section:
            continue
        match = re.match(rf"^\s+{re.escape(key)}:\s*(.*?)\s*$", line)
        if match:
            return match.group(1).strip().strip("'\"")
    return ""


def _config_cwd_hint() -> str:
    try:
        config = (HERMES_HOME / "config.yaml").read_text("utf-8")
    except Exception:
        return ""
    cwd = _nested_yaml_value(config, "terminal", "cwd")
    if not cwd:
        return ""
    return Path(cwd).name


def _terminal_cwd() -> str:
    try:
        config = (HERMES_HOME / "config.yaml").read_text("utf-8")
    except Exception:
        return ""
    return _nested_yaml_value(config, "terminal", "cwd")


def _read_json(path: Path) -> dict[str, Any]:
    path_key = str(path)
    try:
        data = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        _CONFIG_READ_WARNINGS.pop(path_key, None)
        return {}
    except Exception as exc:
        message = str(exc)
        if _CONFIG_READ_WARNINGS.get(path_key) != message:
            logger.warning("Could not read Paperclip Cockpit config %s: %s", path, exc)
            _CONFIG_READ_WARNINGS[path_key] = message
        return {}
    _CONFIG_READ_WARNINGS.pop(path_key, None)
    return data if isinstance(data, dict) else {}


def _merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _config_paths() -> list[Path]:
    explicit = os.environ.get("PAPERCLIP_COCKPIT_CONFIG")
    if explicit:
        return [Path(explicit).expanduser()]

    paths = [HERMES_HOME / "paperclip-cockpit.json"]
    cwd = _terminal_cwd()
    if cwd:
        paths.append(Path(cwd) / "paperclip-cockpit.json")
    return paths


def _config() -> dict[str, Any]:
    config: dict[str, Any] = {
        "command": {"name": "pc"},
        "labels": DEFAULT_LABELS,
        "terms": DEFAULT_TERMS,
        "aliases": DEFAULT_ALIASES,
        "markers": DEFAULT_MARKERS,
        "actions": {},
        "intents": {},
        "gateway": {},
        "hooks": {},
        "notifications": DEFAULT_NOTIFICATIONS,
        "presentation": DEFAULT_PRESENTATION,
    }
    for path in _config_paths():
        config = _merge_dict(config, _read_json(path))
    return config


def _gateway_config() -> dict[str, Any]:
    config = _config().get("gateway", {})
    return config if isinstance(config, dict) else {}


def _hooks_config() -> dict[str, Any]:
    config = _config().get("hooks", {})
    return config if isinstance(config, dict) else {}


def _notifications_config() -> dict[str, Any]:
    raw = _config().get("notifications", {})
    return _merge_dict(DEFAULT_NOTIFICATIONS, raw if isinstance(raw, dict) else {})


def _notification_comment_template(key: str) -> str:
    comments = _notifications_config().get("comments", {})
    if not isinstance(comments, dict):
        comments = {}
    return str(comments.get(key) or DEFAULT_NOTIFICATIONS["comments"].get(key) or "")


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _notification_text(key: str, **values: Any) -> str:
    template = _notification_comment_template(key).strip()
    if not template:
        return ""
    try:
        return template.format_map(_SafeFormatDict({name: "" if value is None else value for name, value in values.items()})).strip()
    except Exception:
        logger.warning("Paperclip Cockpit could not format notification template %s", key)
        return template


def _post_issue_comment(issue_id: str, body: str, *, log_context: str) -> bool:
    text = str(body or "").strip()
    if not text:
        return False
    try:
        _api(f"/issues/{issue_id}/comments", method="POST", body={"body": text})
        return True
    except Exception as exc:
        logger.info("Paperclip comment failed for %s: %s", log_context, exc)
        return False


def _after_move_auto_finalize_statuses() -> set[str]:
    hooks = _hooks_config()
    after_move = hooks.get("after_move", {}) if isinstance(hooks, dict) else {}
    if not isinstance(after_move, dict):
        return set()
    values = (
        after_move.get("auto_finalize_parents_on_statuses")
        or after_move.get("auto_finalize_statuses")
        or after_move.get("finalize_on_statuses")
    )
    return {str(item).strip().casefold() for item in _listify(values) if str(item).strip()}


def _reset_on_gateway_shutdown_enabled() -> bool:
    env_value = os.environ.get("PAPERCLIP_COCKPIT_RESET_ON_GATEWAY_SHUTDOWN")
    if env_value is not None:
        return _env_bool("PAPERCLIP_COCKPIT_RESET_ON_GATEWAY_SHUTDOWN", False)

    gateway = _gateway_config()
    for key in ("reset_on_gateway_shutdown", "reset_on_shutdown_interruption", "reset_interrupted_context"):
        if key in gateway:
            return _as_bool(gateway.get(key), False)
    return False


def _reset_on_gateway_shutdown_reasons() -> set[str]:
    gateway = _gateway_config()
    reasons = (
        gateway.get("reset_resume_reasons")
        or gateway.get("reset_on_gateway_shutdown_reasons")
        or gateway.get("reset_interrupted_reasons")
    )
    return {item.strip().casefold() for item in _listify(reasons) if item.strip()}


def _gateway_reset_age_minutes() -> float | None:
    gateway = _gateway_config()
    return _as_positive_float(
        gateway.get("reset_session_age_minutes")
        or gateway.get("reset_after_minutes")
        or gateway.get("max_session_age_minutes")
    )


def _gateway_reset_idle_minutes() -> float | None:
    gateway = _gateway_config()
    return _as_positive_float(
        gateway.get("reset_idle_minutes")
        or gateway.get("reset_after_idle_minutes")
        or gateway.get("max_idle_minutes")
    )


def _sanitize_command_name(value: str) -> str:
    raw = str(value or "").strip().casefold().replace("-", "_")
    cleaned = COMMAND_RE.sub("", raw)
    return cleaned or "pc"


def _command_name() -> str:
    config = _config()
    env_name = os.environ.get("PAPERCLIP_COCKPIT_COMMAND", "")
    raw = env_name or config.get("command_prefix") or config.get("command", {}).get("name") or "pc"
    return _sanitize_command_name(str(raw))


def _slash(*parts: str) -> str:
    command = f"/{_command_name()}"
    tail = " ".join(part for part in parts if part)
    return f"{command} {tail}".strip()


def _label(key: str) -> str:
    labels = _config().get("labels", {})
    return str(labels.get(key) or DEFAULT_LABELS.get(key) or key)


def _term(key: str) -> str:
    terms = _config().get("terms", {})
    return str(terms.get(key) or DEFAULT_TERMS.get(key) or key)


def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _aliases(key: str) -> set[str]:
    aliases = set(DEFAULT_ALIASES.get(key, []))
    aliases.add(key)
    aliases.add(_term(key))
    configured = _config().get("aliases", {})
    aliases.update(_listify(configured.get(key)))
    return {item.strip().casefold() for item in aliases if item.strip()}


def _markers() -> set[str]:
    markers = set(DEFAULT_MARKERS)
    markers.add(_command_name())
    markers.update(_listify(_config().get("markers")))
    return {item.strip().casefold() for item in markers if item.strip()}


def _presentation_config() -> dict[str, Any]:
    raw = _config().get("presentation", {})
    return _merge_dict(DEFAULT_PRESENTATION, raw if isinstance(raw, dict) else {})


def _presentation_language() -> str:
    env_language = os.environ.get("PAPERCLIP_COCKPIT_LANGUAGE", "")
    raw = env_language or _presentation_config().get("language") or _config().get("language") or "en"
    language = str(raw).strip().casefold().split("-")[0]
    return language if language in DEFAULT_HELP_TEXT else "en"


def _help_config() -> dict[str, Any]:
    help_config = _presentation_config().get("help", {})
    return help_config if isinstance(help_config, dict) else {}


def _help_text(key: str) -> str:
    configured = _help_config().get(key)
    if configured is not None:
        return str(configured)
    language = _presentation_language()
    return DEFAULT_HELP_TEXT.get(language, DEFAULT_HELP_TEXT["en"]).get(key, DEFAULT_HELP_TEXT["en"].get(key, key))


def _command_description(key: str) -> str:
    configured = _help_config().get("command_descriptions", {})
    if isinstance(configured, dict) and configured.get(key):
        return str(configured.get(key))
    language = _presentation_language()
    descriptions = DEFAULT_COMMAND_DESCRIPTIONS.get(language, DEFAULT_COMMAND_DESCRIPTIONS["en"])
    return str(descriptions.get(key) or "")


def _presentation_mode() -> str:
    env_mode = os.environ.get("PAPERCLIP_COCKPIT_PRESENTATION", "")
    mode = env_mode or _presentation_config().get("mode") or "human"
    return str(mode).strip().casefold()


def _human_enabled() -> bool:
    mode = _presentation_mode()
    if mode in {"raw", "technical", "debug", "off", "false", "0"}:
        return False
    return True


def _show_technical_by_default() -> bool:
    return _as_bool(_presentation_config().get("show_technical_by_default"), False)


def _presentation_section(key: str, fallback: str) -> str:
    sections = _presentation_config().get("sections", {})
    return str(sections.get(key) or fallback)


def _presentation_limit(key: str, default: int) -> int:
    limits = _presentation_config().get("limits", {})
    try:
        value = int(limits.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(0, value)


def _presentation_visibility(key: str, default: Any = None) -> Any:
    visibility = _presentation_config().get("visibility", {})
    return visibility.get(key, default) if isinstance(visibility, dict) else default


def _status_word(value: Any) -> str:
    raw = str(value or "unknown")
    words = _presentation_config().get("status_words", {})
    return str(words.get(raw, raw.replace("_", " "))) if isinstance(words, dict) else raw.replace("_", " ")


def _full_tokens() -> set[str]:
    debug = _presentation_config().get("debug", {})
    tokens = _listify(debug.get("full_tokens") if isinstance(debug, dict) else None)
    tokens.extend(DEFAULT_PRESENTATION["debug"]["full_tokens"])
    return {item.strip().casefold() for item in tokens if item.strip()}


def _strip_full_tokens(words: list[str]) -> tuple[list[str], bool]:
    tokens = _full_tokens()
    filtered: list[str] = []
    full = False
    for word in words:
        if word.casefold() in tokens:
            full = True
        else:
            filtered.append(word)
    return filtered, full


def _is_full_request(raw_args: str) -> bool:
    _, full = _strip_full_tokens(_parse_words(raw_args))
    return full


def _line(text: Any, limit: int | None = None) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    max_chars = _presentation_limit("line_chars", 900) if limit is None else max(0, limit)
    if not max_chars or len(value) <= max_chars:
        return value
    suffix = " ... [clipped]"
    return f"{value[: max(0, max_chars - len(suffix))].rstrip()}{suffix}"


def _clip_output(text: str) -> str:
    return _clip(text, _presentation_limit("output_chars", 12000) or 12000)


def _issue_ident(issue: dict[str, Any]) -> str:
    ident = issue.get("identifier")
    if ident:
        return str(ident)
    return _compact_id(issue.get("id") or "")


def _format_command(value: str) -> str:
    command = str(value or "").strip()
    if not command:
        return _slash()
    if command.startswith("/"):
        return command
    return _slash(command)


def _format_action_command(item: dict[str, Any]) -> str:
    if item.get("command"):
        return _format_command(str(item.get("command")))
    action = str(item.get("action") or "").strip()
    if not action:
        return _slash()
    return _slash(_term(action))


def _append_more(lines: list[str], shown: int, total: int, command: str = "") -> None:
    hidden = max(0, total - shown)
    if hidden:
        suffix = f"; {command}" if command else ""
        lines.append(f"- and {hidden} more{suffix}")


def _sort_issues_recent(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        issues,
        key=lambda item: str(item.get("lastActivityAt") or item.get("updatedAt") or item.get("createdAt") or ""),
        reverse=True,
    )


def _issue_sort_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    ident = str(issue.get("identifier") or "")
    match = re.match(r"^([A-Z][A-Z0-9]{1,12})-(\d+)$", ident, re.IGNORECASE)
    if match:
        return (0, match.group(1).casefold(), int(match.group(2)))
    return (
        1,
        str(issue.get("createdAt") or ""),
        str(issue.get("updatedAt") or ""),
        str(issue.get("id") or ""),
    )


def _is_active_agent(agent: dict[str, Any]) -> bool:
    status = str(agent.get("status") or "").casefold()
    return bool(status and status not in {"idle", "offline", "inactive", "unknown"})


def _company_hints() -> list[str]:
    hints = [
        *_listify(_config().get("company_hints")),
        os.environ.get("PAPERCLIP_DEFAULT_COMPANY", ""),
        os.environ.get("PAPERCLIP_COMPANY_NAME", ""),
        _config_cwd_hint(),
        HERMES_HOME.name,
    ]
    return [item for item in hints if item]


def _match_company(companies: list[dict[str, Any]], token: str) -> dict[str, Any] | None:
    needle = _norm(token)
    if not needle:
        return None

    for company in companies:
        if str(company.get("id", "")) == token:
            return company
    for company in companies:
        if _norm(company.get("name", "")) == needle:
            return company
    for company in companies:
        name = _norm(company.get("name", ""))
        if needle in name or name in needle:
            return company
    for company in companies:
        if str(company.get("issuePrefix", "")).casefold() == token.casefold():
            return company
    return None


def _companies() -> list[dict[str, Any]]:
    data = _api("/companies")
    if not isinstance(data, list):
        raise PaperclipError("Paperclip /companies returned unexpected data")
    return data


def _resolve_company(token: str = "") -> dict[str, Any]:
    companies = _companies()
    if token:
        match = _match_company(companies, token)
        if match:
            return match
        raise PaperclipError(f"Unknown Paperclip {_label('company')}: {token}\n\n{_format_companies(companies)}")

    for hint in _company_hints():
        match = _match_company(companies, hint)
        if match:
            return match

    if len(companies) == 1:
        return companies[0]

    raise PaperclipError(
        f"Multiple Paperclip {_label('companies')} found. "
        f"Pass --company \"Name\" or set PAPERCLIP_DEFAULT_COMPANY.\n\n{_format_companies(companies)}"
    )


def _extract_company(words: list[str]) -> tuple[list[str], str]:
    remaining: list[str] = []
    company = ""
    index = 0
    while index < len(words):
        word = words[index]
        if word == "--company" and index + 1 < len(words):
            company = words[index + 1]
            index += 2
            continue
        if word.startswith("--company="):
            company = word.split("=", 1)[1]
            index += 1
            continue
        remaining.append(word)
        index += 1
    return remaining, company


def _agent_tags(agent: dict[str, Any]) -> list[str]:
    metadata = agent.get("metadata")
    tags = metadata.get("tags") if isinstance(metadata, dict) else []
    if isinstance(tags, list):
        return [str(tag).strip() for tag in tags if str(tag).strip()]
    return []


def _extract_agent_options(words: list[str]) -> tuple[list[str], dict[str, Any]]:
    remaining: list[str] = []
    options: dict[str, Any] = {"tag": "", "show_tags": False}
    index = 0
    while index < len(words):
        word = words[index]
        if word in {"--tags", "tags"}:
            options["show_tags"] = True
            index += 1
            continue
        if word == "--tag" and index + 1 < len(words):
            options["tag"] = words[index + 1].strip().casefold()
            index += 2
            continue
        if word.startswith("--tag="):
            options["tag"] = word.split("=", 1)[1].strip().casefold()
            index += 1
            continue
        remaining.append(word)
        index += 1
    return remaining, options


def _agent_name(agent_by_id: dict[str, dict[str, Any]], agent_id: str | None) -> str:
    if not agent_id:
        return "-"
    agent = agent_by_id.get(agent_id)
    return str(agent.get("name", agent_id)) if agent else str(agent_id)


def _issue_ref(raw_args: str) -> str:
    match = ISSUE_RE.search(raw_args or "")
    if match:
        return match.group(1).upper()
    words = _parse_words(raw_args)
    return words[0] if words else ""


def _issue_url(issue: dict[str, Any]) -> str:
    issue_id = issue.get("id") or issue.get("identifier") or ""
    return f"{PUBLIC_BASE}/issues/{issue_id}"


def _format_companies(companies: list[dict[str, Any]]) -> str:
    lines = [f"# Paperclip {_label('companies')}"]
    for company in sorted(companies, key=lambda item: str(item.get("name", "")).casefold()):
        prefix = company.get("issuePrefix") or "-"
        status = company.get("status") or "unknown"
        lines.append(f"- {company.get('name')} ({prefix}) status={status} id={_compact_id(company.get('id'))}")
    return "\n".join(lines)


def _actions() -> dict[str, dict[str, Any]]:
    raw = _config().get("actions", {})
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def _intents() -> list[dict[str, Any]]:
    raw = _config().get("intents", {})
    items: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("name", str(name))
                items.append(item)
    elif isinstance(raw, list):
        for value in raw:
            if isinstance(value, dict):
                items.append(dict(value))
    return items


def _action_aliases(name: str, action: dict[str, Any]) -> set[str]:
    aliases = {name}
    aliases.update(_listify(action.get("aliases")))
    return {item.strip().casefold() for item in aliases if item.strip()}


def _action_usage(name: str, action: dict[str, Any]) -> str:
    usage = str(action.get("usage") or name).strip()
    return usage or name


def _help_line(command_text: str, description: str = "") -> str:
    if description:
        return f"{command_text} - {description}"
    return command_text


def _action_description(action: dict[str, Any]) -> str:
    presentation = action.get("presentation", {})
    if isinstance(presentation, dict):
        for key in ("description", "help", "text"):
            if presentation.get(key):
                return str(presentation.get(key))
    for key in ("description", "help", "text", "summary"):
        if action.get(key):
            return str(action.get(key))
    return ""


def _technical_help(_: str = "") -> str:
    writes = _help_text("enabled") if _writes_enabled() else _help_text("disabled")
    nl_writes = _help_text("enabled") if _nl_writes_enabled() else _help_text("disabled")
    command = _slash()
    lines = [
        _help_text("usage_heading"),
        _help_line(f"{command} help", _command_description("help")),
        _help_line(f"{command} {_term('companies')}", _command_description("companies")),
        _help_line(f"{command} {_term('health')}", _command_description("health")),
        _help_line(f"{command} {_term('status')} [full]", _command_description("status")),
        _help_line(f"{command} {_term('agents')} [--company NAME] [--tags|--tag TAG]", _command_description("agents")),
        _help_line(
            f"{command} {_term('tasks')} [--company NAME] [open|all|todo|in_progress|blocked|done|cancelled] [limit]",
            _command_description("tasks"),
        ),
        _help_line(f"{command} {_term('task')} ISSUE", _command_description("task")),
        _help_line(f"{command} {_term('comments')} ISSUE", _command_description("comments")),
        _help_line(
            f"{command} {_term('move')} ISSUE <todo|in_progress|blocked|done|cancelled>",
            _command_description("move"),
        ),
        _help_line(f"{command} {_term('capabilities')}", _command_description("capabilities")),
        _help_line(f"{command} {_term('debug')}", _command_description("debug")),
    ]
    actions = _actions()
    if actions:
        lines.extend(["", _help_text("project_actions_heading")])
        for name, action in actions.items():
            lines.append(_help_line(f"{command} {_action_usage(name, action)}", _action_description(action)))
    lines.extend(
        [
            "",
            _help_text("safety_heading"),
            f"- {_help_text('slash_writes')}: {writes}",
            f"- {_help_text('natural_writes')}: {nl_writes}",
            "",
            _help_text("company_heading"),
            _help_text("company_config_hints"),
            _help_text("company_env"),
            _help_text("company_cwd"),
            _help_text("company_flag"),
        ]
    )
    return "\n".join(lines)


def _human_home() -> str:
    presentation = _presentation_config()
    home = presentation.get("home", {})
    if not isinstance(home, dict):
        home = {}
    title = str(home.get("title") or "").strip()
    intro = str(home.get("intro") or "Connected to Paperclip.").strip()
    items = home.get("items") if isinstance(home.get("items"), list) else DEFAULT_PRESENTATION["home"]["items"]
    more = home.get("more") if isinstance(home.get("more"), list) else DEFAULT_PRESENTATION["home"]["more"]

    lines: list[str] = []
    if title:
        lines.append(title)
        lines.append("")
    if intro:
        lines.append(intro)
        lines.append("")

    if items:
        lines.append(_presentation_section("useful_commands", "Useful commands:"))
        for item in items:
            if not isinstance(item, dict):
                continue
            command = _format_action_command(item)
            text = str(item.get("text") or item.get("description") or "").strip()
            lines.append(f"- {command}{f' - {text}' if text else ''}")
        lines.append("")

    if more:
        lines.append(_presentation_section("more", "More:"))
        for item in more:
            if not isinstance(item, dict):
                continue
            command = _format_action_command(item)
            text = str(item.get("text") or item.get("description") or "").strip()
            lines.append(f"- {command}{f' - {text}' if text else ''}")

    return "\n".join(line for line in lines).strip()


def _help(raw_args: str = "") -> str:
    if _human_enabled() and not _show_technical_by_default() and not _is_full_request(raw_args):
        return _human_home()
    return _technical_help(raw_args)


def _health(_: str) -> str:
    data = _api("/health", timeout=5)
    if isinstance(data, dict):
        return f"Paperclip health: {'ok' if data.get('ok', True) else 'failed'} version={data.get('version', '-')}"
    return "Paperclip health: ok"


def _companies_cmd(raw_args: str = "") -> str:
    companies = _companies()
    if not _human_enabled() or _is_full_request(raw_args):
        return _format_companies(companies)

    lines = [f"Paperclip {_label('companies')}:"]
    for company in sorted(companies, key=lambda item: str(item.get("name", "")).casefold()):
        prefix = company.get("issuePrefix") or "-"
        status = _status_word(company.get("status") or "unknown")
        lines.append(f"- {company.get('name')} ({prefix}) - {status}")
    return "\n".join(lines)


def _runs_for_company(company_id: str) -> list[dict[str, Any]]:
    try:
        runs = _api(f"/companies/{company_id}/heartbeat-runs")
    except PaperclipError:
        return []
    return runs if isinstance(runs, list) else []


def _technical_status(company_token: str = "") -> str:
    health = _api("/health", timeout=5)
    company = _resolve_company(company_token)
    agents = _api(f"/companies/{company['id']}/agents")
    issues = [item for item in _api(f"/companies/{company['id']}/issues") if not item.get("hiddenAt")]
    runs = _runs_for_company(company["id"])
    agent_by_id = {agent["id"]: agent for agent in agents}

    lines = [
        "# Paperclip status",
        f"- health: {'ok' if not isinstance(health, dict) or health.get('ok', True) else 'failed'}",
        f"- {_label('company')}: {company.get('name')} ({company.get('issuePrefix') or '-'})",
        f"- {_label('agents')}: {len(agents)}",
        f"- {_label('tasks')}: {len(issues)}",
        "",
        f"## Recent {_label('tasks')}",
    ]
    recent_issues = _sort_issues_recent(issues)[: _presentation_limit("tasks", 10) or 10]
    if not recent_issues:
        lines.append(f"- No {_label('tasks')}.")
    for issue in recent_issues:
        assignee = _agent_name(agent_by_id, issue.get("assigneeAgentId"))
        parent = "child" if issue.get("parentId") else "root"
        lines.append(f"- {issue.get('status'):<12} {_issue_ident(issue):<8} {parent:<5} assignee={assignee} {issue.get('title')}")

    lines.append("")
    lines.append("## Recent runs")
    if not runs:
        lines.append("- No recent runs or runs endpoint unavailable.")
    for run in _sort_issues_recent(runs)[: _presentation_limit("runs", 12) or 12]:
        issue = run.get("contextSnapshot", {}).get("taskKey") or run.get("contextSnapshot", {}).get("issueId") or "-"
        agent = _agent_name(agent_by_id, run.get("agentId"))
        error = f" error={run.get('errorCode')}" if run.get("errorCode") else ""
        lines.append(f"- {run.get('status', 'unknown'):<10} run={run.get('id')} issue={issue} agent={agent}{error} updated={run.get('updatedAt')}")

    return "\n".join(lines)


def _human_status(company_token: str = "") -> str:
    health = _api("/health", timeout=5)
    company = _resolve_company(company_token)
    agents = _api(f"/companies/{company['id']}/agents")
    issues = [item for item in _api(f"/companies/{company['id']}/issues") if not item.get("hiddenAt")]
    active_agents = [agent for agent in agents if _is_active_agent(agent)]
    open_issues = [issue for issue in issues if issue.get("status") in OPEN_STATUSES]
    roots = [issue for issue in issues if not issue.get("parentId")]
    done_roots = [issue for issue in roots if issue.get("status") == "done"]
    latest_root = _sort_issues_recent(roots)[0] if roots else None
    latest_done = _sort_issues_recent(done_roots)[0] if done_roots else None

    ok = not isinstance(health, dict) or bool(health.get("ok", True))
    lines = ["Paperclip is reachable." if ok else "Paperclip responded, but health is not ok.", ""]
    lines.append(f"{_label('company').title()}: {company.get('name')}")
    lines.append(f"{_label('agents').title()}: {len(agents)}")
    lines.append(f"Active {_label('agents')}: {len(active_agents)}")
    lines.append(f"Open {_label('tasks')}: {len(open_issues)}")
    if latest_root:
        lines.append(f"Latest {_label('task')}: {_issue_ident(latest_root)} - {_line(latest_root.get('title'), 160)}")
    if latest_done:
        lines.append(f"Latest done {_label('task')}: {_issue_ident(latest_done)} - {_line(latest_done.get('title'), 160)}")

    if _presentation_visibility("status_runs", False):
        runs = _runs_for_company(company["id"])
        if runs:
            counts: dict[str, int] = {}
            for run in runs:
                status = str(run.get("status") or "unknown")
                counts[status] = counts.get(status, 0) + 1
            lines.append(f"Recent runs: {len(runs)}")
            for status, count in sorted(counts.items()):
                lines.append(f"- {_status_word(status)}: {count}")

    lines.extend(["", _presentation_section("details", "Details:")])
    lines.append(f"- {_slash(_term('tasks'))}")
    lines.append(f"- {_slash(_term('status'), 'full')}")
    return "\n".join(lines)


def _status_cmd(raw_args: str = "") -> str:
    words, full = _strip_full_tokens(_parse_words(raw_args))
    words, company_token = _extract_company(words)
    if words and not company_token:
        company_token = " ".join(words)
    if not _human_enabled() or full or _show_technical_by_default():
        return _technical_status(company_token)
    return _human_status(company_token)


def _agents_cmd(raw_args: str) -> str:
    words, full = _strip_full_tokens(_parse_words(raw_args))
    words, company_token = _extract_company(words)
    words, options = _extract_agent_options(words)
    if words and not company_token:
        company_token = " ".join(words)
    company = _resolve_company(company_token)
    agents = _api(f"/companies/{company['id']}/agents")

    if options["show_tags"]:
        counts: dict[str, int] = {}
        for agent in agents:
            for tag in _agent_tags(agent):
                counts[tag] = counts.get(tag, 0) + 1
        lines = [f"# Paperclip {_label('agent')} tags: {company['name']}"]
        for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold())):
            lines.append(f"- {tag}: {count}")
        lines.append(f"\nTotal tags: {len(counts)}")
        return "\n".join(lines)

    tag_filter = str(options["tag"] or "")
    if tag_filter:
        agents = [agent for agent in agents if tag_filter in {tag.casefold() for tag in _agent_tags(agent)}]

    if _human_enabled() and not full and not _show_technical_by_default():
        limit = _presentation_limit("agents", 12) or 12
        active = sorted([agent for agent in agents if _is_active_agent(agent)], key=lambda item: str(item.get("name", "")).casefold())
        idle = sorted([agent for agent in agents if not _is_active_agent(agent)], key=lambda item: str(item.get("name", "")).casefold())
        lines = [f"{_label('agents').title()}: {len(agents)}"]
        if tag_filter:
            lines.append(f"Filter: {tag_filter}")
        lines.append("")

        if active:
            lines.append(_presentation_section("active_agents", "Active:"))
            shown = active[:limit]
            for agent in shown:
                status = _status_word(agent.get("status") or "active")
                tags = _agent_tags(agent)
                tag_text = f" ({', '.join(tags[:3])})" if tags else ""
                lines.append(f"- {agent.get('name')} - {status}{tag_text}")
            _append_more(lines, len(shown), len(active), _slash(_term("agents"), "full"))
            lines.append("")

        if idle:
            if active:
                lines.append(f"{_presentation_section('idle_agents', 'Idle:')} {len(idle)}")
            else:
                lines.append(f"{_presentation_section('idle_agents', 'Idle:')} {len(idle)}")
                sample = idle[: min(limit, len(idle))]
                for agent in sample:
                    lines.append(f"- {agent.get('name')}")
                _append_more(lines, len(sample), len(idle), _slash(_term("agents"), "full"))

        lines.extend(["", _presentation_section("more", "More:")])
        lines.append(f"- {_slash(_term('agents'), 'full')}")
        lines.append(f"- {_slash(_term('agents'), '--tags')}")
        return "\n".join(line for line in lines if line is not None).strip()

    lines = [f"# Paperclip {_label('agents')}: {company['name']}"]
    for agent in sorted(agents, key=lambda item: str(item.get("name", "")).casefold()):
        status = agent.get("status") or "unknown"
        adapter = agent.get("adapterType") or "-"
        role = agent.get("role") or "-"
        tags = _agent_tags(agent)
        tag_text = f" tags={', '.join(tags)}" if tags else ""
        lines.append(f"- {status:<12} {agent.get('name')} role={role} adapter={adapter}{tag_text}")
    if tag_filter:
        lines.append(f"\nFilter tag: {tag_filter}")
    lines.append(f"\nTotal: {len(agents)}")
    return "\n".join(lines)


def _normalize_scope(value: str) -> str:
    normalized = value.casefold()
    if normalized in {"все", "всё", "all"}:
        return "all"
    if normalized in {"открытые", "open"}:
        return "open"
    return normalized


def _tasks_cmd(raw_args: str) -> str:
    words, full = _strip_full_tokens(_parse_words(raw_args))
    words, company_token = _extract_company(words)
    scope = "open"
    limit = _presentation_limit("tasks", 10) or 10

    if words and _normalize_scope(words[0]) in {"open", "all", "todo", "in_progress", "blocked", "done", "cancelled"}:
        scope = _normalize_scope(words.pop(0))
    elif words and not words[0].isdigit():
        company_token = words.pop(0)

    if words and _normalize_scope(words[0]) in {"open", "all", "todo", "in_progress", "blocked", "done", "cancelled"}:
        scope = _normalize_scope(words.pop(0))
    if words and words[0].isdigit():
        limit = max(1, min(50, int(words[0])))

    company = _resolve_company(company_token)
    issues = [item for item in _api(f"/companies/{company['id']}/issues") if not item.get("hiddenAt")]
    agents = _api(f"/companies/{company['id']}/agents")
    agent_by_id = {agent["id"]: agent for agent in agents}

    if scope == "open":
        issues = [item for item in issues if item.get("status") in OPEN_STATUSES]
    elif scope != "all":
        issues = [item for item in issues if item.get("status") == scope]

    issues = _sort_issues_recent(issues)

    if _human_enabled() and not full and not _show_technical_by_default():
        title_scope = "Open" if scope == "open" else scope.replace("_", " ").title()
        lines = [f"{title_scope} {_label('tasks')}: {len(issues)}"]
        if not issues:
            lines.append("")
            lines.append(f"No {_label('tasks')} in this view.")
        else:
            lines.append("")
            shown = issues[:limit]
            for issue in shown:
                ident = _issue_ident(issue)
                status = _status_word(issue.get("status") or "unknown")
                assignee = _agent_name(agent_by_id, issue.get("assigneeAgentId"))
                assignee_text = "" if assignee == "-" else f" - {assignee}"
                lines.append(f"- {ident} - {status}{assignee_text} - {_line(issue.get('title'), 220)}")
            _append_more(lines, len(shown), len(issues), _slash(_term("tasks"), scope, "full") if scope != "open" else _slash(_term("tasks"), "full"))
        lines.extend(["", _presentation_section("more", "More:")])
        lines.append(f"- {_slash(_term('tasks'), 'all')}")
        lines.append(f"- {_slash(_term('tasks'), 'full')}")
        return "\n".join(lines).strip()

    lines = [f"# Paperclip {_label('tasks')}: {company['name']} ({scope}, limit {limit})"]
    if not issues:
        lines.append(f"- No {_label('tasks')}.")
    for issue in issues[:limit]:
        assignee = _agent_name(agent_by_id, issue.get("assigneeAgentId"))
        ident = issue.get("identifier") or _compact_id(issue.get("id"))
        parent = "child" if issue.get("parentId") else "root"
        lines.append(f"- {issue.get('status'):<12} {ident:<8} {parent:<5} assignee={assignee} {issue.get('title')}")
    return "\n".join(lines)


def _task_cmd(raw_args: str) -> str:
    words, full = _strip_full_tokens(_parse_words(raw_args))
    filtered_raw = " ".join(words)
    issue_ref = _issue_ref(filtered_raw)
    if not issue_ref:
        return f"Usage: {_slash(_term('task'), 'ISSUE')}"
    issue = _api(f"/issues/{issue_ref}")
    agents = _api(f"/companies/{issue['companyId']}/agents")
    agent_by_id = {agent["id"]: agent for agent in agents}
    comments = [item for item in _api(f"/issues/{issue['id']}/comments") if not item.get("deletedAt")]

    if _human_enabled() and not full and not _show_technical_by_default():
        comment_limit = _presentation_limit("comments", 3)
        comment_chars = _presentation_limit("comment_chars", 500) or 500
        assignee = _agent_name(agent_by_id, issue.get("assigneeAgentId"))
        lines = [
            f"{issue.get('identifier') or _compact_id(issue.get('id'))}",
            str(issue.get("title") or "").strip(),
            "",
            f"Status: {_status_word(issue.get('status') or 'unknown')}",
            f"Priority: {issue.get('priority') or '-'}",
            f"Assignee: {assignee}",
            f"Parent: {_compact_id(issue.get('parentId')) if issue.get('parentId') else 'none'}",
            "",
            _presentation_section("recent_comments", f"Recent {_label('comments')}:"),
        ]
        if not comments or not comment_limit:
            lines.append(f"- No {_label('comments')}.")
        for comment in (comments[-comment_limit:] if comment_limit else []):
            body = _line(comment.get("body") or "", comment_chars)
            author = comment.get("authorType") or "unknown"
            created = comment.get("createdAt") or ""
            lines.append(f"- {author} {created}: {body}")
        lines.extend(["", "Open:", _issue_url(issue), "", _presentation_section("more", "More:")])
        lines.append(f"- {_slash(_term('task'), issue_ref, 'full')}")
        lines.append(f"- {_slash(_term('comments'), issue_ref, 'full')}")
        return "\n".join(lines).strip()

    lines = [
        f"# {issue.get('identifier') or issue.get('id')}: {issue.get('title')}",
        f"- status: {issue.get('status')}",
        f"- priority: {issue.get('priority') or '-'}",
        f"- assignee: {_agent_name(agent_by_id, issue.get('assigneeAgentId'))}",
        f"- parent: {issue.get('parentId') or '-'}",
        f"- url: {_issue_url(issue)}",
        "",
        "## Description",
        _clip(issue.get("description") or "", 2000) or "-",
        "",
        f"## Last {_label('comments')}",
    ]
    if not comments:
        lines.append(f"- No {_label('comments')}.")
    for comment in comments[-3:]:
        body = re.sub(r"\s+", " ", comment.get("body") or "").strip()
        lines.append(f"- {comment.get('authorType') or 'unknown'} {comment.get('createdAt') or ''}: {_clip(body, 500)}")
    return "\n".join(lines)


def _comments_cmd(raw_args: str) -> str:
    words, full = _strip_full_tokens(_parse_words(raw_args))
    filtered_raw = " ".join(words)
    issue_ref = _issue_ref(filtered_raw)
    if not issue_ref:
        return f"Usage: {_slash(_term('comments'), 'ISSUE')}"
    issue = _api(f"/issues/{issue_ref}")
    comments = [item for item in _api(f"/issues/{issue['id']}/comments") if not item.get("deletedAt")]

    if _human_enabled() and not full and not _show_technical_by_default():
        comment_limit = _presentation_limit("comments", 3)
        comment_chars = _presentation_limit("comment_chars", 500) or 500
        lines = [
            f"{_label('comments').title()}: {issue.get('identifier') or _compact_id(issue.get('id'))}",
            str(issue.get("title") or "").strip(),
            "",
        ]
        if not comments or not comment_limit:
            lines.append(f"No {_label('comments')}.")
        for comment in (comments[-comment_limit:] if comment_limit else []):
            author = comment.get("authorType") or "unknown"
            created = comment.get("createdAt") or ""
            lines.append(f"- {author} {created}: {_line(comment.get('body') or '', comment_chars)}")
        lines.extend(["", _presentation_section("more", "More:")])
        lines.append(f"- {_slash(_term('comments'), issue_ref, 'full')}")
        return "\n".join(lines).strip()

    lines = [f"# {_label('comments').title()}: {issue.get('identifier') or issue.get('id')}", issue.get("title") or ""]
    if not comments:
        lines.append(f"\nNo {_label('comments')}.")
    for comment in comments[-8:]:
        lines.extend(["", f"--- {comment.get('authorType') or 'unknown'} {comment.get('createdAt') or ''} ---", comment.get("body") or ""])
    return _clip("\n".join(lines))


def _move_cmd(raw_args: str) -> str:
    if not _writes_enabled():
        return (
            "Paperclip writes are disabled. Set PAPERCLIP_COCKPIT_ENABLE_WRITES=1 "
            f"in the Hermes environment to enable {_slash(_term('move'))}."
        )
    words = _parse_words(raw_args)
    if len(words) != 2 or words[1] not in TASK_STATUSES:
        return f"Usage: {_slash(_term('move'), 'ISSUE <todo|in_progress|blocked|done|cancelled>')}"
    issue_ref, next_status = words
    issue = _api(f"/issues/{issue_ref}")
    old_status = issue.get("status")
    if old_status == next_status:
        return f"{issue.get('identifier') or issue.get('id')} already {next_status}"
    updated = _api(f"/issues/{issue['id']}", method="PATCH", body={"status": next_status})
    _post_issue_comment(
        str(issue["id"]),
        _notification_text(
            "move_status_changed",
            issue_id=issue.get("id"),
            issue_identifier=issue.get("identifier"),
            old_status=old_status,
            new_status=next_status,
        ),
        log_context=f"move {issue.get('id')}",
    )
    ident = updated.get("identifier") or issue.get("identifier") or issue.get("id")
    lines = [f"Moved {ident}: {old_status} -> {next_status}"]
    auto_finalize_statuses = _after_move_auto_finalize_statuses()
    if next_status in auto_finalize_statuses:
        finalize_result = _finalize_issue_tree(updated, dry_run=False)
        finalized = [item for item in finalize_result["changed"] if str(item.get("id") or "") != str(updated.get("id") or "")]
        if finalized:
            lines.extend(["", "Auto-finalized parents:"])
            for item in finalized:
                lines.append(f"- {item.get('identifier') or _compact_id(item.get('id'))}: {_line(item.get('title'), 180)}")
        elif finalize_result["open_root_children"]:
            lines.extend(["", "Parents stay open: some sibling issues are not in terminal statuses."])
    lines.append(f"Open: {_issue_url(issue)}")
    return "\n".join(lines)


def _capabilities_cmd(_: str) -> str:
    config_paths = [str(path) for path in _config_paths()]
    lines = [
        "# Paperclip Cockpit capabilities",
        f"- plugin: {PLUGIN_NAME} {VERSION}",
        f"- command: {_slash()}",
        f"- config_paths: {', '.join(config_paths) or '-'}",
        f"- api_base: {API_BASE}",
        f"- profile: {HERMES_HOME}",
        f"- default_company_hints: {', '.join(_company_hints()) or '-'}",
        f"- natural_language_rewrite: {_env_bool('PAPERCLIP_COCKPIT_NL_REWRITE', True)}",
        f"- slash_command_writes: {_writes_enabled()}",
        f"- natural_language_writes: {_nl_writes_enabled()}",
        f"- reset_on_gateway_shutdown: {_reset_on_gateway_shutdown_enabled()}",
        f"- after_move_auto_finalize_statuses: {', '.join(sorted(_after_move_auto_finalize_statuses())) or '-'}",
        f"- explicit_commands_registered: {_env_bool('PAPERCLIP_COCKPIT_REGISTER_EXPLICIT', False)}",
        f"- project_actions: {', '.join(_actions().keys()) or '-'}",
    ]
    return "\n".join(lines)


def _debug_cmd(raw_args: str = "") -> str:
    parts = [_capabilities_cmd(raw_args), "", _technical_help(raw_args)]
    return "\n".join(parts).strip()


def _humanize_action_output(text: str) -> str:
    lines = str(text or "").splitlines()
    filtered: list[str] = []
    skip_until_blank = False
    hidden_sections = {"safety", "company selection"}
    for line in lines:
        heading = line.strip().rstrip(":").casefold()
        if heading in hidden_sections:
            skip_until_blank = True
            continue
        if skip_until_blank:
            if not line.strip():
                skip_until_blank = False
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def _format_error(exc: Exception) -> str:
    message = str(exc)
    errors = _presentation_config().get("errors", {})
    show_details = _as_bool(errors.get("show_details") if isinstance(errors, dict) else None, False)
    show_debug_hint = _as_bool(errors.get("show_debug_hint") if isinstance(errors, dict) else None, True)
    if not _human_enabled() or show_details:
        return message

    lowered = message.casefold()
    if "failed:" in lowered or "before http response" in lowered or "connection" in lowered:
        lines = [
            "I could not complete the Paperclip request.",
            "",
            "Check that the local Paperclip API is running and reachable.",
        ]
    else:
        lines = [
            "I could not complete the Paperclip request.",
            "",
            _line(message, 240),
        ]
    if show_debug_hint:
        lines.extend(["", _presentation_section("details", "Details:"), f"- {_slash(_term('debug'))}"])
    return "\n".join(lines).strip()


def _run_action(name: str, action: dict[str, Any], raw_args: str) -> str:
    if action.get("disabled"):
        return f"Project action disabled: {name}"
    builtin = str(action.get("builtin") or action.get("paperclip_builtin") or "").strip().casefold()
    if builtin:
        return _run_builtin_action(name, builtin, raw_args, action)
    command = action.get("exec") or action.get("command")
    if isinstance(command, str):
        args = _parse_words(command)
    elif isinstance(command, list):
        args = [str(item) for item in command]
    else:
        return f"Project action {name} has no exec command."
    if not args:
        return f"Project action {name} has an empty exec command."

    if action.get("append_args", True):
        args.extend(_parse_words(raw_args))

    cwd = str(action.get("cwd") or _config().get("cwd") or _terminal_cwd() or os.getcwd())
    timeout = int(action.get("timeout", 180))
    try:
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return f"Project action timed out after {timeout}s: `{shlex.join(args)}`"
    except Exception as exc:
        logger.warning("project action failed before execution: %s", exc)
        return f"Project action failed before execution: {exc}"

    output = result.stdout.strip()
    error = result.stderr.strip()
    presentation = action.get("presentation")
    action_mode = "passthrough"
    action_clip = None
    if isinstance(presentation, dict):
        action_mode = str(presentation.get("mode") or "passthrough").strip().casefold()
        try:
            action_clip = int(presentation.get("clip")) if presentation.get("clip") is not None else None
        except (TypeError, ValueError):
            action_clip = None
    limit = action_clip or _presentation_limit("output_chars", 12000) or 12000

    def present(text: str) -> str:
        if action_mode == "raw":
            return text
        if action_mode == "human":
            return _clip(_humanize_action_output(text), limit)
        return _clip(text, limit)

    if result.returncode == 0:
        return present(output or "OK")
    body = output
    if error:
        body = f"{body}\n\nstderr:\n{error}".strip()
    return present(f"Project action exited with {result.returncode}.\n\n{body}")


def _visible_children(by_parent: dict[str, list[dict[str, Any]]], issue_id: str) -> list[dict[str, Any]]:
    children = by_parent.get(issue_id, [])
    return sorted([child for child in children if not child.get("hiddenAt")], key=_issue_sort_key)


def _collect_issue_tree(root: dict[str, Any], issues: list[dict[str, Any]]) -> tuple[list[tuple[dict[str, Any], int]], dict[str, list[dict[str, Any]]]]:
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for item in issues:
        if item.get("hiddenAt") or not item.get("parentId"):
            continue
        by_parent.setdefault(str(item["parentId"]), []).append(item)

    items: list[tuple[dict[str, Any], int]] = []

    def visit(issue: dict[str, Any], depth: int) -> None:
        for child in _visible_children(by_parent, str(issue.get("id") or "")):
            items.append((child, depth))
            visit(child, depth + 1)

    visit(root, 1)
    return items, by_parent


def _resolve_root_issue(issue: dict[str, Any]) -> dict[str, Any]:
    current = issue
    seen: set[str] = set()
    while current.get("parentId"):
        parent_id = str(current.get("parentId") or "")
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        current = _api(f"/issues/{parent_id}")
    return current


def _finalize_issue_tree(start_issue: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    root = _resolve_root_issue(start_issue)
    issues = [item for item in _api(f"/companies/{root['companyId']}/issues") if not item.get("hiddenAt")]
    items, by_parent = _collect_issue_tree(root, issues)
    issue_by_id = {str(root["id"]): root, **{str(issue["id"]): issue for issue, _depth in items}}
    changed: list[dict[str, Any]] = []

    for issue, depth in sorted(items, key=lambda item: (-item[1], _issue_sort_key(item[0]))):
        children = _visible_children(by_parent, str(issue.get("id") or ""))
        if not children or issue.get("status") in TERMINAL_STATUSES:
            continue
        if not all((issue_by_id.get(str(child.get("id") or ""), child).get("status") in TERMINAL_STATUSES) for child in children):
            continue
        if not dry_run:
            _api(f"/issues/{issue['id']}", method="PATCH", body={"status": "done"})
            _post_issue_comment(
                str(issue["id"]),
                _notification_text(
                    "auto_finalized",
                    issue_id=issue.get("id"),
                    issue_identifier=issue.get("identifier"),
                    status=issue.get("status"),
                ),
                log_context=f"finalize {issue.get('id')}",
            )
            issue["status"] = "done"
        else:
            issue["status"] = "done"
        changed.append(issue)

    root_children = _visible_children(by_parent, str(root.get("id") or ""))
    open_root_children = [
        child for child in root_children if issue_by_id.get(str(child.get("id") or ""), child).get("status") not in TERMINAL_STATUSES
    ]

    if root_children and not open_root_children and root.get("status") not in TERMINAL_STATUSES:
        if not dry_run:
            _api(f"/issues/{root['id']}", method="PATCH", body={"status": "done"})
            _post_issue_comment(
                str(root["id"]),
                _notification_text(
                    "auto_finalized",
                    issue_id=root.get("id"),
                    issue_identifier=root.get("identifier"),
                    status=root.get("status"),
                ),
                log_context=f"finalize root {root.get('id')}",
            )
            root["status"] = "done"
        else:
            root["status"] = "done"
        changed.append(root)

    return {
        "root": root,
        "changed": changed,
        "root_children": root_children,
        "open_root_children": open_root_children,
    }


def _finalize_builtin(name: str, raw_args: str, _: dict[str, Any]) -> str:
    words = _parse_words(raw_args)
    dry_run = False
    filtered: list[str] = []
    for word in words:
        if word in {"--dry-run", "dry-run", "dryrun"}:
            dry_run = True
            continue
        filtered.append(word)

    issue_ref = _issue_ref(" ".join(filtered))
    if not issue_ref:
        return f"Usage: {_slash(_action_usage(name, {'usage': f'{name} ISSUE [--dry-run]'}) )}"

    if not dry_run and not _writes_enabled():
        return (
            "Paperclip writes are disabled. Set PAPERCLIP_COCKPIT_ENABLE_WRITES=1 "
            f"to enable {_format_command(_action_usage(name, {'usage': f'{name} ISSUE'}))}."
        )

    start = _api(f"/issues/{issue_ref}")
    finalize_result = _finalize_issue_tree(start, dry_run=dry_run)
    root = finalize_result["root"]
    changed = finalize_result["changed"]
    root_children = finalize_result["root_children"]
    open_root_children = finalize_result["open_root_children"]

    lines = [
        f"Finalize tree: {root.get('identifier') or _compact_id(root.get('id'))}",
        str(root.get("title") or "").strip(),
        f"- dry_run: {'yes' if dry_run else 'no'}",
        f"- root status: {root.get('status') or 'unknown'}",
        f"- children: {len(root_children)}",
    ]
    if open_root_children:
        lines.extend(["", "Root issue stays open: some child issues are not in terminal statuses."])
        for child in open_root_children:
            lines.append(
                f"- {child.get('identifier') or _compact_id(child.get('id'))} - {_status_word(child.get('status') or 'unknown')} - {_line(child.get('title'), 180)}"
            )
        if changed:
            lines.append("")
            lines.append("Finalized nested parents:")
            for issue in changed:
                lines.append(f"- {issue.get('identifier') or _compact_id(issue.get('id'))}")
        return "\n".join(lines)

    lines.append("")
    if not changed:
        lines.append("No changes: the issue tree is already finalized or does not need auto-finalization.")
    else:
        lines.append("Would finalize:" if dry_run else "Finalized:")
        for issue in changed:
            lines.append(f"- {issue.get('identifier') or _compact_id(issue.get('id'))}: {_line(issue.get('title'), 180)}")
    lines.append(f"Open: {_issue_url(root)}")
    return "\n".join(lines)


def _run_builtin_action(name: str, builtin: str, raw_args: str, action: dict[str, Any]) -> str:
    if builtin == "finalize":
        return _finalize_builtin(name, raw_args, action)
    return f"Unknown Paperclip Cockpit builtin action: {builtin}"


def _router(raw_args: str) -> str:
    raw = raw_args.strip()
    if not raw:
        return _help().strip()
    words = _parse_words(raw)
    head = words[0].casefold()
    tail = " ".join(words[1:]).strip()

    try:
        if head in _aliases("help"):
            return _help(tail).strip()
        if head in _aliases("health"):
            return _health(tail)
        if head in _aliases("companies"):
            return _companies_cmd(tail)
        if head in _aliases("status"):
            return _status_cmd(tail)
        if head in _aliases("agents"):
            return _agents_cmd(tail)
        if head in _aliases("tasks"):
            return _tasks_cmd(tail)
        if head in _aliases("task"):
            return _task_cmd(tail)
        if head in _aliases("comments"):
            return _comments_cmd(tail)
        if head in _aliases("move"):
            return _move_cmd(tail)
        if head in _aliases("debug"):
            return _debug_cmd(tail)
        if head in _aliases("capabilities"):
            return _capabilities_cmd(tail)

        for name, action in _actions().items():
            if head in _action_aliases(name, action):
                return _run_action(name, action, tail)
    except PaperclipError as exc:
        return _format_error(exc)

    return _help().strip()


def _contains_any(text: str, needles: set[str]) -> bool:
    return any(needle in text for needle in needles)


def _status_from_text(text: str) -> str:
    status_aliases = {
        "todo": {"todo", "to do", "backlog", "новая", "новое", "в план", "в очередь"},
        "in_progress": {"in_progress", "in progress", "doing", "работа", "в работу", "делается"},
        "blocked": {"blocked", "block", "заблок", "блок", "стоп"},
        "done": {"done", "complete", "completed", "закрой", "закрыть", "готово", "сделано", "выполнено"},
        "cancelled": {"cancelled", "canceled", "cancel", "отмени", "отменить", "отменено"},
    }
    for status, aliases in status_aliases.items():
        if _contains_any(text, aliases):
            return status
    return ""


def _contains_alias(text: str, key: str) -> bool:
    aliases = _aliases(key)
    for alias in aliases:
        if len(alias) <= 2:
            if text == alias:
                return True
            continue
        if alias in text:
            return True
    return False


def _rewrite_alias_command(raw: str, lowered: str, key: str) -> str | None:
    for alias in sorted(_aliases(key), key=len, reverse=True):
        if len(alias) <= 2:
            if lowered == alias:
                return _slash(_term(key))
            continue
        if lowered == alias:
            return _slash(_term(key))
        for separator in (":", " - ", " "):
            prefix = f"{alias}{separator}"
            if lowered.startswith(prefix):
                tail = raw[len(alias + separator) :].strip()
                if tail.casefold() in _markers():
                    tail = ""
                return _slash(_term(key), tail)
    return None


def _tags_requested(lowered: str) -> bool:
    return _contains_any(lowered, {"tag", "tags", "тег", "теги", "тегами", "по тегу"})


def _agent_tags_tail(lowered: str) -> str:
    if _contains_any(lowered, {"с тег", "with tag"}):
        return "full"
    return "--tags" if _tags_requested(lowered) else ""


def _rewrite_agents_command(raw: str, lowered: str) -> str | None:
    rewritten = _rewrite_alias_command(raw, lowered, "agents")
    if rewritten:
        if _tags_requested(lowered) and "--tag" not in rewritten:
            return _slash(_term("agents"), _agent_tags_tail(lowered))
        return rewritten
    if _contains_alias(lowered, "agents"):
        return _slash(_term("agents"), _agent_tags_tail(lowered))
    return None


def _rewrite_action(raw: str, lowered: str) -> str | None:
    for name, action in _actions().items():
        natural = _listify(action.get("natural_aliases"))
        natural.extend(_listify(action.get("rewrite_aliases")))
        for alias in natural:
            alias_text = alias.strip().casefold()
            if not alias_text:
                continue
            if lowered == alias_text:
                return _slash(name)
            for separator in (":", " - ", " "):
                prefix = f"{alias_text}{separator}"
                if lowered.startswith(prefix):
                    tail = raw[len(alias_text + separator) :].strip()
                    return _slash(name, tail)
    return None


def _rewrite_intent(raw: str, lowered: str) -> str | None:
    actions = _actions()
    for intent in _intents():
        action_name = str(intent.get("action") or intent.get("target") or "").strip()
        if not action_name or action_name not in actions:
            continue
        aliases = _listify(intent.get("aliases") or intent.get("natural_aliases") or intent.get("phrases"))
        if not aliases:
            continue
        match_mode = str(intent.get("match") or intent.get("mode") or "prefix").strip().casefold()
        min_tail_chars = int(intent.get("min_tail_chars") or intent.get("minimum_tail_chars") or 0)
        require_tail = _as_bool(intent.get("require_tail"), False)
        preserve_full_text = _as_bool(intent.get("preserve_full_text"), False)

        for alias in aliases:
            alias_text = alias.strip().casefold()
            if not alias_text:
                continue

            tail = ""
            matched = False
            if match_mode == "contains":
                index = lowered.find(alias_text)
                if index >= 0:
                    matched = True
                    tail = raw if preserve_full_text else raw[index + len(alias_text) :].strip(" :-\t")
            else:
                if lowered == alias_text:
                    matched = True
                    tail = ""
                else:
                    for separator in (":", " - ", " "):
                        prefix = f"{alias_text}{separator}"
                        if lowered.startswith(prefix):
                            matched = True
                            tail = raw[len(alias_text + separator) :].strip()
                            break

            if not matched:
                continue
            if require_tail and not tail:
                continue
            if min_tail_chars and len(tail) < min_tail_chars:
                continue
            return _slash(action_name, tail)
    return None


def _rewrite_text(text: str) -> str | None:
    if not _env_bool("PAPERCLIP_COCKPIT_NL_REWRITE", True):
        return None
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return None

    lowered = raw.casefold()
    command = _slash()
    if lowered.startswith(command.casefold()):
        return None
    if raw.startswith("/"):
        return None

    action_rewrite = _rewrite_action(raw, lowered)
    if action_rewrite:
        return action_rewrite

    intent_rewrite = _rewrite_intent(raw, lowered)
    if intent_rewrite:
        return intent_rewrite

    issue_match = ISSUE_RE.search(raw)
    issue_ref = issue_match.group(1).upper() if issue_match else ""
    marker = _contains_any(lowered, _markers())

    if issue_ref and _nl_writes_enabled() and _contains_any(lowered, {"move", "перемести", "двинь", "поставь", "закрой", "отмени"}):
        status = _status_from_text(lowered)
        if status:
            return _slash(_term("move"), issue_ref, status)

    if issue_ref and _contains_alias(lowered, "comments"):
        return _slash(_term("comments"), issue_ref)

    if issue_ref and (marker or _contains_alias(lowered, "task") or _contains_any(lowered, {"покажи", "что по", "show"})):
        return _slash(_term("task"), issue_ref)

    rewritten = _rewrite_alias_command(raw, lowered, "health")
    if rewritten or _contains_alias(lowered, "health") or _contains_any(lowered, {"статус paperclip", "статус перклип"}):
        return rewritten or _slash(_term("health"))

    rewritten = _rewrite_agents_command(raw, lowered)
    if rewritten:
        return rewritten

    rewritten = _rewrite_alias_command(raw, lowered, "companies")
    if rewritten or _contains_alias(lowered, "companies") or (marker and _contains_any(lowered, {"organizations", "организации", "компании"})):
        return rewritten or _slash(_term("companies"))

    rewritten = _rewrite_alias_command(raw, lowered, "tasks")
    if rewritten or _contains_alias(lowered, "tasks"):
        return rewritten or _slash(_term("tasks"))

    return None


def _event_allowed(event: Any) -> bool:
    allowed_platforms = _env_csv("PAPERCLIP_COCKPIT_ALLOWED_PLATFORMS")
    allowed_chats = _env_csv("PAPERCLIP_COCKPIT_ALLOWED_CHATS")
    source = getattr(event, "source", None)
    platform_obj = getattr(source, "platform", None)
    platform = getattr(platform_obj, "value", platform_obj)
    platform_text = str(platform or "").casefold()
    chat_id = str(getattr(source, "chat_id", "") or "").casefold()

    if allowed_platforms and platform_text not in allowed_platforms:
        return False
    if allowed_chats and chat_id not in allowed_chats:
        return False
    return True


def _maybe_reset_gateway_shutdown_context(event: Any, gateway: Any = None, session_store: Any = None) -> bool:
    if not _reset_on_gateway_shutdown_enabled():
        return False

    source = getattr(event, "source", None)
    if source is None:
        return False

    store = session_store or getattr(gateway, "session_store", None)
    if store is None:
        return False

    session_key = ""
    try:
        if gateway is not None and hasattr(gateway, "_session_key_for_source"):
            session_key = str(gateway._session_key_for_source(source) or "")
        elif hasattr(store, "_generate_session_key"):
            session_key = str(store._generate_session_key(source) or "")
    except Exception as exc:
        logger.debug("Paperclip Cockpit could not resolve gateway session key: %s", exc)
        return False

    if not session_key:
        return False

    try:
        ensure_loaded = getattr(store, "_ensure_loaded", None)
        if callable(ensure_loaded):
            ensure_loaded()
        entries = getattr(store, "_entries", {}) or {}
        entry = entries.get(session_key)
        if entry is None or not bool(getattr(entry, "resume_pending", False)):
            return False

        reason = str(getattr(entry, "resume_reason", "") or "").casefold()
        allowed_reasons = _reset_on_gateway_shutdown_reasons()
        if allowed_reasons and reason not in allowed_reasons:
            return False

        reset_session = getattr(store, "reset_session", None)
        if not callable(reset_session):
            return False

        reset_session(session_key)
        logger.info(
            "Paperclip Cockpit reset Hermes gateway session %s after interrupted gateway shutdown (reason=%s)",
            session_key,
            reason or "unknown",
        )
        return True
    except Exception as exc:
        logger.warning("Paperclip Cockpit failed to reset interrupted gateway context: %s", exc)
        return False


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _minutes_since(value: Any, now: datetime) -> float | None:
    moment = _datetime_value(value)
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=now.tzinfo)
    return max(0.0, (now - moment.astimezone(now.tzinfo)).total_seconds() / 60.0)


def _maybe_reset_stale_gateway_context(event: Any, gateway: Any = None, session_store: Any = None) -> bool:
    max_age = _gateway_reset_age_minutes()
    max_idle = _gateway_reset_idle_minutes()
    if max_age is None and max_idle is None:
        return False

    source = getattr(event, "source", None)
    if source is None:
        return False

    store = session_store or getattr(gateway, "session_store", None)
    if store is None:
        return False

    try:
        if gateway is not None and hasattr(gateway, "_session_key_for_source"):
            session_key = str(gateway._session_key_for_source(source) or "")
        elif hasattr(store, "_generate_session_key"):
            session_key = str(store._generate_session_key(source) or "")
        else:
            session_key = ""
    except Exception as exc:
        logger.debug("Paperclip Cockpit could not resolve gateway session key: %s", exc)
        return False

    if not session_key:
        return False

    try:
        ensure_loaded = getattr(store, "_ensure_loaded", None)
        if callable(ensure_loaded):
            ensure_loaded()
        entries = getattr(store, "_entries", {}) or {}
        entry = entries.get(session_key)
        if entry is None:
            return False

        now = datetime.now(timezone.utc)
        age = _minutes_since(getattr(entry, "created_at", None), now)
        idle = _minutes_since(getattr(entry, "updated_at", None), now)
        should_reset_age = max_age is not None and age is not None and age >= max_age
        should_reset_idle = max_idle is not None and idle is not None and idle >= max_idle
        if not should_reset_age and not should_reset_idle:
            return False

        reset_session = getattr(store, "reset_session", None)
        if not callable(reset_session):
            return False

        reset_session(session_key)
        logger.info(
            "Paperclip Cockpit reset stale Hermes gateway session %s (age=%.1f idle=%.1f max_age=%s max_idle=%s)",
            session_key,
            age if age is not None else -1,
            idle if idle is not None else -1,
            max_age,
            max_idle,
        )
        return True
    except Exception as exc:
        logger.warning("Paperclip Cockpit failed to reset stale gateway context: %s", exc)
        return False


def _pre_gateway_dispatch(event: Any, **kwargs: Any) -> dict[str, str] | None:
    if not _event_allowed(event):
        return None
    _maybe_reset_stale_gateway_context(
        event,
        gateway=kwargs.get("gateway"),
        session_store=kwargs.get("session_store"),
    )
    _maybe_reset_gateway_shutdown_context(
        event,
        gateway=kwargs.get("gateway"),
        session_store=kwargs.get("session_store"),
    )
    rewritten = _rewrite_text(getattr(event, "text", "") or "")
    if not rewritten:
        return None
    logger.info("Paperclip Cockpit rewrote inbound text to %s", rewritten.split()[0])
    return {"action": "rewrite", "text": rewritten}


def _safe(handler: Any, raw_args: str) -> str:
    try:
        return _clip_output(handler(raw_args))
    except PaperclipError as exc:
        return _format_error(exc)
    except Exception as exc:
        logger.exception("paperclip command failed")
        return _format_error(PaperclipError(f"Paperclip command failed: {exc}"))


def _register_explicit_commands(ctx: Any, command: str) -> None:
    prefix = command.replace("_", "-")
    explicit = {
        f"{prefix}-companies": (_companies_cmd, "List Paperclip companies.", ""),
        f"{prefix}-health": (_health, "Check Paperclip API health.", ""),
        f"{prefix}-status": (_status_cmd, "Show compact Paperclip status.", "[full]"),
        f"{prefix}-agents": (_agents_cmd, "List agents in a Paperclip company.", '[--company "Company Name"]'),
        f"{prefix}-tasks": (
            _tasks_cmd,
            "List Paperclip tasks/issues.",
            '[--company "Company Name"] [open|all|todo|in_progress|blocked|done|cancelled] [limit]',
        ),
        f"{prefix}-task": (_task_cmd, "Show one Paperclip task/issue.", "ISSUE"),
        f"{prefix}-comments": (_comments_cmd, "Show comments for one Paperclip task/issue.", "ISSUE"),
        f"{prefix}-move": (_move_cmd, "Move a Paperclip task/issue to another status.", "ISSUE <status>"),
        f"{prefix}-debug": (_debug_cmd, "Show Paperclip Cockpit diagnostics.", ""),
    }
    for name, (handler, description, args_hint) in explicit.items():
        ctx.register_command(name=name, handler=lambda raw, item=handler: _safe(item, raw), description=description, args_hint=args_hint)


def register(ctx: Any) -> None:
    command = _command_name()
    description = str(
        _config().get("command", {}).get(
            "description",
            "Paperclip cockpit: companies, agents, tasks, comments, project actions, and safe issue moves.",
        )
    )
    ctx.register_command(
        name=command,
        handler=lambda raw: _safe(_router, raw),
        description=description,
        args_hint="",
    )

    register_pc_fallback = bool(_config().get("command", {}).get("register_pc_fallback", False))
    if command != "pc" and register_pc_fallback:
        ctx.register_command(
            name="pc",
            handler=lambda raw: _safe(_router, raw),
            description="Paperclip Cockpit fallback command.",
            args_hint="",
        )

    if _env_bool("PAPERCLIP_COCKPIT_REGISTER_EXPLICIT", False):
        _register_explicit_commands(ctx, command)

    if _env_bool("PAPERCLIP_COCKPIT_PRE_GATEWAY", True) and hasattr(ctx, "register_hook"):
        ctx.register_hook("pre_gateway_dispatch", _pre_gateway_dispatch)
