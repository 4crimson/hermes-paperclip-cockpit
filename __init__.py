from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLUGIN_NAME = "paperclip-cockpit"
VERSION = "0.3.0"

API_BASE = os.environ.get("PAPERCLIP_API_BASE", "http://127.0.0.1:3100/api").rstrip("/")
PUBLIC_BASE = os.environ.get("PAPERCLIP_PUBLIC_BASE", API_BASE.removesuffix("/api")).rstrip("/")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

TASK_STATUSES = {"todo", "in_progress", "blocked", "done", "cancelled"}
OPEN_STATUSES = {"todo", "in_progress", "blocked"}
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
    "agents": "agents",
    "tasks": "tasks",
    "task": "task",
    "comments": "comments",
    "move": "move",
    "capabilities": "capabilities",
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
    "agents": ["agents", "people", "staff", "roster", "who is in", "агенты", "сотрудники"],
    "tasks": ["tasks", "issues", "list", "таски", "задачи"],
    "task": ["task", "issue", "t", "задача"],
    "comments": ["comments", "comment", "комменты", "комментарии"],
    "move": ["move", "m", "двинь", "перемести"],
    "capabilities": ["capabilities", "caps", "config", "settings", "возможности", "настройки"],
}

DEFAULT_MARKERS = ["paperclip", "пеперклип", "перклип", "pc", "пер клип"]


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
    try:
        data = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Could not read Paperclip Cockpit config %s: %s", path, exc)
        return {}
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
        "gateway": {},
    }
    for path in _config_paths():
        config = _merge_dict(config, _read_json(path))
    return config


def _gateway_config() -> dict[str, Any]:
    config = _config().get("gateway", {})
    return config if isinstance(config, dict) else {}


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


def _action_aliases(name: str, action: dict[str, Any]) -> set[str]:
    aliases = {name}
    aliases.update(_listify(action.get("aliases")))
    return {item.strip().casefold() for item in aliases if item.strip()}


def _action_usage(name: str, action: dict[str, Any]) -> str:
    usage = str(action.get("usage") or name).strip()
    return usage or name


def _help(_: str = "") -> str:
    writes = "enabled" if _writes_enabled() else "disabled"
    nl_writes = "enabled" if _nl_writes_enabled() else "disabled"
    command = _slash()
    lines = [
        "Usage:",
        f"{command} help",
        f"{command} {_term('companies')}",
        f"{command} {_term('health')}",
        f"{command} {_term('agents')} [--company NAME]",
        f"{command} {_term('tasks')} [--company NAME] [open|all|todo|in_progress|blocked|done|cancelled] [limit]",
        f"{command} {_term('task')} ISSUE",
        f"{command} {_term('comments')} ISSUE",
        f"{command} {_term('move')} ISSUE <todo|in_progress|blocked|done|cancelled>",
        f"{command} {_term('capabilities')}",
    ]
    actions = _actions()
    if actions:
        lines.extend(["", "Project actions:"])
        for name, action in actions.items():
            lines.append(f"{command} {_action_usage(name, action)}")
    lines.extend(
        [
            "",
            "Safety:",
            f"- slash-command writes: {writes}",
            f"- natural-language writes: {nl_writes}",
            "",
            "Company selection:",
            "- config company_hints",
            "- env PAPERCLIP_DEFAULT_COMPANY or PAPERCLIP_COMPANY_NAME",
            "- otherwise Hermes terminal.cwd is fuzzy-matched to a Paperclip company",
            "- pass --company \"Company Name\" when needed",
        ]
    )
    return "\n".join(lines)


def _health(_: str) -> str:
    data = _api("/health", timeout=5)
    if isinstance(data, dict):
        return f"Paperclip health: {'ok' if data.get('ok', True) else 'failed'} version={data.get('version', '-')}"
    return "Paperclip health: ok"


def _companies_cmd(_: str) -> str:
    return _format_companies(_companies())


