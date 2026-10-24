"""Pacote para embarcar no jogo: só dados de runtime, sem nenhuma identidade real.

O pacote do contrato (`make package`) serve ao desenvolvimento e à calibração e leva dados reais (nomes, steamids, times).
Este (`make package-game`) é o que pode ir dentro de um build do jogo:

  - lista de permissão: só artefatos de runtime e código de referência (a documentação tem exemplos reais e fica no pacote de desenvolvimento);
  - sanitização: ids de rounds derivados de nomes de demos e nomes de torneios são trocados por hashes e por "evento";
  - detector: antes de gravar o zip, todo arquivo é varrido atrás de steamid, nome de demo, torneio, time e apelido de
    jogador reais; qualquer achado reprova o build e nenhum zip é criado.

Uso: .venv/bin/python -m pipeline.package_game
"""
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from pipeline.common import ARTIFACTS_DIR, CONTRACT_DIR, CONTRACT_VERSION

ARTIFACTS = ("game_rules.json", "weapon_dynamics.json", "team_model.json", "tactics.json", "tactics_playbook.json",
             "elite_players.json", "manager_params.json")
REFERENCE = ("__init__.py", "team_model.py", "tactics.py", "weapon_dynamics.py", "profile_synthesis.py", "manager_economy.py")
DIST_DIR = CONTRACT_DIR.parent / "dist"
ZIP_TIME = (2026, 1, 1, 0, 0, 0)  # data fixa: o mesmo conteúdo gera o mesmo zip

STEAMID_RE = re.compile(r"(?<!\d)7656\d{13}(?!\d)")
DEMO_RE = re.compile(r"\.dem\b")
EVENT_RE = re.compile(r"(?<![a-z0-9])(thunderpick|esl|starladder|blast|pgl|iem)(?![a-z0-9])", re.I)


class LeakError(Exception):
    """O pacote ainda carrega alguma identidade real; `leaks` mapeia arquivo -> achados."""

    def __init__(self, leaks: Dict[str, List[Tuple[str, str]]]):
        self.leaks = leaks
        super().__init__("; ".join("%s: %s" % (f, ", ".join("%s=%r" % kv for kv in v[:4])) for f, v in leaks.items()))


class Identities:
    def __init__(self, names: Set[str], teams: Set[str]):
        self.names, self.teams = set(names), set(teams)
        team_alt = "|".join(re.escape(t) for t in sorted(self.teams, key=len, reverse=True))
        self.team_re = re.compile(r"(?<![a-z0-9])(%s)(?![a-z0-9])" % team_alt, re.I) if team_alt else None
        name_alt = "|".join(re.escape(n) for n in sorted(self.names, key=len, reverse=True) if n)
        # apelido só conta como valor; como chave de JSON (`"max":`) é coincidência com uma palavra do jogo
        self.name_re = re.compile(r'"(%s)"(?!\s*:)' % name_alt) if name_alt else None


def load_identities(path: Optional[Path] = None) -> Identities:
    with open(path or ARTIFACTS_DIR / "player_profiles.json", encoding="utf-8") as f:
        players = json.load(f)["players"]
    return Identities({p["name"] for p in players}, {p["team"] for p in players})


def find_leaks(text: str, ident: Identities) -> List[Tuple[str, str]]:
    found = []
    for kind, rx in (("steamid", STEAMID_RE), ("demo_file", DEMO_RE), ("event", EVENT_RE),
                     ("team", ident.team_re), ("nickname", ident.name_re)):
        if rx is not None:
            found += [(kind, m.group(m.lastindex or 0)) for m in rx.finditer(text)]
    return sorted(set(found))


def _sanitize_str(s: str, ident: Identities) -> str:
    t = EVENT_RE.sub("evento", s)
    if DEMO_RE.search(t) or (ident.team_re and ident.team_re.search(t)):
        base, sep, n = t.partition("#")  # ids de rounds: "<demo>#<n>" -> "m<hash>#<n>", mantendo o número do round
        t = "m" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:8] + sep + n
    return t


def sanitize(obj, ident: Identities):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            key = _sanitize_str(k, ident)
            if key in out:
                raise ValueError("a sanitização juntou duas chaves em %r" % key)
            out[key] = sanitize(v, ident)
        return out
    if isinstance(obj, list):
        return [sanitize(v, ident) for v in obj]
    if isinstance(obj, str):
        return _sanitize_str(obj, ident)
    return obj


PACKAGE_NOTE = """# Pacote para o jogo (cs-simulator {version})

Dados de runtime do contrato, **sem identidade real**: nenhum nome de jogador, steamid, time, demo ou torneio reais.

- `artifacts/`: regras, dinâmica das armas, modelo de time, tática, playbook, `elite_players.json` (jogadores com identidade ficcional) e `manager_params.json` (números da economia do manager).
- `reference/`: código de referência (Python) das funções que a Unity porta.
- `MANIFEST.json`: tamanho e sha256 de cada arquivo.

A documentação dos artefatos fica no pacote de desenvolvimento, porque seus exemplos citam jogadores e times reais.

Nos artefatos, ids de rounds viraram hashes e os nomes de torneios viraram "evento".

**Não coloque no build do jogo** o pacote de desenvolvimento (`make package`), `player_profiles.json`, `sharded/` nem `examples/`:
eles têm nomes, steamids e times reais e servem só à calibração.
"""


def _members(ident: Identities) -> Dict[str, bytes]:
    files: Dict[str, bytes] = {}
    for name in ARTIFACTS:
        doc = json.loads((ARTIFACTS_DIR / name).read_text(encoding="utf-8"))
        files["artifacts/" + name] = json.dumps(sanitize(doc, ident), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    for name in REFERENCE:
        files["reference/" + name] = (CONTRACT_DIR / "reference" / name).read_bytes()
    files["VERSION"] = (CONTRACT_DIR / "VERSION").read_bytes()
    files["PACKAGE.md"] = PACKAGE_NOTE.format(version=CONTRACT_VERSION).encode("utf-8")
    manifest = {"contract_version": CONTRACT_VERSION,
                "files": {n: {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in sorted(files.items())}}
    files["MANIFEST.json"] = json.dumps(manifest, indent=1).encode("utf-8")
    return files


def build(out_dir: Path, ident: Optional[Identities] = None) -> Path:
    ident = ident or load_identities()
    files = _members(ident)
    leaks = {n: found for n, b in files.items() if (found := find_leaks(b.decode("utf-8"), ident))}
    if leaks:
        raise LeakError(leaks)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("cs-simulator-game-%s.zip" % CONTRACT_VERSION)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, files[name])
    return path


def main() -> int:
    try:
        path = build(DIST_DIR)
    except LeakError as e:
        print("ERRO: o pacote ainda carrega identidade real; nenhum zip foi criado.")
        for name, found in e.leaks.items():
            print("  %s: %s" % (name, ", ".join("%s=%r" % kv for kv in found[:6])))
        return 1
    with zipfile.ZipFile(path) as z:
        print("%s: %d arquivos, %.0f KB, sem identidade real" % (path.name, len(z.namelist()), path.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
