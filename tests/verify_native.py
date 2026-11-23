"""Exercise a generated Windows profile with a native Codex app-server."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
from queue import Queue
import subprocess
import sys
import tempfile
from threading import Thread
from time import monotonic
import tomllib
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import ROOT, catalog, inspect, prepare


@contextmanager
def server(executable, workspace, state):
    test_codex_directory = state / "profile"
    test_codex_directory.mkdir()
    trust = "[projects." + json.dumps(os.path.normcase(str(workspace))) + ']\ntrust_level = "trusted"\n'
    (test_codex_directory / "config.toml").write_text(trust, encoding="utf-8")
    # CODEX_HOME is the native client's configuration API. This value exists only in the child.
    environment = {**os.environ, "CODEX_HOME": str(test_codex_directory)}
    arguments = [
        str(executable), "app-server", "--listen", "stdio://",
        "-c", "sqlite_home=" + json.dumps(state.as_posix()),
        "-c", "log_dir=" + json.dumps((state / "logs").as_posix()),
    ]
    with (state / "app-server.stderr").open("wb") as err, subprocess.Popen(
        arguments, cwd=workspace, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=err, text=True, encoding="utf-8",
    ) as child:
        replies = Queue()

        def read():
            for line in child.stdout:
                try:
                    replies.put(json.loads(line))
                except ValueError:
                    continue
            replies.put(None)

        Thread(target=read, daemon=True).start()
        sequence = 0

        def call(method, params=None, *, notification=False):
            nonlocal sequence
            request = {"method": method, "params": params or {}}
            if not notification:
                sequence += 1
                request["id"] = sequence
            child.stdin.write(json.dumps(request) + "\n")
            child.stdin.flush()
            if notification:
                return None
            deadline = monotonic() + 50
            while True:
                result = replies.get(timeout=max(0, deadline - monotonic()))
                if result is None:
                    raise RuntimeError(f"O app-server fechou durante {method}.")
                if result.get("id") == sequence:
                    if "error" in result:
                        raise RuntimeError(f"{method} falhou: {result['error']}")
                    return result["result"]

        try:
            call("initialize", {"clientInfo": {"name": "harness-local-native", "version": "1"},
                                "capabilities": {"experimentalApi": True}})
            call("initialized", notification=True)
            yield call
        finally:
            child.stdin.close()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)


def index_fixture(work, runtime_root):
    hooks = work / ".git/harness-empty-hooks"
    hooks.mkdir()
    git = ["git", "-c", f"core.hooksPath={hooks}", "-c", "user.name=Harness Fixture",
           "-c", "user.email=harness-fixture@example.invalid", "-c", "commit.gpgsign=false"]
    fixture_env = {**os.environ, "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
                   "NO_PROXY": "", "PYTHONIOENCODING": "utf-8"}
    subprocess.run([*git, "add", "sample.py"], cwd=work, check=True)
    subprocess.run([*git, "commit", "-qm", "Add synthetic example"], cwd=work, check=True)
    sample = work / "sample.py"
    sample.write_text(sample.read_text(encoding="utf-8") + "\nsize = 12\n", encoding="utf-8")
    subprocess.run([*git, "add", "sample.py"], cwd=work, check=True)
    subprocess.run([*git, "commit", "-qm", "Record example size"], cwd=work, check=True)
    call = subprocess.run([
        str(runtime_root / "runtimes/powershell/pwsh.exe"), "-NoProfile", "-NonInteractive",
        "-File", str(runtime_root / "repowise/Invoke-RepoWise.ps1"), "init", str(work),
        "--yes", "--no-prose", "--no-editor-setup", "--no-codex", "--no-save-key",
        "--provider", "mock", "--embedder", "mock",
    ], cwd=work, env=fixture_env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=55)
    if call.returncode:
        raise RuntimeError("Falha ao indexar o Git sintético no RepoWise. " + (call.stdout + call.stderr)[-2400:])


def create_fixture(parent, runtime_root, skills_root, repowise=False):
    canvas = Path(tempfile.mkdtemp(prefix="profile-", dir=parent)).resolve()
    work = canvas / "workspace"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
    (work / "sample.py").write_text("target(1)\ntarget(\n    2\n)\ncaption = 'target(3)'\n", encoding="utf-8")
    (work / "tests/e2e").mkdir(parents=True)
    (work / "tests/e2e/smoke.spec.cjs").write_text(
        "const { test, expect } = require('@playwright/test');\n"
        "test('shows the harness fixture', async ({page}) => {\n"
        "  await page.setContent('<h1>Harness</h1>');\n"
        "  await expect(page.getByRole('heading', {name: 'Harness'})).toBeVisible();\n"
        "});\n",
        encoding="utf-8",
    )
    if repowise:
        index_fixture(work, runtime_root)
    items, routes = catalog()
    options = argparse.Namespace(
        target=work, profile="completo", runtime_root=runtime_root, skills_root=skills_root,
        database=canvas / "memory.sqlite3", activity=True, repowise=repowise, allow_partial=False,
    )
    rendered = prepare(items, routes, inspect(items, options.profile, runtime_root, skills_root), options)
    return canvas, work, rendered


def probe(executable, runtime_root, skills_root, label, repowise=False):
    parent = ROOT / ".harness-local/native-checks"
    parent.mkdir(parents=True, exist_ok=True)
    canvas, work, rendered = create_fixture(parent, runtime_root, skills_root, repowise)
    state = canvas / "codex"
    state.mkdir()
    config = tomllib.loads((work / ".codex/config.toml").read_text(encoding="utf-8"))
    mcp = config["mcp_servers"]
    with server(executable, work, state) as call:
        catalog_result = call("skills/list", {"cwds": [str(work)], "forceReload": True})
        generated = {
            item["name"] for group in catalog_result["data"] for item in group["skills"]
            if item.get("enabled") and Path(item["path"]).is_relative_to(work / ".agents/skills")
        }
        if len(generated) != rendered["skills"]:
            raise RuntimeError(f"O catálogo nativo descobriu {len(generated)} skills do projeto: {sorted(generated)}")
        configuration = call("config/read", {"cwd": str(work), "includeLayers": True})
        current = configuration["config"]["mcp_servers"]
        for name, item in mcp.items():
            if current[name]["args"] != item["args"]:
                layers = [
                    {"name": entry.get("name"), "disabledReason": entry.get("disabledReason")}
                    for entry in configuration.get("layers") or []
                ]
                raise RuntimeError(
                    f"O cliente não usou a configuração de projeto de {name}. "
                    f"Argumentos esperados/efetivos: {item['args']!r} / {current[name]['args']!r}. "
                    f"Camadas: {layers!r}"
                )
        thread = call("thread/start", {"ephemeral": True, "cwd": str(work)})["thread"]["id"]
        tools = {}
        for name in mcp:
            statuses = call("mcpServerStatus/list", {
                "threadId": thread, "serverName": name, "detail": "toolsAndAuthOnly",
            })["data"]
            tools[name] = set(next((entry["tools"] for entry in statuses if entry["name"] == name), {}))
        expected = {
            "harness_local": {"memory_recall", "memory_save", "memory_forget"},
            "ast_grep": {"find_code", "find_code_by_rule", "dump_syntax_tree"},
            "playwright-test": {"test_list", "test_run", "planner_setup_page", "generator_write_test", "test_debug"},
        }
        if repowise:
            expected["repowise"] = {"get_change_risk", "get_dependency_path", "get_why"}
        for name, contract in expected.items():
            if not contract <= tools.get(name, set()):
                raise RuntimeError(f"Ferramentas MCP ausentes em {name}: {contract - tools.get(name, set())}")
        def invoke(name, tool, args):
            result = call("mcpServer/tool/call", {
                "threadId": thread, "server": name, "tool": tool, "arguments": args,
            })
            content = "\n".join(part.get("text", "") for part in result["content"])
            if result.get("isError"):
                raise RuntimeError(f"{tool} falhou: {content}")
            return content

        key = "native-smoke-" + uuid4().hex[:10]
        note = "Memória sintética do perfil gerado."
        invoke("harness_local", "memory_save",
               {"key": key, "kind": "decision", "note": note, "source": "native fixture", "workspace": str(work)})
        recalled = json.loads(invoke("harness_local", "memory_recall", {"query": key, "workspace": str(work)}))
        assert [entry["note"] for entry in recalled["notes"]] == [note]
        assert (canvas / "memory.sqlite3").is_file()
        found = invoke("ast_grep", "find_code",
                       {"project_folder": str(work), "language": "python", "pattern": "target($ARG)", "max_results": 9})
        assert "Found 2 matches" in found and "target(3)" not in found, found
        discovered = invoke("playwright-test", "test_list", {})
        assert "shows the harness fixture" in discovered, discovered
        played = invoke("playwright-test", "test_run", {"locations": ["tests/e2e/smoke.spec.cjs"]})
        if "1 passed" not in played:
            raise RuntimeError(f"O teste do navegador não passou: {played}")
        if repowise:
            risk = invoke("repowise", "get_change_risk", {
                "include_paths": ["sample.py"], "revspec": "HEAD", "include": ["findings", "diagnostics"],
            })
            assert "health_delta" in risk and "sample.py" in risk, risk
    return {"client": label, "skills": len(generated), "agents": rendered["agents"],
            "mcp_tools": {name: len(available) for name, available in tools.items()},
            "memory_roundtrip": True, "ast_matches": 2, "playwright_passed": True,
            **({"repowise_risk": True} if repowise else {})}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--skills-root", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--repowise", action="store_true")
    options = parser.parse_args()
    print(json.dumps(probe(options.codex, options.runtime_root.resolve(), options.skills_root.resolve(),
                           options.label, options.repowise)))
