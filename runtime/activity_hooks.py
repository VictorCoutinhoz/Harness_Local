"""Keep short, project-scoped activity notes from documented Codex hook events."""

import argparse
import json
import ntpath
import re
import shlex
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID


APP_DIR = Path(__file__).resolve().parent
# Python's isolated mode excludes the script directory. Import only our neighbor.
sys.path.insert(0, str(APP_DIR))
from server import SECRET, open_database, save, workspace_key


SOURCE = "Hooks locais de atividade do Codex"
KEY_PREFIX = "atividade-codex-"
MAX_EVENT_BYTES = 2 * 1024 * 1024
PATCH_PATH = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.MULTILINE)
SAFE_PATH = re.compile(r"[\w./ -]{1,110}", re.UNICODE)
PRIVATE_PATH = re.compile(
    r"(?:^|[ ./_-])(?:secrets?|credentials?|passwords?|tokens?|id_rsa|id_ed25519)(?:[ ./_-]|$)",
    re.IGNORECASE,
)
PRIVATE_EXTENSIONS = {".key", ".pem", ".pfx", ".p12", ".kdbx", ".sqlite", ".sqlite3", ".db"}
EXIT_HEADER = re.compile(
    r"\A(?:(?:Chunk ID: [^\r\n]+\r?\n)?(?:Wall time: [^\r\n]+\r?\n)?"
    r"Process exited with code:?[ \t]*(-?\d+)\b|"
    r"Exit code:[ \t]*(-?\d+)\r?\nWall time: [^\r\n]+\r?\nOutput:\r?\n)"
)
ANSI_STYLE = re.compile(r"\x1b\[[0-9;]*m")
UNITTEST_SUMMARY = re.compile(
    r"(?m)^-{30,}\r?\nRan \d+ tests? in [\d.]+s\r?\n\r?\n"
    r"(OK|FAILED)(?: \([^\r\n]+\))?[ \t]*\r?\n?\Z"
)
PYTEST_SUMMARY = re.compile(
    r"(?m)^=*[ \t]*(\d+ \w+(?:, \d+ \w+)*) in [\d.]+s(?: \([^\r\n]+\))?[ \t]*=*\r?$"
)
PLAYWRIGHT_SUMMARY = re.compile(r"(?m)^[ \t]+[1-9]\d* (passed|failed)(?: \([^\r\n]+\))?[ \t]*\r?$")
CHECK_COMMANDS = {
    ("pytest",): "pytest",
    ("python", "-m", "pytest"): "pytest",
    ("python", "-m", "unittest"): "unittest",
    ("uv", "run", "pytest"): "pytest",
    ("cargo", "test"): "cargo test",
    ("go", "test"): "go test",
    ("dotnet", "test"): "dotnet test",
    ("npm", "test"): "npm test",
    ("pnpm", "test"): "pnpm test",
    ("yarn", "test"): "yarn test",
    ("bun", "test"): "bun test",
    ("playwright", "test"): "Playwright",
    ("invoke-playwright.ps1", "test"): "Playwright",
    ("npx", "playwright", "test"): "Playwright",
    ("pnpm", "exec", "playwright", "test"): "Playwright",
    ("npm", "exec", "playwright", "test"): "Playwright",
}
for runner in ("npm", "pnpm", "yarn", "bun"):
    for task in ("test", "lint", "typecheck", "build"):
        CHECK_COMMANDS[(runner, "run", task)] = f"{runner} run {task}"


def project_scope(cwd):
    root = Path(cwd).resolve()
    if not root.is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute",
             "--show-toplevel", "--git-common-dir"],
            capture_output=True, text=True, encoding="utf-8", timeout=1.5,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode == 0:
            worktree, common_dir = result.stdout.splitlines()
            return Path(worktree).resolve(), workspace_key(common_dir)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return root, workspace_key(str(root))


def safe_file(path):
    return (SAFE_PATH.fullmatch(path) and not SECRET.search(path)
            and not PRIVATE_PATH.search(path)
            and not any(part.startswith(".") for part in path.split("/"))
            and Path(path).suffix.casefold() not in PRIVATE_EXTENSIONS)


