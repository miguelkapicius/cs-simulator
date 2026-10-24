"""Fatia os artefatos em arquivos independentes por jogador, time e mapa (contract/sharded/) e gera o manifesto.

Um confronto (mapa + dois times) carrega só o que precisa: os dados globais, os dois times, os 10 jogadores e o mapa.
Os arquivos únicos de contract/artifacts/ continuam existindo e são a fonte; as fatias são geradas a partir deles.

  contract/sharded/manifest.json        índice: caminho, tamanho e sha256 de cada arquivo
  contract/sharded/global/              baseline dos perfis e dados táticos que valem para qualquer mapa
  contract/sharded/teams/<time>.json    elenco e estatísticas descritivas do time
  contract/sharded/players/<steamid>.json
  contract/sharded/maps/<mapa>/tactics.json e playbook.json

Os dados globais já existentes (game_rules, weapon_dynamics, team_model) são referenciados no lugar, sem cópia.

Uso: .venv/bin/python -m pipeline.build_shards
"""
import hashlib
import json
import re
import shutil
from datetime import date

from contract.reference import manifest as ref
from pipeline.common import ARTIFACTS_DIR, BUY_TYPES, CONTRACT_DIR, CONTRACT_VERSION, VECTORS_DIR
from pipeline.tactics_data import load_rounds

