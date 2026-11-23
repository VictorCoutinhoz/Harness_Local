from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import tomllib
import unittest
from uuid import uuid4

from harness import ROOT, STATE, catalog, inspect, main, relative_path


class ProfileTests(unittest.TestCase):
    def setUp(self):
        fixtures = ROOT / ".harness-local/test-fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=fixtures)
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name)
        self.database = self.target / ".harness-local/state/test.sqlite3"
        self.options = ["prepare", str(self.target), "--database", str(self.database)]

    def run_cli(self, args, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(args)
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def test_catalog_contains_every_owned_skill_and_playwright_role(self):
        items, routes = catalog()
        self.assertEqual(sum(item["kind"] == "skill" for item in items.values()), 26)
        self.assertEqual(sum(item["kind"] == "mcp" for item in items.values()), 4)
        roles = {name for name, item in items.items() if item["kind"] == "agent"}
        self.assertEqual(len(roles), 3)
        self.assertTrue(roles <= set(routes["e2e"]["uses"]))
        status = inspect(items, "base")
        self.assertEqual(status["harness_local"], "disponível")
        self.assertTrue(all(status[role] != "disponível" for role in roles))

    def test_repeat_preparation_and_preserve_existing_instructions(self):
        instructions = self.target / "AGENTS.md"
        instructions.write_bytes(b"# Projeto\r\n\r\nUse a stack atual.\r\n")
        first = json.loads(self.run_cli(self.options)[0])
        second = json.loads(self.run_cli(self.options)[0])
        self.assertEqual(first["skills"], 17)
        self.assertEqual(first["mcp"], ["harness_local"])
        self.assertEqual(second["changes"], 0)
        self.assertTrue(instructions.read_bytes().startswith(b"# Projeto\r\n\r\nUse a stack atual.\r\n"))
        self.assertFalse((self.target / ".codex/hooks.json").exists())

    def test_refuse_unmanaged_config_without_partial_writes(self):
        config = self.target / ".codex/config.toml"
        config.parent.mkdir()
        config.write_bytes(b'model = "custom"\n')
        _, error = self.run_cli(self.options, code=1)
        self.assertIn(".codex/config.toml", error)
        self.assertEqual(config.read_bytes(), b'model = "custom"\n')
        self.assertFalse((self.target / ".agents").exists())
        self.assertFalse((self.target / STATE).exists())

    def test_remove_only_an_owned_hook_when_switching_to_manual_activity(self):
        self.run_cli([*self.options, "--activity"])
        hook = self.target / ".codex/hooks.json"
        data = json.loads(hook.read_bytes())
        self.assertEqual(set(data["hooks"]), {"SessionStart", "PostToolUse"})
        self.run_cli(self.options)
        self.assertFalse(hook.exists())
        self.assertTrue((self.target / ".codex/config.toml").exists())

    def test_refuse_edited_managed_file(self):
        self.run_cli(self.options)
        config = self.target / ".codex/config.toml"
        previous = config.read_bytes()
        config.write_bytes(previous + b"# Local change\n")
        self.run_cli([*self.options, "--activity"], code=1)
        self.assertEqual(config.read_bytes(), previous + b"# Local change\n")
        self.assertFalse((self.target / ".codex/hooks.json").exists())

    def test_strict_complete_reports_missing_without_writes(self):
        stdout, _ = self.run_cli(["doctor", "--profile", "completo", "--strict"], code=1)
        self.assertIn("repowise", json.loads(stdout)["missing"])
        self.run_cli([*self.options, "--profile", "completo"], code=1)
        self.assertFalse((self.target / ".codex").exists())

    def test_reject_escaping_relative_paths(self):
        for value in ("../state.json", "C:/state.json", "/state.json", "one/../two", "one\\two"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                relative_path(value)

    def test_runtime_preparation_reuses_launchers_and_protects_customized_copies(self):
        command = ["prepare-runtime", str(self.target / "runtime")]
        self.assertEqual(json.loads(self.run_cli(command)[0])["launchers_created"], 10)
        self.assertEqual(json.loads(self.run_cli(command)[0])["launchers_created"], 0)
        launcher = self.target / "runtime/graphify/Invoke-Graphify.ps1"
        launcher.write_text("# local customization", encoding="utf-8")
        self.run_cli(command, code=1)
        self.assertEqual(launcher.read_text(encoding="utf-8"), "# local customization")

    def test_memory_roundtrip_uses_the_generated_database(self):
        self.run_cli(self.options)
        path = self.target / ".codex/config.toml"
        config = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["harness_local"]

        def session(name, arguments):
            def message(number, method, params):
                return json.dumps({"jsonrpc": "2.0", "id": number, "method": method, "params": params})

            requests = "\n".join([
                message(1, "initialize", {"protocolVersion": "2025-11-25"}),
                message(2, "tools/call", {"name": name, "arguments": arguments}), "",
            ])
            process = subprocess.run(
                [config["command"], *config["args"]], cwd=config["cwd"], input=requests,
                capture_output=True, text=True, encoding="utf-8", check=True, timeout=15,
            )
            reply = json.loads(process.stdout.splitlines()[-1])
            return json.loads(reply["result"]["content"][0]["text"])

        fixture = {"workspace": str(self.target), "key": "teste", "kind": "decision",
                   "note": "Nota sintética de teste.", "source": "fixture"}
        self.assertEqual(session("memory_save", fixture)["status"], "success")
        notes = session("memory_recall", {"workspace": str(self.target), "query": "teste"})["notes"]
        self.assertTrue(self.database.is_file())
        self.assertEqual([note["note"] for note in notes], [fixture["note"]])

    def test_activity_uses_the_generated_commands_and_the_same_database(self):
        self.run_cli([*self.options, "--activity"])
        hooks = json.loads((self.target / ".codex/hooks.json").read_bytes())["hooks"]

        def call(event, payload):
            command = hooks[event][0]["hooks"][0]["command"]
            result = subprocess.run(
                command if os.name == "nt" else shlex.split(command),
                cwd=self.target, text=True, encoding="utf-8", input=json.dumps({
                    "cwd": str(self.target), "hook_event_name": event, **payload,
                }),
                check=True, capture_output=True, timeout=15,
            )
            return result.stdout

        call("PostToolUse", {"session_id": str(uuid4()), "tool_name": "Bash",
                            "tool_input": {"command": "python -m unittest"},
                            "tool_response": {"exit_code": 0, "output": "test fixture"}})
        context = call("SessionStart", {"session_id": str(uuid4()), "source": "startup"})
        self.assertIn("unittest passou", context)
        self.assertNotIn("test fixture", context)
        self.assertTrue(self.database.is_file())
