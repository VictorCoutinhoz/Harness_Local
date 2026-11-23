"""Prepare project-scoped Codex profiles from the Harness_Local catalog."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
STATE = ".harness-local/installation.json"
MANAGED = "Harness_Local"
AUTHORIZED_SOURCE_TYPES = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".py", ".js", ".mjs", ".cjs",
    ".sh", ".ps1", ".svg", ".csv", ".css", ".html", ".png", ".jpg", ".webp",
}
SKIP_SOURCE = {".git", "__pycache__", ".venv", "node_modules", ".env", ".DS_Store"}


def relative_path(value):
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise ValueError(f"Caminho relativo inválido {value!r}.")
    parsed = PurePosixPath(value)
    if not parsed.parts or parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != value:
        raise ValueError(f"Caminho relativo inválido {value!r}.")
    return value


def safe_path(root, relative):
    path = root / relative_path(relative)
    if path.resolve() != path:
        raise ValueError(f"Caminho redirecionado no perfil {relative}.")
    return path


def catalog():
    data = json.loads((ROOT / "catalog.json").read_bytes())
    if data["schema_version"] != 1:
        raise ValueError("Versão de catálogo incompatível.")
    items = {item["id"]: item for item in data["components"]}
    routes = {route["id"]: route for route in data["routes"]}
    if len(items) != len(data["components"]) or len(routes) != len(data["routes"]):
        raise ValueError("ID repetido no catálogo.")

    def check_dependencies(item, pending):
        name = item["id"]
        if name in pending:
            raise ValueError(f"Dependência circular em {name}.")
        for dependency in item.get("requires", ()):
            check_dependencies(items[dependency], pending | {name})

    for name, item in items.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
            raise ValueError(f"ID inválido {name!r}.")
        for path in item.get("paths", ()):
            relative_path(path)
        check_dependencies(item, set())
    for route in routes.values():
        if not set(route["uses"]) <= items.keys():
            raise ValueError(f"Dependência ausente na rota {route['id']}.")
    return items, routes


def inspect(items, profile, runtime_root=None, skills_root=None):
    status = {}

    def assess(name):
        if name in status:
            return status[name]
        item = items[name]
        kind, distribution = item["kind"], item["distribution"]
        detail = "disponível"
        if distribution == "host":
            detail = "fornecido pelo cliente"
        elif profile == "base" and distribution != "bundled":
            detail = "perfil completo"
        elif kind == "skill":
            base = ROOT / "skills" if distribution == "bundled" else skills_root
            if base is None or not (base / name / "SKILL.md").is_file():
                detail = "pasta da skill ausente"
        elif kind == "agent" and not (ROOT / "agents" / f"{name}.toml").is_file():
            detail = "perfil do agente ausente"
        elif kind == "runtime":
            base = ROOT if distribution == "bundled" else runtime_root
            missing = [path for path in item["paths"] if base is None or not (base / path).exists()]
            if missing:
                detail = "faltam " + ", ".join(missing)
        if detail == "disponível":
            lacking = [dep for dep in item.get("requires", ()) if assess(dep) != "disponível"]
            if lacking:
                detail = "requer " + ", ".join(lacking)
        status[name] = detail
        return detail

    return {name: assess(name) for name in items}


def needed(items, profile, status):
    required = {
        name for name, item in items.items()
        if (profile == "completo" and item["distribution"] != "host")
        or (item["distribution"] == "bundled" and item["kind"] in {"skill", "mcp"})
    }
    return {name: status[name] for name in sorted(required) if status[name] != "disponível"}


def route_markdown(routes, status):
    text = ["# Rotas do Harness_Local", ""]
    for route in routes.values():
        available = [name for name in route["uses"] if status[name] in {"disponível", "fornecido pelo cliente"}]
        inactive = [name for name in route["uses"] if name not in available]
        text.extend([f"## {route['title']}", "", route["workflow"], ""])
        if available:
            text.extend(["Consulte " + ", ".join(f"`{name}`" for name in available) + ".", ""])
        if inactive:
            text.extend(["Neste perfil, use a alternativa a seguir quando precisar de "
                         + ", ".join(f"`{name}`" for name in inactive) + ".", "", route["fallback"], ""])
    return "\n".join(text).encode("utf-8")


def toml_string(value):
    if isinstance(value, Path):
        value = value.as_posix()
    return json.dumps(value, ensure_ascii=False)


def memory_args(database):
    return [
        Path(sys.executable), "-I", "-B", "-X", "utf8", ROOT / "runtime/server.py", "--db", database,
    ]


def profile_config(status, target, database, runtime_root, repowise):
    entries = {"harness_local": (memory_args(database), target, {})}
    if status["playwright-test"] == "disponível":
        entries["playwright-test"] = (
            [runtime_root / "runtimes/powershell/pwsh.exe", "-NoProfile", "-NonInteractive",
             "-File", ROOT / "runtime/windows/playwright/Invoke-Playwright.ps1", "run-test-mcp-server", "--headless"],
            target, {"HARNESS_LOCAL_PLAYWRIGHT_ROOT": (runtime_root / "playwright").as_posix()},
        )
    if status["ast_grep"] == "disponível":
        ast = runtime_root / "ast-grep"
        entries["ast_grep"] = (
            [ast / "venv/Scripts/python.exe", "-I", "-B", "-X", "utf8",
             ast / "upstream/main.py", "--transport", "stdio"],
            ast / "upstream", {"AST_GREP_PATH": '"' + (ast / "bin/ast-grep.exe").as_posix() + '"',
                               "AST_GREP_CONFIG": ""},
        )
    if repowise:
        if status["repowise"] != "disponível" or not (target / ".repowise/config.yaml").is_file():
            raise ValueError("Prepare o índice do RepoWise neste repositório antes de ativar seu MCP.")
        entries["repowise"] = (
            [runtime_root / "runtimes/powershell/pwsh.exe", "-NoProfile", "-NonInteractive",
             "-File", runtime_root / "repowise/Invoke-RepoWise.ps1", "mcp", target, "--transport", "stdio",
             "--no-workspace", "--tools", "get_change_risk,get_dependency_path,get_why"],
            target, {},
        )
    config = ["# Gerado pelo Harness_Local para este projeto.", ""]
    for name, (args, cwd, env) in entries.items():
        config.extend([
            f"[mcp_servers.{name}]",
            "command = " + toml_string(args[0]),
            "args = [" + ", ".join(map(toml_string, args[1:])) + "]",
            "cwd = " + toml_string(cwd),
        ])
        if env:
            config.append("env = { " + ", ".join(f"{key} = {toml_string(value)}" for key, value in env.items()) + " }")
        config.append("")
    result = "\n".join(config)
    if set(tomllib.loads(result)["mcp_servers"]) != set(entries):
        raise ValueError("Falha ao validar a configuração MCP.")
    return result.encode("utf-8")


def hook_config(database):
    args = [
        str(Path(sys.executable)), "-I", "-B", "-X", "utf8", str(ROOT / "runtime/activity_hooks.py"),
        "--db", str(database),
    ]
    shell_metacharacters = set('"\r\n\0%!`$&|<>^()')
    if any(shell_metacharacters.intersection(arg) for arg in args):
        raise ValueError("Use um caminho simples para o executável e o banco dos hooks.")
    if os.name == "nt":
        command = subprocess.list2cmdline(args)
    else:
        import shlex
        command = shlex.join(args)
    hook = {"type": "command", "command": command, "timeout": 10}
    hooks = {
        "SessionStart": [{"matcher": "^(startup|resume|fork)$", "hooks": [hook]}],
        "PostToolUse": [{"matcher": "^(apply_patch|Bash|exec_command|shell_command|PowerShell)$", "hooks": [hook]}],
    }
    return (json.dumps({"hooks": hooks}, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def files_for_skill(source, runtime_root, skills_root, target):
    for current, folders, filenames in os.walk(source, followlinks=False):
        directory = Path(current)
        folders[:] = [name for name in sorted(folders) if name not in SKIP_SOURCE and
                      (directory / name).resolve() == directory / name]
        for name in sorted(filenames):
            path = directory / name
            if name in SKIP_SOURCE or path.resolve() != path:
                continue
            if path.suffix.lower() not in AUTHORIZED_SOURCE_TYPES and name not in {"LICENSE", "NOTICE", ".skill_id"}:
                continue
            if path.stat().st_size > 3 * 1024 * 1024:
                raise ValueError(f"Arquivo grande demais na skill {source.name}/{name}.")
            payload = path.read_bytes()
            if (skills_root is not None and source.parent == skills_root and
                    path.suffix.lower() in {".md", ".py", ".json", ".yaml", ".yml", ".ps1"}):
                text = payload.decode("utf-8")
                previous = skills_root.as_posix()
                relative_home = (target / ".agents/skills").as_posix()
                for spelling in {previous, str(skills_root)}:
                    text = re.sub(re.escape(spelling) + r"(?=[/\\])", lambda _: relative_home, text, flags=re.I)
                if runtime_root is not None:
                    text = re.sub(
                        r"[A-Za-z]:[/\\][^\r\n`'\"]*?[/\\]Applications[/\\]HarnessLocal(?=[/\\])",
                        lambda _: runtime_root.as_posix(), text,
                    )
                    if source.name == "find-skills" and name == "SKILL.md":
                        legacy_launcher = runtime_root.as_posix() + "/Find-Skills.ps1"
                        text = text.replace(
                            "& '" + legacy_launcher + "'",
                            f"& '{Path(sys.executable).as_posix()}' -I -B -X utf8 "
                            f"'{(ROOT / 'runtime/find_skills.py').as_posix()}'",
                        )
                payload = text.encode("utf-8")
            yield path.relative_to(source).as_posix(), payload


def local_reference(database, runtime_root):
    fallback = [str(arg) for arg in [*memory_args(database), "--call", "memory_recall"]]
    sample = '{"query":"paginação","limit":5}'
    if os.name == "nt":
        quote = lambda value: "'" + value.replace("'", "''") + "'"
        language = "powershell"
        invocation = quote(sample) + " | & " + " ".join(map(quote, fallback))
    else:
        import shlex
        language = "sh"
        invocation = "printf '%s\\n' " + shlex.quote(sample) + " | " + shlex.join(fallback)
    lines = [
        "# Comandos deste perfil", "",
        "Consulte a memória pelo MCP `harness_local`. Para consulta direta ao mesmo banco, envie um objeto JSON pela entrada padrão.", "",
        "```" + language, invocation,
        "```", "",
        "Regra CSS do ast-grep em `" + (ROOT / "runtime/css-tokens.yaml").as_posix() + "`.", "",
    ]
    if runtime_root is not None:
        lines.extend(["Use os launchers do perfil em `" + runtime_root.as_posix() + "`.",
                      "Para RepoWise, abra o repositório Git de interesse e use seu launcher no modo de projeto.", ""])
    return "\n".join(lines).encode("utf-8")


def managed_block(existing, label, lines):
    prefix = "<!-- Harness_Local " if label == "instructions" else "# Harness_Local "
    suffix = " -->" if label == "instructions" else ""
    start, end = prefix + label + " begin" + suffix, prefix + label + " end" + suffix
    newline = "\r\n" if "\r\n" in existing else "\n"
    block = newline.join([start, *lines, end]) + newline
    if start in existing or end in existing:
        if existing.count(start) != 1 or existing.count(end) != 1 or existing.index(start) > existing.index(end):
            raise ValueError(f"Bloco gerenciado inválido em {label}.")
        before, separator, rest = existing.partition(start)
        _, separator, after = rest.partition(end)
        return before + block + after.removeprefix(newline)
    return existing + (newline * (1 if existing.endswith(newline) else 2) if existing else "") + block


def digest(content):
    return hashlib.sha256(content).hexdigest()


def write_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".harness-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
        except BaseException:
            stream.close()
            temporary.unlink()
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_profile(target, next_files, profile, status):
    state = safe_path(target, STATE)
    previous_state = state.read_bytes() if state.is_file() else None
    if previous_state is not None:
        old = json.loads(previous_state)
        if old.get("managed_by") != MANAGED or old.get("schema_version") != 1:
            raise ValueError("Registro de instalação desconhecido.")
        owned = old["files"]
    else:
        owned = {}

    # Only files inside the reserved project skill/agent/config locations are owned.
    for name in owned:
        if not (name in {".codex/config.toml", ".codex/hooks.json"} or
                name.startswith((".agents/skills/", ".codex/agents/"))):
            raise ValueError(f"Caminho fora do perfil gerenciado {name}.")
    snapshot = {}
    for name in sorted(set(owned) | next_files.keys()):
        path = safe_path(target, name)
        present = path.read_bytes() if path.is_file() else None
        snapshot[path] = present
        if present is not None and present != next_files.get(name) and digest(present) != owned.get(name):
            raise ValueError(f"Arquivo existente ou editado em {name}. Use outro destino ou preserve a edição.")

    contents = {safe_path(target, name): payload for name, payload in next_files.items()}
    for file, label, lines in [
        ("AGENTS.md", "instructions", [
            "Use `harness-local` para retomar contexto e escolher a rota da tarefa.",
            "As rotas deste projeto ficam em `.agents/skills/harness-local/references/routes.md`.",
            "Use `revisar-escrita` para redigir e revisar materiais voltados ao leitor.",
        ]),
        (".gitignore", "workspace", [
            "/.harness-local/",
            "/.repowise/",
            "/.codex/config.toml",
            "/.codex/hooks.json",
            *("/.agents/skills/" + name + "/" for name in sorted({
                path.split("/")[2] for path in next_files if path.startswith(".agents/skills/")
            })),
            *("/" + path for path in sorted(next_files) if path.startswith(".codex/agents/")),
        ]),
    ]:
        path = safe_path(target, file)
        old = path.read_bytes() if path.is_file() else None
        snapshot[path] = old
        encoded = managed_block(old.decode("utf-8") if old is not None else "", label, lines).encode("utf-8")
        contents[path] = encoded

    manifest = {"managed_by": MANAGED, "schema_version": 1, "profile": profile,
                "files": {name: digest(content) for name, content in sorted(next_files.items())},
                "available": sorted(name for name, value in status.items() if value == "disponível")}
    snapshot[state] = previous_state
    contents[state] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    changed = []
    try:
        for path in (*[p for p in snapshot if p != state], state):
            old, new = snapshot[path], contents.get(path)
            if old == new:
                continue
            safe_path(target, path.relative_to(target).as_posix())
            if (path.read_bytes() if path.is_file() else None) != old:
                raise ValueError(f"Arquivo mudou durante a preparação {path.name}.")
            if new is None:
                path.unlink()
            else:
                write_bytes(path, new)
            changed.append(path)
    except BaseException:
        for path in reversed(changed):
            old = snapshot[path]
            if old is None:
                path.unlink(missing_ok=True)
            else:
                write_bytes(path, old)
        raise
    return len(changed)


def prepare(items, routes, status, options):
    missing = needed(items, options.profile, status)
    if options.profile == "completo" and missing and not options.allow_partial:
        details = ", ".join(f"{name} ({reason})" for name, reason in missing.items())
        raise ValueError("O perfil completo requer " + details + ". Use doctor para conferir o inventário.")
    if needed(items, "base", status):
        raise ValueError("Há arquivos do núcleo ausentes. Confira a cópia do repositório.")
    target = options.target.resolve()
    database = options.database.resolve() if options.database else ROOT / ".harness-local/state/memoria.sqlite3"
    files = {".codex/config.toml": profile_config(status, target, database, options.runtime_root, options.repowise)}
    if options.activity:
        files[".codex/hooks.json"] = hook_config(database)
    for name, item in items.items():
        if status[name] != "disponível":
            continue
        if item["kind"] == "skill":
            base = ROOT / "skills" if item["distribution"] == "bundled" else options.skills_root
            source = safe_path(base, name)
            for path, content in files_for_skill(source, options.runtime_root, options.skills_root, target):
                files[f".agents/skills/{name}/{path}"] = content
        elif item["kind"] == "agent":
            path = f"agents/{name}.toml"
            files[f".codex/{path}"] = (ROOT / path).read_bytes()
    files[".agents/skills/harness-local/references/routes.md"] = route_markdown(routes, status)
    files[".agents/skills/harness-local/references/commands.md"] = local_reference(database, options.runtime_root)
    changes = apply_profile(target, files, options.profile, status)
    return {"profile": options.profile, "target": str(target), "database": str(database),
            "skills": sum(item["kind"] == "skill" and status[name] == "disponível" for name, item in items.items()),
            "agents": sum(item["kind"] == "agent" and status[name] == "disponível" for name, item in items.items()),
            "mcp": list(tomllib.loads(files[".codex/config.toml"].decode("utf-8"))["mcp_servers"]),
            "hooks": options.activity, "changes": changes, "missing": missing}


def prepare_runtime(target):
    target = target.resolve()
    adapters = ROOT / "runtime/windows"
    pending = {}
    for name, content in files_for_skill(adapters, None, None, target):
        destination = safe_path(target, name)
        if destination.exists():
            if not destination.is_file() or destination.read_bytes() != content:
                raise ValueError(f"Launcher existente com conteúdo diferente em {name}.")
        else:
            pending[destination] = content
    created = []
    try:
        for path, content in pending.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                created.append(path)
                stream.write(content)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return {"runtime_root": str(target), "launchers_created": len(created)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--profile", choices=["base", "completo"], default="base")
    shared.add_argument("--runtime-root", type=Path)
    shared.add_argument("--skills-root", type=Path)
    commands.add_parser("inventory", help="Lista as origens do catálogo.")
    runtime = commands.add_parser("prepare-runtime", help="Copia os launchers Windows para um diretório local.")
    runtime.add_argument("target", type=Path)
    doctor = commands.add_parser("doctor", parents=[shared], help="Verifica os arquivos de um perfil.")
    doctor.add_argument("--strict", action="store_true")
    route = commands.add_parser("route", parents=[shared], help="Mostra o fluxo de uma tarefa.")
    route.add_argument("topic")
    installation = commands.add_parser("prepare", parents=[shared], help="Prepara o perfil no projeto indicado.")
    installation.add_argument("target", type=Path)
    installation.add_argument("--database", type=Path)
    installation.add_argument("--activity", action="store_true", help="Gera os hooks de atividade para revisão no Codex.")
    installation.add_argument("--repowise", action="store_true", help="Adiciona o MCP do RepoWise em um Git já indexado.")
    installation.add_argument("--allow-partial", action="store_true", help="Prepara as partes disponíveis do perfil completo.")
    options = parser.parse_args(argv)
    try:
        items, routes = catalog()
        if options.command == "inventory":
            print(json.dumps({"components": list(items.values()), "routes": list(routes)}, indent=2, ensure_ascii=False))
            return 0
        if options.command == "prepare-runtime":
            print(json.dumps(prepare_runtime(options.target), indent=2, ensure_ascii=False))
            return 0
        for option in ("runtime_root", "skills_root"):
            value = getattr(options, option)
            if value is not None:
                setattr(options, option, value.resolve(strict=True))
        status = inspect(items, options.profile, options.runtime_root, options.skills_root)
        if options.command == "prepare":
            print(json.dumps(prepare(items, routes, status, options), indent=2, ensure_ascii=False))
        elif options.command == "route":
            print(route_markdown({options.topic: routes[options.topic]}, status).decode("utf-8"))
        else:
            missing = needed(items, options.profile, status)
            print(json.dumps({"profile": options.profile, "status": status, "missing": missing}, indent=2, ensure_ascii=False))
            if options.strict and missing:
                return 1
    except (KeyError, OSError, ValueError) as exc:
        print(f"Harness_Local: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