def _agents_cmd(raw_args: str) -> str:
    words, company_token = _extract_company(_parse_words(raw_args))
    if words and not company_token:
        company_token = " ".join(words)
    company = _resolve_company(company_token)
    agents = _api(f"/companies/{company['id']}/agents")
    lines = [f"# Paperclip {_label('agents')}: {company['name']}"]
    for agent in sorted(agents, key=lambda item: str(item.get("name", "")).casefold()):
        status = agent.get("status") or "unknown"
        adapter = agent.get("adapterType") or "-"
        role = agent.get("role") or "-"
        lines.append(f"- {status:<12} {agent.get('name')} role={role} adapter={adapter}")
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
    words, company_token = _extract_company(_parse_words(raw_args))
    scope = "open"
    limit = 10

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

    issues.sort(key=lambda item: str(item.get("lastActivityAt") or item.get("updatedAt") or ""), reverse=True)
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
    issue_ref = _issue_ref(raw_args)
    if not issue_ref:
        return f"Usage: {_slash(_term('task'), 'ISSUE')}"
    issue = _api(f"/issues/{issue_ref}")
    agents = _api(f"/companies/{issue['companyId']}/agents")
    agent_by_id = {agent["id"]: agent for agent in agents}
    comments = [item for item in _api(f"/issues/{issue['id']}/comments") if not item.get("deletedAt")]
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
    issue_ref = _issue_ref(raw_args)
    if not issue_ref:
        return f"Usage: {_slash(_term('comments'), 'ISSUE')}"
    issue = _api(f"/issues/{issue_ref}")
    comments = [item for item in _api(f"/issues/{issue['id']}/comments") if not item.get("deletedAt")]
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
    try:
        _api(
            f"/issues/{issue['id']}/comments",
            method="POST",
            body={"body": f"Status changed via Paperclip Cockpit: {old_status} -> {next_status}."},
        )
    except Exception as exc:
        logger.info("Paperclip comment after move failed: %s", exc)
    ident = updated.get("identifier") or issue.get("identifier") or issue.get("id")
    return f"Moved {ident}: {old_status} -> {next_status}\nOpen: {_issue_url(issue)}"


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
        f"- explicit_commands_registered: {_env_bool('PAPERCLIP_COCKPIT_REGISTER_EXPLICIT', False)}",
        f"- project_actions: {', '.join(_actions().keys()) or '-'}",
    ]
    return "\n".join(lines)


def _run_action(name: str, action: dict[str, Any], raw_args: str) -> str:
    if action.get("disabled"):
        return f"Project action disabled: {name}"
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
    if result.returncode == 0:
        return _clip(output or "OK")
    body = output
    if error:
        body = f"{body}\n\nstderr:\n{error}".strip()
    return _clip(f"Project action exited with {result.returncode}.\n\n{body}")


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
        if head in _aliases("capabilities"):
            return _capabilities_cmd(tail)

        for name, action in _actions().items():
            if head in _action_aliases(name, action):
                return _run_action(name, action, tail)
    except PaperclipError as exc:
        return str(exc)

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

    rewritten = _rewrite_alias_command(raw, lowered, "companies")
    if rewritten or _contains_alias(lowered, "companies") or (marker and _contains_any(lowered, {"organizations", "организации", "компании"})):
        return rewritten or _slash(_term("companies"))

    rewritten = _rewrite_alias_command(raw, lowered, "agents")
    if rewritten or _contains_alias(lowered, "agents"):
        return rewritten or _slash(_term("agents"))

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


def _pre_gateway_dispatch(event: Any, **kwargs: Any) -> dict[str, str] | None:
    if not _event_allowed(event):
        return None
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
        return _clip(handler(raw_args))
    except PaperclipError as exc:
        return str(exc)
    except Exception as exc:
        logger.exception("paperclip command failed")
        return f"Paperclip command failed: {exc}"


def _register_explicit_commands(ctx: Any, command: str) -> None:
    prefix = command.replace("_", "-")
    explicit = {
        f"{prefix}-companies": (_companies_cmd, "List Paperclip companies.", ""),
        f"{prefix}-health": (_health, "Check Paperclip API health.", ""),
        f"{prefix}-agents": (_agents_cmd, "List agents in a Paperclip company.", '[--company "Company Name"]'),
        f"{prefix}-tasks": (
            _tasks_cmd,
            "List Paperclip tasks/issues.",
            '[--company "Company Name"] [open|all|todo|in_progress|blocked|done|cancelled] [limit]',
        ),
        f"{prefix}-task": (_task_cmd, "Show one Paperclip task/issue.", "ISSUE"),
        f"{prefix}-comments": (_comments_cmd, "Show comments for one Paperclip task/issue.", "ISSUE"),
        f"{prefix}-move": (_move_cmd, "Move a Paperclip task/issue to another status.", "ISSUE <status>"),
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
