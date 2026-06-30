import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("paperclip_cockpit", ROOT / "__init__.py")
paperclip_cockpit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(paperclip_cockpit)


class RewriteTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("PAPERCLIP_COCKPIT_NL_WRITES", None)
        os.environ.pop("PAPERCLIP_COCKPIT_NL_REWRITE", None)
        os.environ.pop("PAPERCLIP_COCKPIT_CONFIG", None)
        os.environ.pop("PAPERCLIP_COCKPIT_PRESENTATION", None)
        self._orig_api = paperclip_cockpit._api
        self.addCleanup(setattr, paperclip_cockpit, "_api", self._orig_api)

    def test_rewrites_companies(self):
        self.assertEqual(paperclip_cockpit._rewrite_text("show paperclip companies"), "/pc companies")

    def test_rewrites_russian_company_genitive(self):
        self.assertEqual(paperclip_cockpit._rewrite_text("покажи список компаний"), "/pc companies")

    def test_rewrites_russian_tasks(self):
        self.assertEqual(paperclip_cockpit._rewrite_text("покажи задачи"), "/pc tasks")

    def test_rewrites_task_tail(self):
        self.assertEqual(paperclip_cockpit._rewrite_text("tasks all 20"), "/pc tasks all 20")

    def test_rewrites_agent_phrase(self):
        self.assertEqual(paperclip_cockpit._rewrite_text("who is in paperclip"), "/pc agents")

    def test_rewrites_issue_detail(self):
        self.assertEqual(paperclip_cockpit._rewrite_text("что по THE-9"), "/pc task THE-9")

    def test_rewrites_comments(self):
        self.assertEqual(paperclip_cockpit._rewrite_text("комменты THE-9"), "/pc comments THE-9")

    def test_does_not_rewrite_write_by_default(self):
        self.assertIsNone(paperclip_cockpit._rewrite_text("move THE-9 done"))

    def test_rewrites_write_when_enabled(self):
        os.environ["PAPERCLIP_COCKPIT_NL_WRITES"] = "1"
        self.assertEqual(paperclip_cockpit._rewrite_text("move THE-9 done"), "/pc move THE-9 done")

    def test_respects_rewrite_disable(self):
        os.environ["PAPERCLIP_COCKPIT_NL_REWRITE"] = "0"
        self.assertIsNone(paperclip_cockpit._rewrite_text("покажи задачи"))

    def test_custom_command_and_alias_config(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as config:
            config.write(
                '{"command":{"name":"work"},"terms":{"agents":"members"},'
                '"aliases":{"agents":["team roster"]},"markers":["work"]}'
            )
            config.flush()
            os.environ["PAPERCLIP_COCKPIT_CONFIG"] = config.name
            self.assertEqual(paperclip_cockpit._rewrite_text("team roster"), "/work members")
            self.assertEqual(paperclip_cockpit._slash(), "/work")

    def test_intent_rewrites_to_project_action(self):
        body = {
            "command": {"name": "lab"},
            "actions": {
                "research": {
                    "exec": ["./scripts/research"],
                    "usage": "research QUESTION",
                }
            },
            "intents": {
                "create_research": {
                    "action": "research",
                    "aliases": ["start research", "запусти исследование"],
                    "require_tail": True,
                    "min_tail_chars": 10,
                }
            },
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as config:
            config.write(json.dumps(body))
            config.flush()
            os.environ["PAPERCLIP_COCKPIT_CONFIG"] = config.name
            self.assertEqual(
                paperclip_cockpit._rewrite_text("запусти исследование: план релиза проекта"),
                "/lab research план релиза проекта",
            )
            self.assertIsNone(paperclip_cockpit._rewrite_text("запусти исследование"))
            self.assertIsNone(paperclip_cockpit._rewrite_text("запусти исследование: ок"))

    def test_extract_agent_tag_options(self):
        remaining, options = paperclip_cockpit._extract_agent_options(["--tag", "ethics", "The", "Agora"])
        self.assertEqual(remaining, ["The", "Agora"])
        self.assertEqual(options["tag"], "ethics")
        self.assertFalse(options["show_tags"])

        remaining, options = paperclip_cockpit._extract_agent_options(["--tags"])
        self.assertEqual(remaining, [])
        self.assertTrue(options["show_tags"])

    def test_agent_tags_from_metadata(self):
        self.assertEqual(
            paperclip_cockpit._agent_tags({"metadata": {"tags": ["ethics", "", " politics "]}}),
            ["ethics", "politics"],
        )

    def test_gateway_shutdown_reset_when_enabled(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as config:
            config.write('{"gateway":{"reset_on_gateway_shutdown":true}}')
            config.flush()
            os.environ["PAPERCLIP_COCKPIT_CONFIG"] = config.name

            session_key = "agent:main:telegram:dm:1"

            class Store:
                def __init__(self):
                    self._entries = {
                        session_key: SimpleNamespace(
                            resume_pending=True,
                            resume_reason="shutdown_timeout",
                        )
                    }
                    self.reset_calls = []

                def _ensure_loaded(self):
                    return None

                def reset_session(self, key):
                    self.reset_calls.append(key)
                    self._entries[key].resume_pending = False
                    return SimpleNamespace(session_id="fresh")

            store = Store()
            gateway = SimpleNamespace(
                session_store=store,
                _session_key_for_source=lambda source: session_key,
            )
            event = SimpleNamespace(
                text="show paperclip companies",
                source=SimpleNamespace(
                    platform=SimpleNamespace(value="telegram"),
                    chat_id="1",
                ),
            )

            self.assertTrue(paperclip_cockpit._maybe_reset_gateway_shutdown_context(event, gateway=gateway))
            self.assertEqual(store.reset_calls, [session_key])

    def test_gateway_shutdown_reset_disabled_by_default(self):
        session_key = "agent:main:telegram:dm:1"
        store = SimpleNamespace(
            _entries={
                session_key: SimpleNamespace(
                    resume_pending=True,
                    resume_reason="shutdown_timeout",
                )
            },
            _ensure_loaded=lambda: None,
            reset_session=lambda key: (_ for _ in ()).throw(AssertionError("should not reset")),
        )
        gateway = SimpleNamespace(
            session_store=store,
            _session_key_for_source=lambda source: session_key,
        )
        event = SimpleNamespace(
            text="show paperclip companies",
            source=SimpleNamespace(
                platform=SimpleNamespace(value="telegram"),
                chat_id="1",
            ),
        )

        self.assertFalse(paperclip_cockpit._maybe_reset_gateway_shutdown_context(event, gateway=gateway))

    def test_stale_gateway_session_reset_by_age(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as config:
            config.write('{"gateway":{"reset_session_age_minutes":60}}')
            config.flush()
            os.environ["PAPERCLIP_COCKPIT_CONFIG"] = config.name

            session_key = "agent:main:telegram:dm:1"

            class Store:
                def __init__(self):
                    now = datetime.now(timezone.utc)
                    self._entries = {
                        session_key: SimpleNamespace(
                            created_at=now - timedelta(minutes=90),
                            updated_at=now,
                        )
                    }
                    self.reset_calls = []

                def _ensure_loaded(self):
                    return None

                def reset_session(self, key):
                    self.reset_calls.append(key)
                    return SimpleNamespace(session_id="fresh")

            store = Store()
            gateway = SimpleNamespace(
                session_store=store,
                _session_key_for_source=lambda source: session_key,
            )
            event = SimpleNamespace(
                text="show paperclip companies",
                source=SimpleNamespace(
                    platform=SimpleNamespace(value="telegram"),
                    chat_id="1",
                ),
            )

            self.assertTrue(paperclip_cockpit._maybe_reset_stale_gateway_context(event, gateway=gateway))
            self.assertEqual(store.reset_calls, [session_key])

    def test_human_home_default_hides_technical_blocks(self):
        output = paperclip_cockpit._router("")
        self.assertIn("Connected to Paperclip.", output)
        self.assertIn("/pc status", output)
        self.assertNotIn("Usage:", output)
        self.assertNotIn("Safety:", output)
        self.assertNotIn("Company selection:", output)

    def test_help_full_preserves_technical_help(self):
        output = paperclip_cockpit._router("help full")
        self.assertIn("Usage:", output)
        self.assertIn("Safety:", output)
        self.assertIn("Company selection:", output)

    def test_raw_presentation_env_uses_technical_help(self):
        os.environ["PAPERCLIP_COCKPIT_PRESENTATION"] = "raw"
        output = paperclip_cockpit._router("")
        self.assertIn("Usage:", output)
        self.assertIn("Safety:", output)

    def test_custom_terms_drive_human_home(self):
        body = {
            "command": {"name": "work"},
            "terms": {"agents": "members", "tasks": "items", "status": "overview", "debug": "debug"},
            "presentation": {
                "home": {
                    "intro": "Workspace connected.",
                    "items": [
                        {"action": "status", "text": "quick state"},
                        {"action": "agents", "text": "team list"},
                        {"action": "tasks", "text": "work queue"},
                    ],
                    "more": [{"action": "debug", "text": "diagnostics"}],
                }
            },
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as config:
            config.write(json.dumps(body))
            config.flush()
            os.environ["PAPERCLIP_COCKPIT_CONFIG"] = config.name
            output = paperclip_cockpit._router("")
        self.assertIn("Workspace connected.", output)
        self.assertIn("/work overview - quick state", output)
        self.assertIn("/work members - team list", output)
        self.assertIn("/work items - work queue", output)

    def test_human_status_summarizes_and_hides_run_ids(self):
        run_id = "11111111-2222-3333-4444-555555555555"

        def fake_api(path, **kwargs):
            if path == "/health":
                return {"ok": True}
            if path == "/companies":
                return [{"id": "c1", "name": "Example Workspace", "issuePrefix": "EX", "status": "active"}]
            if path == "/companies/c1/agents":
                return [{"id": f"a{i}", "name": f"Agent {i}", "status": "idle"} for i in range(80)]
            if path == "/companies/c1/issues":
                return [
                    {
                        "id": "i1",
                        "identifier": "EX-1",
                        "title": "Open item",
                        "status": "todo",
                        "parentId": None,
                        "updatedAt": "2026-01-02T00:00:00Z",
                    },
                    {
                        "id": "i2",
                        "identifier": "EX-2",
                        "title": "Done item",
                        "status": "done",
                        "parentId": None,
                        "updatedAt": "2026-01-01T00:00:00Z",
                    },
                ]
            if path == "/companies/c1/heartbeat-runs":
                return [{"id": run_id, "status": "succeeded", "updatedAt": "2026-01-03T00:00:00Z"}]
            raise AssertionError(path)

        paperclip_cockpit._api = fake_api
        output = paperclip_cockpit._router("status")
        self.assertIn("Paperclip is reachable.", output)
        self.assertIn("Agents: 80", output)
        self.assertIn("Active agents: 0", output)
        self.assertIn("Open tasks: 1", output)
        self.assertIn("Latest task: EX-1", output)
        self.assertNotIn(run_id, output)

        full = paperclip_cockpit._router("status full")
        self.assertIn("Recent runs", full)
        self.assertIn(run_id, full)

    def test_human_agents_summarizes_large_idle_roster(self):
        def fake_api(path, **kwargs):
            if path == "/companies":
                return [{"id": "c1", "name": "Example Workspace", "issuePrefix": "EX", "status": "active"}]
            if path == "/companies/c1/agents":
                return [{"id": f"a{i}", "name": f"Agent {i}", "status": "idle", "role": "worker"} for i in range(80)]
            raise AssertionError(path)

        paperclip_cockpit._api = fake_api
        output = paperclip_cockpit._router("agents")
        self.assertIn("Agents: 80", output)
        self.assertIn("Idle: 80", output)
        self.assertIn("and 68 more", output)
        self.assertLess(output.count("Agent "), 20)

        full = paperclip_cockpit._router("agents full")
        self.assertIn("role=worker", full)
        self.assertGreater(full.count("Agent "), 70)

    def test_human_tasks_respects_limits(self):
        body = {"presentation": {"limits": {"tasks": 2}}}
        issues = [
            {
                "id": f"i{i}",
                "identifier": f"EX-{i}",
                "title": f"Task {i}",
                "status": "todo",
                "parentId": None,
                "assigneeAgentId": None,
                "updatedAt": f"2026-01-0{i}T00:00:00Z",
            }
            for i in range(1, 5)
        ]

        def fake_api(path, **kwargs):
            if path == "/companies":
                return [{"id": "c1", "name": "Example Workspace", "issuePrefix": "EX", "status": "active"}]
            if path == "/companies/c1/issues":
                return issues
            if path == "/companies/c1/agents":
                return []
            raise AssertionError(path)

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as config:
            config.write(json.dumps(body))
            config.flush()
            os.environ["PAPERCLIP_COCKPIT_CONFIG"] = config.name
            paperclip_cockpit._api = fake_api
            output = paperclip_cockpit._router("tasks")
        self.assertIn("Open tasks: 4", output)
        self.assertIn("EX-4", output)
        self.assertIn("EX-3", output)
        self.assertNotIn("EX-2", output)
        self.assertIn("and 2 more", output)

    def test_human_error_hides_raw_detail_by_default(self):
        def fake_api(path, **kwargs):
            raise paperclip_cockpit.PaperclipError("GET /health failed: connection refused")

        paperclip_cockpit._api = fake_api
        output = paperclip_cockpit._router("status")
        self.assertIn("I could not complete the Paperclip request.", output)
        self.assertIn("/pc debug", output)
        self.assertNotIn("GET /health failed", output)

    def test_error_details_can_be_enabled(self):
        body = {"presentation": {"errors": {"show_details": True}}}

        def fake_api(path, **kwargs):
            raise paperclip_cockpit.PaperclipError("GET /health failed: connection refused")

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as config:
            config.write(json.dumps(body))
            config.flush()
            os.environ["PAPERCLIP_COCKPIT_CONFIG"] = config.name
            paperclip_cockpit._api = fake_api
            output = paperclip_cockpit._router("status")
        self.assertIn("GET /health failed", output)

    def test_project_action_human_presentation_filters_technical_blocks(self):
        script = "print('Keep this')\nprint('Safety:')\nprint('- noisy')\nprint()\nprint('Company selection:')\nprint('- noisy')\nprint()\nprint('Still here')"
        body = {
            "actions": {
                "demo": {
                    "exec": [sys.executable, "-c", script],
                    "presentation": {"mode": "human", "clip": 1000},
                }
            }
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as config:
            config.write(json.dumps(body))
            config.flush()
            os.environ["PAPERCLIP_COCKPIT_CONFIG"] = config.name
            output = paperclip_cockpit._router("demo")
        self.assertIn("Keep this", output)
        self.assertIn("Still here", output)
        self.assertNotIn("Safety:", output)
        self.assertNotIn("Company selection:", output)

    def test_human_task_card_and_full_comments(self):
        comments = [
            {"authorType": "user", "createdAt": f"2026-01-0{i}T00:00:00Z", "body": f"Comment {i}"}
            for i in range(1, 5)
        ]

        def fake_api(path, **kwargs):
            if path == "/issues/EX-1":
                return {
                    "id": "i1",
                    "companyId": "c1",
                    "identifier": "EX-1",
                    "title": "Readable task",
                    "description": "Long description",
                    "status": "in_progress",
                    "priority": "high",
                    "assigneeAgentId": "a1",
                    "parentId": None,
                }
            if path == "/companies/c1/agents":
                return [{"id": "a1", "name": "Alice", "status": "active"}]
            if path == "/issues/i1/comments":
                return comments
            raise AssertionError(path)

        paperclip_cockpit._api = fake_api
        task = paperclip_cockpit._router("task EX-1")
        self.assertIn("EX-1", task)
        self.assertIn("Readable task", task)
        self.assertIn("Status: in progress", task)
        self.assertIn("Assignee: Alice", task)
        self.assertIn("Comment 2", task)
        self.assertIn("Comment 4", task)
        self.assertNotIn("Comment 1", task)
        self.assertIn("/pc task EX-1 full", task)

        full_task = paperclip_cockpit._router("task EX-1 full")
        self.assertIn("## Description", full_task)
        self.assertIn("Long description", full_task)

        notes = paperclip_cockpit._router("comments EX-1")
        self.assertIn("Comments: EX-1", notes)
        self.assertIn("Comment 2", notes)
        self.assertIn("Comment 4", notes)
        self.assertNotIn("---", notes)

        full_notes = paperclip_cockpit._router("comments EX-1 full")
        self.assertIn("--- user 2026-01-01T00:00:00Z ---", full_notes)
        self.assertIn("Comment 1", full_notes)


if __name__ == "__main__":
    unittest.main()