def relative_file(path, cwd, root):
    try:
        relative = (cwd / path.strip()).resolve().relative_to(root).as_posix()
    except (OSError, ValueError, RuntimeError):
        return None
    return relative if safe_file(relative) else None


def tool_text(response):
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        output = response.get("output", response.get("text"))
        if isinstance(output, str):
            return output
        response = response.get("content")
    if isinstance(response, list) and len(response) == 1:
        item = response[0]
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return item["text"]
    return ""


def command_exit(response):
    if isinstance(response, dict) and type(response.get("exit_code")) is int:
        return response["exit_code"]
    if match := EXIT_HEADER.match(tool_text(response)):
        return int(match.group(1) or match.group(2))
    return None


def verification_status(label, response):
    code = command_exit(response)
    if code is not None:
        return "passou" if code == 0 else "falhou"
    # Native Bash hooks can supply just the runner's terminal output.
    output = ANSI_STYLE.sub("", tool_text(response)[-8192:]).rstrip()
    if label == "unittest" and (match := UNITTEST_SUMMARY.search(output)):
        return "passou" if match.group(1) == "OK" else "falhou"
    if label == "pytest":
        matches = PYTEST_SUMMARY.findall(output)
        if matches:
            outcomes = set(re.findall(r"\d+ (\w+)", matches[-1]))
            if outcomes & {"failed", "error", "errors"}:
                return "falhou"
            if outcomes & {"passed", "skipped", "xfailed", "xpassed"}:
                return "passou"
    if label == "Playwright":
        outcomes = PLAYWRIGHT_SUMMARY.findall(output)
        if "failed" in outcomes:
            return "falhou"
        if "passed" in outcomes:
            return "passou"
    return None


def check_name(command):
    command = command.strip().removeprefix("& ").strip()
    if not command or re.search(r"[\r\n;&|<>\x60$()]", command):
        return None
    try:
        argv = shlex.split(command, posix=False)
    except ValueError:
        return None
    executable = ntpath.basename(argv[0].strip("'\"")).casefold()
    if executable.endswith((".exe", ".cmd", ".bat")):
        executable = executable[:-4]
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable):
        executable = "python"
    argv[0] = executable
    for length in (4, 3, 2, 1):
        if label := CHECK_COMMANDS.get(tuple(argv[:length])):
            return label
    return None


def event_observation(event):
    args = event.get("tool_input")
    if not isinstance(args, dict):
        return (), ()
    command = args.get("command", args.get("cmd"))
    if not isinstance(command, str):
        return (), ()
    response = event.get("tool_response")
    if event["tool_name"] == "apply_patch":
        result = tool_text(response)
        if result.startswith("Success. Updated the following files:") or (
            command_exit(response) == 0
            and "\nSuccess. Updated the following files:" in result
        ):
            return PATCH_PATH.findall(command), ()
        return (), ()
    if (label := check_name(command)) and (status := verification_status(label, response)):
        return (), ((label, status),)
    return (), ()


def note_entries(note, updated_at):
    """Parse the fixed output generated here. Other text never enters hook context."""
    files = []
    checks = []
    for line in note.splitlines():
        if not line.startswith("- "):
            continue
        value = line[2:]
        if value.startswith("\x60") and value.endswith("\x60") and safe_file(value[1:-1]):
            files.append(value[1:-1])
            continue
        check, time_separator, timestamp = value.partition(" · ")
        label, separator, status = check.rpartition(" ")
        if (separator and label in CHECK_COMMANDS.values() and status in {"passou", "falhou"}):
            try:
                observed = datetime.fromisoformat(timestamp if time_separator else updated_at)
            except ValueError:
                continue
            if observed.tzinfo is not None:
                checks.append((label, status, observed))
    return files, checks


def activity_note(files, checks):
    sections = []
    if files:
        sections.append("Arquivos alterados via Codex\n" + "\n".join(
            f"- \x60{path}\x60" for path in files
        ))
    if checks:
        sections.append("Verificações observadas\n" + "\n".join(
            f"- {label} {status} · {observed.isoformat()}" for label, status, observed in checks
        ))
    return "\n\n".join(sections)


