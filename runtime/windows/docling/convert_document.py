"""Run the installed Docling CLI with the harness's local document models."""

import argparse
import os
from tempfile import TemporaryDirectory
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Converte um documento local com o Docling.")
    parser.add_argument("document", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("md", "json", "html", "text"), default="md")
    parser.add_argument("--no-ocr", action="store_true")
    args = parser.parse_args()

    source = args.document.resolve()
    if not source.is_file():
        parser.error(f"Arquivo local não encontrado: {source}")
    destination = args.output.resolve()
    extension = "txt" if args.format == "text" else args.format
    output = destination / f"{source.stem}.{extension}"
    if output.exists():
        parser.error("O arquivo de saída já existe. Escolha outro diretório de saída.")

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from docling.cli.main import app

    models = Path(__file__).resolve().parent / "models"
    options = [
        "convert", "--to", args.format, "--artifacts-path", str(models),
        "--device", "cpu", "--fail-on", "partial", "--html-image-fetch", "none",
        "--image-export-mode", "placeholder",
    ]
    if args.no_ocr:
        options.append("--no-ocr")
    else:
        options.extend(("--ocr-engine", "rapidocr", "--ocr-lang", "iso:pt"))

    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".docling-", dir=destination) as staging:
        status = app(
            args=[*options, "--output", staging, str(source)],
            prog_name="docling",
            standalone_mode=False,
        )
        if status:
            return status
        staged = Path(staging) / output.name
        if not staged.is_file():
            parser.exit(1, "O Docling terminou sem produzir o arquivo esperado.\n")
        try:
            staged.rename(output)
        except FileExistsError:
            parser.error("Já existe um arquivo com esse nome no diretório de saída.")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
