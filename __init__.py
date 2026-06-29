from __future__ import annotations

import json
import logging
import os
import re
import shlex
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLUGIN_NAME = "paperclip-cockpit"
VERSION = "0.1.0"

API_BASE = os.environ.get("PAPERCLIP_API_BASE", "http://127.0.0.1:3100/api").rstrip("/")
PUBLIC_BASE = os.environ.get("PAPERCLIP_PUBLIC_BASE", API_BASE.removesuffix("/api")).rstrip("/")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

TASK_STATUSES = {"todo", "in_progress", "blocked", "done", "cancelled"}
OPEN_STATUSES = {"todo", "in_progress", "blocked"}
ISSUE_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,12}-\d+)\b", re.IGNORECASE)


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


def _company_hints() -> list[str]:
    hints = [
        os.environ.get("PAPERCLIP_DEFAULT_COMPANY", ""),
        os.environ.get("PAPERCLIP_COMPANY_NAME", ""),
        os.environ.get("INNER_AGORA_COMPANY_NAME", ""),
        os.environ.get("AI_BOARD_COMPANY_NAME", ""),
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
        raise PaperclipError(f"Unknown Paperclip company: {token}\n\n{_format_companies(companies)}")

    for hint in _company_hints():
        match = _match_company(companies, hint)
        if match:
            return match

    if len(companies) == 1:
        return companies[0]

    raise PaperclipError(
        "Multiple Paperclip companies found. Pass --company \"Name\" or set PAPERCLIP_DEFAULT_COMPANY.\n\n"
        + _format_companies(companies)
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
    lines = ["# Paperclip companies"]
    for company in sorted(companies, key=lambda item: str(item.get("name", "")).casefold()):
        prefix = company.get("issuePrefix") or "-"
        status = company.get("status") or "unknown"
        lines.append(f"- {company.get('name')} ({prefix}) status={status} id={_compact_id(company.get('id'))}")
    return "\n".join(lines)


def _help(_: str = "") -> str:
    writes = "enabled" if _writes_enabled() else "disabled"
    nl_writes = "enabled" if _nl_writes_enabled() else "disabled"
    return f"""Usage:
/pc help
/pc companies
/pc health
/pc agents [--company NAME]
/pc tasks [--company NAME] [open|all|todo|in_progress|blocked|done|cancelled] [limit]
/pc task ISSUE
/pc comments ISSUE
/pc move ISSUE <todo|in_progress|blocked|done|cancelled>
/pc capabilities

Aliases:
/pc orgs
/pc people
/pc list
/pc t ISSUE
/pc m ISSUE STATUS

Safety:
- slash-command writes: {writes}
- natural-language writes: {nl_writes}

Company selection:
- env PAPERCLIP_DEFAULT_COMPANY or PAPERCLIP_COMPANY_NAME
- otherwise Hermes terminal.cwd is fuzzy-matched to a Paperclip company
- pass --company "Company Name" when needed
"""


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
    lines = [f"# Paperclip agents: {company['name']}"]
    for agent in sorted(agents, key=lambda item: str(item.get("name", "")).casefold()):
        status = agent.get("status") or "unknown"
        adapter = agent.get("adapterType") or "-"
        role = agent.get("role") or "-"
        lines.append(f"- {status:<12} {agent.get('name')} role={role} adapter={adapter}")
    lines.append(f"\nTotal: {len(agents)}")
    return "\n".join(lines)


def _tasks_cmd(raw_args: str) -> str:
    words, company_token = _extract_company(_parse_words(raw_args))
    scope = "open"
    limit = 10

    if words and words[0].casefold() in {"open", "all", "todo", "in_progress", "blocked", "done", "cancelled"}:
        scope = words.pop(0).casefold()
    elif words and not words[0].isdigit():
        company_token = words.pop(0)

    if words and words[0].casefold() in {"open", "all", "todo", "in_progress", "blocked", "done", "cancelled"}:
        scope = words.pop(0).casefold()
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
    lines = [f"# Paperclip tasks: {company['name']} ({scope}, limit {limit})"]
    if not issues:
        lines.append("- No tasks.")
    for issue in issues[:limit]:
        assignee = _agent_name(agent_by_id, issue.get("assigneeAgentId"))
        ident = issue.get("identifier") or _compact_id(issue.get("id"))
        parent = "child" if issue.get("parentId") else "root"
        lines.append(f"- {issue.get('status'):<12} {ident:<8} {parent:<5} assignee={assignee} {issue.get('title')}")
    return "\n".join(lines)


def _task_cmd(raw_args: str) -> str:
    issue_ref = _issue_ref(raw_args)
    if not issue_ref:
        return "Usage: /pc task ISSUE"
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
        "## Last comments",
    ]
    if not comments:
        lines.append("- No comments.")
    for comment in comments[-3:]:
        body = re.sub(r"\s+", " ", comment.get("body") or "").strip()
        lines.append(f"- {comment.get('authorType') or 'unknown'} {comment.get('createdAt') or ''}: {_clip(body, 500)}")
    return "\n".join(lines)


def _comments_cmd(raw_args: str) -> str:
    issue_ref = _issue_ref(raw_args)
    if not issue_ref:
        return "Usage: /pc comments ISSUE"
    issue = _api(f"/issues/{issue_ref}")
    comments = [item for item in _api(f"/issues/{issue['id']}/comments") if not item.get("deletedAt")]
    lines = [f"# Comments: {issue.get('identifier') or issue.get('id')}", issue.get("title") or ""]
    if not comments:
        lines.append("\nNo comments.")
    for comment in comments[-8:]:
        lines.extend(["", f"--- {comment.get('authorType') or 'unknown'} {comment.get('createdAt') or ''} ---", comment.get("body") or ""])
    return _clip("\n".join(lines))


def _move_cmd(raw_args: str) -> str:
    if not _writes_enabled():
        return (
            "Paperclip writes are disabled. Set PAPERCLIP_COCKPIT_ENABLE_WRITES=1 "
            "in the Hermes environment to enable /pc move."
        )
    words = _parse_words(raw_args)
    if len(words) != 2 or words[1] not in TASK_STATUSES:
        return "Usage: /pc move ISSUE <todo|in_progress|blocked|done|cancelled>"
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
    lines = [
        "# Paperclip Cockpit capabilities",
        f"- plugin: {PLUGIN_NAME} {VERSION}",
        f"- api_base: {API_BASE}",
        f"- profile: {HERMES_HOME}",
        f"- default_company_hints: {', '.join(_company_hints()) or '-'}",
        f"- natural_language_rewrite: {_env_bool('PAPERCLIP_COCKPIT_NL_REWRITE', True)}",
        f"- slash_command_writes: {_writes_enabled()}",
        f"- natural_language_writes: {_nl_writes_enabled()}",
        f"- explicit_commands_registered: {_env_bool('PAPERCLIP_COCKPIT_REGISTER_EXPLICIT', False)}",
    ]
    return "\n".join(lines)


def _router(raw_args: str) -> str:
    raw = raw_args.strip()
    if not raw:
        return _help().strip()
    words = _parse_words(raw)
    head = words[0].casefold()
    tail = " ".join(words[1:]).strip()

    try:
        if head in {"help", "помощь", "commands", "?"}:
            return _help(tail).strip()
        if head in {"health", "ping", "здоровье"}:
            return _health(tail)
        if head in {"companies", "company", "orgs", "org", "организации", "компании"}:
            return _companies_cmd(tail)
        if head in {"agents", "people", "staff", "philosophers", "агенты", "сотрудники", "философы"}:
            return _agents_cmd(tail)
        if head in {"tasks", "issues", "list", "таски", "задачи"}:
            return _tasks_cmd(tail)
        if head in {"task", "issue", "t", "задача"}:
            return _task_cmd(tail)
        if head in {"comments", "comment", "комменты", "комментарии"}:
            return _comments_cmd(tail)
        if head in {"move", "m", "двинь", "перемести"}:
            return _move_cmd(tail)
        if head in {"capabilities", "caps", "config", "settings", "возможности", "настройки"}:
            return _capabilities_cmd(tail)
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


def _rewrite_text(text: str) -> str | None:
    if not _env_bool("PAPERCLIP_COCKPIT_NL_REWRITE", True):
        return None
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw or raw.startswith("/"):
        return None

    lowered = raw.casefold()
    issue_match = ISSUE_RE.search(raw)
    issue_ref = issue_match.group(1).upper() if issue_match else ""
    pc_marker = _contains_any(lowered, {"paperclip", "пеперклип", "перклип", "pc", "пер клип"})

    if issue_ref and _nl_writes_enabled() and _contains_any(lowered, {"move", "перемести", "двинь", "поставь", "закрой", "отмени"}):
        status = _status_from_text(lowered)
        if status:
            return f"/pc move {issue_ref} {status}"

    if issue_ref and _contains_any(lowered, {"comments", "comment", "комменты", "комментарии", "обсуждение"}):
        return f"/pc comments {issue_ref}"

    if issue_ref and (pc_marker or _contains_any(lowered, {"task", "issue", "задача", "покажи", "что по", "show"})):
        return f"/pc task {issue_ref}"

    if _contains_any(lowered, {"health", "ping", "статус paperclip", "статус перклип", "работает paperclip", "работает перклип"}):
        return "/pc health"

    if pc_marker and _contains_any(lowered, {"companies", "orgs", "organizations", "организации", "компании"}):
        return "/pc companies"

    if _contains_any(lowered, {"paperclip companies", "paperclip orgs", "перклип организации", "пеперклип организации"}):
        return "/pc companies"

    if _contains_any(lowered, {"agents", "people", "staff", "агенты", "сотрудники"}) or (
        pc_marker and _contains_any(lowered, {"философ", "кто в организации", "состав"})
    ):
        return "/pc agents"

    if _contains_any(lowered, {"tasks", "issues", "таски", "задачи"}) or (
        pc_marker and _contains_any(lowered, {"список дел", "что делать"})
    ):
        return "/pc tasks"

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


def _pre_gateway_dispatch(event: Any, **_: Any) -> dict[str, str] | None:
    if not _event_allowed(event):
        return None
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


def _register_explicit_commands(ctx: Any) -> None:
    ctx.register_command(
        name="pc-companies",
        handler=lambda raw: _safe(_companies_cmd, raw),
        description="List Paperclip companies.",
        args_hint="",
    )
    ctx.register_command(
        name="pc-health",
        handler=lambda raw: _safe(_health, raw),
        description="Check Paperclip API health.",
        args_hint="",
    )
    ctx.register_command(
        name="pc-agents",
        handler=lambda raw: _safe(_agents_cmd, raw),
        description="List agents in a Paperclip company.",
        args_hint='[--company "Company Name"]',
    )
    ctx.register_command(
        name="pc-tasks",
        handler=lambda raw: _safe(_tasks_cmd, raw),
        description="List Paperclip tasks/issues.",
        args_hint='[--company "Company Name"] [open|all|todo|in_progress|blocked|done|cancelled] [limit]',
    )
    ctx.register_command(
        name="pc-task",
        handler=lambda raw: _safe(_task_cmd, raw),
        description="Show one Paperclip task/issue.",
        args_hint="ISSUE",
    )
    ctx.register_command(
        name="pc-comments",
        handler=lambda raw: _safe(_comments_cmd, raw),
        description="Show comments for one Paperclip task/issue.",
        args_hint="ISSUE",
    )
    ctx.register_command(
        name="pc-move",
        handler=lambda raw: _safe(_move_cmd, raw),
        description="Move a Paperclip task/issue to another status.",
        args_hint="ISSUE <todo|in_progress|blocked|done|cancelled>",
    )


def register(ctx: Any) -> None:
    ctx.register_command(
        name="pc",
        handler=lambda raw: _safe(_router, raw),
        description="Paperclip cockpit: companies, agents, tasks, comments, and safe issue moves.",
        args_hint="",
    )

    if _env_bool("PAPERCLIP_COCKPIT_REGISTER_EXPLICIT", False):
        _register_explicit_commands(ctx)

    if _env_bool("PAPERCLIP_COCKPIT_PRE_GATEWAY", True) and hasattr(ctx, "register_hook"):
        ctx.register_hook("pre_gateway_dispatch", _pre_gateway_dispatch)
