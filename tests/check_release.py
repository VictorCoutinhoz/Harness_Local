"""Check the Git index for profile state and common credential formats."""

from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {".codex", ".agents", ".harness-local", ".repowise", ".venv", "node_modules", "__pycache__"}
PRIVATE_EXTENSIONS = {".sqlite", ".sqlite3", ".db", ".exe", ".dll", ".key", ".pem", ".pfx"}
SIGNATURES = {
    "caminho Windows de usuário": re.compile(rb"[A-Z]:[/\\]Users[/\\][^\r\n/\\]+", re.I),
    "token OpenAI": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    "token GitHub": re.compile(rb"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{26,}\b"),
    "chave privada": re.compile(rb"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----"),
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    entries = [entry for entry in git("ls-files", "--stage", "-z").split(b"\0") if entry]
    if not entries:
        print("O índice do Git está vazio.", file=sys.stderr)
        return 1
    failures = []
    for entry in entries:
        fields, encoded_name = entry.split(b"\t", 1)
        mode, revision, stage = fields.split()
        name = encoded_name.decode("utf-8")
        path = PurePosixPath(name)
        if (stage != b"0" or mode not in {b"100644", b"100755"} or
                PRIVATE_PARTS.intersection(path.parts) or path.suffix.lower() in PRIVATE_EXTENSIONS or
                any(part == ".env" or part.startswith(".env.") for part in path.parts)):
            failures.append((name, "metadado, binário ou caminho de estado"))
            continue
        content = git("cat-file", "blob", revision.decode("ascii"))
        failures.extend((name, issue) for issue, pattern in SIGNATURES.items() if pattern.search(content))
    if failures:
        for name, issue in failures:
            print(f"{name} | {issue}", file=sys.stderr)
        return 1
    print(f"{len(entries)} arquivos do índice verificados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