def append_unique(previous, incoming, limit):
    recent = [item for item in previous if item not in incoming]
    return list(dict.fromkeys([*recent, *incoming]))[-limit:]


def latest_checks(checks):
    latest = {}
    for check in sorted(checks, key=lambda item: item[2]):
        latest.pop(check[0], None)
        latest[check[0]] = check
    return latest


def record_activity(db_path, workspace, key, files, checks):
    with closing(open_database(db_path)) as db:
        for _ in range(3):
            previous = db.execute(
                "SELECT note, revision, source, updated_at FROM notes WHERE workspace = ? AND key = ?",
                (workspace, key),
            ).fetchone()
            if previous and previous["source"] != SOURCE:
                return
            old_files, old_checks = (
                note_entries(previous["note"], previous["updated_at"]) if previous else ([], [])
            )
            recent_checks = latest_checks([*old_checks, *checks])
            note = activity_note(
                append_unique(old_files, files, 6), list(recent_checks.values())[-6:]
            )
            result = save(db, workspace, key, "handoff", note, SOURCE,
                          expected_revision=previous["revision"] if previous else None)
            if result["status"] == "success":
                return
    raise ValueError("Conflito ao atualizar atividade")


def session_context(db_path, workspace, key):
    if not db_path.is_file():
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with closing(open_database(db_path, read_only=True)) as db:
        rows = db.execute(
            """SELECT note, updated_at FROM notes
               WHERE workspace = ? AND source = ? AND key LIKE ? AND key <> ?
                 AND updated_at >= ?
               ORDER BY updated_at DESC, id DESC LIMIT 2""",
            (workspace, SOURCE, KEY_PREFIX + "%", key, cutoff),
        ).fetchall()
    entries = [(row["updated_at"], *note_entries(row["note"], row["updated_at"])) for row in rows]
    current_checks = latest_checks(check for _, _, checks in entries for check in checks)
    sections = []
    for updated_at, files, checks in entries:
        recent = []
        for check in checks:
            if check == current_checks.get(check[0]):
                recent.append(current_checks.pop(check[0]))
        note = activity_note(files, recent)
        if note:
            date = datetime.fromisoformat(updated_at).date()
            sections.append(f"### {date}\n{note}")
    if sections:
        context = "\n\n".join([
            "Atividade recente de outros chats no mesmo escopo. Use como referência "
            "quando for pertinente ao pedido e confirme o estado atual do projeto.",
            *sections,
        ])
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    return None


def handle(db_path, event):
    if not isinstance(event, dict):
        return None
    event_name = event.get("hook_event_name")
    if event_name not in {"SessionStart", "PostToolUse"}:
        return None
    session_id, cwd = event.get("session_id"), event.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str) or not Path(cwd).is_absolute():
        return None
    key = KEY_PREFIX + UUID(session_id).hex
    if event_name == "SessionStart":
        if event.get("source") not in {"startup", "resume", "fork"}:
            return None
        scope = project_scope(cwd)
        return session_context(db_path, scope[1], key) if scope else None
    if event.get("tool_name") not in {"Bash", "apply_patch", "exec_command", "shell_command", "PowerShell"}:
        return None
    observed = datetime.now(timezone.utc)
    paths, check_results = event_observation(event)
    if not paths and not check_results:
        return None
    workdir = event["tool_input"].get("workdir")
    if isinstance(workdir, str) and Path(workdir).is_absolute():
        cwd = workdir
    scope = project_scope(cwd)
    if scope is None:
        return None
    root, workspace = scope
    files = tuple(path for value in paths if (path := relative_file(value, Path(cwd), root)))
    checks = tuple((label, status, observed) for label, status in check_results)
    if files or checks:
        record_activity(db_path, workspace, key, files, checks)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=APP_DIR.parent / ".harness-local/state/memoria.sqlite3")
    options = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        if not raw or len(raw) > MAX_EVENT_BYTES:
            return 0
        result = handle(options.db, json.loads(raw))
        if result:
            sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8") + b"\n")
    except (OSError, ValueError, sqlite3.Error):
        print("harness-local: houve uma falha ao processar a atividade local", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
