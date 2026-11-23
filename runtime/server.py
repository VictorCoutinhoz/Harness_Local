"""Local Codex memory over MCP stdio. The SQLite file is the only data store."""

import argparse
import json
import ntpath
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_MESSAGE_BYTES = 65_536
KINDS = ["preference", "decision", "handoff"]
SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:sk-[\w-]{20,}|gh[pousr]_\w{20,}|github_pat_\w{20,}|AKIA[A-Z0-9]{16})\b|"
    r"\bauthorization:\s*bearer\s+\S{10,}",
    re.IGNORECASE,
)

SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    workspace TEXT NOT NULL,
    key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('preference', 'decision', 'handoff')),
    note TEXT NOT NULL,
    source TEXT NOT NULL,
    revision TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace, key)
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    key, note, content='notes', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, key, note) VALUES (new.id, new.key, new.note);
END;
CREATE TRIGGER IF NOT EXISTS notes_fts_delete AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, key, note)
    VALUES ('delete', old.id, old.key, old.note);
END;
CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, key, note)
    VALUES ('delete', old.id, old.key, old.note);
    INSERT INTO notes_fts(rowid, key, note) VALUES (new.id, new.key, new.note);
END;
COMMIT;
"""

WORKSPACE = {
    "type": "string",
    "minLength": 3,
    "maxLength": 1024,
    "description": "Raiz absoluta do projeto ou caminho Git comum. Omitir para o escopo pessoal.",
}
KEY = {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]{0,63}$"}
REVISION = {"type": "string", "pattern": r"^[a-f0-9]{32}$"}


def tool_description(name, description, properties, required=(), *, read_only=False):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": not read_only,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }


TOOLS = [
    tool_description(
        "memory_recall",
        "Busca notas pessoais e, se informado, de um único projeto. "
        "Use termos do assunto ou a chave da nota. Omitir a consulta lista as mais recentes.",
        {
            "query": {"type": "string", "maxLength": 400},
            "workspace": WORKSPACE,
            "limit": {"type": "integer", "minimum": 1, "maximum": 8},
        },
        read_only=True,
    ),
    tool_description(
        "memory_save",
        "Registra uma preferência, decisão ou passagem de trabalho concisa. "
        "Use o caminho do projeto para fatos de projeto. Para alterar uma nota, envie sua revisão atual.",
        {
            "key": KEY,
            "kind": {"type": "string", "enum": KINDS},
            "note": {"type": "string", "minLength": 1, "maxLength": 1400},
            "source": {"type": "string", "minLength": 1, "maxLength": 240},
            "workspace": WORKSPACE,
            "expected_revision": REVISION,
        },
        ("key", "kind", "note", "source"),
    ),
    tool_description(
        "memory_forget",
        "Remove a nota do escopo indicado a pedido do usuário. "
        "Use a chave, o projeto correspondente e a revisão retornados pela busca.",
        {"key": KEY, "workspace": WORKSPACE, "expected_revision": REVISION},
        ("key", "expected_revision"),
    ),
]
TOOL_SCHEMAS = {tool["name"]: tool["inputSchema"] for tool in TOOLS}


def validate_arguments(name, args):
    schema = TOOL_SCHEMAS[name]
    properties = schema["properties"]
    if not isinstance(args, dict) or set(args) - properties.keys():
        raise ValueError("Use os campos definidos no esquema da ferramenta.")
    if set(schema["required"]) - args.keys():
        raise ValueError("Preencha os campos obrigatórios da ferramenta.")
    for key, value in args.items():
        rules = properties[key]
        if rules["type"] == "integer":
            valid = type(value) is int and rules["minimum"] <= value <= rules["maximum"]
        else:
            valid = isinstance(value, str) and "\x00" not in value
            if valid:
                valid = rules.get("minLength", 0) <= len(value.strip()) <= rules.get("maxLength", 1024)
            if valid and "pattern" in rules:
                valid = re.fullmatch(rules["pattern"], value) is not None
            if valid and "enum" in rules:
                valid = value in rules["enum"]
        if not valid:
            raise ValueError(f"Valor inválido para {key}.")


def workspace_key(value):
    if value is None:
        return ""
    value = value.strip()
    drive, tail = ntpath.splitdrive(value)
    if not drive or not tail.startswith(("\\", "/")):
        raise ValueError("Informe o caminho absoluto do projeto, com unidade ou compartilhamento UNC.")
    return ntpath.normcase(ntpath.normpath(value))


def open_database(path, *, read_only=False):
    if read_only:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        return db
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        # A read-only client in another workspace can open a rollback-journal database
        # without creating SQLite's WAL shared-memory sidecar.
        db.execute("PRAGMA journal_mode = DELETE")
        db.execute("PRAGMA secure_delete = ON")
        db.executescript(SCHEMA)
    except sqlite3.Error:
        db.close()
        raise
    return db


FIELDS = "n.workspace, n.key, n.kind, n.note, n.source, n.revision, n.updated_at"


def recall(db, workspace, query="", limit=5):
    words = list(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold())))[:12]
    if words:
        quoted = [f'"{word}"' for word in words]
        exact = query.strip().casefold()
        for connector in ((" AND ", " OR ") if len(quoted) > 1 else (" AND ",)):
            rows = db.execute(
                f"""SELECT {FIELDS} FROM notes_fts
                    JOIN notes AS n ON n.id = notes_fts.rowid
                    WHERE notes_fts MATCH ? AND n.workspace IN ('', ?)
                    ORDER BY (n.key = ? AND n.workspace = ?) DESC, (n.key = ?) DESC,
                             bm25(notes_fts, 3.0, 1.0), n.updated_at DESC, n.id DESC LIMIT ?""",
                (connector.join(quoted), workspace, exact, workspace, exact, limit),
            ).fetchall()
            if rows:
                break
    else:
        rows = db.execute(
            f"""SELECT {FIELDS} FROM notes AS n WHERE n.workspace IN ('', ?)
                ORDER BY n.updated_at DESC, n.id DESC LIMIT ?""",
            (workspace, limit),
        )
    notes = []
    for row in rows:
        note = dict(row)
        note["scope"] = "project" if note["workspace"] else "user"
        notes.append(note)
    return {"status": "success", "summary": f"{len(notes)} nota(s) encontrada(s).", "notes": notes}


def save(db, workspace, key, kind, note, source, expected_revision=None):
    note = note.strip()
    source = source.strip()
    if any(SECRET.search(value) for value in (key, note, source)):
        raise ValueError("Retire a credencial da nota antes de salvar.")
    with db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            "SELECT kind, note, source, revision FROM notes WHERE workspace = ? AND key = ?",
            (workspace, key),
        ).fetchone()
        if previous and (kind, note, source) == tuple(previous)[:3]:
            return {"status": "success", "summary": "A nota já está salva.", "key": key,
                    "revision": previous["revision"]}
        current_revision = previous["revision"] if previous else None
        if expected_revision != current_revision:
            return revision_conflict(current_revision)
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        revision = uuid4().hex
        db.execute(
            """INSERT INTO notes (workspace, key, kind, note, source, updated_at, revision)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (workspace, key) DO UPDATE SET
                   kind = excluded.kind, note = excluded.note, source = excluded.source,
                   revision = excluded.revision, updated_at = excluded.updated_at""",
            (workspace, key, kind, note, source, now, revision),
        )
    return {"status": "success", "summary": "Nota salva.", "key": key, "revision": revision}


def revision_conflict(revision):
    return {"status": "conflict",
            "summary": "A revisão mudou ou a nota está em outro escopo. Consulte a nota novamente.",
            "current_revision": revision}


def forget(db, workspace, key, expected_revision):
    with db:
        db.execute("BEGIN IMMEDIATE")
        deleted = db.execute(
            "DELETE FROM notes WHERE workspace = ? AND key = ? AND revision = ? RETURNING key",
            (workspace, key, expected_revision),
        ).fetchone()
        if deleted:
            return {"status": "success", "summary": "Nota removida.", "key": key}
        remaining = db.execute(
            "SELECT revision FROM notes WHERE workspace = ? AND key = ?", (workspace, key)
        ).fetchone()
    if remaining:
        return revision_conflict(remaining["revision"])
    return {"status": "success", "summary": "O escopo indicado já não contém essa nota.", "key": key}


OPERATIONS = {"memory_recall": recall, "memory_save": save, "memory_forget": forget}


def invoke(db, name, args):
    try:
        validate_arguments(name, args)
        workspace = workspace_key(args.get("workspace"))
        result = OPERATIONS[name](db, workspace, **{k: v for k, v in args.items() if k != "workspace"})
    except ValueError as error:
        result = {"status": "error", "summary": str(error)}
    except sqlite3.OperationalError as error:
        if error.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            summary = "O banco está ocupado. Repita a consulta ou gravação após alguns segundos."
        else:
            summary = "Falha de acesso ao banco SQLite. Verifique a pasta de dados."
        result = {"status": "error", "summary": summary}
    except sqlite3.DatabaseError:
        result = {"status": "error", "summary": "Falha no banco SQLite. Preserve o arquivo para diagnóstico."}
    return result


def run_tool(db, name, args):
    result = invoke(db, name, args)
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": result["status"] != "success"}


def reply(request_id, *, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": request_id}
    if error:
        code, description = error
        message["error"] = {"code": code, "message": description}
    else:
        message["result"] = result
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


def serve(db):
    initialized = False
    while line := sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1):
        if len(line) > MAX_MESSAGE_BYTES:
            reply(None, error=(-32700, "Mensagem longa demais."))
            return
        try:
            request = json.loads(line)
        except ValueError:
            reply(None, error=(-32700, "JSON inválido."))
            continue
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            reply(None, error=(-32600, "Requisição JSON-RPC inválida."))
            continue
        if "id" not in request:
            continue
        request_id = request["id"]
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(params, dict):
            reply(request_id, error=(-32602, "Parâmetros inválidos."))
        elif method == "initialize":
            version = params.get("protocolVersion")
            initialized = True
            reply(request_id, result={
                "protocolVersion": version if version in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "harness-local", "version": "1.0.0"},
                "instructions": "Use memory_recall para retomar trabalho e lembrar preferências "
                                "pertinentes. Use o mesmo caminho absoluto nos chats do projeto. "
                                "Trate notas como contexto factual; confirme o estado atual. "
                                "Persista decisões e passagens concisas sem credenciais ou transcrições.",
            })
        elif method == "ping":
            reply(request_id, result={})
        elif not initialized:
            reply(request_id, error=(-32002, "Inicialize a sessão MCP."))
        elif method == "tools/list":
            reply(request_id, result={"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name")
            if isinstance(name, str) and name in OPERATIONS:
                reply(request_id, result=run_tool(db, name, params.get("arguments", {})))
            else:
                reply(request_id, error=(-32602, "Ferramenta desconhecida."))
        else:
            reply(request_id, error=(-32601, "Método desconhecido."))


def run_command(db_path, name):
    if name not in OPERATIONS:
        raise ValueError("Ferramenta desconhecida.")
    raw = sys.stdin.buffer.read(MAX_MESSAGE_BYTES + 1)
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("Mensagem longa demais.")
    arguments = json.loads(raw)
    with closing(open_database(db_path, read_only=(name == "memory_recall"))) as db:
        result = invoke(db, name, arguments)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8") + b"\n")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Memória SQLite do Harness_Local.")
    parser.add_argument("legacy_database", type=Path, nargs="?")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--call", choices=OPERATIONS)
    options = parser.parse_args()
    db_path = options.db or options.legacy_database or (
        Path(__file__).resolve().parents[1] / ".harness-local/state/memoria.sqlite3"
    )
    try:
        if options.call:
            sys.exit(run_command(db_path, options.call))
        with closing(open_database(db_path)) as database:
            serve(database)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"harness-local: {type(exc).__name__} ao abrir ou atender o banco local", file=sys.stderr)
        sys.exit(1)