SHARDS_DIR = CONTRACT_DIR / "sharded"
HEADER_KEYS = ("schema_version", "contract_version", "generated_at")
SAMPLE_CASES = 10                      # confrontos com a lista completa de arquivos nos vetores de teste


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def header():
    return {"schema_version": "1.0", "contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat()}


def write(rel, obj, indent=None):
    """Grava um arquivo dentro de contract/ e devolve a entrada do manifesto (caminho, bytes, sha256)."""
    path = CONTRACT_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=indent, separators=(",", ":") if indent is None else None).encode("utf-8")
    path.write_bytes(data)
    return {"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def existing(rel):
    data = (CONTRACT_DIR / rel).read_bytes()
    return {"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def team_stats(R, team, players):
    """Estatísticas descritivas do time por mapa. Com 28 partidas a diferença entre times é pequena (ver tactics.site_decision.team_effects)."""
    own = R[(R.ct_team == team) | (R.t_team == team)]
    maps = {}
    for mp, g in own.groupby("map"):
        ct, t = g[g.ct_team == team], g[g.t_team == team]
        tp = t[t.planted & t.plant_site.isin(["A", "B"])]
        maps[mp] = {
            "rounds": int(len(g)),
            "ct": {"rounds": int(len(ct)), "win_rate": round(float((ct.winner_side == "CT").mean()), 3) if len(ct) else None,
                   "buy": {b: round(float((ct.ct_buy == b).mean()), 3) for b in BUY_TYPES} if len(ct) else None},
            "t": {"rounds": int(len(t)), "win_rate": round(float((t.winner_side == "T").mean()), 3) if len(t) else None,
                  "plant_rate": round(float(t.planted.mean()), 3) if len(t) else None,
                  "plant_a_share": round(float((tp.plant_site == "A").mean()), 3) if len(tp) else None, "plants": int(len(tp)),
                  "buy": {b: round(float((t.t_buy == b).mean()), 3) for b in BUY_TYPES} if len(t) else None},
        }
    return {"team": team, "rounds": int(len(own)), "matches": int(own.match.nunique()),
            "roster": [{"steamid": p["steamid"], "name": p["name"], "role_tags": p["role_tags"], "rounds": p["performance"]["rounds"]} for p in players],
            "maps": maps,
            "note": "Descritivo. As equipes quase não diferem de forma estatisticamente clara dentro do mesmo mapa (ver tactics.site_decision.team_effects); "
                    "use com cuidado quando 'rounds' for pequeno."}


def main():
    profiles = json.loads((ARTIFACTS_DIR / "player_profiles.json").read_text())
    tactics = json.loads((ARTIFACTS_DIR / "tactics.json").read_text())
    playbook = json.loads((ARTIFACTS_DIR / "tactics_playbook.json").read_text())
    R, _ = load_rounds()

    if SHARDS_DIR.exists():
        shutil.rmtree(SHARDS_DIR)

    manifest = {**header(), "layout": ref.LAYOUT_DOC, "global": {}, "teams": {}, "players": {}, "maps": {}}
    for name in ("game_rules", "weapon_dynamics", "team_model"):
        manifest["global"][name] = existing(f"artifacts/{name}.json")
    manifest["global"]["profiles_baseline"] = write("sharded/global/profiles_baseline.json", {
        **header(), **{k: profiles[k] for k in ("source", "units", "method", "baseline")}}, indent=1)
    manifest["global"]["tactics_global"] = write("sharded/global/tactics_global.json", {
        **header(), **{k: tactics[k] for k in ("source", "conventions", "findings", "site_decision")}}, indent=1)

    by_team = {}
    for i, p in enumerate(profiles["players"]):
        entry = write(f"sharded/players/{p['steamid']}.json", {**header(), **p}, indent=1)
        manifest["players"][p["steamid"]] = {**entry, "name": p["name"], "team": p["team"], "index": i, "rounds": p["performance"]["rounds"]}
        by_team.setdefault(p["team"], []).append(p)

    for team, players in sorted(by_team.items()):
        stats = team_stats(R, team, players)
        entry = write(f"sharded/teams/{slug(team)}.json", {**header(), **stats}, indent=1)
        manifest["teams"][team] = {**entry, "players": [p["steamid"] for p in players], "rounds": stats["rounds"]}

    for mp, m in sorted(tactics["maps"].items()):
        pb = playbook["maps"][mp]
        manifest["maps"][mp] = {
            "rounds": m["n_rounds"],
            "tactics": write(f"sharded/maps/{mp}/tactics.json", {**header(), "map": mp, **m}, indent=1),
            "playbook": write(f"sharded/maps/{mp}/playbook.json", {**header(), "map": mp, **pb}),
        }

    (SHARDS_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    teams, maps = sorted(manifest["teams"]), sorted(manifest["maps"])
    cases = []
    for i, a in enumerate(teams):
        for b in teams[i + 1:]:
            for mp in maps:
                got = ref.match_files(manifest, mp, a, b)
                cases.append({"input": {"map": mp, "team_a": a, "team_b": b}, "expected": {"n_files": len(got["files"]), "bytes": got["bytes"]}})
    step = max(len(cases) // SAMPLE_CASES, 1)
    for c in cases[::step][:SAMPLE_CASES]:
        c["expected"]["files"] = ref.match_files(manifest, c["input"]["map"], c["input"]["team_a"], c["input"]["team_b"])["files"]
    vec = {"contract_version": CONTRACT_VERSION, "generated_at": date.today().isoformat(),
           "description": "Arquivos que um confronto (mapa + dois times) precisa carregar, a partir do manifesto. A versão em C# deve devolver a mesma lista (ordenada) e o mesmo total de bytes. "
                          "Alguns casos trazem a lista completa; os demais, só a contagem e os bytes.",
           "cases": cases}
    (VECTORS_DIR / "manifest_vectors.json").write_text(json.dumps(vec, ensure_ascii=False, indent=1))

    total = sum(f["bytes"] for f in ref.all_files(manifest))
    worst = max(c["expected"]["bytes"] for c in cases)
    print(f"{len(manifest['players'])} jogadores, {len(manifest['teams'])} times, {len(manifest['maps'])} mapas; {len(ref.all_files(manifest))} arquivos, {total // 1024} KB no total")
    print(f"um confronto carrega entre {min(c['expected']['bytes'] for c in cases) // 1024} e {worst // 1024} KB ({100 * worst // total}% do total no pior caso); {len(cases)} confrontos nos vetores")


if __name__ == "__main__":
    main()
