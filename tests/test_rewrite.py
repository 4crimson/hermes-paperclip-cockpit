import importlib.util
import os
import pathlib
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
