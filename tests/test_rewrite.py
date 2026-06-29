import importlib.util
import os
import pathlib
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
