"""Importa as demos novas de uma pasta de downloads (.rar do HLTV) para o projeto.

Para cada arquivo de partida (nome com `-bo3-`/`-bo5-`) que ainda não foi importado:
  1. confere que o arquivo está completo e legível (lista o conteúdo com bsdtar);
  2. move o .rar para archives/;
  3. extrai as .dem para demos/ com o nome `<evento>-<série>-<id>__<mapa>.dem` (o prefixo evita colisão entre séries repetidas);
  4. confere o cabeçalho PBDEMS2 e descarta demos idênticas a outras já existentes.

Ignora: arquivos já importados, cópias repetidas (terminadas em "(1)"), arquivos muito pequenos (download incompleto) e arquivos ilegíveis.
Nunca apaga nada de downloads: o que não foi importado fica lá.

Uso: .venv/bin/python -m pipeline.ingest_archives [--source ~/Downloads] [--dry-run]
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline.common import DEMOS_DIR, ROOT

ARCHIVES_DIR = ROOT / "archives"
MATCH_NAME = re.compile(r"-bo\d-")
MIN_ARCHIVE_BYTES = 50 * 1024 * 1024        # abaixo disto o download está incompleto
HASH_CHARS = 22                              # sufixo do id do HLTV no nome do arquivo
SIGNATURE = b"PBDEMS2"


def normalize(name):
    """Nome sem o ' (1)' que o navegador acrescenta a downloads repetidos."""
    return re.sub(r"\s*\(\d+\)(?=\.[a-z0-9]+$)", "", name, flags=re.I)


def demo_prefix(archive_name):
    stem = Path(normalize(archive_name)).stem
    tail = stem[-HASH_CHARS:]
    return f"{stem[:-HASH_CHARS - 1]}-{tail[:6]}"


def fingerprint(path):
    """Impressão digital rápida de uma demo: tamanho + sha256 dos primeiros e últimos 2 MB."""
    size = path.stat().st_size
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(2 << 20))
        f.seek(max(size - (2 << 20), 0))
        h.update(f.read(2 << 20))
    return size, h.hexdigest()


def list_archive(path):
    r = subprocess.run(["bsdtar", "-tf", str(path)], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.endswith(".dem")] if r.returncode == 0 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(Path.home() / "Downloads"))
    ap.add_argument("--dry-run", action="store_true", help="só mostra o que seria importado")
    args = ap.parse_args(argv)

    source = Path(args.source).expanduser()
    ARCHIVES_DIR.mkdir(exist_ok=True)
    DEMOS_DIR.mkdir(exist_ok=True)
    known = {normalize(p.name) for p in ARCHIVES_DIR.iterdir()}
    existing = {fingerprint(p) for p in DEMOS_DIR.glob("*.dem")}

    candidates, seen, report = [], set(), {"já importado": [], "cópia repetida": [], "incompleto": [], "ilegível": [], "sem .dem": []}
    for p in sorted(source.iterdir()):
        if not (p.is_file() and p.suffix.lower() in (".rar", ".zip", ".7z") and MATCH_NAME.search(p.name)):
            continue
        norm = normalize(p.name)
        if norm in known:
            report["já importado"].append(p.name)
        elif p.stat().st_size < MIN_ARCHIVE_BYTES:
            report["incompleto"].append(f"{p.name} ({p.stat().st_size / 1e6:.1f} MB)")
        elif (norm, p.stat().st_size) in seen:
            report["cópia repetida"].append(p.name)
        else:
            names = list_archive(p)
            if names is None:
                report["ilegível"].append(p.name)
            elif not names:
                report["sem .dem"].append(p.name)
            else:
                seen.add((norm, p.stat().st_size))
                candidates.append((p, names))

    imported, dropped = [], []
    for p, names in candidates:
        prefix = demo_prefix(p.name)
        if args.dry_run:
            print(f"importaria {p.name}: {len(names)} demo(s)")
            continue
        with tempfile.TemporaryDirectory(dir=DEMOS_DIR) as tmp:
            r = subprocess.run(["bsdtar", "-xf", str(p), "-C", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                report["ilegível"].append(f"{p.name} (falha ao extrair: {r.stderr.strip()[:80]})")
                continue
            for dem in sorted(Path(tmp).rglob("*.dem")):
                with open(dem, "rb") as f:
                    if f.read(len(SIGNATURE)) != SIGNATURE:
                        dropped.append(f"{p.name}/{dem.name}: cabeçalho inválido")
                        continue
                fp = fingerprint(dem)
                if fp in existing:
                    dropped.append(f"{p.name}/{dem.name}: idêntica a uma demo já existente")
                    continue
                existing.add(fp)
                target = DEMOS_DIR / f"{prefix}__{dem.name}"
                shutil.move(str(dem), target)
                imported.append(target.name)
        shutil.move(str(p), ARCHIVES_DIR / normalize(p.name))
        print(f"  {p.name}: {len(names)} demo(s)", flush=True)

    print(f"\nimportadas {len(imported)} demos de {len(candidates)} arquivos.")
    for why, items in report.items():
        if items:
            print(f"ignorados ({why}): {len(items)}")
            for i in items:
                print("   -", i)
    for d in dropped:
        print("descartada:", d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
