import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from activity_hooks import KEY_PREFIX, SOURCE, handle, record_activity, session_context, verification_status
from server import open_database, recall, save, workspace_key


class MemoryTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        root = Path(fixture.name)
        self.project = root / "project"
        self.project.mkdir()
        self.other = root / "other"
        self.other.mkdir()
        self.db_path = root / "memory.sqlite3"
        self.workspace = workspace_key(str(self.project))

    def test_recall_prefers_full_query_and_keeps_partial_fallback(self):
        with closing(open_database(self.db_path)) as db:
            save(db, self.workspace, "monitor-paleta", "decision", "monitor paleta", "fixture")
            save(db, self.workspace, "paginacao", "decision", "monitor paginação", "fixture")
            save(db, "", "tema-editor", "preference", "tema do editor", "fixture")
            other = workspace_key(str(self.other))
            save(db, other, "paginacao", "decision", "monitor paginação de outra raiz", "fixture")
            exact = recall(db, self.workspace, "monitor paginacao")["notes"]
            self.assertEqual([note["key"] for note in exact], ["paginacao"])
            partial = recall(db, self.workspace, "tema inexistente")["notes"]
            self.assertEqual([note["key"] for note in partial], ["tema-editor"])

    def test_exact_key_prefers_project_match(self):
        with closing(open_database(self.db_path)) as db:
            save(db, "", "paginacao", "decision", "monitor paginação pessoal", "fixture")
            save(db, self.workspace, "paginacao", "decision", "total de páginas", "fixture")
            results = recall(db, self.workspace, "paginacao")["notes"]
            self.assertEqual([note["scope"] for note in results], ["project", "user"])

    def test_activity_preserves_latest_check_and_filters_file_paths(self):
        session_id = str(uuid4())
        common = {"hook_event_name": "PostToolUse", "session_id": session_id, "cwd": str(self.project)}
        patch = dict(common, tool_name="apply_patch",
                     tool_input={"command": "*** Update File: src/main.py\n*** Update File: .env"},
                     tool_response="Exit code: 0\nWall time: 0.2 seconds\nOutput:\n"
                                   "Success. Updated the following files:\nM src/main.py\nM .env")
        handle(self.db_path, patch)
        verification = dict(common, tool_name="Bash", tool_input={"command": "python -m unittest"})
        for exit_code in (1, 0):
            handle(self.db_path, dict(verification, tool_response={
                "exit_code": exit_code, "output": "full tool output stays out",
            }))
        with closing(open_database(self.db_path, read_only=True)) as db:
            output = recall(db, self.workspace)["notes"][0]["note"]
            self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
        self.assertIn("src/main.py", output)
        self.assertIn("unittest passou ·", output)
        for private in (".env", "full tool output", "unittest falhou"):
            self.assertNotIn(private, output)
        start = {"hook_event_name": "SessionStart", "source": "startup",
                 "cwd": str(self.project), "session_id": session_id}
        self.assertIsNone(handle(self.db_path, start))
        other_start = dict(start, session_id=str(uuid4()))
        self.assertIn("unittest passou", str(handle(self.db_path, other_start)))
        self.assertIsNone(handle(self.db_path, dict(other_start, cwd=str(self.other))))

    def test_legacy_note_and_late_event_do_not_erase_newer_outcome(self):
        key = KEY_PREFIX + uuid4().hex
        with closing(open_database(self.db_path)) as db:
            save(db, self.workspace, key, "handoff", "- pytest falhou\n- pytest passou", SOURCE)
            row = db.execute("SELECT updated_at FROM notes").fetchone()
        legacy_time = datetime.fromisoformat(row["updated_at"])
        earlier = legacy_time.replace(year=legacy_time.year - 1)
        record_activity(self.db_path, self.workspace, key, (), (("pytest", "falhou", earlier),))
        context = session_context(self.db_path, self.workspace, KEY_PREFIX + uuid4().hex)
        self.assertIn("pytest passou", str(context))
        self.assertNotIn("pytest falhou", str(context))

    def test_native_bash_result_can_be_plain_stdout(self):
        unittest_output = ".\r\n" + "-" * 70 + "\r\nRan 1 test in 0.000s\r\n\r\nOK\r\n"
        self.assertEqual(verification_status("unittest", unittest_output), "passou")
        failed = unittest_output.replace("OK", "FAILED (failures=1)")
        self.assertEqual(verification_status("unittest", failed), "falhou")
        self.assertIsNone(verification_status("npm test", "OK"))
        self.assertEqual(verification_status("unittest", {"exit_code": 1, "output": unittest_output}), "falhou")
        self.assertEqual(verification_status("pytest", "2 passed in 0.44s"), "passou")
        self.assertEqual(verification_status("pytest", "=== 1 error, 2 passed in 0.55s ==="), "falhou")
        playwright = "Running 2 tests\n  1 failed\n    tests/bug.spec.ts:3:2 › saves\n  1 passed (1.6s)"
        self.assertEqual(verification_status("Playwright", playwright), "falhou")

    def test_context_uses_check_time_across_chat_notes(self):
        old_key, new_key = (KEY_PREFIX + uuid4().hex for _ in range(2))
        before = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        after = datetime.fromisoformat("2026-01-02T00:00:00+00:00")
        record_activity(self.db_path, self.workspace, new_key, (), (("pytest", "passou", after),))
        record_activity(self.db_path, self.workspace, old_key, ("edited.py",), (("pytest", "falhou", before),))
        context = session_context(self.db_path, self.workspace, KEY_PREFIX + uuid4().hex)
        self.assertIn("pytest passou", str(context))
        self.assertIn("edited.py", str(context))
        self.assertNotIn("pytest falhou", str(context))


if __name__ == "__main__":
    unittest.main()
